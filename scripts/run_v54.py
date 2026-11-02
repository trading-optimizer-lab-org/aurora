"""v54 (V54_PREREGISTRATION.md): the FREE daily book chosen year by year from the years before only.

  run    one size book (members DS1, NS, RU, any of them left out) under TZC and three stress sets: daily account
         returns at every equity level and seed
  final  the walk-forward choice, its grading, V54_REPORT.md and v54_summary.json
Artifacts hold daily account returns and aggregates only.
"""
from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v50 as F  # noqa: E402

Q, W, V, R43, R40, R35, R29 = F.Q, F.W, F.V, F.R43, F.R40, F.R35, F.R29
R32 = R43.R32
LEVELS, E2K, SEEDS = F.LEVELS, F.E2K, F.SEEDS
TASKS = ("base", "hot5")
BOOKS = [b for b in itertools.product((0.0, 0.20, 0.30, 0.40), (0.0, 0.40, 0.60, 0.80), (0.0, 0.15, 0.20, 0.25), (5, 8))
         if any(b[:3])]
MAIN = "TZC"
STRESS = {"B2": "TZC-B2", "L0": "TZC-L0", "L25": "TZC-L25"}
STRESS_SEEDS = tuple(range(10))
TEST_YEARS = tuple(range(2019, 2027))
SEL_YEARS, LOCK_YEARS = tuple(range(2019, 2025)), (2025, 2026)
WINDOWS = {"exp": None, "roll3": 3}
HIST_SEEDS = (0, 1, 2)
MAX_RUIN, TARGET = 0.025, 10_000.0
REFS = {"v49": (0.20, 0.40, 0.20, 5), "v50": (0.20, 0.60, 0.20, 5)}
CHECK = (9_065.0, 0.001)  # v50's answer DS0.20-NS0.60-RU0.20-N5 under TZC, all paths: median and ruin


# ---------------------------------------------------------------- run

def _job(job: tuple) -> tuple:
    level, task = job
    R43.LEVEL = level
    R43._G["count"] = {}
    sz = W._G["sizes"]
    items, recs = V.items_for(*V.pairs(level, task, Q.TZA), Q.TZA)
    items = [it for it in items if sz[it["member"]] > 0]
    out = {}
    for name in [MAIN] + list(STRESS.values()):
        if name != MAIN and task != "base":
            continue
        its, rs = F.variant(items, recs, F.SETS[name])
        seeds = SEEDS if name == MAIN else STRESS_SEEDS
        out[name] = np.stack([Q.account([it for it in its if not W.dropped(it, sd)], rs, W._G["mn"], True)
                              [R43._G["pos"]] for sd in seeds]).astype(np.float32)
    return job, out


def cmd_run(args) -> int:
    ds, ns, ru, mn = BOOKS[args.book]
    W._G["mn"] = int(mn)
    sizes = W.sizes_of(ds, ns, ru)
    W._G["sizes"] = sizes
    R40.SIZES = {m: (s if s > 0 else 0.20) for m, s in sizes.items()}  # a left-out member's trades are dropped
    t0 = time.time()
    lv2 = [float(x) for x in np.r_[E2K, LEVELS]]
    R43.setup(args, tuple(lv2))
    V._G.update(rows=R35._rows(args), days=V.candidates())
    jobs = [(lv, t) for t in TASKS for lv in lv2]
    with mp.get_context("fork").Pool(args.procs) as pool:
        for (lv, t), (oi, om, _) in pool.map(V._o1_job, jobs, chunksize=1):
            V._G["o1"][(lv, t)] = (oi, om)
    with mp.get_context("fork").Pool(args.procs) as pool:
        R = dict(pool.map(_job, jobs, chunksize=1))
    arr = {}
    for t in TASKS:
        for name in R[(lv2[0], t)]:
            arr[f"{name}|{t}"] = np.stack([R[(lv, t)][name] for lv in lv2[1:]], axis=1)  # seeds x levels x days
    args.out.mkdir(parents=True, exist_ok=True)
    cal = R43._G["cal"]
    np.savez_compressed(args.out / f"b{args.book}.npz", years=np.asarray(cal.year), **arr)
    print(json.dumps({"book": W.book_id(ds, ns, ru, int(mn)), "sec": round(time.time() - t0)}), flush=True)
    return 0


# ---------------------------------------------------------------- final

def _map(fn, jobs: list, procs: int) -> list:
    if procs <= 1:
        return [fn(j) for j in jobs]
    with mp.get_context("fork").Pool(procs) as pool:
        return pool.map(fn, jobs, chunksize=1)


def boot(Rb: np.ndarray, ix: np.ndarray) -> dict:
    """One seed's (levels x days) returns on one-year paths ``ix``: v43's bootstrap (FREE fixed cost)."""
    return R43.boot(Rb, {"s": ix})["s"]


def draws(years: np.ndarray, keep: tuple) -> np.ndarray:
    sub = np.flatnonzero(np.isin(years, keep))
    return sub[R29.draws(len(sub))]


def ens(rows: list[dict]) -> dict:
    r = np.array([x["p_ruin"] for x in rows])
    return {"med": float(np.mean([x["med"] for x in rows])), "ruin": float(r.mean()),
            "ruin90": float(np.quantile(r, 0.9)), "p10": float(np.mean([x["p10"] for x in rows]))}


def train_years(window: str, y: int) -> tuple:
    n = WINDOWS[window]
    first = TEST_YEARS[0] - 1
    return tuple(range(first if n is None else max(first, y - n), y))


def _hist(job: tuple) -> tuple:
    b, yrs = job
    Z, years = _F["Z"][b], _F["years"]
    ix = draws(years, yrs)
    return job, {t: ens([boot(Z[f"{MAIN}|{t}"][s], ix) for s in HIST_SEEDS]) for t in TASKS}


def _grade(job: tuple) -> tuple:
    key, plan = job  # plan: {year: book or None}
    Z, years = _F["Z"], _F["years"]
    idx = {"sel": draws(years, SEL_YEARS), "lock": draws(years, LOCK_YEARS), "all": draws(years, TEST_YEARS)}
    out = {}
    sets = [(MAIN, t, SEEDS) for t in TASKS] + [(n, "base", STRESS_SEEDS) for n in STRESS.values()]
    for name, t, seeds in sets:
        per = {k: [] for k in idx}
        for s in range(len(seeds)):
            R = np.zeros((len(LEVELS), len(years)), np.float64)
            for y, b in plan.items():
                if b is not None:
                    m = years == y
                    R[:, m] = Z[b][f"{name}|{t}"][s][:, m]
            for k, ix in idx.items():
                per[k].append(boot(R, ix))
        out[f"{name}|{t}"] = {k: ens(v) for k, v in per.items()}
    R = np.zeros((len(LEVELS), len(years)))
    for y, b in plan.items():
        if b is not None:
            R[:, years == y] = Z[b][f"{MAIN}|base"][0][:, years == y]
    seq = np.flatnonzero(np.isin(years, TEST_YEARS))[None, :]
    eq, low = R32.paths(R, R, seq, R35.FIXED, None, R29.E0)
    out["history"] = {"end": float(eq[0]), "low": float(low[0]),
                      "yearly": {str(y): float(R[1][years == y].sum()) for y in TEST_YEARS}}
    return key, out


_F: dict = {}


def cmd_final(args) -> int:
    Z, years = {}, None
    for p in sorted(args.runs.rglob("b*.npz")):
        z = np.load(p)
        Z[int(p.stem[1:])] = {k: z[k] for k in z.files if k != "years"}
        years = z["years"]
    _F.update(Z=Z, years=years)
    books = sorted(Z)
    refs = {k: BOOKS.index(v) for k, v in REFS.items()}
    wins = sorted({train_years(w, y) for w in WINDOWS for y in TEST_YEARS})
    H = dict(_map(_hist, [(b, yrs) for b in books for yrs in wins], args.procs))
    chosen = {}
    for w in WINDOWS:
        plan = {}
        for y in TEST_YEARS:
            yrs = train_years(w, y)
            ok = [b for b in books if all(H[(b, yrs)][t]["ruin"] <= MAX_RUIN for t in TASKS)]
            plan[y] = max(ok, key=lambda b: H[(b, yrs)]["base"]["med"]) if ok else None
        chosen[w] = plan
    plans = {**{f"wf-{w}": p for w, p in chosen.items()},
             **{f"fixed-{k}": {y: b for y in TEST_YEARS} for k, b in refs.items()}}
    G = dict(_map(_grade, list(plans.items()), args.procs))
    check = ens([boot(Z[refs["v50"]][f"{MAIN}|base"][s], R29.draws(len(years))) for s in range(len(SEEDS))])
    elig = [k for k in chosen if all(G[f"wf-{k}"][f"{MAIN}|{t}"]["sel"]["ruin"] <= MAX_RUIN for t in TASKS)]
    pick = max(elig, key=lambda k: G[f"wf-{k}"][f"{MAIN}|base"]["sel"]["med"]) if elig else None
    verdict = {"survives": None, "met": None, "robust": None}
    if pick:
        g = G[f"wf-{pick}"]
        surv = all(g[f"{MAIN}|{t}"][s]["ruin"] <= MAX_RUIN for t in TASKS for s in ("lock", "all"))
        met = surv and all(g[f"{MAIN}|{t}"]["lock"]["med"] >= TARGET for t in TASKS)
        rob = surv and all(g[f"{n}|base"]["all"]["ruin"] <= MAX_RUIN for n in STRESS.values())
        verdict = {"survives": surv, "met": met, "robust": rob}
    _d = F._d

    def bk(b):
        return "cash" if b is None else W.book_id(*BOOKS[b][:3], int(BOOKS[b][3]))
    L = ["# v54 report: the FREE daily book chosen year by year", "",
         f"Pre-registered in V54_PREREGISTRATION.md. {len(books)} size books under TZC. Check: v50's answer on all "
         f"2018-2026 paths here {_d(check['med'])}, ruin {check['ruin']:.1%} (v50: {_d(CHECK[0])}, {CHECK[1]:.1%}).",
         ""]
    if pick is None:
        L += ["**No walk-forward procedure keeps selection ruin (2019-2024) at or under 2.5%: DOES NOT SURVIVE.**", ""]
    else:
        L += [f"**Chosen: wf-{pick}. Survives: {verdict['survives']}. Target $10k met: {verdict['met']}. "
              f"Robust to stress: {verdict['robust']}.**", ""]
    L += ["| plan | sel med | sel ruin | sel HOT5 ruin | lock med | lock ruin | lock HOT5 ruin | all med | all ruin | "
          "borrow x2 all | locates never fail all | locates fail half as often all | history end | history low |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, g in G.items():
        m, h = g[f"{MAIN}|base"], g[f"{MAIN}|hot5"]
        L.append(f"| {k}{' **chosen**' if k == f'wf-{pick}' else ''} | {_d(m['sel']['med'])} | {m['sel']['ruin']:.1%} | "
                 f"{h['sel']['ruin']:.1%} | {_d(m['lock']['med'])} | {m['lock']['ruin']:.1%} | {h['lock']['ruin']:.1%} | "
                 f"{_d(m['all']['med'])} | {m['all']['ruin']:.1%} | "
                 + " | ".join(f"{_d(g[f'{n}|base']['all']['med'])} / {g[f'{n}|base']['all']['ruin']:.1%}"
                              for n in STRESS.values())
                 + f" | {_d(g['history']['end'])} | {_d(g['history']['low'])} |")
    for k, plan in plans.items():
        if not k.startswith("wf-"):
            continue
        w = k[3:]
        L += ["", f"## {k}: the book of each test year", "",
              "| year | book | train med | train ruin | train HOT5 ruin | year sum at $5k |", "|---|---|---|---|---|---|"]
        for y in TEST_YEARS:
            b = plan[y]
            tr = "n/a | n/a | n/a"
            if b is not None:
                hh = H[(b, train_years(w, y))]
                tr = f"{_d(hh['base']['med'])} | {hh['base']['ruin']:.1%} | {hh['hot5']['ruin']:.1%}"
            L.append(f"| {y} | {bk(b)} | {tr} | {100 * G[k]['history']['yearly'][str(y)]:+.0f}% |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V54_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    summary = {"verdict": verdict, "pick": pick, "check": check,
               "plans": {k: {str(y): (bk(b)) for y, b in p.items()} for k, p in plans.items()}, "grades": G}
    (args.out / "v54_summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print("\n".join(L[:8]), flush=True)
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
        p.add_argument("--out", type=Path, default=Path("outputs/v54w"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v54"
    raise SystemExit(main())
