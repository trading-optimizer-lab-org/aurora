"""v49 checks: the books and sets as pre-registered, the extra borrow cost, the volume cap, the failed locates and the
2:1 rule in the account."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def M():
    from test_v24 import _script
    return _script("run_v49", "run_v49_under_test")


def test_books_and_sets(M) -> None:
    assert [b[2] for b in M.BOOKS] == [0.40, 0.30, 0.25, 0.20, 0.15] and all(b[:2] == (0.20, 0.40) for b in M.BOOKS)
    assert all(b[3] == 5 for b in M.BOOKS) and M.MAIN == "TZC" and M.SETS["TZA"] is None
    assert M.SETS["TZC"] == {"borrow": 1.0, "margin": 0.09} and M.SETS["TZC-M0"]["margin"] == 0.0
    assert M.SETS["TZC-B2"]["borrow"] == 2.0 and M.UNAVAIL == {1: 0.10, 2: 0.50} and M.VOL_SHARE == 0.10


def test_extra_cost(M) -> None:
    # Thursday close to Monday: 1 session night charged by the model, 4 calendar days
    assert M.extra_cost(100.0, 1, 4, 1.0, 0.0) == pytest.approx(3 / 360)
    assert M.extra_cost(100.0, 1, 4, 1.0, 0.09) == pytest.approx((4 * 1.09 - 1) / 360)
    assert M.extra_cost(100.0, 2, 2, 2.0, 0.0) == pytest.approx(2 / 360)
    assert M.extra_cost(100.0, 0, 0, 1.0, 0.09) == 0.0


def test_vol_scale_and_locates(M) -> None:
    assert M.vol_scale(1000, 50_000) == 1.0 and M.vol_scale(1000, 5_000) == pytest.approx(0.5)
    assert M.vol_scale(1000, 0.0) == 0.0
    its = [{"sym": f"S{k}", "t": k, "tier": tier} for k in range(4000) for tier in (0, 1, 2)]
    share = {tier: np.mean([M.unavailable(it) for it in its if it["tier"] == tier]) for tier in (0, 1, 2)}
    assert share[0] == 0 and 0.08 < share[1] < 0.12 and 0.47 < share[2] < 0.53


def _setup(M, monkeypatch, vw: float) -> tuple[list, list]:
    R43 = M.R43
    B = {k: np.full(960, 1.0) for k in ("o", "h", "l", "c", "vw")}
    B["vw"][:] = vw
    B["o"][:] = vw
    B["v"] = np.full(960, 1e9)
    monkeypatch.setattr(R43, "timeline", lambda u, j: B)
    monkeypatch.setitem(R43._G, "D", {"C": np.ones((3, 1))})
    monkeypatch.setitem(R43._G, "count", {})
    G = np.zeros(960)
    G[M.K1545:] = -0.01
    G[R43.LAST] = -0.02
    rec = {"u": [0, 1], "G": [G, G], "Q": [np.ones(960), np.ones(960)], "M": [np.ones(960), np.ones(960)],
           "es": 0, "kind": "open", "t": 0, "j": 0, "e": 1.0, "n": 100.0, "cost": 0.0}
    return [{"w": 3.0, "_rec": 0}], [rec]


def test_two_to_one_rule(M, monkeypatch) -> None:
    taken, recs = _setup(M, monkeypatch, 1.0)
    off = M.liquidate(taken, recs, 3, "next_vwap", None, False)
    assert off[:2] == pytest.approx([-0.06, -0.06])
    on = M.liquidate(taken, recs, 3, "next_vwap", None, True)
    # 3x the 0.97 equity at 15:45 -> f covered at 15:45 (G -0.01), the rest to the close (-0.02); then reduced
    f = 1 - 2 * 0.97 / 3
    assert on[0] == pytest.approx(3 * ((1 - f) * -0.02 + f * -0.01))
    assert on[1] == pytest.approx(3 * (1 - f) * -0.02) and M.R43._G["count"]["v49_forced_2to1"] == 1
    taken, recs = _setup(M, monkeypatch, 1.05)
    on = M.liquidate(taken, recs, 3, "next_vwap", None, True)
    assert on[0] == pytest.approx(3 * ((1 - f) * -0.02 + f * (-0.01 - 0.05)))
