"""Verified incremental resume planning for optimized catalog runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from pydantic import Field

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)
from aurora.infra.github_performance.shard_planner import sha256_file


def _scientific_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _scientific_value(item)
            for key, item in sorted(value.items())
            if key != "objective_runtime_seconds"
        }
    if isinstance(value, list):
        return [_scientific_value(item) for item in value]
    return value


def scientific_result_sha256(result: dict[str, Any]) -> str:
    payload = json.dumps(
        _scientific_value(result),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(b"catalog-resume-result-v1\0" + payload).hexdigest()


class ResumeResultV1(FrozenModel):
    strategy_id: str = Field(min_length=1)
    result_json: str = Field(min_length=2)
    scientific_result_sha256: Sha256
    source_path: str = Field(min_length=1)


class CatalogResumeIndexV1(FrozenModel):
    schema_version: str = "1"
    science_identity_sha256: Sha256
    catalog_manifest_sha256: Sha256
    results: tuple[ResumeResultV1, ...]
    strategy_ids: tuple[str, ...]
    physical_result_count: int = Field(ge=0)
    duplicate_result_count: int = Field(ge=0)
    validation_opened: bool = False
    locked_opened: bool = False
    index_sha256: Sha256


class CatalogResumeWorkManifestV1(FrozenModel):
    schema_version: str = "1"
    all_strategy_ids: tuple[str, ...]
    cached_strategy_ids: tuple[str, ...]
    pending_strategy_ids: tuple[str, ...]
    active_workers: int = Field(ge=0, le=360)
    validation_opened: bool = False
    locked_opened: bool = False
    manifest_sha256: Sha256

    def assign(self, shard_index: int) -> tuple[str, ...]:
        if not 0 <= shard_index < self.active_workers:
            raise ValueError("RESUME_WORKER_INDEX_INVALID")
        return self.pending_strategy_ids[shard_index :: self.active_workers]


def _result_partitions(root: Path) -> Iterable[tuple[Path, Path]]:
    root = Path(root)
    if (root / "results.parquet").is_file() and (root / "receipt.json").is_file():
        yield root / "results.parquet", root / "receipt.json"
        return
    for result_path in sorted(root.rglob("results.parquet")):
        receipt_path = result_path.parent / "receipt.json"
        if receipt_path.is_file():
            yield result_path, receipt_path


def load_resume_index(
    roots: Sequence[Path],
    *,
    expected_science_identity_sha256: str,
    expected_catalog_manifest_sha256: str,
) -> CatalogResumeIndexV1:
    by_strategy: dict[str, ResumeResultV1] = {}
    physical_count = 0
    duplicate_count = 0
    source_count = 0
    for root in roots:
        for result_path, receipt_path in _result_partitions(Path(root)):
            source_count += 1
            try:
                receipt = json.loads(receipt_path.read_text("utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("RESUME_SOURCE_RECEIPT_INVALID") from exc
            if (
                receipt.get("science_identity_sha256")
                != expected_science_identity_sha256
                or receipt.get("catalog_manifest_sha256")
                != expected_catalog_manifest_sha256
                or receipt.get("validation_opened") is not False
                or receipt.get("locked_opened") is not False
                or receipt.get("result_sha256") != sha256_file(result_path)
            ):
                raise ValueError("RESUME_SOURCE_INCOMPATIBLE")
            table = pq.read_table(result_path, columns=["strategy_id", "result_json"])
            for row in table.to_pylist():
                strategy_id = str(row["strategy_id"])
                result_json = str(row["result_json"])
                try:
                    result = json.loads(result_json)
                except ValueError as exc:
                    raise ValueError("RESUME_RESULT_INVALID") from exc
                if not isinstance(result, dict):
                    raise ValueError("RESUME_RESULT_INVALID")
                result_sha256 = scientific_result_sha256(result)
                candidate = ResumeResultV1(
                    strategy_id=strategy_id,
                    result_json=result_json,
                    scientific_result_sha256=result_sha256,
                    source_path=str(result_path),
                )
                physical_count += 1
                previous = by_strategy.get(strategy_id)
                if previous is not None:
                    duplicate_count += 1
                    if previous.scientific_result_sha256 != result_sha256:
                        raise ValueError("RESUME_RESULT_CONFLICT")
                    continue
                by_strategy[strategy_id] = candidate
    if roots and source_count == 0:
        raise ValueError("RESUME_SOURCE_RESULTS_MISSING")
    results = tuple(by_strategy[key] for key in sorted(by_strategy))
    identity = {
        "schema_version": "1",
        "science_identity_sha256": expected_science_identity_sha256,
        "catalog_manifest_sha256": expected_catalog_manifest_sha256,
        "results": results,
        "strategy_ids": tuple(item.strategy_id for item in results),
        "physical_result_count": physical_count,
        "duplicate_result_count": duplicate_count,
        "validation_opened": False,
        "locked_opened": False,
    }
    return CatalogResumeIndexV1(
        **identity,
        index_sha256=canonical_sha256(identity),
    )


def build_resume_work_manifest(
    strategy_ids: Sequence[str],
    *,
    cached_strategy_ids: Sequence[str],
    maximum_workers: int,
) -> CatalogResumeWorkManifestV1:
    all_ids = tuple(str(value) for value in strategy_ids)
    if not all_ids or len(set(all_ids)) != len(all_ids):
        raise ValueError("RESUME_STRATEGY_SET_INVALID")
    cached_set = {str(value) for value in cached_strategy_ids}
    if not cached_set.issubset(all_ids):
        raise ValueError("RESUME_CACHE_STRATEGY_UNKNOWN")
    cached = tuple(value for value in all_ids if value in cached_set)
    pending = tuple(value for value in all_ids if value not in cached_set)
    if not 1 <= maximum_workers <= 360:
        raise ValueError("RESUME_MAXIMUM_WORKERS_INVALID")
    active_workers = min(maximum_workers, len(pending))
    identity = {
        "schema_version": "1",
        "all_strategy_ids": all_ids,
        "cached_strategy_ids": cached,
        "pending_strategy_ids": pending,
        "active_workers": active_workers,
        "validation_opened": False,
        "locked_opened": False,
    }
    return CatalogResumeWorkManifestV1(
        **identity,
        manifest_sha256=canonical_sha256(identity),
    )


__all__ = [
    "CatalogResumeIndexV1",
    "CatalogResumeWorkManifestV1",
    "ResumeResultV1",
    "build_resume_work_manifest",
    "load_resume_index",
    "scientific_result_sha256",
]
