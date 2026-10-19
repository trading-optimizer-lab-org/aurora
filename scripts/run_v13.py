#!/usr/bin/env python3
"""v13: an honest estimate without overfitting. Pre-registered in docs/research/V13_PREREGISTRATION.md.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_v13.py universe --panel-dir outputs/stock_panel \
        --nasdaq outputs/alpaca/ixic.csv --cache outputs/v13_adj --out outputs/v13
    ... python scripts/run_v13.py build --panel-dir outputs/stock_panel --nasdaq outputs/alpaca/ixic.csv \
        --inputs outputs/v10/inputs --cache outputs/alpaca_locked --out outputs/v13
    python scripts/run_v13.py analyze --inputs outputs/v10/inputs --out outputs/v13

Market data stays in the Actions cache; only strategy returns and the report are uploaded.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_stars as qs
from aurora.research import qullamaggie_wind as qw
from aurora.research import stock_catalog as sc
from aurora.research import stock_data_checks as checks
from aurora.research import stock_trades as st
from aurora.research import v10
from aurora.research import v11
from aurora.research import v13

ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"
EXCHANGES = ("NYSE", "NASDAQ", "AMEX")
SYMBOL = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
GAP_SESSIONS, BATCH = 20, 50
SYMBOLS = Path("docs/research/data/stock_catalog_symbols.csv")
V11_PICK = "QB_MIX3_XQ3_20_DAY_GAP_M1_R1_C35_G1_P0_M8"
FIELDS = ("open", "high", "low", "close", "volume")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LK, R10, V9 = _script("run_intraday_locked"), _script("run_v10"), _script("run_v9")


def _open() -> None:
    LK.LAST = v13.LAST
    LK.open_window()
    qi.START, qi.WARMUP, qi.END = v13.START, pd.Timestamp("2015-11-02"), v13.LAST


# ---------------------------------------------------------------- universe

def cmd_universe(args) -> int:
    nasdaq_old = LK.QS.nasdaq_close(args.nasdaq)  # read before the window opens (sealed series)
    _open()
    api = LK.FETCH.Alpaca()
    r = requests.get(ASSETS_URL, params={"asset_class": "us_equity"}, headers=api.headers, timeout=120)
    r.raise_for_status()
    assets = pd.DataFrame(r.json())
    keep = assets[assets["exchange"].isin(EXCHANGES) & assets["symbol"].astype(str).str.match(SYMBOL)]
    info = {"assets": int(len(assets)), "kept": int(len(keep)),
            "by_status": keep["status"].value_counts().to_dict(), "by_exchange": keep["exchange"].value_counts().to_dict()}
    print(json.dumps(info), flush=True)
    symbols = sorted(keep["symbol"].astype(str))
    folder = args.cache / "adj_daily"
    folder.mkdir(parents=True, exist_ok=True)
    limiter = V9.Limiter(V9.ALPACA_PER_MIN / 60)
    start, end = LK.FETCH._ny(pd.Timestamp("2015-01-01"), 0, 0), LK.FETCH._ny(v13.LAST, 20, 0)

    def one(k: int, batch: list[str]) -> None:
        path = folder / f"batch_{k:05d}.parquet"
        if path.exists():
            return
        params = {"symbols": ",".join(batch), "timeframe": "1Day", "start": start.isoformat(), "end": end.isoformat(),
                  "feed": "sip", "adjustment": "all", "limit": 10000}
        rows = []
        while True:
            body = V9._get(LK.FETCH.API, params, api.headers, limiter) or {}
            for sym, bars in (body.get("bars") or {}).items():
                for x in bars:
                    rows.append((sym, pd.Timestamp(x["t"]).tz_convert(LK.FETCH.NY).normalize().tz_localize(None),
                                 x["o"], x["h"], x["l"], x["c"], x["v"]))
            token = body.get("next_page_token")
            if not token:
                break
            params = {**params, "page_token": token}
        tmp = path.with_suffix(".tmp")
        pd.DataFrame(rows, columns=["symbol", "date", *FIELDS]).to_parquet(tmp, index=False)
        tmp.replace(path)

    batches = [symbols[i:i + BATCH] for i in range(0, len(symbols), BATCH)]
    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, k, b) for k, b in enumerate(batches)]
        for n, fut in enumerate(as_completed(futs)):
            fut.result()
            if n % 50 == 0:
                print(f"adjusted daily bars: {n}/{len(batches)} batches, {limiter.calls} calls", flush=True)
    df = pd.concat([pd.read_parquet(p) for p in sorted(folder.glob("batch_*.parquet"))], ignore_index=True)
    bench, nasdaq = _benchmarks_from(args, nasdaq_old)
    calendar = bench["gspc"].dropna().loc["2015-01-01":v13.LAST].index
    out: dict[str, dict[str, pd.Series]] = {f: {} for f in FIELDS}
    segmented, dropped = 0, 0
    for sym, g in df.groupby("symbol"):
        g = g.drop_duplicates("date").set_index("date").sort_index().reindex(calendar)
        have = np.flatnonzero(g["close"].notna().to_numpy())
        if len(have) < sc.MIN_HISTORY:
            continue
        cut = np.flatnonzero(np.diff(have) >= GAP_SESSIONS)
        if cut.size:
            segmented += 1
            g = g.iloc[have[cut[-1] + 1]:]
        part = g.dropna(subset=["close"])
        if len(part) < sc.MIN_HISTORY:
            continue
        chk = part.assign(adj_close=part["close"], stock_splits=0.0)
        if checks.is_severe(checks.check_series(chk, calendar)):
            dropped += 1
            continue
        name = str(sym).replace(".", "-")
        for f in FIELDS:
            out[f][name] = g[f].astype(np.float32)
    wide = {f: pd.DataFrame(out[f]).reindex(calendar) for f in FIELDS}
    dv = (wide["close"] * wide["volume"]).rolling(20, min_periods=20).mean()
    liquid = ((wide["close"] >= q.MIN_PRICE) & (dv >= q.MIN_DV)).any()  # the rules' own floor: no candidate is lost
    info["below_liquidity_floor"] = int((~liquid).sum())
    pdir = args.out / "panel"
    pdir.mkdir(parents=True, exist_ok=True)
    for f in FIELDS:
        wide[f].loc[:, liquid[liquid].index].to_parquet(pdir / f"{f}.parquet")
    bench.to_parquet(pdir / "benchmarks.parquet")
    nasdaq.rename("ixic").to_csv(pdir / "ixic.csv")
    info.update(alpaca_calls=limiter.calls, symbols_with_bars=int(df["symbol"].nunique()), kept_series=int(liquid.sum()),
                segmented=segmented, failed_checks=dropped)
    (args.out / "universe.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info), flush=True)
    return 0


def _benchmarks_from(args, nasdaq_old: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    _, bench = LK.PANEL.load_panel(args.panel_dir)
    gspc = LK._spliced(bench["gspc"].dropna(), LK._yahoo_series("^GSPC", "Adj Close"), "^GSPC")
    spy = LK._spliced(bench["spy"].dropna(), LK._yahoo_series("SPY", "Adj Close"), "SPY")
    nasdaq = LK._spliced(nasdaq_old, LK._yahoo_series("^IXIC", "Close"), "^IXIC")
    return pd.DataFrame({"gspc": gspc, "spy": spy}), nasdaq


# ---------------------------------------------------------------- build

def sim(g: dict, G: dict, regimes: dict[str, np.ndarray]) -> pd.Series:
    e, s, px, sd = G["sig"][g["set"]]
    m = e & regimes[g["regime"]][:, None]

    def df(a: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame(a, index=G["dates"], columns=G["cols"])

    return sc.simulate(G["panel"], G["ind"], df(m), df(s), g["exit"], G["cash"], G["rank"]["RS63"], start=v13.START,
                       entry_px=df(px), same_day_px=df(sd), risk=g["risk"], cap=g["cap"], max_gross=G["gross"][1.0],
                       max_pos=g["max_pos"] or None)["return"]


def _regimes(m1: pd.Series, nasdaq: pd.Series, dates: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    nz = nasdaq.reindex(dates.union(nasdaq.index)).ffill()
    n50 = (nz > nz.rolling(50, min_periods=50).mean()).shift(1, fill_value=False).reindex(dates).fillna(False)
    m1 = m1.reindex(dates).fillna(False).astype(bool)
    return {"M1": m1.to_numpy(), "N50": n50.to_numpy(bool), "M1_N50": (m1 & n50).to_numpy(bool)}


def train_model(panel_dir: Path, nasdaq_csv: Path) -> dict:
    """The breakout model exactly as in every earlier phase: trained on the sealed panel's 1995-2010 trades."""
    panel, bench = LK.PANEL.load_panel(panel_dir)
    panel = {k: v.loc[:"2020-12-31"] for k, v in panel.items()}
    nasdaq = LK.QS.nasdaq_close(nasdaq_csv).loc[:"2020-12-31"]
    industry = pd.read_csv(SYMBOLS).set_index("symbol")["industry"].reindex(panel["close"].columns)
    ind = sc.indicators(panel, bench["gspc"].loc[:"2020-12-31"], industry)
    ctx = q.context(panel, ind, nasdaq)
    feats = qs.features(panel, ind, nasdaq)
    e35, s35, px35 = q.breakout(panel, ind, ctx, "STOP", *q.BO_SELECTIONS["SCAN35"])
    stream = st.trade_list(panel, ind, e35.fillna(False).astype(bool), s35.astype(np.float32), qw.EXIT,
                           entry_px=px35.astype(np.float32))
    return qs.train_model(feats, stream)


def cmd_build(args) -> int:
    _open()
    # survivors-only universe: the inputs of the v11 run, which published the gate value
    G_s = R10.qb_globals(R10._load(args.inputs / "qb.pkl"))
    nasdaq_ext = pd.read_csv(args.out / "panel" / "ixic.csv", index_col=0, parse_dates=True).iloc[:, 0]
    reg_s = _regimes(pd.Series(G_s["m1"], index=G_s["dates"]), nasdaq_ext, G_s["dates"])
    pick = {"set": "MIX3", "exit": "XQ3_20", "stop": "DAY", "rank": "GAP", "regime": "M1", "risk": 0.01, "cap": 0.35,
            "gross": 1.0, "pyramid": False, "max_pos": 8}
    gate_r = v10.qb_sim(pick, G_s)
    m = sc.metrics(gate_r.loc[v11.JUDGE[0]:v11.JUDGE[1]], G_s["cash"])
    ref = float(pd.read_csv("docs/research/data/v11_shortlist.csv").set_index("name").at[V11_PICK, "judge_sortino"])
    print(f"gate: v11 pick 2021-2026 Sortino {m['sortino_monthly']:.6f} vs published {ref:.6f}", flush=True)
    if abs(m["sortino_monthly"] - ref) > 1e-9:
        print("GATE FAILED", flush=True)
        return 1
    cfgs = v13.grid()
    R_s = pd.DataFrame({v13.cname(g): sim(g, G_s, reg_s) for g in cfgs})
    dates_s, cash_s = G_s["dates"], G_s["cash"]
    del G_s, reg_s
    print("survivors universe done", flush=True)
    # survivorship-free universe
    model = train_model(args.panel_dir, args.nasdaq)
    panel, bench = LK.PANEL.load_panel(args.out / "panel")
    nasdaq = pd.read_csv(args.out / "panel" / "ixic.csv", index_col=0, parse_dates=True).iloc[:, 0]
    cash_index = LK.MAB.tbill_index({}).loc[:v13.LAST]
    industry = pd.read_csv(SYMBOLS).set_index("symbol")["industry"].reindex(panel["close"].columns)
    ind = sc.indicators(panel, bench["gspc"], industry)
    ctx = q.context(panel, ind, nasdaq)
    cands = qi.candidates(panel, ind, ctx)
    need = qi.needed(cands)
    del cands
    api = LK.FETCH.Alpaca()
    alp_daily = LK.FETCH.fetch_daily(api, args.cache, sorted({s for v in need.values() for s in v}))
    LK.FETCH.fetch_minutes(api, args.cache, need)
    print(f"Alpaca calls for the new candidates: {api.calls}", flush=True)
    feats = qs.features(panel, ind, nasdaq)
    setup5, _ = q.breakout_setup(panel, ind, ctx, *q.BO_SELECTIONS["SCAN5"])
    tiebreak = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True).shift(1)
    score = qs.model_score(feats, model)
    kept = {n: qs.top_n(score, setup5, tiebreak, n) for n in (1, 3)}
    del feats, score
    prep = qi.prepare(panel, ind, ctx, cash_index, LK.FETCH.minute_loader(args.cache), alp_daily)
    _, ie, _ = qs.intraday_signals(prep, None)
    sigs = {"EP_N1": ie, "MIX1": qs.intraday_signals(prep, kept[1])[2], "MIX3": qs.intraday_signals(prep, kept[3])[2]}
    dates, cols = prep["panel"]["close"].index, prep["panel"]["close"].columns
    shape = (len(dates), len(cols))
    G_n = {"panel": {k: v.astype(np.float32) for k, v in prep["panel"].items()},
           "ind": {k: prep["ind"][k].astype(np.float32) for k in R10.IND_KEYS}, "cash": prep["cash"], "dates": dates,
           "cols": cols, "rank": {"RS63": prep["rank"]}, "gross": {1.0: pd.Series(1.0, index=dates)},
           "sig": {k: v10.dense(v10.sparse(v), shape) for k, v in sigs.items()}}
    reg_n = _regimes(prep["m1"], nasdaq, dates)
    R_n = pd.DataFrame({v13.cname(g): sim(g, G_n, reg_n) for g in cfgs})
    print("survivorship-free universe done", flush=True)
    O = R11_globals(args.inputs)
    CT = pd.DataFrame({b: v11.to_trading(O["crypto"][b].dropna(), dates_s) for b in v10.CT_BASES})
    LT = pd.DataFrame({t["name"]: v10.lt_sim(t, O["etf"], O["cash"]) for t in v10.other_trials() if t["family"] == "LT"})
    args.out.mkdir(parents=True, exist_ok=True)
    R_s.astype(np.float32).to_parquet(args.out / "streams_survivors.parquet")
    R_n.astype(np.float32).to_parquet(args.out / "streams_full.parquet")
    CT.astype(np.float32).to_parquet(args.out / "streams_ct.parquet")
    LT.reindex(dates_s).astype(np.float32).to_parquet(args.out / "streams_lt.parquet")
    cash_s.to_frame("cash").to_parquet(args.out / "cash.parquet")
    O["etf"]["SPY"].pct_change(fill_method=None).reindex(dates_s).to_frame("SPY").to_parquet(args.out / "spy.parquet")
    print(json.dumps({"full_universe_columns": len(cols), "gate": m["sortino_monthly"]}), flush=True)
    return 0


def R11_globals(inputs: Path) -> dict:
    return R10.other_globals(inputs)


# ---------------------------------------------------------------- analyze

def _f(v, fmt: str) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return "-" if not np.isfinite(v) else fmt.format(v)


HEAD = ("| {} | Sortino 2018-26 | Sortino 2018-21 | Sortino 2022-26 | CAGR | max DD | total | "
        + " | ".join(str(y) for y in v13.WF_YEARS) + " |")
SEP = "|" + "---|" * (7 + len(v13.WF_YEARS))


def _line(n: str, m: dict) -> str:
    ys = " | ".join(_f(m["yearly"].get(y), "{:+.0%}") for y in v13.WF_YEARS)
    return (f"| {n} | {_f(m['wf_sortino'], '{:.2f}')} | {_f(m['h1_sortino'], '{:.2f}')} | {_f(m['h2_sortino'], '{:.2f}')} | "
            f"{_f(m['wf_cagr'], '{:.1%}')} | {_f(m['wf_dd'], '{:.1%}')} | {_f(m['wf_total'], '{:+.0%}')} | {ys} |")


def cmd_analyze(args) -> int:
    cash = pd.read_parquet(args.out / "cash.parquet")["cash"]
    spy = pd.read_parquet(args.out / "spy.parquet")["SPY"]
    CT = pd.read_parquet(args.out / "streams_ct.parquet")
    LT = pd.read_parquet(args.out / "streams_lt.parquet")
    nb = v13.neighbours(v13.grid())
    ct_picks = v13.wf_family(CT, cash, [[i] for i in range(CT.shape[1])])
    lt_picks = v13.wf_family(LT, cash, v13.lt_neighbours(list(LT.columns)))
    lines = ["# v13: an honest estimate without overfitting (pre-registered)", "",
             "144 configurations fixed in advance; yearly walk-forward 2018-2026 chosen only on earlier data by plateau "
             "score; combinatorial cross-validation (252 splits) for the PBO. Target: monthly Sortino 4 in the "
             "walk-forward record, at least 3 in both halves, PBO below 20%.", ""]
    universe = json.loads((args.out / "universe.json").read_text(encoding="utf-8"))
    lines += [f"Survivorship-free universe: {universe}", ""]
    verdict = {}
    for label, path in (("FULL (survivorship-free)", "streams_full.parquet"), ("SURVIVORS (earlier panel)",
                                                                              "streams_survivors.parquet")):
        R = pd.read_parquet(args.out / path).astype(float)
        wf = v13.walk_forward(R, cash, nb)
        div = v13.wf_div(R, wf, [(CT.astype(float), ct_picks), (LT.astype(float), lt_picks)])
        cpcv = v13.cpcv(R, cash, nb)
        res = {"WF_ONE": v13.stats(wf["one"], cash), "WF_ENS5": v13.stats(wf["ens"], cash), "WF_DIV": v13.stats(div, cash)}
        ok = {k: bool((m["wf_sortino"] or 0) >= 4 and (m["h1_sortino"] or 0) >= 3 and (m["h2_sortino"] or 0) >= 3
                      and cpcv["pbo"] < 0.2) for k, m in res.items()}
        verdict[label] = ok
        lines += [f"## {label}", "", HEAD.format("strategy"), SEP]
        lines += [_line(f"{k} ({'SUCCESS' if ok[k] else 'not reached'})", m) for k, m in res.items()]
        lines.append(_line("SPY", v13.stats(spy, cash)))
        lines += ["", f"CPCV over {cpcv['splits']} splits: PBO {cpcv['pbo']:.0%}; test Sortino of the chosen "
                  f"configuration: median {cpcv['test_median']:.2f}, 10th-90th percentile {cpcv['test_p10']:.2f} to "
                  f"{cpcv['test_p90']:.2f}, share >= 4: {cpcv['share_test_ge4']:.0%}.", "",
                  "Yearly choices (WF_ONE): " + "; ".join(f"{y}: {p['one']} ({p['score']:.2f})" for y, p in wf["picks"].items()),
                  ""]
    lines += ["Diversifiers chosen each year (score, kept if >= 1.5): crypto "
              + "; ".join(f"{y}: {n} ({s:.2f})" for y, (n, s) in ct_picks.items()) + "; index trend "
              + "; ".join(f"{y}: {n} ({s:.2f})" for y, (n, s) in lt_picks.items()) + ".", ""]
    text = "\n".join(lines) + "\n"
    (args.out / "REPORT.md").write_text(text, encoding="utf-8")
    (args.out / "verdict.json").write_text(json.dumps(verdict, indent=1), encoding="utf-8")
    print(text, flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("universe", "build", "analyze"):
        a = sub.add_parser(name)
        a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
        a.add_argument("--nasdaq", type=Path, default=Path("outputs/alpaca/ixic.csv"))
        a.add_argument("--inputs", type=Path, default=Path("outputs/v10/inputs"))
        a.add_argument("--cache", type=Path, default=Path("outputs/v13_adj" if name == "universe" else "outputs/alpaca_locked"))
        a.add_argument("--out", type=Path, default=Path("outputs/v13"))
    args = ap.parse_args()
    return {"universe": cmd_universe, "build": cmd_build, "analyze": cmd_analyze}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
