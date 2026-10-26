"""v40: a large walk-forward grid of overlays on v39's best book (V40_PREREGISTRATION.md). The book's trades are
fixed; regime, cluster, calendar, dilution and crowding filters, stops, targets, holds and a size scale change what
happens to them. Every variant at the $10,000 level, picked each year on earlier years.

  run    one shard of the 5,174,400 variants (4 processes): each year's log growth and worst drawdown
  final  the walk-forward picks, both books on the bootstrap paths at the four costs, V40_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import time
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


R36 = _script("run_v36")
R35, R33 = R36.R35, R36.R33
R29, R32, R14 = R33.R29, R33.R32, R33.R14
v28 = R33.A.v28
LEVELS = R35.LEVELS
SIZES = {"B:v19:DS1": 0.20, "B:v20:RU": 0.70, "B:v20:NS": 0.40}
LEVEL = 10_000.0
REGIME: list = ["none"] + [(m, q, a) for m in ("runners", "breadth", "vix_hi", "vix_lo") for q in (0.7, 0.8, 0.9)
                           for a in ("skip", "half")]
CLUSTER: list = ["none"] + [(k, a) for k in (5, 10, 20) for a in ("skip", "half")]
CALENDAR = ("none", "june", "qend", "both")
DILUTION: list = ["none"] + [(f, a) for f in ("event", "runway", "so", "gc", "any") for a in ("boost", "cut")]
CROWD: list = ["none"] + [(f, a) for f in ("si15", "si30", "dtc5") for a in ("half", "skip")]
STOPS = (None, 0.30, 0.60, 1.00)
TARGETS = (None, 0.30, 0.50)
HOLDS = (None, 5)
SCALES = (0.6, 0.8, 1.0, 1.25)
DIMS = (REGIME, CLUSTER, CALENDAR, DILUTION, CROWD, STOPS, TARGETS, HOLDS, SCALES)
SHAPE = tuple(len(d) for d in DIMS)
NV = int(np.prod(SHAPE))
BASE = (0, 0, 0, 0, 0, 0, 0, 0, SCALES.index(1.0))
BASE_ID = int(np.ravel_multi_index(BASE, SHAPE))
TASKS = ("base",) + R35.STRESS
GAIN = 1.15
MULT = {"skip": 0.0, "half": 0.5}


def decode(vid: int) -> tuple:
    return tuple(int(x) for x in np.unravel_index(vid, SHAPE))


def name(vid: int) -> str:
    v = decode(vid)
    parts = [f"{k} {DIMS[i][v[i]]}" for i, k in enumerate(("regime", "cluster", "calendar", "dilution", "crowd",
                                                             "stop", "target", "hold", "scale"))
             if v[i] != BASE[i]]
    return ", ".join(parts) if parts else "base book"


# ---------------------------------------------------------------- the trades' features

def pct_flags(m: np.ndarray, q: float) -> tuple[np.ndarray, np.ndarray]:
    """m at or over its q-quantile of the 252 sessions before (high), at or under its (1-q)-quantile (low)."""
    s = pd.Series(np.asarray(m, float))
    hi = s.rolling(252, min_periods=126).quantile(q).shift(1).to_numpy()
    lo = s.rolling(252, min_periods=126).quantile(1 - q).shift(1).to_numpy()
    with np.errstate(invalid="ignore"):
        return np.asarray(m >= hi), np.asarray(m <= lo)


def market(D: dict, X: dict) -> dict[str, np.ndarray]:
    C = np.asarray(D["C"], float)
    base = np.asarray(v28._base(D), bool)
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        r5 = np.full_like(C, np.nan)
        r5[5:] = C[5:] / C[:-5]
        out["runners"] = np.sum(base & (r5 >= 2.0), axis=1).astype(float)
        r20 = np.full_like(C, np.nan)
        r20[20:] = np.clip(C[20:] / C[:-20] - 1, -0.9, 3.0)
        r20 = np.where(base, r20, np.nan)
        n = np.sum(np.isfinite(r20), axis=1)
        out["breadth"] = np.where(n > 0, np.nansum(r20, axis=1) / np.maximum(n, 1), np.nan)
    vix = X.get("vix")
    out["vix"] = np.asarray(vix, float) if vix is not None else np.full(C.shape[0], np.nan)
    return out


def _event_index(X: dict) -> dict[int, np.ndarray]:
    ev = X.get("events", {})
    rows = [ev[k] for k in ("effect", "pipe") if k in ev and len(ev[k])]
    if not rows:
        return {}
    x = pd.concat(rows)
    return {int(j): np.sort(g["t"].to_numpy(int)) for j, g in x.groupby("j")}


def _at(X: dict, key: str, s: np.ndarray, j: np.ndarray) -> np.ndarray:
    a = X.get(key)
    if a is None:
        return np.full(len(s), np.nan)
    a = np.asarray(a)
    ok = (s >= 0) & (j >= 0)
    out = np.full(len(s), np.nan)
    out[ok] = a[s[ok], j[ok]].astype(float)
    return out


def quarter_end(dates: pd.DatetimeIndex, k: int = 5) -> np.ndarray:
    """The last k sessions of each calendar quarter (a quarter the dates end inside of has none)."""
    q = np.asarray(dates.year * 4 + (dates.month - 1) // 3)
    rank = pd.Series(np.arange(len(q))).groupby(q).rank(ascending=False).to_numpy()
    end = dates.to_period("Q").end_time.normalize()
    done = pd.Series(np.asarray(dates)).groupby(q).transform("max").to_numpy() >= np.asarray(end - pd.Timedelta(days=6))
    return (rank <= k) & done


def exit_path(it: dict, stop, target, hold, O, H, L, C) -> tuple[np.ndarray, float] | None:
    """A run-up short's returns with a buy stop at entry x (1 + stop), a buy limit at entry x (1 - target) (not on
    the entry session) and at most ``hold`` sessions; None when nothing changes. The returns are on the entry price
    as v31's position_days reads them; a shortened trade keeps its full entry costs."""
    if it["side"] >= 0 or it.get("member") not in R35.RUN_UP or "raw0" not in it:
        return None
    i0, t, j = int(it["i0"]), int(it["t"]), int(it["j"])
    if j < 0 or i0 not in (t, t + 1):
        return None
    r = np.asarray(it["r"], float)
    n = min(len(r), C.shape[0] - i0)
    if n <= 0:
        return None
    e = float(it["entry"]) if "entry" in it else float(O[t, j] if i0 == t else C[t, j])
    if not np.isfinite(e) or e <= 0:
        return None
    cost0 = float(it["raw0"]) - r[0]
    last = n if hold is None else min(n, hold)
    sp = e * (1 + stop) if stop else None
    tp = e * (1 - target) if target else None
    for k in range(last):
        u = i0 + k
        prev = e if k == 0 else C[u - 1, j]
        entry_day = k == 0 and i0 == t
        o = e if entry_day else O[u, j]
        if not np.isfinite(o):
            o = C[u, j]
        px = None
        if sp is not None:
            if not entry_day and o >= sp:
                px = o
            elif np.isfinite(H[u, j]) and H[u, j] >= sp:
                px = sp
        if px is None and tp is not None and not entry_day:
            if o <= tp:
                px = o
            elif np.isfinite(L[u, j]) and L[u, j] <= tp:
                px = tp
        if px is not None:
            raw_k = -(px - prev) / e
            out = r[:k + 1].copy()
            if k == 0:
                out[0] = raw_k - cost0
                return out, raw_k
            out[k] = raw_k
            return out, float(it["raw0"])
    if last < n:
        return r[:last].copy(), float(it["raw0"])
    return None


def features(its: list[dict], D: dict, X: dict, mk: dict) -> dict:
    """Each trade's flags, known before its signal session, and its returns under each exit."""
    t = np.array([int(it["t"]) for it in its])
    j = np.array([int(it["j"]) for it in its])
    i0 = np.array([int(it["i0"]) for it in its])
    s = t - 1
    sc = np.clip(s, 0, None)
    f: dict = {"n": len(its)}
    for m, key in (("runners", "runners"), ("breadth", "breadth"), ("vix_hi", "vix"), ("vix_lo", "vix")):
        for q in (0.7, 0.8, 0.9):
            hi, lo = pct_flags(mk[key], q)
            f[("reg", m, q)] = np.where(s >= 0, (lo if m == "vix_lo" else hi)[sc], False)
    srt = np.sort(i0)
    f["cluster"] = np.searchsorted(srt, i0, "left") - np.searchsorted(srt, i0 - 5, "left")
    dates = D["dates"]
    f["june"] = np.asarray(dates[i0].month == 6)
    f["qend"] = quarter_end(dates)[i0]
    evx = _event_index(X)
    event = np.zeros(len(its), bool)
    for k in range(len(its)):
        e = evx.get(int(j[k]))
        if e is not None and s[k] >= 0:
            event[k] = np.searchsorted(e, s[k], "right") - np.searchsorted(e, s[k] - 119, "left") > 0
    with np.errstate(invalid="ignore"):
        dil = {"event": event, "runway": _at(X, "runway", s, j) < 6, "so": _at(X, "so_g250", s, j) >= 0.25,
               "gc": _at(X, "gc", s, j) > 0}
        dil["any"] = dil["event"] | dil["runway"] | dil["so"] | dil["gc"]
        si, dtc = _at(X, "si_so", s, j), _at(X, "dtc", s, j)
        crowd = {"si15": si >= 0.15, "si30": si >= 0.30, "dtc5": dtc >= 5}
    f.update({("dil", k): v for k, v in dil.items()})
    f.update({("crowd", k): v for k, v in crowd.items()})
    O, H, L, C = (np.asarray(D[k], float) for k in ("O", "H", "L", "C"))
    for st in STOPS:
        for tg in TARGETS:
            for hd in HOLDS:
                if st is None and tg is None and hd is None:
                    continue
                f[("exit", st, tg, hd)] = {k: p for k, it in enumerate(its)
                                           if (p := exit_path(it, st, tg, hd, O, H, L, C)) is not None}
    return f


def weights(f: dict, v: tuple) -> np.ndarray:
    n = f["n"]
    w = np.full(n, SCALES[v[8]])
    reg = REGIME[v[0]]
    if reg != "none":
        m, q, a = reg
        w = np.where(f[("reg", m, q)], w * MULT[a], w)
    cl = CLUSTER[v[1]]
    if cl != "none":
        w = np.where(f["cluster"] >= cl[0], w * MULT[cl[1]], w)
    cal = CALENDAR[v[2]]
    if cal in ("june", "both"):
        w = np.where(f["june"], 0.0, w)
    if cal in ("qend", "both"):
        w = np.where(f["qend"], 0.0, w)
    dl = DILUTION[v[3]]
    if dl != "none":
        flag = f[("dil", dl[0])]
        w = np.where(flag, w * 1.5, w) if dl[1] == "boost" else np.where(flag, w, w * 0.5)
    cr = CROWD[v[4]]
    if cr != "none":
        w = np.where(f[("crowd", cr[0])], w * MULT[cr[1]], w)
    return w


def apply(its: list[dict], f: dict, vid: int) -> list[dict]:
    v = decode(vid)
    w = weights(f, v)
    key = ("exit", STOPS[v[5]], TARGETS[v[6]], HOLDS[v[7]])
    ex = f.get(key, {})
    out = []
    for k, it in enumerate(its):
        if w[k] <= 0:
            continue
        p = ex.get(k)
        if p is None:
            out.append({**it, "w": it["w"] * w[k]})
        else:
            out.append({**it, "w": it["w"] * w[k], "r": p[0], "raw0": p[1]})
    return out


def year_stats(r: np.ndarray, years: np.ndarray, ys: list[int]) -> np.ndarray:
    """(year, [log growth, worst drawdown inside the year])."""
    out = np.full((len(ys), 2), np.nan, np.float32)
    lg = np.log1p(np.maximum(np.asarray(r, float), -0.999))
    for k, y in enumerate(ys):
        x = lg[years == y]
        if not len(x):
            continue
        eq = np.exp(np.concatenate([[0.0], np.cumsum(x)]))
        out[k] = (x.sum(), (eq / np.maximum.accumulate(eq) - 1).min())
    return out


# ---------------------------------------------------------------- the stages

def book_its(rows: list[dict], level: float, **costs) -> list[dict]:
    its: list[dict] = []
    for m, size in SIZES.items():
        its += R35.book_items([r for r in rows if r["fam"] == m], level, size, None, **costs)
    return its


_W: dict = {}


def _eval(vid: int) -> np.ndarray:
    r = R36.stream(apply(_W["its"], _W["f"], vid), None)[_W["pos"]]
    return year_stats(r, _W["years"], _W["ys"])


def _setup(args, level: float, task: str = "base") -> None:
    rows = R35._rows(args)
    D = R14._G["D"]
    cal, pos = R29._cal()
    its = book_its(rows, level, **R33.TASKS[task])
    X = v28.X
    _W.update(its=its, f=features(its, D, X, market(D, X)), pos=pos, years=np.asarray(cal.year),
              ys=sorted(set(int(y) for y in cal.year)), cal=cal)


def coverage(f: dict) -> dict:
    out = {"trades": f["n"]}
    for k, v in f.items():
        if isinstance(k, tuple) and k[0] in ("reg", "dil", "crowd"):
            out["|".join(map(str, k))] = float(np.mean(v)) if f["n"] else 0.0
        elif isinstance(k, tuple) and k[0] == "exit":
            out["|".join(map(str, k))] = len(v)
    out["cluster>=5"] = float(np.mean(f["cluster"] >= 5)) if f["n"] else 0.0
    return out


def cmd_run(args) -> int:
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    _setup(args, LEVEL)
    vids = list(range(args.shard, NV, args.shards))
    if R29.QUICK:
        vids = sorted(set(vids[:6]) | ({BASE_ID} if args.shard == 0 else set()))
    t0 = time.time()
    with mp.get_context("fork").Pool(args.procs) as pool:
        S = np.stack(pool.map(_eval, vids, chunksize=8))
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / f"part_{args.shard}.npz", vids=np.array(vids, np.int64), S=S,
                        ys=np.array(_W["ys"]))
    if args.shard == 0:
        (args.out / "coverage.json").write_text(json.dumps(coverage(_W["f"]), indent=1), encoding="utf-8")
    each = (time.time() - t0) / max(len(vids), 1) * args.procs
    print(args.shard, len(vids), "variants", f"{each:.2f} cpu-s each", flush=True)
    return 0


def smooth(G: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """Half a variant's own value, half the mean of the variants that differ from it in one dimension."""
    g = np.where(ok, G, 0.0).reshape(SHAPE)
    m = ok.astype(float).reshape(SHAPE)
    s_nb, n_nb = np.zeros(SHAPE), np.zeros(SHAPE)
    for d in range(len(SHAPE)):
        s_nb += g.sum(axis=d, keepdims=True) - g
        n_nb += m.sum(axis=d, keepdims=True) - m
    nb = np.where(n_nb > 0, s_nb / np.maximum(n_nb, 1), g)
    return (0.5 * g + 0.5 * nb).ravel()


def walk_forward(G: np.ndarray, DD: np.ndarray, ys: list[int]) -> dict[int, int]:
    """For each year after the first: the eligible variant with the highest smoothed log growth before it."""
    picks = {ys[0]: BASE_ID}
    for k in range(1, len(ys)):
        g = np.nansum(G[:, :k], axis=1)
        dd = np.nanmin(DD[:, :k], axis=1)
        ok = np.isfinite(G[:, :k]).all(axis=1) & np.isfinite(dd)
        elig = ok & (dd >= dd[BASE_ID] - 1e-12)
        sm = smooth(g, ok)
        picks[ys[k]] = int(np.flatnonzero(elig)[np.argmax(sm[elig])])
    return picks


def _read(runs: Path) -> tuple[np.ndarray, list[int], int]:
    S, ys, n = None, None, 0
    for p in sorted(runs.rglob("part_*.npz")):
        z = np.load(p)
        if S is None:
            ys = [int(y) for y in z["ys"]]
            S = np.full((NV, len(ys), 2), np.nan, np.float32)
        S[z["vids"]] = z["S"]
        n += len(z["vids"])
    assert S is not None and ys is not None, "no parts"
    return S, ys, n


def streams(args, vids: list[int]) -> dict[str, dict[int, np.ndarray]]:
    """(task) -> (variant) -> (level, session) daily returns."""
    out: dict = {t: {v: np.zeros((len(LEVELS), 0)) for v in vids} for t in TASKS}
    for task in TASKS:
        R: dict[int, list] = {v: [] for v in vids}
        for level in LEVELS:
            _setup(args, float(level), task)
            for v in vids:
                R[v].append(R36.stream(apply(_W["its"], _W["f"], v), None)[_W["pos"]])
        out[task] = {v: np.stack(R[v]) for v in vids}
        print(task, flush=True)
    return out


def cmd_final(args) -> int:
    S, ys, n = _read(args.runs)
    G, DD = S[:, :, 0].astype(float), S[:, :, 1].astype(float)
    picks = walk_forward(G, DD, ys)
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    chosen = sorted(set(picks.values()) | {BASE_ID})
    st = streams(args, chosen)
    years = np.asarray(cal.year)
    res = {}
    for task in TASKS:
        wf = np.zeros_like(st[task][BASE_ID])
        for y, v in picks.items():
            wf[:, years == y] = st[task][v][:, years == y]
        sub = idx if task == "base" else {"all": idx["all"]}
        res[task] = {"wf": R35.book_stats(wf, sub), "base": R35.book_stats(st[task][BASE_ID], sub)}
    b, w = res["base"]["base"]["all"], res["base"]["wf"]["all"]
    improved = bool(w["med"] >= GAIN * b["med"] and w["p_ruin"] <= R35.MAX_RUIN
                    and res["hot5"]["wf"]["all"]["p_ruin"] <= R35.MAX_RUIN
                    and res["high"]["wf"]["all"]["med"] >= res["high"]["base"]["all"]["med"])
    d = R35._d
    ok = np.isfinite(G).all(axis=1)
    gall = np.where(ok, G.sum(axis=1), -np.inf)
    dmin = np.where(ok, DD.min(axis=1), -np.inf)
    elig = ok & (dmin >= dmin[BASE_ID] - 1e-12)
    top = np.flatnonzero(elig)[np.argsort(-gall[elig])[:10]]
    L = ["# v40: a large walk-forward grid of overlays on v39's best book", "",
         f"{n:,} of {NV:,} variants computed; base book DS1 20% RU 70% NS 40% ON1 out; {R29.PATHS} one-year "
         "bootstrap paths from $5,000; ruin = at or under $1,250 at any time.", "", "## 1. The question", "",
         f"**v40 improves the book: {improved}.** (Walk-forward median >= {GAIN} x the base book's, ruin <= 2.5% at "
         "base costs and at HOT 5%, high-cost median >= the base book's.)", "",
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
    L += ["", "## 2. The walk-forward picks", "", "| year | variant |", "|---|---|"]
    L += [f"| {y} | {name(v)} |" for y, v in sorted(picks.items())]
    L += ["", "## 3. In-sample (all years, $10,000 level; not a result)", "",
          "Top 10 by log growth among variants whose worst yearly drawdown is no worse than the base book's:", "",
          "| variant | growth x | worst yearly drawdown |", "|---|---|---|"]
    L += [f"| {name(int(v))} | {np.exp(gall[v]):,.1f} | {dmin[v]:.0%} |" for v in top]
    L += [f"| base book | {np.exp(gall[BASE_ID]):,.1f} | {dmin[BASE_ID]:.0%} |", "",
          "Each dimension's mean all-years log growth by value (over every other dimension):", ""]
    gm = np.where(ok, G.sum(axis=1), np.nan).reshape(SHAPE)
    for i, dname in enumerate(("regime", "cluster", "calendar", "dilution", "crowd", "stop", "target", "hold",
                               "scale")):
        ax = tuple(a for a in range(len(SHAPE)) if a != i)
        mv = np.nanmean(gm, axis=ax)
        L.append(f"- {dname}: " + "; ".join(f"{DIMS[i][k]} {mv[k]:.2f}" for k in range(SHAPE[i])))
    cov = args.runs / "coverage.json"
    if cov.exists():
        L += ["", "Coverage (share of the book's trades flagged; trades an exit changes):", "",
              "```", cov.read_text(encoding="utf-8").strip(), "```"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V40_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v40_summary.json").write_text(json.dumps(
        {"improved": improved, "n": n, "picks": {str(y): {"id": v, "name": name(v)} for y, v in picks.items()},
         "results": res, "top": [{"id": int(v), "name": name(int(v)), "log_growth": float(gall[v]),
                                  "dd": float(dmin[v])} for v in top]}, indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, required=True)
    r.add_argument("--shards", type=int, default=300)
    r.add_argument("--procs", type=int, default=4)
    f = sub.add_parser("final")
    f.add_argument("--runs", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--choice", type=Path, required=True)
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"run": cmd_run, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v40"
    raise SystemExit(main())
