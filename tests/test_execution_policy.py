from __future__ import annotations

import pytest

from aurora.core.execution_policy import (
    EXPLICIT_LOCAL_TOKEN,
    LocalRunBlocked,
    require_github_execution,
)


def test_guard_allows_github() -> None:
    require_github_execution("candidate sweep", {"GITHUB_ACTIONS": "true"})


def test_guard_accepts_case_insensitive_github_flag() -> None:
    require_github_execution("candidate sweep", {"GITHUB_ACTIONS": "TRUE"})


def test_guard_blocks_local() -> None:
    with pytest.raises(LocalRunBlocked, match="Run local bloqueado"):
        require_github_execution("candidate sweep", {})


def test_guard_allows_exact_user_token() -> None:
    env = {"AURORA_ALLOW_LOCAL_RUNS_EXPLICIT": EXPLICIT_LOCAL_TOKEN}
    require_github_execution("candidate sweep", env)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "true",
        "USER_REQUESTED_LOCAL_RUN",
        " USER_REQUESTED_LOCAL_RUN_THIS_TURN",
        "USER_REQUESTED_LOCAL_RUN_THIS_TURN ",
    ],
)
def test_guard_rejects_approximate_local_tokens(token: str) -> None:
    with pytest.raises(LocalRunBlocked):
        require_github_execution(
            "candidate sweep",
            {"AURORA_ALLOW_LOCAL_RUNS_EXPLICIT": token},
        )


def test_block_message_names_the_operation() -> None:
    with pytest.raises(LocalRunBlocked, match="candidate sweep"):
        require_github_execution("candidate sweep", {})
