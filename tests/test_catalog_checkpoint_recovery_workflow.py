from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/catalog-optimized-run.yml"


@pytest.mark.parametrize("defect", [None, "physical", "duplicate", "receipt", "real_source"])
def test_local_seed_calls_source_validator_with_protected_bindings(tmp_path, monkeypatch, defect):
    from dataclasses import asdict
    import scripts.restore_catalog_checkpoint_recovery as cli
    from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1

    profile = cli.load_checkpoint_recovery_profile(ROOT, cli.CHECKPOINT_RECOVERY_CAMPAIGN_KEY, 8)
    assert profile is not None
    proof = CheckpointRecoveryOwnerProofV1(
        profile_sha256=profile.profile_sha256, campaign_key=profile.campaign_key,
        target_generation=profile.target_generation, source_request_sha256=profile.source_request_sha256,
        source_issue_number=profile.source_issue_number, source_run_id=profile.source_run_id,
        source_run_attempt=profile.source_run_attempt,
        source_protected_commit_sha=profile.source_protected_commit_sha,
        source_decision_sha256=profile.source_plan_bindings["decision_sha256"], source_finalizer_job_id=1,
    )
    plan = tmp_path / "checkpoint-recovery/source-plan"
    checkpoints = tmp_path / "checkpoint-recovery/checkpoints"
    plan.mkdir(parents=True)
    checkpoints.mkdir()
    template = tmp_path / "templates/workers-030"
    ids = tuple(f"id-{i}" for i in range(profile.expected_result_count))
    document = dict(schema_version="1", profile=profile.model_dump(mode="json"),
                    owner_proof=asdict(proof), binding=cli.build_checkpoint_recovery_binding(profile, proof),
                    source_plan_relative="source-plan", checkpoint_relative="checkpoints",
                    source_plan_receipt_sha256=profile.source_plan_receipt_sha256,
                    cached_strategy_ids_sha256=profile.cached_strategy_ids_sha256)
    def verify_template(p, actual, owner):
        assert (p, actual, owner) == (template, profile, proof)
    monkeypatch.setattr(cli, "verify_checkpoint_recovery_plan", verify_template)
    def derive(path, actual):
        assert path == plan and actual == profile
        return ids
    monkeypatch.setattr(cli, "_derive_expected_pending_ids", derive)
    real_validator = cli.verify_checkpoint_recovery_source
    calls = []
    def verify(*args):
        assert args == (plan, checkpoints, dict(profile.source_plan_bindings),
                        profile.science_sha256, profile.catalog_manifest_sha256, ids, profile.worker_ids)
        calls.append(args)
        if defect == "real_source":
            return real_validator(*args)
        return SimpleNamespace(
            plan_receipt_sha256="0" * 64 if defect == "receipt" else profile.source_plan_receipt_sha256,
            checkpoint_count=120, resume_index_sha256="e" * 64,
            resume_index=SimpleNamespace(strategy_ids=ids,
                physical_result_count=0 if defect == "physical" else profile.expected_result_count,
                duplicate_result_count=1 if defect == "duplicate" else 0))
    monkeypatch.setattr(cli, "verify_checkpoint_recovery_source", verify)
    if defect:
        with pytest.raises((ValueError, OSError)):
            cli._load_checkpoint_recovery_seed(ROOT, tmp_path, profile.campaign_key,
                {"checkpoint_recovery": document}, sealed_plan=template)
    else:
        state = cli._load_checkpoint_recovery_seed(ROOT, tmp_path, profile.campaign_key,
            {"checkpoint_recovery": document}, sealed_plan=template)
        assert state["proof"] == proof
    assert len(calls) == 1


def _workflow() -> dict:
    return load_github_yaml(WORKFLOW)


def _step(job: dict, *, name: str | None = None, step_id: str | None = None) -> dict:
    matches = [
        step
        for step in job["steps"]
        if (name is None or step.get("name") == name)
        and (step_id is None or step.get("id") == step_id)
    ]
    assert len(matches) == 1
    return matches[0]


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _checkpoint_binding() -> dict[str, object]:
    return {
        "schema_version": "1",
        "profile_sha256": "a" * 64,
        "owner_proof_sha256": "b" * 64,
        "source_plan_receipt_sha256": "c" * 64,
        "science_sha256": "d" * 64,
        "catalog_manifest_sha256": "e" * 64,
        "cached_strategy_ids_sha256": "f" * 64,
        "cached_recipe_count": 18630,
        "total_recipe_count": 37258,
    }


def _controller(binding: dict[str, object] | None) -> dict[str, object]:
    envelope: dict[str, object] = {}
    if binding is not None:
        envelope["checkpoint_recovery"] = binding
    controller: dict[str, object] = {"binding": envelope}
    controller["content_sha256"] = _canonical_sha256(controller)
    return controller


def _checkpoint_gate_script() -> str:
    step = _step(_workflow()["jobs"]["engine_verify_sealed_plan"], step_id="checkpoint_recovery")
    marker = "python -S - <<'PY'\n"
    body = step["run"].split(marker, 1)[1].rsplit("\nPY", 1)[0]
    return textwrap.dedent(body)


def _run_checkpoint_gate(
    tmp_path: Path,
    binding: dict[str, object] | None,
    *,
    legacy_reduction_only: str = "false",
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    sealed_plan = tmp_path / "sealed-plan"
    sealed_plan.mkdir(parents=True)
    (sealed_plan / "controller_binding.json").write_text(
        json.dumps(_controller(binding)), encoding="utf-8"
    )
    (sealed_plan / "run_plan.json").write_text(
        json.dumps({"cached_recipe_count": binding["cached_recipe_count"] if binding else 0}),
        encoding="utf-8",
    )
    output = tmp_path / "github-output"
    environment = os.environ.copy()
    environment.update(
        {
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "LEGACY_REDUCTION_ONLY": legacy_reduction_only,
        }
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", _checkpoint_gate_script()],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    values = {}
    if output.exists():
        values = dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    return result, values


def test_checkpoint_recovery_is_absent_by_default(tmp_path: Path) -> None:
    result, outputs = _run_checkpoint_gate(tmp_path, None)

    assert result.returncode == 0, result.stderr
    assert outputs == {"enabled": "false"}


def test_checkpoint_recovery_binding_is_opt_in_and_shape_checked(tmp_path: Path) -> None:
    result, outputs = _run_checkpoint_gate(tmp_path, _checkpoint_binding())

    assert result.returncode == 0, result.stderr
    assert outputs == {"enabled": "true"}

    malformed = _checkpoint_binding()
    malformed["unexpected"] = "field"
    result, outputs = _run_checkpoint_gate(tmp_path / "malformed", malformed)
    assert result.returncode != 0
    assert "CATALOG_CHECKPOINT_RECOVERY_BINDING_INVALID" in result.stderr
    assert outputs == {}


def test_checkpoint_recovery_cannot_coexist_with_legacy_reduction_only(
    tmp_path: Path,
) -> None:
    result, outputs = _run_checkpoint_gate(
        tmp_path,
        _checkpoint_binding(),
        legacy_reduction_only="true",
    )

    assert result.returncode != 0
    assert "CATALOG_CHECKPOINT_RECOVERY_ROUTES_CONFLICT" in result.stderr
    assert outputs == {}


def test_workflow_preserves_legacy_route_and_opt_in_uses_normal_resume_root() -> None:
    document = _workflow()
    engine = document["jobs"]["engine_verify_sealed_plan"]
    reduce = document["jobs"]["reduce"]
    outputs = engine["outputs"]
    assert outputs["reduction_only"] == "${{ steps.recovery.outputs.reduction_only }}"
    assert outputs["recovery_verified"] == "${{ steps.recovery.outputs.recovery_verified }}"
    assert outputs["checkpoint_recovery_enabled"] == "${{ steps.checkpoint_recovery.outputs.enabled }}"

    legacy = _step(engine, name="Verify optional sealed reduction-recovery profile")
    assert legacy["id"] == "recovery"
    legacy_code = legacy["run"].split("python -S - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    compile(legacy_code, "legacy-reduction-recovery", "exec")
    assert "reduction_only" in legacy["run"]
    assert "recovery_verified" in legacy["run"]
    assert "config/catalog_reduction_recovery_profiles_v1.json" in legacy["run"]

    gate = _step(engine, step_id="checkpoint_recovery")
    assert "steps.recovery.outputs.reduction_only" in gate["env"]["LEGACY_REDUCTION_ONLY"]
    assert "CATALOG_CHECKPOINT_RECOVERY_ROUTES_CONFLICT" in gate["run"]

    reduce_steps = reduce["steps"]
    restore_index = next(
        index for index, step in enumerate(reduce_steps)
        if step.get("id") == "checkpoint_restore"
    )
    runtime_index = next(
        index for index, step in enumerate(reduce_steps)
        if step.get("name") == "Activate sealed offline runtime"
    )
    legacy_restore = _step(reduce, name="Restore sealed reduction-only source")
    checkpoint_restore = _step(reduce, step_id="checkpoint_restore")
    assert runtime_index < restore_index
    assert checkpoint_restore["if"] == (
        "${{ needs.engine_verify_sealed_plan.outputs.checkpoint_recovery_enabled == 'true' }}"
    )
    assert "scripts/restore_catalog_checkpoint_recovery.py" in checkpoint_restore["run"]
    assert "--sealed-plan" in checkpoint_restore["run"]
    assert "GITHUB_REPOSITORY" in checkpoint_restore["env"]
    assert "--recovery-source-root" not in checkpoint_restore["run"]
    assert legacy_restore["if"] == (
        "${{ needs.engine_verify_sealed_plan.outputs.reduction_only == 'true' }}"
    )
    assert "scripts/restore_catalog_reduction_recovery.py" in legacy_restore["run"]
    assert "--recovery-source-root" not in legacy_restore["run"]

    merge = _step(reduce, name="Merge the sealed bounded reduction groups")
    merge_run = merge["run"]
    assert "recovery_args=()" in merge_run
    assert "--recovery-source-root \"$RUNNER_TEMP/reduction-recovery\"" in merge_run
    assert "resume_args=()" in merge_run
    assert "--resume-root \"${{ steps.checkpoint_restore.outputs.checkpoint_root }}\"" in merge_run
    assert "${resume_args[@]}" in merge_run
    assert "reduction_only != 'true'" in str(reduce["if"])


def test_full_prepared_transport_is_same_run_and_opt_in() -> None:
    gate = load_github_yaml(ROOT / ".github/workflows/catalog-fast-controller.yml")["jobs"]["gate"]
    upload = _step(gate, name="Publish authenticated checkpoint recovery PREPARED bundle")
    assert "launch_required == 'true'" in upload["if"]
    assert "checkpoint_recovery_enabled == 'true'" in upload["if"]
    assert upload["uses"] == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert upload["with"]["compression-level"] == 6
    assert upload["with"]["path"] == "${{ runner.temp }}/prepared-bundle"
    reduce = _workflow()["jobs"]["reduce"]
    download = _step(reduce, name="Download authenticated checkpoint recovery PREPARED bundle")
    assert download["if"] == "${{ needs.engine_verify_sealed_plan.outputs.checkpoint_recovery_enabled == 'true' }}"
    assert download["uses"] == "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
    assert download["with"]["name"] == "catalog-checkpoint-recovery-prepared-${{ inputs.authority_id }}"
    assert "run-id" not in download["with"]
    restore = _step(reduce, step_id="checkpoint_restore")
    assert "GH_TOKEN" not in restore["env"]
    assert "--prepared-bundle" in restore["run"]
    assert "--output-dir" not in restore["run"]


@pytest.mark.parametrize("defect", [
    None, "tamper", "foreignmanifest", "receipt", "identity", "absentprofile",
    "missinganchor", "currentplan", "source", "commit", "science",
])
def test_restore_cli_requires_bound_local_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], defect: str | None,
) -> None:
    import scripts.restore_catalog_checkpoint_recovery as cli
    from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
        write_prepared_catalog_bundle_manifest,
    )
    from aurora.infra.sp500_megarun.catalog_fast_path import (
        CatalogPreparationIdentityV1, CatalogPreparedReceiptV1,
    )
    from datetime import datetime, timezone

    sealed = tmp_path / "sealed-plan"
    sealed.mkdir()
    science = {"catalog_manifest_sha256": "4" * 64,
               "validation_opened": False, "locked_opened": False}
    (sealed / "resolved_contract.json").write_text(json.dumps({"science": science}))
    bundle = tmp_path / "bundle"
    (bundle / "evidence").mkdir(parents=True)
    (bundle / "checkpoint-recovery/checkpoints").mkdir(parents=True)
    (bundle / "checkpoint-recovery/source-plan").mkdir()
    identity = CatalogPreparationIdentityV1(
        schema_version="1", engine_id="optimized_catalog_v1",
        campaign_key="sp500-optimized-catalog-v1",
        campaign_definition_sha256="1" * 64,
        scientific_contract_sha256="2" * 64,
        optimization_policy_sha256="3" * 64,
        data_contract_sha256="3" * 64, feature_contract_sha256="3" * 64,
        selected_config_sha256="3" * 64,
        catalog_manifest_sha256="4" * 64,
        protected_commit_sha="d" * 40,
        dependency_lock_sha256="5" * 64,
    )
    receipt = CatalogPreparedReceiptV1.create(
        identity=identity, generated_at=datetime.now(timezone.utc),
        runtime_identity_sha256="6" * 64, prepared_input_identity_sha256="7" * 64,
        component_store_manifest_sha256="8" * 64,
        execution_plan_template_sha256="9" * 64,
        required_cache_keys=("test-cache",), logical_recipe_count=37258,
        unique_component_count=1, qualified_worker_ceiling=30,
        production_dependency_smoke_passed=True, recipe_worker_build_allowed=False,
    )
    (bundle / "prepared-receipt.json").write_text(receipt.model_dump_json())
    (bundle / "evidence/preparation-seed.json").write_text('{"checkpoint_recovery": {}}')
    data = bundle / "checkpoint-recovery/checkpoints/data"
    data.write_bytes(b"verified checkpoint bytes")
    manifest = write_prepared_catalog_bundle_manifest(bundle_dir=bundle, prepared_receipt=receipt)
    binding = {
        "checkpoint_recovery": _checkpoint_binding(),
        "checkpoint_recovery_prepared_bundle_manifest_sha256": manifest.manifest_sha256,
        "prepared_receipt_sha256": receipt.receipt_sha256,
    }
    if defect == "foreignmanifest":
        binding["checkpoint_recovery_prepared_bundle_manifest_sha256"] = "0" * 64
    if defect == "missinganchor":
        del binding["checkpoint_recovery_prepared_bundle_manifest_sha256"]
    if defect == "receipt":
        binding["prepared_receipt_sha256"] = "0" * 64
    (sealed / "controller_binding.json").write_text(json.dumps({"binding": binding}))
    if defect == "tamper":
        data.write_bytes(b"tampered")
    profile = SimpleNamespace(
        profile_sha256="a" * 64,
        science_sha256="0" * 64 if defect == "science" else _canonical_sha256(science),
        catalog_manifest_sha256="4" * 64, cached_strategy_ids_sha256="f" * 64,
        expected_result_count=18630, expected_total_count=37258,
    )
    proof = SimpleNamespace(evidence_sha256="b" * 64)
    state = dict(profile=profile, proof=proof, checkpoint_relative="checkpoints",
                 source_plan_relative="source-plan", source_plan_receipt_sha256="c" * 64,
                 resume_index_sha256="e" * 64)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", cli.REPOSITORY)
    monkeypatch.setenv("CATALOG_PROTECTED_COMMIT_SHA", "d" * 40)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout=("c" if defect == "commit" else "d") * 40))
    monkeypatch.setattr(cli, "load_checkpoint_recovery_profile",
                        lambda *a: None if defect == "absentprofile" else profile)
    monkeypatch.setattr(cli, "load_catalog_campaign_registry", lambda *a: object())
    monkeypatch.setattr(cli, "resolve_catalog_campaign", lambda *a: object())
    expected = identity.model_copy(update={"protected_commit_sha": "c" * 40}) if defect == "identity" else identity
    monkeypatch.setattr(cli, "build_catalog_preparation_identity", lambda **k: expected)
    events = []

    def verify_sealed(path, **kwargs):
        assert path == sealed
        assert kwargs["expected_bindings"] == {"protected_commit_sha": "d" * 40}
        events.append("sealed")
    monkeypatch.setattr(cli, "verify_sealed_global_reuse_execution_plan", verify_sealed)

    def source(root, seed, campaign, context, *, sealed_plan):
        assert seed == bundle
        assert sealed_plan == bundle / "templates/workers-030"
        assert campaign == "sp500-optimized-catalog-v1"
        assert "checkpoint_recovery" in context
        events.append("source")
        if defect == "source":
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_INVALID")
        return state
    monkeypatch.setattr(cli, "_load_checkpoint_recovery_seed", source)

    def verify_current(path, actual_profile, actual_proof):
        assert (path, actual_profile, actual_proof) == (sealed, profile, proof)
        events.append("current")
        if defect == "currentplan":
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_BINDING_INVALID")
    monkeypatch.setattr(cli, "verify_checkpoint_recovery_plan", verify_current)
    validate_science = cli._validate_contract_science

    def verify_science(*args, **kwargs):
        events.append("science")
        return validate_science(*args, **kwargs)
    monkeypatch.setattr(cli, "_validate_contract_science", verify_science)
    code = cli.main(["--sealed-plan", str(sealed), "--prepared-bundle", str(bundle)])
    output = capsys.readouterr()
    if defect:
        assert code == 1, output
        assert not output.out
        assert "CATALOG_" in output.err
        if defect in {"tamper", "foreignmanifest", "receipt", "identity", "absentprofile", "missinganchor", "commit"}:
            assert "source" not in events
    else:
        assert code == 0, output.err
        assert events == ["sealed", "source", "current", "science"]
        payload = json.loads(output.out)
        assert payload["checkpoint_root"] == str(bundle / "checkpoint-recovery/checkpoints")
        assert payload["owner_proof_sha256"] == proof.evidence_sha256
        assert payload["cached_recipe_count"] == 18630
