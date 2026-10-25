"""v32: account A with tail controls and entries ranked by edge (V32_PREREGISTRATION.md). v29's FREE members under
TradeZero International's costs and v31's forced liquidation; a bigger size a position, at most 1-5 new a session, a
cap on the open HOT shorts, a drawdown brake that halves the size, and the entry order by the family's earlier net
edge minus the locate; the choice by v29's ruin rule, and whether it beats A1.

  grid    one cell (size, order): every book at the five levels at full and half size, one-year paths
  choose  the choice, the best book for each lever value, the top 10
  sens    one shard of the battery around A1 and the choice
  final   V32_REPORT.md
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


R31 = _script("run_v31")
R29 = R31.R29
A, R14 = R29.A, R29.R14
LEVELS, E0, FIXED = R29.LEVELS, R29.E0, R29.FIXED["FREE"]
SIZES: tuple[float, ...] = (0.20, 0.25, 0.30, 0.40)
ORDERS = ("move", "edge")
MAX_NEW: tuple[int, ...] = (1, 2, 3, 5)
MAX_OPEN: tuple[int, ...] = (10, 20)
HOT_CAPS: tuple[float | None, ...] = (0.6, 1.0, None)
BRAKES: tuple[float | None, ...] = (None, 0.2, 0.3)
GROSS, FLOOR, HALF_SIZE = 2.0, 2.5, 0.5
if R29.QUICK:
    SIZES, MAX_NEW, MAX_OPEN, HOT_CAPS, BRAKES = (0.20,), (3,), (10,), (None, 0.6), (None, 0.3)
CELLS = [(s, o) for s in SIZES for o in ORDERS]
A1 = {"size": 0.20, "order": "move", "max_new": 3, "max_open": 20, "hot_cap": None, "brake": None}
KEYS = tuple(A1)
MODE: dict = {"theta": R31.THETA}
TASKS: dict[str, dict] = {"base": {}, "hot5": {"hot": 0.05}, "hot8": {"hot": 0.08}, "spread2": {"spread": 2.0},
         "high": {"spread": 2.0, "fee": 3.0}, "liq30": {"theta": 0.30}, "liq_off": {"theta": None}}
SPLIT = pd.Timestamp("2023-01-01")
LOG: list[dict] = []  # one entry a series under the rule: forced liquidations, worst session with and without it


# ---------------------------------------------------------------- the account's trades

def with_edge(items: list[dict]) -> list[dict]:
    """Each trade's ``prio`` set to its family's mean net return a trade (after costs, before the locate) over the
    candidates of earlier years, minus its locate; -1 when the family has no earlier year (ranked after the rest)."""
    if not items:
        return []
    D = R14._G["D"]
    df = pd.DataFrame({"fam": [it["fam"] for it in items], "yr": [D["dates"][it["t"]].year for it in items],
                       "net": [float(np.sum(it["r"])) for it in items]})
    g = df.groupby(["fam", "yr"])["net"].agg(["sum", "count"]).reset_index().sort_values(["fam", "yr"])
    g["csum"] = g.groupby("fam")["sum"].cumsum() - g["sum"]
    g["ccnt"] = g.groupby("fam")["count"].cumsum() - g["count"]
    edge = {(f, y): (cs / cc if cc > 0 else np.nan) for f, y, cs, cc in zip(g["fam"], g["yr"], g["csum"], g["ccnt"])}
    out = []
    for it, f, y in zip(items, df["fam"], df["yr"]):
        e = edge[(f, y)]
        out.append({**it, "prio": float(e - it["loc"]) if np.isfinite(e) else -1.0})
    return out


def items(size: float, order: str, level: float, scale: float = 1.0, spread: float = 1.0, fee: float = 1.0,
          hot: float = R29.BASE_LOC[1]) -> list[dict]:
    s = size * scale
    raw = R29.book("FREE", s / 10, s, level, spread, fee)
    its = R29.tz_items(raw, level, R29.BASE_LOC[0], hot, floor=FLOOR)
    return with_edge(its) if order == "edge" else its


def series(its: list[dict], max_open: int, max_new: int, hot_cap: float | None, order: str) -> np.ndarray:
    """One account's daily returns under the liquidation rule (MODE['theta']; None: off)."""
    D = R14._G["D"]
    s, taken = A.joint(its, D["dates"], GROSS, max_open, max_new, order, "none", "tzi", 0.0, 0.0, None, None,
                       hot_cap=hot_cap)
    s = s.to_numpy(float)
    theta = MODE["theta"]
    if theta is None:
        return s
    T = len(s)
    P = R31.position_days(taken, D, T)
    assert np.allclose(np.bincount(P["day"].astype(int), P["cl"], minlength=T), s, atol=1e-9)
    out, days = R31.liquidate(P, T, theta)
    LOG.append({"n": len(days), "worst_on": float(out.min()) if T else 0.0, "worst_off": float(s.min()) if T else 0.0})
    return out


# ---------------------------------------------------------------- one year from $5,000

def paths(Rf: np.ndarray, Rh: np.ndarray, idx: np.ndarray, fixed_month: float, brake: float | None,
          e0: float = E0) -> tuple[np.ndarray, np.ndarray]:
    """v29's paths; with a brake, a session starting more than ``brake`` under the path's highest close so far uses
    the half-size book's return."""
    eq = np.full(idx.shape[0], e0)
    low, peak = eq.copy(), eq.copy()
    daily = fixed_month * 12 / 252
    for s in range(idx.shape[1]):
        k = np.clip(np.searchsorted(LEVELS, eq, side="right") - 1, 0, len(LEVELS) - 1)
        r = Rf[k, idx[:, s]]
        if brake is not None:
            r = np.where(eq < (1 - brake) * peak, Rh[k, idx[:, s]], r)
        eq = np.where(eq > 0, np.maximum(eq * (1 + np.maximum(r, -1.0)) - daily, 0.0), 0.0)
        low = np.minimum(low, eq)
        peak = np.maximum(peak, eq)
    return eq, low


def stats(eq: np.ndarray, low: np.ndarray) -> dict:
    q = np.sort(eq)
    return {**R29.year_stats(eq, low), "es5": float(q[:max(1, int(0.05 * len(q)))].mean())}


def _sub_idx(cal: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    out = {"all": R29.draws(len(cal))}
    for name, keep in (("early", cal < SPLIT), ("late", cal >= SPLIT)):
        sub = np.flatnonzero(np.asarray(keep))
        if len(sub):
            out[name] = sub[R29.draws(len(sub))]
    return out


# ---------------------------------------------------------------- the stages

def cmd_grid(args) -> int:
    size, order = CELLS[args.shard]
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, pos = R29._cal()
    idx = R29.draws(len(cal))
    books = [(mn, mo, hc) for mn in MAX_NEW for mo in MAX_OPEN for hc in HOT_CAPS]
    R = {(b, sc): np.zeros((len(LEVELS), len(cal))) for b in books for sc in (1.0, HALF_SIZE)}
    for li, level in enumerate(LEVELS):
        for sc in (1.0, HALF_SIZE):
            its = items(size, order, float(level), sc)
            for b in books:
                R[(b, sc)][li] = series(its, b[1], b[0], b[2], order)[pos]
        print(f"size {size} {order} level {level:.0f}", flush=True)
    rows = []
    for b in books:
        for br in BRAKES:
            eq, low = paths(R[(b, 1.0)], R[(b, HALF_SIZE)], idx, FIXED, br)
            rows.append({"size": size, "order": order, "max_new": b[0], "max_open": b[1], "hot_cap": b[2],
                         "brake": br, **stats(eq, low)})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"grid_{args.shard:02d}.json").write_text(json.dumps(rows, default=float), encoding="utf-8")
    return 0


def _same(row: dict, c: dict) -> bool:
    return all(row[k] == c[k] or (isinstance(c[k], float) and row[k] is not None and abs(float(row[k]) - c[k]) < 1e-12)
               for k in KEYS)


def pick(rows: list[dict]) -> dict | None:
    ok = [r for r in rows if r["p_ruin"] <= 0.01]
    return max(ok, key=lambda r: (r["med"], -r["p_ruin"])) if ok else None


def cmd_choose(args) -> int:
    rows = [r for p in sorted(args.grid.rglob("grid_*.json")) for r in json.loads(p.read_text(encoding="utf-8"))]
    ok = [r for r in rows if r["p_ruin"] <= 0.01]
    ch = pick(rows)
    out: dict = {"n": len(rows), "books": {"A1": A1, "choice": {k: ch[k] for k in KEYS} if ch else A1},
                 "a1_row": next((r for r in rows if _same(r, A1)), None), "choice_row": ch}
    out["levers"] = []
    for k in KEYS:
        for v in sorted({r[k] for r in rows}, key=lambda x: (x is None, x)):
            b = pick([r for r in ok if r[k] == v])
            out["levers"].append({"lever": k, "value": v, "med": b["med"] if b else None,
                                  "p_ruin": b["p_ruin"] if b else None, "book": {q: b[q] for q in KEYS} if b else None})
    out["top"] = sorted(ok, key=lambda r: -r["med"])[:10]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "choice.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps(out["books"], indent=1, default=float), flush=True)
    return 0


def levels(c: dict, spread: float = 1.0, fee: float = 1.0, hot: float = R29.BASE_LOC[1]
           ) -> tuple[np.ndarray, np.ndarray]:
    """A book's returns at the five levels, at full and half size."""
    _, pos = R29._cal()
    out = []
    for sc in (1.0, HALF_SIZE):
        Rx = np.zeros((len(LEVELS), len(pos)))
        for li, level in enumerate(LEVELS):
            its = items(c["size"], c["order"], float(level), sc, spread, fee, hot)
            Rx[li] = series(its, int(c["max_open"]), int(c["max_new"]), c["hot_cap"], c["order"])[pos]
        out.append(Rx)
    return out[0], out[1]


def cmd_sens(args) -> int:
    ch = json.loads((args.choice / "choice.json").read_text(encoding="utf-8"))
    jobs = [(name, task) for name in ("A1", "choice") for task in TASKS]
    mine = jobs[args.shard::args.shards]
    if not mine:
        return 0
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, _ = R29._cal()
    idx = _sub_idx(cal)
    out = []
    for name, task in mine:
        c = ch["books"][name]
        kw = dict(TASKS[task])
        MODE["theta"] = kw.pop("theta", R31.THETA)
        LOG.clear()
        Rf, Rh = levels(c, **kw)
        for sample, ix in idx.items():
            if sample != "all" and task != "base":
                continue
            row = {"book": name, "task": task if sample == "all" else f"base_{sample}", "theta": MODE["theta"],
                   **stats(*paths(Rf, Rh, ix, FIXED, c["brake"]))}
            if MODE["theta"] is not None and len(LOG) > 1:
                row["liq_5k"] = LOG[1]
            out.append(row)
            print(name, row["task"], round(row["med"]), round(row["p_ruin"], 4), flush=True)
    MODE["theta"] = R31.THETA
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"sens_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


def verdict(get: dict) -> dict | None:
    """Section 4: the choice beats A1's median at the base costs, HOT 5% and spreads x2, with ruin at most 1%."""
    tasks = ("base", "hot5", "spread2")
    if not all(("A1", t) in get and ("choice", t) in get for t in tasks):
        return None
    beats = {t: get[("choice", t)]["med"] > get[("A1", t)]["med"] for t in tasks}
    ruin = get[("choice", "base")]["p_ruin"] <= 0.01
    return {**{f"beats_{t}": v for t, v in beats.items()}, "ruin_ok": ruin, "raises_median": all(beats.values()) and ruin}


def _b(c: dict | None) -> str:
    if not c:
        return "-"
    hc = "none" if c["hot_cap"] is None else f"{c['hot_cap']:.0%}"
    br = "off" if c["brake"] is None else f"{c['brake']:.0%}"
    return f"size {c['size']:.0%}, {c['order']}, {c['max_new']} new, {c['max_open']} open, HOT cap {hc}, brake {br}"


def cmd_final(args) -> int:
    d, p = R31.R30._d, R31.R30._p
    ch = json.loads((args.choice / "choice.json").read_text(encoding="utf-8"))
    sens = [r for f in sorted(args.sens.rglob("sens_*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]
    get = {(r["book"], r["task"]): r for r in sens}
    v = verdict(get)
    L = ["# v32: account A with tail controls and entries ranked by edge", "",
         f"v29's FREE members, TradeZero International's costs, base locates HTB 1% / HOT 3% unless stated, v31's "
         f"forced liquidation at {R31.THETA:.0%}; {R29.PATHS} one-year bootstrap paths from $5,000; ruin = the equity "
         f"at or under $1,250 at any time. {ch['n']} books in the grid.", "", "## 1. The question", ""]
    if v:
        L += [f"The choice against A1: beats its median at the base costs {v['beats_base']}, at HOT 5% "
              f"{v['beats_hot5']}, at spreads x2 {v['beats_spread2']}; ruin at most 1% {v['ruin_ok']}. "
              f"**v32 raises A1's median: {v['raises_median']}.**", ""]
    L += ["## 2. Books", "", f"- A1: {_b(ch['books']['A1'])}", f"- choice: {_b(ch['books']['choice'])}", "",
          "## 3. Battery", "", "| book | task | median | mean | p10 | p90 | ruin | -50% | loss | worst 5% mean | "
          "liquidations at $5k | worst session with / without the rule |", "|" + "---|" * 12]
    for r in sens:
        lq = r.get("liq_5k")
        L.append(f"| {r['book']} | {r['task']} | {d(r['med'])} | {d(r['mean'])} | {d(r['p10'])} | {d(r['p90'])} | "
                 f"{p(r['p_ruin'])} | {p(r['p_half'])} | {p(r['p_loss'])} | {d(r['es5'])} | "
                 f"{lq['n'] if lq else '-'} | {p(lq['worst_on']) + ' / ' + p(lq['worst_off']) if lq else '-'} |")
    L += ["", "## 4. Best median for each lever value (ruin at most 1%)", "", "| lever | value | median | ruin | book |",
          "|---|---|---|---|---|"]
    for x in ch["levers"]:
        L.append(f"| {x['lever']} | {x['value']} | {d(x['med'])} | {p(x['p_ruin'])} | {_b(x['book'])} |")
    L += ["", "## 5. Top 10 (ruin at most 1%)", "", "| book | median | p10 | ruin | -50% | worst 5% mean |",
          "|---|---|---|---|---|---|"]
    for r in ch["top"]:
        L.append(f"| {_b(r)} | {d(r['med'])} | {d(r['p10'])} | {p(r['p_ruin'])} | {p(r['p_half'])} | {d(r['es5'])} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V32_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v32_summary.json").write_text(json.dumps({"verdict": v, "books": ch["books"], "levers": ch["levers"],
                                                           "sens": sens}, indent=1, default=float), encoding="utf-8")
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
    sys.argv[0] = "run_v32"
    raise SystemExit(main())
