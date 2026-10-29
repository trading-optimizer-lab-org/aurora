"""v47h: three-year paths from $2,000 for the base book and the variants an API bot can run (descriptive).

v29's block bootstrap stretched to 756 sessions, with the equity read at each year's end. One level is added above
v29's five ($150,000) so the paths feel the book's capacity once they pass $60,000.

  run    one variant: its returns at every level (base costs and HOT 5%) and the three-year paths
  final  V47H_REPORT.md from the variants
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v47 as V  # noqa: E402

R43, R29, R32 = V.R43, V.R29, V.R32
E0 = 2_000.0
LEVELS = np.array([2_000.0, 2_500.0, 5_000.0, 10_000.0, 25_000.0, 60_000.0, 150_000.0])
YEARS = 3
NAMES = ("base", "C955", "X955", "TZA")
TASKS = ("base", "hot5")


def _job(job: tuple) -> tuple:
    name, level, task = job
    v = V.VARIANTS[name]
    R43._G["count"] = {}
    R43.LEVEL = level
    items, recs = V.items_for(*V.pairs(level, task, v), v)
    r, _ = V.account(items, recs)
    return job, r[R43._G["pos"]]


def three_years(R: np.ndarray, n: int) -> list[dict]:
    keep_days, keep_lv = R29.DAYS, R32.LEVELS
    R29.DAYS, R32.LEVELS = 252 * YEARS, LEVELS
    try:
        idx = R29.draws(n)
        out = []
        for y in range(1, YEARS + 1):
            eq, low = R32.paths(R, R, idx[:, :252 * y], R29.FIXED["FREE"], None, E0)
            q = np.quantile(eq, [0.05, 0.10, 0.25, 0.5, 0.75, 0.90])
            out.append({"year": y, "p05": q[0], "p10": q[1], "p25": q[2], "med": q[3], "p75": q[4], "p90": q[5],
                        "mean": float(eq.mean()), "p_ruin": float((low <= R29.RUIN * E0).mean()),
                        "p_loss": float((eq < E0).mean()), "over_60k": float((eq > 60_000).mean())})
        return out
    finally:
        R29.DAYS, R32.LEVELS = keep_days, keep_lv


def cmd_run(args) -> int:
    lv =tuple(float(x) for x in LEVELS)
    R43.setup(args, lv)
    v = V.VARIANTS[args.variant]
    if v.get("o1"):
        V._G.update(rows=V.R35._rows(args), days=V.candidates())
        with mp.get_context("fork").Pool(args.procs) as pool:
            got = pool.map(V._o1_job, [(level, task) for level in lv for task in TASKS], chunksize=1)
        for (level, task), (oi, om, _) in got:
            V._G["o1"][(level, task)] = (oi, om)
    jobs = [(args.variant, level, task) for level in lv for task in TASKS]
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = dict(pool.map(_job, jobs, chunksize=1))
    n = len(R43._G["cal"])
    res = {task: three_years(np.stack([got[(args.variant, level, task)] for level in lv]), n) for task in TASKS}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"v47h_{args.variant}.json").write_text(json.dumps({"variant": args.variant, "res": res},
                                                                   default=float), encoding="utf-8")
    print(json.dumps(res, default=float), flush=True)
    return 0


def _d(x: float) -> str:
    return f"${x:,.0f}"


def cmd_final(args) -> int:
    got = {json.loads(p.read_text(encoding="utf-8"))["variant"]: json.loads(p.read_text(encoding="utf-8"))
           for p in sorted(args.runs.rglob("v47h_*.json"))}
    L = ["# v47h: three years from $2,000", "",
         f"{R29.PATHS} block-bootstrap paths of {252 * YEARS} sessions from {_d(E0)}; ruin = at or under "
         f"{_d(R29.RUIN * E0)} at any time; $6 a month of server costs. Descriptive and in sample.", "",
         "| variant | costs | year | p10 | p25 | median | p75 | p90 | ruin so far | below $2,000 | over $60,000 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in NAMES:
        if n not in got:
            continue
        for task in TASKS:
            for r in got[n]["res"][task]:
                L.append(f"| {n} | {task} | {r['year']} | {_d(r['p10'])} | {_d(r['p25'])} | {_d(r['med'])} | "
                         f"{_d(r['p75'])} | {_d(r['p90'])} | {r['p_ruin']:.1%} | {r['p_loss']:.1%} | "
                         f"{r['over_60k']:.0%} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V47H_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--variant", choices=NAMES, required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--procs", type=int, default=4)
        p.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--data", type=Path, default=Path("outputs/v43"))
        p.add_argument("--out", type=Path, default=Path("outputs/v47h"))
    args = ap.parse_args()
    return cmd_run(args) if args.cmd == "run" else cmd_final(args)


if __name__ == "__main__":
    sys.argv[0] = "run_v47h"
    raise SystemExit(main())
