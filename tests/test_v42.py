"""v42 checks: the grid, the long signals (known at the entry close), the per-session cap, the gate's lag, the
historical path measures and the two pass tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v42", "run_v42_under_test")


def test_grid(V) -> None:
    assert len(V.VARIANTS) == 19 and V.VARIANTS[V.BASE_ID] == "base"
    assert V.name(V.VARIANTS.index(("follow", "runners", 0.10))) == "follow runners 10%"


def _D(T: int = 40, N: int = 3) -> dict:
    C = np.full((T, N), 10.0)
    H, L = C * 1.02, C * 0.98
    DV = np.full((T, N), 1e6)
    C[30:, 0] = 11.0  # column 0: +10% at session 30, a 20-session high, closing at the high
    H[30, 0], L[30, 0] = 11.0, 10.0
    DV[30, 0] = 3e6
    C[25:30, 1] = [11, 12, 13, 14, 15]  # column 1: +50% in 5 sessions by session 29 ... and on at 30
    C[30:, 1] = 17.0
    H[25:31, 1], L[25:31, 1] = C[25:31, 1], C[25:31, 1] * 0.9
    return {"C": C, "H": H, "L": L, "O": C.copy(), "P": C.copy(), "DV": DV, "valid": np.ones((T, N), bool),
            "dates": pd.bdate_range("2020-01-01", periods=T)}


def test_signals(V) -> None:
    D = _D()
    b = V.signals(D, "breakout")
    assert b[30, 0] and not b[31, 0] and not b[:30, 0].any()
    u = V.signals(D, "burst")
    assert u[30, 0] and not u[31, 0]
    f = V.signals(D, "follow")
    assert f[30, 1] and f[29, 1] and not f[30, 0]  # 17 / 11 and 15 / 10
    D2 = {**D, "C": D["C"].copy()}
    D2["C"][31:, 0] = 1e3  # a later jump does not change the signal at 30
    assert V.signals(D2, "breakout")[30, 0]
    D3 = {**D, "P": D["P"] * 0.05}
    assert not V.signals(D3, "breakout").any()  # under $1


def test_specs_cap_and_gate(V, monkeypatch) -> None:
    D = _D(N=5)
    for j in range(5):
        D["C"][30:, j] = 10.0 * (1.1 + 0.01 * j)
        D["H"][30, j], D["L"][30, j] = D["C"][30, j], 10.0
        D["DV"][30, j] = 3e6
    sp = V.specs(D, "breakout", None)
    assert len(sp) == V.PER_DAY and [s.j for s in sp] == [4, 3, 2]
    assert all(s.side == 1 and s.kind == "close" and s.rule == "ma10" and s.prio < 1e-5 for s in sp)
    gate = np.zeros(40, bool)
    assert V.specs(D, "breakout", gate) == []
    m = np.r_[np.linspace(10, 0, 300), np.ones(10) * 50.0]
    monkeypatch.setattr(V.R40, "market", lambda D, X: {"runners": m})
    g = V.gate_flag({}, {})
    assert not g[300] and g[301]  # the flag at the session before


def test_history_and_verdict(V) -> None:
    r = np.r_[np.zeros(30), -0.5, np.zeros(30)]
    h = V.history(r)
    assert h["worst21"] == pytest.approx(-0.5) and h["maxdd"] == pytest.approx(-0.5)
    st = {"med": 100.0, "p_ruin": 0.01}
    res = {t: {"base": {"all": dict(st), "late": dict(st)}, "wf": {"all": dict(st), "late": dict(st)}}
           for t in V.TASKS}
    hist = {"base": {"worst21": -0.4, "maxdd": -0.6}, "wf": {"worst21": -0.3, "maxdd": -0.5}}
    assert V.improved(res, hist) == {"growth": False, "hedge": True, "any": True}
    hist["wf"]["maxdd"] = -0.58
    assert not V.improved(res, hist)["hedge"]
    res["base"]["wf"]["all"]["med"] = 120.0
    res["base"]["wf"]["late"]["med"] = 120.0
    assert V.improved(res, hist)["growth"]
