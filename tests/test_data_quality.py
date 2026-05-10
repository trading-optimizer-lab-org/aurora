"""Tests for R161 data quality score + quarantine ledger."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.data_contracts import (
    ContractField,
    DataContract,
)
from aurora.data_contracts.quality import (
    CoverageReport,
    DataQualityReport,
    QuarantineEntry,
    QuarantineLedger,
    build_coverage,
    score_dataframe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ohlcv_contract(name: str = "test", exchange: str | None = None) -> DataContract:
    return DataContract(
        name=name,
        version="1.0.0",
        fields=(
            ContractField(name="timestamp", dtype_kind="datetime", nullable=False),
            ContractField(name="open", dtype_kind="numeric", positive_only=True, is_price=True),
            ContractField(name="high", dtype_kind="numeric", positive_only=True, is_price=True),
            ContractField(name="low", dtype_kind="numeric", positive_only=True, is_price=True),
            ContractField(name="close", dtype_kind="numeric", positive_only=True, is_price=True),
            ContractField(name="volume", dtype_kind="numeric"),
        ),
        timestamp_col="timestamp",
        timezone="UTC",
        allow_naive_timestamps=True,
        exchange=exchange,
    )


def _good_frame(n: int = 30) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=n)
    rng = np.random.default_rng(0)
    base = 100 + rng.standard_normal(n).cumsum()
    return pd.DataFrame({
        "timestamp": idx,
        "open": base + 0.5,
        "high": base + 1.0,
        "low": base - 1.0,
        "close": base,
        "volume": np.full(n, 1_000_000),
    })


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------


def test_clean_frame_is_approved():
    df = _good_frame()
    report = score_dataframe(
        df, _ohlcv_contract(), provider="yahoo", symbol="SPY",
    )
    assert report.decision == "approved"
    assert report.score >= 0.85
    assert report.duplicate_dates == 0
    assert report.impossible_ohlc == 0


def test_duplicate_dates_force_rejected():
    df = _good_frame()
    df.iloc[1, df.columns.get_loc("timestamp")] = df.iloc[0]["timestamp"]
    report = score_dataframe(
        df, _ohlcv_contract(), provider="yahoo", symbol="SPY",
    )
    assert report.duplicate_dates >= 1
    assert report.decision == "rejected"


def test_impossible_ohlc_force_rejected():
    df = _good_frame()
    df.iloc[3, df.columns.get_loc("low")] = df.iloc[3]["high"] + 5
    report = score_dataframe(
        df, _ohlcv_contract(), provider="yahoo", symbol="SPY",
    )
    assert report.impossible_ohlc >= 1
    assert report.decision == "rejected"


def test_nonpositive_price_warns():
    df = _good_frame()
    df.iloc[5, df.columns.get_loc("close")] = -1.0
    df.iloc[5, df.columns.get_loc("low")] = -2.0
    report = score_dataframe(
        df, _ohlcv_contract(), provider="yahoo", symbol="SPY",
    )
    assert report.nonpositive_prices >= 1
    assert report.decision in ("warning", "quarantined", "rejected")


def test_extreme_returns_lower_score():
    df = _good_frame()
    df.loc[df.index[10], "close"] = df["close"].iloc[9] * 5  # 500% jump
    df.loc[df.index[10], "open"] = df["close"].iloc[10]
    df.loc[df.index[10], "high"] = df["close"].iloc[10] + 1
    df.loc[df.index[10], "low"] = df["close"].iloc[10] - 1
    report = score_dataframe(
        df, _ohlcv_contract(), provider="yahoo", symbol="SPY",
    )
    assert report.extreme_returns >= 1


def test_quarantined_flag_overrides_decision():
    df = _good_frame()
    report = score_dataframe(
        df, _ohlcv_contract(), provider="yahoo", symbol="SPY",
        quarantined=True,
    )
    assert report.decision == "quarantined"
    assert report.is_blocking is True


def test_missing_sessions_only_flagged_for_equity_calendar():
    df_full = _good_frame(n=60)
    # Drop a chunk to create a gap in the equity calendar.
    df_gap = df_full.drop(index=range(20, 30)).reset_index(drop=True)
    eq_report = score_dataframe(
        df_gap, _ohlcv_contract(exchange="NYSE"),
        provider="yahoo", symbol="SPY",
    )
    crypto_report = score_dataframe(
        df_gap, _ohlcv_contract(exchange="BINANCE"),
        provider="yahoo", symbol="SPY",
    )
    assert eq_report.missing_sessions > 0
    assert crypto_report.missing_sessions == 0


def test_report_serialises_to_dict():
    df = _good_frame()
    report = score_dataframe(
        df, _ohlcv_contract(), provider="yahoo", symbol="SPY", version="v1",
    )
    payload = report.to_dict()
    assert payload["decision"] == "approved"
    assert payload["provider"] == "yahoo"
    assert payload["symbol"] == "SPY"
    assert "generated_at" in payload


def test_report_score_is_clamped_to_zero():
    df = _good_frame(n=4)
    # Multiple stacked failures: duplicate, impossible OHLC, nonpositive.
    df.loc[df.index[1], "timestamp"] = df.iloc[0]["timestamp"]
    df.loc[df.index[2], "low"] = df.iloc[2]["high"] + 5
    df.loc[df.index[3], "close"] = -10
    report = score_dataframe(
        df, _ohlcv_contract(), provider="yahoo", symbol="SPY",
    )
    assert report.score >= 0.0
    assert report.decision == "rejected"


# ---------------------------------------------------------------------------
# Quarantine ledger tests
# ---------------------------------------------------------------------------


def test_quarantine_ledger_round_trip(tmp_path: Path):
    ledger = QuarantineLedger(tmp_path / "q.jsonl")
    entry = ledger.quarantine(
        provider="yahoo", library="prices_daily",
        symbol="BAD", version="v1",
        reason="impossible OHLC",
        actor="operator",
    )
    assert entry.decision == "quarantined"
    assert ledger.is_quarantined(
        provider="yahoo", library="prices_daily",
        symbol="BAD", version="v1",
    ) is True


def test_quarantine_ledger_approve_clears_state(tmp_path: Path):
    ledger = QuarantineLedger(tmp_path / "q.jsonl")
    ledger.quarantine(
        provider="yahoo", library="prices_daily",
        symbol="GOOD", version="v1",
        reason="initial review",
        actor="operator",
    )
    ledger.approve(
        provider="yahoo", library="prices_daily",
        symbol="GOOD", version="v1",
        reason="data fixed",
        actor="operator",
    )
    assert ledger.is_quarantined(
        provider="yahoo", library="prices_daily",
        symbol="GOOD", version="v1",
    ) is False


def test_quarantine_ledger_persists_across_instances(tmp_path: Path):
    path = tmp_path / "q.jsonl"
    ledger1 = QuarantineLedger(path)
    ledger1.quarantine(
        provider="yahoo", library="prices_daily",
        symbol="BAD", version="v1",
        reason="duplicate dates",
        actor="operator",
    )
    ledger2 = QuarantineLedger(path)
    assert ledger2.is_quarantined(
        provider="yahoo", library="prices_daily",
        symbol="BAD", version="v1",
    ) is True


def test_quarantine_ledger_returns_empty_when_file_missing(tmp_path: Path):
    ledger = QuarantineLedger(tmp_path / "nope.jsonl")
    assert ledger.entries() == []
    assert ledger.is_quarantined(
        provider="yahoo", library="prices", symbol="X", version="v1",
    ) is False


def test_quarantine_ledger_rejects_non_recordable_decision(tmp_path: Path):
    ledger = QuarantineLedger(tmp_path / "q.jsonl")
    entry = QuarantineEntry(
        provider="yahoo",
        library="prices_daily",
        symbol="BAD",
        version="v1",
        reason="bogus",
        actor="op",
        decision="rejected",  # type: ignore[arg-type]
        recorded_at="2026-05-10T00:00:00+00:00",
    )
    with pytest.raises(ValueError):
        ledger.append(entry)


def test_quarantine_ledger_lines_are_valid_json(tmp_path: Path):
    ledger = QuarantineLedger(tmp_path / "q.jsonl")
    ledger.quarantine(
        provider="yahoo", library="prices_daily",
        symbol="BAD", version="v1",
        reason="x", actor="op",
    )
    raw = (tmp_path / "q.jsonl").read_text(encoding="utf-8").splitlines()
    assert raw
    for line in raw:
        json.loads(line)


# ---------------------------------------------------------------------------
# Coverage tests
# ---------------------------------------------------------------------------


def test_build_coverage_classifies_per_decision():
    df = _good_frame()
    contract = _ohlcv_contract()
    rep_a = score_dataframe(df, contract, provider="yahoo", symbol="A")
    bad_df = df.copy()
    bad_df.loc[bad_df.index[1], "timestamp"] = bad_df.iloc[0]["timestamp"]
    rep_b = score_dataframe(bad_df, contract, provider="yahoo", symbol="B")
    rep_c = score_dataframe(
        df, contract, provider="yahoo", symbol="C", quarantined=True,
    )
    coverage = build_coverage(["A", "B", "C", "MISSING"], [rep_a, rep_b, rep_c])
    assert coverage.approved == ("A",)
    assert coverage.rejected == ("B",)
    assert coverage.quarantined == ("C",)
    assert coverage.missing == ("MISSING",)
    assert coverage.counts["requested"] == 4
    payload = coverage.to_dict()
    assert payload["counts"]["approved"] == 1
