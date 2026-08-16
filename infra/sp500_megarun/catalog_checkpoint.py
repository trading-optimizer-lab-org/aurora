"""Atomic microshard checkpoint that records only confirmed units."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, Sha256, canonical_sha256


class CompletedCatalogUnitV1(FrozenModel):
    unit_id: str = Field(min_length=1)
    result_sha256: Sha256


class CatalogCheckpoint(FrozenModel):
    schema_version: str = "1"
    path: Path
    plan_sha256: Sha256
    unit_ids: tuple[str, ...]
    completed: tuple[CompletedCatalogUnitV1, ...]
    checkpoint_sha256: Sha256

    @property
    def completed_unit_ids(self) -> tuple[str, ...]:
        return tuple(item.unit_id for item in self.completed)

    @property
    def pending_unit_ids(self) -> tuple[str, ...]:
        completed = set(self.completed_unit_ids)
        return tuple(item for item in self.unit_ids if item not in completed)

    def _identity(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_sha256": self.plan_sha256,
            "unit_ids": self.unit_ids,
            "completed": self.completed,
        }

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(self.model_dump_json(indent=2) + "\n", "utf-8")
        temporary.replace(self.path)

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        plan_sha256: str,
        unit_ids: tuple[str, ...],
    ) -> CatalogCheckpoint:
        if not unit_ids or len(set(unit_ids)) != len(unit_ids):
            raise ValueError("CHECKPOINT_UNIT_IDS_INVALID")
        identity = {
            "schema_version": "1",
            "plan_sha256": plan_sha256,
            "unit_ids": unit_ids,
            "completed": (),
        }
        checkpoint = cls(
            path=Path(path),
            **identity,
            checkpoint_sha256=canonical_sha256(identity),
        )
        checkpoint._write()
        return checkpoint

    @classmethod
    def load(cls, path: Path) -> CatalogCheckpoint:
        try:
            payload = json.loads(Path(path).read_text("utf-8"))
            payload["path"] = Path(path)
            checkpoint = cls.model_validate(payload)
        except (OSError, ValueError) as exc:
            raise ValueError("CHECKPOINT_INVALID") from exc
        if checkpoint.checkpoint_sha256 != canonical_sha256(checkpoint._identity()):
            raise ValueError("CHECKPOINT_HASH_INVALID")
        return checkpoint

    def commit(self, unit_id: str, *, result_sha256: str) -> CatalogCheckpoint:
        if unit_id not in self.unit_ids:
            raise ValueError("CHECKPOINT_UNIT_UNKNOWN")
        existing = {item.unit_id: item for item in self.completed}
        if unit_id in existing:
            if existing[unit_id].result_sha256 != result_sha256:
                raise ValueError("CHECKPOINT_RESULT_CONFLICT")
            return self
        completed = tuple(
            sorted(
                (*self.completed, CompletedCatalogUnitV1(unit_id=unit_id, result_sha256=result_sha256)),
                key=lambda item: item.unit_id,
            )
        )
        identity = {
            "schema_version": "1",
            "plan_sha256": self.plan_sha256,
            "unit_ids": self.unit_ids,
            "completed": completed,
        }
        updated = CatalogCheckpoint(
            path=self.path,
            **identity,
            checkpoint_sha256=canonical_sha256(identity),
        )
        updated._write()
        return updated


__all__ = ["CatalogCheckpoint", "CompletedCatalogUnitV1"]
