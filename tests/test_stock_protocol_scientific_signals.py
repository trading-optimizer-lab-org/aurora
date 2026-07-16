"""Scientific signal and cross-sectional selection contracts.

These tests intentionally describe the corrected behaviour before the
implementation is changed.  They run in GitHub Actions under the repository's
GitHub-only execution policy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research.stock_protocol import signals
from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel


def _panel(frame: pd.DataFrame) -> ResearchPanel:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    audit = PackAudit(
        source_root="synthetic",
        output_root="synthetic",
        data_start=data["date"].min().date().isoformat(),
        data_end="2020-12-31",
        rows=len(data),
        symbols=data["symbol"].nunique(),
        locked_rows=0,
        survivorship_free=False,
        metadata_is_bitemporal=False,
        dataset_hash="synthetic-hash",
    )
    return ResearchPanel(data, audit)


def _daily_symbol(symbol: str, periods: int = 300) -> pd.DataFrame:
    dates = pd.bdate_range("2019-01-02", periods=periods)
    close = np.arange(100.0, 100.0 + periods)
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": close - 0.25,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "adj_close": close,
            "volume": np.full(periods, 100.0),
            "dividends": np.zeros(periods),
            "stock_splits": np.zeros(periods),
        }
    )


def _require(name: str):
    value = getattr(signals, name, None)
    assert callable(value), f"signals.{name} is not implemented"
    return value


def test_momentum_12_1_is_t_minus_21_over_t_minus_252():
    compute_features = _require("compute_features")
    frame = _daily_symbol("A")
    result = compute_features(_panel(frame))
    row = result.iloc[-1]
    expected = frame.iloc[-22]["adj_close"] / frame.iloc[-253]["adj_close"] - 1.0
    assert row["mom_12_1"] == expected


def test_momentum_6_1_is_t_minus_21_over_t_minus_126():
    compute_features = _require("compute_features")
    frame = _daily_symbol("A")
    result = compute_features(_panel(frame))
    row = result.iloc[-1]
    expected = frame.iloc[-22]["adj_close"] / frame.iloc[-127]["adj_close"] - 1.0
    assert row["mom_6_1"] == expected


def test_rvol_excludes_current_volume_from_historical_average():
    compute_features = _require("compute_features")
    frame = _daily_symbol("A", 80)
    frame.loc[frame.index[-1], "volume"] = 1000.0
    result = compute_features(_panel(frame))
    assert result.iloc[-1]["rvol50"] == 10.0


def test_true_range_uses_gaps_not_absolute_close_return_proxy():
    true_range = _require("compute_true_range")
    frame = pd.DataFrame(
        {
            "high": [101.0, 112.0],
            "low": [99.0, 109.0],
            "close": [100.0, 110.0],
        }
    )
    result = true_range(frame)
    assert result.iloc[1] == 12.0


def test_split_adjusted_prices_do_not_create_false_breakout():
    compute_features = _require("compute_features")
    frame = _daily_symbol("A", 260)
    split_index = frame.index[-1]
    frame.loc[split_index, ["open", "high", "low", "close"]] /= 2.0
    frame.loc[split_index, "adj_close"] = frame.loc[split_index - 1, "adj_close"]
    frame.loc[split_index, "stock_splits"] = 2.0
    result = compute_features(_panel(frame))
    assert not bool(result.iloc[-1]["breakout_252"])


def test_top_percent_selection_is_cross_sectional_per_date():
    select_cross_section = _require("select_cross_section")
    dates = pd.to_datetime(["2020-01-31"] * 10 + ["2020-02-28"] * 10)
    candidates = pd.DataFrame(
        {
            "signal_date": dates,
            "symbol": [f"S{i}" for i in range(10)] * 2,
            "score": list(range(10)) + list(reversed(range(10))),
        }
    )
    selected = select_cross_section(candidates, {"kind": "top_percent", "value": 0.20})
    assert selected.groupby("signal_date").size().to_dict() == {
        pd.Timestamp("2020-01-31"): 2,
        pd.Timestamp("2020-02-28"): 2,
    }
    assert set(selected.loc[selected["signal_date"] == pd.Timestamp("2020-01-31"), "symbol"]) == {"S8", "S9"}
    assert set(selected.loc[selected["signal_date"] == pd.Timestamp("2020-02-28"), "symbol"]) == {"S0", "S1"}


def test_binary_selection_excludes_zero_false_and_nan():
    select_cross_section = _require("select_cross_section")
    candidates = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2020-01-31"] * 5),
            "symbol": list("ABCDE"),
            "score": [1, 0, True, False, np.nan],
        }
    )
    selected = select_cross_section(candidates, {"kind": "binary"})
    assert selected["symbol"].tolist() == ["A", "C"]


def test_fixed_top_n_quintile_and_decile_are_supported():
    select_cross_section = _require("select_cross_section")
    candidates = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2020-01-31"] * 20),
            "symbol": [f"S{i:02d}" for i in range(20)],
            "score": np.arange(20),
        }
    )
    assert len(select_cross_section(candidates, {"kind": "top_n", "value": 3})) == 3
    assert len(select_cross_section(candidates, {"kind": "quintile", "value": 1})) == 4
    assert len(select_cross_section(candidates, {"kind": "decile", "value": 1})) == 2


def test_monthly_rebalance_emits_only_last_observed_date_per_month():
    rebalance_mask = _require("rebalance_mask")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-29", "2020-01-30", "2020-01-31", "2020-02-27", "2020-02-28"]),
            "symbol": ["A"] * 5,
        }
    )
    result = frame.loc[rebalance_mask(frame, frequency="monthly"), "date"].tolist()
    assert result == [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-28")]
