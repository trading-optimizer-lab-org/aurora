"""Re-fetch R158 macro section using FRED's free CSV endpoint."""
from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from aurora.data_contracts.timeseries_store import default_store  # noqa: E402

MACRO_SERIES = [
    "DGS1", "DGS2", "DGS5", "DGS10", "DGS30",
    "T10Y2Y", "T10Y3M", "FEDFUNDS", "SOFR", "UNRATE",
    "CPIAUCSL", "CORESTICKM159SFRBATL", "PAYEMS", "VIXCLS", "BAMLH0A0HYM2",
]
START = "2015-01-01"
HTTP_TIMEOUT = 30


def fetch_fred_csv(series: str) -> pd.DataFrame | None:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200 or not r.text.strip():
            return None
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        date_col = "observation_date" if "observation_date" in df.columns else "DATE"
        df["date"] = pd.to_datetime(df[date_col]).dt.tz_localize(None)
        df = df.set_index("date").drop(columns=[date_col])
        df = df[df.index >= pd.Timestamp(START)]
        df = df.replace(".", pd.NA).dropna()
        if df.empty:
            return None
        df = df.rename(columns={series: "value"})
        return df[["value"]].astype({"value": "float64"})
    except Exception as exc:
        print(f"  exc {series}: {exc}")
        return None


def main() -> None:
    store = default_store()
    version = datetime.now().strftime("%Y%m%dT%H%M%S")
    ok = 0
    fail = 0
    for s in MACRO_SERIES:
        df = fetch_fred_csv(s)
        if df is None or df.empty:
            print(f"  FAIL {s}")
            fail += 1
            continue
        rec = store.put("macro_daily", s, df, version=version, metadata={
            "provider": "fred_csv",
            "endpoint": "https://fred.stlouisfed.org/graph/fredgraph.csv",
            "manifest": "diversified_seed",
            "section": "macro",
        }, replace=True)
        print(f"  OK   {s:<22} rows={rec.n_rows}")
        ok += 1
    print(f"\nsummary: {ok} ok, {fail} fail")


if __name__ == "__main__":
    main()
