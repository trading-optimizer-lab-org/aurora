"""v20 shards and report. Pre-registered in docs/research/V20_PREREGISTRATION.md.

  shard   every configuration under the realistic R3 costs: monthly returns at half-spreads x0.5, x1 and x2 (borrow
          x3 at x2) and gross, daily middle-cost returns, trade statistics, and 200 placebos with their Sortino
          ratio over the whole period and over the months before each walk-forward year
  report  the v14 procedure vectorised over the monthly matrices (plateau walk-forward picks, placebo gate, CPCV
          PBO, COMBO20, deflated Sharpe), the false discovery rate over every configuration, the gross record, the
          2023-07+ segment, the trades, and how each entry and exit choice did
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import norm

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v20_grid as v20


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R19 = _script("run_v19")
R16, R14 = R19.R16, R19.R14
SHARDS, REPS, SLIP = 300, 200, 0.25
SEGMENT = ("2023-07-01", "2026-10-16")
WINDOWS = ("all", *range(2018, 2027))  # placebo Sortino windows: the whole period, and the months before each year


def registry() -> dict[str, tuple[str, list[dict]]]:
    out = {k: ("intra", core.grid(d)) for k, d in v20.INTRA_DIMS.items()}
    out.update({k: ("daily", core.grid(d)) for k, d in v20.DAILY_DIMS.items()})
    return out


def configs() -> list[tuple[str, int]]:
    return [(k, i) for k, (_, cfgs) in registry().items() for i in range(len(cfgs))]


def window_rows(months: pd.DatetimeIndex, w) -> np.ndarray:
    return np.ones(len(months), bool) if w == "all" else np.asarray(months < pd.Timestamp(f"{w}-01-01"))


# ---------------------------------------------------------------- shard

_G: dict = {"pools": {}}


def _books(key: str, g: dict):
    kind = registry()[key][0]
    D, store = R14._G["D"], R14._G["store"]
    table, E = R16._W["table"], R16._W["E"]
    if kind == "intra":
        trades = v20.intraday_trades(store, D, key, g)
        return trades, lambda sp, fm, gr: v19.intra_book(trades, D["dates"], table, sp, fm, gr)
    specs = v20.daily_specs(D, E, key, g)
    return specs, lambda sp, fm, gr: v19.daily_book(D, specs, table, sp, fm, gr)


def _design(s: pd.Series) -> pd.Series:
    return s.loc[core.DESIGN_START:core.last_day()]


def evaluate(key: str, ci: int) -> tuple[dict, pd.Series, np.ndarray, dict]:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    D, store, table = R14._G["D"], R14._G["store"], R16._W["table"]
    dates = D["dates"]
    v19.set_costs("r3", SLIP)
    trades, book = _books(key, g)
    real, stats = {}, {"signals": len(trades)}
    for sc, spread, fee in R19.SCENARIOS:
        s, paths, taken = book(spread, fee, False)
        real[sc] = s
        if sc == "mid":
            stats.update(v19.trade_stats(paths, taken, dates))
    v19.set_costs("r3", 0.0)  # the gross record has no costs at all, slippage included
    try:
        real["gross"] = _books(key, g)[1](0.0, 1.0, True)[0]
    finally:
        v19.set_costs("r3", SLIP)
    daily = {k: _design(v) for k, v in real.items()}
    monthly = {k: core.monthly(v.to_frame("r"))["r"] for k, v in daily.items()}
    mid = daily["mid"]
    stats["sharpe"] = float(mid.mean() / mid.std() * np.sqrt(252)) if mid.std() > 0 else None
    months = monthly["mid"].index
    if "cm" not in _G:
        _G["cm"] = core.monthly(D["cash"].reindex(mid.index).fillna(0.0).to_frame("c"))["c"].reindex(months).to_numpy()
    PM = np.zeros((len(months), REPS))
    for r in range(REPS):
        rng = np.random.default_rng(R14._seed(key, ci, r + 1))
        if kind == "intra":
            pk = (key, g["band"])
            if pk not in _G["pools"]:
                _G["pools"][pk] = v20.pool_by_day(store, key, g["band"])
            s = v19.intra_book(v19.intraday_placebo(store, D, trades, rng, _G["pools"][pk]), dates, table, 1.0)[0]
        else:
            s = v19.daily_book(D, v20.daily_placebo(D, trades, rng, g.get("band")), table, 1.0)[0]
        PM[:, r] = core.monthly(_design(s).to_frame("r"))["r"].reindex(months).fillna(0.0).to_numpy()
    ts = months.to_timestamp()
    W = np.full((REPS, len(WINDOWS)), np.nan, np.float32)
    for k, w in enumerate(WINDOWS):
        rows = window_rows(ts, w)
        if rows.sum() >= 12:
            W[:, k] = core.sortino_cols(PM[rows], _G["cm"][rows])
    return monthly, mid, W, stats


def _work(u):
    key, ci, deadline = u
    t0 = time.time()
    if t0 > deadline:
        return key, ci, None, 0.0, "skipped: shard time limit"
    try:
        return key, ci, evaluate(key, ci), time.time() - t0, None
    except Exception as exc:  # recorded and reported
        return key, ci, None, time.time() - t0, f"{type(exc).__name__}: {exc}"


def cmd_shard(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v20 runs on the whole sample: the unlock must be set")
    t0 = time.time()
    R19.load(args.inputs)
    deadline = t0 + args.minutes * 60
    mine = [(k, i, deadline) for k, i in configs()[args.shard::args.shards]]
    print(f"shard {args.shard}: {len(mine)} configurations", flush=True)
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            res = list(pool.imap_unordered(_work, mine, chunksize=1))
    else:
        res = [_work(u) for u in mine]
    mcols, dcols, names, Ws, meta = {}, {}, [], [], []
    for key, ci, out, sec, err in res:
        name = f"{key}|{ci}"
        st = {}
        if out is not None:
            monthly, mid, W, st = out
            for sc, m in monthly.items():
                mcols[f"{name}|{sc}"] = m.astype(np.float32)
            dcols[name] = mid.astype(np.float32)
            names.append(name)
            Ws.append(W)
        meta.append({"key": key, "ci": ci, "sec": round(sec, 1), "error": err, **st})
    args.out.mkdir(parents=True, exist_ok=True)
    if mcols:
        m = pd.DataFrame(mcols)
        m.index = m.index.to_timestamp()
        m.to_parquet(args.out / "monthly.parquet")
        pd.DataFrame(dcols).to_parquet(args.out / "daily.parquet")
        np.savez_compressed(args.out / "placebo.npz", names=np.array(names), W=np.stack(Ws))
    (args.out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    errs = [x for x in meta if x["error"]]
    print(f"shard done in {time.time() - t0:.0f}s: {len(res)} configurations, {len(errs)} errors or skipped", flush=True)
    for e in errs[:5]:
        print("error:", e, flush=True)
    return 0


# ---------------------------------------------------------------- the v14 procedure, vectorised

def neighbours_matrix(cfgs: list[dict]) -> sparse.csr_matrix:
    """``core.neighbours`` for configurations of one grid, as a sparse 0/1 matrix: every configuration and those
    that differ from it in one value."""
    n = len(cfgs)
    keys = list(cfgs[0])
    codes = np.column_stack([pd.factorize(pd.Series([c[k] for c in cfgs], dtype=object))[0] for k in keys])
    rows, cols = [np.arange(n)], [np.arange(n)]
    for d in range(len(keys)):
        _, grp = np.unique(np.delete(codes, d, axis=1), axis=0, return_inverse=True)
        grp = np.asarray(grp).ravel()
        order = np.argsort(grp, kind="stable")
        bounds = np.flatnonzero(np.diff(grp[order])) + 1
        for members in np.split(order, bounds):
            if len(members) > 1:
                rows.append(np.repeat(members, len(members)))
                cols.append(np.tile(members, len(members)))
    r, c = np.concatenate(rows), np.concatenate(cols)
    A = sparse.csr_matrix((np.ones(len(r)), (r, c)), shape=(n, n))
    A.data[:] = 1.0
    return A


def plateau(s: np.ndarray, A: sparse.csr_matrix) -> np.ndarray:
    f = np.isfinite(s)
    num = A @ np.where(f, s, 0.0)
    den = A @ f.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def walk_forward(M: np.ndarray, cm: np.ndarray, A, months: pd.DatetimeIndex, last_year: int) -> dict:
    """``core.walk_forward``'s yearly picks: {year: (column, plateau score)}."""
    picks = {}
    for y in range(core.WF_YEARS[0], last_year + 1):
        tr = window_rows(months, y)
        if tr.sum() < 12:
            continue
        s = plateau(core.score(M[tr], cm[tr]), A)
        if not np.isfinite(s).any():
            continue
        i = int(np.nanargmax(s))
        picks[y] = (i, float(s[i]))
    return picks


def cpcv(M: np.ndarray, cm: np.ndarray, A) -> dict:
    """``core.cpcv`` on a monthly matrix."""
    blocks = np.array_split(np.arange(len(M)), core.N_BLOCKS)
    test_s, ranks = [], []
    for tr in combinations(range(core.N_BLOCKS), core.N_BLOCKS // 2):
        tr_rows = np.concatenate([blocks[b] for b in tr])
        te_rows = np.concatenate([blocks[b] for b in range(core.N_BLOCKS) if b not in tr])
        s = plateau(core.score(M[tr_rows], cm[tr_rows]), A)
        if not np.isfinite(s).any():
            continue
        i = int(np.nanargmax(s))
        te = core.sortino_cols(M[te_rows], cm[te_rows])
        valid = te[np.isfinite(te)]
        if not len(valid):
            continue
        test_s.append(float(te[i]))
        ranks.append(float((valid < te[i]).sum() + 0.5 * (valid == te[i]).sum()) / len(valid))
    ra, ta = np.array(ranks), np.array(test_s)
    if not len(ra):
        return {"splits": 0, "pbo": np.nan}
    return {"splits": len(ra), "pbo": float((ra < 0.5).mean()), "test_median": float(np.nanmedian(ta)),
            "test_p10": float(np.nanpercentile(ta, 10)), "test_p90": float(np.nanpercentile(ta, 90))}


def combo_pbo(mats: dict, cm: np.ndarray) -> dict:
    """``run_v14.combo_pbo`` on monthly matrices: {family: (M, A)}."""
    allM = np.hstack([M for M, _ in mats.values()])
    blocks = np.array_split(np.arange(len(cm)), core.N_BLOCKS)
    ranks, tests = [], []
    for tr in combinations(range(core.N_BLOCKS), core.N_BLOCKS // 2):
        tr_rows = np.concatenate([blocks[b] for b in tr])
        te_rows = np.concatenate([blocks[b] for b in range(core.N_BLOCKS) if b not in tr])
        cols = []
        for M, A in mats.values():
            s = plateau(core.score(M[tr_rows], cm[tr_rows]), A)
            if np.isfinite(s).any() and np.nanmax(s) >= 1.0:
                cols.append(M[:, int(np.nanargmax(s))])
        te_all = core.sortino_cols(allM[te_rows], cm[te_rows])
        valid = te_all[np.isfinite(te_all)]
        if not cols or not len(valid):
            continue
        C = np.column_stack(cols)
        w = R14._ivol(pd.DataFrame(C[tr_rows])).to_numpy()
        combo_te = core.sortino_cols((C[te_rows] @ w)[:, None], cm[te_rows])[0]
        tests.append(combo_te)
        ranks.append(float((valid < combo_te).sum() + 0.5 * (valid == combo_te).sum()) / len(valid))
    if not ranks:
        return {"splits": 0, "pbo": np.nan}
    return {"splits": len(ranks), "pbo": float((np.array(ranks) < 0.5).mean()),
            "test_median": float(np.median(tests)), "test_p10": float(np.percentile(tests, 10))}


def bh(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg rejections at false discovery rate q."""
    p = np.where(np.isfinite(p), p, 1.0)
    order = np.argsort(p)
    ok = p[order] <= q * np.arange(1, len(p) + 1) / len(p)
    out = np.zeros(len(p), bool)
    if ok.any():
        out[order[:np.flatnonzero(ok).max() + 1]] = True
    return out


# ---------------------------------------------------------------- report

def _load(parts: Path):
    monthly = pd.concat([pd.read_parquet(p) for p in sorted(parts.rglob("monthly.parquet"))], axis=1)
    daily = pd.concat([pd.read_parquet(p) for p in sorted(parts.rglob("daily.parquet"))], axis=1)
    W = {}
    for p in sorted(parts.rglob("placebo.npz")):
        z = np.load(p, allow_pickle=False)
        W.update(zip(z["names"].tolist(), z["W"]))
    meta = [m for p in sorted(parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))]
    return monthly.sort_index(), daily.sort_index(), W, meta


def _fmt(d: dict, k: str, f: str) -> str:
    return f.format(d[k]) if d and k in d and d[k] is not None and np.isfinite(d[k]) else "-"


def cmd_report(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v20 runs on the whole sample: the unlock must be set")
    monthly, daily, W, meta = _load(args.parts)
    D = R14.PREP.load(args.inputs / "daily.pkl")
    cash, end = D["cash"], core.last_day()
    months = monthly.index
    cm = core.monthly(cash.reindex(daily.index).fillna(0.0).to_frame("c"))["c"]
    cm.index = cm.index.to_timestamp()
    cm = cm.reindex(months).fillna(0.0).to_numpy()
    reg = registry()
    stats = {f"{m['key']}|{m['ci']}": m for m in meta}
    errors = [m for m in meta if m["error"]]
    wf_index = daily.loc["2018-01-01":end].index
    lines = [f"# v20: small caps, a wide grid under realistic costs ({len(configs())} configurations, walk-forward "
             "2018-2026, pre-registered)", "",
             f"Configurations evaluated {len(meta) - len(errors)} of {len(configs())}; errors or skipped {len(errors)}. "
             f"{REPS} placebos each. R3 costs (middle) unless stated. Target: COMBO20 monthly Sortino 4.", "",
             "## 1. Families", "",
             "| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | gross | "
             "years placebo-ok | gate | PBO | best config (design Sortino, p) |", "|" + "---|" * 14]
    summary, streams, fam_info, mats = {}, {}, {}, {}
    for key, (_, cfgs) in reg.items():
        fam = R14.family_of(key)
        names = [f"{key}|{i}" for i in range(len(cfgs)) if f"{key}|{i}|mid" in monthly]
        if not names:
            continue
        M = monthly[[n + "|mid" for n in names]].to_numpy(float)
        A = neighbours_matrix([{"rule": key, **cfgs[int(n.split("|")[1])]} for n in names])
        mats[fam] = (M, A)
        picks = walk_forward(M, cm, A, months, end.year)
        pv, ok_years = {}, 0
        for y, (i, _) in picks.items():
            rows = window_rows(months, y)
            pl = W.get(names[i])
            if rows.sum() >= 12 and pl is not None:
                s_real = core.sortino_cols(M[rows, i][:, None], cm[rows])[0]
                pv[y] = float(np.mean(pl[:, WINDOWS.index(y)] >= s_real))
                ok_years += int(pv[y] <= 0.05)
        wf = pd.concat([daily[names[i]].loc[f"{y}-01-01":min(end, pd.Timestamp(f"{y}-12-31"))]
                        for y, (i, _) in picks.items()]).reindex(wf_index).fillna(0.0)
        streams[fam] = wf
        st = R14._stats(wf, cash, "2018-01-01", str(end.date()))
        h1, h2 = R14._stats(wf, cash, "2018-01-01", "2020-12-31"), R14._stats(wf, cash, "2021-01-01", str(end.date()))
        sc_s = {}
        for sc in ("low", "high", "gross"):
            m = pd.concat([monthly[f"{names[i]}|{sc}"].loc[f"{y}-01-01":f"{y}-12-31"] for y, (i, _) in picks.items()])
            rows = np.isin(months, m.index)
            sc_s[sc] = float(core.sortino_cols(m.reindex(months[rows]).to_numpy()[:, None], cm[rows])[0])
        gate = bool(st and st["sortino"] >= 1.0 and ok_years >= np.ceil(2 / 3 * len(picks)))
        pbo = cpcv(M, cm, A)
        design = core.sortino_cols(M, cm)
        b = int(np.nanargmax(design))
        p_best = float(np.mean(W[names[b]][:, 0] >= design[b])) if names[b] in W else np.nan
        fam_info[fam] = (names, picks, pv, M)
        summary[fam] = {"wf": st, "h1": h1, "h2": h2, "low": sc_s["low"], "high": sc_s["high"],
                        "gross": sc_s["gross"], "placebo_years": ok_years, "years": len(picks), "gate": gate,
                        "pbo": pbo, "best": names[b], "best_design": float(design[b]), "best_p": p_best,
                        "picks": {int(y): names[i] for y, (i, _) in picks.items()},
                        "pick_scores": {int(y): s for y, (_, s) in picks.items()}, "p_years": pv}
        lines.append(f"| {fam} | {_fmt(st, 'sortino', '{:.2f}')} | {_fmt(h1, 'sortino', '{:.2f}')} | "
                     f"{_fmt(h2, 'sortino', '{:.2f}')} | {_fmt(st, 'cagr', '{:.1%}')} | {_fmt(st, 'dd', '{:.1%}')} | "
                     f"{_fmt(st, 'total', '{:+.0%}')} | {sc_s['low']:.2f} | {sc_s['high']:.2f} | {sc_s['gross']:.2f} | "
                     f"{ok_years}/{len(picks)} | {'pass' if gate else 'fail'} | {_fmt(pbo, 'pbo', '{:.0%}')} | "
                     f"{names[b]} ({design[b]:.2f}, p {p_best:.2f}) |")
    # combination, as run_v14.cmd_report
    cal = daily.index
    pieces, members = [], {}
    for y in range(core.WF_YEARS[0], end.year + 1):
        chosen = {}
        for fam, (names, picks, pv, _) in fam_info.items():
            if y in picks and picks[y][1] >= 1.0 and np.isfinite(pv.get(y, np.nan)) and pv[y] <= 0.05:
                chosen[fam] = daily[names[picks[y][0]]]
        members[y] = sorted(chosen)
        span = cal[(cal >= pd.Timestamp(f"{y}-01-01")) & (cal <= min(end, pd.Timestamp(f"{y}-12-31")))]
        if not chosen:
            pieces.append(pd.Series(0.0, index=span))
            continue
        Mx = pd.DataFrame(chosen)
        w = R14._ivol(Mx.loc[:f"{y - 1}-12-31"])
        pieces.append((Mx.loc[span] * w).sum(axis=1))
    combo = pd.concat(pieces).reindex(wf_index).fillna(0.0)
    cs = R14._stats(combo, cash, "2018-01-01", str(end.date()))
    c1, c2 = R14._stats(combo, cash, "2018-01-01", "2020-12-31"), R14._stats(combo, cash, "2021-01-01", str(end.date()))
    seg = R14._stats(combo, cash, *SEGMENT)
    sh = np.array([m["sharpe"] for m in meta if m.get("sharpe") is not None], float)
    prior = R14._script("run_v10")._prior_pool()
    pool = np.concatenate([sh[np.isfinite(sh)], prior[np.isfinite(prior)]])
    gm, n = np.euler_gamma, len(pool)
    e_max = (1 - gm) * norm.ppf(1 - 1 / n) + gm * norm.ppf(1 - 1 / (n * np.e))
    x = combo.loc["2018-01-01":]
    sr = x.mean() / x.std() if x.std() > 0 else 0.0
    sr0 = pool.std() / np.sqrt(252) * e_max
    den = 1 - x.skew() * sr + (x.kurt() + 2) / 4 * sr ** 2
    dsr = float(norm.cdf((sr - sr0) * np.sqrt(len(x) - 1) / np.sqrt(den))) if den > 0 else np.nan
    cpbo = combo_pbo(mats, cm)
    ok = bool(cs and c1 and c2 and cs["sortino"] >= 4 and c1["sortino"] >= 3 and c2["sortino"] >= 3
              and np.isfinite(cpbo["pbo"]) and cpbo["pbo"] < 0.2 and seg.get("sortino", 0) >= 3)
    yearly = {int(y): float(v) for y, v in ((1 + combo).groupby(combo.index.year).prod() - 1).items()}
    lines += ["", "## 2. COMBO20 (families chosen each year on earlier data only)", "",
              "| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |",
              "|---|---|---|---|---|---|---|---|---|---|---|",
              f"| COMBO20 | {_fmt(cs, 'sortino', '{:.2f}')} | {_fmt(c1, 'sortino', '{:.2f}')} | "
              f"{_fmt(c2, 'sortino', '{:.2f}')} | {_fmt(cs, 'cagr', '{:.1%}')} | {_fmt(cs, 'dd', '{:.1%}')} | "
              f"{_fmt(cs, 'total', '{:+.0%}')} | {_fmt(seg, 'sortino', '{:.2f}')} | {dsr:.2f} | "
              f"{_fmt(cpbo, 'pbo', '{:.0%}')} | {'met' if ok else 'not met'} |", "",
              "Members by year: " + "; ".join(f"{y}: {', '.join(m) or 'none'}" for y, m in members.items()), "",
              "COMBO20 by year: " + ", ".join(f"{y} {v:+.1%}" for y, v in yearly.items())]
    # the 2023-07+ segment of each family
    lines += ["", "## 3. The 2023-07+ segment", "", "| family | Sortino | CAGR | max DD |", "|---|---|---|---|"]
    for fam, s in streams.items():
        st = R14._stats(s, cash, *SEGMENT)
        lines.append(f"| {fam} | {_fmt(st, 'sortino', '{:.2f}')} | {_fmt(st, 'cagr', '{:.1%}')} | "
                     f"{_fmt(st, 'dd', '{:.1%}')} |")
    # trades
    n_months = len(pd.period_range("2018-01", end.strftime("%Y-%m"), freq="M"))
    lines += ["", "## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)", "",
              "| family | trades a month | mean net return a trade | win rate | worst trade |", "|---|---|---|---|---|"]
    lines += [R19._trades_line(fam, info["picks"], stats, n_months) for fam, info in summary.items()]
    # false discovery rate over every configuration
    allnames = [n for names, *_ in fam_info.values() for n in names if n in W]
    Mall = np.column_stack([monthly[n + "|mid"].to_numpy(float) for n in allnames])
    s_all = core.sortino_cols(Mall, cm)
    PL = np.stack([W[n][:, 0] for n in allnames], axis=1)
    p_emp = (1 + (PL >= s_all).sum(axis=0)) / (1 + PL.shape[0])
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (s_all - np.nanmean(PL, axis=0)) / np.nanstd(PL, axis=0, ddof=1)
    p_z = norm.sf(z)
    rej_e, rej_z = bh(p_emp), bh(p_z)
    lines += ["", "## 5. False discovery rate over all configurations (Benjamini-Hochberg, q = 5%)", "",
              f"Whole-period Sortino of each configuration against its {REPS} placebos; p empirical (rank) and p from "
              f"the placebos' normal z-score. {int(rej_e.sum())} of {len(allnames)} configurations survive with the "
              f"empirical p, {int(rej_z.sum())} with the z-score p.", "",
              "| family | configurations | survive (empirical) | survive (z) | best three by z (Sortino, z) |",
              "|---|---|---|---|---|"]
    fam_of = np.array([R14.family_of(n.split("|")[0]) for n in allnames])
    fdr = {}
    for fam in fam_info:
        f = fam_of == fam
        idx = np.flatnonzero(f & rej_z)
        top = idx[np.argsort(-z[idx])][:3]
        fdr[fam] = {"n": int(f.sum()), "emp": int((f & rej_e).sum()), "z": int((f & rej_z).sum()),
                    "top": [allnames[i] for i in top]}
        txt = "; ".join(f"{allnames[i]} ({s_all[i]:.2f}, {z[i]:.1f})" for i in top) or "-"
        lines.append(f"| {fam} | {int(f.sum())} | {fdr[fam]['emp']} | {fdr[fam]['z']} | {txt} |")
    # entry and exit choices
    rows18 = np.asarray(months >= pd.Timestamp("2018-01-01"))
    sort18 = pd.Series(core.sortino_cols(Mall[rows18], cm[rows18]), index=allnames)
    lines += ["", "## 6. Entry and exit choices", "",
              "Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in "
              "brackets the walk-forward years that picked it.", "", "| family | dimension | value median (years) |",
              "|---|---|---|"]
    for fam, info in summary.items():
        keys = [k for k in reg if R14.family_of(k) == fam]
        lines += _choices(fam, keys, sort18, info["picks"], reg)
    lines += ["", "## 7. Latest pick of each family", ""]
    for fam, info in summary.items():
        if info["picks"]:
            y, name = max(info["picks"].items())
            k, ci = name.split("|")
            lines.append(f"- {fam} {y}: {name} = {reg[k][1][int(ci)]}")
    if errors:
        lines += ["", f"Errors or skipped: {len(errors)}, first: {errors[0]}"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps(
        {"families": summary, "combo": cs, "combo_h1": c1, "combo_h2": c2, "combo_segment": seg, "dsr": dsr,
         "combo_pbo": cpbo, "criterion": ok, "members": members, "combo_yearly": yearly, "fdr": fdr,
         "fdr_total": {"configs": len(allnames), "emp": int(rej_e.sum()), "z": int(rej_z.sum())}},
        indent=1, default=float), encoding="utf-8")
    pd.DataFrame({**streams, "COMBO": combo}).astype(np.float32).to_parquet(args.out / "streams.parquet")
    print("\n".join(lines), flush=True)
    return 0


def _choices(fam: str, keys: list[str], sortino: pd.Series, picks: dict, reg: dict) -> list[str]:
    rows = []
    for key in keys:
        cfgs = reg[key][1]
        for dim in cfgs[0]:
            parts = []
            for val in dict.fromkeys(c[dim] for c in cfgs):
                ids = [f"{key}|{i}" for i, c in enumerate(cfgs) if c[dim] == val]
                med = float(np.nanmedian(sortino.reindex(ids))) if ids else np.nan
                parts.append(f"{val} {med:.2f} ({sum(1 for p in picks.values() if p in ids)})")
            rows.append(f"| {fam} | {dim} | {' / '.join(parts)} |")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, default=SHARDS)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--minutes", type=float, default=320.0, help="start no configuration after this many minutes")
    s.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v20/report"))
    args = ap.parse_args()
    return {"shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
