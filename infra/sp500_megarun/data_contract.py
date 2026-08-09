"""Validation for the free-data contract used by the 120-lane SP500 mega-run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class DataContractError(ValueError):
    """Raised when the mega-run data contract fails closed."""


@dataclass(frozen=True)
class Boundaries:
    search_start: date
    search_end: date
    evaluation_start: date
    evaluation_end: date
    validation_opened: bool
    locked_opened: bool


@dataclass(frozen=True)
class DatasetContract:
    dataset_id: str
    provider: str
    url: str
    cost: str
    license_status: str
    coverage_start: date
    causal_coverage_start: date
    coverage_end: str
    causal_lag: str
    adapter: str
    readiness: str


@dataclass(frozen=True)
class LaneContract:
    lane_id: str
    required_datasets: tuple[str, ...]
    fidelity: str
    original_dependency: str
    replacement_note: str


@dataclass(frozen=True)
class FreeDataContract:
    path: Path
    sha256: str
    boundaries: Boundaries
    datasets: Mapping[str, DatasetContract]
    lanes: tuple[LaneContract, ...]


@dataclass(frozen=True)
class SnapshotValidation:
    dataset_count: int
    maximum_date: date


@dataclass(frozen=True)
class SourcePlanItem:
    dataset_id: str
    execution: str
    acquisition_kind: str
    adapter: str
    maximum_observation_date: date
    resources: tuple[Mapping[str, Any], ...]


def _parse_date(value: Any, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DataContractError(f"INVALID_DATE:{label}:{value}") from exc


def _read_payload(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise DataContractError(f"CONTRACT_NOT_FOUND:{path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataContractError(f"INVALID_CONTRACT_JSON:{path}") from exc
    if not isinstance(payload, Mapping):
        raise DataContractError("CONTRACT_ROOT_NOT_OBJECT")
    return raw, payload


def _validate_payload(payload: Mapping[str, Any], *, path: Path) -> FreeDataContract:
    raw_boundaries = payload.get("boundaries")
    if not isinstance(raw_boundaries, Mapping):
        raise DataContractError("MISSING_BOUNDARIES")
    boundaries = Boundaries(
        search_start=_parse_date(raw_boundaries.get("search_start"), label="search_start"),
        search_end=_parse_date(raw_boundaries.get("search_end"), label="search_end"),
        evaluation_start=_parse_date(
            raw_boundaries.get("evaluation_start"), label="evaluation_start"
        ),
        evaluation_end=_parse_date(raw_boundaries.get("evaluation_end"), label="evaluation_end"),
        validation_opened=bool(raw_boundaries.get("validation_opened")),
        locked_opened=bool(raw_boundaries.get("locked_opened")),
    )
    if boundaries.validation_opened:
        raise DataContractError("VALIDATION_MUST_REMAIN_CLOSED")
    if boundaries.locked_opened:
        raise DataContractError("LOCKED_MUST_REMAIN_CLOSED")
    if not (
        boundaries.search_start <= boundaries.search_end
        < boundaries.evaluation_start
        <= boundaries.evaluation_end
    ):
        raise DataContractError("INVALID_PHASE_ORDER")

    raw_datasets = payload.get("datasets")
    if not isinstance(raw_datasets, Mapping) or not raw_datasets:
        raise DataContractError("MISSING_DATASETS")
    datasets: dict[str, DatasetContract] = {}
    for dataset_id, raw_dataset in raw_datasets.items():
        if not isinstance(raw_dataset, Mapping):
            raise DataContractError(f"INVALID_DATASET:{dataset_id}")
        cost = str(raw_dataset.get("cost", ""))
        if cost != "free":
            raise DataContractError(f"NON_FREE_DATASET:{dataset_id}")
        coverage_start = _parse_date(
            raw_dataset.get("coverage_start"), label=f"{dataset_id}.coverage_start"
        )
        if coverage_start > boundaries.search_start:
            raise DataContractError(f"SEARCH_COVERAGE_GAP:{dataset_id}")
        causal_coverage_start = _parse_date(
            raw_dataset.get("causal_coverage_start", raw_dataset.get("coverage_start")),
            label=f"{dataset_id}.causal_coverage_start",
        )
        if causal_coverage_start > boundaries.search_start:
            raise DataContractError(f"CAUSAL_SEARCH_COVERAGE_GAP:{dataset_id}")
        readiness = str(raw_dataset.get("readiness", ""))
        if readiness != "source_and_adapter_ready":
            raise DataContractError(f"DATASET_NOT_READY:{dataset_id}:{readiness}")
        datasets[str(dataset_id)] = DatasetContract(
            dataset_id=str(dataset_id),
            provider=str(raw_dataset.get("provider", "")),
            url=str(raw_dataset.get("url", "")),
            cost=cost,
            license_status=str(raw_dataset.get("license_status", "")),
            coverage_start=coverage_start,
            causal_coverage_start=causal_coverage_start,
            coverage_end=str(raw_dataset.get("coverage_end", "")),
            causal_lag=str(raw_dataset.get("causal_lag", "")),
            adapter=str(raw_dataset.get("adapter", "")),
            readiness=readiness,
        )

    raw_lanes = payload.get("lanes")
    if not isinstance(raw_lanes, list) or len(raw_lanes) != 120:
        raise DataContractError(f"EXPECTED_120_LANES:{len(raw_lanes or [])}")
    lanes: list[LaneContract] = []
    for index, raw_lane in enumerate(raw_lanes, start=1):
        if not isinstance(raw_lane, Mapping):
            raise DataContractError(f"INVALID_LANE_AT:{index}")
        expected_id = f"F{index:03d}"
        lane_id = str(raw_lane.get("lane_id", ""))
        if lane_id != expected_id:
            raise DataContractError(f"NON_CONTIGUOUS_LANE:{expected_id}:{lane_id}")
        required = tuple(str(item) for item in raw_lane.get("required_datasets", ()))
        if not required:
            raise DataContractError(f"NO_DATASET_FOR_LANE:{lane_id}")
        for dataset_id in required:
            if dataset_id not in datasets:
                raise DataContractError(f"UNKNOWN_DATASET:{lane_id}:{dataset_id}")
        fidelity = str(raw_lane.get("fidelity", ""))
        replacement_note = str(raw_lane.get("replacement_note", "")).strip()
        if fidelity not in {"exact", "proxy", "redesigned"}:
            raise DataContractError(f"INVALID_FIDELITY:{lane_id}:{fidelity}")
        if fidelity != "exact" and not replacement_note:
            raise DataContractError(f"UNDISCLOSED_REPLACEMENT:{lane_id}")
        lanes.append(
            LaneContract(
                lane_id=lane_id,
                required_datasets=required,
                fidelity=fidelity,
                original_dependency=str(raw_lane.get("original_dependency", "")),
                replacement_note=replacement_note,
            )
        )

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return FreeDataContract(
        path=path,
        sha256=hashlib.sha256(canonical).hexdigest(),
        boundaries=boundaries,
        datasets=datasets,
        lanes=tuple(lanes),
    )


def load_and_validate_contract(path: Path) -> FreeDataContract:
    """Load a contract and reject any paid, incomplete, or temporally invalid input."""

    _, payload = _read_payload(path)
    return _validate_payload(payload, path=path)


def load_and_validate_source_plan(
    path: Path, contract: FreeDataContract
) -> Mapping[str, SourcePlanItem]:
    """Validate that every contracted dataset has a bounded GitHub-only acquisition plan."""

    _, payload = _read_payload(path)
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, Mapping):
        raise DataContractError("SOURCE_PLAN_MISSING_SOURCES")
    expected = set(contract.datasets)
    actual = set(str(item) for item in raw_sources)
    if expected - actual:
        raise DataContractError(f"SOURCE_PLAN_MISSING:{','.join(sorted(expected - actual))}")
    if actual - expected:
        raise DataContractError(f"SOURCE_PLAN_UNEXPECTED:{','.join(sorted(actual - expected))}")
    result: dict[str, SourcePlanItem] = {}
    for dataset_id in sorted(expected):
        raw_item = raw_sources[dataset_id]
        if not isinstance(raw_item, Mapping):
            raise DataContractError(f"SOURCE_PLAN_INVALID:{dataset_id}")
        execution = str(raw_item.get("execution", ""))
        if execution != "github_actions_only":
            raise DataContractError(f"SOURCE_PLAN_NOT_GITHUB_ONLY:{dataset_id}")
        adapter = str(raw_item.get("adapter", ""))
        if adapter != contract.datasets[dataset_id].adapter:
            raise DataContractError(f"SOURCE_PLAN_ADAPTER_MISMATCH:{dataset_id}")
        maximum_date = _parse_date(
            raw_item.get("maximum_observation_date"),
            label=f"{dataset_id}.maximum_observation_date",
        )
        if maximum_date != contract.boundaries.evaluation_end:
            raise DataContractError(f"SOURCE_PLAN_BOUNDARY_MISMATCH:{dataset_id}")
        acquisition_kind = str(raw_item.get("acquisition_kind", ""))
        if acquisition_kind not in {"existing", "direct", "bundle", "derived"}:
            raise DataContractError(f"SOURCE_PLAN_KIND_INVALID:{dataset_id}")
        raw_resources = raw_item.get("resources", [])
        if not isinstance(raw_resources, list):
            raise DataContractError(f"SOURCE_PLAN_RESOURCES_INVALID:{dataset_id}")
        if acquisition_kind in {"direct", "bundle"} and not raw_resources:
            raise DataContractError(f"SOURCE_PLAN_RESOURCES_MISSING:{dataset_id}")
        result[dataset_id] = SourcePlanItem(
            dataset_id=dataset_id,
            execution=execution,
            acquisition_kind=acquisition_kind,
            adapter=adapter,
            maximum_observation_date=maximum_date,
            resources=tuple(item for item in raw_resources if isinstance(item, Mapping)),
        )
    return result


def validate_snapshot_manifest(
    contract_payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    expected_contract_path: Path,
    verify_contract_hash: bool = True,
) -> SnapshotValidation:
    """Prove that a generated snapshot covers every contracted dataset and no later phase."""

    contract = _validate_payload(contract_payload, path=expected_contract_path)
    if verify_contract_hash and manifest.get("contract_sha256") != contract.sha256:
        raise DataContractError("CONTRACT_HASH_MISMATCH")
    manifest_datasets = manifest.get("datasets")
    if not isinstance(manifest_datasets, Mapping):
        raise DataContractError("SNAPSHOT_DATASETS_MISSING")
    expected = set(contract.datasets)
    actual = set(str(item) for item in manifest_datasets)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise DataContractError(f"SNAPSHOT_DATASET_MISSING:{','.join(missing)}")
    if extra:
        raise DataContractError(f"SNAPSHOT_DATASET_UNEXPECTED:{','.join(extra)}")

    maximum_dates: list[date] = []
    for dataset_id in sorted(expected):
        row = manifest_datasets[dataset_id]
        if not isinstance(row, Mapping):
            raise DataContractError(f"INVALID_SNAPSHOT_ROW:{dataset_id}")
        if int(row.get("row_count", 0)) <= 0:
            raise DataContractError(f"EMPTY_SNAPSHOT:{dataset_id}")
        if not row.get("schema_valid"):
            raise DataContractError(f"SCHEMA_INVALID:{dataset_id}")
        if not row.get("causal_valid"):
            raise DataContractError(f"CAUSALITY_INVALID:{dataset_id}")
        sha256 = str(row.get("sha256", ""))
        if len(sha256) != 64:
            raise DataContractError(f"INVALID_SNAPSHOT_HASH:{dataset_id}")
        maximum_date = _parse_date(row.get("maximum_date"), label=f"{dataset_id}.maximum_date")
        if maximum_date > contract.boundaries.evaluation_end:
            raise DataContractError(f"POST_EVALUATION_DATA:{dataset_id}")
        maximum_dates.append(maximum_date)

    return SnapshotValidation(
        dataset_count=len(expected),
        maximum_date=max(maximum_dates),
    )
