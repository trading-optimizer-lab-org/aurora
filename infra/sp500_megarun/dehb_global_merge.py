"""Verified campaign-wide inventory, clone control, and return reconstruction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
        verifier(contract, bundle, expected_island_id=island_id)
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
            if existing is not None and existing != candidate:
                raise GlobalMergeError("CANDIDATE_IDENTITY_COLLISION")
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
    return {
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


def reconstruct_candidate_returns(
    contract: Any,
    feature_contract: Any,
    *,
    runtime_input_pack: Path,
    candidate_records: Sequence[Mapping[str, Any]],
) -> tuple[pd.DataFrame, pd.Series]:
    """Recompute exact train returns for globally unique full-fidelity candidates."""

    from aurora.infra.sp500_megarun.dehb_lane_registry import (
        TrainLaneEvaluator,
        default_lane_configurations,
    )

    expected_aggregate = getattr(contract, "runtime_input_aggregate_sha256", None)
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
    "collect_verified_campaign_inventory",
    "reconstruct_candidate_returns",
    "select_seed_consensus_finalists",
]
