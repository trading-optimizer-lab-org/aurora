"""Reconstruct and verify a fixed GTBI V6 preservation part set."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes  # noqa: E402
from core.execution_policy import require_github_only_execution  # noqa: E402
from scripts.preserve_gtbi_v6_artifact import (  # noqa: E402
    CHUNK_BYTES,
    PreservationError,
    inspect_archive,
    load_and_verify_manifest,
)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, "sha256:" + digest.hexdigest()


def restore(parts_dir: Path, receipt_path: Path, output_dir: Path) -> dict:
    require_github_only_execution("fixed GTBI V6 artifact restoration")
    manifest = load_and_verify_manifest()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["preservation_manifest_digest"] != (
        manifest["preservation_manifest_digest"]
    ):
        raise PreservationError("receipt uses a different preservation manifest")
    output_dir.mkdir(parents=True, exist_ok=False)
    archive_path = output_dir / "restored-source-artifact.zip"
    digest = hashlib.sha256()
    size = 0
    with archive_path.open("xb") as output:
        for expected_index, part in enumerate(receipt["parts"]):
            if part["part_index"] != expected_index:
                raise PreservationError("part indexes are not contiguous")
            part_path = parts_dir / part["filename"]
            actual_size, actual_digest = _hash_file(part_path)
            if (
                actual_size != part["size_bytes"]
                or actual_digest != part["sha256"]
            ):
                raise PreservationError(f"part mismatch: {part['filename']}")
            with part_path.open("rb") as source:
                while True:
                    chunk = source.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
    archive_digest = "sha256:" + digest.hexdigest()
    if (
        size != manifest["source_size_bytes"]
        or archive_digest != manifest["source_archive_digest"]
    ):
        raise PreservationError("reconstructed archive identity mismatch")
    inspection = inspect_archive(archive_path, manifest)
    if inspection["members"] != receipt["members"]:
        raise PreservationError("reconstructed member manifest mismatch")
    result = {
        "schema_version": "v6_preservation_restore_receipt_v1",
        "preservation_manifest_digest": manifest[
            "preservation_manifest_digest"
        ],
        "source_archive_digest": archive_digest,
        "source_size_bytes": size,
        "member_count": inspection["member_count"],
        "member_manifest_match": True,
    }
    (output_dir / "restore_receipt.json").write_bytes(
        canonical_bytes(result) + b"\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = restore(
        args.parts_dir.resolve(),
        args.receipt.resolve(),
        args.output_dir.resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
