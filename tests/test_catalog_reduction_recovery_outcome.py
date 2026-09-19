from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _local_script_command(script: Path, *arguments: str) -> list[str]:
    bootstrap = """
import importlib.util
import runpy
import sys
from pathlib import Path

script = Path(sys.argv[1]).resolve()
root = script.parents[1]
try:
    import __editable___aurora_1_5_0_finder as editable_finder
    editable_finder.MAPPING["aurora"] = str(root)
except ImportError:
    pass
spec = importlib.util.spec_from_file_location(
    "aurora", root / "__init__.py", submodule_search_locations=[str(root)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["aurora"] = module
assert spec.loader is not None
spec.loader.exec_module(module)
sys.meta_path[:] = [
    finder for finder in sys.meta_path
    if not finder.__class__.__module__.startswith("__editable___")
]
sys.argv = [str(script), *sys.argv[2:]]
runpy.run_path(str(script), run_name="__main__")
"""
    return [sys.executable, "-c", bootstrap, str(script), *arguments]


def _payload(**updates: object) -> dict[str, object]:
    stages = {
        "engine_verify_sealed_plan": "success",
        "prepare_runtime_and_inputs": "success",
        "publish_sealed_payload_artifacts": "skipped",
        "build_components_a": "skipped",
        "build_components_b": "skipped",
        "materialize_cached_components_a": "skipped",
        "materialize_cached_components_b": "skipped",
        "verify_component_store": "skipped",
        "evaluate_a": "skipped",
        "evaluate_b": "skipped",
        "evaluate_c": "skipped",
        "reconcile_wave_0": "skipped",
        "recovery_wave_1": "skipped",
        "recovery_wave_2": "skipped",
        "recovery_wave_3": "skipped",
        "ready_to_merge": "skipped",
        "reduce_groups": "skipped",
        "reduce": "success",
        "verify_terminal_science": "success",
        "audit_runtime": "success",
    }
    payload: dict[str, object] = {
        "request_sha256": "1" * 64,
        "authority_id": "018f47a2-6e91-7c34-8000-000000000101",
        "campaign_id": "2" * 64,
        "science_sha256": "3" * 64,
        "execution_plan_sha256": "4" * 64,
        "execution_protocol_sha256": "5" * 64,
        "protected_commit_sha": "6" * 40,
        "engine_run_id": 1234,
        "engine_run_attempt": 1,
        "stage_results": stages,
        "recovery_statuses": [],
        "final_evidence_artifact": "catalog-final-root",
        "runtime_audit_artifact": "catalog-runtime-audit",
        "science_evidence_artifact": "catalog-terminal-science",
        "recovery_evidence_artifact": None,
        "failure_fingerprint": None,
        "failure_occurrence_count": 0,
        "failure_reason_code": None,
        "retry_not_before": None,
        "terminal_failure_code": None,
        "created_at": datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc).isoformat(),
        "reduction_only": True,
        "recovery_verified": True,
    }
    payload.update(updates)
    return payload


def _run(tmp_path: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "input.json"
    target = tmp_path / "outcome.json"
    output = tmp_path / "github-output.txt"
    source.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        _local_script_command(
            ROOT / "scripts/prepare_catalog_engine_outcome.py",
            "--input",
            str(source),
            "--output",
            str(target),
            "--github-output",
            str(output),
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_accepts_verified_reduction_only_terminal_outcome(tmp_path: Path) -> None:
    result = _run(tmp_path, _payload())
    assert result.returncode == 0, result.stderr
    output = dict(
        line.split("=", 1)
        for line in (tmp_path / "github-output.txt").read_text(encoding="utf-8").splitlines()
    )
    assert output["campaign_state"] == "TERMINAL_CANDIDATE"
    assert output["reduction_only"] == "true"
    assert output["recovery_verified"] == "true"


def test_cli_rejects_reduction_only_without_sealed_recovery_verification(tmp_path: Path) -> None:
    result = _run(tmp_path, _payload(recovery_verified=False))
    assert result.returncode == 2
    assert "CATALOG_ENGINE_OUTCOME_INPUT_INVALID" in result.stderr
    assert not (tmp_path / "outcome.json").exists()


def test_cli_classifies_reduction_failure_without_turning_it_into_input_invalid(
    tmp_path: Path,
) -> None:
    base_stages = _payload()["stage_results"]
    assert isinstance(base_stages, dict)
    result = _run(
        tmp_path,
        _payload(
            stage_results={**base_stages, "reduce": "failure"}
        ),
    )
    assert result.returncode == 0, result.stderr
    outcome = json.loads((tmp_path / "outcome.json").read_text(encoding="utf-8"))
    assert outcome["state"] == "BLOCKED"
    assert outcome["reason_code"] == "CATALOG_REDUCTION_FAILED"
