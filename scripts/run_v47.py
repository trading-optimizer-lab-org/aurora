"""v47: the book under TradeZero's real API rules (V47_PREREGISTRATION.md): no closing-auction orders, close entries
decided at 15:50, per-share locates, price floors, the SEC's short-sale price test, missing locates and missed days.

  run    one shard: one variant at every level and cost set, its bootstrap, symbol halves and diagnostics
  final  V47_REPORT.md and v47_summary.json from the shards
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing as mp
import sys
import time
import types
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


R43 = _script("run_v43")
R40, R35, R33, R32, R29, A = R43.R40, R43.R35, R43.R33, R43.R32, R43.R29, R43.A
OPEN, LAST, AH, LEVEL, TASKS, LEVELS, E2K = R43.OPEN, R43.LAST, R43.AH, R43.LEVEL, R43.TASKS, R43.LEVELS, R43.E2K
FILL, PART, LIQ, EFILL = "next_open", 0.10, "next_vwap", "auction"  # v43's central case
RULE = (0, 1.0, "hold", None, None, 1.0)
QUICK = R29.QUICK
SCRIPTS = Path(__file__).resolve().parent
GAIN_MIN, MAX_RUIN = 0.85, 0.025
CHECK = (22_006.0, 0.001)
DECIDE = 950  # close entries decided on the bars to 15:49 (the 15:50 price)
WINDOW = 30  # sessions a patched close can reach: RU's 20-session low, the 5-session trigger window, once per 20
CACHES = {"run_v26": ("_E", "_ROWS", "_OWN"), "run_v28": ("_C",), "run_v28_after": ("_TR",)}  # specs built from D

TZA = {"o1": True, "xclose": 955, "loc": (0.01, 0.03), "floor": 0.5, "ssr": True}
VARIANTS: dict[str, dict] = {
    "base": {},
    "O1": {"o1": True},
    "C955": {"cmkt": 955},
    **{f"X{s}": {"xclose": s} for s in (951, 955, 958)},
    "L1": {"loc": (0.01, 0.03)}, "L2": {"loc": (0.02, 0.05)}, "L3": {"loc": (0.03, 0.10)},
    **{f"F{int(round(f * 100)):03d}": {"floor": f} for f in (0.5, 1.0, 2.0, 2.5)},
    "SSR": {"ssr": True},
    **{f"U{int(p * 100):02d}": {"unavail": p} for p in (0.10, 0.25, 0.50)},
    **{f"M{int(p * 100):02d}": {"miss": p} for p in (0.05, 0.10, 0.20)},
    "TZA": TZA,
    "TZB": {**TZA, "loc": (0.03, 0.10), "floor": 2.0, "unavail": 0.25, "miss": 0.10},
    "TZA0": {**{k: v for k, v in TZA.items() if k != "o1"}, "cmkt": 955},
}
NAMES = list(VARIANTS)
DIAG = ("base", "TZA", "TZB")
QUICK_NAMES = ("base", "O1", "TZB")

_G: dict = {"o1": {}, "o1_count": {}}


def _u(*key) -> float:
    """A uniform number fixed by the key (seeded, the same at every level and cost set)."""
    return int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:8], 16) / 2 ** 32


def half_of(sym) -> int:
    return int(hashlib.sha256(str(sym).encode()).hexdigest()[:8], 16) % 2  # v28's symbol halves


# ---------------------------------------------------------------- O1: close entries decided at 15:50

def classes(days: list[tuple[int, int]], window: int = WINDOW) -> list[set]:
    """The close-entry days split so that no two of one column in a class lie within ``window`` sessions: each class's
    days can take their 15:50 prices at once without changing another's earlier closes."""
    out: list[set] = []
    last: list[dict] = []
    for t, j in sorted(set(days)):
        for c, lt in zip(out, last):
            if t - lt.get(j, -10 ** 9) > window:
                c.add((t, j))
                lt[j] = t
                break
        else:
            out.append({(t, j)})
            last.append({j: t})
    return out


def at_decision(B: dict, step: int = DECIDE) -> tuple[float, float, float] | None:
    """(price, high, low) of the regular session from the bars before ``step``; None without a bar."""
    c = B["c"][OPEN:step]
    ok = np.isfinite(c)
    if not ok.any():
        return None
    return float(c[ok][-1]), float(np.nanmax(B["h"][OPEN:step])), float(np.nanmin(B["l"][OPEN:step]))


def candidates() -> list[tuple[int, int]]:
    """The sessions O1 can rebuild: those with regular-session bars before the decision (the book's own entry and
    holding sessions)."""
    return sorted(k for k, B in R43._G["tl"].items() if B is not None and at_decision(B) is not None)


def patch(D: dict, days: set) -> dict:
    """D's close, high and low on ``days`` replaced in place by the 15:50 values; returns the originals to restore."""
    for k in ("C", "H", "L"):
        if not D[k].flags.writeable:
            D[k] = D[k].copy()
    keep = {}
    for t, j in days:
        B = R43.timeline(t, j)
        got = at_decision(B) if B is not None else None
        if got is None:
            continue
        keep[(t, j)] = tuple(float(D[k][t, j]) for k in ("C", "H", "L"))
        for k, x in zip(("C", "H", "L"), got):
            D[k][t, j] = x
    return keep


def restore(D: dict, keep: dict) -> None:
    for (t, j), xs in keep.items():
        for k, x in zip(("C", "H", "L"), xs):
            D[k][t, j] = x


def _clear_caches() -> None:
    """The member pipeline's caches of daily specs (rebuilt from D on the next capture)."""
    seen, stack = set(), [R43]
    while stack:
        mod = stack.pop()
        if id(mod) in seen:
            continue
        seen.add(id(mod))
        for name in CACHES.get(mod.__name__, ()):
            getattr(mod, name).clear()
        for x in vars(mod).values():
            if isinstance(x, types.ModuleType) and Path(str(getattr(x, "__file__", ""))).parent == SCRIPTS:
                stack.append(x)


def capture_o1(rows: list[dict], level: float, task: str, days: list[tuple[int, int]]) -> tuple[list, list, dict]:
    """The close entries whose signals fire with the 15:50 price as the close, on ``days``."""
    D = R43._G["D"]
    its, metas = R43._G["its"][(float(level), task)]
    out_i, out_m = [], []
    cl = classes(days)
    for cls in cl:
        keep = patch(D, cls)
        _clear_caches()
        try:
            ci, cm = R43.capture(rows, level, task)
        finally:
            restore(D, keep)
            _clear_caches()
        for it, m in zip(ci, cm):
            if m["kind"] == "close" and (int(it["t"]), int(it["j"])) in cls:
                out_i.append(it)
                out_m.append(m)
    a = {(int(it["t"]), int(it["j"]), it["member"]) for it, m in zip(its, metas) if m["kind"] == "close"}
    b = {(int(it["t"]), int(it["j"]), it["member"]) for it in out_i}
    return out_i, out_m, {"close_real": len(a), "kept": len(a & b), "dropped": len(a - b), "added": len(b - a),
                          "days": len(days), "classes": len(cl)}


def _o1_job(job: tuple) -> tuple:
    level, task = job
    return job, capture_o1(_G["rows"], level, task, _G["days"])


# ---------------------------------------------------------------- the variant's items

def cmkt_exe(step: int):
    """Close entries at market from ``step`` instead of the closing auction; open entries unchanged."""
    def f(it: dict, m: dict, e: float, es: int):
        if m["kind"] == "open":
            return e, es
        B = R43.timeline(int(it["t"]), int(it["j"]))
        if B is None:
            R43._count("cmkt_no_bars")
            return e, es
        k = np.flatnonzero(np.isfinite(B["o"][step:LAST + 1]))
        return (float(B["o"][step + k[0]]), es) if len(k) else (e, es)

    return f


def ssr_on(it: dict, kind: str) -> bool:
    """The short-sale price test on at the entry: a regular-session low 10% or more under the prior close on the
    session before, or on the entry session before a close entry's decision."""
    D = R43._G["D"]
    t, j = int(it["t"]), int(it["j"])
    C, L = D["C"], D["L"]
    if t >= 2 and np.isfinite(L[t - 1, j]) and np.isfinite(C[t - 2, j]) and L[t - 1, j] <= 0.9 * C[t - 2, j]:
        return True
    if kind == "open" or t < 1:
        return False
    B = R43.timeline(t, j)
    if B is None:
        return False
    lo = B["l"][OPEN:DECIDE]
    return bool(np.isfinite(lo).any() and np.nanmin(lo) <= 0.9 * float(C[t - 1, j]))


def locate(it: dict, v: dict) -> float:
    """The trade's locate cost a unit of value: v29's tier share, or the variant's per-share price scaled as the cost
    set scales the tier's share."""
    loc, tier = float(it.get("loc", 0.0)), int(it.get("tier", 0))
    if not v.get("loc") or tier < 1:
        return loc
    base = float(R29.BASE_LOC[tier - 1])
    return float(v["loc"][tier - 1]) / max(float(it["price"]), 0.01) * (loc / base if base > 0 else 1.0)


def kept(it: dict, m: dict, v: dict) -> bool:
    if float(it["price"]) < v.get("floor", 0.0):
        return False
    if v.get("unavail") and int(it.get("tier", 0)) >= 1 and _u(it["sym"], int(it["t"]), "47loc") < v["unavail"]:
        return False
    if v.get("miss") and _u(int(it["t"]), "47day") < v["miss"]:
        return False
    return not (v.get("ssr") and ssr_on(it, m["kind"]))


def pairs(level: float, task: str, v: dict) -> tuple[list, list]:
    its, metas = R43._G["its"][(float(level), task)]
    if not v.get("o1"):
        return its, metas
    oi, om = _G["o1"][(float(level), task)]
    keep = [(it, m) for it, m in zip(its, metas) if m["kind"] == "open"] + list(zip(oi, om))
    return [x[0] for x in keep], [x[1] for x in keep]


def items_for(its: list[dict], metas: list[dict], v: dict, half: int | None = None) -> tuple[list, list]:
    cm = v.get("cmkt", 955 if v.get("o1") else None)
    exe = cmkt_exe(cm) if cm else None
    out, recs = [], []
    for it, m in zip(its, metas):
        if half is not None and half_of(it["sym"]) != half:
            continue
        if not kept(it, m, v):
            continue
        loc = locate(it, v)
        rec = R43.replay(it, m, RULE, FILL, PART, EFILL, exe=exe, xclose=v.get("xclose"))
        if rec is None:
            continue
        c0 = float(it["raw0"]) - float(it["r"][0])
        r = np.array(rec["g"], float)
        r[0] -= c0
        rec["cost"] = c0 + loc
        recs.append(rec)
        out.append({**it, "r": r, "raw0": rec["g"][0], "i0": rec["u"][0], "nights": rec["nights"], "loc": loc,
                    "_rec": len(recs) - 1})
    return out, recs


def account(items: list[dict], recs: list[dict]) -> tuple[np.ndarray, list[dict]]:
    D = R43._G["D"]
    _, taken = A.joint(items, D["dates"], R33.GROSS, R33.MAX_OPEN, R33.MAX_NEW, "move", "none", "tzi", 0.0, 0.0,
                       None, None, None)
    return R43.liquidate(taken, recs, len(D["dates"]), LIQ, PART), taken


def gross_check(taken: list[dict], recs: list[dict]) -> dict:
    """The sessions whose short market value is over twice the equity at 15:45 and at the close (the close counts the
    close entries made that day), at a fixed level, measured and not enforced."""
    rows: dict[int, list[tuple[int, int]]] = {}
    new: dict[int, float] = {}
    for p, it in enumerate(taken):
        rec = recs[it["_rec"]]
        for i, u in enumerate(rec["u"]):
            rows.setdefault(u, []).append((p, i))
        if rec["kind"] == "close":
            new[rec["t"]] = new.get(rec["t"], 0.0) + float(it["w"])
    n = b945 = bclose = 0
    worst = 0.0
    for u in sorted(set(rows) | set(new)):
        E, M = np.ones(960), np.zeros(960)
        for p, i in rows.get(u, []):
            rec, w = recs[taken[p]["_rec"]], float(taken[p]["w"])
            G = rec["G"][i]
            if i == 0:
                G = G.copy()
                G[max(rec["es"], 0):] -= rec["cost"]
            E += w * G
            M += w * rec["M"][i]
        M[LAST] += new.get(u, 0.0)
        r945, rc = M[945] / max(E[945], 1e-9), M[LAST] / max(E[LAST], 1e-9)
        n += 1
        b945 += int(r945 > 2)
        bclose += int(rc > 2)
        worst = max(worst, r945, rc)
    return {"sessions": n, "over_2x_1545": b945 / max(n, 1), "over_2x_close": bclose / max(n, 1), "worst": worst}


# ---------------------------------------------------------------- the stages

def setup(args) -> None:
    lv = tuple(float(x) for x in np.r_[E2K, LEVELS])
    R43.setup(args, lv)
    v = VARIANTS[args.variant]
    if v.get("o1"):
        t0 = time.time()
        _G.update(rows=R35._rows(args), days=candidates())
        with mp.get_context("fork").Pool(args.procs) as pool:
            got = pool.map(_o1_job, [(level, task) for level in lv for task in TASKS], chunksize=1)
        for (level, task), (oi, om, cnt) in got:
            _G["o1"][(level, task)] = (oi, om)
            _G["o1_count"][f"{level:.0f}|{task}"] = cnt
        print(json.dumps({"o1_setup_s": round(time.time() - t0), "o1": _G["o1_count"].get(f"{LEVEL:.0f}|base")}),
              flush=True)


def _job(job: tuple) -> tuple:
    name, level, task, half = job
    v = VARIANTS[name]
    R43._G["count"] = {}
    R43.LEVEL = level
    items, recs = items_for(*pairs(level, task, v), v, half)
    r, taken = account(items, recs)
    diag = gross_check(taken, recs) if name in DIAG and half is None and level == LEVEL and task == "base" else None
    return job, r[R43._G["pos"]], {"trades": len(items), "taken": len(taken), **R43._G["count"]}, diag


def cmd_run(args) -> int:
    setup(args)
    lv2 = np.r_[E2K, LEVELS]
    name = args.variant
    jobs = [(name, float(lv), task, None) for lv in lv2 for task in TASKS]
    jobs += [(name, float(LEVEL), "base", h) for h in (0, 1)]
    t0 = time.time()
    with mp.get_context("fork").Pool(args.procs) as pool:
        got = pool.map(_job, jobs, chunksize=1)
    R = {j: r for j, r, _, _ in got}
    info = {f"{j[1]:.0f}|{j[2]}|{j[3]}": c for j, _, c, _ in got}
    diag = next((d for _, _, _, d in got if d is not None), None)
    years, ys = R43._G["years"], R43._G["ys"]
    idx = R32._sub_idx(R43._G["cal"])
    lvs = [float(x) for x in lv2]
    Rb = {task: np.stack([R[(name, lv, task, None)] for lv in lvs]) for task in TASKS}
    res = {task: R43.boot(Rb[task][1:], idx if task == "base" else {"all": idx["all"]}) for task in TASKS}
    two = R43.boot(Rb["base"], {"all": idx["all"]}, E2K, lv2)["all"]
    halves = [float(np.nansum(R40.year_stats(R[(name, float(LEVEL), "base", h)], years, ys)[:, 0])) for h in (0, 1)]
    hist = float(np.nansum(R40.year_stats(Rb["base"][lvs.index(float(LEVEL))], years, ys)[:, 0]))
    out = {"variant": name, "spec": VARIANTS[name], "res": res, "two_k": two, "halves": halves, "log_growth": hist,
           "diag": diag, "o1": _G["o1_count"], "info": info, "sec": round(time.time() - t0)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"v47_{name}.json").write_text(json.dumps(out, default=float), encoding="utf-8")
    b = res["base"]["all"]
    print(name, f"median {b['med']:,.0f} ruin {b['p_ruin']:.1%} halves {halves[0]:.2f}/{halves[1]:.2f}",
          info.get(f"{LEVEL:.0f}|base|None"), diag, flush=True)
    return 0


def _d(x: float) -> str:
    return f"${x:,.0f}"


def cmd_final(args) -> int:
    got = {}
    for p in sorted(args.runs.rglob("v47_*.json")):
        z = json.loads(p.read_text(encoding="utf-8"))
        got[z["variant"]] = z
    want = QUICK_NAMES if QUICK else NAMES
    missing = [n for n in want if n not in got]
    if missing:
        raise SystemExit(f"variants missing: {missing}")
    B = got["base"]
    b = B["res"]["base"]["all"]
    check = abs(b["med"] - CHECK[0]) <= 200 and abs(b["p_ruin"] - CHECK[1]) <= 0.002
    q1 = None
    if "TZA" in got:
        z = got["TZA"]
        q1 = bool(z["res"]["base"]["all"]["med"] >= GAIN_MIN * b["med"] and z["res"]["base"]["all"]["p_ruin"] <= MAX_RUIN
                  and z["res"]["hot5"]["all"]["p_ruin"] <= MAX_RUIN and min(z["halves"]) > 0)
    L = ["# v47: the book under TradeZero's real API rules", "",
         f"{R29.PATHS} one-year bootstrap paths from $5,000; ruin = at or under $1,250. v43's central realism case.", "",
         f"Check (base vs v43's {_d(CHECK[0])}, {CHECK[1]:.1%}): **{'reproduced' if check else 'NOT reproduced'}**.", "",
         "## Q1. Is the book operable through the API (TZA)?", "",
         f"**{q1}** (TZA median >= {GAIN_MIN} x the base's, ruin <= 2.5% at base and HOT 5%, log growth positive on both "
         "symbol halves).", "",
         "## Q2. Each variant (base costs unless named)", "",
         "| variant | change | median | vs base | ruin | p10 | 2018-22 | 2023+ | HOT 5% | spreads x2 | high | halves | "
         "from $2k |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in want:
        z = got[n]
        r = z["res"]
        a = r["base"]["all"]
        L.append(f"| {n} | {json.dumps(z['spec'])} | {_d(a['med'])} | {a['med'] / b['med'] - 1:+.1%} | {a['p_ruin']:.1%} | "
                 f"{_d(a['p10'])} | {_d(r['base']['early']['med'])} | {_d(r['base']['late']['med'])} | "
                 f"{_d(r['hot5']['all']['med'])} / {r['hot5']['all']['p_ruin']:.1%} | "
                 f"{_d(r['spread2']['all']['med'])} / {r['spread2']['all']['p_ruin']:.1%} | "
                 f"{_d(r['high']['all']['med'])} / {r['high']['all']['p_ruin']:.1%} | "
                 f"{z['halves'][0]:.2f} / {z['halves'][1]:.2f} | {_d(z['two_k']['med'])} / {z['two_k']['p_ruin']:.1%} |")
    L += ["", "## Diagnostics ($10,000 level, base costs)", "",
          "| variant | trades | taken | liquidations | sessions over 2:1 at 15:45 | over 2:1 at the close | worst ratio |",
          "|---|---|---|---|---|---|---|"]
    for n in want:
        z = got[n]
        c = z["info"].get(f"{LEVEL:.0f}|base|None", {})
        d = z["diag"] or {}
        L.append(f"| {n} | {c.get('trades', '-')} | {c.get('taken', '-')} | {c.get('liquidations', 0)} | "
                 f"{d.get('over_2x_1545', float('nan')):.1%} | {d.get('over_2x_close', float('nan')):.1%} | "
                 f"{d.get('worst', float('nan')):.2f} |" if d else
                 f"| {n} | {c.get('trades', '-')} | {c.get('taken', '-')} | {c.get('liquidations', 0)} | - | - | - |")
    o1 = got.get("O1", {}).get("o1", {}).get(f"{LEVEL:.0f}|base")
    if o1:
        L += ["", f"O1 close entries at $10,000, base costs: {o1['close_real']} on the close's signals; at 15:50 "
              f"{o1['kept']} kept, {o1['dropped']} dropped, {o1['added']} added (additions only on sessions with minute bars).", ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V47_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    (args.out / "v47_summary.json").write_text(json.dumps({"q1": q1, "check": check, "variants": got}, default=float),
                                               encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--variant", choices=NAMES)
    r.add_argument("--shard", type=int)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--procs", type=int, default=4)
        p.add_argument("--choice", type=Path, required=True)
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--data", type=Path, default=Path("outputs/v43"))
        p.add_argument("--out", type=Path, default=Path("outputs/v47w"))
    args = ap.parse_args()
    if args.cmd == "run":
        if args.variant is None:
            if args.shard is None:
                ap.error("run needs --variant or --shard")
            args.variant = NAMES[args.shard]
        return cmd_run(args)
    return cmd_final(args)


if __name__ == "__main__":
    sys.argv[0] = "run_v47"
    raise SystemExit(main())
