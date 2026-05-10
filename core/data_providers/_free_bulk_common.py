"""Shared helpers for the R155 free bulk daily-data programme.

The new providers under ``aurora.core.data_providers.*`` (Stooq,
yfinance, yahooquery, Binance, CoinGecko, FRED, AKShare, the universe
downloaders, the experimental tier) all share three concerns:

1. They normalise their raw vendor frame into the same OHLCV daily
   contract before returning it (tests then check that the contract gate
   accepts / rejects expected shapes).
2. They wrap the resulting DataFrame in a
   :class:`~aurora.data_contracts.lineage.DataLineage` envelope so that
   provenance tracks the provider name, URL, retrieved-at, asof, query
   params, row count, date range, symbol count, contract hash.
3. They take an injectable client (an HTTP fetcher / parser callable)
   so tests can mock the network without monkey-patching ``urllib`` or
   ``requests``.

This module collects that shared machinery in one place. Putting the
contract here keeps the new providers pure-Python and free of
duplicated definitions, and gives the test suite a single import path
to assert against contract behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Tuple

import pandas as pd

from aurora.data_contracts import (
    AvailabilityPolicy,
    ContractField,
    CorporateActionPolicy,
    DataContract,
    DataLineage,
    hash_dataframe,
    validate_dataframe,
)


__all__ = [
    "FreeBulkLineage",
    "OHLCV_DAILY_V1",
    "UNIVERSE_V1",
    "MACRO_DAILY_V1",
    "FreeBulkContractViolation",
    "assert_against_contract",
    "assert_universe_frame",
    "build_lineage",
    "empty_ohlcv_frame",
    "normalise_ohlcv_frame",
    "utcnow_iso",
]


# ---------------------------------------------------------------------------
# Contracts shared across the free-bulk providers.
# ---------------------------------------------------------------------------


OHLCV_DAILY_V1 = DataContract(
    name="ohlcv_daily_v1",
    version="1.0.0",
    description=(
        "Daily OHLCV bars with timestamp axis, all price columns "
        "positive_only, integer volume."
    ),
    fields=(
        ContractField("timestamp", dtype_kind="datetime"),
        ContractField("open", positive_only=True, is_price=True),
        ContractField("high", positive_only=True, is_price=True),
        ContractField("low", positive_only=True, is_price=True),
        ContractField("close", positive_only=True, is_price=True),
        ContractField("volume", dtype_kind="integer", nullable=True),
    ),
    timestamp_col="timestamp",
    timezone="UTC",
    corporate_actions=CorporateActionPolicy(severity="fail"),
    availability=AvailabilityPolicy(),
)


UNIVERSE_V1 = DataContract(
    name="universe_v1",
    version="1.0.0",
    description=(
        "Normalised universe table: provider_symbol, canonical_symbol, "
        "exchange, asset_class, currency, active, source_timestamp."
    ),
    fields=(
        ContractField("provider_symbol", dtype_kind="string"),
        ContractField("canonical_symbol", dtype_kind="string"),
        ContractField("exchange", dtype_kind="string", nullable=True),
        ContractField("asset_class", dtype_kind="string"),
        ContractField("currency", dtype_kind="string", nullable=True),
        ContractField("active", dtype_kind="bool"),
        ContractField("source_timestamp", dtype_kind="datetime"),
    ),
    timestamp_col="source_timestamp",
    timezone="UTC",
    allow_naive_timestamps=True,
)


MACRO_DAILY_V1 = DataContract(
    name="macro_daily_v1",
    version="1.0.0",
    description=(
        "Daily macro series with a single ``value`` numeric column. "
        "asset_class is recorded in lineage extra (``MACRO``)."
    ),
    fields=(
        ContractField("timestamp", dtype_kind="datetime"),
        ContractField("value", dtype_kind="numeric", nullable=True),
    ),
    timestamp_col="timestamp",
    timezone="UTC",
)


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class FreeBulkContractViolation(ValueError):
    """Raised when a provider frame fails its declared contract.

    The exception carries the validator's :attr:`errors` tuple so callers
    (CLI / fallback chain) can surface them without re-running the check.
    """

    def __init__(self, errors: Tuple[str, ...], contract_name: str) -> None:
        message = (
            f"contract {contract_name!r} violated: " + "; ".join(errors)
        )
        super().__init__(message)
        self.errors = errors
        self.contract_name = contract_name


# ---------------------------------------------------------------------------
# Lineage envelope (minimal extension of DataLineage with provider extras).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FreeBulkLineage:
    """Provenance carrier returned alongside every approved snapshot.

    Wraps :class:`DataLineage` with a few free-bulk-specific extras
    (provider URL, query params, row/date/symbol counts) so the
    provenance object can be appended to the run report or stored
    alongside the parquet without losing provider context.

    The ``warnings`` tuple carries provider-level operator notices
    (licence terms, fallback posture, etc.) that should travel with
    the data without escalating to a contract violation.
    """

    lineage: DataLineage
    provider_name: str
    provider_url: str
    retrieved_at_iso: str
    auth_mode: str
    query_params: Mapping[str, Any]
    row_count: int
    date_range: Tuple[str, str]
    symbol_count: int
    extra: Mapping[str, Any] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def empty_ohlcv_frame() -> pd.DataFrame:
    """Return a tz-aware empty OHLCV frame matching :data:`OHLCV_DAILY_V1`.

    Used by providers when the upstream client returned no rows. The
    returned frame still passes the contract gate (no rows == no
    violations) but carries the UTC tz on the ``timestamp`` column so
    the validator does not falsely flag it as "naive but contract
    requires timezone=UTC".
    """
    return pd.DataFrame({
        "timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
        "open": pd.Series(dtype="float64"),
        "high": pd.Series(dtype="float64"),
        "low": pd.Series(dtype="float64"),
        "close": pd.Series(dtype="float64"),
        "volume": pd.Series(dtype="float64"),
    })


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with seconds precision."""
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=timezone.utc)
    return now.isoformat().replace("+00:00", "Z")


def assert_against_contract(
    df: pd.DataFrame,
    contract: DataContract = OHLCV_DAILY_V1,
) -> str:
    """Run :func:`validate_dataframe` and raise on any error.

    Returns the snapshot hash so callers can stamp it into provenance.
    Warnings are *not* raised -- only hard errors. This keeps the gate
    consistent with R155's "every contract violation surfaces, never
    silently merges" rule: warnings stay visible on the lineage object,
    errors block.
    """
    snapshot_hash = hash_dataframe(df) if isinstance(df, pd.DataFrame) else ""
    result = validate_dataframe(df, contract, snapshot_hash=snapshot_hash)
    if not result.passed:
        raise FreeBulkContractViolation(result.errors, contract.name)
    return snapshot_hash


def assert_universe_frame(df: pd.DataFrame) -> str:
    """Validate a universe DataFrame against :data:`UNIVERSE_V1`.

    Universe tables are not time-series so the standard monotonic /
    unique-timestamp checks do not apply. Instead we enforce: required
    columns present, no nulls in non-nullable columns, ``provider_symbol``
    + ``canonical_symbol`` non-empty, ``active`` boolean, and
    ``canonical_symbol`` uniqueness (one row per symbol within a
    snapshot). Returns the snapshot hash for provenance stamping.
    """
    if not isinstance(df, pd.DataFrame):
        raise FreeBulkContractViolation(
            ("input is not a pandas DataFrame",), UNIVERSE_V1.name
        )
    errors: list[str] = []
    required = (
        "provider_symbol",
        "canonical_symbol",
        "asset_class",
        "active",
        "source_timestamp",
    )
    missing = [c for c in required if c not in df.columns]
    if missing:
        errors.append(f"missing required columns: {sorted(missing)}")
    else:
        if df["provider_symbol"].isna().any():
            errors.append("provider_symbol has null(s) but is non-nullable")
        if df["canonical_symbol"].isna().any():
            errors.append("canonical_symbol has null(s) but is non-nullable")
        if df["asset_class"].isna().any():
            errors.append("asset_class has null(s) but is non-nullable")
        if df["active"].isna().any():
            errors.append("active has null(s) but is non-nullable")
        if df["source_timestamp"].isna().any():
            errors.append("source_timestamp has null(s) but is non-nullable")
        # Empty strings are not allowed for symbols.
        empty_provider = (df["provider_symbol"].astype(str) == "").sum()
        if empty_provider:
            errors.append(
                f"provider_symbol has {int(empty_provider)} empty value(s)"
            )
        empty_canonical = (df["canonical_symbol"].astype(str) == "").sum()
        if empty_canonical:
            errors.append(
                f"canonical_symbol has {int(empty_canonical)} empty value(s)"
            )
        # Uniqueness on canonical_symbol within the snapshot.
        if df["canonical_symbol"].duplicated().any():
            n = int(df["canonical_symbol"].duplicated().sum())
            errors.append(f"duplicate canonical_symbol: {n} duplicate row(s)")
    if errors:
        raise FreeBulkContractViolation(tuple(errors), UNIVERSE_V1.name)
    return hash_dataframe(df)


def normalise_ohlcv_frame(
    df: pd.DataFrame,
    *,
    timestamp_col: str = "timestamp",
) -> pd.DataFrame:
    """Coerce a raw OHLCV DataFrame into the shape OHLCV_DAILY_V1 expects.

    The input is assumed to already carry ``open``, ``high``, ``low``,
    ``close``, ``volume`` columns (case-insensitive) and a date-like
    index. This helper:

    * Lowercases column names.
    * Reorders columns to ``[open, high, low, close, volume]``.
    * Materialises the datetime index as a UTC-stamped ``timestamp``
      column (the contract's ``timestamp_col``).
    * Sorts ascending by timestamp.
    * Coerces ``volume`` to integer where possible (NaN-safe).

    The function does NOT validate -- callers wrap with
    :func:`assert_against_contract` to gate.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("normalise_ohlcv_frame expects a pandas DataFrame")
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    expected = ("open", "high", "low", "close", "volume")
    missing = [c for c in expected if c not in out.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")
    if isinstance(out.index, pd.DatetimeIndex):
        idx = out.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        else:
            idx = idx.tz_convert("UTC")
        # Preserve tz on the materialised column. ``idx.values`` would drop
        # the tz; assigning the index itself keeps tz_aware metadata.
        out = out.reset_index(drop=True)
        out[timestamp_col] = pd.Series(idx, index=out.index)
    else:
        if timestamp_col not in out.columns:
            raise ValueError(
                f"OHLCV frame must have a DatetimeIndex or a "
                f"{timestamp_col!r} column"
            )
        ts = pd.to_datetime(out[timestamp_col], utc=True, errors="coerce")
        out[timestamp_col] = ts
    out = out.sort_values(timestamp_col, kind="mergesort").reset_index(drop=True)
    # Volume to nullable integer; NaN stays NaN so the contract's
    # ``nullable=True`` on volume is honoured.
    if out["volume"].dtype != "int64":
        try:
            out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
        except (TypeError, ValueError):
            pass
    return out[[timestamp_col, *expected]]


def build_lineage(
    *,
    df: pd.DataFrame,
    contract: DataContract,
    provider_name: str,
    provider_url: str,
    retrieved_at_iso: Optional[str] = None,
    auth_mode: str = "none",
    query_params: Optional[Mapping[str, Any]] = None,
    asof_iso: str = "",
    code_version: str = "aurora-r155",
    decision_outcome: str = "accepted",
    transformation_chain: Tuple[str, ...] = (),
    snapshot_hash: Optional[str] = None,
    symbol_count: int = 1,
    extra: Optional[Mapping[str, Any]] = None,
    warnings: Tuple[str, ...] = (),
) -> FreeBulkLineage:
    """Build the provenance carrier for an approved snapshot.

    Computes ``snapshot_hash`` if not supplied, derives the date range
    from the timestamp column, and stamps a UTC ``retrieved_at_iso`` if
    the caller did not pass one.
    """
    snapshot_hash = snapshot_hash or hash_dataframe(df)
    if retrieved_at_iso is None:
        retrieved_at_iso = utcnow_iso()
    timestamp_col = contract.timestamp_col
    if timestamp_col in df.columns:
        ts_series = pd.to_datetime(df[timestamp_col], utc=True, errors="coerce")
        ts_series = ts_series.dropna()
        if len(ts_series):
            date_range = (
                ts_series.min().isoformat(),
                ts_series.max().isoformat(),
            )
        else:
            date_range = ("", "")
    else:
        date_range = ("", "")
    lineage = DataLineage(
        input_dataset_hash=asof_iso or retrieved_at_iso,
        transformation_chain=transformation_chain,
        code_version=code_version,
        contract_version=contract.version,
        snapshot_hash=snapshot_hash,
        validator_version="1.0.0",
        decision_outcome=decision_outcome,
        contract_hash=contract.contract_hash,
    )
    return FreeBulkLineage(
        lineage=lineage,
        provider_name=provider_name,
        provider_url=provider_url,
        retrieved_at_iso=retrieved_at_iso,
        auth_mode=auth_mode,
        query_params=dict(query_params or {}),
        row_count=int(len(df)),
        date_range=date_range,
        symbol_count=int(symbol_count),
        extra=dict(extra or {}),
        warnings=tuple(warnings),
    )
