#!/usr/bin/env python3
"""Run the pre-registered crypto trend study (train + validation only).

See docs/research/CRYPTO_TREND_PREREGISTRATION.md. Prices on or after
2024-01-01 (the locked period) are dropped right after download.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from aurora.research import crypto_trend as ct

YAHOO = {a: f"{a}-USD" for a in ct.ALTS}


def _baselines():
    path = Path(__file__).resolve().parent / "run_multiasset_baselines.py"
    spec = importlib.util.spec_from_file_location("run_multiasset_baselines", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sealed(series: pd.Series) -> pd.Series:
    """Drop locked-period observations before any data-dependent cleanup."""
    return series.loc[series.index < ct.LOCKED_START]


def _download(base, ticker: str, attempts: int = 3) -> pd.Series:
    for attempt in range(attempts):
        s = _sealed(base.yahoo_close(ticker))
        if not s.empty:
            return s
        time.sleep(10 * (attempt + 1))
    return s


def business_day_cash(cash_index: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """T-bill index on ``calendar`` that accrues only on US business days
    (weekdays that are not federal holidays); flat otherwise."""
    daily = cash_index.pct_change(fill_method=None).reindex(calendar).fillna(0.0)
    holidays = USFederalHolidayCalendar().holidays(calendar.min(), calendar.max())
    business = (calendar.weekday < 5) & ~calendar.isin(holidays)
    daily = daily.where(business, 0.0)
    return (1 + daily).cumprod().rename("CASH")


def build_prices() -> tuple[pd.DataFrame, dict]:
    base = _baselines()
    report: dict = {"assets": {}}
    columns = {}
    missing = []
    for asset, ticker in YAHOO.items():
        s = base.continuous_from(_download(base, ticker))
        if s.empty:
            missing.append(ticker)
            continue
        columns[asset] = s
        report["assets"][asset] = {"ticker": ticker, "start": str(s.index[0].date())}
    if missing:
        raise RuntimeError(f"Yahoo returned no pre-2024 history for {missing}; not evaluating a partial universe")
    cash_report: dict = {}
    cash = _sealed(base.tbill_index(cash_report))
    report["assets"]["CASH"] = {"start": str(cash.index[0].date()), **cash_report}
    calendar = pd.date_range(min(s.index[0] for s in columns.values()), max(s.index[-1] for s in columns.values()),
                             freq="D")
    prices = pd.DataFrame({a: s.reindex(calendar).ffill(limit=3).where(calendar >= s.index[0])
                           for a, s in columns.items()})
    prices["CASH"] = business_day_cash(cash.reindex(calendar.union(cash.index)).ffill(), calendar)
    report["data_end"] = str(prices.index.max().date())
    return prices, report


def render(result: dict, data: dict) -> str:
    res = result["results"]
    keys = [("sortino_monthly", "{:.2f}"), ("sharpe_monthly", "{:.2f}"), ("cagr", "{:.1%}"),
            ("max_drawdown", "{:.1%}"), ("positive_months", "{:.0%}")]
    lines = ["# Crypto trend following (pre-registered)", "",
             f"Data end: {data['data_end']} (locked period from 2024-01-01 excluded).",
             "Sortino and Sharpe on calendar-month excess returns over T-bills.", ""]
    for period in ("train", "validation"):
        lines += [f"## {period.capitalize()}", "", "| strategy | " + " | ".join(k for k, _ in keys) + " |",
                  "|" + "---|" * (len(keys) + 1)]
        for name, r in res.items():
            m = r[period]
            lines.append(f"| {name} | " + " | ".join(f.format(m[k]) for k, f in keys) + " |")
        lines.append("")
    lines += ["## Pre-registered criteria (validation 2022-2023)", ""]
    for name in ct.CANDIDATES:
        r = res[name]
        checks = "; ".join(f"{'PASS' if ok else 'FAIL'} {c}" for c, ok in r["checks"].items())
        lines.append(f"- **{name}**: {'PASSED' if r['passed'] else 'FAILED'} ({checks}); "
                     f"deflated Sharpe {r['validation']['deflated_sharpe']:.2f}")
    lines += ["", "## Robustness (validation monthly Sortino)", "",
              "| strategy | " + " | ".join(next(iter(res[n]["robustness"] for n in ct.CANDIDATES))) + " |",
              "|" + "---|" * 6]
    for name in ct.CANDIDATES:
        lines.append(f"| {name} | " + " | ".join(f"{v:.2f}" for v in res[name]["robustness"].values()) + " |")
    lines += ["", "## Data", "", "```json", json.dumps(data["assets"], indent=2), "```"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/crypto_trend"))
    args = parser.parse_args()
    prices, data = build_prices()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prices.to_parquet(args.output_dir / "prices.parquet")
    result = ct.run_study(prices)
    pd.DataFrame(result["daily_returns"]).to_parquet(args.output_dir / "daily_returns.parquet")
    (args.output_dir / "results.json").write_text(
        json.dumps({"data": data, "results": result["results"]}, indent=2, default=str), encoding="utf-8")
    text = render(result, data)
    (args.output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
