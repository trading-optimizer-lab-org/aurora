"""v41: a dilution tilt at equal exposure on v39's best book (V41_PREREGISTRATION.md). Flagged trades get more weight,
unflagged ones less, so the mean multiplier over the book's earlier trades is 1; 48 variants plus the base book,
picked each year on earlier years.

  all    every variant's daily returns at every level and cost, the walk-forward picks, V41_REPORT.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
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


R40 = _script("run_v40")
R36, R35, R33, R29, R32, R14, v28 = R40.R36, R40.R35, R40.R33, R40.R29, R40.R32, R40.R14, R40.v28
R40.STOPS, R40.TARGETS, R40.HOLDS = (None,), (None,), (None,)  # v41 needs the flags, not v40's exits
LEVELS = R35.LEVELS
LEVEL = 10_000.0
FLAGS = ("event", "runway", "so", "gc", "any", "score")
STRENGTHS = (1.25, 1.5, 2.0, 3.0)
SCOPES = ("all", "runup")
RUNUP = ("B:v19:DS1", "B:v20:RU")
MIN_PRIOR = 30
VARIANTS: list = ["base"] + [(f, k, s) for f in FLAGS for k in STRENGTHS for s in SCOPES]
BASE_ID = 0
TASKS = R40.TASKS
GAIN = 1.10


def name(v: int) -> str:
    x = VARIANTS[v]
    return "base book" if x == "base" else f"{x[0]} x{x[1]} {x[2]}"


def raw(f: dict, flag: str, k: float) -> np.ndarray:
    if flag == "score":
        n = sum(np.asarray(f[("dil", g)], bool).astype(float) for g in ("event", "runway", "so", "gc"))
        return np.asarray(1.0 + (k - 1.0) * n / 4.0, float)
    return np.where(np.asarray(f[("dil", flag)], bool), k, 1.0)


def multipliers(m_raw: np.ndarray, i0: np.ndarray, scope: np.ndarray) -> np.ndarray:
    """Each in-scope trade's raw multiplier over the mean of the in-scope trades entered strictly before it (1 until
    MIN_PRIOR of them exist); out-of-scope trades keep 1."""
    out = np.ones(len(m_raw))
    k = np.flatnonzero(scope)
    if not len(k):
        return out
    order = k[np.argsort(i0[k], kind="stable")]
    t, x = i0[order], m_raw[order]
    cs = np.concatenate([[0.0], np.cumsum(x)])
    n_before = np.searchsorted(t, t, "left")
    mean = cs[n_before] / np.maximum(n_before, 1)
    out[order] = np.where(n_before >= MIN_PRIOR, x / np.where(n_before > 0, mean, 1.0), 1.0)
    return out


def apply(its: list[dict], f: dict, v: int) -> list[dict]:
    if VARIANTS[v] == "base":
        return its
    flag, k, sc = VARIANTS[v]
    i0 = np.array([int(it["i0"]) for it in its])
    scope = np.array([sc == "all" or it["member"] in RUNUP for it in its])
    m = multipliers(raw(f, flag, k), i0, scope)
    return [{**it, "w": it["w"] * m[q]} for q, it in enumerate(its)]


_W: dict = {}


def _stream(v: int) -> np.ndarray:
    return R36.stream(apply(_W["its"], _W["f"], v), None)[_W["pos"]]


def walk_forward(G: np.ndarray, DD: np.ndarray, ys: list[int]) -> dict[int, int]:
    """For each year after the first: the eligible variant with the highest log growth summed over earlier years."""
    picks = {ys[0]: BASE_ID}
    for k in range(1, len(ys)):
        g = np.nansum(G[:, :k], axis=1)
        dd = np.nanmin(DD[:, :k], axis=1)
        ok = np.isfinite(G[:, :k]).all(axis=1) & np.isfinite(dd) & (dd >= dd[BASE_ID] - 1e-12)
        picks[ys[k]] = int(np.flatnonzero(ok)[np.argmax(g[ok])])
    return picks


def cmd_all(args) -> int:
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    cal, _ = R29._cal()
    idx = R32._sub_idx(cal)
    years = np.asarray(cal.year)
    ys = sorted(set(int(y) for y in years))
    vids = list(range(len(VARIANTS)))
    if R29.QUICK:
        vids = [0, 1, 2, len(VARIANTS) - 1]
    st: dict = {t: {v: [] for v in vids} for t in TASKS}
    cov: dict = {}
    for task in TASKS:
        for level in LEVELS:
            R40._setup(args, float(level), task)
            _W.update(its=R40._W["its"], f=R40._W["f"], pos=R40._W["pos"])
            if task == "base" and float(level) == LEVEL:
                cov = {g: float(np.mean(_W["f"][("dil", g)])) for g in ("event", "runway", "so", "gc", "any")}
                cov["trades"] = _W["f"]["n"]
            with mp.get_context("fork").Pool(args.procs) as pool:
                for v, r in zip(vids, pool.map(_stream, vids)):
                    st[task][v].append(r)
        print(task, flush=True)
    st = {t: {v: np.stack(x) for v, x in d.items()} for t, d in st.items()}
    li = [float(x) for x in LEVELS].index(LEVEL)
    S = np.full((len(VARIANTS), len(ys), 2), np.nan)
    for v in vids:
        S[v] = R40.year_stats(st["base"][v][li], years, ys)
    G, DD = S[:, :, 0], S[:, :, 1]
    picks = walk_forward(G, DD, ys)
    res = {}
    for task in TASKS:
        wf = np.zeros_like(st[task][BASE_ID])
        for y, v in picks.items():
            wf[:, years == y] = st[task][v][:, years == y]
        sub = idx if task == "base" else {"all": idx["all"]}
        res[task] = {"wf": R35.book_stats(wf, sub), "base": R35.book_stats(st[task][BASE_ID], sub)}
    b, w = res["base"]["base"], res["base"]["wf"]
    improved = bool(w["all"]["med"] >= GAIN * b["all"]["med"] and w["all"]["p_ruin"] <= R35.MAX_RUIN
                    and res["hot5"]["wf"]["all"]["p_ruin"] <= R35.MAX_RUIN
                    and res["high"]["wf"]["all"]["med"] >= res["high"]["base"]["all"]["med"]
                    and w["late"]["med"] >= b["late"]["med"])
    fixed = {v: R35.book_stats(st["base"][v], {"all": idx["all"]})["all"] for v in vids}
    d = R35._d
    L = ["# v41: a dilution tilt at equal exposure on v39's best book", "",
         f"{len(vids)} of {len(VARIANTS)} variants; base book DS1 20% RU 70% NS 40% ON1 out; {R29.PATHS} one-year "
         "bootstrap paths from $5,000; ruin = at or under $1,250 at any time.", "", "## 1. The question", "",
         f"**v41 improves the book: {improved}.** (Walk-forward median >= {GAIN} x the base book's, ruin <= 2.5% at "
         "base costs and at HOT 5%, high-cost median >= the base book's, 2023+ median >= the base book's.)", "",
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
    L += ["", "## 3. Every fixed variant (in-sample, all years; not a result)", "",
          "| variant | all median | all ruin | growth x at $10,000 | worst yearly drawdown |", "|---|---|---|---|---|"]
    order = sorted(vids, key=lambda v: -np.nansum(G[v]))
    L += [f"| {name(v)} | {d(fixed[v]['med'])} | {fixed[v]['p_ruin']:.1%} | {np.exp(np.nansum(G[v])):,.1f} | "
          f"{np.nanmin(DD[v]):.0%} |" for v in order]
    L += ["", f"Flag coverage (share of the book's trades): {json.dumps(cov)}"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V41_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v41_summary.json").write_text(json.dumps(
        {"improved": improved, "picks": {str(y): {"id": v, "name": name(v)} for y, v in picks.items()},
         "results": res, "coverage": cov,
         "fixed": {name(v): {**fixed[v], "log_growth": float(np.nansum(G[v])), "dd": float(np.nanmin(DD[v]))}
                   for v in vids}}, indent=1, default=float), encoding="utf-8")
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
    sys.argv[0] = "run_v41"
    raise SystemExit(main())
