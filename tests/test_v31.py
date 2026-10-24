"""v31 checks: the position sessions built from daily bars, the forced liquidation at the open and within the
session, the closed positions' later sessions dropping out, and no change when the rule never binds."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v31", "run_v31_under_test")


def _D(O, H, L, C) -> dict:
    return {k: np.array(v, float)[:, None] for k, v in (("O", O), ("H", H), ("L", L), ("C", C))}


def _short(r, w, t=0, i0=1, cost=0.0) -> dict:
    """A short entered at the close of session t; ``r`` the account's daily returns on the entry, cost on the first."""
    rr = list(r)
    raw0 = rr[0]
    rr[0] -= cost
    return {"i0": i0, "t": t, "j": 0, "side": -1, "w": w, "r": rr, "raw0": raw0, "loc": 0.0}


def test_no_binding_rule_changes_nothing(V) -> None:
    D = _D([10, 10, 11, 10], [10, 11, 12, 11], [10, 9, 10, 9], [10, 10.5, 11, 10])
    it = _short([-0.05, -0.05, 0.1], 0.2, cost=0.01)
    P = V.position_days([it], D, 4)
    assert np.allclose(np.bincount(P["day"].astype(int), P["cl"], minlength=4), [0, 0.2 * -0.06, 0.2 * -0.05,
                                                                                   0.2 * 0.1])
    out, days = V.liquidate(P, 4, 0.15)
    assert days == [] and np.allclose(out, np.bincount(P["day"].astype(int), P["cl"], minlength=4))


def test_liquidation_within_the_session_and_later_sessions_drop(V) -> None:
    D = _D([10, 10, 30, 30], [10, 10, 31, 40], [10, 10, 29, 29], [10, 10, 30, 35])
    it = _short([0.0, -2.0, -0.5], 0.4)
    out, days = V.liquidate(V.position_days([it], D, 4), 4, 0.15)
    lam = (0.15 * 1.2 - 0.2) / (-0.04 - 0.15 * 0.04)
    assert days == [2] and out[2] == pytest.approx(-0.8 - lam * 0.04) and out[3] == 0.0
    eq, mv = 1 + out[2], 1.2 + lam * 0.04
    assert eq / mv == pytest.approx(0.15)


def test_liquidation_at_the_open(V) -> None:
    D = _D([10, 10, 30], [10, 10, 31], [10, 10, 29], [10, 10, 30])
    it = _short([0.0, -2.0], 0.5)
    out, days = V.liquidate(V.position_days([it], D, 3), 3, 0.15)
    assert days == [2] and out[2] == pytest.approx(-1.0)


def test_exit_within_the_session_uses_the_exit_price(V) -> None:
    D = _D([10, 10, 12], [10, 10, 30], [10, 10, 11], [10, 10, 25])
    it = _short([0.0, -0.3], 1.0)  # stopped at 13 although the high is 30
    P = V.position_days([it], D, 3)
    assert P["a"][1] == pytest.approx(-0.2) and P["b"][1] == pytest.approx(-0.1) and P["m1"][1] == pytest.approx(0.1)
    out, days = V.liquidate(P, 3, 0.15)
    assert days == [] and out[2] == pytest.approx(-0.3)
