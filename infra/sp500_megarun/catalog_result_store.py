"""Partitioned Parquet result transport with immutable verification."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, Sha256, canonical_sha256
from aurora.infra.github_performance.shard_planner import sha256_file


_SCHEMA = pa.schema(
    [
        ("strategy_id", pa.string()),
        ("recipe_sha256", pa.string()),
        ("position_sha256", pa.string()),
        ("annualized_return", pa.float64()),
        ("weekly_positive_rate", pa.float64()),
    ]
)


class ResultPartitionV1(FrozenModel):
    path: str
    sha256: Sha256
    row_count: int = Field(ge=1)


class CatalogResultManifestV1(FrozenModel):
    schema_version: str = "1"
    contract_sha256: Sha256
    row_count: int = Field(ge=1)
    partition_count: int = Field(ge=1)
    partitions: tuple[ResultPartitionV1, ...]
    validation_opened: bool = False
    locked_opened: bool = False
    manifest_sha256: Sha256


class CatalogResultWriter:
    def __init__(
        self,
        root: Path,
        *,
        contract_sha256: str,
        partition_size: int = 4096,
    ) -> None:
        if partition_size < 1:
            raise ValueError("RESULT_PARTITION_SIZE_INVALID")
        self.root = Path(root)
        self.contract_sha256 = contract_sha256
        self.partition_size = partition_size
        self._rows: dict[str, dict[str, object]] = {}

    def add(self, row: Mapping[str, object]) -> bool:
        checked = {name: row[name] for name in _SCHEMA.names}
        recipe_sha256 = str(checked["recipe_sha256"])
        previous = self._rows.get(recipe_sha256)
        if previous is not None:
            if previous != checked:
                raise ValueError("RESULT_STORE_CONFLICT")
            return False
        self._rows[recipe_sha256] = checked
        return True

    def commit(self) -> CatalogResultManifestV1:
        if not self._rows:
            raise ValueError("RESULT_STORE_EMPTY")
        self.root.mkdir(parents=True, exist_ok=False)
        rows = sorted(self._rows.values(), key=lambda row: str(row["strategy_id"]))
        partitions: list[ResultPartitionV1] = []
        for index, start in enumerate(range(0, len(rows), self.partition_size)):
            chunk = rows[start : start + self.partition_size]
            path = self.root / f"part-{index:05d}.parquet"
            pq.write_table(
                pa.Table.from_pylist(chunk, schema=_SCHEMA),
                path,
                compression="zstd",
                use_dictionary=True,
            )
            partitions.append(
                ResultPartitionV1(
                    path=path.name,
                    sha256=sha256_file(path),
                    row_count=len(chunk),
                )
            )
        identity = {
            "schema_version": "1",
            "contract_sha256": self.contract_sha256,
            "row_count": len(rows),
            "partition_count": len(partitions),
            "partitions": partitions,
            "validation_opened": False,
            "locked_opened": False,
        }
        manifest = CatalogResultManifestV1(
            **identity,
            manifest_sha256=canonical_sha256(identity),
        )
        (self.root / "manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n",
            "utf-8",
        )
        return manifest


class CatalogResultStore:
    def __init__(self, root: Path, manifest: CatalogResultManifestV1) -> None:
        self.root = Path(root)
        self.manifest = manifest

    @classmethod
    def open(cls, root: Path) -> CatalogResultStore:
        root = Path(root)
        try:
            manifest = CatalogResultManifestV1.model_validate_json(
                (root / "manifest.json").read_text("utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ValueError("RESULT_STORE_MANIFEST_INVALID") from exc
        identity = manifest.model_dump(mode="python", exclude={"manifest_sha256"})
        if canonical_sha256(identity) != manifest.manifest_sha256:
            raise ValueError("RESULT_STORE_MANIFEST_HASH_INVALID")
        if sum(item.row_count for item in manifest.partitions) != manifest.row_count:
            raise ValueError("RESULT_STORE_ROW_COUNT_INVALID")
        for item in manifest.partitions:
            if sha256_file(root / item.path) != item.sha256:
                raise ValueError("RESULT_STORE_PARTITION_HASH_INVALID")
        return cls(root, manifest)

    def iter_rows(self) -> Iterator[dict[str, object]]:
        for partition in self.manifest.partitions:
            parquet = pq.ParquetFile(self.root / partition.path)
            for batch in parquet.iter_batches(batch_size=4096):
                yield from batch.to_pylist()


__all__ = [
    "CatalogResultManifestV1",
    "CatalogResultStore",
    "CatalogResultWriter",
    "ResultPartitionV1",
]
