"""Contract tests for the immutable full-universe pre-2021 data artifact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from aurora.research.stock_protocol.full_dataset import build_full_pre2021_pack
from aurora.research.stock_protocol.dataset import read_pack


def _write_combined(path: Path, symbols: list[str], include_locked: bool = False) -> None:
    dates = pd.date_range("2019-01-02", periods=260, freq="B")
    if include_locked:
        dates = dates.append(pd.DatetimeIndex([pd.Timestamp("2021-01-04")]))
    rows = []
    for offset, symbol in enumerate(symbols):
        for index, day in enumerate(dates):
            close = 100.0 + offset + index / 10.0
            rows.append(
                {
                    "date": day,
                    "symbol": symbol,
                    "open": close - 0.2,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "adj_close": close,
                    "volume": 1000 + index,
                    "dividends": 0.0,
                    "stock_splits": 0.0,
                }
            )
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_full_pack_is_sharded_hashed_and_strictly_pre2021(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    _write_combined(source / "prices.parquet", ["AAA", "BBB", "CCC"], include_locked=True)

    audit = build_full_pre2021_pack(
        source_roots=[source],
        output_root=output,
        end_date="2020-12-31",
        shard_count=4,
        minimum_symbols=3,
    )

    assert audit["pack_symbols"] == 3
    assert audit["locked_opened"] is False
    assert audit["locked_rows"] == 0
    assert audit["last_date"] <= "2020-12-31"
    assert audit["symbols_with_252_sessions"] == 3
    manifest = json.loads((output / "data_shard_manifest.json").read_text(encoding="utf-8"))
    assert manifest["shards_expected"] == 4
    assert manifest["shards_found"] == 4
    assert sum(item["rows"] for item in manifest["shards"]) == audit["pack_rows"]
    for item in manifest["shards"]:
        path = output / item["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    panel = read_pack(output)
    assert len(panel.frame) == audit["pack_rows"]
    assert panel.frame["date"].max() <= pd.Timestamp("2020-12-31")


def test_full_pack_fails_below_minimum_symbol_control(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write_combined(source / "prices.parquet", ["AAA"])

    try:
        build_full_pre2021_pack(
            source_roots=[source],
            output_root=tmp_path / "output",
            end_date="2020-12-31",
            shard_count=2,
            minimum_symbols=1000,
        )
    except ValueError as exc:
        assert "minimum symbol control" in str(exc)
    else:
        raise AssertionError("minimum symbol control did not fail")
