from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.gtbi_v7_readiness.frozen_data_lake import (
    MANIFEST_FILENAME,
    RECEIPT_FILENAME,
    FrozenDataLakeError,
    package_frozen_data_lake,
    verify_frozen_data_lake_archive,
)


def _source(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    (source / "normalized").mkdir(parents=True)
    (source / "raw").mkdir()
    (source / "catalog.sqlite").write_bytes(b"catalog")
    (source / "normalized/AAPL.parquet").write_bytes(b"A" * 1800)
    (source / "raw/AAPL.parquet").write_bytes(b"B" * 2200)
    files = [path for path in source.rglob("*") if path.is_file()]
    receipt = {
        "schema_version": "gtbi_v7_local_data_lake_receipt_v1",
        "observed_at_utc": "2026-07-29T18:51:15Z",
        "file_count": len(files),
        "local_size_bytes": sum(path.stat().st_size for path in files),
        "locked_rows_present": True,
        "locked_start": "2021-01-01",
        "scientific_cutoff_required": "2020-12-31",
    }
    receipt_path = tmp_path / "source-receipt.json"
    receipt_path.write_bytes(canonical_bytes(receipt) + b"\n")
    return source, receipt_path


def _package(tmp_path: Path, name: str = "output") -> tuple[Path, dict]:
    source, source_receipt = _source(tmp_path)
    output = tmp_path / name
    result = package_frozen_data_lake(
        source_root=source,
        source_receipt_path=source_receipt,
        output_dir=output,
        part_size=1024,
    )
    return output, result


def test_archive_round_trip_verifies_every_file_and_multiple_parts(
    tmp_path: Path,
) -> None:
    output, receipt = _package(tmp_path)
    result = verify_frozen_data_lake_archive(
        parts_dir=output,
        manifest_path=output / MANIFEST_FILENAME,
        receipt_path=output / RECEIPT_FILENAME,
    )

    assert result["verified"] is True
    assert result["source_file_count"] == 3
    assert result["source_total_bytes"] == 4007
    assert result["part_count"] == receipt["part_count"]
    assert receipt["part_count"] > 1
    assert receipt["locked_start"] == "2021-01-01"
    assert receipt["scientific_cutoff"] == "2020-12-31"


def test_archive_is_byte_deterministic(tmp_path: Path) -> None:
    first, _ = _package(tmp_path / "first")
    second, _ = _package(tmp_path / "second")
    first_files = {
        path.name: path.read_bytes() for path in first.iterdir()
    }
    second_files = {
        path.name: path.read_bytes() for path in second.iterdir()
    }

    assert first_files == second_files


def test_archive_receipts_do_not_disclose_local_paths(tmp_path: Path) -> None:
    output, _ = _package(tmp_path)
    combined = (
        (output / MANIFEST_FILENAME).read_text(encoding="utf-8")
        + (output / RECEIPT_FILENAME).read_text(encoding="utf-8")
    )

    assert str(tmp_path) not in combined
    assert "AU_DATA_DIR/prices/free_us_daily" in combined


def test_tampered_part_is_rejected(tmp_path: Path) -> None:
    output, receipt = _package(tmp_path)
    part = output / receipt["parts"][0]["name"]
    data = bytearray(part.read_bytes())
    data[0] ^= 1
    part.write_bytes(data)

    with pytest.raises(FrozenDataLakeError, match="part digest mismatch"):
        verify_frozen_data_lake_archive(
            parts_dir=output,
            manifest_path=output / MANIFEST_FILENAME,
            receipt_path=output / RECEIPT_FILENAME,
        )


def test_source_receipt_count_mismatch_fails_before_packaging(
    tmp_path: Path,
) -> None:
    source, receipt_path = _source(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["file_count"] += 1
    receipt_path.write_bytes(canonical_bytes(receipt) + b"\n")

    with pytest.raises(FrozenDataLakeError, match="file count mismatch"):
        package_frozen_data_lake(
            source_root=source,
            source_receipt_path=receipt_path,
            output_dir=tmp_path / "output",
            part_size=1024,
        )
