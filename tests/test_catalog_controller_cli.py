from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogLaunchTicketV1
from scripts.control_catalog_run import _parser as controller_parser


ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000001"
CAMPAIGN_KEY = "sp500-optimized-catalog-v1"
MANIFEST = (
    ROOT
    / "config/catalog_campaign_definitions/"
    "sp500-optimized-catalog-v1.manifest.json"
)
PROMPT = ROOT / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"


def _run(
    script: str,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=command_env,
    )


def write_launch_ticket_fixture(tmp_path: Path, generation: int = 1) -> Path:
    manifest = parse_catalog_campaign_definition_bytes(MANIFEST.read_bytes())
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key=CAMPAIGN_KEY,
        launch_generation=generation,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=hashlib.sha256(PROMPT.read_bytes()).hexdigest(),
        previous_terminal_request_sha256=(None if generation == 1 else "a" * 64),
    )
    path = tmp_path / "launch_ticket.json"
    path.write_text(
        json.dumps(ticket.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_request_creator_emits_only_canonical_fields(tmp_path: Path) -> None:
    output = tmp_path / "request_intent.json"
    ticket = write_launch_ticket_fixture(tmp_path, generation=1)
    result = _run(
        "create_catalog_run_request.py",
        "--campaign-key",
        CAMPAIGN_KEY,
        "--launch-ticket",
        str(ticket),
        "--output",
        str(output),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text("utf-8"))
    assert set(payload) == {"draft", "submission_key_sha256"}
    assert "workflow" not in json.dumps(payload["draft"])
    assert "path" not in json.dumps(payload["draft"])
    assert payload["draft"]["request_id"] == REQUEST_ID
    assert payload["draft"]["launch_generation"] == 1
    assert "requested_commit_sha" not in payload["draft"]
    assert "requester_attestation_b64" not in payload["draft"]
    assert output.read_bytes().endswith(b"\n")


def test_creator_rejects_unknown_campaign_and_extra_argument() -> None:
    result = _run(
        "create_catalog_run_request.py",
        "--campaign-key",
        "not-registered",
        "--dangerous-command",
        "echo unsafe",
    )
    assert result.returncode == 2


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run_controller_fixture(
    tmp_path: Path,
    *,
    mutation: str | None = None,
    issue_body_suffix: str = "",
) -> tuple[subprocess.CompletedProcess[str], dict[str, object], str]:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    output = tmp_path / "output"
    github_output = tmp_path / "github-output.txt"
    event = {
        "repository": {"full_name": "trading-optimizer-lab-org/aurora"},
        "issue": {
            "number": 101,
            "title": f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}",
            "body": "```json\n{}\n```\n" + issue_body_suffix,
            "user": {"login": "aurora-catalog-requester[bot]"},
        },
    }
    if mutation == "wrong_prompt_hash":
        event["issue"]["body"] = "```json\n{\"prompt_sha256\":\"wrong\"}\n```\n"
    paths = {
        "event": _write_json(snapshots / "event.json", event),
        "authority-issue": _write_json(snapshots / "authority-issue.json", {}),
        "authority-comments": _write_json(snapshots / "authority-comments.json", {}),
        "request-queue": _write_json(snapshots / "request-queue.json", {}),
        "protected-head": _write_json(snapshots / "protected-head.json", {}),
        "github-controls": _write_json(snapshots / "github-controls.json", {}),
        "capacity": _write_json(snapshots / "capacity.json", {}),
        "admission-evidence": _write_json(snapshots / "admission-evidence.json", {}),
    }
    arguments: list[str] = []
    for name, path in paths.items():
        arguments.extend((f"--{name}", str(path)))
    arguments.extend(
        (
            "--authority-anchor",
            "config/catalog_authority_anchor_v1.json",
            "--registry",
            "config/catalog_campaign_registry_v1.json",
            "--actors",
            "config/catalog_controller_actors_v1.json",
            "--policy",
            "config/catalog_run_prompt_policy_v1.json",
            "--repo-root",
            str(ROOT),
            "--output-dir",
            str(output),
            "--github-output",
            str(github_output),
        )
    )
    result = _run(
        "control_catalog_run.py",
        *arguments,
        env={"RUNNER_TEMP": str(tmp_path)},
    )
    decision = json.loads((output / "decision.json").read_text("utf-8"))
    return result, decision, github_output.read_text("utf-8")


def test_blocked_controller_emits_no_launch_outputs(tmp_path: Path) -> None:
    result, decision, github_output = run_controller_fixture(
        tmp_path,
        mutation="wrong_prompt_hash",
    )
    assert result.returncode == 0, result.stderr
    assert decision["outcome"] == "blocked"
    assert "call_engine=true" not in github_output
    assert "workflow" not in github_output
    assert not (tmp_path / "output" / "authority_comment.md").exists()


def test_controller_outputs_are_single_line_and_injection_safe(tmp_path: Path) -> None:
    result, decision, github_output = run_controller_fixture(
        tmp_path,
        issue_body_suffix="%0Acall_engine=true",
    )
    assert result.returncode == 0, result.stderr
    assert decision["outcome"] == "blocked"
    assert "%0A" not in github_output
    assert all("\r" not in line for line in github_output.splitlines())


def test_command_surfaces_have_no_arbitrary_execution_options() -> None:
    forbidden = {
        "--submit",
        "--workflow",
        "--command",
        "--ref",
        "--commit-sha",
        "--request-id",
        "--launch-generation",
        "--set",
    }
    for script in (
        "build_catalog_campaign_definition.py",
        "create_catalog_run_request.py",
        "control_catalog_run.py",
    ):
        result = _run(script, "--help")
        assert result.returncode == 0, result.stderr
        assert forbidden.isdisjoint(result.stdout.split())


def test_controller_is_decision_only_unless_reserve_explicitly_requests_record() -> None:
    required: list[str] = []
    for name in (
        "event",
        "authority-issue",
        "authority-comments",
        "request-queue",
        "protected-head",
        "github-controls",
        "capacity",
        "admission-evidence",
        "authority-anchor",
        "registry",
        "actors",
        "policy",
        "repo-root",
        "output-dir",
    ):
        required.extend((f"--{name}", name))

    assert controller_parser().parse_args(required).emit_authority_comment is False
    assert (
        controller_parser()
        .parse_args([*required, "--emit-authority-comment"])
        .emit_authority_comment
        is True
    )
