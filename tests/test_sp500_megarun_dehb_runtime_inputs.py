from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _contract() -> SimpleNamespace:
    return SimpleNamespace(
        sha256="a" * 64,
        data_contract_file_sha256="1" * 64,
        data_contract_canonical_sha256="2" * 64,
        feature_contract_sha256="3" * 64,
        dehb_lock_domain_sha256="4" * 64,
        train_source_run_id="123",
        train_artifact_digest_sha256="b" * 64,
        train_snapshot_manifest_sha256="c" * 64,
        train_spy_sha256="d" * 64,
        train_partition="train_snapshot_1993_2010",
        search_start="1998-01-01",
        search_end="2010-12-31",
    )


def test_runtime_input_pack_is_self_verifying_and_train_only(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
        package_runtime_inputs,
        scientific_input_binding_sha256,
        verify_runtime_input_pack,
    )

    train = tmp_path / "train_snapshot_1993_2010"
    train.mkdir()
    (train / "D_SPY.parquet").write_bytes(b"train")
    roots = {name: tmp_path / name for name in ("price", "market", "macro")}
    for name, root in roots.items():
        root.mkdir()
        (root / f"{name}.bin").write_bytes(name.encode("ascii"))
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "ready": True,
                "lane_count": 240,
                "campaign_contract_sha256": "a" * 64,
                "validation_opened": False,
                "locked_opened": False,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "pack"
    manifest = package_runtime_inputs(
        contract=_contract(),
        train_snapshot=train,
        baseline_feature_dirs=roots,
        registry_report=report,
        baseline_run_id="456",
        output_dir=output,
    )

    verified = verify_runtime_input_pack(
        output,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(
            _contract()
        ),
        expected_aggregate_sha256=str(manifest["aggregate_sha256"]),
    )
    assert verified["baseline_run_id"] == "456"
    assert verified["validation_opened"] is False
    assert verified["locked_opened"] is False


def test_runtime_input_pack_rejects_tampered_file(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
        RuntimeInputPackError,
        package_runtime_inputs,
        scientific_input_binding_sha256,
        verify_runtime_input_pack,
    )

    train = tmp_path / "train_snapshot_1993_2010"
    train.mkdir()
    (train / "D_SPY.parquet").write_bytes(b"train")
    roots = {name: tmp_path / name for name in ("price", "market", "macro")}
    for root in roots.values():
        root.mkdir()
        (root / "input.bin").write_bytes(b"input")
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "ready": True,
                "lane_count": 240,
                "campaign_contract_sha256": "a" * 64,
                "validation_opened": False,
                "locked_opened": False,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "pack"
    package_runtime_inputs(
        contract=_contract(),
        train_snapshot=train,
        baseline_feature_dirs=roots,
        registry_report=report,
        baseline_run_id="456",
        output_dir=output,
    )
    (output / "baseline_price" / "input.bin").write_bytes(b"tampered")
    with pytest.raises(RuntimeInputPackError, match="RUNTIME_INPUT_FILE_MISMATCH"):
        verify_runtime_input_pack(
            output,
            expected_scientific_input_binding_sha256=scientific_input_binding_sha256(
                _contract()
            ),
        )
