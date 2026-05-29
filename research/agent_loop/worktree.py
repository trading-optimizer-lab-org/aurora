"""Worktree management for Aurora autonomous research loops."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def prepare_agent_worktree(
    *,
    repo_root: Path,
    run_root: Path,
    goal_id: str,
    run_id: str,
    dry_run: bool = True,
    timeout_seconds: int = 120,
) -> Path:
    """Create or simulate an isolated worktree for an agent run."""

    safe_goal = _safe_name(goal_id)
    safe_run = _safe_name(run_id)
    worktree = run_root / "worktrees" / f"codex-aurora-agent-{safe_goal}-{safe_run}"
    if dry_run:
        worktree.mkdir(parents=True, exist_ok=True)
        return worktree
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if worktree.exists():
        return worktree
    branch = f"codex/aurora-agent-{safe_goal}-{safe_run}"
    try:
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"agent worktree creation timed out after {timeout_seconds} seconds"
        ) from exc
    return worktree


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")[:80] or "run"


__all__ = ["prepare_agent_worktree"]
