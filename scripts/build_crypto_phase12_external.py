from __future__ import annotations

import argparse
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aurora.core.runtime_paths import base_data_dir
from aurora.data_contracts.timeseries_store import TimeSeriesStore
from aurora.research.crypto_direction_ml import EXTERNAL_CRYPTO_FEATURE_BACKLOG


USER_AGENT = "QuantForge/crypto-phase12"
BINANCE_ARCHIVE = "https://data.binance.vision/data/futures/um/daily"
BINANCE_FAPI = "https://fapi.binance.com"
COINMETRICS = "https://community-api.coinmetrics.io/v4"


def _http_bytes(url: str, *, timeout: int = 60, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last = exc
        except Exception as exc:
            last = exc
        time.sleep(0.5 * (attempt + 1))
    if last is None:
        raise RuntimeError(f"failed request: {url}")
    raise last


def _http_json(url: str, *, timeout: int = 60, retries: int = 3) -> Any:
    return json.loads(_http_bytes(url, timeout=timeout, retries=retries).decode("utf-8"))


def _date_range(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    days = pd.date_range(start.normalize(), end.normalize(), freq="D", tz="UTC")
    return [pd.Timestamp(day) for day in days]


def _zip_csv(url: str) -> pd.DataFrame:
    raw = _http_bytes(url)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if not names:
            return pd.DataFrame()
        with zf.open(names[0]) as handle:
            return pd.read_csv(handle)


def _fetch_metrics_day(symbol: str, day: pd.Timestamp) -> pd.DataFrame:
    stamp = day.strftime("%Y-%m-%d")
    url = f"{BINANCE_ARCHIVE}/metrics/{symbol}/{symbol}-metrics-{stamp}.zip"
    try:
        raw = _zip_csv(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return pd.DataFrame()
        raise
    if raw.empty:
        return pd.DataFrame()
    idx = pd.to_datetime(raw["create_time"], utc=True)
    out = pd.DataFrame(index=idx)
    out["open_interest"] = pd.to_numeric(
        raw["sum_open_interest"],
        errors="coerce",
    ).to_numpy()
    out["long_short_ratio"] = pd.to_numeric(
        raw["count_long_short_ratio"],
        errors="coerce",
    ).to_numpy()
    out["taker_buy_sell_ratio"] = pd.to_numeric(
        raw["sum_taker_long_short_vol_ratio"],
        errors="coerce",
    ).to_numpy()
    return out.sort_index()


def fetch_binance_metrics(
    symbol: str,
    index: pd.DatetimeIndex,
    *,
    workers: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    days = _date_range(pd.Timestamp(index.min()), pd.Timestamp(index.max()))
    frames: list[pd.DataFrame] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_metrics_day, symbol, day): day for day in days}
        for future in as_completed(futures):
            try:
                frame = future.result()
            except Exception:
                errors += 1
                continue
            if not frame.empty:
                frames.append(frame)
    merged = pd.concat(frames).sort_index() if frames else pd.DataFrame(index=index)
    return merged.reindex(index), {
        "provider": "binance_vision_metrics",
        "days_requested": len(days),
        "days_loaded": len(frames),
        "errors": errors,
    }


def _fetch_book_depth_day(symbol: str, day: pd.Timestamp) -> pd.DataFrame:
    stamp = day.strftime("%Y-%m-%d")
    url = f"{BINANCE_ARCHIVE}/bookDepth/{symbol}/{symbol}-bookDepth-{stamp}.zip"
    try:
        raw = _zip_csv(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return pd.DataFrame()
        raise
    if raw.empty:
        return pd.DataFrame()
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    raw["percentage"] = pd.to_numeric(raw["percentage"], errors="coerce")
    raw["depth"] = pd.to_numeric(raw["depth"], errors="coerce")
    one_pct = raw[raw["percentage"].isin([-1, 1])]
    if one_pct.empty:
        return pd.DataFrame()
    pivot = one_pct.pivot_table(
        index="timestamp",
        columns="percentage",
        values="depth",
        aggfunc="last",
    ).sort_index()
    bid = pivot.get(-1.0, pivot.get(-1))
    ask = pivot.get(1.0, pivot.get(1))
    out = pd.DataFrame(index=pivot.index)
    out["depth_1pct_bid"] = bid
    out["depth_1pct_ask"] = ask
    denom = (bid + ask).replace(0.0, np.nan)
    out["orderbook_imbalance"] = (bid - ask) / denom
    return out.resample("5min").last()


def fetch_binance_book_depth(
    symbol: str,
    index: pd.DatetimeIndex,
    *,
    workers: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    days = _date_range(pd.Timestamp(index.min()), pd.Timestamp(index.max()))
    frames: list[pd.DataFrame] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_book_depth_day, symbol, day): day for day in days}
        for future in as_completed(futures):
            try:
                frame = future.result()
            except Exception:
                errors += 1
                continue
            if not frame.empty:
                frames.append(frame)
    merged = pd.concat(frames).sort_index() if frames else pd.DataFrame(index=index)
    return merged.reindex(index), {
        "provider": "binance_vision_bookDepth",
        "days_requested": len(days),
        "days_loaded": len(frames),
        "errors": errors,
    }


def _binance_klines(
    path: str,
    symbol: str,
    index: pd.DatetimeIndex,
    *,
    interval: str = "5m",
    limit: int = 1500,
) -> pd.DataFrame:
    start_ms = int(pd.Timestamp(index.min()).timestamp() * 1000)
    end_ms = int(pd.Timestamp(index.max()).timestamp() * 1000)
    rows: list[list[Any]] = []
    while start_ms <= end_ms:
        params = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
                "startTime": start_ms,
                "endTime": end_ms,
            }
        )
        data = _http_json(f"{BINANCE_FAPI}{path}?{params}")
        if not data:
            break
        rows.extend(data)
        last_open = int(data[-1][0])
        next_start = last_open + 300_000
        if next_start <= start_ms:
            break
        start_ms = next_start
        time.sleep(0.05)
    if not rows:
        return pd.DataFrame(index=index)
    raw = pd.DataFrame(rows)
    out = pd.DataFrame(index=pd.to_datetime(raw[0], unit="ms", utc=True))
    out["open"] = pd.to_numeric(raw[1], errors="coerce").to_numpy()
    out["high"] = pd.to_numeric(raw[2], errors="coerce").to_numpy()
    out["low"] = pd.to_numeric(raw[3], errors="coerce").to_numpy()
    out["close"] = pd.to_numeric(raw[4], errors="coerce").to_numpy()
    return out[~out.index.duplicated(keep="last")].sort_index().reindex(index)


def fetch_binance_funding(symbol: str, index: pd.DatetimeIndex) -> tuple[pd.Series, dict[str, Any]]:
    start_ms = int(pd.Timestamp(index.min()).timestamp() * 1000)
    end_ms = int(pd.Timestamp(index.max()).timestamp() * 1000)
    rows: list[dict[str, Any]] = []
    while start_ms <= end_ms:
        params = urllib.parse.urlencode(
            {"symbol": symbol, "limit": 1000, "startTime": start_ms, "endTime": end_ms}
        )
        data = _http_json(f"{BINANCE_FAPI}/fapi/v1/fundingRate?{params}")
        if not data:
            break
        rows.extend(data)
        last_time = int(data[-1]["fundingTime"])
        next_start = last_time + 1
        if next_start <= start_ms:
            break
        start_ms = next_start
        time.sleep(0.05)
    if not rows:
        return pd.Series(index=index, dtype=float), {"provider": "binance_fundingRate", "rows": 0}
    raw = pd.DataFrame(rows)
    series = pd.Series(
        pd.to_numeric(raw["fundingRate"], errors="coerce").to_numpy(),
        index=pd.to_datetime(raw["fundingTime"], unit="ms", utc=True),
    ).sort_index()
    return series.reindex(index, method="ffill"), {
        "provider": "binance_fundingRate",
        "rows": len(rows),
    }


def fetch_binance_premium_basis(
    symbol: str,
    spot_close: pd.Series,
    index: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    premium = _binance_klines("/fapi/v1/premiumIndexKlines", symbol, index)
    mark = _binance_klines("/fapi/v1/markPriceKlines", symbol, index)
    out = pd.DataFrame(index=index)
    out["perp_premium"] = premium["close"]
    out["basis_spot_perp"] = mark["close"] / spot_close.replace(0.0, np.nan) - 1.0
    return out, {
        "provider": "binance_fapi_premium_mark_klines",
        "premium_rows": int(premium["close"].notna().sum()),
        "mark_rows": int(mark["close"].notna().sum()),
    }


def fetch_fear_greed(index: pd.DatetimeIndex) -> tuple[pd.Series, dict[str, Any]]:
    payload = _http_json("https://api.alternative.me/fng/?limit=0&format=json")
    rows = payload.get("data") or []
    if not rows:
        return pd.Series(index=index, dtype=float), {"provider": "alternative_me_fng", "rows": 0}
    raw = pd.DataFrame(rows)
    series = pd.Series(
        pd.to_numeric(raw["value"], errors="coerce").to_numpy(),
        index=pd.to_datetime(pd.to_numeric(raw["timestamp"], errors="coerce"), unit="s", utc=True),
    ).sort_index()
    feature = series.shift(1)
    return feature.reindex(index, method="ffill"), {
        "provider": "alternative_me_fng",
        "rows": len(rows),
    }


def _coinmetrics_metric(
    assets: str,
    metrics: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    params = urllib.parse.urlencode(
        {
            "assets": assets,
            "metrics": metrics,
            "start_time": start.strftime("%Y-%m-%d"),
            "end_time": (end + timedelta(days=1)).strftime("%Y-%m-%d"),
            "frequency": "1d",
        }
    )
    payload = _http_json(f"{COINMETRICS}/timeseries/asset-metrics?{params}", timeout=90)
    rows = payload.get("data") or []
    if not rows:
        return pd.DataFrame()
    raw = pd.DataFrame(rows)
    raw["time"] = pd.to_datetime(raw["time"], utc=True)
    return raw


def _align_daily(index: pd.DatetimeIndex, series: pd.Series, *, shift_days: int = 1) -> pd.Series:
    daily = series.copy().sort_index()
    daily.index = pd.DatetimeIndex(daily.index).tz_convert("UTC").normalize()
    return daily.shift(shift_days).reindex(index, method="ffill")


def fetch_coinmetrics_daily(index: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, Any]]:
    start = pd.Timestamp(index.min()).normalize()
    end = pd.Timestamp(index.max()).normalize()
    out = pd.DataFrame(index=index)
    notes: dict[str, Any] = {"provider": "coinmetrics_community", "licence": "community_non_commercial"}

    try:
        flows = _coinmetrics_metric("btc", "FlowInExNtv,FlowOutExNtv", start, end)
        if not flows.empty:
            flow_in = pd.to_numeric(flows["FlowInExNtv"], errors="coerce")
            flow_out = pd.to_numeric(flows["FlowOutExNtv"], errors="coerce")
            net = pd.Series((flow_in - flow_out).to_numpy(), index=flows["time"])
            out["exchange_netflow_btc"] = _align_daily(index, net)
            notes["exchange_netflow_rows"] = int(net.notna().sum())
    except Exception as exc:
        notes["exchange_netflow_error"] = str(exc)

    try:
        stable = _coinmetrics_metric("usdt,usdc", "SplyCur", start, end)
        if not stable.empty:
            stable["SplyCur"] = pd.to_numeric(stable["SplyCur"], errors="coerce")
            supply = stable.pivot_table(index="time", columns="asset", values="SplyCur", aggfunc="last").sum(axis=1)
            out["stablecoin_supply_change"] = _align_daily(index, supply.diff())
            notes["stablecoin_supply_rows"] = int(supply.notna().sum())
    except Exception as exc:
        notes["stablecoin_supply_error"] = str(exc)

    cap_assets = ("btc", "eth", "usdt", "usdc", "xrp", "doge", "ada", "link")
    cap_frames: list[pd.DataFrame] = []
    for asset in cap_assets:
        try:
            cap = _coinmetrics_metric(asset, "CapMrktCurUSD", start, end)
        except Exception:
            continue
        if not cap.empty:
            cap_frames.append(cap)
    if cap_frames:
        caps = pd.concat(cap_frames, ignore_index=True)
        caps["CapMrktCurUSD"] = pd.to_numeric(caps["CapMrktCurUSD"], errors="coerce")
        pivot = caps.pivot_table(index="time", columns="asset", values="CapMrktCurUSD", aggfunc="last")
        total_proxy = pivot.sum(axis=1)
        btc_cap = pivot.get("btc")
        out["total_crypto_market_cap"] = _align_daily(index, total_proxy)
        if btc_cap is not None:
            out["btc_dominance"] = _align_daily(index, btc_cap / total_proxy.replace(0.0, np.nan))
        notes["market_cap_proxy_assets"] = [asset for asset in cap_assets if asset in pivot.columns]
        notes["market_cap_proxy_not_full_market"] = True

    try:
        miner = _coinmetrics_metric("btc", "SplyMiner0HopAllNtv", start, end)
        if not miner.empty:
            values = pd.to_numeric(miner["SplyMiner0HopAllNtv"], errors="coerce")
            out["miner_reserve_change"] = _align_daily(index, pd.Series(values.to_numpy(), index=miner["time"]).diff())
    except Exception as exc:
        notes["miner_reserve_unavailable"] = str(exc)

    return out, notes


def build_phase12_external_panel(
    source: pd.DataFrame,
    *,
    symbol: str = "BTCUSDT",
    workers: int = 8,
    include_book_depth: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    index = pd.DatetimeIndex(source.index)
    out = pd.DataFrame(index=index)
    for column in EXTERNAL_CRYPTO_FEATURE_BACKLOG:
        out[column] = np.nan
    notes: dict[str, Any] = {"symbol": symbol, "columns": list(EXTERNAL_CRYPTO_FEATURE_BACKLOG)}

    try:
        metrics, note = fetch_binance_metrics(symbol, index, workers=workers)
        out.update(metrics)
        notes["binance_metrics"] = note
    except Exception as exc:
        notes["binance_metrics"] = {"status": "unavailable", "error": str(exc)}

    try:
        funding, note = fetch_binance_funding(symbol, index)
        out["funding_rate"] = funding
        notes["binance_funding"] = note
    except Exception as exc:
        notes["binance_funding"] = {"status": "unavailable", "error": str(exc)}

    try:
        premium_basis, note = fetch_binance_premium_basis(symbol, source["close"].astype(float), index)
        out.update(premium_basis)
        notes["binance_premium_basis"] = note
    except Exception as exc:
        notes["binance_premium_basis"] = {"status": "unavailable", "error": str(exc)}

    if include_book_depth:
        try:
            depth, note = fetch_binance_book_depth(symbol, index, workers=workers)
            out.update(depth)
            notes["binance_book_depth"] = note
        except Exception as exc:
            notes["binance_book_depth"] = {"status": "unavailable", "error": str(exc)}

    try:
        fear, note = fetch_fear_greed(index)
        out["fear_greed_index"] = fear
        notes["fear_greed"] = note
    except Exception as exc:
        notes["fear_greed"] = {"status": "unavailable", "error": str(exc)}

    try:
        coinmetrics, note = fetch_coinmetrics_daily(index)
        out.update(coinmetrics)
        notes["coinmetrics"] = note
    except Exception as exc:
        notes["coinmetrics"] = {"status": "unavailable", "error": str(exc)}

    out = out.replace([np.inf, -np.inf], np.nan)
    notes["non_null_by_column"] = {column: int(out[column].notna().sum()) for column in out.columns}
    notes["missing_columns"] = [column for column in out.columns if int(out[column].notna().sum()) == 0]
    return out, notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--source-library", default="crypto_5m")
    parser.add_argument("--source-version", default="binance_5m_36m")
    parser.add_argument("--output-library", default="crypto_5m_external")
    parser.add_argument("--output-version", default="binance_5m_36m_phase12_v1")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-book-depth", action="store_true")
    args = parser.parse_args()

    store = TimeSeriesStore(base_data_dir() / "timeseries")
    source = store.read(args.source_library, args.symbol, version=args.source_version)
    panel, notes = build_phase12_external_panel(
        source,
        symbol=args.symbol,
        workers=args.workers,
        include_book_depth=not args.skip_book_depth,
    )
    record = store.put(
        args.output_library,
        args.symbol,
        panel,
        version=args.output_version,
        replace=True,
        metadata={
            "source_library": args.source_library,
            "source_version": args.source_version,
            "feature_group": "12",
            "locked_opened": False,
            "notes": notes,
        },
    )
    summary = {
        "library": record.library,
        "symbol": record.symbol,
        "version": record.version,
        "rows": record.n_rows,
        "columns": len(record.columns),
        "non_null_by_column": notes["non_null_by_column"],
        "missing_columns": notes["missing_columns"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
