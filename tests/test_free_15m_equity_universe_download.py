from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.download_free_15m_equity_universe import (
    DEFAULT_SYMBOLS,
    filter_regular_session,
    normalise_yfinance_ohlcv,
    parse_symbols,
    write_aligned_universe,
)


def make_15m_bars(days: int = 25, *, offset: float = 0.0) -> pd.DataFrame:
    stamps = []
    for day in pd.bdate_range("2026-01-02", periods=days):
        start = day + pd.Timedelta(hours=9, minutes=30)
        stamps.extend(start + pd.Timedelta(minutes=15 * i) for i in range(26))
    idx = pd.DatetimeIndex(stamps)
    close = pd.Series(100.0 + offset + np.arange(len(idx)) * 0.01, index=idx)
    return pd.DataFrame(
        {
            "Open": close - 0.05,
            "High": close + 0.10,
            "Low": close - 0.10,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )


def test_default_symbol_list_has_at_least_20_unique_names() -> None:
    assert len(DEFAULT_SYMBOLS) >= 20
    assert len(set(DEFAULT_SYMBOLS)) == len(DEFAULT_SYMBOLS)
    assert parse_symbols("aapl, MSFT,,aapl\nNVDA") == ["AAPL", "MSFT", "NVDA"]


def test_normalise_yfinance_multiindex_and_regular_session() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-01-02 08:00",
            "2026-01-02 09:30",
            "2026-01-02 15:45",
            "2026-01-02 16:00",
        ]
    )
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL"]])
    raw = pd.DataFrame(
        [
            [99.0, 100.0, 98.0, 99.5, 1],
            [100.0, 101.0, 99.0, 100.5, 2],
            [101.0, 102.0, 100.0, 101.5, 3],
            [102.0, 103.0, 101.0, 102.5, 4],
        ],
        index=idx,
        columns=columns,
    )

    out = normalise_yfinance_ohlcv(raw, symbol="AAPL")

    assert list(out.index) == [idx[1], idx[2]]
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert out.iloc[-1]["Close"] == 101.5


def test_filter_regular_session_keeps_cash_bars_only() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-01-02 09:15",
            "2026-01-02 09:30",
            "2026-01-02 15:45",
            "2026-01-02 16:00",
            "2026-01-03 09:30",
        ]
    )
    bars = pd.DataFrame({"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 1}, index=idx)

    out = filter_regular_session(bars)

    assert list(out.index) == [idx[1], idx[2]]


def test_write_aligned_universe_uses_exact_shared_timestamp_index(tmp_path: Path) -> None:
    frames = {
        "AAA": make_15m_bars(days=25, offset=1.0),
        "BBB": make_15m_bars(days=25, offset=2.0).iloc[10:],
        "CCC": make_15m_bars(days=25, offset=3.0).iloc[:-5],
    }

    manifest = write_aligned_universe(
        frames,
        output_dir=tmp_path,
        requested_symbols=["AAA", "BBB", "CCC"],
        requested_period="60d",
        interval="15m",
        source="test",
        failures=[],
        min_symbols=3,
    )

    assert manifest["symbol_count"] == 3
    assert manifest["common_rows_per_symbol"] == len(frames["AAA"].index[10:-5])
    assert manifest["common_start"] == str(frames["AAA"].index[10])
    assert manifest["common_end"] == str(frames["AAA"].index[-6])

    aaa = pd.read_csv(tmp_path / "data" / "AAA_15m.csv")
    bbb = pd.read_csv(tmp_path / "data" / "BBB_15m.csv")
    ccc = pd.read_csv(tmp_path / "data" / "CCC_15m.csv")
    assert aaa["timestamp"].tolist() == bbb["timestamp"].tolist() == ccc["timestamp"].tolist()
    assert (tmp_path / "wide" / "close.csv").exists()
    assert (tmp_path / "wide" / "close.parquet").exists()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "summary.csv").exists()


def test_free_15m_universe_workflow_is_manual_and_uploads_artifact() -> None:
    path = Path(".github/workflows/free-15m-equity-universe-download.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "Free 15m Equity Universe Download"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    assert data[True]["workflow_dispatch"]["inputs"]["period"]["default"] == "60d"
    assert data[True]["workflow_dispatch"]["inputs"]["min_symbols"]["default"] == "20"
    assert "--interval 15m" in text
    assert "free-15m-equity-universe-yfinance-data" in text
