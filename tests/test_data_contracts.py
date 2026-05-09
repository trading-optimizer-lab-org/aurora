"""Tests for the data-contracts package (Phase 1, Candidate C).

Each requirement listed in the Phase 1 playbook gets one focused test:

* Clean data passes
* Missing required column fails
* Duplicate timestamp fails
* Non-monotonic timestamp fails
* Mixed timezone input fails
* Zero / negative price fails
* Split-like jump warns or fails per contract severity
* ``available_time > decision_time`` fails
* Validator result preserves policy and snapshot hashes
* SecurityMaster lookup and active-at-date logic
* Corporate-action split adjustment verification
* Lineage round-trip via ``to_dict`` / ``from_dict``
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from quantforge.data_contracts import (
    AvailabilityPolicy,
    ContractField,
    CorporateActionPolicy,
    CorporateActionRecord,
    DataContract,
    DataLineage,
    SecurityMaster,
    SecurityMasterRecord,
    hash_dataframe,
    validate_dataframe,
    verify_dividend_adjustment,
    verify_split_adjustment,
)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _utc(year: int, month: int, day: int) -> pd.Timestamp:
    return pd.Timestamp(datetime(year, month, day, tzinfo=timezone.utc))


def _basic_contract(**overrides) -> DataContract:
    """Return a baseline OHLC contract used across the suite."""
    base = dict(
        name="ohlc_v1",
        fields=(
            ContractField("timestamp", dtype_kind="datetime"),
            ContractField("open", positive_only=True, is_price=True),
            ContractField("high", positive_only=True, is_price=True),
            ContractField("low", positive_only=True, is_price=True),
            ContractField("close", positive_only=True, is_price=True),
            ContractField("volume", dtype_kind="integer"),
        ),
        timestamp_col="timestamp",
        timezone="UTC",
        corporate_actions=CorporateActionPolicy(
            split_jump_threshold=0.5,
            severity="warn",
            impossible_return_threshold=2.3,
        ),
    )
    base.update(overrides)
    return DataContract(**base)


def _clean_df(rows: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [_utc(2024, 1, d) for d in range(1, rows + 1)],
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1_000 + i for i in range(rows)],
        }
    )


# --------------------------------------------------------------------------
# 1. clean data passes
# --------------------------------------------------------------------------


def test_clean_data_passes() -> None:
    df = _clean_df()
    contract = _basic_contract()
    result = validate_dataframe(df, contract)
    assert result.passed, f"errors={result.errors} warnings={result.warnings}"
    assert result.errors == ()
    assert result.contract_hash == contract.contract_hash


# --------------------------------------------------------------------------
# 2. missing required column fails
# --------------------------------------------------------------------------


def test_missing_required_column_fails() -> None:
    df = _clean_df().drop(columns=["close"])
    result = validate_dataframe(df, _basic_contract())
    assert not result.passed
    assert any("missing required columns" in e for e in result.errors)
    assert any("'close'" in e or "close" in e for e in result.errors)


# --------------------------------------------------------------------------
# 3. duplicate timestamp fails
# --------------------------------------------------------------------------


def test_duplicate_timestamp_fails() -> None:
    df = _clean_df()
    df.loc[1, "timestamp"] = df.loc[0, "timestamp"]
    result = validate_dataframe(df, _basic_contract())
    assert not result.passed
    assert any("duplicate timestamps" in e for e in result.errors)


# --------------------------------------------------------------------------
# 4. non-monotonic timestamp fails
# --------------------------------------------------------------------------


def test_non_monotonic_timestamp_fails() -> None:
    df = _clean_df()
    # Swap two rows so the index is no longer monotonic.
    a = df.loc[1, "timestamp"]
    df.loc[1, "timestamp"] = df.loc[3, "timestamp"]
    df.loc[3, "timestamp"] = a
    result = validate_dataframe(df, _basic_contract())
    assert not result.passed
    assert any("monotonically increasing" in e for e in result.errors)


# --------------------------------------------------------------------------
# 5. mixed timezone input fails
# --------------------------------------------------------------------------


def test_mixed_timezone_fails() -> None:
    # Build a column with mixed timezones directly. Pandas would auto-convert
    # if we used df.loc[...] = on a tz-aware column, so we construct the
    # whole Series as object dtype with two distinct tz-aware Timestamps.
    rows = 5
    timestamps = [
        pd.Timestamp(datetime(2024, 1, 1, tzinfo=timezone.utc)),
        pd.Timestamp("2024-01-02 09:30:00", tz="US/Eastern"),
        pd.Timestamp(datetime(2024, 1, 3, tzinfo=timezone.utc)),
        pd.Timestamp(datetime(2024, 1, 4, tzinfo=timezone.utc)),
        pd.Timestamp(datetime(2024, 1, 5, tzinfo=timezone.utc)),
    ]
    df = pd.DataFrame(
        {
            "timestamp": pd.Series(timestamps, dtype=object),
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1_000 + i for i in range(rows)],
        }
    )
    result = validate_dataframe(df, _basic_contract())
    assert not result.passed
    assert any(
        "mixed timezones" in e or "tz" in e or "timezone" in e for e in result.errors
    )


# --------------------------------------------------------------------------
# 6. zero / negative price fails
# --------------------------------------------------------------------------


def test_zero_or_negative_price_fails() -> None:
    df = _clean_df()
    df.loc[2, "close"] = 0.0
    df.loc[3, "open"] = -1.5
    result = validate_dataframe(df, _basic_contract())
    assert not result.passed
    assert any("non-positive value" in e for e in result.errors)


# --------------------------------------------------------------------------
# 7. split-like jump: warns or fails per contract severity
# --------------------------------------------------------------------------


def test_split_like_jump_warns() -> None:
    df = _clean_df()
    # Simulate a 2-for-1 unadjusted split: close jumps from 102.5 to 51.25.
    df.loc[2, "close"] = 51.25
    df.loc[2, "open"] = 51.0
    df.loc[2, "high"] = 51.5
    df.loc[2, "low"] = 50.0
    contract = _basic_contract(
        corporate_actions=CorporateActionPolicy(
            split_jump_threshold=0.5,
            severity="warn",
            impossible_return_threshold=2.3,
        )
    )
    result = validate_dataframe(df, contract)
    assert result.passed, f"unexpected errors {result.errors}"
    assert any("split-like jump" in w for w in result.warnings)


def test_split_like_jump_fails_when_severity_is_fail() -> None:
    df = _clean_df()
    df.loc[2, "close"] = 51.25
    df.loc[2, "open"] = 51.0
    df.loc[2, "high"] = 51.5
    df.loc[2, "low"] = 50.0
    contract = _basic_contract(
        corporate_actions=CorporateActionPolicy(
            split_jump_threshold=0.5,
            severity="fail",
            impossible_return_threshold=2.3,
        )
    )
    result = validate_dataframe(df, contract)
    assert not result.passed
    assert any("split-like jump" in e for e in result.errors)


# --------------------------------------------------------------------------
# 8. available_time > decision_time fails
# --------------------------------------------------------------------------


def test_available_time_after_decision_time_fails() -> None:
    df = _clean_df()
    df["available_time"] = [
        _utc(2024, 1, 1),
        _utc(2024, 1, 2),
        _utc(2024, 1, 3),
        _utc(2024, 1, 4),
        _utc(2024, 1, 10),  # leaks past the decision time below
    ]
    contract = _basic_contract(
        fields=(
            ContractField("timestamp", dtype_kind="datetime"),
            ContractField("open", positive_only=True, is_price=True),
            ContractField("high", positive_only=True, is_price=True),
            ContractField("low", positive_only=True, is_price=True),
            ContractField("close", positive_only=True, is_price=True),
            ContractField("volume", dtype_kind="integer"),
            ContractField("available_time", dtype_kind="datetime"),
        ),
        availability=AvailabilityPolicy(available_time_col="available_time"),
    )
    decision_time = _utc(2024, 1, 5)
    result = validate_dataframe(df, contract, decision_time=decision_time)
    assert not result.passed
    assert any("point-in-time leak" in e for e in result.errors)


# --------------------------------------------------------------------------
# 9. validator result preserves policy and snapshot hashes
# --------------------------------------------------------------------------


def test_result_preserves_snapshot_and_contract_hashes() -> None:
    df = _clean_df()
    contract = _basic_contract()
    snap = hash_dataframe(df)
    result = validate_dataframe(df, contract, snapshot_hash=snap)
    assert result.snapshot_hash == snap
    assert result.contract_hash == contract.contract_hash
    assert result.validator_version


# --------------------------------------------------------------------------
# 10. SecurityMaster lookup and active-at-date logic
# --------------------------------------------------------------------------


def test_security_master_lookup_and_active_window() -> None:
    sm = SecurityMaster()
    aapl = SecurityMasterRecord(
        symbol="AAPL",
        vendor_symbol="AAPL",
        broker_symbol="AAPL",
        exchange="NASDAQ",
        currency="USD",
        listing_window=(date(1980, 12, 12), date(2099, 1, 1)),
        active=True,
        isin="US0378331005",
    )
    delisted = SecurityMasterRecord(
        symbol="ENRN",
        vendor_symbol="ENRN",
        broker_symbol="ENRN",
        exchange="NYSE",
        currency="USD",
        listing_window=(date(1985, 7, 1), date(2001, 12, 2)),
        active=False,
    )
    sm.register(aapl)
    sm.register(delisted)

    # lookup
    assert sm.get("AAPL") is aapl
    assert sm.get("UNKNOWN") is None
    assert "AAPL" in sm
    assert len(sm) == 2
    assert sm.all_symbols() == ("AAPL", "ENRN")

    # active-at-date
    assert sm.is_active_at("AAPL", date(2024, 1, 1)) is True
    assert sm.is_active_at("AAPL", date(1900, 1, 1)) is False
    assert sm.is_active_at("ENRN", date(2024, 1, 1)) is False
    assert sm.is_active_at("UNKNOWN", date(2024, 1, 1)) is False
    # accepts datetime + ISO string
    assert sm.is_active_at("AAPL", datetime(2024, 1, 1)) is True
    assert sm.is_active_at("AAPL", "2024-01-01") is True


def test_security_master_register_requires_symbol() -> None:
    sm = SecurityMaster()
    with pytest.raises(ValueError):
        sm.register(
            SecurityMasterRecord(
                symbol="",
                vendor_symbol="x",
                broker_symbol="x",
                exchange="X",
                currency="USD",
            )
        )


# --------------------------------------------------------------------------
# 11. corporate action split adjustment verification
# --------------------------------------------------------------------------


def test_split_adjustment_verifier_accepts_consistent_data() -> None:
    # 2-for-1 split: pre-action prices around 100, post-action around 50.
    action = CorporateActionRecord(
        symbol="AAPL",
        action_type="split",
        effective_date=date(2024, 1, 5),
        factor=2.0,
    )
    check = verify_split_adjustment([99.0, 100.0], [50.0, 50.5], action)
    assert check.passed
    assert "consistent" in check.reason


def test_split_adjustment_verifier_rejects_inconsistent_data() -> None:
    action = CorporateActionRecord(
        symbol="AAPL",
        action_type="split",
        effective_date=date(2024, 1, 5),
        factor=2.0,
    )
    # post-action prices look unchanged -> inconsistent with a 2-for-1 split.
    check = verify_split_adjustment([100.0], [99.0], action)
    assert not check.passed
    assert "inconsistent" in check.reason


def test_dividend_adjustment_verifier_accepts_consistent_data() -> None:
    action = CorporateActionRecord(
        symbol="AAPL",
        action_type="cash_dividend",
        effective_date=date(2024, 1, 5),
        cash_amount=1.0,
    )
    check = verify_dividend_adjustment([100.0], [99.0], action)
    assert check.passed


# --------------------------------------------------------------------------
# 12. lineage round-trip
# --------------------------------------------------------------------------


def test_lineage_round_trip() -> None:
    lineage = DataLineage(
        input_dataset_hash="abc123",
        transformation_chain=("ingest", "adjust_splits", "resample_daily"),
        code_version="1.4.0",
        contract_version="1.0.0",
        snapshot_hash="def456",
        validator_version="1.0.0",
        decision_outcome="accepted",
        contract_hash="contracthash",
        policy_hash="policyhash",
    )
    payload = lineage.to_dict()
    assert payload["transformation_chain"] == [
        "ingest",
        "adjust_splits",
        "resample_daily",
    ]
    restored = DataLineage.from_dict(payload)
    assert restored == lineage


# --------------------------------------------------------------------------
# bonus: impossible-return is hard error regardless of severity
# --------------------------------------------------------------------------


def test_impossible_return_always_errors() -> None:
    df = _clean_df()
    df.loc[2, "close"] = 0.0001  # log return ~ -13
    df.loc[2, "open"] = 0.0001
    df.loc[2, "high"] = 0.0002
    df.loc[2, "low"] = 0.00005
    contract = _basic_contract(
        corporate_actions=CorporateActionPolicy(
            split_jump_threshold=0.5,
            severity="warn",
            impossible_return_threshold=2.3,
        )
    )
    result = validate_dataframe(df, contract)
    assert not result.passed
    assert any("impossible bar-to-bar move" in e for e in result.errors)
