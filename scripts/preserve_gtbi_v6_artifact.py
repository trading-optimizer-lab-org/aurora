"""Stream, inspect and split the one fixed GTBI V6 result artifact.

This is transport-only code. It is intentionally unusable for arbitrary
repositories, runs, artifacts, URLs or local files.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest  # noqa: E402


def _load_execution_policy():
    policy_path = ROOT / "core/execution_policy.py"
    spec = importlib.util.spec_from_file_location(
        "_gtbi_v7_execution_policy", policy_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load central GitHub-only execution policy")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_execution_policy = _load_execution_policy()
LocalRunBlocked = _execution_policy.LocalRunBlocked
require_github_only_execution = _execution_policy.require_github_only_execution

DOMAIN = "GTBI_V6_PRESERVATION_MANIFEST_V1"
MANIFEST_PATH = (
    ROOT / "config/gtbi/manifests/v6_fast_strict_preservation_manifest.json"
)
CHUNK_BYTES = 8 * 1024 * 1024


class PreservationError(RuntimeError):
    """Raised when the fixed artifact cannot be preserved exactly."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_and_verify_manifest(path: Path = MANIFEST_PATH) -> dict:
    if path.resolve() != MANIFEST_PATH.resolve():
        raise PreservationError("only the reviewed fixed manifest is accepted")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = domain_digest(
        DOMAIN,
        manifest,
        omit_top_level_fields=("preservation_manifest_digest",),
    )
    if manifest.get("preservation_manifest_digest") != expected:
        raise PreservationError("fixed preservation manifest digest mismatch")
    return manifest


def verify_remote_metadata(metadata: dict, manifest: dict) -> None:
    expected = {
        "id": manifest["source_artifact_id"],
        "name": manifest["source_artifact_name"],
        "size_in_bytes": manifest["source_size_bytes"],
        "digest": manifest["source_archive_digest"],
        "expires_at": manifest["source_expires_at_utc"],
        "expired": False,
    }
    mismatches = {
        field: {"expected": value, "actual": metadata.get(field)}
        for field, value in expected.items()
        if metadata.get(field) != value
    }
    run_id = (metadata.get("workflow_run") or {}).get("id")
    if run_id != manifest["source_run_id"]:
        mismatches["workflow_run.id"] = {
            "expected": manifest["source_run_id"],
            "actual": run_id,
        }
    if mismatches:
        raise PreservationError(f"remote artifact metadata mismatch: {mismatches}")


def _api_json(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "aurora-gtbi-v6-preservation/1",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _open_artifact_stream(url: str, token: str) -> BinaryIO:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "aurora-gtbi-v6-preservation/1",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        response = opener.open(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise
        location = exc.headers.get("Location")
        if not location:
            raise PreservationError("artifact redirect has no Location") from exc
        # The redirect is a short-lived signed object URL. Never forward the
        # GitHub bearer token to that different host.
        return urllib.request.urlopen(
            urllib.request.Request(
                location,
                headers={"User-Agent": "aurora-gtbi-v6-preservation/1"},
            ),
            timeout=60,
        )
    return response


def stream_fixed_artifact(
    *,
    token: str,
    destination: Path,
    manifest: dict,
) -> tuple[int, str]:
    free = shutil.disk_usage(destination.parent).free
    required = manifest["maximum_archive_bytes"] + CHUNK_BYTES
    if free < required:
        raise PreservationError(
            f"insufficient free disk: required={required}, available={free}"
        )
    url = (
        "https://api.github.com/repos/"
        f"{manifest['source_repository']}/actions/artifacts/"
        f"{manifest['source_artifact_id']}/zip"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        destination.unlink(missing_ok=True)
        digest = hashlib.sha256()
        total = 0
        try:
            with (
                _open_artifact_stream(url, token) as source,
                destination.open("xb") as out,
            ):
                while True:
                    chunk = source.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > manifest["maximum_archive_bytes"]:
                        raise PreservationError(
                            "archive exceeded fixed maximum byte count"
                        )
                    digest.update(chunk)
                    out.write(chunk)
            value = "sha256:" + digest.hexdigest()
            if total != manifest["source_size_bytes"]:
                raise PreservationError(
                    f"archive byte count mismatch: expected "
                    f"{manifest['source_size_bytes']}, got {total}"
                )
            if value != manifest["source_archive_digest"]:
                raise PreservationError("downloaded archive digest mismatch")
            return total, value
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
    raise PreservationError("fixed artifact download failed after 3 attempts") from (
        last_error
    )


def _safe_member_name(name: str) -> str:
    if "\\" in name or "\x00" in name:
        raise PreservationError(f"unsafe ZIP member name: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PreservationError(f"unsafe ZIP member path: {name!r}")
    return path.as_posix()


def inspect_archive(path: Path, manifest: dict) -> dict:
    members: list[dict] = []
    names: set[str] = set()
    total_uncompressed = 0
    total_compressed = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > manifest["maximum_member_count"]:
            raise PreservationError("ZIP member count exceeds fixed limit")
        for info in infos:
            name = _safe_member_name(info.filename)
            if name in names:
                raise PreservationError(f"duplicate ZIP member: {name}")
            names.add(name)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise PreservationError(f"ZIP symlink is forbidden: {name}")
            member_type = stat.S_IFMT(mode)
            if member_type and not (
                stat.S_ISREG(mode) or stat.S_ISDIR(mode)
            ):
                raise PreservationError(
                    f"non-regular ZIP member is forbidden: {name}"
                )
            if info.flag_bits & 0x1:
                raise PreservationError(f"encrypted ZIP member is forbidden: {name}")
            total_uncompressed += info.file_size
            total_compressed += info.compress_size
            if total_uncompressed > manifest["maximum_total_uncompressed_bytes"]:
                raise PreservationError("ZIP uncompressed bytes exceed fixed limit")
            if info.is_dir():
                members.append(
                    {
                        "path": name,
                        "size_bytes": 0,
                        "compressed_size_bytes": 0,
                        "sha256": None,
                        "directory": True,
                    }
                )
                continue
            digest = hashlib.sha256()
            with archive.open(info, "r") as source:
                while True:
                    chunk = source.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    digest.update(chunk)
            members.append(
                {
                    "path": name,
                    "size_bytes": info.file_size,
                    "compressed_size_bytes": info.compress_size,
                    "sha256": "sha256:" + digest.hexdigest(),
                    "directory": False,
                }
            )
    compression_ratio = (
        total_uncompressed / max(1, total_compressed)
    )
    if compression_ratio > manifest["maximum_compression_ratio"]:
        raise PreservationError("ZIP compression ratio exceeds fixed limit")
    return {
        "member_count": len(members),
        "total_uncompressed_bytes": total_uncompressed,
        "total_compressed_bytes": total_compressed,
        "compression_ratio": compression_ratio,
        "members": members,
    }


def split_archive(path: Path, destination: Path, part_size: int) -> list[dict]:
    destination.mkdir(parents=True, exist_ok=True)
    parts: list[dict] = []
    with path.open("rb") as source:
        index = 0
        while True:
            part_path = destination / f"{path.name}.part-{index:04d}"
            digest = hashlib.sha256()
            written = 0
            with part_path.open("xb") as output:
                while written < part_size:
                    chunk = source.read(min(CHUNK_BYTES, part_size - written))
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
            if written == 0:
                part_path.unlink()
                break
            parts.append(
                {
                    "part_index": index,
                    "filename": part_path.name,
                    "size_bytes": written,
                    "sha256": "sha256:" + digest.hexdigest(),
                }
            )
            index += 1
    return parts


def preserve(output_dir: Path, token: str) -> dict:
    require_github_only_execution("fixed GTBI V6 artifact preservation")
    manifest = load_and_verify_manifest()
    metadata_url = (
        "https://api.github.com/repos/"
        f"{manifest['source_repository']}/actions/artifacts/"
        f"{manifest['source_artifact_id']}"
    )
    metadata = _api_json(metadata_url, token)
    verify_remote_metadata(metadata, manifest)
    output_dir.mkdir(parents=True, exist_ok=False)
    archive_path = output_dir / "source-artifact.zip"
    size, archive_digest = stream_fixed_artifact(
        token=token,
        destination=archive_path,
        manifest=manifest,
    )
    inspection = inspect_archive(archive_path, manifest)
    parts = split_archive(
        archive_path,
        output_dir / "parts",
        manifest["part_size_bytes"],
    )
    receipt = {
        "schema_version": "v6_preservation_transport_receipt_v1",
        "preservation_manifest_digest": manifest[
            "preservation_manifest_digest"
        ],
        "source_archive_digest": archive_digest,
        "source_size_bytes": size,
        "inspected_at_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        **inspection,
        "parts": parts,
    }
    (output_dir / "private_transport_receipt.json").write_bytes(
        canonical_bytes(receipt) + b"\n"
    )
    archive_path.unlink()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise PreservationError("GH_TOKEN or GITHUB_TOKEN is required")
    receipt = preserve(args.output_dir.resolve(), token)
    print(
        json.dumps(
            {
                "source_archive_digest": receipt["source_archive_digest"],
                "source_size_bytes": receipt["source_size_bytes"],
                "member_count": receipt["member_count"],
                "part_count": len(receipt["parts"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
