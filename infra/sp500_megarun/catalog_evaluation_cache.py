"""Hash-bound persistent result cache for compatible catalog evaluations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from aurora.infra.github_performance.contracts import FrozenModel, Sha256, canonical_sha256


class EvaluationCacheKeyV1(FrozenModel):
    schema_version: str = "1"
    evaluator_sha256: Sha256
    data_snapshot_sha256: Sha256
    recipe_sha256: Sha256
    numeric_profile: str

    @property
    def cache_key_sha256(self) -> str:
        return canonical_sha256(self)


class EvaluationCacheEntryV1(FrozenModel):
    key: EvaluationCacheKeyV1
    cache_key_sha256: Sha256
    result: dict[str, Any]
    result_sha256: Sha256
    origin: Literal["physical", "prior_run", "checkpoint"]


class CatalogEvaluationCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "entries.jsonl"
        self._entries: dict[str, EvaluationCacheEntryV1] = {}
        if self.path.is_file():
            for line in self.path.read_text("utf-8").splitlines():
                if line:
                    entry = EvaluationCacheEntryV1.model_validate_json(line)
                    self._insert_verified(entry)

    def _insert_verified(self, entry: EvaluationCacheEntryV1) -> None:
        if entry.cache_key_sha256 != entry.key.cache_key_sha256:
            raise ValueError("EVALUATION_CACHE_KEY_HASH_INVALID")
        if entry.result_sha256 != canonical_sha256(entry.result):
            raise ValueError("EVALUATION_CACHE_RESULT_HASH_INVALID")
        previous = self._entries.get(entry.cache_key_sha256)
        if previous is not None and previous.result_sha256 != entry.result_sha256:
            raise ValueError("EVALUATION_CACHE_CONFLICT")
        self._entries[entry.cache_key_sha256] = entry

    def get(self, key: EvaluationCacheKeyV1) -> EvaluationCacheEntryV1 | None:
        return self._entries.get(key.cache_key_sha256)

    def put(
        self,
        key: EvaluationCacheKeyV1,
        result: dict[str, Any],
        *,
        origin: Literal["physical", "prior_run", "checkpoint"],
    ) -> bool:
        result_copy = dict(result)
        entry = EvaluationCacheEntryV1(
            key=key,
            cache_key_sha256=key.cache_key_sha256,
            result=result_copy,
            result_sha256=canonical_sha256(result_copy),
            origin=origin,
        )
        previous = self._entries.get(entry.cache_key_sha256)
        self._insert_verified(entry)
        if previous is not None:
            return False
        rows = sorted(self._entries.values(), key=lambda item: item.cache_key_sha256)
        temporary = self.path.with_suffix(".jsonl.tmp")
        temporary.write_text(
            "".join(item.model_dump_json() + "\n" for item in rows),
            "utf-8",
        )
        temporary.replace(self.path)
        return True


__all__ = [
    "CatalogEvaluationCache",
    "EvaluationCacheEntryV1",
    "EvaluationCacheKeyV1",
]
