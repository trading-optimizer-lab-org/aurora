#!/usr/bin/env python3
"""Run the pre-registered crypto funding carry study (train + validation).

See docs/research/CRYPTO_CARRY_PREREGISTRATION.md. Only monthly files before
2024-01 are requested from Binance Data Vision, so locked-period data is never
downloaded.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

from aurora.research import crypto_carry as cc

BASE = "https://data.binance.vision/data"
SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
FIRST_MONTH = pd.Period("2019-09", "M")
LAST_MONTH = pd.Period("2023-12", "M")


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _csv_from_zip(url: str, attempts: int = 3) -> pd.DataFrame | None:
    for attempt in range(attempts):
        resp = requests.get(url, timeout=60)
        if resp.status_code == 404:
            return None
        if resp.ok:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                raw = z.read(z.namelist()[0]).decode("utf-8")
            has_header = not raw[:1].isdigit()
            return pd.read_csv(io.StringIO(raw), header=0 if has_header else None)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"download failed: {url} ({resp.status_code})")


def _months() -> list[str]:
    return [str(p) for p in pd.period_range(FIRST_MONTH, LAST_MONTH, freq="M")]


def daily_closes(kind: str, symbol: str) -> pd.Series:
    frames = []
    for month in _months():
        url = f"{BASE}/{kind}/monthly/klines/{symbol}/1d/{symbol}-1d-{month}.zip"
        df = _csv_from_zip(url)
        if df is not None:
            frames.append(pd.Series(df.iloc[:, 4].astype(float).to_numpy(),
                                    index=pd.to_datetime(df.iloc[:, 0].astype("int64"), unit="ms")))
    s = pd.concat(frames).sort_index()
    return s[~s.index.duplicated()].rename(symbol)


def daily_funding(symbol: str) -> pd.Series:
    frames = []
    for month in _months():
        url = f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
        df = _csv_from_zip(url)
        if df is None and frames:
            raise RuntimeError(f"funding archive missing after inception: {url}")
        if df is not None:
            frames.append(pd.Series(df.iloc[:, -1].astype(float).to_numpy(),
                                    index=pd.to_datetime(df.iloc[:, 0].astype("int64"), unit="ms")))
    events = pd.concat(frames).sort_index()
    events = events[~events.index.duplicated()]
    return events.groupby(events.index.normalize()).sum().rename(symbol)


def build_data() -> tuple[dict[str, pd.DataFrame], pd.Series, dict]:
    report: dict = {"assets": {}}
    data = {}
    for asset, symbol in SYMBOLS.items():
        spot = daily_closes("spot", symbol)
        perp = daily_closes("futures/um", symbol)
        funding = daily_funding(symbol)
        start = max(spot.index[0], perp.index[0], funding.index[0])
        idx = pd.date_range(start, min(spot.index[-1], perp.index[-1]), freq="D")
        frame = pd.DataFrame({"spot": spot.reindex(idx).ffill(limit=2),
                              "perp": perp.reindex(idx).ffill(limit=2),
                              "funding": funding.reindex(idx)})
        if frame["funding"].isna().any():
            missing = frame.index[frame["funding"].isna()]
            raise RuntimeError(f"{symbol} has no funding events on {len(missing)} days, "
                               f"first {missing[0].date()}; not zero-filling")
        if frame[["spot", "perp"]].isna().any().any():
            raise RuntimeError(f"gaps in {symbol} closes; not evaluating a partial history")
        data[asset] = frame.loc[frame.index < cc.LOCKED_START]
        report["assets"][asset] = {"symbol": symbol, "start": str(idx[0].date()),
                                   "end": str(data[asset].index[-1].date()),
                                   "funding_events_days": int((funding != 0).sum())}
    trend = _script("run_crypto_trend")
    base = _script("run_multiasset_baselines")
    calendar = pd.date_range(min(d.index[0] for d in data.values()),
                             max(d.index[-1] for d in data.values()), freq="D")
    cash_report: dict = {}
    raw_cash = trend._sealed(base.tbill_index(cash_report))
    cash_index = trend.business_day_cash(raw_cash.reindex(calendar.union(raw_cash.index)).ffill(), calendar)
    report["assets"]["CASH"] = cash_report
    return data, cash_index.pct_change(fill_method=None).fillna(0.0), report


def render(result: dict, data: dict) -> str:
    res = result["results"]
    keys = [("sortino_monthly", "{:.2f}"), ("sharpe_monthly", "{:.2f}"), ("cagr", "{:.1%}"),
            ("cash_cagr", "{:.1%}"), ("max_drawdown", "{:.1%}"), ("positive_months", "{:.0%}")]
    lines = ["# Crypto funding carry (pre-registered)", "",
             "Locked period from 2024-01-01 never downloaded. Monthly metrics on excess returns over T-bills.", ""]
    for period in ("train", "validation"):
        lines += [f"## {period.capitalize()}", "", "| strategy | " + " | ".join(k for k, _ in keys) + " |",
                  "|" + "---|" * (len(keys) + 1)]
        lines += [f"| {n} | " + " | ".join(f.format(r[period][k]) for k, f in keys) + " |" for n, r in res.items()]
        lines.append("")
    lines += ["## Pre-registered criteria (validation 2022-2023)", ""]
    for n, r in res.items():
        checks = "; ".join(f"{'PASS' if ok else 'FAIL'} {c}" for c, ok in r["checks"].items())
        lines.append(f"- **{n}**: {'PASSED' if r['passed'] else 'FAILED'} ({checks}); "
                     f"deflated Sharpe {r['validation']['deflated_sharpe']:.2f}")
    lines += ["", "## Data", "", "```json", json.dumps(data["assets"], indent=2), "```"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/crypto_carry"))
    args = parser.parse_args()
    data, cash, report = build_data()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.concat({a: d for a, d in data.items()}, axis=1).to_parquet(args.output_dir / "data.parquet")
    result = cc.run_study(data, cash)
    pd.DataFrame(result["daily_returns"]).to_parquet(args.output_dir / "daily_returns.parquet")
    (args.output_dir / "results.json").write_text(
        json.dumps({"data": report, "results": result["results"]}, indent=2, default=str), encoding="utf-8")
    text = render(result, report)
    (args.output_dir / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
