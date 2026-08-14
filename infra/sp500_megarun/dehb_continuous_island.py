"""Deterministic four-slot official-DEHB state machine for continuous search."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
import zipfile

from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
    _canonical_bytes,
    scientific_result_sha256,
)
from aurora.infra.sp500_megarun.dehb_island_runner import (
    _ask_valid_batch,
    _validated_result,
)


class ContinuousIslandError(RuntimeError):
    """Raised when an island batch would change or corrupt DEHB semantics."""


@dataclass(frozen=True)
class IslandBatchV1:
    island_id: str
    batch_sequence: int
    jobs: tuple[Mapping[str, Any], ...]
    batch_sha256: str
    schema_version: int = 1


@dataclass(frozen=True)
class IslandAdvanceV1:
    island_id: str
    batch_sequence: int
    consumed_result_sha256s: tuple[str, ...]
    checkpoint_bytes: bytes
    checkpoint_sha256: str
    prior_checkpoint_sha256: str | None
    evaluations: int
    full_fidelity_evaluations: int
    completed_since_improvement: int
    best_archive_key: tuple[float, ...] | None
    stopped: bool
    schema_version: int = 1


@dataclass(frozen=True)
class CheckpointRestoreReceiptV1:
    checkpoint_sha256: str
    file_count: int
    total_bytes: int
    schema_version: int = 1


def pack_checkpoint_directory(source: Path) -> bytes:
    """Create a byte-stable, manifest-bound archive of an official DEHB checkpoint."""

    root = Path(source).resolve()
    if not root.is_dir():
        raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_SOURCE_INVALID")
    entries = []
    contents: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink():
            raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_SYMLINK_FORBIDDEN")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        contents.append((relative, data))
        entries.append(
            {
                "path": relative,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    if not entries:
        raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_EMPTY")
    manifest = json.dumps(
        {"schema_version": 1, "files": entries},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [*contents, ("__checkpoint_manifest__.json", manifest)]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            info.create_system = 3
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def restore_checkpoint_directory(
    checkpoint_bytes: bytes,
    destination: Path,
    *,
    expected_checkpoint_sha256: str,
) -> CheckpointRestoreReceiptV1:
    """Verify the complete archive before materializing its files."""

    if not isinstance(checkpoint_bytes, bytes) or not checkpoint_bytes:
        raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_ARCHIVE_INVALID")
    checkpoint_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
    if checkpoint_sha256 != str(expected_checkpoint_sha256):
        raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_HASH_MISMATCH")
    target = Path(destination).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_DESTINATION_NOT_EMPTY")
    try:
        with zipfile.ZipFile(io.BytesIO(checkpoint_bytes), "r") as archive:
            names = archive.namelist()
            if names.count("__checkpoint_manifest__.json") != 1:
                raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_MANIFEST_INVALID")
            manifest = json.loads(archive.read("__checkpoint_manifest__.json"))
            if manifest.get("schema_version") != 1 or not isinstance(
                manifest.get("files"), list
            ):
                raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_MANIFEST_INVALID")
            verified: list[tuple[PurePosixPath, bytes]] = []
            expected_names = {"__checkpoint_manifest__.json"}
            for entry in manifest["files"]:
                relative = PurePosixPath(str(entry.get("path", "")))
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_PATH_INVALID")
                name = relative.as_posix()
                expected_names.add(name)
                data = archive.read(name)
                if int(entry.get("size", -1)) != len(data) or entry.get(
                    "sha256"
                ) != hashlib.sha256(data).hexdigest():
                    raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_FILE_HASH_MISMATCH")
                verified.append((relative, data))
            if set(names) != expected_names:
                raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_ARCHIVE_MEMBERS_MISMATCH")
    except ContinuousIslandError:
        raise
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ContinuousIslandError("CONTINUOUS_CHECKPOINT_ARCHIVE_INVALID") from exc

    target.mkdir(parents=True, exist_ok=True)
    for relative, data in verified:
        output = target.joinpath(*relative.parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    return CheckpointRestoreReceiptV1(
        checkpoint_sha256=checkpoint_sha256,
        file_count=len(verified),
        total_bytes=sum(len(data) for _relative, data in verified),
    )


class ContinuousIslandState:
    """One island with at most one unresolved official-DEHB batch."""

    def __init__(
        self,
        *,
        island_id: str,
        optimizer: Any,
        full_fidelity: int,
        plateau_minimum_completed: int,
        plateau_completed_without_improvement: int,
        checkpoint_serializer: Callable[[Any], bytes],
        next_batch_sequence: int = 1,
        evaluations: int = 0,
        full_fidelity_evaluations: int = 0,
        completed_since_improvement: int = 0,
        best_archive_key: tuple[float, ...] | None = None,
        prior_checkpoint_sha256: str | None = None,
        invalid_config_rejections: int = 0,
    ) -> None:
        if not str(island_id):
            raise ContinuousIslandError("CONTINUOUS_ISLAND_ID_INVALID")
        if int(full_fidelity) < 1:
            raise ContinuousIslandError("CONTINUOUS_ISLAND_FULL_FIDELITY_INVALID")
        if not 0 < plateau_minimum_completed <= plateau_completed_without_improvement:
            raise ContinuousIslandError("CONTINUOUS_ISLAND_PLATEAU_INVALID")
        self.island_id = str(island_id)
        self.optimizer = optimizer
        self.full_fidelity = int(full_fidelity)
        self.plateau_minimum_completed = int(plateau_minimum_completed)
        self.plateau_completed_without_improvement = int(
            plateau_completed_without_improvement
        )
        self.checkpoint_serializer = checkpoint_serializer
        self.next_batch_sequence = int(next_batch_sequence)
        self.evaluations = int(evaluations)
        self.full_fidelity_evaluations = int(full_fidelity_evaluations)
        self.completed_since_improvement = int(completed_since_improvement)
        self.best_archive_key = best_archive_key
        self.prior_checkpoint_sha256 = prior_checkpoint_sha256
        self.invalid_config_rejections = int(invalid_config_rejections)
        self._open_batch: IslandBatchV1 | None = None

    def ask_batch(self) -> IslandBatchV1:
        if self._open_batch is not None:
            raise ContinuousIslandError("CONTINUOUS_ISLAND_BATCH_ALREADY_OPEN")
        jobs, rejected = _ask_valid_batch(
            self.optimizer,
            n_configs=4,
            rejection_limit=max(1, 10_000 - self.invalid_config_rejections),
        )
        self.invalid_config_rejections += rejected
        normalized_jobs = tuple(dict(job) for job in jobs)
        payload = {
            "schema_version": 1,
            "island_id": self.island_id,
            "batch_sequence": self.next_batch_sequence,
            "jobs": normalized_jobs,
        }
        batch = IslandBatchV1(
            island_id=self.island_id,
            batch_sequence=self.next_batch_sequence,
            jobs=normalized_jobs,
            batch_sha256=hashlib.sha256(
                b"SP500-DEHB-ISLAND-BATCH-V1\0" + _canonical_bytes(payload)
            ).hexdigest(),
        )
        self._open_batch = batch
        return batch

    def restore_open_batch(self, expected_batch: IslandBatchV1) -> None:
        """Replay deterministic ask from the prior checkpoint and verify exact identity."""

        if expected_batch.island_id != self.island_id:
            raise ContinuousIslandError("CONTINUOUS_ISLAND_RESTORED_BATCH_ISLAND_MISMATCH")
        if expected_batch.batch_sequence != self.next_batch_sequence:
            raise ContinuousIslandError("CONTINUOUS_ISLAND_RESTORED_BATCH_SEQUENCE_MISMATCH")
        replayed = self.ask_batch()
        if replayed.batch_sha256 != expected_batch.batch_sha256:
            self._open_batch = None
            raise ContinuousIslandError("CONTINUOUS_ISLAND_RESTORED_BATCH_HASH_MISMATCH")

    def tell_batch(
        self,
        batch: IslandBatchV1,
        results_by_slot: Mapping[int, Mapping[str, Any]],
    ) -> IslandAdvanceV1:
        if self._open_batch is None or batch.batch_sha256 != self._open_batch.batch_sha256:
            raise ContinuousIslandError("CONTINUOUS_ISLAND_BATCH_MISMATCH")
        if set(results_by_slot) != {0, 1, 2, 3}:
            raise ContinuousIslandError("CONTINUOUS_ISLAND_BATCH_RESULTS_INCOMPLETE")

        validated: list[tuple[Mapping[str, Any], float, Mapping[str, Any], str]] = []
        for slot in range(4):
            raw_result = results_by_slot[slot]
            if not isinstance(raw_result, Mapping):
                raise ContinuousIslandError("CONTINUOUS_ISLAND_RESULT_NOT_MAPPING")
            info = raw_result.get("info")
            if not isinstance(info, Mapping):
                raise ContinuousIslandError("CONTINUOUS_ISLAND_RESULT_INFO_INVALID")
            if info.get("validation_opened") is not False:
                raise ContinuousIslandError("CONTINUOUS_ISLAND_OPENED_VALIDATION")
            if info.get("locked_opened") is not False:
                raise ContinuousIslandError("CONTINUOUS_ISLAND_OPENED_LOCKED")
            try:
                _fitness, _cost, checked_info = _validated_result(raw_result)
            except ValueError as exc:
                raise ContinuousIslandError("CONTINUOUS_ISLAND_RESULT_INVALID") from exc
            validated.append(
                (
                    raw_result,
                    float(batch.jobs[slot]["fidelity"]),
                    checked_info,
                    scientific_result_sha256(raw_result),
                )
            )

        for slot, (raw_result, fidelity, info, _result_hash) in enumerate(validated):
            self.optimizer.tell(batch.jobs[slot], raw_result)
            self.evaluations += 1
            self.completed_since_improvement += 1
            if int(fidelity) == self.full_fidelity:
                self.full_fidelity_evaluations += 1
                raw_archive = info.get("archive_key")
                if not isinstance(raw_archive, list) or not raw_archive:
                    raise ContinuousIslandError("CONTINUOUS_ISLAND_ARCHIVE_KEY_MISSING")
                archive_key = tuple(float(value) for value in raw_archive)
                if self.best_archive_key is None or archive_key < self.best_archive_key:
                    self.best_archive_key = archive_key
                    self.completed_since_improvement = 0

        checkpoint = self.checkpoint_serializer(self.optimizer)
        if not isinstance(checkpoint, bytes) or not checkpoint:
            raise ContinuousIslandError("CONTINUOUS_ISLAND_CHECKPOINT_INVALID")
        checkpoint_sha256 = hashlib.sha256(checkpoint).hexdigest()
        stopped = (
            self.evaluations >= self.plateau_minimum_completed
            and self.completed_since_improvement
            >= self.plateau_completed_without_improvement
        )
        advance = IslandAdvanceV1(
            island_id=self.island_id,
            batch_sequence=batch.batch_sequence,
            consumed_result_sha256s=tuple(item[3] for item in validated),
            checkpoint_bytes=checkpoint,
            checkpoint_sha256=checkpoint_sha256,
            prior_checkpoint_sha256=self.prior_checkpoint_sha256,
            evaluations=self.evaluations,
            full_fidelity_evaluations=self.full_fidelity_evaluations,
            completed_since_improvement=self.completed_since_improvement,
            best_archive_key=self.best_archive_key,
            stopped=stopped,
        )
        self.prior_checkpoint_sha256 = checkpoint_sha256
        self.next_batch_sequence += 1
        self._open_batch = None
        return advance


__all__ = [
    "ContinuousIslandError",
    "ContinuousIslandState",
    "CheckpointRestoreReceiptV1",
    "IslandAdvanceV1",
    "IslandBatchV1",
    "pack_checkpoint_directory",
    "restore_checkpoint_directory",
]
