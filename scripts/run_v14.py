"""v14 shards and report. Pre-registered in docs/research/V14_PREREGISTRATION.md.

  shard   one slice of (configuration, placebo block): the real daily returns in three cost scenarios (block 0) and
          the monthly returns of 25 placebo runs (each block)
  report  family walk-forward, gates, combination, CPCV/PBO, deflated Sharpe -> REPORT.md and summary.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from aurora.research import v11
from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v14_macro as vm
from aurora.research import v14_swing as vs

REPS, BLOCK = 200, 25
N_BLOCKS = REPS // BLOCK
SHARDS = 300


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREP = _script("run_v14_prepare")


def registry() -> dict[str, tuple[str, list[dict]]]:
    out = {}
    for k, dims in vi.A_DIMS.items():
        out[k] = ("intra", core.grid(dims))
    for k, dims in vi.INDEX_DIMS.items():
        out[k] = ("index", core.grid(dims))
    for k, dims in vs.SWING_DIMS.items():
        out[k] = ("swing", core.grid(dims))
    for k, dims in vm.MACRO_DIMS.items():
        out[k] = ("macro", core.grid(dims))
    return out


def family_of(key: str) -> str:
    return key.split("_")[0]


def units() -> list[tuple[str, int, int]]:
    return [(k, i, b) for k, (_, cfgs) in registry().items() for i in range(len(cfgs)) for b in range(N_BLOCKS)]


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


# ---------------------------------------------------------------- inputs (shared by forked workers)

_G: dict = {}


def load_inputs(inputs: Path) -> None:
    D = PREP.load(inputs / "daily.pkl")
    end = core.last_day()
    keep = D["dates"] <= end
    if not keep.all():
        raise SystemExit("inputs reach past the allowed last day")
    cands = pd.read_parquet(inputs / "cands.parquet")
    arr = np.load(inputs / "store.npz")
    store = vi.Store(cands, {k: arr[k] for k in vi.FIELDS})
    idx = PREP.load(inputs / "index.pkl")
    by_inst = {s: {d: (pc, tuple(a[f] for f in vi.FIELDS)) for d, pc, a in rows} for s, rows in idx.items()}
    _G.update(D=D, store=store, index=by_inst, X=PREP.load(inputs / "etf.pkl"), Y=PREP.load(inputs / "crypto.pkl"))
    _G["pools"] = {}


def _design(r: pd.Series) -> pd.Series:
    start = core.CRYPTO_START if r.index.freq is not None or _is_calendar(r.index) else core.DESIGN_START
    return r.loc[start:core.last_day()]


def _is_calendar(ix: pd.DatetimeIndex) -> bool:
    return len(ix) > 10 and (ix.dayofweek >= 5).mean() > 0.2


# ---------------------------------------------------------------- one configuration

def index_rows(key: str, g: dict) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(direction, gross window return, cost) per day for C16/C17; the noise family returns its net in ``gross``."""
    insts = ("SPY", "QQQ", "IWM") if g["inst"] == "MIX" else (g["inst"],)
    dirs, grs = [], []
    for s in insts:
        days = sorted(_G["index"][s])
        d_, r_ = {}, {}
        hist: list[np.ndarray] = []
        for day in days:
            pc, bars = _G["index"][s][day]
            if key == "C16_NOISE":
                r_[day], d_[day] = vi.noise_day(bars, hist, g["every"]), 1.0
                hist.append(vi.move_profile(bars))
            else:
                d_[day], r_[day] = vi.index_signal(bars, pc, key, g)
        dirs.append(pd.Series(d_))
        grs.append(pd.Series(r_))
    d = pd.concat(dirs, axis=1).fillna(0.0)
    r = pd.concat(grs, axis=1).fillna(0.0)
    return d, r, pd.Series(2 * vi.ETF_COST, index=d.index)


def _index_net(d: pd.DataFrame, r: pd.DataFrame, cost: pd.Series, noise: bool) -> pd.Series:
    if noise:
        return r.mean(axis=1)
    return (d * r).mean(axis=1) - (d.abs().mean(axis=1) * cost)


def real_and_placebo(key: str, ci: int, block: int) -> tuple[dict, dict, dict]:
    kind, cfgs = registry()[key]
    g = cfgs[ci]
    D, store = _G["D"], _G["store"]
    dates = D["dates"]
    reps = range(block * BLOCK + 1, (block + 1) * BLOCK + 1)
    real, plac, stats = {}, {}, {}
    if kind == "intra":
        trades = vi.family_trades(store, key, g)
        if block == 0:
            for sc in core.SCENARIOS:
                real[sc], used = core.intraday_book(trades, dates, sc)
                if sc == "mid" and len(used):
                    wins, losses = used.loc[used["net"] > 0, "net"].sum(), -used.loc[used["net"] < 0, "net"].sum()
                    stats = {"trades": int(len(used)), "pf": float(wins / losses) if losses > 0 else None,
                             "avg": float(used["net"].mean())}
        for rep in reps:
            rng = np.random.default_rng(_seed(key, ci, rep))
            if key not in _G["pools"]:
                _G["pools"][key] = vi.pool_by_day(store, key)
            pt = vi.placebo(store, key, g, trades, rng, _G["pools"][key])
            plac[rep] = core.intraday_book(pt, dates, "mid")[0]
    elif kind == "swing":
        sp = vs.specs(D, key, g)
        if block == 0:
            for sc in core.SCENARIOS:
                real[sc] = vs.book(D, sp, sc)
            paths = [p for s in sp if (p := vs.path(D, s, "mid")) is not None]
            tot = np.array([np.prod(1 + p[1]) - 1 for p in paths]) if paths else np.zeros(0)
            stats = {"trades": int(len(tot)), "pf": float(tot[tot > 0].sum() / -tot[tot < 0].sum())
                     if (tot < 0).any() else None, "avg": float(tot.mean()) if len(tot) else None}
        for rep in reps:
            rng = np.random.default_rng(_seed(key, ci, rep))
            plac[rep] = vs.book(D, vs.placebo_specs(D, key, sp, rng), "mid")
    elif kind == "index":
        d, r, cost = index_rows(key, g)
        noise = key == "C16_NOISE"
        net = _index_net(d, r, cost, noise).reindex(dates).fillna(0.0)
        if block == 0:
            real = {sc: net for sc in core.SCENARIOS}
        for rep in reps:
            rng = np.random.default_rng(_seed(key, ci, rep))
            if noise:
                flip = rng.choice([-1.0, 1.0], size=len(r))
                p = (r.mean(axis=1) * flip)
            else:
                k = int(rng.integers(60, 501))
                ds = pd.DataFrame(np.roll(d.to_numpy(), k, axis=0), index=d.index, columns=d.columns)
                p = _index_net(ds, r, cost, False)
            plac[rep] = p.reindex(dates).fillna(0.0)
    else:
        net = vm.run(key, g, _G["X"], _G["Y"])
        if block == 0:
            real = {sc: net for sc in core.SCENARIOS}
        for rep in reps:
            rng = np.random.default_rng(_seed(key, ci, rep))
            plac[rep] = vm.run(key, g, _G["X"], _G["Y"], shift=int(rng.integers(60, 501)))
    real = {k: _design(v) for k, v in real.items()}
    plac = {k: core.monthly(_design(v).to_frame("r"))["r"] for k, v in plac.items()}
    for m in plac.values():
        m.index = m.index.to_timestamp()  # parquet keeps timestamps, not periods
    return real, plac, stats


def _work(u: tuple[str, int, int]):
    t0 = time.time()
    try:
        real, plac, stats = real_and_placebo(*u)
        return u, real, plac, stats, time.time() - t0, None
    except Exception as exc:  # recorded, reported, never silently dropped
        return u, {}, {}, {}, time.time() - t0, f"{type(exc).__name__}: {exc}"


def cmd_shard(args) -> int:
    load_inputs(args.inputs)
    mine = units()[args.shard::args.shards]
    print(f"shard {args.shard}: {len(mine)} units", flush=True)
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            res = list(pool.imap_unordered(_work, mine))
    else:
        res = [_work(u) for u in mine]
    real_cols, plac_cols, meta = {}, {}, []
    for (key, ci, b), real, plac, stats, sec, err in res:
        for sc, s in real.items():
            real_cols[f"{key}|{ci}|{sc}"] = s.astype(np.float32)
        for rep, m in plac.items():
            plac_cols[f"{key}|{ci}|{rep}"] = m.astype(np.float32)
        meta.append({"key": key, "ci": ci, "block": b, "sec": round(sec, 1), "error": err, **stats})
    args.out.mkdir(parents=True, exist_ok=True)
    if real_cols:
        pd.DataFrame(real_cols).to_parquet(args.out / "real.parquet")
    if plac_cols:
        pd.DataFrame(plac_cols).astype(np.float32).to_parquet(args.out / "placebo.parquet")
    (args.out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    errs = [m for m in meta if m["error"]]
    print(f"shard done: {len(res)} units, {len(errs)} errors", flush=True)
    for e in errs[:5]:
        print("error:", e, flush=True)
    return 0


# ---------------------------------------------------------------- report

def _stats(r: pd.Series, cash: pd.Series, a: str, b: str) -> dict:
    x = r.loc[a:b].dropna()
    if len(x) < 40:
        return {}
    total = float((1 + x).prod() - 1)
    years = max((x.index[-1] - x.index[0]).days / 365.25, 1e-9)
    eq = (1 + x).cumprod()
    return {"sortino": core.sortino(x, cash), "cagr": (1 + total) ** (1 / years) - 1,
            "dd": float((eq / eq.cummax() - 1).min()), "total": total,
            "sharpe": float((x - cash.reindex(x.index).fillna(0)).mean() / x.std() * np.sqrt(252)) if x.std() > 0 else 0}


def _p_value(real_m: pd.Series, plac: pd.DataFrame, cash_m: pd.Series, before: pd.Period | None) -> float:
    rm = real_m if before is None else real_m[real_m.index < before]
    pm = plac if before is None else plac[plac.index < before]
    if len(rm) < 12 or pm.shape[1] == 0:
        return np.nan
    cm = cash_m.reindex(rm.index).fillna(0.0).to_numpy()
    s_real = core.sortino_cols(rm.to_numpy()[:, None], cm)[0]
    s_pl = core.sortino_cols(pm.reindex(rm.index).fillna(0.0).to_numpy(), cm)
    return float((s_pl >= s_real).mean())


def _ivol(R: pd.DataFrame, cap: float = 0.35) -> pd.Series:
    vol = R.tail(252).std().replace(0, np.nan)
    w = (1 / vol).fillna(0.0)
    if w.sum() <= 0:
        return w
    w = w / w.sum()
    for _ in range(10):
        over = w > cap
        if not over.any():
            break
        extra = (w[over] - cap).sum()
        w[over] = cap
        under = ~over
        if w[under].sum() > 0:
            w[under] += extra * w[under] / w[under].sum()
    return w.clip(upper=cap)


def combo_pbo(fam_R: dict[str, tuple[pd.DataFrame, list]], cash: pd.Series, end: pd.Timestamp) -> dict:
    """CPCV of the whole procedure: in each split every family's best plateau configuration on the training blocks
    enters if its training score is >= 1, inverse-volatility weights (cap 35%) from the training months; the
    combination's test Sortino is ranked among the test Sortinos of all configurations."""
    from itertools import combinations
    mats = {f: core.monthly(R.loc[core.DESIGN_START:end]) for f, (R, _) in fam_R.items()}
    months = sorted(set().union(*[m.index for m in mats.values()]))
    mats = {f: m.reindex(months).fillna(0.0).to_numpy() for f, m in mats.items()}
    cm = core.monthly(cash.loc[core.DESIGN_START:end].to_frame("c"))["c"].reindex(months).fillna(0.0).to_numpy()
    allM = np.hstack(list(mats.values()))
    blocks = np.array_split(np.arange(len(months)), core.N_BLOCKS)
    ranks, tests = [], []
    for tr in combinations(range(core.N_BLOCKS), core.N_BLOCKS // 2):
        tr_rows = np.concatenate([blocks[b] for b in tr])
        te_rows = np.concatenate([blocks[b] for b in range(core.N_BLOCKS) if b not in tr])
        cols = []
        for f, M in mats.items():
            s = core.plateau(core.score(M[tr_rows], cm[tr_rows]), fam_R[f][1])
            if np.isfinite(s).any() and np.nanmax(s) >= 1.0:
                cols.append(M[:, int(np.nanargmax(s))])
        te_all = core.sortino_cols(allM[te_rows], cm[te_rows])
        valid = te_all[np.isfinite(te_all)]
        if not cols or not len(valid):
            continue
        C = np.column_stack(cols)
        w = _ivol(pd.DataFrame(C[tr_rows])).to_numpy()
        combo_te = core.sortino_cols((C[te_rows] @ w)[:, None], cm[te_rows])[0]
        tests.append(combo_te)
        ranks.append(float((valid < combo_te).sum() + 0.5 * (valid == combo_te).sum()) / len(valid))
    if not ranks:
        return {"splits": 0, "pbo": np.nan}
    return {"splits": len(ranks), "pbo": float((np.array(ranks) < 0.5).mean()),
            "test_median": float(np.median(tests)), "test_p10": float(np.percentile(tests, 10))}


def cmd_report(args) -> int:
    reg = registry()
    real = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.rglob("real.parquet"))], axis=1)
    plac = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.rglob("placebo.parquet"))], axis=1)
    meta = [m for p in sorted(args.parts.rglob("meta.json")) for m in json.loads(p.read_text(encoding="utf-8"))]
    D = PREP.load(args.inputs / "daily.pkl")
    cal, cash = D["dates"], D["cash"]
    end = core.last_day()
    cash_m = core.monthly(cash.to_frame("c"))["c"]
    expected = len(units())
    errors = [m for m in meta if m["error"]]
    # every stream on the trading calendar
    cols = {}
    for c in real.columns:
        s = real[c].dropna()
        cols[c] = v11.to_trading(s, cal).fillna(0.0) if _is_calendar(s.index) else s.reindex(cal).fillna(0.0)
    R_all = pd.DataFrame(cols).loc[core.DESIGN_START:end]
    fams: dict[str, list[str]] = {}
    for key, (_, cfgs) in reg.items():
        fams.setdefault(family_of(key), []).extend([key + "|" + str(i) for i in range(len(cfgs))])
    lines = ["# v14: many independent ideas on survivorship-free data (pre-registered)", "",
             f"Units {len(meta)} of {expected}; errors {len(errors)}. Design 2016-01-04 to {end.date()} (crypto from "
             f"2018); walk-forward from 2018. Middle costs unless stated. Target: COMBO monthly Sortino 4.", ""]
    head = ("| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | "
            "years placebo-ok | gate | PBO | best config (design Sortino, p) |")
    lines += ["## 1. Families", "", head, "|" + "---|" * 13]
    fam_streams, fam_picks, fam_nb, summary = {}, {}, {}, {}
    for fam, names in fams.items():
        mid = [n + "|mid" for n in names if n + "|mid" in R_all]
        if not mid:
            continue
        R = R_all[mid].copy()
        R.columns = [c[:-4] for c in mid]
        cfg_dicts = []
        for c in R.columns:
            key, ci = c.split("|")
            cfg_dicts.append({"rule": key, **reg[key][1][int(ci)]})
        nb = core.neighbours(cfg_dicts)
        wf, picks = core.walk_forward(R, cash, nb, end=end)
        if wf.empty:
            continue
        wf = wf.reindex(R.loc["2018-01-01":end].index).fillna(0.0)
        ok_years = 0
        pv = {}
        for y, (name, sc) in picks.items():
            pl = plac[[c for c in plac.columns if c.startswith(name + "|")]]
            pl.index = pd.PeriodIndex(pl.index, freq="M") if not isinstance(pl.index, pd.PeriodIndex) else pl.index
            rm = core.monthly(R[[name]])[name]
            pv[y] = _p_value(rm, pl, cash_m, pd.Period(f"{y}-01", "M"))
            ok_years += int(np.isfinite(pv[y]) and pv[y] <= 0.05)
        st = _stats(wf, cash, "2018-01-01", str(end.date()))
        h1, h2 = _stats(wf, cash, "2018-01-01", "2020-12-31"), _stats(wf, cash, "2021-01-01", str(end.date()))
        lo = high = {}
        for sc, tgt in (("low", "lo"), ("high", "hi")):
            pieces = [R_all[f"{name}|{sc}"].loc[f"{y}-01-01":f"{y}-12-31"] for y, (name, _) in picks.items()
                      if f"{name}|{sc}" in R_all]
            s = pd.concat(pieces).reindex(wf.index).fillna(0.0) if pieces else wf * 0
            if tgt == "lo":
                lo = _stats(s, cash, "2018-01-01", str(end.date()))
            else:
                high = _stats(s, cash, "2018-01-01", str(end.date()))
        gate = bool(st and st["sortino"] >= 1.0 and ok_years >= np.ceil(2 / 3 * len(picks)))
        pbo = core.cpcv(R, cash, nb, end=end)
        design_s = {c: core.sortino(R[c], cash) for c in R.columns}
        best = max(design_s, key=lambda c: design_s[c])
        pl = plac[[c for c in plac.columns if c.startswith(best + "|")]]
        pl.index = pd.PeriodIndex(pl.index, freq="M") if not isinstance(pl.index, pd.PeriodIndex) else pl.index
        p_best = _p_value(core.monthly(R[[best]])[best], pl, cash_m, None)
        fam_streams[fam], fam_picks[fam], fam_nb[fam] = wf, (picks, pv, R), (R, nb)
        summary[fam] = {"wf": st, "h1": h1, "h2": h2, "low": lo, "high": high, "placebo_years": ok_years,
                        "years": len(picks), "gate": gate, "pbo": pbo, "best": best, "best_design": design_s[best],
                        "best_p": p_best, "picks": {int(y): v[0] for y, v in picks.items()}}

        def f(d, k, fmt):
            return fmt.format(d[k]) if d and k in d and d[k] is not None and np.isfinite(d[k]) else "-"
        lines.append(f"| {fam} | {f(st, 'sortino', '{:.2f}')} | {f(h1, 'sortino', '{:.2f}')} | "
                     f"{f(h2, 'sortino', '{:.2f}')} | {f(st, 'cagr', '{:.1%}')} | {f(st, 'dd', '{:.1%}')} | "
                     f"{f(st, 'total', '{:+.0%}')} | {f(lo, 'sortino', '{:.2f}')} | {f(high, 'sortino', '{:.2f}')} | "
                     f"{ok_years}/{len(picks)} | {'pass' if gate else 'fail'} | {f(pbo, 'pbo', '{:.0%}')} | "
                     f"{best} ({design_s[best]:.2f}, p {p_best:.2f}) |")
    # combination, year by year on earlier data only
    pieces, members = [], {}
    for y in range(core.WF_YEARS[0], end.year + 1):
        chosen = {}
        for fam, (picks, pv, R) in fam_picks.items():
            if y in picks and picks[y][1] >= 1.0 and np.isfinite(pv.get(y, np.nan)) and pv[y] <= 0.05:
                chosen[fam] = R[picks[y][0]]
        members[y] = sorted(chosen)
        if not chosen:
            pieces.append(pd.Series(0.0, index=cal[(cal >= pd.Timestamp(f"{y}-01-01")) &
                                                   (cal <= min(end, pd.Timestamp(f"{y}-12-31")))]))
            continue
        M = pd.DataFrame(chosen)
        w = _ivol(M.loc[:f"{y - 1}-12-31"])
        pieces.append((M.loc[f"{y}-01-01":min(end, pd.Timestamp(f"{y}-12-31"))] * w).sum(axis=1))
    combo = pd.concat(pieces).reindex(cal[(cal >= pd.Timestamp("2018-01-01")) & (cal <= end)]).fillna(0.0)
    cs = _stats(combo, cash, "2018-01-01", str(end.date()))
    c1, c2 = _stats(combo, cash, "2018-01-01", "2020-12-31"), _stats(combo, cash, "2021-01-01", str(end.date()))
    allR = R_all[[c for c in R_all.columns if c.endswith("|mid")]]
    sh = allR.apply(lambda s: s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else np.nan).dropna()
    prior = _script("run_v10")._prior_pool()
    pool = np.concatenate([sh.to_numpy(), prior[np.isfinite(prior)]])
    g = np.euler_gamma
    n = len(pool)
    e_max = (1 - g) * norm.ppf(1 - 1 / n) + g * norm.ppf(1 - 1 / (n * np.e))
    x = combo.loc["2018-01-01":]
    sr = x.mean() / x.std() if x.std() > 0 else 0.0
    sr0 = pool.std() / np.sqrt(252) * e_max
    den = 1 - x.skew() * sr + (x.kurt() + 2) / 4 * sr ** 2
    dsr = float(norm.cdf((sr - sr0) * np.sqrt(len(x) - 1) / np.sqrt(den))) if den > 0 else np.nan
    cpbo = combo_pbo(fam_nb, cash, end)
    ok = bool(cs and c1 and c2 and cs["sortino"] >= 4 and c1["sortino"] >= 3 and c2["sortino"] >= 3
              and np.isfinite(cpbo["pbo"]) and cpbo["pbo"] < 0.2)
    lines += ["", "## 2. Combination (families chosen each year on earlier data only)", "",
              "| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | DSR | PBO | design criterion |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    if cs:
        lines.append(f"| COMBO | {cs['sortino']:.2f} | {c1.get('sortino', np.nan):.2f} | "
                     f"{c2.get('sortino', np.nan):.2f} | {cs['cagr']:.1%} | {cs['dd']:.1%} | {cs['total']:+.0%} | "
                     f"{dsr:.2f} | {cpbo['pbo']:.0%} | {'met' if ok else 'not met'} |")
    yearly = {int(y): float(v) for y, v in ((1 + combo).groupby(combo.index.year).prod() - 1).items()}
    lines += ["", "Members by year: " + "; ".join(f"{y}: {', '.join(m) or 'none'}" for y, m in members.items()),
              "", "COMBO by year: " + ", ".join(f"{y} {v:+.1%}" for y, v in yearly.items())]
    if errors:
        lines += ["", f"Errors in {len(errors)} units, first: {errors[0]}"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps({"families": summary, "combo": cs, "combo_h1": c1,
                                                       "combo_h2": c2, "dsr": dsr, "combo_pbo": cpbo, "criterion": ok,
                                                       "members": members, "combo_yearly": yearly},
                                                      indent=1, default=float), encoding="utf-8")
    pd.DataFrame({**{f: s for f, s in fam_streams.items()}, "COMBO": combo}).astype(np.float32).to_parquet(
        args.out / "streams.parquet")
    print("\n".join(lines), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, default=SHARDS)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--inputs", type=Path, default=Path("outputs/v14/inputs"))
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--inputs", type=Path, default=Path("outputs/v14/inputs"))
    r.add_argument("--parts", type=Path, required=True)
    r.add_argument("--out", type=Path, default=Path("outputs/v14/report"))
    args = ap.parse_args()
    return {"shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
