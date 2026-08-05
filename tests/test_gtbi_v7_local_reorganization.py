from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from infra.gtbi_v7_readiness.local_reorganization import (
    preserve_local_worktrees,
    validate_local_reorganization,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo, check=True
    )
    (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/aurora.git"],
        cwd=repo,
        check=True,
    )
    return repo


def test_preserves_dirty_worktree_and_verifies_restore(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
    (repo / "new.md").write_text("new document\n", encoding="utf-8")
    before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    public = tmp_path / "public"
    private = tmp_path / "private"

    receipt = preserve_local_worktrees(
        repository_path=repo,
        primary_clone_path=repo,
        public_output_dir=public,
        private_output_dir=private,
        home=tmp_path,
        observed_at_utc="2026-08-02T00:00:00Z",
    )

    assert validate_local_reorganization(public) == []
    assert receipt["dirty_worktree_count"] == 1
    assert receipt["dirty_path_count"] == 2
    assert receipt["restore_verification"] == "passed"
    assert receipt["source_worktrees_modified"] is False
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before
    assert (private / "repository-local-only-commits.bundle").is_file()
    with (public / "dirty_paths.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["relative_path"] for row in rows} == {"tracked.txt", "new.md"}
    assert {row["preservation_decision"] for row in rows} == {
        "captured_by_verified_patch",
        "verified_file_copy",
    }


def test_secret_like_untracked_file_is_not_copied(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    (repo / "secret.txt").write_text(
        "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n", encoding="utf-8"
    )
    public = tmp_path / "public"
    private = tmp_path / "private"

    receipt = preserve_local_worktrees(
        repository_path=repo,
        primary_clone_path=repo,
        public_output_dir=public,
        private_output_dir=private,
        home=tmp_path,
    )

    assert receipt["unresolved_secret_finding_count"] == 1
    private_manifest = json.loads(
        (private / "private_path_manifest.json").read_text(encoding="utf-8")
    )
    secret = next(
        row for row in private_manifest["paths"] if row["source_path"].endswith("secret.txt")
    )
    assert secret["destination_path"] == ""
    assert secret["preservation_decision"] == (
        "retained_in_source_secret_review_required"
    )
