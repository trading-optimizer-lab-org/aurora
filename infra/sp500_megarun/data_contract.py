"""Fail-closed validation for the free-data SP500 mega-run contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
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
    warmup_start: date | None = None
    locked_start: date | None = None

    @property
    def acquisition_start(self) -> date:
        """Earliest observation that may be needed for causal warm-up."""

        return self.warmup_start or self.search_start

    @property
    def forbidden_from(self) -> date:
        """First date that must be physically absent from preflight artifacts."""

        return self.locked_start or (self.evaluation_end + timedelta(days=1))


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
    available_at_rule: str
    required_coverage_start: date


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
    expected_lane_count: int


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


def _merge_contract_payload(
    payload: Mapping[str, Any], *, path: Path, seen: frozenset[Path] = frozenset()
) -> Mapping[str, Any]:
    """Expand a frozen v2 contract that inherits the audited v1 catalog."""

    extends = payload.get("extends")
    if not extends:
        return payload
    resolved = (path.parent / str(extends)).resolve()
    if resolved in seen or resolved == path.resolve():
        raise DataContractError("CONTRACT_INHERITANCE_CYCLE")
    _, base_raw = _read_payload(resolved)
    base = _merge_contract_payload(base_raw, path=resolved, seen=seen | {path.resolve()})
    merged: dict[str, Any] = dict(base)
    for key in ("schema_version", "contract_id", "expected_lane_count", "boundaries"):
        if key in payload:
            merged[key] = payload[key]

    datasets = {
        str(dataset_id): dict(row)
        for dataset_id, row in dict(base.get("datasets", {})).items()
    }
    for dataset_id in payload.get("remove_datasets", []):
        datasets.pop(str(dataset_id), None)
    for dataset_id, override in dict(payload.get("dataset_overrides", {})).items():
        if str(dataset_id) not in datasets:
            raise DataContractError(f"UNKNOWN_DATASET_OVERRIDE:{dataset_id}")
        datasets[str(dataset_id)].update(dict(override))
    for dataset_id, row in dict(payload.get("datasets", {})).items():
        datasets[str(dataset_id)] = dict(row)
    merged["datasets"] = datasets

    lanes = {
        str(row.get("lane_id")): dict(row)
        for row in base.get("lanes", [])
        if isinstance(row, Mapping)
    }
    for lane_id, override in dict(payload.get("lane_overrides", {})).items():
        if str(lane_id) not in lanes:
            raise DataContractError(f"UNKNOWN_LANE_OVERRIDE:{lane_id}")
        lanes[str(lane_id)].update(dict(override))
    for row in payload.get("lanes", []):
        if not isinstance(row, Mapping):
            raise DataContractError("INVALID_EXTENSION_LANE")
        lanes[str(row.get("lane_id"))] = dict(row)
    merged["lanes"] = [lanes[key] for key in sorted(lanes)]
    return merged


def _merge_source_payload(
    payload: Mapping[str, Any], *, path: Path, seen: frozenset[Path] = frozenset()
) -> Mapping[str, Any]:
    """Expand a source plan while preserving the reviewed v1 source declarations."""

    extends = payload.get("extends")
    if not extends:
        return payload
    resolved = (path.parent / str(extends)).resolve()
    if resolved in seen or resolved == path.resolve():
        raise DataContractError("SOURCE_INHERITANCE_CYCLE")
    _, base_raw = _read_payload(resolved)
    base = _merge_source_payload(base_raw, path=resolved, seen=seen | {path.resolve()})
    sources = {
        str(dataset_id): dict(row)
        for dataset_id, row in dict(base.get("sources", {})).items()
    }
    for dataset_id in payload.get("remove_sources", []):
        sources.pop(str(dataset_id), None)
    for dataset_id, override in dict(payload.get("source_overrides", {})).items():
        if str(dataset_id) not in sources:
            raise DataContractError(f"UNKNOWN_SOURCE_OVERRIDE:{dataset_id}")
        sources[str(dataset_id)].update(dict(override))
    for dataset_id, row in dict(payload.get("sources", {})).items():
        sources[str(dataset_id)] = dict(row)
    return {
        "schema_version": payload.get("schema_version", base.get("schema_version", 1)),
        "sources": sources,
    }


def _validate_payload(payload: Mapping[str, Any], *, path: Path) -> FreeDataContract:
    schema_version = int(payload.get("schema_version", 1))
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
        warmup_start=(
            _parse_date(raw_boundaries.get("warmup_start"), label="warmup_start")
            if raw_boundaries.get("warmup_start") is not None
            else None
        ),
        locked_start=(
            _parse_date(raw_boundaries.get("locked_start"), label="locked_start")
            if raw_boundaries.get("locked_start") is not None
            else None
        ),
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
    if boundaries.acquisition_start > boundaries.search_start:
        raise DataContractError("WARMUP_START_AFTER_SEARCH_START")
    if boundaries.forbidden_from <= boundaries.evaluation_end:
        raise DataContractError("LOCKED_START_NOT_AFTER_EVALUATION")

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
        required_coverage_start = _parse_date(
            raw_dataset.get("required_coverage_start", boundaries.search_start),
            label=f"{dataset_id}.required_coverage_start",
        )
        if not boundaries.acquisition_start <= required_coverage_start <= boundaries.search_start:
            raise DataContractError(f"INVALID_REQUIRED_COVERAGE_START:{dataset_id}")
        if coverage_start > required_coverage_start:
            raise DataContractError(f"SEARCH_COVERAGE_GAP:{dataset_id}")
        causal_coverage_start = _parse_date(
            raw_dataset.get("causal_coverage_start", raw_dataset.get("coverage_start")),
            label=f"{dataset_id}.causal_coverage_start",
        )
        if causal_coverage_start > required_coverage_start:
            raise DataContractError(f"CAUSAL_SEARCH_COVERAGE_GAP:{dataset_id}")
        available_at_rule = str(
            raw_dataset.get("available_at_rule", raw_dataset.get("causal_lag", ""))
        ).strip()
        if schema_version >= 2 and not available_at_rule:
            raise DataContractError(f"MISSING_AVAILABLE_AT_RULE:{dataset_id}")
        coverage_end = str(raw_dataset.get("coverage_end", ""))
        if schema_version >= 2 and coverage_end != "current":
            parsed_coverage_end = _parse_date(
                coverage_end, label=f"{dataset_id}.coverage_end"
            )
            if parsed_coverage_end < boundaries.evaluation_end:
                raise DataContractError(f"EVALUATION_COVERAGE_GAP:{dataset_id}")
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
            coverage_end=coverage_end,
            causal_lag=str(raw_dataset.get("causal_lag", "")),
            adapter=str(raw_dataset.get("adapter", "")),
            readiness=readiness,
            available_at_rule=available_at_rule,
            required_coverage_start=required_coverage_start,
        )

    raw_lanes = payload.get("lanes")
    expected_lane_count = int(payload.get("expected_lane_count", 120))
    if expected_lane_count <= 0:
        raise DataContractError("INVALID_EXPECTED_LANE_COUNT")
    if not isinstance(raw_lanes, list) or len(raw_lanes) != expected_lane_count:
        raise DataContractError(
            f"EXPECTED_{expected_lane_count}_LANES:{len(raw_lanes or [])}"
        )
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
        expected_lane_count=expected_lane_count,
    )


def load_and_validate_contract(path: Path) -> FreeDataContract:
    """Load a contract and reject any paid, incomplete, or temporally invalid input."""

    _, raw_payload = _read_payload(path)
    payload = _merge_contract_payload(raw_payload, path=path)
    return _validate_payload(payload, path=path)


def load_and_validate_source_plan(
    path: Path, contract: FreeDataContract
) -> Mapping[str, SourcePlanItem]:
    """Validate that every contracted dataset has a bounded GitHub-only acquisition plan."""

    _, raw_payload = _read_payload(path)
    payload = _merge_source_payload(raw_payload, path=path)
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

    expanded_payload = _merge_contract_payload(
        contract_payload, path=expected_contract_path
    )
    contract = _validate_payload(expanded_payload, path=expected_contract_path)
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


def validate_snapshot_partitions(
    contract: FreeDataContract,
    train_manifest: Mapping[str, Any],
    validation_manifest: Mapping[str, Any],
) -> Mapping[str, str]:
    """Prove physical train/validation isolation and reject every locked observation."""

    if train_manifest.get("contract_sha256") != contract.sha256:
        raise DataContractError("TRAIN_CONTRACT_HASH_MISMATCH")
    if validation_manifest.get("contract_sha256") != contract.sha256:
        raise DataContractError("VALIDATION_CONTRACT_HASH_MISMATCH")
    if train_manifest.get("partition") != "train":
        raise DataContractError("INVALID_TRAIN_PARTITION")
    if validation_manifest.get("partition") != "validation":
        raise DataContractError("INVALID_VALIDATION_PARTITION")
    if train_manifest.get("mountable_by_first_cycle") is not True:
        raise DataContractError("TRAIN_NOT_MOUNTABLE_BY_FIRST_CYCLE")
    if validation_manifest.get("mountable_by_first_cycle") is not False:
        raise DataContractError("VALIDATION_MOUNTABLE_BY_FIRST_CYCLE")

    expected = set(contract.datasets)
    train_rows = train_manifest.get("datasets")
    validation_rows = validation_manifest.get("datasets")
    if not isinstance(train_rows, Mapping) or set(train_rows) != expected:
        raise DataContractError("TRAIN_DATASET_SET_MISMATCH")
    if not isinstance(validation_rows, Mapping) or set(validation_rows) != expected:
        raise DataContractError("VALIDATION_DATASET_SET_MISMATCH")

    train_maxima: list[date] = []
    validation_maxima: list[date] = []
    for dataset_id in sorted(expected):
        train_row = train_rows[dataset_id]
        validation_row = validation_rows[dataset_id]
        if not isinstance(train_row, Mapping) or not isinstance(validation_row, Mapping):
            raise DataContractError(f"INVALID_PARTITION_ROW:{dataset_id}")
        train_max = _parse_date(
            train_row.get("maximum_date"), label=f"train.{dataset_id}.maximum_date"
        )
        validation_min = _parse_date(
            validation_row.get("minimum_date"),
            label=f"validation.{dataset_id}.minimum_date",
        )
        validation_max = _parse_date(
            validation_row.get("maximum_date"),
            label=f"validation.{dataset_id}.maximum_date",
        )
        if train_max > contract.boundaries.search_end:
            raise DataContractError(f"VALIDATION_DATA_IN_TRAIN:{dataset_id}")
        if validation_min < contract.boundaries.evaluation_start:
            raise DataContractError(f"TRAIN_DATA_IN_VALIDATION:{dataset_id}")
        if validation_max >= contract.boundaries.forbidden_from:
            raise DataContractError(f"LOCKED_DATA_PRESENT:{dataset_id}")
        if validation_max > contract.boundaries.evaluation_end:
            raise DataContractError(f"POST_EVALUATION_DATA:{dataset_id}")
        train_maxima.append(train_max)
        validation_maxima.append(validation_max)

    return {
        "train_maximum_date": max(train_maxima).isoformat(),
        "validation_maximum_date": max(validation_maxima).isoformat(),
        "locked_start": contract.boundaries.forbidden_from.isoformat(),
    }
