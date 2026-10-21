"""v25 checks: the short grid, no look-ahead in any family's entry, the mirror (a gap-up fill short, a short opening
range break), the short special exits, trades and placebos on a synthetic store, the patched runner."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v23_ta1m as v23
from aurora.research import v24_long1m as v24
from aurora.research import v25_short1m as v25
from test_v24 import _bars_simple, _cd, _daily, _day, _perturb, _script, _store


def _cd25(b: tuple, rng: np.random.Generator) -> dict:
    cd = _cd(b, rng)
    cd.update({"l252": cd["pc"] * 0.6, "green2": float(rng.random() < 0.5)})
    if rng.random() < 0.5:  # a daily downtrend near its lows (the mirror of v24's uptrend contexts)
        pc = cd["pc"]
        cd.update({"sma20d": pc * 1.03, "sma50d": pc * 1.08, "ret60": -0.4, "l20": pc * 0.97})
    return cd


def test_grid_is_short_only_and_counted() -> None:
    sizes = {k: len(core.grid(d)) for k, d in v25.INTRA_DIMS.items()}
    assert len(sizes) == 28 and len({k.split("_")[0] for k in sizes}) == 28
    assert sum(sizes.values()) == 213000
    for k, fam in v25.V23S.items():
        for g in core.grid(v25.INTRA_DIMS[k])[:300]:
            assert v23.side_of(fam, g) == -1
    for k in ("SR_SHORT", "DD_DAILY"):
        assert all(v23.SETUP_SIDE[s] == -1 for s in v25.INTRA_DIMS[k]["setup"])


@pytest.mark.parametrize("family", sorted(v25.INTRA_DIMS))
def test_entries_do_not_look_ahead(family: str) -> None:
    rng = np.random.default_rng(abs(hash(family + "25")) % 2 ** 32)
    cfgs = core.grid(v25.INTRA_DIMS[family])
    found = 0
    for ci in rng.choice(len(cfgs), size=min(40, len(cfgs)), replace=False):
        g = cfgs[int(ci)]
        for _ in range(8):
            b = _day(rng, halt=family == "HS_HALT")
            cd = _cd25(b, rng)
            lv = v25.levels(cd)
            line = vi.vwap(b[4], b[5], b[6])
            j, e, ref, tgt, _ = v25.signal(family, g, b, line, cd, lv)
            if j < 0:
                continue
            found += 1
            assert not np.isfinite(ref) or ref > e * 0.999, (family, g)  # a short's stop reference is above
            assert not np.isfinite(tgt) or tgt > 0, (family, g)
            b2 = _perturb(b, j, rng)
            j2, e2, ref2, tgt2, _ = v25.signal(family, g, b2, vi.vwap(b2[4], b2[5], b2[6]), cd, lv)
            assert (j2, e2) == (j, pytest.approx(e)), (family, g)
            assert np.isclose(ref2, ref, equal_nan=True) and np.isclose(tgt2, tgt, equal_nan=True), (family, g)
    assert found > 0, family


def test_gap_up_fill_short_breaks_the_opening_range_low() -> None:
    c = [10.6] * 3 + [10.8, 10.7, 10.65, 10.6, 10.5, 10.3, 10.2] + [10.1] * 30
    b = _bars_simple(c)
    cd = {"open": 10.6, "pc": 10.0, "gap": 0.06, "pmh": 10.9, "pml": 10.4, "pdh": 10.2, "pdl": 9.8, "h5": 10.5,
          "l5": 9.5, "atr14": 0.5, "rv5": 2.0, "rvrank": 9.0, "ret60": 0.1, "day1": 0.02, "day1_loc": 0.5, "red2": 0.0,
          "green2": 0.0, "l252": 6.0, "date": pd.Timestamp("2021-01-04"), "t": 5, "j": 0, "symbol": "X", "pmv": 1e6,
          "so": 2e7}
    cd.update({k: 10.0 for k in v24.DAILY})
    v19.set_costs("r4", 0.0, None)
    g = {"gap": -0.04, "trig": "orh5", "stop": "lod", "exit": "fill", "scope": "liquid", "band": "8-20"}
    line = vi.vwap(b[4], b[5], b[6])
    j, e, ref, _, mirror = v25.signal("GU_GAPFILL", g, b, line, cd, v25.levels(cd))
    orl = float(b[3][:5].min())  # the first five minutes' low (bars 0-4)
    assert j == int(np.flatnonzero(b[3][5:] < orl)[0]) + 5 and e == pytest.approx(orl)
    stop = v25.stop_of("GU_GAPFILL", g, b, j, e, ref, np.nan, mirror)
    assert stop == pytest.approx(float(b[2][:j].max()))  # the mirrored low of day: the real high of day so far
    r = v25.make_trade({}, "GU_GAPFILL", g, cd, b, line, v25.levels(cd), j, e, stop, np.nan, 0.0)
    assert r["side"] == -1 and r["rets"][0] == pytest.approx(-(c[-1] - e) / e)  # 10.0 never reached: out at the close


def test_short_break_even_exit() -> None:
    c = [10.0] * 3 + [9.5, 8.9, 9.4, 10.05, 10.1, 10.1, 10.1]
    o = np.r_[c[0], c[:-1]]
    b = (np.arange(10, dtype=np.int16), o, np.maximum(o, c) + 0.01, np.minimum(o, c) - 0.01, np.array(c),
         np.full(10, 1e3), np.array(c))
    cd = {"date": pd.Timestamp("2021-01-04"), "t": 5, "j": 0, "symbol": "X", "open": 10.0, "pmv": 1e6, "so": 2e7,
          "pc": 10.5}
    v19.set_costs("r4", 0.0, None)
    r = v24.special({}, cd, b, b[4], 3, 9.5, 10.05, "be1r", 0.0, side=-1)  # 1R = 8.95 at bar 4, back to 9.5 at 6
    assert r["side"] == -1 and r["rets"][0] == pytest.approx(0.0) and r["xmin"] == 6
    r = v24.special({}, cd, b, b[4], 3, 9.5, 10.05, "tstop15", 0.0, side=-1)
    assert r["rets"][0] == pytest.approx(-(10.05 / 9.5 - 1))  # the stop at bar 6, before 15 minutes


def test_trades_and_placebos_on_a_synthetic_store() -> None:
    D = _daily()
    rng = np.random.default_rng(4)
    rows = [(t, j) for t in range(250, 290) for j in range(3)]
    stores = {"event": _store(D, rows, rng), "liquid": _store(D, rows[::2], rng), "mover": _store(D, rows[1::2], rng)}
    for nm in ("liquid", "mover"):
        c = stores[nm].cands
        c["pml"], c["pdh"], c["pdl"], c["h5"], c["l5"] = c["pml30"], np.nan, np.nan, np.nan, np.nan
    v25.prepare(stores, D)
    assert np.isfinite(stores["event"].cands["l252"]).all()
    v24._IDX.clear()
    v19.set_costs("r4", 0.25, None)
    n_tr = 0
    for fam in ("SB_INPLAY", "IS_IND", "MP_MORNPOP", "SR_SHORT", "XR_ORB", "GU_GAPFILL", "BT_BLOWOFF", "NL_NOISE"):
        for g in core.grid(v25.INTRA_DIMS[fam])[::89][:12]:
            tr = v25.trades(stores, D, fam, g)
            assert list(tr.columns) == v19.COLS and ((tr["side"] == -1).all() if len(tr) else True)
            assert ((tr["stop"] > tr["entry"]).all() if len(tr) else True)
            n_tr += len(tr)
            if len(tr):
                pl = v25.placebo(stores, v24.pool_by_day(stores, g), D, fam, g, tr, np.random.default_rng(0))
                assert len(pl) <= len(tr) and ((pl["side"] == -1).all() if len(pl) else True)
    assert n_tr > 0


def test_worker_pool_can_pickle_the_patched_runner() -> None:
    import pickle

    module = _script("run_v25", "run_v25_under_test")
    assert pickle.loads(pickle.dumps(module.R22._work)) is module.R22._work
    assert module.R22.configs is module.configs and len(module.configs()) == 213000
    assert module.configs()[:3] != _script("run_v24", "run_v24_again").configs()[:3]
