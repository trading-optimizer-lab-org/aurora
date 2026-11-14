"""v61b (V61B_PREREGISTRATION.md): v61 with RU extended past the grid edge where v61's choice landed (RU 0.70),
one job per (book, locate world) so the run fills the concurrent job limit.

  run    one (DS1, NS, RU) book in one locate world
  final  merge worlds per book, then v61's choice rule and report
Aggregates only.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v61 as B  # noqa: E402

DSS = (0.15, 0.20, 0.25)
NSS = (0.80, 1.00, 1.25)
RUS = (0.70, 0.90, 1.20, 1.50, 2.00)
GRID = list(itertools.product(DSS, NSS, RUS))
WORLDS = B.WORLDS
CELLS = list(itertools.product(range(len(GRID)), WORLDS))


def cmd_run(args) -> int:
    g, w = CELLS[args.cell]
    B.GRID, B.WORLDS = GRID, (w,)
    args.cell, args.out = g, args.out / w
    return B.cmd_run(args)


def cmd_final(args) -> int:
    Z = {}
    for p in sorted(args.runs.rglob("c*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        Z.setdefault(z["book"], {**z, "res": {}})["res"].update(z["res"])
    missing = [b for b, z in Z.items() if set(z["res"]) != set(WORLDS)]
    if missing:
        print("books missing a world (dropped):", missing, flush=True)
    B.GRID = GRID
    with tempfile.TemporaryDirectory() as d:
        for i, (b, z) in enumerate(Z.items()):
            if b not in missing:
                (Path(d) / f"c{i}.json").write_text(json.dumps(z, default=float), encoding="utf-8")
        args.runs = Path(d)
        B.cmd_final(args)
    rep = args.out / "V61_REPORT.md"
    txt = rep.read_text(encoding="utf-8").replace("# v61 report:", "# v61b report (RU extended):", 1)
    (args.out / "V61B_REPORT.md").write_text(txt, encoding="utf-8")
    rep.unlink()
    (args.out / "v61_summary.json").rename(args.out / "v61b_summary.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cell", type=int, required=True, choices=range(len(CELLS)))
    r.add_argument("--iex", type=Path, default=Path("outputs/v55/iex"))
    r.add_argument("--procs", type=int, default=os.cpu_count() or 4)
    r.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    r.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    r.add_argument("--data", type=Path, default=Path("outputs/v43"))
    r.add_argument("--out", type=Path, default=Path("outputs/v61bw/runs"))
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/v61bw/report"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v61b"
    raise SystemExit(main())
