from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from aurora.cli import cmd_github
from aurora.cli.forge import build_parser
from aurora.infra.github_performance.campaign import (
    CampaignPhase,
    initialize_campaign_state,
    load_latest_campaign_state,
    transition_campaign_state,
    write_campaign_state,
)
from github_performance_helpers import minimal_valid_spec, write_yaml


def test_validate_parser_binds_expected_command() -> None:
    args = build_parser().parse_args(
        ["github", "validate", "--spec", "x.yaml"]
    )
    assert args.func is cmd_github.cmd_github_validate


def test_run_shard_parser_can_defer_recorded_failure_to_recovery() -> None:
    args = build_parser().parse_args(
        [
            "github",
            "run-shard",
            "--spec",
            "spec.json",
            "--workload",
            "aurora.example:WORKLOAD",
            "--shard",
            "shard.json",
            "--output-dir",
            "out",
            "--attempt-id",
            "attempt",
            "--artifact-name",
            "artifact",
            "--defer-technical-failure-to-recovery",
        ]
    )

    assert args.func is cmd_github.cmd_github_run_shard
    assert args.defer_technical_failure_to_recovery is True


def test_environment_identity_ignores_cache_hit_but_detects_tampering(
    tmp_path: Path,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": "1",
        "cache": {"key": "exact", "hit": False},
        "installed_wheel_sha256": "a" * 64,
    }
    identity = json.loads(json.dumps(payload))
    identity["cache"].pop("hit")
    digest = hashlib.sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    payload["environment_sha256"] = digest
    path = tmp_path / "environment_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cmd_github._verified_environment_sha256(path) == digest
    assert (
        cmd_github._runtime_value(path, "dependency_lock_sha256")
        == "a" * 64
    )
    payload["cache"]["hit"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cmd_github._verified_environment_sha256(path) == digest
    payload["cache"]["key"] = "different"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="identity hash mismatch"):
        cmd_github._verified_environment_sha256(path)


def test_environment_identity_v2_separates_observations_from_identity(
    tmp_path: Path,
) -> None:
    identity = {
        "schema_version": "2",
        "dependency_lock_sha256": "a" * 64,
        "installed_wheelhouse_sha256": "b" * 64,
        "installed_packages": [{"name": "aurora", "version": "1.5.0"}],
    }
    digest = hashlib.sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": "2",
        "identity": identity,
        "observations": {
            "image_version": "one",
            "setup_seconds": 5.0,
        },
        "environment_sha256": digest,
    }
    path = tmp_path / "environment_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cmd_github._verified_environment_sha256(path) == digest
    assert (
        cmd_github._runtime_value(path, "dependency_lock_sha256")
        == "a" * 64
    )

    payload["observations"]["image_version"] = "two"
    payload["observations"]["setup_seconds"] = 9.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cmd_github._verified_environment_sha256(path) == digest

    payload["identity"]["dependency_lock_sha256"] = "c" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="identity hash mismatch"):
        cmd_github._verified_environment_sha256(path)


def test_phase_commands_are_registered() -> None:
    parser = build_parser()
    commands = (
        ("prepare", "--spec x --workload aurora.x:W --output-dir out"),
        (
            "freeze-contract",
            "--spec x --prepared p --environment-manifest e "
            "--workflow w --metric-contract m --capacity-profile c "
            "--code-sha a --output-dir out",
        ),
        ("smoke", "--spec x --workload aurora.x:W --prepared p --output o"),
        ("pilot", "--spec x --workload aurora.x:W --prepared p --output o"),
        (
            "resolve-pilot",
            "--spec x --workload aurora.x:W --prepared p --contract c "
            "--output o --resolution-output r",
        ),
        (
            "build-performance-profile",
            "--contract c --pilot p --environment-setup-benchmark e "
            "--source-run-id 1 --output o",
        ),
        (
            "merge-group",
            "--spec s --workload aurora.x:W --shard-plan p --merge-group g "
            "--inputs-root i --output-dir o",
        ),
        (
            "final-merge",
            "--spec x --workload aurora.x:W --partials-root p "
            "--plan-root r --contract-root c --output-dir o",
        ),
        (
            "seal-final-artifact",
            "--spec x --root o",
        ),
        (
            "guardrail-check",
            "--spec x --projected-wall-seconds 10 "
            "--projected-billable-minutes 20 --output-dir o",
        ),
        (
            "campaign-update",
            "--spec x --state-root s --phase executing",
        ),
        (
            "recovery-loop",
            "--spec x --shard-plan p --state-root s --output-dir o",
        ),
        (
            "replan",
            "--spec x --state-root s --new-plan-sha256 "
            + "a" * 64
            + " --logical-unit-manifest-sha256 "
            + "b" * 64
            + " --completed-unit-manifest-sha256 "
            + "c" * 64
            + " --output-dir o",
        ),
        (
            "replan-pending",
            "--spec x --state-root s --work-unit-manifest m "
            "--work-units u --requested-jobs 2 --output-dir o",
        ),
        (
            "merge-only",
            "--spec x --state-root s --source-artifact a "
            "--output-dir o",
        ),
    )
    for command, tail in commands:
        args = parser.parse_args(["github", command, *tail.split()])
        assert callable(args.func)


def test_campaign_update_preserves_verified_sources_when_omitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_path = write_yaml(tmp_path / "spec.yaml", minimal_valid_spec())
    state_root = tmp_path / "state"
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    initial = initialize_campaign_state(
        campaign_id="test-campaign",
        scientific_contract_sha256="1" * 64,
        logical_unit_manifest_sha256="2" * 64,
        logical_unit_count=2,
        active_plan_sha256="3" * 64,
        created_at=now,
    )
    write_campaign_state(initial, state_root)
    merging = transition_campaign_state(
        initial,
        phase=CampaignPhase.MERGING,
        completed_unit_count=2,
        completed_unit_manifest_sha256="4" * 64,
        pending_unit_count=0,
        verified_source_artifacts=("partial-a", "partial-b"),
        created_at=now,
    )
    write_campaign_state(merging, state_root)
    monkeypatch.setattr(
        cmd_github,
        "require_github_execution",
        lambda _operation: None,
    )
    args = argparse.Namespace(
        spec=str(spec_path),
        state_root=str(state_root),
        phase=CampaignPhase.VERIFYING.value,
        logical_unit_manifest_sha256="",
        logical_unit_count=0,
        active_plan_sha256="",
        completed_unit_manifest_sha256="",
        completed_unit_count=None,
        pending_unit_count=None,
        verified_source_artifact=[],
        active_attempt_id=[],
        wave=None,
        hard_failure_reason="",
        created_at="2026-07-26T01:00:00Z",
    )

    assert cmd_github.cmd_github_campaign_update(args) == 0
    updated = load_latest_campaign_state(state_root)

    assert updated.verified_source_artifacts == (
        "partial-a",
        "partial-b",
    )


@pytest.mark.parametrize(
    ("command", "args"),
    [
        (cmd_github.cmd_github_prepare, {"spec": "missing"}),
        (cmd_github.cmd_github_freeze_contract, {"spec": "missing"}),
        (cmd_github.cmd_github_smoke, {"spec": "missing"}),
        (cmd_github.cmd_github_pilot, {"spec": "missing"}),
        (cmd_github.cmd_github_resolve_pilot, {"spec": "missing"}),
        (
            cmd_github.cmd_github_build_performance_profile,
            {"contract": "missing"},
        ),
        (cmd_github.cmd_github_plan, {"spec": "missing"}),
        (cmd_github.cmd_github_run_shard, {"spec": "missing"}),
        (
            cmd_github.cmd_github_recover_plan,
            {
                "spec": "missing",
                "shard_plan": "missing",
                "attempt": [],
                "checkpoint": [],
                "output_dir": "missing",
            },
        ),
        (
            cmd_github.cmd_github_merge_plan,
            {"shard_plan": "missing"},
        ),
        (
            cmd_github.cmd_github_merge_group,
            {"spec": "missing", "shard_plan": "missing"},
        ),
        (
            cmd_github.cmd_github_merge_plan_group,
            {"spec": "missing", "shard_plan": "missing"},
        ),
        (cmd_github.cmd_github_final_merge, {"spec": "missing"}),
        (
            cmd_github.cmd_github_seal_final_artifact,
            {"spec": "missing"},
        ),
        (cmd_github.cmd_github_verify, {"spec": "missing"}),
        (cmd_github.cmd_github_guardrail_check, {"spec": "missing"}),
        (cmd_github.cmd_github_campaign_update, {"spec": "missing"}),
        (cmd_github.cmd_github_recovery_loop, {"spec": "missing"}),
        (cmd_github.cmd_github_replan, {"spec": "missing"}),
        (cmd_github.cmd_github_replan_pending, {"spec": "missing"}),
        (cmd_github.cmd_github_merge_only, {"spec": "missing"}),
    ],
)
def test_heavy_commands_call_github_guard_first(
    monkeypatch,
    command,
    args,
) -> None:
    calls: list[str] = []

    def record(operation: str) -> None:
        calls.append(operation)

    monkeypatch.setattr(cmd_github, "require_github_execution", record)
    with pytest.raises((FileNotFoundError, ModuleNotFoundError)):
        command(argparse.Namespace(**args))
    assert len(calls) == 1
