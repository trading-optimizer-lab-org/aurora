"""Immutable, mmap-readable global store for exact {-1,0,+1} components."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, Sha256, canonical_sha256
from aurora.infra.github_performance.shard_planner import sha256_file


class ComponentStoreEntryV1(FrozenModel):
    component_id: str = Field(min_length=1)
    row_index: int = Field(ge=0)
    result_sha256: Sha256


class ComponentStoreManifestV1(FrozenModel):
    schema_version: str = "1"
    data_snapshot_sha256: Sha256
    evaluator_sha256: Sha256
    session_count: int = Field(ge=1)
    component_count: int = Field(ge=1)
    matrix_sha256: Sha256
    entries: tuple[ComponentStoreEntryV1, ...]
    validation_opened: bool = False
    locked_opened: bool = False
    manifest_sha256: Sha256


def _signal_sha256(values: np.ndarray) -> str:
    return hashlib.sha256(b"catalog-component-v1\0" + values.tobytes()).hexdigest()


def _close_memory_map(matrix: object) -> None:
    mapped_file = getattr(matrix, "_mmap", None)
    if mapped_file is not None:
        mapped_file.close()


class ComponentStoreWriter:
    def __init__(
        self,
        root: Path,
        *,
        data_snapshot_sha256: str,
        evaluator_sha256: str,
        session_count: int,
    ) -> None:
        self.root = Path(root)
        self.data_snapshot_sha256 = data_snapshot_sha256
        self.evaluator_sha256 = evaluator_sha256
        self.session_count = int(session_count)
        if self.session_count < 1:
            raise ValueError("COMPONENT_SESSION_COUNT_INVALID")
        self._values: dict[str, np.ndarray] = {}

    def add(self, component_id: str, values: np.ndarray) -> bool:
        checked = np.asarray(values, dtype=np.int8)
        if checked.shape != (self.session_count,) or not np.isin(
            checked,
            (-1, 0, 1),
        ).all():
            raise ValueError("COMPONENT_SIGNAL_INVALID")
        checked = np.ascontiguousarray(checked)
        existing = self._values.get(str(component_id))
        if existing is not None:
            if not np.array_equal(existing, checked):
                raise ValueError("COMPONENT_RESULT_CONFLICT")
            return False
        self._values[str(component_id)] = checked.copy()
        return True

    def commit(self) -> ComponentStoreManifestV1:
        if not self._values:
            raise ValueError("COMPONENT_STORE_EMPTY")
        self.root.mkdir(parents=True, exist_ok=False)
        ordered = sorted(self._values.items())
        matrix = np.stack([values for _, values in ordered])
        matrix_path = self.root / "signals.npy"
        with matrix_path.open("wb") as handle:
            np.save(handle, matrix, allow_pickle=False)
        entries = tuple(
            ComponentStoreEntryV1(
                component_id=component_id,
                row_index=index,
                result_sha256=_signal_sha256(values),
            )
            for index, (component_id, values) in enumerate(ordered)
        )
        identity = {
            "schema_version": "1",
            "data_snapshot_sha256": self.data_snapshot_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "session_count": self.session_count,
            "component_count": len(entries),
            "matrix_sha256": sha256_file(matrix_path),
            "entries": entries,
            "validation_opened": False,
            "locked_opened": False,
        }
        manifest = ComponentStoreManifestV1(
            **identity,
            manifest_sha256=canonical_sha256(identity),
        )
        (self.root / "manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n",
            "utf-8",
        )
        return manifest


class CatalogComponentStore:
    def __init__(
        self,
        root: Path,
        manifest: ComponentStoreManifestV1,
        matrix: np.ndarray,
    ) -> None:
        self.root = Path(root)
        self.manifest = manifest
        self._matrix = matrix
        self._entries = {item.component_id: item for item in manifest.entries}
        self._closed = False

    def __enter__(self) -> CatalogComponentStore:
        if self._closed:
            raise ValueError("COMPONENT_STORE_CLOSED")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the mmap promptly so Windows can replace or remove the store."""

        if self._closed:
            return
        _close_memory_map(self._matrix)
        self._closed = True

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        expected_data_snapshot_sha256: str | None = None,
        expected_evaluator_sha256: str | None = None,
    ) -> CatalogComponentStore:
        root = Path(root)
        try:
            payload = json.loads((root / "manifest.json").read_text("utf-8"))
            manifest = ComponentStoreManifestV1.model_validate(payload)
        except (OSError, ValueError) as exc:
            raise ValueError("COMPONENT_STORE_MANIFEST_INVALID") from exc
        identity = manifest.model_dump(mode="python", exclude={"manifest_sha256"})
        if canonical_sha256(identity) != manifest.manifest_sha256:
            raise ValueError("COMPONENT_STORE_MANIFEST_HASH_INVALID")
        if (
            expected_data_snapshot_sha256 is not None
            and manifest.data_snapshot_sha256 != expected_data_snapshot_sha256
        ) or (
            expected_evaluator_sha256 is not None
            and manifest.evaluator_sha256 != expected_evaluator_sha256
        ):
            raise ValueError("COMPONENT_STORE_INCOMPATIBLE")
        matrix_path = root / "signals.npy"
        if sha256_file(matrix_path) != manifest.matrix_sha256:
            raise ValueError("COMPONENT_STORE_MATRIX_HASH_INVALID")
        matrix = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
        if matrix.shape != (manifest.component_count, manifest.session_count):
            _close_memory_map(matrix)
            raise ValueError("COMPONENT_STORE_MATRIX_SHAPE_INVALID")
        return cls(root, manifest, matrix)

    def get(self, component_id: str) -> np.ndarray:
        if self._closed:
            raise ValueError("COMPONENT_STORE_CLOSED")
        entry = self._entries.get(str(component_id))
        if entry is None:
            raise KeyError(component_id)
        values = np.asarray(self._matrix[entry.row_index])
        if _signal_sha256(values) != entry.result_sha256:
            raise ValueError("COMPONENT_STORE_RESULT_HASH_INVALID")
        return values


def merge_component_stores(
    source_roots: list[Path],
    output_root: Path,
) -> ComponentStoreManifestV1:
    """Merge disjoint partial stores and fail on any duplicate conflict."""

    stores: list[CatalogComponentStore] = []
    try:
        for path in source_roots:
            stores.append(CatalogComponentStore.open(path))
        if not stores:
            raise ValueError("COMPONENT_STORE_SOURCES_EMPTY")
        reference = stores[0].manifest
        writer = ComponentStoreWriter(
            output_root,
            data_snapshot_sha256=reference.data_snapshot_sha256,
            evaluator_sha256=reference.evaluator_sha256,
            session_count=reference.session_count,
        )
        for store in stores:
            manifest = store.manifest
            if (
                manifest.data_snapshot_sha256 != reference.data_snapshot_sha256
                or manifest.evaluator_sha256 != reference.evaluator_sha256
                or manifest.session_count != reference.session_count
            ):
                raise ValueError("COMPONENT_STORE_INCOMPATIBLE")
            for entry in manifest.entries:
                writer.add(entry.component_id, store.get(entry.component_id))
        return writer.commit()
    finally:
        for store in stores:
            store.close()


__all__ = [
    "CatalogComponentStore",
    "ComponentStoreEntryV1",
    "ComponentStoreManifestV1",
    "ComponentStoreWriter",
    "merge_component_stores",
]
