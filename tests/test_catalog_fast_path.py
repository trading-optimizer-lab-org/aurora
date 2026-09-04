from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignEntryV1,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogExecutionSampleV1,
    CatalogFastGateSnapshotV1,
    CatalogPreparedReceiptV1,
    CatalogPreparationIdentityV1,
    CatalogTerminalReceiptV1,
    ExistingCatalogLaunchV1,
    build_catalog_preparation_identity,
    decide_fast_catalog_launch,
    select_fast_execution_configuration,
    should_retry_catalog_failure,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    verify_prepared_catalog_bundle,
    write_prepared_catalog_bundle_manifest,
)
from scripts.finalize_catalog_preparation import (
    conservative_reduction_projections,
    required_prepared_cache_keys,
)
from scripts.prepare_catalog_campaign import build_preparation_bindings
from scripts.select_catalog_preparation_targets import select_targets
from scripts.verify_catalog_prepared_bundle import missing_required_cache_keys


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
COMMIT = "a" * 40
SCIENCE = "b" * 64
DEFINITION = "c" * 64
REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000001"


def _entry() -> CatalogCampaignEntryV1:
    return CatalogCampaignEntryV1(
        campaign_key="sp500-optimized-catalog-v1",
        engine_id="optimized_catalog_v1",
        definition_manifest_path=(
            "config/catalog_campaign_definitions/sp500-optimized-catalog-v1.manifest.json"
        ),
        optimization_policy_path="config/sp500_catalog_optimization_policy_v1.json",
        campaign_contract_path="config/sp500_megarun_dehb_campaign_v1.json",
        catalog_dir="config/sp500_megarun_strategy_catalog_v1",
        selected_config_path="config/sp500_megarun_selected_dehb_13.json",
        admission_evidence_path="config/sp500_catalog_admission_evidence_current_v1.json",
        data_contract_path="config/sp500_megarun_free_data_240.json",
        feature_contract_path="config/sp500_megarun_feature_contract_240.json",
        runtime_input_run_id=31418682679,
        reference_run_id=31948898747,
        scientific_contract_sha256=SCIENCE,
        max_free_workers=360,
        allowed_protected_branch="main",
        source_artifact_contracts=("runtime_input_pack_v1", "reference_oracle_v1"),
        component_store_family="sp500_component_store_v1",
        reducer_family="catalog_hierarchical_reducer_v1",
        active=True,
    )


def _identity(**updates: object) -> CatalogPreparationIdentityV1:
    values: dict[str, object] = {
        "schema_version": "1",
        "campaign_key": _entry().campaign_key,
        "engine_id": _entry().engine_id,
        "protected_commit_sha": COMMIT,
        "campaign_definition_sha256": DEFINITION,
        "scientific_contract_sha256": SCIENCE,
        "dependency_lock_sha256": "d" * 64,
        "optimization_policy_sha256": "e" * 64,
        "data_contract_sha256": "f" * 64,
        "feature_contract_sha256": "1" * 64,
        "catalog_manifest_sha256": "2" * 64,
        "selected_config_sha256": "3" * 64,
    }
    values.update(updates)
    return CatalogPreparationIdentityV1.model_validate(values)


def _prepared(**updates: object) -> CatalogPreparedReceiptV1:
    values: dict[str, object] = {
        "identity": _identity(),
        "generated_at": NOW - timedelta(minutes=2),
        "runtime_identity_sha256": "4" * 64,
        "prepared_input_identity_sha256": "5" * 64,
        "component_store_manifest_sha256": "6" * 64,
        "execution_plan_template_sha256": "7" * 64,
        "required_cache_keys": (
            "aurora-catalog-component-main",
            "aurora-catalog-input-main",
            "aurora-catalog-runtime-main",
        ),
        "logical_recipe_count": 37_258,
        "unique_component_count": 7_281,
        "qualified_worker_ceiling": 240,
        "production_dependency_smoke_passed": True,
        "recipe_worker_build_allowed": False,
    }
    values.update(updates)
    return CatalogPreparedReceiptV1.create(**values)


def test_prepared_receipt_rejects_noncanonical_cache_keys() -> None:
    with pytest.raises(ValueError, match="CATALOG_PREPARED_CACHE_KEYS_INVALID"):
        _prepared(required_cache_keys=("z", "a", "z"))


def test_live_cache_check_covers_every_cache_bound_to_prepared() -> None:
    required = _prepared().required_cache_keys
    rows = tuple(
        {"key": key, "ref": "refs/heads/main"}
        for key in required[:-1]
    )

    assert missing_required_cache_keys(required, rows) == (required[-1],)


def test_preparation_receipt_binds_runtime_inputs_and_components() -> None:
    index = SimpleNamespace(
        candidates=(
            SimpleNamespace(object_family="runtime", cache_key="runtime-key"),
            SimpleNamespace(object_family="prepared_input", cache_key="input-key"),
            SimpleNamespace(object_family="component", cache_key="component-key"),
        )
    )
    receipt = {
        "runtime_cache_key": "runtime-key",
        "prepared_input_cache_keys": (("runtime-fragment-core", "input-key"),),
    }

    assert required_prepared_cache_keys(index, receipt) == (
        "component-key",
        "input-key",
        "runtime-key",
    )


def _request(**updates: object) -> CatalogRunRequestV1:
    values: dict[str, object] = {
        "schema_version": "1",
        "request_id": REQUEST_ID,
        "campaign_key": _entry().campaign_key,
        "launch_generation": 1,
        "launch_ticket_sha256": "8" * 64,
        "previous_terminal_request_sha256": None,
        "campaign_definition_sha256": DEFINITION,
        "prompt_sha256": "9" * 64,
        "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        "free_resources_only": True,
        "automatic_recovery": True,
        "max_same_failure_count": 3,
        "requester_public_key_sha256": "a" * 64,
        "requester_attestation_algorithm": "rsa-pss-sha256-v1",
        "requester_attestation_b64": "A" * 300,
    }
    values.update(updates)
    return CatalogRunRequestV1.model_validate(values)


def _snapshot(**updates: object) -> CatalogFastGateSnapshotV1:
    values: dict[str, object] = {
        "schema_version": "1",
        "observed_at": NOW,
        "protected_commit_sha": COMMIT,
        "controller_enabled": True,
        "production_armed": True,
        "current_safe_free_capacity": 180,
        "existing_launches": (),
        "active_campaign_keys": (),
    }
    values.update(updates)
    return CatalogFastGateSnapshotV1.model_validate(values)


def test_valid_prepared_request_is_admitted_once_with_safe_capacity() -> None:
    decision = decide_fast_catalog_launch(
        request=_request(),
        registry_entry=_entry(),
        prepared_receipt=_prepared(),
        expected_preparation_identity=_identity(),
        snapshot=_snapshot(),
        issue_created_at=NOW - timedelta(seconds=10),
    )

    assert decision.state == "QUEUED"
    assert decision.reason_code == "CATALOG_FAST_PATH_ADMITTED"
    assert decision.launch_required is True
    assert decision.selected_workers == 180
    assert decision.expires_at == NOW + timedelta(minutes=30) - timedelta(seconds=10)


def test_signed_campaign_key_survives_preparation_only_revisions() -> None:
    decision = decide_fast_catalog_launch(
        request=_request(campaign_definition_sha256="0" * 64),
        registry_entry=_entry(),
        prepared_receipt=_prepared(),
        expected_preparation_identity=_identity(),
        snapshot=_snapshot(),
        issue_created_at=NOW - timedelta(seconds=10),
    )

    assert decision.state == "QUEUED"
    assert decision.reason_code == "CATALOG_FAST_PATH_ADMITTED"
    assert decision.launch_required is True


@pytest.mark.parametrize(
    ("prepared", "snapshot", "reason"),
    [
        (
            _prepared(identity=_identity(protected_commit_sha="f" * 40)),
            _snapshot(),
            "CATALOG_PREPARATION_STALE",
        ),
        (
            _prepared(),
            _snapshot(controller_enabled=False),
            "CATALOG_CONTROLLER_DISABLED",
        ),
        (
            _prepared(),
            _snapshot(production_armed=False),
            "CATALOG_PRODUCTION_DISARMED",
        ),
        (
            _prepared(),
            _snapshot(current_safe_free_capacity=0),
            "CATALOG_FREE_CAPACITY_UNAVAILABLE",
        ),
        (
            _prepared(),
            _snapshot(active_campaign_keys=(_entry().campaign_key,)),
            "CATALOG_CAMPAIGN_BUSY",
        ),
    ],
)
def test_gate_blocks_with_one_exact_reason(
    prepared: CatalogPreparedReceiptV1,
    snapshot: CatalogFastGateSnapshotV1,
    reason: str,
) -> None:
    decision = decide_fast_catalog_launch(
        request=_request(),
        registry_entry=_entry(),
        prepared_receipt=prepared,
        expected_preparation_identity=_identity(),
        snapshot=snapshot,
        issue_created_at=NOW - timedelta(seconds=10),
    )

    assert decision.state == "BLOCKED"
    assert decision.reason_code == reason
    assert decision.launch_required is False
    assert decision.selected_workers == 0


def test_expired_request_is_rejected_instead_of_starting_late() -> None:
    decision = decide_fast_catalog_launch(
        request=_request(),
        registry_entry=_entry(),
        prepared_receipt=_prepared(),
        expected_preparation_identity=_identity(),
        snapshot=_snapshot(),
        issue_created_at=NOW - timedelta(minutes=31),
    )

    assert decision.state == "BLOCKED"
    assert decision.reason_code == "CATALOG_REQUEST_EXPIRED"
    assert decision.launch_required is False


def test_existing_submission_is_adopted_without_duplicate_launch() -> None:
    request = _request()
    existing = ExistingCatalogLaunchV1(
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        state="RUNNING",
        run_id=123,
    )
    decision = decide_fast_catalog_launch(
        request=request,
        registry_entry=_entry(),
        prepared_receipt=_prepared(),
        expected_preparation_identity=_identity(),
        snapshot=_snapshot(existing_launches=(existing,)),
        issue_created_at=NOW - timedelta(seconds=10),
    )

    assert decision.state == "RUNNING"
    assert decision.reason_code == "CATALOG_REQUEST_ALREADY_RUNNING"
    assert decision.launch_required is False
    assert decision.existing_run_id == 123


def test_any_preparation_input_drift_is_rejected_before_launch() -> None:
    decision = decide_fast_catalog_launch(
        request=_request(),
        registry_entry=_entry(),
        prepared_receipt=_prepared(),
        expected_preparation_identity=_identity(dependency_lock_sha256="0" * 64),
        snapshot=_snapshot(),
        issue_created_at=NOW - timedelta(seconds=10),
    )

    assert decision.state == "BLOCKED"
    assert decision.reason_code == "CATALOG_PREPARATION_STALE"
    assert decision.launch_required is False


def test_prepared_receipt_rejects_content_tampering() -> None:
    receipt = _prepared()
    payload = receipt.model_dump(mode="json")
    payload["unique_component_count"] = 7_282

    with pytest.raises(ValueError, match="CATALOG_PREPARED_RECEIPT_HASH_INVALID"):
        CatalogPreparedReceiptV1.model_validate(payload)


def test_repository_preparation_identity_binds_every_invalidation_input() -> None:
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    entry = __import__(
        "aurora.infra.sp500_megarun.catalog_campaign_registry",
        fromlist=["load_catalog_campaign_registry"],
    ).load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    ).campaigns[0]

    identity = build_catalog_preparation_identity(
        repo_root=root,
        registry_entry=entry,
        protected_commit_sha=COMMIT,
    )

    assert identity.campaign_key == entry.campaign_key
    assert identity.scientific_contract_sha256 == entry.scientific_contract_sha256
    assert identity.protected_commit_sha == COMMIT
    assert len(identity.preparation_key_sha256) == 64


def test_configuration_selection_minimizes_request_to_completion_not_compute_only() -> None:
    samples = (
        CatalogExecutionSampleV1(
            workers=60,
            component_workers=120,
            component_processes_per_worker=4,
            processes_per_worker=1,
            block_size=1,
            queue_seconds=5,
            setup_seconds=15,
            compute_seconds=80,
            reduction_seconds=10,
            equivalent=True,
            free_resources_only=True,
        ),
        CatalogExecutionSampleV1(
            workers=240,
            component_workers=120,
            component_processes_per_worker=4,
            processes_per_worker=1,
            block_size=1,
            queue_seconds=120,
            setup_seconds=15,
            compute_seconds=30,
            reduction_seconds=10,
            equivalent=True,
            free_resources_only=True,
        ),
    )

    selected = select_fast_execution_configuration(
        samples,
        maximum_workers=360,
        current_safe_free_capacity=240,
    )

    assert selected.workers == 60
    assert selected.request_to_completion_seconds == 110


@pytest.mark.parametrize(
    ("reason", "occurrences", "expected"),
    [
        ("GITHUB_RUNNER_LOST", 1, True),
        ("GITHUB_RUNNER_LOST", 2, True),
        ("GITHUB_RUNNER_LOST", 3, False),
        ("CATALOG_SCIENCE_IDENTITY_MISMATCH", 1, False),
        ("CATALOG_REQUEST_INVALID", 1, False),
    ],
)
def test_only_transient_failures_receive_at_most_two_retries(
    reason: str,
    occurrences: int,
    expected: bool,
) -> None:
    assert should_retry_catalog_failure(reason, occurrences=occurrences) is expected


def test_prepared_bundle_is_content_bound_and_exactly_reusable(tmp_path: Path) -> None:
    receipt = _prepared()
    (tmp_path / "prepared-receipt.json").write_text(
        json.dumps(receipt.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    (tmp_path / "material.json").write_text('{"ready":true}\n', encoding="utf-8")

    manifest = write_prepared_catalog_bundle_manifest(
        bundle_dir=tmp_path,
        prepared_receipt=receipt,
    )
    verified_receipt, verified_manifest = verify_prepared_catalog_bundle(
        bundle_dir=tmp_path,
        expected_identity=_identity(),
    )

    assert verified_receipt == receipt
    assert verified_manifest == manifest


def test_prepared_bundle_rejects_any_material_tampering(tmp_path: Path) -> None:
    receipt = _prepared()
    (tmp_path / "prepared-receipt.json").write_text(
        json.dumps(receipt.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    material = tmp_path / "material.json"
    material.write_text('{"ready":true}\n', encoding="utf-8")
    write_prepared_catalog_bundle_manifest(
        bundle_dir=tmp_path,
        prepared_receipt=receipt,
    )
    material.write_text('{"ready":false}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="CATALOG_PREPARED_BUNDLE_CONTENT_INVALID"):
        verify_prepared_catalog_bundle(
            bundle_dir=tmp_path,
            expected_identity=_identity(),
        )


def test_fast_plan_verifier_import_does_not_require_pyarrow() -> None:
    code = """
import importlib.abc
import sys
from pathlib import Path
from types import ModuleType

repo = Path.cwd()
for package_name, package_path in (
    ("aurora", repo),
    ("aurora.infra", repo / "infra"),
    ("aurora.infra.sp500_megarun", repo / "infra" / "sp500_megarun"),
):
    package = ModuleType(package_name)
    package.__path__ = [str(package_path)]
    sys.modules[package_name] = package

class BlockPyArrow(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "pyarrow" or fullname.startswith("pyarrow."):
            raise ModuleNotFoundError("pyarrow blocked in controller gate")
        return None

sys.meta_path.insert(0, BlockPyArrow())
from aurora.infra.sp500_megarun.catalog_prepared_bundle import materialize_prepared_catalog_plan

try:
    materialize_prepared_catalog_plan(
        bundle_dir=Path("missing-prepared-bundle"),
        expected_identity=None,
        request_sha256="a" * 64,
        decision_sha256="b" * 64,
        output_dir=Path("unused-output"),
    )
except ModuleNotFoundError as exc:
    if exc.name == "pyarrow":
        raise
except (FileNotFoundError, ValueError):
    pass
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_terminal_success_receipt_requires_exact_coverage_and_separate_times() -> None:
    receipt = CatalogTerminalReceiptV1.create(
        state="SUCCESS",
        reason_code="CATALOG_RUN_SUCCESS",
        request_sha256=_request().request_sha256,
        submission_key_sha256=_request().submission_key_sha256,
        campaign_key=_entry().campaign_key,
        prepared_receipt_sha256=_prepared().receipt_sha256,
        engine_run_id=123,
        run_url="https://github.com/example/repository/actions/runs/123",
        expected_recipe_count=37_258,
        observed_recipe_count=37_258,
        queue_seconds=12.0,
        preparation_seconds=0.0,
        computation_seconds=81.0,
        recovery_seconds=4.0,
        reduction_seconds=8.0,
        recovered_block_count=1,
        failure_class=None,
        result_science_sha256="f" * 64,
        created_at=NOW,
    )

    assert receipt.state == "SUCCESS"
    assert receipt.observed_recipe_count == receipt.expected_recipe_count
    assert receipt.receipt_sha256


def test_terminal_success_receipt_rejects_incomplete_coverage() -> None:
    with pytest.raises(ValueError, match="CATALOG_TERMINAL_COVERAGE_INVALID"):
        CatalogTerminalReceiptV1.create(
            state="SUCCESS",
            reason_code="CATALOG_RUN_SUCCESS",
            request_sha256=_request().request_sha256,
            submission_key_sha256=_request().submission_key_sha256,
            campaign_key=_entry().campaign_key,
            prepared_receipt_sha256=_prepared().receipt_sha256,
            engine_run_id=123,
            run_url="https://github.com/example/repository/actions/runs/123",
            expected_recipe_count=37_258,
            observed_recipe_count=37_257,
            queue_seconds=0.0,
            preparation_seconds=0.0,
            computation_seconds=80.0,
            recovery_seconds=0.0,
            reduction_seconds=8.0,
            recovered_block_count=0,
            failure_class=None,
            result_science_sha256="f" * 64,
            created_at=NOW,
        )


def test_blocked_terminal_receipt_can_report_missing_preparation() -> None:
    receipt = CatalogTerminalReceiptV1.create(
        state="BLOCKED",
        reason_code="CATALOG_PREPARATION_REQUIRED",
        request_sha256=_request().request_sha256,
        submission_key_sha256=_request().submission_key_sha256,
        campaign_key=_entry().campaign_key,
        prepared_receipt_sha256=None,
        engine_run_id=None,
        run_url=None,
        expected_recipe_count=37_258,
        observed_recipe_count=0,
        queue_seconds=1.0,
        preparation_seconds=0.0,
        computation_seconds=0.0,
        recovery_seconds=0.0,
        reduction_seconds=0.0,
        recovered_block_count=0,
        failure_class="infrastructure",
        result_science_sha256=None,
        created_at=NOW,
    )

    assert receipt.state == "BLOCKED"
    assert receipt.prepared_receipt_sha256 is None


def test_preparation_bindings_are_deterministic_and_request_independent() -> None:
    first = build_preparation_bindings(_identity())
    second = build_preparation_bindings(_identity())

    assert first == second
    assert set(first) == {
        "campaign_id",
        "request_sha256",
        "authority_id",
        "execution_plan_sha256",
        "decision_sha256",
    }


def test_hot_reduction_defaults_to_a_bounded_tree() -> None:
    central, hierarchical = conservative_reduction_projections(
        recipe_count=37_258,
        workers=60,
        result_bytes_per_recipe=512,
    )

    assert central.timeout_fraction_p99 is None
    assert max(
        value
        for value in hierarchical.model_dump(mode="python").values()
        if isinstance(value, float)
    ) <= 0.69


def test_preparation_target_selection_includes_only_active_registered_catalogs(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "github-output.txt"

    selected = select_targets(repo_root=root, campaign_key="", github_output=output)

    assert selected == ("sp500-optimized-catalog-v1",)
    assert "target_count=1" in output.read_text("utf-8")
