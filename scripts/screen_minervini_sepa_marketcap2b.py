from __future__ import annotations

import argparse
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from yfinance import EquityQuery


NASDAQ_SCREENER_URL = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=25000&download=true"
)


@dataclass(frozen=True)
class ScreenerConfig:
    min_market_cap: float
    output_dir: Path
    batch_size: int
    sleep_seconds: float
    period: str
    benchmark: str
    universe: str
    regions: tuple[str, ...]


def _parse_market_cap(value: Any) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text or text in {"--", "N/A", "nan"}:
        return float("nan")
    multiplier = 1.0
    suffix = text[-1:].upper()
    if suffix == "T":
        multiplier = 1_000_000_000_000.0
        text = text[:-1]
    elif suffix == "B":
        multiplier = 1_000_000_000.0
        text = text[:-1]
    elif suffix == "M":
        multiplier = 1_000_000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        digits = re.sub(r"[^0-9.]", "", text)
        return float(digits) * multiplier if digits else float("nan")


def _clean_symbol(symbol: str) -> str:
    return symbol.strip().replace("/", "-")


def fetch_us_stock_universe(min_market_cap: float) -> pd.DataFrame:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/126 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/market-activity/stocks/screener",
    }
    response = requests.get(NASDAQ_SCREENER_URL, headers=headers, timeout=60)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", {}).get("rows", [])
    if not rows:
        raise RuntimeError("Nasdaq screener returned no rows")

    frame = pd.DataFrame(rows)
    frame.columns = [str(c).strip() for c in frame.columns]
    symbol_col = "symbol" if "symbol" in frame.columns else "Symbol"
    name_col = "name" if "name" in frame.columns else "Name"
    market_cap_col = "marketCap" if "marketCap" in frame.columns else "Market Cap"
    country_col = "country" if "country" in frame.columns else None
    ipo_col = "ipoyear" if "ipoyear" in frame.columns else None

    out = pd.DataFrame(
        {
            "symbol": frame[symbol_col].astype(str).map(_clean_symbol),
            "name": frame[name_col].astype(str) if name_col in frame else "",
            "market_cap": frame[market_cap_col].map(_parse_market_cap),
        }
    )
    if country_col:
        out["country"] = frame[country_col].astype(str)
    if ipo_col:
        out["ipo_year"] = frame[ipo_col].astype(str)

    out = out.dropna(subset=["market_cap"])
    out = out[out["market_cap"] >= min_market_cap].copy()
    out = out[~out["symbol"].str.contains(r"[.$\^]", regex=True, na=False)]
    out = out[~out["name"].str.contains("ETF|ETN|Fund|Trust|Warrant|Unit", case=False, na=False)]
    out = out.drop_duplicates("symbol").sort_values("market_cap", ascending=False)
    if out.empty:
        raise RuntimeError("No symbols survived market cap filter")
    return out.reset_index(drop=True)


def _first_present(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _extract_yahoo_quotes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("quotes", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    finance = payload.get("finance")
    if isinstance(finance, dict):
        result = finance.get("result")
        if isinstance(result, list) and result:
            quotes = result[0].get("quotes")
            if isinstance(quotes, list):
                return quotes
    return []


def fetch_yahoo_region_universe(min_market_cap: float, regions: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for region in regions:
        query = EquityQuery(
            "and",
            [
                EquityQuery("eq", ["region", region]),
                EquityQuery("gte", ["intradaymarketcap", min_market_cap]),
                EquityQuery("gt", ["intradayprice", 0]),
            ],
        )
        for offset in range(0, 10000, 250):
            try:
                payload = yf.screen(
                    query,
                    offset=offset,
                    size=250,
                    sortField="intradaymarketcap",
                    sortAsc=False,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({"region": region, "error": str(exc)})
                break
            quotes = _extract_yahoo_quotes(payload)
            if not quotes:
                break
            for quote in quotes:
                symbol = str(_first_present(quote, ("symbol", "ticker")) or "").strip()
                if not symbol:
                    continue
                market_cap = _first_present(
                    quote,
                    (
                        "intradaymarketcap",
                        "marketCap",
                        "marketcap",
                        "lastclosemarketcap.lasttwelvemonths",
                    ),
                )
                try:
                    cap = float(market_cap)
                except (TypeError, ValueError):
                    cap = float("nan")
                if not math.isfinite(cap) or cap < min_market_cap:
                    continue
                quote_type = str(_first_present(quote, ("quoteType", "typeDisp")) or "").upper()
                if quote_type and quote_type not in {"EQUITY", "COMMON STOCK", "ADR"}:
                    continue
                name = str(_first_present(quote, ("longName", "shortName", "name")) or "")
                rows.append(
                    {
                        "symbol": _clean_symbol(symbol),
                        "name": name,
                        "market_cap": cap,
                        "region": region,
                        "exchange": _first_present(quote, ("exchange", "fullExchangeName", "exchangeName")),
                        "currency": _first_present(quote, ("currency", "financialCurrency")),
                    }
                )
            if len(quotes) < 250:
                break
            time.sleep(0.2)
    out = pd.DataFrame(rows)
    if out.empty:
        detail = "; ".join(f"{e['region']}={e['error']}" for e in errors[:10])
        raise RuntimeError(f"Yahoo screener returned no usable rows. {detail}")
    out = out.drop_duplicates("symbol").sort_values(["market_cap", "symbol"], ascending=[False, True])
    return out.reset_index(drop=True)


def fetch_universe(config: ScreenerConfig) -> pd.DataFrame:
    if config.universe == "nasdaq_us":
        return fetch_us_stock_universe(config.min_market_cap)
    if config.universe == "yahoo_regions":
        return fetch_yahoo_region_universe(config.min_market_cap, config.regions)
    if config.universe == "combined":
        frames = [
            fetch_us_stock_universe(config.min_market_cap),
            fetch_yahoo_region_universe(config.min_market_cap, config.regions),
        ]
        out = pd.concat(frames, ignore_index=True, sort=False)
        return out.drop_duplicates("symbol").sort_values("market_cap", ascending=False).reset_index(drop=True)
    raise ValueError(f"Unknown universe: {config.universe}")


def _flatten_yfinance_prices(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol in raw.columns.get_level_values(0):
            raw = raw[symbol]
        elif symbol in raw.columns.get_level_values(-1):
            raw = raw.xs(symbol, level=-1, axis=1)
    raw = raw.rename(columns={str(c): str(c).lower().replace(" ", "_") for c in raw.columns})
    needed = {"open", "high", "low", "close", "volume"}
    if not needed.issubset(set(raw.columns)):
        return pd.DataFrame()
    out = raw[["open", "high", "low", "close", "volume"]].copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.dropna(subset=["close"])
    return out


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_signal(prices: pd.DataFrame, spy_close: pd.Series) -> dict[str, Any] | None:
    if len(prices) < 330:
        return None

    close = prices["close"]
    high = prices["high"]
    low = prices["low"]
    volume = prices["volume"]

    sma50 = close.rolling(50, min_periods=50).mean()
    sma150 = close.rolling(150, min_periods=150).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    ema150 = close.ewm(span=150, adjust=False, min_periods=150).mean()
    ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()

    high52 = high.rolling(252, min_periods=252).max()
    low52 = low.rolling(252, min_periods=252).min()
    near_high = close >= high52 * 0.75
    above_low = close >= low52 * 1.30

    sma_trend = (
        (close > sma50)
        & (close > sma150)
        & (close > sma200)
        & (sma50 > sma150)
        & (sma150 > sma200)
        & (sma200 > sma200.shift(21))
        & near_high
        & above_low
    )
    ema_trend = (
        (close > ema50)
        & (close > ema150)
        & (close > ema200)
        & (ema50 > ema150)
        & (ema150 > ema200)
        & (ema200 > ema200.shift(21))
        & near_high
        & above_low
    )
    trend_ok = sma_trend | ema_trend

    aligned_spy = spy_close.reindex(close.index).ffill()
    rs_line = close / aligned_spy
    rs_avg = rs_line.rolling(63, min_periods=63).mean()
    rs_high = rs_line.rolling(63, min_periods=63).max()
    rs_strong = (rs_line > rs_avg) & (rs_line >= rs_high * 0.98)

    stage2 = (close > sma200) & (sma200 > sma200.shift(21)) & (sma50 > sma150)

    ma10 = close.rolling(10, min_periods=10).mean()
    ma21 = close.ewm(span=21, adjust=False, min_periods=21).mean()
    ma325 = close.rolling(325, min_periods=325).mean()
    oneil_ok = (close > ma10) & (ma10 > ma21) & (ma21 > sma50) & (sma50 > sma200) & (close > ma325)

    resistance = high.shift(1).rolling(50, min_periods=50).max()
    avg_vol = volume.rolling(50, min_periods=50).mean()
    base_range = high.rolling(20, min_periods=20).max() - low.rolling(20, min_periods=20).min()
    base_tight = base_range / close < 0.18
    breakout = (close > resistance) & (volume > avg_vol * 1.25) & base_tight

    down_vol = volume.where(close < close.shift(1), 0.0)
    max_down_vol = down_vol.shift(1).rolling(10, min_periods=10).max()
    pocket_pivot = (close > close.shift(1)) & (volume > max_down_vol) & (close > sma50) & (close > sma200)

    rsi = _rsi(close, 14)
    rsi_extended = rsi >= 75.0

    raw_score = (
        trend_ok.astype(int) * 25
        + stage2.astype(int) * 15
        + rs_strong.astype(int) * 15
        + oneil_ok.astype(int) * 10
        + breakout.astype(int) * 15
        + pocket_pivot.astype(int) * 15
        + ((rsi > 50.0) & (rsi < 75.0)).astype(int) * 5
    )
    score = (raw_score * 100 / 100).round()

    entry_trigger = breakout | pocket_pivot
    entry_signal = trend_ok & stage2 & rs_strong & entry_trigger & (~rsi_extended)
    fresh_buy = entry_signal & (~entry_signal.shift(1).fillna(False))

    last_idx = close.dropna().index[-1]
    prev_idx = close.dropna().index[-2]
    return {
        "last_date": last_idx.date().isoformat(),
        "prev_date": prev_idx.date().isoformat(),
        "close": float(close.loc[last_idx]),
        "score": float(score.loc[last_idx]) if pd.notna(score.loc[last_idx]) else math.nan,
        "rsi": float(rsi.loc[last_idx]) if pd.notna(rsi.loc[last_idx]) else math.nan,
        "trend_ok": bool(trend_ok.loc[last_idx]),
        "stage2": bool(stage2.loc[last_idx]),
        "rs_strong": bool(rs_strong.loc[last_idx]),
        "breakout": bool(breakout.loc[last_idx]),
        "pocket_pivot": bool(pocket_pivot.loc[last_idx]),
        "entry_signal": bool(entry_signal.loc[last_idx]),
        "fresh_buy": bool(fresh_buy.loc[last_idx]),
        "prev_entry_signal": bool(entry_signal.loc[prev_idx]),
    }


def download_prices(symbols: list[str], period: str, batch_size: int, sleep_seconds: float) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for start in range(0, len(symbols), batch_size):
        batch = symbols[start : start + batch_size]
        raw = yf.download(
            tickers=" ".join(batch),
            period=period,
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            progress=False,
            threads=True,
            timeout=60,
        )
        for symbol in batch:
            frame = _flatten_yfinance_prices(raw, symbol)
            if not frame.empty:
                out[symbol] = frame
        time.sleep(sleep_seconds)
    return out


def run(config: ScreenerConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe(config)
    universe.to_csv(config.output_dir / "universe_marketcap_filtered.csv", index=False)

    benchmark_raw = yf.download(
        config.benchmark,
        period=config.period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        timeout=60,
    )
    benchmark_prices = _flatten_yfinance_prices(benchmark_raw, config.benchmark)
    if benchmark_prices.empty:
        raise RuntimeError(f"Could not download benchmark {config.benchmark}")

    prices = download_prices(
        universe["symbol"].tolist(),
        period=config.period,
        batch_size=config.batch_size,
        sleep_seconds=config.sleep_seconds,
    )

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    meta = universe.set_index("symbol").to_dict("index")
    for symbol, frame in prices.items():
        try:
            signal = compute_signal(frame, benchmark_prices["close"])
        except Exception as exc:  # noqa: BLE001
            failures.append({"symbol": symbol, "error": str(exc)})
            continue
        if signal is None:
            failures.append({"symbol": symbol, "error": "not_enough_history"})
            continue
        rows.append({"symbol": symbol, **meta.get(symbol, {}), **signal})

    results = pd.DataFrame(rows).sort_values(["fresh_buy", "score", "market_cap"], ascending=[False, False, False])
    fresh = results[results["fresh_buy"]].copy() if not results.empty else pd.DataFrame()

    results.to_csv(config.output_dir / "minervini_sepa_marketcap2b_all_results.csv", index=False)
    fresh.to_csv(config.output_dir / "minervini_sepa_marketcap2b_fresh_buys.csv", index=False)
    pd.DataFrame(failures).to_csv(config.output_dir / "minervini_sepa_marketcap2b_failures.csv", index=False)

    summary = {
        "min_market_cap": config.min_market_cap,
        "period": config.period,
        "benchmark": config.benchmark,
        "universe": config.universe,
        "regions": list(config.regions),
        "universe_count": int(len(universe)),
        "downloaded_count": int(len(prices)),
        "evaluated_count": int(len(results)),
        "fresh_buy_count": int(len(fresh)),
        "failure_count": int(len(failures)),
        "params": {
            "timeframe": "daily",
            "preset": "Equilibrado",
            "strictness": "Dura",
            "use_minervini_sma": True,
            "use_minervini_ema": True,
            "strict_entry": True,
            "entry_mode": "Breakout or Pocket Pivot",
            "sma_lengths": [50, 150, 200],
            "ema_lengths": [50, 150, 200],
            "rs_lookback": 63,
            "breakout_len": 50,
            "base_len": 20,
            "base_max": 0.18,
            "volume_multiplier": 1.25,
            "pocket_pivot_lookback": 10,
            "rsi_len": 14,
            "rsi_max": 75,
        },
    }
    (config.output_dir / "minervini_sepa_marketcap2b_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))
    if not fresh.empty:
        print(fresh[["symbol", "name", "market_cap", "last_date", "close", "score", "rsi", "breakout", "pocket_pivot"]].to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-market-cap", type=float, default=2_000_000_000.0)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/minervini_sepa_marketcap2b_daily_screener"))
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--period", default="3y")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--universe", choices=["nasdaq_us", "yahoo_regions", "combined"], default="nasdaq_us")
    parser.add_argument(
        "--regions",
        default="us,gb,de,fr,es,it,nl,se,ch,no,dk,fi,be,at,ie,pt,pl",
        help="Yahoo Finance region codes separated by comma",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(
        ScreenerConfig(
            min_market_cap=args.min_market_cap,
            output_dir=args.output_dir,
            batch_size=args.batch_size,
            sleep_seconds=args.sleep_seconds,
            period=args.period,
            benchmark=args.benchmark,
            universe=args.universe,
            regions=tuple(r.strip().lower() for r in args.regions.split(",") if r.strip()),
        )
    )
