"""Official DEHB ask/tell slice with four external process slots."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
import hashlib
from importlib import metadata
import importlib
import json
import math
from pathlib import Path
import shutil
import time
from typing import Any, Callable, Mapping

import pandas as pd


Objective = Callable[[Any, float], Mapping[str, Any]]


class IslandRunnerError(ValueError):
    """Raised when official ask/tell state or an objective result is invalid."""


@dataclass(frozen=True)
class IslandSliceResult:
    status: str
    stop_reason: str
    evaluations: int
    full_fidelity_evaluations: int
    completed_since_improvement: int
    seconds_since_improvement: float
    best_archive_key: tuple[float, ...] | None
    trials: tuple[Mapping[str, Any], ...]


def _configuration_dict(config: Any) -> dict[str, Any]:
    if isinstance(config, Mapping):
        raw = config
    else:
        try:
            raw = dict(config)
        except (TypeError, ValueError) as exc:
            raise IslandRunnerError("INVALID_OFFICIAL_DEHB_CONFIG") from exc
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if hasattr(value, "item"):
            value = value.item()
        if value is not None and not isinstance(value, (bool, int, float, str)):
            raise IslandRunnerError(f"NONSCALAR_OFFICIAL_DEHB_CONFIG:{key}")
        result[str(key)] = value
    return result


def _validated_result(result: Mapping[str, Any]) -> tuple[float, float, Mapping[str, Any]]:
    try:
        fitness = float(result["fitness"])
        cost = float(result["cost"])
        info = result["info"]
    except (KeyError, TypeError, ValueError) as exc:
        raise IslandRunnerError("INVALID_OFFICIAL_DEHB_RESULT") from exc
    if not math.isfinite(fitness) or not math.isfinite(cost) or cost < 0.0:
        raise IslandRunnerError("NONFINITE_OFFICIAL_DEHB_RESULT")
    if not isinstance(info, Mapping):
        raise IslandRunnerError("OFFICIAL_DEHB_INFO_NOT_MAPPING")
    if info.get("validation_opened", False) is not False:
        raise IslandRunnerError("OBJECTIVE_OPENED_VALIDATION")
    if info.get("locked_opened", False) is not False:
        raise IslandRunnerError("OBJECTIVE_OPENED_LOCKED")
    return fitness, cost, info


def run_ask_tell_slice(
    optimizer: Any,
    objective: Objective,
    *,
    n_workers: int,
    full_fidelity: int,
    slice_seconds: float,
    plateau_minimum_completed: int,
    plateau_completed_without_improvement: int,
    plateau_seconds_without_improvement: float,
    initial_evaluations: int = 0,
    initial_full_fidelity_evaluations: int = 0,
    initial_completed_since_improvement: int = 0,
    initial_seconds_since_improvement: float = 0.0,
    initial_best_archive_key: tuple[float, ...] | None = None,
    clock: Callable[[], float] = time.monotonic,
    executor_factory: Any = ProcessPoolExecutor,
) -> IslandSliceResult:
    """Run synchronous batches in parallel and stop only at a safe batch boundary."""

    if n_workers != 4:
        raise IslandRunnerError("MEGARUN_REQUIRES_FOUR_WORKERS_PER_ISLAND")
    if slice_seconds <= 0.0:
        raise IslandRunnerError("INVALID_ISLAND_SLICE_SECONDS")
    if not 0 < plateau_minimum_completed <= plateau_completed_without_improvement:
        raise IslandRunnerError("INVALID_PLATEAU_EVALUATION_THRESHOLDS")
    if plateau_seconds_without_improvement <= 0.0:
        raise IslandRunnerError("INVALID_PLATEAU_SECONDS")
    if min(
        initial_evaluations,
        initial_full_fidelity_evaluations,
        initial_completed_since_improvement,
    ) < 0 or initial_seconds_since_improvement < 0.0:
        raise IslandRunnerError("INVALID_INITIAL_SLICE_STATE")

    started = clock()
    last_improvement = started - initial_seconds_since_improvement
    completed_since_improvement = initial_completed_since_improvement
    best_archive_key = initial_best_archive_key
    evaluations = initial_evaluations
    full_fidelity_evaluations = initial_full_fidelity_evaluations
    trials: list[Mapping[str, Any]] = []
    status = "paused_at_runner_slice"
    stop_reason = "runner_slice_elapsed"

    with executor_factory(max_workers=n_workers) as executor:
        while True:
            if clock() - started >= slice_seconds:
                break
            jobs = optimizer.ask(n_configs=n_workers)
            if not isinstance(jobs, list) or len(jobs) != n_workers:
                raise IslandRunnerError("OFFICIAL_DEHB_ASK_BATCH_MISMATCH")
            futures = [
                executor.submit(objective, job["config"], float(job["fidelity"]))
                for job in jobs
            ]
            for job, future in zip(jobs, futures, strict=True):
                raw_result = future.result()
                if not isinstance(raw_result, Mapping):
                    raise IslandRunnerError("OFFICIAL_DEHB_RESULT_NOT_MAPPING")
                fitness, cost, info = _validated_result(raw_result)
                optimizer.tell(job, raw_result)
                fidelity = int(float(job["fidelity"]))
                evaluations += 1
                completed_since_improvement += 1
                if fidelity == full_fidelity:
                    full_fidelity_evaluations += 1
                    archive = info.get("archive_key")
                    if not isinstance(archive, list) or not archive:
                        raise IslandRunnerError("FULL_FIDELITY_ARCHIVE_KEY_MISSING")
                    archive_key = tuple(float(value) for value in archive)
                    if not all(math.isfinite(value) for value in archive_key):
                        raise IslandRunnerError("NONFINITE_ARCHIVE_KEY")
                    if best_archive_key is None or archive_key < best_archive_key:
                        best_archive_key = archive_key
                        completed_since_improvement = 0
                        last_improvement = clock()
                trials.append(
                    {
                        "evaluation": evaluations,
                        "config_id": int(job.get("config_id", -1)),
                        "configuration": _configuration_dict(job["config"]),
                        "fidelity": fidelity,
                        "fitness": fitness,
                        "cost": cost,
                        "info": dict(info),
                    }
                )

            now = clock()
            if evaluations >= plateau_minimum_completed:
                if (
                    completed_since_improvement
                    >= plateau_completed_without_improvement
                ):
                    status = "completed"
                    stop_reason = "plateau_completed_evaluations"
                    break
                if now - last_improvement >= plateau_seconds_without_improvement:
                    status = "completed"
                    stop_reason = "plateau_elapsed_time"
                    break
            if now - started >= slice_seconds:
                break

    return IslandSliceResult(
        status=status,
        stop_reason=stop_reason,
        evaluations=evaluations,
        full_fidelity_evaluations=full_fidelity_evaluations,
        completed_since_improvement=completed_since_improvement,
        seconds_since_improvement=max(0.0, clock() - last_improvement),
        best_archive_key=best_archive_key,
        trials=tuple(trials),
    )


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IslandRunnerError("ISLAND_VALUE_NOT_CANONICAL_JSON") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise IslandRunnerError(f"ISLAND_FILE_READ_FAILED:{path}") from exc
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _candidate_rows(search: IslandSliceResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in search.trials:
        info = trial["info"]
        if not isinstance(info, Mapping) or info.get("full_fidelity") is not True:
            continue
        rows.append(
            {
                "evaluation": int(trial["evaluation"]),
                "config_id": int(trial["config_id"]),
                "fidelity": int(trial["fidelity"]),
                "fitness": float(trial["fitness"]),
                "configuration_json": _canonical_bytes(
                    trial["configuration"]
                ).decode("utf-8"),
                "strategy_fingerprint": str(info.get("strategy_fingerprint", "")),
                "position_fingerprint": str(info.get("position_fingerprint", "")),
                "train_feasible": bool(info.get("train_feasible", False)),
                "annualized_strategy_return": info.get(
                    "annualized_strategy_return"
                ),
                "weekly_spy_beat_rate": info.get("weekly_spy_beat_rate"),
                "annualized_alpha": info.get("annualized_alpha"),
                "archive_key_json": _canonical_bytes(
                    info.get("archive_key", [])
                ).decode("utf-8"),
                "info_json": _canonical_bytes(dict(info)).decode("utf-8"),
            }
        )
    return rows


def _pareto_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feasible = [row for row in candidates if row["train_feasible"]]

    def metric(row: Mapping[str, Any], name: str) -> float:
        value = row.get(name)
        return float(value) if value is not None else -math.inf

    result: list[dict[str, Any]] = []
    for row in feasible:
        dominated = any(
            (
                metric(other, "annualized_strategy_return")
                >= metric(row, "annualized_strategy_return")
                and metric(other, "weekly_spy_beat_rate")
                >= metric(row, "weekly_spy_beat_rate")
                and (
                    metric(other, "annualized_strategy_return")
                    > metric(row, "annualized_strategy_return")
                    or metric(other, "weekly_spy_beat_rate")
                    > metric(row, "weekly_spy_beat_rate")
                )
            )
            for other in feasible
            if other is not row
        )
        if not dominated:
            result.append(row)
    return sorted(result, key=lambda row: str(row["archive_key_json"]))


def _annual_rows(search: IslandSliceResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in search.trials:
        info = trial["info"]
        if not isinstance(info, Mapping):
            continue
        annual = info.get("annual_returns")
        if not isinstance(annual, Mapping):
            continue
        for year, metrics in annual.items():
            if isinstance(metrics, Mapping):
                rows.append(
                    {
                        "evaluation": int(trial["evaluation"]),
                        "config_id": int(trial["config_id"]),
                        "fidelity": int(trial["fidelity"]),
                        "year": int(year),
                        **dict(metrics),
                    }
                )
    return rows


def _native_checkpoint_receipt(native: Path) -> Mapping[str, Any]:
    files = sorted(path for path in native.rglob("*") if path.is_file())
    if not files:
        raise IslandRunnerError("OFFICIAL_DEHB_NATIVE_CHECKPOINT_EMPTY")
    rows = [
        {
            "path": path.relative_to(native).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in files
    ]
    return {
        "schema_version": 1,
        "official_dehb_native_checkpoint": True,
        "files": rows,
        "aggregate_sha256": hashlib.sha256(_canonical_bytes(rows)).hexdigest(),
    }


def write_island_bundle(
    contract: Any,
    *,
    assignment: Mapping[str, Any],
    wave: int,
    search: IslandSliceResult,
    output_dir: Path,
    data_access_audit: Mapping[str, Any],
    robustness_reviewer: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    prior_bundle: Path | None = None,
    maximum_bundle_bytes: int = 12 * 1024 * 1024,
) -> Mapping[str, Any]:
    """Write one self-verifying island bundle around DEHB's native checkpoint."""

    if data_access_audit.get("validation_opened") is not False:
        raise IslandRunnerError("DATA_ACCESS_AUDIT_OPENED_VALIDATION")
    if data_access_audit.get("locked_opened") is not False:
        raise IslandRunnerError("DATA_ACCESS_AUDIT_OPENED_LOCKED")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    native = root / "native_checkpoint"
    native_receipt = _native_checkpoint_receipt(native)
    _write_json(root / "native_checkpoint_manifest.json", native_receipt)

    from aurora.infra.sp500_megarun.dehb_campaign_runtime import (
        append_ledger_event,
        build_checkpoint_envelope,
        verify_event_ledger,
    )

    event_path = root / "events.jsonl"
    prior = Path(prior_bundle).resolve() if prior_bundle is not None else None
    if prior is not None:
        previous_events = prior / "events.jsonl"
        if not previous_events.is_file():
            raise IslandRunnerError("PRIOR_ISLAND_EVENTS_MISSING")
        shutil.copy2(previous_events, event_path)
    append_ledger_event(
        event_path,
        campaign_sha256=contract.sha256,
        event={
            "type": "island_slice_finished",
            "island_id": str(assignment["island_id"]),
            "wave": wave,
            "status": search.status,
            "stop_reason": search.stop_reason,
            "evaluations": search.evaluations,
        },
    )
    ledger_receipt = verify_event_ledger(
        event_path, campaign_sha256=contract.sha256
    )
    envelope = build_checkpoint_envelope(
        contract,
        island_id=str(assignment["island_id"]),
        wave=wave,
        restart_ordinal=int(assignment["restart_ordinal"]),
        evaluations=search.evaluations,
        dehb_state_sha256=str(native_receipt["aggregate_sha256"]),
        ledger_tail_hash=str(ledger_receipt["tail_hash"]),
    )
    _write_json(root / "checkpoint_envelope.json", envelope)

    trial_rows = [
        {
            "evaluation": int(trial["evaluation"]),
            "config_id": int(trial["config_id"]),
            "fidelity": int(trial["fidelity"]),
            "fitness": float(trial["fitness"]),
            "cost": float(trial["cost"]),
            "configuration_json": _canonical_bytes(
                trial["configuration"]
            ).decode("utf-8"),
            "info_json": _canonical_bytes(trial["info"]).decode("utf-8"),
        }
        for trial in search.trials
    ]
    trial_frame = pd.DataFrame(
        trial_rows,
        columns=(
            "evaluation", "config_id", "fidelity", "fitness", "cost",
            "configuration_json", "info_json",
        ),
    )
    if prior is not None:
        trial_frame = pd.concat(
            [pd.read_parquet(prior / "trial_ledger.parquet"), trial_frame],
            ignore_index=True,
        )
    trial_frame.to_parquet(root / "trial_ledger.parquet", index=False)
    candidates = _candidate_rows(search)
    candidate_columns = (
        "evaluation", "config_id", "fidelity", "fitness",
        "configuration_json", "strategy_fingerprint", "position_fingerprint",
        "train_feasible",
        "annualized_strategy_return", "weekly_spy_beat_rate",
        "annualized_alpha", "archive_key_json", "info_json",
    )
    candidate_frame = pd.DataFrame(candidates, columns=candidate_columns)
    if prior is not None:
        candidate_frame = pd.concat(
            [
                pd.read_parquet(prior / "full_fidelity_candidates.parquet"),
                candidate_frame,
            ],
            ignore_index=True,
        )
    candidate_frame.to_parquet(
        root / "full_fidelity_candidates.parquet", index=False
    )
    cumulative_candidates = candidate_frame.to_dict(orient="records")
    pd.DataFrame(
        _pareto_rows(cumulative_candidates), columns=candidate_columns
    ).to_parquet(
        root / "pareto_front.parquet", index=False
    )
    annual_frame = pd.DataFrame(_annual_rows(search))
    if prior is not None:
        annual_frame = pd.concat(
            [pd.read_parquet(prior / "annual_metrics.parquet"), annual_frame],
            ignore_index=True,
        )
    annual_frame.to_parquet(root / "annual_metrics.parquet", index=False)
    previous_failures = (
        (prior / "failure_ledger.jsonl").read_text("utf-8")
        if prior is not None
        else ""
    )
    (root / "failure_ledger.jsonl").write_text(
        previous_failures, encoding="utf-8"
    )
    runtime_audit = {
        "schema_version": 1,
        "status": search.status,
        "stop_reason": search.stop_reason,
        "evaluations": search.evaluations,
        "full_fidelity_evaluations": search.full_fidelity_evaluations,
        "completed_since_improvement": search.completed_since_improvement,
        "seconds_since_improvement": search.seconds_since_improvement,
        "best_archive_key": list(search.best_archive_key)
        if search.best_archive_key is not None
        else None,
        "n_workers": 4,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write_json(root / "runtime_audit.json", runtime_audit)
    _write_json(root / "data_access_audit.json", dict(data_access_audit))

    feasible_trials = []
    for row in cumulative_candidates:
        if not bool(row.get("train_feasible", False)):
            continue
        info = json.loads(str(row["info_json"]))
        configuration = json.loads(str(row["configuration_json"]))
        feasible_trials.append(
            {
                "evaluation": int(row["evaluation"]),
                "configuration": configuration,
                "info": info,
            }
        )
    champion: Mapping[str, Any] | None = None
    if feasible_trials:
        best = min(
            feasible_trials,
            key=lambda trial: tuple(float(value) for value in trial["info"]["archive_key"]),
        )
        review = (
            dict(robustness_reviewer(best))
            if robustness_reviewer is not None
            else {"passed": False, "status": "not_run"}
        )
        champion = {
            **dict(best["info"]),
            "configuration": dict(best["configuration"]),
            "candidate_local_robustness_passed": (
                review.get("candidate_local_passed") is True
            ),
            "robustness_passed": review.get("passed") is True,
            "robustness": review,
        }
    manifest = {
        "schema_version": 1,
        "campaign_contract_sha256": contract.sha256,
        "island_id": str(assignment["island_id"]),
        "lane_id": str(assignment["lane_id"]),
        "replicate": int(assignment["replicate"]),
        "restart_ordinal": int(assignment["restart_ordinal"]),
        "restart_seed": int(assignment["restart_seed"]),
        "wave": wave,
        "status": search.status,
        "stop_reason": search.stop_reason,
        "evaluations": search.evaluations,
        "full_fidelity_evaluations": search.full_fidelity_evaluations,
        "checkpoint_sha256": envelope["checkpoint_envelope_sha256"],
        "official_dehb_native_checkpoint": True,
        "native_checkpoint_sha256": native_receipt["aggregate_sha256"],
        "champion": champion,
        "train_partition": contract.train_partition,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write_json(root / "island_manifest.json", manifest)

    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    )
    total_bytes = sum(path.stat().st_size for path in files)
    if total_bytes > maximum_bundle_bytes:
        raise IslandRunnerError(
            f"ISLAND_BUNDLE_TOO_LARGE:{total_bytes}:{maximum_bundle_bytes}"
        )
    checksum_lines = [
        f"{_sha256_file(path)}  {path.relative_to(root).as_posix()}"
        for path in files
    ]
    (root / "checksums.sha256").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    return manifest


def verify_island_bundle(
    contract: Any,
    root: Path,
    *,
    expected_island_id: str,
) -> Mapping[str, Any]:
    """Verify checksums, campaign binding, checkpoint envelope and closed tiers."""

    bundle = Path(root).resolve()
    checksum_path = bundle / "checksums.sha256"
    try:
        lines = checksum_path.read_text("utf-8").splitlines()
    except OSError as exc:
        raise IslandRunnerError("BUNDLE_CHECKSUMS_MISSING") from exc
    for line in lines:
        try:
            expected, relative = line.split("  ", maxsplit=1)
        except ValueError as exc:
            raise IslandRunnerError("BUNDLE_CHECKSUM_LINE_INVALID") from exc
        target = (bundle / relative).resolve()
        if bundle not in target.parents or not target.is_file():
            raise IslandRunnerError(f"BUNDLE_FILE_INVALID:{relative}")
        if _sha256_file(target) != expected:
            raise IslandRunnerError(f"BUNDLE_CHECKSUM_MISMATCH:{relative}")
    try:
        manifest = json.loads((bundle / "island_manifest.json").read_text("utf-8"))
        envelope = json.loads(
            (bundle / "checkpoint_envelope.json").read_text("utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise IslandRunnerError("BUNDLE_MANIFEST_INVALID") from exc
    if (
        manifest.get("campaign_contract_sha256") != contract.sha256
        or manifest.get("island_id") != expected_island_id
    ):
        raise IslandRunnerError("BUNDLE_LINEAGE_MISMATCH")
    if manifest.get("validation_opened") is not False:
        raise IslandRunnerError("BUNDLE_OPENED_VALIDATION")
    if manifest.get("locked_opened") is not False:
        raise IslandRunnerError("BUNDLE_OPENED_LOCKED")
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import (
        validate_checkpoint_envelope,
    )

    validate_checkpoint_envelope(
        contract, envelope, expected_island_id=expected_island_id
    )
    return {
        "verified": True,
        "island_id": expected_island_id,
        "file_count": len(lines),
        "validation_opened": False,
        "locked_opened": False,
    }


def run_official_dehb_island(
    contract: Any,
    feature_contract: Any,
    *,
    assignment: Mapping[str, Any],
    wave: int,
    train_snapshot: Path,
    baseline_feature_dirs: Mapping[str, Path],
    output_dir: Path,
    prior_bundle: Path | None = None,
    slice_seconds: float | None = None,
    robustness_reviewer: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    dehb_module: Any | None = None,
    executor_factory: Any = ProcessPoolExecutor,
) -> Mapping[str, Any]:
    """Run one exact island using official DEHB 0.1.2 and its native resume state."""

    if metadata.version("DEHB") != "0.1.2":
        raise IslandRunnerError("OFFICIAL_DEHB_VERSION_MISMATCH")
    if metadata.version("ConfigSpace") != "1.2.2":
        raise IslandRunnerError("CONFIGSPACE_VERSION_MISMATCH")
    if int(assignment.get("n_workers", -1)) != 4:
        raise IslandRunnerError("ISLAND_ASSIGNMENT_WORKER_COUNT_MISMATCH")
    lane_id = str(assignment["lane_id"])
    root = Path(output_dir).resolve()
    native = root / "native_checkpoint"
    if root.exists() and any(root.iterdir()):
        raise IslandRunnerError("ISLAND_OUTPUT_MUST_START_EMPTY")
    root.mkdir(parents=True, exist_ok=True)

    initial: Mapping[str, Any] = {}
    resume = prior_bundle is not None
    if prior_bundle is not None:
        prior = Path(prior_bundle).resolve()
        verify_island_bundle(
            contract, prior, expected_island_id=str(assignment["island_id"])
        )
        prior_native = prior / "native_checkpoint"
        if not prior_native.is_dir():
            raise IslandRunnerError("PRIOR_NATIVE_CHECKPOINT_MISSING")
        shutil.copytree(prior_native, native)
        try:
            initial = json.loads(
                (prior / "runtime_audit.json").read_text("utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise IslandRunnerError("PRIOR_RUNTIME_AUDIT_INVALID") from exc
    else:
        native.mkdir(parents=True)

    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace
    from aurora.infra.sp500_megarun.dehb_lane_registry import (
        default_lane_configurations,
    )
    from aurora.infra.sp500_megarun.dehb_worker import (
        evaluate_physical_lane_candidate,
    )

    default_configurations = default_lane_configurations(feature_contract)
    fidelity_years = {
        int(spec.budget): tuple(int(year) for year in spec.years)
        for spec in contract.fidelities
    }
    objective = partial(
        evaluate_physical_lane_candidate,
        lane_id=lane_id,
        train_snapshot=str(Path(train_snapshot).resolve()),
        expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
        expected_spy_sha256=contract.train_spy_sha256,
        default_configurations=default_configurations,
        baseline_feature_dirs={
            name: str(Path(path).resolve())
            for name, path in baseline_feature_dirs.items()
        },
        fidelity_years=fidelity_years,
        allowed_end=contract.search_end,
    )
    lane_space = build_lane_configspace(
        feature_contract,
        lane_id,
        seed=int(assignment["restart_seed"]),
    )
    if robustness_reviewer is None:
        from aurora.infra.sp500_megarun.dehb_robustness import (
            build_physical_candidate_robustness_reviewer,
        )

        robustness_reviewer = build_physical_candidate_robustness_reviewer(
            contract,
            feature_contract,
            lane_id=lane_id,
            train_snapshot=Path(train_snapshot).resolve(),
            baseline_feature_dirs={
                name: Path(path).resolve()
                for name, path in baseline_feature_dirs.items()
            },
            lane_configspace=lane_space,
            seed=int(assignment["restart_seed"]),
        )
    module = dehb_module or importlib.import_module("dehb")
    optimizer = module.DEHB(
        cs=lane_space.configspace,
        f=objective,
        min_fidelity=min(fidelity_years),
        max_fidelity=max(fidelity_years),
        eta=contract.eta,
        seed=int(assignment["restart_seed"]),
        n_workers=1,
        output_path=native,
        save_freq="end",
        log_level="WARNING",
        resume=resume,
    )
    try:
        prior_best = initial.get("best_archive_key")
        search = run_ask_tell_slice(
            optimizer,
            objective,
            n_workers=4,
            full_fidelity=max(fidelity_years),
            slice_seconds=float(
                slice_seconds
                if slice_seconds is not None
                else contract.island_slice_minutes * 60
            ),
            plateau_minimum_completed=contract.plateau_minimum_completed,
            plateau_completed_without_improvement=(
                contract.plateau_completed_without_improvement
            ),
            plateau_seconds_without_improvement=(
                contract.plateau_minutes_without_improvement * 60
            ),
            initial_evaluations=int(initial.get("evaluations", 0)),
            initial_full_fidelity_evaluations=int(
                initial.get("full_fidelity_evaluations", 0)
            ),
            initial_completed_since_improvement=int(
                initial.get("completed_since_improvement", 0)
            ),
            initial_seconds_since_improvement=float(
                initial.get("seconds_since_improvement", 0.0)
            ),
            initial_best_archive_key=tuple(float(value) for value in prior_best)
            if isinstance(prior_best, list)
            else None,
            executor_factory=executor_factory,
        )
        optimizer.save()
    finally:
        client = getattr(optimizer, "client", None)
        if client is not None:
            client.close()
            optimizer.client = None

    data_access_audit = {
        "schema_version": 1,
        "train_source_run_id": contract.train_source_run_id,
        "train_artifact_name": contract.train_artifact_name,
        "train_artifact_digest_sha256": contract.train_artifact_digest_sha256,
        "train_snapshot_manifest_sha256": contract.train_snapshot_manifest_sha256,
        "train_spy_sha256": contract.train_spy_sha256,
        "train_partition": contract.train_partition,
        "search_end": contract.search_end,
        "validation_partition_mounted": False,
        "locked_partition_mounted": False,
        "validation_opened": False,
        "locked_opened": False,
    }
    return write_island_bundle(
        contract,
        assignment=assignment,
        wave=wave,
        search=search,
        output_dir=root,
        data_access_audit=data_access_audit,
        robustness_reviewer=robustness_reviewer,
        prior_bundle=prior_bundle,
    )


__all__ = [
    "IslandRunnerError",
    "IslandSliceResult",
    "Objective",
    "run_ask_tell_slice",
    "run_official_dehb_island",
    "verify_island_bundle",
    "write_island_bundle",
]
