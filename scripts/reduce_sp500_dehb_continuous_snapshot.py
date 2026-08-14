"""Build one immutable train-only reducer snapshot on GitHub Actions."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any, Mapping

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract as load_and_validate_data_contract,
)
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace
from aurora.infra.sp500_megarun.dehb_continuous_reducer import ContinuousReducer
from aurora.infra.sp500_megarun.dehb_continuous_robustness import (
    execute_candidate_local_reviews,
)
from aurora.infra.sp500_megarun.dehb_continuous_store import (
    PostgresContinuousCampaignStore,
)
from aurora.infra.sp500_megarun.dehb_robustness import (
    build_physical_candidate_robustness_reviewer,
)
from aurora.infra.sp500_megarun.dehb_finalist_robustness import (
    apply_finalist_train_gate_evidence,
    blocked_signal_placebo_test,
    load_runtime_regime_review,
)
from aurora.infra.sp500_megarun.dehb_global_merge import (
    reconstruct_candidate_returns,
    review_candidate_prefix_invariance,
    select_seed_consensus_finalists,
)
from aurora.infra.sp500_megarun.dehb_global_robustness import (
    evaluate_global_robustness,
)
from aurora.infra.sp500_megarun.dehb_launch_contract import (
    load_and_validate_launch_contract,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


class _RobustnessEnrichedStore:
    def __init__(self, base, enriched_rows):
        self.base = base
        self.enriched_rows = list(enriched_rows)

    def result_rows(self, _cutoff):
        return list(self.enriched_rows)

    def persist_reducer_snapshot(self, snapshot):
        return self.base.persist_reducer_snapshot(snapshot)

    def freeze_campaign(self, snapshot_sha256, winner):
        return self.base.freeze_campaign(snapshot_sha256, winner)


def _candidate_inventory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("full_fidelity") is not True:
            continue
        candidate_id = str(row.get("strategy_fingerprint", ""))
        position = str(row.get("position_fingerprint", ""))
        configuration = row.get("config", row.get("configuration"))
        if len(candidate_id) != 64 or len(position) != 64 or not isinstance(
            configuration, Mapping
        ):
            raise RuntimeError("CONTINUOUS_REDUCER_CANDIDATE_INVALID")
        candidate = {
            "candidate_id": candidate_id,
            "strategy_fingerprint": candidate_id,
            "position_fingerprint": position,
            "lane_id": str(row["lane_id"]),
            "configuration": dict(configuration),
            "archive_key": list(row["archive_key"]),
            "train_feasible": row.get("train_feasible") is True,
        }
        existing = candidates.get(candidate_id)
        if existing is not None and existing != candidate:
            raise RuntimeError("CONTINUOUS_REDUCER_CANDIDATE_CONFLICT")
        candidates[candidate_id] = candidate
    return [candidates[key] for key in sorted(candidates)]


def _close_global_gates(
    gate_matrix: list[Mapping[str, Any]],
    global_row: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_gate = {int(row["gate_id"]): dict(row) for row in gate_matrix}
    gates = global_row.get("gates", {})
    for gate_id in range(43, 49):
        row = by_gate.get(gate_id, {"gate_id": gate_id, "stage": "global_merge"})
        row["status"] = "PASS" if gates.get(str(gate_id)) is True else "FAIL"
        by_gate[gate_id] = row
    return [by_gate[gate_id] for gate_id in range(1, 61)]


def _run_global_reviews(
    *,
    rows: list[dict[str, Any]],
    reviewed: list[dict[str, Any]],
    campaign: Any,
    feature_contract: Any,
    launch: Any,
    runtime_input_pack: Path,
    technical_evidence_path: Path,
    cutoff: int,
    store: Any,
) -> dict[tuple[str, str], dict[str, Any]]:
    finalists = select_seed_consensus_finalists(reviewed)
    if not finalists:
        return {}
    candidates = _candidate_inventory(rows)
    returns, spy = reconstruct_candidate_returns(
        campaign,
        feature_contract,
        launch,
        runtime_input_pack=runtime_input_pack,
        candidate_records=candidates,
    )
    multiplicity = evaluate_global_robustness(
        returns,
        spy,
        finalist_ids=[str(row["strategy_fingerprint"]) for row in finalists],
        raw_trial_count=len(rows),
        strategy_fingerprints={
            str(row["candidate_id"]): str(row["position_fingerprint"])
            for row in candidates
        },
        seed=campaign.master_seed,
    )
    technical = json.loads(technical_evidence_path.read_text("utf-8"))
    train_manifest = json.loads(
        (runtime_input_pack / "train_snapshot_1993_2010" / "snapshot_manifest.json").read_text(
            "utf-8"
        )
    )
    candidates_by_id = {str(row["candidate_id"]): row for row in candidates}
    lanes = {str(lane.lane_id): lane for lane in feature_contract.lanes}
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for finalist in finalists:
        candidate_id = str(finalist["strategy_fingerprint"])
        position = str(finalist["position_fingerprint"])
        global_row = multiplicity["finalists"].get(candidate_id, {})
        prefix = review_candidate_prefix_invariance(
            campaign,
            feature_contract,
            runtime_input_pack=runtime_input_pack,
            candidate_record=candidates_by_id[candidate_id],
        )
        placebo = blocked_signal_placebo_test(
            returns[candidate_id],
            spy,
            seed=campaign.master_seed + int(candidate_id[:8], 16),
        )
        regimes = load_runtime_regime_review(
            runtime_input_pack, returns[candidate_id], spy
        )
        local = finalist.get("robustness")
        if not isinstance(local, Mapping):
            raise RuntimeError("CONTINUOUS_REDUCER_LOCAL_ROBUSTNESS_MISSING")
        lane_id = str(finalist["lane_id"])
        gate_matrix = apply_finalist_train_gate_evidence(
            list(local.get("gate_matrix", ())),
            campaign_sha256=campaign.sha256,
            lane_id=lane_id,
            required_datasets=lanes[lane_id].required_datasets,
            seed_consensus=int(finalist["seed_consensus"]),
            prefix_review=prefix,
            placebo_review=placebo,
            regime_review=regimes,
            train_manifest=train_manifest,
            technical_evidence=technical,
            reconstruction_verified=True,
        )
        gate_matrix = _close_global_gates(gate_matrix, global_row)
        accepted = {"PASS", "MEASURED", "NOT_APPLICABLE"}
        train_gate_ids = (*range(1, 49), *range(55, 61))
        train_freeze_eligible = (
            global_row.get("passed") is True
            and all(gate_matrix[gate_id - 1].get("status") in accepted for gate_id in train_gate_ids)
        )
        evidence = {
            "cutoff_sequence": cutoff,
            "global_robustness_passed": global_row.get("passed") is True,
            "train_freeze_eligible": train_freeze_eligible,
            "multiplicity": dict(global_row),
            "prefix_invariance": prefix,
            "blocked_signal_placebos": placebo,
            "regimes": regimes,
            "gate_matrix": gate_matrix,
            "validation_opened": False,
            "locked_opened": False,
        }
        store.put_robustness_evidence(
            stage="global_merge",
            strategy_fingerprint=candidate_id,
            position_fingerprint=position,
            robustness_seed=campaign.master_seed + cutoff,
            evidence=evidence,
        )
        output[(lane_id, position)] = evidence
    return output


def main() -> int:
    require_github_only_execution("SP500_DEHB_CONTINUOUS_REDUCER_V2")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--launch-contract", type=Path, required=True)
    parser.add_argument("--technical-evidence", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--cutoff-sequence", required=True)
    parser.add_argument("--database-url-env", default="SP500_DEHB_COORDINATOR_DATABASE_URL")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get(args.database_url_env)
    if not dsn:
        raise RuntimeError("CONTINUOUS_REDUCER_DATABASE_URL_MISSING")
    store = PostgresContinuousCampaignStore(dsn=dsn, campaign_id=args.campaign_id)
    cutoff = (
        store.latest_event_sequence()
        if args.cutoff_sequence == "latest"
        else int(args.cutoff_sequence)
    )
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_data_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(
        args.feature_contract, data_contract
    )
    pack = args.runtime_input_pack.resolve()
    launch = load_and_validate_launch_contract(
        args.launch_contract,
        campaign,
        runtime_input_pack=pack,
        technical_evidence_path=args.technical_evidence,
    )
    train_snapshot = pack / "train_snapshot_1993_2010"
    baseline_dirs = {
        "price": pack / "baseline_price",
        "market": pack / "baseline_market",
        "macro": pack / "baseline_macro",
    }
    raw_rows = store.result_rows(cutoff)
    reviewer_cache = {}

    def reviewer(request):
        identity = (request.lane_id, request.robustness_seed)
        bound = reviewer_cache.get(identity)
        if bound is None:
            lane_space = build_lane_configspace(
                feature_contract, request.lane_id, seed=request.robustness_seed
            )
            bound = build_physical_candidate_robustness_reviewer(
                campaign,
                feature_contract,
                lane_id=request.lane_id,
                train_snapshot=train_snapshot,
                baseline_feature_dirs=baseline_dirs,
                lane_configspace=lane_space,
                seed=request.robustness_seed,
            )
            reviewer_cache[identity] = bound
        return bound(
            {"info": dict(request.candidate), "configuration": dict(request.configuration)}
        )

    reviewed = execute_candidate_local_reviews(raw_rows, store=store, reviewer=reviewer)
    global_reviews = _run_global_reviews(
        rows=raw_rows,
        reviewed=reviewed,
        campaign=campaign,
        feature_contract=feature_contract,
        launch=launch,
        runtime_input_pack=pack,
        technical_evidence_path=args.technical_evidence,
        cutoff=cutoff,
        store=store,
    )
    reviewed = [
        {
            **row,
            **global_reviews.get(
                (str(row["lane_id"]), str(row["position_fingerprint"])), {}
            ),
        }
        for row in reviewed
    ]
    by_identity = {
        (row["island_id"], row["strategy_fingerprint"]): row for row in reviewed
    }
    enriched_rows = [
        by_identity.get((row.get("island_id"), row.get("strategy_fingerprint")), row)
        for row in raw_rows
    ]
    reducer = ContinuousReducer(_RobustnessEnrichedStore(store, enriched_rows))
    snapshot = reducer.build_snapshot(cutoff)
    decision = reducer.attempt_train_freeze(snapshot)
    payload = {"snapshot": asdict(snapshot), "decision": asdict(decision)}
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
