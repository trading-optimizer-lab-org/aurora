from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import crypto_carry as cc


def _asset(n: int = 1600, funding: float = 0.0003, seed: int = 0) -> pd.DataFrame:
    idx = pd.date_range("2019-09-10", periods=n, freq="D")
    rng = np.random.default_rng(seed)
    spot = 100 * np.cumprod(1 + rng.normal(0, 0.04, n))
    perp = spot * (1 + rng.normal(0, 0.0005, n))
    return pd.DataFrame({"spot": spot, "perp": perp, "funding": funding}, index=idx)


def test_identical_legs_earn_half_the_funding_minus_entry_fees() -> None:
    d = _asset()
    d["spot"] = 100.0
    d["perp"] = 100.0
    r = cc.sleeve_returns(d["spot"], d["perp"], d["funding"], pd.Series(True, index=d.index))
    entry = 0.5 * (cc.FEE_SPOT + cc.FEE_PERP)
    assert r.iloc[1] == pytest.approx(-entry)
    # With flat prices each day earns 0.5 * funding, less the fees of growing
    # both legs by half of that gain.
    assert r.iloc[50] == pytest.approx(0.5 * 0.0003, rel=0.01)


def test_daily_rebalancing_costs_scale_with_price_moves() -> None:
    d = _asset()
    d["perp"] = d["spot"]
    d["funding"] = 0.0
    r = cc.sleeve_returns(d["spot"], d["perp"], d["funding"], pd.Series(True, index=d.index))
    assert (r.iloc[2:] < 0).all()  # no funding: only rebalancing fees remain


def test_flat_when_inactive() -> None:
    d = _asset()
    r = cc.sleeve_returns(d["spot"], d["perp"], d["funding"], pd.Series(False, index=d.index))
    assert (r == 0).all()


def test_positive_rule_uses_the_previous_days() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    funding = pd.Series([-1, -1, -1, -1, -1, -1, -1, 1, 1, 1], index=idx, dtype=float) * 1e-4
    active = cc.active_days(funding, "positive")
    assert not active.iloc[:8].any()  # trailing 7-day mean still negative, and lagged a day
    assert cc.active_days(funding, "always").all()


def test_run_study_rejects_locked_data() -> None:
    d = _asset(n=1700)
    cash = pd.Series(0.0, index=d.index)
    with pytest.raises(ValueError, match="locked"):
        cc.run_study({"BTC": d, "ETH": d}, cash)


def test_run_study_reports_every_candidate() -> None:
    d = _asset()
    d = d.loc[:"2023-12-31"]
    cash = pd.Series(0.00005, index=d.index)
    out = cc.run_study({"BTC": d, "ETH": _asset(seed=1).loc[:"2023-12-31"]}, cash)
    assert set(out["results"]) == set(cc.CANDIDATES)
    for r in out["results"].values():
        assert r["validation"]["start"] >= "2022-01-01"
        assert len(r["checks"]) == 3
