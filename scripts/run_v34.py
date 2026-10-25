"""v34: bigger positions with limit entries (V34_PREREGISTRATION.md). v33's A1 and limit members (run 40192951586)
in A1's account at sizes 20-40% a position under v31's liquidation; whether a bigger size with limit entries beats
A1.

  run    one shard of the members x sizes x costs: the account's one-year paths
  final  V34_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R33 = _script("run_v33")
R32, R29 = R33.R32, R33.R29
LEVELS, E0, FIXED = R33.LEVELS, R33.E0, R33.FIXED
ARMS = ("A1", "limit")
SIZES: tuple[float, ...] = (0.20, 0.25, 0.30, 0.40)
TASKS = R33.TASKS
JOBS = [(arm, s, task) for arm in ARMS for s in SIZES for task in TASKS]


def cmd_run(args) -> int:
    ch = json.loads((args.choice / "arms.json").read_text(encoding="utf-8"))
    jobs = JOBS[args.shard::args.shards]
    if not jobs:
        return 0
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, pos = R29._cal()
    idx = R32._sub_idx(cal)
    out = []
    for arm, size, task in jobs:
        R33.RISK, R33.CAP = size / 10, size
        R = np.zeros((len(LEVELS), len(pos)))
        R32.LOG.clear()
        for li, level in enumerate(LEVELS):
            R[li] = R33.account(ch["arms"][arm], float(level), **TASKS[task])[0][pos]
        for sample, ix in idx.items():
            if sample != "all" and task != "base":
                continue
            row = {"arm": arm, "size": size, "task": task if sample == "all" else f"base_{sample}",
                   **R32.stats(*R32.paths(R, R, ix, FIXED, None))}
            if task == "base" and sample == "all":
                row["liq_5k"] = R32.LOG[1] if len(R32.LOG) > 1 else None
            out.append(row)
            print(arm, size, row["task"], round(row["med"]), round(row["p_ruin"], 4), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"run_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


def verdict(get: dict) -> dict:
    """Section 2: the limit members at each size above 20% against A1 at 20%."""
    tasks = ("base", "base_late", "hot5", "spread2")
    out = {}
    for s in SIZES[1:]:
        if not all(("A1", 0.20, t) in get and ("limit", s, t) in get for t in tasks):
            continue
        beats = {t: get[("limit", s, t)]["med"] > get[("A1", 0.20, t)]["med"] for t in tasks}
        ruin = get[("limit", s, "base")]["p_ruin"] <= 0.01
        out[str(s)] = {**{f"beats_{t}": v for t, v in beats.items()}, "ruin_ok": ruin,
                       "raises": all(beats.values()) and ruin, "med": get[("limit", s, "base")]["med"]}
    passing = [s for s, v in out.items() if v["raises"]]
    return {"sizes": out, "choice": max(passing, key=lambda s: out[s]["med"]) if passing else None}


def cmd_final(args) -> int:
    d, p = R33.R31.R30._d, R33.R31.R30._p
    rows = [r for f in sorted(args.runs.rglob("run_*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]
    get = {(r["arm"], r["size"], r["task"]): r for r in rows}
    v = verdict(get)
    L = ["# v34: bigger positions with limit entries", "",
         f"v33's A1 and limit members, A1's account at each size, v31's liquidation; {R29.PATHS} one-year bootstrap "
         "paths from $5,000; ruin = at or under $1,250 at any time.", "", "## 1. The question", ""]
    for s, x in v["sizes"].items():
        L.append(f"- limit at {float(s):.0%}: beats A1 (20%) at base {x['beats_base']}, 2023+ {x['beats_base_late']}, "
                 f"HOT 5% {x['beats_hot5']}, spreads x2 {x['beats_spread2']}; ruin <= 1% {x['ruin_ok']} -> "
                 f"**{x['raises']}**")
    L += ["", f"**v34's choice: {'limit at ' + format(float(v['choice']), '.0%') if v['choice'] else 'none'}.**", "",
          "## 2. Results", "", "| members | size | task | median | mean | p10 | p90 | ruin | -50% | loss | "
          "worst 5% mean | liquidations at $5k |", "|" + "---|" * 12]
    for r in sorted(rows, key=lambda r: (r["arm"], r["size"], r["task"])):
        lq = r.get("liq_5k")
        L.append(f"| {r['arm']} | {r['size']:.0%} | {r['task']} | {d(r['med'])} | {d(r['mean'])} | {d(r['p10'])} | "
                 f"{d(r['p90'])} | {p(r['p_ruin'])} | {p(r['p_half'])} | {p(r['p_loss'])} | {d(r['es5'])} | "
                 f"{lq['n'] if lq else '-'} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V34_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v34_summary.json").write_text(json.dumps({"verdict": v, "results": rows}, indent=1, default=float),
                                               encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, required=True)
    r.add_argument("--shards", type=int, default=1)
    r.add_argument("--choice", type=Path, required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v34"
    raise SystemExit(main())
