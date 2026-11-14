"""v60m (V60M_PREREGISTRATION.md): does the short margin rule cap what a bigger size can earn? Diagnostic only.

  run    one (book, margin rule) cell in v58's locate worlds, with the account's average exposure logged
  final  V60M_REPORT.md and v60m_summary.json
Margin rules: tzi (the engine's), tzus (TradeZero's 4-8 PM column, $5 a share under $5, held all night),
tz6 (TradeZero's published overnight maintenance, 1/6 at $2.50 and up), none (no margin check; 2:1 gross kept).
Aggregates only.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v58 as Q  # noqa: E402

P, W, V, R43, S = Q.P, Q.W, Q.V, Q.R43, Q.S
Q49 = P.Q
A = Q49.A
BOOKS = [(0.10, 0.40, 0.10), (0.20, 0.60, 0.25), (0.20, 1.00, 0.25), (0.30, 1.00, 0.25), (0.45, 1.50, 0.50)]
RULES = ("tzi", "tzus", "tz6", "none")
GRID = list(itertools.product(range(len(BOOKS)), RULES))
DIAG_LEVEL, DIAG_WORLDS = 5000.0, ("W0", "F0C1")
_G: dict = {"rule": "tzi", "dir": None, "ctx": None}
_MARGIN = A.joint.__globals__["margin"]


def name(b: int, rule: str) -> str:
    ds, ns, ru = BOOKS[b]
    return f"DS{ds:.2f}-NS{ns:.2f}-RU{ru:.2f}|{rule}"


def margin(price, side, rule: str, when: str) -> np.ndarray:
    if rule != "tz6":
        return _MARGIN(price, side, rule, when)
    p = np.maximum(np.asarray(price, float), 0.01)
    m = np.where(p < 5, 5.0 / p, 0.5) if when == "ah" else np.where(p < 2.5, 2.5 / p, 1 / 6)
    return np.where(np.asarray(side) < 0, m, 1 / 6 if when == "intra" else 0.5)


def exposure(taken: list[dict], T: int) -> dict:
    gross, req = np.zeros(T), np.zeros(T)
    m = _MARGIN(np.array([it["price"] for it in taken]), np.array([it["side"] for it in taken]), "tzi", "night") \
        if taken else []
    for k, it in enumerate(taken):
        n = min(len(it["r"]), T - it["i0"])
        gross[it["i0"]:it["i0"] + n] += it["w"]
        req[it["i0"]:it["i0"] + n] += it["w"] * m[k]
    pos = R43._G["pos"]
    g, r = gross[pos], req[pos]
    return {"gross_mean": float(g.mean()), "gross_p90": float(np.quantile(g, 0.9)),
            "tzi_margin_mean": float(r.mean()), "days_tzi_margin_over_90pct": float((r > 0.9).mean())}


def account(items: list[dict], recs: list[dict], max_new: int, two: bool) -> np.ndarray:
    D = R43._G["D"]
    _, taken = A.joint(items, D["dates"], Q49.R33.GROSS, Q49.R33.MAX_OPEN, max_new, "move", "none", _G["rule"],
                       0.0, 0.0, None, None, None)
    if _G["ctx"] is not None:
        mem = sorted({it["member"] for it in items})
        z = {"cands": {m: sum(it["member"] == m for it in items) for m in mem},
             "taken": {m: sum(it["member"] == m for it in taken) for m in mem}, **exposure(taken, len(D["dates"]))}
        (_G["dir"] / f"diag_{_G['ctx']}.json").write_text(json.dumps(z), encoding="utf-8")
    return Q49.liquidate(taken, recs, len(D["dates"]), V.LIQ, V.PART, two)


def _job(job: tuple) -> tuple:
    level, task = job
    R43.LEVEL = level
    R43._G["count"] = {}
    items, recs = V.items_for(*V.pairs(level, task, P.Q.TZA), P.Q.TZA)
    out = {}
    for wname, s in Q.SETS.items():
        _, pps, etb = Q.WORLDS[wname]
        its, rs = P.variant(*Q.relocate(items, recs, pps, etb), s)
        res = {}
        for sd in P.SEEDS:
            diag = level == DIAG_LEVEL and task == "base" and sd == 0 and wname in DIAG_WORLDS
            _G["ctx"] = wname if diag else None
            res[sd] = account([it for it in its if not W.dropped(it, sd)], rs, W._G["mn"], True)[R43._G["pos"]]
        out[wname] = res
    _G["ctx"] = None
    return job, out, None


def cmd_run(args) -> int:
    b, rule = GRID[args.cell]
    A.joint.__globals__["margin"] = margin
    _G.update(rule=rule, dir=args.out / f"tmp_{args.cell}")
    _G["dir"].mkdir(parents=True, exist_ok=True)
    assert DIAG_LEVEL in [float(x) for x in P.LEVELS]
    Q._job = _job
    Q.BOOKS = [(*BOOKS[b], 5)]
    out = args.out
    args.out, args.book = _G["dir"], 0
    Q.cmd_run(args)
    z = json.loads((args.out / "b0.json").read_text(encoding="utf-8"))
    z.update(book=name(b, rule), cell=args.cell,
             diag={w: json.loads((_G["dir"] / f"diag_{w}.json").read_text(encoding="utf-8")) for w in DIAG_WORLDS})
    (out / f"c{args.cell}.json").write_text(json.dumps(z, default=float), encoding="utf-8")
    print(json.dumps({"book": z["book"], **z["diag"]["F0C1"]}), flush=True)
    return 0


def cmd_final(args) -> int:
    Z = {}
    for p in sorted(args.runs.rglob("c*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        Z[z["book"]] = z
    books = [name(b, r) for b, r in GRID if name(b, r) in Z]
    e = {(k, w, t, s): W.ensemble(Z[k]["res"][w][t], s) for k in books for w in Q.SETS for t in Q.TASKS
         for s in ("all", "early", "late")}
    _d = P._d
    L = ["# v60m report: does the short margin rule cap a bigger size?", "",
         "Pre-registered in V60M_PREREGISTRATION.md. Diagnostic only, chooses nothing. v58's engine (TZC, IEX, "
         "31 seeds, one-year paths from $5,000, ruin = touching $1,250), 2:1 gross and the 15:45 2:1 rule kept in "
         "every rule. Exposure and trade counts: $5,000 level, base costs, seed 0, F0C1.", "",
         "| book | margin rule | W0 all | F0C1 all | F0C1 2018-2022 | F0C1 2023-2026 | HOT5 ruin F0C1 | "
         "mean gross | mean tzi margin | days margin >90% | taken / candidates |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in books:
        d = Z[k]["diag"]["F0C1"]
        tk = ", ".join(f"{m.split(':')[-1]} {d['taken'][m]}/{d['cands'][m]}" for m in d["cands"])
        c = [f"{_d(e[(k, w, 'base', s)]['med'])} / {e[(k, w, 'base', s)]['ruin']:.1%}"
             for w, s in (("W0", "all"), ("F0C1", "all"), ("F0C1", "early"), ("F0C1", "late"))]
        L.append(f"| {k.split('|')[0]} | {k.split('|')[1]} | " + " | ".join(c)
                 + f" | {e[(k, 'F0C1', 'hot5', 'all')]['ruin']:.1%} | {d['gross_mean']:.2f} | "
                 f"{d['tzi_margin_mean']:.2f} | {d['days_tzi_margin_over_90pct']:.0%} | {tk} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V60M_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v60m_summary.json").write_text(json.dumps(
        {"diag": {k: Z[k]["diag"] for k in books}, "ensemble": {"|".join(k): v for k, v in e.items()}},
        default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cell", type=int, required=True, choices=range(len(GRID)))
    r.add_argument("--iex", type=Path, default=Path("outputs/v55/iex"))
    r.add_argument("--procs", type=int, default=os.cpu_count() or 4)
    r.add_argument("--choice", type=Path, default=Path("outputs/v33w/choice"))
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    r.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    r.add_argument("--data", type=Path, default=Path("outputs/v43"))
    r.add_argument("--out", type=Path, default=Path("outputs/v60mw/runs"))
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/v60mw/report"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v60m"
    raise SystemExit(main())
