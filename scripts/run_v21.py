"""v21 calibration, shards and report. Pre-registered in docs/research/V21_PREREGISTRATION.md.

  calibrate  R4 half-spreads by price tier and leg time (the open, during the session, the last minute) from every
             quote measured so far (v17 and v19q quote studies); a cell with fewer than 200 legs keeps R3's value
  shard      every configuration under R4: monthly returns at half-spreads x0.5, x1 and x2 (borrow x3) and gross,
             daily middle-cost returns, trade statistics, and 200 placebos summarised by the placebo p-value of each
             walk-forward window and the placebos' whole-period mean, deviation and count above the real Sortino
  report     v20's vectorised v14 procedure (COMBO21), the false discovery rate over every configuration, and the
             tables of v20
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import norm

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v21_grid as v21


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R20 = _script("run_v20")
R19, R16, R14 = R20.R19, R20.R16, R20.R14
SHARDS, REPS, SLIP = 600, 200, 0.25
SEGMENT = R20.SEGMENT
WINDOWS = R20.WINDOWS
TIERS = (0, 2, 5, 10, np.inf)


def registry() -> dict[str, tuple[str, list[dict]]]:
    out = {k: ("intra", core.grid(d)) for k, d in v21.INTRA_DIMS.items()}
    out.update({k: ("daily", core.grid(d)) for k, d in v21.DAILY_DIMS.items()})
    return out


def configs() -> list[tuple[str, int]]:
    return [(k, i) for k, (_, cfgs) in registry().items() for i in range(len(cfgs))]


def r4_half() -> np.ndarray:
    raw = os.environ.get("V21_SPREADS", "")
    return np.array(json.loads(raw), float) if raw.strip().startswith("[") else v19.R4_HALF.copy()


# ---------------------------------------------------------------- calibrate

def cmd_calibrate(args) -> int:
    legs = []
    q19, q17 = args.q19, args.q17
    if (q19 / "spreads.parquet").exists():
        t = pd.read_parquet(q19 / "trades.parquet")
        legs += [t[["entry_date", "symbol", "entry_min", "price"]].set_axis(["date", "symbol", "minute", "price"], axis=1),
                 t[["exit_date", "symbol", "exit_min", "price"]].set_axis(["date", "symbol", "minute", "price"], axis=1)]
        sp19 = pd.read_parquet(q19 / "spreads.parquet")
    else:
        sp19 = None
    if (q17 / "spreads.parquet").exists():
        t = pd.read_parquet(q17 / "trades.parquet")
        legs += [t[["date", "symbol", "minute", "price"]],
                 t[["date", "symbol", "exit_minute", "price"]].rename(columns={"exit_minute": "minute"})]
        sp17 = pd.read_parquet(q17 / "spreads.parquet")
    else:
        sp17 = None
    sp = pd.concat([x for x in (sp19, sp17) if x is not None], ignore_index=True) if legs else None
    half = v19.R4_HALF.copy()
    rows = []
    if sp is not None:
        sp = sp.drop_duplicates(["date", "symbol", "minute"]).assign(half=lambda x: x["spread"] / 2)
        lg = pd.concat(legs, ignore_index=True).drop_duplicates(["date", "symbol", "minute"])
        lg["date"] = lg["date"].astype(str)
        sp["date"] = sp["date"].astype(str)
        lg = lg.merge(sp[["date", "symbol", "minute", "half"]], on=["date", "symbol", "minute"], how="inner").dropna()
        lg["tier"] = np.searchsorted(TIERS[1:-1], lg["price"].to_numpy(float), side="right")
        lg["leg"] = np.where(lg["minute"] == 0, 0, np.where(lg["minute"] >= 385, 2, 1))
        for (ti, le), x in lg.groupby(["tier", "leg"])["half"]:
            w = x.clip(upper=x.quantile(0.99)).mean()
            rows.append((int(ti), int(le), len(x), float(w)))
            if len(x) >= 200:
                half[int(ti), int(le)] = w
    print(json.dumps({"cells": rows}), flush=True)
    print("R4 half-spreads (rows <2, 2-5, 5-10, 10-20; columns open, session, close):", flush=True)
    print(np.round(half * 100, 3), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "spreads.json").write_text(json.dumps(half.round(6).tolist()), encoding="utf-8")
    (args.out / "cells.json").write_text(json.dumps(rows), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- shard

_G: dict = {"pools": {}}


def _books(key: str, g: dict):
    kind = registry()[key][0]
    D, store = R14._G["D"], R14._G["store"]
    table, E = R16._W["table"], R16._W["E"]
    if kind == "intra":
        trades = v21.intraday_trades(store, D, key, g)
        return trades, lambda sp, fm, gr: v19.intra_book(trades, D["dates"], table, sp, fm, gr)
    specs = v21.daily_specs(D, E, key, g)
    return specs, lambda sp, fm, gr: v19.daily_book(D, specs, table, sp, fm, gr)


def _design(s: pd.Series) -> pd.Series:
    return s.loc[core.DESIGN_START:core.last_day()]


def evaluate(key: str, ci: int, half: np.ndarray) -> tuple:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    D, store, table = R14._G["D"], R14._G["store"], R16._W["table"]
    dates = D["dates"]
    v19.set_costs("r4", SLIP, half)
    trades, book = _books(key, g)
    real, stats = {}, {"signals": len(trades)}
    for sc, spread, fee in R19.SCENARIOS:
        s, paths, taken = book(spread, fee, False)
        real[sc] = s
        if sc == "mid":
            stats.update(v19.trade_stats(paths, taken, dates))
    v19.set_costs("r4", 0.0, half)  # the gross record has no costs at all, slippage included
    try:
        real["gross"] = _books(key, g)[1](0.0, 1.0, True)[0]
    finally:
        v19.set_costs("r4", SLIP, half)
    daily = {k: _design(v) for k, v in real.items()}
    monthly = {k: core.monthly(v.to_frame("r"))["r"] for k, v in daily.items()}
    mid = daily["mid"]
    stats["sharpe"] = float(mid.mean() / mid.std() * np.sqrt(252)) if mid.std() > 0 else None
    months = monthly["mid"].index
    if "cm" not in _G:
        _G["cm"] = core.monthly(D["cash"].reindex(mid.index).fillna(0.0).to_frame("c"))["c"].reindex(months).to_numpy()
    cm = _G["cm"]
    PM = np.zeros((len(months), REPS))
    for r in range(REPS):
        rng = np.random.default_rng(R14._seed(key, ci, r + 1))
        if kind == "intra":
            pk = (key, g["band"])
            if pk not in _G["pools"]:
                _G["pools"][pk] = v21.pool_by_day(store, key, g["band"])
            s = v19.intra_book(v21.intraday_placebo(store, D, trades, rng, _G["pools"][pk]), dates, table, 1.0)[0]
        else:
            s = v19.daily_book(D, v21.daily_placebo(D, trades, rng, g.get("band")), table, 1.0)[0]
        PM[:, r] = core.monthly(_design(s).to_frame("r"))["r"].reindex(months).fillna(0.0).to_numpy()
    ts = months.to_timestamp()
    rm = monthly["mid"].to_numpy()
    P = np.full(len(WINDOWS), np.nan, np.float32)
    for k, w in enumerate(WINDOWS):
        rows = R20.window_rows(ts, w)
        if rows.sum() >= 12:
            s_real = core.sortino_cols(rm[rows][:, None], cm[rows])[0]
            P[k] = np.mean(core.sortino_cols(PM[rows], cm[rows]) >= s_real)
    pl = core.sortino_cols(PM, cm)
    s_all = core.sortino_cols(rm[:, None], cm)[0]
    Z = np.array([np.nanmean(pl), np.nanstd(pl, ddof=1), float((pl >= s_all).sum())], np.float32)
    return monthly, mid, P, Z, stats


def _work(u):
    key, ci, half = u
    t0 = time.time()
    try:
        return key, ci, evaluate(key, ci, half), time.time() - t0, None
    except Exception as exc:  # recorded and reported
        return key, ci, None, time.time() - t0, f"{type(exc).__name__}: {exc}"


def cmd_shard(args) -> int:
    global REPS
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v21 runs on the whole sample: the unlock must be set")
    t0 = time.time()
    R19.load(args.inputs)
    v21.set_regime(R14._G["X"], R14._G["D"]["dates"])
    half = r4_half()
    print("R4 half-spreads:", np.round(half * 100, 3).tolist(), flush=True)
    mine = [(k, i, half) for k, i in configs()[args.shard::args.shards]]
    if args.canary:  # the first and the last configuration of every family, with 5 placebos, on the real inputs
        REPS = 5
        mine = [(k, i, half) for k, (_, cfgs) in registry().items() for i in sorted({0, len(cfgs) - 1})]
    print(f"shard {args.shard}: {len(mine)} configurations", flush=True)
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            res = list(pool.imap_unordered(_work, mine, chunksize=1))
    else:
        res = [_work(u) for u in mine]
    mid_cols, other_cols, dcols, names, Ps, Zs, meta = {}, {}, {}, [], [], [], []
    for key, ci, out, sec, err in res:
        name = f"{key}|{ci}"
        st = {}
        if out is not None:
            monthly, mid, P, Z, st = out
            mid_cols[name] = monthly["mid"].astype(np.float32)
            for sc in ("low", "high", "gross"):
                other_cols[f"{name}|{sc}"] = monthly[sc].astype(np.float32)
            dcols[name] = mid.astype(np.float32)
            names.append(name)
            Ps.append(P)
            Zs.append(Z)
        meta.append({"key": key, "ci": ci, "sec": round(sec, 1), "error": err, **st})
    args.out.mkdir(parents=True, exist_ok=True)
    if mid_cols:
        for nm, cols in (("monthly_mid", mid_cols), ("monthly_other", other_cols)):
            m = pd.DataFrame(cols)
            m.index = m.index.to_timestamp()
            m.to_parquet(args.out / f"{nm}.parquet")
        pd.DataFrame(dcols).to_parquet(args.out / "daily.parquet")
        np.savez_compressed(args.out / "pstats.npz", names=np.array(names), P=np.stack(Ps), Z=np.stack(Zs))
    (args.out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    errs = [x for x in meta if x["error"]]
    print(f"shard done in {time.time() - t0:.0f}s: {len(res)} configurations, {len(errs)} errors", flush=True)
    for e in errs[:5]:
        print("error:", e, flush=True)
    if args.canary:
        for m in meta:
            print(f"canary {m['key']}|{m['ci']}: {m['sec']}s, {m.get('signals')} signals, error {m['error']}", flush=True)
        return 1 if errs else 0
    return 0


# ---------------------------------------------------------------- report

class Lazy:
    """Columns of many parquet files, read on demand."""

    def __init__(self, files: list[Path]):
        self.where = {}
        for f in files:
            for c in pq.read_schema(f).names:
                if c != "__index_level_0__":
                    self.where[c] = f

    def __contains__(self, c: str) -> bool:
        return c in self.where

    def get(self, cols: list[str]) -> pd.DataFrame:
        by: dict = {}
        for c in cols:
            by.setdefault(self.where[c], []).append(c)
        return pd.concat([pd.read_parquet(f, columns=cs) for f, cs in by.items()], axis=1)[cols]


def cmd_report(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v21 runs on the whole sample: the unlock must be set")
    parts = args.parts
    monthly = pd.concat([pd.read_parquet(p) for p in sorted(parts.rglob("monthly_mid.parquet"))], axis=1).sort_index()
    other = Lazy(sorted(parts.rglob("monthly_other.parquet")))
    daily_l = Lazy(sorted(parts.rglob("daily.parquet")))
    PS, ZS = {}, {}
    for p in sorted(parts.rglob("pstats.npz")):
        z = np.load(p, allow_pickle=False)
        PS.update(zip(z["names"].tolist(), z["P"]))
        ZS.update(zip(z["names"].tolist(), z["Z"]))
    meta = [m for p in sorted(parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))]
    D = R14.PREP.load(args.inputs / "daily.pkl")
    cash, end = D["cash"], core.last_day()
    months = monthly.index
    cal = D["dates"][(D["dates"] >= core.DESIGN_START) & (D["dates"] <= end)]
    cm = core.monthly(cash.reindex(cal).fillna(0.0).to_frame("c"))["c"]
    cm.index = cm.index.to_timestamp()
    cm = cm.reindex(months).fillna(0.0).to_numpy()
    reg = registry()
    stats = {f"{m['key']}|{m['ci']}": m for m in meta}
    errors = [m for m in meta if m["error"]]
    wf_index = cal[cal >= pd.Timestamp("2018-01-01")]
    half = r4_half()
    lines = [f"# v21: small caps, a five-times-larger grid with new ideas under realistic costs ({len(configs())} "
             "configurations, walk-forward 2018-2026, pre-registered)", "",
             f"Configurations evaluated {len(meta) - len(errors)} of {len(configs())}; errors {len(errors)}. {REPS} "
             "placebos each. R4 costs (middle) unless stated. Target: COMBO21 monthly Sortino 4.", "",
             "R4 half-spreads (open / session / last minute): " + "; ".join(
                 f"{t} {half[i, 0]:.2%} / {half[i, 1]:.2%} / {half[i, 2]:.2%}"
                 for i, t in enumerate(("<$2", "$2-5", "$5-10", "$10-20"))), "",
             "## 1. Families", "",
             "| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | gross | "
             "years placebo-ok | gate | PBO | best config (design Sortino, p) |", "|" + "---|" * 14]
    summary, streams, fam_info, mats, picked = {}, {}, {}, {}, {}
    fmt = R20._fmt
    for key, (_, cfgs) in reg.items():
        fam = R14.family_of(key)
        names = [f"{key}|{i}" for i in range(len(cfgs)) if f"{key}|{i}" in monthly]
        if not names:
            continue
        M = monthly[names].to_numpy(float)
        A = R20.neighbours_matrix([{"rule": key, **cfgs[int(n.split("|")[1])]} for n in names])
        mats[fam] = (M, A)
        picks = R20.walk_forward(M, cm, A, months, end.year)
        need = sorted({names[i] for i, _ in picks.values()})
        dd = daily_l.get(need)
        pv, ok_years = {}, 0
        for y, (i, _) in picks.items():
            p = PS.get(names[i])
            if p is not None and np.isfinite(p[WINDOWS.index(y)]):
                pv[y] = float(p[WINDOWS.index(y)])
                ok_years += int(pv[y] <= 0.05)
        wf = pd.concat([dd[names[i]].loc[f"{y}-01-01":min(end, pd.Timestamp(f"{y}-12-31"))]
                        for y, (i, _) in picks.items()]).reindex(wf_index).fillna(0.0)
        streams[fam] = wf
        st = R14._stats(wf, cash, "2018-01-01", str(end.date()))
        h1, h2 = R14._stats(wf, cash, "2018-01-01", "2020-12-31"), R14._stats(wf, cash, "2021-01-01", str(end.date()))
        oo = other.get([f"{n}|{sc}" for n in need for sc in ("low", "high", "gross")])
        sc_s = {}
        for sc in ("low", "high", "gross"):
            m = pd.concat([oo[f"{names[i]}|{sc}"].loc[f"{y}-01-01":f"{y}-12-31"] for y, (i, _) in picks.items()])
            rows = np.isin(months, m.index)
            sc_s[sc] = float(core.sortino_cols(m.reindex(months[rows]).to_numpy()[:, None], cm[rows])[0])
        gate = bool(st and st["sortino"] >= 1.0 and ok_years >= np.ceil(2 / 3 * len(picks)))
        pbo = R20.cpcv(M, cm, A)
        design = core.sortino_cols(M, cm)
        b = int(np.nanargmax(design))
        p_best = float(PS[names[b]][0]) if names[b] in PS else np.nan
        fam_info[fam] = (names, picks, pv)
        picked[fam] = dd
        summary[fam] = {"wf": st, "h1": h1, "h2": h2, "low": sc_s["low"], "high": sc_s["high"],
                        "gross": sc_s["gross"], "placebo_years": ok_years, "years": len(picks), "gate": gate,
                        "pbo": pbo, "best": names[b], "best_design": float(design[b]), "best_p": p_best,
                        "picks": {int(y): names[i] for y, (i, _) in picks.items()},
                        "pick_scores": {int(y): s for y, (_, s) in picks.items()}, "p_years": pv}
        lines.append(f"| {fam} | {fmt(st, 'sortino', '{:.2f}')} | {fmt(h1, 'sortino', '{:.2f}')} | "
                     f"{fmt(h2, 'sortino', '{:.2f}')} | {fmt(st, 'cagr', '{:.1%}')} | {fmt(st, 'dd', '{:.1%}')} | "
                     f"{fmt(st, 'total', '{:+.0%}')} | {sc_s['low']:.2f} | {sc_s['high']:.2f} | {sc_s['gross']:.2f} | "
                     f"{ok_years}/{len(picks)} | {'pass' if gate else 'fail'} | {fmt(pbo, 'pbo', '{:.0%}')} | "
                     f"{names[b]} ({design[b]:.2f}, p {p_best:.2f}) |")
    pieces, members = [], {}
    for y in range(core.WF_YEARS[0], end.year + 1):
        chosen = {}
        for fam, (names, picks, pv) in fam_info.items():
            if y in picks and picks[y][1] >= 1.0 and np.isfinite(pv.get(y, np.nan)) and pv[y] <= 0.05:
                chosen[fam] = picked[fam][names[picks[y][0]]]
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
    cpbo = R20.combo_pbo(mats, cm)
    ok = bool(cs and c1 and c2 and cs["sortino"] >= 4 and c1["sortino"] >= 3 and c2["sortino"] >= 3
              and np.isfinite(cpbo["pbo"]) and cpbo["pbo"] < 0.2 and seg.get("sortino", 0) >= 3)
    yearly = {int(y): float(v) for y, v in ((1 + combo).groupby(combo.index.year).prod() - 1).items()}
    lines += ["", "## 2. COMBO21 (families chosen each year on earlier data only)", "",
              "| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |",
              "|---|---|---|---|---|---|---|---|---|---|---|",
              f"| COMBO21 | {fmt(cs, 'sortino', '{:.2f}')} | {fmt(c1, 'sortino', '{:.2f}')} | "
              f"{fmt(c2, 'sortino', '{:.2f}')} | {fmt(cs, 'cagr', '{:.1%}')} | {fmt(cs, 'dd', '{:.1%}')} | "
              f"{fmt(cs, 'total', '{:+.0%}')} | {fmt(seg, 'sortino', '{:.2f}')} | {dsr:.2f} | "
              f"{fmt(cpbo, 'pbo', '{:.0%}')} | {'met' if ok else 'not met'} |", "",
              "Members by year: " + "; ".join(f"{y}: {', '.join(m) or 'none'}" for y, m in members.items()), "",
              "COMBO21 by year: " + ", ".join(f"{y} {v:+.1%}" for y, v in yearly.items())]
    lines += ["", "## 3. The 2023-07+ segment", "", "| family | Sortino | CAGR | max DD |", "|---|---|---|---|"]
    for fam, s in streams.items():
        st = R14._stats(s, cash, *SEGMENT)
        lines.append(f"| {fam} | {fmt(st, 'sortino', '{:.2f}')} | {fmt(st, 'cagr', '{:.1%}')} | {fmt(st, 'dd', '{:.1%}')} |")
    n_months = len(pd.period_range("2018-01", end.strftime("%Y-%m"), freq="M"))
    lines += ["", "## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)", "",
              "| family | trades a month | mean net return a trade | win rate | worst trade |", "|---|---|---|---|---|"]
    lines += [R19._trades_line(fam, info["picks"], stats, n_months) for fam, info in summary.items()]
    allnames = [n for names, *_ in fam_info.values() for n in names if n in ZS]
    s_all = core.sortino_cols(monthly[allnames].to_numpy(float), cm)
    Zm = np.stack([ZS[n] for n in allnames])
    p_emp = (1 + Zm[:, 2]) / (1 + REPS)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (s_all - Zm[:, 0]) / Zm[:, 1]
    p_z = norm.sf(z)
    rej_e, rej_z = R20.bh(p_emp), R20.bh(p_z)
    lines += ["", "## 5. False discovery rate over all configurations (Benjamini-Hochberg, q = 5%)", "",
              f"{int(rej_e.sum())} of {len(allnames)} configurations survive with the empirical p, {int(rej_z.sum())} "
              "with the placebos' z-score p.", "",
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
    rows18 = np.asarray(months >= pd.Timestamp("2018-01-01"))
    sort18 = pd.Series(core.sortino_cols(monthly[allnames].to_numpy(float)[rows18], cm[rows18]), index=allnames)
    lines += ["", "## 6. Entry and exit choices", "",
              "Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in "
              "brackets the walk-forward years that picked it.", "", "| family | dimension | value median (years) |",
              "|---|---|---|"]
    for fam, info in summary.items():
        keys = [k for k in reg if R14.family_of(k) == fam]
        lines += R20._choices(fam, keys, sort18, info["picks"], reg)
    lines += ["", "## 7. Latest pick of each family", ""]
    for fam, info in summary.items():
        if info["picks"]:
            y, name = max(info["picks"].items())
            k, ci = name.split("|")
            lines.append(f"- {fam} {y}: {name} = {reg[k][1][int(ci)]}")
    if errors:
        lines += ["", f"Errors: {len(errors)}, first: {errors[0]}"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps(
        {"families": summary, "combo": cs, "combo_h1": c1, "combo_h2": c2, "combo_segment": seg, "dsr": dsr,
         "combo_pbo": cpbo, "criterion": ok, "members": members, "combo_yearly": yearly, "fdr": fdr,
         "fdr_total": {"configs": len(allnames), "emp": int(rej_e.sum()), "z": int(rej_z.sum())},
         "r4_half": half.tolist()}, indent=1, default=float), encoding="utf-8")
    pd.DataFrame({**streams, "COMBO": combo}).astype(np.float32).to_parquet(args.out / "streams.parquet")
    print("\n".join(lines), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--q19", type=Path, default=Path("outputs/v19/quotes"))
    c.add_argument("--q17", type=Path, default=Path("outputs/v17/quotes"))
    c.add_argument("--out", type=Path, default=Path("outputs/v21/costs"))
    s = sub.add_parser("shard")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, default=SHARDS)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--canary", action="store_true")
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v21/report"))
    args = ap.parse_args()
    return {"calibrate": cmd_calibrate, "shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
