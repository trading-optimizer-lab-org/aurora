"""v45: the five best small-cap strategies alone, on one yardstick (V45_PREREGISTRATION.md). Each strategy runs alone
in v38/v39's $5,000 TradeZero International account; descriptive, nothing is chosen.

  run    one (costs, strategy) job: its daily returns at the five levels
  final  V45_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R38 = _script("run_v38")
R36, R35, R33, R29, R32 = R38.R36, R38.R35, R38.R33, R38.R29, R38.R32
R14 = R29.R14
LEVELS = R35.LEVELS
TASKS = R38.TASKS
HIST_LEVEL = 10_000.0
# id -> (description, {member: size}, plan)
STRATS: dict[str, tuple[str, dict[str, float], str]] = {
    "BOOK": ("DS1 20% + RU 70% + NS 40%", {"B:v19:DS1": 0.20, "B:v20:RU": 0.70, "B:v20:NS": 0.40}, "FREE"),
    "DS1": ("run-up short, DS1 20%", {"B:v19:DS1": 0.20}, "FREE"),
    "RU": ("run-up short, RU 70%", {"B:v20:RU": 0.70}, "FREE"),
    "NS": ("NS 40%", {"B:v20:NS": 0.40}, "FREE"),
    "XS1": ("intraday gap-up short to d3, XS1 20%", {"XS1": 0.20}, "PAID"),
    "RU20": ("RU 20%", {"B:v20:RU": 0.20}, "FREE"),
    "NS20": ("NS 20%", {"B:v20:NS": 0.20}, "FREE"),
}
IDS = list(STRATS)
JOBS = [(t, s) for t in TASKS for s in IDS]
CHECK = (23_143.0, 0.001)  # v39's robust book: median, ruin


def xs1_items(level: float, size: float, **costs) -> list[dict]:
    """v29's PAID intraday members restricted to the family v19:XS1."""
    its = [it for it in R35.paid_items(level, size, **costs) if str(it["member"]).endswith(":XS1")]
    assert its, "no XS1 trades among the PAID members"
    return its


def strat_items(rows: list[dict], sid: str, level: float, **costs) -> list[dict]:
    _, sizes, _ = STRATS[sid]
    if sid == "XS1":
        return xs1_items(level, sizes["XS1"], **costs)
    its: list[dict] = []
    for m, s in sizes.items():
        its += R35.book_items([r for r in rows if r["fam"] == m], level, s, None, **costs)
    return its


def hist_stats(r: np.ndarray, cal: pd.DatetimeIndex, fixed_month: float, e0: float = HIST_LEVEL) -> dict:
    """The historical path at one level's returns: monthly Sortino, CAGR, maximum drawdown, worst day."""
    daily = fixed_month * 12 / 252 / e0
    g = np.maximum(np.asarray(r, float), -1.0) - daily
    eq = np.cumprod(1 + g)
    m = pd.Series(1 + g, index=cal).groupby(cal.to_period("M")).prod() - 1
    down = np.sqrt(np.mean(np.minimum(m.to_numpy(), 0.0) ** 2))
    years = len(g) / 252
    return {"sortino": float(m.mean() / down * np.sqrt(12)) if down > 0 else float("nan"),
            "cagr": float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 else -1.0,
            "max_dd": float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()),
            "worst_day": float(g.min())}


def cmd_run(args) -> int:
    task, sid = JOBS[args.shard]
    rows = [r for r in R35._rows(args) if r["fam"] not in R38.DROP]
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    _, pos = R29._cal()
    R = np.zeros((len(LEVELS), len(pos)))
    n = 0
    for li, level in enumerate(LEVELS):
        its = strat_items(rows, sid, float(level), **R33.TASKS[task])
        n = max(n, len(its))
        R[li] = R36.stream(its, None)[pos]
        print(task, sid, level, len(its), round(float(R[li].sum()), 3), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    np.save(args.out / f"run_{task}_{sid}.npy", R)
    (args.out / f"run_{task}_{sid}.json").write_text(json.dumps({"trades": n}), encoding="utf-8")
    return 0


def cmd_final(args) -> int:
    R29.load(args.inputs, args.report)
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    li = int(np.flatnonzero(LEVELS == HIST_LEVEL)[0])
    res: dict = {}
    for sid in IDS:
        fixed = R29.FIXED[STRATS[sid][2]]
        res[sid] = {"trades": json.loads((args.runs / f"run_base_{sid}.json").read_text(encoding="utf-8"))["trades"]}
        for task in TASKS:
            R = np.load(args.runs / f"run_{task}_{sid}.npy")
            ix = idx if task == "base" else {"all": idx["all"]}
            res[sid][task] = {k: R32.stats(*R32.paths(R, R, v, fixed, None)) for k, v in ix.items()}
            if task == "base":
                res[sid]["hist"] = hist_stats(R[li], cal, fixed)
    d = R35._d
    b = res["BOOK"]["base"]["all"]
    ok = abs(b["med"] - CHECK[0]) <= 200 and abs(b["p_ruin"] - CHECK[1]) <= 0.002
    L = ["# v45: the five best small-cap strategies alone, on one yardstick", "",
         f"Each strategy alone in the $5,000 TradeZero International account (v38/v39's engine, v31's liquidation); "
         f"{R29.PATHS} one-year bootstrap paths; ruin = at or under $1,250 at any time. Historical path at the "
         f"${HIST_LEVEL:,.0f} level's returns. Descriptive: nothing is chosen.", "",
         f"Check: BOOK median {d(b['med'])}, ruin {b['p_ruin']:.1%} vs v39's {d(CHECK[0])}, {CHECK[1]:.1%}: "
         f"**{'reproduced' if ok else 'NOT reproduced, do not use the table'}**.", "",
         "## 1. Bootstrap from $5,000 (base costs)", "",
         "| id | strategy | plan | median | ruin | p10 | -50% | 2018-22 median | 2023+ median |",
         "|---|---|---|---|---|---|---|---|---|"]
    for sid in IDS:
        s = res[sid]["base"]
        L.append(f"| {sid} | {STRATS[sid][0]} | {STRATS[sid][2]} | {d(s['all']['med'])} | {s['all']['p_ruin']:.1%} | "
                 f"{d(s['all']['p10'])} | {s['all']['p_half']:.1%} | {d(s['early']['med'])} | {d(s['late']['med'])} |")
    L += ["", "## 2. Stress (median / ruin)", "", "| id | HOT 5% | spreads x2 | high |", "|---|---|---|---|"]
    for sid in IDS:
        L.append(f"| {sid} | " + " | ".join(f"{d(res[sid][t]['all']['med'])} / {res[sid][t]['all']['p_ruin']:.1%}"
                                            for t in R35.STRESS) + " |")
    L += ["", f"## 3. Historical path at ${HIST_LEVEL:,.0f} (base costs)", "",
          "| id | monthly Sortino | CAGR | max drawdown | worst day | trades |", "|---|---|---|---|---|---|"]
    for sid in IDS:
        h = res[sid]["hist"]
        L.append(f"| {sid} | {h['sortino']:.2f} | {h['cagr']:.1%} | {h['max_dd']:.1%} | {h['worst_day']:.1%} | "
                 f"{res[sid]['trades']:,} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V45_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v45_summary.json").write_text(json.dumps({"check": ok, "res": res}, indent=1, default=float),
                                               encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--choice", type=Path, required=True)
    r.add_argument("--shard", type=int, required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v45"
    raise SystemExit(main())
