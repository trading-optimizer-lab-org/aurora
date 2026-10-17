#!/usr/bin/env python3
"""Run the pre-registered US stock strategy catalog (train + validation).

See docs/research/STOCK_CATALOG_PREREGISTRATION.md. Reads the panel written by
scripts/build_stock_panel.py (local files or a fresh Yahoo download).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from aurora.research import stock_catalog as sc

FIELDS = ("open", "high", "low", "close", "volume")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_panel(panel_dir: Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    bench = pd.read_parquet(panel_dir / "benchmarks.parquet")
    calendar = bench["gspc"].dropna().loc[sc.WARMUP_START:].index
    panel = {f: pd.read_parquet(panel_dir / f"{f}.parquet").reindex(calendar) for f in FIELDS}
    keep = panel["close"].columns[panel["close"].notna().sum() >= sc.MIN_HISTORY]
    return {f: df[keep] for f, df in panel.items()}, bench.reindex(calendar)


def render(study: dict, data: dict) -> str:
    res = study["results"]
    keys = [("sortino_monthly", "{:.2f}"), ("sharpe_monthly", "{:.2f}"), ("cagr", "{:.1%}"),
            ("max_drawdown", "{:.1%}"), ("positive_months", "{:.0%}")]
    order = ["spy", "equal_weight_universe", *study["candidates"]]
    lines = ["# US stock strategy catalog (pre-registered)", "",
             "Survivorship bias NOT adjusted (owner's choice): results are optimistic. "
             "Locked period from 2021-01-01 never read. Monthly metrics on excess returns over T-bills.", ""]
    for period in ("train", "validation"):
        lines += [f"## {period.capitalize()}", "", "| strategy | " + " | ".join(k for k, _ in keys) + " | invested |",
                  "|" + "---|" * (len(keys) + 2)]
        for n in order:
            r = res[n]
            inv = r.get("invested_mean", float("nan"))
            inv_s = f"{inv:.0%}" if inv == inv else "-"
            lines.append(f"| {n} | " + " | ".join(f.format(r[period][k]) for k, f in keys) + f" | {inv_s} |")
        lines.append("")
    passed = [n for n in study["candidates"] if res[n]["passed"]]
    lines += ["## Pre-registered criteria (validation 2011-2020)", "",
              f"Passed: {', '.join(passed) if passed else 'none'}", ""]
    for n in study["candidates"]:
        r = res[n]
        checks = "; ".join(f"{'PASS' if ok else 'FAIL'} {c}" for c, ok in r["checks"].items())
        lines.append(f"- **{n}**: {'PASSED' if r['passed'] else 'FAILED'} ({checks}); "
                     f"deflated Sharpe {r['validation']['deflated_sharpe']:.2f}; signals {r.get('signals', 0)}")
    tk = [("trades", "{:,}"), ("win_rate", "{:.0%}"), ("avg_return", "{:+.2%}"), ("median_return", "{:+.2%}"),
          ("avg_R", "{:+.2f}"), ("profit_factor", "{:.2f}"), ("total_return", "{:+,.0%}"), ("total_R", "{:+,.0f}"),
          ("avg_days", "{:.1f}"), ("top5pct_share", "{:.0%}")]
    for period in ("train", "validation"):
        lines += ["", f"## Every signal traded on its own ({period}, Amendment 1)", "",
                  "| strategy | " + " | ".join(k for k, _ in tk) + " |", "|" + "---|" * (len(tk) + 1)]
        for n in study["candidates"]:
            tl = res[n].get("trade_level")
            if not tl or not tl[period].get("trades"):
                continue
            row = tl[period]
            lines.append(f"| {n} | " + " | ".join(
                "-" if (v := row.get(k)) is None or v != v else f.format(v) for k, f in tk) + " |")
    years = [str(y) for y in range(2011, 2021)]
    lines += ["", "## Industry filter (IND50) minus no filter, validation years (Jacobs' claim)", "",
              "| strategy | " + " | ".join(years) + " | years better |", "|" + "---|" * (len(years) + 2)]
    for n, _, _ in sc.TREND:
        a, b = res[n]["annual"], res[f"{n}_noind"]["annual"]
        diffs = [a.get(y, 0.0) - b.get(y, 0.0) for y in years]
        lines.append(f"| {n} | " + " | ".join(f"{d:+.1%}" for d in diffs) + f" | {sum(d > 0 for d in diffs)}/10 |")
    lines += ["", "## Data", "", "```json", json.dumps(data, indent=2, default=str), "```"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel-dir", type=Path, default=Path("outputs/stock_panel"))
    ap.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    ap.add_argument("--output-dir", type=Path, default=Path("outputs/stock_catalog"))
    args = ap.parse_args()
    panel, bench = load_panel(args.panel_dir)
    syms = pd.read_csv(args.symbols)
    industry = syms.set_index("symbol")["industry"].reindex(panel["close"].columns)
    base = _script("run_multiasset_baselines")
    cash_report: dict = {}
    cash_index = base.tbill_index(cash_report)
    cash_index = cash_index.loc[cash_index.index < sc.LOCKED_START]
    study = sc.run_study(panel, bench["gspc"], bench["spy"], cash_index, industry)
    summary_path = args.panel_dir / "data_summary.json"
    data = {"symbols_in_panel": int(panel["close"].shape[1]),
            "calendar": [str(panel["close"].index[0].date()), str(panel["close"].index[-1].date())],
            "cash": cash_report,
            "panel": json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(study["daily_returns"]).to_parquet(args.output_dir / "daily_returns.parquet")
    pd.concat({n: t for n, t in study["trades"].items()}, names=["strategy"]).reset_index(level=0).to_parquet(
        args.output_dir / "trades.parquet")
    (args.output_dir / "results.json").write_text(
        json.dumps({"data": data, "results": study["results"]}, indent=2, default=str), encoding="utf-8")
    text = render(study, data)
    (args.output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
