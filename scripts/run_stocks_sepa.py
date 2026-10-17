#!/usr/bin/env python3
"""Run the pre-registered Minervini / O'Neil style US stocks study.

See docs/research/STOCKS_SEPA_PREREGISTRATION.md. Reads the local
``free_us_daily`` catalog; every series is cut before 2021-01-01 as soon as
it is read.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from aurora.research import stocks_sepa as ss

FRENCH_URL = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
              "10_Portfolios_Prior_12_2_CSV.zip")
TIINGO_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", "~")) / "aurora" / "prices" / "free_us_daily"
FIELDS = ("open", "high", "low", "close", "volume", "dollar_volume", "real_price")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_stock(path: Path) -> pd.DataFrame | None:
    df = pd.read_parquet(path, columns=["date", "open", "high", "low", "close", "adj_close",
                                        "volume", "stock_splits"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[~df.index.duplicated()]
    # Yahoo's close is split adjusted as of today; undo later splits to get
    # the price quoted on each day. Only split events are used from after 2020.
    splits = df["stock_splits"].where(df["stock_splits"] > 0, 1.0)
    later = splits[::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
    df = df.loc[(df.index >= ss.WARMUP_START) & (df.index < ss.LOCKED_START)]
    if df.empty:
        return None
    factor = df["adj_close"] / df["close"]
    out = pd.DataFrame({k: df[k] * factor for k in ("open", "high", "low", "close")})
    out["volume"] = df["volume"].astype(float)
    out["dollar_volume"] = df["close"] * df["volume"]
    out["real_price"] = df["close"] * later.loc[df.index]
    return out.replace([np.inf, -np.inf], np.nan).astype("float32")


def build_panel(prices_dir: Path, calendar: pd.DatetimeIndex) -> tuple[dict[str, pd.DataFrame], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted((prices_dir / "normalized").glob("*.parquet")):
        df = read_stock(path)
        if df is not None and len(df) >= ss.MIN_HISTORY:
            frames[path.stem] = df
    symbols = sorted(frames)
    panel = {f: pd.DataFrame({s: frames[s][f] for s in symbols}).reindex(calendar) for f in FIELDS}
    return panel, symbols


def benchmark(prices_dir: Path, name: str) -> pd.Series:
    df = pd.read_parquet(prices_dir / "benchmarks" / f"{name}.parquet", columns=["date", "adj_close"])
    s = pd.Series(df["adj_close"].to_numpy(), index=pd.to_datetime(df["date"])).sort_index()
    return s.loc[s.index < ss.LOCKED_START]


def french_hi_prior() -> pd.Series:
    resp = requests.get(FRENCH_URL, timeout=120)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        text = z.read(z.namelist()[0]).decode("latin-1")
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if "Equal Weighted Returns -- Monthly" in l)
    rows = []
    for line in lines[start + 2:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 11 or not parts[0].isdigit():
            break
        rows.append((pd.Period(f"{parts[0][:4]}-{parts[0][4:]}", "M"), float(parts[10]) / 100))
    s = pd.Series(dict(rows), name="french_hi_prior")
    s = s.loc[s.index < ss.LOCKED_START.to_period("M")]  # sealed before anything else
    return s.where(s > -0.99).dropna()


def local_hi_prior(panel: dict[str, pd.DataFrame], nyse: pd.Index) -> pd.Series:
    by_month = panel["close"].index.to_period("M")
    month_close = panel["close"].groupby(by_month).last()
    month_price = panel["real_price"].groupby(by_month).last()
    return ss.momentum_top_decile(month_close, month_price, nyse)


def delisting_census(local_first: pd.Series) -> dict:
    resp = requests.get(TIINGO_URL, timeout=120)
    resp.raise_for_status()
    t = pd.read_csv(io.BytesIO(resp.content), compression="zip")
    t = t[t["assetType"].eq("Stock") & t["exchange"].isin(["NYSE", "NASDAQ", "AMEX", "NYSE MKT"])]
    start, end = pd.to_datetime(t["startDate"], errors="coerce"), pd.to_datetime(t["endDate"], errors="coerce")
    out = {}
    for year in range(1995, 2021, 5):
        d = pd.Timestamp(f"{year}-06-30")
        out[str(year)] = {"tiingo_listed": int(((start <= d) & (end >= d)).sum()),
                          "local_with_data": int((local_first <= d).sum())}
    return out


def render(study: dict, report: dict) -> str:
    res = study["results"]
    keys = [("sortino_monthly", "{:.2f}"), ("sharpe_monthly", "{:.2f}"), ("cagr", "{:.1%}"),
            ("max_drawdown", "{:.1%}"), ("positive_months", "{:.0%}")]
    lines = ["# US stocks, Minervini / O'Neil style (pre-registered)", "",
             "Locked period from 2021-01-01 never read. Candidates are bias-adjusted "
             "(see the pre-registration); monthly metrics on excess returns over T-bills.", "",
             "Survivorship bias, local minus French top momentum decile, per month: "
             + ", ".join(f"{p} {b:.2%}" for p, b in study["bias_monthly"].items()), ""]
    for period in ("train", "validation"):
        lines += [f"## {period.capitalize()}", "", "| strategy | " + " | ".join(k for k, _ in keys) + " |",
                  "|" + "---|" * (len(keys) + 1)]
        for n, r in res.items():
            lines.append(f"| {n} | " + " | ".join(f.format(r[period][k]) for k, f in keys) + " |")
            if f"{period}_unadjusted" in r:
                u = r[f"{period}_unadjusted"]
                lines.append(f"| {n} (unadjusted) | " + " | ".join(f.format(u[k]) for k, f in keys) + " |")
        lines.append("")
    lines += ["## Pre-registered criteria (validation 2011-2020, bias-adjusted)", ""]
    for n in ss.CANDIDATES:
        r = res[n]
        checks = "; ".join(f"{'PASS' if ok else 'FAIL'} {c}" for c, ok in r["checks"].items())
        lines.append(f"- **{n}**: {'PASSED' if r['passed'] else 'FAILED'} ({checks}); "
                     f"deflated Sharpe {r['validation']['deflated_sharpe']:.2f}; "
                     f"average invested {r['invested_mean']:.0%}")
    lines += ["", "## Data", "", "```json", json.dumps(report, indent=2), "```"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/stocks_sepa"))
    args = parser.parse_args()
    spy = benchmark(args.prices_dir, "SPY")
    gspc = benchmark(args.prices_dir, "GSPC")
    calendar = spy.loc[ss.WARMUP_START:].index
    panel, symbols = build_panel(args.prices_dir, calendar)
    meta = pd.read_parquet(args.prices_dir / "metadata" / "company_metadata.parquet", columns=["symbol", "exchange"])
    nyse = pd.Index(meta.loc[meta["exchange"].eq("NYQ"), "symbol"])
    local_first = panel["close"].apply(lambda c: c.first_valid_index())
    base = _script("run_multiasset_baselines")
    cash_report: dict = {}
    raw_cash = base.tbill_index(cash_report)
    cash_index = raw_cash.loc[raw_cash.index < ss.LOCKED_START]
    report = {"symbols": len(symbols), "nyse_breakpoint_symbols": int(nyse.isin(symbols).sum()),
              "calendar": [str(calendar[0].date()), str(calendar[-1].date())],
              "cash": cash_report, "delisting_census": delisting_census(local_first.dropna())}
    study = ss.run_study(panel, gspc, spy, cash_index, local_hi_prior(panel, nyse), french_hi_prior())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(study["daily_returns"]).to_parquet(args.output_dir / "daily_returns.parquet")
    (args.output_dir / "results.json").write_text(
        json.dumps({"data": report, "bias_monthly": study["bias_monthly"], "results": study["results"]},
                   indent=2, default=str), encoding="utf-8")
    text = render(study, report)
    (args.output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
