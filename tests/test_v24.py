"""v24 checks: the fast indicators against pandas, the grid, no look-ahead in any family's entry, the daily facts
from earlier sessions only, the special exits, trades and placebos on a synthetic store, the movers' selection."""
from __future__ import annotations

import importlib.util
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v22_intra as v22i
from aurora.research import v24_fast as fast
from aurora.research import v24_long1m as v24
from aurora.research import v24_patterns as pat

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def _day(rng: np.random.Generator, n: int = 390, start: float = 5.0, halt: bool = False) -> tuple:
    """A synthetic session: a random walk with jumps, runs and volume bursts, sometimes a pause of six minutes
    (with ``halt``: always, after a 5-bar move of 12% up or down)."""
    r = rng.normal(0, 0.004, n) + rng.choice([0, 0.03, -0.03], n, p=[0.96, 0.02, 0.02])
    drift = rng.choice([-0.0015, 0.0, 0.0015, 0.004])
    k = int(rng.integers(30, 300))
    if halt:
        r[k - 5:k] = rng.choice([0.025, -0.025])
    c = start * np.exp(np.cumsum(r + drift))
    o = np.r_[start * (1 + rng.normal(0, 0.01)), c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
    v = rng.lognormal(8, 1, n) * np.where(rng.random(n) < 0.03, 8, 1)
    m = np.arange(n)
    if halt or rng.random() < 0.5:
        m = np.r_[m[:k], m[k:] + 6]
        keep = m < 390
        m, o, h, lo, c, v = m[keep], o[keep], h[keep], lo[keep], c[keep], v[keep]
    return m.astype(np.int16), o, h, lo, c, v, (h + lo + c) / 3


def _cd(b: tuple, rng: np.random.Generator) -> dict:
    o0 = float(b[1][0])
    pc = o0 / (1 + rng.choice([0.08, 0.2, -0.06, 0.0, 0.5]))
    cd = {"date": pd.Timestamp("2021-03-01"), "t": 10, "j": 0, "symbol": "X", "open": o0, "pc": pc, "gap": o0 / pc - 1,
          "pmv": 1e6, "pmh": o0 * 1.03, "pml": o0 * 0.97, "pdh": pc * 1.05, "pdl": pc * 0.95, "h5": pc * 1.2,
          "l5": pc * 0.8, "so": 2e7, "day1": 0.6, "day1_loc": 0.9, "atr14": pc * 0.08, "rv5": 4.0, "rvrank": 3.0,
          "ret60": 0.4, "red2": 1.0}
    cd.update({k: pc * x for k, x in zip(v24.DAILY, (1.02, 1.1, 1.3, 0.9, 0.8, 0.98, 0.95, 0.9))})
    return cd


def _perturb(b: tuple, j: int, rng: np.random.Generator) -> tuple:
    m, o, h, lo, c, v, vw = (np.array(x, copy=True) for x in b)
    k = np.arange(len(c)) > j
    f = rng.uniform(0.6, 1.5, k.sum())
    o[k], c[k] = o[k] * f, c[k] * f[::-1]
    h[k], lo[k] = np.maximum(o[k], c[k]) * 1.02, np.minimum(o[k], c[k]) * 0.98
    v[k] = v[k] * rng.uniform(0.1, 10, k.sum())
    vw[k] = (h[k] + lo[k] + c[k]) / 3
    return m, o, h, lo, c, v, vw


def test_fast_filters_match_pandas() -> None:
    x = np.random.default_rng(0).normal(size=300).cumsum() + 50
    s = pd.Series(x)
    assert np.allclose(fast.ema(x, 9), s.ewm(span=9, adjust=False).mean())
    assert np.allclose(fast.wilder(x, 14), s.ewm(alpha=1 / 14, adjust=False).mean())
    for w in (2, 5, 20, 55):
        assert np.allclose(fast.rmax(x, w), s.rolling(w, min_periods=1).max())
        assert np.allclose(fast.rmin(x, w), s.rolling(w, min_periods=1).min())
        assert np.allclose(fast.rmean(x, w), s.rolling(w).mean(), equal_nan=True)
        assert np.allclose(fast.rstd(x, w), s.rolling(w).std(), equal_nan=True)
    assert np.allclose(fast.rsi(x, 7), v22i._rsi(x, 7))
    v = np.random.default_rng(1).lognormal(8, 1, 300)
    ref = v / pd.Series(v).rolling(30, min_periods=10).mean().shift(1).to_numpy()
    assert np.allclose(fast.rv(v), ref, equal_nan=True)


def test_grid_is_long_only_and_counted() -> None:
    sizes = {k: len(core.grid(d)) for k, d in v24.INTRA_DIMS.items()}
    assert len(sizes) == 28 and len({k.split("_")[0] for k in sizes}) == 28  # family_of: the prefix
    assert sum(sizes.values()) == 208032
    for k, d in v24.INTRA_DIMS.items():
        assert d.get("side", ("long",)) == ("long",) and d.get("cside", ("long",)) == ("long",)
    from aurora.research import v23_ta1m as v23
    for k, fam in v24.V23L.items():
        for g in core.grid(v24.INTRA_DIMS[k])[:200]:
            assert v23.side_of(fam, g) == 1


@pytest.mark.parametrize("family", sorted(v24.INTRA_DIMS))
def test_entries_do_not_look_ahead(family: str) -> None:
    rng = np.random.default_rng(abs(hash(family)) % 2 ** 32)
    cfgs = core.grid(v24.INTRA_DIMS[family])
    found = 0
    for ci in rng.choice(len(cfgs), size=min(40, len(cfgs)), replace=False):
        g = cfgs[int(ci)]
        for _ in range(8):
            b = _day(rng, halt=family == "HR_HALT")
            cd = _cd(b, rng)
            lv = v24.levels(cd)
            line = vi.vwap(b[4], b[5], b[6])
            j, e, ref, tgt = v24.signal(family, g, b, line, cd, lv)
            if j < 0:
                continue
            found += 1
            b2 = _perturb(b, j, rng)
            j2, e2, ref2, tgt2 = v24.signal(family, g, b2, vi.vwap(b2[4], b2[5], b2[6]), cd, lv)
            assert (j2, e2) == (j, pytest.approx(e)), (family, g)
            assert np.isclose(ref2, ref, equal_nan=True) and np.isclose(tgt2, tgt, equal_nan=True), (family, g)
    assert found > 0, family


def _daily(T: int = 300, N: int = 3) -> dict:
    rng = np.random.default_rng(5)
    C = 5 * np.exp(np.cumsum(rng.normal(0, 0.03, (T, N)), axis=0))
    O = C * (1 + rng.normal(0, 0.01, (T, N)))
    H, L = np.maximum(O, C) * 1.02, np.minimum(O, C) * 0.98
    return {"dates": pd.bdate_range("2019-01-01", periods=T), "O": O, "H": H, "L": L, "C": C, "F": np.ones((T, N)),
            "DV1": np.full((T, N), 5e6), "new": np.zeros((T, N), bool), "cols": np.array(["A", "B", "C"])}


def _store(D: dict, rows: list[tuple[int, int]], rng: np.random.Generator) -> vi.Store:
    cands, arrays, off = [], {f: [] for f in vi.FIELDS}, 0
    for t, j in rows:
        b = _day(rng, start=float(D["O"][t, j]))
        pc = float(D["C"][t - 1, j])
        cands.append({"date": D["dates"][t], "symbol": str(D["cols"][j]), "t": t, "j": j, "off": off, "n": len(b[0]),
                      "open": float(b[1][0]), "pc": pc, "gap": float(b[1][0]) / pc - 1, "pmv": 1e6,
                      "pmh": float(b[1][0]) * 1.02, "pml30": float(b[1][0]) * 0.98, "so": 2e7,
                      "s_gap_up": True, "s_runner": True, "s_gap_down": False, "s_day2": True})
        for f, x in zip(vi.FIELDS, b):
            arrays[f].append(x)
        off += len(b[0])
    return vi.Store(pd.DataFrame(cands), {f: np.concatenate(x) for f, x in arrays.items()})


def test_daily_facts_use_earlier_sessions_only() -> None:
    D = _daily()
    st = _store(D, [(260, 0), (280, 1)], np.random.default_rng(0))
    v24.prepare({"event": st}, D)
    before = st.cands[list(v24.DAILY) + ["pdh", "atr14", "day1", "ret60"]].to_numpy(float).copy()
    for X in ("H", "L", "C", "O"):
        D[X][260:, 0] *= 3.0  # the day itself and later sessions
        D[X][280:, 1] *= 3.0
    st2 = _store(D, [(260, 0), (280, 1)], np.random.default_rng(0))
    v24.prepare({"event": st2}, D)
    assert np.allclose(st2.cands[list(v24.DAILY) + ["pdh", "atr14", "day1", "ret60"]].to_numpy(float), before,
                       equal_nan=True)
    assert st.cands.loc[0, "h252"] == pytest.approx(D["H"][8:260, 0].max())


def test_break_even_and_scale_exits() -> None:
    c = [10.0] * 3 + [10.5, 11.1, 10.6, 9.95, 9.9, 9.9, 9.9]
    o = np.r_[c[0], c[:-1]]
    b = (np.arange(10, dtype=np.int16), o, np.maximum(o, c) + 0.01, np.minimum(o, c) - 0.01, np.array(c),
         np.full(10, 1e3), np.array(c))
    cd = {"date": pd.Timestamp("2021-01-04"), "t": 5, "j": 0, "symbol": "X", "open": 10.0, "pmv": 1e6, "so": 2e7,
          "pc": 9.5}
    v19.set_costs("r4", 0.0, None)
    r = v24.special({}, cd, b, b[4], 3, 10.5, 9.95, "be1r", 0.0)  # 1R = 11.05 at bar 4, back to 10.5 at bar 6
    assert r["rets"][0] == pytest.approx(0.0) and r["xmin"] == 6
    r = v24.special({}, cd, b, b[4], 3, 10.5, 9.95, "tstop15", 0.0)
    assert r["rets"][0] == pytest.approx(9.95 / 10.5 - 1) and r["xmin"] == 6  # the stop before 15 minutes
    r = v24.special({}, cd, b, b[4], 3, 10.5, 9.0, "scale", 0.0)  # 2R (13.5) not reached: both halves at the close
    assert r["rets"][0] == pytest.approx(9.9 / 10.5 - 1)


def test_trades_and_placebos_on_a_synthetic_store() -> None:
    D = _daily()
    rng = np.random.default_rng(3)
    rows = [(t, j) for t in range(250, 290) for j in range(3)]
    stores = {"event": _store(D, rows, rng), "liquid": _store(D, rows[::2], rng), "mover": _store(D, rows[1::2], rng)}
    for nm in ("liquid", "mover"):
        c = stores[nm].cands
        c["pml"], c["pdh"], c["pdl"], c["h5"], c["l5"] = c["pml30"], np.nan, np.nan, np.nan, np.nan
    v24.prepare(stores, D)
    assert np.isfinite(stores["liquid"].cands["rvrank"]).all()
    v24._IDX.clear()
    v19.set_costs("r4", 0.25, None)
    n_tr = 0
    for fam in ("SP_INPLAY", "IX_IND", "MD_MORNDIP", "SR_LONG", "LR_ORB", "GF_GAPFILL"):
        for g in core.grid(v24.INTRA_DIMS[fam])[::97][:12]:
            tr = v24.trades(stores, D, fam, g)
            assert list(tr.columns) == v19.COLS and (tr["side"] == 1).all() if len(tr) else True
            n_tr += len(tr)
            if len(tr):
                pl = v24.placebo(stores, v24.pool_by_day(stores, g), D, fam, g, tr, np.random.default_rng(0))
                assert len(pl) <= len(tr)
    assert n_tr > 0


def test_halt_resume_entry() -> None:
    c = list(np.linspace(5.0, 5.0, 20)) + [5.1, 5.3, 5.5, 5.7, 5.9] + [6.0] * 20
    b = list(_bars_simple(c))
    m = np.r_[np.arange(25), np.arange(25, 45) + 6].astype(np.int16)  # six minutes without bars after bar 24
    b[0] = m
    b[1] = b[1].copy()
    b[1][25] = 6.05  # reopens above the last price
    b[2][25] = max(b[2][25], 6.05)
    j, e, ref, _ = pat.halt({"dir": "up", "move": 0.08, "entry": "resume"}, tuple(b), np.ones(len(c), bool))
    assert j == 25 and e == pytest.approx(6.05) and ref < 5.6


def _bars_simple(c: list[float]) -> tuple:
    c = np.array(c, float)
    o = np.r_[c[0], c[:-1]]
    return (np.arange(len(c), dtype=np.int16), o, np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999, c,
            np.full(len(c), 1e3), c)


def test_mover_selection_leaves_out_the_liquid_set() -> None:
    m = _script("run_v24_data", "run_v24_data_under_test")
    dates = pd.bdate_range(core.DESIGN_START - pd.Timedelta(days=10), periods=30)
    rng = np.random.default_rng(0)
    T, N = len(dates), 300
    C = np.full((T, N), 5.0)
    O = C * (1 + rng.normal(0, 0.05, (T, N)))
    DV = np.full((T, N), 2e6)
    DV[:, :120] = 5e7
    D = {"dates": dates, "O": O, "C": C, "P1": C, "DV1": DV, "valid1": np.ones((T, N), bool), "cols": np.arange(N)}
    sets = m.mover_sets(D)
    t = max(sets)
    assert not set(sets[t]) & set(m.D23.liquid_sets(D)[t])
    assert np.abs(O[t, sets[t]] / C[t - 1, sets[t]] - 1).min() >= 0.04 and len(sets[t]) <= 100


def test_worker_pool_can_pickle_the_patched_runner() -> None:
    module = _script("run_v24", "run_v24_under_test")
    assert pickle.loads(pickle.dumps(module.R22._work)) is module.R22._work
    assert module.R22.configs is module.configs and len(module.configs()) == 208032
