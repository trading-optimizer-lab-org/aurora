"""Tests for quantforge.dataeng.dbt_runner."""
from __future__ import annotations

import pytest

from aurora.dataeng.dbt_runner import DBTConfig, DBTRunner


@pytest.fixture
def runner() -> DBTRunner:
    return DBTRunner(
        DBTConfig(project_dir="/tmp/proj", profiles_dir="/tmp/prof",
                  target="ci", select="+staging"),
        mock=True,
    )


def test_run_returns_success_in_mock(runner: DBTRunner):
    res = runner.run()
    assert res.returncode == 0
    assert "ok" in res.stdout
    assert res.duration_s >= 0.0


def test_test_returns_success_in_mock(runner: DBTRunner):
    res = runner.test()
    assert res.returncode == 0


def test_build_command_uses_config(runner: DBTRunner):
    cmd = runner.build_command("run")
    assert cmd[0] == "dbt"
    assert "--target" in cmd and "ci" in cmd
    assert "--project-dir" in cmd and "/tmp/proj" in cmd
    assert "--select" in cmd and "+staging" in cmd


def test_build_command_omits_select_when_empty():
    r = DBTRunner(DBTConfig(select=""), mock=True)
    cmd = r.build_command("run")
    assert "--select" not in cmd


def test_run_command_field(runner: DBTRunner):
    res = runner.run()
    assert res.command[1] == "run"
