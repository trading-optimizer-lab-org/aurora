#!/usr/bin/env python3
"""Phases 7b and 7c: build the five new intraday streams, combine all 13 streams,
test leverage and write the report.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_combination_plus.py run \
        --panel-dir outputs/stock_panel --cache outputs/alpaca --output-dir outputs/combination_plus

Reuses the minute cache and fetches only the new short candidates. See
docs/research/COMBINATION_PLUS_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import combination_plus as cp
from aurora.research import intraday_more as im
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


HEAD = ("| {} | 2016-18 Sortino | 2019-20 Sortino | 2016-20 Sortino | CAGR | max DD | total | worst month | "
        "positive months | DSR | passed |")


def _row(n: str, r) -> str:
    return (f"| {n} | {_fmt(r.get('p1_sortino_monthly'), '{:.2f}')} | {_fmt(r.get('p2_sortino_monthly'), '{:.2f}')} | "
            f"{_cells(r, 'all')} | {_fmt(r.get('deflated_sharpe'), '{:.2f}')} | "
            f"{'YES' if r.get('passed') is True or r.get('passed') == 1 else ('no' if 'passed' in r else '-')} |")


def render(agg: dict, corr: pd.DataFrame, counts: dict) -> str:
    df, ref, spy = agg["df"], agg["reference"], agg["spy"]
    lines = ["# Phases 7b and 7c: more intraday streams, leverage and the full combination (pre-registered, 18 trials)",
             "", f"{len(df)} of {agg['expected']} trials; deflated Sharpe over {agg['n_trials']:,} trials. 2016-2020. "
             "Survivorship bias NOT adjusted (hurts the short streams). Locked period from 2021-01-01 never read. "
             f"Short candidates: {counts}.", "",
             "## 1. Monthly-return correlations of the 13 streams and SPY, 2016-2020", "",
             "| | " + " | ".join(corr.columns) + " |", "|" + "---|" * (len(corr.columns) + 1)]
    for n, r in corr.iterrows():
        lines.append(f"| {n} | " + " | ".join(f"{v:+.2f}" for v in r) + " |")
    sep = "|" + "---|" * 11
    lines += ["", "## 2. The five new streams alone", "", HEAD.format("stream"), sep]
    lines += [_row(n, df.loc[n]) for n in im.NEW]
    lines += ["", "## 3. Combinations (7c)", "", HEAD.format("combination"), sep]
    lines.append(_row("INTRADAY_EQ (7a, reference)", ref))
    lines += [_row(n, df.loc[n]) for n in df.index if n.startswith(("INTRA8", "ALL13")) and "_L" not in n]
    lines += ["", "## 4. Leverage (account level)", "", HEAD.format("combination"), sep]
    lines += [_row(n, df.loc[n]) for n in df.index if "_L" in n]
    lines += ["", f"SPY: {_cells(spy, 'all')} (Sortino | CAGR | max DD | total | worst month | positive months).", "",
              "## 5. Pre-registered criteria on 2016-2020", "",
              f"Passed: {', '.join(agg['passed']) if agg['passed'] else 'none'}.", ""]
    return "\n".join(lines) + "\n"


def cmd_run(args) -> int:
    fetch = _script("run_qullamaggie_intraday")
    panel, bench = _script("run_stock_catalog").load_panel(args.panel_dir)
    industry = pd.read_csv(args.symbols).set_index("symbol")["industry"].reindex(panel["close"].columns)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    nasdaq = _script("run_qullamaggie").nasdaq_close(args.cache / "ixic.csv")
    ind = sc.indicators(panel, bench["gspc"], industry)
    ctx = q.context(panel, ind, nasdaq)
    need = qi.needed(qi.candidates(panel, ind, ctx))
    for day, syms in im.short_needed(im.short_candidates(panel, ind, ctx)).items():
        need[day] = sorted(set(need.get(day, [])) | set(syms))
    api = fetch.Alpaca()
    alp_daily = fetch.fetch_daily(api, args.cache, sorted({s for v in need.values() for s in v}))
    fetch.fetch_minutes(api, args.cache, need)
    print(f"Alpaca calls (only for data missing from the cache): {api.calls}", flush=True)
    new, counts = im.new_streams(panel, ind, ctx, nasdaq, cash_index, fetch.minute_loader(args.cache), alp_daily)
    del ind, ctx
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    spy = bench["spy"].reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    streams = pd.concat([cp.load_7a(), pd.DataFrame(new)], axis=1).sort_index()
    rows, corr = cp.results(streams, spy, cash)
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k, v in prior.items() if isinstance(v, dict) for x in v.values()]
    pool += [x for x in prior["v7"] if x is not None]
    agg = cp.aggregate(pd.DataFrame(rows), pool)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(new).to_csv(out / "streams_7b.csv")
    agg["df"].to_parquet(out / "results.parquet")
    corr.to_csv(out / "correlations.csv")
    text = render(agg, corr, counts)
    (out / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if len(agg["df"]) == agg["expected"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--output-dir", type=Path, default=Path("outputs/combination_plus"))
    args = ap.parse_args()
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
