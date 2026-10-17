#!/usr/bin/env python3
"""Run the pre-registered stock catalog v2 (train + validation).

See docs/research/STOCK_CATALOG_V2_PREREGISTRATION.md. Uses the same panel as
v1 (scripts/build_stock_panel.py) and, when given, v1's results.json for the
deflated Sharpe trial count.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v2 as v2


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(study: dict) -> str:
    res = study["results"]
    keys = [("sortino_monthly", "{:.2f}"), ("sharpe_monthly", "{:.2f}"), ("cagr", "{:.1%}"),
            ("max_drawdown", "{:.1%}"), ("positive_months", "{:.0%}")]
    lines = ["# US stock strategy catalog v2 (pre-registered)", "",
             "Designed after seeing v1, so validation is not a clean out-of-sample test. "
             "Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read.",
             f"Deflated Sharpe uses {study['n_trials']} trials (v2 + v1).", ""]
    for period in ("train", "validation"):
        lines += [f"## Portfolio, {period}", "", "| strategy | " + " | ".join(k for k, _ in keys) + " | invested |",
                  "|" + "---|" * (len(keys) + 2)]
        for n in ["spy", *study["candidates"]]:
            r = res[n]
            inv = r.get("invested_mean")
            lines.append(f"| {n} | " + " | ".join(f.format(r[period][k]) for k, f in keys)
                         + (f" | {inv:.0%} |" if inv is not None else " | - |"))
        lines.append("")
    passed = [n for n in study["candidates"] if res[n]["passed"]]
    lines += ["## Pre-registered criteria (validation 2011-2020)", "", f"Passed: {', '.join(passed) or 'none'}", ""]
    for n in study["candidates"]:
        r = res[n]
        checks = "; ".join(f"{'PASS' if ok else 'FAIL'} {c}" for c, ok in r["checks"].items())
        lines.append(f"- **{n}**: {'PASSED' if r['passed'] else 'FAILED'} ({checks}); "
                     f"deflated Sharpe {r['validation']['deflated_sharpe']:.2f}; signals {r['signals']}")
    tk = [("trades", "{:,}"), ("win_rate", "{:.0%}"), ("avg_return", "{:+.2%}"), ("median_return", "{:+.2%}"),
          ("avg_R", "{:+.2f}"), ("profit_factor", "{:.2f}"), ("total_return", "{:+,.0%}"), ("total_R", "{:+,.0f}"),
          ("avg_days", "{:.1f}"), ("top5pct_share", "{:.0%}")]
    for period in ("train", "validation"):
        lines += ["", f"## Every signal traded on its own ({period})", "",
                  "| strategy | " + " | ".join(k for k, _ in tk) + " |", "|" + "---|" * (len(tk) + 1)]
        rows = [(n, res[n]["trade_level"][period]) for n in study["candidates"]
                if "trade_level" in res[n] and res[n]["trade_level"][period].get("trades")]
        for n, row in sorted(rows, key=lambda x: -x[1]["profit_factor"]):
            lines.append(f"| {n} | " + " | ".join(
                "-" if (v := row.get(k)) is None or v != v else f.format(v) for k, f in tk) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    ap.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    ap.add_argument("--v1-results", type=Path, default=Path("outputs/stock_catalog/results.json"))
    ap.add_argument("--output-dir", type=Path, default=Path("outputs/stock_catalog_v2"))
    args = ap.parse_args()
    panel, bench = _script("run_stock_catalog").load_panel(args.panel_dir)
    industry = pd.read_csv(args.symbols).set_index("symbol")["industry"].reindex(panel["close"].columns)
    cash_index = _script("run_multiasset_baselines").tbill_index({})
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    v1 = None
    if args.v1_results.exists():
        r1 = json.loads(args.v1_results.read_text(encoding="utf-8"))["results"]
        v1 = [r1[c.name]["validation"]["sharpe"] for c in sc.CANDIDATES] + [r1[sc.BLEND[0]]["validation"]["sharpe"]]
    study = v2.run_study(panel, bench["gspc"], bench["spy"], cash_index, industry, v1)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(study["daily_returns"]).to_parquet(args.output_dir / "daily_returns.parquet")
    pd.concat(study["trades"], names=["strategy"]).reset_index(level=0).to_parquet(args.output_dir / "trades.parquet")
    (args.output_dir / "results.json").write_text(json.dumps({"results": study["results"]}, indent=2, default=str),
                                                  encoding="utf-8")
    text = render(study)
    (args.output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
