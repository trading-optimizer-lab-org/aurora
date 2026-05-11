"""R157 / R158 persistence helper -- writes one frame to the TimeSeriesStore.

The provider modules already gate on the contract internally; the
caller only invokes :func:`persist` after a fetch returns successfully.

R158 hardens the persistence layer with extra contract gates beyond
what the contract validator enforces:

* required_columns: per-section spec from the manifest
  (``expected_fields``).
* monotonic_dates / no_duplicates / OHLC order / zero-or-negative
  prices / empty frame: redundant defence-in-depth checks.
* extreme_return_spike: any |daily_return| > 1.0 -> reject; > 0.5 ->
  warning. Catches feed-corruption events the schema validator does
  not flag (a 200% one-day move is technically valid OHLCV).
* calendar_gap: a daily series with a gap > 5 calendar days emits a
  warning so the operator can audit holidays vs missing data.
* timezone_policy: any non-UTC timestamp -> reject.

Violations that constitute a hard reject raise
:class:`PersistenceContractViolation`. The walker turns the exception
into a per-symbol failure record (no row in the store).
"""
from __future__ import annotations

from typing import Any, Iterable, Tuple

import numpy as np
import pandas as pd

from aurora.data_contracts.timeseries_store import TimeSeriesStore

from .._free_bulk_common import FreeBulkLineage


__all__ = ["persist", "PersistenceContractViolation"]


_OHLCV_PRICE_COLS = ("open", "high", "low", "close")

# Daily returns above this are flagged as warnings.
_RETURN_WARN_THRESHOLD = 0.5
# Daily returns above this are hard-rejected as "feed corruption".
_RETURN_REJECT_THRESHOLD = 1.0
# Gap (calendar days) between consecutive rows that triggers a warning
# in supposedly-daily series.
_DAILY_GAP_WARN_DAYS = 5


class PersistenceContractViolation(ValueError):
    """Raised by :func:`persist` when the post-contract gate fails.

    The walker catches this and records the violation as a per-symbol
    failure with no row in the store.
    """

    def __init__(self, errors: Tuple[str, ...]) -> None:
        message = "persistence contract violated: " + "; ".join(errors)
        super().__init__(message)
        self.errors = tuple(errors)


def _check_required_columns(
    df: pd.DataFrame, expected: Iterable[str], errors: list[str],
) -> None:
    missing = [c for c in expected if c not in df.columns]
    if missing:
        errors.append(f"missing columns: {','.join(missing)}")


def _check_empty(df: pd.DataFrame, errors: list[str]) -> None:
    if len(df) == 0:
        errors.append("empty frame")


def _check_timestamp(
    df: pd.DataFrame, errors: list[str], warnings: list[str], frequency: str,
) -> None:
    """Enforce timestamp policy on OHLCV / FX / macro frames.

    Macro frames may use the index instead of a ``timestamp`` column;
    skip the column check when no obvious time axis is present (the
    base contract gate already covered the column requirement).
    """
    if "timestamp" not in df.columns:
        return
    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=False)
    if ts.isna().any():
        errors.append("timestamp column has un-parseable values")
        return
    if not ts.is_monotonic_increasing:
        errors.append("timestamps not monotonic increasing")
    if ts.duplicated().any():
        errors.append("duplicate timestamps")
    # tz policy: providers must hand UTC up; naive is allowed only when
    # the contract validator already accepted it.
    tz_attr = getattr(ts.dtype, "tz", None)
    if tz_attr is not None and str(tz_attr) not in ("UTC", "tzutc()"):
        errors.append(f"non-UTC timezone: {tz_attr}")
    # Calendar gap warning (daily only).
    if frequency == "1d" and len(ts) >= 2:
        gap_days = (ts.iloc[-1] - ts.iloc[0]).days
        if gap_days >= 0:
            diffs = ts.diff().dropna().dt.days
            if (diffs > _DAILY_GAP_WARN_DAYS).any():
                worst = int(diffs.max())
                warnings.append(
                    f"calendar gap > {_DAILY_GAP_WARN_DAYS} days "
                    f"detected in daily series (worst={worst}d)"
                )


def _check_prices(df: pd.DataFrame, errors: list[str]) -> None:
    """Reject zero/negative prices and out-of-order OHLC bands."""
    have = [c for c in _OHLCV_PRICE_COLS if c in df.columns]
    if not have:
        return
    for col in have:
        vals = pd.to_numeric(df[col], errors="coerce")
        if (vals <= 0).any():
            errors.append(f"non-positive {col} values")
    if all(c in df.columns for c in _OHLCV_PRICE_COLS):
        o = pd.to_numeric(df["open"], errors="coerce")
        h = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce")
        c = pd.to_numeric(df["close"], errors="coerce")
        # high >= max(open, close) and low <= min(open, close)
        max_oc = np.maximum(o.to_numpy(), c.to_numpy())
        min_oc = np.minimum(o.to_numpy(), c.to_numpy())
        if (h.to_numpy() < max_oc).any():
            errors.append("OHLC violation: high < max(open, close)")
        if (low.to_numpy() > min_oc).any():
            errors.append("OHLC violation: low > min(open, close)")


def _check_extreme_returns(
    df: pd.DataFrame, errors: list[str], warnings: list[str],
) -> None:
    """Reject daily returns > _RETURN_REJECT_THRESHOLD; warn over warn threshold.

    Operates on the close column when present. A 200% intraday move
    on a major US equity is, in practice, a feed corruption flag.
    Crypto markets can move >50% on a single day in extreme tails, so
    we warn at 50% but only reject at 100%.
    """
    if "close" not in df.columns or len(df) < 2:
        return
    closes = pd.to_numeric(df["close"], errors="coerce")
    rets = closes.pct_change().abs()
    if (rets > _RETURN_REJECT_THRESHOLD).any():
        worst = float(rets.max())
        errors.append(
            f"extreme return spike rejected (|daily return| {worst:.2%}"
            f" > {_RETURN_REJECT_THRESHOLD:.0%})"
        )
    elif (rets > _RETURN_WARN_THRESHOLD).any():
        worst = float(rets.max())
        warnings.append(
            f"extreme return spike warning (|daily return| {worst:.2%}"
            f" > {_RETURN_WARN_THRESHOLD:.0%})"
        )


def _run_strict_gates(
    df: pd.DataFrame,
    *,
    expected_fields: Iterable[str],
    section_name: str,
    frequency: str,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Run the R158 strict contract gates. Returns (errors, warnings).

    Identity / fundamentals frames are not OHLCV, so we skip the
    price-band and return-spike checks for them. The required-field
    check still runs.
    """
    errors: list[str] = []
    warnings: list[str] = []
    _check_empty(df, errors)
    _check_required_columns(df, expected_fields, errors)
    sn = section_name.lower()
    if sn not in ("identity", "fundamentals"):
        _check_timestamp(df, errors, warnings, frequency)
        _check_prices(df, errors)
        _check_extreme_returns(df, errors, warnings)
    return tuple(errors), tuple(warnings)


def persist(
    store: TimeSeriesStore,
    library: str,
    symbol: str,
    df: pd.DataFrame,
    lineage: FreeBulkLineage,
    *,
    section_name: str,
    expected_fields: Iterable[str] = (),
    frequency: str = "1d",
) -> Tuple[str, str]:
    """Write ``df`` to the store with a lineage-derived metadata blob.

    Runs the R158 strict contract gates first; raises
    :class:`PersistenceContractViolation` on hard reject. Otherwise
    returns ``(version, content_hash)`` so the caller can record both
    in the per-symbol report.

    Strict-gate warnings are appended to the metadata's ``warnings``
    list so the bootstrap report surfaces them via ``coverage-report``.
    """
    errs, warns = _run_strict_gates(
        df,
        expected_fields=expected_fields,
        section_name=section_name,
        frequency=frequency,
    )
    if errs:
        raise PersistenceContractViolation(errs)
    metadata: dict[str, Any] = {
        "section": section_name,
        "provider_name": lineage.provider_name,
        "provider_url": lineage.provider_url,
        "retrieved_at_iso": lineage.retrieved_at_iso,
        "auth_mode": lineage.auth_mode,
        "row_count": int(lineage.row_count),
        "date_range_start": lineage.date_range[0] if lineage.date_range else "",
        "date_range_end": lineage.date_range[1] if lineage.date_range else "",
        "snapshot_hash": lineage.lineage.snapshot_hash,
        "contract_hash": lineage.lineage.contract_hash,
        "warnings": list(lineage.warnings) + list(warns),
    }
    # Fold provider-specific extras (reliability, source, adjustment_posture,
    # ...). Cast to strings so the metadata json stays small.
    for k, v in dict(lineage.extra).items():
        metadata[f"extra_{k}"] = str(v) if v is not None else ""
    rec = store.put(library, symbol, df, metadata=metadata)
    return rec.version, rec.content_hash
