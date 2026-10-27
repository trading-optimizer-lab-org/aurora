"""v44 part C: the book plus a sleeve of COMBO44's members in the $5,000 TradeZero account
(V44_PREREGISTRATION.md section 3).

The book is the base rule, or part M's walk-forward book when it passed Q1. Each year's members (run_v22's rule in
part N's summary) are rebuilt at the strict fills and sized as v26 at one of four (risk, cap) sizes; the size, or no
sleeve, is chosen each year by v43's walk-forward rule at the $10,000 level. v28's joint caps; the broker's 15% rule
every minute on the book's trades and at the close on the sleeve's. The PAID plan's extra $99 a month is charged on the
days of the years the sleeve is on (at each equity level of the bootstrap).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v44_new1m as v44


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


M = _script("run_v44m")
N = _script("run_v44n")  # its helpers only (stores and extras); its patched runner is not used here
R43, R40, R33, R32, R29, R35, A = M.R43, M.R40, M.R33, M.R32, M.R29, M.R35, M.A
R14, R16, R22 = R29.R14, R29.R16, R29.R22
LEVEL, TASKS, OPEN, LAST = M.LEVEL, M.TASKS, M.OPEN, M.LAST
SIZES: list = [None, (0.005, 0.10), (0.01, 0.10), (0.01, 0.20), (0.02, 0.20)]  # None: no sleeve
PAID_EXTRA = R29.FIXED["PAID"] - R29.FIXED["FREE"]
GAIN, MAX_RUIN, E2K = 1.15, 0.025, 2_000.0
_G: dict = {}


def members(summary: dict) -> list[tuple[int, str, str]]:
    """(year, family, pick) of COMBO44's members."""
    out = []
    for y, fams in summary.get("members", {}).items():
        for fam in fams:
            nm = summary["families"][fam]["picks"].get(str(y))
            if nm:
                out.append((int(y), fam, nm))
    return out


def pick_trades(name: str) -> pd.DataFrame:
    """A pick's trades at the strict fills (stops at the crossing bar's extreme)."""
    key, ci = name.split("|")
    g = N.registry()[key][1][int(ci)]
    v19.set_costs("r4", N.STRICT_SLIP, R22.R4)
    try:
        return v44.trades(_G["stores"], _G["D"], key, g)
    finally:
        v19.set_costs("r4", R22.SLIP, R22.R4)


def sleeve_items(level: float, task: str, size: int, years: set) -> list[dict]:
    if SIZES[size] is None:
        return []
    risk, cap = SIZES[size]
    c = R33.TASKS[task]
    out: list[dict] = []
    keep = core.ACCOUNT
    core.ACCOUNT = level
    try:
        for y, fam, nm in _G["members"]:
            if y not in years:
                continue
            t = _G["trades"][nm]
            t = t[pd.to_datetime(t["date"]).dt.year == y] if len(t) else t
            its = A._rows_items(t, R16._W["table"], risk, cap, level, c.get("spread", 1.0), c.get("fee", 1.0), fam)
            out += R29.tz_items(its, level, R29.BASE_LOC[0], c.get("hot", R29.BASE_LOC[1]))
    finally:
        core.ACCOUNT = keep
    return [{**it, "sleeve": True} for it in out]


def book_items(level: float, task: str, picks: dict[int, int]) -> tuple[list[dict], list[dict]]:
    """The book's items at a level and cost set, each year from its pick (part M's ids)."""
    R43.LEVEL = level
    its, metas = R43._G["its"][(float(level), task)]
    years = _G["years_of_t"]
    out: list[dict] = []
    recs: list[dict] = []
    for bid in sorted(set(picks.values())):
        f, tr, ex, xx, lo, pa = M.book_of(bid)
        ys = {y for y, b in picks.items() if b == bid}
        sel = [k for k, it in enumerate(its) if int(years[int(it["t"])]) in ys]
        items, rr = M.items_for([its[k] for k in sel], [metas[k] for k in sel], tr, ex, xx, lo, pa)
        off = len(recs)
        recs += rr
        out += [{**it, "_rec": it["_rec"] + off} for it in M.filtered(items, f)]
    return out, recs


def liquidate_mixed(taken: list[dict], recs: list[dict], T: int) -> np.ndarray:
    """R43.liquidate with the sleeve's trades: their session return enters at the close, their entry value is held as
    market value over the nights they are open."""
    rows: dict[int, list[tuple[int, int]]] = {}
    for p, it in enumerate(taken):
        us = recs[it["_rec"]]["u"] if "_rec" in it else [int(it["i0"]) + i for i in range(len(it["r"]))]
        for i, u in enumerate(us):
            rows.setdefault(u, []).append((p, i))
    alive = np.ones(len(taken), bool)
    out = np.zeros(T)
    for u in sorted(rows):
        live = [(p, i) for p, i in rows[u] if alive[p]]
        if not live:
            continue
        E, Mv = np.ones(960), np.zeros(960)
        parts, sleeve = [], 0.0
        for p, i in live:
            it = taken[p]
            w = float(it["w"])
            if "_rec" not in it:
                r = float(it["r"][i]) - (float(it.get("loc", 0.0)) if i == 0 and it["side"] < 0 else 0.0)
                sleeve += w * r
                E[LAST:] += w * r
                if i < len(it["r"]) - 1:
                    Mv[LAST] += w
                continue
            rec = recs[it["_rec"]]
            G = rec["G"][i].copy()
            if i == 0:
                G[max(rec["es"], 0):] -= rec["cost"]
            E += w * G
            Mv += w * rec["M"][i]
            parts.append((rec, w, G, i))
        hit = (Mv > 0) & (E <= R43.THETA * Mv)
        if not hit.any():
            out[u] = float(E[LAST] - 1)
            continue
        k = int(np.flatnonzero(hit)[0])
        R43._count("liquidations")
        tot = sleeve
        for rec, w, G, i in parts:
            Qk = float(rec["Q"][i][k])
            if Qk <= 1e-12:
                tot += w * G[k]
                continue
            B = R43.timeline(u, rec["j"]) or R43.synthetic(u, rec["j"])
            Pk = float(rec["M"][i][k] / Qk * rec["e"])
            f = R43.market(B, k, LAST, None, M.LIQ, rec["n"] * Qk, M.PART, (LAST, float(_G["D"]["C"][u, rec["j"]])))
            tot += w * (G[k] + Qk * (Pk - sum(a * b for _, a, b in f)) / rec["e"])
        out[u] = tot
        for p, _ in rows[u]:
            alive[p] = False
        for p, it in enumerate(taken):  # entries at that day's close are not taken either
            if "_rec" in it and recs[it["_rec"]]["kind"] == "close" and recs[it["_rec"]]["t"] == u:
                alive[p] = False
    return out


def account(level: float, task: str, size: int, sleeve_years: set) -> np.ndarray:
    items, recs = book_items(level, task, _G["book_picks"])
    items = items + sleeve_items(level, task, size, sleeve_years)
    D = _G["D"]
    _, taken = A.joint(items, D["dates"], R33.GROSS, R33.MAX_OPEN, R33.MAX_NEW, "move", "none", "tzi", 0.0, 0.0,
                       None, None, None)
    return liquidate_mixed(taken, recs, len(D["dates"]))


def _job(job: tuple) -> tuple[tuple, np.ndarray]:
    level, task, size = job
    return job, account(level, task, size, _G["member_years"])[R43._G["pos"]]


def setup(args, levels: tuple) -> None:
    M.setup(args, levels=levels, procs=args.procs)
    D = R43._G["D"]
    _G["D"] = D
    _G["years_of_t"] = np.asarray(pd.DatetimeIndex(D["dates"]).year)
    msum: dict = json.loads(args.msum.read_text(encoding="utf-8")) if args.msum.exists() else {"q1": False}
    q1 = bool(msum.get("q1"))
    ys = R43._G["ys"]
    _G["book_picks"] = {int(y): int(b) for y, b in msum["picks"].items()} if q1 else {y: M.BASE for y in ys}
    _G["q1"] = q1
    nsum = json.loads(args.nsum.read_text(encoding="utf-8")) if args.nsum.exists() else {}
    _G["members"] = members(nsum)
    _G["criterion"] = nsum.get("criterion")
    _G["member_years"] = {y for y, _, _ in _G["members"]}
    stores = {"event": R14._G["store"], "liquid": N._store(N.LIQUID), "mover": N._store(N.MOVERS)}
    if (N.DATA / "filing" / "store" / "cands.parquet").exists():
        stores["filing"] = N._store(N.DATA / "filing" / "store")
    v44.prepare(stores, D, N.extras(D))
    _G["stores"] = stores
    _G["trades"] = {nm: pick_trades(nm) for nm in sorted({nm for _, _, nm in _G["members"]})}
    print(json.dumps({"book": "part M walk-forward" if q1 else "base rule", "members": len(_G["members"]),
                      "member_years": sorted(_G["member_years"]),
                      "trades": {k: len(v) for k, v in _G["trades"].items()}}), flush=True)


def cmd_final(args) -> int:
    lv2 = np.r_[E2K, R43.LEVELS]
    setup(args, tuple(float(x) for x in lv2))
    cal, years, ys = R43._G["cal"], R43._G["years"], R43._G["ys"]
    idx = R32._sub_idx(cal)
    sizes = range(len(SIZES)) if _G["members"] else range(1)
    jobs = [(float(lv), task, s) for lv in lv2 for task in TASKS for s in sizes]
    R43._G["count"] = {}
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = dict(pool.map(_job, jobs, chunksize=1))
    G = np.full((len(SIZES), len(ys)), np.nan)
    DD = np.full((len(SIZES), len(ys)), np.nan)
    for s in sizes:
        st = R40.year_stats(got[(LEVEL, "base", s)], years, ys)
        G[s], DD[s] = st[:, 0], st[:, 1]
    picks = {ys[0]: 0}
    for k in range(1, len(ys)):
        g, dd = np.nansum(G[:, :k], axis=1), np.nanmin(DD[:, :k], axis=1)
        elig = np.isfinite(G[:, :k]).all(axis=1) & (dd >= dd[0] - 1e-12)
        picks[ys[k]] = int(np.flatnonzero(elig)[np.argmax(g[elig])])
    on_years = {y for y, s in picks.items() if s and y in _G["member_years"]}

    def series(task: str, wf: bool, fixed: int = 0) -> np.ndarray:
        R = np.stack([got[(float(lv), task, 0 if wf else fixed)] for lv in lv2])
        on = set(on_years) if wf else (_G["member_years"] if fixed else set())
        if wf:
            for y, s in picks.items():
                R[:, years == y] = np.stack([got[(float(lv), task, s)] for lv in lv2])[:, years == y]
        day = np.isin(years, sorted(on))
        R = R.copy()
        R[:, day] -= (PAID_EXTRA * 12 / 252 / lv2)[:, None]  # the PAID plan on the sleeve's days
        return R

    res = {t: {b: R43.boot(series(t, b == "wf")[1:], idx if t == "base" else {"all": idx["all"]})
               for b in ("alone", "wf")} for t in TASKS}
    fixed = {s: R43.boot(series("base", False, s)[1:], {"all": idx["all"]})["all"] for s in sizes}
    two = {b: R43.boot(series("base", b == "wf"), {"all": idx["all"]}, E2K, lv2)["all"] for b in ("alone", "wf")}
    a = {t: {b: res[t][b]["all"] for b in ("alone", "wf")} for t in TASKS}
    q3 = bool(a["base"]["wf"]["med"] >= GAIN * a["base"]["alone"]["med"] and a["base"]["wf"]["p_ruin"] <= MAX_RUIN
              and a["hot5"]["wf"]["p_ruin"] <= MAX_RUIN and a["high"]["wf"]["med"] >= a["high"]["alone"]["med"])
    d = R35._d

    def sname(s: int) -> str:
        return "no sleeve" if SIZES[s] is None else f"risk {SIZES[s][0]:.1%}, cap {SIZES[s][1]:.0%}"

    L = ["# v44 part C: the book plus COMBO44's sleeve in the $5,000 TradeZero account", "",
         f"Book: {'part M walk-forward (Q1 passed)' if _G['q1'] else 'the base rule (part M did not pass Q1)'}. "
         f"COMBO44 criterion: {_G['criterion']}. Members: {len(_G['members'])} pick-years in "
         f"{sorted(_G['member_years']) or 'no year'}. {R29.PATHS} one-year bootstrap paths from $5,000; ruin = at "
         "or under $1,250.", "", "## Q3. Does the sleeve improve the account?", "",
         f"**{q3}** (walk-forward median >= {GAIN} x the book alone's, ruin <= 2.5% at base and HOT 5%, high-cost "
         "median >= the book alone's).", "",
         "| account | costs | all median | all ruin | p10 | 2018-22 median | 2023+ median |", "|---|---|---|---|---|---|---|"]
    for b in ("alone", "wf"):
        for t in TASKS:
            s_ = res[t][b]
            L.append(f"| {'book alone' if b == 'alone' else 'walk-forward sleeve'} | {t} | {d(s_['all']['med'])} | "
                     f"{s_['all']['p_ruin']:.1%} | {d(s_['all']['p10'])} | "
                     f"{d(s_['early']['med']) if 'early' in s_ else '-'} | "
                     f"{d(s_['late']['med']) if 'late' in s_ else '-'} |")
    L += ["", "Each size fixed in every member year (in-sample, base costs):", "",
          "| sleeve | median | ruin | p10 | log growth at $10,000 | worst yearly drawdown |", "|---|---|---|---|---|---|"]
    for s in sizes:
        L.append(f"| {sname(s)} | {d(fixed[s]['med'])} | {fixed[s]['p_ruin']:.1%} | {d(fixed[s]['p10'])} | "
                 f"{np.nansum(G[s]):.2f} | {np.nanmin(DD[s]):.1%} |")
    L += ["", "Walk-forward sizes: " + "; ".join(f"{y}: {sname(s)}" for y, s in picks.items()), "",
          "Members: " + ("; ".join(f"{y} {fam} `{nm}`" for y, fam, nm in _G["members"]) or "none"), "",
          "## Q4. From $2,000 (base costs; ruin = at or under $500)", "",
          "| account | median | ruin | p10 | -50% |", "|---|---|---|---|---|"]
    for b, s_ in two.items():
        L.append(f"| {'book alone' if b == 'alone' else 'walk-forward sleeve'} | {d(s_['med'])} | "
                 f"{s_['p_ruin']:.1%} | {d(s_['p10'])} | {s_['p_half']:.1%} |")
    L += ["", "## Counts", "", json.dumps(R43._G["count"]), ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V44C_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    (args.out / "v44c_summary.json").write_text(json.dumps(
        {"q3": q3, "book_q1": _G["q1"], "picks": {str(y): sname(s) for y, s in picks.items()}, "res": res,
         "fixed": {sname(s): v for s, v in fixed.items()}, "two_k": two, "members": _G["members"]}, indent=1,
        default=float), encoding="utf-8")
    print("\n".join(L[:12]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--choice", type=Path, required=True)
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    ap.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    ap.add_argument("--data", type=Path, default=Path("outputs/v43"))
    ap.add_argument("--v44", type=Path, default=Path("outputs/v44"))
    ap.add_argument("--nsum", type=Path, required=True)
    ap.add_argument("--msum", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("outputs/v44w/c"))
    return cmd_final(ap.parse_args())


if __name__ == "__main__":
    sys.argv[0] = "run_v44c"
    raise SystemExit(main())
