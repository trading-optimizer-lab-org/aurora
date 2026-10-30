"""v48d: facts behind the book's fragile ruin (diagnostic, $10,000, base costs, base variant). For each member: the
candidate trades and those the account takes, their weights, each trade's net return per unit of weight, its worst
price against the entry, the growth of one trade at a fixed fraction of equity, and the worst trades left out.

  run  writes V48D_REPORT.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v47 as V  # noqa: E402

R43 = V.R43
FRACS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.70)
BINS = (0.0, 0.15, 0.25, 0.35, 0.50, 0.71)


def net(it: dict) -> float:
    return float(np.sum(it["r"])) - float(it["loc"])


def adverse(rec: dict) -> float:
    return max(float(np.nanmax(m)) for m in rec["M"]) - 1.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    ap.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    ap.add_argument("--data", type=Path, default=Path("outputs/v43"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v48d"))
    args = ap.parse_args()
    R43.setup(args, (float(V.LEVEL),))
    R43._G["count"] = {}
    R43.LEVEL = V.LEVEL
    items, recs = V.items_for(*V.pairs(V.LEVEL, "base", {}), {})
    r, taken = V.account(items, recs)
    D = R43._G["D"]
    took = {(it["sym"], int(it["t"]), it["member"]) for it in taken}
    L = ["# v48d: the book's trades at $10,000, base costs", "",
         f"Candidates {len(items)}, taken {len(taken)}. Net return = the trade's summed daily returns on the entry "
         "price after costs and locate, per unit of weight. Worst against = the highest price over the entry while "
         "fully open, minus 1.", ""]
    for mem in sorted({it["member"] for it in items}):
        c = [it for it in items if it["member"] == mem]
        t = [it for it in taken if it["member"] == mem]
        R = np.array([net(it) for it in c])
        Rt = np.array([net(it) for it in t])
        W = np.array([float(it["w"]) for it in t])
        A = np.array([adverse(recs[it["_rec"]]) for it in c])
        L += [f"## {mem}", "", f"Candidates {len(c)}, taken {len(t)}.", "",
              "| set | mean | median | p5 | p1 | worst | share < -50% | share < -100% | worst against p99 / max |",
              "|---|---|---|---|---|---|---|---|---|"]
        for nm, x, a in (("candidates", R, A), ("taken", Rt, np.array([adverse(recs[it["_rec"]]) for it in t]))):
            if len(x):
                L.append(f"| {nm} | {x.mean():+.1%} | {np.median(x):+.1%} | {np.quantile(x, 0.05):+.1%} | "
                         f"{np.quantile(x, 0.01):+.1%} | {x.min():+.1%} | {(x < -0.5).mean():.1%} | "
                         f"{(x < -1).mean():.1%} | {np.quantile(a, 0.99):+.0%} / {a.max():+.0%} |")
        L += ["", "Taken weights and their share of the summed weighted return (weight x net):", "",
              "| weight | trades | share of weighted return | worst weighted |", "|---|---|---|---|"]
        tot = float(np.sum(W * Rt)) if len(t) else 0.0
        for lo, hi in zip(BINS[:-1], BINS[1:]):
            k = (W >= lo) & (W < hi)
            if k.any():
                L.append(f"| {lo:.2f}-{hi:.2f} | {int(k.sum())} | {float(np.sum(W[k] * Rt[k])) / tot:+.0%} | "
                         f"{float(np.min(W[k] * Rt[k])):+.1%} |")
        L += ["", "Mean log growth of one trade at a fixed fraction f of equity (all candidates; a loss past 100% "
              "counts as -100%):", "", "| f | " + " | ".join(f"{f:.2f}" for f in FRACS) + " |",
              "|---|" + "---|" * len(FRACS),
              "| mean log(1 + f x net) | " + " | ".join(
                  f"{np.mean(np.log(np.maximum(1 + f * R, 1e-4))):+.4f}" for f in FRACS) + " |", ""]
        out = sorted((net(it), it) for it in c if (it["sym"], int(it["t"]), it["member"]) not in took)[:5]
        if out:
            L += ["Worst candidates the account left out:", "", "| entry | symbol | kind | weight | net | worst against |",
                  "|---|---|---|---|---|---|"]
            for x, it in out:
                L.append(f"| {D['dates'][int(it['t'])].date()} | {it['sym']} | {recs[it['_rec']]['kind']} | "
                         f"{float(it['w']):.2f} | {x:+.0%} | {adverse(recs[it['_rec']]):+.0%} |")
            L.append("")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V48D_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


if __name__ == "__main__":
    sys.argv[0] = "run_v48d"
    raise SystemExit(main())
