from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import multiasset_baselines as mab
from aurora.research import multiasset_robustness as rob

ASSETS = ["SPY", "TLT", "IEF", "GLD", "DBC", "EFA", "EEM", "AGG", "LQD", "SHY"]


def _prices(start: str = "2000-01-03", end: str = "2020-12-31") -> pd.DataFrame:
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(3)
    rets = rng.normal(0.0003, 0.008, size=(len(idx), len(ASSETS)))
    prices = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=ASSETS)
    prices["CASH"] = 100 * (1 + 0.02 / 252) ** np.arange(len(idx))
    return prices


def test_signal_dates_on_a_day_of_month() -> None:
    idx = pd.bdate_range("2020-02-01", "2020-03-31")
    days = mab.signal_dates(idx, day=15)
    assert list(days) == [pd.Timestamp("2020-02-14"), pd.Timestamp("2020-03-13")]


def test_aw_vaa_baseline_matches_the_registered_blend() -> None:
    prices = _prices(start="2015-01-01", end="2017-12-29")
    monthly = prices.loc[mab.signal_dates(prices.index)]
    view = mab.MarketView(prices, monthly)
    assert rob.aw_vaa()(view) == pytest.approx(mab.BLENDS["blend_aw_vaa"](view))


def test_aw_share_moves_weight_between_sleeves() -> None:
    prices = _prices(start="2015-01-01", end="2017-12-29")
    monthly = prices.loc[mab.signal_dates(prices.index)]
    view = mab.MarketView(prices, monthly)
    w = rob.aw_vaa(aw_share=0.6)(view)
    # VAA-G4 never holds gold, so GLD comes only from the All Weather sleeve.
    assert w["GLD"] == pytest.approx(0.6 * 0.075)
    assert sum(w.values()) == pytest.approx(1.0)


def test_block_bootstrap_is_reproducible_and_ordered() -> None:
    excess = pd.Series(np.random.default_rng(5).normal(0.005, 0.02, 120))
    a = rob.block_bootstrap_sortino(excess, n=200, seed=1)
    b = rob.block_bootstrap_sortino(excess, n=200, seed=1)
    assert a == b
    assert a["p05"] <= a["p50"] <= a["p95"]


def test_run_robustness_rejects_locked_data() -> None:
    with pytest.raises(ValueError, match="locked"):
        rob.run_robustness(_prices(end="2021-02-01"), bootstrap_draws=10)


def test_run_robustness_reports_every_check() -> None:
    out = rob.run_robustness(_prices(), bootstrap_draws=20)
    assert set(out) == {"baseline", "costs", "rebalance_day", "rolling_36m", "bootstrap", "parameters"}
    assert len(out["parameters"]) == len(rob.SCORES) * 3
    assert out["costs"]["40bps"]["val_sortino_monthly"] <= out["costs"]["5bps"]["val_sortino_monthly"]
    assert out["rolling_36m"]["windows"] > 0
