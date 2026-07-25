from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from aurora.cli import cmd_github
from aurora.cli.forge import build_parser


def test_validate_parser_binds_expected_command() -> None:
    args = build_parser().parse_args(
        ["github", "validate", "--spec", "x.yaml"]
    )
    assert args.func is cmd_github.cmd_github_validate


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
    payload = {
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
            "merge-only",
            "--spec x --state-root s --source-artifact a "
            "--output-dir o",
        ),
    )
    for command, tail in commands:
        args = parser.parse_args(["github", command, *tail.split()])
        assert callable(args.func)


@pytest.mark.parametrize(
    ("command", "args"),
    [
        (cmd_github.cmd_github_prepare, {"spec": "missing"}),
        (cmd_github.cmd_github_freeze_contract, {"spec": "missing"}),
        (cmd_github.cmd_github_smoke, {"spec": "missing"}),
        (cmd_github.cmd_github_pilot, {"spec": "missing"}),
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
        (cmd_github.cmd_github_final_merge, {"spec": "missing"}),
        (cmd_github.cmd_github_verify, {"spec": "missing"}),
        (cmd_github.cmd_github_guardrail_check, {"spec": "missing"}),
        (cmd_github.cmd_github_campaign_update, {"spec": "missing"}),
        (cmd_github.cmd_github_recovery_loop, {"spec": "missing"}),
        (cmd_github.cmd_github_replan, {"spec": "missing"}),
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
