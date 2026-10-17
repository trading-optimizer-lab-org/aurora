#!/usr/bin/env python3
"""Download free multi-asset history and evaluate the published baselines.

Data (all free, no API key):
* ETFs and their pre-inception Vanguard/PIMCO mutual-fund proxies from Yahoo
  Finance (dividend-adjusted closes). A proxy only fills the dates before the
  ETF existed; its returns are chained into the ETF's index.
* 3-month T-bill rate (FRED DTB3) as the CASH index and risk-free rate.
* CBOE PUT and BXM index levels.

Everything on or after 2021-01-01 is dropped right after download.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from aurora.research.multiasset_baselines import LOCKED_START, run_all

# ETF -> proxies, tried in order; each proxy fills only dates before the
# series built so far starts.
PROXIES: dict[str, list[str]] = {
    "SPY": ["VFINX"],
    "IWM": ["NAESX"],
    "EFA": ["VTRIX"],
    "EEM": ["VEIEX"],
    "IEF": ["VFITX"],
    "TLT": ["VUSTX"],
    "SHY": ["VFISX"],
    "AGG": ["VBMFX"],
    "LQD": ["VFICX"],
    "TIP": ["VIPSX"],
    "HYG": ["VWEHX"],
    "GLD": ["GC=F"],
    "DBC": ["PCRIX"],
    "VNQ": ["VGSIX"],
    "QQQ": [],
    **{s: [] for s in ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]},
}
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
HEADERS = {"User-Agent": "Mozilla/5.0 (aurora research)"}


def yahoo_close(symbol: str) -> pd.Series:
    import yfinance as yf

    df = yf.download(symbol, period="max", auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        return pd.Series(dtype=float, name=symbol)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    return close.dropna().rename(symbol)


def splice(primary: pd.Series, proxies: list[pd.Series]) -> tuple[pd.Series, list[dict]]:
    """Chain proxy returns before the primary series starts."""
    series = primary.dropna()
    used: list[dict] = []
    for proxy in proxies:
        proxy = proxy.dropna()
        if proxy.empty or series.empty or proxy.index[0] >= series.index[0]:
            continue
        early = proxy.loc[:series.index[0]]
        early = early / early.iloc[-1] * series.iloc[0]
        used.append({"proxy": proxy.name, "from": str(early.index[0].date()),
                     "to": str(series.index[0].date())})
        series = pd.concat([early.iloc[:-1], series])
    return series, used


def continuous_from(series: pd.Series, max_gap_days: int = 10) -> pd.Series:
    """Drop the part of ``series`` before its last gap longer than ``max_gap_days``
    calendar days, so sparse early history is never forward-filled."""
    s = series.dropna()
    gaps = s.index.to_series().diff().dt.days
    long_gaps = gaps[gaps > max_gap_days]
    return s.loc[long_gaps.index[-1]:] if len(long_gaps) else s


def cboe_index(name: str) -> pd.Series:
    resp = requests.get(CBOE_URL.format(name), headers=HEADERS, timeout=60)
    resp.raise_for_status()
    lines = resp.text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.upper().startswith("DATE"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df.columns = [c.strip().upper() for c in df.columns]
    value = name.upper() if name.upper() in df.columns else df.columns[-1]
    s = pd.Series(pd.to_numeric(df[value], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df["DATE"], errors="coerce"), name=name)
    return s[s.index.notna()].dropna().sort_index()


def tbill_index() -> pd.Series:
    resp = requests.get(FRED_URL.format("DTB3"), headers=HEADERS, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = ["date", "rate"]
    rate = pd.to_numeric(df["rate"], errors="coerce")
    s = pd.Series(rate.to_numpy(), index=pd.to_datetime(df["date"])).ffill().dropna()
    daily = (1 + s / 100.0) ** (1 / 252) - 1
    return (1 + daily).cumprod().rename("CASH")


def build_prices() -> tuple[pd.DataFrame, dict]:
    report: dict = {"assets": {}}
    columns: dict[str, pd.Series] = {}
    for etf, proxies in PROXIES.items():
        series, used = splice(yahoo_close(etf), [yahoo_close(p) for p in proxies])
        if series.empty:
            report["assets"][etf] = {"status": "missing"}
            continue
        columns[etf] = series
        report["assets"][etf] = {"start": str(series.index[0].date()), "proxies": used}
    for name in ("PUT", "BXM"):
        try:
            columns[name] = cboe_index(name)
            report["assets"][name] = {"start": str(columns[name].index[0].date()), "source": "CBOE"}
        except Exception as exc:  # optional asset; record and continue
            report["assets"][name] = {"status": f"missing: {exc}"}
    columns["CASH"] = tbill_index()
    report["assets"]["CASH"] = {"start": str(columns["CASH"].index[0].date()), "source": "FRED DTB3"}
    for name, s in columns.items():
        trimmed = continuous_from(s)
        if trimmed.index[0] != s.index[0]:
            report["assets"][name]["continuous_from"] = str(trimmed.index[0].date())
        columns[name] = trimmed

    calendar = columns["SPY"].index
    prices = pd.DataFrame({k: v.reindex(calendar.union(v.index)).ffill(limit=5).reindex(calendar)
                           for k, v in columns.items()})
    for name, s in columns.items():
        first = s.index[0]
        prices.loc[prices.index < first, name] = np.nan
    prices = prices.loc[prices.index < LOCKED_START]
    report["data_end"] = str(prices.index.max().date())
    return prices, report


def _markdown_table(table: pd.DataFrame) -> str:
    def cell(v: object) -> str:
        return f"{v:.3f}" if isinstance(v, float) else str(v)

    lines = ["| " + " | ".join(table.columns) + " |", "|" + "---|" * len(table.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in table.itertuples(index=False)]
    return "\n".join(lines)


def write_report(result: dict, data_report: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in result["ranking"]:
        v = result["strategies"][name]["validation"]
        i = result["strategies"][name]["in_sample"]
        rows.append({"strategy": name, "val_sharpe": v["sharpe"], "val_sortino": v["sortino"],
                     "val_cagr": v["cagr"], "val_vol": v["vol"], "val_max_dd": v["max_drawdown"],
                     "val_calmar": v["calmar"], "val_deflated_sharpe": v["deflated_sharpe"],
                     "is_start": i.get("start"), "is_sharpe": i.get("sharpe"),
                     "is_sortino": i.get("sortino"), "is_max_dd": i.get("max_drawdown")})
    table = pd.DataFrame(rows)
    table.to_csv(out / "ranking.csv", index=False)
    pd.DataFrame(result["daily_returns"]).to_parquet(out / "daily_returns.parquet")
    summary = {k: v for k, v in result.items() if k != "daily_returns"}
    (out / "results.json").write_text(json.dumps({"data": data_report, **summary}, indent=2, default=str),
                                      encoding="utf-8")
    lines = [
        "# Multi-asset baselines",
        "",
        f"Data end: {data_report['data_end']} (locked period from 2021-01-01 excluded).",
        f"Trials counted for the deflated Sharpe: {result['n_trials']}.",
        "Ranking: mean of validation (2011-2020) Sharpe rank and Sortino rank.",
        "",
        _markdown_table(table),
        "",
        "## Data sources",
        "",
        "```json",
        json.dumps(data_report["assets"], indent=2),
        "```",
    ]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/multiasset_baselines"))
    args = parser.parse_args()
    prices, data_report = build_prices()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prices.to_parquet(args.output_dir / "prices.parquet")
    result = run_all(prices)
    write_report(result, data_report, args.output_dir)
    print((args.output_dir / "REPORT.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
