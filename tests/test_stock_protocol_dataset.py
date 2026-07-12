"""Contract tests for the date-bounded stock research pack."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.research.stock_protocol.dataset import (
    PackAudit,
    build_research_pack,
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


def test_panel_rejects_rows_after_locked_boundary(tmp_path: Path):
    _write_source(tmp_path, "2021-01-04")
    with pytest.raises(ValueError, match="2020-12-31"):
        load_bounded_daily_panel(tmp_path, "2020-12-31")


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

