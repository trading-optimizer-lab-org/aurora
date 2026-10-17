from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research import multiasset_baselines as mab

ASSETS = sorted({a for fn in ("SPY", "IWM", "EFA", "EEM", "IEF", "TLT", "SHY", "AGG", "LQD",
                              "TIP", "HYG", "GLD", "DBC", "VNQ", "QQQ", "XLB", "XLE", "XLF",
                              "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "PUT", "BXM") for a in [fn]})


def _prices(start: str = "1996-01-01", end: str = "2020-12-31", seed: int = 7) -> pd.DataFrame:
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.01, size=(len(idx), len(ASSETS)))
    prices = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=ASSETS)
    prices["CASH"] = 100 * (1 + 0.02 / 252) ** np.arange(len(idx))
    return prices


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_multiasset_baselines.py"
    spec = importlib.util.spec_from_file_location("run_multiasset_baselines", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_simulate_applies_targets_from_the_next_day_and_charges_costs() -> None:
    idx = pd.bdate_range("2020-01-01", periods=6)
    prices = pd.DataFrame({"A": [100, 110, 121, 121, 121, 121], "CASH": [1.0] * 6}, index=idx)
    weights = pd.DataFrame({"A": [1.0], "CASH": [0.0]}, index=[idx[1]])
    rets, turnover = mab.simulate(prices, weights, cost_bps=10)
    assert idx[1] not in rets.index  # nothing held on the signal day
    assert rets.loc[idx[2]] == pytest.approx(0.10 - 2 * 0.5 * 10 / 1e4)
    assert turnover.loc[idx[2]] == pytest.approx(0.5)


def test_holdings_drift_between_rebalances() -> None:
    idx = pd.bdate_range("2020-01-01", periods=4)
    prices = pd.DataFrame({"A": [100, 100, 200, 200], "B": [100, 100, 100, 50]}, index=idx)
    weights = pd.DataFrame({"A": [0.5], "B": [0.5]}, index=[idx[0]])
    rets, _ = mab.simulate(prices, weights, cost_bps=0)
    # After A doubles the book is 2/3 A, 1/3 B, so B halving costs 1/6.
    assert rets.loc[idx[3]] == pytest.approx(-1 / 6)


def test_simulate_refuses_to_pad_a_gap_in_a_held_asset() -> None:
    idx = pd.bdate_range("2020-01-01", periods=5)
    prices = pd.DataFrame({"A": [100, 101, np.nan, 103, 104]}, index=idx)
    weights = pd.DataFrame({"A": [1.0]}, index=[idx[0]])
    with pytest.raises(ValueError, match="missing return"):
        mab.simulate(prices, weights, cost_bps=0)


def test_blend_sums_sleeve_targets_by_share() -> None:
    idx = pd.bdate_range("2015-01-01", "2016-12-31")
    prices = pd.DataFrame({a: np.linspace(100, 150, len(idx)) for a in ["SPY", "IEF"]}, index=idx)
    monthly = prices.loc[mab.signal_dates(prices.index)]
    view = mab.MarketView(prices, monthly)
    mix = mab.blend({"spy_buy_hold": 0.5, "sixty_forty": 0.5})(view)
    assert mix == pytest.approx({"SPY": 0.8, "IEF": 0.2})


def test_blend_waits_for_every_sleeve() -> None:
    idx = pd.bdate_range("2015-01-01", "2015-03-31")
    prices = pd.DataFrame({a: np.linspace(100, 150, len(idx)) for a in ["SPY", "IEF"]}, index=idx)
    monthly = prices.loc[mab.signal_dates(prices.index)]
    assert mab.blend({"sixty_forty": 0.5, "gem": 0.5})(mab.MarketView(prices, monthly)) is None


def test_monthly_metrics_count_positive_months() -> None:
    idx = pd.bdate_range("2015-01-01", "2015-04-30")
    r = pd.Series(0.0, index=idx)
    r[r.index.month == 1] = 0.001
    r[r.index.month == 2] = -0.001
    r[r.index.month == 3] = 0.002
    r[r.index.month == 4] = 0.001
    out = mab._monthly_metrics(r, pd.Series(0.0, index=idx))
    assert out["positive_months"] == pytest.approx(0.75)
    assert out["sortino_monthly"] > out["sharpe_monthly"] > 0


def test_monthly_sortino_without_downside_follows_daily_convention() -> None:
    idx = pd.bdate_range("2015-01-01", "2015-06-30")
    up = mab._monthly_metrics(pd.Series(0.001, index=idx), pd.Series(0.0, index=idx))
    flat = mab._monthly_metrics(pd.Series(0.0, index=idx), pd.Series(0.0, index=idx))
    assert up["sortino_monthly"] == float("inf")
    assert flat["sortino_monthly"] == 0.0


def test_rank_uses_the_requested_period() -> None:
    results = {
        "a": {"in_sample": {"sharpe": 2.0, "sortino": 2.0}, "validation": {"sharpe": 0.1, "sortino": 0.1}},
        "b": {"in_sample": {"sharpe": 0.5, "sortino": 0.5}, "validation": {"sharpe": 1.0, "sortino": 1.0}},
    }
    assert mab._rank(results, period="in_sample") == ["a", "b"]
    assert mab._rank(results) == ["b", "a"]


def test_run_all_rejects_locked_period() -> None:
    prices = _prices(end="2021-01-05")
    with pytest.raises(ValueError, match="locked"):
        mab.run_all(prices)


def test_gtaa5_moves_assets_below_their_sma_to_cash() -> None:
    idx = pd.bdate_range("2015-01-01", "2016-12-31")
    prices = pd.DataFrame({a: np.linspace(100, 200, len(idx)) for a in ["SPY", "EFA", "IEF", "VNQ"]},
                          index=idx)
    prices["DBC"] = np.linspace(200, 100, len(idx))
    monthly = prices.loc[mab.signal_dates(prices.index)]
    w = mab.gtaa5(mab.MarketView(prices, monthly))
    assert w == pytest.approx({"CASH": 0.2, "SPY": 0.2, "EFA": 0.2, "IEF": 0.2, "VNQ": 0.2})


def test_vaa_g4_goes_defensive_when_any_offensive_asset_is_negative() -> None:
    idx = pd.bdate_range("2015-01-01", "2016-12-31")
    up = np.linspace(100, 150, len(idx))
    prices = pd.DataFrame({a: up for a in ["SPY", "EFA", "AGG", "LQD", "SHY"]}, index=idx)
    prices["EEM"] = np.linspace(150, 100, len(idx))
    prices["IEF"] = np.linspace(100, 200, len(idx))
    monthly = prices.loc[mab.signal_dates(prices.index)]
    assert mab.vaa_g4(mab.MarketView(prices, monthly)) == {"IEF": 1.0}


def test_vol_target_overlay_never_levers() -> None:
    idx = pd.bdate_range("2015-01-01", "2016-12-31")
    rets = pd.Series(np.random.default_rng(1).normal(0, 0.03, len(idx)), index=idx)
    cash = pd.Series(0.0, index=idx)
    out = mab.vol_target_overlay(rets, cash, cost_bps=0)
    assert (out.abs() <= rets.reindex(out.index).abs() + 1e-12).all()


def test_run_all_ranks_every_strategy_and_adds_the_overlay() -> None:
    result = mab.run_all(_prices())
    names = set(result["ranking"])
    assert set(mab.ALL_STRATEGIES) <= names
    assert any(n.startswith("vol_target_10__") for n in names)
    assert result["n_trials"] == len(mab.ALL_STRATEGIES) + 1
    for name in result["ranking"]:
        v = result["strategies"][name]["validation"]
        assert v["start"] >= "2011-01-01" and v["end"] <= "2020-12-31"
        assert 0.0 <= v["deflated_sharpe"] <= 1.0
    assert max(s.index.max() for s in result["daily_returns"].values()) < mab.LOCKED_START


def test_deflated_sharpe_scales_the_null_by_trial_dispersion() -> None:
    trials = [0.2, 0.4, 0.6, 0.8, 1.0]
    best = mab.deflated_sharpe(1.0, trials, n_periods=2520, skew=0.0, kurtosis=3.0)
    worst = mab.deflated_sharpe(0.2, trials, n_periods=2520, skew=0.0, kurtosis=3.0)
    assert 0.5 < best <= 1.0
    assert worst < best
    # Same Sharpe, more dispersed trials -> higher null bar -> lower DSR.
    wide = mab.deflated_sharpe(1.0, [0.0, 0.5, 1.0, 1.5, 2.0], n_periods=2520, skew=0.0, kurtosis=3.0)
    assert wide < best


def test_continuous_from_drops_sparse_early_history() -> None:
    script = _script()
    idx = pd.DatetimeIndex(["1991-03-04", "1991-06-28", "1991-07-01", "1991-07-02", "1991-07-03"])
    out = script.continuous_from(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx))
    assert out.index[0] == pd.Timestamp("1991-06-28")


def test_splice_fills_only_dates_before_the_etf_and_keeps_levels_continuous() -> None:
    script = _script()
    proxy = pd.Series([10.0, 11.0, 12.0, 13.0], index=pd.bdate_range("2000-01-03", periods=4), name="P")
    etf = pd.Series([100.0, 105.0], index=proxy.index[2:], name="E")
    out, used = script.splice(etf, [proxy])
    assert list(out.index) == list(proxy.index)
    assert out.iloc[2:].tolist() == [100.0, 105.0]
    assert out.iloc[1] == pytest.approx(100.0 * 11 / 12)
    assert used[0]["proxy"] == "P"
