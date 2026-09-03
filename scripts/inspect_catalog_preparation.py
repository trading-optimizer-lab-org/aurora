#!/usr/bin/env python3
"""Derive the exact cache identity for one registered catalog preparation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    build_catalog_preparation_identity,
)


_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect one catalog preparation.")
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--github-output", required=True, type=Path)
    return parser


def inspect_preparation(
    *,
    campaign_key: str,
    repo_root: Path,
    github_output: Path,
) -> dict[str, str]:
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    if not _COMMIT.fullmatch(expected_commit):
        raise ValueError("CATALOG_PREPARATION_INVOCATION_INVALID")
    root = repo_root.resolve(strict=True)
    if repo_root.is_symlink() or not root.is_dir() or github_output.is_symlink():
        raise ValueError("CATALOG_PREPARATION_PATH_INVALID")
    checked_out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if checked_out != expected_commit:
        raise ValueError("CATALOG_PREPARATION_PROTECTED_COMMIT_MISMATCH")
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    entry = resolve_catalog_campaign(registry, campaign_key, root)
    if not entry.active:
        raise ValueError("CATALOG_CAMPAIGN_NOT_ACTIVE")
    identity = build_catalog_preparation_identity(
        repo_root=root,
        registry_entry=entry,
        protected_commit_sha=expected_commit,
    )
    policy = json.loads((root / entry.optimization_policy_path).read_text("utf-8"))
    workers = policy.get("execution", {}).get("workers")
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 360:
        raise ValueError("CATALOG_WORKER_CEILING_INVALID")
    values = {
        "campaign_key": campaign_key,
        "preparation_key_sha256": identity.preparation_key_sha256,
        "prepared_cache_restore_prefix": (
            f"aurora-catalog-prepared-v1-{identity.preparation_key_sha256}-"
        ),
        "qualified_workers": str(min(workers, entry.max_free_workers)),
        "protected_commit_sha": expected_commit,
    }
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError("CATALOG_PREPARATION_OUTPUT_INVALID")
            stream.write(f"{key}={value}\n")
    return values


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inspect_preparation(
            campaign_key=args.campaign_key,
            repo_root=args.repo_root,
            github_output=args.github_output,
        )
        return 0
    except (json.JSONDecodeError, OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
