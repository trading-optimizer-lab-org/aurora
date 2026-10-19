#!/usr/bin/env python3
"""v12: everything that could raise the Sortino of the intraday book. Pre-registered in
docs/research/V12_PREREGISTRATION.md.

    python scripts/run_v12.py prepare ... (same arguments as run_v10.py prepare)
    python scripts/run_v12.py shard --shard 0 --inputs outputs/v10/inputs --out outputs/v12_part --workers 4
    python scripts/run_v12.py report --inputs outputs/v10/inputs --parts outputs/v12_parts --out outputs/v12_report
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

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import stock_catalog as sc
from aurora.research import v9_common as c9
from aurora.research import v10
from aurora.research import v11
from aurora.research import v12

SYMBOLS = Path("docs/research/data/stock_catalog_symbols.csv")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R10, R11 = _script("run_v10"), _script("run_v11")


# ---------------------------------------------------------------- prepare

def cmd_prepare(args) -> int:
    rc = R11.cmd_prepare(args)
    if rc:
        return rc
    LK = _script("run_intraday_locked")
    inputs = args.out / "inputs"
    panel, bench = LK.PANEL.load_panel(args.out / "panel")
    nasdaq = LK.QS.nasdaq_close(args.out / "panel" / "ixic.csv")
    qb = R10._load(inputs / "qb.pkl")
    dates, cols = qb["dates"], qb["cols"]
    industry = pd.read_csv(SYMBOLS).set_index("symbol")["industry"].reindex(panel["close"].columns)
    ind = sc.indicators(panel, bench["gspc"], industry)
    ctx = q.context(panel, ind, nasdaq)
    O, H, L, C = (panel[k] for k in ("open", "high", "low", "close"))
    ep = q.episodic_gap(panel, ind, ctx, qi.EP_ADR, False).fillna(False).astype(bool)
    nz = nasdaq.reindex(C.index).ffill()
    e10, e20 = nz.ewm(span=10, adjust=False).mean(), nz.ewm(span=20, adjust=False).mean()
    s50 = nz.rolling(50, min_periods=50).mean()
    lag = lambda s: s.shift(1, fill_value=False).astype(bool)  # noqa: E731
    ranks = c9.universe_ranks(C, panel["volume"])
    uni = ranks <= 1000
    above = (C > C.rolling(50, min_periods=50).mean()) & uni
    breadth = above.sum(axis=1) / uni.sum(axis=1).replace(0, np.nan)
    hi = (C >= C.rolling(252, min_periods=200).max()) & uni
    lo = (C <= C.rolling(252, min_periods=200).min()) & uni
    vix = LK.MAB.yahoo_close("^VIX").reindex(C.index).ffill()
    m1 = ctx["m1"].astype(bool)
    reg = {"NONE": pd.Series(True, index=C.index), "M1": m1, "NEMA": lag((nz > e10) & (nz > e20)), "N20": lag(nz > e20),
           "N50": lag(nz > s50), "BR50": lag(breadth >= 0.5), "NHNL": lag(hi.sum(axis=1) > lo.sum(axis=1)),
           "VIX25": lag(vix < 25)}
    reg["M1_N50"] = reg["M1"] & reg["N50"]
    reg["M1_BR50"] = reg["M1"] & reg["BR50"]
    regime = {k: v.reindex(dates).fillna(False).to_numpy(bool) for k, v in reg.items()}
    P = qb["panel"]
    gap = (P["open"] / P["close"].shift(1) - 1).to_numpy(np.float32)
    rs = (C / C.shift(63) - 1).rank(axis=1, pct=True).shift(1).reindex(index=dates, columns=cols)
    fresh = ~(ep.shift(1, fill_value=False).astype(float).rolling(63, min_periods=1).max() > 0)
    codes = pd.factorize(industry.reindex(cols).fillna("__none__"))[0].astype(np.int32)
    codes[industry.reindex(cols).isna().to_numpy()] = -1
    rng = (H - L).where(H > L)
    ec = (ep & (C >= O) & ((C - L) / rng >= 0.75)).reindex(index=dates, columns=cols).fillna(False).astype(bool)
    Ld = L.reindex(index=dates, columns=cols).astype(np.float32)
    nan = Ld * np.nan
    lt = R10._load(inputs / "lt.pkl")
    x12 = {"regime": regime, "gap": np.nan_to_num(gap, nan=0.0), "gap_ep": np.nan_to_num(gap, nan=0.0) >= 0.10,
           "rs_prior": rs.fillna(0.0).to_numpy(np.float32),
           "fresh": fresh.reindex(index=dates, columns=cols).fillna(True).to_numpy(bool), "groups": codes,
           "ep_close": v10.sparse((ec, Ld, nan, nan)),
           "qqq": lt["etf"]["QQQ"].pct_change(fill_method=None).reindex(dates).fillna(0.0)}
    R10._dump(x12, inputs / "x12.pkl")
    print({k: float(v.mean()) for k, v in regime.items()}, {"ep_close": int(len(x12["ep_close"]["r"]))}, flush=True)
    return 0


# ---------------------------------------------------------------- shards

_G: dict = {}
_X: dict = {}


def load(inputs: Path) -> tuple[dict, dict]:
    G = R10.qb_globals(R10._load(inputs / "qb.pkl"))
    X = R10._load(inputs / "x12.pkl")
    shape = (len(G["dates"]), len(G["cols"]))
    G["sig"]["EP_CLOSE"] = v10.dense(X["ep_close"], shape)
    X["cash_np"] = G["cash"].reindex(G["dates"]).fillna(0.0).to_numpy()
    X["plan"] = v12.metric_plan(G["dates"], X["cash_np"])
    return G, X


def _work(i: int) -> list[dict]:
    return v12.evaluate_base(i, _G, _X)


def aggregates(df: pd.DataFrame) -> dict:
    cfgs = pd.DataFrame([v12.cfg(int(i)) for i in df["id"]])
    cfgs["overlay"] = [v12.OVERLAYS[k] for k in df["ov"]]
    cfgs["hedge"] = [v12.HEDGES[k] for k in df["hg"]]
    good = df["robust"].astype(float) >= 3
    out: dict = {}
    for col in cfgs.columns:
        for val, idx in cfgs.groupby(col).groups.items():
            sub = df.loc[idx]
            g = good.loc[idx]
            hist = np.histogram(np.clip(sub.loc[g, "judge_sortino"].astype(float).dropna(), -5, 15), v12.HIST_EDGES)[0]
            out[f"{col}={val}"] = {"n": int(len(sub)), "n_r3": int(g.sum()), "hist": hist.tolist()}
    sh = df["judge_sharpe"].astype(float)
    sh = sh[np.isfinite(sh)]
    out["_sharpe"] = {"n": int(len(sh)), "sum": float(sh.sum()), "sumsq": float((sh ** 2).sum())}
    return out


def cmd_shard(args) -> int:
    t0 = time.time()
    G, X = load(args.inputs)
    _G.update(G)
    _X.update(X)
    ids = list(range(args.shard, v12.N_BASE, v12.SHARDS))
    print(f"shard {args.shard}: {len(ids)} base configurations, inputs in {time.time() - t0:.0f}s", flush=True)
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            chunks = list(pool.imap_unordered(_work, ids, chunksize=4))
    else:
        chunks = [_work(i) for i in ids]
    df = pd.DataFrame([r for ch in chunks for r in ch])
    args.out.mkdir(parents=True, exist_ok=True)
    df[np.isfinite(df["robust"].astype(float))].nlargest(v12.TOP_PER_SHARD, "robust").to_parquet(
        args.out / "top.parquet", index=False)
    (args.out / "agg.json").write_text(json.dumps(aggregates(df)), encoding="utf-8")
    print(f"shard done in {time.time() - t0:.0f}s, {len(df)} evaluations", flush=True)
    return 0


# ---------------------------------------------------------------- report

def _f(v, fmt: str) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return "-" if not np.isfinite(v) else fmt.format(v)


def _stats(r: pd.Series, cash: pd.Series) -> dict:
    out = {}
    for p in ("design", "judge", "j1", "j2"):
        a, b = v12.PERIODS[p]
        x = r.loc[a:b].dropna()
        m = sc.metrics(x, cash)
        total = float((1 + x).prod() - 1)
        years = (x.index[-1] - x.index[0]).days / 365.25
        out.update({f"{p}_sortino": m.get("sortino_monthly"), f"{p}_cagr": (1 + total) ** (1 / years) - 1,
                    f"{p}_dd": m.get("max_drawdown"), f"{p}_total": total, f"{p}_sharpe": m.get("sharpe"),
                    f"{p}_days": len(x), f"{p}_skew": m.get("skew"), f"{p}_kurtosis": m.get("kurtosis")})
    x = r.loc[v12.PERIODS["design"][0]:v12.LAST].dropna()
    out["yearly"] = {int(y): float(v) for y, v in ((1 + x).groupby(x.index.year).prod() - 1).items()}
    return out


def _dsr(m: dict, pool_n: int, pool_std_ann: float) -> float:
    g = np.euler_gamma
    e_max = (1 - g) * norm.ppf(1 - 1 / pool_n) + g * norm.ppf(1 - 1 / (pool_n * np.e))
    sr0 = pool_std_ann / np.sqrt(sc.PPY) * e_max
    sr = m["judge_sharpe"] / np.sqrt(sc.PPY)
    t = m["judge_days"]
    den = 1 - m["judge_skew"] * sr + (m["judge_kurtosis"] - 1) / 4 * sr ** 2
    return float(norm.cdf((sr - sr0) * np.sqrt(t - 1) / np.sqrt(den))) if den > 0 else np.nan


HEAD = ("| {} | Sortino 2016-20 | Sortino 2021-26 | 2021-23 | 2024-26 | CAGR 2021-26 | max DD 2021-26 | total 2021-26 | "
        + " | ".join(str(y) for y in range(2016, 2027)) + " |")
SEP = "|" + "---|" * 19


def _line(n: str, m: dict) -> str:
    ys = " | ".join(_f(m["yearly"].get(y), "{:+.0%}") for y in range(2016, 2027))
    return (f"| {n} | {_f(m['design_sortino'], '{:.2f}')} | {_f(m['judge_sortino'], '{:.2f}')} | "
            f"{_f(m['j1_sortino'], '{:.2f}')} | {_f(m['j2_sortino'], '{:.2f}')} | {_f(m['judge_cagr'], '{:.1%}')} | "
            f"{_f(m['judge_dd'], '{:.1%}')} | {_f(m['judge_total'], '{:+.0%}')} | {ys} |")


def _median_from_hist(hist: list[int]) -> float:
    h = np.asarray(hist)
    if h.sum() == 0:
        return np.nan
    k = int(np.searchsorted(np.cumsum(h), h.sum() / 2))
    return float((v12.HIST_EDGES[k] + v12.HIST_EDGES[k + 1]) / 2)


def cmd_report(args) -> int:
    tops = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.rglob("top.parquet"))], ignore_index=True)
    aggs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.parts.rglob("agg.json"))]
    G, X = load(args.inputs)
    cash = G["cash"]
    best = tops.sort_values("robust", ascending=False).drop_duplicates(["id", "ov", "hg"]).head(25).reset_index(drop=True)
    series = {}
    for _, r in best.iterrows():
        ov = v12.OVERLAYS[int(r["ov"])]
        rr, inv = v12.runs(int(r["id"]), G, X, overlays=("NONE",) if ov == "NONE" else ("NONE", ov))[ov]
        nm = v12.name(v12.cfg(int(r["id"])), ov, v12.HEDGES[int(r["hg"])])
        series[nm] = v12.hedge(rr, inv, v12.HEDGES[int(r["hg"])], X["qqq"], cash).reindex(G["dates"])
    R = pd.DataFrame(series)
    names = list(R.columns)
    combos = {"PICK": R[names[0]], **{f"ENS{k}": R[names[:k]].mean(axis=1) for k in (5, 10, 25)}}
    GO = R11._globals(args.inputs, "OTHER")
    extra = {}
    for t in v11.other_trials():
        s, c_ = R11.stream(t, GO)
        sc_row = v11.score_row(t["name"], t["family"], s, c_)
        if np.isfinite(sc_row["robust"]) and sc_row["robust"] >= 2.0:
            extra[t["name"]] = (v11.to_trading(s, G["dates"]) if t["family"] == "CT" else s).reindex(G["dates"])
    plus = pd.concat([R[names[:10]], pd.DataFrame(extra)], axis=1)
    D = plus.loc[v12.PERIODS["design"][0]:v12.PERIODS["design"][1]]
    combos["ENS10_PLUS"] = v11.combine(plus, v11.ivol_weights(D))
    n12 = sum(a["_sharpe"]["n"] for a in aggs)
    s1, s2 = sum(a["_sharpe"]["sum"] for a in aggs), sum(a["_sharpe"]["sumsq"] for a in aggs)
    prior = R10._prior_pool()
    prior = prior[np.isfinite(prior)]
    n_all = n12 + len(prior)
    mean = (s1 + prior.sum()) / n_all
    std = np.sqrt(max((s2 + (prior ** 2).sum()) / n_all - mean ** 2, 0.0))
    spy = GO["etf"]["SPY"].dropna().pct_change(fill_method=None).reindex(G["dates"])
    stats = {k: _stats(v, cash) for k, v in combos.items()}
    for m in stats.values():
        m["dsr"] = _dsr(m, n_all, std)
    lines = ["# v12: everything that could raise the Sortino of the intraday book (pre-registered)", "",
             f"{n12:,} evaluations (expected {v12.N_BASE * 15:,}); chosen on 2016-2020 by the worse half; judged on "
             f"2021-01-01 to {v12.LAST.date()} and its halves. Owner's target: monthly Sortino of 4. Deflated Sharpe "
             f"over {n_all:,} trials. Extra streams with a robust score >= 2 for ENS10_PLUS: {len(extra)}.", "",
             "## 1. Picks and ensembles", "", HEAD.format("strategy"), SEP]
    for k, m in stats.items():
        lines.append(_line(f"{k} (DSR {_f(m['dsr'], '{:.2f}')}{', SORTINO >= 4' if (m['judge_sortino'] or 0) >= 4 else ''})", m))
    lines.append(_line("SPY", _stats(spy, cash)))
    lines += ["", f"PICK = `{names[0]}`", "", "## 2. The 25 most robust configurations", "", HEAD.format("configuration"), SEP]
    lines += [_line(n, _stats(R[n], cash)) for n in names]
    lines += ["", "## 3. What helps: per lever value, configurations with a robust score >= 3 and their median "
              "2021-2026 Sortino", "", "| lever = value | evaluations | robust >= 3 | share | median Sortino 2021-26 |",
              "|---|---|---|---|---|"]
    keys = sorted({k for a in aggs for k in a if not k.startswith("_")})
    for k in keys:
        n = sum(a[k]["n"] for a in aggs if k in a)
        r3 = sum(a[k]["n_r3"] for a in aggs if k in a)
        hist = np.sum([a[k]["hist"] for a in aggs if k in a], axis=0)
        lines.append(f"| {k} | {n:,} | {r3:,} | {r3 / n:.2%} | {_f(_median_from_hist(hist.tolist()), '{:.2f}')} |")
    if extra:
        lines += ["", "Extra streams in ENS10_PLUS: " + ", ".join(extra) + "."]
    text = "\n".join(lines) + "\n"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "REPORT.md").write_text(text, encoding="utf-8")
    pd.DataFrame(combos).to_csv(args.out / "combo_streams.csv")
    best.to_csv(args.out / "top25.csv", index=False)
    print(text, flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--out", type=Path, default=Path("outputs/v10"))
    a.add_argument("--old-cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca_locked"))
    a.add_argument("--sec-cache", type=Path, default=Path("outputs/sec_locked"))
    a.add_argument("--nasdaq", type=Path, default=Path("outputs/alpaca/ixic.csv"))
    a = sub.add_parser("shard")
    a.add_argument("--shard", type=int, required=True)
    a.add_argument("--inputs", type=Path, default=Path("outputs/v10/inputs"))
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--workers", type=int, default=4)
    a = sub.add_parser("report")
    a.add_argument("--inputs", type=Path, default=Path("outputs/v10/inputs"))
    a.add_argument("--parts", type=Path, default=Path("outputs/v12_parts"))
    a.add_argument("--out", type=Path, default=Path("outputs/v12_report"))
    args = ap.parse_args()
    return {"prepare": cmd_prepare, "shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
