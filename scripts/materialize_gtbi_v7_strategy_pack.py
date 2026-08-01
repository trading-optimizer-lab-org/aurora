"""Build or verify the compact, deterministic GTBI V7 strategy-shard archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes


ARCHIVE_NAME = "strategy_shards.zip"
MANIFEST_NAME = "strategy_shards_manifest.json"
PACK_ID = "gtbi_long_hold_fundamental_timing_v1"


class StrategyPackArchiveError(RuntimeError):
    """Raised when the compact strategy pack is incomplete or altered."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _manifest_digest(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("manifest_digest", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _safe_member(name: str) -> str:
    pure = PurePosixPath(name)
    if (
        pure.is_absolute()
        or len(pure.parts) != 1
        or pure.name != name
        or not name.startswith("shard_")
        or not name.endswith(".jsonl")
        or "\\" in name
        or "\x00" in name
    ):
        raise StrategyPackArchiveError(f"unsafe strategy shard member: {name}")
    return name


def build_archive(
    *,
    shards_root: Path,
    pack_root: Path,
    expected_shards: int = 360,
    expected_rows_per_shard: int = 200,
) -> dict[str, Any]:
    """Create a reproducible ZIP and canonical inventory from source shards."""
    source = Path(shards_root)
    destination = Path(pack_root)
    if not source.is_dir():
        raise FileNotFoundError(f"strategy shards not found: {source}")
    if destination.exists() and any(destination.iterdir()):
        raise StrategyPackArchiveError(f"pack output is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    paths = sorted(source.glob("shard_*.jsonl"), key=lambda path: path.name)
    expected_names = [f"shard_{index:03d}.jsonl" for index in range(int(expected_shards))]
    if [path.name for path in paths] != expected_names:
        raise StrategyPackArchiveError("strategy shard membership is not exact and contiguous")
    archive_path = destination / ARCHIVE_NAME
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(
        archive_path,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for path in paths:
            data = path.read_bytes()
            line_count = sum(1 for line in data.splitlines() if line.strip())
            if line_count != int(expected_rows_per_shard):
                raise StrategyPackArchiveError(
                    f"{path.name} has {line_count} strategies; expected {expected_rows_per_shard}"
                )
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            rows.append(
                {
                    "path": path.name,
                    "size_bytes": len(data),
                    "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                    "strategy_rows": line_count,
                }
            )
    manifest = {
        "schema_version": "gtbi_v7_strategy_shards_archive_v1",
        "pack_id": PACK_ID,
        "archive_name": ARCHIVE_NAME,
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": _sha256(archive_path),
        "shard_count": len(rows),
        "strategies_per_shard": int(expected_rows_per_shard),
        "strategy_count": sum(int(row["strategy_rows"]) for row in rows),
        "uncompressed_size_bytes": sum(int(row["size_bytes"]) for row in rows),
        "files": rows,
    }
    manifest["manifest_digest"] = _manifest_digest(manifest)
    (destination / MANIFEST_NAME).write_bytes(canonical_bytes(manifest) + b"\n")
    return manifest


def extract_archive(*, pack_root: Path, output_dir: Path) -> dict[str, Any]:
    """Verify every compressed and uncompressed byte, then extract atomically."""
    root = Path(pack_root)
    output = Path(output_dir)
    if output.exists():
        raise StrategyPackArchiveError(f"strategy output already exists: {output}")
    manifest_path = root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise StrategyPackArchiveError("strategy archive manifest is not an object")
    if manifest_path.read_bytes() != canonical_bytes(manifest) + b"\n":
        raise StrategyPackArchiveError("strategy archive manifest is not canonical")
    if manifest.get("manifest_digest") != _manifest_digest(manifest):
        raise StrategyPackArchiveError("strategy archive manifest digest mismatch")
    if manifest.get("pack_id") != PACK_ID or manifest.get("archive_name") != ARCHIVE_NAME:
        raise StrategyPackArchiveError("strategy archive identity mismatch")
    archive_path = root / ARCHIVE_NAME
    if (
        not archive_path.is_file()
        or archive_path.stat().st_size != int(manifest.get("archive_size_bytes", -1))
        or _sha256(archive_path) != manifest.get("archive_sha256")
    ):
        raise StrategyPackArchiveError("strategy archive bytes do not match manifest")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise StrategyPackArchiveError("strategy archive file inventory is empty")
    expected = {str(row.get("path") or ""): dict(row) for row in raw_files if isinstance(row, dict)}
    expected_names = [f"shard_{index:03d}.jsonl" for index in range(int(manifest["shard_count"]))]
    if sorted(expected) != expected_names or len(expected) != len(raw_files):
        raise StrategyPackArchiveError("strategy archive file inventory is not exact")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    shards = temporary / "shards"
    shards.mkdir()
    observed: set[str] = set()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [_safe_member(info.filename) for info in infos]
            if sorted(names) != sorted(expected) or len(names) != len(set(names)):
                raise StrategyPackArchiveError("strategy ZIP membership differs from manifest")
            for info in infos:
                name = _safe_member(info.filename)
                row = expected[name]
                digest = hashlib.sha256()
                size = 0
                line_count = 0
                destination = shards / name
                with archive.open(info) as source, destination.open("xb") as sink:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        line_count += sum(1 for line in chunk.splitlines() if line.strip())
                        sink.write(chunk)
                if (
                    size != int(row.get("size_bytes", -1))
                    or "sha256:" + digest.hexdigest() != row.get("sha256")
                ):
                    raise StrategyPackArchiveError(f"strategy shard digest mismatch: {name}")
                # A shard row is one compact JSON object per physical line. Chunk
                # boundaries can only over-count when a line crosses a chunk, so
                # use the verified file for the final exact count.
                line_count = sum(1 for line in destination.read_bytes().splitlines() if line.strip())
                if line_count != int(row.get("strategy_rows", -1)):
                    raise StrategyPackArchiveError(f"strategy shard row count mismatch: {name}")
                observed.add(name)
        if observed != set(expected):
            raise StrategyPackArchiveError("strategy archive extraction is incomplete")
        receipt = {
            "schema_version": "gtbi_v7_strategy_shards_materialization_v1",
            "pack_id": PACK_ID,
            "archive_sha256": manifest["archive_sha256"],
            "manifest_digest": manifest["manifest_digest"],
            "shard_count": int(manifest["shard_count"]),
            "strategy_count": int(manifest["strategy_count"]),
            "verified": True,
        }
        receipt["receipt_digest"] = _manifest_digest(receipt)
        (temporary / "materialization_receipt.json").write_bytes(canonical_bytes(receipt) + b"\n")
        temporary.replace(output)
        return receipt
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--shards-root", type=Path, required=True)
    build.add_argument("--pack-root", type=Path, required=True)
    build.add_argument("--expected-shards", type=int, default=360)
    build.add_argument("--expected-rows-per-shard", type=int, default=200)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--pack-root", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        result = build_archive(
            shards_root=args.shards_root,
            pack_root=args.pack_root,
            expected_shards=args.expected_shards,
            expected_rows_per_shard=args.expected_rows_per_shard,
        )
    else:
        result = extract_archive(pack_root=args.pack_root, output_dir=args.output_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
