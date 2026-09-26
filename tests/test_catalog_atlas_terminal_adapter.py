"""Focused fixtures for the in-run Atlas terminal contract."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Mapping, cast

import pytest

from aurora.infra.sp500_megarun import catalog_atlas_terminal_adapter as adapter
from scripts.finalize_catalog_atlas_fast_run import _parser, finalize_atlas_run
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
from aurora.infra.github_performance.contracts import canonical_sha256
from tests.test_catalog_cloud_authority import signed_request


def _dynamic_prepared() -> adapter.AtlasPreparedReceiptV1:
    identity = adapter.AtlasPreparationIdentityV1(
        campaign_key=adapter.CAMPAIGN_KEY,
        protected_commit_sha="e" * 40,
        campaign_definition_sha256="a" * 64,
        scientific_contract_sha256="b" * 64,
        dependency_lock_sha256="c" * 64,
        freeze_manifest_sha256="d" * 64,
        data_contract_sha256="e" * 64,
        feature_contract_sha256="f" * 64,
        runtime_input_run_id=adapter.EXPECTED_RUNTIME_INPUT_RUN_ID,
        selection_sha256=adapter.EXPECTED_SELECTION_SHA256,
    )
    return adapter.AtlasPreparedReceiptV1.create(
        identity=identity,
        qualified_worker_ceiling=20,
        target_end_iso="2030-01-01T00:00:00+00:00",
        calibration_receipt_sha256="1" * 64,
        plan_sha256="2" * 64,
        generated_at=adapter.datetime(2026, 9, 23, tzinfo=adapter.timezone.utc),
    )


def test_terminal_accepts_admitted_plan_not_historical_plan() -> None:
    prepared = _dynamic_prepared()
    plan = SimpleNamespace(
        catalog_id=adapter.CATALOG_ID,
        plan_sha256=prepared.plan_sha256,
        catalog_manifest_sha256=adapter.EXPECTED_CATALOG_MANIFEST_SHA256,
        catalog_space_sha256=adapter.EXPECTED_CATALOG_SPACE_SHA256,
        calibration_receipt_sha256=prepared.calibration_receipt_sha256,
        implementation_commit_sha=adapter.EXPECTED_IMPLEMENTATION_COMMIT_SHA,
        train_end=adapter.EXPECTED_TRAIN_END,
        target_end_iso=prepared.target_end_iso,
        requested_recipe_count=adapter.EXPECTED_RECIPE_COUNT,
        total_shards=adapter.EXPECTED_SHARD_COUNT,
        selection_seed=adapter.EXPECTED_SELECTION_SEED,
        selection_sha256=adapter.EXPECTED_SELECTION_SHA256,
        model_dump=lambda **_: {"validation_opened": False, "locked_opened": False},
    )
    adapter._validate_freeze(Path(__file__).parents[1], plan, prepared)
    plan.plan_sha256 = adapter.EXPECTED_PLAN_SHA256
    with pytest.raises(adapter.AtlasTerminalEvidenceError, match="ATLAS_TERMINAL_PLAN_BINDING_INVALID"):
        adapter._validate_freeze(Path(__file__).parents[1], plan, prepared)


def test_terminal_prepared_receipt_must_match_admission_and_identity(tmp_path: Path) -> None:
    prepared = _dynamic_prepared()
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "atlas_prepared_receipt.json").write_text(
        json.dumps(prepared.model_dump(mode="json")), encoding="utf-8"
    )
    assert adapter._load_bound_prepared_receipt(
        tmp_path,
        expected_receipt_sha256=prepared.receipt_sha256,
        expected_identity=prepared.identity,
    ) == prepared
    with pytest.raises(adapter.AtlasTerminalEvidenceError, match="ATLAS_TERMINAL_PREPARED_BINDING_INVALID"):
        adapter._load_bound_prepared_receipt(
            tmp_path,
            expected_receipt_sha256="0" * 64,
            expected_identity=prepared.identity,
        )
    with pytest.raises(adapter.AtlasTerminalEvidenceError, match="ATLAS_TERMINAL_PREPARED_BINDING_INVALID"):
        adapter._load_bound_prepared_receipt(
            tmp_path,
            expected_receipt_sha256=prepared.receipt_sha256,
            expected_identity=prepared.identity.model_copy(update={"protected_commit_sha": "f" * 40}),
        )


def test_terminal_accepts_frozen_catalog_hash_forms_and_rejects_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _dynamic_prepared()
    plan_dir = tmp_path / "plan"
    atlas_dir = tmp_path / "atlas"
    plan_dir.mkdir()
    atlas_dir.mkdir()
    (plan_dir / "atlas_prepared_receipt.json").write_text(prepared.model_dump_json(), encoding="utf-8")
    space: dict[str, bool | str] = {"validation_opened": False, "locked_opened": False}
    space["space_sha256"] = canonical_sha256(space)
    space_path = atlas_dir / "recipe_space.json"
    space_path.write_text(json.dumps(space, sort_keys=True), encoding="utf-8")
    space_file_sha256 = hashlib.sha256(space_path.read_bytes()).hexdigest()
    manifest = {
        "catalog_id": adapter.CATALOG_ID,
        "execution_authorized": False,
        "validation_opened": False,
        "locked_opened": False,
        "artifacts_sha256": {"recipe_space.json": space_file_sha256},
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    manifest_path = atlas_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest["manifest_sha256"]
    assert space_file_sha256 != space["space_sha256"]
    (plan_dir / "atlas_campaign_selection.json").write_text(json.dumps({
        "requested_recipe_count": adapter.EXPECTED_RECIPE_COUNT,
        "seed": adapter.EXPECTED_SELECTION_SEED,
        "selection_sha256": adapter.EXPECTED_SELECTION_SHA256,
    }), encoding="utf-8")
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED", reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256="a" * 64, submission_key_sha256="a" * 64,
        campaign_key=adapter.CAMPAIGN_KEY,
        prepared_receipt_sha256=prepared.receipt_sha256,
        selected_workers=20, launch_required=True, existing_run_id=None,
        decided_at=adapter.datetime(2026, 9, 24, tzinfo=adapter.timezone.utc),
        expires_at=adapter.datetime(2026, 9, 24, 1, tzinfo=adapter.timezone.utc),
    )
    monkeypatch.setattr(adapter, "EXPECTED_CATALOG_MANIFEST_SHA256", manifest["manifest_sha256"])
    monkeypatch.setattr(adapter, "EXPECTED_CATALOG_SPACE_SHA256", space_file_sha256)
    monkeypatch.setattr(adapter, "load_plan", lambda _: SimpleNamespace(plan_sha256=prepared.plan_sha256))
    monkeypatch.setattr(adapter, "build_atlas_preparation_identity", lambda *_: prepared.identity)
    monkeypatch.setattr(adapter, "_validate_freeze", lambda *_: None)

    _, plan_sha256 = adapter._validate_preflight(
        tmp_path, Path(__file__).parents[1], decision, prepared.identity.protected_commit_sha,
    )
    assert plan_sha256 == prepared.plan_sha256

    manifest["catalog_id"] = "tampered"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(adapter.AtlasTerminalEvidenceError, match="ATLAS_TERMINAL_CATALOG_HASH_INVALID"):
        adapter._validate_preflight(
            tmp_path, Path(__file__).parents[1], decision, prepared.identity.protected_commit_sha,
        )

    manifest["catalog_id"] = adapter.CATALOG_ID
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    space["space_sha256"] = "0" * 64
    space_path.write_text(json.dumps(space, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(adapter, "EXPECTED_CATALOG_SPACE_SHA256", hashlib.sha256(space_path.read_bytes()).hexdigest())
    with pytest.raises(adapter.AtlasTerminalEvidenceError, match="ATLAS_TERMINAL_SPACE_HASH_INVALID"):
        adapter._validate_preflight(
            tmp_path, Path(__file__).parents[1], decision, prepared.identity.protected_commit_sha,
        )


def _plan() -> SimpleNamespace:
    return SimpleNamespace(
        plan_sha256="a" * 64,
        catalog_manifest_sha256="b" * 64,
        selection_sha256="c" * 64,
        shards=(SimpleNamespace(shard_index=0, start_ordinal=0, stop_ordinal=2, expected_recipe_count=2),),
    )


def _write_final(root: Path, *, source_index: bool = False) -> None:
    plan = _plan()
    rows = []
    for ordinal in range(2):
        row = {
            "ordinal": ordinal,
            "plan_sha256": plan.plan_sha256,
            "validation_opened": False,
            "locked_opened": False,
            "value": ordinal,
        }
        row["result_sha256"] = adapter._canonical(row)
        rows.append(row)
    result_bytes = b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n" for row in rows
    )
    (root / "results.jsonl").write_bytes(result_bytes)
    result_sha = hashlib.sha256(result_bytes).hexdigest()
    common = {
        "plan_sha256": plan.plan_sha256,
        "requested_recipe_count": 2,
        "verified_recipe_count": 2,
        "verified_shard_count": 1,
    }
    (root / "reduction_receipt.json").write_text(json.dumps({
        **common,
        "accepted": True,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "selection_sha256": plan.selection_sha256,
        "missing_ordinals": 0,
        "duplicate_ordinals": 0,
        "conflicts": 0,
        "results_sha256": result_sha,
        "storage_mode": "combined_results_file",
        "row_hash_verification_mode": "canonical_row_hash",
        "row_hashes_recomputed": True,
        "result_file_hashes_verified": True,
        "validation_opened": False,
        "locked_opened": False,
    }))
    (root / "coverage_report.json").write_text(json.dumps({
        "requested_recipe_count": 2,
        "verified_recipe_count": 2,
        "verified_shard_count": 1,
        "missing_ordinals": 0,
        "duplicate_ordinals": 0,
        "conflicts": 0,
        "validation_opened": False,
        "locked_opened": False,
    }))
    (root / "all_results_manifest.json").write_text(json.dumps({
        "storage_mode": "combined_results_file",
        "results_path": "../results.jsonl",
        "results_sha256": result_sha,
        "row_count": 2,
        "row_hash_verification_mode": "canonical_row_hash",
        "row_hashes_recomputed": True,
        "result_file_hashes_verified": True,
        "validation_opened": False,
        "locked_opened": False,
    }))
    if source_index:
        source = {
            "schema_version": 1,
            "storage_mode": "combined_results_file",
            "plan_sha256": plan.plan_sha256,
            "catalog_manifest_sha256": plan.catalog_manifest_sha256,
            "row_count": 2,
            "shard_count": 1,
            "validation_opened": False,
            "locked_opened": False,
            "shards": [{
                "shard_index": 0,
                "start_ordinal": 0,
                "stop_ordinal": 2,
                "expected_recipe_count": 2,
                "result_sha256": "d" * 64,
            }],
        }
        source["source_index_sha256"] = adapter._canonical(source)
        (root / "source_results_index.json").write_text(json.dumps(source))


def test_reducer_fixture_is_verified_without_shard_downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "EXPECTED_RECIPE_COUNT", 2)
    monkeypatch.setattr(adapter, "EXPECTED_SHARD_COUNT", 1)
    root = tmp_path / "final"
    root.mkdir()
    _write_final(root)

    count, digest = adapter._verify_final(root, _plan())

    assert count == 2
    assert digest == hashlib.sha256((root / "results.jsonl").read_bytes()).hexdigest()


def test_normal_full_result_does_not_require_source_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "EXPECTED_RECIPE_COUNT", 2)
    monkeypatch.setattr(adapter, "EXPECTED_SHARD_COUNT", 1)
    root = tmp_path / "final"
    root.mkdir()
    _write_final(root, source_index=False)

    count, _ = adapter._verify_final(root, _plan())

    assert count == 2


def test_optional_source_index_is_still_fail_closed_when_present_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "EXPECTED_RECIPE_COUNT", 2)
    monkeypatch.setattr(adapter, "EXPECTED_SHARD_COUNT", 1)
    root = tmp_path / "final"
    root.mkdir()
    _write_final(root, source_index=True)
    source = json.loads((root / "source_results_index.json").read_text())
    source["shard_count"] = 2
    source["source_index_sha256"] = adapter._canonical({key: value for key, value in source.items() if key != "source_index_sha256"})
    (root / "source_results_index.json").write_text(json.dumps(source))

    with pytest.raises(adapter.AtlasTerminalEvidenceError) as caught:
        adapter._verify_final(root, _plan())

    assert caught.value.code == "ATLAS_TERMINAL_SOURCE_INDEX_BINDING_INVALID"


def test_parent_run_in_progress_and_required_matrix_jobs_are_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps({
        "id": 209906,
        "html_url": "https://github.com/example/repo/actions/runs/209906",
        "head_sha": "e" * 40,
        "path": adapter.CONTROLLER_WORKFLOW_PATH,
        "status": "in_progress",
        "conclusion": None,
    }))
    run, run_id, _, _ = adapter._parse_run(run_path)
    assert run["status"] == "in_progress"
    assert run["conclusion"] is None
    assert run_id == 209906

    monkeypatch.setattr(adapter, "EXPECTED_SHARD_COUNT", 360)
    rows = [
        {"name": "gate", "conclusion": "success"},
        {"name": "engine", "conclusion": "skipped"},
        {"name": "engine / engine_verify_sealed_plan", "conclusion": "skipped"},
        {"name": "engine_atlas", "conclusion": "success"},
        {"name": "engine_atlas / preflight", "conclusion": "success"},
        {"name": "engine_atlas / reduce", "conclusion": "success"},
        {"name": "finalize", "conclusion": None},
    ]
    rows.extend({"name": f"engine_atlas / evaluate_{name} ({index})", "conclusion": "success"}
                for index, name in enumerate(("a", "b", "c") * 120))
    assert len(adapter._validate_jobs({"jobs": rows})) == 367
    assert len(adapter._validate_jobs({"jobs": [
        row for row in rows if cast(Mapping[str, object], row)["name"] != "engine"
    ]})) == 366


def test_cli_requires_only_parent_snapshots_and_two_artifact_roots() -> None:
    args = _parser().parse_args([
        "--request-context", "context.json", "--decision", "decision.json",
        "--run", "run.json", "--jobs", "jobs.json",
        "--preflight-root", "preflight", "--final-root", "final",
        "--output", "receipt.json", "--comment-output", "comment.json",
        "--github-output", "github-output",
    ])

    assert args.final_results_artifact == "sp500-atlas-final-results"
    assert adapter.CAMPAIGN_KEY == "sp500-atlas-v1"
    assert adapter.CATALOG_ID == "sp500-atlas-1"
    assert not hasattr(args, "invocation")
    assert not hasattr(args, "artifacts")
    assert not hasattr(args, "shards_root")


def test_unlaunched_atlas_preserves_gate_reason_for_protected_expiry_close(tmp_path: Path) -> None:
    request = signed_request(campaign_key=adapter.CAMPAIGN_KEY)
    decided = adapter.datetime(2026, 9, 24, 13, 8, 51, tzinfo=adapter.timezone.utc)
    decision = CatalogFastLaunchDecisionV1.create(
        state="BLOCKED", reason_code="CATALOG_PREPARATION_REQUIRED",
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key, prepared_receipt_sha256=None,
        selected_workers=0, launch_required=False, existing_run_id=None,
        decided_at=decided, expires_at=decided,
    )
    context = {
        "identity": {"engine_id": "atlas_static_v1", "campaign_key": adapter.CAMPAIGN_KEY},
        "logical_recipe_count": 209906,
        "request": request.model_dump(mode="json"),
    }
    context["content_sha256"] = canonical_sha256(context)
    context_path = tmp_path / "context.json"
    decision_path = tmp_path / "decision.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    decision_path.write_text(decision.model_dump_json(), encoding="utf-8")
    receipt = finalize_atlas_run(
        repo_root=tmp_path, request_context_path=context_path, decision_path=decision_path,
        run_path=tmp_path / "missing-run.json", jobs_path=tmp_path / "missing-jobs.json",
        preflight_root=tmp_path / "missing-preflight", final_root=tmp_path / "missing-final",
        output_path=tmp_path / "receipt.json", comment_output_path=tmp_path / "comment.json",
        github_output=tmp_path / "github-output", gate_result="success",
    )
    assert receipt.state == "BLOCKED"
    assert receipt.reason_code == decision.reason_code
    assert receipt.engine_run_id is None
    assert receipt.observed_recipe_count == 0


def test_adapter_imports_without_pyarrow() -> None:
    class NoPyarrow:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "pyarrow" or fullname.startswith("pyarrow."):
                raise ModuleNotFoundError("pyarrow intentionally unavailable", name=fullname)
            return None

    module_name = adapter.__name__
    original = sys.modules.pop(module_name)
    blocker = NoPyarrow()
    sys.meta_path.insert(0, blocker)
    try:
        reloaded = importlib.import_module(module_name)
        assert reloaded.EXPECTED_RECIPE_COUNT == 209_906
    finally:
        sys.meta_path.remove(blocker)
        sys.modules[module_name] = original
