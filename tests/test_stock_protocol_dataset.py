"""Contract tests for the date-bounded stock research pack."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.research.stock_protocol.dataset import (
    PackAudit,
    build_research_pack,
    discover_daily_sources,
    load_bounded_daily_panel,
    read_pack,
)
from aurora.research.stock_protocol.manifest import load_protocol_manifest


def _write_source(root: Path, end: str = "2020-12-31") -> None:
    target = root / "normalized"
    target.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": ["2020-12-30", end],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "adj_close": [101.0, 102.0],
            "volume": [1000, 1200],
        }
    ).to_parquet(target / "TEST.parquet", index=False)


def test_panel_materialises_only_prelocked_rows(tmp_path: Path):
    _write_source(tmp_path, "2021-01-04")
    panel = load_bounded_daily_panel(tmp_path, "2020-12-31")
    assert panel.frame["date"].max() == pd.Timestamp("2020-12-30")
    assert panel.audit.locked_rows == 0
    assert panel.audit.locked_opened is False


def test_discovery_does_not_stop_after_two_visible_benchmarks(tmp_path: Path):
    benchmark = tmp_path / "benchmarks"
    nested = tmp_path / "prices" / "free_us_daily" / "normalized"
    benchmark.mkdir(parents=True)
    nested.mkdir(parents=True)
    for symbol, target in (
        ("SPY", benchmark),
        ("GSPC", benchmark),
        ("AAPL", nested),
        ("MSFT", nested),
        ("NVDA", nested),
    ):
        pd.DataFrame(
            {
                "date": ["2020-12-30"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "adj_close": [100.5],
                "volume": [1000],
            }
        ).to_parquet(target / f"{symbol}.parquet", index=False)

    discovered = discover_daily_sources([tmp_path])
    assert {item.path.name for item in discovered} == {
        "SPY.parquet", "GSPC.parquet", "AAPL.parquet", "MSFT.parquet", "NVDA.parquet"
    }
    panel = load_bounded_daily_panel([tmp_path], "2020-12-31")
    assert set(panel.frame["symbol"]) == {"SPY", "GSPC", "AAPL", "MSFT", "NVDA"}
    assert panel.audit.source_files == 5


def test_loader_combines_multiple_roots_and_supported_formats(tmp_path: Path):
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    pd.DataFrame(
        {
            "date": ["2020-12-30", "2020-12-30"],
            "symbol": ["AAPL", "MSFT"],
            "open": [100.0, 200.0],
            "high": [101.0, 201.0],
            "low": [99.0, 199.0],
            "close": [100.5, 200.5],
            "adj_close": [100.5, 200.5],
            "volume": [1000, 2000],
        }
    ).to_parquet(root_a / "combined.parquet", index=False)
    pd.DataFrame(
        {
            "date": ["2020-12-30"],
            "symbol": ["NVDA"],
            "open": [300.0],
            "high": [301.0],
            "low": [299.0],
            "close": [300.5],
            "adj_close": [300.5],
            "volume": [3000],
        }
    ).to_csv(root_b / "daily.csv", index=False)

    panel = load_bounded_daily_panel([root_a, root_b], "2020-12-31")
    assert set(panel.frame["symbol"]) == {"AAPL", "MSFT", "NVDA"}
    assert panel.audit.source_files == 2


def test_loader_uses_first_root_as_deterministic_canonical_source(tmp_path: Path):
    roots = [tmp_path / "preferred", tmp_path / "fallback"]
    for root, close in zip(roots, (101.0, 999.0), strict=True):
        root.mkdir()
        pd.DataFrame(
            {
                "date": ["2020-12-30"],
                "symbol": ["AAPL"],
                "open": [100.0],
                "high": [1000.0],
                "low": [99.0],
                "close": [close],
                "adj_close": [close],
                "volume": [1000],
            }
        ).to_parquet(root / "prices.parquet", index=False)

    panel = load_bounded_daily_panel(roots, "2020-12-31")
    assert panel.frame.iloc[0]["close"] == 101.0
    assert panel.audit.duplicates_removed == 1


def test_pack_audit_declares_active_universe_limitation():
    audit = PackAudit(
        source_root="source", output_root="pack", data_start="1995-01-01",
        data_end="2020-12-31", rows=1, symbols=1, locked_rows=0,
        survivorship_free=False, metadata_is_bitemporal=False,
        dataset_hash="hash",
    )
    assert audit.locked_opened is False


def test_build_pack_writes_audit_and_partition(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "pack"
    _write_source(source)
    manifest = load_protocol_manifest(
        Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"
    )
    audit = build_research_pack(source, output, manifest)
    assert audit.data_end == "2020-12-31"
    assert audit.rows == 2
    assert audit.locked_opened is False
    assert (output / "year=2020" / "data.parquet").exists()
    assert read_pack(output).audit.dataset_hash == audit.dataset_hash
