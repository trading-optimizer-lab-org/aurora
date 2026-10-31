"""v51 engine and pipeline checks on synthetic data: fills, no look-ahead, the grid against brute force, the account,
and every stage end to end on a small synthetic panel."""
from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd
import pytest

from aurora.research import v51_engine as E

NM = E.NM


def _tl(K: int = 3, pc: float = 10.0, seed: int = 0, dense: bool = True) -> E.Timeline:
    """A random walk timeline: K minute days (every minute traded when dense) and ND daily bars that agree."""
    rng = np.random.default_rng(seed)
    px = pc * np.exp(np.cumsum(rng.normal(0, 0.004, (E.ND, NM)), axis=1))
    o = np.c_[px[:, :1], px[:, :-1]]
    c = px
    h, l_ = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998
    v = np.full((E.ND, NM), 100.0)
    if not dense:
        gone = rng.random((E.ND, NM)) < 0.5
        for a in (o, h, l_, c):
            a[gone] = np.nan
        v[gone] = 0
    reg = slice(E.OPEN, E.LAST + 1)
    dO, dC = o[:, E.OPEN], c[:, E.LAST]
    dH, dL = np.nanmax(h[:, reg], 1), np.nanmin(l_[:, reg], 1)
    return E.Timeline(o[:K].copy(), h[:K].copy(), l_[:K].copy(), c[:K].copy(), v[:K].copy(), c[:K].copy(),
                      dO.copy(), dH.copy(), dL.copy(), dC.copy(), pc)


def _set(tl: E.Timeline, d: int, m: int, o: float, h: float, l_: float, c: float) -> None:
    tl.o[d, m], tl.h[d, m], tl.l[d, m], tl.c[d, m], tl.v[d, m] = o, h, l_, c, 100.0


def test_market_and_limit_fills() -> None:
    tl = _tl()
    d, m, px, leg = E.entry(tl, (0, "mkt", 0, E.M1555), -1)
    assert (d, m, px, leg) == (0, E.M1555, tl.o[0, E.M1555], E.L_CLOSE)
    tl.o[0, E.M1555] = np.nan  # no trade at 15:55: the next bar with volume
    tl.v[0, E.M1555] = 0
    assert E.entry(tl, (0, "mkt", 0, E.M1555), -1)[1] == E.M1555 + 1
    lim = tl.dC[0] * 1.05
    for k in range(E.AH_FIRST, NM):
        _set(tl, 0, k, lim * 0.99, lim * 0.995, lim * 0.98, lim * 0.99)
    _set(tl, 0, 800, lim * 1.0004, lim * 1.0005, lim * 0.99, lim)  # touches, not through by 0.1%
    assert E.entry(tl, (0, "lim_ah", 0, 0.05), -1) is None
    _set(tl, 0, 900, lim * 0.999, lim * 1.003, lim * 0.99, lim)
    assert E.entry(tl, (0, "lim_ah", 0, 0.05), -1) == (0, 900, lim, E.L_PASS)
    _set(tl, 0, 850, lim * 1.02, lim * 1.03, lim * 1.01, lim * 1.02)  # opens above the limit: the open, better
    assert E.entry(tl, (0, "lim_ah", 0, 0.05), -1) == (0, 850, lim * 1.02, E.L_PASS)


def test_stop_before_target_and_stop_limit_fallback() -> None:
    tl = _tl()
    e = 10.0
    for a in (tl.o, tl.h, tl.l, tl.c):
        a[1:, :] = e
        a[0, E.M1555:] = e
    _set(tl, 1, 400, e, e * 1.30, e * 0.70, e)  # one bar through the 25% stop and the 25% target
    px, key, leg = E.exits(tl, 0, E.M1555, e, -1)
    k = E.EXITS.index((E.TIMES.index("d10c"), 1, 1))
    assert key[k] == NM + 400 and px[k] == pytest.approx(12.5)  # the stop, at the stop (open under it)
    k = E.EXITS.index((E.TIMES.index("d10c"), 1, 0))
    assert key[k] == NM + 400 and px[k] == pytest.approx(7.5)  # the target alone
    tl2 = _tl()
    for a in (tl2.o, tl2.h, tl2.l, tl2.c):
        a[1:, :] = e
    _set(tl2, 1, 400, e * 1.40, e * 1.40, e * 1.39, e * 1.40)  # gapped past the limit (13.125), never back under
    for m in range(401, NM):
        _set(tl2, 1, m, e * 1.40, e * 1.40, e * 1.39, e * 1.40)
    got = E.stop_event(tl2, NM + E.M1555 - NM, e, 0.25, -1)
    assert got[0] == NM + 405 and got[1] == pytest.approx(14.0)  # market 5 minutes after the trigger


def _perturb_after(tl: E.Timeline, g: int, day: int, seed: int = 9) -> E.Timeline:
    rng = np.random.default_rng(seed)
    out = E.Timeline(*(np.array(getattr(tl, k), float) for k in ("o", "h", "l", "c", "v", "vw", "dO", "dH", "dL",
                                                                   "dC")), tl.pc)
    for k in ("o", "h", "l", "c"):
        a = getattr(out, k).reshape(-1)
        a[g + 1:] *= rng.uniform(0.5, 2.0, max(len(a) - g - 1, 0))
    for k in ("dO", "dH", "dL", "dC"):
        a = getattr(out, k)
        a[day + 1:] *= rng.uniform(0.5, 2.0, max(len(a) - day - 1, 0))
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_look_ahead(seed: int) -> None:
    for dense in (True, False):
        tl = _tl(K=3, seed=seed, dense=dense)
        tau = E.runner_minute(tl, 0.0)
        for side in (-1, 1):
            for name, spec in {**E.CLOSE_ENTRIES, **E.OPEN_ENTRIES, **E.RUN_ENTRIES}.items():
                got = E.entry(tl, spec, side, tau)
                if got is None:
                    continue
                d, m, px, _ = got
                again = E.entry(_perturb_after(tl, d * NM + m, d), spec, side, tau)
                assert again is not None and again[:3] == got[:3], name
                xp, key, _ = E.exits(tl, d, m, px, side)
                for k in np.flatnonzero(key >= 0)[::7]:
                    dx = int(key[k]) // NM
                    xp2, key2, _ = E.exits(_perturb_after(tl, int(key[k]), dx), d, m, px, side)
                    assert key2[k] == key[k] and xp2[k] == pytest.approx(xp[k], nan_ok=True), (name, E.EXITS[k])


def test_1549_decision_ignores_the_close() -> None:
    tl = _tl(seed=4)
    a = E.at_1549(tl, "STRONG", 5.0)
    tl2 = _perturb_after(tl, E.M1550 - 1, 0)
    tl2.dC[0] *= 3
    assert E.at_1549(tl2, "STRONG", 5.0) == a


def test_marks_add_up() -> None:
    tl = _tl(K=2, seed=5)
    for side in (-1, 1):
        mk, adv, hi = E.marks(tl, side, 0, E.M1555, 10.0, 4, E.LAST, float(tl.dC[4]), 0.123)
        assert mk.sum() == pytest.approx(0.123) and (adv <= mk + 1e-12).all() and len(mk) == 5
        assert (hi > 0).all() if side < 0 else (hi == 0).all()


def test_grid_matches_brute_force() -> None:
    rng = np.random.default_rng(0)
    n = 600
    b = {k: rng.integers(0, m, n) for k, m in (("p", E.NP_), ("s", E.NS_), ("d", E.NDV), ("o", E.NSO), ("t", E.NT),
                                                ("a", E.NA))}
    cells = E.cell_of(b["p"], b["s"], b["d"], b["o"], b["t"], b["a"])
    R = rng.normal(0.01, 0.1, (n, 3))
    R[rng.random((n, 3)) < 0.1] = np.nan
    per = rng.integers(0, 4, n)
    cs = E.cell_sums(cells, R, per, 4)
    M = E.filter_matrix()
    so = {"all": lambda o: True, "known": lambda o: o >= 1, "u10": lambda o: o == 1, "u50": lambda o: o in (1, 2),
          "o10": lambda o: o >= 2}
    tier = {"all": lambda t: True, "nohot": lambda t: t < 2, "hot": lambda t: t == 2}
    age = {"all": lambda a: True, "young": lambda a: a == 0, "old": lambda a: a >= 1}
    for f in rng.choice(len(E.FILTERS), 25, replace=False):
        a_, b_, s, d, o, t, g = E.FILTERS[f]
        keep = np.array([a_ <= b["p"][i] <= b_ and b["s"][i] >= s and b["d"][i] >= d and so[E.SO_SETS[o]](b["o"][i])
                         and tier[E.TIER_SETS[t]](b["t"][i]) and age[E.AGE_SETS[g]](b["a"][i]) for i in range(n)])
        got = M[f] @ cs[:, :2].sum(1).reshape(E.NCELL, -1)
        got = got.reshape(3, 4)
        for x in range(3):
            r = R[keep & (per < 2), x]
            r = r[np.isfinite(r)]
            want = [len(r), r.sum(), r[r > 0].sum(), -r[r < 0].sum()]
            assert got[x] == pytest.approx(want, abs=1e-6)
    assert len(E.FILTERS) == 10_800


def _trades(rows: list[dict]) -> E.Trades:
    marks = [r.pop("mk") for r in rows]
    off = np.cumsum([0] + [len(m[0]) for m in marks])[:-1]
    cols = {k: np.array([r[k] for r in rows]) for k in rows[0]}
    return E.Trades(**cols, off=off, mark=np.concatenate([m[0] for m in marks]),
                    adv=np.concatenate([m[1] for m in marks]), hi=np.concatenate([m[2] for m in marks]),
                    member=np.zeros(len(rows), int))


def _row(t_in: int, t_out: int, sym: str = "AAA", side: int = -1, price: float = 5.0, mk=None) -> dict:
    n = t_out - t_in + 1
    mk = mk or (np.full(n, 0.01), np.full(n, -0.01), np.full(n, 1.0))
    return {"t_in": t_in, "t_out": t_out, "m_in": 715, "side": side, "price": price, "dv1": 1e7, "tier": 1,
            "sym": sym, "t_ev": t_in, "g": float(np.sum(mk[0])), "sale": 0.001, "loc": 0.002, "borrow": 0.003,
            "margin": 0.0005, "mk": mk}


def test_account_rules() -> None:
    tr = _trades([_row(10, 12), _row(10, 11, "BBB"), _row(11, 13, "AAA"), _row(20, 20, "CCC")])
    size = np.full(4, 0.2)
    R = E.account(tr, np.arange(4), size, 10_000.0, 5, 10, 40)
    w = 400 * 5.0 / 10_000  # whole shares of $2,000
    comm = 2 * max(400 * E.COMM, E.COMM_MIN) + 2 * max(np.ceil(E.REP * 400 * 100) / 100, E.REP_MIN)
    cost = w * (0.001 + 0.002 + 0.003 + 0.0005) + comm / 10_000
    assert R[12] == pytest.approx(w * 0.01)  # AAA's last session; the second AAA overlaps it: skipped
    assert R[13] == 0.0
    assert R[10] == pytest.approx(2 * (w * 0.01 - cost))
    assert R[20] == pytest.approx(w * 0.01 - cost)
    R1 = E.account(tr, np.arange(4), size, 10_000.0, 1, 10, 40)  # one new a session
    assert R1[11] == pytest.approx(w * 0.01) and R1[10] == pytest.approx(w * 0.01 - cost)
    squeeze = (np.array([0.01, -0.5]), np.array([-0.01, -3.0]), np.array([1.0, 4.0]))
    tr = _trades([_row(5, 6, mk=squeeze)])
    R = E.account(tr, np.arange(1), np.array([0.4]), 10_000.0, 5, 10, 20)
    w = 800 * 5.0 / 10_000
    assert R[6] == pytest.approx(w * -3.0)  # liquidated at the extreme


# ---------------------------------------------------------------- end to end on a synthetic panel

@pytest.fixture(scope="module")
def M():
    from test_v24 import _script
    return _script("run_v51", "run_v51_under_test")


@pytest.fixture(scope="module")
def MD():
    from test_v24 import _script
    return _script("run_v51_data", "run_v51_data_e2e")


def _world(root, MD) -> None:
    rng = np.random.default_rng(7)
    T, N = 420, 30
    dates = pd.bdate_range("2021-07-01", periods=T)
    cols = pd.Index([f"S{k:02d}" for k in range(N)])
    C = 3.0 * np.exp(np.cumsum(rng.normal(0, 0.03, (T, N)), axis=0))
    pc = np.vstack([C[:1], C[:-1]])
    O = pc * np.exp(rng.normal(0, 0.01, (T, N)))
    ev = rng.random((T, N)) < 0.04
    O[ev] = pc[ev] * rng.uniform(1.25, 1.8, ev.sum())
    C[ev] = O[ev] * rng.uniform(0.75, 1.15, ev.sum())
    H = np.maximum(O, C) * rng.uniform(1.0, 1.25, (T, N))
    L = np.minimum(O, C) * rng.uniform(0.85, 1.0, (T, N))
    f32 = np.float32
    D = {"dates": dates, "cols": cols, "O": O.astype(f32), "H": H.astype(f32), "L": L.astype(f32),
         "C": C.astype(f32), "P": C.astype(f32), "F": np.ones((T, N), f32), "DV": np.full((T, N), 3e6, f32),
         "SO": np.full((T, N), 2e7), "valid": np.ones((T, N), bool), "new": np.zeros((T, N), bool)}
    D["valid1"] = D["valid"].copy()
    D["valid1"][0] = False
    D["P1"] = np.vstack([np.full((1, N), np.nan), D["P"][:-1]])
    D["DV1"] = np.vstack([np.full((1, N), np.nan), D["DV"][:-1]])
    (root / "v18" / "v14").mkdir(parents=True)
    (root / "v18" / "v15").mkdir(parents=True)
    (root / "v28").mkdir(parents=True)
    with open(root / "v18" / "v14" / "daily.pkl", "wb") as fh:
        pickle.dump(D, fh)
    with open(root / "v18" / "v15" / "avail.pkl", "wb") as fh:
        pickle.dump({"table": {}}, fh)
    with open(root / "v28" / "extras28.pkl", "wb") as fh:
        pickle.dump({"si_so": np.zeros((T, N), f32), "thr": np.zeros((T, N), bool)}, fh)
    sup = MD.superset(D)
    need = MD.need_days(D, sup, 3)
    out = root / "v51"
    (out / "minutes").mkdir(parents=True)
    t, j = np.nonzero(sup)
    pd.DataFrame({"t": t.astype(np.int32), "j": j.astype(np.int32)}).to_parquet(out / "events.parquet")
    (out / "census.json").write_text(json.dumps({"hold": 3}), encoding="utf-8")
    mins = np.arange(NM)
    for day, syms in need.items():
        u = dates.get_loc(pd.Timestamp(day))
        parts = []
        for s in syms:
            k = cols.get_loc(s)
            o, h, lo, c = (float(a[u, k]) for a in (O, H, L, C))
            path = np.interp(mins, [0, E.OPEN, 400, 600, E.LAST, NM - 1],
                             [o * 0.98, o, h * 0.999, lo * 1.001, c, c * 1.01])
            path *= np.exp(rng.normal(0, 0.002, NM))
            po = np.r_[path[0], path[:-1]]
            parts.append(pd.DataFrame({"symbol": s, "minute": mins.astype(np.int16), "o": po, "h": np.maximum(po, path),
                                       "l": np.minimum(po, path), "c": path, "v": 500.0, "vw": path}))
        df = pd.concat(parts)
        for k in ("o", "h", "l", "c", "v", "vw"):
            df[k] = df[k].astype(np.float32)
        df["symbol"] = df["symbol"].astype("category")
        df.to_parquet(out / "minutes" / f"{day}.parquet", index=False)


@pytest.mark.slow
def test_pipeline_end_to_end(M, MD, tmp_path, monkeypatch) -> None:
    import argparse
    _world(tmp_path, MD)
    monkeypatch.setattr(M, "PATHS", 300)
    monkeypatch.setattr(M, "SEEDS", (0, 1))
    monkeypatch.setattr(M, "SEEDS_CONF", (0, 1))
    monkeypatch.setattr(M, "SINGLES", 2)
    monkeypatch.setattr(M, "CONFIRM", 2)
    monkeypatch.setattr(M, "SIZES", (0.2,))
    monkeypatch.setattr(M, "BOOK_SIZES", (0.2,))
    monkeypatch.setattr(M, "TOP_ENTRY", 20)
    monkeypatch.setattr(M, "TOP_GROUP", 3)
    ns = argparse.Namespace
    fac = tmp_path / "fac"
    for g in ("GAPUP-short", "STRONG-long", "RUN40-short"):
        assert M.cmd_factory(ns(group=g, inputs=tmp_path / "v18", extras=tmp_path / "v28", data=tmp_path / "v51",
                                out=fac / g, procs=1)) == 0
        rep = json.loads((fac / g / "report.json").read_text(encoding="utf-8"))
        assert rep["events"] > 0 and rep["n_scored"] > 0
    sel = tmp_path / "sel"
    assert M.cmd_select(ns(factory=fac, out=sel, procs=1)) == 0
    configs = json.loads((sel / "configs.json").read_text(encoding="utf-8"))
    assert configs
    runs = tmp_path / "runs"
    assert M.cmd_account(ns(sel=sel, shard=0, shards=1, out=runs / "acc", procs=1)) == 0
    picks = tmp_path / "picks"
    assert M.cmd_pick(ns(runs=runs / "acc", out=picks, procs=1)) == 0
    assert M.cmd_books(ns(sel=sel, picks=picks, shard=0, shards=1, out=runs / "books", procs=1)) == 0
    assert M.cmd_pick2(ns(runs=runs / "books", sel=sel, out=picks, procs=1)) == 0
    todo = json.loads((picks / "confirm.json").read_text(encoding="utf-8"))["confirm"]
    for s in range(len(todo)):
        assert M.cmd_confirm(ns(sel=sel, picks=picks, shard=s, shards=len(todo), out=runs / "conf", procs=1)) == 0
    out = tmp_path / "final"
    assert M.cmd_final(ns(factory=fac, sel=sel, picks=picks, runs=runs / "conf", out=out, procs=1)) == 0
    assert "# v51 report" in (out / "V51_REPORT.md").read_text(encoding="utf-8")
