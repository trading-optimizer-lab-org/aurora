"""v60 (V60_PREREGISTRATION.md): v59's gap filter on the night short crossed with a larger NS size, chosen on
2018-2022 and graded on 2023-2026.

  run    one (gap, NS size) book, DS1 0.20 and RU 0.25 fixed, in v58's locate worlds
  final  the choice per world, V60_REPORT.md and v60_summary.json
Aggregates only.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v59 as G  # noqa: E402

Q, W, P, V = G.Q, G.W, G.P, G.V
S = Q.S
GAPS = ("none", "50", "75", "100", "150")
NS_SIZES = (0.60, 0.80, 1.00, 1.20)
GRID = list(itertools.product(GAPS, NS_SIZES))
CONTROL = "Gnone-NS0.60"


def name(gap: str, ns: float) -> str:
    return f"G{gap}-NS{ns:.2f}"


def cmd_run(args) -> int:
    gap, ns = GRID[args.cell]
    G._GAP["min"] = None if gap == "none" else int(gap) / 100.0
    V.pairs = G.pairs
    Q.BOOKS = [(0.20, ns, 0.25, 5)]
    out = args.out
    args.out = out / f"tmp_{args.cell}"
    args.book = 0
    Q.cmd_run(args)
    z = json.loads((args.out / "b0.json").read_text(encoding="utf-8"))
    z.update(book=name(gap, ns), cell=args.cell, counts=G.counts())
    (out / f"c{args.cell}.json").write_text(json.dumps(z, default=float), encoding="utf-8")
    print(json.dumps({"book": z["book"], **z["counts"]}), flush=True)
    return 0


def cmd_final(args) -> int:
    Z = {}
    for p in sorted(args.runs.rglob("c*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        Z[z["book"]] = z
    books = [name(g, n) for g, n in GRID if name(g, n) in Z]
    e = {(b, w, t, s): W.ensemble(Z[b]["res"][w][t], s) for b in books for w in Q.SETS for t in Q.TASKS
         for s in ("all", "early", "late")}
    picks = {w: S.pick(e, books, w) for w in Q.SETS}
    _d = P._d

    def cell(b, w, s):
        a = e[(b, w, "base", s)]
        return f"{_d(a['med'])} / {a['ruin']:.1%}"

    L = ["# v60 report: night-short gap filter x NS size, chosen on 2018-2022", "",
         f"Pre-registered in V60_PREREGISTRATION.md. {len(books)} books (DS1 0.20, RU 0.25, N5), close entries "
         "decided on IEX, TZC costs, 31 seeds, one-year paths from $5,000. Cells: median end equity / ruin.", ""]
    if CONTROL in Z:
        a = e[(CONTROL, "W0", "base", "all")]
        ok = abs(a["med"] - Q.CHECK[0]) <= 1.0 and abs(a["ruin"] - Q.CHECK[1]) <= 0.0005
        L += [f"Check: {CONTROL} in W0 {_d(a['med'])} ruin {a['ruin']:.1%}: "
              f"{'reproduced' if ok else 'NOT reproduced'}.", ""]
    L += ["| world | chosen on 2018-2022 | 2018-2022 | 2023-2026 | all years | control 2023-2026 | control all |",
          "|---|---|---|---|---|---|---|"]
    for w in Q.SETS:
        c = picks[w]["choice"]
        L.append(f"| {w} | {c or 'none'} | {cell(c, w, 'early') if c else '-'} | {cell(c, w, 'late') if c else '-'} "
                 f"| {cell(c, w, 'all') if c else '-'} | {cell(CONTROL, w, 'late')} | {cell(CONTROL, w, 'all')} |")
    L += ["", "## Every book in F0C1: 2018-2022 | 2023-2026 | all years | HOT5 ruin all", "",
          "| book | NS candidates | 2018-2022 | 2023-2026 | all | HOT5 ruin |", "|---|---|---|---|---|---|"]
    for b in books:
        c = Z[b]["counts"]
        L.append(f"| {b} | {c['ns_kept']} | {cell(b, 'F0C1', 'early')} | {cell(b, 'F0C1', 'late')} | "
                 f"{cell(b, 'F0C1', 'all')} | {e[(b, 'F0C1', 'hot5', 'all')]['ruin']:.1%} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V60_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v60_summary.json").write_text(json.dumps(
        {"picks": picks, "ensemble": {"|".join(k): v for k, v in e.items()}}, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cell", type=int, required=True, choices=range(len(GRID)))
    r.add_argument("--iex", type=Path, default=Path("outputs/v55/iex"))
    r.add_argument("--procs", type=int, default=4)
    r.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    r.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    r.add_argument("--data", type=Path, default=Path("outputs/v43"))
    r.add_argument("--out", type=Path, default=Path("outputs/v60w/runs"))
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/v60w/report"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v60"
    raise SystemExit(main())
