"""v48b: the RU size dial under TradeZero API rules, and the capital plans (V48B_PREREGISTRATION.md).

  run    one book under v47's API rules (TZA) with v48's ensemble: v29's bootstrap and v30's capital plans
  final  V48B_REPORT.md and v48b_summary.json
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v48 as W  # noqa: E402

V, R43, R40, R35, R29 = W.V, W.R43, W.R40, W.R35, W.R29
LEVELS, E2K, ENS_TASKS, SEEDS = W.LEVELS, W.E2K, W.ENS_TASKS, W.SEEDS
BOOKS = [(0.20, 0.40, ru, 5) for ru in W.RUS] + [W.BASE]
PLANS = {"A": (5_000.0, 0.0), "B": (2_500.0, 2_500.0), "C": (2_000.0, 0.0)}  # (first deposit, reserve)
HORIZONS = {"1y": (252, R29.SEED), "3y": (756, 30)}
MIN_EQ, LOW = 500.0, 1_000.0
MAX_RUIN = W.MAX_RUIN
CHECK_BASE = (20_742.0, 0.059, 300.0, 0.005)
CHECK_N5 = (18_765.0, 0.077, 300.0, 0.005)

_G: dict = {}


def draws(n: int, days: int, seed: int, paths: int | None = None) -> np.ndarray:
    """v30's stationary block bootstrap (mean block 20 sessions)."""
    rng = np.random.default_rng(seed)
    P = paths or R29.PATHS
    new = rng.random((P, days)) < 1 / R29.BLOCK
    new[:, 0] = True
    starts = rng.integers(n, size=(P, days))
    pos = np.maximum.accumulate(np.where(new, np.arange(days), 0), axis=1)
    return (np.take_along_axis(starts, pos, axis=1) + (np.arange(days) - pos)) % n


def accounts(R: np.ndarray, levels: np.ndarray, idx: np.ndarray, fixed_month: float, start: float,
             reserve: float) -> tuple[np.ndarray, np.ndarray]:
    """v30's accounts with the book's returns at ``levels``: total wealth of each path and whether the reserve was
    deposited. An account ending a session under MIN_EQ deposits the reserve once (paying any debt), else freezes."""
    P = idx.shape[0]
    eq = np.full(P, start)
    live = np.ones(P, bool)
    used = np.zeros(P, bool)
    daily = fixed_month * 12 / 252
    for s in range(idx.shape[1]):
        k = np.clip(np.searchsorted(levels, np.maximum(eq, 0.0), side="right") - 1, 0, len(levels) - 1)
        eq = np.where(live, eq * (1 + R[k, idx[:, s]]) - daily, eq)
        bust = live & (eq < MIN_EQ)
        dep = bust & ~used & (reserve > 0)
        eq = np.where(dep, eq + reserve, eq)
        used |= dep
        live &= ~(bust & (~dep | (eq < MIN_EQ)))
    return eq + np.where(used, 0.0, reserve), used


def plan_stats(w: np.ndarray, used: np.ndarray) -> dict:
    q = np.sort(w)
    return {"med": float(np.median(w)), "p10": float(np.quantile(w, 0.10)), "p_1000": float((w <= LOW).mean()),
            "es5": float(q[:max(1, int(0.05 * len(q)))].mean()), "p_dep": float(used.mean())}


def plans_ens(per_seed: dict, key: str) -> dict:
    """Mean over the seeds of each statistic of one plan and horizon."""
    return {k: float(np.mean([per_seed[s][key][k] for s in per_seed])) for k in per_seed[next(iter(per_seed))][key]}


def b_better(a: dict, b: dict) -> bool:
    return b["med"] > a["med"] and b["es5"] > a["es5"] and b["p_1000"] <= a["p_1000"]


def choose(books: dict) -> str | None:
    ok = [k for k, z in books.items() if all(W.ensemble(z["res"][t], "all")["ruin"] <= MAX_RUIN for t in ENS_TASKS)]
    return max(ok, key=lambda k: W.ensemble(books[k]["res"]["base"], "all")["med"]) if ok else None


# ---------------------------------------------------------------- run

def _plans_job(job: tuple) -> tuple:
    key, Rs = job
    R = np.stack(Rs)
    return key, {f"{p}_{hz}": plan_stats(*accounts(R, _G["levels"], _G["idx"][hz], R35.FIXED, start, res))
                 for p, (start, res) in PLANS.items() for hz in HORIZONS}


def cmd_run(args) -> int:
    ds, ns, ru, mn = BOOKS[args.book]
    W._G["mn"] = int(mn)
    R40.SIZES = W.sizes_of(ds, ns, ru)
    t0 = time.time()
    lv2 = [float(x) for x in np.r_[E2K, LEVELS]]
    R43.setup(args, tuple(lv2))
    V._G.update(rows=R35._rows(args), days=V.candidates())
    jobs = [(lv, t) for t in ENS_TASKS for lv in lv2]
    with mp.get_context("fork").Pool(args.procs) as pool:
        for (lv, t), (oi, om, _) in pool.map(V._o1_job, jobs, chunksize=1):
            V._G["o1"][(lv, t)] = (oi, om)
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = dict(pool.map(W._api_job, jobs, chunksize=1))
    n = len(got[jobs[0]][0])
    _G.update(levels=np.array(lv2), idx={hz: draws(n, d, sd) for hz, (d, sd) in HORIZONS.items()})
    with mp.get_context("fork").Pool(args.procs) as pool:
        B = dict(pool.map(W._boot_job, [((t, s), [got[(lv, t)][s] for lv in lv2], ("all", "early", "late"))
                                        for t in ENS_TASKS for s in SEEDS], chunksize=1))
        P = dict(pool.map(_plans_job, [((t, s), [got[(lv, t)][s] for lv in lv2]) for t in ENS_TASKS for s in SEEDS],
                          chunksize=1))
    out = {"book": W.book_id(ds, ns, ru, int(mn)), "sizes": [ds, ns, ru, mn],
           "res": {t: {str(s): B[(t, s)] for s in SEEDS} for t in ENS_TASKS},
           "plans": {t: {str(s): P[(t, s)] for s in SEEDS} for t in ENS_TASKS},
           "sec": round(time.time() - t0)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"b{args.book}.json").write_text(json.dumps(out, default=float), encoding="utf-8")
    e = W.ensemble(out["res"]["base"], "all")
    print(out["book"], f"TZA ens median {e['med']:,.0f} ruin {e['ruin']:.1%} | seed0 {e['med0']:,.0f} {e['ruin0']:.1%}",
          {k: round(v["med"]) for k, v in out["plans"]["base"]["0"].items()}, out["sec"], flush=True)
    return 0


# ---------------------------------------------------------------- final

def _d(x: float) -> str:
    return f"${x:,.0f}"


def _ok(med: float, ruin: float, ref: tuple) -> bool:
    return abs(med - ref[0]) <= ref[2] and abs(ruin - ref[1]) <= ref[3]


def cmd_final(args) -> int:
    books = {}
    for p in sorted(args.runs.rglob("b[0-9]*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        books[z["book"]] = z
    e = {(k, t, s): W.ensemble(books[k]["res"][t], s) for k in books for t in ENS_TASKS for s in ("all", "early", "late")}
    pe = {(k, t, key): plans_ens(books[k]["plans"][t], key) for k in books for t in ENS_TASKS
          for key in books[k]["plans"][t]["0"]}
    base, n5 = W.book_id(*W.BASE), W.book_id(0.20, 0.40, 0.70, 5)
    zb, zn = e.get((base, "base", "all")), e.get((n5, "base", "all"))
    checks = {"base": bool(zb) and _ok(zb["med0"], zb["ruin0"], CHECK_BASE),
              "n5": bool(zn) and _ok(zn["med"], zn["ruin"], CHECK_N5)}
    ch = choose(books)
    plan = None
    if ch:
        plan = "B" if b_better(pe[(ch, "base", "A_1y")], pe[(ch, "base", "B_1y")]) else "A"
    L = ["# v48b: the RU size dial under TradeZero API rules, and the capital plans", "",
         f"TZA rules, {len(SEEDS)} seeds (seed 0 = history, the rest drop {W.DROP:.0%} of candidates). Bootstrap: "
         f"{R29.PATHS} one-year paths from $5,000, ruin at or under $1,250. Plans: A $5,000; B $2,500 plus a $2,500 "
         "reserve; C $2,000. W = total wealth; ens = mean over seeds.", "",
         f"Checks: base seed 0 vs v47 TZA {'reproduced' if checks['base'] else 'NOT reproduced'}; RU 0.70 at 5 a day vs "
         f"v48 {'reproduced' if checks['n5'] else 'NOT reproduced'}.", "",
         f"## Definitive strategy: book **{ch}**, capital plan **{plan}**", "",
         "## 1. Bootstrap from $5,000 (TZA)", "",
         "| book | ens median | ens ruin | p90 ruin | seed 0 | 2018-22 | 2023+ | HOT 5% |",
         "|---|---|---|---|---|---|---|---|"]
    order = sorted(books, key=lambda k: -books[k]["sizes"][2] - books[k]["sizes"][3] / 100)
    for k in order:
        a, h = e[(k, "base", "all")], e[(k, "hot5", "all")]
        L.append(f"| {k} | {_d(a['med'])} | {a['ruin']:.1%} | {a['ruin90']:.1%} | {_d(a['med0'])} / {a['ruin0']:.1%} | "
                 f"{_d(e[(k, 'base', 'early')]['med'])} / {e[(k, 'base', 'early')]['ruin']:.1%} | "
                 f"{_d(e[(k, 'base', 'late')]['med'])} / {e[(k, 'base', 'late')]['ruin']:.1%} | "
                 f"{_d(h['med'])} / {h['ruin']:.1%} |")
    for t in ENS_TASKS:
        L += ["", f"## 2. Capital plans, {t} costs (ens median W / p10 / share W <= $1,000 / es5 / deposits)", "",
              "| book | A 1y | B 1y | C 1y | A 3y | B 3y | C 3y |", "|---|---|---|---|---|---|---|"]
        for k in order:
            cells = []
            for hz in HORIZONS:
                for p in PLANS:
                    z = pe[(k, t, f"{p}_{hz}")]
                    dep = f" / {z['p_dep']:.1%}" if p == "B" else ""
                    cells.append(f"{_d(z['med'])} / {_d(z['p10'])} / {z['p_1000']:.1%} / {_d(z['es5'])}{dep}")
            L.append(f"| {k} | " + " | ".join(cells) + " |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V48B_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    (args.out / "v48b_summary.json").write_text(json.dumps(
        {"choice": ch, "plan": plan, "checks": checks, "ensemble": {"|".join(k): v for k, v in e.items()},
         "plans": {"|".join(k): v for k, v in pe.items()}}, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--book", type=int, required=True)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--procs", type=int, default=4)
        p.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--data", type=Path, default=Path("outputs/v43"))
        p.add_argument("--out", type=Path, default=Path("outputs/v48bw"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v48b"
    raise SystemExit(main())
