"""v61 (V61_PREREGISTRATION.md): the book with the most dollars when ruin means losing the account (equity at or
under $50, 1% of $5,000) and ruin is held to at most 10% in 2018-2022 and in 2023-2026 alike.

  run    one (DS1, NS, RU) book, N5, in three of v58's locate worlds (W0, F0C1, F1C1)
  final  the choice per world, V61_REPORT.md and v61_summary.json
Aggregates only.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v58 as Q  # noqa: E402

P, W, R43 = Q.P, Q.W, Q.R43
R29 = R43.R29
DSS = (0.10, 0.20, 0.30, 0.45)
NSS = (0.60, 0.80, 1.00, 1.25, 1.50)
RUS = (0.25, 0.35, 0.50, 0.70)
GRID = list(itertools.product(DSS, NSS, RUS))
WORLDS = ("W0", "F0C1", "F1C1")
RUIN, RUIN75, MAX_RUIN = 0.01, 0.25, 0.10
CONTROL = "DS0.20-NS0.60-RU0.25"
STATS = ("med", "mean", "p_ruin", "p_ruin75", "p_half")
_YS = R29.year_stats


def year_stats(eq: np.ndarray, low: np.ndarray, e0: float = R29.E0) -> dict:
    return {**_YS(eq, low, e0), "p_ruin75": float((low <= RUIN75 * e0).mean())}


def name(ds: float, ns: float, ru: float) -> str:
    return f"DS{ds:.2f}-NS{ns:.2f}-RU{ru:.2f}"


def ens(per_seed: dict, sample: str) -> dict:
    return {k: float(np.mean([per_seed[s][sample][k] for s in per_seed])) for k in STATS}


def cmd_run(args) -> int:
    ds, ns, ru = GRID[args.cell]
    R29.RUIN = RUIN
    R29.year_stats = year_stats
    Q.SETS = {w: Q.SETS[w] for w in WORLDS}
    Q.BOOKS = [(ds, ns, ru, 5)]
    out = args.out
    args.out, args.book = out / f"tmp_{args.cell}", 0
    Q.cmd_run(args)
    z = json.loads((args.out / "b0.json").read_text(encoding="utf-8"))
    z.update(book=name(ds, ns, ru), cell=args.cell)
    (out / f"c{args.cell}.json").write_text(json.dumps(z, default=float), encoding="utf-8")
    return 0


def cmd_final(args) -> int:
    Z = {}
    for p in sorted(args.runs.rglob("c*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        Z[z["book"]] = z
    books = [name(*g) for g in GRID if name(*g) in Z]
    e = {(b, w, t, s): ens(Z[b]["res"][w][t], s) for b in books for w in WORLDS for t in Q.TASKS
         for s in ("all", "early", "late")}

    def ok(b, w):
        return all(e[(b, w, t, s)]["p_ruin"] <= MAX_RUIN for t in Q.TASKS for s in ("early", "late"))

    picks = {}
    for w in WORLDS:
        el = [b for b in books if ok(b, w)]
        picks[w] = {"choice": max(el, key=lambda b: e[(b, w, "base", "all")]["med"]) if el else None,
                    "eligible": len(el)}
    _d = P._d

    def row(b, w):
        c = [e[(b, w, "base", s)] for s in ("all", "early", "late")]
        h = max(e[(b, w, "hot5", s)]["p_ruin"] for s in ("early", "late"))
        return (f"| {b} | {_d(c[0]['med'])} | {_d(c[0]['mean'])} | {_d(c[1]['med'])} / {c[1]['p_ruin']:.1%} | "
                f"{_d(c[2]['med'])} / {c[2]['p_ruin']:.1%} | {h:.1%} | {c[0]['p_ruin']:.1%} | "
                f"{c[0]['p_ruin75']:.1%} | {c[0]['p_half']:.1%} |")

    head = ["| book | median all | mean all | 2018-2022 median / ruin | 2023-2026 median / ruin | HOT5 worst-period "
            "ruin | ruin all (lose 99%) | lose 75% | lose 50% |", "|---|---|---|---|---|---|---|---|---|"]
    L = ["# v61 report: most dollars with ruin = losing the account, at most 10% in each period", "",
         f"Pre-registered in V61_PREREGISTRATION.md. {len(books)} books, N5, TZC costs, IEX 15:50 decision, 31 seeds, "
         "4,000 one-year paths from $5,000. Ruin = equity at or under $50 at any point of the year. Eligible: ruin "
         "at most 10% in 2018-2022 and in 2023-2026, base and HOT5. Choice: highest all-years median.", ""]
    for w in WORLDS:
        c = picks[w]["choice"]
        L += [f"## {w}: {c or 'none'} ({picks[w]['eligible']} eligible)", ""] + head
        L += [row(b, w) for b in ([c] if c else []) + ([CONTROL] if CONTROL in Z and CONTROL != c else [])]
        L.append("")
    L += ["## Every book in F0C1, by all-years median", ""] + head
    L += [row(b, "F0C1") + (" eligible" if ok(b, "F0C1") else "")
          for b in sorted(books, key=lambda b: -e[(b, "F0C1", "base", "all")]["med"])]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V61_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v61_summary.json").write_text(json.dumps(
        {"picks": picks, "ensemble": {"|".join(k): v for k, v in e.items()}}, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cell", type=int, required=True, choices=range(len(GRID)))
    r.add_argument("--iex", type=Path, default=Path("outputs/v55/iex"))
    r.add_argument("--procs", type=int, default=os.cpu_count() or 4)
    r.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    r.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    r.add_argument("--data", type=Path, default=Path("outputs/v43"))
    r.add_argument("--out", type=Path, default=Path("outputs/v61w/runs"))
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/v61w/report"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v61"
    raise SystemExit(main())
