from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _payload() -> dict[str, object]:
    return {
        "request_sha256": "1" * 64,
        "authority_id": "018f47a2-6e91-7c34-8000-000000000101",
        "campaign_id": "2" * 64,
        "science_sha256": "3" * 64,
        "execution_plan_sha256": "4" * 64,
        "execution_protocol_sha256": "5" * 64,
        "protected_commit_sha": "6" * 40,
        "engine_run_id": 1234,
        "engine_run_attempt": 1,
        "stage_results": {
            "engine_verify_sealed_plan": "success",
            "reduce": "success",
            "verify_terminal_science": "success",
            "audit_runtime": "success",
        },
        "recovery_statuses": ["complete"],
        "final_evidence_artifact": "catalog-final-root",
        "runtime_audit_artifact": "catalog-runtime-audit",
        "science_evidence_artifact": "catalog-terminal-science",
        "recovery_evidence_artifact": "catalog-recovery-evidence",
        "failure_fingerprint": None,
        "failure_occurrence_count": 0,
        "failure_reason_code": None,
        "retry_not_before": None,
        "terminal_failure_code": None,
        "created_at": datetime(2026, 8, 22, 10, 0, tzinfo=UTC).isoformat(),
    }


def test_cli_writes_one_hashed_outcome_and_safe_outputs(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    target = tmp_path / "outcome.json"
    github_output = tmp_path / "github-output.txt"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_catalog_engine_outcome.py"),
            "--input",
            str(source),
            "--output",
            str(target),
            "--github-output",
            str(github_output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(target.read_text("utf-8"))
    assert payload["state"] == "TERMINAL_CANDIDATE"
    outputs = dict(
        line.split("=", 1)
        for line in github_output.read_text("utf-8").splitlines()
    )
    assert outputs["campaign_state"] == "TERMINAL_CANDIDATE"
    assert outputs["outcome_evidence_sha256"] == payload["evidence_sha256"]


def test_cli_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text('{"request_sha256":"a","request_sha256":"b"}', "utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_catalog_engine_outcome.py"),
            "--input",
            str(source),
            "--output",
            str(tmp_path / "out.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "CATALOG_ENGINE_OUTCOME_INPUT_INVALID" in result.stderr
