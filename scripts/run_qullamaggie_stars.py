#!/usr/bin/env python3
"""Qullamaggie phase 3 ("5-star" setup selection): 24 trials, then the report.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_qullamaggie_stars.py run \
        --panel-dir outputs/stock_panel --cache outputs/alpaca --output-dir outputs/qullamaggie_stars

Reuses the phase 1 minute cache and only downloads what is missing. See
docs/research/QULLAMAGGIE_STARS_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_stars as qs
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


def _cells(r: pd.Series, p: str) -> str:
    return (f"{_fmt(r[f'{p}_sortino_monthly'], '{:.2f}')} | {_fmt(r[f'{p}_cagr'], '{:.1%}')} | "
            f"{_fmt(r[f'{p}_max_drawdown'], '{:.1%}')}")


def render(agg: dict, info: dict) -> str:
    df, spy, dg = agg["df"], pd.Series(agg["spy"]), info["diagnostics"]
    lines = ["# Qullamaggie phase 3: 5-star setup selection (pre-registered, 24 trials)", "",
             f"{len(df)} of {agg['expected']} trials; deflated Sharpe over {agg['n_trials']:,} trials. Survivorship "
             "bias NOT adjusted. Locked period from 2021-01-01 never read. Columns per period: monthly Sortino | "
             "CAGR | max drawdown of the portfolio.", "",
             f"SPY: 1995-2010 {_cells(spy, 'train')} · 2011-2020 {_cells(spy, 'validation')} · 2016-2020 "
             f"{_cells(spy, 'all')}.", "", "## 1. How well the scores rank breakouts (daily SCAN35 stream)", "",
             f"Model trained on {dg['train_rows']:,} trades of 1995-2010 ({dg['train_positives']:,} in the top 10%). "
             "Coefficients (standardised features): "
             + ", ".join(f"{k} {v:+.3f}" for k, v in dg["coefficients"].items()) + ".", "",
             "| period | AUC stars | AUC model |", "|---|---|---|"]
    for p in ("train", "validation", "val1", "val2"):
        if f"{p}_auc_stars" in dg:
            lines.append(f"| {p} | {_fmt(dg[f'{p}_auc_stars'], '{:.3f}')} | {_fmt(dg[f'{p}_auc_model'], '{:.3f}')} |")
    lines += ["", "Average trade return by number of stars (trades in brackets):", "",
              "| stars | 1995-2010 | 2011-2020 |", "|---|---|---|"]
    train, val = dg.get("train_return_by_stars", {}), dg.get("validation_return_by_stars", {})
    for k in sorted({int(x) for x in list(train) + list(val)}):
        a, b = train.get(k) or train.get(str(k)), val.get(k) or val.get(str(k))
        lines.append(f"| {k} | {_fmt(a[0] if a else None, '{:+.2%}')} ({a[1] if a else 0}) | "
                     f"{_fmt(b[0] if b else None, '{:+.2%}')} ({b[1] if b else 0}) |")
    lines += ["", "## 2. Daily breakouts with selection, 1995-2020", "",
              "| trial | 1995-2010 Sortino | CAGR | max DD | 2011-2020 Sortino | CAGR | max DD | trades 11-20 | PF 11-20 | "
              "best 5% captured | DSR | passed |", "|" + "---|" * 12]
    for n, r in df[df["setup"].str.startswith("D_")].iterrows():
        lines.append(f"| {n} | {_cells(r, 'train')} | {_cells(r, 'validation')} | "
                     f"{_fmt(r['validation_tl_trades'], '{:,.0f}')} | {_fmt(r['validation_tl_profit_factor'], '{:.2f}')} | "
                     f"{_fmt(r['best5_captured'], '{:.0%}')} | {_fmt(r['deflated_sharpe'], '{:.2f}')} | "
                     f"{'YES' if r['passed'] else 'no'} |")
    lines += ["", "## 3. Intraday setups with selection, 2016-2020", "",
              "| trial | 2016-2018 Sortino | CAGR | max DD | 2019-2020 Sortino | CAGR | max DD | 2016-2020 Sortino | "
              "CAGR | max DD | trades | PF | best 5% captured | DSR | passed |", "|" + "---|" * 16]
    for n, r in df[df["setup"].str.startswith("I_")].iterrows():
        lines.append(f"| {n} | {_cells(r, 'p1')} | {_cells(r, 'p2')} | {_cells(r, 'all')} | "
                     f"{_fmt(r['all_tl_trades'], '{:,.0f}')} | {_fmt(r['all_tl_profit_factor'], '{:.2f}')} | "
                     f"{_fmt(r['best5_captured'], '{:.0%}')} | {_fmt(r['deflated_sharpe'], '{:.2f}')} | "
                     f"{'YES' if r['passed'] else 'no'} |")
    lines += ["", "## 4. Pre-registered criteria (2011-2020 daily, 2016-2020 intraday)", "",
              f"Passed: {', '.join(agg['passed']) if agg['passed'] else 'none'}.", ""]
    return "\n".join(lines) + "\n"


def report(rows: pd.DataFrame, info: dict, output_dir: Path) -> int:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k in ("v1", "v2", "v3", "v4", "v5", "v6", "qullamaggie", "qullamaggie_intraday",
                        "qullamaggie_wind") for x in prior[k].values()]
    pool += [x for x in prior["v7"] if x is not None]
    agg = qs.aggregate(rows, pool)
    output_dir.mkdir(parents=True, exist_ok=True)
    agg["df"].to_parquet(output_dir / "results.parquet")
    (output_dir / "summary.json").write_text(json.dumps({"passed": agg["passed"], "info": info, "spy": agg["spy"]},
                                                        indent=1, default=str), encoding="utf-8")
    text = render(agg, info)
    (output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if len(agg["df"]) == agg["expected"] else 1


def cmd_run(args) -> int:
    fetch = _script("run_qullamaggie_intraday")
    panel, bench = _script("run_stock_catalog").load_panel(args.panel_dir)
    industry = pd.read_csv(args.symbols).set_index("symbol")["industry"].reindex(panel["close"].columns)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    nasdaq = _script("run_qullamaggie").nasdaq_close(args.cache / "ixic.csv")
    ind = sc.indicators(panel, bench["gspc"], industry)
    need = qi.needed(qi.candidates(panel, ind, q.context(panel, ind, nasdaq)))
    del ind
    api = fetch.Alpaca()
    alp_daily = fetch.fetch_daily(api, args.cache, sorted({s for v in need.values() for s in v}))
    fetch.fetch_minutes(api, args.cache, need)
    print(f"Alpaca calls (only for data missing from the cache): {api.calls}", flush=True)
    rows, info = qs.run(panel, bench["gspc"], bench["spy"], nasdaq, cash_index, industry,
                        fetch.minute_loader(args.cache), alp_daily, workers=args.workers)
    df = pd.DataFrame(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output_dir / "rows.parquet", index=False)
    (args.output_dir / "info.json").write_text(json.dumps(info, indent=1, default=str), encoding="utf-8")
    return report(df, info, args.output_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--output-dir", type=Path, default=Path("outputs/qullamaggie_stars"))
    a.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
