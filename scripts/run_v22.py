"""v22 shards, selection and report. Pre-registered in docs/research/V22_PREREGISTRATION.md.

  real     every configuration: monthly returns at R4 half-spreads x0.5, x1, x2 (borrow x3), with the open and close
           legs at the session's half-spread (auction orders), and gross; daily middle-cost returns; trades a month
  select   each family's walk-forward pick for each year among the configurations active enough before it (at
           least 50 trades and a trade in at least 40% of the months), and its best active configuration
  placebo  500 placebos of each selected configuration, 25 a unit (monthly returns)
  report   gate, COMBO22, CPCV PBO, Hansen's SPA test of each family against cash, deflated Sharpe, the 2023-07+
           segment, trades, entry and exit choices
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
from scipy.stats import norm

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v22_intra as vin
from aurora.research import v22_ta as ta


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R20 = _script("run_v20")
R19, R16, R14 = R20.R19, R20.R16, R20.R14
SHARDS, REPS, BLOCK, SLIP = 300, 500, 25, 0.25
MIN_TRADES, MIN_ACTIVE = 50, 0.40
TITLE, COMBO = "v22: technical analysis on small caps", "COMBO22"  # v23 reuses this runner with its own names
SEGMENT = R20.SEGMENT
WINDOWS = R20.WINDOWS
# R4 (v21's calibration on 27,782 measured quote legs): rows <$2, $2-5, $5-10, $10-20; columns open, session, close
R4 = np.array([[0.006633, 0.004728, 0.005763], [0.008026, 0.003602, 0.004782], [0.008188, 0.003977, 0.004642],
               [0.009853, 0.005096, 0.004473]])
AUCTION = np.repeat(R4[:, 1:2], 3, axis=1)  # open and close legs at the session's half-spread
SCEN = (("mid", R4, 1.0, 1.0, False), ("low", R4, 0.5, 1.0, False), ("high", R4, 2.0, 3.0, False),
        ("auction", AUCTION, 1.0, 1.0, False))  # the middle first: its net paths give the trade statistics


def registry() -> dict[str, tuple[str, list[dict]]]:
    out = {k: ("daily", core.grid(d)) for k, d in ta.DAILY_DIMS.items()}
    out.update({k: ("intra", core.grid(d)) for k, d in vin.INTRA_DIMS.items()})
    return out


def configs() -> list[tuple[str, int]]:
    return [(k, i) for k, (_, cfgs) in registry().items() for i in range(len(cfgs))]


def _design(s: pd.Series) -> pd.Series:
    return s.loc[core.DESIGN_START:core.last_day()]


def _month_counts(paths: list, taken: np.ndarray, dates: pd.DatetimeIndex) -> pd.Series:
    first = [p[0] for p, tk in zip(paths, taken) if tk]
    s = pd.Series(1.0, index=dates[first]) if first else pd.Series(dtype=float)
    return s.groupby(s.index.to_period("M")).sum() if len(s) else pd.Series(dtype=float)


def evaluate(key: str, ci: int, placebo_rng: np.random.Generator | None = None) -> tuple:
    """(daily returns by scenario, paths, taken) of a configuration, or of one placebo of it at the middle costs."""
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    D, store, table, E = R14._G["D"], R14._G["store"], R16._W["table"], R16._W["E"]
    dates = D["dates"]
    v19.set_costs("r4", SLIP, R4)
    if kind == "daily":
        sp, xm = ta.specs(D, E, key, g)
        if placebo_rng is not None:
            out, _, _ = ta.book(D, ta.placebo(D, sp, placebo_rng, g["band"]), xm, table, [SCEN[0]])
            return out["mid"], None, None
        out, paths, taken = ta.book(D, sp, xm, table, list(SCEN))
        v19.set_costs("r4", 0.0, R4)
        try:
            out["gross"] = ta.book(D, sp, xm, table, [("gross", R4, 0.0, 1.0, True)])[0]["gross"]
        finally:
            v19.set_costs("r4", SLIP, R4)
        return out, paths, taken
    trades = vin.intraday_trades(store, D, key, g)
    if placebo_rng is not None:
        pk = ("pool", key, g["scope"], g["band"])
        if pk not in _P:
            _P[pk] = vin.pool_by_day(store, g)
        pt = vin.intraday_placebo(store, D, key, g, trades, placebo_rng, _P[pk])
        return v19.intra_book(pt, dates, table, 1.0)[0], None, None
    out = {}
    for name, half, spread, fee, gross in SCEN:
        v19.set_costs("r4", SLIP, half)
        s, paths_, taken_ = v19.intra_book(trades, dates, table, spread, fee, gross)
        out[name] = s
        if name == "mid":
            paths, taken = paths_, taken_
    v19.set_costs("r4", 0.0, R4)
    try:
        out["gross"] = v19.intra_book(vin.intraday_trades(store, D, key, g), dates, table, 0.0, 1.0, True)[0]
    finally:
        v19.set_costs("r4", SLIP, R4)
    return out, paths, taken


_P: dict = {}


def _work(u):
    t0 = time.time()
    try:
        if len(u) == 2:
            key, ci = u
            out, paths, taken = evaluate(key, ci)
            dates = R14._G["D"]["dates"]
            st = {"signals": len(paths)}
            st.update(v19.trade_stats(paths, taken, dates))
            mid = _design(out["mid"])
            st["sharpe"] = float(mid.mean() / mid.std() * np.sqrt(252)) if mid.std() > 0 else None
            monthly = {k: core.monthly(_design(v).to_frame("r"))["r"] for k, v in out.items()}
            counts = _month_counts(paths, taken, dates).reindex(monthly["mid"].index).fillna(0.0)
            return u, (monthly, mid, counts), st, time.time() - t0, None
        key, ci, block = u
        res = {}
        for rep in range(block * BLOCK + 1, (block + 1) * BLOCK + 1):
            rng = np.random.default_rng(R14._seed(key, ci, rep))
            s, _, _ = evaluate(key, ci, rng)
            res[rep] = core.monthly(_design(s).to_frame("r"))["r"]
        return u, res, {}, time.time() - t0, None
    except Exception as exc:  # recorded and reported
        return u, None, {}, time.time() - t0, f"{type(exc).__name__}: {exc}"


def _run(units: list, args) -> list:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v22 runs on the whole sample: the unlock must be set")
    R19.load(args.inputs)
    print(f"shard {args.shard}: {len(units)} units", flush=True)
    if args.workers > 1 and os.name != "nt":
        chunk = max(1, len(units) // (args.workers * 4))  # neighbouring configurations share indicators
        with mp.get_context("fork").Pool(args.workers) as pool:
            return list(pool.imap_unordered(_work, units, chunksize=chunk))
    return [_work(u) for u in units]


def _slice(n: int, shard: int, shards: int) -> slice:
    size = -(-n // shards)
    return slice(shard * size, (shard + 1) * size)


def cmd_real(args) -> int:
    allc = configs()
    if args.canary:
        mine = [(k, i) for k, (_, cfgs) in registry().items() for i in sorted({0, len(cfgs) - 1})]
    else:
        mine = allc[_slice(len(allc), args.shard, args.shards)]
    res = _run(mine, args)
    mcols, dcols, ccols, meta = {}, {}, {}, []
    for (key, ci), out, st, sec, err in res:
        name = f"{key}|{ci}"
        if out is not None:
            monthly, mid, counts = out
            for sc, m in monthly.items():
                mcols[f"{name}|{sc}"] = m.astype(np.float32)
            dcols[name] = mid.astype(np.float32)
            ccols[name] = counts.astype(np.float32)
        meta.append({"key": key, "ci": ci, "sec": round(sec, 1), "error": err, **st})
    args.out.mkdir(parents=True, exist_ok=True)
    if mcols:
        for nm, cols in (("monthly", mcols), ("counts", ccols)):
            f = pd.DataFrame(cols)
            f.index = f.index.to_timestamp()
            f.to_parquet(args.out / f"{nm}.parquet")
        pd.DataFrame(dcols).to_parquet(args.out / "daily.parquet")
    (args.out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    errs = [m for m in meta if m["error"]]
    print(f"done: {len(res)} configurations, {len(errs)} errors", flush=True)
    for e in errs[:5]:
        print("error:", e, flush=True)
    if args.canary:
        for m in meta:
            print(f"canary {m['key']}|{m['ci']}: {m['sec']}s, {m.get('signals')} trades, error {m['error']}", flush=True)
        return 1 if errs else 0
    return 0


def cmd_placebo(args) -> int:
    names = [n for n in args.selected.split(",") if n]
    units = [(n.split("|")[0], int(n.split("|")[1]), b) for n in names for b in range(REPS // BLOCK)]
    res = _run(units[args.shard::args.shards], args)
    cols, meta = {}, []
    for (key, ci, b), out, _, sec, err in res:
        if out is not None:
            for rep, m in out.items():
                cols[f"{key}|{ci}|{rep}"] = m.astype(np.float32)
        meta.append({"key": key, "ci": ci, "block": b, "sec": round(sec, 1), "error": err})
    args.out.mkdir(parents=True, exist_ok=True)
    if cols:
        f = pd.DataFrame(cols)
        f.index = f.index.to_timestamp()
        f.to_parquet(args.out / "placebo.parquet")
    (args.out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"done: {len(res)} units, {sum(1 for m in meta if m['error'])} errors", flush=True)
    return 0


# ---------------------------------------------------------------- selection

def _cash_m(D: dict, months: pd.DatetimeIndex) -> np.ndarray:
    cal = D["dates"][(D["dates"] >= core.DESIGN_START) & (D["dates"] <= core.last_day())]
    cm = core.monthly(D["cash"].reindex(cal).fillna(0.0).to_frame("c"))["c"]
    cm.index = cm.index.to_timestamp()
    return cm.reindex(months).fillna(0.0).to_numpy()


def eligible(Cn: np.ndarray, rows: np.ndarray) -> np.ndarray:
    tr = Cn[rows]
    return (tr.sum(axis=0) >= MIN_TRADES) & ((tr > 0).mean(axis=0) >= MIN_ACTIVE)


def walk_forward(M: np.ndarray, Cn: np.ndarray, cm: np.ndarray, A, months: pd.DatetimeIndex, last_year: int) -> dict:
    """v14's plateau walk-forward among the configurations active enough on the data before each year."""
    picks = {}
    for y in range(core.WF_YEARS[0], last_year + 1):
        tr = R20.window_rows(months, y)
        if tr.sum() < 12:
            continue
        s = core.score(M[tr], cm[tr])
        s = np.where(eligible(Cn, tr), s, np.nan)
        s = R20.plateau(s, A)
        s = np.where(eligible(Cn, tr), s, np.nan)
        if not np.isfinite(s).any():
            continue
        i = int(np.nanargmax(s))
        picks[y] = (i, float(s[i]))
    return picks


def family_frames(monthly: pd.DataFrame, counts: pd.DataFrame, reg: dict) -> dict:
    out = {}
    for key, (_, cfgs) in reg.items():
        names = [f"{key}|{i}" for i in range(len(cfgs)) if f"{key}|{i}|mid" in monthly]
        if names:
            M = monthly[[n + "|mid" for n in names]].to_numpy(float)
            Cn = counts.reindex(columns=names).fillna(0.0).to_numpy(float)
            A = R20.neighbours_matrix([{"rule": key, **cfgs[int(n.split("|")[1])]} for n in names])
            out[R14.family_of(key)] = (key, names, M, Cn, A)
    return out


def _load_real(parts: Path) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    monthly = pd.concat([pd.read_parquet(p) for p in sorted(parts.rglob("monthly.parquet"))], axis=1).sort_index()
    counts = pd.concat([pd.read_parquet(p) for p in sorted(parts.rglob("counts.parquet"))], axis=1).sort_index()
    meta = [m for p in sorted(parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))
            if "block" not in m]
    return monthly, counts, meta


def choices(monthly: pd.DataFrame, counts: pd.DataFrame, D: dict) -> dict:
    months = monthly.index
    cm = _cash_m(D, months)
    out = {}
    for fam, (key, names, M, Cn, A) in family_frames(monthly, counts, registry()).items():
        picks = walk_forward(M, Cn, cm, A, months, core.last_day().year)
        design = np.where(eligible(Cn, np.ones(len(months), bool)), core.sortino_cols(M, cm), np.nan)
        best = names[int(np.nanargmax(design))] if np.isfinite(design).any() else None
        out[fam] = {"picks": {int(y): names[i] for y, (i, _) in picks.items()}, "best": best,
                    "scores": {int(y): s for y, (_, s) in picks.items()}}
    return out


def cmd_select(args) -> int:
    monthly, counts, meta = _load_real(args.parts)
    D = R14.PREP.load(args.inputs / "v14" / "daily.pkl")
    ch = choices(monthly, counts, D)
    names = sorted({n for c in ch.values() for n in [*c["picks"].values(), c["best"]] if n})
    real_dir = args.out / "real"
    real_dir.mkdir(parents=True, exist_ok=True)
    daily = _script("run_v21").Lazy(sorted(args.parts.rglob("daily.parquet")))
    daily.get(names).to_parquet(real_dir / "daily.parquet")  # the selected configurations' daily returns
    monthly.to_parquet(real_dir / "monthly.parquet")
    counts.to_parquet(real_dir / "counts.parquet")
    (real_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (args.out / "selected.json").write_text(json.dumps({"choices": ch, "names": names}, indent=1), encoding="utf-8")
    (args.out / "selected.txt").write_text(",".join(names), encoding="utf-8")
    errs = [m for m in meta if m["error"]]
    print(f"configurations {len(meta)} of {len(configs())}, errors {len(errs)}; selected {len(names)}", flush=True)
    return 0


# ---------------------------------------------------------------- report

def spa(X: np.ndarray, B: int = 1000, block: int = 6, seed: int = 0) -> tuple[float, int, float]:
    """Hansen's SPA test (consistent version, stationary bootstrap) of the best column of monthly excess returns
    ``X`` against zero: (p-value, best column, its t-statistic)."""
    n, _ = X.shape
    rng = np.random.default_rng(seed)
    idx = np.empty((B, n), int)
    for b in range(B):
        i = int(rng.integers(n))
        for t in range(n):
            if t and rng.random() < 1 / block:
                i = int(rng.integers(n))
            elif t:
                i = (i + 1) % n
            idx[b, t] = i
    counts = np.stack([np.bincount(r, minlength=n) for r in idx]).astype(float)
    mu = X.mean(axis=0)
    mb = counts @ X / n
    om = np.sqrt(n) * mb.std(axis=0, ddof=1)
    om = np.where(om > 0, om, np.nan)
    t = np.sqrt(n) * mu / om
    stat = max(np.nanmax(t), 0.0)
    mu_c = np.where(t <= -np.sqrt(2 * np.log(np.log(n))), mu, 0.0)
    tb = np.sqrt(n) * (mb - mu + mu_c) / om
    boot = np.maximum(np.nanmax(tb, axis=1), 0.0)
    best = int(np.nanargmax(t))
    return float(np.mean(boot >= stat)), best, float(t[best])


def cmd_report(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit("v22 runs on the whole sample: the unlock must be set")
    monthly, counts, meta = _load_real(args.parts)
    daily_l = _script("run_v21").Lazy(sorted(args.parts.rglob("daily.parquet")))
    plac = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.rglob("placebo.parquet"))], axis=1).sort_index()
    sel = json.loads(args.selected.read_text(encoding="utf-8"))
    D = R14.PREP.load(args.inputs / "daily.pkl")
    cash, end = D["cash"], core.last_day()
    months = monthly.index
    cm = _cash_m(D, months)
    reg = registry()
    stats = {f"{m['key']}|{m['ci']}": m for m in meta}
    errors = [m for m in meta if m["error"]]
    cal = D["dates"][(D["dates"] >= core.DESIGN_START) & (D["dates"] <= end)]
    wf_index = cal[cal >= pd.Timestamp("2018-01-01")]
    fmt = R20._fmt
    lines = [f"# {TITLE} ({len(configs())} configurations, walk-forward 2018-2026, pre-registered)", "",
             f"Configurations evaluated {len(meta) - len(errors)} of {len(configs())}; errors {len(errors)}. R4 costs "
             f"(middle) unless stated; {REPS} placebos for each selected configuration; a configuration can be picked "
             f"only with at least {MIN_TRADES} trades and a trade in {MIN_ACTIVE:.0%} of the months before. Target: "
             f"{COMBO} monthly Sortino 4.", "", "## 1. Families", "",
             "| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | low | high | auction | gross | "
             "years placebo-ok | gate | PBO | SPA p (best t) |", "|" + "---|" * 14]
    summary, streams, fam_info, mats = {}, {}, {}, {}
    for fam, (key, names, M, Cn, A) in family_frames(monthly, counts, reg).items():
        chf = sel["choices"].get(fam, {"picks": {}, "scores": {}})
        picks = {int(y): (names.index(n), float(chf["scores"][y])) for y, n in chf["picks"].items()}
        act = eligible(Cn, np.ones(len(months), bool))
        mats[fam] = (M[:, act], R20.neighbours_matrix([{"rule": key, **reg[key][1][int(n.split("|")[1])]}
                                                       for n, a in zip(names, act) if a])) if act.sum() else None
        if not picks:
            continue
        need = sorted({names[i] for i, _ in picks.values()})
        dd = daily_l.get(need)
        pv, ok_years = {}, 0
        for y, (i, _) in picks.items():
            rows = R20.window_rows(months, y)
            pl = plac[[c for c in plac.columns if c.startswith(names[i] + "|")]].reindex(months).fillna(0.0)
            if rows.sum() >= 12 and pl.shape[1]:
                s_real = core.sortino_cols(M[rows, i][:, None], cm[rows])[0]
                pv[y] = float(np.mean(core.sortino_cols(pl.to_numpy()[rows], cm[rows]) >= s_real))
                ok_years += int(pv[y] <= 0.05)
        wf = pd.concat([dd[names[i]].loc[f"{y}-01-01":min(end, pd.Timestamp(f"{y}-12-31"))]
                        for y, (i, _) in picks.items()]).reindex(wf_index).fillna(0.0)
        streams[fam] = wf
        st = R14._stats(wf, cash, "2018-01-01", str(end.date()))
        h1, h2 = R14._stats(wf, cash, "2018-01-01", "2020-12-31"), R14._stats(wf, cash, "2021-01-01", str(end.date()))
        sc_s = {}
        for sc in ("low", "high", "auction", "gross"):
            m = pd.concat([monthly[f"{names[i]}|{sc}"].loc[f"{y}-01-01":f"{y}-12-31"] for y, (i, _) in picks.items()])
            rows = np.isin(months, m.index)
            sc_s[sc] = float(core.sortino_cols(m.reindex(months[rows]).to_numpy()[:, None], cm[rows])[0])
        gate = bool(st and st["sortino"] >= 1.0 and ok_years >= np.ceil(2 / 3 * len(picks)))
        Ma, Aa = mats[fam] if mats[fam] else (M, A)
        pbo = R20.cpcv(Ma, cm, Aa)
        sp_p, sp_i, sp_t = spa(Ma - cm[:, None]) if Ma.shape[1] else (np.nan, 0, np.nan)
        fam_info[fam] = (names, picks, pv, dd)
        summary[fam] = {"wf": st, "h1": h1, "h2": h2, **sc_s, "placebo_years": ok_years, "years": len(picks),
                        "gate": gate, "pbo": pbo, "spa_p": sp_p, "spa_t": sp_t,
                        "picks": {int(y): names[i] for y, (i, _) in picks.items()}, "p_years": pv,
                        "active_configs": int(act.sum())}
        lines.append(f"| {fam} | {fmt(st, 'sortino', '{:.2f}')} | {fmt(h1, 'sortino', '{:.2f}')} | "
                     f"{fmt(h2, 'sortino', '{:.2f}')} | {fmt(st, 'cagr', '{:.1%}')} | {fmt(st, 'dd', '{:.1%}')} | "
                     f"{sc_s['low']:.2f} | {sc_s['high']:.2f} | {sc_s['auction']:.2f} | {sc_s['gross']:.2f} | "
                     f"{ok_years}/{len(picks)} | {'pass' if gate else 'fail'} | {fmt(pbo, 'pbo', '{:.0%}')} | "
                     f"{sp_p:.3f} ({sp_t:.1f}) |")
    pieces, members = [], {}
    for y in range(core.WF_YEARS[0], end.year + 1):
        chosen = {}
        for fam, (names, picks, pv, dd) in fam_info.items():
            if y in picks and picks[y][1] >= 1.0 and np.isfinite(pv.get(y, np.nan)) and pv[y] <= 0.05:
                chosen[fam] = dd[names[picks[y][0]]]
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
    cpbo = R20.combo_pbo({f: v for f, v in mats.items() if v}, cm)
    ok = bool(cs and c1 and c2 and cs["sortino"] >= 4 and c1["sortino"] >= 3 and c2["sortino"] >= 3
              and np.isfinite(cpbo["pbo"]) and cpbo["pbo"] < 0.2 and seg.get("sortino", 0) >= 3)
    yearly = {int(y): float(v) for y, v in ((1 + combo).groupby(combo.index.year).prod() - 1).items()}
    lines += ["", f"## 2. {COMBO} (families chosen each year on earlier data only)", "",
              "| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |",
              "|---|---|---|---|---|---|---|---|---|---|---|",
              f"| {COMBO} | {fmt(cs, 'sortino', '{:.2f}')} | {fmt(c1, 'sortino', '{:.2f}')} | "
              f"{fmt(c2, 'sortino', '{:.2f}')} | {fmt(cs, 'cagr', '{:.1%}')} | {fmt(cs, 'dd', '{:.1%}')} | "
              f"{fmt(cs, 'total', '{:+.0%}')} | {fmt(seg, 'sortino', '{:.2f}')} | {dsr:.2f} | "
              f"{fmt(cpbo, 'pbo', '{:.0%}')} | {'met' if ok else 'not met'} |", "",
              "Members by year: " + "; ".join(f"{y}: {', '.join(m) or 'none'}" for y, m in members.items()), "",
              f"{COMBO} by year: " + ", ".join(f"{y} {v:+.1%}" for y, v in yearly.items())]
    lines += ["", "## 3. The 2023-07+ segment", "", "| family | Sortino | CAGR | max DD |", "|---|---|---|---|"]
    for fam, s in streams.items():
        st = R14._stats(s, cash, *SEGMENT)
        lines.append(f"| {fam} | {fmt(st, 'sortino', '{:.2f}')} | {fmt(st, 'cagr', '{:.1%}')} | {fmt(st, 'dd', '{:.1%}')} |")
    n_months = len(pd.period_range("2018-01", end.strftime("%Y-%m"), freq="M"))
    lines += ["", "## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)", "",
              "| family | trades a month | mean net return a trade | win rate | worst trade |", "|---|---|---|---|---|"]
    lines += [R19._trades_line(fam, info["picks"], stats, n_months) for fam, info in summary.items()]
    allnames = list(monthly.columns[monthly.columns.str.endswith("|mid")].str[:-4])
    rows18 = np.asarray(months >= pd.Timestamp("2018-01-01"))
    sort18 = pd.Series(core.sortino_cols(monthly[[n + "|mid" for n in allnames]].to_numpy(float)[rows18], cm[rows18]),
                       index=allnames)
    lines += ["", "## 5. Entry and exit choices", "",
              "Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in "
              "brackets the walk-forward years that picked it.", "", "| family | dimension | value median (years) |",
              "|---|---|---|"]
    for fam, info in summary.items():
        keys = [k for k in reg if R14.family_of(k) == fam]
        lines += R20._choices(fam, keys, sort18, info["picks"], reg)
    lines += ["", "## 6. Latest pick of each family", ""]
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
         "combo_pbo": cpbo, "criterion": ok, "members": members, "combo_yearly": yearly}, indent=1, default=float),
        encoding="utf-8")
    pd.DataFrame({**streams, "COMBO": combo}).astype(np.float32).to_parquet(args.out / "streams.parquet")
    print("\n".join(lines), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("real", "placebo"):
        s = sub.add_parser(name)
        s.add_argument("--shard", type=int, default=0)
        s.add_argument("--shards", type=int, default=SHARDS)
        s.add_argument("--workers", type=int, default=4)
        s.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        s.add_argument("--out", type=Path, required=True)
        if name == "real":
            s.add_argument("--canary", action="store_true")
        else:
            s.add_argument("--selected", required=True)
    s = sub.add_parser("select")
    s.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    s.add_argument("--parts", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--selected", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v22/report"))
    args = ap.parse_args()
    return {"real": cmd_real, "placebo": cmd_placebo, "select": cmd_select, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
