from __future__ import annotations

import pandas as pd

from aurora.infra.sp500_megarun.complete_snapshot import (
    build_financial_composites,
    build_lane_readiness,
)
from aurora.infra.sp500_megarun.data_contract import LaneContract


def test_financial_composites_are_bounded_to_spy_sessions_and_causal() -> None:
    spy = pd.DataFrame(
        {
            "date": pd.date_range("2009-01-02", periods=90, freq="B"),
            "close": range(100, 190),
        }
    )
    rates = pd.DataFrame(
        {
            "date": pd.date_range("2008-12-01", periods=120, freq="B"),
            "value": [2.0 + index / 100 for index in range(120)],
            "series_id": ["rate"] * 120,
        }
    )
    vix = pd.DataFrame(
        {
            "date": pd.date_range("2008-12-01", periods=120, freq="B"),
            "Close": [30.0 - index / 20 for index in range(120)],
        }
    )

    conditions, uncertainty = build_financial_composites(spy, rates, vix)

    assert conditions["date"].tolist() == spy["date"].tolist()
    assert uncertainty["date"].tolist() == spy["date"].tolist()
    assert conditions["financial_conditions_score"].notna().all()
    assert uncertainty["uncertainty_score"].notna().all()


def test_financial_composites_never_backfill_prepublication_sessions() -> None:
    sessions = pd.date_range("2009-01-02", periods=8, freq="B")
    spy = pd.DataFrame({"date": sessions, "close": range(100, 108)})
    rates = pd.DataFrame(
        {
            "date": sessions[2:],
            "value": [2.0, 2.1, 2.2, 2.3, 2.4, 2.5],
            "series_id": ["rate"] * 6,
        }
    )
    vix = pd.DataFrame(
        {
            "date": sessions[3:],
            "Close": [20.0, 19.0, 18.0, 17.0, 16.0],
        }
    )

    conditions, uncertainty = build_financial_composites(spy, rates, vix)

    assert conditions["date"].min() == sessions[3]
    assert uncertainty["date"].min() == sessions[3]
    assert sessions[:3].intersection(pd.DatetimeIndex(conditions["date"])).empty


def test_lane_readiness_requires_every_declared_dataset() -> None:
    lanes = (
        LaneContract("F001", ("D_SPY",), "exact", "SPY", ""),
        LaneContract("F002", ("D_SPY", "D_VIX"), "exact", "SPY and VIX", ""),
    )

    ready = build_lane_readiness(lanes, {"D_SPY", "D_VIX"})
    missing = build_lane_readiness(lanes, {"D_SPY"})

    assert [row["status"] for row in ready] == ["ready", "ready"]
    assert missing[1]["status"] == "blocked"
    assert missing[1]["missing_datasets"] == ["D_VIX"]
