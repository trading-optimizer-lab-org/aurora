"""Fetch a complete daily SPY benchmark for a GitHub-only forward pass."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


def fetch(output: Path) -> pd.DataFrame:
    period1 = int(pd.Timestamp("1990-01-01", tz="UTC").timestamp())
    period2 = int(pd.Timestamp.now(tz="UTC").timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
        f"?period1={period1}&period2={period2}&interval=1d&events=div%2Csplits"
    )
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError("Yahoo returned no SPY benchmark data")
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None).normalize(),
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "adj_close": adj if adj is not None else quote.get("close", []),
            "volume": quote.get("volume", []),
            "symbol": "SPY",
        }
    )
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output, index=False)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frame = fetch(args.output)
    print(f"SPY benchmark rows={len(frame)} last={frame['date'].max().date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
