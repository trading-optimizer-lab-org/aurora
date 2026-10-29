"""v43: v39's best book replayed on one-minute bars, and a large minute grid (V43_PREREGISTRATION.md).

Every trade of the book is walked minute by minute with its shield's rules; the fills follow a realism case, the
account is rerun on the new returns and the broker's 15% liquidation is checked every minute.

  run    one shard of the 115,200 replays (rule x stop fill x participation x entry fill), each through the account
         at the three liquidation fills and the four cost sets: each year's log growth and worst drawdown
  final  the walk-forward picks per realism case, the bootstrap of the central and daily-like cases, V43_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DV = _script("run_v43_data")  # the shield path that records each trade's facts (DV.META)
R40 = DV.R40
R36, R35, R33, R29, R14 = R40.R36, R40.R35, R40.R33, R40.R29, R40.R14
R31, R32, A = R36.R31, R36.R32, R36.A
sh, v19 = DV.sh, R33.sh.v19
LEVELS = R35.LEVELS
LEVEL = R40.LEVEL
TASKS = R40.TASKS
THETA = R31.THETA
QUICK = R29.QUICK

DELAYS = (0, 1, 5, 15, 30)
STOPX: tuple[float | None, ...] = (0.75, 1.0, 1.25, 1.5, None)
FLATS: tuple[str | int, ...] = ("hold", "close", 955, 945)  # 955 / 945: the session steps of 15:55 / 15:45
COVERS: tuple[float | None, ...] = (None, 0.10, 0.20, 0.30)
TRAILS: tuple[float | None, ...] = (None, 0.10, 0.20)
SIZEX = (0.75, 1.0, 1.25)
RDIMS = (DELAYS, STOPX, FLATS, COVERS, TRAILS, SIZEX)
RSHAPE = tuple(len(d) for d in RDIMS)
NR = int(np.prod(RSHAPE))
BASE_RULE = int(np.ravel_multi_index((0, 1, 0, 0, 0, 1), RSHAPE))
FILLS = ("slip", "next_open", "next_vwap", "next_high")
PARTS: tuple[float | None, ...] = (None, 0.20, 0.10, 0.05)
LIQS = ("threshold", "next_vwap", "next_high")
EFILLS = ("auction", "vwap")
USHAPE = (NR, len(FILLS), len(PARTS), len(EFILLS))
NU = int(np.prod(USHAPE))
CENTRAL = (FILLS.index("next_open"), PARTS.index(0.10), LIQS.index("next_vwap"), EFILLS.index("auction"))
DAILY = (FILLS.index("slip"), PARTS.index(None), LIQS.index("threshold"), EFILLS.index("auction"))
GAIN, MAX_RUIN, SURVIVE_MED, SURVIVE_RUIN = 1.15, 0.025, 15_000.0, 0.02
E2K = 2_000.0
OPEN, LAST, AH = 570, 959, 240  # session steps: 09:30, 15:59 (the close at 16:00 is filled on it), 04:00
HALT_GAP, HALT_JUMP = 5, 0.10

_G: dict = {"bars": {}, "tl": {}, "count": {}}


def rule_of(rid: int) -> tuple:
    return tuple(d[i] for d, i in zip(RDIMS, np.unravel_index(rid, RSHAPE)))


def rule_name(rid: int) -> str:
    d, s, f, c, t, x = rule_of(rid)
    return (f"delay {d}, stop {'none' if s is None else f'x{s}'}, flat {f}, cover {c or 'none'}, "
            f"trail {t or 'none'}, size x{x}")


def _count(key: str, n: int = 1) -> None:
    _G["count"][key] = _G["count"].get(key, 0) + n


# ---------------------------------------------------------------- the bars

def load_bars(folder: Path, D: dict) -> None:
    """The minute store as {(row, column): (minute, o, h, l, c, v, vw)} on raw prices."""
    row = {str(d.date()): u for u, d in enumerate(D["dates"])}
    col = {str(c): j for j, c in enumerate(D["cols"])}
    out = {}
    for p in sorted(folder.glob("*.parquet")):
        u = row.get(p.stem)
        if u is None:
            continue
        df = pd.read_parquet(p)
        for sym, g in df.groupby("symbol", sort=False):
            j = col.get(str(sym))
            if j is not None:
                out[(u, j)] = tuple(g[k].to_numpy(np.float64) if k != "minute" else g[k].to_numpy(np.int64)
                                    for k in ("minute", "o", "h", "l", "c", "v", "vw"))
    _G["bars"] = out
    _G["tl"] = {}
    for u, j in out:  # built once before the workers fork, so they share them
        timeline(u, j)


def timeline(u: int, j: int) -> dict | None:
    """Session u of column j on 960 steps, split-adjusted: steps 0-239 the after-hours of session u - 1 (16:00-19:59),
    240-959 session u from 04:00 to 15:59. None when session u has no bars."""
    key = (u, j)
    if key in _G["tl"]:
        return _G["tl"][key]
    D = _G["D"]
    F = D["F"]
    b = _G["bars"].get((u, j))
    out = None
    if b is not None:
        out = {k: np.full(960, np.nan) for k in ("o", "h", "l", "c", "v", "vw")}
        for src, lo, hi, shift, uu in ((_G["bars"].get((u - 1, j)), 720, 960, -720, u - 1), (b, 0, 720, AH, u)):
            if src is None or uu < 0:
                continue
            f = float(F[uu, j])
            if not np.isfinite(f) or f <= 0:
                continue
            m = src[0]
            keep = (m >= lo) & (m < hi)
            s = m[keep] + shift
            for k, a in zip(("o", "h", "l", "c", "v", "vw"), src[1:]):
                out[k][s] = a[keep] * (f if k != "v" else 1.0)
        vw = out["vw"]
        out["vw"] = np.where(np.isfinite(vw), vw, out["c"])
        if not np.isfinite(out["o"][OPEN:]).any():
            out = None
    _G["tl"][key] = out
    return out


def synthetic(u: int, j: int) -> dict:
    """A session without bars: its daily open at 09:30 and its daily range in the next step, unlimited volume."""
    D = _G["D"]
    out = {k: np.full(960, np.nan) for k in ("o", "h", "l", "c", "v", "vw")}
    o, h, lo, c = (float(D[k][u, j]) for k in ("O", "H", "L", "C"))
    o = o if np.isfinite(o) else c
    for k, v in (("o", o), ("h", o), ("l", o), ("c", o), ("v", np.inf), ("vw", o)):
        out[k][OPEN] = v
    for k, v in (("o", o), ("h", h), ("l", lo), ("c", c), ("v", np.inf), ("vw", (o + c) / 2)):
        out[k][OPEN + 1] = v
    return out


# ---------------------------------------------------------------- fills

def market(B: dict, k: int, hi: int, level: float | None, how: str, n: float, q: float | None,
           rest: tuple[int, float]) -> list[tuple[int, float, float]]:
    """A buy to cover set off on bar k: [(step, part, price)], the parts summing to 1. Under `slip` the first part
    fills on bar k (its open if past `level`, else level + 25% of the way to its high; a time exit at its open;
    `close` at its close), the rest at later bars' opens; else from the next bar on at each bar's open, VWAP or high.
    A bar takes at most q of its volume (n shares in all); what is left by bar hi fills at `rest` (an auction)."""
    o = B["o"]
    first = k if how in ("slip", "close") else k + 1
    steps = np.flatnonzero(np.isfinite(o[first:hi + 1])) + first
    out: list[tuple[int, float, float]] = []
    left = 1.0
    for s in steps:
        if s == k and how == "slip":
            px = o[s] if level is None or o[s] >= level else v19._slip(level, B["h"][s])
        elif s == k:
            px = B["c"][s]
        elif how in ("slip", "close", "next_open"):
            px = o[s]
        else:
            px = B["vw"][s] if how == "next_vwap" else B["h"][s]
        part = left if q is None else min(left, q * B["v"][s] / max(n, 1e-9))
        if part > 0:
            if not out and s > k:
                prev = np.flatnonzero(np.isfinite(o[:s]))
                if len(prev) and s - prev[-1] >= HALT_GAP and abs(o[s] / B["c"][prev[-1]] - 1) >= HALT_JUMP:
                    _count("fills_after_halt")
            out.append((int(s), float(part), float(px)))
            left -= part
        if left <= 1e-12:
            return out
    if q is not None and out:
        _count("fills_cut_by_cap")
    out.append((rest[0], left, rest[1]))
    return out


def limit(B: dict, k: int, hi: int, level: float, n: float, q: float | None,
          rest: tuple[int, float]) -> list[tuple[int, float, float]]:
    """A resting buy limit at `level` from bar k: each bar trading at or under it fills at the better of its open and
    the level (at most q of its volume); what is left by bar hi fills at `rest`."""
    o, lo = B["o"], B["l"]
    steps = np.flatnonzero(np.isfinite(o[k:hi + 1]) & (lo[k:hi + 1] <= level)) + k
    out, left = [], 1.0
    for s in steps:
        part = left if q is None else min(left, q * B["v"][s] / max(n, 1e-9))
        if part > 0:
            out.append((int(s), float(part), float(min(o[s], level))))
            left -= part
        if left <= 1e-12:
            return out
    out.append((rest[0], left, rest[1]))
    return out


def _first(mask: np.ndarray) -> int:
    k = np.flatnonzero(mask)
    return int(k[0]) if len(k) else 10_000


# ---------------------------------------------------------------- one trade

def replay(it: dict, m: dict, rule: tuple, fill: str, part: float | None, efill: str, exe=None, xmask=None,
           half: bool = False, stopf=None, pmx=None, xclose: int | None = None) -> dict | None:
    """The trade walked minute by minute: its sessions, gross return a session and minute marks (gain since the
    last close, part open, market value, all per unit of weight on the entry price); None when it does not fill.
    v44's hooks: ``exe(it, m, e, es)`` -> (e, es) or None re-prices the entry; ``xmask(B, u, j, e)`` -> a mask over
    the 960 steps of an emergency cover set off at a bar's close; ``half`` covers half at an open entry's first
    close. v46's hooks: a close entry's ``exe`` may return an after-hours step (0-239 of the next session's
    timeline) as its entry step; ``stopf(it, m, e, es, S)`` -> the stop level; ``pmx(B, u, j, e, ref, lo)`` -> the step
    (lo to 569) of a cover set off before the open of a carried session, or None. v47's hook: ``xclose`` sends a
    cover at a close as a market order set off the minute before that step instead of the closing auction."""
    D = _G["D"]
    O, C, new = D["O"], D["C"], D["new"]
    T = C.shape[0]
    delay, stopx, flat, cover, trail, size = rule
    t, j, kind = int(it["t"]), int(it["j"]), m["kind"]
    assert it["side"] < 0
    n_sh = it["w"] * size * LEVEL / max(float(it["price"]), 0.01)
    e0 = float(it["entry"])
    if kind == "open":
        B = timeline(t, j)
        lim = m.get("lim", np.nan)
        lvl = float(C[t - 1, j]) * (1 + lim) if np.isfinite(lim) and t > 0 else None
        e, es = e0, OPEN
        if B is None:
            _count("no_bars_entry")
        elif lvl is None and (delay or efill == "vwap"):
            s = _first(np.isfinite(B["o"][OPEN + delay:])) + OPEN + delay
            if s > LAST:
                _count("entry_not_filled")
                return None
            e, es = (float(B["o"][s]) if efill == "auction" else float(B["vw"][s])), s
        elif lvl is not None and not (delay == 0 and float(O[t, j]) >= lvl):
            lo = OPEN + delay
            seg_o, seg_h = B["o"][lo:], B["h"][lo:]
            s = _first(np.isfinite(seg_o) & ((seg_o >= lvl) | (seg_h >= lvl * (1 + R33.FILL_THROUGH)))) + lo
            if s > LAST:
                _count("entry_not_filled")
                return None
            e, es = (float(B["o"][s]) if B["o"][s] >= lvl else lvl), s
        first = t
    else:
        e, es, first = e0, -1, t + 1
    if exe is not None:
        got = exe(it, m, e, es)
        if got is None:
            _count("entry_not_filled")
            return None
        e, es = got
    S = float(m["stop"]) * e / e0 if np.isfinite(m["stop"]) else np.inf
    S = np.inf if stopx is None else e + stopx * (S - e)
    if stopf is not None:
        S = float(stopf(it, m, e, es, S))
    catl = e * (1 + m["cat"]) if np.isfinite(m.get("cat", np.nan)) else np.inf
    tg = m.get("target", "none")
    tgl = e * (1 - int(tg[1:]) / 100) if tg != "none" else -np.inf
    cvl = e * (1 - cover) if cover else -np.inf
    closes = sh.HOLD[m["hold"]]
    fr = sh.fractions(m["scale"], closes + 1)
    sess = list(range(first, min(first + closes + 1, T)))
    if flat != "hold":
        sess = sess[:1]
    live = {"ah": m["ext"] in ("ah", "both"), "pm": m["ext"] in ("pm", "both")}
    rally = m["rally"]
    q, ref, low = 1.0, e, np.inf
    flag = False
    rec = {"u": [], "g": [], "G": [], "Q": [], "M": [], "es": es, "kind": kind, "t": t, "j": j, "e": e,
           "n": n_sh, "nights": 0}
    for i, u in enumerate(sess):
        if new[u, j] or not np.isfinite(C[u, j]):
            break
        B = timeline(u, j)
        if B is None:
            _count("no_bars_session")
            B = synthetic(u, j)
        c_u = float(C[u, j])
        o_u = float(O[u, j]) if np.isfinite(O[u, j]) else c_u
        carried = not (kind == "open" and i == 0)
        if carried:
            rec["nights"] += 1
        ev: list[tuple[int, float, float]] = []  # (step, part of the original position, price)
        done = False
        Bo, Bh, Bl, Bc = B["o"], B["h"], B["l"], B["c"]
        lo0 = es if (i == 0 and kind != "open" and es >= 0) else 0  # an after-hours entry: its bars from es
        if carried and (live["ah"] or live["pm"] or rally != "none" or pmx is not None):
            st = np.arange(OPEN)
            ok = np.isfinite(Bo[:OPEN]) & (st >= lo0)
            on = np.where(st < AH, live["ah"], live["pm"])
            ks = _first(ok & on & (Bh[:OPEN] >= S))
            kr = _first(ok & (Bc[:OPEN] >= ref * (1 + int(rally[1:]) / 100))) if rally != "none" else 10_000
            kp = pmx(B, u, j, e, ref, lo0) if pmx is not None else None
            kp = 10_000 if kp is None or not lo0 <= kp < OPEN else int(kp)
            if kp < min(ks, kr):
                f = market(B, kp, OPEN - 1, None, "next_open" if fill == "slip" else fill, n_sh * q, part,
                           (OPEN, o_u))
                ev += [(s, p * q, px) for s, p, px in f]
                rec.setdefault("pmx", []).append((len(rec["u"]), q, kp))  # (session index, part, step)
                done = True
            elif min(ks, kr) < OPEN:
                if ks <= kr:
                    how = ("next_open" if m.get("ext_delay") else "slip") if fill == "slip" else fill
                    f = market(B, ks, OPEN - 1, S, how, n_sh * q, part, (OPEN, o_u))
                else:
                    f = market(B, kr, OPEN - 1, None, "close" if fill == "slip" else fill, n_sh * q, part,
                               (OPEN, o_u))
                ev += [(s, p * q, px) for s, p, px in f]
                done = True
        trail_now = low * (1 + trail) if trail and low <= e * (1 - trail) else np.inf
        if not done and carried and (flag or o_u >= min(S, trail_now) or o_u <= tgl or o_u <= cvl):
            ev.append((OPEN, q, o_u))  # the open auction: the emergency cover, a stop or a cover level gapped past
            done = True
        if not done:
            lo_s = max(es, OPEN) if not carried else OPEN
            seg = slice(lo_s, LAST + 1)
            ok = np.isfinite(Bo[seg])
            lows = np.where(ok, Bl[seg], np.inf)
            run = np.minimum.accumulate(np.r_[low, lows])[:-1]  # the lowest low before each bar
            S_eff = np.full(len(lows), S)
            if trail:
                S_eff = np.minimum(S, np.where(run <= e * (1 - trail), run * (1 + trail), np.inf))
            k_stop = _first(ok & (Bh[seg] >= S_eff))
            k_tg = _first(ok & (Bl[seg] <= tgl))
            k_cv = _first(ok & (Bl[seg] <= cvl))
            k_time = _first(ok & (np.arange(lo_s, LAST + 1) >= flat)) if isinstance(flat, int) else 10_000
            k_x = _first(ok & xmask(B, u, j, e)[seg]) if xmask is not None else 10_000
            k = min(k_time, k_stop, k_tg, k_cv, k_x)
            if k < 10_000:
                s0 = lo_s + k
                rest = (LAST, c_u)
                if k == k_time:
                    f = market(B, s0, LAST, None, "slip" if fill == "slip" else fill, n_sh * q, part, rest)
                elif k == k_stop:
                    f = market(B, s0, LAST, float(S_eff[k]), fill, n_sh * q, part, rest)
                elif k == k_x:
                    f = market(B, s0, LAST, None, "next_open" if fill == "slip" else fill, n_sh * q, part, rest)
                else:
                    f = limit(B, s0, LAST, tgl if k == k_tg else cvl, n_sh * q, part, rest)
                ev += [(s, p * q, px) for s, p, px in f]
                done = True
            low = min(low, float(np.min(lows[:k + 1] if k < 10_000 else lows, initial=np.inf)))
        if not done:
            cut = q if i == len(sess) - 1 else min(fr[i], q)
            if half and i == 0 and kind == "open":
                cut = min(q, max(cut, 0.5))
            if cut > 0 and xclose is not None:
                how = "next_open" if fill == "slip" else fill
                ev += [(s, p * cut, px) for s, p, px in market(B, xclose - 1, LAST, None, how, n_sh * cut, part,
                                                               (LAST, c_u))]
            elif cut > 0:
                ev.append((LAST, cut, c_u))
        # the marks
        Q = np.zeros(960)
        start = es if not carried else lo0
        Q[start:] = q
        real = np.zeros(960)
        for s, p, px in ev:
            Q[s:] -= p
            real[s:] += p * (ref - px) / e
        Q = np.maximum(Q, 0.0)
        P = pd.Series(Bc).ffill().to_numpy()
        P = np.where(np.isfinite(P), P, ref)
        P[:start] = ref
        P[LAST] = c_u
        G = real + Q * (ref - P) / e
        rec["u"].append(u)
        rec["g"].append(float(G[LAST]))
        rec["G"].append(G)
        rec["Q"].append(Q)
        rec["M"].append(Q * P / e)
        q = float(Q[LAST])
        if q <= 1e-12:
            break
        ref = c_u
        flag = c_u >= catl
    if not rec["u"]:
        return None
    if kind == "close" or len(rec["u"]) > 1:
        rec["nights"] = len(rec["u"]) - (kind == "open")
    return rec


# ---------------------------------------------------------------- the account

def items_for(its: list[dict], metas: list[dict], rule: tuple, fill: str, part: float | None,
              efill: str) -> tuple[list[dict], list[dict]]:
    """The trades with their minute returns (the daily cost charged on the first session) for the joint account."""
    out, recs = [], []
    size = rule[5]
    for k, (it, m) in enumerate(zip(its, metas)):
        rec = replay(it, m, rule, fill, part, efill)
        if rec is None:
            continue
        c0 = float(it["raw0"]) - float(it["r"][0])
        r = np.array(rec["g"], float)
        r[0] -= c0
        rec["cost"] = c0 + float(it.get("loc", 0.0))
        recs.append(rec)
        out.append({**it, "r": r, "raw0": rec["g"][0], "i0": rec["u"][0], "w": it["w"] * size,
                    "nights": rec["nights"], "_rec": len(recs) - 1})
    return out, recs


def liquidate(taken: list[dict], recs: list[dict], T: int, liq: str, part: float | None) -> np.ndarray:
    """The account's sessions with the broker's rule checked every minute."""
    rows: dict[int, list[tuple[int, int]]] = {}
    for p, it in enumerate(taken):
        for i, u in enumerate(recs[it["_rec"]]["u"]):
            rows.setdefault(u, []).append((p, i))
    entry_close: dict[int, list[int]] = {}
    for p, it in enumerate(taken):
        rec = recs[it["_rec"]]
        if rec["kind"] == "close":
            entry_close.setdefault(rec["t"], []).append(p)
    alive = np.ones(len(taken), bool)
    out = np.zeros(T)
    for u in sorted(rows):
        live = [(p, i) for p, i in rows[u] if alive[p]]
        if not live:
            continue
        E, M = np.ones(960), np.zeros(960)
        parts = []
        for p, i in live:
            rec, w = recs[taken[p]["_rec"]], float(taken[p]["w"])
            G = rec["G"][i].copy()
            if i == 0:
                G[max(rec["es"], 0):] -= rec["cost"]
            E += w * G
            M += w * rec["M"][i]
            parts.append((p, i, rec, w, G))
        hit = (M > 0) & (E <= THETA * M)
        if not hit.any():
            out[u] = float(E[LAST] - 1)
            continue
        k = int(np.flatnonzero(hit)[0])
        _count("liquidations")
        if liq == "threshold":
            if k > 0 and E[k - 1] > THETA * M[k - 1]:
                lam = (E[k - 1] - THETA * M[k - 1]) / ((E[k - 1] - E[k]) - THETA * (M[k - 1] - M[k]))
                out[u] = float(E[k - 1] + lam * (E[k] - E[k - 1]) - 1)
            else:
                out[u] = float(E[k] - 1)
        else:
            tot = 0.0
            for p, i, rec, w, G in parts:
                Qk = float(rec["Q"][i][k])
                if Qk <= 1e-12:
                    tot += w * G[k]
                    continue
                B = timeline(u, rec["j"]) or synthetic(u, rec["j"])
                Pk = float(rec["M"][i][k] / Qk * rec["e"])
                f = market(B, k, LAST, None, liq, rec["n"] * Qk, part, (LAST, float(_G["D"]["C"][u, rec["j"]])))
                px = sum(a * b for _, a, b in f)
                tot += w * (G[k] + Qk * (Pk - px) / rec["e"])
            out[u] = tot
        for p, _ in rows[u]:
            alive[p] = False
        for p in entry_close.get(u, []):
            alive[p] = False
    return out


def book(its: list[dict], metas: list[dict], rule: tuple, fill: str, part: float | None, efill: str,
         liqs: tuple[str, ...] = LIQS) -> list[np.ndarray]:
    D = _G["D"]
    items, recs = items_for(its, metas, rule, fill, part, efill)
    s, taken = A.joint(items, D["dates"], R33.GROSS, R33.MAX_OPEN, R33.MAX_NEW, "move", "none", "tzi", 0.0, 0.0,
                       None, None, None)
    return [liquidate(taken, recs, len(D["dates"]), liq, part) for liq in liqs]


# ---------------------------------------------------------------- setup and the stages

def capture(rows: list[dict], level: float, task: str) -> tuple[list[dict], list[dict]]:
    """The book's trades at a level and cost set, with each trade's shield facts."""
    DV.META.clear()
    its = R40.book_its(rows, float(level), **R33.TASKS[task])
    metas = [DV.META[(int(it["t"]), int(it["j"]), float(it["prio"]))] for it in its]
    return its, metas


def setup(args, levels=(LEVEL,)) -> None:
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    D = R14._G["D"]
    _G["D"] = D
    rows = R35._rows(args)
    _G["its"] = {(float(lv), task): capture(rows, lv, task) for lv in levels for task in TASKS}
    load_bars(args.data / "minutes", _G["D"])
    cal, pos = R29._cal()
    _G.update(pos=pos, years=np.asarray(cal.year), ys=sorted(set(int(y) for y in cal.year)), cal=cal)


def _unit(uid: int) -> np.ndarray:
    rid, fi, pi, ei = np.unravel_index(uid, USHAPE)
    rule = rule_of(int(rid))
    S = np.full((len(LIQS), len(TASKS), len(_G["ys"]), 2), np.nan, np.float32)
    for ti, task in enumerate(TASKS):
        its, metas = _G["its"][(LEVEL, task)]
        for li, r in enumerate(book(its, metas, rule, FILLS[fi], PARTS[pi], EFILLS[ei])):
            S[li, ti] = R40.year_stats(r[_G["pos"]], _G["years"], _G["ys"])
    return S


def units(shard: int, shards: int) -> list[int]:
    u = list(range(shard, NU, shards))
    if QUICK:
        base = [int(np.ravel_multi_index((BASE_RULE, f, p, e), USHAPE)) for f, p, e in
                ((CENTRAL[0], CENTRAL[1], CENTRAL[3]), (DAILY[0], DAILY[1], DAILY[3]))]
        u = sorted(set(u[:4]) | (set(base) if shard == 0 else set()))
    return u


def cmd_run(args) -> int:
    setup(args)
    uids = units(args.shard, args.shards)
    t0 = time.time()
    with mp.get_context("fork").Pool(args.procs) as pool:
        S = np.stack(pool.map(_unit, uids, chunksize=4))
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / f"part_{args.shard}.npz", uids=np.array(uids, np.int64), S=S,
                        ys=np.array(_G["ys"]))
    each = (time.time() - t0) / max(len(uids), 1) * args.procs
    print(args.shard, len(uids), "units", f"{each:.2f} cpu-s each", flush=True)
    return 0


def walk_forward(G: np.ndarray, DD: np.ndarray, ys: list[int]) -> dict[int, int]:
    """For each year after the first: among the rules whose worst yearly drawdown before it is no worse than the
    shield's rule's, the highest log growth summed over the years before."""
    picks = {ys[0]: BASE_RULE}
    for k in range(1, len(ys)):
        g = np.nansum(G[:, :k], axis=1)
        dd = np.nanmin(DD[:, :k], axis=1)
        ok = np.isfinite(G[:, :k]).all(axis=1) & np.isfinite(dd)
        elig = ok & (dd >= dd[BASE_RULE] - 1e-12)
        picks[ys[k]] = int(np.flatnonzero(elig)[np.argmax(g[elig])])
    return picks


def _read(runs: Path) -> tuple[np.ndarray, list[int], int]:
    S, ys, n = None, None, 0
    for p in sorted(runs.rglob("part_*.npz")):
        z = np.load(p)
        if S is None:
            ys = [int(y) for y in z["ys"]]
            S = np.full((NU, len(LIQS), len(TASKS), len(ys), 2), np.nan, np.float32)
        S[z["uids"]] = z["S"]
        n += len(z["uids"])
    assert S is not None and ys is not None, "no parts"
    return S.reshape(USHAPE + S.shape[1:]), ys, n


def _stream(job: tuple) -> tuple[tuple, np.ndarray]:
    """(level, task, rule, fill, part, efill) -> the three liquidation fills' daily returns on the calendar."""
    level, task, rid, fi, pi, ei = job
    its, metas = _G["its"][(level, task)]
    global LEVEL
    LEVEL = level
    rs = book(its, metas, rule_of(rid), FILLS[fi], PARTS[pi], EFILLS[ei])
    return job, np.stack([r[_G["pos"]] for r in rs])


def boot(Rb: np.ndarray, idx: dict, e0: float = R29.E0, levels: np.ndarray = LEVELS) -> dict:
    keep = R32.LEVELS
    R32.LEVELS = levels
    try:
        out = {}
        for sample, ix in idx.items():
            eq, low = R32.paths(Rb, Rb, ix, R35.FIXED, None, e0)
            q = np.sort(eq)
            out[sample] = {**R29.year_stats(eq, low, e0), "es5": float(q[:max(1, int(0.05 * len(q)))].mean())}
        return out
    finally:
        R32.LEVELS = keep


def cmd_final(args) -> int:
    S, ys, n = _read(args.runs)
    lv2 = np.r_[E2K, LEVELS]
    setup(args, levels=tuple(float(x) for x in lv2))
    cal = _G["cal"]
    idx = R32._sub_idx(cal)
    years = _G["years"]
    picks, hist = {}, {}
    for fi in range(len(FILLS)):
        for pi in range(len(PARTS)):
            for li in range(len(LIQS)):
                for ei in range(len(EFILLS)):
                    G = S[:, fi, pi, ei, li, 0, :, 0].astype(float)
                    DDm = S[:, fi, pi, ei, li, 0, :, 1].astype(float)
                    if not np.isfinite(G[BASE_RULE]).all():
                        continue
                    pk = walk_forward(G, DDm, ys)
                    picks[(fi, pi, li, ei)] = pk
                    wf = sum(float(G[pk[y], k]) for k, y in enumerate(ys))
                    hist[(fi, pi, li, ei)] = {"wf": wf, "base": float(np.nansum(G[BASE_RULE]))}
    jobs = [(float(lv), task, BASE_RULE, fi, pi, ei) for lv in lv2 for task in TASKS for fi in range(len(FILLS))
            for pi in range(len(PARTS)) for ei in range(len(EFILLS))]
    for case in (CENTRAL, DAILY):
        for rid in set(picks.get(case, {}).values()) - {BASE_RULE}:
            jobs += [(float(lv), task, rid, case[0], case[1], case[3]) for lv in lv2 for task in TASKS]
    _G["count"] = {}
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = dict(pool.map(_stream, jobs, chunksize=2))
    lv_i = {float(lv): k for k, lv in enumerate(lv2)}

    def stack(task: str, rid: int, fi: int, pi: int, li: int, ei: int) -> np.ndarray:
        return np.stack([got[(float(lv), task, rid, fi, pi, ei)][li] for lv in lv2])

    def series(task: str, case: tuple, wf: bool) -> np.ndarray:
        fi, pi, li, ei = case
        R = stack(task, BASE_RULE, fi, pi, li, ei)
        if wf:
            for y, rid in picks[case].items():
                R[:, years == y] = stack(task, rid, fi, pi, li, ei)[:, years == y]
        return R

    q1 = {}
    for fi in range(len(FILLS)):
        for pi in range(len(PARTS)):
            for li in range(len(LIQS)):
                for ei in range(len(EFILLS)):
                    q1[(fi, pi, li, ei)] = {t: boot(series(t, (fi, pi, li, ei), False)[1:], {"all": idx["all"]})
                                            ["all"] for t in TASKS}
    res = {}
    for case in (CENTRAL, DAILY):
        res[case] = {t: {"base": boot(series(t, case, False)[1:], idx if t == "base" else {"all": idx["all"]}),
                         "wf": boot(series(t, case, True)[1:], idx if t == "base" else {"all": idx["all"]})}
                     for t in TASKS}
    two = {b: boot(series("base", CENTRAL, b == "wf"), {"all": idx["all"]}, E2K, lv2)["all"]
           for b in ("base", "wf")}
    c = q1[CENTRAL]["base"]
    survive = bool(c["med"] >= SURVIVE_MED and c["p_ruin"] <= SURVIVE_RUIN)
    rc = res[CENTRAL]
    improved = bool(rc["base"]["wf"]["all"]["med"] >= GAIN * rc["base"]["base"]["all"]["med"]
                    and rc["base"]["wf"]["all"]["p_ruin"] <= MAX_RUIN and rc["hot5"]["wf"]["all"]["p_ruin"] <= MAX_RUIN
                    and rc["high"]["wf"]["all"]["med"] >= rc["high"]["base"]["all"]["med"])
    beats = sum(1 for h in hist.values() if h["wf"] > h["base"])
    d = R35._d

    def cname(case: tuple) -> str:
        fi, pi, li, ei = case
        return f"{FILLS[fi]} / {'no cap' if PARTS[pi] is None else f'{PARTS[pi]:.0%}'} / {LIQS[li]} / {EFILLS[ei]}"

    L = ["# v43: v39's best book replayed on one-minute bars, and a large minute grid", "",
         f"{n:,} of {NU:,} replays computed ({n * len(LIQS) * len(TASKS):,} books); {R29.PATHS} one-year bootstrap "
         "paths from $5,000; ruin = at or under $1,250 at any time.", "", "## Q1. Does the book survive the minute "
         "replay?", "", f"**{survive}** (central case `{cname(CENTRAL)}`, base costs: median >= $15,000 and ruin <= "
         "2%).", "", "| case | base median | base ruin | HOT 5% median | HOT 5% ruin | high median | high ruin |",
         "|---|---|---|---|---|---|---|"]
    for case, st in sorted(q1.items(), key=lambda kv: -kv[1]["base"]["med"]):
        tag = " **(central)**" if case == CENTRAL else " *(daily-like)*" if case == DAILY else ""
        L.append(f"| {cname(case)}{tag} | {d(st['base']['med'])} | {st['base']['p_ruin']:.1%} | "
                 f"{d(st['hot5']['med'])} | {st['hot5']['p_ruin']:.1%} | {d(st['high']['med'])} | "
                 f"{st['high']['p_ruin']:.1%} |")
    L += ["", "v39's daily book for reference: median $23,143, ruin 0.1%.", "",
          "## Q2. Do minute rules improve the book?", "", f"**{improved}** (central case: walk-forward median >= "
          f"{GAIN} x the shield's rule's, ruin <= 2.5% at base and HOT 5%, high-cost median >= the shield's rule's).",
          "", "| case | book | costs | all median | all ruin | p10 | 2018-22 median | 2023+ median |",
          "|---|---|---|---|---|---|---|---|"]
    for case in (CENTRAL, DAILY):
        for b in ("base", "wf"):
            for t in TASKS:
                st = res[case][t][b]
                a = st["all"]
                L.append(f"| {cname(case)} | {'shield rule' if b == 'base' else 'walk-forward'} | {t} | "
                         f"{d(a['med'])} | {a['p_ruin']:.1%} | {d(a['p10'])} | "
                         f"{d(st['early']['med']) if 'early' in st else '-'} | "
                         f"{d(st['late']['med']) if 'late' in st else '-'} |")
    L += ["", f"In {beats} of {len(hist)} realism cases the walk-forward choice beats the shield's rule on the "
          "historical path ($10,000 level, base costs, summed log growth).", "", "Central-case picks:", ""]
    for y, rid in picks.get(CENTRAL, {}).items():
        L.append(f"- {y}: {rule_name(rid)}")
    G = S[:, CENTRAL[0], CENTRAL[1], CENTRAL[3], CENTRAL[2], 0, :, 0].astype(float)
    DDm = S[:, CENTRAL[0], CENTRAL[1], CENTRAL[3], CENTRAL[2], 0, :, 1].astype(float)
    ok = np.isfinite(G).all(axis=1)
    gall = np.where(ok, G.sum(axis=1), -np.inf)
    dmin = np.where(ok, DDm.min(axis=1), -np.inf)
    elig = ok & (dmin >= dmin[BASE_RULE] - 1e-12)
    top = np.flatnonzero(elig)[np.argsort(-gall[elig])[:10]]
    L += ["", "Top fixed rules in the central case (in-sample, all years, chosen after the fact):", "",
          "| rule | log growth | worst yearly drawdown |", "|---|---|---|",
          f"| shield rule | {gall[BASE_RULE]:.2f} | {dmin[BASE_RULE]:.1%} |"]
    L += [f"| {rule_name(int(r))} | {gall[r]:.2f} | {dmin[r]:.1%} |" for r in top]
    L += ["", "## Q3. From $2,000 (central case, base costs; ruin = at or under $500)", "",
          "| book | median | ruin | p10 | -50% |", "|---|---|---|---|---|"]
    for b, st in two.items():
        L.append(f"| {'shield rule' if b == 'base' else 'walk-forward'} | {d(st['med'])} | {st['p_ruin']:.1%} | "
                 f"{d(st['p10'])} | {st['p_half']:.1%} |")
    L += ["", "## Counts (all final replays)", "", json.dumps(_G["count"]), ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V43_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    summ = {"survive": survive, "improved": improved, "beats": beats, "cases": len(hist),
            "q1": {cname(k): v for k, v in q1.items()},
            "picks": {cname(k): {str(y): rule_name(r) for y, r in v.items()} for k, v in picks.items()
                      if k in (CENTRAL, DAILY)},
            "res": {cname(k): v for k, v in res.items()}, "two_k": two, "count": _G["count"]}
    (args.out / "v43_summary.json").write_text(json.dumps(summ, indent=1, default=float), encoding="utf-8")
    print("\n".join(L[:12]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, required=True)
    r.add_argument("--shards", type=int, required=True)
    r.add_argument("--procs", type=int, default=4)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--procs", type=int, default=4)
    for p in sub.choices.values():
        p.add_argument("--choice", type=Path, required=True)
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--data", type=Path, default=Path("outputs/v43"))
        p.add_argument("--out", type=Path, default=Path("outputs/v43w"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v43"
    raise SystemExit(main())
