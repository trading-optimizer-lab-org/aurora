"""Verified campaign-wide inventory, clone control, and return reconstruction."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.dehb_objective import score_ledger_decisions
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    candidate_fingerprints,
    feature_frame_to_decisions,
    load_train_total_return_ledger,
)


class GlobalMergeError(ValueError):
    """Raised when campaign evidence is missing, duplicated, or inconsistent."""


BundleVerifier = Callable[..., Mapping[str, Any]]
_ARCHIVE_KEY_REL_TOLERANCE = 1e-12
_ARCHIVE_KEY_ABS_TOLERANCE = 1e-12


def candidate_records_equivalent(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    """Compare candidate identity while tolerating replica float serialization noise.

    The strategy and position fingerprints, lane, configuration, and feasibility
    must remain exact. Only archive-score floats may differ within a tight
    numerical tolerance because independent replicas can serialize the same
    deterministic score with a final-bit rounding difference.
    """

    for key in (
        "candidate_id",
        "strategy_fingerprint",
        "position_fingerprint",
        "lane_id",
        "configuration",
        "train_feasible",
    ):
        if left.get(key) != right.get(key):
            return False
    left_archive = left.get("archive_key")
    right_archive = right.get("archive_key")
    if not isinstance(left_archive, Sequence) or isinstance(left_archive, (str, bytes)):
        return False
    if not isinstance(right_archive, Sequence) or isinstance(
        right_archive, (str, bytes)
    ):
        return False
    if len(left_archive) != len(right_archive):
        return False
    try:
        return all(
            math.isfinite(float(left_value))
            and math.isfinite(float(right_value))
            and math.isclose(
                float(left_value),
                float(right_value),
                rel_tol=_ARCHIVE_KEY_REL_TOLERANCE,
                abs_tol=_ARCHIVE_KEY_ABS_TOLERANCE,
            )
            for left_value, right_value in zip(left_archive, right_archive)
        )
    except (TypeError, ValueError):
        return False


def compare_prefix_feature_frames(
    full_feature: pd.DataFrame,
    prefix_feature: pd.DataFrame,
    *,
    cutoff: str,
) -> Mapping[str, Any]:
    """Prove that recomputing with a verified data prefix cannot alter the past."""

    required = ["date", "available_at", "value"]

    def normalize(frame: pd.DataFrame) -> pd.DataFrame:
        missing = sorted(set(required) - set(frame.columns))
        if missing:
            raise GlobalMergeError(
                f"PREFIX_FEATURE_COLUMN_MISSING:{','.join(missing)}"
            )
        result = frame.loc[:, required].copy()
        result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
        result["available_at"] = pd.to_datetime(
            result["available_at"], errors="raise"
        ).dt.normalize()
        result["value"] = pd.to_numeric(result["value"], errors="raise").astype(float)
        return result.sort_values("date", kind="mergesort").reset_index(drop=True)

    boundary = pd.Timestamp(cutoff).normalize()
    expected = normalize(full_feature)
    expected = expected.loc[expected["date"].le(boundary)].reset_index(drop=True)
    actual = normalize(prefix_feature)
    if actual["date"].gt(boundary).any():
        return {
            "cutoff": boundary.date().isoformat(),
            "passed": False,
            "reason": "PREFIX_OUTPUT_AFTER_CUTOFF",
            "expected_rows": int(len(expected)),
            "actual_rows": int(len(actual)),
        }
    if len(expected) != len(actual) or not expected[["date", "available_at"]].equals(
        actual[["date", "available_at"]]
    ):
        return {
            "cutoff": boundary.date().isoformat(),
            "passed": False,
            "reason": "PREFIX_DATES_CHANGED",
            "expected_rows": int(len(expected)),
            "actual_rows": int(len(actual)),
        }
    same_values = np.allclose(
        expected["value"].to_numpy(dtype=float),
        actual["value"].to_numpy(dtype=float),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    return {
        "cutoff": boundary.date().isoformat(),
        "passed": bool(same_values),
        "reason": None if same_values else "PREFIX_VALUES_CHANGED",
        "expected_rows": int(len(expected)),
        "actual_rows": int(len(actual)),
    }


def review_candidate_prefix_invariance(
    contract: Any,
    feature_contract: Any,
    *,
    runtime_input_pack: Path,
    candidate_record: Mapping[str, Any],
    cutoffs: Sequence[str] = ("2001-12-31", "2005-12-31", "2008-12-31"),
) -> Mapping[str, Any]:
    """Recompute one candidate against several physically hidden train prefixes."""

    from aurora.infra.sp500_megarun.dehb_lane_registry import (
        LaneRegistryError,
        TrainLaneEvaluator,
        default_lane_configurations,
    )

    pack = Path(runtime_input_pack).resolve()
    common = {
        "train_snapshot": pack / "train_snapshot_1993_2010",
        "expected_manifest_sha256": contract.train_snapshot_manifest_sha256,
        "expected_spy_sha256": contract.train_spy_sha256,
        "default_configurations": default_lane_configurations(feature_contract),
        "baseline_feature_dirs": {
            "price": pack / "baseline_price",
            "market": pack / "baseline_market",
            "macro": pack / "baseline_macro",
        },
    }
    lane_id = str(candidate_record["lane_id"])
    configuration = candidate_record.get("configuration")
    if not isinstance(configuration, Mapping):
        raise GlobalMergeError("CANDIDATE_CONFIGURATION_INVALID")
    warm_evaluator = TrainLaneEvaluator(**common)
    full = warm_evaluator(lane_id, configuration)
    hot = warm_evaluator(lane_id, configuration)
    cold = TrainLaneEvaluator(**common)(lane_id, configuration)
    hot_cache = compare_prefix_feature_frames(
        full, hot, cutoff=str(contract.search_end)
    )
    cold_cache = compare_prefix_feature_frames(
        full, cold, cutoff=str(contract.search_end)
    )
    rows: list[Mapping[str, Any]] = []
    for cutoff in cutoffs:
        expected_count = int(
            pd.to_datetime(full["date"], errors="raise")
            .dt.normalize()
            .le(pd.Timestamp(cutoff).normalize())
            .sum()
        )
        if expected_count == 0:
            rows.append(
                {
                    "cutoff": cutoff,
                    "passed": None,
                    "reason": "NO_CANDIDATE_OUTPUT_YET",
                    "expected_rows": 0,
                    "actual_rows": 0,
                }
            )
            continue
        try:
            prefix = TrainLaneEvaluator(**common, maximum_date=cutoff)(
                lane_id, configuration
            )
        except LaneRegistryError as exc:
            rows.append(
                {
                    "cutoff": cutoff,
                    "passed": False,
                    "reason": f"PREFIX_RECOMPUTE_FAILED:{exc}",
                    "expected_rows": expected_count,
                    "actual_rows": 0,
                }
            )
            continue
        rows.append(compare_prefix_feature_frames(full, prefix, cutoff=cutoff))
    evaluated = [row for row in rows if row["passed"] is not None]
    cache_reproduction_passed = (
        hot_cache["passed"] is True and cold_cache["passed"] is True
    )
    return {
        "schema_version": 1,
        "lane_id": lane_id,
        "strategy_fingerprint": str(candidate_record["candidate_id"]),
        "cutoffs": rows,
        "evaluated_prefix_count": len(evaluated),
        "hot_cache_reproduction": hot_cache,
        "cold_cache_reproduction": cold_cache,
        "cache_reproduction_passed": cache_reproduction_passed,
        "passed": (
            bool(evaluated)
            and all(row["passed"] is True for row in evaluated)
            and cache_reproduction_passed
        ),
        "validation_opened": False,
        "locked_opened": False,
    }


def select_seed_consensus_finalists(
    champions: Sequence[Mapping[str, Any]],
    *,
    required_replicates: int = 2,
) -> list[Mapping[str, Any]]:
    """Select one representative per behavior found by enough independent seeds."""

    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for champion in champions:
        if (
            champion.get("full_fidelity") is not True
            or champion.get("train_feasible") is not True
            or champion.get("candidate_local_robustness_passed") is not True
        ):
            continue
        lane_id = str(champion.get("lane_id", ""))
        position_fingerprint = str(champion.get("position_fingerprint", ""))
        if not lane_id or len(position_fingerprint) != 64:
            raise GlobalMergeError("CHAMPION_FINGERPRINT_INVALID")
        grouped.setdefault((lane_id, position_fingerprint), []).append(champion)
    finalists: list[Mapping[str, Any]] = []
    for (lane_id, position_fingerprint), rows in grouped.items():
        replicates = {int(row.get("replicate", 0)) for row in rows}
        if len(replicates) < required_replicates:
            continue
        representative = min(
            rows,
            key=lambda row: tuple(float(value) for value in row["archive_key"]),
        )
        finalists.append(
            {
                **dict(representative),
                "lane_id": lane_id,
                "position_fingerprint": position_fingerprint,
                "seed_consensus": len(replicates),
                "supporting_islands": sorted(
                    str(row["island_id"]) for row in rows
                ),
            }
        )
    return sorted(
        finalists,
        key=lambda row: (
            tuple(float(value) for value in row["archive_key"]),
            str(row["lane_id"]),
            str(row["strategy_fingerprint"]),
        ),
    )


def collect_verified_campaign_inventory(
    contract: Any,
    worker_root: Path,
    *,
    launch_contract_sha256: str | None = None,
    bundle_verifier: BundleVerifier | None = None,
) -> Mapping[str, Any]:
    """Read all 720 cumulative island bundles and count every attempted trial."""

    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        build_island_schedule,
    )
    from aurora.infra.sp500_megarun.dehb_island_runner import verify_island_bundle

    verifier = bundle_verifier or verify_island_bundle
    expected = {
        island.island_id
        for job in build_island_schedule(contract)
        for island in job.islands
    }
    manifests = sorted(Path(worker_root).rglob("island_manifest.json"))
    by_island: dict[str, Path] = {}
    for path in manifests:
        try:
            manifest = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GlobalMergeError(f"ISLAND_MANIFEST_INVALID:{path}") from exc
        island_id = str(manifest.get("island_id", ""))
        if island_id in by_island:
            raise GlobalMergeError(f"DUPLICATE_ISLAND_BUNDLE:{island_id}")
        by_island[island_id] = path.parent
    if set(by_island) != expected:
        missing = sorted(expected - set(by_island))
        extra = sorted(set(by_island) - expected)
        raise GlobalMergeError(
            f"ISLAND_BUNDLE_COVERAGE_MISMATCH:missing={len(missing)}:extra={len(extra)}"
        )
    raw_trial_count = 0
    full_fidelity_rows = 0
    candidates: dict[str, dict[str, Any]] = {}
    champions: list[dict[str, Any]] = []
    for island_id in sorted(by_island):
        bundle = by_island[island_id]
        verifier(
            contract,
            bundle,
            expected_island_id=island_id,
            **(
                {"expected_launch_contract_sha256": launch_contract_sha256}
                if launch_contract_sha256 is not None
                else {}
            ),
        )
        manifest = json.loads((bundle / "island_manifest.json").read_text("utf-8"))
        trial_frame = pd.read_parquet(bundle / "trial_ledger.parquet")
        candidate_frame = pd.read_parquet(bundle / "full_fidelity_candidates.parquet")
        raw_trial_count += len(trial_frame)
        full_fidelity_rows += len(candidate_frame)
        lane_id = str(manifest["lane_id"])
        for row in candidate_frame.to_dict(orient="records"):
            try:
                info = json.loads(str(row["info_json"]))
                configuration = json.loads(str(row["configuration_json"]))
            except (json.JSONDecodeError, TypeError) as exc:
                raise GlobalMergeError("CANDIDATE_JSON_INVALID") from exc
            identity = str(row.get("strategy_fingerprint", ""))
            position = str(row.get("position_fingerprint", ""))
            if (
                len(identity) != 64
                or len(position) != 64
                or info.get("lane_id") != lane_id
                or info.get("full_fidelity") is not True
            ):
                raise GlobalMergeError("CANDIDATE_RECORD_INVALID")
            candidate = {
                "candidate_id": identity,
                "strategy_fingerprint": identity,
                "position_fingerprint": position,
                "lane_id": lane_id,
                "configuration": configuration,
                "archive_key": info["archive_key"],
                "train_feasible": info.get("train_feasible") is True,
            }
            existing = candidates.get(identity)
            if existing is not None:
                if not candidate_records_equivalent(existing, candidate):
                    raise GlobalMergeError("CANDIDATE_IDENTITY_COLLISION")
                continue
            candidates[identity] = candidate
        champion = manifest.get("champion")
        if isinstance(champion, Mapping):
            champions.append(
                {
                    **dict(champion),
                    "lane_id": lane_id,
                    "replicate": int(manifest["replicate"]),
                    "island_id": island_id,
                }
            )
    finalists = select_seed_consensus_finalists(champions)
    inventory = {
        "schema_version": 1,
        "island_count": len(by_island),
        "raw_trial_count": raw_trial_count,
        "full_fidelity_trial_rows": full_fidelity_rows,
        "unique_candidate_count": len(candidates),
        "candidates": list(candidates.values()),
        "champions": champions,
        "seed_consensus_finalists": finalists,
        "validation_opened": False,
        "locked_opened": False,
    }
    if launch_contract_sha256 is not None:
        inventory["launch_contract_sha256"] = launch_contract_sha256
    return inventory


def reconstruct_candidate_returns(
    contract: Any,
    feature_contract: Any,
    launch_contract: Any,
    *,
    runtime_input_pack: Path,
    candidate_records: Sequence[Mapping[str, Any]],
) -> tuple[pd.DataFrame, pd.Series]:
    """Recompute exact train returns for globally unique full-fidelity candidates."""

    from aurora.infra.sp500_megarun.dehb_lane_registry import (
        TrainLaneEvaluator,
        default_lane_configurations,
    )

    if launch_contract.campaign_contract_sha256 != contract.sha256:
        raise GlobalMergeError("LAUNCH_CONTRACT_CAMPAIGN_MISMATCH")
    expected_aggregate = getattr(
        launch_contract, "runtime_input_aggregate_sha256", None
    )
    if not isinstance(expected_aggregate, str) or len(expected_aggregate) != 64:
        raise GlobalMergeError("RUNTIME_INPUT_AGGREGATE_NOT_FROZEN")
    pack = Path(runtime_input_pack).resolve()
    verify_runtime_input_pack(
        pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(
            contract
        ),
        expected_aggregate_sha256=expected_aggregate,
    )
    train = pack / "train_snapshot_1993_2010"
    ledger = load_train_total_return_ledger(
        train,
        allowed_end=contract.search_end,
        expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
        expected_spy_sha256=contract.train_spy_sha256,
    )
    evaluator = TrainLaneEvaluator(
        train,
        expected_manifest_sha256=contract.train_snapshot_manifest_sha256,
        expected_spy_sha256=contract.train_spy_sha256,
        default_configurations=default_lane_configurations(feature_contract),
        baseline_feature_dirs={
            "price": pack / "baseline_price",
            "market": pack / "baseline_market",
            "macro": pack / "baseline_macro",
        },
    )
    full_years = max(contract.fidelities, key=lambda item: item.budget).years
    columns: dict[str, pd.Series] = {}
    benchmark: pd.Series | None = None
    for record in candidate_records:
        candidate_id = str(record["candidate_id"])
        lane_id = str(record["lane_id"])
        configuration = record["configuration"]
        if not isinstance(configuration, Mapping):
            raise GlobalMergeError("CANDIDATE_CONFIGURATION_INVALID")
        feature = evaluator(lane_id, configuration)
        decisions = feature_frame_to_decisions(feature, allowed_end=contract.search_end)
        identity, position = candidate_fingerprints(lane_id, configuration, decisions)
        if (
            identity != candidate_id
            or position != record.get("position_fingerprint")
        ):
            raise GlobalMergeError("RECONSTRUCTED_FINGERPRINT_MISMATCH")
        scored = score_ledger_decisions(
            ledger,
            decisions,
            target_years=full_years,
            allowed_end=contract.search_end,
        )
        columns[candidate_id] = scored.strategy_returns
        if benchmark is None:
            benchmark = scored.spy_returns
        elif not benchmark.equals(scored.spy_returns):
            raise GlobalMergeError("RECONSTRUCTED_BENCHMARK_CHANGED")
    if benchmark is None:
        raise GlobalMergeError("NO_CANDIDATE_RETURNS_TO_RECONSTRUCT")
    return pd.DataFrame(columns), benchmark


__all__ = [
    "GlobalMergeError",
    "compare_prefix_feature_frames",
    "collect_verified_campaign_inventory",
    "reconstruct_candidate_returns",
    "review_candidate_prefix_invariance",
    "select_seed_consensus_finalists",
]
