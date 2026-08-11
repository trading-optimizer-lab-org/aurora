from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_PATH = ROOT / "config" / "sp500_megarun_dehb_campaign_v1.json"


@pytest.mark.parametrize(
    "script_name",
    [
        "build_sp500_megarun_dehb_launch_contract.py",
        "plan_sp500_megarun_dehb_campaign.py",
    ],
)
def test_controller_scripts_bootstrap_without_numpy(script_name: str) -> None:
    script = ROOT / "scripts" / script_name
    probe = f"""
import builtins
import os
import runpy
import sys

original_import = builtins.__import__

def import_without_numpy(name, *args, **kwargs):
    if name == "numpy" or name.startswith("numpy."):
        raise ModuleNotFoundError("numpy deliberately unavailable")
    return original_import(name, *args, **kwargs)

builtins.__import__ = import_without_numpy
os.environ["GITHUB_ACTIONS"] = "true"
sys.argv = [{str(script)!r}, "--help"]
runpy.run_path({str(script)!r}, run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_campaign_binding_validation_bootstraps_without_numeric_dependencies() -> None:
    probe = f"""
import builtins
from pathlib import Path

original_import = builtins.__import__

def import_without_numeric_dependencies(name, *args, **kwargs):
    if name in {{"numpy", "pandas"}} or name.startswith(("numpy.", "pandas.")):
        raise ModuleNotFoundError(f"{{name}} deliberately unavailable")
    return original_import(name, *args, **kwargs)

builtins.__import__ = import_without_numeric_dependencies

from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
    validate_campaign_bindings,
)

root = Path({str(ROOT)!r})
contract = load_and_validate_campaign_contract(
    root / "config" / "sp500_megarun_dehb_campaign_v1.json"
)
receipt = validate_campaign_bindings(contract, repo_root=root)
assert receipt["verified"] is True
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _fixtures(tmp_path: Path):
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )
    from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
        scientific_input_binding_sha256,
    )

    campaign = load_and_validate_campaign_contract(CAMPAIGN_PATH)
    runtime_pack = tmp_path / "runtime"
    runtime_pack.mkdir()
    runtime_manifest = {
        "schema_version": 1,
        "scientific_input_binding_sha256": scientific_input_binding_sha256(campaign),
        "source_run_id": campaign.train_source_run_id,
        "baseline_run_id": "31418682679",
        "train_artifact_digest_sha256": campaign.train_artifact_digest_sha256,
        "train_snapshot_manifest_sha256": campaign.train_snapshot_manifest_sha256,
        "train_spy_sha256": campaign.train_spy_sha256,
        "file_count": 0,
        "total_bytes": 0,
        "aggregate_sha256": hashlib.sha256(b"[]").hexdigest(),
        "files": [],
        "validation_opened": False,
        "locked_opened": False,
    }
    (runtime_pack / "runtime_input_manifest.json").write_text(
        json.dumps(runtime_manifest), encoding="utf-8"
    )
    code_sha = "a" * 40
    technical = {
        "schema_version": 1,
        "campaign_contract_sha256": campaign.sha256,
        "github_sha": code_sha,
        "official_smoke_report_sha256": "1" * 64,
        "official_smoke": {
            "official_dehb_version": "0.1.2",
            "configspace_version": "1.2.2",
            "worker_equivalence_1_2_4": True,
            "checkpoint_resume_exact": True,
            "actual_four_worker_run": True,
        },
        "fault_injection": {
            "controller_retries_missing_jobs": True,
            "tampered_job_payload_rejected": True,
            "tampered_checkpoint_rejected": True,
        },
        "gates": {
            gate: {"status": "PASS", "evidence": "fixture"}
            for gate in ("55", "56", "60")
        },
        "validation_opened": False,
        "locked_opened": False,
    }
    technical["technical_evidence_sha256"] = _canonical_hash(technical)
    technical_path = tmp_path / "technical_evidence.json"
    technical_path.write_text(json.dumps(technical), encoding="utf-8")
    return campaign, runtime_pack, technical_path, code_sha


def test_launch_contract_binds_exact_code_artifacts_and_closed_tiers(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_launch_contract import (
        build_launch_contract,
        load_and_validate_launch_contract,
    )

    campaign, runtime_pack, technical_path, code_sha = _fixtures(tmp_path)
    target = tmp_path / "launch_contract.json"
    built = build_launch_contract(
        campaign,
        code_commit_sha=code_sha,
        repository="trading-optimizer-lab-org/aurora",
        runtime_input_pack=runtime_pack,
        runtime_input_run_id="31418682679",
        runtime_input_artifact_name=(
            "sp500-megarun-dehb-runtime-inputs-31418682679"
        ),
        runtime_input_artifact_digest_sha256="b" * 64,
        technical_evidence_path=technical_path,
        technical_evidence_run_id="31420960581",
        technical_evidence_artifact_name=(
            "sp500-megarun-official-dehb-smoke-31420960581"
        ),
        technical_evidence_artifact_digest_sha256="c" * 64,
        output_path=target,
    )
    loaded = load_and_validate_launch_contract(
        target,
        campaign,
        runtime_input_pack=runtime_pack,
        technical_evidence_path=technical_path,
        expected_code_commit_sha=code_sha,
    )

    assert loaded.sha256 == built.sha256
    assert loaded.campaign_contract_sha256 == campaign.sha256
    assert loaded.code_commit_sha == code_sha
    assert loaded.runtime_input_aggregate_sha256 == hashlib.sha256(b"[]").hexdigest()
    assert loaded.runtime_input_run_id == "31418682679"
    assert loaded.technical_evidence_run_id == "31420960581"
    assert loaded.validation_opened is False
    assert loaded.locked_opened is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["boundaries"].update(validation_opened=True), "LAUNCH_BOUNDARY_OPEN"),
        (lambda value: value["runtime_inputs"].update(aggregate_sha256="0" * 64), "LAUNCH_CONTRACT_SHA256_MISMATCH"),
        (lambda value: value.update(code_commit_sha="f" * 40), "LAUNCH_CONTRACT_SHA256_MISMATCH"),
    ],
)
def test_launch_contract_rejects_tampering(tmp_path: Path, mutation, message: str) -> None:
    from aurora.infra.sp500_megarun.dehb_launch_contract import (
        LaunchContractError,
        build_launch_contract,
        load_and_validate_launch_contract,
    )

    campaign, runtime_pack, technical_path, code_sha = _fixtures(tmp_path)
    target = tmp_path / "launch_contract.json"
    build_launch_contract(
        campaign,
        code_commit_sha=code_sha,
        repository="trading-optimizer-lab-org/aurora",
        runtime_input_pack=runtime_pack,
        runtime_input_run_id="31418682679",
        runtime_input_artifact_name="sp500-megarun-dehb-runtime-inputs-31418682679",
        runtime_input_artifact_digest_sha256="b" * 64,
        technical_evidence_path=technical_path,
        technical_evidence_run_id="31420960581",
        technical_evidence_artifact_name="sp500-megarun-official-dehb-smoke-31420960581",
        technical_evidence_artifact_digest_sha256="c" * 64,
        output_path=target,
    )
    value = json.loads(target.read_text("utf-8"))
    mutation(value)
    target.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(LaunchContractError, match=message):
        load_and_validate_launch_contract(target, campaign)


def test_launch_contract_rejects_technical_evidence_from_different_commit(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_launch_contract import (
        LaunchContractError,
        build_launch_contract,
    )

    campaign, runtime_pack, technical_path, code_sha = _fixtures(tmp_path)
    with pytest.raises(LaunchContractError, match="TECHNICAL_EVIDENCE_CODE_MISMATCH"):
        build_launch_contract(
            campaign,
            code_commit_sha="f" * 40,
            repository="trading-optimizer-lab-org/aurora",
            runtime_input_pack=runtime_pack,
            runtime_input_run_id="31418682679",
            runtime_input_artifact_name="sp500-megarun-dehb-runtime-inputs-31418682679",
            runtime_input_artifact_digest_sha256="b" * 64,
            technical_evidence_path=technical_path,
            technical_evidence_run_id="31420960581",
            technical_evidence_artifact_name="sp500-megarun-official-dehb-smoke-31420960581",
            technical_evidence_artifact_digest_sha256="c" * 64,
            output_path=tmp_path / "launch_contract.json",
        )
