#!/usr/bin/env python3
"""Verify one final catalog root against its sealed plan and frozen oracle."""

from __future__ import annotations

from aurora.infra.sp500_megarun.catalog_recovery_blocks import aggregate_recovery_metrics

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_resources import aggregate_worker_evaluation
from scripts.verify_sp500_optimized_run import (
    _load_results,
    scientific_results_sha256,
    verify_equivalence,
)


_FINAL_FILES = frozenset(
    {"results.parquet", "selected_results.jsonl", "summary.csv", "receipt.json"}
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify exact terminal catalog science and equivalence."
    )
    parser.add_argument("--final-root", required=True, type=Path)
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--sealed-plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _strict_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("expected one regular JSON file")
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON constant: {value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_directory(path: Path, *, exact_files: set[str] | None = None) -> Path:
    if path.is_symlink():
        raise ValueError("CATALOG_TERMINAL_DIRECTORY_INVALID")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("CATALOG_TERMINAL_DIRECTORY_INVALID")
    entries = tuple(resolved.rglob("*"))
    if any(entry.is_symlink() for entry in entries):
        raise ValueError("CATALOG_TERMINAL_SYMLINK_FORBIDDEN")
    if exact_files is not None:
        actual = {
            entry.relative_to(resolved).as_posix()
            for entry in entries
            if entry.is_file()
        }
        if actual != exact_files or any(entry.is_dir() for entry in entries):
            raise ValueError("CATALOG_TERMINAL_FILE_SET_INVALID")
    return resolved


def _verify_content_hashed_document(
    path: Path,
    *,
    document_type: str,
) -> Mapping[str, object]:
    document = _mapping(_strict_json(path), "CATALOG_TERMINAL_DOCUMENT_INVALID")
    identity = {key: value for key, value in document.items() if key != "content_sha256"}
    if (
        document.get("schema_version") != "1"
        or document.get("document_type") != document_type
        or document.get("content_sha256") != canonical_sha256(identity)
    ):
        raise ValueError("CATALOG_TERMINAL_DOCUMENT_INVALID")
    return document


def _verify_plan_receipt(sealed: Path) -> Mapping[str, object]:
    receipt = _mapping(
        _strict_json(sealed / "execution_plan_receipt.json"),
        "CATALOG_TERMINAL_PLAN_RECEIPT_INVALID",
    )
    identity = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    required = {
        "request_sha256",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
        "protected_commit_sha",
    }
    if (
        receipt.get("schema_version") != "1"
        or not required.issubset(receipt)
        or receipt.get("receipt_sha256") != canonical_sha256(identity)
        or receipt.get("validation_opened") is not False
        or receipt.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_TERMINAL_PLAN_RECEIPT_INVALID")
    return receipt


def _verify_source_and_reference(
    sealed: Path,
    reference: Path,
) -> Mapping[str, object]:
    document = _verify_content_hashed_document(
        sealed / "source_artifacts.json",
        document_type="catalog_source_artifacts_v1",
    )
    payload = _mapping(
        document.get("payload"),
        "CATALOG_TERMINAL_SOURCE_CONTRACT_INVALID",
    )
    source_contract = _mapping(
        payload.get("source_contract"),
        "CATALOG_TERMINAL_SOURCE_CONTRACT_INVALID",
    )
    contracts = source_contract.get("artifacts")
    normalized = payload.get("artifacts")
    if not isinstance(contracts, list) or not isinstance(normalized, list):
        raise ValueError("CATALOG_TERMINAL_SOURCE_CONTRACT_INVALID")
    reference_contracts = [
        row
        for row in contracts
        if isinstance(row, Mapping)
        and row.get("contract_name") == "reference_oracle_v1"
    ]
    normalized_rows = [
        row
        for row in normalized
        if isinstance(row, Mapping)
        and row.get("contract_name") == "reference_oracle_v1"
    ]
    if len(reference_contracts) != 1 or len(normalized_rows) != 1:
        raise ValueError("CATALOG_TERMINAL_REFERENCE_CONTRACT_INVALID")
    contract = reference_contracts[0]
    observed = normalized_rows[0]
    overlap = (
        "contract_name",
        "run_id",
        "artifact_id",
        "artifact_name",
        "artifact_digest",
        "head_sha",
        "validation_opened",
        "locked_opened",
    )
    files = contract.get("files")
    if (
        contract.get("classification") != "training_reference"
        or contract.get("verification_mode") != "closed_file_list_v1"
        or contract.get("validation_opened") is not False
        or contract.get("locked_opened") is not False
        or any(contract.get(key) != observed.get(key) for key in overlap)
        or not isinstance(files, list)
        or not files
    ):
        raise ValueError("CATALOG_TERMINAL_REFERENCE_CONTRACT_INVALID")
    expected_files: set[str] = set()
    for raw in files:
        row = _mapping(raw, "CATALOG_TERMINAL_REFERENCE_FILE_INVALID")
        relative_value = row.get("path")
        if not isinstance(relative_value, str):
            raise ValueError("CATALOG_TERMINAL_REFERENCE_FILE_INVALID")
        relative = PurePosixPath(relative_value)
        if (
            relative.is_absolute()
            or relative.as_posix() != relative_value
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative_value in expected_files
        ):
            raise ValueError("CATALOG_TERMINAL_REFERENCE_FILE_INVALID")
        target = reference.joinpath(*relative.parts)
        if (
            target.is_symlink()
            or not target.is_file()
            or target.stat().st_size != row.get("bytes")
            or _sha256_file(target) != row.get("sha256")
        ):
            raise ValueError("CATALOG_TERMINAL_REFERENCE_FILE_INVALID")
        expected_files.add(relative_value)
    _verify_directory(reference, exact_files=expected_files)
    if "results.jsonl" not in expected_files:
        raise ValueError("CATALOG_TERMINAL_REFERENCE_RESULTS_MISSING")
    return contract


def _verify_logical_manifest(
    sealed: Path,
    receipt: Mapping[str, object],
) -> tuple[str, ...]:
    document = _verify_content_hashed_document(
        sealed / "logical_recipe_manifest.json",
        document_type="logical_recipe_manifest",
    )
    for field in (
        "campaign_id",
        "authority_id",
        "science_sha256",
        "execution_plan_sha256",
    ):
        if document.get(field) != receipt.get(field):
            raise ValueError("CATALOG_TERMINAL_LOGICAL_MANIFEST_BINDING_INVALID")
    # The production plan writer emits fields at the document root. Older
    # fixtures/documents wrapped them in payload; never accept both layouts.
    if "payload" in document and any(key in document for key in ("recipes", "strategy_count")):
        raise ValueError("CATALOG_TERMINAL_LOGICAL_MANIFEST_AMBIGUOUS")
    payload = _mapping(
        document["payload"] if "payload" in document else document,
        "CATALOG_TERMINAL_LOGICAL_MANIFEST_INVALID",
    )
    recipes = payload.get("recipes")
    if not isinstance(recipes, list):
        raise ValueError("CATALOG_TERMINAL_LOGICAL_MANIFEST_INVALID")
    strategy_ids = tuple(
        str(_mapping(row, "CATALOG_TERMINAL_LOGICAL_MANIFEST_INVALID").get("strategy_id"))
        for row in recipes
    )
    if (
        payload.get("strategy_count") != len(strategy_ids)
        or not strategy_ids
        or len(strategy_ids) != len(set(strategy_ids))
        or any(not value or value == "None" for value in strategy_ids)
    ):
        raise ValueError("CATALOG_TERMINAL_LOGICAL_MANIFEST_INVALID")
    return strategy_ids


def _verify_final_root(
    final_root: Path,
    sealed: Path,
    plan_receipt: Mapping[str, object],
    expected_strategy_ids: tuple[str, ...],
) -> tuple[Mapping[str, object], str, int]:
    _verify_directory(final_root, exact_files=set(_FINAL_FILES))
    resolved = _mapping(
        _strict_json(sealed / "resolved_contract.json"),
        "CATALOG_TERMINAL_CONTRACT_INVALID",
    )
    science = _mapping(
        resolved.get("science"),
        "CATALOG_TERMINAL_CONTRACT_INVALID",
    )
    if (
        science.get("validation_opened") is not False
        or science.get("locked_opened") is not False
        or canonical_sha256(science) != plan_receipt.get("science_sha256")
    ):
        raise ValueError("CATALOG_TERMINAL_SCIENCE_BINDING_INVALID")
    final_receipt = _mapping(
        _strict_json(final_root / "receipt.json"),
        "CATALOG_TERMINAL_REDUCTION_RECEIPT_INVALID",
    )
    identity = {
        key: value for key, value in final_receipt.items() if key != "receipt_sha256"
    }
    results = _load_results(final_root)
    count, scientific_sha256 = scientific_results_sha256(final_root)
    if (
        final_receipt.get("receipt_sha256") != canonical_sha256(identity)
        or final_receipt.get("strategy_count") != count
        or tuple(sorted(results)) != tuple(sorted(expected_strategy_ids))
        or final_receipt.get("science_identity_sha256")
        != plan_receipt.get("science_sha256")
        or final_receipt.get("catalog_manifest_sha256")
        != science.get("catalog_manifest_sha256")
        or final_receipt.get("result_sha256")
        != _sha256_file(final_root / "results.parquet")
        or final_receipt.get("validation_opened") is not False
        or final_receipt.get("locked_opened") is not False
        or (
            "scientific_results_sha256" in final_receipt
            and final_receipt.get("scientific_results_sha256") != scientific_sha256
        )
    ):
        raise ValueError("CATALOG_TERMINAL_REDUCTION_RECEIPT_INVALID")
    return final_receipt, scientific_sha256, count


def _hashed(payload: Mapping[str, object], field: str) -> dict[str, object]:
    result = dict(payload)
    result[field] = canonical_sha256(payload)
    return result


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def verify(
    *,
    final_root: Path,
    reference_root: Path,
    sealed_plan: Path,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("CATALOG_TERMINAL_SCIENCE_OUTPUT_EXISTS")
    sealed = _verify_directory(sealed_plan)
    reference = _verify_directory(reference_root)
    final = _verify_directory(final_root)
    plan_receipt = _verify_plan_receipt(sealed)
    reference_contract = _verify_source_and_reference(sealed, reference)
    expected_ids = _verify_logical_manifest(sealed, plan_receipt)
    final_receipt, scientific_sha256, count = _verify_final_root(
        final,
        sealed,
        plan_receipt,
        expected_ids,
    )
    equivalence = verify_equivalence(
        final, reference, expected_strategy_ids=expected_ids,
    )
    if not equivalence.get("equivalent"):
        raise ValueError("CATALOG_TERMINAL_REFERENCE_EQUIVALENCE_FAILED")
    binding = {
        key: plan_receipt[key]
        for key in (
            "request_sha256",
            "authority_id",
            "campaign_id",
            "science_sha256",
            "execution_plan_sha256",
            "execution_protocol_sha256",
            "protected_commit_sha",
        )
    }
    scientific = _hashed(
        {
            "schema_version": "1",
            **binding,
            "strategy_count": count,
            "scientific_results_sha256": scientific_sha256,
            "reduction_receipt_sha256": final_receipt["receipt_sha256"],
              "execution_metrics": aggregate_worker_evaluation([final_receipt]),
              "recovery_metrics": aggregate_recovery_metrics([final_receipt]),
            "schemas_valid": True,
            "validation_opened": False,
            "locked_opened": False,
        },
        "receipt_sha256",
    )
    equivalence_receipt = _hashed(
        {
            "schema_version": "1",
            **binding,
            **equivalence,
            "reference_run_id": reference_contract["run_id"],
            "reference_artifact_id": reference_contract["artifact_id"],
            "reference_artifact_digest": reference_contract["artifact_digest"],
        },
        "receipt_sha256",
    )
    regression = _hashed(
        {
            "schema_version": "1",
            **binding,
            "gate": "frozen_reference_scientific_equivalence_v1",
            "no_regression": True,
            "equivalence_receipt_sha256": equivalence_receipt["receipt_sha256"],
            "validation_opened": False,
            "locked_opened": False,
        },
        "receipt_sha256",
    )
    output_dir.mkdir(parents=False, exist_ok=False)
    documents = {
        "catalog_scientific_audit_receipt_v1.json": scientific,
        "catalog_equivalence_receipt_v1.json": equivalence_receipt,
        "catalog_regression_receipt_v1.json": regression,
    }
    for name, value in documents.items():
        _write_json(output_dir / name, value)
    index_identity = {
        "schema_version": "1",
        **binding,
        "files": [
            {
                "path": name,
                "sha256": _sha256_file(output_dir / name),
                "size_bytes": (output_dir / name).stat().st_size,
            }
            for name in sorted(documents)
        ],
        "validation_opened": False,
        "locked_opened": False,
    }
    index = _hashed(index_identity, "index_sha256")
    _write_json(output_dir / "catalog_terminal_science_index_v1.json", index)
    return index


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify(
            final_root=args.final_root,
            reference_root=args.reference_root,
            sealed_plan=args.sealed_plan,
            output_dir=args.output_dir,
        )
        return 0
    except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"CATALOG_TERMINAL_SCIENCE_INVALID:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
