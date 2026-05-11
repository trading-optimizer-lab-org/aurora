"""Fix R158 download bugs:

1. Re-fetch all 10 crypto from Binance with correct timestamp scale detection
   (ms vs us; Binance switched format in 2024).
2. Persist SEC fundamentals JSONs into TimeSeriesStore under library
   ``fundamentals`` (one row-per-fact frame keyed on accession_number).
3. Re-freeze BTCUSDT snapshot with corrected dates.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from aurora.data_contracts.timeseries_store import default_store
from aurora.core.snapshots import SnapshotStore
from aurora.core.runtime_paths import base_data_dir


CRYPTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT",
]
START = "2015-01-01"
HTTP_TIMEOUT = 30


def detect_unit(ts_value: int) -> str:
    """13 digits = ms, 16 digits = us (Binance format change in 2024)."""
    digits = len(str(int(ts_value)))
    if digits >= 16:
        return "us"
    if digits >= 13:
        return "ms"
    return "s"


def fetch_binance_klines(pair: str, start: str = START) -> pd.DataFrame | None:
    sym = pair.upper()
    start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    today = date.today()
    frames: list[pd.DataFrame] = []
    cur = start_dt.replace(day=1)
    while cur <= today:
        ym = cur.strftime("%Y-%m")
        url = f"https://data.binance.vision/data/spot/monthly/klines/{sym}/1d/{sym}-1d-{ym}.zip"
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                _bump(cur)
                cur = _next_month(cur)
                continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                csv_name = zf.namelist()[0]
                with zf.open(csv_name) as f:
                    df = pd.read_csv(f, header=None, names=[
                        "open_time", "open", "high", "low", "close", "volume",
                        "close_time", "quote_volume", "trades", "taker_buy_base",
                        "taker_buy_quote", "ignore",
                    ])
                    if df.empty:
                        cur = _next_month(cur)
                        continue
                    unit = detect_unit(df["open_time"].iloc[0])
                    df["date"] = (
                        pd.to_datetime(df["open_time"], unit=unit)
                        .dt.tz_localize(None)
                        .dt.normalize()
                    )
                    df = df.set_index("date")
                    frames.append(df[["open", "high", "low", "close", "volume"]])
        except Exception as exc:
            print(f"    {pair} {ym} exc: {exc}")
        cur = _next_month(cur)
    if not frames:
        return None
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _bump(_):
    return None


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def refetch_crypto(store) -> int:
    version = datetime.now().strftime("%Y%m%dT%H%M%S")
    n_ok = 0
    for sym in CRYPTO_SYMBOLS:
        df = fetch_binance_klines(sym)
        if df is None or df.empty:
            print(f"  FAIL {sym}")
            continue
        # contract gate: dates must be plausible (no future)
        max_date = df.index.max()
        if max_date > pd.Timestamp.now() + pd.Timedelta(days=2):
            print(f"  REJECT {sym} max_date={max_date} > today; bug not fully fixed")
            continue
        rec = store.put("crypto_daily", sym, df, version=version, metadata={
            "provider": "binance_public_data",
            "section": "crypto",
            "manifest": "diversified_seed",
            "fix": "timestamp_scale_detection",
        }, replace=True)
        print(f"  OK   {sym:<10} rows={rec.n_rows} first={df.index.min().date()} last={df.index.max().date()}")
        n_ok += 1
    return n_ok


def persist_sec_fundamentals(store) -> int:
    """Read each SEC JSON and persist a flat fact frame to TimeSeriesStore."""
    src_dir = base_data_dir() / "fundamentals_sec"
    if not src_dir.exists():
        print(f"  no SEC dir: {src_dir}")
        return 0
    version = datetime.now().strftime("%Y%m%dT%H%M%S")
    n_ok = 0
    for path in sorted(src_dir.glob("*.json")):
        ticker = path.stem.split("_")[0]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cik = data.get("cik")
            facts_root = data.get("facts", {}).get("facts", {})
            rows = []
            for taxonomy, tags in facts_root.items():
                for tag, body in tags.items():
                    units = body.get("units", {})
                    for unit, entries in units.items():
                        for entry in entries:
                            end = entry.get("end")
                            if not end:
                                continue
                            rows.append({
                                "date": pd.to_datetime(end),
                                "taxonomy": taxonomy,
                                "tag": tag,
                                "unit": unit,
                                "value": entry.get("val"),
                                "form": entry.get("form"),
                                "accession": entry.get("accn"),
                                "filed": entry.get("filed"),
                                "fy": entry.get("fy"),
                                "fp": entry.get("fp"),
                            })
            if not rows:
                print(f"  FAIL {ticker} no facts")
                continue
            df = pd.DataFrame(rows).set_index("date").sort_index()
            rec = store.put("fundamentals", ticker, df, version=version, metadata={
                "provider": "sec_edgar",
                "section": "fundamentals",
                "manifest": "diversified_seed",
                "cik": cik,
                "raw_path": str(path),
            }, replace=True)
            print(f"  OK   {ticker:<10} cik={cik} rows={rec.n_rows}")
            n_ok += 1
        except Exception as exc:
            print(f"  FAIL {ticker} {type(exc).__name__}: {exc}")
    return n_ok


def refreeze_crypto(store, snap, symbol: str = "BTCUSDT") -> bool:
    df = store.read("crypto_daily", symbol)
    if df is None or df.empty:
        print(f"  FAIL refreeze {symbol} empty")
        return False
    series = df["close"]
    series.name = symbol
    version = datetime.now().strftime("%Y%m%dT%H%M%S")
    provenance = f"r158_refrozen:{symbol}:{version}"
    snap.freeze(series, symbol=symbol, provenance=provenance, locked=False)
    print(f"  OK   refreeze {symbol} rows={len(series)} first={df.index.min().date()} last={df.index.max().date()}")
    return True


def main() -> None:
    store = default_store()
    snap = SnapshotStore()
    print("=== Fix 1: re-fetch crypto with ms/us auto-detect ===")
    crypto_ok = refetch_crypto(store)
    print(f"crypto: {crypto_ok}/10 ok")
    print("\n=== Fix 2: persist SEC fundamentals into TimeSeriesStore ===")
    sec_ok = persist_sec_fundamentals(store)
    print(f"sec: {sec_ok}/20 ok")
    print("\n=== Fix 3: re-freeze BTCUSDT snapshot ===")
    refreeze_ok = refreeze_crypto(store, snap, "BTCUSDT")
    print(f"refreeze: {'ok' if refreeze_ok else 'fail'}")


if __name__ == "__main__":
    main()
