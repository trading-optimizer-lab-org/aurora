"""v58 (V58_PREREGISTRATION.md): v57 on a finer grid of cheaper locate worlds, between v56's W0 and v57's F1C2.

  run    one book under TZC in every world, close entries decided on IEX (v55's iex source)
  final  V58_REPORT.md and v58_summary.json
Aggregates only. The grid is generic: which world matches TradeZero's real quotes is read privately.
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
import run_v56 as S  # noqa: E402

X, P, W, V, R43 = S.X, S.P, S.W, S.V, S.R43
BOOKS, TASKS, TARGET, MAX_RUIN = S.BOOKS, S.TASKS, S.TARGET, S.MAX_RUIN
TZA_PPS = tuple(P.Q.TZA["loc"])  # v47's locate price a share (HTB, HOT) behind every v56 cost
FAILS = {"F0": (0.01, 0.05), "F1": (0.02, 0.10)}  # HTB, HOT
PRICES = {"C0": (0.01, 0.03), "C1": (0.02, 0.06)}  # dollars a share, HTB, HOT
WORLDS = {"W0": ((0.0, 0.0), TZA_PPS, False)}
WORLDS.update({f"{f}{c}{'E' if e else ''}": (FAILS[f], PRICES[c], e)
               for f, c, e in itertools.product(FAILS, PRICES, (False,))})
SETS = {w: {**P.TZC, "loc": {1: fl[0], 2: fl[1]}} for w, (fl, _, _) in WORLDS.items()}
CHECK_BOOK, CHECK = "DS0.20-NS0.60-RU0.25-N5", (13_041.0, 0.010)  # v56 W0, the chosen book


def relocate(items: list[dict], recs: list[dict], pps: tuple, etb: bool) -> tuple[list[dict], list[dict]]:
    """Reprice every short's locate at pps dollars a share (v47's scaling kept), and with etb treat ETB shorts as
    HTB: they pay the HTB price and can fail as HTB."""
    if pps == TZA_PPS and not etb:
        return items, recs
    rs = [dict(r) for r in recs]
    out = []
    for it in items:
        tier, short = int(it.get("tier", 0)), int(it.get("side", -1)) < 0
        if short and tier >= 1:
            new = float(it["loc"]) * pps[tier - 1] / TZA_PPS[tier - 1]
        elif short and etb:
            new, tier = pps[0] / max(float(it["price"]), 0.01), 1
        else:
            out.append(it)
            continue
        rs[it["_rec"]]["cost"] += new - float(it["loc"])
        out.append({**it, "loc": new, "tier": tier})
    return out, rs


def _job(job: tuple) -> tuple:
    level, task = job
    R43.LEVEL = level
    R43._G["count"] = {}
    items, recs = V.items_for(*V.pairs(level, task, P.Q.TZA), P.Q.TZA)
    out = {}
    for name, s in SETS.items():
        _, pps, etb = WORLDS[name]
        its, rs = P.variant(*relocate(items, recs, pps, etb), s)
        out[name] = {sd: P.Q.account([it for it in its if not W.dropped(it, sd)], rs, W._G["mn"], True)
                     [R43._G["pos"]] for sd in P.SEEDS}
    return job, out, None


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
        R = {job: res for job, res, _ in pool.map(_job, jobs, chunksize=1)}
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


def cmd_final(args) -> int:
    Z = {}
    for p in sorted(args.runs.rglob("b[0-9]*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        Z[z["book"]] = z
    books = sorted(Z)
    e = {(b, w, t, s): W.ensemble(Z[b]["res"][w][t], s) for b in books for w in SETS for t in TASKS
         for s in ("all", "early", "late")}
    picks = {w: S.pick(e, books, w) for w in SETS}
    _d = P._d

    def cell(b, w):
        a, h, late = e[(b, w, "base", "all")], e[(b, w, "hot5", "all")], e[(b, w, "base", "late")]
        return (f"{_d(a['med'])} ({a['med'] / 5000 - 1:+.0%}) ruin {a['ruin']:.1%}, HOT5 {h['ruin']:.1%}, "
                f"2023+ {_d(late['med'])} / {late['ruin']:.1%}")

    L = ["# v58 report: v56's books on a finer grid of cheaper locate worlds", "",
         f"Pre-registered in V58_PREREGISTRATION.md. {len(books)} books, close entries decided on IEX, TZC costs, "
         f"31 seeds, one-year paths from $5,000. Target {_d(TARGET)}, ruin at most {MAX_RUIN:.0%}.", ""]
    if CHECK_BOOK in Z:
        a = e[(CHECK_BOOK, "W0", "base", "all")]
        ok = abs(a["med"] - CHECK[0]) <= 1.0 and abs(a["ruin"] - CHECK[1]) <= 0.0005
        L += [f"Check: {CHECK_BOOK} in W0 {_d(a['med'])} ruin {a['ruin']:.1%} vs v56 {_d(CHECK[0])} "
              f"{CHECK[1]:.1%}: {'reproduced' if ok else 'NOT reproduced'}.", ""]
    L += ["| world | fail HTB / HOT | locate $/share HTB / HOT | ETB as HTB | chosen on 2018-2022 | its result 2018-2026 "
          "| MET | hindsight best at ruin 5% | its result |", "|---|---|---|---|---|---|---|---|---|"]
    for w, (fl, pps, etb) in WORLDS.items():
        k = picks[w]
        c, h = k["choice"], k["hindsight"]
        L.append(f"| {w} | {fl[0]:.0%} / {fl[1]:.0%} | {pps[0]:.2f} / {pps[1]:.2f} | {'yes' if etb else 'no'} | "
                 f"{c or 'none'} | {cell(c, w) if c else '-'} | {'**MET**' if k['met'] else 'NOT MET'} | "
                 f"{h or 'none'} | {cell(h, w) if h else '-'} |")
    L += ["", "## Every book, base costs, all paths: median / ruin", "",
          "| book | " + " | ".join(SETS) + " |", "|---|" + "---|" * len(SETS)]
    for b in sorted(books, key=lambda b: -e[(b, "W0", "base", "all")]["med"]):
        L.append(f"| {b} | " + " | ".join(f"{_d(e[(b, w, 'base', 'all')]['med'])} / "
                                          f"{e[(b, w, 'base', 'all')]['ruin']:.1%}" for w in SETS) + " |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V58_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v58_summary.json").write_text(json.dumps(
        {"picks": picks, "ensemble": {"|".join(k): v for k, v in e.items()}}, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
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
    r.add_argument("--out", type=Path, default=Path("outputs/v58w/runs"))
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/v58w/report"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v58"
    raise SystemExit(main())
