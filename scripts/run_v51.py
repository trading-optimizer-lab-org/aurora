"""v51 (V51_PREREGISTRATION.md): every small-cap setup x side x entry x exit x filter set on one-minute bars.

  factory  one setup and side: every event's minute path walked once per entry for the 81 exits, the filter grid on
           2018-2022, the top configurations' trades (cache only) and aggregate tables (artifact)
  select   the top 200 configurations across groups, and v50's members
  account  a shard of (configuration x size x new a day): the account and the one-year bootstrap, 6 seeds
  pick     the 12 best singles and every book of 1-3 of them
  books    a shard of the books
  pick2    the 50 best books and v50's book
  confirm  one book: 31 seeds at base and HOT 5%, the stress sets, the symbol halves
  final    V51_REPORT.md and v51_summary.json
Market data and trade prices stay in the Actions cache; artifacts hold aggregate statistics only.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import multiprocessing as mp
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v51_engine as E
from aurora.research.v15_ah import lookup

FIRST, SPLIT = pd.Timestamp("2018-01-01"), pd.Timestamp("2023-01-01")
Y0, NPER, NDES, DESIGN_YEARS = 2018, 9, 5, 5.0  # entry years 2018-2026, design 2018-2022
SIDES = ("short", "long")
GROUPS = [f"{s}-{d}" for s in E.SETUPS for d in SIDES]
TOP_ENTRY, TOP_GROUP, SELECT = 200, 10, 200
SIZES, NEWS, MAX_OPEN = (0.10, 0.20, 0.30, 0.40), (3, 5), 10
SEEDS, SEEDS_CONF, DROP = tuple(range(6)), tuple(range(31)), 0.10
TASKS = {"base": 0.03, "hot5": 0.05}  # the HOT locate a share
STRESS = {"borrow2": {"borrow": 2.0}, "loc_never": {"unavail": {}}, "loc_half": {"unavail": {1: 0.05, 2: 0.25}}}
SINGLES, BOOK_SIZES, CONFIRM, MAX_RUIN, TARGET = 12, (0.10, 0.20, 0.30), 50, 0.025, 10_000.0
CHUNK = 20  # sessions of events a worker walks at once
PATHS = E.PATHS
CODES = ("ok", "no_fill", "ssr", "floor", "locate", "no_setup", "", "", "no_bars")
ALL = E.FILTERS.index((0, E.NP_ - 1, 0, 0, 0, 0, 0))
V50 = (("DS1", "RUNUP", "short", "c_open", ("d5c", 0.50, 0.0), (0, 4, 2, 1, 0, 0, 0), 0.20),
       ("RU", "RUNUP", "short", "c_open", ("d10c", 0.50, 0.0), (0, 4, 2, 1, 0, 0, 0), 0.20),
       ("NS", "FADE", "short", "c_1555", ("d3c", 0.0, 0.0), (2, 2, 0, 1, 0, 0, 0), 0.60))
V50_NEW, V50_REF = 5, 9_065.0
TR_FIELDS = ("t_in", "t_out", "m_in", "side", "price", "dv1", "tier", "sym", "t_ev", "g", "sale", "loc", "borrow",
             "margin", "off", "mark", "adv", "hi", "member")
_G: dict = {}


def exit_ix(time_name: str, tgt: float, stop: float) -> int:
    return E.EXITS.index((E.TIMES.index(time_name), E.TGTS.index(tgt), E.STOPS.index(stop)))


def exit_name(x: int) -> str:
    ti, gi, si = E.EXITS[x]
    return f"{E.TIMES[ti]}/t{E.TGTS[gi]:.2f}/s{E.STOPS[si]:.2f}"


def filter_name(f: int) -> str:
    a, b, s, d, o, t, g = E.FILTERS[f]
    return (f"price{a}-{b} str{s} dv{d} so:{E.SO_SETS[o]} tier:{E.TIER_SETS[t]} age:{E.AGE_SETS[g]}")


def _pf(win, loss):
    win, loss = np.asarray(win, float), np.asarray(loss, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(loss > 0, win / loss, np.where(win > 0, 99.0, np.nan))


def _num(x):
    x = float(x)
    return None if not np.isfinite(x) else round(x, 6)


# ---------------------------------------------------------------- inputs (factory)

def load_inputs(inputs: Path, extras: Path) -> dict:
    with open(inputs / "v14" / "daily.pkl", "rb") as f:
        D = pickle.load(f)
    G = {k: np.asarray(D[k]) for k in ("O", "H", "L", "C", "P", "F", "P1", "DV1", "SO", "valid")}
    G["dates"], G["cols"] = pd.DatetimeIndex(D["dates"]), pd.Index(D["cols"])
    del D
    with open(inputs / "v15" / "avail.pkl", "rb") as f:
        G["table"] = pickle.load(f)["table"]
    G["X"] = {}
    if (extras / "extras28.pkl").exists():
        with open(extras / "extras28.pkl", "rb") as f:
            x = pickle.load(f)
        G["X"] = {k: np.asarray(x[k]) for k in ("si_so", "thr") if k in x}
    G["low20s2"] = pd.DataFrame(G["C"].astype(float)).rolling(20, min_periods=10).min().shift(2).to_numpy()
    G["dn"] = G["dates"].values.astype("datetime64[D]").astype(np.int64)
    G["year"] = np.asarray(G["dates"].year)
    first = np.argmax(G["valid"], axis=0)
    G["first"] = np.where(G["valid"].any(0), first, 0)
    return G


def tiers(G: dict, t: np.ndarray, j: np.ndarray, price: np.ndarray) -> np.ndarray:
    """v29's tiers (0 ETB, 1 HTB, 2 HOT) from the state known at session t."""
    X = G["X"]
    pc = G["C"][t - 1, j].astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = G["O"][t, j] / pc
        rise = pc / G["low20s2"][t, j]
        si = X["si_so"][t, j].astype(float) if "si_so" in X else np.zeros(len(t))
        thr = X["thr"][t, j].astype(bool) if "thr" in X else np.zeros(len(t), bool)
        hot = thr | (gap >= 1.5) | (rise >= 2.0) | (si >= 0.2)
        etb = ~hot & (np.asarray(price, float) >= 10) & (G["SO"][t, j] >= 50e6) & (G["DV1"][t, j] >= 20e6)
    return np.where(hot, 2, np.where(etb, 0, 1))


def setup_events(G: dict, out51: Path, setup: str) -> dict:
    """The setup's candidate events from v51-data's superset, with what is known at the decision."""
    ev = pd.read_parquet(out51 / "events.parquet")
    t, j = ev["t"].to_numpy(np.int64), ev["j"].to_numpy(np.int64)
    t, j = t[t >= 5], j[t >= 5]

    def f(k: str, lag: int = 0) -> np.ndarray:
        return G[k][t - lag, j].astype(float)

    O, H, L, C, pc = f("O"), f("H"), f("L"), f("C"), f("C", 1)
    low4 = np.fmin.reduce(np.stack([f("L", s) for s in range(1, 5)]), axis=0)
    low5 = np.fmin(low4, L)
    val, cond = E.setup_value(setup, O, H, L, C, pc, low5)
    sb = np.where(cond, E.strength(setup, val), -1)
    keep = (sb >= 0) | E.candidate(setup, O, H, L, pc, low5)
    t, j, sb, low4 = t[keep], j[keep], sb[keep], low4[keep]
    T = len(G["dates"])
    P1, DV1, SO = G["P1"][t, j].astype(float), G["DV1"][t, j].astype(float), G["SO"][t, j].astype(float)
    age = G["dn"][t] - G["dn"][G["first"][j]] + np.where(G["first"][j] == 0, 10_000, 0)
    _, fee = lookup(G["table"], np.maximum(P1, 0.01), SO)
    return {"t": t, "j": j, "sym": np.asarray(G["cols"][j]).astype(str), "sb": sb, "low4": low4,
            "pb": np.searchsorted(E.PRICE_EDGES, P1, side="right"),
            "db": np.searchsorted(E.DV_EDGES, DV1, side="right"), "ob": E.so_bucket(SO), "ab": E.age_bucket(age),
            "tier0": tiers(G, t, j, P1), "tier1": tiers(G, np.minimum(t + 1, T - 1), j, G["P"][t, j]),
            "fee": np.maximum(2 * fee, 100.0), "dv1": DV1}


# ---------------------------------------------------------------- the minute walk

def _frames(days: range, js: np.ndarray) -> dict:
    """(session, column) -> 6 x 960 split-adjusted o, h, l, c, v, vw of the needed symbols."""
    G = _G["G"]
    want = np.zeros(len(G["cols"]), bool)
    want[js] = True
    out = {}
    for u in days:
        if u >= len(G["dates"]):
            break
        p = _G["folder"] / f"{G['dates'][u].date()}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        jj = G["cols"].get_indexer(df["symbol"].astype(str))
        ok = (jj >= 0) & want[np.maximum(jj, 0)]
        if not ok.any():
            continue
        jj, mins = jj[ok], df["minute"].to_numpy(np.int64)[ok]
        vals = df[["o", "h", "l", "c", "v", "vw"]].to_numpy(np.float64)[ok]
        order = np.argsort(jj, kind="stable")
        jj, mins, vals = jj[order], mins[order], vals[order]
        cuts = np.flatnonzero(np.diff(jj)) + 1
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(jj)]):
            k = int(jj[a])
            fac = float(G["F"][u, k])
            if not (np.isfinite(fac) and fac > 0):
                continue
            A = np.full((6, E.NM), np.nan)
            A[:, mins[a:b]] = vals[a:b].T
            A[[0, 1, 2, 3, 5]] *= fac
            out[(u, k)] = A
    return out


def _timeline(frames: dict, t: int, j: int) -> E.Timeline | None:
    G = _G["G"]
    rows = []
    for d in range(_G["H"] + 1):
        A = frames.get((t + d, j))
        if A is None:
            break
        rows.append(A)
    if not rows:
        return None
    M = np.stack(rows)
    T = len(G["dates"])
    ii = t + np.arange(E.ND)
    ok = ii < T
    ii = np.minimum(ii, T - 1)

    def day(k: str) -> np.ndarray:
        return np.where(ok, G[k][ii, j].astype(float), np.nan)

    return E.Timeline(*(M[:, q] for q in range(6)), day("O"), day("H"), day("L"), day("C"), float(G["C"][t - 1, j]))


def _ssr(tl: E.Timeline, t: int, j: int, de: int, me: int) -> bool:
    """The SEC short-sale price test at the entry: a low 10% or more under the prior close on the prior session, or
    in the entry session's regular hours before the entry."""
    C, L = _G["G"]["C"], _G["G"]["L"]
    u = t + de
    if u >= 2 and np.isfinite(L[u - 1, j]) and L[u - 1, j] <= 0.9 * C[u - 2, j]:
        return True
    if de < tl.K and me > E.OPEN:
        lo = tl.l[de, E.OPEN:min(me, E.LAST + 1)]
        return bool(np.isfinite(lo).any() and np.nanmin(lo) <= 0.9 * float(C[u - 1, j]))
    return False


def _entry(tl: E.Timeline, i: int, q: int, sb1549: int, tau: int) -> tuple:
    """(code, strength, day, minute, price, raw price, leg, cost tier, locate draw) of entry q for event i."""
    EV, G = _G["EV"], _G["G"]
    name, spec = _G["entries"][q]
    sgn = _G["sgn"]
    sb = sb1549 if name == "c_1555" else int(EV["sb"][i])
    if sb < 0 or (E.SETUPS[_G["setup"]][0] == "run" and tau < 0):
        return (5, sb)
    got = E.entry(tl, spec, sgn, tau)
    t, j = int(EV["t"][i]), int(EV["j"][i])
    if got is None or t + got[0] >= len(G["dates"]) or not (np.isfinite(got[2]) and got[2] > 0):
        return (1, sb)
    de, me, e, leg = got
    u = t + de
    fac = float(G["F"][u, j]) if np.isfinite(G["F"][u, j]) and G["F"][u, j] > 0 else float(G["F"][t, j])
    raw = e / fac
    tier = int(EV["tier0"][i]) if de == 0 or me <= E.OPEN else max(int(EV["tier0"][i]), int(EV["tier1"][i]))
    lu = E.unit(EV["sym"][i], u, "49loc") if sgn < 0 and tier >= 1 else 1.0
    code = 0
    if sgn < 0:
        if raw < E.FLOOR:
            code = 3
        elif _ssr(tl, t, j, de, me):
            code = 2
        elif lu < E.UNAVAIL.get(tier, 0.0):
            code = 4
    return (code, sb, de, me, e, raw, leg, tier, lu)


def _returns(tl: E.Timeline, i: int, en: tuple) -> tuple:
    """Net returns at the $1,000 reference size of the 81 exits, and what the trades need."""
    G, EV, sgn = _G["G"], _G["EV"], _G["sgn"]
    _, _, de, me, e, raw, leg, tier, _ = en
    t = int(EV["t"][i])
    T = len(G["dates"])
    px, key, legx = E.exits(tl, de, me, e, sgn)
    g = E.gross(sgn, e, px, int(E.tier_of(raw)), leg, legx)
    tout = t + np.where(key >= 0, key // E.NM, 0)
    ok = (key >= 0) & np.isfinite(px) & (tout < T)
    cal = np.where(ok, G["dn"][np.minimum(tout, T - 1)] - G["dn"][t + de], 0)
    fc = E.fixed_costs(sgn, raw, tier, float(EV["fee"][i]), cal)
    return np.where(ok, g - fc, np.nan), px, key, g, cal


def _decide(tl: E.Timeline, i: int) -> tuple[int, int]:
    EV, setup = _G["EV"], _G["setup"]
    kind = E.SETUPS[setup][0]
    sb1549 = E.at_1549(tl, setup, float(EV["low4"][i])) if kind == "close" else int(EV["sb"][i])
    tau = E.runner_minute(tl, E.SETUPS[setup][1][0]) if kind == "run" else -1
    return sb1549, tau


def _pass1(ix: np.ndarray) -> dict:
    EV = _G["EV"]
    n, Q = len(ix), len(_G["entries"])
    out = {"code": np.full((n, Q), 8, np.int8), "sb": np.full((n, Q), -1, np.int8), "de": np.zeros((n, Q), np.int8),
           "me": np.zeros((n, Q), np.int16), "R": np.full((n, Q, E.NX), np.nan, np.float32)}
    t = EV["t"][ix]
    frames = _frames(range(int(t.min()), int(t.max()) + _G["H"] + 1), EV["j"][ix])
    for r, i in enumerate(ix):
        tl = _timeline(frames, int(EV["t"][i]), int(EV["j"][i]))
        if tl is None:
            continue
        sb1549, tau = _decide(tl, i)
        for q in range(Q):
            en = _entry(tl, i, q, sb1549, tau)
            out["code"][r, q], out["sb"][r, q] = en[0], en[1]
            if en[0] in (0, 4):
                out["de"][r, q], out["me"][r, q] = en[2], en[3]
                out["R"][r, q] = _returns(tl, i, en)[0]
    return out


def _pass2(ix: np.ndarray) -> list[dict]:
    """The trades of the kept configurations on events ``ix``: want maps entry -> [(config, exit, events)]."""
    EV, G, sgn, want = _G["EV"], _G["G"], _G["sgn"], _G["want"]
    t = EV["t"][ix]
    frames = _frames(range(int(t.min()), int(t.max()) + _G["H"] + 1), EV["j"][ix])
    rows = []
    for i in ix:
        tl = _timeline(frames, int(EV["t"][i]), int(EV["j"][i]))
        if tl is None:
            continue
        sb1549, tau = _decide(tl, i)
        for q, cx in want.items():
            mine = [(c, x) for c, x, evs in cx if i in evs]
            if not mine:
                continue
            en = _entry(tl, i, q, sb1549, tau)
            if en[0] not in (0, 4):
                continue
            R, px, key, g, cal = _returns(tl, i, en)
            _, _, de, me, e, raw, _, tier, lu = en
            t_ev = int(EV["t"][i])
            for c, x in mine:
                if not np.isfinite(R[x]):
                    continue
                dx, mx = divmod(int(key[x]), E.NM)
                mk, adv, hi = E.marks(tl, sgn, de, me, e, dx, mx, float(px[x]), float(g[x]))
                rows.append({"cfg": c, "t_in": t_ev + de, "t_out": t_ev + dx, "m_in": me,
                             "side": sgn, "price": raw, "dv1": float(EV["dv1"][i]), "tier": tier,
                             "sym": str(EV["sym"][i]), "t_ev": t_ev, "g": float(g[x]),
                             "sale": E.SEC + E.TAF / max(raw, 0.01),
                             "loc": (E.LOC[tier] / max(raw, 0.01)) if sgn < 0 else 0.0,
                             "borrow": float(EV["fee"][i]) / 100 / 360 * cal[x] if sgn < 0 else 0.0,
                             "margin": E.MARGIN / 360 * cal[x], "mark": mk, "adv": adv, "hi": hi,
                             "lu": lu, "code": int(en[0]), "r": float(R[x]), "year": int(G["year"][t_ev + de])})
    return rows


def _chunks(t: np.ndarray, width: int = CHUNK) -> list[np.ndarray]:
    order = np.argsort(t, kind="stable")
    key = (t[order] - t.min()) // width
    cuts = np.flatnonzero(np.diff(key)) + 1
    return [order[a:b] for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(order)])]


def _map(fn, jobs: list, procs: int) -> list:
    if procs <= 1:
        return [fn(j) for j in jobs]
    with mp.get_context("fork").Pool(procs) as pool:
        return pool.map(fn, jobs, chunksize=1)


# ---------------------------------------------------------------- the grid

def _cells(q: int, codes: tuple = (0,)) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    P, EV, G = _G["P1"], _G["EV"], _G["G"]
    ev = np.flatnonzero(np.isin(P["code"][:, q], codes))
    cells = E.cell_of(EV["pb"][ev], P["sb"][ev, q], EV["db"][ev], EV["ob"][ev], EV["tier0"][ev], EV["ab"][ev])
    per = np.clip(G["year"][EV["t"][ev] + P["de"][ev, q]] - Y0, 0, NPER - 1)
    return ev, cells, per


def _stats(Gx: np.ndarray) -> dict:
    n, s, w, lo = (Gx[..., k] for k in range(4))
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"n": n, "mean": np.where(n > 0, s / np.maximum(n, 1), np.nan), "pf": _pf(w, lo)}


def _grid(q: int) -> dict:
    ev, cells, per = _cells(q)
    if not len(ev):
        return {"q": q, "rows": [], "n_scored": 0, "n_pass": 0}
    R = _G["P1"]["R"][ev, q].astype(float)
    cs = E.cell_sums(cells, R, per, NPER)
    des, late = cs[:, :NDES].sum(1), cs[:, NDES:].sum(1)
    M = _G["M"]
    Gd = (M @ des.reshape(E.NCELL, -1)).reshape(len(E.FILTERS), E.NX, 4)
    Gl = (M @ late.reshape(E.NCELL, -1)).reshape(len(E.FILTERS), E.NX, 4)
    sc = E.score(Gd[..., 0], Gd[..., 2], Gd[..., 3], DESIGN_YEARS)
    flat = sc.ravel()
    k = min(TOP_ENTRY, int(np.isfinite(flat).sum()))
    top = np.argpartition(-np.nan_to_num(flat, neginf=-1e300), k)[:k] if k else np.array([], int)
    sd, sl = _stats(Gd), _stats(Gl)
    rows = sorted(({"q": q, "x": int(x), "f": int(f), "score": float(sc[f, x]), "n_d": int(sd["n"][f, x]),
                    "pf_d": _num(sd["pf"][f, x]), "mean_d": _num(sd["mean"][f, x]), "n_l": int(sl["n"][f, x]),
                    "pf_l": _num(sl["pf"][f, x]), "mean_l": _num(sl["mean"][f, x])}
                   for f, x in (divmod(int(z), E.NX) for z in top)), key=lambda r: -r["score"])
    best = np.max(sc, axis=0)
    table = [{"x": x, "n_d": int(sd["n"][ALL, x]), "pf_d": _num(sd["pf"][ALL, x]), "mean_d": _num(sd["mean"][ALL, x]),
              "n_l": int(sl["n"][ALL, x]), "pf_l": _num(sl["pf"][ALL, x]), "mean_l": _num(sl["mean"][ALL, x]),
              "score_all": _num(sc[ALL, x]), "best_f": int(np.argmax(sc[:, x])), "best_score": _num(best[x])}
             for x in range(E.NX)]
    unf = np.where(np.isfinite(sc[ALL]), sc[ALL], -1e300)
    shown = list(dict.fromkeys([int(x) for x in np.argsort(-np.where(np.isfinite(best), best, -1e300))[:3]]
                               + [int(np.argmax(unf))]))
    return {"q": q, "rows": rows, "table": table, "marginals": {exit_name(x): _marginals(cs, x) for x in shown},
            "n_scored": int(sc.size), "n_pass": int(np.isfinite(sc).sum())}


def _marginals(cs: np.ndarray, x: int) -> dict:
    """One exit's trades by each filter dimension's bucket and by year (unfiltered): all years and 2018-2022."""
    def row(a: np.ndarray, z: np.ndarray | None = None) -> dict:
        out = {"n": int(a[0]), "mean": _num(a[1] / a[0]) if a[0] else None, "pf": _num(_pf(a[2], a[3]))}
        if z is not None:
            out.update(n_d=int(z[0]), pf_d=_num(_pf(z[2], z[3])))
        return out

    tot, des = cs[:, :, x, :].sum(1), cs[:, :NDES, x, :].sum(1)
    out = {}
    for name, ax in zip(("price", "strength", "dv", "so", "tier", "age"), E._cell_axes()):
        nb = int(ax.max()) + 1
        a = np.stack([np.bincount(ax, tot[:, s], minlength=nb) for s in range(4)], 1)
        z = np.stack([np.bincount(ax, des[:, s], minlength=nb) for s in range(4)], 1)
        out[name] = [row(a[b], z[b]) for b in range(nb)]
    yr = cs[:, :, x, :].sum(0)
    out["year"] = [{"year": Y0 + p, **row(yr[p])} for p in range(NPER)]
    return out


def _signature(q: int, x: int, f: int) -> tuple[str, np.ndarray]:
    """The hash of a configuration's located trades, and its events with failed locates too (the stress sets)."""
    P = _G["P1"]
    out = []
    for codes in ((0,), (0, 4)):
        ev, cells, _ = _cells(q, codes)
        R = P["R"][ev, q, x]
        out.append((ev, R, _G["Mb"][f][cells] & np.isfinite(R)))
    ev, R, keep = out[0]
    key = np.stack([ev[keep], P["de"][ev[keep], q], P["me"][ev[keep], q]]).astype(np.int64)
    h = hashlib.sha256(key.tobytes() + np.round(R[keep].astype(float), 6).tobytes()).hexdigest()
    return h, out[1][0][out[1][2]]


def cmd_factory(args) -> int:
    t0 = time.time()
    setup, side = args.group.split("-")
    G = load_inputs(args.inputs, args.extras)
    census = json.loads((args.data / "census.json").read_text(encoding="utf-8"))
    EV = setup_events(G, args.data, setup)
    kind = E.SETUPS[setup][0]
    entries = list(E.ENTRIES[kind].items())
    _G.update(G=G, EV=EV, setup=setup, sgn=-1 if side == "short" else 1, entries=entries, H=int(census["hold"]),
              folder=args.data / "minutes")
    print(json.dumps({"group": args.group, "events": len(EV["t"]), "hold": _G["H"], "entries": len(entries)}),
          flush=True)
    parts = _map(_pass1, _chunks(EV["t"]), args.procs)
    order = np.concatenate(_chunks(EV["t"]))
    P = {k: np.empty((len(order),) + parts[0][k].shape[1:], parts[0][k].dtype) for k in parts[0]}
    for k in P:
        P[k][order] = np.concatenate([p[k] for p in parts])
    _G["P1"] = P
    print(f"pass 1 {time.time() - t0:.0f}s", flush=True)
    Mf = E.filter_matrix()
    _G.update(M=Mf.astype(np.float64), Mb=Mf.astype(bool))
    grids = _map(_grid, list(range(len(entries))), args.procs)
    print(f"grid {time.time() - t0:.0f}s", flush=True)
    rows = sorted((r for g in grids for r in g["rows"]), key=lambda r: -r["score"])
    kept, seen = [], set()
    for r in rows:
        h, evs = _signature(r["q"], r["x"], r["f"])
        if h in seen:
            continue
        seen.add(h)
        kept.append({**r, "tag": "", "evs": evs})
        if len(kept) == TOP_GROUP:
            break
    names = [n for n, _ in entries]
    for tag, s50, side50, entry50, (tn, tg, st), filt, _ in V50:
        if (s50, side50) == (setup, side):
            q, x, f = names.index(entry50), exit_ix(tn, tg, st), E.FILTERS.index(filt)
            kept.append({"q": q, "x": x, "f": f, "score": None, "tag": f"v50:{tag}", "evs": _signature(q, x, f)[1]})
    configs = [{"id": c, "group": args.group, "entry": names[k["q"]], "exit": exit_name(k["x"]),
                "filter": filter_name(k["f"]), "q": k["q"], "x": k["x"], "f": k["f"], "tag": k["tag"],
                "score": k["score"], "cls": E.ENTRIES[kind][names[k["q"]]][0]} for c, k in enumerate(kept)]
    want: dict[int, list] = {}
    for c, k in enumerate(kept):
        want.setdefault(k["q"], []).append((c, k["x"], set(k["evs"].tolist())))
    need = np.unique(np.concatenate([k["evs"] for k in kept])) if kept else np.array([], int)
    _G["want"] = want
    jobs = [need[c] for c in _chunks(EV["t"][need])] if len(need) else []
    trades = [r for part in _map(_pass2, jobs, args.procs) for r in part]
    print(f"pass 2 {time.time() - t0:.0f}s, {len(trades)} trades", flush=True)
    for c in configs:
        mine = [r for r in trades if r["cfg"] == c["id"] and r["code"] == 0]
        c.update(_summary(mine))
    counts = {names[q]: {CODES[k]: int((P["code"][:, q] == k).sum()) for k in np.unique(P["code"][:, q])}
              for q in range(len(entries))}
    report = {"group": args.group, "events": len(EV["t"]), "hold": _G["H"], "counts": counts,
              "n_scored": sum(g["n_scored"] for g in grids), "n_pass": sum(g["n_pass"] for g in grids),
              "entries": {names[g["q"]]: {"table": g.get("table", []), "marginals": g.get("marginals", {}),
                                          "top": g["rows"][:20]} for g in grids},
              "configs": configs, "sec": round(time.time() - t0)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report), encoding="utf-8")
    save_trades(args.out / "trades.npz", trades, configs)
    np.save(args.out / "dn.npy", G["dn"])
    print(json.dumps({"kept": [(c["entry"], c["exit"], c["filter"], c["score"], c.get("n"), c.get("pf_d"))
                               for c in configs]}), flush=True)
    return 0


def _summary(rows: list[dict]) -> dict:
    """A configuration's trades (located): count a year, PF and mean by year, design and later, the worst trade."""
    if not rows:
        return {"n": 0}
    r = np.array([x["r"] for x in rows])
    y = np.array([x["year"] for x in rows])
    d = y < SPLIT.year

    def part(m):
        w, lo = r[m][r[m] > 0].sum(), -r[m][r[m] < 0].sum()
        return {"n": int(m.sum()), "pf": _num(_pf(w, lo)), "mean": _num(r[m].mean()) if m.any() else None}

    return {"n": len(r), "worst": _num(r.min()), "design": part(d), "later": part(~d),
            "pf_d": part(d)["pf"], "years": {int(k): part(y == k) for k in np.unique(y)}}


def save_trades(path: Path, rows: list[dict], configs: list[dict]) -> None:
    off = np.cumsum([0] + [len(r["mark"]) for r in rows])[:-1] if rows else np.array([], int)
    cat = (lambda k: np.concatenate([r[k] for r in rows]) if rows else np.array([]))
    out = {k: np.array([r[k] for r in rows]) for k in ("cfg", "t_in", "t_out", "m_in", "side", "price", "dv1", "tier",
                                                       "t_ev", "g", "sale", "loc", "borrow", "margin", "lu", "code",
                                                       "r", "year")}
    out["sym"] = np.array([r["sym"] for r in rows], dtype="U12")
    out.update(off=np.asarray(off, np.int64), mark=cat("mark"), adv=cat("adv"), hi=cat("hi"))
    np.savez_compressed(path, **out, configs=np.array(json.dumps(configs)))


def load_trades(path: Path) -> tuple[dict, list[dict]]:
    z = np.load(path, allow_pickle=False)
    return {k: z[k] for k in z.files if k != "configs"}, json.loads(str(z["configs"]))


# ---------------------------------------------------------------- selection

def _set_sig(A: dict, m: np.ndarray) -> str:
    key = np.stack([A["t_in"][m], A["m_in"][m], A["t_out"][m]]).astype(np.int64)
    return hashlib.sha256(key.tobytes() + "|".join(A["sym"][m]).encode() + np.round(A["r"][m], 6).tobytes()
                          ).hexdigest()


def cmd_select(args) -> int:
    pool = []
    for g in GROUPS:
        p = args.factory / g / "trades.npz"
        if not p.exists():
            print(f"{g}: no factory output", flush=True)
            continue
        A, cfgs = load_trades(p)
        for c in cfgs:
            m = A["cfg"] == c["id"]
            pool.append((c, {k: v[m] for k, v in A.items() if k not in ("off", "mark", "adv", "hi")},
                         [(A["mark"][o:o + n], A["adv"][o:o + n], A["hi"][o:o + n])
                          for o, n in zip(A["off"][m], A["t_out"][m] - A["t_in"][m] + 1)]))
    ranked = sorted([p for p in pool if not p[0]["tag"] and p[0]["score"] is not None],
                    key=lambda p: -p[0]["score"])
    chosen, seen = [], set()
    for p in ranked:
        h = _set_sig(p[1], p[1]["code"] == 0)
        if h not in seen:
            seen.add(h)
            chosen.append(p)
        if len(chosen) == SELECT:
            break
    chosen += [p for p in pool if p[0]["tag"]]
    configs, rows = [], []
    for c, (cfg, A, mk) in enumerate(chosen):
        configs.append({**cfg, "id": c, "src_id": cfg["id"]})
        for k in range(len(A["t_in"])):
            rows.append({**{f: A[f][k] for f in A if f != "cfg"}, "cfg": c, "mark": mk[k][0], "adv": mk[k][1],
                         "hi": mk[k][2]})
    args.out.mkdir(parents=True, exist_ok=True)
    save_trades(args.out / "trades.npz", rows, configs)
    np.save(args.out / "dn.npy", np.load(next(args.factory.rglob("dn.npy"))))
    (args.out / "configs.json").write_text(json.dumps(configs, indent=1), encoding="utf-8")
    print(json.dumps({"pool": len(pool), "selected": len(configs), "trades": len(rows)}), flush=True)
    return 0


# ---------------------------------------------------------------- the account stages

def load_selection(sel: Path) -> dict:
    A, configs = load_trades(sel / "trades.npz")
    dn = np.load(sel / "dn.npy")
    dates = pd.DatetimeIndex(dn.astype("datetime64[D]"))
    pos = np.flatnonzero(dates >= FIRST)
    cal = dates[pos]
    idx = {"all": E.draws(len(cal), paths=PATHS)}
    for name, keep in (("early", cal < SPLIT), ("late", cal >= SPLIT)):
        sub = np.flatnonzero(np.asarray(keep))
        if len(sub):
            idx[name] = sub[E.draws(len(sub), paths=PATHS)]
    n = len(A["t_in"])
    TR = E.Trades(**{k: A[k] for k in TR_FIELDS if k != "member"}, member=A["cfg"])
    by_cfg = {c["id"]: np.flatnonzero(A["cfg"] == c["id"]) for c in configs}
    return {"A": A, "TR": TR, "configs": configs, "by_cfg": by_cfg, "T": len(dn), "pos": pos, "idx": idx,
            "years": np.asarray(cal.year), "n": n}


def _dropped(S: dict, ids: np.ndarray, seed: int) -> np.ndarray:
    if seed == 0:
        return np.zeros(len(ids), bool)
    A = S["A"]
    return np.array([E.unit(seed, A["sym"][k], int(A["t_ev"][k]), int(A["cfg"][k]), "51drop") < DROP for k in ids])


def _half(sym: str) -> int:
    return int(E.unit(sym, "51half") < 0.5)


def ensemble(per_seed: dict) -> dict:
    out = {}
    for sample in next(iter(per_seed.values())):
        z = [per_seed[s][sample] for s in sorted(per_seed)]
        r = np.array([x["p_ruin"] for x in z])
        out[sample] = {"med": float(np.mean([x["med"] for x in z])), "ruin": float(r.mean()),
                       "ruin90": float(np.quantile(r, 0.9)), "p10": float(np.mean([x["p10"] for x in z])),
                       "p_loss": float(np.mean([x["p_loss"] for x in z])), "med0": z[0]["med"], "ruin0": z[0]["p_ruin"]}
    return out


def book_returns(S: dict, members: list, mn: int, seed: int, loc_hot: float = E.LOC[2], borrow: float = 1.0,
                 unavail: dict | None = None, half: int | None = None) -> np.ndarray:
    """A book's daily returns at the five equity levels over the bootstrap window: members [(config, size)]."""
    A, TR = S["A"], S["TR"]
    un = E.UNAVAIL if unavail is None else unavail
    ids = np.concatenate([S["by_cfg"][c] for c, _ in members])
    rank = np.concatenate([np.full(len(S["by_cfg"][c]), r) for r, (c, _) in enumerate(members)])
    size = np.zeros(S["n"])
    for c, s in members:
        size[S["by_cfg"][c]] = s
    rate = np.array([un.get(int(k), 0.0) for k in A["tier"][ids]])
    ok = (A["side"][ids] > 0) | (A["lu"][ids] >= rate)
    ok &= ~_dropped(S, ids, seed)
    if half is not None:
        ok &= np.array([_half(s) == half for s in A["sym"][ids]])
    ids, rank = ids[ok], rank[ok]
    order = ids[np.lexsort((rank, A["m_in"][ids], A["t_in"][ids]))]
    return np.stack([E.account(TR, order, size, lv, mn, MAX_OPEN, S["T"], loc_hot, borrow)[S["pos"]]
                     for lv in E.LEVELS])


def evaluate(S: dict, members: list, mn: int, seeds=None, **kw) -> dict:
    cls = max(int(S["configs"][c]["cls"]) for c, _ in members)
    per_seed = {}
    for seed in SEEDS if seeds is None else seeds:
        Rb = book_returns(S, members, mn, seed, **kw)
        per_seed[seed] = {k: E.year_stats(*E.paths(Rb, ix, E.FIXED[cls])) for k, ix in S["idx"].items()}
    return ensemble(per_seed)


def _acc_job(task: tuple) -> tuple:
    c, s, mn = task
    S = _G["S"]
    return task, {name: evaluate(S, [(c, s)], mn, loc_hot=lh) for name, lh in TASKS.items()}


def cmd_account(args) -> int:
    S = load_selection(args.sel)
    _G["S"] = S
    tasks = [(c["id"], s, mn) for c in S["configs"] for s in SIZES for mn in NEWS]
    mine = tasks[args.shard::args.shards]
    out = {f"{c}|{s}|{mn}": r for (c, s, mn), r in _map(_acc_job, mine, args.procs)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"acc-{args.shard}.json").write_text(json.dumps(out), encoding="utf-8")
    print(f"{len(mine)} tasks", flush=True)
    return 0


def _eligible(r: dict) -> bool:
    return all(r[t]["early"]["ruin"] <= MAX_RUIN for t in TASKS)


def _read_json(folder: Path, pattern: str) -> dict:
    out = {}
    for p in sorted(folder.rglob(pattern)):
        out.update(json.loads(p.read_text(encoding="utf-8")))
    return out


def v50_members(configs: list[dict]) -> list[tuple[int, float]]:
    tags = {c["tag"]: c["id"] for c in configs if c["tag"]}
    return [(tags[f"v50:{t}"], s) for t, *_, s in V50 if f"v50:{t}" in tags]


def cmd_pick(args) -> int:
    res = _read_json(args.runs, "acc-*.json")
    best: dict[int, tuple] = {}
    for key, r in res.items():
        c, s, mn = key.split("|")
        if _eligible(r):
            med = r["base"]["early"]["med"]
            if int(c) not in best or med > best[int(c)][0]:
                best[int(c)] = (med, float(s), int(mn))
    singles = sorted(best, key=lambda c: -best[c][0])[:SINGLES]
    books = [[[[c, s] for c, s in zip(combo, sz)], mn] for k in (1, 2, 3) for combo in itertools.combinations(singles, k)
             for sz in itertools.product(BOOK_SIZES, repeat=k) for mn in NEWS]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "picks.json").write_text(json.dumps({"singles": [[c, *best[c]] for c in singles], "books": books}),
                                         encoding="utf-8")
    print(json.dumps({"eligible": len(best), "singles": len(singles), "books": len(books)}), flush=True)
    return 0


def _book_job(job: tuple) -> tuple:
    b, (members, mn) = job
    S = _G["S"]
    m = [(int(c), float(s)) for c, s in members]
    return b, {name: evaluate(S, m, int(mn), loc_hot=lh) for name, lh in TASKS.items()}


def cmd_books(args) -> int:
    S = load_selection(args.sel)
    _G["S"] = S
    books = json.loads((args.picks / "picks.json").read_text(encoding="utf-8"))["books"]
    mine = [(b, books[b]) for b in range(args.shard, len(books), args.shards)]
    out = {str(b): {"book": books[b], "res": r} for b, r in _map(_book_job, mine, args.procs)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"books-{args.shard}.json").write_text(json.dumps(out), encoding="utf-8")
    print(f"{len(mine)} books", flush=True)
    return 0


def cmd_pick2(args) -> int:
    res = _read_json(args.runs, "books-*.json")
    ok = sorted((b for b in res if _eligible(res[b]["res"])), key=lambda b: -res[b]["res"]["base"]["early"]["med"])
    rest = sorted((b for b in res if b not in set(ok)), key=lambda b: -res[b]["res"]["base"]["early"]["med"])
    top = [res[b]["book"] for b in (ok + rest)[:CONFIRM]]
    configs = json.loads((args.sel / "configs.json").read_text(encoding="utf-8"))
    v50 = v50_members(configs)
    confirm = [{"book": b, "kind": "top"} for b in top]
    if v50:
        confirm.append({"book": [[[c, s] for c, s in v50], V50_NEW], "kind": "v50"})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "confirm.json").write_text(json.dumps({"eligible": len(ok), "books": len(res), "confirm": confirm}),
                                           encoding="utf-8")
    print(json.dumps({"books": len(res), "eligible": len(ok), "confirm": len(confirm)}), flush=True)
    return 0


def _conf_job(job: tuple) -> tuple:
    name, members, mn, kw, seeds = job
    return name, evaluate(_G["S"], members, mn, seeds=seeds, **kw)


def cmd_confirm(args) -> int:
    S = load_selection(args.sel)
    _G["S"] = S
    todo = json.loads((args.picks / "confirm.json").read_text(encoding="utf-8"))["confirm"]
    args.out.mkdir(parents=True, exist_ok=True)
    if args.shard >= len(todo):
        (args.out / f"conf-{args.shard}.json").write_text("{}", encoding="utf-8")
        return 0
    item = todo[args.shard]
    members, mn = [(int(c), float(s)) for c, s in item["book"][0]], int(item["book"][1])
    jobs = [(t, members, mn, {"loc_hot": lh}, SEEDS_CONF) for t, lh in TASKS.items()]
    jobs += [(t, members, mn, kw, SEEDS_CONF) for t, kw in STRESS.items()]
    jobs += [(f"half{h}", members, mn, {"half": h}, (0,)) for h in (0, 1)]
    res = dict(_map(_conf_job, jobs, args.procs))
    Rb = book_returns(S, members, mn, 0)
    cls = max(int(S["configs"][c]["cls"]) for c, _ in members)
    eq, low = E.paths(Rb, np.arange(len(S["pos"]))[None, :], E.FIXED[cls])
    lv = list(E.LEVELS).index(5_000.0)
    yearly = {int(y): float(Rb[lv][S["years"] == y].sum()) for y in np.unique(S["years"])}
    out = {"book": item["book"], "kind": item["kind"], "res": res,
           "history": {"end": float(eq[0]), "low": float(low[0]), "yearly_at_5k": yearly}}
    (args.out / f"conf-{args.shard}.json").write_text(json.dumps({str(args.shard): out}), encoding="utf-8")
    print(json.dumps({"book": item["book"], "base": res["base"]["all"], "hot5": res["hot5"]["all"]}), flush=True)
    return 0


# ---------------------------------------------------------------- final

def _d(x) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"${x:,.0f}"


def _p(x) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{100 * x:.1f}%"


def _f(x, k: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{k}f}"


def choose(conf: dict) -> str | None:
    ok = [k for k, z in conf.items() if z.get("kind") == "top" and _eligible(z["res"])]
    return max(ok, key=lambda k: conf[k]["res"]["base"]["early"]["med"]) if ok else None


def cmd_final(args) -> int:
    reports = {r["group"]: r for r in (json.loads(p.read_text(encoding="utf-8"))
                                       for p in sorted(args.factory.rglob("report.json")))}
    reports = {g: reports[g] for g in GROUPS if g in reports}
    configs = json.loads((args.sel / "configs.json").read_text(encoding="utf-8"))
    picks = json.loads((args.picks / "picks.json").read_text(encoding="utf-8"))
    conf = _read_json(args.runs, "conf-*.json")
    pick2 = json.loads((args.picks / "confirm.json").read_text(encoding="utf-8"))
    name = {c["id"]: f"{c['group']} {c['entry']} {c['exit']} [{c['filter']}]" + (f" {c['tag']}" if c["tag"] else "")
            for c in configs}
    ans = choose(conf)
    met = None
    if ans is not None:
        r = conf[ans]["res"]
        met = all(r[t]["all"]["med"] >= TARGET and r[t]["all"]["ruin"] <= MAX_RUIN for t in TASKS)
    n_scored = sum(r["n_scored"] for r in reports.values())
    missing = [g for g in GROUPS if g not in reports]
    L = ["# v51 report: every small-cap setup on one-minute bars", "",
         f"Pre-registered in V51_PREREGISTRATION.md. Configurations scored: {n_scored:,} "
         f"({sum(r['n_pass'] for r in reports.values()):,} pass the vetoes)."
         + (f" Groups without a factory result: {', '.join(missing)}." if missing else ""), ""]
    if ans is None:
        L += ["**No answer: no confirmed book keeps ensemble ruin at or under 2.5% on 2018-2022 paths at base and "
              "HOT 5%.**", ""]
    else:
        z = conf[ans]
        b, h = z["res"]["base"], z["res"]["hot5"]
        L += [f"**{'MET' if met else 'NOT MET'}.** Answer: "
              + " + ".join(f"{name[int(c)]} at {100 * float(s):.0f}%" for c, s in z["book"][0])
              + f", {z['book'][1]} new a day.", "",
              f"- all paths: median {_d(b['all']['med'])}, ruin {_p(b['all']['ruin'])} (HOT 5%: {_d(h['all']['med'])},"
              f" {_p(h['all']['ruin'])})",
              f"- 2018-2022 paths: median {_d(b['early']['med'])}, ruin {_p(b['early']['ruin'])}; 2023+ paths: median "
              f"{_d(b['late']['med'])}, ruin {_p(b['late']['ruin'])}", ""]
    L += ["## Confirmed books", "", "| book | new | all med | all ruin | HOT5 med | HOT5 ruin | design med | later med |"
          " borrow x2 | locates never fail | half rates | half 0 | half 1 | history from $5k |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(conf, key=lambda k: -conf[k]["res"]["base"]["early"]["med"]):
        z = conf[k]
        r = z["res"]
        L.append("| " + ("**v50** " if z["kind"] == "v50" else "")
                 + "; ".join(f"{name[int(c)]} {100 * float(s):.0f}%" for c, s in z["book"][0])
                 + f" | {z['book'][1]} | {_d(r['base']['all']['med'])} | {_p(r['base']['all']['ruin'])} | "
                 f"{_d(r['hot5']['all']['med'])} | {_p(r['hot5']['all']['ruin'])} | {_d(r['base']['early']['med'])} | "
                 f"{_d(r['base']['late']['med'])} | {_d(r['borrow2']['all']['med'])} | "
                 f"{_d(r['loc_never']['all']['med'])} | {_d(r['loc_half']['all']['med'])} | "
                 f"{_d(r['half0']['all']['med'])} | {_d(r['half1']['all']['med'])} | {_d(z['history']['end'])} |")
    L += ["", f"v50's book in v51's terms is marked; v50 itself reported a median of {_d(V50_REF)}.", "",
          "## The 12 singles", "", "| configuration | design med (best size) | size | new |", "|---|---|---|---|"]
    L += [f"| {name[int(c)]} | {_d(m)} | {100 * s:.0f}% | {mn} |" for c, m, s, mn in picks["singles"]]
    L += ["", f"Books run: {len(picks['books']):,}; eligible: {pick2['eligible']:,}.", "",
          "## Each group's best configurations (factory, $1,000 reference size, TZC costs)", "",
          "| group | events | entry | exit | filters | score | trades | PF 2018-22 | PF 2023+ | worst |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for g, r in reports.items():
        for c in r["configs"]:
            L.append(f"| {g} | {r['events']:,} | {c['entry']} | {c['exit']} | {c['filter']} {c['tag']} | "
                     f"{_f(c['score'])} | {c.get('n', 0)} | {_f(c.get('design', {}).get('pf'))} | "
                     f"{_f(c.get('later', {}).get('pf'))} | {_p(c.get('worst'))} |")
    L += ["", "## Where the edge is: each entry's best exit unfiltered (2018-2022)", "",
          "| group | entry | best exit unfiltered | trades | PF 2018-22 | PF 2023+ | mean | best filtered score |",
          "|---|---|---|---|---|---|---|---|"]
    for g, r in reports.items():
        for en, z in r["entries"].items():
            tb = [t for t in z["table"] if t["score_all"] is not None]
            if not tb:
                continue
            t = max(tb, key=lambda t: t["score_all"])
            L.append(f"| {g} | {en} | {exit_name(t['x'])} | {t['n_d']} | {_f(t['pf_d'])} | {_f(t['pf_l'])} | "
                     f"{_p(t['mean_d'])} | {_f(t['best_score'])} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V51_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    summary = {"met": met, "answer": conf.get(ans), "confirmed": conf, "singles": picks["singles"],
               "books": len(picks["books"]), "eligible_books": pick2["eligible"], "n_scored": n_scored,
               "names": name, "groups": {g: {"events": r["events"], "counts": r["counts"], "configs": r["configs"]}
                                         for g, r in reports.items()}}
    (args.out / "v51_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n".join(L[:12]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("factory")
    c.add_argument("--group", required=True, choices=GROUPS)
    c.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    c.add_argument("--extras", type=Path, default=Path("outputs/v28/inputs"))
    c.add_argument("--data", type=Path, default=Path("outputs/v51"))
    c = sub.add_parser("select")
    c.add_argument("--factory", type=Path, required=True)
    for name in ("account", "books", "confirm"):
        c = sub.add_parser(name)
        c.add_argument("--sel", type=Path, required=True)
        c.add_argument("--shard", type=int, default=0)
        c.add_argument("--shards", type=int, default=1)
        if name != "account":
            c.add_argument("--picks", type=Path, required=True)
    c = sub.add_parser("pick")
    c.add_argument("--runs", type=Path, required=True)
    c = sub.add_parser("pick2")
    c.add_argument("--runs", type=Path, required=True)
    c.add_argument("--sel", type=Path, required=True)
    c = sub.add_parser("final")
    for k in ("factory", "sel", "picks", "runs"):
        c.add_argument(f"--{k}", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--procs", type=int, default=4)
    args = ap.parse_args()
    return {"factory": cmd_factory, "select": cmd_select, "account": cmd_account,
            "pick": cmd_pick, "books": cmd_books, "pick2": cmd_pick2, "confirm": cmd_confirm,
            "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v51"
    raise SystemExit(main())
