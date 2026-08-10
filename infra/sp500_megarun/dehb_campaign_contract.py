"""Frozen scientific and execution contract for the official DEHB mega-run."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


EXPECTED_DATA_FILE_SHA256 = (
    "9b2a971c1d1ad0374ad63e03e03c91127bf634e0ed822195c06180140acfa2c8"
)
EXPECTED_DATA_CANONICAL_SHA256 = (
    "c923005def76f5ac8f908bc3e29b31a84dd1848fa70879ae506378123292f057"
)
EXPECTED_FEATURE_SHA256 = (
    "58dd6dba2857223c2040ef383b7ec0513b957675f4ba104ffc408ab5f47ad62c"
)
EXPECTED_DEHB_LOCK_DOMAIN_SHA256 = (
    "89617c4ca6fe54739804e039177c61b8a62933b921cd65617d93fce634a06734"
)
EXPECTED_TRAIN_YEARS = tuple(range(1998, 2011))
EXPECTED_ANNUAL_GATES = (
    "strategy_total_return_gt_zero",
    "strategy_total_return_gt_spy",
)
EXPECTED_OBJECTIVE_ORDER = (
    "annual_gate_feasibility",
    "annualized_strategy_return",
    "weekly_spy_beat_rate",
    "annualized_alpha",
)


class CampaignContractError(ValueError):
    """Raised when a campaign could silently change the scientific experiment."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CampaignContractError("CAMPAIGN_NOT_CANONICAL_JSON") from exc


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CampaignContractError(f"EXPECTED_MAPPING:{label}")
    return value


@dataclass(frozen=True)
class FidelitySpec:
    budget: int
    years: tuple[int, ...]
    bootstrap_paths: int
    parameter_neighbors: int
    temporal_perturbations: int
    finalist_eligible: bool


@dataclass(frozen=True)
class IslandAssignment:
    island_id: str
    lane_id: str
    replicate: int
    seed: int
    n_workers: int


@dataclass(frozen=True)
class JobAssignment:
    job_id: str
    job_index: int
    shard_id: str
    islands: tuple[IslandAssignment, IslandAssignment]


@dataclass(frozen=True)
class FrozenCampaignContract:
    source_path: Path
    sha256: str
    raw: Mapping[str, Any]
    data_contract_file_sha256: str
    data_contract_canonical_sha256: str
    feature_contract_sha256: str
    dehb_lock_domain_sha256: str
    train_source_run_id: str
    train_artifact_name: str
    train_artifact_digest_sha256: str
    train_snapshot_manifest_sha256: str
    train_spy_sha256: str
    train_partition: str
    warmup_start: str
    search_start: str
    search_end: str
    validation_opened: bool
    locked_opened: bool
    validation_partition_mounted: bool
    locked_partition_mounted: bool
    lane_count: int
    replicates_per_lane: int
    island_count: int
    job_count: int
    jobs_per_shard: int
    islands_per_job: int
    n_workers_per_island: int
    island_slice_minutes: int
    job_timeout_minutes: int
    setup_and_upload_reserve_minutes: int
    master_seed: int
    lane_seed_multiplier: int
    replicate_seed_offsets: tuple[int, ...]
    eta: int
    fidelities: tuple[FidelitySpec, ...]
    annual_gates: tuple[str, ...]
    objective_order: tuple[str, ...]
    no_global_time_limit: bool
    plateau_minimum_completed: int
    plateau_completed_without_improvement: int
    plateau_minutes_without_improvement: int
    terminal_no_strategy_allowed: bool


def _parse_fidelities(search: Mapping[str, Any]) -> tuple[FidelitySpec, ...]:
    rows = search.get("fidelities")
    if not isinstance(rows, list):
        raise CampaignContractError("INVALID_FIDELITIES")
    fidelities = tuple(
        FidelitySpec(
            budget=int(_mapping(row, "fidelity")["budget"]),
            years=tuple(int(year) for year in _mapping(row, "fidelity")["years"]),
            bootstrap_paths=int(_mapping(row, "fidelity")["bootstrap_paths"]),
            parameter_neighbors=int(
                _mapping(row, "fidelity")["parameter_neighbors"]
            ),
            temporal_perturbations=int(
                _mapping(row, "fidelity")["temporal_perturbations"]
            ),
            finalist_eligible=bool(
                _mapping(row, "fidelity")["finalist_eligible"]
            ),
        )
        for row in rows
    )
    if tuple(item.budget for item in fidelities) != (1, 3, 9, 27):
        raise CampaignContractError("FIDELITY_BUDGET_MISMATCH")
    for previous, current in zip(fidelities, fidelities[1:]):
        if not set(previous.years) < set(current.years):
            raise CampaignContractError("FIDELITY_YEARS_NOT_STRICTLY_NESTED")
        if previous.bootstrap_paths >= current.bootstrap_paths:
            raise CampaignContractError("FIDELITY_BOOTSTRAPS_NOT_INCREASING")
    if fidelities[-1].years != EXPECTED_TRAIN_YEARS:
        raise CampaignContractError("FULL_FIDELITY_TRAIN_YEARS_MISMATCH")
    if not fidelities[-1].finalist_eligible:
        raise CampaignContractError("FULL_FIDELITY_NOT_FINALIST_ELIGIBLE")
    if any(item.finalist_eligible for item in fidelities[:-1]):
        raise CampaignContractError("LOW_FIDELITY_FINALIST_FORBIDDEN")
    return fidelities


def load_and_validate_campaign_contract(path: Path) -> FrozenCampaignContract:
    """Load the exact campaign and reject any opened hidden partition."""

    source_path = Path(path).resolve()
    try:
        raw_value = json.loads(source_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignContractError(f"CAMPAIGN_READ_FAILED:{source_path}") from exc
    raw = _mapping(raw_value, "root")
    if raw.get("schema_version") != 1:
        raise CampaignContractError("CAMPAIGN_SCHEMA_VERSION_MISMATCH")
    if raw.get("campaign_id") != "sp500-megarun-official-dehb-240x3-v1":
        raise CampaignContractError("CAMPAIGN_ID_MISMATCH")

    inputs = _mapping(raw.get("scientific_inputs"), "scientific_inputs")
    exact_inputs = {
        "data_contract_file_sha256": EXPECTED_DATA_FILE_SHA256,
        "data_contract_canonical_sha256": EXPECTED_DATA_CANONICAL_SHA256,
        "feature_contract_sha256": EXPECTED_FEATURE_SHA256,
        "dehb_lock_domain_sha256": EXPECTED_DEHB_LOCK_DOMAIN_SHA256,
        "dehb_lock_expected_bytes": 40742,
        "train_source_run_id": "31411795360",
        "train_artifact_name": (
            "sp500-megarun-train-1993-2010-F001-F240-31411795360"
        ),
        "train_artifact_digest_sha256": (
            "1c15d9e0ae23821a23464a2775f16fe98441e3b11ccbce31267e3cb63a49af7e"
        ),
        "train_snapshot_manifest_sha256": (
            "f1d6267c8be55e3d84d887ef0af5a5e3db4c21a409494ecbf6083249dd4fdbef"
        ),
        "train_spy_sha256": (
            "ee3797c1473a7ade2dca383f2c37ac4b8627037c65c1e85d56ebd33a6717b150"
        ),
        "train_partition": "train_snapshot_1993_2010",
    }
    for key, expected in exact_inputs.items():
        if inputs.get(key) != expected:
            raise CampaignContractError(f"SCIENTIFIC_INPUT_MISMATCH:{key}")

    boundaries = _mapping(raw.get("boundaries"), "boundaries")
    expected_dates = {
        "warmup_start": "1993-01-22",
        "search_start": "1998-01-01",
        "search_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
    }
    for key, expected in expected_dates.items():
        if boundaries.get(key) != expected:
            raise CampaignContractError(f"BOUNDARY_DATE_MISMATCH:{key}")
    closed_flags = (
        "validation_opened",
        "locked_opened",
        "validation_partition_mounted",
        "locked_partition_mounted",
    )
    if any(boundaries.get(key) is not False for key in closed_flags):
        raise CampaignContractError("BOUNDARY_MUST_REMAIN_CLOSED")

    topology = _mapping(raw.get("topology"), "topology")
    exact_topology = {
        "lane_count": 240,
        "replicates_per_lane": 3,
        "island_count": 720,
        "job_count": 360,
        "shards": ["A", "B", "C"],
        "jobs_per_shard": 120,
        "islands_per_job": 2,
        "n_workers_per_island": 4,
        "island_execution": "sequential",
        "island_slice_minutes": 135,
        "runner_slice_action": "checkpoint_and_resume_same_population",
        "job_timeout_minutes": 330,
        "setup_and_upload_reserve_minutes": 60,
        "island_order": "replicate_major_then_lane",
        "job_pairing": "job_j_receives_island_j_and_j_plus_360",
        "replicate_seed_offsets": [104729, 130363, 155921],
    }
    for key, expected in exact_topology.items():
        if topology.get(key) != expected:
            raise CampaignContractError(f"TOPOLOGY_MISMATCH:{key}")
    thread_limits = _mapping(topology.get("thread_limits"), "thread_limits")
    if set(thread_limits.values()) != {1} or len(thread_limits) != 4:
        raise CampaignContractError("THREAD_LIMITS_MUST_EQUAL_ONE")

    search = _mapping(raw.get("search"), "search")
    if search.get("engine") != "official_dehb" or search.get("eta") != 3:
        raise CampaignContractError("OFFICIAL_DEHB_SEARCH_MISMATCH")
    fidelities = _parse_fidelities(search)

    objective = _mapping(raw.get("objective"), "objective")
    annual_gates = tuple(str(value) for value in objective.get("annual_gates", ()))
    objective_order = tuple(
        str(value) for value in objective.get("objective_order", ())
    )
    if annual_gates != EXPECTED_ANNUAL_GATES:
        raise CampaignContractError("ANNUAL_GATES_MISMATCH")
    if objective_order != EXPECTED_OBJECTIVE_ORDER:
        raise CampaignContractError("OBJECTIVE_ORDER_MISMATCH")
    if objective.get("position_values") != [-1, 1]:
        raise CampaignContractError("POSITION_VALUES_MISMATCH")
    if objective.get("weekly_ties_count_as_win") is not False:
        raise CampaignContractError("WEEKLY_TIES_MUST_NOT_WIN")
    if any(word in " ".join(annual_gates).lower() for word in ("sharpe", "drawdown", "cost")):
        raise CampaignContractError("FORBIDDEN_OBJECTIVE_GATE")

    plateau = _mapping(raw.get("plateau"), "plateau")
    if plateau.get("action") != "checkpoint_and_restart_diverse_population":
        raise CampaignContractError("PLATEAU_MUST_RESTART")
    if plateau.get("trigger") != (
        "completed_threshold_or_elapsed_threshold_after_minimum_completed"
    ):
        raise CampaignContractError("PLATEAU_TRIGGER_MISMATCH")
    if plateau.get("no_global_time_limit") is not True:
        raise CampaignContractError("GLOBAL_TIME_LIMIT_FORBIDDEN")
    if plateau.get("terminal_no_strategy_allowed") is not False:
        raise CampaignContractError("TERMINAL_NO_STRATEGY_FORBIDDEN")
    slice_minutes = int(topology["island_slice_minutes"])
    job_timeout = int(topology["job_timeout_minutes"])
    reserve_minutes = int(topology["setup_and_upload_reserve_minutes"])
    if slice_minutes * int(topology["islands_per_job"]) + reserve_minutes > job_timeout:
        raise CampaignContractError("RUNNER_SLICES_EXCEED_JOB_TIMEOUT")
    if not 0 < int(plateau["minutes_without_improvement"]) < slice_minutes:
        raise CampaignContractError("PLATEAU_TIME_MUST_FIT_ISLAND_SLICE")
    if job_timeout > 360:
        raise CampaignContractError("GITHUB_JOB_TIMEOUT_EXCEEDS_SIX_HOURS")

    contract = FrozenCampaignContract(
        source_path=source_path,
        sha256=hashlib.sha256(_canonical_bytes(raw)).hexdigest(),
        raw=raw,
        data_contract_file_sha256=str(inputs["data_contract_file_sha256"]),
        data_contract_canonical_sha256=str(inputs["data_contract_canonical_sha256"]),
        feature_contract_sha256=str(inputs["feature_contract_sha256"]),
        dehb_lock_domain_sha256=str(inputs["dehb_lock_domain_sha256"]),
        train_source_run_id=str(inputs["train_source_run_id"]),
        train_artifact_name=str(inputs["train_artifact_name"]),
        train_artifact_digest_sha256=str(inputs["train_artifact_digest_sha256"]),
        train_snapshot_manifest_sha256=str(
            inputs["train_snapshot_manifest_sha256"]
        ),
        train_spy_sha256=str(inputs["train_spy_sha256"]),
        train_partition=str(inputs["train_partition"]),
        warmup_start=str(boundaries["warmup_start"]),
        search_start=str(boundaries["search_start"]),
        search_end=str(boundaries["search_end"]),
        validation_opened=bool(boundaries["validation_opened"]),
        locked_opened=bool(boundaries["locked_opened"]),
        validation_partition_mounted=bool(
            boundaries["validation_partition_mounted"]
        ),
        locked_partition_mounted=bool(boundaries["locked_partition_mounted"]),
        lane_count=int(topology["lane_count"]),
        replicates_per_lane=int(topology["replicates_per_lane"]),
        island_count=int(topology["island_count"]),
        job_count=int(topology["job_count"]),
        jobs_per_shard=int(topology["jobs_per_shard"]),
        islands_per_job=int(topology["islands_per_job"]),
        n_workers_per_island=int(topology["n_workers_per_island"]),
        island_slice_minutes=int(topology["island_slice_minutes"]),
        job_timeout_minutes=int(topology["job_timeout_minutes"]),
        setup_and_upload_reserve_minutes=int(
            topology["setup_and_upload_reserve_minutes"]
        ),
        master_seed=int(topology["master_seed"]),
        lane_seed_multiplier=int(topology["lane_seed_multiplier"]),
        replicate_seed_offsets=tuple(
            int(value) for value in topology["replicate_seed_offsets"]
        ),
        eta=int(search["eta"]),
        fidelities=fidelities,
        annual_gates=annual_gates,
        objective_order=objective_order,
        no_global_time_limit=bool(plateau["no_global_time_limit"]),
        plateau_minimum_completed=int(plateau["minimum_completed_evaluations"]),
        plateau_completed_without_improvement=int(
            plateau["completed_evaluations_without_improvement"]
        ),
        plateau_minutes_without_improvement=int(
            plateau["minutes_without_improvement"]
        ),
        terminal_no_strategy_allowed=bool(
            plateau["terminal_no_strategy_allowed"]
        ),
    )
    build_island_schedule(contract)
    return contract


def build_island_schedule(
    contract: FrozenCampaignContract,
) -> tuple[JobAssignment, ...]:
    """Map three deterministic islands per lane onto 360 two-island jobs."""

    islands: list[IslandAssignment] = []
    for replicate, offset in enumerate(contract.replicate_seed_offsets, start=1):
        for lane_number in range(1, contract.lane_count + 1):
            lane_id = f"F{lane_number:03d}"
            seed = (
                contract.master_seed
                + lane_number * contract.lane_seed_multiplier
                + offset
            )
            islands.append(
                IslandAssignment(
                    island_id=f"{lane_id}-R{replicate}",
                    lane_id=lane_id,
                    replicate=replicate,
                    seed=seed,
                    n_workers=contract.n_workers_per_island,
                )
            )
    if len(islands) != contract.island_count:
        raise CampaignContractError("ISLAND_COUNT_MISMATCH")
    if len({item.island_id for item in islands}) != len(islands):
        raise CampaignContractError("DUPLICATE_ISLAND_ID")
    if len({item.seed for item in islands}) != len(islands):
        raise CampaignContractError("DUPLICATE_ISLAND_SEED")
    if any(item.seed < 0 or item.seed >= 2**32 for item in islands):
        raise CampaignContractError("ISLAND_SEED_OUT_OF_UINT32")

    schedule: list[JobAssignment] = []
    for job_index in range(contract.job_count):
        shard_index = job_index // contract.jobs_per_shard
        shard_id = ("A", "B", "C")[shard_index]
        schedule.append(
            JobAssignment(
                job_id=f"J{job_index + 1:03d}",
                job_index=job_index,
                shard_id=shard_id,
                islands=(islands[job_index], islands[job_index + contract.job_count]),
            )
        )
    assigned = [item for job in schedule for item in job.islands]
    if len(schedule) != contract.job_count or set(assigned) != set(islands):
        raise CampaignContractError("JOB_ISLAND_COVERAGE_MISMATCH")
    return tuple(schedule)


def plateau_action(
    contract: FrozenCampaignContract,
    *,
    completed_since_improvement: int,
    minutes_since_improvement: float,
) -> str:
    """Return a population action; plateau is never a scientific terminal state."""

    if completed_since_improvement < 0 or minutes_since_improvement < 0:
        raise CampaignContractError("NEGATIVE_PLATEAU_COUNTER")
    if completed_since_improvement < contract.plateau_minimum_completed:
        return "continue_population"
    if (
        completed_since_improvement
        >= contract.plateau_completed_without_improvement
        or minutes_since_improvement >= contract.plateau_minutes_without_improvement
    ):
        return "checkpoint_and_restart_diverse_population"
    return "continue_population"


def build_campaign_manifest(contract: FrozenCampaignContract) -> Mapping[str, Any]:
    """Create the deterministic, hash-bound controller input."""

    jobs = build_island_schedule(contract)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "campaign_id": contract.raw["campaign_id"],
        "campaign_contract_sha256": contract.sha256,
        "job_count": len(jobs),
        "island_count": sum(len(job.islands) for job in jobs),
        "validation_opened": False,
        "locked_opened": False,
        "jobs": [
            {
                "job_id": job.job_id,
                "job_index": job.job_index,
                "shard_id": job.shard_id,
                "islands": [
                    {
                        "island_id": island.island_id,
                        "lane_id": island.lane_id,
                        "replicate": island.replicate,
                        "seed": island.seed,
                        "n_workers": island.n_workers,
                    }
                    for island in job.islands
                ],
            }
            for job in jobs
        ],
    }
    payload["manifest_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def validate_campaign_bindings(
    contract: FrozenCampaignContract,
    *,
    repo_root: Path,
) -> Mapping[str, Any]:
    """Verify that the repository bytes still match every frozen campaign input."""

    from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
    from aurora.infra.sp500_megarun.dehb_official_smoke import verify_dependency_lock
    from aurora.infra.sp500_megarun.feature_contract import (
        load_and_validate_feature_contract,
    )

    root = Path(repo_root).resolve()
    inputs = _mapping(contract.raw["scientific_inputs"], "scientific_inputs")

    def bound_path(key: str) -> Path:
        candidate = (root / str(inputs[key])).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise CampaignContractError(f"BOUND_PATH_ESCAPES_REPOSITORY:{key}") from exc
        if not candidate.is_file():
            raise CampaignContractError(f"BOUND_FILE_MISSING:{key}")
        return candidate

    data_path = bound_path("data_contract_path")
    feature_path = bound_path("feature_contract_path")
    lock_path = bound_path("dehb_lock_path")
    data_file_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
    if data_file_hash != contract.data_contract_file_sha256:
        raise CampaignContractError("BOUND_DATA_FILE_HASH_MISMATCH")
    data_contract = load_and_validate_contract(data_path)
    if data_contract.sha256 != contract.data_contract_canonical_sha256:
        raise CampaignContractError("BOUND_DATA_CANONICAL_HASH_MISMATCH")
    feature_contract = load_and_validate_feature_contract(feature_path, data_contract)
    if feature_contract.sha256 != contract.feature_contract_sha256:
        raise CampaignContractError("BOUND_FEATURE_HASH_MISMATCH")
    lock_receipt = verify_dependency_lock(lock_path)
    if lock_receipt["domain_sha256"] != contract.dehb_lock_domain_sha256:
        raise CampaignContractError("BOUND_DEHB_LOCK_HASH_MISMATCH")
    return {
        "verified": True,
        "data_contract_file_sha256": data_file_hash,
        "data_contract_canonical_sha256": data_contract.sha256,
        "feature_contract_sha256": feature_contract.sha256,
        "dehb_lock_domain_sha256": lock_receipt["domain_sha256"],
        "dehb_lock_bytes": lock_receipt["byte_count"],
    }


__all__ = [
    "CampaignContractError",
    "FidelitySpec",
    "FrozenCampaignContract",
    "IslandAssignment",
    "JobAssignment",
    "build_campaign_manifest",
    "build_island_schedule",
    "load_and_validate_campaign_contract",
    "plateau_action",
    "validate_campaign_bindings",
]
