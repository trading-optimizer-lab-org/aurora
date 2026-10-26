"""v42: a long small-cap sleeve beside v39's best book (V42_PREREGISTRATION.md). Three long rules on the shorts'
universe, in the same account behind every short; 18 variants plus the base book, picked each year on earlier years.

  all    every variant's daily returns at every level and cost, the walk-forward picks, V42_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
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


R41 = _script("run_v41")
R40 = R41.R40
R36, R35, R33, R29, R32, R14, v28 = R40.R36, R40.R35, R40.R33, R40.R29, R40.R32, R40.R14, R40.v28
A = R33.A
v19, core = A.v19, A.core
LEVELS = R35.LEVELS
LEVEL = 10_000.0
RULES = ("breakout", "burst", "follow")
GATES = ("always", "runners")
SIZES = (0.05, 0.10, 0.15)
VARIANTS: list = ["base"] + [(r, g, s) for r in RULES for g in GATES for s in SIZES]
BASE_ID = 0
TASKS = R40.TASKS
GAIN = 1.10
HEDGE = 0.05
PER_DAY = 3
MIN_PRICE = 1.0
LONG = "L:v42"


def name(v: int) -> str:
    x = VARIANTS[v]
    return "base book" if x == "base" else f"{x[0]} {x[1]} {x[2]:.0%}"


# ---------------------------------------------------------------- the long signals

def _prior(a: np.ndarray, n: int, how: str) -> np.ndarray:
    """The max or mean of the n sessions before each session (nan until n exist)."""
    s = pd.DataFrame(a)
    r = s.rolling(n, min_periods=n)
    return (r.max() if how == "max" else r.mean()).shift(1).to_numpy()


def signals(D: dict, rule: str) -> np.ndarray:
    """(session, column) True where the rule fires at that close."""
    C, H, L, P = (np.asarray(D[k], float) for k in ("C", "H", "L", "P"))
    DV = np.nan_to_num(np.asarray(D["DV"], float))
    base = np.asarray(v28._base(D), bool) & (P >= MIN_PRICE)
    with np.errstate(invalid="ignore", divide="ignore"):
        prev = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
        day = C / prev - 1
        top = (C - L) / np.where(H > L, H - L, np.nan) >= 0.75
        if rule == "breakout":
            ok = (C > _prior(C, 20, "max")) & (DV >= 2 * _prior(DV, 20, "mean")) & (day >= 0.05) & top
        elif rule == "burst":
            rng = H / L - 1
            rng_prev = np.vstack([np.full((1, C.shape[1]), np.nan), rng[:-1]])
            calm = rng_prev <= np.vstack([np.full((1, C.shape[1]), np.nan), _prior(rng, 20, "mean")[:-1]])
            ok = (day >= 0.10) & (DV >= 3 * _prior(DV, 20, "mean")) & calm
        else:
            c5 = np.vstack([np.full((5, C.shape[1]), np.nan), C[:-5]])
            ok = (C / c5 >= 1.5) & (C >= _prior(C, 5, "max")) & top
    return np.asarray(ok & base & np.isfinite(day))


EXITS = {"breakout": {"hold": 20, "stop": 0.10, "rule": "ma10"},
         "burst": {"hold": 3, "stop": 0.08, "rule": "time"},
         "follow": {"hold": 5, "stop": 0.15, "rule": "weak"}}


def specs(D: dict, rule: str, gate: np.ndarray | None) -> list:
    """v19 long specs, at most PER_DAY a session by the day's gain."""
    ok = signals(D, rule)
    if gate is not None:
        ok &= gate[:, None]
    C = np.asarray(D["C"], float)
    prev = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    out = []
    ex = EXITS[rule]
    for t in np.flatnonzero(ok.any(axis=1)):
        js = np.flatnonzero(ok[t])
        g = C[t, js] / prev[t, js] - 1
        for j, gain in sorted(zip(js, g), key=lambda x: -x[1])[:PER_DAY]:
            out.append(v19.Spec(j=int(j), t=int(t), kind="close", side=1, hold=ex["hold"], stop=ex["stop"],
                                target=np.nan, trail=np.nan, rule=ex["rule"], prio=1e-6 * float(gain)))
    return out


def gate_flag(D: dict, X: dict) -> np.ndarray:
    hi, _ = R40.pct_flags(R40.market(D, X)["runners"], 0.8)
    s = np.concatenate([[False], hi[:-1]])  # the flag at the session before the signal
    return np.asarray(s, bool)


_D64: dict = {}


def _d64(D: dict) -> dict:
    """The data with float64 prices, so a path's returns match v31's position_days checks to 1e-9."""
    if _D64.get("id") != id(D):
        _D64.clear()
        _D64.update(id=id(D), D={**D, **{k: np.asarray(D[k], float) for k in ("O", "H", "L", "C")}})
    return _D64["D"]


def long_items(sp: list, level: float, size: float, spread: float = 1.0, fee: float = 1.0, hot: float = 0.0
               ) -> list[dict]:
    """The long specs as account items at an equity level (v19's costs; TradeZero's commissions, no locate)."""
    D, table = _d64(R14._G["D"]), A.R16._W["table"]
    keep = core.ACCOUNT
    core.ACCOUNT = level
    v19.set_costs("r4", A.R22.SLIP, A.R22.R4)
    try:
        raw = A._spec_items(D, sp, table, size / 2, size, level, spread, fee, LONG)
    finally:
        core.ACCOUNT = keep
    its = R29.tz_items(raw, level, R29.BASE_LOC[0], hot)
    return [{**it, "member": LONG} for it in its]


# ---------------------------------------------------------------- the account

_W: dict = {}


def _stream(v: int) -> np.ndarray:
    x = VARIANTS[v]
    its = _W["short"] if x == "base" else _W["short"] + _W["long"][x]
    return R36.stream(its, None)[_W["pos"]]


def _alone(key: tuple) -> np.ndarray:
    return R36.stream(_W["long"][key], None)[_W["pos"]]


def history(r: np.ndarray) -> dict[str, float]:
    """On the historical path: the worst 21-session return and the maximum drawdown."""
    lg = np.log1p(np.maximum(np.asarray(r, float), -0.999))
    eq = np.exp(np.concatenate([[0.0], np.cumsum(lg)]))
    w = eq[21:] / eq[:-21] - 1 if len(eq) > 21 else np.array([0.0])
    return {"worst21": float(w.min()), "maxdd": float((eq / np.maximum.accumulate(eq) - 1).min())}


def improved(res: dict, hist: dict) -> dict[str, bool]:
    b, w = res["base"]["base"], res["base"]["wf"]
    growth = bool(w["all"]["med"] >= GAIN * b["all"]["med"] and w["all"]["p_ruin"] <= R35.MAX_RUIN
                  and res["hot5"]["wf"]["all"]["p_ruin"] <= R35.MAX_RUIN
                  and res["high"]["wf"]["all"]["med"] >= res["high"]["base"]["all"]["med"]
                  and w["late"]["med"] >= b["late"]["med"])
    hedge = bool(w["all"]["med"] >= b["all"]["med"] and w["all"]["p_ruin"] <= b["all"]["p_ruin"]
                 and res["hot5"]["wf"]["all"]["p_ruin"] <= res["hot5"]["base"]["all"]["p_ruin"]
                 and hist["wf"]["worst21"] >= hist["base"]["worst21"] + HEDGE
                 and hist["wf"]["maxdd"] >= hist["base"]["maxdd"] + HEDGE)
    return {"growth": growth, "hedge": hedge, "any": growth or hedge}


def cmd_all(args) -> int:
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    years = np.asarray(cal.year)
    ys = sorted(set(int(y) for y in years))
    vids = list(range(len(VARIANTS)))
    if R29.QUICK:
        vids = [0, 1, 8, len(VARIANTS) - 1]
    keys = sorted({VARIANTS[v][:2] for v in vids if v != BASE_ID})
    D, X = R14._G["D"], v28.X
    g = gate_flag(D, X)
    sp = {k: specs(D, k[0], g if k[1] == "runners" else None) for k in keys}
    counts = {f"{k[0]} {k[1]}": len(s) for k, s in sp.items()}
    print(counts, flush=True)
    st: dict = {t: {v: [] for v in vids} for t in TASKS}
    alone: dict = {}
    for task in TASKS:
        costs = R33.TASKS[task]
        for level in LEVELS:
            R40._setup(args, float(level), task)
            longs = {VARIANTS[v]: long_items(sp[VARIANTS[v][:2]], float(level), VARIANTS[v][2],
                                             costs.get("spread", 1.0), costs.get("fee", 1.0))
                     for v in vids if v != BASE_ID}
            _W.update(short=R40._W["its"], long=longs, pos=R40._W["pos"])
            with mp.get_context("fork").Pool(args.procs) as pool:
                for v, r in zip(vids, pool.map(_stream, vids)):
                    st[task][v].append(r)
                if task == "base" and float(level) == LEVEL:
                    ks = [VARIANTS[v] for v in vids if v != BASE_ID]
                    alone = dict(zip(ks, pool.map(_alone, ks)))
        print(task, flush=True)
    st = {t: {v: np.stack(x) for v, x in d.items()} for t, d in st.items()}
    li = [float(x) for x in LEVELS].index(LEVEL)
    S = np.full((len(VARIANTS), len(ys), 2), np.nan)
    for v in vids:
        S[v] = R40.year_stats(st["base"][v][li], years, ys)
    G, DD = S[:, :, 0], S[:, :, 1]
    picks = R41.walk_forward(G, DD, ys)
    res, wf10 = {}, None
    for task in TASKS:
        wf = np.zeros_like(st[task][BASE_ID])
        for y, v in picks.items():
            wf[:, years == y] = st[task][v][:, years == y]
        if task == "base":
            wf10 = wf[li]
        sub = idx if task == "base" else {"all": idx["all"]}
        res[task] = {"wf": R35.book_stats(wf, sub), "base": R35.book_stats(st[task][BASE_ID], sub)}
    assert wf10 is not None
    hist = {"base": history(st["base"][BASE_ID][li]), "wf": history(wf10)}
    verdict = improved(res, hist)
    base10 = st["base"][BASE_ID][li]
    worst = base10 <= np.quantile(base10, 0.05)
    fixed = {}
    for v in vids:
        fx = {**R35.book_stats(st["base"][v], {"all": idx["all"]})["all"], **history(st["base"][v][li]),
              "log_growth": float(np.nansum(G[v])), "dd": float(np.nanmin(DD[v]))}
        if v != BASE_ID:
            a = alone[VARIANTS[v]]
            fx.update(alone_growth=float(np.log1p(np.maximum(a, -0.999)).sum()), alone_on_worst=float(a[worst].mean()))
        fixed[v] = fx
    d = R35._d
    L = ["# v42: a long small-cap sleeve beside v39's best book", "",
         f"{len(vids)} of {len(VARIANTS)} variants; base book DS1 20% RU 70% NS 40% ON1 out; {R29.PATHS} one-year "
         "bootstrap paths from $5,000; ruin = at or under $1,250 at any time. Long signals: " + json.dumps(counts),
         "", "## 1. The question", "",
         f"**v42 improves the book: {verdict['any']}** (growth test {verdict['growth']}, hedge test "
         f"{verdict['hedge']}).", "",
         "| book | costs | all median | all ruin | -50% | p10 | 2018-22 median | 2018-22 ruin | 2023+ median | "
         "2023+ ruin |", "|" + "---|" * 10]
    for task in TASKS:
        for k in ("base", "wf"):
            x = res[task][k]
            row = f"| {'walk-forward' if k == 'wf' else 'base book'} | {task} | {d(x['all']['med'])} | " \
                  f"{x['all']['p_ruin']:.1%} | {x['all']['p_half']:.1%} | {d(x['all']['p10'])} | "
            if "early" in x:
                row += f"{d(x['early']['med'])} | {x['early']['p_ruin']:.1%} | {d(x['late']['med'])} | " \
                       f"{x['late']['p_ruin']:.1%} |"
            else:
                row += "- | - | - | - |"
            L.append(row)
    L += ["", "Historical path at $10,000: " + "; ".join(
        f"{k} worst 21 sessions {h['worst21']:.1%}, max drawdown {h['maxdd']:.1%}" for k, h in hist.items()),
        "", "## 2. The walk-forward picks", "", "| year | variant |", "|---|---|"]
    L += [f"| {y} | {name(v)} |" for y, v in sorted(picks.items())]
    L += ["", "## 3. Every fixed variant (in-sample, all years; not a result)", "",
          "| variant | all median | all ruin | growth x at $10,000 | worst 21 sessions | max drawdown | sleeve alone "
          "growth x | sleeve on the base book's worst 5% sessions |", "|---|---|---|---|---|---|---|---|"]
    for v in sorted(vids, key=lambda v: -fixed[v]["log_growth"]):
        f = fixed[v]
        tail = (f"{np.exp(f['alone_growth']):,.2f} | {f['alone_on_worst']:+.2%}" if "alone_growth" in f else "- | -")
        L.append(f"| {name(v)} | {d(f['med'])} | {f['p_ruin']:.1%} | {np.exp(f['log_growth']):,.1f} | "
                 f"{f['worst21']:.1%} | {f['maxdd']:.1%} | {tail} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V42_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v42_summary.json").write_text(json.dumps(
        {"improved": verdict, "picks": {str(y): {"id": v, "name": name(v)} for y, v in picks.items()},
         "results": res, "history": hist, "signals": counts, "fixed": {name(v): f for v, f in fixed.items()}},
        indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("all")
    a.add_argument("--procs", type=int, default=4)
    a.add_argument("--choice", type=Path, required=True)
    a.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    a.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    a.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"all": cmd_all}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v42"
    raise SystemExit(main())
