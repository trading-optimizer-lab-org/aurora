"""Real-network bootstrap of the R158 diversified seed manifest.

Operator action only. Reads `config/diversified_seed_dataset.yaml`,
fetches data from free providers, persists into the local TimeSeriesStore,
and prints a coverage report.

Providers used:
- yfinance for equities / ETFs / FX (free, unofficial Yahoo API).
- Binance Public Data ZIPs for crypto (free, no auth).
- DBnomics for macro (FRED redistributed; free, no auth).
- SEC EDGAR for fundamentals (free, requires User-Agent).
- OpenFIGI for identity (free, low rate).

Skipped without operator credentials:
- Stooq (requires API key / CAPTCHA per current Stooq policy).
- Tiingo (requires AU_TIINGO_API_TOKEN).
- Dukascopy / MarketDataApp (gated env vars).
"""
from __future__ import annotations

import io
import argparse
import json
import os
import time
import warnings
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
import yaml

warnings.filterwarnings("ignore")

import yfinance as yf  # noqa: E402
import pandas as pd  # noqa: E402

from aurora.data_contracts.timeseries_store import default_store  # noqa: E402
from aurora.core.runtime_paths import base_data_dir  # noqa: E402


SEC_USER_AGENT = os.environ.get(
    "AU_SEC_EDGAR_USER_AGENT",
    "Aurora research operator@example.com",
)
DEFAULT_START = "2015-01-01"
START = DEFAULT_START
END = None  # today
HTTP_TIMEOUT = 30

# Binance spot data did not exist in 1995. For late-entry runs, starting each
# crypto pair at a realistic first month avoids thousands of guaranteed 404s.
BINANCE_SPOT_FIRST_MONTH = {
    "BTCUSDT": "2017-08-01",
    "ETHUSDT": "2017-08-01",
    "BNBUSDT": "2017-11-01",
    "XRPUSDT": "2018-05-01",
    "ADAUSDT": "2018-04-01",
    "DOGEUSDT": "2019-07-01",
    "LINKUSDT": "2019-01-01",
    "SOLUSDT": "2020-08-01",
    "DOTUSDT": "2020-08-01",
    "AVAXUSDT": "2020-09-01",
}

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "config" / "diversified_seed_dataset.yaml"


def now_iso() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def normalise_yfinance_df(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Flatten yfinance MultiIndex (Price, Ticker) to plain OHLCV."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    return df[["open", "high", "low", "close", "adj_close", "volume"]]


def fetch_yfinance(symbol: str, start: str | None = None) -> pd.DataFrame | None:
    try:
        start = START if start is None else start
        df = yf.download(symbol, start=start, end=END, progress=False, auto_adjust=False, threads=False)
        if df is None or df.empty:
            return None
        return normalise_yfinance_df(df, symbol)
    except Exception:
        return None


def binance_effective_start(pair: str, start: str) -> str:
    requested = datetime.strptime(start, "%Y-%m-%d").date()
    first = datetime.strptime(
        BINANCE_SPOT_FIRST_MONTH.get(pair.upper(), "2017-01-01"),
        "%Y-%m-%d",
    ).date()
    return max(requested, first).isoformat()


def fetch_binance_klines(pair: str, start: str | None = None) -> pd.DataFrame | None:
    """Aggregate Binance daily klines from monthly ZIPs."""
    sym = pair.upper()
    start = START if start is None else start
    start_dt = datetime.strptime(binance_effective_start(sym, start), "%Y-%m-%d").date()
    today = datetime.strptime(END, "%Y-%m-%d").date() if END else date.today()
    if start_dt > today:
        return None
    frames: list[pd.DataFrame] = []
    cur = start_dt.replace(day=1)
    while cur <= today:
        ym = cur.strftime("%Y-%m")
        url = f"https://data.binance.vision/data/spot/monthly/klines/{sym}/1d/{sym}-1d-{ym}.zip"
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                next_year = cur.year + (1 if cur.month == 12 else 0)
                next_month = 1 if cur.month == 12 else cur.month + 1
                cur = date(next_year, next_month, 1)
                continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                csv_name = zf.namelist()[0]
                with zf.open(csv_name) as f:
                    df = pd.read_csv(f, header=None, names=[
                        "open_time", "open", "high", "low", "close", "volume",
                        "close_time", "quote_volume", "trades", "taker_buy_base",
                        "taker_buy_quote", "ignore",
                    ])
                    df["date"] = pd.to_datetime(df["open_time"], unit="ms").dt.tz_localize(None).dt.normalize()
                    df = df.set_index("date")
                    frames.append(df[["open", "high", "low", "close", "volume"]])
        except Exception:
            pass
        next_year = cur.year + (1 if cur.month == 12 else 0)
        next_month = 1 if cur.month == 12 else cur.month + 1
        cur = date(next_year, next_month, 1)
    if not frames:
        return None
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


# DBnomics-via-FRED series-key map (each US macro series under FRED/* dataset).
DBNOMICS_FRED_KEYS = {
    "DGS1": "FRED/H15/RIFLGFCY01_N_B",
    "DGS2": "FRED/H15/RIFLGFCY02_N_B",
    "DGS5": "FRED/H15/RIFLGFCY05_N_B",
    "DGS10": "FRED/H15/RIFLGFCY10_N_B",
    "DGS30": "FRED/H15/RIFLGFCY30_N_B",
    "T10Y2Y": "FRED/T10Y2Y/T10Y2Y",
    "T10Y3M": "FRED/T10Y3M/T10Y3M",
    "FEDFUNDS": "FRED/FEDFUNDS/FEDFUNDS",
    "SOFR": "FRED/SOFR/SOFR",
    "UNRATE": "FRED/UNRATE/UNRATE",
    "CPIAUCSL": "FRED/CPIAUCSL/CPIAUCSL",
    "CORESTICKM159SFRBATL": "FRED/CORESTICKM159SFRBATL/CORESTICKM159SFRBATL",
    "PAYEMS": "FRED/PAYEMS/PAYEMS",
    "VIXCLS": "FRED/VIXCLS/VIXCLS",
    "BAMLH0A0HYM2": "FRED/BAMLH0A0HYM2/BAMLH0A0HYM2",
}


def fetch_dbnomics_series(fred_id: str) -> pd.DataFrame | None:
    triple = DBNOMICS_FRED_KEYS.get(fred_id)
    if triple is None:
        return None
    url = f"https://api.db.nomics.world/v22/series/{triple}?observations=1"
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        docs = data.get("series", {}).get("docs", [])
        if not docs:
            return None
        obs = docs[0]
        periods = obs.get("period", [])
        values = obs.get("value", [])
        df = pd.DataFrame({
            "date": pd.to_datetime(periods),
            "value": values,
        }).dropna()
        df = df.set_index("date").sort_index()
        return df
    except Exception:
        return None


# FX yfinance suffix
def yf_fx_symbol(pair: str) -> str:
    return f"{pair}=X" if pair != "DXY" else "DX-Y.NYB"


def fetch_sec_companyfacts(ticker: str) -> dict[str, Any] | None:
    """Get CIK from ticker map, then companyfacts JSON."""
    try:
        headers = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        m = r.json()
        cik = None
        for entry in m.values():
            if entry.get("ticker") == ticker.upper():
                cik = int(entry["cik_str"])
                break
        if cik is None:
            return None
        time.sleep(0.15)  # SEC rate-limit etiquette
        cik_padded = f"CIK{cik:010d}"
        r2 = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/{cik_padded}.json",
            headers=headers, timeout=HTTP_TIMEOUT,
        )
        if r2.status_code != 200:
            return None
        return {"cik": cik, "facts": r2.json()}
    except Exception:
        return None


def fetch_openfigi(ticker: str) -> list[dict] | None:
    try:
        r = requests.post(
            "https://api.openfigi.com/v3/mapping",
            json=[{"idType": "TICKER", "idValue": ticker, "exchCode": "US"}],
            headers={"Content-Type": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        out = r.json()
        if out and out[0].get("data"):
            return out[0]["data"]
        return []
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Download diversified seed dataset into the Aurora TimeSeriesStore.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()
    global START, END
    START = str(args.start)
    END = str(args.end) if args.end else None
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    sections = manifest["sections"]
    store = default_store()

    report: dict[str, Any] = {"started_iso": now_iso(), "sections": {}}
    version = now_iso()

    print(f"AURORA real-network bootstrap of '{manifest['name']}'")
    print(f"start={START} end={END or 'today'} version={version}")
    print(f"data dir: {base_data_dir()}")
    print()

    for sec_name, sec_cfg in sections.items():
        symbols = sec_cfg["symbols"]
        library = sec_cfg["library"]
        sec_report = {"library": library, "requested": len(symbols), "ok": 0, "fail": 0, "results": []}
        print(f"\n[{sec_name}] library={library} requested={len(symbols)}")

        for sym in symbols:
            persisted = False
            provider = "-"
            rows = 0
            first_date = None
            last_date = None
            error = None
            try:
                if sec_name == "fx":
                    df = fetch_yfinance(yf_fx_symbol(sym), start=START)
                    provider = "yfinance"
                elif sec_name == "crypto":
                    df = fetch_binance_klines(sym, start=START)
                    provider = "binance_public_data"
                elif sec_name == "macro":
                    df = fetch_dbnomics_series(sym)
                    provider = "dbnomics_fred"
                elif sec_name == "fundamentals":
                    facts = fetch_sec_companyfacts(sym)
                    if facts:
                        out_dir = base_data_dir() / "fundamentals_sec"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        path = out_dir / f"{sym}_{version}.json"
                        path.write_text(json.dumps(facts, indent=2), encoding="utf-8")
                        rows = len(facts.get("facts", {}).get("facts", {}).get("us-gaap", {}))
                        provider = "sec_edgar"
                        persisted = True
                        time.sleep(0.15)
                    df = None
                else:
                    df = fetch_yfinance(sym, start=START)
                    provider = "yfinance"
                if df is not None and not df.empty:
                    if END is not None:
                        df = df.loc[: pd.Timestamp(END)]
                    rows = len(df)
                    first_date = str(pd.to_datetime(df.index).min().date())
                    last_date = str(pd.to_datetime(df.index).max().date())
                    df_to_store = df.reset_index()
                    df_to_store.columns = [str(c).lower() for c in df_to_store.columns]
                    rec = store.put(library, sym, df, version=version, metadata={
                        "provider": provider,
                        "retrieved_at": version,
                        "manifest": manifest["name"],
                        "section": sec_name,
                    }, replace=True)
                    rows = rec.n_rows
                    persisted = True
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            if persisted:
                sec_report["ok"] += 1
                sec_report["results"].append({"symbol": sym, "provider": provider, "rows": rows, "start": first_date, "end": last_date})
                print(f"  OK  {sym:<12} via {provider:<22} rows={rows} start={first_date} end={last_date}")
            else:
                sec_report["fail"] += 1
                sec_report["results"].append({"symbol": sym, "provider": provider, "rows": 0, "error": error or "empty"})
                print(f"  FAIL {sym:<12} via {provider:<22} {error or 'empty'}")

        # Identity via OpenFIGI: only for first 3 large caps to stay under rate limit.
        if sec_name == "fundamentals":
            for sym in symbols[:3]:
                try:
                    mapping = fetch_openfigi(sym)
                    if mapping:
                        out = base_data_dir() / "identity_openfigi"
                        out.mkdir(parents=True, exist_ok=True)
                        (out / f"{sym}_{version}.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
                        time.sleep(0.3)
                except Exception:
                    pass

        report["sections"][sec_name] = sec_report

    report["finished_iso"] = now_iso()
    out_path = base_data_dir() / f"diversified_seed_real_run_{version}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport: {out_path}")

    total_ok = sum(s["ok"] for s in report["sections"].values())
    total_fail = sum(s["fail"] for s in report["sections"].values())
    print(f"\nsummary: {total_ok} ok, {total_fail} fail")


if __name__ == "__main__":
    main()
