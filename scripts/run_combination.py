#!/usr/bin/env python3
"""Phase 7a: rebuild the best strategy streams, combine them, write the report.

    SEC_USER_AGENT=... APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_combination.py run \
        --panel-dir outputs/stock_panel --cache outputs/alpaca --sec-cache outputs/sec --output-dir outputs/combination

Reuses the minute and SEC caches. See docs/research/COMBINATION_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import combination as cb
from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import stock_catalog as sc

PRIOR = Path("docs/research/data/stock_catalog_prior_sharpes.json")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fmt(v, f: str) -> str:
    return "-" if v is None or v != v else f.format(v)


def _cells(r, p: str) -> str:
    return (f"{_fmt(r.get(f'{p}_sortino_monthly'), '{:.2f}')} | {_fmt(r.get(f'{p}_cagr'), '{:.1%}')} | "
            f"{_fmt(r.get(f'{p}_max_drawdown'), '{:.1%}')} | {_fmt(r.get(f'{p}_total'), '{:+.0%}')} | "
            f"{_fmt(r.get(f'{p}_worst_month'), '{:+.1%}')} | {_fmt(r.get(f'{p}_positive_months'), '{:.0%}')}")


def render(agg: dict, corr: pd.DataFrame) -> str:
    st, co, spy = agg["streams"], agg["combo"], agg["spy"]
    head = "| {} | Sortino | CAGR | max DD | total | worst month | positive months |"
    lines = ["# Phase 7a: combining the best strategy streams (pre-registered, 12 combinations)", "",
             f"Deflated Sharpe over {agg['n_trials']:,} trials. Survivorship bias NOT adjusted. Locked period from "
             "2021-01-01 never read. Risk-parity volatilities are floored at 2% a year.", "",
             "## 1. Monthly-return correlations, 2016-2020", "",
             "| | " + " | ".join(corr.columns) + " |", "|" + "---|" * (len(corr.columns) + 1)]
    for n, r in corr.iterrows():
        lines.append(f"| {n} | " + " | ".join(f"{v:+.2f}" for v in r) + " |")
    lines += ["", "## 2. Streams alone, 2016-2020", "", head.format("stream"), "|" + "---|" * 7]
    for n, r in st.iterrows():
        lines.append(f"| {n} | {_cells(r, 'all')} |")
    lines.append(f"| SPY | {_cells(spy, 'all')} |")
    lines += ["", "Daily streams over the long history (1995-2010 / 2011-2020): " + "; ".join(
        f"{n} Sortino {_fmt(r.get('train_sortino_monthly'), '{:.2f}')} / {_fmt(r.get('validation_sortino_monthly'), '{:.2f}')}"
        for n, r in st.iterrows() if n in cb.DAILY) + ".", "",
        "## 3. Combinations, 2016-2020", "",
        "| combination | Sortino | CAGR | max DD | total | worst month | positive months | DSR | passed |",
        "|" + "---|" * 9]
    for n, r in co.iterrows():
        lines.append(f"| {n} | {_cells(r, 'all')} | {_fmt(r['deflated_sharpe'], '{:.2f}')} | "
                     f"{'YES' if r['passed'] else 'no'} |")
    lines += ["", "## 4. DAILY set over the long history", "",
              "| combination | 1995-2010 Sortino | CAGR | max DD | total | worst month | positive | 2011-2020 Sortino | "
              "CAGR | max DD | total | worst month | positive |", "|" + "---|" * 13]
    for n, r in co[co.index.str.startswith("DAILY")].iterrows():
        lines.append(f"| {n} | {_cells(r, 'train')} | {_cells(r, 'validation')} |")
    lines.append(f"| SPY | {_cells(spy, 'train')} | {_cells(spy, 'validation')} |")
    lines += ["", "## 5. Pre-registered criteria (2016-2020; 2011-2020 for DAILY)", "",
              f"Passed: {', '.join(agg['passed']) if agg['passed'] else 'none'}.", ""]
    return "\n".join(lines) + "\n"


def cmd_run(args) -> int:
    fetch, cat = _script("run_qullamaggie_intraday"), _script("run_qullamaggie_catalyst")
    sec = cat.Sec()
    panel, bench = _script("run_stock_catalog").load_panel(args.panel_dir)
    industry = pd.read_csv(args.symbols).set_index("symbol")["industry"].reindex(panel["close"].columns)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    nasdaq = _script("run_qullamaggie").nasdaq_close(args.cache / "ixic.csv")
    streams: dict[str, pd.Series] = {}
    for name, spec in cb.V7_STREAMS.items():
        streams[name] = cb.v7_stream(panel, bench["gspc"], industry, cash_index, *spec)
        print(f"stream {name} done", flush=True)
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = sc.indicators(panel, bench["gspc"], industry)
    ctx = q.context(panel, ind, nasdaq)
    streams["PARA_SHORT"] = cb.para_short_stream(panel, ind, ctx, cash)
    cands = qi.candidates(panel, ind, ctx)
    need = qi.needed(cands)
    ep_symbols = sorted(cands["IEP_N0"].columns[cands["IEP_N0"].fillna(False).astype(bool).any()])
    del cands
    api = fetch.Alpaca()
    alp_daily = fetch.fetch_daily(api, args.cache, sorted({s for v in need.values() for s in v}))
    fetch.fetch_minutes(api, args.cache, need)
    ciks = cat.ticker_ciks(sec, args.sec_cache)
    cik = {s: ciks[s.upper()] for s in ep_symbols if s.upper() in ciks}
    earnings = {}
    for s, c in sorted(cik.items()):
        dts = cat.earnings_dates(sec, args.sec_cache, c)
        if dts is not None:
            earnings[s] = [pd.Timestamp(d) for d in dts]
    revenue = cat.revenue_frames(sec, args.sec_cache)
    print(f"Alpaca calls {api.calls}, SEC calls {sec.calls} (only for data missing from the caches)", flush=True)
    streams.update(cb.intraday_streams(panel, ind, ctx, nasdaq, cash_index, fetch.minute_loader(args.cache), alp_daily,
                                       earnings, set(earnings), cik, revenue))
    del ind, ctx
    S = pd.DataFrame(streams).sort_index()
    spy = bench["spy"].reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    rows, corr = cb.results(S, spy, cash)
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k, v in prior.items() if isinstance(v, dict) for x in v.values()]
    pool += [x for x in prior["v7"] if x is not None]
    agg = cb.aggregate(pd.DataFrame(rows), pool)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    S.to_parquet(out / "streams.parquet")
    pd.concat([agg["streams"], agg["combo"]]).to_parquet(out / "results.parquet")
    corr.to_csv(out / "correlations.csv")
    text = render(agg, corr)
    (out / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--sec-cache", type=Path, default=Path("outputs/sec"))
    a.add_argument("--output-dir", type=Path, default=Path("outputs/combination"))
    args = ap.parse_args()
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
