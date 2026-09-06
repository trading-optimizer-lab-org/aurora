#!/usr/bin/env python3
"""Verify the live authority before admission; no remote mutation or bootstrap."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.sp500_megarun.catalog_fast_authority_github import load_current_fast_authority
from aurora.infra.sp500_megarun.catalog_gate_budget import gate_timeout
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient, CatalogGitHubSnapshotError
from scripts.admit_catalog_fast_request import _download_owner_archive, _historical_owner_commit_approved, _strict_json


def read_live_edit(anchor: dict[str, Any]) -> dict[str, Any]:
    """Fixed read-only GraphQL operation; identifiers come from protected config."""
    number = anchor["issue_number"]
    if type(number) is not int or number < 1 or anchor["repository"] != "trading-optimizer-lab-org/aurora":
        raise ValueError("CATALOG_FAST_AUTHORITY_ANCHOR_INVALID")
    query = '''query { repository(owner:"trading-optimizer-lab-org",name:"aurora") {
      id nameWithOwner issue(number:NUMBER) { id number title state locked body createdAt lastEditedAt
        author { login } editor { login }
        userContentEdits(first:1) { nodes { id editedAt deletedAt editor { login } } }
      }
    }}'''.replace("NUMBER", str(number))
    result = subprocess.run(["gh", "api", "graphql", "--input", "-"],
        input=json.dumps({"query": query}), capture_output=True, text=True, timeout=gate_timeout(20), check=False)
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("CATALOG_FAST_AUTHORITY_EDIT_UNAVAILABLE")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_FAST_AUTHORITY_EDIT_INVALID")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GH_TOKEN", "")
        if repository != "trading-optimizer-lab-org/aurora" or not token or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("CATALOG_FAST_AUTHORITY_ENVIRONMENT_INVALID")
        root = args.repo_root.resolve(strict=True)
        temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        output = args.output.resolve(strict=False)
        if (args.repo_root.is_symlink() or args.output.is_symlink() or args.output.exists()
            or not output.is_relative_to(temp) or not output.parent.is_dir()):
            raise ValueError("CATALOG_FAST_AUTHORITY_OUTPUT_INVALID")
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False)
        if head.returncode != 0 or head.stdout.strip() != commit:
            raise ValueError("CATALOG_FAST_AUTHORITY_CHECKOUT_INVALID")
        anchor = _strict_json(root / "config/catalog_authority_anchor_v1.json")
        if not isinstance(anchor, dict):
            raise ValueError("CATALOG_FAST_AUTHORITY_ANCHOR_INVALID")
        client = CatalogGitHubReadOnlyClient(repository, token)
        state = load_current_fast_authority(client=client, anchor=anchor, protected_commit=commit,
            read_edit=lambda: read_live_edit(anchor),
            download_archive=lambda artifact_id: _download_owner_archive(repository, token, artifact_id),
            approve_historical_commit=lambda candidate: _historical_owner_commit_approved(client, candidate, commit))
        with output.open("x", encoding="utf-8") as stream:
            stream.write(state.model_dump_json() + "\n")
        print(json.dumps({"status": "CURRENT_AUTHORITY_VERIFIED", "revision": state.revision,
            "state_sha256": state.state_sha256}))
        return 0
    except (ValueError, OSError, KeyError, CatalogGitHubSnapshotError, subprocess.SubprocessError) as exc:
        reason = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"CATALOG_[A-Z0-9_]+", reason):
            reason = "CATALOG_FAST_AUTHORITY_UNAVAILABLE"
        print(reason, file=sys.stderr)
        return 4 if reason == "CATALOG_FAST_AUTHORITY_ARTIFACT_MISSING" else 2


if __name__ == "__main__":
    raise SystemExit(main())
