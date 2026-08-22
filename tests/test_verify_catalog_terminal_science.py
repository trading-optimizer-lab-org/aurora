from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import canonical_sha256
from scripts.verify_sp500_optimized_run import scientific_results_sha256
from scripts.fetch_catalog_reference_artifact import verify_reference_metadata


ROOT = Path(__file__).resolve().parents[1]


def test_reference_download_metadata_must_match_every_sealed_identity() -> None:
    contract = {
        "contract_name": "reference_oracle_v1",
        "run_id": 22,
        "artifact_id": 33,
        "artifact_name": "reference-results",
        "artifact_digest": "sha256:" + "a" * 64,
        "artifact_size_in_bytes": 100,
        "head_sha": "b" * 40,
        "validation_opened": False,
        "locked_opened": False,
    }
    metadata = {
        "id": 33,
        "name": "reference-results",
        "digest": "sha256:" + "a" * 64,
        "size_in_bytes": 100,
        "expired": False,
        "workflow_run": {"id": 22, "head_sha": "b" * 40},
    }
    assert verify_reference_metadata(contract, metadata)["artifact_id"] == 33
    for key, value in (
        ("digest", "sha256:" + "c" * 64),
        ("expired", True),
        ("size_in_bytes", 101),
    ):
        changed = {**metadata, key: value}
        try:
            verify_reference_metadata(contract, changed)
        except ValueError as exc:
            assert "CATALOG_REFERENCE_ARTIFACT_METADATA_INVALID" in str(exc)
        else:
            raise AssertionError(f"metadata mutation accepted: {key}")


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    final_root = tmp_path / "final"
    reference_root = tmp_path / "reference"
    sealed = tmp_path / "sealed"
    final_root.mkdir()
    reference_root.mkdir()
    sealed.mkdir()
    science = {
        "catalog_manifest_sha256": "7" * 64,
        "validation_opened": False,
        "locked_opened": False,
    }
    science_sha256 = canonical_sha256(science)
    results = {
        "recipe-1": {"objective": 1.25, "info": {"train_feasible": True}},
        "recipe-2": {"objective": 2.5, "info": {"train_feasible": True}},
    }
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "strategy_id": strategy_id,
                    "result_json": json.dumps(result, sort_keys=True),
                }
                for strategy_id, result in results.items()
            ]
        ),
        final_root / "results.parquet",
    )
    (final_root / "selected_results.jsonl").write_text("", "utf-8")
    (final_root / "summary.csv").write_text("strategy_id\nrecipe-1\nrecipe-2\n", "utf-8")
    reference_rows = [
        {"strategy_id": strategy_id, "result": result}
        for strategy_id, result in results.items()
    ]
    (reference_root / "results.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in reference_rows
        ),
        "utf-8",
    )
    count, scientific_sha = scientific_results_sha256(final_root)
    final_receipt_identity = {
        "schema_version": 1,
        "strategy_count": count,
        "result_sha256": hashlib.sha256(
            (final_root / "results.parquet").read_bytes()
        ).hexdigest(),
        "science_identity_sha256": science_sha256,
        "catalog_manifest_sha256": "7" * 64,
        "work_manifest_sha256": "8" * 64,
        "scientific_results_sha256": scientific_sha,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write_json(
        final_root / "receipt.json",
        {
            **final_receipt_identity,
            "receipt_sha256": canonical_sha256(final_receipt_identity),
        },
    )
    source_contract = {
        "schema_version": "1",
        "repository": "trading-optimizer-lab-org/aurora",
        "artifacts": [
            {
                "contract_name": "reference_oracle_v1",
                "classification": "training_reference",
                "run_id": 22,
                "artifact_id": 33,
                "artifact_name": "reference-results",
                "artifact_digest": "sha256:" + "a" * 64,
                "artifact_size_in_bytes": 100,
                "head_sha": "b" * 40,
                "verification_mode": "closed_file_list_v1",
                "files": [
                    {
                        "path": "results.jsonl",
                        "bytes": (reference_root / "results.jsonl").stat().st_size,
                        "sha256": hashlib.sha256(
                            (reference_root / "results.jsonl").read_bytes()
                        ).hexdigest(),
                    }
                ],
                "validation_opened": False,
                "locked_opened": False,
            }
        ],
    }
    source_identity = {
        "schema_version": "1",
        "document_type": "catalog_source_artifacts_v1",
        "payload": {
            "source_contract": source_contract,
            "artifacts": [
                {
                    "contract_name": "reference_oracle_v1",
                    "artifact_id": 33,
                    "run_id": 22,
                    "artifact_name": "reference-results",
                    "artifact_digest": "sha256:" + "a" * 64,
                    "head_sha": "b" * 40,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            ],
        },
    }
    _write_json(
        sealed / "source_artifacts.json",
        {**source_identity, "content_sha256": canonical_sha256(source_identity)},
    )
    _write_json(sealed / "resolved_contract.json", {"science": science})
    logical_identity = {
        "schema_version": "1",
        "document_type": "logical_recipe_manifest",
        "campaign_id": "2" * 64,
        "authority_id": "018f47a2-6e91-7c34-8000-000000000101",
        "science_sha256": science_sha256,
        "execution_plan_sha256": "4" * 64,
        "payload": {
            "strategy_count": 2,
            "recipes": [
                {"strategy_id": "recipe-1"},
                {"strategy_id": "recipe-2"},
            ],
        },
    }
    _write_json(
        sealed / "logical_recipe_manifest.json",
        {**logical_identity, "content_sha256": canonical_sha256(logical_identity)},
    )
    receipt_identity = {
        "schema_version": "1",
        "request_sha256": "1" * 64,
        "authority_id": "018f47a2-6e91-7c34-8000-000000000101",
        "campaign_id": "2" * 64,
        "science_sha256": science_sha256,
        "execution_plan_sha256": "4" * 64,
        "execution_protocol_sha256": "5" * 64,
        "protected_commit_sha": "6" * 40,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write_json(
        sealed / "execution_plan_receipt.json",
        {**receipt_identity, "receipt_sha256": canonical_sha256(receipt_identity)},
    )
    return final_root, reference_root, sealed


def _run(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    final_root, reference_root, sealed = _fixture(tmp_path)
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_catalog_terminal_science.py"),
            "--final-root",
            str(final_root),
            "--reference-root",
            str(reference_root),
            "--sealed-plan",
            str(sealed),
            "--output-dir",
            str(tmp_path / "science"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_terminal_science_verifier_binds_result_plan_reference_and_equivalence(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    output = tmp_path / "science"
    assert {path.name for path in output.iterdir()} == {
        "catalog_scientific_audit_receipt_v1.json",
        "catalog_equivalence_receipt_v1.json",
        "catalog_regression_receipt_v1.json",
        "catalog_terminal_science_index_v1.json",
    }
    equivalence = json.loads(
        (output / "catalog_equivalence_receipt_v1.json").read_text("utf-8")
    )
    assert equivalence["equivalent"] is True
    assert equivalence["observed_count"] == 2


def test_terminal_science_verifier_fails_closed_on_one_changed_result(
    tmp_path: Path,
) -> None:
    final_root, reference_root, sealed = _fixture(tmp_path)
    rows = [
        {
            "strategy_id": "recipe-1",
            "result": {"objective": 99.0, "info": {"train_feasible": True}},
        },
        {
            "strategy_id": "recipe-2",
            "result": {"objective": 2.5, "info": {"train_feasible": True}},
        },
    ]
    (reference_root / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        "utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_catalog_terminal_science.py"),
            "--final-root",
            str(final_root),
            "--reference-root",
            str(reference_root),
            "--sealed-plan",
            str(sealed),
            "--output-dir",
            str(tmp_path / "science"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert not (tmp_path / "science").exists()
