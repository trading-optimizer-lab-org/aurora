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


def test_signal_is_traded_at_the_close_it_is_decided() -> None:
    d = _asset()
    d["spot"] = 100.0
    d["perp"] = 100.0
    d["funding"] = 0.0
    d.iloc[10:, d.columns.get_loc("funding")] = 1e-4
    active = cc.active_days(d["funding"], "positive")
    assert not active.iloc[:10].any() and active.iloc[10]
    r = cc.sleeve_returns(d["spot"], d["perp"], d["funding"], active)
    assert (r.iloc[:10] == 0).all()
    assert r.iloc[10] < 0  # entry fees at the close of the first positive day
    assert r.iloc[11] > 0  # funding earned the next day


def test_two_asset_candidate_lets_sleeves_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="D")
    fixed = {100.0: pd.Series([0.0, 0.10, 0.10], index=idx), 200.0: pd.Series(0.0, index=idx)}
    monkeypatch.setattr(cc, "sleeve_returns", lambda spot, *a: fixed[spot.iloc[0]])
    data = {a: pd.DataFrame({"spot": px, "perp": px, "funding": 0.0}, index=idx)
            for a, px in (("BTC", 100.0), ("ETH", 200.0))}
    r = cc.run_one(data, "carry_btc_eth_positive")
    assert r.iloc[1] == pytest.approx(0.05)
    # Day 3: BTC sleeve's 10% on its drifted weight 1.1 / 2.1, no reset to 50/50.
    assert r.iloc[2] == pytest.approx(0.10 * 1.1 / 2.1)
