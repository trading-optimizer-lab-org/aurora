"""Run campaign-wide train-only multiplicity and 60-gate reconciliation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_global_merge import (
    collect_verified_campaign_inventory,
    reconstruct_candidate_returns,
)
from aurora.infra.sp500_megarun.dehb_global_robustness import (
    evaluate_global_robustness,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


def _reconcile_finalist(
    finalist: Mapping[str, Any],
    multiplicity: Mapping[str, Any],
) -> Mapping[str, Any]:
    candidate_id = str(finalist["strategy_fingerprint"])
    global_row = multiplicity["finalists"].get(candidate_id, {})
    local = finalist.get("robustness")
    gate_rows = list(local.get("gate_matrix", ())) if isinstance(local, Mapping) else []
    by_gate = {
        int(row["gate_id"]): dict(row)
        for row in gate_rows
        if isinstance(row, Mapping) and "gate_id" in row
    }
    global_gates = global_row.get("gates", {}) if isinstance(global_row, Mapping) else {}
    for gate_id in range(43, 49):
        row = by_gate.get(gate_id, {"gate_id": gate_id, "stage": "global_merge"})
        row["status"] = "PASS" if global_gates.get(str(gate_id)) is True else "FAIL"
        by_gate[gate_id] = row
    accepted_statuses = {"PASS", "MEASURED", "NOT_APPLICABLE"}
    train_freeze_eligible = len(by_gate) == 60 and all(
        by_gate[gate_id].get("status") in accepted_statuses
        for gate_id in (*range(1, 49), *range(55, 61))
    )
    complete = len(by_gate) == 60 and all(
        row.get("status") in accepted_statuses
        for row in by_gate.values()
    )
    return {
        "strategy_fingerprint": candidate_id,
        "position_fingerprint": str(finalist["position_fingerprint"]),
        "lane_id": str(finalist["lane_id"]),
        "archive_key": list(finalist["archive_key"]),
        "seed_consensus": int(finalist["seed_consensus"]),
        "supporting_islands": list(finalist["supporting_islands"]),
        "candidate_local_robustness_passed": (
            finalist.get("candidate_local_robustness_passed") is True
        ),
        "global_multiplicity_passed": global_row.get("passed") is True,
        "train_freeze_eligible": train_freeze_eligible,
        "all_60_gates_passed": complete,
        "gate_matrix": [by_gate[gate_id] for gate_id in sorted(by_gate)],
    }


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_GLOBAL_REDUCE")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--worker-root", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(
        args.feature_contract, data_contract
    )
    inventory = collect_verified_campaign_inventory(campaign, args.worker_root)
    finalists = inventory["seed_consensus_finalists"]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    multiplicity: Mapping[str, Any] | None = None
    reconciled: list[Mapping[str, Any]] = []
    if finalists:
        returns, spy = reconstruct_candidate_returns(
            campaign,
            feature_contract,
            runtime_input_pack=args.runtime_input_pack,
            candidate_records=inventory["candidates"],
        )
        returns.to_parquet(output / "candidate_train_returns.parquet")
        spy.rename("spy_return").to_frame().to_parquet(
            output / "spy_train_returns.parquet"
        )
        multiplicity = evaluate_global_robustness(
            returns,
            spy,
            finalist_ids=[str(row["strategy_fingerprint"]) for row in finalists],
            raw_trial_count=int(inventory["raw_trial_count"]),
            strategy_fingerprints={
                str(row["candidate_id"]): str(row["position_fingerprint"])
                for row in inventory["candidates"]
            },
            seed=campaign.master_seed,
        )
        reconciled = [
            _reconcile_finalist(finalist, multiplicity)
            for finalist in finalists
        ]
    candidate_frame = pd.DataFrame(
        {
            **dict(row),
            "configuration_json": json.dumps(
                row["configuration"], sort_keys=True, separators=(",", ":")
            ),
        }
        for row in inventory["candidates"]
    ).drop(columns=["configuration"], errors="ignore")
    candidate_frame.to_parquet(output / "candidate_inventory.parquet", index=False)
    report = {
        "schema_version": 1,
        "campaign_contract_sha256": campaign.sha256,
        "island_count": inventory["island_count"],
        "raw_trial_count": inventory["raw_trial_count"],
        "full_fidelity_trial_rows": inventory["full_fidelity_trial_rows"],
        "unique_candidate_count": inventory["unique_candidate_count"],
        "seed_consensus_finalist_count": len(finalists),
        "multiplicity": multiplicity,
        "eligible_finalists": reconciled,
        "all_60_gate_winner_found": any(
            row["all_60_gates_passed"] for row in reconciled
        ),
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "global_robustness.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
