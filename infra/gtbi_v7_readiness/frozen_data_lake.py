"""Deterministic byte transport for the frozen GTBI V7 data lake.

This module never interprets market data. It packages regular files as opaque
bytes, produces content-addressed manifests and verifies the complete archive.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
    require_digest,
)

ARCHIVE_STEM = "gtbi-v7-frozen-data-lake-v1.tar"
MANIFEST_FILENAME = "gtbi-v7-frozen-data-lake-v1.manifest.json"
RECEIPT_FILENAME = "gtbi-v7-frozen-data-lake-v1.receipt.json"
MANIFEST_MEMBER = "_aurora/gtbi_v7_frozen_data_lake_manifest.json"
MANIFEST_DOMAIN = "GTBI_V7_FROZEN_DATA_LAKE_MANIFEST_V1"
RECEIPT_DOMAIN = "GTBI_V7_FROZEN_DATA_LAKE_RECEIPT_V1"
DEFAULT_PART_SIZE = 1_500_000_000
COPY_CHUNK_SIZE = 8 * 1024 * 1024


class FrozenDataLakeError(RuntimeError):
    """Raised when byte-preservation input or output is unsafe or invalid."""


def _write_canonical_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise FrozenDataLakeError(f"path escapes source root: {path}") from exc
    value = PurePosixPath(relative.as_posix())
    if (
        value.is_absolute()
        or not value.parts
        or any(part in {"", ".", ".."} for part in value.parts)
        or "\\" in value.as_posix()
        or "\x00" in value.as_posix()
    ):
        raise FrozenDataLakeError(f"unsafe relative path: {value}")
    return value.as_posix()


def _source_files(source_root: Path) -> tuple[list[Path], int]:
    root = source_root.resolve()
    if not root.is_dir():
        raise FrozenDataLakeError(f"source root is not a directory: {root}")
    files: list[tuple[str, Path]] = []
    total = 0
    for path in root.rglob("*"):
        metadata = path.lstat()
        if path.is_symlink() or stat.S_ISLNK(metadata.st_mode):
            raise FrozenDataLakeError(f"symbolic links are forbidden: {path}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise FrozenDataLakeError(f"non-regular source entry: {path}")
        relative = _safe_relative_path(path, root)
        files.append((relative, path))
        total += metadata.st_size
    files.sort(key=lambda item: item[0])
    return [path for _, path in files], total


class _HashingReader:
    def __init__(self, source: BinaryIO) -> None:
        self._source = source
        self._digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        data = self._source.read(size)
        self._digest.update(data)
        self.bytes_read += len(data)
        return data

    @property
    def digest(self) -> str:
        return "sha256:" + self._digest.hexdigest()


class _SplitWriter(io.RawIOBase):
    def __init__(self, output_dir: Path, stem: str, part_size: int) -> None:
        if part_size <= 0:
            raise FrozenDataLakeError("part size must be positive")
        self.output_dir = output_dir
        self.stem = stem
        self.part_size = part_size
        self.parts: list[dict[str, Any]] = []
        self._part: BinaryIO | None = None
        self._part_path: Path | None = None
        self._part_digest: Any | None = None
        self._part_bytes = 0
        self._archive_digest = hashlib.sha256()
        self._archive_bytes = 0
        self._closed_for_writes = False

    def writable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._archive_bytes

    def _open_part(self) -> None:
        index = len(self.parts) + 1
        path = self.output_dir / f"{self.stem}.part-{index:04d}"
        if path.exists():
            raise FrozenDataLakeError(f"archive part already exists: {path}")
        self._part = path.open("xb")
        self._part_path = path
        self._part_digest = hashlib.sha256()
        self._part_bytes = 0

    def _close_part(self) -> None:
        if self._part is None:
            return
        self._part.flush()
        os.fsync(self._part.fileno())
        self._part.close()
        assert self._part_path is not None
        assert self._part_digest is not None
        self.parts.append(
            {
                "index": len(self.parts) + 1,
                "name": self._part_path.name,
                "size_bytes": self._part_bytes,
                "sha256": "sha256:" + self._part_digest.hexdigest(),
            }
        )
        self._part = None
        self._part_path = None
        self._part_digest = None
        self._part_bytes = 0

    def write(self, data: Any) -> int:
        if self._closed_for_writes:
            raise FrozenDataLakeError("cannot write after archive finalization")
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            if self._part is None:
                self._open_part()
            remaining = self.part_size - self._part_bytes
            chunk = view[offset : offset + remaining]
            assert self._part is not None
            assert self._part_digest is not None
            written = self._part.write(chunk)
            if written != len(chunk):
                raise FrozenDataLakeError("short write while creating archive")
            raw = chunk.tobytes()
            self._part_digest.update(raw)
            self._archive_digest.update(raw)
            self._part_bytes += written
            self._archive_bytes += written
            offset += written
            if self._part_bytes == self.part_size:
                self._close_part()
        return len(view)

    def flush(self) -> None:
        if self._part is not None:
            self._part.flush()

    def finalize(self) -> None:
        if self._closed_for_writes:
            return
        self._close_part()
        self._closed_for_writes = True

    @property
    def archive_size_bytes(self) -> int:
        return self._archive_bytes

    @property
    def archive_sha256(self) -> str:
        return "sha256:" + self._archive_digest.hexdigest()


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mode = 0o600
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.pax_headers = {}
    return info


def _manifest(
    *,
    source_receipt: dict[str, Any],
    source_receipt_sha256: str,
    files: list[dict[str, Any]],
    source_size_bytes: int,
) -> dict[str, Any]:
    payload = {
        "schema_version": "gtbi_v7_frozen_data_lake_manifest_v1",
        "archive_format": "deterministic_posix_tar_split_v1",
        "source_root_logical": "AU_DATA_DIR/prices/free_us_daily",
        "source_receipt_sha256": source_receipt_sha256,
        "source_observed_at_utc": source_receipt["observed_at_utc"],
        "source_file_count": len(files),
        "source_total_bytes": source_size_bytes,
        "historical_provenance": "yahoo_finance_via_yfinance",
        "provider_download_performed": False,
        "locked_rows_present_in_source": bool(
            source_receipt["locked_rows_present"]
        ),
        "locked_start": source_receipt["locked_start"],
        "scientific_cutoff": source_receipt[
            "scientific_cutoff_required"
        ],
        "scientific_view_rule": "exclude_dates_on_or_after_locked_start",
        "files": files,
        "manifest_digest": "",
    }
    payload["manifest_digest"] = domain_digest(
        MANIFEST_DOMAIN,
        payload,
        omit_top_level_fields=("manifest_digest",),
    )
    return payload


def package_frozen_data_lake(
    *,
    source_root: Path,
    source_receipt_path: Path,
    output_dir: Path,
    part_size: int = DEFAULT_PART_SIZE,
) -> dict[str, Any]:
    """Package the exact local data lake without interpreting its contents."""
    root = source_root.resolve()
    receipt_path = source_receipt_path.resolve()
    destination = output_dir.resolve()
    source_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    source_files, source_size = _source_files(root)
    expected_count = int(source_receipt["file_count"])
    expected_size = int(source_receipt["local_size_bytes"])
    if len(source_files) != expected_count:
        raise FrozenDataLakeError(
            f"source file count mismatch: expected={expected_count}, "
            f"actual={len(source_files)}"
        )
    if source_size != expected_size:
        raise FrozenDataLakeError(
            f"source size mismatch: expected={expected_size}, "
            f"actual={source_size}"
        )
    if source_receipt["locked_start"] != "2021-01-01":
        raise FrozenDataLakeError("unexpected locked_start")
    if source_receipt["scientific_cutoff_required"] != "2020-12-31":
        raise FrozenDataLakeError("unexpected scientific cutoff")
    required_free = source_size + max(64 * 1024 * 1024, part_size // 20)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FrozenDataLakeError(
            f"output directory must be empty: {destination}"
        )
    free = shutil.disk_usage(destination).free
    if free < required_free:
        raise FrozenDataLakeError(
            f"insufficient free disk: required={required_free}, available={free}"
        )

    writer = _SplitWriter(destination, ARCHIVE_STEM, part_size)
    file_rows: list[dict[str, Any]] = []
    with tarfile.open(
        fileobj=writer,
        mode="w|",
        format=tarfile.PAX_FORMAT,
        bufsize=COPY_CHUNK_SIZE,
    ) as archive:
        for path in source_files:
            relative = _safe_relative_path(path, root)
            size = path.stat().st_size
            with path.open("rb") as raw:
                source = _HashingReader(raw)
                archive.addfile(_tar_info(relative, size), source)
            if source.bytes_read != size:
                raise FrozenDataLakeError(f"short read: {relative}")
            file_rows.append(
                {
                    "path": relative,
                    "size_bytes": size,
                    "sha256": source.digest,
                }
            )
        manifest = _manifest(
            source_receipt=source_receipt,
            source_receipt_sha256=raw_sha256(receipt_path),
            files=file_rows,
            source_size_bytes=source_size,
        )
        manifest_bytes = canonical_bytes(manifest) + b"\n"
        archive.addfile(
            _tar_info(MANIFEST_MEMBER, len(manifest_bytes)),
            io.BytesIO(manifest_bytes),
        )
    writer.finalize()
    if not writer.parts:
        raise FrozenDataLakeError("archive produced no parts")
    if any(part["size_bytes"] > part_size for part in writer.parts):
        raise FrozenDataLakeError("archive part exceeded fixed part size")

    _write_canonical_json(destination / MANIFEST_FILENAME, manifest)
    transport_receipt = {
        "schema_version": "gtbi_v7_frozen_data_lake_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "asset_repository": "trading-optimizer-lab-org/aurora-v7-assets",
        "asset_repository_id": 1317002870,
        "release_tag": "gtbi-v7-frozen-data-lake-v1",
        "source_snapshot_observed_at_utc": source_receipt[
            "observed_at_utc"
        ],
        "source_root_logical": "AU_DATA_DIR/prices/free_us_daily",
        "source_receipt_sha256": raw_sha256(receipt_path),
        "source_file_count": len(file_rows),
        "source_total_bytes": source_size,
        "manifest_filename": MANIFEST_FILENAME,
        "manifest_digest": manifest["manifest_digest"],
        "archive_stem": ARCHIVE_STEM,
        "archive_size_bytes": writer.archive_size_bytes,
        "archive_sha256": writer.archive_sha256,
        "part_size_bytes": part_size,
        "part_count": len(writer.parts),
        "parts": writer.parts,
        "provider_download_performed": False,
        "locked_rows_present_in_source": True,
        "locked_start": "2021-01-01",
        "scientific_cutoff": "2020-12-31",
        "github_only_scientific_execution": True,
        "local_scientific_execution_performed": False,
        "maximum_incremental_net_spend_usd": 0,
        "receipt_digest": "",
    }
    transport_receipt["receipt_digest"] = domain_digest(
        RECEIPT_DOMAIN,
        transport_receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    _write_canonical_json(destination / RECEIPT_FILENAME, transport_receipt)
    return transport_receipt


def _validate_manifest(manifest: dict[str, Any]) -> None:
    require_digest(str(manifest.get("manifest_digest")))
    expected = domain_digest(
        MANIFEST_DOMAIN,
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    if manifest["manifest_digest"] != expected:
        raise FrozenDataLakeError("manifest digest mismatch")
    paths = [str(row["path"]) for row in manifest["files"]]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise FrozenDataLakeError("manifest paths are not unique and sorted")
    for path in paths:
        value = PurePosixPath(path)
        if (
            value.is_absolute()
            or not value.parts
            or any(part in {"", ".", ".."} for part in value.parts)
            or "\\" in path
            or "\x00" in path
        ):
            raise FrozenDataLakeError(f"manifest contains unsafe path: {path}")


def _validate_receipt(receipt: dict[str, Any]) -> None:
    require_digest(str(receipt.get("receipt_digest")))
    expected = domain_digest(
        RECEIPT_DOMAIN,
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    if receipt["receipt_digest"] != expected:
        raise FrozenDataLakeError("transport receipt digest mismatch")
    if receipt["locked_start"] != "2021-01-01":
        raise FrozenDataLakeError("receipt locked_start mismatch")
    if receipt["scientific_cutoff"] != "2020-12-31":
        raise FrozenDataLakeError("receipt scientific cutoff mismatch")


def _part_paths(
    parts_dir: Path,
    receipt: dict[str, Any],
) -> list[Path]:
    expected = receipt["parts"]
    if int(receipt["part_count"]) != len(expected):
        raise FrozenDataLakeError("receipt part count mismatch")
    paths: list[Path] = []
    archive_digest = hashlib.sha256()
    archive_bytes = 0
    for expected_index, row in enumerate(expected, start=1):
        if int(row["index"]) != expected_index:
            raise FrozenDataLakeError("archive part indices are not contiguous")
        path = parts_dir / str(row["name"])
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(COPY_CHUNK_SIZE):
                digest.update(chunk)
                archive_digest.update(chunk)
                size += len(chunk)
                archive_bytes += len(chunk)
        if size != int(row["size_bytes"]):
            raise FrozenDataLakeError(f"part size mismatch: {path.name}")
        if "sha256:" + digest.hexdigest() != row["sha256"]:
            raise FrozenDataLakeError(f"part digest mismatch: {path.name}")
        paths.append(path)
    if archive_bytes != int(receipt["archive_size_bytes"]):
        raise FrozenDataLakeError("archive byte count mismatch")
    if "sha256:" + archive_digest.hexdigest() != receipt["archive_sha256"]:
        raise FrozenDataLakeError("archive stream digest mismatch")
    return paths


class _ConcatenatedReader(io.RawIOBase):
    def __init__(self, paths: Iterable[Path]) -> None:
        self._paths = iter(paths)
        self._current: BinaryIO | None = None

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer)
        while True:
            if self._current is None:
                try:
                    self._current = next(self._paths).open("rb")
                except StopIteration:
                    return 0
            data = self._current.read(len(view))
            if data:
                view[: len(data)] = data
                return len(data)
            self._current.close()
            self._current = None

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        super().close()


def verify_frozen_data_lake_archive(
    *,
    parts_dir: Path,
    manifest_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    """Verify every release byte and TAR member without extracting data."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if manifest_path.read_bytes() != canonical_bytes(manifest) + b"\n":
        raise FrozenDataLakeError("manifest is not canonical JSON")
    if receipt_path.read_bytes() != canonical_bytes(receipt) + b"\n":
        raise FrozenDataLakeError("receipt is not canonical JSON")
    _validate_manifest(manifest)
    _validate_receipt(receipt)
    if receipt["manifest_digest"] != manifest["manifest_digest"]:
        raise FrozenDataLakeError("receipt and manifest disagree")
    part_paths = _part_paths(parts_dir.resolve(), receipt)
    expected_files = {
        str(row["path"]): row for row in manifest["files"]
    }
    observed: dict[str, dict[str, Any]] = {}
    embedded_manifest: dict[str, Any] | None = None
    raw_stream = _ConcatenatedReader(part_paths)
    with (
        raw_stream,
        tarfile.open(
            fileobj=raw_stream,
            mode="r|",
            bufsize=COPY_CHUNK_SIZE,
        ) as archive,
    ):
        for member in archive:
            if not member.isfile():
                raise FrozenDataLakeError(
                    f"non-file TAR member is forbidden: {member.name}"
                )
            if member.name == MANIFEST_MEMBER:
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise FrozenDataLakeError("embedded manifest is unreadable")
                embedded_manifest = json.load(extracted)
                continue
            if member.name not in expected_files:
                raise FrozenDataLakeError(
                    f"unexpected TAR member: {member.name}"
                )
            extracted = archive.extractfile(member)
            if extracted is None:
                raise FrozenDataLakeError(
                    f"TAR member is unreadable: {member.name}"
                )
            digest = hashlib.sha256()
            size = 0
            while chunk := extracted.read(COPY_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
            observed[member.name] = {
                "path": member.name,
                "size_bytes": size,
                "sha256": "sha256:" + digest.hexdigest(),
            }
    if embedded_manifest != manifest:
        raise FrozenDataLakeError("embedded manifest mismatch")
    if observed != expected_files:
        missing = sorted(set(expected_files) - set(observed))
        raise FrozenDataLakeError(f"TAR file coverage mismatch: missing={missing}")
    return {
        "verified": True,
        "source_file_count": len(observed),
        "source_total_bytes": sum(
            int(row["size_bytes"]) for row in observed.values()
        ),
        "part_count": len(part_paths),
        "archive_size_bytes": receipt["archive_size_bytes"],
        "archive_sha256": receipt["archive_sha256"],
        "manifest_digest": manifest["manifest_digest"],
        "locked_start": receipt["locked_start"],
        "scientific_cutoff": receipt["scientific_cutoff"],
    }


def utc_now() -> str:
    """Return a canonical UTC timestamp for external upload receipts."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "ARCHIVE_STEM",
    "DEFAULT_PART_SIZE",
    "FrozenDataLakeError",
    "MANIFEST_FILENAME",
    "RECEIPT_FILENAME",
    "package_frozen_data_lake",
    "utc_now",
    "verify_frozen_data_lake_archive",
]
