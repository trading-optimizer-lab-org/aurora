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


class CatalogResultCheckpointV1(FrozenModel):
    schema_version: str = "1"
    contract_sha256: Sha256
    row_count: int = Field(ge=0)
    partition_count: int = Field(ge=0)
    partitions: tuple[ResultPartitionV1, ...]
    last_strategy_id: str | None
    validation_opened: bool = False
    locked_opened: bool = False
    checkpoint_sha256: Sha256


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


class CatalogStreamingResultWriter:
    """Bounded-memory, atomic Parquet writer that resumes committed partitions."""

    def __init__(
        self,
        root: Path,
        *,
        contract_sha256: str,
        partition_size: int = 65_536,
        resume: bool = False,
    ) -> None:
        if partition_size < 1:
            raise ValueError("RESULT_PARTITION_SIZE_INVALID")
        self.root = Path(root)
        self.contract_sha256 = contract_sha256
        self.partition_size = partition_size
        self._buffer: list[dict[str, object]] = []
        self._partitions: list[ResultPartitionV1] = []
        self._row_count = 0
        self._last_strategy_id: str | None = None
        self.max_buffered_rows = 0
        if resume:
            self._restore()
        else:
            self.root.mkdir(parents=True, exist_ok=False)

    @staticmethod
    def _checkpoint_identity(
        *,
        contract_sha256: str,
        row_count: int,
        partitions: tuple[ResultPartitionV1, ...],
        last_strategy_id: str | None,
    ) -> dict[str, object]:
        return {
            "schema_version": "1",
            "contract_sha256": contract_sha256,
            "row_count": row_count,
            "partition_count": len(partitions),
            "partitions": partitions,
            "last_strategy_id": last_strategy_id,
            "validation_opened": False,
            "locked_opened": False,
        }

    def _restore(self) -> None:
        try:
            checkpoint = CatalogResultCheckpointV1.model_validate_json(
                (self.root / "checkpoint.json").read_text("utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ValueError("RESULT_CHECKPOINT_INVALID") from exc
        identity = checkpoint.model_dump(
            mode="python",
            exclude={"checkpoint_sha256"},
        )
        if canonical_sha256(identity) != checkpoint.checkpoint_sha256:
            raise ValueError("RESULT_CHECKPOINT_HASH_INVALID")
        if checkpoint.contract_sha256 != self.contract_sha256:
            raise ValueError("RESULT_CHECKPOINT_CONTRACT_MISMATCH")
        if (
            checkpoint.partition_count != len(checkpoint.partitions)
            or checkpoint.row_count
            != sum(item.row_count for item in checkpoint.partitions)
        ):
            raise ValueError("RESULT_CHECKPOINT_COUNT_INVALID")
        for item in checkpoint.partitions:
            if sha256_file(self.root / item.path) != item.sha256:
                raise ValueError("RESULT_CHECKPOINT_PARTITION_INVALID")
        self._partitions = list(checkpoint.partitions)
        self._row_count = checkpoint.row_count
        self._last_strategy_id = checkpoint.last_strategy_id

    def _write_checkpoint(self) -> CatalogResultCheckpointV1:
        partitions = tuple(self._partitions)
        identity = self._checkpoint_identity(
            contract_sha256=self.contract_sha256,
            row_count=self._row_count,
            partitions=partitions,
            last_strategy_id=self._last_strategy_id,
        )
        checkpoint = CatalogResultCheckpointV1(
            **identity,
            checkpoint_sha256=canonical_sha256(identity),
        )
        target = self.root / "checkpoint.json"
        temporary = self.root / "checkpoint.json.tmp"
        temporary.write_text(checkpoint.model_dump_json(indent=2) + "\n", "utf-8")
        temporary.replace(target)
        return checkpoint

    def _flush(self) -> None:
        if not self._buffer:
            return
        table = pa.Table.from_pylist(self._buffer, schema=_SCHEMA)
        row_count = len(self._buffer)
        self._buffer.clear()
        self._write_table(table, row_count=row_count)

    def _write_table(self, table: pa.Table, *, row_count: int) -> None:
        index = len(self._partitions)
        path = self.root / f"part-{index:08d}.parquet"
        temporary = self.root / f"part-{index:08d}.parquet.tmp"
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            use_dictionary=True,
        )
        temporary.replace(path)
        self._partitions.append(
            ResultPartitionV1(
                path=path.name,
                sha256=sha256_file(path),
                row_count=row_count,
            )
        )
        self._row_count += row_count
        self._write_checkpoint()

    def add(self, row: Mapping[str, object]) -> None:
        checked = {name: row[name] for name in _SCHEMA.names}
        strategy_id = str(checked["strategy_id"])
        if self._last_strategy_id is not None and strategy_id <= self._last_strategy_id:
            raise ValueError("RESULT_STREAM_ORDER_OR_DUPLICATE_INVALID")
        self._last_strategy_id = strategy_id
        self._buffer.append(checked)
        self.max_buffered_rows = max(self.max_buffered_rows, len(self._buffer))
        if len(self._buffer) >= self.partition_size:
            self._flush()

    def append_table(self, table: pa.Table) -> None:
        """Append an ordered Arrow batch without materializing Python row dicts."""

        self._flush()
        try:
            checked = table.select(_SCHEMA.names).cast(_SCHEMA).combine_chunks()
        except (KeyError, pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
            raise ValueError("RESULT_STREAM_TABLE_SCHEMA_INVALID") from exc
        if checked.num_rows == 0:
            return
        strategy_ids = checked.column("strategy_id").to_pylist()
        if any(
            str(current) >= str(following)
            for current, following in zip(
                strategy_ids,
                strategy_ids[1:],
            )
        ):
            raise ValueError("RESULT_STREAM_ORDER_OR_DUPLICATE_INVALID")
        first = str(strategy_ids[0])
        if self._last_strategy_id is not None and first <= self._last_strategy_id:
            raise ValueError("RESULT_STREAM_ORDER_OR_DUPLICATE_INVALID")
        for start in range(0, checked.num_rows, self.partition_size):
            chunk = checked.slice(start, self.partition_size)
            self._last_strategy_id = str(
                chunk.column("strategy_id")[chunk.num_rows - 1].as_py()
            )
            self._write_table(chunk, row_count=chunk.num_rows)

    def checkpoint(self) -> CatalogResultCheckpointV1:
        self._flush()
        return self._write_checkpoint()

    def commit(self) -> CatalogResultManifestV1:
        self._flush()
        if self._row_count == 0:
            raise ValueError("RESULT_STORE_EMPTY")
        partitions = tuple(self._partitions)
        identity = {
            "schema_version": "1",
            "contract_sha256": self.contract_sha256,
            "row_count": self._row_count,
            "partition_count": len(partitions),
            "partitions": partitions,
            "validation_opened": False,
            "locked_opened": False,
        }
        manifest = CatalogResultManifestV1(
            **identity,
            manifest_sha256=canonical_sha256(identity),
        )
        target = self.root / "manifest.json"
        temporary = self.root / "manifest.json.tmp"
        temporary.write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
        temporary.replace(target)
        return manifest


__all__ = [
    "CatalogResultManifestV1",
    "CatalogResultCheckpointV1",
    "CatalogResultStore",
    "CatalogStreamingResultWriter",
    "CatalogResultWriter",
    "ResultPartitionV1",
]
