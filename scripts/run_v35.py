"""v35: growing the limit book (V35_PREREGISTRATION.md). Phase 0 is a diagnostic of v34's limit members at 30%
a position (v33 run 40192951586's choice), base costs: what each member earns, the signals the account's caps leave
out, how full the account is, and the trades and sessions behind the tail. Nothing is chosen in phase 0.

  diag    V35_DIAG.md and v35_diag.json
  run     phase 1, one (size, ladder) unit: its daily returns at the five levels under each of the 8 caps
  choose  phase 1's 384 books on the bootstrap paths, the choice on 2018-2022 paths
  stress  the choice and the top 10 at HOT 5%, spreads x2 and high costs
  final   V35_REPORT.md
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


R33 = _script("run_v33")
R29, R31, R32, A, R14 = R33.R29, R33.R31, R33.R32, R33.A, R33.R14
LEVELS, E0, FIXED = R33.LEVELS, R33.E0, R33.FIXED
SIZE = 0.30
SIZES: tuple[float, ...] = (0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
LADDERS: tuple[tuple[float, float] | None, ...] = (None, (0.10, 0.30), (0.20, 0.40), (0.20, 0.60))
CAPS1: list[tuple[float, int, int]] = [(g, mo, mn) for g in (2.0, 3.0) for mn in (3, 5) for mo in (20, 40)]
SCHEDULES: list[tuple[float, float]] = [(s1, s2) for s1 in (0.20, 0.25, 0.30) for s2 in (0.30, 0.35, 0.40, 0.50)]
UNITS = [(s, li) for s in SIZES for li in range(len(LADDERS))]
BOOKS = [(sc, ci, li) for sc in SCHEDULES for ci in range(len(CAPS1)) for li in range(len(LADDERS))]
SPLIT_LEVEL = 10_000.0
RUN_UP = ("B:v19:DS1", "B:v20:RU")
TARGET, MAX_RUIN = 30_000.0, 0.025
STRESS = ("hot5", "spread2", "high")
DIAG_LEVELS = (5_000.0, 25_000.0)
CAPS: dict[str, tuple[float, int, int]] = {"base": (2.0, 20, 3), "gross3": (3.0, 20, 3), "new5": (2.0, 20, 5),
                                           "open40": (2.0, 40, 3), "free": (99.0, 999, 99)}


def pf(net: np.ndarray) -> float:
    """Profit factor: the sum of the winning trades' returns over the sum of the losing trades' losses."""
    win, loss = net[net > 0].sum(), -net[net < 0].sum()
    return float(win / loss) if loss > 0 else float("inf")


def daily_book(taken: list[dict], T: int) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Gross weight and open positions per session, and each member's contribution per session (before the
    broker's liquidation)."""
    gross, n_open = np.zeros(T), np.zeros(T)
    by: dict[str, np.ndarray] = {}
    for it in taken:
        r, w, i0 = np.asarray(it["r"], float), float(it["w"]), int(it["i0"])
        n = min(len(r), T - i0)
        if n <= 0:
            continue
        gross[i0:i0 + n] += w
        n_open[i0:i0 + n] += 1
        by.setdefault(it["member"], np.zeros(T))[i0:i0 + n] += w * r[:n]
    return gross, n_open, by


def members_table(taken: list[dict]) -> dict[str, dict]:
    out = {}
    for m in sorted({it["member"] for it in taken}):
        x = [it for it in taken if it["member"] == m]
        net = np.array([it["net"] for it in x])
        out[m] = {"n": len(x), "win": float((net > 0).mean()), "pf": pf(net), "mean_net": float(net.mean()),
                  "worst_net": float(net.min()), "contrib": float(sum(it["contrib"] for it in x)),
                  "w_mean": float(np.mean([it["w"] for it in x]))}
    return out


def _key(it: dict) -> tuple:
    return int(it["i0"]), int(it["j"]), it["member"]


def summary(s: pd.Series, taken: list[dict], gross_cap: float) -> dict:
    T = len(s)
    gross, n_open, _ = daily_book(taken, T)
    net = np.array([it["net"] for it in taken]) if taken else np.zeros(0)
    years = s.groupby(s.index.year).apply(lambda x: float(np.prod(1 + x.to_numpy()) - 1))
    return {"n": len(taken), "pf": pf(net) if len(net) else None, "contrib": float(sum(it["contrib"] for it in taken)),
            "gross_mean": float(gross.mean()), "gross_full": float((gross >= 0.9 * gross_cap).mean()),
            "open_mean": float(n_open.mean()), "days_in": float((n_open > 0).mean()),
            "years": {str(k): v for k, v in years.items()}, "members": members_table(taken)}


def cmd_diag(args) -> int:
    ch = json.loads((args.choice / "arms.json").read_text(encoding="utf-8"))
    rows = ch["arms"]["limit"]
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    D = R14._G["D"]
    dates = D["dates"]
    R33.RISK, R33.CAP = SIZE / 10, SIZE
    out: dict = {"size": SIZE, "levels": {}}
    for level in DIAG_LEVELS:
        its = []
        for r in rows:
            its += [{**it, "member": r["fam"]} for it in R33.member_items(r["name"], {int(r["year"])}, level,
                                                                         tuple(r["var"]))]
        runs = {}
        for name, (g, mo, mn) in CAPS.items():
            s, taken = A.joint(its, dates, g, mo, mn, "move", "none", "tzi", 0.0, 0.0, None, None)
            runs[name] = (s, taken)
        lv: dict = {"offered": len(its), "caps": {n: summary(s, tk, CAPS[n][0]) for n, (s, tk) in runs.items()}}
        base_keys = {_key(it) for it in runs["base"][1]}
        left = [it for it in runs["free"][1] if _key(it) not in base_keys]
        lnet = np.array([it["net"] for it in left]) if left else np.zeros(0)
        lv["left_out"] = {"n": len(left), "mean_net": float(lnet.mean()) if len(lnet) else None,
                          "pf": pf(lnet) if len(lnet) else None,
                          "by_member": {m: sum(1 for it in left if it["member"] == m)
                                        for m in sorted({it["member"] for it in left})}}
        s, taken = runs["base"]
        worst = sorted(taken, key=lambda it: it["contrib"])[:15]
        lv["worst_trades"] = [{"date": it["date"], "member": it["member"], "entry": float(it["entry"]),
                               "w": float(it["w"]), "net": float(it["net"]), "contrib": float(it["contrib"]),
                               "sessions": len(it["r"]), "tier": int(it.get("tier", -1))} for it in worst]
        liq, _ = R33.account(rows, level)
        _, _, by = daily_book(taken, len(s))
        order = np.argsort(liq)[:10]
        lv["worst_days"] = [{"date": str(dates[d].date()), "liquidated": float(liq[d]), "before": float(s.iloc[d]),
                             "by_member": {m: float(v[d]) for m, v in by.items() if abs(v[d]) > 1e-6}}
                            for d in order]
        out["levels"][f"{level:.0f}"] = lv
        print(level, lv["offered"], {n: c["n"] for n, c in lv["caps"].items()}, flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "v35_diag.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    (args.out / "V35_DIAG.md").write_text(report(out), encoding="utf-8")
    print(report(out), flush=True)
    return 0


def _p(x) -> str:
    return "-" if x is None else f"{x:.1%}"


def report(out: dict) -> str:
    L = ["# v35 phase 0: diagnostic of the limit book at 30%", "",
         "v33's limit members (run 40192951586), size 30% a position, base costs, before the broker's liquidation "
         "unless stated. Nothing is chosen here.", ""]
    for level, lv in out["levels"].items():
        L += [f"## Equity level ${int(level):,}", "", f"Trades offered by the members: {lv['offered']}.", "",
              "| caps (gross, open, new) | trades | PF | sum of contributions | mean gross | sessions >= 90% gross | "
              "mean open | sessions in |", "|---|---|---|---|---|---|---|---|"]
        for n, c in lv["caps"].items():
            g, mo, mn = CAPS[n]
            L.append(f"| {n} ({g:g}, {mo}, {mn}) | {c['n']} | {c['pf']:.2f} | {c['contrib']:.2f} | "
                     f"{c['gross_mean']:.2f} | {_p(c['gross_full'])} | {c['open_mean']:.1f} | {_p(c['days_in'])} |")
        lo = lv["left_out"]
        L += ["", f"Left out by the base caps but taken without caps: {lo['n']} trades, mean net "
                  f"{_p(lo['mean_net'])}, PF {lo['pf'] if lo['pf'] is None else round(lo['pf'], 2)}, "
                  f"by member {lo['by_member']}.", "", "| member | trades | win | PF | mean net | worst | sum of "
                  "contributions | mean weight |", "|---|---|---|---|---|---|---|---|"]
        for m, x in lv["caps"]["base"]["members"].items():
            L.append(f"| {m} | {x['n']} | {_p(x['win'])} | {x['pf']:.2f} | {_p(x['mean_net'])} | "
                     f"{_p(x['worst_net'])} | {x['contrib']:.2f} | {x['w_mean']:.2f} |")
        L += ["", "Year by year (base caps, compounded at this level): " + ", ".join(
            f"{y} {_p(v)}" for y, v in lv["caps"]["base"]["years"].items()), "",
            "| worst trades: date | member | weight | net | contribution | sessions | tier |",
            "|---|---|---|---|---|---|---|"]
        for t in lv["worst_trades"]:
            L.append(f"| {t['date']} | {t['member']} | {t['w']:.2f} | {_p(t['net'])} | {_p(t['contrib'])} | "
                     f"{t['sessions']} | {t['tier']} |")
        L += ["", "| worst sessions: date | with liquidation | before | by member |", "|---|---|---|---|"]
        for d in lv["worst_days"]:
            L.append(f"| {d['date']} | {_p(d['liquidated'])} | {_p(d['before'])} | " + ", ".join(
                f"{m} {_p(v)}" for m, v in d["by_member"].items()) + " |")
        L.append("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- phase 1

def book_items(rows: list[dict], level: float, size: float, ladder: tuple[float, float] | None,
               spread: float = 1.0, fee: float = 1.0, hot: float = R29.BASE_LOC[1]) -> list[dict]:
    """The members' trades at a size; with a ladder, each run-up member-year is two halves at the ladder's limits
    (each half capped at half the size; the 1% of dollar volume limit applies to each half)."""
    its: list[dict] = []
    for r in rows:
        years, var = {int(r["year"])}, tuple(r["var"])
        if ladder is None or r["fam"] not in RUN_UP:
            R33.RISK, R33.CAP = size / 10, size
            its += [{**it, "member": r["fam"]} for it in R33.member_items(r["name"], years, level, var, spread, fee,
                                                                         hot)]
            continue
        R33.RISK, R33.CAP = size / 20, size / 2
        for k, lim in enumerate(ladder):
            for it in R33.member_items(r["name"], years, level, (lim, var[1], var[2]), spread, fee, hot):
                # the later half ranks just behind the first, so the first is offered the room first
                its.append({**it, "member": r["fam"], "tranche": k, "prio": it["prio"] * (1 - 1e-9 * k)})
    return its


def liq_stream(its: list[dict], caps: tuple[float, int, int]) -> np.ndarray:
    D = R14._G["D"]
    g, mo, mn = caps
    s, taken = A.joint(its, D["dates"], g, mo, mn, "move", "none", "tzi", 0.0, 0.0, None, None)
    r = s.to_numpy(float)
    out, _ = R31.liquidate(R31.position_days(taken, D, len(r)), len(r), R31.THETA)
    return out


def unit_R(rows: list[dict], size: float, ladder, caps_list: list[tuple[float, int, int]], pos: np.ndarray,
           **costs) -> np.ndarray:
    """(caps, level, session) daily returns of one (size, ladder) unit."""
    R = np.zeros((len(caps_list), len(LEVELS), len(pos)))
    for li, level in enumerate(LEVELS):
        its = book_items(rows, float(level), size, ladder, **costs)
        for ci, caps in enumerate(caps_list):
            R[ci, li] = liq_stream(its, caps)[pos]
    return R


def schedule_R(get, sched: tuple[float, float]) -> np.ndarray:
    """A schedule's returns at the five levels: size s1 below $10k, s2 from $10k. ``get(size)`` -> (level, session)."""
    lo, hi = get(sched[0]), get(sched[1])
    return np.stack([lo[li] if LEVELS[li] < SPLIT_LEVEL else hi[li] for li in range(len(LEVELS))])


def book_stats(Rb: np.ndarray, idx: dict) -> dict:
    return {sample: R32.stats(*R32.paths(Rb, Rb, ix, FIXED, None)) for sample, ix in idx.items()}


def pick(rows: list[dict]) -> dict | None:
    """The highest 2018-2022 median among the books with ruin at most 2.5% on 2018-2022 paths."""
    ok = [r for r in rows if r["early"]["p_ruin"] <= MAX_RUIN]
    return max(ok, key=lambda r: r["early"]["med"]) if ok else None


def met(r: dict | None) -> bool:
    return r is not None and r["all"]["med"] >= TARGET and r["all"]["p_ruin"] <= MAX_RUIN


def _rows(args) -> list[dict]:
    ch = json.loads((args.choice / "arms.json").read_text(encoding="utf-8"))
    return ch["arms"]["limit"]


def cmd_run(args) -> int:
    rows = _rows(args)
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    _, pos = R29._cal()
    args.out.mkdir(parents=True, exist_ok=True)
    for size, li in UNITS[args.shard::args.shards]:
        R = unit_R(rows, size, LADDERS[li], CAPS1, pos)
        np.save(args.out / f"unit_{size:.2f}_{li}.npy", R)
        print(size, LADDERS[li], np.round(R[0, 1].sum(), 3), flush=True)
    return 0


def _book_name(b: tuple) -> dict:
    (s1, s2), ci, li = b
    g, mo, mn = CAPS1[ci]
    return {"s1": s1, "s2": s2, "gross": g, "max_open": mo, "max_new": mn, "ladder": LADDERS[li]}


def cmd_choose(args) -> int:
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    units = {(s, li): np.load(args.units / f"unit_{s:.2f}_{li}.npy") for s, li in UNITS
             if (args.units / f"unit_{s:.2f}_{li}.npy").exists()}
    out = []
    for b in BOOKS:
        sc, ci, li = b
        if (sc[0], li) not in units or (sc[1], li) not in units:
            continue
        Rb = schedule_R(lambda s, li=li, ci=ci: units[(s, li)][ci], sc)
        out.append({"book": list(b), **_book_name(b), **book_stats(Rb, idx)})
    choice = pick(out)
    top = sorted([r for r in out if r["early"]["p_ruin"] <= MAX_RUIN], key=lambda r: -r["early"]["med"])[:10]
    ref = next((r for r in out if r["s1"] == r["s2"] == 0.30 and r["gross"] == 2.0 and r["max_open"] == 20
                and r["max_new"] == 3 and r["ladder"] is None), None)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "books.json").write_text(json.dumps({"choice": choice, "top": top, "v34": ref, "books": out},
                                                    indent=1, default=float), encoding="utf-8")
    print("choice", choice and {k: choice[k] for k in ("s1", "s2", "gross", "max_open", "max_new", "ladder")},
          choice and round(choice["all"]["med"]), flush=True)
    return 0


def stress_jobs(books: dict) -> list[tuple[tuple, str]]:
    seen: list[tuple] = []
    for r in ([books["choice"]] if books["choice"] else []) + books["top"]:
        b = (tuple(r["book"][0]), r["book"][1], r["book"][2])
        if b not in seen:
            seen.append(b)
    return [(b, task) for b in seen for task in STRESS]


def cmd_stress(args) -> int:
    books = json.loads((args.books / "books.json").read_text(encoding="utf-8"))
    jobs = stress_jobs(books)[args.shard::args.shards]
    if not jobs:
        return 0
    rows = _rows(args)
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, pos = R29._cal()
    idx = {"all": R32._sub_idx(cal)["all"]}
    out = []
    for b, task in jobs:
        sc, ci, li = b
        per = {s: unit_R(rows, s, LADDERS[li], [CAPS1[ci]], pos, **R33.TASKS[task])[0] for s in set(sc)}
        out.append({"book": [list(sc), ci, li], "task": task, **book_stats(schedule_R(per.__getitem__, sc), idx)})
        print(b, task, round(out[-1]["all"]["med"]), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"stress_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


def _d(x) -> str:
    return f"${x:,.0f}"


def _desc(r: dict) -> str:
    lad = "single limit" if r["ladder"] is None else f"halves at +{r['ladder'][0]:.0%}/+{r['ladder'][1]:.0%}"
    return (f"{r['s1']:.0%} under $10k, {r['s2']:.0%} from $10k; gross {r['gross']:g}x, {r['max_open']} open, "
            f"{r['max_new']} new; {lad}")


def cmd_final(args) -> int:
    books = json.loads((args.books / "books.json").read_text(encoding="utf-8"))
    stress = [r for f in sorted(args.stress.rglob("stress_*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]
    st = {(json.dumps(r["book"]), r["task"]): r["all"] for r in stress}
    c = books["choice"]
    L = ["# v35 phase 1: account levers on the limit members", "",
         f"v33's limit members; {len(books['books'])} books (size schedule x caps x entry ladder); {R29.PATHS} one-year "
         "bootstrap paths from $5,000; ruin = at or under $1,250 at any time; v31's liquidation. Choice: highest "
         "median on 2018-2022 paths with ruin <= 2.5% there.", "", "## 1. The question", ""]
    if c:
        L += [f"Choice: {_desc(c)}. All paths: median {_d(c['all']['med'])}, ruin {c['all']['p_ruin']:.1%}. "
              f"**Target (median >= $30,000, ruin <= 2.5%) met: {met(c)}.**", ""]
    else:
        L += ["No book has ruin <= 2.5% on 2018-2022 paths. **Target not met.**", ""]
    L += ["## 2. The choice, the top 10 (by 2018-2022 median) and v34's book", "",
          "| book | all median | all ruin | -50% | p10 | 2018-22 median | 2018-22 ruin | 2023+ median | 2023+ ruin | "
          "HOT 5% | spreads x2 | high |", "|" + "---|" * 12]
    rows = ([("**choice**", c)] if c else []) + [(str(i + 1), r) for i, r in enumerate(books["top"])] + \
        ([("v34", books["v34"])] if books["v34"] else [])
    for tag, r in rows:
        k = json.dumps(r["book"])
        sx = [st.get((k, t)) for t in STRESS]
        L.append(f"| {tag}: {_desc(r)} | {_d(r['all']['med'])} | {r['all']['p_ruin']:.1%} | "
                 f"{r['all']['p_half']:.1%} | {_d(r['all']['p10'])} | {_d(r['early']['med'])} | "
                 f"{r['early']['p_ruin']:.1%} | {_d(r['late']['med'])} | {r['late']['p_ruin']:.1%} | " +
                 " | ".join(f"{_d(x['med'])} / {x['p_ruin']:.1%}" if x else "-" for x in sx) + " |")
    allb = books["books"]
    L += ["", "## 3. Every lever's best book on all paths with ruin <= 2.5% (reference, not a choice)", ""]
    for name, key in (("size schedule", lambda r: (r["s1"], r["s2"])), ("caps", lambda r: (r["gross"], r["max_open"],
                      r["max_new"])), ("ladder", lambda r: str(r["ladder"]))):
        L.append(f"### {name}")
        L.append("")
        groups: dict = {}
        for r in allb:
            if r["all"]["p_ruin"] <= MAX_RUIN:
                g = key(r)
                if g not in groups or r["all"]["med"] > groups[g]["all"]["med"]:
                    groups[g] = r
        for g, r in sorted(groups.items(), key=lambda x: -x[1]["all"]["med"]):
            L.append(f"- {g}: {_d(r['all']['med'])} (ruin {r['all']['p_ruin']:.1%}) with {_desc(r)}")
        L.append("")
    best = max(allb, key=lambda r: r["all"]["med"] if r["all"]["p_ruin"] <= MAX_RUIN else -1, default=None)
    if best:
        L += [f"Highest all-paths median with all-paths ruin <= 2.5% (in-sample, not the choice): {_desc(best)}: "
              f"{_d(best['all']['med'])}, ruin {best['all']['p_ruin']:.1%}.", ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V35_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v35_summary.json").write_text(json.dumps({"met": met(c), "choice": c, "top": books["top"],
                                                           "v34": books["v34"], "stress": stress}, indent=1,
                                                          default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


# ---------------------------------------------------------------- phase 2

THRESHOLDS: dict[str, float | None] = {"never": None, "10k": 10_000.0, "25k": 25_000.0}
PAID_FIXED = R29.FIXED["PAID"]
P2_TASKS = ("base",) + STRESS


def paid_items(level: float, size: float, spread: float = 1.0, fee: float = 1.0,
               hot: float = R29.BASE_LOC[1]) -> list[dict]:
    """v29's PAID intraday members (A28's members that are not daily specs) at the book's size, v29's PAID stops."""
    R29.set_plan("PAID")
    try:
        raw: list[dict] = []
        for y, fam, nm, v26n in A.members("A28"):
            form = A._unsized(nm, v26n, 0)[0]
            if form in ("stream", "specs"):
                continue
            raw += [{**it, "member": fam} for it in A.pick_items(nm, v26n, {y}, size / 10, size, level, spread, fee)]
        return R29.tz_items(raw, level, R29.BASE_LOC[0], hot, floor=R33.FLOOR)
    finally:
        R29.set_plan("FREE")


def p2_jobs() -> list[tuple[str, int]]:
    return [(task, li) for task in P2_TASKS for li in range(len(LEVELS))]


def cmd_paid(args) -> int:
    """One (task, level): the phase 1 choice's FREE returns at its size there and, from $10k, with the PAID members."""
    books = json.loads((args.books / "books.json").read_text(encoding="utf-8"))
    c = books["choice"]
    jobs = p2_jobs()[args.shard::args.shards]
    if not jobs or c is None:
        return 0
    rows = _rows(args)
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    _, pos = R29._cal()
    caps = CAPS1[c["book"][1]]
    ladder = LADDERS[c["book"][2]]
    args.out.mkdir(parents=True, exist_ok=True)
    for task, li in jobs:
        level = float(LEVELS[li])
        size = c["s1"] if level < SPLIT_LEVEL else c["s2"]
        free = book_items(rows, level, size, ladder, **R33.TASKS[task])
        out = {"free": liq_stream(free, caps)[pos]}
        if level >= SPLIT_LEVEL:
            out["paid"] = liq_stream(free + paid_items(level, size, **R33.TASKS[task]), caps)[pos]
        np.savez(args.out / f"p2_{task}_{li}.npz", **out)
        print(task, level, {k: round(float(v.sum()), 3) for k, v in out.items()}, flush=True)
    return 0


def threshold_R(parts: dict[int, dict[str, np.ndarray]], x: float | None) -> np.ndarray:
    """The five levels' returns: FREE below the threshold, FREE + PAID from it."""
    return np.stack([parts[li]["paid"] if x is not None and LEVELS[li] >= x else parts[li]["free"]
                     for li in range(len(LEVELS))])


def paths_fee(R: np.ndarray, idx: np.ndarray, x: float | None, e0: float = E0) -> tuple[np.ndarray, np.ndarray]:
    """R32.paths with the data fee: $105 a month while the equity is at or above the threshold, else $6."""
    eq = np.full(idx.shape[0], e0)
    low = eq.copy()
    for s in range(idx.shape[1]):
        k = np.clip(np.searchsorted(LEVELS, eq, side="right") - 1, 0, len(LEVELS) - 1)
        r = R[k, idx[:, s]]
        fixed = (np.where(eq >= x, PAID_FIXED, FIXED) if x is not None else np.full(len(eq), FIXED)) * 12 / 252
        eq = np.where(eq > 0, np.maximum(eq * (1 + np.maximum(r, -1.0)) - fixed, 0.0), 0.0)
        low = np.minimum(low, eq)
    return eq, low


def cmd_final2(args) -> int:
    books = json.loads((args.books / "books.json").read_text(encoding="utf-8"))
    R29.load(args.inputs, args.report)
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    res: dict = {}
    for task in P2_TASKS:
        parts = {li: dict(np.load(args.runs / f"p2_{task}_{li}.npz")) for li in range(len(LEVELS))
                 if (args.runs / f"p2_{task}_{li}.npz").exists()}
        if len(parts) < len(LEVELS):
            continue
        samples = idx if task == "base" else {"all": idx["all"]}
        for name, x in THRESHOLDS.items():
            R = threshold_R(parts, x)
            res[(name, task)] = {s: R32.stats(*paths_fee(R, ix, x)) for s, ix in samples.items()}
    base = [{"x": n, **res[(n, "base")]} for n in THRESHOLDS if (n, "base") in res]
    choice = pick(base)
    L = ["# v35 phase 2: intraday members once the account can pay for data", "",
         f"Phase 1's choice ({_desc(books['choice'])}) below the threshold; from it the same book plus v29's PAID "
         "intraday members at the book's size, paying $105 a month while at or above it. Choice: highest median on "
         "2018-2022 paths with ruin <= 2.5% there.", ""]
    if choice:
        L += [f"Choice: threshold {choice['x']}. All paths: median {_d(choice['all']['med'])}, ruin "
              f"{choice['all']['p_ruin']:.1%}. **Target (median >= $30,000, ruin <= 2.5%) met: {met(choice)}.**", ""]
    else:
        L += ["No threshold has ruin <= 2.5% on 2018-2022 paths. **Target not met.**", ""]
    L += ["| threshold | all median | all ruin | -50% | p10 | 2018-22 median | 2018-22 ruin | 2023+ median | 2023+ ruin | "
          "HOT 5% | spreads x2 | high |", "|" + "---|" * 12]
    for r in base:
        sx = [res.get((r["x"], t)) for t in STRESS]
        L.append(f"| {r['x']} | {_d(r['all']['med'])} | {r['all']['p_ruin']:.1%} | {r['all']['p_half']:.1%} | "
                 f"{_d(r['all']['p10'])} | {_d(r['early']['med'])} | {r['early']['p_ruin']:.1%} | "
                 f"{_d(r['late']['med'])} | {r['late']['p_ruin']:.1%} | " +
                 " | ".join(f"{_d(x['all']['med'])} / {x['all']['p_ruin']:.1%}" if x else "-" for x in sx) + " |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V35_PHASE2.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v35_phase2.json").write_text(json.dumps({"met": met(choice), "choice": choice, "rows": base,
                                                          "stress": {f"{n}|{t}": v for (n, t), v in res.items()
                                                                     if t != "base"}}, indent=1, default=float),
                                              encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diag")
    d.add_argument("--choice", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--choice", type=Path, required=True)
    r.add_argument("--shard", type=int, required=True)
    r.add_argument("--shards", type=int, default=1)
    c = sub.add_parser("choose")
    c.add_argument("--units", type=Path, required=True)
    s = sub.add_parser("stress")
    s.add_argument("--choice", type=Path, required=True)
    s.add_argument("--books", type=Path, required=True)
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, default=1)
    f = sub.add_parser("final")
    f.add_argument("--books", type=Path, required=True)
    f.add_argument("--stress", type=Path, required=True)
    p2 = sub.add_parser("paid")
    p2.add_argument("--choice", type=Path, required=True)
    p2.add_argument("--books", type=Path, required=True)
    p2.add_argument("--shard", type=int, required=True)
    p2.add_argument("--shards", type=int, default=1)
    f2 = sub.add_parser("final2")
    f2.add_argument("--books", type=Path, required=True)
    f2.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"diag": cmd_diag, "run": cmd_run, "choose": cmd_choose, "stress": cmd_stress,
            "final": cmd_final, "paid": cmd_paid, "final2": cmd_final2}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v35"
    raise SystemExit(main())
