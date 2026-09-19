from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_admission import CatalogRunPlanV1
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_resume import build_resume_work_manifest
from aurora.infra.sp500_megarun.catalog_sealed_plan import (
    verify_sealed_global_reuse_execution_plan,
)
from scripts.plan_sp500_optimized_catalog_run import (
    write_sealed_global_reuse_execution_plan,
)
from aurora.tests.test_sp500_catalog_optimization_contract import (
    _task10_contract_payload,
    _task10_plan_fixture,
)

from aurora.infra.sp500_megarun.catalog_reduction_recovery_source import (
    ValidatedReductionRecoverySource,
    verify_reduction_recovery_source,
)


_PARQUET_SCHEMA = pa.schema(
    [
        ("strategy_id", pa.string()),
        ("result_json", pa.string()),
    ]
)


def build_historical_reduction_source_fixture(tmp_path: Path) -> dict[str, Any]:
    contract = RunOptimizationContractV1.model_validate(_task10_contract_payload())
    plan = _task10_plan_fixture(
        warm_component_ordinals=set(range(12)),
        worker_count_override=7,
        qualify_layout=False,
    )
    strategy_ids = tuple(item.strategy_id for item in plan.recipe_requirements)
    cached_strategy_ids = strategy_ids[:2]
    work_manifest = build_resume_work_manifest(
        strategy_ids,
        cached_strategy_ids=cached_strategy_ids,
        maximum_workers=len(plan.recipe_assignments),
    )
    run_plan = CatalogRunPlanV1(
        contract_sha256=contract.contract_sha256,
        evidence_sha256="f" * 64,
        admission_token_sha256="e" * 64,
        workers=contract.execution.workers,
        active_workers=len(plan.recipe_assignments),
        component_workers=contract.execution.component_workers,
        component_processes_per_worker=contract.execution.component_processes_per_worker,
        processes_per_worker=contract.execution.processes_per_worker,
        block_size=contract.execution.block_size,
        matrices=(tuple(item.worker_id for item in plan.recipe_assignments),),
        work_manifest_sha256=work_manifest.manifest_sha256,
        pending_recipe_count=len(work_manifest.pending_strategy_ids),
        cached_recipe_count=len(work_manifest.cached_strategy_ids),
        expected_physical_component_builds=12,
    )
    bindings = {
        "request_sha256": "a" * 64,
        "decision_sha256": "d" * 64,
        "protected_commit_sha": "a" * 40,
        "authority_id": plan.authority_id,
        "campaign_id": plan.campaign_id,
        "execution_plan_sha256": plan.execution_plan_sha256,
    }
    source_artifacts_identity = {
        "schema_version": "1",
        "document_type": "catalog_source_artifacts_v1",
        "payload": {
            "artifacts": [
                {
                    "contract_name": "reference_oracle_v1",
                    "run_id": 31948898747,
                    "artifact_id": 9264302413,
                    "artifact_name": "sp500-strategy-catalog-final-results",
                    "artifact_digest": "sha256:" + "f" * 64,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            ]
        },
    }
    sealed_plan = tmp_path / "sealed-plan"
    plan_receipt = write_sealed_global_reuse_execution_plan(
        output_dir=sealed_plan,
        contract=contract,
        plan=plan,
        request_sha256=bindings["request_sha256"],
        execution_protocol_sha256="b" * 64,
        protected_commit_sha=bindings["protected_commit_sha"],
        decision_sha256=bindings["decision_sha256"],
        admission_token_sha256=run_plan.admission_token_sha256,
        controller_binding={
            "schema_version": "1",
            "request_sha256": bindings["request_sha256"],
            "authority_id": plan.authority_id,
            "campaign_id": plan.campaign_id,
        },
        run_plan=run_plan.model_dump(mode="json"),
        resume_work_manifest=work_manifest.model_dump(mode="json"),
        recipe_dag_bytes=b"PAR1-recovery-source-fixture",
        recipe_dag_manifest={
            "schema_version": "1",
            "recipe_count": len(strategy_ids),
            "validation_opened": False,
            "locked_opened": False,
        },
        source_artifacts={
            **source_artifacts_identity,
            "content_sha256": canonical_sha256(source_artifacts_identity),
        },
    )
    groups = tmp_path / "groups"
    reduction_plan = json.loads(
        (sealed_plan / "reduction_plan.json").read_text(encoding="utf-8")
    )
    assignments = {
        item.worker_id: item.strategy_ids for item in plan.recipe_assignments
    }
    expected_science = canonical_sha256(contract.science)
    expected_catalog = contract.science.catalog_manifest_sha256
    _write_groups(
        groups,
        reduction_plan=reduction_plan,
        assignments=assignments,
        expected_strategy_ids=work_manifest.pending_strategy_ids,
        expected_science=expected_science,
        expected_catalog=expected_catalog,
        work_manifest_sha256=work_manifest.manifest_sha256,
        processes_per_worker=contract.execution.processes_per_worker,
        block_size=contract.execution.block_size,
    )
    return {
        "sealed_plan": sealed_plan,
        "groups": groups,
        "bindings": bindings,
        "science": expected_science,
        "catalog": expected_catalog,
        "strategy_ids": work_manifest.pending_strategy_ids,
        "all_strategy_ids": strategy_ids,
        "cached_strategy_ids": work_manifest.cached_strategy_ids,
        "work_manifest_sha256": work_manifest.manifest_sha256,
        "plan_receipt": plan_receipt,
        "run_plan": run_plan,
        "work_manifest": work_manifest,
        "reduction_plan": reduction_plan,
    }


_source_fixture = build_historical_reduction_source_fixture


def _write_groups(
    root: Path,
    *,
    reduction_plan: dict[str, Any],
    assignments: dict[int, tuple[str, ...]],
    expected_strategy_ids: tuple[str, ...],
    expected_science: str,
    expected_catalog: str,
    work_manifest_sha256: str,
    processes_per_worker: int,
    block_size: int,
) -> None:
    root.mkdir()
    nodes_by_artifact = {
        str(node["output_artifact"]): node
        for node in reduction_plan["nodes"]
    }
    for group in reduction_plan["groups"]:
        artifact = str(group["reduction_artifact"])
        group_root = root / artifact
        group_root.mkdir()
        strategy_ids = tuple(
            strategy_id
            for worker_id in group["worker_ids"]
            for strategy_id in assignments[int(worker_id)]
            if strategy_id in expected_strategy_ids
        )
        rows = [
            {
                "strategy_id": strategy_id,
                "result_json": json.dumps(
                    {
                        "fitness": float(index),
                        "info": {
                            "lane_id": f"fixture-lane-{index:03d}",
                            "fidelity": 27,
                            "target_years": list(range(1998, 2011)),
                            "config": {"fixture_strategy_index": index},
                            "config_sha256": canonical_sha256(
                                {"fixture_strategy_index": index}
                            ),
                            "strategy_fingerprint": hashlib.sha256(
                                f"strategy:{strategy_id}".encode("utf-8")
                            ).hexdigest(),
                            "annualized_strategy_return": 0.01 + index / 1000,
                            "annualized_alpha": 0.001 + index / 10000,
                            "annualized_spy_return": 0.02,
                            "annual_returns": {
                                str(year): {
                                    "active_return": -0.01,
                                    "passed": False,
                                    "spy_return": 0.02,
                                    "strategy_return": 0.01,
                                    "year": year,
                                }
                                for year in range(1998, 2011)
                            },
                            "weekly_spy_beat_rate": 0.5,
                            "positive_weeks": 500 + index,
                            "winning_or_positive_weeks": 510 + index,
                            "weekly_winning_or_positive_rate": 0.75,
                            "week_count": 679,
                            "train_feasible": True,
                            "failed_years": [],
                            "weeks_beating_spy": 340 + index,
                            "archive_key": [1.0, float(index), 0.0, 0.0, 0.0],
                            "objective_runtime_seconds": 0.0,
                            "full_fidelity": True,
                            "position_fingerprint": hashlib.sha256(
                                strategy_id.encode("utf-8")
                            ).hexdigest(),
                            "validation_opened": False,
                            "locked_opened": False,
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
            for index, strategy_id in enumerate(strategy_ids)
        ]
        result_path = group_root / "results.parquet"
        pq.write_table(
            pa.Table.from_pylist(rows, schema=_PARQUET_SCHEMA),
            result_path,
            compression="zstd",
        )
        result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
        node = nodes_by_artifact[artifact]
        receipt_identity = {
            "schema_version": 1,
            "reduction_group_id": group["group_id"],
            "reduction_artifact": artifact,
            "worker_ids": group["worker_ids"],
            "source_worker_receipt_count": len(group["worker_ids"]),
            "science_identity_sha256": expected_science,
            "catalog_manifest_sha256": expected_catalog,
            "work_manifest_sha256": work_manifest_sha256,
            "reduction_plan_sha256": reduction_plan["content_sha256"],
            "node_descriptor_sha256": node["node_descriptor_sha256"],
            "processes_per_worker": processes_per_worker,
            "block_size": block_size,
            "validation_opened": False,
            "locked_opened": False,
            "result_sha256": result_sha256,
        }
        receipt = {
            **receipt_identity,
            "receipt_sha256": canonical_sha256(receipt_identity),
        }
        manifest = {
            "group_id": group["group_id"],
            "worker_ids": group["worker_ids"],
            "result_sha256": result_sha256,
            "reduction_plan_sha256": reduction_plan["content_sha256"],
            "node_descriptor_sha256": node["node_descriptor_sha256"],
            "checkpoint_receipt_manifest_sha256": None,
            "validation_opened": False,
            "locked_opened": False,
        }
        (group_root / "receipt.json").write_text(
            json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
        )
        (group_root / "reduction_group_manifest.json").write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
        )


def test_valid_historical_groups_return_an_immutable_exact_summary(
    tmp_path: Path,
) -> None:
    fixture = _source_fixture(tmp_path)
    assert fixture["run_plan"].cached_recipe_count > 0
    assert fixture["run_plan"].pending_recipe_count == len(fixture["strategy_ids"])

    result = verify_reduction_recovery_source(
        fixture["sealed_plan"],
        fixture["groups"],
        fixture["bindings"],
        fixture["science"],
        fixture["catalog"],
        fixture["strategy_ids"],
    )

    assert isinstance(result, ValidatedReductionRecoverySource)
    assert result.strategy_ids == tuple(sorted(fixture["strategy_ids"]))
    assert result.resume_index.strategy_ids == result.strategy_ids
    assert result.index_sha256 == result.resume_index.index_sha256
    assert result.plan_receipt["receipt_sha256"] == fixture["plan_receipt"]["receipt_sha256"]
    assert len(result.group_receipts) == 1
    assert result.group_receipt_sha256s
    assert result.group_ids == (0,)
    assert result.work_manifest_sha256 == fixture["work_manifest_sha256"]
    assert result.source_root_node_descriptor_sha256
    group_receipt = result.group_receipts[0]
    assert group_receipt["processes_per_worker"] == fixture["run_plan"].processes_per_worker
    assert group_receipt["block_size"] == fixture["run_plan"].block_size
    _, rows = _group_root_and_rows(fixture)
    assert rows
    info = json.loads(rows[0]["result_json"])["info"]
    assert {
        "annualized_strategy_return",
        "annualized_alpha",
        "weekly_spy_beat_rate",
        "position_fingerprint",
        "annual_returns",
        "strategy_fingerprint",
        "validation_opened",
        "locked_opened",
    }.issubset(info)
    with pytest.raises((TypeError, ValueError)):
        result.strategy_ids = ()
    with pytest.raises(TypeError):
        result.plan_receipt["receipt_sha256"] = "0" * 64
    with pytest.raises(TypeError):
        result.group_receipts[0]["receipt_sha256"] = "0" * 64


def _call_validator(fixture: dict[str, Any], **overrides: Any) -> Any:
    arguments = {
        "sealed_plan": fixture["sealed_plan"],
        "group_root": fixture["groups"],
        "expected_bindings": fixture["bindings"],
        "expected_science_identity_sha256": fixture["science"],
        "expected_catalog_manifest_sha256": fixture["catalog"],
        "expected_strategy_ids": fixture["strategy_ids"],
    }
    arguments.update(overrides)
    return verify_reduction_recovery_source(**arguments)


def _group_root_and_rows(fixture: dict[str, Any]) -> tuple[Path, list[dict[str, str]]]:
    group_root = next(path for path in fixture["groups"].iterdir() if path.is_dir())
    rows = pq.read_table(group_root / "results.parquet").to_pylist()
    return group_root, rows


def _rewrite_group_rows(group_root: Path, rows: list[dict[str, str]]) -> None:
    result_path = group_root / "results.parquet"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=_PARQUET_SCHEMA),
        result_path,
        compression="zstd",
    )
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    receipt_path = group_root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["result_sha256"] = result_sha256
    receipt_identity = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt_identity)
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = group_root / "reduction_group_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_sha256"] = result_sha256
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )


def _reseal_member(
    fixture: dict[str, Any],
    member: str,
    payload: dict[str, Any],
) -> None:
    member_path = fixture["sealed_plan"] / member
    member_path.write_text(
        json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    receipt_path = fixture["sealed_plan"] / "execution_plan_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    content_manifest = receipt["content_manifest"]
    member_bytes = member_path.read_bytes()
    sealed_paths = [
        item["path"]
        for item in content_manifest
        if item["path"] == member
        or item["path"].endswith(f"/{member}")
    ]
    for relative_path in sealed_paths:
        target = fixture["sealed_plan"] / relative_path
        target.write_bytes(member_bytes)
    payload_manifest_path = fixture["sealed_plan"] / "payload_bundle_manifest.json"
    payload_manifest = json.loads(
        payload_manifest_path.read_text(encoding="utf-8")
    )
    for item in payload_manifest["payloads"]:
        if item["member"] == member:
            target = (
                fixture["sealed_plan"]
                / "payload_artifacts"
                / item["artifact"]
                / item["member"]
            )
            item["size_bytes"] = target.stat().st_size
            item["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    payload_manifest_path.write_text(
        json.dumps(payload_manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    sealed_paths.append("payload_bundle_manifest.json")
    for item in content_manifest:
        if item["path"] in sealed_paths:
            target = fixture["sealed_plan"] / item["path"]
            item["size_bytes"] = target.stat().st_size
            item["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    if not sealed_paths:  # pragma: no cover - fixture always contains members
        raise AssertionError(f"sealed member missing: {member}")
    receipt["content_manifest_sha256"] = canonical_sha256(content_manifest)
    receipt["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
    )


@pytest.mark.parametrize("binding_name", ["request_sha256", "execution_plan_sha256"])
def test_wrong_source_bindings_are_rejected(
    tmp_path: Path,
    binding_name: str,
) -> None:
    fixture = _source_fixture(tmp_path)
    wrong_bindings = dict(fixture["bindings"])
    wrong_bindings[binding_name] = "0" * len(wrong_bindings[binding_name])

    with pytest.raises(ValueError, match="CATALOG_SEALED_PLAN_BINDING_INVALID"):
        _call_validator(fixture, expected_bindings=wrong_bindings)


def test_source_bindings_must_be_complete_and_nonempty(tmp_path: Path) -> None:
    fixture = _source_fixture(tmp_path)
    incomplete = dict(fixture["bindings"])
    incomplete.pop("decision_sha256")

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_SOURCE_BINDINGS_INCOMPLETE"):
        _call_validator(fixture, expected_bindings=incomplete)

    empty = dict(fixture["bindings"])
    empty["campaign_id"] = ""
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_SOURCE_BINDINGS_INVALID"):
        _call_validator(fixture, expected_bindings=empty)


def test_run_plan_token_is_verified_by_existing_consumer(tmp_path: Path) -> None:
    fixture = _source_fixture(tmp_path)
    run_plan = fixture["run_plan"].model_dump(mode="json")
    run_plan["admission_token_sha256"] = "0" * 64
    _reseal_member(fixture, "run_plan.json", run_plan)

    with pytest.raises(ValueError, match="CATALOG_ADMISSION_TOKEN_INVALID"):
        _call_validator(fixture)


def test_work_manifest_binding_is_verified_without_rewriting_the_source(
    tmp_path: Path,
) -> None:
    fixture = _source_fixture(tmp_path)
    run_plan = fixture["run_plan"].model_dump(mode="json")
    run_plan["work_manifest_sha256"] = "0" * 64
    _reseal_member(fixture, "run_plan.json", run_plan)

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_WORK_MANIFEST_BINDING_INVALID"):
        _call_validator(fixture)


@pytest.mark.parametrize(
    ("argument_name", "wrong_value", "error_code"),
    [
        (
            "expected_science_identity_sha256",
            "0" * 64,
            "CATALOG_RECOVERY_SOURCE_SCIENCE_BINDING_INVALID",
        ),
        (
            "expected_catalog_manifest_sha256",
            "0" * 64,
            "CATALOG_RECOVERY_SOURCE_SCIENCE_BINDING_INVALID",
        ),
    ],
)
def test_science_and_catalog_bindings_are_checked_against_contract(
    tmp_path: Path,
    argument_name: str,
    wrong_value: str,
    error_code: str,
) -> None:
    fixture = _source_fixture(tmp_path)

    with pytest.raises(ValueError, match=error_code):
        _call_validator(fixture, **{argument_name: wrong_value})


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_group_result_coverage_is_exact_without_duplicate_ids(
    tmp_path: Path,
    mutation: str,
) -> None:
    fixture = _source_fixture(tmp_path)
    group_root, rows = _group_root_and_rows(fixture)
    if mutation == "missing":
        rows = rows[:-1]
    elif mutation == "extra":
        extra = dict(rows[0])
        extra["strategy_id"] = "extra-historical-strategy"
        rows.append(extra)
    else:
        rows.append(dict(rows[0]))
    _rewrite_group_rows(group_root, rows)

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_STRATEGY_COVERAGE_INVALID"):
        _call_validator(fixture)


def test_partial_group_receipt_is_rejected_even_with_a_valid_hash(tmp_path: Path) -> None:
    fixture = _source_fixture(tmp_path)
    group_root, _ = _group_root_and_rows(fixture)
    receipt_path = group_root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["partial"] = True
    receipt["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_GROUP_BOUNDARY_INVALID"):
        _call_validator(fixture)


def test_altered_result_bytes_are_rejected_by_real_group_verifier(
    tmp_path: Path,
) -> None:
    fixture = _source_fixture(tmp_path)
    group_root, _ = _group_root_and_rows(fixture)
    result_path = group_root / "results.parquet"
    result_path.write_bytes(result_path.read_bytes() + b"altered")

    with pytest.raises(SystemExit, match="OPTIMIZED_REDUCTION_GROUP_INVALID"):
        _call_validator(fixture)


def test_invalid_group_manifest_hash_is_rejected_by_real_group_verifier(
    tmp_path: Path,
) -> None:
    fixture = _source_fixture(tmp_path)
    group_root, _ = _group_root_and_rows(fixture)
    manifest_path = group_root / "reduction_group_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["node_descriptor_sha256"] = "0" * 64
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="OPTIMIZED_REDUCTION_GROUP_INVALID"):
        _call_validator(fixture)


def test_sealed_manifest_bytes_are_not_repaired_or_rewritten(tmp_path: Path) -> None:
    fixture = _source_fixture(tmp_path)
    manifest_path = fixture["sealed_plan"] / "resume_work_manifest.json"
    original_bytes = manifest_path.read_bytes()
    manifest_path.write_bytes(original_bytes + b"altered")

    with pytest.raises(ValueError, match="CATALOG_SEALED_PLAN_CONTENT_INVALID"):
        _call_validator(fixture)
    assert manifest_path.read_bytes() == original_bytes + b"altered"
