"""v54dd: the maximum drawdown of v49's fixed book and v54m's margin pick, on v54's daily account returns.

  final  one-year paths from $5,000 (v54's bootstrap and costs) with each path's largest fall from its own high,
         and the single 2019-2026 sequence; V54DD_REPORT.md and v54dd_summary.json
Descriptive only: no choice is made here. Aggregates only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v54 as M  # noqa: E402

BOOKS = {"v49": (0.20, 0.40, 0.20, 5), "margin": (0.00, 0.40, 0.15, 5)}
SAMPLES = {"all": M.TEST_YEARS, "lock": M.LOCK_YEARS}


def dd_paths(R: np.ndarray, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """v32's paths (FREE fixed cost, size level by equity), returning the end equity and the largest fall from the
    path's own high."""
    lv, e0 = M.R43.LEVELS, M.R29.E0
    eq = np.full(idx.shape[0], e0)
    peak, mdd = eq.copy(), np.zeros(idx.shape[0])
    daily = M.R35.FIXED * 12 / 252
    for s in range(idx.shape[1]):
        k = np.clip(np.searchsorted(lv, eq, side="right") - 1, 0, len(lv) - 1)
        r = R[k, idx[:, s]]
        eq = np.where(eq > 0, np.maximum(eq * (1 + np.maximum(r, -1.0)) - daily, 0.0), 0.0)
        peak = np.maximum(peak, eq)
        mdd = np.maximum(mdd, 1 - eq / peak)
    return eq, mdd


def cmd_final(args) -> int:
    Z, years = {}, None
    want = {M.BOOKS.index(v): k for k, v in BOOKS.items()}
    for p in sorted(args.runs.rglob("b*.npz")):
        b = int(p.stem[1:])
        if b in want:
            z = np.load(p)
            Z[want[b]] = {k: z[k] for k in z.files if k != "years"}
            years = z["years"]
    out = {}
    for name, z in Z.items():
        out[name] = {}
        for t in M.TASKS:
            for smp, keep in SAMPLES.items():
                ix = M.draws(years, keep)
                eq, dd = map(np.concatenate, zip(*(dd_paths(z[f"{M.MAIN}|{t}"][s], ix) for s in range(len(M.SEEDS)))))
                out[name][f"{t}|{smp}"] = {"med": float(np.median(eq)), "dd_med": float(np.median(dd)),
                                           "dd_p90": float(np.quantile(dd, 0.9)), "dd_p99": float(np.quantile(dd, 0.99))}
        seq = np.flatnonzero(np.isin(years, M.TEST_YEARS))[None, :]
        eq, dd = dd_paths(z[f"{M.MAIN}|base"][0], seq)
        out[name]["history"] = {"end": float(eq[0]), "dd": float(dd[0])}
    _d = M.F._d
    L = ["# v54dd report: maximum drawdown of the fixed daily books", "",
         "One-year paths from $5,000 drawn from the sample's sessions, 31 seeds pooled. Drawdown: the largest fall "
         "of the account from its own highest value so far.", "",
         "| book | set | sample | median end | median max drawdown | 1 year in 10 worse than | 1 year in 100 worse than |",
         "|---|---|---|---|---|---|---|"]
    for name, g in out.items():
        for k, v in g.items():
            if k != "history":
                t, smp = k.split("|")
                L.append(f"| {name} | {t} | {smp} | {_d(v['med'])} | {v['dd_med']:.0%} | {v['dd_p90']:.0%} | "
                         f"{v['dd_p99']:.0%} |")
    L += ["", "Single sequence 2019-2026 from $5,000:", ""]
    L += [f"- {name}: end {_d(g['history']['end'])}, max drawdown {g['history']['dd']:.0%}" for name, g in out.items()]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V54DD_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v54dd_summary.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/v54ddw"))
    args = ap.parse_args()
    return {"final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v54dd"
    raise SystemExit(main())
