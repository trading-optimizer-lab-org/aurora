#!/usr/bin/env python3
"""One-shot locked-period test of the phase 7 intraday combination INTRADAY_EQ
(EP_EARN + EP_NEWS + BO_TOP3) on 2021-01-04 to 2026-09-30.
Pre-registered in docs/research/INTRADAY_LOCKED_PREREGISTRATION.md.

    python scripts/run_intraday_locked.py rehearse --panel-dir outputs/stock_panel --cache outputs/alpaca \
        --sec-cache outputs/sec
    python scripts/run_intraday_locked.py prepare --panel-dir outputs/stock_panel --out outputs/locked \
        --cache outputs/alpaca_locked --sec-cache outputs/sec_locked
    python scripts/run_intraday_locked.py evaluate --out outputs/locked --cache outputs/alpaca_locked \
        --sec-cache outputs/sec_locked

``rehearse`` recomputes the three streams for 2016-2020 from the caches and must match the published ones.
``prepare`` extends the data to 2026-09-30 and fetches the bars and filings (no strategy result). ``evaluate``
computes the result once. Market data stays in the Actions cache.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import combination as cb
from aurora.research import combination_plus as cp
from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import stock_catalog as sc
from aurora.research import stock_data_checks as checks
from aurora.research import v9_common as c

FIRST, LAST = pd.Timestamp("2021-01-04"), pd.Timestamp("2026-09-30")
WARMUP = pd.Timestamp("2020-11-02")
DOWNLOAD_FROM = pd.Timestamp("2020-09-01")
SPLICE = (pd.Timestamp("2020-10-01"), pd.Timestamp("2020-12-31"))
MIN_OVERLAP, MAX_RATIO_DEV, TOLERANCE = 40, 0.01, 1e-9
STREAMS = ("EP_EARN", "EP_NEWS", "BO_TOP3")
REFERENCE_2016_2020 = {"sortino_monthly": 4.92, "cagr": 0.165, "max_drawdown": -0.077}
FIELDS = ("open", "high", "low", "close", "volume")
SYMBOLS = Path("docs/research/data/stock_catalog_symbols.csv")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FETCH, CAT = _script("run_qullamaggie_intraday"), _script("run_qullamaggie_catalyst")
PANEL, BUILD = _script("run_stock_catalog"), _script("build_stock_panel")
MAB, QS = _script("run_multiasset_baselines"), _script("run_qullamaggie")


def streams(panel: dict, bench: pd.DataFrame, cash_index: pd.Series, nasdaq: pd.Series, cache: Path,
            sec_cache: Path, fetch_only: bool = False) -> tuple[dict[str, pd.Series], dict]:
    """The three phase 7a intraday streams, built exactly as in scripts/run_combination.py."""
    industry = pd.read_csv(SYMBOLS).set_index("symbol")["industry"].reindex(panel["close"].columns)
    ind = sc.indicators(panel, bench["gspc"], industry)
    ctx = q.context(panel, ind, nasdaq)
    cands = qi.candidates(panel, ind, ctx)
    need = qi.needed(cands)
    ep_symbols = sorted(cands["IEP_N0"].columns[cands["IEP_N0"].fillna(False).astype(bool).any()])
    info = {"candidate_days": int(sum(len(v) for v in need.values())), "ep_symbols": len(ep_symbols)}
    del cands
    api = FETCH.Alpaca()
    alp_daily = FETCH.fetch_daily(api, cache, sorted({s for v in need.values() for s in v}))
    FETCH.fetch_minutes(api, cache, need)
    sec = CAT.Sec()
    ciks = CAT.ticker_ciks(sec, sec_cache)
    cik = {s: ciks[s.upper()] for s in ep_symbols if s.upper() in ciks}
    earnings: dict[str, list[pd.Timestamp]] = {}
    for s, k in sorted(cik.items()):
        dts = CAT.earnings_dates(sec, sec_cache, k)
        if dts is not None:
            earnings[s] = [pd.Timestamp(d) for d in dts]
    info.update(alpaca_calls=api.calls, sec_calls=sec.calls, sec_covered=len(earnings))
    print(json.dumps(info), flush=True)
    if fetch_only:
        return {}, info
    # Revenue frames only feed the EARNG label, which none of the three streams uses.
    out = cb.intraday_streams(panel, ind, ctx, nasdaq, cash_index, FETCH.minute_loader(cache), alp_daily,
                              earnings, set(earnings), cik, {})
    return out, info


def cmd_rehearse(args) -> int:
    panel, bench = PANEL.load_panel(args.panel_dir)
    if panel["close"].index.max() >= sc.LOCKED_START:
        raise ValueError("the rehearsal must run on the sealed panel")
    cash_index = MAB.tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    nasdaq = QS.nasdaq_close(args.cache / "ixic.csv")
    out, _ = streams(panel, bench, cash_index, nasdaq, args.cache, args.sec_cache)
    ref = cp.load_7a()
    bad = []
    for k in STREAMS:
        a = out[k].reindex(ref.index).loc[qi.START:qi.END]
        b = ref[k].loc[qi.START:qi.END]
        same_nan = bool((a.isna() == b.isna()).all())
        worst = float((a - b).abs().max())
        print(f"{k}: max difference {worst:.3e} over {int(b.notna().sum())} sessions, same gaps {same_nan}", flush=True)
        if not same_nan or not np.isfinite(worst) or worst > TOLERANCE:
            bad.append(k)
    if bad:
        print(f"REHEARSAL FAILED for {bad}: nothing from 2021+ will be read", flush=True)
        return 1
    print("rehearsal passed: the code reproduces the published 2016-2020 streams", flush=True)
    return 0


def open_window() -> None:
    """Lift the 2021 guards in this process only, to the pre-registered end date."""
    sc.LOCKED_START = LAST + pd.Timedelta(days=1)
    FETCH.LAST = LAST
    CAT.FIRST, CAT.LAST = "2020-11-01", str(LAST.date())
    BUILD.START = DOWNLOAD_FROM
    qi.START, qi.END, qi.WARMUP = FIRST, LAST, WARMUP
    qi.PERIODS = {"all": (FIRST, LAST)}


def splice_factor(old: pd.Series, new: pd.Series) -> float | None:
    """Median of old / new over October-December 2020, or None when they do not agree within 1%."""
    both = pd.concat([old, new], axis=1).loc[SPLICE[0]:SPLICE[1]].dropna()
    both = both[(both.iloc[:, 0] > 0) & (both.iloc[:, 1] > 0)]
    if len(both) < MIN_OVERLAP:
        return None
    ratio = both.iloc[:, 0] / both.iloc[:, 1]
    f = float(ratio.median())
    return f if float((ratio / f - 1).abs().max()) <= MAX_RATIO_DEV else None


def _yahoo_series(ticker: str, column: str) -> pd.Series:
    import yfinance as yf

    raw = yf.download(ticker, start=str(DOWNLOAD_FROM.date()), end=str(sc.LOCKED_START.date()), auto_adjust=False,
                      progress=False)
    s = raw[column]
    s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s.loc[:LAST].dropna()


def _spliced(old: pd.Series, new: pd.Series, name: str) -> pd.Series:
    f = splice_factor(old, new)
    if f is None:
        raise RuntimeError(f"cannot splice {name}: the 2020 overlap does not agree")
    return pd.concat([old.loc[:SPLICE[1]], new.loc[SPLICE[1] + pd.Timedelta(days=1):] * f])


def extend_panel(panel: dict, raw: dict[str, pd.DataFrame], calendar: pd.DatetimeIndex) -> tuple[dict, dict]:
    """The cached panel with the 2021+ rows of every symbol that splices cleanly; the coverage counts."""
    new_rows = calendar[calendar > SPLICE[1]]
    cols: dict[str, dict[str, pd.Series]] = {f: {} for f in FIELDS}
    cov = {"inactive_end_2020": 0, "no_yahoo_data": 0, "splice_mismatch": 0, "failed_checks": 0, "spliced": 0}
    for s in panel["close"].columns:
        old_c = panel["close"][s].loc[SPLICE[0]:SPLICE[1]]
        if old_c.notna().sum() < MIN_OVERLAP:
            cov["inactive_end_2020"] += 1
            continue
        df = raw.get(s)
        if df is None or df.empty:
            cov["no_yahoo_data"] += 1
            continue
        adj = (df["adj_close"] / df["close"]).replace([np.inf, -np.inf], np.nan)
        fp = splice_factor(panel["close"][s], df["close"] * adj)
        if fp is None:
            cov["splice_mismatch"] += 1
            continue
        part = df.loc[df.index > SPLICE[1]]
        if part.empty or checks.is_severe(checks.check_series(part, new_rows)):
            cov["failed_checks"] += 1
            continue
        vr = (panel["volume"][s] / df["volume"]).loc[SPLICE[0]:SPLICE[1]].replace([np.inf, -np.inf], np.nan)
        vr = vr[vr > 0].dropna()
        fv = float(vr.median()) if len(vr) else 1.0
        for f in ("open", "high", "low", "close"):
            cols[f][s] = part[f] * adj.loc[part.index] * fp
        cols["volume"][s] = part["volume"] * fv
        cov["spliced"] += 1
    out = {}
    for f in FIELDS:
        extra = pd.DataFrame(cols[f]).reindex(index=new_rows, columns=panel[f].columns).astype(np.float32)
        out[f] = pd.concat([panel[f].loc[:SPLICE[1]], extra])
    return out, cov


def cmd_prepare(args) -> int:
    panel, bench = PANEL.load_panel(args.panel_dir)
    if not args.nasdaq.exists():
        raise SystemExit(f"{args.nasdaq} missing: the Nasdaq series of phase 7 is needed unchanged")
    nasdaq_old = QS.nasdaq_close(args.nasdaq)
    open_window()
    gspc = _spliced(bench["gspc"].dropna(), _yahoo_series("^GSPC", "Adj Close"), "^GSPC")
    spy = _spliced(bench["spy"].dropna(), _yahoo_series("SPY", "Adj Close"), "SPY")
    nasdaq = _spliced(nasdaq_old, _yahoo_series("^IXIC", "Close"), "^IXIC")
    calendar = gspc.index
    syms = pd.read_csv(SYMBOLS)
    syms = syms[syms["symbol"].isin(panel["close"].columns)]
    got = BUILD.download_yahoo(syms["yfinance_symbol"].tolist())
    back = dict(zip(syms["yfinance_symbol"], syms["symbol"]))
    raw = {back[t]: df.loc[:LAST] for t, df in got.items()}
    ext, cov = extend_panel(panel, raw, calendar)
    out = args.out / "panel"
    out.mkdir(parents=True, exist_ok=True)
    for f in FIELDS:
        ext[f].to_parquet(out / f"{f}.parquet")
    pd.DataFrame({"gspc": gspc, "spy": spy}).to_parquet(out / "benchmarks.parquet")
    nasdaq.rename("ixic").to_csv(out / "ixic.csv")
    cov["calendar_last"] = str(calendar.max().date())
    if calendar.max() < LAST - pd.Timedelta(days=5):
        raise RuntimeError(f"benchmark data ends {calendar.max().date()}, before {LAST.date()}")
    panel2, bench2 = PANEL.load_panel(out)
    cash_index = MAB.tbill_index({}).loc[:LAST]
    _, info = streams(panel2, bench2, cash_index, QS.nasdaq_close(out / "ixic.csv"), args.cache, args.sec_cache,
                      fetch_only=True)
    (args.out / "coverage.json").write_text(json.dumps({**cov, **info}, indent=1), encoding="utf-8")
    print(json.dumps(cov), flush=True)
    return 0


def _yearly(r: pd.Series) -> dict[str, float]:
    return {str(y): float((1 + g).prod() - 1) for y, g in r.groupby(r.index.year)}


def cmd_evaluate(args) -> int:
    open_window()
    panel, bench = PANEL.load_panel(args.out / "panel")
    cash_index = MAB.tbill_index({}).loc[:LAST]
    out, info = streams(panel, bench, cash_index, QS.nasdaq_close(args.out / "panel" / "ixic.csv"), args.cache,
                        args.sec_cache)
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0).loc[FIRST:LAST]
    S = pd.DataFrame(out).loc[FIRST:LAST, list(STREAMS)].fillna(0.0)
    eq = S.mean(axis=1)
    spy = bench["spy"].reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0).loc[FIRST:LAST]
    series = {"INTRADAY_EQ": eq, "INTRADAY_EQ_L2": cp.leverage(eq, cash, 2.0), **{k: S[k] for k in STREAMS},
              "SPY": spy}
    period = {"locked": (FIRST, LAST)}
    rows = {n: {**c.evaluate(r, cash, period), "yearly": _yearly(r)} for n, r in series.items()}
    main, ref = rows["INTRADAY_EQ"], rows["SPY"]
    crit = sc.criteria({"sortino_monthly": main["locked_sortino_monthly"], "cagr": main["locked_cagr"],
                        "max_drawdown": main["locked_max_drawdown"]}, {"cagr": ref["locked_cagr"]})
    coverage = json.loads((args.out / "coverage.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(series).to_csv(args.out / "streams_locked.csv")
    (args.out / "results.json").write_text(json.dumps({"rows": rows, "criteria": crit, "coverage": coverage,
                                                       "info": info}, indent=1, default=float), encoding="utf-8")
    text = render(rows, crit, coverage)
    (args.out / "LOCKED.md").write_text(text, encoding="utf-8")
    print(text, flush=True)
    return 0


def _f(v, fmt: str) -> str:
    return "-" if v is None or not np.isfinite(float(v)) else fmt.format(float(v))


def render(rows: dict, crit: dict, coverage: dict) -> str:
    verdict = "PASSED" if all(crit.values()) else "FAILED"
    lines = [f"# Locked test of INTRADAY_EQ, 2021-01-04 to 2026-09-30: {verdict}", "",
             "One-shot test pre-registered in docs/research/INTRADAY_LOCKED_PREREGISTRATION.md. Survivorship: "
             f"{coverage.get('spliced')} symbols spliced into 2021+, {coverage.get('no_yahoo_data')} active at the end of "
             f"2020 had no Yahoo data (delisted or renamed), {coverage.get('splice_mismatch')} did not splice, "
             f"{coverage.get('failed_checks')} failed the data checks; companies listed after 2020 are not included.", "",
             "| stream | monthly Sortino | CAGR | max DD | total | worst month | worst day | positive months |",
             "|---|---|---|---|---|---|---|---|"]
    for n, r in rows.items():
        lines.append(f"| {n} | {_f(r.get('locked_sortino_monthly'), '{:.2f}')} | {_f(r.get('locked_cagr'), '{:.1%}')} | "
                     f"{_f(r.get('locked_max_drawdown'), '{:.1%}')} | {_f(r.get('locked_total'), '{:+.0%}')} | "
                     f"{_f(r.get('locked_worst_month'), '{:+.1%}')} | {_f(r.get('locked_worst_day'), '{:+.1%}')} | "
                     f"{_f(r.get('locked_positive_months'), '{:.0%}')} |")
    ref = REFERENCE_2016_2020
    lines += ["", f"2016-2020 reference for INTRADAY_EQ: Sortino {ref['sortino_monthly']:.2f}, CAGR {ref['cagr']:.1%}, "
              f"max DD {ref['max_drawdown']:.1%}.", "", "## Yearly returns", "",
              "| stream | " + " | ".join(rows["INTRADAY_EQ"]["yearly"]) + " |",
              "|---|" + "---|" * len(rows["INTRADAY_EQ"]["yearly"])]
    for n, r in rows.items():
        lines.append(f"| {n} | " + " | ".join(_f(v, "{:+.1%}") for v in r["yearly"].values()) + " |")
    lines += ["", "## Pre-registered criteria (INTRADAY_EQ at 1x)", ""]
    lines += [f"- {k}: {'yes' if v else 'NO'}" for k, v in crit.items()]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("rehearse", "prepare", "evaluate"):
        a = sub.add_parser(name)
        a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
        a.add_argument("--out", type=Path, default=Path("outputs/locked"))
        a.add_argument("--cache", type=Path, default=Path("outputs/alpaca" if name == "rehearse" else "outputs/alpaca_locked"))
        a.add_argument("--sec-cache", type=Path, default=Path("outputs/sec" if name == "rehearse" else "outputs/sec_locked"))
        a.add_argument("--nasdaq", type=Path, default=Path("outputs/alpaca/ixic.csv"))
    args = ap.parse_args()
    return {"rehearse": cmd_rehearse, "prepare": cmd_prepare, "evaluate": cmd_evaluate}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
