#!/usr/bin/env python3
"""v10: every idea to close the gap, on 320 runners. Pre-registered in docs/research/V10_PREREGISTRATION.md.

    python scripts/run_v10.py prepare --panel-dir outputs/stock_panel --out outputs/v10 --old-cache outputs/alpaca \
        --cache outputs/alpaca_locked --sec-cache outputs/sec_locked --nasdaq outputs/alpaca/ixic.csv
    python scripts/run_v10.py shard --shard 0 --inputs outputs/v10/inputs --out outputs/v10/part_0 --workers 4
    python scripts/run_v10.py report --inputs outputs/v10/inputs --parts outputs/v10_parts --out outputs/v10_report

Market data stays in the Actions cache (the inputs folder); only strategy results are uploaded.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import combination_plus as cp
from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_catalyst as qc
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_stars as qs
from aurora.research import qullamaggie_wind as qw
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7
from aurora.research import stock_trades as st
from aurora.research import v10

WARMUP = pd.Timestamp("2015-11-02")
IND_KEYS = ("sma5", "sma10", "sma20", "sma50", "ema21", "adr")
CRYPTO = Path("docs/research/data/after_2020_crypto_streams.csv")
PRIOR = Path("docs/research/data/stock_catalog_prior_sharpes.json")
MONSTERS = Path("docs/research/data/gap_monsters.csv")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dump(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(obj, fh, protocol=5)


def _load(path: Path):
    with open(path, "rb") as fh:
        return pickle.load(fh)


def _mix(a: tuple, b: tuple) -> tuple:
    """Breakout entries a and EP entries b in one book (a's values where both fire), as qs.intraday_signals."""
    return (a[0] | b[0], a[1].where(a[0], b[1]), a[2].where(a[0], b[2]), a[3].where(a[0], b[3]))


# ---------------------------------------------------------------- prepare

def cmd_prepare(args) -> int:
    LK, RA, GP = _script("run_intraday_locked"), _script("run_after_2020"), _script("run_gap")
    LK.LAST = v10.LAST
    LK.cmd_prepare(argparse.Namespace(panel_dir=args.panel_dir, out=args.out, cache=args.cache,
                                      sec_cache=args.sec_cache, nasdaq=args.nasdaq))
    qi.START, qi.WARMUP, qi.END = v10.QB_START, WARMUP, v10.LAST
    GP.merge_caches(args.old_cache, args.cache)
    panel, bench = LK.PANEL.load_panel(args.out / "panel")
    cash_index = LK.MAB.tbill_index({}).loc[:v10.LAST]
    nasdaq = LK.QS.nasdaq_close(args.out / "panel" / "ixic.csv")
    industry = pd.read_csv(LK.SYMBOLS).set_index("symbol")["industry"].reindex(panel["close"].columns)
    ind = sc.indicators(panel, bench["gspc"], industry)
    ctx = q.context(panel, ind, nasdaq)
    cands = qi.candidates(panel, ind, ctx)
    need = qi.needed(cands)
    ep_symbols = sorted(cands["IEP_N0"].columns[cands["IEP_N0"].fillna(False).astype(bool).any()])
    del cands
    api = LK.FETCH.Alpaca()
    alp_daily = LK.FETCH.fetch_daily(api, args.cache, sorted({s for v in need.values() for s in v}))
    LK.FETCH.fetch_minutes(api, args.cache, need)
    sec = LK.CAT.Sec()
    ciks = LK.CAT.ticker_ciks(sec, args.sec_cache)
    cik = {s: ciks[s.upper()] for s in ep_symbols if s.upper() in ciks}
    earnings: dict[str, list[pd.Timestamp]] = {}
    for s, k in sorted(cik.items()):
        dts = LK.CAT.earnings_dates(sec, args.sec_cache, k)
        if dts is not None:
            earnings[s] = [pd.Timestamp(d) for d in dts]
    print(f"calls for missing data: Alpaca {api.calls}, SEC {sec.calls}", flush=True)
    wind_df = qw.wind(panel, ind, ctx)
    kept, _ = qs.selected_breakouts(panel, ind, ctx, nasdaq)
    feats = qs.features(panel, ind, nasdaq)
    e35, s35, px35 = q.breakout(panel, ind, ctx, "STOP", *q.BO_SELECTIONS["SCAN35"])
    stream = st.trade_list(panel, ind, e35.fillna(False).astype(bool), s35.astype(np.float32), qw.EXIT,
                           entry_px=px35.astype(np.float32))
    score = qs.model_score(feats, qs.train_model(feats, stream))
    del feats, stream, e35, s35, px35
    prep = qi.prepare(panel, ind, ctx, cash_index, LK.FETCH.minute_loader(args.cache), alp_daily)
    ib0, ie, _ = qs.intraday_signals(prep, None)
    a = (prep["table"], prep["cands"], prep["m1"], prep["adr_prior"], prep["like"])
    en0 = qi.trial_inputs(qi.Trial("IEP_N0_Q05_K5_XQ3_20", "IEP", "N0", "Q05", 5, qw.EXIT), *a)[:4]
    cand = prep["cands"]["IEP_N0"].stack()
    cells = cand[cand].index.to_frame(index=False)
    cells.columns = ["date", "symbol"]
    lab = qc.labels(cells, prep["panel"]["close"].index, earnings, set(earnings), cik, {})
    labelled = {}
    for name, cat_name, n in (("EP_EARN", "EARN", "N0"), ("EP_NEWS", "NOEARN", "N1")):
        mask = qc.label_mask(lab, cat_name, prep["cands"]["IEP_N0"])
        cands2 = dict(prep["cands"])
        cands2[f"IEP_{n}"] = cands2[f"IEP_{n}"] & mask.reindex_like(cands2[f"IEP_{n}"]).fillna(False)
        trial = qi.Trial(f"IEP_{n}_Q05_K5_XQ3_20", "IEP", n, "Q05", 5, qw.EXIT)
        labelled[name] = qi.trial_inputs(trial, prep["table"], cands2, prep["m1"], prep["adr_prior"], prep["like"])[:4]
    sigs = {"EP_N1": ie, "EP_N0": en0, "EP_EARN": labelled["EP_EARN"], "EP_NEWS": labelled["EP_NEWS"],
            "BO_ALL": ib0, "MIX1": qs.intraday_signals(prep, kept[("MODEL", 1)])[2],
            "MIX3": qs.intraday_signals(prep, kept[("MODEL", 3)])[2],
            "MIXS3": qs.intraday_signals(prep, kept[("STARS", 3)])[2], "ALL": _mix(ib0, en0)}
    dates, cols = prep["panel"]["close"].index, prep["panel"]["close"].columns
    P = prep["panel"]
    gap = (P["open"] / P["close"].shift(1) - 1).astype(np.float32)
    dv = (panel["close"] * panel["volume"]).rolling(20, min_periods=20).mean().shift(1).reindex(index=dates, columns=cols)
    ranks = {"RS63": prep["rank"], "GAP": gap.fillna(0.0), "MODEL": score.reindex(index=dates, columns=cols).fillna(0.0),
             "DV": dv.fillna(0.0).astype(np.float32)}
    not_red = (wind_df["state"].shift(1).fillna("yellow") != "red").reindex(dates).fillna(True).to_numpy()
    qb = {"panel": {k: v.astype(np.float32) for k, v in P.items()},
          "ind": {k: prep["ind"][k].astype(np.float32) for k in IND_KEYS},
          "cash": prep["cash"], "dates": dates, "cols": cols, "rank": {k: v.astype(np.float32) for k, v in ranks.items()},
          "sig": {k: v10.sparse(v) for k, v in sigs.items()},
          "m1": prep["m1"].reindex(dates).fillna(False).to_numpy(bool), "not_red": not_red,
          "adr_prior": prep["adr_prior"].reindex(index=dates, columns=cols).to_numpy(np.float32)}
    inputs = args.out / "inputs"
    _dump(qb, inputs / "qb.pkl")
    print({k: int(len(v["r"])) for k, v in qb["sig"].items()}, flush=True)

    # gate: the base book rebuilt from the saved inputs reproduces its published 2016-2020 result
    G = qb_globals(_load(inputs / "qb.pkl"))
    scale, gross, cap = qw.policy("E0", wind_df)
    e, s, px, sd = G["sig"]["MIX3"]
    df = lambda x: pd.DataFrame(x, index=G["dates"], columns=G["cols"])  # noqa: E731
    base = sc.simulate(G["panel"], G["ind"], df(e), df(s), qw.EXIT, G["cash"], G["rank"]["RS63"], start=v10.QB_START,
                       entry_px=df(px), same_day_px=df(sd), risk_scale=scale, max_gross=gross, cap=cap)["return"]
    m = sc.metrics(base.loc[v10.QB_START:v10.DESIGN_END], G["cash"])
    ref_s, ref_c = RA.REFERENCE["I_MIX_MODEL_N3_E0"]
    diff = max(abs(m["sortino_monthly"] - ref_s), abs(m["cagr"] - ref_c))
    print(f"gate: Sortino {m['sortino_monthly']:.6f} vs {ref_s:.6f}, CAGR {m['cagr']:.6f} vs {ref_c:.6f}", flush=True)
    if not np.isfinite(diff) or diff > 1e-9:
        print("GATE FAILED", flush=True)
        return 1

    # the other families' inputs
    etf = pd.DataFrame({t: LK.MAB.yahoo_close(t) for t in ("QQQ", "SPY", "IWM", "IEF")}).loc[:v10.LAST]
    _dump({"etf": etf, "cash": cash_index.pct_change(fill_method=None).fillna(0.0)}, inputs / "lt.pkl")
    _dump({"close": panel["close"].astype(np.float32), "volume": panel["volume"].astype(np.float32),
           "spy": bench["spy"], "cash": cash_index}, inputs / "mr.pkl")
    print("inputs ready", flush=True)
    return 0


# ---------------------------------------------------------------- shards

_G: dict = {}


def qb_globals(raw: dict) -> dict:
    shape = (len(raw["dates"]), len(raw["cols"]))
    G = dict(raw)
    G["sig"] = {k: v10.dense(v, shape) for k, v in raw["sig"].items()}
    G["gross"] = {g: pd.Series(g, index=raw["dates"]) for g in v10.QB_DIMS["gross"]}
    return G


def other_globals(inputs: Path) -> dict:
    lt = _load(inputs / "lt.pkl")
    mr = _load(inputs / "mr.pkl")
    cash_td = mr["cash"].pct_change(fill_method=None).fillna(0.0)
    cal = pd.date_range("2014-01-01", v10.LAST)
    daily = cash_td.reindex(cal).fillna(0.0)
    crypto = pd.read_csv(CRYPTO, index_col=0, parse_dates=True).loc[:v10.LAST]
    return {"etf": lt["etf"], "cash": lt["cash"], "cash_cal": daily, "crypto": crypto,
            "mr": v10.mr_context(mr["close"], mr["volume"], mr["spy"], cash_td)}


def _qb_work(i: int) -> dict:
    g = v10.qb_cfg(i)
    return {**v10.row(v10.qb_name(g), "QB", v10.qb_sim(g, _G), _G["cash"]), "id": i}


def _other_work(t: dict) -> dict:
    f = t["family"]
    if f == "LT":
        r, cash = v10.lt_sim(t, _G["etf"], _G["cash"]), _G["cash"]
    elif f == "CT":
        r, cash = v10.ct_sim(t, _G["crypto"], _G["cash_cal"]), _G["cash_cal"]
    else:
        r, cash = v10.mr_sim(t, _G["mr"]), _G["mr"]["cash_s"]
    return {**v10.row(t["name"], f, r, cash), "id": -1}


def cmd_shard(args) -> int:
    t0 = time.time()
    kind, items = v10.shard_items(args.shard)
    if kind == "QB":
        _G.update(qb_globals(_load(args.inputs / "qb.pkl")))
        work = _qb_work
    else:
        _G.update(other_globals(args.inputs))
        work = _other_work  # type: ignore[assignment]
    print(f"shard {args.shard}: {kind}, {len(items)} trials, inputs in {time.time() - t0:.0f}s", flush=True)
    if args.workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(args.workers) as pool:
            rows = list(pool.imap_unordered(work, items, chunksize=8))
    else:
        rows = [work(x) for x in items]
    args.out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(args.out / "rows.parquet", index=False)
    print(f"shard done in {time.time() - t0:.0f}s", flush=True)
    return 0


# ---------------------------------------------------------------- report

def _fmt(v, f: str) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return "-" if not np.isfinite(v) else f.format(v)


def _line(name: str, r) -> str:
    g = lambda k: r.get(k, np.nan)  # noqa: E731
    years = " | ".join(_fmt(g(f"y{y}"), "{:+.0%}") for y in range(2016, 2027))
    return (f"| {name} | {_fmt(g('design_cagr'), '{:.1%}')} | {_fmt(g('design_sortino'), '{:.2f}')} | "
            f"{_fmt(g('design_dd'), '{:.1%}')} | {_fmt(g('judge_cagr'), '{:.1%}')} | {_fmt(g('judge_sortino'), '{:.2f}')} | "
            f"{_fmt(g('judge_dd'), '{:.1%}')} | {_fmt(g('judge_total'), '{:+.0%}')} | {_fmt(g('judge_worst_month'), '{:+.1%}')} | "
            f"{_fmt(g('judge_worst_day'), '{:+.1%}')} | {years} |")


HEAD = ("| {} | CAGR design | Sortino design | DD design | CAGR 2021-26 | Sortino 2021-26 | DD 2021-26 | total 2021-26 | "
        "worst month | worst day | " + " | ".join(str(y) for y in range(2016, 2027)) + " |")
SEP = "|" + "---|" * 21


def cmd_report(args) -> int:
    parts = sorted(args.parts.rglob("rows.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    expected = v10.QB_N + len(v10.other_trials())
    raw = _load(args.inputs / "qb.pkl")
    G = qb_globals(raw)
    O = other_globals(args.inputs)
    spy_td = O["etf"]["SPY"].dropna().pct_change(fill_method=None).dropna()
    spy_row = v10.row("SPY", "LT", spy_td, O["cash"])
    picks, series = {}, {}
    for fam in ("QB", "LT", "CT", "MR"):
        sub = df[df["family"] == fam]
        p = v10.pick(sub)
        if p is None:
            continue
        picks[fam] = p
        if fam == "QB":
            series[fam] = v10.qb_sim(v10.qb_cfg(int(p["id"])), G)
        else:
            t = next(x for x in v10.other_trials() if x["name"] == p["name"])
            series[fam] = (v10.lt_sim(t, O["etf"], O["cash"]) if fam == "LT" else v10.ct_sim(t, O["crypto"], O["cash_cal"])
                           if fam == "CT" else v10.mr_sim(t, O["mr"]))
    cal = pd.date_range(v10.JUDGE_START - pd.Timedelta(days=400), v10.LAST)
    R = pd.DataFrame({f: s.reindex(cal) for f, s in series.items()})
    trading = R.drop(columns=["CT"], errors="ignore").notna().any(axis=1)
    if "CT" in R:  # crypto trades every day: compound its weekend returns into the next trading day
        ct = (1 + R["CT"].fillna(0.0)).groupby(trading[::-1].cumsum()[::-1]).transform("prod") - 1
        R["CT"] = ct.where(trading)
    R = R[trading].loc[v10.JUDGE_START - pd.Timedelta(days=380):]
    cash = O["mr"]["cash_s"].reindex(R.index).fillna(0.0)
    combo = R.mean(axis=1)
    combo_rows = {n: {k: v for k, v in v10.row(n, "QB", r, cash).items() if not k.startswith("design_")}
                  for n, r in (("COMBO", combo), ("COMBO_L1.5", cp.leverage(combo, cash, 1.5)))}
    tri = df.copy()
    pool = np.concatenate([tri["judge_sharpe"].astype(float).to_numpy(), _prior_pool()])
    for fam, p in picks.items():
        picks[fam] = p.copy()
        picks[fam]["dsr"] = float(v7.deflated_sharpe([p["judge_sharpe"]], pool, [p["judge_days"]], [p["judge_skew"]],
                                                     [p["judge_kurtosis"]])[0])
    monsters = _monster_check(picks.get("QB"), G)
    text = render(df, picks, combo_rows, spy_row, monsters, expected, len(df))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "REPORT.md").write_text(text, encoding="utf-8")
    pd.DataFrame(series).to_csv(args.out / "pick_streams.csv")
    best = df.sort_values("design_cagr", ascending=False).groupby("family").head(2000)
    best.to_parquet(args.out / "top_rows.parquet", index=False)
    print(text[:20000], flush=True)
    return 0 if len(df) == expected else 1


def _prior_pool() -> np.ndarray:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k, v in prior.items() if isinstance(v, dict) for x in v.values()]
    pool += [x for x in prior["v7"] if x is not None]
    return np.asarray(pool, dtype=float)


def _monster_check(p, G: dict) -> dict:
    if p is None:
        return {}
    trades: list = []
    v10.qb_sim(v10.qb_cfg(int(p["id"])), G, trades=trades)
    tr = pd.DataFrame(trades, columns=["symbol", "entry_date", "exit_date", "entry", "exit", "fraction", "return"])
    tr["symbol"] = G["cols"][tr["symbol"].to_numpy(dtype=int)]
    mons = pd.read_csv(MONSTERS, parse_dates=["low_date", "half_date", "peak_date"])
    bought, capt = [], []
    for _, r in mons.iterrows():
        t = tr[(tr["symbol"] == r["symbol"]) & (tr["entry_date"] >= r["low_date"]) & (tr["entry_date"] <= r["peak_date"])]
        bought.append(len(t) > 0)
        capt.append(float(t["return"].max() / (r["multiple"] - 1)) if len(t) else np.nan)
    mons["bought_pick"], mons["captured_pick"] = bought, capt
    return {"bought": float(np.mean(bought)), "captured_median": float(np.nanmedian(capt)) if any(bought) else np.nan,
            "base_bought": float(mons["bought"].mean()), "base_captured_median":
            float(mons.loc[mons["bought"], "captured"].median())}


def render(df: pd.DataFrame, picks: dict, combos: dict, spy: dict, monsters: dict, expected: int, got: int) -> str:
    lines = ["# v10: every idea to close the gap (pre-registered)", "",
             f"{got:,} of {expected:,} configurations. Picks: best design-period CAGR with a design drawdown no deeper "
             f"than {v10.DD_CAP:.0%}; judged on 2021-01-01 to {v10.LAST.date()} (pass: CAGR above SPY and drawdown no "
             f"deeper than {v10.OWNER_DD:.0%}). Survivors-only stock list.", "",
             "## 1. Family picks and the combination", "", HEAD.format("strategy"), SEP]
    for fam, p in picks.items():
        ok = p["judge_cagr"] > spy.get("judge_cagr", np.nan) and p["judge_dd"] >= v10.OWNER_DD
        lines.append(_line(f"{fam}: {p['name']} (DSR {p['dsr']:.2f}, {'PASS' if ok else 'fail'})", p))
    for n, r in combos.items():
        ok = r.get("judge_cagr", -1) > spy.get("judge_cagr", np.nan) and r.get("judge_dd", -1) >= v10.OWNER_DD
        lines.append(_line(f"{n} ({'PASS' if ok else 'fail'})", r))
    lines.append(_line("SPY", spy))
    lines += ["", "## 2. Picks under other drawdown caps (design period)", "", HEAD.format("family / cap"), SEP]
    for fam in ("QB", "LT", "CT", "MR"):
        sub = df[df["family"] == fam]
        for cap in v10.DD_CAPS:
            p = v10.pick(sub, cap)
            if p is not None:
                lines.append(_line(f"{fam} {cap:.0%}: {p['name']}", p))
    lines += ["", "## 3. Plateau check: median 2021-2026 result of the 100 best design configurations (cap -40%)", "",
              "| family | n | median CAGR 2021-26 | median Sortino | median DD |", "|---|---|---|---|---|"]
    for fam in ("QB", "LT", "CT", "MR"):
        pl = v10.plateau(df[df["family"] == fam])
        lines.append(f"| {fam} | {pl['n']} | {_fmt(pl['cagr'], '{:.1%}')} | {_fmt(pl['sortino'], '{:.2f}')} | "
                     f"{_fmt(pl['dd'], '{:.1%}')} |")
    qb = df[df["family"] == "QB"]
    lines += ["", "## 4. QB: share of configurations that pass in 2021-2026, by lever (design DD cap -40%)", ""]
    ok = qb[qb["design_dd"].astype(float) >= v10.DD_CAP].copy()
    ok["pass"] = (ok["judge_cagr"].astype(float) > spy.get("judge_cagr", np.nan)) & (ok["judge_dd"].astype(float) >= v10.OWNER_DD)
    lines.append(f"Eligible {len(ok):,} of {len(qb):,}; passing {int(ok['pass'].sum()):,}.")
    if monsters:
        lines += ["", f"Monster moves (gap study list): the QB pick bought {monsters['bought']:.0%} (base book "
                  f"{monsters['base_bought']:.0%}), median share captured {_fmt(monsters['captured_median'], '{:.0%}')} "
                  f"(base {_fmt(monsters['base_captured_median'], '{:.0%}')})."]
    lines += ["", "## 5. The 30 best configurations by design CAGR within the -40% cap, all families", "",
              HEAD.format("configuration"), SEP]
    top = df[np.isfinite(df["design_cagr"].astype(float)) & (df["design_dd"].astype(float) >= v10.DD_CAP)]
    lines += [_line(r["name"], r) for _, r in top.nlargest(30, "design_cagr").iterrows()]
    return "\n".join(lines) + "\n"


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
    a.add_argument("--parts", type=Path, default=Path("outputs/v10_parts"))
    a.add_argument("--out", type=Path, default=Path("outputs/v10_report"))
    args = ap.parse_args()
    return {"prepare": cmd_prepare, "shard": cmd_shard, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
