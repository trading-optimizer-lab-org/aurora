"""v50: the size grid under TradeZero's costs and rules, and what each TZC rule costs (V50_PREREGISTRATION.md).

  run    one book under TZA, TZC and the TZC variants with v48's ensemble
  final  V50_REPORT.md and v50_summary.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v49 as Q  # noqa: E402

W, V, R43, R40, R35, R29 = Q.W, Q.V, Q.R43, Q.R40, Q.R35, Q.R29
LEVELS, E2K, ENS_TASKS, SEEDS = Q.LEVELS, Q.E2K, Q.ENS_TASKS, Q.SEEDS
BOOKS = [(ds, ns, ru, mn) for ds, ns, ru, mn in
         itertools.product((0.20, 0.30, 0.40), (0.40, 0.60, 0.80), (0.15, 0.20, 0.25), (5, 8))]
TZC = {"borrow": 1.0, "margin": 0.09, "loc": Q.UNAVAIL, "two": True, "vol": True}
SETS = {"TZA": None,
        "TZC": TZC,
        "TZC-B2": {**TZC, "borrow": 2.0},
        "TZC-L0": {**TZC, "loc": {}},
        "TZC-L25": {**TZC, "loc": {1: 0.05, 2: 0.25}},
        "TZC-T0": {**TZC, "two": False},
        "TZC-V0": {**TZC, "vol": False}}
MAIN = "TZC"
TARGET = 10_000.0
MAX_RUIN = Q.MAX_RUIN
CHECK = (8_498.0, 0.0, 200.0, 0.003)  # v49's answer, DS0.20-NS0.40-RU0.20-N5 under TZC


def variant(items: list[dict], recs: list[dict], s: dict | None) -> tuple[list[dict], list[dict]]:
    """v49's TZC variant with the locate rates and the volume cap of the set."""
    if s is None:
        return items, recs
    Q.UNAVAIL = s["loc"]
    vs = Q.vol_scale
    if not s["vol"]:
        Q.vol_scale = lambda want, vol: 1.0
    try:
        return Q.variant(items, recs, s)
    finally:
        Q.vol_scale = vs


def choose(books: dict) -> str | None:
    ok = [k for k, z in books.items()
          if all(W.ensemble(z["res"][MAIN][t], "all")["ruin"] <= MAX_RUIN for t in ENS_TASKS)]
    return max(ok, key=lambda k: W.ensemble(books[k]["res"][MAIN]["base"], "all")["med"]) if ok else None


# ---------------------------------------------------------------- run

def _job(job: tuple) -> tuple:
    level, task = job
    R43.LEVEL = level
    R43._G["count"] = {}
    items, recs = V.items_for(*V.pairs(level, task, Q.TZA), Q.TZA)
    out = {}
    for name, s in SETS.items():
        its, rs = variant(items, recs, s)
        two = bool(s and s["two"])
        out[name] = {sd: Q.account([it for it in its if not W.dropped(it, sd)], rs, W._G["mn"], two)
                     [R43._G["pos"]] for sd in SEEDS}
    return job, out, dict(R43._G["count"]) if level == W.LEVEL and task == "base" else None


def cmd_run(args) -> int:
    ds, ns, ru, mn = BOOKS[args.book]
    W._G["mn"] = int(mn)
    R40.SIZES = W.sizes_of(ds, ns, ru)
    t0 = time.time()
    lv2 = [float(x) for x in np.r_[E2K, LEVELS]]
    R43.setup(args, tuple(lv2))
    V._G.update(rows=R35._rows(args), days=V.candidates())
    jobs = [(lv, t) for t in ENS_TASKS for lv in lv2]
    with mp.get_context("fork").Pool(args.procs) as pool:
        for (lv, t), (oi, om, _) in pool.map(V._o1_job, jobs, chunksize=1):
            V._G["o1"][(lv, t)] = (oi, om)
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = pool.map(_job, jobs, chunksize=1)
        R = {job: out for job, out, _ in got}
        count = next((c for _, _, c in got if c is not None), {})
        B = dict(pool.map(W._boot_job, [((n, t, s), [R[(lv, t)][n][s] for lv in lv2], ("all", "early", "late"))
                                        for n in SETS for t in ENS_TASKS for s in SEEDS], chunksize=1))
    out = {"book": W.book_id(ds, ns, ru, int(mn)), "sizes": [ds, ns, ru, mn],
           "res": {n: {t: {str(s): B[(n, t, s)] for s in SEEDS} for t in ENS_TASKS} for n in SETS},
           "count": count, "sec": round(time.time() - t0)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"b{args.book}.json").write_text(json.dumps(out, default=float), encoding="utf-8")
    for n in SETS:
        e = W.ensemble(out["res"][n]["base"], "all")
        print(out["book"], n, f"ens median {e['med']:,.0f} ruin {e['ruin']:.1%} p90 {e['ruin90']:.1%}", flush=True)
    print(json.dumps({"count": count, "sec": out["sec"]}), flush=True)
    return 0


# ---------------------------------------------------------------- final

def _d(x: float) -> str:
    return f"${x:,.0f}"


def cmd_final(args) -> int:
    books = {}
    for p in sorted(args.runs.rglob("b[0-9]*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        books[z["book"]] = z
    e = {(k, n, t, s): W.ensemble(books[k]["res"][n][t], s) for k in books for n in SETS for t in ENS_TASKS
         for s in ("all", "early", "late")}
    ref = W.book_id(0.20, 0.40, 0.20, 5)
    z = e.get((ref, MAIN, "base", "all"))
    check = bool(z) and abs(z["med"] - CHECK[0]) <= CHECK[2] and abs(z["ruin"] - CHECK[1]) <= CHECK[3]
    ch = choose(books)
    a = e[(ch, MAIN, "base", "all")] if ch else None
    met = bool(a) and a["med"] >= TARGET
    L = ["# v50: the size grid under TradeZero's costs and rules, and what each TZC rule costs", "",
         f"{len(books)} books, {len(SEEDS)} seeds, {R29.PATHS} one-year paths from $5,000, ruin at or under $1,250. "
         "TZC as v49. B2 borrow doubled; L0 no failed locates; L25 locates fail HOT 25%, HTB 5%; T0 no 2:1 rule; "
         "V0 no volume cap on close entries.", "",
         f"Check (DS0.20-NS0.40-RU0.20-N5 under TZC vs v49 {_d(CHECK[0])}, {CHECK[1]:.1%}): "
         f"**{'reproduced' if check else 'NOT reproduced'}**.", ""]
    if a:
        L += [f"## Answer: **{ch}**, target $10,000 **{'MET' if met else 'NOT MET'}**", "",
              f"TZC, base costs, all paths, ensemble mean of {len(SEEDS)} seeds: one-year median from $5,000 "
              f"**{_d(a['med'])}**, ruin **{a['ruin']:.1%}** (p90 over seeds {a['ruin90']:.1%}).", ""]
    else:
        L += ["## Answer: **none passes** the ruin bar under TZC", ""]
    top = sorted(books, key=lambda k: -e[(k, MAIN, "base", "all")]["med"])
    L += ["## Books by TZC median (base, all paths)", "",
          "| book | TZC median | ruin | p90 | 2023+ | HOT 5% | TZA |", "|---|---|---|---|---|---|---|"]
    for k in top:
        x, h, t = e[(k, MAIN, "base", "all")], e[(k, MAIN, "hot5", "all")], e[(k, "TZA", "base", "all")]
        late = e[(k, MAIN, "base", "late")]
        L.append(f"| {k} | {_d(x['med'])} | {x['ruin']:.1%} | {x['ruin90']:.1%} | {_d(late['med'])} / "
                 f"{late['ruin']:.1%} | {_d(h['med'])} / {h['ruin']:.1%} | {_d(t['med'])} / {t['ruin']:.1%} |")
    L += ["", "## What each TZC rule costs (base, all paths)", "",
          "| book | " + " | ".join(SETS) + " |", "|---|" + "---|" * len(SETS)]
    for k in top[:10] + ([ref] if ref in books and ref not in top[:10] else []):
        L.append(f"| {k} | " + " | ".join(f"{_d(e[(k, n, 'base', 'all')]['med'])} / "
                                          f"{e[(k, n, 'base', 'all')]['ruin']:.1%}" for n in SETS) + " |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V50_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    (args.out / "v50_summary.json").write_text(json.dumps(
        {"choice": ch, "answer": a, "met": met, "check": check,
         "ensemble": {"|".join(k): v for k, v in e.items()}}, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--book", type=int, required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--procs", type=int, default=4)
        p.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--data", type=Path, default=Path("outputs/v43"))
        p.add_argument("--out", type=Path, default=Path("outputs/v50w"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v50"
    raise SystemExit(main())
