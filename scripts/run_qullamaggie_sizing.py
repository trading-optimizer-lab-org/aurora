#!/usr/bin/env python3
"""Qullamaggie phase 4 (sizing and position management): 16 trials, then the report.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_qullamaggie_sizing.py run \
        --panel-dir outputs/stock_panel --cache outputs/alpaca --output-dir outputs/qullamaggie_sizing

Reuses the phase 1 minute cache and only downloads what is missing. See
docs/research/QULLAMAGGIE_SIZING_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_sizing as qz
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
    return (f"{_fmt(r[f'{p}_sortino_monthly'], '{:.2f}')} | {_fmt(r[f'{p}_cagr'], '{:.1%}')} | "
            f"{_fmt(r[f'{p}_max_drawdown'], '{:.1%}')} | {_fmt(r[f'{p}_total'], '{:+.0%}')}")


def render(agg: dict) -> str:
    df, spy = agg["df"], pd.Series(agg["spy"])
    lines = ["# Qullamaggie phase 4: sizing and position management (pre-registered, 16 trials)", "",
             f"{len(df)} of {agg['expected']} trials on `I_MIX_MODEL_N3` (2016-2020); deflated Sharpe over "
             f"{agg['n_trials']:,} trials. Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read. "
             "Columns per period: monthly Sortino | CAGR | max drawdown | total return of the portfolio. S1 = 0.25% "
             "risk, 10% cap; S2 = 0.5%, 20%. P1 = add 50% at +2R; C1 = profit cushion (2x risk and margin); X1 = sell a "
             "third 30% above the SMA10.", "",
             f"SPY: 2016-2018 {_cells(spy, 'p1')} · 2019-2020 {_cells(spy, 'p2')} · 2016-2020 {_cells(spy, 'all')}.", "",
             "## 1. All trials", "",
             "| trial | 2016-18 Sortino | CAGR | max DD | total | 2019-20 Sortino | CAGR | max DD | total | 2016-20 Sortino | "
             "CAGR | max DD | total | max invested | best 5% captured | DSR | passed |", "|" + "---|" * 17]
    for n, r in df.iterrows():
        lines.append(f"| {n} | {_cells(r, 'p1')} | {_cells(r, 'p2')} | {_cells(r, 'all')} | "
                     f"{_fmt(r['max_invested'], '{:.0%}')} | {_fmt(r['best5_captured'], '{:.0%}')} | "
                     f"{_fmt(r['deflated_sharpe'], '{:.2f}')} | {'YES' if r['passed'] else 'no'} |")
    lines += ["", "## 2. Average effect of each tool (mean with it minus mean without, over the other 8 combinations)", "",
              "| tool | Sortino 2016-20 | CAGR 2016-20 | max DD 2016-20 | CAGR 2016-18 | CAGR 2019-20 |",
              "|---|---|---|---|---|---|"]
    for tool, e in agg["effects"].items():
        lines.append(f"| {tool} | {e['all_sortino_monthly']:+.2f} | {e['all_cagr']:+.1%} | {e['all_max_drawdown']:+.1%} | "
                     f"{e['p1_cagr']:+.1%} | {e['p2_cagr']:+.1%} |")
    lines += ["", "## 3. Pre-registered criteria on 2016-2020", "",
              f"Passed: {', '.join(agg['passed']) if agg['passed'] else 'none'}.", ""]
    return "\n".join(lines) + "\n"


def report(rows: pd.DataFrame, info: dict, output_dir: Path) -> int:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    pool = [x for k in ("v1", "v2", "v3", "v4", "v5", "v6", "qullamaggie", "qullamaggie_intraday",
                        "qullamaggie_wind", "qullamaggie_stars") for x in prior[k].values()]
    pool += [x for x in prior["v7"] if x is not None]
    agg = qz.aggregate(rows, pool)
    output_dir.mkdir(parents=True, exist_ok=True)
    agg["df"].to_parquet(output_dir / "results.parquet")
    (output_dir / "summary.json").write_text(json.dumps({"passed": agg["passed"], "effects": agg["effects"],
                                                         "info": info, "spy": agg["spy"]}, indent=1, default=str),
                                             encoding="utf-8")
    text = render(agg)
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
    rows, info = qz.run(panel, bench["gspc"], bench["spy"], nasdaq, cash_index, industry,
                        fetch.minute_loader(args.cache), alp_daily, workers=args.workers)
    df = pd.DataFrame(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output_dir / "rows.parquet", index=False)
    return report(df, info, args.output_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    a.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    a.add_argument("--cache", type=Path, default=Path("outputs/alpaca"))
    a.add_argument("--output-dir", type=Path, default=Path("outputs/qullamaggie_sizing"))
    a.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
