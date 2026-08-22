#!/usr/bin/env python3
"""Select due existing catalog request issues for bounded controller replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_request_reconciler import (
    select_catalog_request_reconciliation_candidates,
)


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay only due, already-existing catalog request issues."
    )
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-output", required=True, type=Path)
    return parser


def _strict_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_RECONCILER_CONFIG_INVALID")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GH_TOKEN", "")
        runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
        if repository != _REPOSITORY or not token or not runner_temp_raw:
            raise ValueError("CATALOG_RECONCILER_INVOCATION_INVALID")
        root = args.repo_root.resolve(strict=True)
        runner_temp = Path(runner_temp_raw).resolve(strict=True)
        output = args.output.resolve(strict=False)
        github_output = args.github_output.resolve(strict=False)
        if (
            args.repo_root.is_symlink()
            or not root.is_dir()
            or args.output.exists()
            or args.output.is_symlink()
            or not output.is_relative_to(runner_temp)
            or args.github_output.is_symlink()
            or not github_output.is_relative_to(runner_temp)
        ):
            raise ValueError("CATALOG_RECONCILER_INVOCATION_INVALID")
        controls = _strict_json(root / "config/catalog_github_controls_v1.json")
        terminal = controls.get("issue_labels", {}).get("terminal", {})
        terminal_label = terminal.get("name")
        if not isinstance(terminal_label, str):
            raise ValueError("CATALOG_RECONCILER_CONFIG_INVALID")

        client = CatalogGitHubReadOnlyClient(repository, token)
        issues = client.stable_paginated(
            f"/repos/{repository}/issues?state=open&sort=created&direction=asc",
            root="list",
        )
        comments = client.stable_paginated(
            f"/repos/{repository}/issues/comments?sort=created&direction=asc",
            root="list",
        )
        observed_at = max(issues.observed_at, comments.observed_at)
        source_identity = {
            "schema_version": "1",
            "repository": repository,
            "issues_snapshot_sha256": issues.snapshot_sha256,
            "comments_snapshot_sha256": comments.snapshot_sha256,
        }
        source_sha256 = hashlib.sha256(
            json.dumps(
                source_identity,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if not _SHA256.fullmatch(source_sha256):
            raise ValueError("CATALOG_RECONCILER_SOURCE_INVALID")
        plan = select_catalog_request_reconciliation_candidates(
            repository=repository,
            issues=issues.collection.rows,
            comments=comments.collection.rows,
            terminal_label=terminal_label,
            observed_at=observed_at,
            source_sha256=source_sha256,
        )
        args.output.write_bytes(canonical_model_bytes(plan) + b"\n")
        matrix = json.dumps(
            plan.matrix["include"],
            sort_keys=True,
            separators=(",", ":"),
        )
        with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"matrix={matrix}\n")
            stream.write(f"has_candidates={str(plan.has_candidates).lower()}\n")
            stream.write(f"plan_sha256={plan.plan_sha256}\n")
        return 0
    except (CatalogGitHubSnapshotError, OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
