"""v49: the RU size dial with TradeZero's real borrow costs and broker rules (V49_PREREGISTRATION.md).

  run    one book under TZA and the TZC sets with v48's ensemble
  final  V49_REPORT.md and v49_summary.json
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

V, R43, R40, R35, R33, R29, A = W.V, W.R43, W.R40, W.R35, W.R33, W.R29, W.A
LEVELS, E2K, ENS_TASKS, SEEDS = W.LEVELS, W.E2K, W.ENS_TASKS, W.SEEDS
BOOKS = [(0.20, 0.40, ru, 5) for ru in (0.40, 0.30, 0.25, 0.20, 0.15)]
TZA = W.TZA
SETS = {"TZA": None,
        "TZC": {"borrow": 1.0, "margin": 0.09},
        "TZC-M0": {"borrow": 1.0, "margin": 0.0},
        "TZC-B2": {"borrow": 2.0, "margin": 0.09}}
MAIN = "TZC"
UNAVAIL = {1: 0.10, 2: 0.50}  # tier -> chance a locate fails (HTB, HOT)
VOL_SHARE = 0.10
C955, K1545 = 955, 945  # steps: 15:55, 15:45
MAX_RUIN = W.MAX_RUIN
CHECK = (14_411.0, 0.010, 200.0, 0.003)


def unavailable(it: dict) -> bool:
    p = UNAVAIL.get(int(it.get("tier", 0)), 0.0)
    return p > 0 and V._u(it["sym"], int(it["t"]), "49loc") < p


def fee_rate(price: float, so: float) -> float:
    """The model's yearly borrow rate in percent (v19 r3/r4: the cell fee doubled, at least 100%)."""
    _, fee = R29.v19.v15.lookup(R29.R16._W["table"], np.array([max(price, 0.01)]), np.array([so], float))
    return float(max(2 * fee[0], 100.0))


def extra_cost(fee: float, nights: int, cal: int, borrow: float, margin: float) -> float:
    """What TZC adds a unit of value: borrow by calendar day at ``borrow`` times the rate and margin interest, less
    the per-session borrow the model already charged."""
    return (fee * borrow / 100 + margin) / 360 * cal - fee / 100 / 360 * nights


def vol_scale(want: float, vol: float) -> float:
    return 1.0 if want <= 0 else float(min(1.0, max(VOL_SHARE * vol, 0.0) / want))


def variant(items: list[dict], recs: list[dict], s: dict | None) -> tuple[list[dict], list[dict]]:
    """The TZA trades turned into a TZC set: failed locates out, close entries capped by volume, the extra cost."""
    if s is None:
        return items, recs
    dates = R43._G["D"]["dates"]
    out, rs = [], []
    for it in items:
        rec = recs[it["_rec"]]
        if unavailable(it):
            R43._count("v49_no_locate")
            continue
        w = float(it["w"])
        if rec["kind"] == "close":
            B = R43.timeline(int(rec["t"]), int(rec["j"]))
            vol = float(np.nansum(B["v"][C955:R43.LAST + 1])) if B is not None else 0.0
            k = vol_scale(float(rec["n"]), vol)
            if k < 1.0:
                R43._count("v49_capped")
            w *= k
            if w <= 0:
                continue
        cost = 0.0
        if int(it.get("side", -1)) < 0:
            cal = int((dates[rec["u"][-1]] - dates[rec["u"][0]]).days)
            cost = extra_cost(fee_rate(float(it["price"]), float(it.get("so", np.nan))), int(it.get("nights", 0)),
                              cal, s["borrow"], s["margin"])
        rs.append({**rec, "cost": rec["cost"] + cost})
        r = np.array(it["r"], float)
        r[0] -= cost
        out.append({**it, "w": w, "r": r, "_rec": len(rs) - 1})
    return out, rs


def liquidate(taken: list[dict], recs: list[dict], T: int, liq: str, part: float | None, two: bool) -> np.ndarray:
    """v43's liquidate with, when ``two``, the 2:1 rule at 15:45: positions covered in proportion at market down to
    twice the equity, and kept reduced afterwards."""
    rows: dict[int, list[tuple[int, int]]] = {}
    for p, it in enumerate(taken):
        for i, u in enumerate(recs[it["_rec"]]["u"]):
            rows.setdefault(u, []).append((p, i))
    entry_close: dict[int, list[int]] = {}
    for p, it in enumerate(taken):
        rec = recs[it["_rec"]]
        if rec["kind"] == "close":
            entry_close.setdefault(rec["t"], []).append(p)
    alive = np.ones(len(taken), bool)
    scale = np.ones(len(taken))
    out = np.zeros(T)
    D = R43._G["D"]

    def cover(rec: dict, i: int, u: int, k: int, frac: float) -> tuple[float, float]:
        Qk = float(rec["Q"][i][k])
        if Qk <= 1e-12:
            return 0.0, 0.0
        B = R43.timeline(u, rec["j"]) or R43.synthetic(u, rec["j"])
        Pk = float(rec["M"][i][k] / Qk * rec["e"])
        f = R43.market(B, k, R43.LAST, None, liq, rec["n"] * Qk * frac, part, (R43.LAST, float(D["C"][u, rec["j"]])))
        px = sum(a * b for _, a, b in f)
        return Qk, Qk * (Pk - px) / rec["e"]

    for u in sorted(rows):
        live = [(p, i) for p, i in rows[u] if alive[p]]
        if not live:
            continue
        E, M = np.ones(960), np.zeros(960)
        parts = []
        for p, i in live:
            rec, w = recs[taken[p]["_rec"]], float(taken[p]["w"]) * scale[p]
            G = rec["G"][i].copy()
            if i == 0:
                G[max(rec["es"], 0):] -= rec["cost"]
            E += w * G
            M += w * rec["M"][i]
            parts.append((p, i, rec, w, G))
        hit = (M > 0) & (E <= R43.THETA * M)
        k = int(np.flatnonzero(hit)[0]) if hit.any() else 10_000
        if two and k > K1545 and M[K1545] > 2 * E[K1545] > 0:
            frac = 1 - 2 * E[K1545] / M[K1545]
            R43._count("v49_forced_2to1")
            tot = 0.0
            for p, i, rec, w, G in parts:
                Qk, slip = cover(rec, i, u, K1545, frac)
                tot += w * ((1 - frac) * G[R43.LAST] + frac * (G[K1545] + slip)) if Qk > 0 else w * G[R43.LAST]
                scale[p] *= 1 - frac
            out[u] = tot
            continue
        if k == 10_000:
            out[u] = float(E[R43.LAST] - 1)
            continue
        R43._count("liquidations")
        tot = 0.0
        for p, i, rec, w, G in parts:
            Qk, slip = cover(rec, i, u, k, 1.0)
            tot += w * (G[k] + slip) if Qk > 0 else w * G[k]
        out[u] = tot
        for p, _ in rows[u]:
            alive[p] = False
        for p in entry_close.get(u, []):
            alive[p] = False
    return out


def account(items: list[dict], recs: list[dict], max_new: int, two: bool) -> np.ndarray:
    D = R43._G["D"]
    _, taken = A.joint(items, D["dates"], R33.GROSS, R33.MAX_OPEN, max_new, "move", "none", "tzi", 0.0, 0.0,
                       None, None, None)
    return liquidate(taken, recs, len(D["dates"]), V.LIQ, V.PART, two)


def choose(books: dict) -> str | None:
    ok = [k for k, z in books.items()
          if all(W.ensemble(z["res"][MAIN][t], "all")["ruin"] <= MAX_RUIN for t in ENS_TASKS)]
    return max(ok, key=lambda k: W.ensemble(books[k]["res"][MAIN]["base"], "all")["med"]) if ok else None


# ---------------------------------------------------------------- run

def _job(job: tuple) -> tuple:
    level, task = job
    R43.LEVEL = level
    R43._G["count"] = {}
    items, recs = V.items_for(*V.pairs(level, task, TZA), TZA)
    out = {}
    for name, s in SETS.items():
        its, rs = variant(items, recs, s)
        out[name] = {sd: account([it for it in its if not W.dropped(it, sd)], rs, W._G["mn"], s is not None)
                     [R43._G["pos"]] for sd in SEEDS}
    return job, out, dict(R43._G["count"]) if level == W.LEVEL and task == "base" else None


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
        got = pool.map(_job, jobs, chunksize=1)
        R = {job: out for job, out, _ in got}
        count = next((c for _, _, c in got if c is not None), {})
        B = dict(pool.map(W._boot_job, [((n, t, s), [R[(lv, t)][n][s] for lv in lv2], ("all", "early", "late"))
                                        for n in SETS for t in ENS_TASKS for s in SEEDS], chunksize=1))
    out = {"book": W.book_id(ds, ns, ru, int(mn)), "sizes": [ds, ns, ru, mn],
           "res": {n: {t: {str(s): B[(n, t, s)] for s in SEEDS} for t in ENS_TASKS} for n in SETS},
           "count": count, "sec": round(time.time() - t0)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"b{args.book}.json").write_text(json.dumps(out, default=float), encoding="utf-8")
    for n in SETS:
        e = W.ensemble(out["res"][n]["base"], "all")
        print(out["book"], n, f"ens median {e['med']:,.0f} ruin {e['ruin']:.1%} p90 {e['ruin90']:.1%}", flush=True)
    print(json.dumps({"count": count, "sec": out["sec"]}), flush=True)
    return 0


# ---------------------------------------------------------------- final

def _d(x: float) -> str:
    return f"${x:,.0f}"


def cmd_final(args) -> int:
    books = {}
    for p in sorted(args.runs.rglob("b[0-9]*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        books[z["book"]] = z
    e = {(k, n, t, s): W.ensemble(books[k]["res"][n][t], s) for k in books for n in SETS for t in ENS_TASKS
         for s in ("all", "early", "late")}
    ref = W.book_id(0.20, 0.40, 0.30, 5)
    z = e.get((ref, "TZA", "base", "all"))
    check = bool(z) and abs(z["med"] - CHECK[0]) <= CHECK[2] and abs(z["ruin"] - CHECK[1]) <= CHECK[3]
    ch = choose(books)
    pick = ch or (min(books, key=lambda k: e[(k, MAIN, "base", "all")]["ruin"]) if books else None)
    a = e[(pick, MAIN, "base", "all")] if pick else None
    L = ["# v49: the RU size dial with TradeZero's real borrow costs and broker rules", "",
         f"{len(SEEDS)} seeds, {R29.PATHS} one-year paths from $5,000, ruin at or under $1,250. TZC = TZA plus borrow "
         "by calendar day, 9% margin interest, failed locates (HOT 50%, HTB 10%), the 2:1 rule at 15:45 enforced, close "
         "entries capped at 10% of 15:55-15:59 volume. M0 = no margin interest; B2 = borrow doubled.", "",
         f"Check (RU 0.30 under TZA vs v48b {_d(CHECK[0])}, {CHECK[1]:.1%}): "
         f"**{'reproduced' if check else 'NOT reproduced'}**.", ""]
    if a:
        L += [f"## Answer: **{ch if ch else 'none passes'}**" + ("" if ch else f" (lowest TZC ruin: {pick})"), "",
              f"TZC, base costs, all paths, ensemble mean of {len(SEEDS)} seeds: one-year median from $5,000 "
              f"**{_d(a['med'])}**, ruin **{a['ruin']:.1%}** (p90 over seeds {a['ruin90']:.1%}).", ""]
    L += ["| book | set | ens median | ens ruin | p90 ruin | seed 0 | 2018-22 | 2023+ | HOT 5% |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(books, key=lambda k: -books[k]["sizes"][2]):
        for n in SETS:
            x, h = e[(k, n, "base", "all")], e[(k, n, "hot5", "all")]
            L.append(f"| {k} | {n} | {_d(x['med'])} | {x['ruin']:.1%} | {x['ruin90']:.1%} | {_d(x['med0'])} / "
                     f"{x['ruin0']:.1%} | {_d(e[(k, n, 'base', 'early')]['med'])} / "
                     f"{e[(k, n, 'base', 'early')]['ruin']:.1%} | {_d(e[(k, n, 'base', 'late')]['med'])} / "
                     f"{e[(k, n, 'base', 'late')]['ruin']:.1%} | {_d(h['med'])} / {h['ruin']:.1%} |")
    L += ["", "Counts at $10,000, base costs, all sets together (forced 2:1 covers, failed locates, capped entries):",
          "", *[f"- {k}: {books[k]['count']}" for k in sorted(books)]]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V49_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    (args.out / "v49_summary.json").write_text(json.dumps(
        {"choice": ch, "pick": pick, "answer": a, "check": check,
         "ensemble": {"|".join(k): v for k, v in e.items()}}, default=float), encoding="utf-8")
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
        p.add_argument("--out", type=Path, default=Path("outputs/v49w"))
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v49"
    raise SystemExit(main())
