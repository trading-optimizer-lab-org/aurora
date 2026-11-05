"""v56 (V56_PREREGISTRATION.md): the locate fill rate 150% a year at 5% ruin needs, on v55's IEX decisions.

  run    one book under TZC in four locate worlds, close entries decided on IEX (v55's iex source)
  final  V56_REPORT.md and v56_summary.json
Aggregates only.
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
import run_v55 as X  # noqa: E402

P, W, V, R43 = X.P, X.W, X.V, X.R43
BOOKS = [(ds, ns, ru, 5) for ds, ns, ru in
         itertools.product((0.10, 0.20, 0.30), (0.40, 0.60, 0.80, 1.00), (0.10, 0.15, 0.20, 0.25))]
WORLDS = {"W0": (0.0, 0.0), "W10": (0.10, 0.02), "W25": (0.25, 0.05), "W50": (0.50, 0.10)}  # HOT, HTB fail
SETS = {w: {**P.TZC, "loc": {1: htb, 2: hot}} for w, (hot, htb) in WORLDS.items()}
TARGET, MAX_RUIN = 12_500.0, 0.05
TASKS = P.ENS_TASKS


def cmd_run(args) -> int:
    ds, ns, ru, mn = BOOKS[args.book]
    W._G["mn"] = int(mn)
    P.R40.SIZES = W.sizes_of(ds, ns, ru)
    P.SETS = SETS
    t0 = time.time()
    lv2 = [float(x) for x in np.r_[P.E2K, P.LEVELS]]
    R43.setup(args, tuple(lv2))
    X.load_iex(args.iex)
    X._G["maxage"] = None
    V.patch = X.patch_iex
    days = [k for k in V.candidates() if X.iex_decision(*k) is not None]
    V._G.update(rows=P.R35._rows(args), days=days)
    jobs = [(lv, t) for t in TASKS for lv in lv2]
    with mp.get_context("fork").Pool(args.procs) as pool:
        for (lv, t), (oi, om, _) in pool.map(V._o1_job, jobs, chunksize=1):
            V._G["o1"][(lv, t)] = (oi, om)
    with mp.get_context("fork").Pool(args.procs) as pool:
        R = {job: res for job, res, _ in pool.map(P._job, jobs, chunksize=1)}
        B = dict(pool.map(W._boot_job, [((n, t, s), [R[(lv, t)][n][s] for lv in lv2], ("all", "early", "late"))
                                        for n in SETS for t in TASKS for s in P.SEEDS], chunksize=1))
    out = {"book": W.book_id(ds, ns, ru, int(mn)), "sizes": [ds, ns, ru, mn],
           "res": {n: {t: {str(s): B[(n, t, s)] for s in P.SEEDS} for t in TASKS} for n in SETS},
           "sec": round(time.time() - t0)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"b{args.book}.json").write_text(json.dumps(out, default=float), encoding="utf-8")
    for n in SETS:
        e = W.ensemble(out["res"][n]["base"], "all")
        print(out["book"], n, f"ens median {e['med']:,.0f} ruin {e['ruin']:.1%}", flush=True)
    return 0


def pick(e: dict, books: list[str], w: str) -> dict:
    """The book chosen on 2018-2022, its all-sample test, and the hindsight best at all-sample ruin <= 5%."""
    ok = [b for b in books if all(e[(b, w, t, "early")]["ruin"] <= MAX_RUIN for t in TASKS)]
    ch = max(ok, key=lambda b: e[(b, w, "base", "early")]["med"]) if ok else None
    met = bool(ch) and (e[(ch, w, "base", "all")]["med"] >= TARGET
                        and all(e[(ch, w, t, "all")]["ruin"] <= MAX_RUIN for t in TASKS)
                        and e[(ch, w, "base", "late")]["ruin"] <= MAX_RUIN)
    hs = [b for b in books if all(e[(b, w, t, "all")]["ruin"] <= MAX_RUIN for t in TASKS)]
    best = max(hs, key=lambda b: e[(b, w, "base", "all")]["med"]) if hs else None
    return {"choice": ch, "met": met, "hindsight": best}


def cmd_final(args) -> int:
    Z = {}
    for p in sorted(args.runs.rglob("b[0-9]*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        Z[z["book"]] = z
    books = sorted(Z)
    e = {(b, w, t, s): W.ensemble(Z[b]["res"][w][t], s) for b in books for w in SETS for t in TASKS
         for s in ("all", "early", "late")}
    picks = {w: pick(e, books, w) for w in SETS}
    _d = P._d

    def cell(b, w):
        a, h, late = e[(b, w, "base", "all")], e[(b, w, "hot5", "all")], e[(b, w, "base", "late")]
        return (f"{_d(a['med'])} ({a['med'] / 5000 - 1:+.0%}) ruin {a['ruin']:.1%}, HOT5 {h['ruin']:.1%}, "
                f"2023+ {_d(late['med'])} / {late['ruin']:.1%}")

    L = ["# v56 report: the locate fill rate for 150% a year at 5% ruin", "",
         f"Pre-registered in V56_PREREGISTRATION.md. {len(books)} books, close entries decided on IEX, TZC costs, "
         f"31 seeds, one-year paths from $5,000. Target {_d(TARGET)}, ruin at most {MAX_RUIN:.0%}.", "",
         "| world (HOT / HTB fail) | chosen on 2018-2022 | its result 2018-2026 | MET | hindsight best at ruin 5% | "
         "its result |", "|---|---|---|---|---|---|"]
    for w, (hot, htb) in WORLDS.items():
        k = picks[w]
        c, h = k["choice"], k["hindsight"]
        L.append(f"| {w} ({hot:.0%} / {htb:.0%}) | {c or 'none'} | {cell(c, w) if c else '-'} | "
                 f"{'**MET**' if k['met'] else 'NOT MET'} | {h or 'none'} | {cell(h, w) if h else '-'} |")
    L += ["", "## Every book, base costs, all paths: median / ruin", "",
          "| book | " + " | ".join(SETS) + " |", "|---|" + "---|" * len(SETS)]
    for b in sorted(books, key=lambda b: -e[(b, "W0", "base", "all")]["med"]):
        L.append(f"| {b} | " + " | ".join(f"{_d(e[(b, w, 'base', 'all')]['med'])} / "
                                          f"{e[(b, w, 'base', 'all')]['ruin']:.1%}" for w in SETS) + " |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V56_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v56_summary.json").write_text(json.dumps(
        {"picks": picks, "ensemble": {"|".join(k): v for k, v in e.items()}}, default=float), encoding="utf-8")
    print("\n".join(L[:10]), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--book", type=int, required=True)
    r.add_argument("--iex", type=Path, default=Path("outputs/v55/iex"))
    r.add_argument("--procs", type=int, default=4)
    r.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    r.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    r.add_argument("--data", type=Path, default=Path("outputs/v43"))
    r.add_argument("--out", type=Path, default=Path("outputs/v56w/runs"))
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/v56w/report"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v56"
    raise SystemExit(main())
