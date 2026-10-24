"""v30 checks: the two account rules (freeze under $500, one reserve deposit that pays a debt first, losses beyond
the equity kept), total wealth with the unused reserve, the statistics, the bootstrap length, the choice and the
verdict."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v30", "run_v30_under_test")


def _R(V, returns: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """The same returns at every equity level; one path walking through them in order."""
    r = np.array(returns, float)
    return np.tile(r, (len(V.LEVELS), 1)), np.arange(len(r))[None, :]


def test_a_freezes_and_keeps_a_debt(V) -> None:
    R, idx = _R(V, [-0.95, 0.5, 0.5])
    w, used = V.accounts(R, idx, 0.0, 5_000.0, 0.0)
    assert w[0] == pytest.approx(250.0) and not used[0]  # frozen at $250: the later gains do not count
    R, idx = _R(V, [-1.5, 0.5])
    w, _ = V.accounts(R, idx, 0.0, 5_000.0, 0.0)
    assert w[0] == pytest.approx(-2_500.0)


def test_b_deposits_once_and_pays_the_debt(V) -> None:
    R, idx = _R(V, [-0.9, 0.1])
    w, used = V.accounts(R, idx, 0.0, 2_500.0, 2_500.0)
    assert used[0] and w[0] == pytest.approx((250.0 + 2_500.0) * 1.1)
    R, idx = _R(V, [-1.5, -1.5, 0.5])
    w, used = V.accounts(R, idx, 0.0, 2_500.0, 2_500.0)
    assert used[0] and w[0] == pytest.approx((-1_250.0 + 2_500.0) * -0.5)  # second loss freezes it with a debt
    R, idx = _R(V, [-2.0])
    w, _ = V.accounts(R, idx, 0.0, 2_500.0, 2_500.0)
    assert w[0] == pytest.approx(-2_500.0 + 2_500.0)  # the deposit only pays the debt: frozen at $0
    R, idx = _R(V, [0.2, 0.2])
    w, used = V.accounts(R, idx, 0.0, 2_500.0, 2_500.0)
    assert not used[0] and w[0] == pytest.approx(2_500.0 * 1.44 + 2_500.0)  # the unused reserve counts


def test_fixed_costs_and_stats(V) -> None:
    R, idx = _R(V, [0.0] * 21)
    w, _ = V.accounts(R, idx, 12.0, 5_000.0, 0.0)
    assert w[0] == pytest.approx(5_000.0 - 21 * 12.0 * 12 / 252)
    w = np.array([-100.0, 400.0, 900.0, 5_000.0, 6_000.0] * 4)
    s = V.wealth_stats(w, np.zeros(len(w), bool))
    assert s["p_debt"] == pytest.approx(0.2) and s["p_1000"] == pytest.approx(0.6) and s["worst"] == -100.0
    assert s["es5"] == -100.0 and s["p_loss"] == pytest.approx(0.6)


def test_draws_and_choice(V) -> None:
    ix = V.draws(500, 756, 30, paths=7)
    assert ix.shape == (7, 756) and ix.min() >= 0 and ix.max() < 500
    rows = [{**V.A1, "B_1y": {"med": 9.0, "p_1000": 0.2}}, {**V.BMAX, "B_1y": {"med": 9.0, "p_1000": 0.1}},
            {**V.A1, "risk": 0.01, "B_1y": {"med": 5.0, "p_1000": 0.0}}]
    assert V.best(rows, "B")["risk"] == 0.04 and V._same(rows[0], V.A1) and not V._same(rows[2], V.A1)
    v = V.verdict({"med": 10.0, "es5": 500.0, "p_1000": 0.1}, {"med": 12.0, "es5": 400.0, "p_1000": 0.1})
    assert v["higher_median"] and not v["smaller_tail"] and not v["b_better"] and not v["b_avoids_tail"]
