"""Unit tests for the v9 study engines (docs/research/V9_PREREGISTRATION.md)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v9_common as c
from aurora.research import v9_etf as vf
from aurora.research import v9_intraday as vi
from aurora.research import v9_overlay as vo


def test_trial_list_matches_preregistration():
    tri = c.trials()
    names = [t["name"] for t in tri]
    assert len(tri) == 3658 and len(set(names)) == len(names)
    assert sum(t["group"] == "daily" for t in tri) == 2416
    covered = [t["name"] for g in ("daily", "mixed") for k in range(160) for t in c.shard_trials(g, k, 160)]
    assert sorted(covered) == sorted(names)


def test_ls_weights_legs_and_minimum():
    S = np.tile(np.arange(40, dtype=float), (3, 1))
    m = np.ones_like(S, dtype=bool)
    m[2, 25:] = False  # 25 names left: still a book
    W = c.ls_weights(S, m, 0.1)
    assert np.allclose(W[:2].clip(min=0).sum(axis=1), 0.5) and np.allclose(W[:2].clip(max=0).sum(axis=1), -0.5)
    assert W[0, 39] > 0 and W[0, 0] < 0 and W[0, 20] == 0
    m[2, 15:] = False  # 15 names: below the minimum, flat
    assert np.all(c.ls_weights(S, m, 0.1)[2] == 0)


def test_demean_removes_group_means():
    S = np.array([[1.0, 3.0, 10.0, 20.0, 5.0]])
    out = c.demean(S, np.ones_like(S, dtype=bool), np.array([0, 0, 1, 1, -1]))
    assert np.allclose(out[0, :4], [-1, 1, -5, 5]) and np.isnan(out[0, 4])


def test_book_alignment_turnover_and_costs():
    W = np.array([[0.5, -0.5], [0.5, -0.5], [0.0, 0.0]])
    R = np.array([[0.0, 0.0], [0.02, -0.01], [0.03, 0.03]])
    cash = np.zeros(3)
    pnl, tv, sh = c.book(W, R, cash, lag=1)
    assert np.allclose(pnl, [0, 0.015, 0.0]) and np.allclose(tv, [0, 1.0, 0.0]) and np.allclose(sh, [0, 0.5, 0.5])
    s = c.net_series(pnl, tv, sh, cash, (5,), pd.bdate_range("2020-01-01", periods=3))[5]
    assert len(s) == 2 and s.iloc[0] == pytest.approx(0.015 - 5e-4 - 0.01 / 252 * 0.5)


def test_overlap_and_monthly_hold():
    W = np.array([[1.0], [0.0], [0.0]])
    assert np.allclose(c.overlap(W, 2)[:, 0], [1, 0.5, 0])
    out = c.monthly(np.array([[1.0], [3.0]]), np.array([1, 3]), 5, h=2)
    assert np.allclose(out[:, 0], [0, 1, 1, 2, 2])


def test_bar_indices():
    assert vi.bar_ending(1000) == 1 and vi.bar_ending(1600) == 25 and vi.bar_starting(945) == 1
    assert vi.bar_starting(1530) == 24 and vi._exit(4, 60) == 7 and vi._exit(24, "CLOSE") == 25


def test_pre_holiday_sessions():
    dates = pd.DatetimeIndex(["2019-07-02", "2019-07-03", "2019-07-05", "2019-07-08"])
    assert list(vf.pre_holiday(dates)) == [False, True, False, False]


def test_month_brake_goes_to_cash_until_month_end():
    idx = pd.bdate_range("2020-01-27", "2020-02-05")
    r = pd.Series(0.001, index=idx)
    r.loc["2020-01-28"] = -0.02
    cash = pd.Series(0.0001, index=idx)
    out = vo.brake(r, cash, "MONTH", 1.0)
    assert out.loc["2020-01-28"] == pytest.approx(-0.02 - vo.BRAKE_COST)
    assert (out.loc["2020-01-29":"2020-01-31"] == 0.0001).all() and (out.loc["2020-02-03":] == 0.001).all()


def test_risk_parity_ignores_members_not_trading():
    idx = pd.bdate_range("2019-01-01", periods=300)
    rng = np.random.default_rng(0)
    R = pd.DataFrame({"a": rng.normal(0, 0.01, 300), "b": rng.normal(0, 0.02, 300)}, index=idx)
    R.iloc[:200, 1] = np.nan
    r = vo.rp_available(R)
    assert np.allclose(r.iloc[130:200], R["a"].iloc[130:200])
    assert np.isfinite(r).all()
