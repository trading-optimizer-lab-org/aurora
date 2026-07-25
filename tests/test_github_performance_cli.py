from __future__ import annotations

import argparse

import pytest

from aurora.cli import cmd_github
from aurora.cli.forge import build_parser


def test_validate_parser_binds_expected_command() -> None:
    args = build_parser().parse_args(
        ["github", "validate", "--spec", "x.yaml"]
    )
    assert args.func is cmd_github.cmd_github_validate


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
            "--workload aurora.x:W --shard-plan p --merge-group g "
            "--inputs-root i --output-dir o",
        ),
        (
            "final-merge",
            "--spec x --workload aurora.x:W --partials-root p "
            "--plan-root r --contract-root c --output-dir o",
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
            {"shard_plan": "missing"},
        ),
        (cmd_github.cmd_github_final_merge, {"spec": "missing"}),
        (cmd_github.cmd_github_verify, {"spec": "missing"}),
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
