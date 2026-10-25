"""v32 checks: the paths without a brake are v29's, the brake switches to the half-size book under the drawdown
limit and back, the edge order uses only earlier years, the HOT cap in the joint book, the choice and the verdict."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v32", "run_v32_under_test")


def _R(V, returns: list[float]) -> tuple[np.ndarray, np.ndarray]:
    r = np.array(returns, float)
    return np.tile(r, (len(V.LEVELS), 1)), np.arange(len(r))[None, :]


def test_no_brake_is_v29(V) -> None:
    rng = np.random.default_rng(0)
    Rf = rng.normal(0.002, 0.05, (len(V.LEVELS), 300))
    idx = V.R29.draws(300, paths=50)
    eq, low = V.paths(Rf, Rf * 0, idx, 6.0, None)
    eq29, low29 = V.R29.paths(Rf, idx, 6.0)
    assert np.allclose(eq, eq29) and np.allclose(low, low29)


def test_brake_switches_and_returns(V) -> None:
    Rf, idx = _R(V, [-0.3, 0.1, 0.5, 0.1])
    Rh, _ = _R(V, [-0.15, 0.05, 0.25, 0.05])
    eq, _ = V.paths(Rf, Rh, idx, 0.0, 0.2)
    # 5000 -> 3500 (full); under 4000: half -> 3675, 4593.75; back within 20% of 5000: full -> 5053.125
    assert eq[0] == pytest.approx(5_000 * 0.7 * 1.05 * 1.25 * 1.1)
    eq, _ = V.paths(Rf, Rh, idx, 0.0, 0.3)
    assert eq[0] == pytest.approx(5_000 * 0.7 * 1.1 * 1.5 * 1.1)  # 3500 is exactly 30% under: no switch


def test_edge_uses_earlier_years_only(V, monkeypatch) -> None:
    dates = pd.DatetimeIndex(["2019-06-03", "2020-06-01", "2020-06-02", "2021-06-01"])
    monkeypatch.setitem(V.R14._G, "D", {"dates": dates})
    its = [{"fam": "X", "t": 0, "r": [0.04], "loc": 0.03}, {"fam": "X", "t": 1, "r": [0.10], "loc": 0.01},
           {"fam": "X", "t": 2, "r": [-0.02], "loc": 0.0}, {"fam": "X", "t": 3, "r": [0.0], "loc": 0.02},
           {"fam": "Y", "t": 3, "r": [0.5], "loc": 0.0}]
    out = V.with_edge(its)
    assert out[0]["prio"] == -1.0 and out[4]["prio"] == -1.0  # first year of a family
    assert out[1]["prio"] == pytest.approx(0.04 - 0.01) and out[2]["prio"] == pytest.approx(0.04)
    assert out[3]["prio"] == pytest.approx((0.04 + 0.10 - 0.02) / 3 - 0.02)


def test_hot_cap_in_the_joint_book(V) -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="B")

    def it(j, tier, prio):
        return {"i0": 1, "t": 1, "j": j, "r": [0.01, 0.01], "w": 0.2, "prio": prio, "price": 10.0, "side": -1,
                "nights": 1, "ah": False, "tier": tier, "loc": 0.0, "liq": 1.0}

    its = [it(0, 2, 3.0), it(1, 2, 2.0), it(2, 1, 1.0)]
    _, taken = V.A.joint(its, dates, 2.0, 20, 5, "move", "none", "none", 0.0, 0.0, None, None, hot_cap=0.3)
    assert sorted(t["j"] for t in taken) == [0, 2]
    _, taken = V.A.joint(its, dates, 2.0, 20, 5, "move", "none", "none", 0.0, 0.0, None, None)
    assert len(taken) == 3


def test_choice_levers_and_verdict(V, tmp_path) -> None:
    def row(med, ruin, **kw):
        return {**V.A1, **kw, "med": med, "p_ruin": ruin, "p_half": 0.1, "p10": 1.0, "es5": 1.0}

    rows = [row(10.0, 0.005), row(14.0, 0.02, size=0.4), row(12.0, 0.01, size=0.3, brake=0.2)]
    g = tmp_path / "grid"
    g.mkdir()
    (g / "grid_00.json").write_text(__import__("json").dumps(rows), encoding="utf-8")
    import argparse
    V.cmd_choose(argparse.Namespace(grid=g, out=tmp_path / "ch"))
    ch = __import__("json").loads((tmp_path / "ch" / "choice.json").read_text(encoding="utf-8"))
    assert ch["books"]["choice"]["size"] == 0.3 and ch["a1_row"]["med"] == 10.0
    size40 = next(x for x in ch["levers"] if x["lever"] == "size" and x["value"] == 0.4)
    assert size40["med"] is None  # its only book breaks the ruin rule
    get = {(b, t): {"med": m, "p_ruin": 0.005} for b, t, m in
           [("A1", "base", 10), ("choice", "base", 12), ("A1", "hot5", 8), ("choice", "hot5", 9),
            ("A1", "spread2", 9), ("choice", "spread2", 8)]}
    v = V.verdict(get)
    assert v["beats_base"] and v["beats_hot5"] and not v["beats_spread2"] and not v["raises_median"]
