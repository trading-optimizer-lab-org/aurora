#!/usr/bin/env python3
"""Fetch the one exact frozen reference artifact named by a sealed plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
import re
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256  # noqa: E402
from scripts.run_catalog_artifact_keeper import (  # noqa: E402
    GitHubReadOnlyClient,
    KeeperError,
    _safe_extract,
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and verify the sealed reference oracle artifact."
    )
    parser.add_argument("--sealed-plan", required=True, type=Path)
    parser.add_argument("--output-archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _strict_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_REFERENCE_SOURCE_DOCUMENT_INVALID")
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON constant: {value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _reference_contract(sealed_plan: Path) -> Mapping[str, object]:
    source = _mapping(
        _strict_json(sealed_plan / "source_artifacts.json"),
        "CATALOG_REFERENCE_SOURCE_DOCUMENT_INVALID",
    )
    identity = {key: value for key, value in source.items() if key != "content_sha256"}
    payload = _mapping(
        source.get("payload"),
        "CATALOG_REFERENCE_SOURCE_DOCUMENT_INVALID",
    )
    source_contract = _mapping(
        payload.get("source_contract"),
        "CATALOG_REFERENCE_SOURCE_DOCUMENT_INVALID",
    )
    rows = source_contract.get("artifacts")
    if (
        source.get("schema_version") != "1"
        or source.get("document_type") != "catalog_source_artifacts_v1"
        or source.get("content_sha256") != canonical_sha256(identity)
        or not isinstance(rows, list)
    ):
        raise ValueError("CATALOG_REFERENCE_SOURCE_DOCUMENT_INVALID")
    selected = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("contract_name") == "reference_oracle_v1"
    ]
    if len(selected) != 1:
        raise ValueError("CATALOG_REFERENCE_SOURCE_DOCUMENT_INVALID")
    contract = selected[0]
    if (
        contract.get("classification") != "training_reference"
        or contract.get("verification_mode") != "closed_file_list_v1"
        or contract.get("validation_opened") is not False
        or contract.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_REFERENCE_SOURCE_DOCUMENT_INVALID")
    return contract


def verify_reference_metadata(
    contract: Mapping[str, object],
    metadata: Mapping[str, object],
) -> dict[str, object]:
    """Require every immutable REST identity before downloading one byte."""

    workflow_run = metadata.get("workflow_run")
    artifact_id = contract.get("artifact_id")
    run_id = contract.get("run_id")
    size = contract.get("artifact_size_in_bytes")
    if (
        isinstance(artifact_id, bool)
        or not isinstance(artifact_id, int)
        or artifact_id < 1
        or isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id < 1
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or metadata.get("id") != artifact_id
        or metadata.get("name") != contract.get("artifact_name")
        or metadata.get("digest") != contract.get("artifact_digest")
        or metadata.get("size_in_bytes") != size
        or metadata.get("expired") is not False
        or not isinstance(workflow_run, Mapping)
        or workflow_run.get("id") != run_id
        or workflow_run.get("head_sha") != contract.get("head_sha")
        or contract.get("validation_opened") is not False
        or contract.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_REFERENCE_ARTIFACT_METADATA_INVALID")
    return {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "artifact_name": contract.get("artifact_name"),
        "artifact_digest": contract.get("artifact_digest"),
        "artifact_size_in_bytes": size,
        "head_sha": contract.get("head_sha"),
    }


def _verify_extracted(root: Path, contract: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    files = contract.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("CATALOG_REFERENCE_FILE_CONTRACT_INVALID")
    expected: set[str] = set()
    verified: list[dict[str, object]] = []
    for raw in files:
        row = _mapping(raw, "CATALOG_REFERENCE_FILE_CONTRACT_INVALID")
        relative_value = row.get("path")
        if not isinstance(relative_value, str):
            raise ValueError("CATALOG_REFERENCE_FILE_CONTRACT_INVALID")
        relative = PurePosixPath(relative_value)
        if (
            relative.is_absolute()
            or relative.as_posix() != relative_value
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative_value in expected
        ):
            raise ValueError("CATALOG_REFERENCE_FILE_CONTRACT_INVALID")
        target = root.joinpath(*relative.parts)
        observed_sha = _sha256_file(target) if target.is_file() else ""
        if (
            target.is_symlink()
            or not target.is_file()
            or target.stat().st_size != row.get("bytes")
            or observed_sha != row.get("sha256")
        ):
            raise ValueError("CATALOG_REFERENCE_FILE_CONTENT_INVALID")
        expected.add(relative_value)
        verified.append(
            {
                "path": relative_value,
                "bytes": target.stat().st_size,
                "sha256": observed_sha,
            }
        )
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual != expected or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("CATALOG_REFERENCE_FILE_SET_INVALID")
    return tuple(verified)


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
        raise ValueError("CATALOG_REFERENCE_INVOCATION_INVALID")
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
        raise ValueError("CATALOG_REFERENCE_PATH_INVALID")
    contract = _reference_contract(sealed_plan)
    client = GitHubReadOnlyClient(repository, token)
    artifact_id = contract.get("artifact_id")
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
        raise ValueError("CATALOG_REFERENCE_SOURCE_DOCUMENT_INVALID")
    metadata, _headers = client.get_json(
        f"/repos/{repository}/actions/artifacts/{artifact_id}"
    )
    normalized = verify_reference_metadata(
        contract,
        _mapping(metadata, "CATALOG_REFERENCE_ARTIFACT_METADATA_INVALID"),
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
        raise ValueError("CATALOG_REFERENCE_ARCHIVE_INVALID")
    files = contract.get("files")
    if not isinstance(files, list):
        raise ValueError("CATALOG_REFERENCE_FILE_CONTRACT_INVALID")
    uncompressed_cap = sum(int(_mapping(row, "CATALOG_REFERENCE_FILE_CONTRACT_INVALID")["bytes"]) for row in files)
    _safe_extract(output_archive, output_dir, uncompressed_cap)
    verified_files = _verify_extracted(output_dir, contract)
    identity = {
        "schema_version": "1",
        "repository": repository,
        **normalized,
        "archive_sha256": archive_sha256,
        "verified_files": verified_files,
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
        print(f"CATALOG_REFERENCE_FETCH_INVALID:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
