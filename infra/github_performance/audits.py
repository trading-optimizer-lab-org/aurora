"""Runtime-derived data, policy, execution, and provenance audits."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    RunSpec,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.shard_planner import sha256_file


AUDIT_SCHEMA_VERSION = "1"


class RuntimePolicyViolation(RuntimeError):
    """Raised when observed data access contradicts the frozen policy."""


class DataAccessRecord(FrozenModel):
    """One exact runtime read from a dated data partition."""

    source: str
    partition: str
    minimum_date: date | None
    maximum_date: date | None
    row_count: int = Field(ge=0)
    split: Literal["train", "validation", "locked", "other"]
    purpose: Literal["selection", "report", "preparation"]
    locked: bool
    shard_id: str
    attempt_id: str

    @model_validator(mode="after")
    def _validate_dates(self) -> DataAccessRecord:
        if self.row_count:
            if self.minimum_date is None or self.maximum_date is None:
                raise ValueError("non-empty access requires minimum and maximum dates")
            if self.minimum_date > self.maximum_date:
                raise ValueError("minimum_date must not exceed maximum_date")
        elif self.minimum_date is not None or self.maximum_date is not None:
            raise ValueError("empty access must not declare dates")
        return self


class RuntimeAccessLedger(FrozenModel):
    schema_version: Literal["1"] = AUDIT_SCHEMA_VERSION
    records: tuple[DataAccessRecord, ...]


class DataAudit(FrozenModel):
    schema_version: Literal["1"] = AUDIT_SCHEMA_VERSION
    access_record_count: int = Field(ge=0)
    rows_accessed: int = Field(ge=0)
    locked_rows_accessed: int = Field(ge=0)
    selection_rows_accessed: int = Field(ge=0)
    report_rows_accessed: int = Field(ge=0)
    minimum_accessed_date: date | None
    maximum_accessed_date: date | None
    rows_by_split: Mapping[str, int]


class PolicyAudit(FrozenModel):
    schema_version: Literal["1"] = AUDIT_SCHEMA_VERSION
    locked_opened: bool
    locked_rows_accessed: int = Field(ge=0)
    validation_used_for_selection: bool
    maximum_selection_date: date | None
    train_end: date
    validation_end: date
    locked_start: date
    evidence_source: Literal["runtime_access_ledger"]


class RuntimeAudit(FrozenModel):
    schema_version: Literal["1"] = AUDIT_SCHEMA_VERSION
    github_only_run: bool
    runner_label: str
    standard_runner_only: bool
    larger_runner_used: bool
    access_ledger_sha256: str


class ProvenanceRecord(FrozenModel):
    schema_version: Literal["1"] = AUDIT_SCHEMA_VERSION
    code_sha: str
    workflow_sha256: str
    environment_sha256: str
    spec_sha256: str
    policy_hash: str
    snapshot_hash: str
    runtime_access_ledger_sha256: str


class RequiredAudits(FrozenModel):
    data: DataAudit
    policy: PolicyAudit
    runtime: RuntimeAudit
    provenance: ProvenanceRecord
    access_ledger: RuntimeAccessLedger


ACCESS_SCHEMA = pa.schema(
    [
        pa.field("source", pa.string(), nullable=False),
        pa.field("partition", pa.string(), nullable=False),
        pa.field("minimum_date", pa.date32(), nullable=True),
        pa.field("maximum_date", pa.date32(), nullable=True),
        pa.field("row_count", pa.int64(), nullable=False),
        pa.field("split", pa.string(), nullable=False),
        pa.field("purpose", pa.string(), nullable=False),
        pa.field("locked", pa.bool_(), nullable=False),
        pa.field("shard_id", pa.string(), nullable=False),
        pa.field("attempt_id", pa.string(), nullable=False),
    ],
    metadata={b"schema_version": AUDIT_SCHEMA_VERSION.encode("ascii")},
)


def _atomic_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            deep_thaw_json(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def write_runtime_access_ledger(
    path: Path,
    ledger: RuntimeAccessLedger,
) -> Path:
    """Write a deterministic Parquet ledger for one shard or merge."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        record.model_dump(mode="python")
        for record in sorted(
            ledger.records,
            key=lambda item: (
                item.shard_id,
                item.attempt_id,
                item.source,
                item.partition,
                item.purpose,
                item.minimum_date or date.min,
            ),
        )
    ]
    table = pa.Table.from_pylist(rows, schema=ACCESS_SCHEMA)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", version="2.6")
    temporary.replace(path)
    return path


def read_runtime_access_ledger(path: Path) -> RuntimeAccessLedger:
    path = Path(path)
    parquet = pq.ParquetFile(path)
    metadata = parquet.schema_arrow.metadata or {}
    if metadata.get(b"schema_version") != AUDIT_SCHEMA_VERSION.encode("ascii"):
        raise ValueError("runtime access ledger schema version mismatch")
    records = tuple(
        DataAccessRecord.model_validate(row)
        for row in parquet.read().to_pylist()
    )
    return RuntimeAccessLedger(records=records)


def combine_runtime_access_ledgers(
    paths: Sequence[Path],
) -> RuntimeAccessLedger:
    records: list[DataAccessRecord] = []
    for path in sorted(Path(item) for item in paths):
        records.extend(read_runtime_access_ledger(path).records)
    return RuntimeAccessLedger(records=tuple(records))


def _positive_records(
    ledger: RuntimeAccessLedger,
) -> tuple[DataAccessRecord, ...]:
    return tuple(record for record in ledger.records if record.row_count > 0)


def build_required_audits(
    spec: RunSpec,
    ledger: RuntimeAccessLedger,
    environment: Mapping[str, Any],
) -> RequiredAudits:
    """Derive hard policy evidence from observed runtime reads."""

    records = _positive_records(ledger)
    train_end = date.fromisoformat(str(spec.policy["train_end"]))
    validation_end = date.fromisoformat(str(spec.policy["validation_end"]))
    locked_start = date.fromisoformat(str(spec.policy["locked_start"]))
    errors: list[str] = []
    locked_rows = 0
    validation_selection = False
    maximum_selection_date: date | None = None
    for record in records:
        maximum = record.maximum_date
        minimum = record.minimum_date
        assert maximum is not None and minimum is not None
        is_locked = (
            record.locked
            or record.split == "locked"
            or maximum >= locked_start
        )
        if is_locked:
            locked_rows += record.row_count
        if maximum > validation_end:
            errors.append("DATA_AFTER_VALIDATION_END")
        if record.purpose == "selection":
            if (
                maximum_selection_date is None
                or maximum > maximum_selection_date
            ):
                maximum_selection_date = maximum
            if maximum > train_end:
                validation_selection = True
    if locked_rows:
        errors.append("LOCKED_ROWS_ACCESSED")
    if validation_selection:
        errors.append("VALIDATION_USED_FOR_SELECTION")
    if errors:
        raise RuntimePolicyViolation(",".join(sorted(set(errors))))

    minimum_dates = [
        record.minimum_date
        for record in records
        if record.minimum_date is not None
    ]
    maximum_dates = [
        record.maximum_date
        for record in records
        if record.maximum_date is not None
    ]
    split_counts = Counter[str]()
    for record in records:
        split_counts[record.split] += record.row_count
    ledger_hash = canonical_sha256(ledger)
    runner_label = str(environment.get("runner_label", ""))
    github_only = environment.get("github_actions") is True
    larger_runner_used = environment.get("larger_runner_used") is True
    standard_runner_only = (
        github_only
        and runner_label == "ubuntu-24.04"
        and not larger_runner_used
    )
    data = DataAudit(
        access_record_count=len(records),
        rows_accessed=sum(record.row_count for record in records),
        locked_rows_accessed=locked_rows,
        selection_rows_accessed=sum(
            record.row_count
            for record in records
            if record.purpose == "selection"
        ),
        report_rows_accessed=sum(
            record.row_count
            for record in records
            if record.purpose == "report"
        ),
        minimum_accessed_date=min(minimum_dates) if minimum_dates else None,
        maximum_accessed_date=max(maximum_dates) if maximum_dates else None,
        rows_by_split=dict(sorted(split_counts.items())),
    )
    policy = PolicyAudit(
        locked_opened=bool(locked_rows),
        locked_rows_accessed=locked_rows,
        validation_used_for_selection=validation_selection,
        maximum_selection_date=maximum_selection_date,
        train_end=train_end,
        validation_end=validation_end,
        locked_start=locked_start,
        evidence_source="runtime_access_ledger",
    )
    runtime = RuntimeAudit(
        github_only_run=github_only,
        runner_label=runner_label,
        standard_runner_only=standard_runner_only,
        larger_runner_used=larger_runner_used,
        access_ledger_sha256=ledger_hash,
    )
    provenance = ProvenanceRecord(
        code_sha=str(
            environment.get("code_sha", spec.identity.get("code_sha", ""))
        ),
        workflow_sha256=str(environment.get("workflow_sha256", "")),
        environment_sha256=str(environment.get("environment_sha256", "")),
        spec_sha256=canonical_sha256(spec),
        policy_hash=str(spec.policy["policy_hash"]),
        snapshot_hash=str(spec.data["snapshot_hash"]),
        runtime_access_ledger_sha256=ledger_hash,
    )
    return RequiredAudits(
        data=data,
        policy=policy,
        runtime=runtime,
        provenance=provenance,
        access_ledger=ledger,
    )


def write_required_audits(
    root: Path,
    audits: RequiredAudits,
) -> tuple[Path, ...]:
    root = Path(root)
    ledger_path = write_runtime_access_ledger(
        root / "runtime_access_ledger.parquet",
        audits.access_ledger,
    )
    paths = (
        _atomic_json(root / "data_audit.json", audits.data),
        _atomic_json(root / "policy_audit.json", audits.policy),
        _atomic_json(root / "runtime_audit.json", audits.runtime),
        _atomic_json(root / "provenance.json", audits.provenance),
        ledger_path,
    )
    if sha256_file(ledger_path) == "":
        raise AssertionError("runtime access ledger hash must not be empty")
    return paths
