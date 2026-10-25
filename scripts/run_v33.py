"""v33: changing the FREE members themselves (V33_PREREGISTRATION.md). The four daily short families of v28's B block
re-picked under the account's costs, limit entries, an emergency exit and a HOT skip for the night shorts; the
members then go into v29's A1 account under v31's liquidation, against A1.

  real      one shard of the re-pick grid: each configuration alone in A1's account at $5,000, monthly returns
  select    v22's walk-forward picks of each family under the account's costs
  variants  one shard of the variants of every v28 pick and every re-pick
  choose    each arm's members by year (the variants chosen walk-forward)
  arms      one shard of the arms x costs: the account's one-year paths
  final     V33_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R32 = _script("run_v32")
R31, R29 = R32.R31, R32.R29
A, R14, R22 = R29.A, R29.R14, R29.A.R22
R20, R28 = R22.R20, A.R28
LEVELS, E0, FIXED = R29.LEVELS, R29.E0, R29.FIXED["FREE"]
KEYS = ("B:v19:DS1_RUNUP", "B:v20:RU_RUNUP", "B:v19:ON1_NIGHTSHORT", "B:v20:NS_NIGHTSHORT")
FAMS = tuple(R14.family_of(k) for k in KEYS)
NIGHT = ("B:v19:ON1", "B:v20:NS")
RISK, CAP, GROSS, MAX_OPEN, MAX_NEW, FLOOR = 0.02, 0.20, 2.0, 20, 3, 2.5
LIMITS: tuple[float | None, ...] = (None, 0.05, 0.10, 0.20)
CATS: tuple[float | None, ...] = (None, 0.5, 1.0)
FILL_THROUGH = 0.01
BASE_VAR = (None, None, False)
ALL_YEARS = set(range(1990, 2100))
QUICK = R29.QUICK
ARMS = ("A1", "repick", "limit", "exit", "nohot", "no_night", "all")
TASKS: dict[str, dict] = {"base": {}, "hot5": {"hot": 0.05}, "spread2": {"spread": 2.0},
                          "high": {"spread": 2.0, "fee": 3.0}}
VARIANT: dict = {"limit": None, "cat": None}
ENTRIES: list[float] = []  # each trade's entry price, in the order the daily path returns them


# ---------------------------------------------------------------- the variants inside the shield's daily path

def walk(D: dict, u0: int, j: int, e: float, stop: float, prev: float, w: float, fracs: list[float],
         P: dict) -> tuple[list[float], float, int]:
    """sh.walk with the emergency exit: after a close at or beyond e x (1 + cat), cover at the next open."""
    O, H, C, F, new = D["O"], D["H"], D["C"], D["F"], D["new"]
    T = C.shape[0]
    cat = VARIANT["cat"]
    lvl = e * (1 + cat) if cat is not None else np.inf
    flag = prev >= lvl
    rets, nights, leg = [], 0.0, 2
    for k, fr in enumerate(fracs):
        u = u0 + k + 1
        if u >= T:
            break
        hit = sh._night(u - 1, j, stop, prev, F, P)
        if hit is not None:
            px, leg, mm = hit
            nights += w if leg == sh.LEG_PM else 0.0
            rets.append(w * (prev - px) / e)
            sh.EXIT.update(row=u - 1 if leg == sh.LEG_AH else u, kind="ah" if leg == sh.LEG_AH else "pm", minute=mm)
            return rets, nights, leg
        c = float(C[u, j])
        if new[u, j] or not np.isfinite(c):
            leg = 2
            sh.EXIT.update(row=u - 1, kind="close", minute=-1)
            break
        o, h = float(O[u, j]), float(H[u, j])
        o = o if np.isfinite(o) else c
        nights += w
        if flag:  # the emergency exit: charged the close leg, as a carried trade's exit at an open
            rets.append(w * (prev - o) / e)
            sh.EXIT.update(row=u, kind="open", minute=-1)
            return rets, nights, 2
        if h >= stop:
            px = o if o >= stop else v19._slip(stop, h)
            rets.append(w * (prev - px) / e)
            sh.EXIT.update(row=u, kind="open" if o >= stop else "stop", minute=-1)
            return rets, nights, 2
        tg = P.get("target", "none")
        if tg != "none":
            tl, lo = e * (1 - int(tg[1:]) / 100), float(D["L"][u, j])
            if np.isfinite(lo) and lo <= tl:
                px = o if o <= tl else tl
                rets.append(w * (prev - px) / e)
                sh.EXIT.update(row=u, kind="target", minute=-1)
                return rets, nights, 2
        rets.append(w * (prev - c) / e)
        prev = c
        flag = c >= lvl
        sh.EXIT.update(row=u, kind="close", minute=-1)
        if k == len(fracs) - 1:
            return rets, nights, 2
        w -= fr
    return rets, nights, leg


def daily_path(D: dict, s: v19.Spec, table: dict, spread: float, fee_mult: float, gross: bool,
               w_max: float) -> tuple[int, np.ndarray, float, float] | None:
    """sh.daily_path with the limit entry (an open entry only) and the emergency exit."""
    P = sh.PARAMS
    assert P is not None
    O, H, C, P_raw = D["O"], D["H"], D["C"], D["P"]
    T = C.shape[0]
    t, j = s.t, s.j
    own = s.stop
    closes = sh.HOLD[P["hold"]]
    leg_in = 2
    if s.kind == "close":
        e, first, raw = float(C[t, j]), t + 1, float(P_raw[t, j])
    else:
        e, first = float(O[t, j]), t
        lim = VARIANT["limit"]
        leg_in = 0
        if lim is not None:
            pc = float(C[t - 1, j]) if t > 0 else np.nan
            if not np.isfinite(pc) or pc <= 0 or not np.isfinite(e):
                return None
            lvl = pc * (1 + lim)
            if e < lvl:
                if not float(H[t, j]) >= lvl * (1 + FILL_THROUGH):
                    return None
                e, leg_in = lvl, 1
        raw = float(P_raw[t - 1, j] * (e / C[t - 1, j])) if t > 0 and C[t - 1, j] > 0 else float(P_raw[t, j])
    if not np.isfinite(e) or e <= 0 or first >= T or not np.isfinite(raw):
        return None
    own_lvl = e * (1 + own) if np.isfinite(own) else np.inf
    stop = sh.stop_level(P["stop"], e, own_lvl, t, j, 1.0)
    if not np.isfinite(stop) or stop <= e:
        stop = np.inf if P["stop"] == "own" else e * 1.20
    sh.EXIT.clear()
    if s.kind == "close":
        rets, nights, leg = walk(D, t, j, e, stop, e, 1.0, sh.fractions(P["scale"], closes + 1), P)
    else:
        h, c = float(H[t, j]), float(C[t, j])
        if not np.isfinite(c):
            return None
        if h >= stop:
            rets, nights, leg = [(e - v19._slip(stop, h)) / e], 0.0, 2
            sh.EXIT.update(row=t, kind="stop", minute=-1)
        else:
            rets, nights, leg = [(e - c) / e], 0.0, 2
            sh.EXIT.update(row=t, kind="close", minute=-1)
            if closes > 0:
                fr = sh.fractions(P["scale"], closes + 1)
                more, nights, leg = walk(D, t, j, e, stop, c, 1.0 - fr[0], fr[1:], P)
                rets += more
    if not rets:
        return None
    r = np.array(rets)
    w = min(w_max, 0.01 * D["DV1"][t, j] / core.ACCOUNT) if np.isfinite(D["DV1"][t, j]) else 0.0
    cost, avail = v19._costs(np.array([raw]), np.array([D["SO"][t, j]]), np.array([-1]), np.array([nights]),
                             np.array([int(leg_in == 0) + int(leg == 0)]), table, spread, fee_mult, gross,
                             (np.array([leg_in]), np.array([leg])))
    if not gross and s.kind == "open" and t > 0 and e <= 0.9 * C[t - 1, j]:
        cost = cost + v19.vs.SSR_EXTRA
    r[0] -= cost[0]
    ENTRIES.append(e)
    return first, r, s.prio, w * float(avail[0])


_ORIG_DAILY = sh.daily_path
sh.daily_path = daily_path


# ---------------------------------------------------------------- members

def member_items(name: str, years: set, level: float, var: tuple = BASE_VAR, spread: float = 1.0, fee: float = 1.0,
                 hot: float = R29.BASE_LOC[1]) -> list[dict]:
    """One pick's trades at an equity level under TradeZero's account, with a variant (limit, exit, HOT skip)."""
    VARIANT.update(limit=var[0], cat=var[1])
    ENTRIES.clear()
    try:
        raw = A.pick_items(name, False, years, RISK, CAP, level, spread, fee)
    finally:
        VARIANT.update(limit=None, cat=None)
    assert len(ENTRIES) == len(raw)  # every member is a short walked by the shield's daily path
    raw = [{**it, "entry": e} for it, e in zip(raw, ENTRIES)]
    its = R29.tz_items(raw, level, R29.BASE_LOC[0], hot, floor=FLOOR)
    return [it for it in its if it["tier"] != 2] if var[2] else its


def alone(its: list[dict]) -> tuple[pd.Series, pd.Series]:
    """A family alone in A1's account (no liquidation rule): monthly returns and trades a month, design window."""
    D = R14._G["D"]
    s, taken = A.joint(its, D["dates"], GROSS, MAX_OPEN, MAX_NEW, "move", "none", "tzi", 0.0, 0.0, None, None)
    m = core.monthly(s.loc[core.DESIGN_START:core.last_day()].to_frame("r"))["r"]
    first = pd.Series(1.0, index=D["dates"][[it["i0"] for it in taken]]) if taken else pd.Series(dtype=float)
    c = first.groupby(first.index.to_period("M")).sum() if len(first) else pd.Series(dtype=float)
    return m, c.reindex(m.index).fillna(0.0)


def grid() -> list[tuple[str, int]]:
    reg = R28.registry()
    out = [(k, i) for k in KEYS for i, c in enumerate(reg[k][1]) if c["ext"] == "none"]
    if QUICK:
        out = [u for k in KEYS for u in [x for x in out if x[0] == k][:2]]
    return out


def variants(fam: str) -> list[tuple]:
    return [(lim, cat, hs) for lim in LIMITS for cat in CATS for hs in ((False, True) if fam in NIGHT else (False,))]


def vname(name: str, var: tuple) -> str:
    return f"{name}|{var[0]}|{var[1]}|{int(var[2])}"


def _write(out: Path, cols: dict, counts: dict, meta: list) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if cols:
        for nm, d in (("monthly", cols), ("counts", counts)):
            f = pd.DataFrame(d).astype(np.float32)
            f.index = f.index.to_timestamp()
            f.to_parquet(out / f"{nm}.parquet")
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _read(parts: Path, name: str) -> pd.DataFrame:
    fs = sorted(parts.rglob(f"{name}.parquet"))
    return pd.concat([pd.read_parquet(p) for p in fs], axis=1).sort_index() if fs else pd.DataFrame()


def _run_units(units: list[tuple[str, tuple]], out: Path) -> int:
    import time
    cols, counts, meta = {}, {}, []
    for name, var in units:
        t0 = time.time()
        err = None
        try:
            m, c = alone(member_items(name, ALL_YEARS, E0, var))
            cols[vname(name, var)], counts[vname(name, var)] = m, c
        except Exception as exc:  # recorded and reported
            err = f"{type(exc).__name__}: {exc}"
        A._TR.pop((name, False, 0), None)
        meta.append({"name": vname(name, var), "sec": round(time.time() - t0, 1), "error": err})
        print(meta[-1], flush=True)
    _write(out, cols, counts, meta)
    print(f"done: {len(meta)} units, {sum(1 for m in meta if m['error'])} errors", flush=True)
    return 0


def cmd_real(args) -> int:
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    units = [(f"{k}|{i}", BASE_VAR) for k, i in grid()][args.shard::args.shards]
    return _run_units(units, args.out)


def _cash(args, months: pd.DatetimeIndex) -> np.ndarray:
    D = R14.PREP.load(args.inputs / "v14" / "daily.pkl")
    return R22._cash_m(D, months)


def cmd_select(args) -> int:
    monthly, counts = _read(args.parts, "monthly"), _read(args.parts, "counts")
    meta = [m for p in sorted(args.parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))]
    months = monthly.index
    cm = _cash(args, months)
    reg = R28.registry()
    out: dict = {"n": len(meta), "errors": [m for m in meta if m["error"]][:20], "picks": {}}
    for key in KEYS:
        names = [n for n in monthly.columns if n.startswith(key + "|")]
        if not names:
            continue
        cfgs = [reg[key][1][int(n.split("|")[1])] for n in names]
        M = monthly[names].to_numpy(float)
        Cn = counts.reindex(columns=names).fillna(0.0).to_numpy(float)
        Anb = R20.neighbours_matrix([{"rule": key, **c} for c in cfgs])
        picks = R22.walk_forward(M, Cn, cm, Anb, months, core.last_day().year)
        out["picks"][R14.family_of(key)] = {str(y): {"name": names[i].rsplit("|", 3)[0], "score": s, "cfg": cfgs[i]}
                                            for y, (i, s) in picks.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "picks1.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps({f: {y: p["name"] for y, p in v.items()} for f, v in out["picks"].items()}, indent=1), flush=True)
    return 0


def v28_members() -> list[tuple[int, str, str]]:
    """(year, family, pick) of v29's FREE members (the daily ones among COMBO28's)."""
    out = []
    for y, fam, nm, v26n in A.members("A28"):
        if A._unsized(nm, v26n, 0)[0] == "specs":
            out.append((y, fam, nm))
    return out


def _variant_units(picks1: dict) -> list[tuple[str, tuple]]:
    names: dict[str, set] = {f: set() for f in FAMS}
    for _, fam, nm in v28_members():
        if fam in names:
            names[fam].add(nm)
    for fam, by_year in picks1["picks"].items():
        names[fam] |= {p["name"] for p in by_year.values()}
    return [(nm, var) for fam in FAMS for nm in sorted(names[fam]) for var in variants(fam)]


def cmd_variants(args) -> int:
    picks1 = json.loads((args.picks / "picks1.json").read_text(encoding="utf-8"))
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    return _run_units(_variant_units(picks1)[args.shard::args.shards], args.out)


def choose_variant(name: str, fam: str, year: int, allowed: list[tuple], monthly: pd.DataFrame,
                   counts: pd.DataFrame, cm: np.ndarray) -> tuple:
    """The allowed variant of a pick with the best v14 score on the months before the year, among those active
    enough; the pick as it is when none is."""
    cols = [vname(name, v) for v in allowed]
    ok = [c in monthly.columns for c in cols]
    if not all(ok):
        return BASE_VAR
    tr = R20.window_rows(monthly.index, year)
    if tr.sum() < 12:
        return BASE_VAR
    M = monthly[cols].to_numpy(float)
    Cn = counts.reindex(columns=cols).fillna(0.0).to_numpy(float)
    s = np.where(R22.eligible(Cn, tr), core.score(M[tr], cm[tr]), np.nan)
    return allowed[int(np.nanargmax(s))] if np.isfinite(s).any() else BASE_VAR


def arm_members(arm: str, picks1: dict, monthly: pd.DataFrame, counts: pd.DataFrame, cm: np.ndarray
                ) -> list[dict]:
    rows = []
    v28 = v28_members()
    years = sorted({y for y, _, _ in v28})
    for y in years:
        for fam in sorted({f for yy, f, _ in v28 if yy == y} | (set(FAMS) if arm in ("repick", "all") else set())):
            if fam in FAMS and arm in ("repick", "all"):
                p = picks1["picks"].get(fam, {}).get(str(y))
                nm = p["name"] if p else None
            else:
                nm = next((n for yy, f, n in v28 if yy == y and f == fam), None)
            if nm is None or (arm == "no_night" and fam in NIGHT):
                continue
            allowed = [BASE_VAR]
            if fam in FAMS:
                vs = variants(fam)
                allowed = {"limit": [v for v in vs if v[1] is None and not v[2]],
                           "exit": [v for v in vs if v[0] is None and not v[2]],
                           "nohot": [v for v in vs if v[0] is None and v[1] is None],
                           "all": vs}.get(arm, [BASE_VAR])
            var = choose_variant(nm, fam, y, allowed, monthly, counts, cm) if len(allowed) > 1 else BASE_VAR
            rows.append({"year": y, "fam": fam, "name": nm, "var": list(var)})
    return rows


def cmd_choose(args) -> int:
    picks1 = json.loads((args.picks / "picks1.json").read_text(encoding="utf-8"))
    monthly, counts = _read(args.parts, "monthly"), _read(args.parts, "counts")
    cm = _cash(args, monthly.index) if len(monthly) else np.zeros(0)
    R29.load(args.inputs, args.report)  # members() reads the report; _unsized needs the data for a pick's form
    out: dict = {"arms": {arm: arm_members(arm, picks1, monthly, counts, cm) for arm in ARMS}}
    meta = [m for p in sorted(args.parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))]
    out["variant_errors"] = [m for m in meta if m["error"]][:20]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "arms.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    for arm, rows in out["arms"].items():
        print(arm, len(rows), "member-years;", sum(1 for r in rows if tuple(r["var"]) != BASE_VAR), "with a variant",
              flush=True)
    return 0


def account(rows: list[dict], level: float, spread: float = 1.0, fee: float = 1.0,
            hot: float = R29.BASE_LOC[1]) -> tuple[np.ndarray, list[dict]]:
    """The arm's account at an equity level under the liquidation rule: daily returns and the trades taken."""
    D = R14._G["D"]
    its = []
    for r in rows:
        its += member_items(r["name"], {int(r["year"])}, level, tuple(r["var"]), spread, fee, hot)
    s, taken = A.joint(its, D["dates"], GROSS, MAX_OPEN, MAX_NEW, "move", "none", "tzi", 0.0, 0.0, None, None)
    s = s.to_numpy(float)
    T = len(s)
    P = R31.position_days(taken, D, T)
    out, days = R31.liquidate(P, T, R31.THETA)
    R32.LOG.append({"n": len(days), "worst_on": float(out.min()) if T else 0.0, "worst_off": float(s.min()) if T else 0.0})
    return out, taken


def cmd_arms(args) -> int:
    ch = json.loads((args.choice / "arms.json").read_text(encoding="utf-8"))
    jobs = [(arm, task) for arm in ARMS for task in TASKS][args.shard::args.shards]
    if not jobs:
        return 0
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, pos = R29._cal()
    idx = R32._sub_idx(cal)
    out = []
    for arm, task in jobs:
        rows = ch["arms"][arm]
        R = np.zeros((len(LEVELS), len(pos)))
        R32.LOG.clear()
        taken5: list[dict] = []
        for li, level in enumerate(LEVELS):
            s, taken = account(rows, float(level), **TASKS[task])
            R[li] = s[pos]
            if level == E0:
                taken5 = taken
        for sample, ix in idx.items():
            if sample != "all" and task != "base":
                continue
            row = {"arm": arm, "task": task if sample == "all" else f"base_{sample}",
                   **R32.stats(*R32.paths(R, R, ix, FIXED, None))}
            if task == "base" and sample == "all":
                row.update(liq_5k=R32.LOG[1] if len(R32.LOG) > 1 else None, trades_5k=len(taken5),
                           hot_5k=float(np.mean([it["tier"] == 2 for it in taken5])) if taken5 else None,
                           fams_5k={f: int(n) for f, n in pd.Series([it["fam"] for it in taken5]).value_counts()
                                    .items()} if taken5 else {})
            out.append(row)
            print(arm, row["task"], round(row["med"]), round(row["p_ruin"], 4), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"arms_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


def verdict(get: dict) -> dict:
    """Section 4: each arm against A1 at the base costs, on 2023+ paths, at HOT 5% and at spreads x2; ruin <= 1%."""
    out = {}
    for arm in ARMS[1:]:
        tasks = ("base", "base_late", "hot5", "spread2")
        if not all((a, t) in get for a in ("A1", arm) for t in tasks):
            continue
        beats = {t: get[(arm, t)]["med"] > get[("A1", t)]["med"] for t in tasks}
        ruin = get[(arm, "base")]["p_ruin"] <= 0.01
        out[arm] = {**{f"beats_{t}": v for t, v in beats.items()}, "ruin_ok": ruin,
                    "raises": all(beats.values()) and ruin, "med": get[(arm, "base")]["med"]}
    passing = [a for a, v in out.items() if v["raises"]]
    return {"arms": out, "choice": max(passing, key=lambda a: out[a]["med"]) if passing else None}


def _var(v: list) -> str:
    lim = "-" if v[0] is None else f"limit {v[0]:.0%}"
    cat = "-" if v[1] is None else f"exit {v[1]:.0%}"
    return f"{lim}, {cat}, {'HOT skip' if v[2] else '-'}"


def cmd_final(args) -> int:
    d, p = R31.R30._d, R31.R30._p
    picks1 = json.loads((args.picks / "picks1.json").read_text(encoding="utf-8"))
    ch = json.loads((args.choice / "arms.json").read_text(encoding="utf-8"))
    rows = [r for f in sorted(args.arms.rglob("arms_*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]
    get = {(r["arm"], r["task"]): r for r in rows}
    v = verdict(get)
    L = ["# v33: changing the FREE members themselves", "",
         f"A1's account (size 20%, move, 3 new, 20 open, gross 2x, $2.50 floor), TradeZero International's costs, base "
         f"locates HTB 1% / HOT 3% unless stated, v31's liquidation at {R31.THETA:.0%}; {R29.PATHS} one-year bootstrap "
         f"paths from $5,000; ruin = the equity at or under $1,250 at any time. Re-pick grid: {picks1['n']} "
         "configurations.", "", "## 1. The question", ""]
    a1 = get.get(("A1", "base"))
    if a1:
        L.append(f"Check: A1's base median {d(a1['med'])} (v29/v32: $12,831).")
        L.append("")
    for arm, x in v["arms"].items():
        L.append(f"- {arm}: beats A1 at base {x['beats_base']}, 2023+ {x['beats_base_late']}, HOT 5% "
                 f"{x['beats_hot5']}, spreads x2 {x['beats_spread2']}; ruin <= 1% {x['ruin_ok']} -> **{x['raises']}**")
    L += ["", f"**v33's choice: {v['choice'] or 'none (no arm raises the median)'}.**", "",
          "## 2. Results", "", "| arm | task | median | mean | p10 | p90 | ruin | -50% | loss | worst 5% mean | "
          "liquidations at $5k | trades at $5k | HOT share |", "|" + "---|" * 13]
    for r in rows:
        lq = r.get("liq_5k")
        L.append(f"| {r['arm']} | {r['task']} | {d(r['med'])} | {d(r['mean'])} | {d(r['p10'])} | {d(r['p90'])} | "
                 f"{p(r['p_ruin'])} | {p(r['p_half'])} | {p(r['p_loss'])} | {d(r['es5'])} | "
                 f"{lq['n'] if lq else '-'} | {r.get('trades_5k', '-')} | "
                 f"{p(r['hot_5k']) if r.get('hot_5k') is not None else '-'} |")
    L += ["", "## 3. Change 1: the re-picks against v28's picks", "", "| family | year | v28 pick | re-pick | "
          "re-pick's hold / stop / filter / target |", "|---|---|---|---|---|"]
    v28 = {(f, y): n for y, f, n in ((r["year"], r["fam"], r["name"]) for r in ch["arms"]["A1"])}
    for fam, by_year in picks1["picks"].items():
        for y, pk in sorted(by_year.items()):
            c = pk["cfg"]
            L.append(f"| {fam} | {y} | {v28.get((fam, int(y)), '-')} | {pk['name']} | "
                     f"{c['hold']} / {c['stop']} / {c['filt']} / {c['target']} |")
    L += ["", "## 4. Variants chosen", "", "| arm | family | year | pick | variant |", "|---|---|---|---|---|"]
    for arm in ("limit", "exit", "nohot", "all"):
        for r in ch["arms"][arm]:
            if r["fam"] in FAMS:
                L.append(f"| {arm} | {r['fam']} | {r['year']} | {r['name']} | {_var(r['var'])} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V33_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v33_summary.json").write_text(json.dumps({"verdict": v, "picks1": picks1["picks"], "arms": ch["arms"],
                                                           "results": rows}, indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("real", "variants", "arms"):
        s = sub.add_parser(name)
        s.add_argument("--shard", type=int, required=True)
        s.add_argument("--shards", type=int, default=1)
    sub.add_parser("select").add_argument("--parts", type=Path, required=True)
    sub.choices["variants"].add_argument("--picks", type=Path, required=True)
    c = sub.add_parser("choose")
    c.add_argument("--picks", type=Path, required=True)
    c.add_argument("--parts", type=Path, required=True)
    sub.choices["arms"].add_argument("--choice", type=Path, required=True)
    f = sub.add_parser("final")
    f.add_argument("--picks", type=Path, required=True)
    f.add_argument("--choice", type=Path, required=True)
    f.add_argument("--arms", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"real": cmd_real, "select": cmd_select, "variants": cmd_variants, "choose": cmd_choose,
            "arms": cmd_arms, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v33"
    raise SystemExit(main())
