"""Offline, fail-closed tests for the Atlas PREPARED producer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_atlas_cloud_identity import (
    AtlasPreparedReceiptV1,
)
from scripts import prepare_catalog_atlas_bundle as producer


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/catalog-atlas-prepare-one.yml"
COMMIT = "c" * 40
START = datetime(2030, 1, 1, tzinfo=timezone.utc)
START_ISO = "2030-01-01T00:00:00Z"
TARGET_ISO = "2030-01-08T00:00:00Z"
SELECTION_SHA256 = "8fc537ed98a04b74ae37529fe7659a49432b2d36d1b38de1998d5f5e6771e3a1"


def _context() -> producer.CampaignContext:
    freeze = {
        "catalog_id": "sp500-atlas-1",
        "catalog_manifest_sha256": "09068cf0b0ff716075bdd693dbdfbdcf3779c7cb326a92aca11d9ab22b577f08",
        "catalog_space_sha256": "c5a29064acd626a0aa67559222789022aecd253cb9ab011bd6e7e4bb2253be63",
        "selection_sha256": SELECTION_SHA256,
        "runtime_input_run_id": 31418682679,
        "scientific_implementation_commit_sha": "0b654f1d25588cfca55c449e3634dd392e62e8f3",
        "pilot_source_run_id": "32142082213",
        "pilot_verify_run_id": "32152459079",
        "pilot_receipt_sha256": "9d72807e6f27a8aec11fe3defd8b005bccc96555d8fac66d65ad94209bfcdad6",
        "pilot_manifest_sha256": "8c6eeb0a79c3c1c5769f15beb70734e8781393afd4aa95a04a48c40d47f4e420",
        "pilot_fault_fixture_receipt_sha256": "fe49ec1b750a8b52c72abbeb727c3319f18aacb34f3df869a66b4731641618c4",
        "pilot_verified_recipe_count": 34985,
        "pilot_verified_shard_count": 60,
        "pilot_effective_concurrency": 20.490609608222336,
        "pilot_validation_opened": False,
        "pilot_locked_opened": False,
    }
    entry = SimpleNamespace(
        campaign_key="sp500-atlas-v1",
        engine_id="atlas_static_v1",
        scientific_contract_sha256="a" * 64,
        runtime_input_run_id=31418682679,
        max_free_workers=20,
    )
    return producer.CampaignContext(
        entry=entry,
        campaign_definition_sha256="b" * 64,
        freeze_manifest_sha256="d" * 64,
        dependency_lock_sha256="e" * 64,
        data_contract_sha256="f" * 64,
        feature_contract_sha256="1" * 64,
        freeze=freeze,
    )


def _fake_calibration_output(root: Path) -> Path:
    calibration = root / "calibration-output"
    (calibration / "atlas").mkdir(parents=True)
    (calibration / "atlas/manifest.json").write_text("{}\n", encoding="utf-8")
    (calibration / "atlas/recipe_space.json").write_text("{}\n", encoding="utf-8")
    (calibration / "calibration").mkdir()
    (calibration / "calibration/calibration_receipt.json").write_text(
        '{"recommended_mode":"cold"}\n', encoding="utf-8"
    )
    return calibration


def _verified_identity() -> dict[str, object]:
    return {
        "catalog_id": "sp500-atlas-1",
        "catalog_manifest_sha256": "09068cf0b0ff716075bdd693dbdfbdcf3779c7cb326a92aca11d9ab22b577f08",
        "catalog_space_sha256": "c5a29064acd626a0aa67559222789022aecd253cb9ab011bd6e7e4bb2253be63",
        "scientific_contract_sha256": "a" * 64,
        "freeze_manifest_sha256": "d" * 64,
        "data_contract_sha256": "f" * 64,
        "feature_contract_sha256": "1" * 64,
        "calibration_receipt_sha256": "2" * 64,
        "requested_recipe_count": 209906,
        "total_shards": 360,
        "selection_seed": 20260818,
        "selection_sha256": SELECTION_SHA256,
        "train_end": "2010-12-31",
        "planned_target_end_iso": TARGET_ISO,
        "validation_opened": False,
        "locked_opened": False,
        "execution_authorized": False,
    }


def _install_fake_plan(
    monkeypatch: pytest.MonkeyPatch,
    *,
    requested_recipe_count: int = 209906,
) -> dict[str, object]:
    plan_sha256 = "3" * 64
    calls: dict[str, object] = {}

    def fake_plan_atlas_run(**kwargs):
        calls.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        plan_data = {
            "train_end": "2010-12-31",
            "catalog_id": "sp500-atlas-1",
            "catalog_manifest_sha256": "09068cf0b0ff716075bdd693dbdfbdcf3779c7cb326a92aca11d9ab22b577f08",
            "catalog_space_sha256": "c5a29064acd626a0aa67559222789022aecd253cb9ab011bd6e7e4bb2253be63",
            "requested_recipe_count": requested_recipe_count,
            "total_shards": 360,
            "selection_seed": 20260818,
            "selection_sha256": SELECTION_SHA256,
            "target_end_iso": TARGET_ISO,
            "validation_opened": False,
            "locked_opened": False,
            "calibration_receipt_sha256": "2" * 64,
        }
        (output_dir / "atlas_run_plan.json").write_text(
            json.dumps(plan_data), encoding="utf-8"
        )
        (output_dir / "atlas_campaign_selection.json").write_text(
            json.dumps(
                {
                    "requested_recipe_count": 209906,
                    "seed": 20260818,
                    "selection_sha256": SELECTION_SHA256,
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "atlas_worker_matrices.json").write_text("{}", encoding="utf-8")
        (output_dir / "atlas_plan_summary.json").write_text("{}", encoding="utf-8")
        return {
            "accepted": True,
            "plan_sha256": plan_sha256,
            "requested_recipe_count": requested_recipe_count,
            "total_shards": 360,
            "target_end_iso": TARGET_ISO,
            "selection_seed": 20260818,
            "validation_opened": False,
            "locked_opened": False,
            "execution_authorized": False,
        }

    fake_plan_type = type(
        "PlanStub",
        (),
        {
            "model_validate": staticmethod(
                lambda payload: SimpleNamespace(
                    **payload,
                    plan_sha256=plan_sha256,
                )
            )
        },
    )
    monkeypatch.setattr(producer, "plan_atlas_run", fake_plan_atlas_run)
    monkeypatch.setattr(producer, "AtlasRunPlanV1", fake_plan_type)
    monkeypatch.setattr(
        producer,
        "verify_atlas_cloud_identity",
        lambda *args, **kwargs: _verified_identity(),
    )
    return calls


def _prepare(root: Path, monkeypatch: pytest.MonkeyPatch, **kwargs):
    calibration = _fake_calibration_output(root)
    monkeypatch.setattr(producer, "resolve_preparation_context", lambda *_: _context())
    expected_key = producer._build_static_identity(_context(), COMMIT).preparation_key_sha256
    return producer.prepare_catalog_atlas_bundle(
        repo_root=root,
        campaign_key="sp500-atlas-v1",
        protected_commit_sha=COMMIT,
        repository=producer.REPOSITORY,
        ref="refs/heads/main",
        planning_started_at_iso=START_ISO,
        planned_target_end_iso=TARGET_ISO,
        expected_campaign_definition_sha256="b" * 64,
        expected_preparation_key_sha256=expected_key,
        calibration_output_dir=calibration,
        bundle_dir=root / "prepared-bundle",
        now=START + timedelta(minutes=1),
        **kwargs,
    )


def test_planning_window_is_exactly_seven_days_and_utc() -> None:
    started, target = producer.planning_window(
        datetime(2030, 1, 1, 3, 4, 5, 900000, tzinfo=timezone(timedelta(hours=3)))
    )
    assert started == "2030-01-01T00:04:05Z"
    assert datetime.fromisoformat(target.replace("Z", "+00:00")) - datetime.fromisoformat(
        started.replace("Z", "+00:00")
    ) == timedelta(days=7)


def test_planning_window_rejects_a_future_anchor() -> None:
    with pytest.raises(ValueError, match="PLANNING_START_IN_FUTURE"):
        producer._validate_planning_window(
            "2030-01-02T00:00:00Z",
            "2030-01-09T00:00:00Z",
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    ("repository", "ref", "sha"),
    [
        ("fork/aurora", "refs/heads/main", COMMIT),
        (producer.REPOSITORY, "refs/heads/feature", COMMIT),
        (producer.REPOSITORY, "refs/heads/main", "not-a-commit"),
    ],
)
def test_preflight_rejects_noncanonical_protected_context(repository, ref, sha) -> None:
    with pytest.raises(ValueError, match="PROTECTED_MAIN_REQUIRED|PROTECTED_COMMIT_SHA_INVALID"):
        producer._require_protected_main(repository, ref, sha)


def test_pilot_qualified_worker_ceiling_is_floor_and_rejects_registry_above_it() -> None:
    context = _context()
    assert producer._qualified_worker_ceiling(context) == 20
    context.entry.max_free_workers = 21
    with pytest.raises(ValueError, match="QUALIFIED_WORKER_CEILING_EXCEEDS_PILOT"):
        producer._qualified_worker_ceiling(context)


def test_prepared_bundle_uses_frozen_plan_and_binds_all_required_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_plan(monkeypatch)
    result = _prepare(tmp_path, monkeypatch)
    bundle = tmp_path / "prepared-bundle"

    assert calls["total_shards"] == 360
    assert calls["recipe_count"] == 209906
    assert calls["selection_seed"] == 20260818
    assert (bundle / "atlas_prepared_receipt.json").is_file()
    assert (bundle / "plan/atlas_run_plan.json").is_file()
    assert (bundle / "plan/atlas_campaign_selection.json").is_file()
    assert (bundle / "atlas/manifest.json").is_file()
    assert (bundle / "atlas/recipe_space.json").is_file()
    assert (bundle / "calibration/calibration_receipt.json").is_file()
    receipt = AtlasPreparedReceiptV1.model_validate(
        json.loads((bundle / "atlas_prepared_receipt.json").read_text(encoding="utf-8"))
    )
    assert receipt.status == "PREPARED"
    assert receipt.identity.protected_commit_sha == COMMIT
    assert receipt.identity.campaign_definition_sha256 == "b" * 64
    assert result["preparation_key_sha256"] == receipt.identity.preparation_key_sha256
    assert len(result["preparation_key_sha256"]) == 64
    assert result["artifact_name"] == (
        f"catalog-atlas-prepared-sp500-atlas-v1-{result['preparation_key_sha256']}"
    )
    assert receipt.qualified_worker_ceiling == 20
    assert receipt.plan_sha256 == "3" * 64
    assert receipt.receipt_sha256 == canonical_sha256(
        receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    )


def test_insufficient_capacity_or_other_identity_failure_never_emits_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_plan(monkeypatch)

    def fail_capacity(*args, **kwargs):
        raise ValueError("ATLAS_CLOUD_IDENTITY_CALIBRATION_CAPACITY_INSUFFICIENT")

    monkeypatch.setattr(producer, "verify_atlas_cloud_identity", fail_capacity)
    with pytest.raises(ValueError, match="CALIBRATION_CAPACITY_INSUFFICIENT"):
        _prepare(tmp_path, monkeypatch)
    assert not (tmp_path / "prepared-bundle/atlas_prepared_receipt.json").exists()


def test_cache_may_supply_catalog_but_never_the_current_calibration_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_plan(monkeypatch)
    calibration = _fake_calibration_output(tmp_path)
    (calibration / "atlas/manifest.json").unlink()
    (calibration / "atlas/recipe_space.json").unlink()
    (calibration / "atlas").rmdir()
    previous = tmp_path / "previous-cache"
    (previous / "atlas").mkdir(parents=True)
    (previous / "atlas/manifest.json").write_text('{"cached":true}\n', encoding="utf-8")
    (previous / "atlas/recipe_space.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(producer, "resolve_preparation_context", lambda *_: _context())
    expected_key = producer._build_static_identity(_context(), COMMIT).preparation_key_sha256

    producer.prepare_catalog_atlas_bundle(
        repo_root=tmp_path,
        campaign_key="sp500-atlas-v1",
        protected_commit_sha=COMMIT,
        repository=producer.REPOSITORY,
        ref="refs/heads/main",
        planning_started_at_iso=START_ISO,
        planned_target_end_iso=TARGET_ISO,
        expected_campaign_definition_sha256="b" * 64,
        expected_preparation_key_sha256=expected_key,
        calibration_output_dir=calibration,
        bundle_dir=tmp_path / "prepared-bundle",
        previous_bundle_dir=previous,
        now=START + timedelta(minutes=1),
    )

    output = tmp_path / "prepared-bundle"
    assert json.loads((output / "atlas/manifest.json").read_text(encoding="utf-8")) == {
        "cached": True
    }
    assert (output / "calibration/calibration_receipt.json").read_text(
        encoding="utf-8"
    ) == '{"recommended_mode":"cold"}\n'


def test_workflow_is_call_only_cold_and_publishes_commit_definition_keyed_outputs() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    call = workflow["on"]["workflow_call"]
    assert tuple(workflow["on"]) == ("workflow_call",)
    assert tuple(call["inputs"]) == ("campaign_key",)
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["jobs"]["calibrate"]["uses"] == "./.github/workflows/sp500-atlas-calibration.yml"
    assert workflow["jobs"]["calibrate"]["with"]["catalog_target_end_iso"] == (
        producer.CATALOG_TARGET_END_ISO
    )
    assert workflow["jobs"]["calibrate"]["with"]["cache_mode"] == "cold"
    assert "${{ needs.preflight.outputs.planned_target_end_iso }}" == workflow["jobs"][
        "calibrate"
    ]["with"]["target_end_iso"]
    assert workflow["jobs"]["prepare"]["runs-on"] == "ubuntu-24.04"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "catalog-atlas-prepared-${{ inputs.campaign_key }}-${{ steps.prepare.outputs.preparation_key_sha256 }}" in text
    restore = workflow["jobs"]["prepare"]["steps"]
    cache_restore = next(
        step for step in restore if step.get("uses", "").startswith("actions/cache/restore@")
    )
    cache_save = next(
        step for step in restore if step.get("uses", "").startswith("actions/cache/save@")
    )
    assert cache_restore["with"]["key"] == (
        "aurora-catalog-atlas-prepared-v1-${{ needs.preflight.outputs.preparation_key_sha256 }}-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert cache_restore["with"]["restore-keys"].strip() == (
        "aurora-catalog-atlas-prepared-v1-${{ needs.preflight.outputs.preparation_key_sha256 }}-"
    )
    assert cache_save["with"]["key"] == (
        "aurora-catalog-atlas-prepared-v1-${{ steps.prepare.outputs.preparation_key_sha256 }}-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    preflight_outputs = workflow["jobs"]["preflight"]["outputs"]
    assert preflight_outputs["preparation_key_sha256"] == (
        "${{ steps.preflight.outputs.preparation_key_sha256 }}"
    )
    assert "retention-days: 90" in text
    assert "refs/heads/main" in text
