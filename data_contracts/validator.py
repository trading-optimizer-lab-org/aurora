"""DataFrame validator gating dataset entry into the engine.

Runs a battery of cheap structural and statistical checks against an
input DataFrame using a :class:`~aurora.data_contracts.contract.DataContract`
and emits a :class:`~aurora.data_contracts.contract.DataValidationResult`.
The intent is that backtest, GA, validation pipeline and factory submit
all call :func:`validate_dataframe` before doing anything else with the
data.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, List, Optional

import numpy as np
import pandas as pd

from aurora.data_contracts.contract import (
    DataContract,
    DataValidationResult,
)


VALIDATOR_VERSION = "1.0.0"


def validate_dataframe(
    df: pd.DataFrame,
    contract: DataContract,
    *,
    decision_time: Optional[Any] = None,
    snapshot_hash: Optional[str] = None,
) -> DataValidationResult:
    """Validate ``df`` against ``contract``.

    Args:
        df: dataset to validate. Must be a pandas DataFrame.
        contract: declared shape and policies.
        decision_time: when supplied, the validator enforces that no
            row's ``available_time`` is greater than this timestamp.
            Accepts ``datetime`` / ``pd.Timestamp`` / ISO string.
        snapshot_hash: caller-provided sha256 of the input snapshot.
            Echoed back into the result so downstream provenance can
            reuse it without recomputing.

    Returns:
        :class:`DataValidationResult`.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(df, pd.DataFrame):
        return DataValidationResult(
            passed=False,
            errors=("input is not a pandas DataFrame",),
            warnings=tuple(),
            snapshot_hash=snapshot_hash,
            contract_hash=contract.contract_hash,
            validator_version=VALIDATOR_VERSION,
        )

    # 1. required columns -- if any are missing, downstream checks would
    # raise KeyError so we short-circuit and return early.
    df_cols = set(df.columns)
    missing = [c for c in contract.required_columns if c not in df_cols]
    if missing:
        errors.append(f"missing required columns: {sorted(missing)}")
        return _build_result(errors, warnings, snapshot_hash, contract)

    # 2. timestamp axis (column or index)
    ts_series = _extract_timestamp_series(df, contract)
    if ts_series is None:
        errors.append(
            f"timestamp axis missing: expected column or index named "
            f"'{contract.timestamp_col}'"
        )
        return _build_result(errors, warnings, snapshot_hash, contract)
    _check_timestamp_axis(ts_series, contract, errors)

    # 3. duplicate rows on timestamp axis
    if ts_series.duplicated().any():
        n_dups = int(ts_series.duplicated().sum())
        errors.append(f"duplicate timestamps: {n_dups} duplicate rows")

    # 4. null policy per column
    for cf in contract.fields:
        if cf.name not in df_cols:
            continue
        col = df[cf.name]
        if not cf.nullable and col.isna().any():
            n_null = int(col.isna().sum())
            errors.append(f"column '{cf.name}' has {n_null} null(s) but is non-nullable")

    # 5. zero / negative on positive_only fields (incl. price columns)
    for cf in contract.fields:
        if not cf.positive_only or cf.name not in df_cols:
            continue
        col = pd.to_numeric(df[cf.name], errors="coerce")
        bad_mask = col.le(0) & col.notna()
        if bool(bad_mask.any()):
            n_bad = int(bad_mask.sum())
            errors.append(
                f"column '{cf.name}' has {n_bad} non-positive value(s) "
                f"but contract declares positive_only=True"
            )

    # 6. impossible / split-like jumps on price columns
    _check_price_jumps(df, contract, errors, warnings)

    # 7. point-in-time access (available_time vs decision_time)
    _check_pit(df, contract, decision_time, errors)

    # 8. staleness (latest timestamp vs decision_time)
    _check_staleness(ts_series, contract, decision_time, warnings, errors)

    return _build_result(errors, warnings, snapshot_hash, contract)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _build_result(
    errors: List[str],
    warnings: List[str],
    snapshot_hash: Optional[str],
    contract: DataContract,
) -> DataValidationResult:
    return DataValidationResult(
        passed=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        snapshot_hash=snapshot_hash,
        contract_hash=contract.contract_hash,
        validator_version=VALIDATOR_VERSION,
    )


def _extract_timestamp_series(
    df: pd.DataFrame, contract: DataContract
) -> Optional[pd.Series]:
    """Return the timestamp series from column or index, else ``None``."""
    if contract.timestamp_col in df.columns:
        return df[contract.timestamp_col]
    if df.index.name == contract.timestamp_col:
        return pd.Series(df.index, index=df.index)
    return None


def _check_timestamp_axis(
    ts_series: pd.Series, contract: DataContract, errors: List[str]
) -> None:
    """Validate timezone, monotonicity, type."""
    # Detect mixed-timezone input FIRST. ``pd.to_datetime`` will return NaT
    # for an object-dtype series of timestamps with different tz when
    # ``utc=False``, so we cannot rely on the converted view to spot it.
    tz_set = _collect_tz_set(ts_series)
    if len(tz_set) > 1:
        errors.append(
            f"timestamp column '{contract.timestamp_col}' has mixed timezones: "
            f"{sorted(str(t) for t in tz_set)}"
        )
        return

    converted = pd.to_datetime(ts_series, errors="coerce", utc=False)
    if converted.isna().any():
        errors.append(
            f"timestamp column '{contract.timestamp_col}' has unparseable values"
        )
        return

    only_tz = next(iter(tz_set)) if tz_set else None
    if contract.timezone is not None and not contract.allow_naive_timestamps:
        if only_tz is None:
            errors.append(
                f"timestamp column '{contract.timestamp_col}' is naive but "
                f"contract requires timezone='{contract.timezone}'"
            )
        else:
            if str(only_tz) != contract.timezone and getattr(only_tz, "zone", None) != contract.timezone:
                # Some tz objects stringify as "UTC" / "tzutc()" / etc.;
                # fall back to a tolerant compare.
                if not _tz_matches(only_tz, contract.timezone):
                    errors.append(
                        f"timestamp column '{contract.timestamp_col}' tz "
                        f"'{only_tz}' != contract tz '{contract.timezone}'"
                    )

    # monotonic increasing
    if not converted.is_monotonic_increasing:
        errors.append(
            f"timestamp column '{contract.timestamp_col}' is not "
            "monotonically increasing"
        )


def _collect_tz_set(ts_series: pd.Series) -> set:
    """Return distinct tz objects observed in ``ts_series`` (excludes naive)."""
    if hasattr(ts_series, "dt") and hasattr(ts_series.dtype, "tz"):
        tz = getattr(ts_series.dtype, "tz", None)
        if tz is not None:
            return {tz}
        return set()

    tzs = set()
    for v in ts_series:
        if isinstance(v, pd.Timestamp):
            if v.tz is not None:
                tzs.add(v.tz)
        elif isinstance(v, datetime):
            if v.tzinfo is not None:
                tzs.add(v.tzinfo)
    return tzs


def _tz_matches(tz_obj: Any, expected: str) -> bool:
    """Tolerant timezone equality: 'UTC' matches several tz representations."""
    s = str(tz_obj)
    if s == expected:
        return True
    if expected.upper() == "UTC" and s.upper() in {"UTC", "TZUTC()", "UTC+00:00"}:
        return True
    return False


def _check_price_jumps(
    df: pd.DataFrame,
    contract: DataContract,
    errors: List[str],
    warnings: List[str],
) -> None:
    """Detect split-like and impossible bar-to-bar moves on price columns."""
    cap = contract.corporate_actions
    if cap.severity == "ignore":
        return
    for col_name in contract.price_columns:
        if col_name not in df.columns:
            continue
        col = pd.to_numeric(df[col_name], errors="coerce")
        if col.isna().all() or len(col) < 2:
            continue
        positive = col.where(col > 0)
        log_col = np.log(positive.astype(float))
        log_ret = log_col.diff().abs()

        impossible_mask = log_ret > cap.impossible_return_threshold
        if bool(impossible_mask.any()):
            n = int(impossible_mask.sum())
            errors.append(
                f"column '{col_name}' has {n} impossible bar-to-bar move(s) "
                f"|log_return| > {cap.impossible_return_threshold}"
            )

        suspect_mask = (log_ret > cap.split_jump_threshold) & (~impossible_mask)
        if bool(suspect_mask.any()):
            n = int(suspect_mask.sum())
            msg = (
                f"column '{col_name}' has {n} suspicious split-like jump(s) "
                f"|log_return| > {cap.split_jump_threshold}"
            )
            if cap.severity == "fail":
                errors.append(msg)
            else:
                warnings.append(msg)


def _check_pit(
    df: pd.DataFrame,
    contract: DataContract,
    decision_time: Optional[Any],
    errors: List[str],
) -> None:
    """Enforce point-in-time policy.

    * If the contract requires PIT columns, fail when any are missing.
    * If ``decision_time`` is supplied AND the contract names an
      ``available_time`` column AND that column exists, fail when any
      ``available_time > decision_time``.
    """
    avail = contract.availability
    pit_cols = [
        avail.event_time_col,
        avail.available_time_col,
        avail.ingested_time_col,
        avail.revision_time_col,
    ]
    declared = [c for c in pit_cols if c is not None]
    if avail.require_pit_columns:
        missing = [c for c in declared if c not in df.columns]
        if missing:
            errors.append(f"point-in-time columns missing: {sorted(missing)}")

    if decision_time is None:
        return
    avail_col = avail.available_time_col
    if avail_col is None or avail_col not in df.columns:
        return
    decision_ts = pd.Timestamp(decision_time)
    avail_series = pd.to_datetime(df[avail_col], errors="coerce", utc=False)
    # Align tz: if avail_series is tz-aware and decision is naive, normalise.
    avail_series, decision_ts = _align_tz(avail_series, decision_ts)
    if avail_series.isna().any():
        errors.append(f"point-in-time column '{avail_col}' has unparseable values")
        return
    leak_mask = avail_series > decision_ts
    if bool(leak_mask.any()):
        n = int(leak_mask.sum())
        errors.append(
            f"point-in-time leak: {n} row(s) have available_time > "
            f"decision_time={decision_ts.isoformat()}"
        )


def _align_tz(series: pd.Series, ts: pd.Timestamp) -> tuple[pd.Series, pd.Timestamp]:
    """Best-effort alignment of timezone awareness between ``series`` and ``ts``.

    Avoids ``TypeError: Cannot compare tz-naive and tz-aware`` while keeping
    actual instant-in-time semantics where possible.
    """
    series_tz = getattr(series.dtype, "tz", None)
    ts_tz = ts.tz
    if series_tz is None and ts_tz is None:
        return series, ts
    if series_tz is not None and ts_tz is None:
        return series, ts.tz_localize(series_tz)
    if series_tz is None and ts_tz is not None:
        # Treat naive series as already in ts_tz (defensive default).
        return series.dt.tz_localize(ts_tz), ts
    return series, ts.tz_convert(series_tz)


def _check_staleness(
    ts_series: pd.Series,
    contract: DataContract,
    decision_time: Optional[Any],
    warnings: List[str],
    errors: List[str],
) -> None:
    """Compare last timestamp to ``decision_time`` against ``max_staleness_days``."""
    if contract.max_staleness_days is None or decision_time is None:
        return
    converted = pd.to_datetime(ts_series, errors="coerce", utc=False)
    if converted.isna().any() or len(converted) == 0:
        return
    last_ts = pd.Timestamp(converted.max())
    decision_ts = pd.Timestamp(decision_time)
    # Align tz for subtraction.
    if last_ts.tz is not None and decision_ts.tz is None:
        decision_ts = decision_ts.tz_localize(last_ts.tz)
    elif last_ts.tz is None and decision_ts.tz is not None:
        last_ts = last_ts.tz_localize(decision_ts.tz)
    delta_days = (decision_ts - last_ts).days
    if delta_days > contract.max_staleness_days:
        msg = (
            f"snapshot is stale: last timestamp {last_ts.isoformat()} is "
            f"{delta_days} day(s) before decision_time={decision_ts.isoformat()}, "
            f"max_staleness_days={contract.max_staleness_days}"
        )
        # staleness is a soft warning by convention; tighten if needed.
        warnings.append(msg)
        # Reference parameter "errors" in a no-op so static checkers do not
        # warn about an unused argument; staleness itself does not raise.
        _ = errors


def hash_dataframe(df: pd.DataFrame) -> str:
    """Deterministic ``sha256`` digest of a DataFrame's contents.

    Useful for the ``snapshot_hash`` parameter of :func:`validate_dataframe`.
    Sort order matters: rows are not reordered before hashing, so callers
    that care about content-equivalence must sort first.
    """
    h = hashlib.sha256()
    h.update(repr(tuple(df.columns)).encode("utf-8"))
    # Stable per-column digest. Avoid pickle so the digest is reproducible
    # across Python minor versions.
    for col in df.columns:
        s = df[col]
        h.update(col.encode("utf-8"))
        h.update(np.asarray(s.values).tobytes())
    h.update(np.asarray(df.index.values).tobytes())
    # Decision date stamp is intentionally omitted; this is data only.
    return h.hexdigest()


# Pin a commonly-used UTC reference for callers building decision_time.
UTC = timezone.utc


__all__ = [
    "UTC",
    "VALIDATOR_VERSION",
    "hash_dataframe",
    "validate_dataframe",
]
