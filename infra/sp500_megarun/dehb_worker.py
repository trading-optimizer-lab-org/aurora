"""Train-only objective adapter used by the official DEHB mega worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.dehb_objective import (
    ObjectiveContractError,
    build_adjusted_open_total_return_ledger,
    candidate_rank_key,
    score_ledger_decisions,
)


FeatureEvaluator = Callable[[str, Mapping[str, Any]], pd.DataFrame]
_DECISION_ZERO_TOLERANCE = 1e-12
_PROCESS_CONTEXTS: dict[
    tuple[str, str, str, tuple[tuple[str, str], ...]],
    tuple[pd.DataFrame, FeatureEvaluator],
] = {}


class DehbWorkerError(RuntimeError):
    """Raised when an island input, feature, or objective breaks the contract."""


@dataclass(frozen=True)
class PreparedLaneCandidate:
    """Position path generated before the expensive objective calculation."""

    lane_id: str
    configuration: Mapping[str, Any]
    fidelity: int
    target_years: tuple[int, ...]
    decisions: pd.Series
    strategy_fingerprint: str
    position_fingerprint: str


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DehbWorkerError("WORKER_VALUE_NOT_CANONICAL_JSON") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise DehbWorkerError(f"TRAIN_FILE_READ_FAILED:{path.name}") from exc
    return digest.hexdigest()


def _configuration_dict(config: Any) -> Mapping[str, Any]:
    if isinstance(config, Mapping):
        raw = config
    else:
        try:
            raw = dict(config)
        except (TypeError, ValueError) as exc:
            raise DehbWorkerError("INVALID_DEHB_CONFIGURATION") from exc
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        if hasattr(value, "item"):
            value = value.item()
        if value is not None and not isinstance(value, (bool, int, float, str)):
            raise DehbWorkerError(f"NONSCALAR_DEHB_CONFIGURATION:{key}")
        normalized[str(key)] = value
    _canonical_bytes(normalized)
    return normalized


def candidate_fingerprints(
    lane_id: str,
    configuration: Mapping[str, Any],
    decisions: pd.Series,
) -> tuple[str, str]:
    """Return candidate identity and behavior-only hashes for clone control."""

    config_sha256 = hashlib.sha256(_canonical_bytes(configuration)).hexdigest()
    decision_payload = np.nan_to_num(
        decisions.to_numpy(dtype="<f8"),
        nan=0.0,
    ).tobytes()
    position_fingerprint = hashlib.sha256(decision_payload).hexdigest()
    strategy_fingerprint = hashlib.sha256(
        lane_id.encode("ascii")
        + b"\0"
        + config_sha256.encode("ascii")
        + b"\0"
        + decision_payload
    ).hexdigest()
    return strategy_fingerprint, position_fingerprint


def feature_frame_to_decisions(
    feature: pd.DataFrame,
    *,
    allowed_end: str,
) -> pd.Series:
    """Convert a causal feature into +1/-1 decisions; zero or missing carries state."""

    required = {"date", "available_at", "value"}
    missing = sorted(required - set(feature.columns))
    if missing:
        raise DehbWorkerError(f"FEATURE_COLUMN_MISSING:{','.join(missing)}")
    frame = feature.loc[:, ["date", "available_at", "value"]].copy()
    try:
        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
        frame["available_at"] = pd.to_datetime(
            frame["available_at"], errors="raise"
        ).dt.normalize()
    except (TypeError, ValueError) as exc:
        raise DehbWorkerError("INVALID_FEATURE_TIMESTAMP") from exc
    if frame.empty or frame["date"].duplicated().any():
        raise DehbWorkerError("INVALID_FEATURE_DATES")
    if not frame["date"].is_monotonic_increasing:
        raise DehbWorkerError("UNSORTED_FEATURE_DATES")
    if frame["date"].max() > pd.Timestamp(allowed_end).normalize():
        raise DehbWorkerError("FEATURE_DATE_AFTER_ALLOWED_END")
    if (frame["available_at"] > frame["date"]).any():
        raise DehbWorkerError("FEATURE_AVAILABLE_AFTER_DECISION")
    try:
        values = pd.to_numeric(frame["value"], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise DehbWorkerError("NONNUMERIC_FEATURE_VALUE") from exc
    if np.isinf(values.to_numpy()).any():
        raise DehbWorkerError("NONFINITE_FEATURE_VALUE")
    decisions = pd.Series(np.nan, index=pd.DatetimeIndex(frame["date"]), dtype=float)
    numeric_values = values.to_numpy()
    decisions.loc[numeric_values > _DECISION_ZERO_TOLERANCE] = 1.0
    decisions.loc[numeric_values < -_DECISION_ZERO_TOLERANCE] = -1.0
    decisions.name = "decision"
    return decisions


def prepare_lane_candidate(
    config: Any,
    fidelity: float,
    *,
    lane_id: str,
    feature_evaluator: FeatureEvaluator,
    fidelity_years: Mapping[int, tuple[int, ...]],
    allowed_end: str,
) -> PreparedLaneCandidate:
    """Generate and fingerprint positions without running the expensive score."""

    normalized_config = _configuration_dict(config)
    budget = int(float(fidelity))
    if float(fidelity) != float(budget) or budget not in fidelity_years:
        raise DehbWorkerError(f"UNKNOWN_FIDELITY:{fidelity:g}")
    try:
        feature = feature_evaluator(lane_id, normalized_config)
        decisions = feature_frame_to_decisions(feature, allowed_end=allowed_end)
    except (ObjectiveContractError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, DehbWorkerError):
            raise
        raise DehbWorkerError(
            f"LANE_POSITION_BUILD_FAILED:{lane_id}:{type(exc).__name__}:{exc}"
        ) from exc
    strategy_fingerprint, position_fingerprint = candidate_fingerprints(
        lane_id, normalized_config, decisions
    )
    return PreparedLaneCandidate(
        lane_id=str(lane_id),
        configuration=normalized_config,
        fidelity=budget,
        target_years=tuple(int(year) for year in fidelity_years[budget]),
        decisions=decisions,
        strategy_fingerprint=strategy_fingerprint,
        position_fingerprint=position_fingerprint,
    )


def score_prepared_lane_candidate(
    prepared: PreparedLaneCandidate,
    *,
    ledger: pd.DataFrame,
    fidelity_years: Mapping[int, tuple[int, ...]],
    allowed_end: str,
) -> Mapping[str, Any]:
    """Score a verified position path and bind metrics to its originating config."""

    started = time.perf_counter()
    if tuple(fidelity_years.get(prepared.fidelity, ())) != prepared.target_years:
        raise DehbWorkerError("PREPARED_FIDELITY_RECIPE_MISMATCH")
    try:
        objective = score_ledger_decisions(
            ledger,
            prepared.decisions,
            target_years=prepared.target_years,
            allowed_end=allowed_end,
        )
    except (ObjectiveContractError, KeyError, TypeError, ValueError) as exc:
        raise DehbWorkerError(
            f"LANE_OBJECTIVE_FAILED:{prepared.lane_id}:{type(exc).__name__}:{exc}"
        ) from exc
    score = objective.score
    archive_key = candidate_rank_key(score)
    config_sha256 = hashlib.sha256(_canonical_bytes(prepared.configuration)).hexdigest()
    annual = {
        str(year): asdict(row) for year, row in score.annual_returns.items()
    }
    result = {
        "fitness": float(score.dehb_fitness),
        "cost": float(prepared.fidelity),
        "info": {
            "lane_id": prepared.lane_id,
            "fidelity": prepared.fidelity,
            "target_years": list(prepared.target_years),
            "config": dict(prepared.configuration),
            "config_sha256": config_sha256,
            "strategy_fingerprint": prepared.strategy_fingerprint,
            "position_fingerprint": prepared.position_fingerprint,
            "train_feasible": score.feasible,
            "failed_years": list(score.failed_years),
            "annual_returns": annual,
            "annualized_strategy_return": score.annualized_strategy_return,
            "annualized_spy_return": score.annualized_spy_return,
            "annualized_alpha": score.annualized_alpha,
            "weekly_spy_beat_rate": score.weekly_spy_beat_rate,
            "weeks_beating_spy": score.weeks_beating_spy,
            "week_count": score.week_count,
            "archive_key": list(archive_key),
            "objective_runtime_seconds": max(0.0, time.perf_counter() - started),
            "full_fidelity": prepared.fidelity == max(fidelity_years),
            "validation_opened": False,
            "locked_opened": False,
        },
    }
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        normalize_scientific_result,
    )

    return normalize_scientific_result(result)


def evaluate_lane_candidate(
    config: Any,
    fidelity: float,
    *,
    lane_id: str,
    ledger: pd.DataFrame,
    feature_evaluator: FeatureEvaluator,
    fidelity_years: Mapping[int, tuple[int, ...]],
    allowed_end: str,
) -> Mapping[str, Any]:
    """Evaluate one actual lane configuration under one frozen DEHB fidelity."""

    prepared = prepare_lane_candidate(
        config,
        fidelity,
        lane_id=lane_id,
        feature_evaluator=feature_evaluator,
        fidelity_years=fidelity_years,
        allowed_end=allowed_end,
    )
    return score_prepared_lane_candidate(
        prepared,
        ledger=ledger,
        fidelity_years=fidelity_years,
        allowed_end=allowed_end,
    )


def evaluate_physical_lane_candidate(
    config: Any,
    fidelity: float,
    *,
    lane_id: str,
    train_snapshot: str,
    expected_manifest_sha256: str,
    expected_spy_sha256: str,
    default_configurations: Mapping[str, Mapping[str, Any]],
    baseline_feature_dirs: Mapping[str, str],
    fidelity_years: Mapping[int, tuple[int, ...]],
    allowed_end: str,
) -> Mapping[str, Any]:
    """Process-safe official-DEHB objective with one lazy context per worker."""

    baseline_key = tuple(
        sorted((str(name), str(path)) for name, path in baseline_feature_dirs.items())
    )
    key = (
        str(Path(train_snapshot).resolve()),
        expected_manifest_sha256,
        expected_spy_sha256,
        baseline_key,
    )
    context = _PROCESS_CONTEXTS.get(key)
    if context is None:
        from aurora.infra.sp500_megarun.dehb_lane_registry import (
            TrainLaneEvaluator,
        )

        ledger = load_train_total_return_ledger(
            Path(train_snapshot),
            allowed_end=allowed_end,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_spy_sha256=expected_spy_sha256,
        )
        evaluator = TrainLaneEvaluator(
            Path(train_snapshot),
            expected_manifest_sha256=expected_manifest_sha256,
            expected_spy_sha256=expected_spy_sha256,
            default_configurations=default_configurations,
            baseline_feature_dirs={
                name: Path(path) for name, path in baseline_feature_dirs.items()
            },
        )
        context = (ledger, evaluator)
        _PROCESS_CONTEXTS[key] = context
    ledger, evaluator = context
    return evaluate_lane_candidate(
        config,
        fidelity,
        lane_id=lane_id,
        ledger=ledger,
        feature_evaluator=evaluator,
        fidelity_years=fidelity_years,
        allowed_end=allowed_end,
    )


def load_train_total_return_ledger(
    train_snapshot: Path,
    *,
    allowed_end: str,
    expected_manifest_sha256: str,
    expected_spy_sha256: str,
) -> pd.DataFrame:
    """Load only the physically separated train snapshot and build its ledger."""

    snapshot = Path(train_snapshot).resolve()
    if snapshot.name != "train_snapshot_1993_2010":
        raise DehbWorkerError("TRAIN_SNAPSHOT_PARTITION_REQUIRED")
    manifest_path = snapshot / "snapshot_manifest.json"
    spy_path = snapshot / "D_SPY.parquet"
    if not manifest_path.is_file() or not spy_path.is_file():
        raise DehbWorkerError("TRAIN_SNAPSHOT_INCOMPLETE")
    if _sha256_file(manifest_path) != expected_manifest_sha256:
        raise DehbWorkerError("TRAIN_MANIFEST_SHA256_MISMATCH")
    if _sha256_file(spy_path) != expected_spy_sha256:
        raise DehbWorkerError("TRAIN_SPY_SHA256_MISMATCH")
    try:
        manifest = json.loads(manifest_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DehbWorkerError("TRAIN_SNAPSHOT_MANIFEST_INVALID") from exc
    if (
        manifest.get("partition") != "train"
        or manifest.get("validation_opened") is not False
        or manifest.get("locked_opened") is not False
        or manifest.get("mountable_by_first_cycle", True) is not True
    ):
        raise DehbWorkerError("TRAIN_SNAPSHOT_BOUNDARY_OPEN")
    prices = pd.read_parquet(spy_path)
    try:
        return build_adjusted_open_total_return_ledger(
            prices,
            allowed_end=allowed_end,
        )
    except ObjectiveContractError as exc:
        raise DehbWorkerError(f"TRAIN_TOTAL_RETURN_LEDGER_INVALID:{exc}") from exc


__all__ = [
    "DehbWorkerError",
    "FeatureEvaluator",
    "candidate_fingerprints",
    "evaluate_lane_candidate",
    "evaluate_physical_lane_candidate",
    "feature_frame_to_decisions",
    "load_train_total_return_ledger",
]
