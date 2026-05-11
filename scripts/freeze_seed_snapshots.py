"""Freeze approved snapshots for representative R158 seed symbols.

Per spec: 1 equity (SPY), 1 crypto (BTCUSDT), 1 macro (DGS10) at minimum;
also QQQ, TLT, GLD, EFA per acceptance line 3760.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from aurora.data_contracts.timeseries_store import default_store
from aurora.core.snapshots import SnapshotStore
from aurora.core.runtime_paths import base_data_dir


SYMBOLS_TO_FREEZE: Sequence[tuple[str, str]] = (
    ("prices_daily", "SPY"),
    ("prices_daily", "QQQ"),
    ("prices_daily", "TLT"),
    ("prices_daily", "GLD"),
    ("prices_daily", "EFA"),
    ("crypto_daily", "BTCUSDT"),
    ("macro_daily", "DGS10"),
)


def main() -> None:
    ts = default_store()
    snap = SnapshotStore()
    print(f"snapshot index: {snap.index_path}")
    version = datetime.now().strftime("%Y%m%dT%H%M%S")
    n_ok = 0
    n_fail = 0
    for library, symbol in SYMBOLS_TO_FREEZE:
        try:
            df = ts.read(library, symbol)
            if df is None or df.empty:
                print(f"  FAIL {library}:{symbol} -- not in store")
                n_fail += 1
                continue
            if "close" in df.columns:
                series = df["close"]
            elif "value" in df.columns:
                series = df["value"]
            else:
                series = df.iloc[:, 0]
            series.name = symbol
            provenance = f"r158_diversified_seed:{library}:{symbol}:{version}"
            entry = snap.freeze(series, symbol=symbol, provenance=provenance, locked=False)
            sha = getattr(entry, "content_hash", "?")[:12]
            print(f"  OK   {library:<14} {symbol:<10} rows={len(series)} sha={sha}")
            n_ok += 1
        except Exception as exc:
            print(f"  FAIL {library}:{symbol} -- {type(exc).__name__}: {exc}")
            n_fail += 1
    print(f"\nsummary: {n_ok} approved snapshots, {n_fail} fail")


if __name__ == "__main__":
    main()
