"""v31: v30 with the broker's forced liquidation (V31_PREREGISTRATION.md). Each session the account's open positions
move from the previous close to the open, then all at once to their adverse extremes (a position leaving within the
session to its exit price); when the equity falls to THETA of the positions' market value the broker closes
everything and the closed positions' later sessions drop out. The rest is v30.

  grid    one FREE cell of v29's grid under the rule: every book at the five levels, A and B paths
  choose  the books compared
  sens    one shard of the battery
  final   V31_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R30 = _script("run_v30")
R29 = R30.R29
A, v19, R14 = R29.A, R29.v19, R29.R14
LEVELS, KEYS = R30.LEVELS, R30.KEYS
THETA = 0.15
MODE: dict = {"theta": THETA}
BOOKS = ("A1", "B_best", "B_max", "A_best")
TASKS = {"base": {}, "hot5": {"hot": 0.05}, "hot8": {"hot": 0.08}, "high": {"spread": 2.0, "fee": 3.0},
         "liq30": {"theta": 0.30}, "liq_off": {"theta": None}}
LOG: list[dict] = []  # one entry a series under the rule: liquidations, worst session with and without it

# ---------------------------------------------------------------- the first session's return before costs

_PATH19, _COSTS, _SPEC_ITEMS = v19.path19, v19._costs, A._spec_items
_SEEN: list[float] = []
_RAW0: list[float] = []


def _costs_seen(*a, **k):
    cost, avail = _COSTS(*a, **k)
    _SEEN.append(float(cost[0]))
    return cost, avail


def _path19_raw(D, s, table, spread, fee_mult=1.0, gross=False, w_max=0.05):
    """v19's trade path; records the first session's return before the costs path19 takes off it."""
    _SEEN.clear()
    p = _PATH19(D, s, table, spread, fee_mult, gross, w_max)
    if p is not None:
        cost = _SEEN[0] if _SEEN else 0.0
        t, j = s.t, s.j
        if not gross and s.side < 0 and s.kind == "open" and t > 0 and D["O"][t, j] <= 0.9 * D["C"][t - 1, j]:
            cost += v19.vs.SSR_EXTRA
        _RAW0.append(float(p[1][0]) + cost)
    return p


def _spec_items_raw(*a, **k) -> list[dict]:
    _RAW0.clear()
    out = _SPEC_ITEMS(*a, **k)
    assert len(out) == len(_RAW0)
    return [{**it, "raw0": r0} for it, r0 in zip(out, _RAW0)]


v19._costs, v19.path19, A._spec_items = _costs_seen, _path19_raw, _spec_items_raw

# ---------------------------------------------------------------- the rule


def position_days(taken: list[dict], D: dict, T: int) -> dict[str, np.ndarray]:
    """One row a position and session: the session, the position, and times its weight the gain from the previous
    close to the open (a), from the open to the worst moment (b), the market value at the open (m0) and its change
    to the worst moment (m1), all on the entry price, and the session's return as the account books it (cl)."""
    O, H, L, C = (np.asarray(D[k], float) for k in ("O", "H", "L", "C"))
    rows: dict[str, list] = {k: [] for k in ("day", "pid", "a", "b", "m0", "m1", "cl")}
    for pid, it in enumerate(taken):
        i0, side, w = int(it["i0"]), int(it["side"]), float(it["w"])
        n = min(len(it["r"]), T - i0)
        if n <= 0:
            continue
        rr = np.array(it["r"][:n], float)
        if side < 0:
            rr[0] -= it.get("loc", 0.0)
        u = i0 + np.arange(n)
        j, t = int(it["j"]), int(it["t"])
        if j < 0 or "raw0" not in it or i0 not in (t, t + 1):
            a, b, m0, m1 = rr, np.zeros(n), np.ones(n), np.zeros(n)
        else:
            entry = float(it["entry"]) if "entry" in it else (O[t, j] if i0 == t else C[t, j])  # v33: a limit fill
            c = C[u, j]
            prev = np.concatenate([[entry], c[:-1]])
            o = np.where(np.isfinite(O[u, j]), O[u, j], c)
            if i0 == t:
                o[0] = entry
            ext = H[u, j] if side < 0 else L[u, j]
            ext = np.where(np.isfinite(ext), ext, np.maximum(o, c) if side < 0 else np.minimum(o, c))
            raw = rr.copy()
            raw[0] = it["raw0"]
            assert rr[0] <= raw[0] + 1e-9
            if len(it["r"]) > 1:  # the entry session is not the exit: raw0 is its close-to-close move
                assert abs(raw[0] - side * (c[0] - entry) / entry) < 1e-9
            if abs(raw[-1] - side * (c[-1] - prev[-1]) / entry) > 1e-9:  # left within the session
                px = prev[-1] + side * raw[-1] * entry
                ext[-1] = px
                if side * (o[-1] - prev[-1]) < side * (px - prev[-1]):
                    o[-1] = px
            a = side * (o - prev) / entry
            a[0] += rr[0] - raw[0]
            b = side * (ext - o) / entry
            m0, m1 = o / entry, (ext - o) / entry
        for k, v in (("day", u), ("pid", np.full(n, pid)), ("a", w * a), ("b", w * b), ("m0", w * m0),
                     ("m1", w * m1), ("cl", w * rr)):
            rows[k].append(v)
    return {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in rows.items()}


def liquidate(P: dict[str, np.ndarray], T: int, theta: float) -> tuple[np.ndarray, list[int]]:
    """The account's sessions with the rule, and the sessions the broker closed everything."""
    day, pid = P["day"].astype(int), P["pid"].astype(int)
    alive = np.ones(len(day), bool)
    forced: dict[int, float] = {}
    start = 0
    while True:
        a, b, m0, m1 = (np.bincount(day[alive], P[k][alive], minlength=T) for k in ("a", "b", "m0", "m1"))
        held = np.bincount(day[alive], minlength=T) > 0
        e0, e1 = 1 + a, 1 + a + b
        at_open = e0 <= theta * m0
        hit = held & (at_open | (e1 <= theta * (m0 + m1)))
        hit[:start] = False
        if not hit.any():
            break
        s = int(np.flatnonzero(hit)[0])
        if at_open[s]:
            forced[s] = float(a[s])
        else:
            lam = (theta * m0[s] - e0[s]) / (b[s] - theta * m1[s])
            forced[s] = float(a[s] + lam * b[s])
        closed = np.isin(pid, pid[alive & (day == s)])
        alive &= ~(closed & (day > s))
        start = s + 1
    out = np.bincount(day[alive], P["cl"][alive], minlength=T)
    for s, r in forced.items():
        out[s] = r
    return out, sorted(forced)


_SERIES = R29.series


def series(items: list[dict], g: float, mo: int, mn: int, sleeve=None) -> tuple[np.ndarray, list]:
    s, taken = _SERIES(items, g, mo, mn, sleeve)
    theta = MODE["theta"]
    if theta is None:
        return s, taken
    assert sleeve is None
    T = len(s)
    P = position_days(taken, R14._G["D"], T)
    assert np.allclose(np.bincount(P["day"].astype(int), P["cl"], minlength=T), s, atol=1e-9)
    out, days = liquidate(P, T, theta)
    LOG.append({"n": len(days), "worst_on": float(out.min()) if T else 0.0,
                "worst_off": float(s.min()) if T else 0.0})
    return out, taken


R29.series = series

# ---------------------------------------------------------------- the stages


def cmd_sens(args) -> int:
    ch = json.loads((args.choice / "choice.json").read_text(encoding="utf-8"))
    jobs = [(name, task) for name in BOOKS for task in TASKS]
    mine = jobs[args.shard::args.shards]
    if not mine:
        return 0
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, _ = R29._cal()
    idx = R30._idx(len(cal))
    out = []
    for name, task in mine:
        kw = dict(TASKS[task])
        MODE["theta"] = kw.pop("theta", THETA)
        LOG.clear()
        R, _ = R29._levels(ch["books"][name], **kw)
        row = {"book": name, "task": task, "theta": MODE["theta"], **R30.evaluate(R, idx, R29.FIXED["FREE"])}
        if MODE["theta"] is not None:
            row["liq"] = {f"{lv:.0f}": LOG[i] for i, lv in enumerate(LEVELS) if i < len(LOG)}
        out.append(row)
        print(name, task, round(row["A_1y"]["med"]), round(row["B_1y"]["med"]), flush=True)
    MODE["theta"] = THETA
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"sens_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


def cmd_final(args) -> int:
    d, p = R30._d, R30._p
    ch = json.loads((args.choice / "choice.json").read_text(encoding="utf-8"))
    sens = [r for f in sorted(args.sens.rglob("sens_*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]
    get = {(r["book"], r["task"]): r for r in sens}
    L = ["# v31: v30 with the broker's forced liquidation", "",
         f"v29's FREE books, TradeZero International's costs, base locates HTB 1% / HOT 3% unless stated; the broker "
         f"closes everything when the equity falls to {THETA:.0%} of the positions' market value within a session "
         f"(all extremes at once); {R29.PATHS} bootstrap paths; W = equity + reserve not deposited, from $5,000; "
         f"accounts freeze under $500; losses may exceed the equity (debt). {ch['n']} books in the grid.", "",
         "## 1. The question", ""]
    a, b = get.get(("A1", "base")), get.get(("B_best", "base"))
    v = R30.verdict(a["A_1y"], b["B_1y"]) if a and b else None
    if v:
        L += [f"B_best (B) against A1 (A), one year: higher median {v['higher_median']}, smaller tail (mean of the worst "
              f"5%) {v['smaller_tail']}, no more 80% losses {v['no_more_80pct_losses']}. "
              f"**B better: {v['b_better']}. B avoids the tail: {v['b_avoids_tail']}.**", ""]
    L += ["## 2. Books", "", "| book | " + " | ".join(KEYS[1:]) + " |", "|" + "---|" * len(KEYS)]
    for name, c in ch["books"].items():
        L.append(f"| {name} | " + " | ".join(str(c[k]) for k in KEYS[1:]) + " |")
    L += ["", "## 3. Results", "", "| book | task | rule | horizon | median W | mean | p10 | p90 | W < $5k | W <= $1k | "
          "debt | worst 5% mean | worst | deposit |", "|" + "---|" * 14]
    for r in sens:
        for key in ("A_1y", "B_1y", "A_3y", "B_3y"):
            s = r[key]
            rule, hz = key.split("_")
            L.append(f"| {r['book']} | {r['task']} | {rule} | {hz} | {d(s['med'])} | {d(s['mean'])} | {d(s['p10'])} | "
                     f"{d(s['p90'])} | {p(s['p_loss'])} | {p(s['p_1000'])} | {p(s['p_debt'])} | {d(s['es5'])} | "
                     f"{d(s['worst'])} | {p(s['p_deposit']) if rule == 'B' else '-'} |")
    L += ["", "## 4. Forced liquidations in the stream", "", "| book | task | level | liquidations | worst session "
          "with the rule | without |", "|---|---|---|---|---|---|"]
    for r in sens:
        for lv, x in (r.get("liq") or {}).items():
            if lv in ("2500", "5000"):
                L.append(f"| {r['book']} | {r['task']} | ${int(lv):,} | {x['n']} | {p(x['worst_on'])} | "
                         f"{p(x['worst_off'])} |")
    L += ["", "## 5. Top 10 of the grid by one-year median W", "", "| rule | risk | cap | max open | new | gross | floor | "
          "median W | W <= $1k | worst 5% mean |", "|" + "---|" * 10]
    for rule in ("B", "A"):
        for r in ch[f"top_{rule}"]:
            s = r[f"{rule}_1y"]
            L.append(f"| {rule} | {r['risk']:.1%} | {r['cap']:.0%} | {r['max_open']} | {r['max_new']} | {r['gross']:g} | "
                     f"{r['floor']:g} | {d(s['med'])} | {p(s['p_1000'])} | {d(s['es5'])} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V31_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v31_summary.json").write_text(json.dumps({"verdict": v, "books": ch["books"], "sens": sens},
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
    return {"grid": R30.cmd_grid, "choose": R30.cmd_choose, "sens": cmd_sens, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v31"
    raise SystemExit(main())
