"""v59 (V59_PREREGISTRATION.md): v58's chosen book with its night short (NS) limited to bigger opening gaps.

  run    the book DS0.20-NS0.60-RU0.25-N5 in v58's locate worlds, NS trades kept only when the entry day's open
         is at least G above the prior close (G = none, 30, 50, 75, 100, 150 %)
  final  V59_REPORT.md and v59_summary.json
Aggregates only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v58 as Q  # noqa: E402

V, W, P, R43 = Q.V, Q.W, Q.P, Q.R43
BOOK = 23  # DS0.20-NS0.60-RU0.25-N5 in v56's BOOKS
GAPS = ("none", "30", "50", "75", "100", "150")
_GAP: dict = {"min": None}
_PAIRS = V.pairs


def gap_of(it: dict) -> float:
    D = R43._G["D"]
    t, j = int(it["t"]), int(it["j"])
    o, c = float(D["O"][t, j]), float(D["C"][t - 1, j]) if t >= 1 else np.nan
    return o / c - 1.0 if np.isfinite(o) and np.isfinite(c) and c > 0 else np.nan


def keep(it: dict) -> bool:
    g = _GAP["min"]
    if g is None or it.get("member") != W.NS:
        return True
    x = gap_of(it)
    return bool(np.isfinite(x) and x >= g)


def pairs(level: float, task: str, v: dict) -> tuple[list, list]:
    its, metas = _PAIRS(level, task, v)
    kept = [(it, m) for it, m in zip(its, metas) if keep(it)]
    return [x[0] for x in kept], [x[1] for x in kept]


def counts() -> dict:
    """NS candidate trades at the level nearest $5,000, base costs, before the account's daily and open-position caps."""
    level = min({lv for lv, _ in R43._G["its"]}, key=lambda lv: abs(lv - 5000.0))
    its, _ = _PAIRS(level, "base", P.Q.TZA)
    g = np.array([gap_of(it) for it in its if it.get("member") == W.NS], float)
    return {"ns_all": int(len(g)), "ns_kept": int(len(g) if _GAP["min"] is None else np.sum(g >= _GAP["min"])),
            "gap_median": float(np.nanmedian(g)) if len(g) else None}


def cmd_run(args) -> int:
    _GAP["min"] = None if args.gap == "none" else int(args.gap) / 100.0
    V.pairs = pairs
    out = args.out
    args.out = out / f"tmp_{args.gap}"
    args.book = BOOK
    Q.cmd_run(args)
    z = json.loads((args.out / f"b{BOOK}.json").read_text(encoding="utf-8"))
    z.update(book=f"G{args.gap}", gap=args.gap, counts=counts())
    (out / f"b{args.gap}.json").write_text(json.dumps(z, default=float), encoding="utf-8")
    print(json.dumps({"gap": args.gap, **z["counts"]}), flush=True)
    return 0


def cmd_final(args) -> int:
    Z = {}
    for p in sorted(args.runs.rglob("b*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        if "gap" in z:
            Z[z["gap"]] = z
    gaps = [g for g in GAPS if g in Z]
    e = {(g, w, t, s): W.ensemble(Z[g]["res"][w][t], s) for g in gaps for w in Q.SETS for t in Q.TASKS
         for s in ("all", "early", "late")}
    _d = P._d
    L = ["# v59 report: v58's book with the night short limited to bigger gaps", "",
         f"Pre-registered in V59_PREREGISTRATION.md. Book {Q.CHECK_BOOK}, close entries decided on IEX, TZC costs, "
         "31 seeds, one-year paths from $5,000. Each cell: median end equity / chance of ruin, all years.", ""]
    if "none" in Z:
        a = e[("none", "W0", "base", "all")]
        ok = abs(a["med"] - Q.CHECK[0]) <= 1.0 and abs(a["ruin"] - Q.CHECK[1]) <= 0.0005
        L += [f"Check: no gap filter in W0 {_d(a['med'])} ruin {a['ruin']:.1%} vs v56 {_d(Q.CHECK[0])} "
              f"{Q.CHECK[1]:.1%}: {'reproduced' if ok else 'NOT reproduced'}.", ""]
    L += ["| NS gap at least | NS candidate trades | " + " | ".join(Q.SETS) + " | HOT5 ruin (W0) | 2023+ (W0) |",
          "|---|---|" + "---|" * (len(Q.SETS) + 2)]
    for g in gaps:
        c = Z[g]["counts"]
        h, late = e[(g, "W0", "hot5", "all")], e[(g, "W0", "base", "late")]
        L.append(f"| {g if g == 'none' else g + '%'} | {c['ns_kept']} of {c['ns_all']} | "
                 + " | ".join(f"{_d(e[(g, w, 'base', 'all')]['med'])} / {e[(g, w, 'base', 'all')]['ruin']:.1%}"
                              for w in Q.SETS)
                 + f" | {h['ruin']:.1%} | {_d(late['med'])} / {late['ruin']:.1%} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V59_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v59_summary.json").write_text(json.dumps(
        {"counts": {g: Z[g]["counts"] for g in gaps}, "ensemble": {"|".join(k): v for k, v in e.items()}},
        default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--gap", choices=GAPS, required=True)
    r.add_argument("--iex", type=Path, default=Path("outputs/v55/iex"))
    r.add_argument("--procs", type=int, default=4)
    r.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    r.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    r.add_argument("--data", type=Path, default=Path("outputs/v43"))
    r.add_argument("--out", type=Path, default=Path("outputs/v59w/runs"))
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/v59w/report"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v59"
    raise SystemExit(main())
