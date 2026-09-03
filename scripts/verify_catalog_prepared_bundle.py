#!/usr/bin/env python3
"""Verify one restored PREPARED bundle against the checked-out catalog inputs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogPreparedReceiptV1,
    build_catalog_preparation_identity,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    verify_prepared_catalog_bundle,
)


_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify one PREPARED bundle.")
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--require-live-caches", action="store_true")
    return parser


def missing_required_cache_keys(
    required_cache_keys: tuple[str, ...],
    cache_rows: tuple[Mapping[str, Any], ...],
) -> tuple[str, ...]:
    live = {
        str(row.get("key"))
        for row in cache_rows
        if row.get("ref") == "refs/heads/main" and isinstance(row.get("key"), str)
    }
    return tuple(sorted(set(required_cache_keys) - live))


def _verify_live_caches(receipt: CatalogPreparedReceiptV1) -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if not _REPOSITORY.fullmatch(repository) or not token:
        raise ValueError("CATALOG_PREPARED_CACHE_VERIFY_INVOCATION_INVALID")
    client = CatalogGitHubReadOnlyClient(repository, token)
    inventory = client.stable_paginated(
        f"/repos/{repository}/actions/caches?ref=refs/heads/main",
        root="actions_caches",
    ).collection
    missing = missing_required_cache_keys(receipt.required_cache_keys, inventory.rows)
    if missing:
        raise ValueError(f"CATALOG_PREPARED_CACHE_MISSING:{len(missing)}")


def verify_bundle(
    *,
    campaign_key: str,
    repo_root: Path,
    bundle: Path,
    github_output: Path | None,
    require_live_caches: bool = False,
) -> str:
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    if not _COMMIT.fullmatch(expected_commit):
        raise ValueError("CATALOG_PREPARED_VERIFY_INVOCATION_INVALID")
    root = repo_root.resolve(strict=True)
    checked_out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if checked_out != expected_commit:
        raise ValueError("CATALOG_PREPARED_VERIFY_COMMIT_MISMATCH")
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    entry = resolve_catalog_campaign(registry, campaign_key, root)
    identity = build_catalog_preparation_identity(
        repo_root=root,
        registry_entry=entry,
        protected_commit_sha=expected_commit,
    )
    receipt, manifest = verify_prepared_catalog_bundle(
        bundle_dir=bundle,
        expected_identity=identity,
    )
    if require_live_caches:
        _verify_live_caches(receipt)
    if github_output is not None:
        if github_output.is_symlink():
            raise ValueError("CATALOG_PREPARED_VERIFY_OUTPUT_INVALID")
        with github_output.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("prepared_valid=true\n")
            stream.write(f"prepared_receipt_sha256={receipt.receipt_sha256}\n")
            stream.write(
                f"prepared_bundle_manifest_sha256={manifest.manifest_sha256}\n"
            )
    return receipt.receipt_sha256


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify_bundle(
            campaign_key=args.campaign_key,
            repo_root=args.repo_root,
            bundle=args.bundle,
            github_output=args.github_output,
            require_live_caches=args.require_live_caches,
        )
        return 0
    except (
        CatalogGitHubSnapshotError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
