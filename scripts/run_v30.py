"""v30: $5,000 in one account (A) or $2,500 at full risk with a $2,500 reserve (B) (V30_PREREGISTRATION.md). v29's
FREE books under TradeZero International's costs; accounts freeze under $500 of equity, a loss can exceed the
equity (a debt), B deposits its reserve once; total wealth after one and three years of bootstrap paths.

  grid    one FREE cell (risk, cap) of v29's grid: every book at the five levels, A and B paths
  choose  the books compared
  sens    one shard of the battery
  final   V30_REPORT.md
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


R29 = _script("run_v29")
LEVELS = R29.LEVELS
BUDGET, HALF, MIN_EQ, LOW = 5_000.0, 2_500.0, 500.0, 1_000.0
RULES = {"A": (BUDGET, 0.0), "B": (HALF, HALF)}  # (first deposit, reserve)
HORIZONS = {"1y": (252, R29.SEED), "3y": (756, 30)}
CELLS = [c for c in R29.CELLS if c[0] == "FREE"]
A1 = {"plan": "FREE", "risk": 0.02, "cap": 0.20, "max_open": 20, "max_new": 3, "gross": 2.0, "floor": 2.5,
      "nohot": False, "gate": False}
BMAX = {"plan": "FREE", "risk": 0.04, "cap": 0.40, "max_open": 20, "max_new": 5, "gross": 2.0, "floor": 0.0,
        "nohot": False, "gate": False}
KEYS = R29.KEYS
TASKS = {"base": {}, "hot5": {"hot": 0.05}, "hot8": {"hot": 0.08}, "high": {"spread": 2.0, "fee": 3.0}}


def draws(n: int, days: int, seed: int, paths: int | None = None) -> np.ndarray:
    """v29's stationary block bootstrap (mean block 20 sessions) for any number of sessions."""
    rng = np.random.default_rng(seed)
    P = paths or R29.PATHS
    new = rng.random((P, days)) < 1 / R29.BLOCK
    new[:, 0] = True
    starts = rng.integers(n, size=(P, days))
    pos = np.maximum.accumulate(np.where(new, np.arange(days), 0), axis=1)
    return (np.take_along_axis(starts, pos, axis=1) + (np.arange(days) - pos)) % n


def accounts(R: np.ndarray, idx: np.ndarray, fixed_month: float, start: float, reserve: float
             ) -> tuple[np.ndarray, np.ndarray]:
    """Total wealth (equity + reserve not deposited) of each path, and whether the reserve was deposited. An account
    ending a session under MIN_EQ deposits the reserve once (paying any debt), else freezes; losses are not capped."""
    P = idx.shape[0]
    eq = np.full(P, start)
    live = np.ones(P, bool)
    used = np.zeros(P, bool)
    daily = fixed_month * 12 / 252
    for s in range(idx.shape[1]):
        k = np.clip(np.searchsorted(LEVELS, np.maximum(eq, 0.0), side="right") - 1, 0, len(LEVELS) - 1)
        eq = np.where(live, eq * (1 + R[k, idx[:, s]]) - daily, eq)
        bust = live & (eq < MIN_EQ)
        dep = bust & ~used & (reserve > 0)
        eq = np.where(dep, eq + reserve, eq)
        used |= dep
        live &= ~(bust & (~dep | (eq < MIN_EQ)))
    return eq + np.where(used, 0.0, reserve), used


def wealth_stats(w: np.ndarray, used: np.ndarray) -> dict:
    q = np.sort(w)
    return {"med": float(np.median(w)), "mean": float(w.mean()), "p10": float(np.quantile(w, 0.10)),
            "p90": float(np.quantile(w, 0.90)), "p_loss": float((w < BUDGET).mean()),
            "p_1000": float((w <= LOW).mean()), "p_500": float((w <= MIN_EQ).mean()), "p_debt": float((w < 0).mean()),
            "es5": float(q[:max(1, int(0.05 * len(q)))].mean()), "worst": float(q[0]),
            "p_deposit": float(used.mean())}


def evaluate(R: np.ndarray, idx: dict, fixed_month: float) -> dict:
    out = {}
    for rule, (start, reserve) in RULES.items():
        for hz, ix in idx.items():
            out[f"{rule}_{hz}"] = wealth_stats(*accounts(R, ix, fixed_month, start, reserve))
    return out


def _idx(n: int) -> dict:
    return {hz: draws(n, days, seed) for hz, (days, seed) in HORIZONS.items()}


def cmd_grid(args) -> int:
    plan, risk, cap = CELLS[args.shard]
    R29.load(args.inputs, args.report)
    R29.set_plan(plan)
    cal, pos = R29._cal()
    idx = _idx(len(cal))
    combos = [(f, nh, gt) for f in R29.FLOORS for nh in R29.NOHOT for gt in R29.GATE]
    books = [(mo, mn, g) for mo in R29.MAX_OPEN for mn in R29.MAX_NEW for g in R29.GROSS]
    R = {(c, b): np.zeros((len(LEVELS), len(cal))) for c in combos for b in books}
    for li, level in enumerate(LEVELS):
        raw = R29.book(plan, risk, cap, float(level))
        for f, nh, gt in combos:
            its = R29.tz_items(raw, float(level), *R29.BASE_LOC, floor=f, nohot=nh)
            if gt:
                its = R29.gate(its)
            for b in books:
                R[((f, nh, gt), b)][li] = R29.series(its, b[2], b[0], b[1])[0][pos]
        print(f"{plan} risk {risk} cap {cap} level {level:.0f}: {len(raw)} trades", flush=True)
    rows = []
    for (c, b), arr in R.items():
        rows.append({"plan": plan, "risk": risk, "cap": cap, "floor": c[0], "nohot": c[1], "gate": c[2],
                     "max_open": b[0], "max_new": b[1], "gross": b[2], **evaluate(arr, idx, R29.FIXED[plan])})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"grid_{args.shard:02d}.json").write_text(json.dumps(rows, default=float), encoding="utf-8")
    return 0


def _same(row: dict, c: dict) -> bool:
    return all(row[k] == c[k] or (isinstance(c[k], float) and abs(float(row[k]) - c[k]) < 1e-12) for k in KEYS)


def best(rows: list[dict], rule: str) -> dict | None:
    if not rows:
        return None
    return max(rows, key=lambda r: (r[f"{rule}_1y"]["med"], -r[f"{rule}_1y"]["p_1000"]))


def cmd_choose(args) -> int:
    rows = [r for p in sorted(args.grid.rglob("grid_*.json")) for r in json.loads(p.read_text(encoding="utf-8"))]
    out: dict = {"n": len(rows), "books": {"A1": A1, "B_max": BMAX}}
    for name, rule in (("B_best", "B"), ("A_best", "A")):
        b = best(rows, rule)
        out["books"][name] = {k: b[k] for k in KEYS} if b else A1
        out[f"top_{rule}"] = sorted(rows, key=lambda r: -r[f"{rule}_1y"]["med"])[:10]
    out["grid_rows"] = {name: next((r for r in rows if _same(r, c)), None) for name, c in out["books"].items()}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "choice.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps(out["books"], indent=1, default=float), flush=True)
    return 0


def cmd_sens(args) -> int:
    ch = json.loads((args.choice / "choice.json").read_text(encoding="utf-8"))
    jobs = [(name, task) for name in ("A1", "B_best", "B_max", "A_best") for task in TASKS]
    mine = jobs[args.shard::args.shards]
    if not mine:
        return 0
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, _ = R29._cal()
    idx = _idx(len(cal))
    v29_idx = R29.draws(len(cal))
    out = []
    for name, task in mine:
        c = ch["books"][name]
        R, _ = R29._levels(c, **TASKS[task])
        row = {"book": name, "task": task, **evaluate(R, idx, R29.FIXED["FREE"])}
        if name == "A1" and task == "base":
            eq, low = R29.paths(R, v29_idx, R29.FIXED["FREE"])
            row["v29_check"] = R29.year_stats(eq, low)
        out.append(row)
        print(name, task, round(row["A_1y"]["med"]), round(row["B_1y"]["med"]), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"sens_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


def _d(x) -> str:
    return "-" if not isinstance(x, (int, float)) or not np.isfinite(x) else f"${x:,.0f}"


def _p(x) -> str:
    return "-" if not isinstance(x, (int, float)) or not np.isfinite(x) else f"{x:.1%}"


def verdict(a: dict, b: dict) -> dict:
    """Section 4: B_best against A1 on the one-year paths."""
    checks = {"higher_median": b["med"] > a["med"], "smaller_tail": b["es5"] > a["es5"],
              "no_more_80pct_losses": b["p_1000"] <= a["p_1000"]}
    return {**checks, "b_better": all(checks.values()), "b_avoids_tail": checks["smaller_tail"]
            and checks["no_more_80pct_losses"]}


def cmd_final(args) -> int:
    ch = json.loads((args.choice / "choice.json").read_text(encoding="utf-8"))
    sens = [r for p in sorted(args.sens.rglob("sens_*.json")) for r in json.loads(p.read_text(encoding="utf-8"))]
    get = {(r["book"], r["task"]): r for r in sens}
    L = ["# v30: $5,000 in one account (A) or $2,500 at full risk with a $2,500 reserve (B)", "",
         f"v29's FREE books, TradeZero International's costs, base locates HTB 1% / HOT 3% unless stated; "
         f"{R29.PATHS} bootstrap paths; W = equity + reserve not deposited, from $5,000; accounts freeze under $500; "
         f"losses may exceed the equity (debt). {ch['n']} books in the grid.", "", "## 1. The question", ""]
    a, b = get.get(("A1", "base")), get.get(("B_best", "base"))
    v = verdict(a["A_1y"], b["B_1y"]) if a and b else None
    if v:
        L += [f"B_best (B) against A1 (A), one year: higher median {v['higher_median']}, smaller tail (mean of the worst "
              f"5%) {v['smaller_tail']}, no more 80% losses {v['no_more_80pct_losses']}. "
              f"**B better: {v['b_better']}. B avoids the tail: {v['b_avoids_tail']}.**", ""]
    L += ["## 2. Books", "", "| book | " + " | ".join(KEYS[1:]) + " |", "|" + "---|" * len(KEYS)]
    for name, c in ch["books"].items():
        L.append(f"| {name} | " + " | ".join(str(c[k]) for k in KEYS[1:]) + " |")
    L += ["", "## 3. Results", "", "| book | costs | rule | horizon | median W | mean | p10 | p90 | W < $5k | W <= $1k | "
          "debt | worst 5% mean | worst | deposit |", "|" + "---|" * 14]
    for r in sens:
        for key in ("A_1y", "B_1y", "A_3y", "B_3y"):
            s = r[key]
            rule, hz = key.split("_")
            L.append(f"| {r['book']} | {r['task']} | {rule} | {hz} | {_d(s['med'])} | {_d(s['mean'])} | {_d(s['p10'])} | "
                     f"{_d(s['p90'])} | {_p(s['p_loss'])} | {_p(s['p_1000'])} | {_p(s['p_debt'])} | {_d(s['es5'])} | "
                     f"{_d(s['worst'])} | {_p(s['p_deposit']) if rule == 'B' else '-'} |")
    chk = (get.get(("A1", "base")) or {}).get("v29_check")
    if chk:
        L += ["", f"v29 check (A1 with v29's path rule): median {_d(chk['med'])}, ruin {_p(chk['p_ruin'])}."]
    L += ["", "## 4. Top 10 of the grid by one-year median W", "", "| rule | risk | cap | max open | new | gross | floor | "
          "median W | W <= $1k | worst 5% mean |", "|" + "---|" * 10]
    for rule in ("B", "A"):
        for r in ch[f"top_{rule}"]:
            s = r[f"{rule}_1y"]
            L.append(f"| {rule} | {r['risk']:.1%} | {r['cap']:.0%} | {r['max_open']} | {r['max_new']} | {r['gross']:g} | "
                     f"{r['floor']:g} | {_d(s['med'])} | {_p(s['p_1000'])} | {_d(s['es5'])} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V30_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v30_summary.json").write_text(json.dumps({"verdict": v, "books": ch["books"], "sens": sens},
                                                          indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("grid", "sens"):
        s = sub.add_parser(name)
        s.add_argument("--shard", type=int, required=True)
        s.add_argument("--shards", type=int, default=1)
    sub.choices["sens"].add_argument("--choice", type=Path, required=True)
    sub.add_parser("choose").add_argument("--grid", type=Path, required=True)
    f = sub.add_parser("final")
    f.add_argument("--choice", type=Path, required=True)
    f.add_argument("--sens", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"grid": cmd_grid, "choose": cmd_choose, "sens": cmd_sens, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v30"
    raise SystemExit(main())
