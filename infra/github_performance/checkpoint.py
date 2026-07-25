"""Atomic checkpoint publication for recoverable GitHub shards."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from aurora.infra.github_performance.contracts import CheckpointManifest
from aurora.infra.github_performance.shard_planner import sha256_file


class CheckpointIntegrityError(RuntimeError):
    """Raised when checkpoint evidence is incomplete or has changed."""


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_payload_refresh(path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".checkpoint.tmp")
    with path.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)
    _fsync_directory(path.parent)


def _atomic_manifest(path: Path, manifest: CheckpointManifest) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(manifest.model_dump_json(indent=2))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    _fsync_directory(path.parent)


class CheckpointManager:
    """Publish payload first and the authoritative manifest last."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "checkpoint_manifest.json"

    def commit(
        self,
        shard_id: str,
        attempt_id: str,
        completed_unit_count: int,
        last_completed_unit_key: str | None,
        payload_path: Path,
    ) -> CheckpointManifest:
        payload_path = Path(payload_path).resolve()
        if not payload_path.is_file():
            raise FileNotFoundError(payload_path)
        if completed_unit_count < 0:
            raise ValueError("completed_unit_count must be non-negative")
        if self.manifest_path.is_file():
            previous = load_checkpoint(self.manifest_path)
            if previous.shard_id != shard_id:
                raise CheckpointIntegrityError(
                    "checkpoint shard identity changed"
                )
            if completed_unit_count < previous.completed_unit_count:
                raise CheckpointIntegrityError(
                    "checkpoint completed-unit count regressed"
                )
        _atomic_payload_refresh(payload_path)
        manifest = CheckpointManifest(
            shard_id=shard_id,
            attempt_id=attempt_id,
            artifact_name=f"run-checkpoint-{shard_id}-{attempt_id}",
            completed_unit_count=completed_unit_count,
            last_completed_unit_key=last_completed_unit_key,
            payload_path=str(payload_path),
            payload_sha256=sha256_file(payload_path),
            created_at=datetime.now(timezone.utc),
        )
        _atomic_manifest(self.manifest_path, manifest)
        return manifest


def load_checkpoint(path: Path) -> CheckpointManifest:
    """Load and fully verify one published checkpoint."""

    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        manifest = CheckpointManifest.model_validate(raw)
    except (OSError, ValueError) as exc:
        raise CheckpointIntegrityError(
            f"invalid checkpoint manifest: {path}"
        ) from exc
    expected_artifact = (
        f"run-checkpoint-{manifest.shard_id}-{manifest.attempt_id}"
    )
    if manifest.artifact_name != expected_artifact:
        raise CheckpointIntegrityError(
            "checkpoint shard or attempt identity mismatch"
        )
    payload = Path(manifest.payload_path)
    if not payload.is_file():
        raise CheckpointIntegrityError(
            f"checkpoint payload is missing: {payload}"
        )
    if sha256_file(payload) != manifest.payload_sha256:
        raise CheckpointIntegrityError("checkpoint payload sha256 mismatch")
    return manifest
