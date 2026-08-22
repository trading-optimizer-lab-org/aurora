#!/usr/bin/env python3
"""Fetch the exact frozen runtime-input artifact named by a sealed plan."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
import re
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256  # noqa: E402
from scripts.fetch_catalog_reference_artifact import (  # noqa: E402
    _mapping,
    _strict_json,
    verify_reference_metadata,
)
from scripts.run_catalog_artifact_keeper import (  # noqa: E402
    GitHubReadOnlyClient,
    KeeperError,
    _safe_extract,
    _verify_runtime_input_manifest,
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and verify the sealed runtime-input artifact."
    )
    parser.add_argument("--sealed-plan", required=True, type=Path)
    parser.add_argument("--output-archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser


def _runtime_contract(sealed_plan: Path) -> Mapping[str, object]:
    source = _mapping(
        _strict_json(sealed_plan / "source_artifacts.json"),
        "CATALOG_RUNTIME_SOURCE_DOCUMENT_INVALID",
    )
    identity = {key: value for key, value in source.items() if key != "content_sha256"}
    payload = _mapping(
        source.get("payload"),
        "CATALOG_RUNTIME_SOURCE_DOCUMENT_INVALID",
    )
    source_contract = _mapping(
        payload.get("source_contract"),
        "CATALOG_RUNTIME_SOURCE_DOCUMENT_INVALID",
    )
    rows = source_contract.get("artifacts")
    if (
        source.get("schema_version") != "1"
        or source.get("document_type") != "catalog_source_artifacts_v1"
        or source.get("content_sha256") != canonical_sha256(identity)
        or not isinstance(rows, list)
    ):
        raise ValueError("CATALOG_RUNTIME_SOURCE_DOCUMENT_INVALID")
    selected = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("contract_name") == "runtime_input_pack_v1"
    ]
    if len(selected) != 1:
        raise ValueError("CATALOG_RUNTIME_SOURCE_DOCUMENT_INVALID")
    contract = selected[0]
    if (
        contract.get("classification") != "training_input"
        or contract.get("verification_mode") != "runtime_input_manifest_v1"
        or contract.get("validation_opened") is not False
        or contract.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_RUNTIME_SOURCE_DOCUMENT_INVALID")
    return contract


def fetch(
    *,
    sealed_plan: Path,
    output_archive: Path,
    output_dir: Path,
    receipt: Path,
) -> dict[str, object]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if not _REPOSITORY.fullmatch(repository) or not token:
        raise ValueError("CATALOG_RUNTIME_SOURCE_INVOCATION_INVALID")
    if (
        sealed_plan.is_symlink()
        or not sealed_plan.is_dir()
        or output_archive.exists()
        or output_archive.is_symlink()
        or output_dir.exists()
        or output_dir.is_symlink()
        or receipt.exists()
        or receipt.is_symlink()
    ):
        raise ValueError("CATALOG_RUNTIME_SOURCE_PATH_INVALID")
    contract = _runtime_contract(sealed_plan)
    client = GitHubReadOnlyClient(repository, token)
    artifact_id = contract.get("artifact_id")
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
        raise ValueError("CATALOG_RUNTIME_SOURCE_DOCUMENT_INVALID")
    metadata, _headers = client.get_json(
        f"/repos/{repository}/actions/artifacts/{artifact_id}"
    )
    normalized = verify_reference_metadata(
        contract,
        _mapping(metadata, "CATALOG_RUNTIME_SOURCE_METADATA_INVALID"),
    )
    compressed_cap = int(normalized["artifact_size_in_bytes"])
    archive_sha256 = client.download_artifact(
        artifact_id,
        output_archive,
        compressed_cap,
    )
    expected_archive_sha = str(normalized["artifact_digest"]).removeprefix("sha256:")
    if (
        output_archive.stat().st_size != compressed_cap
        or archive_sha256 != expected_archive_sha
    ):
        raise ValueError("CATALOG_RUNTIME_SOURCE_ARCHIVE_INVALID")
    _safe_extract(output_archive, output_dir, 8 * 1024 * 1024 * 1024)
    content_aggregate_sha256 = _verify_runtime_input_manifest(
        output_dir,
        dict(contract),
    )
    identity = {
        "schema_version": "1",
        "repository": repository,
        **normalized,
        "archive_sha256": archive_sha256,
        "content_aggregate_sha256": content_aggregate_sha256,
        "validation_opened": False,
        "locked_opened": False,
    }
    result = {**identity, "receipt_sha256": canonical_sha256(identity)}
    receipt.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        fetch(
            sealed_plan=args.sealed_plan,
            output_archive=args.output_archive,
            output_dir=args.output_dir,
            receipt=args.receipt,
        )
        return 0
    except (ValueError, TypeError, OSError, json.JSONDecodeError, KeeperError) as exc:
        print(f"CATALOG_RUNTIME_SOURCE_FETCH_INVALID:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
