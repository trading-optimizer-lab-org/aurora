"""v29: a $5,000 TradeZero account for one year (V29_PREREGISTRATION.md). COMBO28's members (the v28 report's
picks) under TradeZero International's costs, two data plans, books at five equity levels, one-year bootstrap paths
from $5,000 with the fixed costs in dollars, the choice by the chance of ruin, and a battery around it.

  grid    one cell (plan, risk, cap) of the construction grid: every book at the five levels and its one-year paths
  choose  the choice of each plan and overall
  sens    one shard of the battery around the choices
  final   V29_REPORT.md
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh
from aurora.research import v28_ideas as v28


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


A = _script("run_v28_after")
R22, R14, R16, S = A.R22, A.R14, A.R16, A.S
DATA = Path("docs/research/data")

LEVELS = np.array([2_500.0, 5_000.0, 10_000.0, 25_000.0, 60_000.0])
E0, RUIN, HALF = 5_000.0, 0.25, 0.50
PLANS = ("FREE", "PAID")
RISKS = (0.005, 0.01, 0.015, 0.02, 0.03, 0.04)
CAPS = (0.05, 0.10, 0.20, 0.40)
MAX_OPEN, MAX_NEW, GROSS = (5, 10, 20), (3, 5), (1.0, 2.0)
FLOORS, NOHOT, GATE = (0.0, 2.5), (False, True), (False, True)
HTB, HOT = (0.0025, 0.005, 0.01, 0.02), (0.01, 0.02, 0.03, 0.05, 0.08)
BASE_LOC = (0.01, 0.03)
FIXED = {"FREE": 6.0, "PAID": 105.0}  # dollars a month: the server, and the server with SIP data
COMM, COMM_MIN, COMM_MAX = 0.005, 0.49, 7.95
SEC, TAF, REP, REP_MIN = 0.0000206, 0.000249, 0.00005, 0.01
PATHS, BLOCK, DAYS, SEED = 4000, 20, 252, 29
SLEEVE_MARGIN = 0.75
QUICK = bool(os.environ.get("V29_QUICK"))  # the canary: a small grid on a test summary
if QUICK:
    RISKS, CAPS, MAX_OPEN, MAX_NEW, GROSS, FLOORS = (0.01,), (0.20,), (10,), (5,), (1.0,), (0.0,)
    HTB, HOT, PATHS = (0.01,), (0.03, 0.08), 200
CELLS = [(p, r, c) for p in PLANS for r in RISKS for c in CAPS]
ORDER = "move"


# ---------------------------------------------------------------- plans

_MODE = {"ext_off": False}
_set_orig = sh.set_params


def _set_params(p: dict | None) -> None:
    if p is not None and _MODE["ext_off"]:
        p = {**p, "ext": "none"}
    _set_orig(p)


sh.set_params = _set_params


def set_plan(plan: str, stops: str = "delay") -> None:
    """FREE: no extended-session stops. PAID: the picks' extended-session stops one bar late ('delay'), on time
    ('now', v28's), or none ('none')."""
    off = plan == "FREE" or stops == "none"
    delay = plan == "PAID" and stops == "delay"
    if (off, delay) != (_MODE["ext_off"], sh.EXT_DELAY):
        A._TR.clear()
    _MODE["ext_off"], sh.EXT_DELAY = off, delay


def tz_costs() -> None:
    """TradeZero International's per-share commission and sale fees in R4's trade cost."""
    v19.R3_COMM, v19.R3_SEC, v19.R3_TAF = COMM, SEC, TAF


def load(inputs: Path, report: Path) -> None:
    A.ARGS = argparse.Namespace(report=str(report))
    R22.R19.load(inputs)
    tz_costs()


# ---------------------------------------------------------------- the account's trades

def book(plan: str, risk: float, cap: float, level: float, spread: float = 1.0, fee: float = 1.0) -> list[dict]:
    """The members' sized trades at an equity level; FREE keeps the members decided on daily data."""
    out: list[dict] = []
    for y, _fam, nm, v26n in A.members("A28"):
        form = A._unsized(nm, v26n, 0)[0]
        if form == "stream" or (plan == "FREE" and form != "specs"):
            continue
        out += A.pick_items(nm, v26n, {y}, risk, cap, level, spread, fee)
    return out


def tiers(D: dict, t: np.ndarray, j: np.ndarray, price: np.ndarray) -> np.ndarray:
    """0 ETB, 1 HTB, 2 HOT, from the state known at the entry."""
    X = v28.X
    t, j = np.asarray(t, int), np.asarray(j, int)
    T, N = np.asarray(D["C"]).shape
    ok = (j >= 0) & (j < N) & (t >= 0) & (t < T)
    tt, jj = np.where(ok, t, 0), np.where(ok, j, 0)
    O, C = np.asarray(D["O"], float), np.asarray(D["C"], float)
    pc = C[np.maximum(tt - 1, 0), jj]
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = O[tt, jj] / pc
        rise = pc / np.asarray(X["low20s2"], float)[tt, jj] if "low20s2" in X else np.zeros(len(tt))
        si = np.asarray(X["si_so"], float)[tt, jj] if "si_so" in X else np.zeros(len(tt))
        thr = np.asarray(X["thr"], bool)[tt, jj] if "thr" in X else np.zeros(len(tt), bool)
        hot = thr | (gap >= 1.5) | (rise >= 2.0) | (si >= 0.2)
        so = np.asarray(D["SO"], float)[tt, jj]
        dv = np.asarray(D["DV1"], float)[tt, jj]
        etb = ~hot & (np.asarray(price, float) >= 10) & (so >= 50e6) & (dv >= 20e6)
    return np.where(~ok, 1, np.where(hot, 2, np.where(etb, 0, 1)))


def _unit(sym: str, t: int) -> float:
    """A uniform number fixed by the trade, the same at every level and book (seeded unavailability)."""
    return int(hashlib.sha256(f"{sym}|{t}|29".encode()).hexdigest()[:8], 16) / 2 ** 32


def tz_items(items: list[dict], level: float, htb: float, hot: float, credit: float = 0.0, unavail: float = 0.0,
             floor: float = 0.0, nohot: bool = False) -> list[dict]:
    """The trades at an equity level under TradeZero's account: whole shares, the commission minimum and maximum,
    the reporting fee, odd-lot overnight borrow, the locate by tier (``loc``), the price floor, no night in HOT
    names, extra HOT unavailability."""
    if not items:
        return []
    D, table = R14._G["D"], R16._W["table"]
    price = np.array([it["price"] for it in items], float)
    tier = tiers(D, np.array([it["t"] for it in items]), np.array([it["j"] for it in items]), price)
    px = np.maximum(price, 0.01)
    _, fee = v19.v15.lookup(table, px, np.array([it["so"] for it in items], float))
    fee = np.maximum(2 * fee, 100.0)
    out = []
    for k, it in enumerate(items):
        if price[k] < floor or (nohot and tier[k] == 2 and it["nights"] > 0):
            continue
        if unavail and tier[k] == 2 and _unit(it["sym"], it["t"]) < unavail:
            continue
        shares = np.floor(it["w"] * level / px[k])
        if shares < 1:
            continue
        value = shares * px[k]
        comm = 2 * (np.clip(COMM * shares, COMM_MIN, COMM_MAX) - COMM * shares) / value
        rep = 2 * max(np.ceil(REP * shares * 100) / 100, REP_MIN) / value
        lots = np.ceil(shares / 100) * 100 / shares
        odd = fee[k] / 100 / 360 * it["nights"] * (lots - 1) if it["side"] < 0 else 0.0
        r = np.array(it["r"], float)
        r[0] -= comm + rep + odd
        loc = (0.0, htb, hot)[int(tier[k])] if it["side"] < 0 else 0.0
        if it["nights"] <= 0:
            loc *= 1 - credit
        out.append({**it, "r": r, "w": float(value / level), "loc": float(loc), "tier": int(tier[k])})
    return out


def gate(items: list[dict]) -> list[dict]:
    """Skip a trade whose locate is at least its family's mean net return a trade (before locates) in the book's
    earlier years; nothing is skipped in a family's first year."""
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
        if np.isfinite(e) and it["loc"] >= e:
            continue
        out.append(it)
    return out


def sleeve_lt(D: dict, weight: float) -> tuple[np.ndarray, float, float] | None:
    if weight <= 0:
        return None
    lt = pd.read_csv(DATA / "v10_pick_streams.csv", index_col=0, parse_dates=True)["LT"]
    return lt.reindex(D["dates"]).fillna(0.0).to_numpy(float), weight, SLEEVE_MARGIN


# ---------------------------------------------------------------- one year from $5,000

def draws(n: int, seed: int = SEED, paths: int | None = None) -> np.ndarray:
    """Stationary block bootstrap (mean block 20 sessions): one-year paths of indices into n sessions."""
    rng = np.random.default_rng(seed)
    P = paths or PATHS
    new = rng.random((P, DAYS)) < 1 / BLOCK
    new[:, 0] = True
    starts = rng.integers(n, size=(P, DAYS))
    pos = np.maximum.accumulate(np.where(new, np.arange(DAYS), 0), axis=1)
    return (np.take_along_axis(starts, pos, axis=1) + (np.arange(DAYS) - pos)) % n


def paths(R: np.ndarray, idx: np.ndarray, fixed_month: float, e0: float = E0) -> tuple[np.ndarray, np.ndarray]:
    """(ending equity, lowest equity) of each path: R[level, session] returns, the level at or below the equity,
    the fixed costs paid every session; a path at zero stays at zero."""
    eq = np.full(idx.shape[0], e0)
    low = eq.copy()
    daily = fixed_month * 12 / 252
    for s in range(idx.shape[1]):
        k = np.clip(np.searchsorted(LEVELS, eq, side="right") - 1, 0, len(LEVELS) - 1)
        r = R[k, idx[:, s]]
        eq = np.where(eq > 0, np.maximum(eq * (1 + np.maximum(r, -1.0)) - daily, 0.0), 0.0)
        low = np.minimum(low, eq)
    return eq, low


def year_stats(eq: np.ndarray, low: np.ndarray, e0: float = E0) -> dict:
    return {"med": float(np.median(eq)), "mean": float(eq.mean()), "p10": float(np.quantile(eq, 0.10)),
            "p90": float(np.quantile(eq, 0.90)), "p_ruin": float((low <= RUIN * e0).mean()),
            "p_half": float((low <= HALF * e0).mean()), "p_loss": float((eq < e0).mean())}


def history(R: np.ndarray, cal: pd.DatetimeIndex, fixed_month: float) -> dict:
    """The historical path from $5,000 on the first session, and every twelve-month window starting a month."""
    eq, low = paths(R, np.arange(len(cal))[None, :], fixed_month)
    per = cal.to_period("M")
    first = np.flatnonzero(np.r_[True, np.asarray(per[1:] != per[:-1])])
    first = first[first + DAYS <= len(cal)]
    win = []
    if len(first):
        e, lo = paths(R, first[:, None] + np.arange(DAYS)[None, :], fixed_month)
        win = [{"start": str(cal[i].date()), "end": float(x), "low": float(y)} for i, x, y in zip(first, e, lo)]
    ends = np.array([w["end"] for w in win]) if win else np.array([np.nan])
    return {"end": float(eq[0]), "low": float(low[0]), "years": len(cal) / 252, "windows": win,
            "win_worst": float(np.nanmin(ends)), "win_med": float(np.nanmedian(ends)),
            "win_low": float(min((w["low"] for w in win), default=np.nan))}


# ---------------------------------------------------------------- books

def series(items: list[dict], g: float, mo: int, mn: int, sleeve=None) -> tuple[np.ndarray, list]:
    D = R14._G["D"]
    s, taken = A.joint(items, D["dates"], g, mo, mn, ORDER, "none", "tzi", 0.0, 0.0, None, sleeve)
    return s.to_numpy(float), taken


def _cal() -> tuple[pd.DatetimeIndex, np.ndarray]:
    D = R14._G["D"]
    a, b, cal = A._window(D)
    return cal, np.flatnonzero((D["dates"] >= a) & (D["dates"] <= b))


def cmd_grid(args) -> int:
    plan, risk, cap = CELLS[args.shard]
    load(args.inputs, args.report)
    set_plan(plan)
    D = R14._G["D"]
    cal, pos = _cal()
    idx = draws(len(cal))
    combos = [(f, nh, gt) for f in FLOORS for nh in NOHOT for gt in GATE]
    books = [(mo, mn, g) for mo in MAX_OPEN for mn in MAX_NEW for g in GROSS]
    R = {(c, b): np.zeros((len(LEVELS), len(cal))) for c in combos for b in books}
    for li, level in enumerate(LEVELS):
        raw = book(plan, risk, cap, float(level))
        for f, nh, gt in combos:
            its = tz_items(raw, float(level), *BASE_LOC, floor=f, nohot=nh)
            if gt:
                its = gate(its)
            for b in books:
                R[((f, nh, gt), b)][li] = series(its, b[2], b[0], b[1])[0][pos]
        print(f"{plan} risk {risk} cap {cap} level {level:.0f}: {len(raw)} trades", flush=True)
    rows = []
    for (c, b), arr in R.items():
        eq, low = paths(arr, idx, FIXED[plan])
        h = history(arr, cal, FIXED[plan])
        rows.append({"plan": plan, "risk": risk, "cap": cap, "floor": c[0], "nohot": c[1], "gate": c[2],
                     "max_open": b[0], "max_new": b[1], "gross": b[2], **year_stats(eq, low),
                     "hist_end": h["end"], "hist_low": h["low"], "win_worst": h["win_worst"], "win_med": h["win_med"],
                     **{f"s5k_{k}": v for k, v in S.stats(pd.Series(arr[1], index=cal), D["cash"]).items()}})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"grid_{args.shard:02d}.json").write_text(json.dumps(rows, default=float), encoding="utf-8")
    return 0


KEYS = ("plan", "risk", "cap", "floor", "nohot", "gate", "max_open", "max_new", "gross")


def pick(df: pd.DataFrame, limit: str = "p_ruin") -> dict | None:
    ok = df[df[limit] <= 0.01]
    if not len(ok):
        return None
    r = ok.sort_values(["med", "p_ruin"], ascending=[False, True], kind="stable").iloc[0]
    return {k: (r[k].item() if hasattr(r[k], "item") else r[k]) for k in r.index}


def cmd_choose(args) -> int:
    rows = [r for p in sorted(args.grid.rglob("grid_*.json")) for r in json.loads(p.read_text(encoding="utf-8"))]
    df = pd.DataFrame(rows)
    out: dict = {"n": len(df), "choice": {}, "safer": {}}
    for plan in PLANS:
        d = df[df["plan"] == plan]
        out["choice"][plan] = pick(d) or (d.iloc[0].to_dict() if QUICK and len(d) else None)
        out["safer"][plan] = pick(d, "p_half")
    ok = [c for c in out["choice"].values() if c]
    out["overall"] = max(ok, key=lambda c: c["med"])["plan"] if ok else None
    out["top"] = {plan: df[(df["plan"] == plan) & (df["p_ruin"] <= 0.01)].sort_values("med", ascending=False)
                  .head(15).to_dict("records") for plan in PLANS}
    by_risk = df[df["p_ruin"] <= 0.01].groupby(["plan", "risk"])["med"].max().reset_index()
    out["by_risk"] = by_risk.to_dict("records")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "choice.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n", "choice", "overall")}, indent=1, default=float), flush=True)
    return 0


TASKS = ("base", "locate", "credit", "spread_1.5", "spread_2.0", "high", "stops_now", "stops_none", "sleeve")


def _levels(c: dict, spread: float = 1.0, fee: float = 1.0, htb: float = BASE_LOC[0], hot: float = BASE_LOC[1],
            credit: float = 0.0, unavail: float = 0.0, sleeve=None, raw: dict | None = None
            ) -> tuple[np.ndarray, list]:
    """A chosen book's returns at the five levels (and its trades at $5,000)."""
    _, pos = _cal()
    R, taken5 = np.zeros((len(LEVELS), len(pos))), []
    for li, level in enumerate(LEVELS):
        if raw is not None and li in raw:
            items = raw[li]
        else:
            items = book(c["plan"], c["risk"], c["cap"], float(level), spread, fee)
            if raw is not None:
                raw[li] = items
        its = tz_items(items, float(level), htb, hot, credit, unavail, c["floor"], bool(c["nohot"]))
        if c["gate"]:
            its = gate(its)
        s, taken = series(its, c["gross"], int(c["max_open"]), int(c["max_new"]), sleeve)
        R[li] = s[pos]
        if level == E0:
            taken5 = taken
    return R, taken5


def cmd_sens(args) -> int:
    ch = json.loads((args.choice / "choice.json").read_text(encoding="utf-8"))
    jobs = [(plan, t) for plan in PLANS for t in TASKS if ch["choice"].get(plan)
            and not (plan == "FREE" and t.startswith("stops"))]
    mine = jobs[args.shard::args.shards]
    if not mine:
        return 0
    load(args.inputs, args.report)
    D = R14._G["D"]
    cal, _ = _cal()
    idx = draws(len(cal))
    out: list[dict] = []

    def add(plan, change, R, fixed, e0=E0, extra=None):
        eq, low = paths(R, idx, fixed, e0)
        h = history(R, cal, fixed)
        out.append({"plan": plan, "change": change, "e0": e0, **year_stats(eq, low, e0),
                    **{k: h[k] for k in ("end", "low", "win_worst", "win_med", "win_low")}, **(extra or {})})
        print(plan, change, round(out[-1]["med"]), round(out[-1]["p_ruin"], 4), flush=True)

    for plan, task in mine:
        c = ch["choice"][plan]
        set_plan(plan)
        fx = FIXED[plan]
        raw: dict = {}
        if task == "base":
            R, taken = _levels(c, raw=raw)
            add(plan, "base", R, fx, extra={"history": history(R, cal, fx)["windows"]})
            for e0 in (2_500.0, 10_000.0):
                add(plan, f"start_{int(e0)}", R, fx, e0)
            if plan == "PAID":
                add(plan, "no_data_fee", R, FIXED["FREE"])
            worst = sorted(taken, key=lambda it: it["net"])[:50]
            out.append({"plan": plan, "change": "worst", "trades": [
                {"date": it["date"], "sym": it["sym"], "fam": it["fam"], "net": it["net"], "contrib": it["contrib"],
                 "price": it["price"], "w": it["w"], "tier": it["tier"], "loc": it["loc"], **A._flags(D, it)}
                for it in worst]})
            tiers_ = {int(k): int(v) for k, v in pd.Series([it["tier"] for it in taken]).value_counts().items()}
            pnl = {int(k): float(v) for k, v in pd.Series([it["contrib"] for it in taken]).groupby(
                [it["tier"] for it in taken]).sum().items()}
            out.append({"plan": plan, "change": "tiers", "count": tiers_, "contrib": pnl, "trades": len(taken)})
        elif task == "locate":
            for h_ in HTB:
                for o_ in HOT:
                    add(plan, f"locate_{h_}_{o_}", _levels(c, htb=h_, hot=o_, raw=raw)[0], fx)
        elif task == "credit":
            for x in (0.25, 0.5):
                add(plan, f"credit_{x}", _levels(c, credit=x, raw=raw)[0], fx)
            for x in (0.25, 0.5):
                add(plan, f"unavail_{x}", _levels(c, unavail=x, raw=raw)[0], fx)
        elif task.startswith("spread"):
            add(plan, task, _levels(c, spread=float(task.split("_")[1]))[0], fx)
        elif task == "high":
            add(plan, "high", _levels(c, spread=2.0, fee=3.0)[0], fx)
        elif task.startswith("stops"):
            set_plan(plan, task.split("_")[1])
            add(plan, task, _levels(c)[0], fx)
            set_plan(plan)
        elif task == "sleeve":
            for wgt in (0.25, 0.5):
                add(plan, f"sleeve_{wgt}", _levels(c, sleeve=sleeve_lt(D, wgt), raw=raw)[0], fx)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"sens_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- V29_REPORT.md

def _d(x) -> str:
    return "-" if not isinstance(x, (int, float)) or not np.isfinite(x) else f"${x:,.0f}"


def _p(x) -> str:
    return "-" if not isinstance(x, (int, float)) or not np.isfinite(x) else f"{x:.1%}"


def cmd_final(args) -> int:
    ch = json.loads((args.choice / "choice.json").read_text(encoding="utf-8"))
    sens = [r for p in sorted(args.sens.rglob("sens_*.json")) for r in json.loads(p.read_text(encoding="utf-8"))]
    L = ["# v29: a $5,000 TradeZero account for one year", "",
         f"COMBO28's members, TradeZero International's costs, locates HTB {BASE_LOC[0]:.0%} / HOT {BASE_LOC[1]:.0%} "
         f"unless stated, middle spreads; {PATHS} one-year bootstrap paths from $5,000; ruin = the equity at or under "
         f"$1,250 at any time in the year. {ch['n']} books.", "", "## 1. The choice", "",
         "| plan | risk | cap | max open | new/day | gross | floor | no night HOT | gate | median end | p10 | p90 | "
         "ruin | -50% | loss | 2018+ from $5k | worst 12m window |", "|" + "---|" * 17]
    for kind in ("choice", "safer"):
        for plan in PLANS:
            c = ch[kind].get(plan)
            lab = plan + (" (safer)" if kind == "safer" else "")
            if not c:
                L.append(f"| {lab} | no book meets the rule |" + " |" * 15)
                continue
            L.append(f"| {lab} | {c['risk']:.1%} | {c['cap']:.0%} | {c['max_open']} | {c['max_new']} | {c['gross']:g} | "
                     f"{c['floor']:g} | {c['nohot']} | {c['gate']} | {_d(c['med'])} | {_d(c['p10'])} | {_d(c['p90'])} | "
                     f"{_p(c['p_ruin'])} | {_p(c['p_half'])} | {_p(c['p_loss'])} | {_d(c['hist_end'])} | "
                     f"{_d(c['win_worst'])} |")
    L += ["", f"Overall: **{ch['overall']}**.", "", "## 2. Best median by risk (ruin at most 1%)", "",
          "| plan | risk | median end |", "|---|---|---|"]
    for r in ch["by_risk"]:
        L.append(f"| {r['plan']} | {r['risk']:.1%} | {_d(r['med'])} |")
    L += ["", "## 3. Battery", "", "| plan | change | start | median end | p10 | p90 | ruin | -50% | loss | "
          "2018+ path | worst 12m |", "|" + "---|" * 11]
    for r in sens:
        if "med" not in r:
            continue
        L.append(f"| {r['plan']} | {r['change']} | {_d(r['e0'])} | {_d(r['med'])} | {_d(r['p10'])} | {_d(r['p90'])} | "
                 f"{_p(r['p_ruin'])} | {_p(r['p_half'])} | {_p(r['p_loss'])} | {_d(r['end'])} | {_d(r['win_worst'])} |")
    L += ["", "## 4. Trades by locate tier (base, $5,000 level)", "", "| plan | tier | trades | contribution |",
          "|---|---|---|---|"]
    for r in sens:
        if r.get("change") == "tiers":
            for k in sorted(r["count"], key=str):
                L.append(f"| {r['plan']} | {['ETB', 'HTB', 'HOT'][int(k)]} | {r['count'][k]} | "
                         f"{_p(r['contrib'].get(k, r['contrib'].get(str(k), np.nan)))} |")
    L += ["", "## 5. The 20 worst trades (base, $5,000 level)", "", "| plan | date | family | net | of the account | "
          "price | tier | gap through |", "|---|---|---|---|---|---|---|---|"]
    for r in sens:
        if r.get("change") == "worst":
            for w in r["trades"][:20]:
                L.append(f"| {r['plan']} | {w['date']} | {w['fam']} | {w['net']:.0%} | {w['contrib']:.1%} | "
                         f"{w['price']:.2f} | {['ETB', 'HTB', 'HOT'][w['tier']]} | {w['gap_through']} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V29_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v29_summary.json").write_text(json.dumps({"choice": ch, "sens": sens}, indent=1, default=float),
                                               encoding="utf-8")
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
    sys.argv[0] = "run_v29"
    raise SystemExit(main())
