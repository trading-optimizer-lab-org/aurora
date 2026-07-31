from __future__ import annotations

import json
import os
import subprocess
import sys
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

ROOT = Path(__file__).resolve().parents[1]


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


def test_byte_verifier_import_does_not_load_scientific_or_validation_packages() -> None:
    code = """
import sys
from infra.gtbi_v7_readiness.frozen_data_lake import verify_frozen_data_lake_archive
for forbidden in ("numpy", "pandas", "jsonschema"):
    assert forbidden not in sys.modules, forbidden
assert callable(verify_frozen_data_lake_archive)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, "-S", "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_published_private_github_release_receipt_is_exact_and_canonical() -> None:
    path = (
        ROOT
        / "docs/readiness/gtbi-v7"
        / "frozen_data_lake_github_release_receipt.json"
    )
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["status"] == "verified_published_private"
    assert receipt["repository"] == (
        "trading-optimizer-lab-org/aurora-v7-assets"
    )
    assert receipt["repository_private"] is True
    assert receipt["release_id"] == 362286563
    assert receipt["release_tag"] == "gtbi-v7-frozen-data-lake-v1"
    assert receipt["verification_run_id"] == 30528738857
    assert receipt["github_only_verification"] is True
    assert receipt["requires_local_machine"] is False
    assert receipt["provider_download_performed"] is False
    assert receipt["scientific_processing_performed"] is False
    assert receipt["source_file_count"] == 10678
    assert receipt["source_total_bytes"] == 3242614328
    assert receipt["archive_size_bytes"] == 3252295680
    assert receipt["part_count"] == 3
    assert receipt["asset_count"] == 6
    assert receipt["scientific_cutoff"] == "2020-12-31"
    assert receipt["locked_start"] == "2021-01-01"
    assert receipt["maximum_incremental_net_spend_usd"] == 0

    readiness_readme = (
        ROOT / "docs/readiness/gtbi-v7" / "README.md"
    ).read_text(encoding="utf-8")
    assert "has already completed its one-time, hash-verified transfer" in readiness_readme
    assert receipt["repository"] in readiness_readme
    assert str(receipt["verification_run_id"]) in readiness_readme
    assert "remains local until its one-time" not in readiness_readme
