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


@pytest.mark.parametrize(
    ("command", "args"),
    [
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
