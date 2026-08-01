"""Generate the owner-authorized GTBI V7 new-reference campaign receipt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256

ROOT = Path(__file__).resolve().parents[1]
OLD_READINESS = ROOT / "docs/readiness/gtbi-v7"
NEW_READINESS = ROOT / "docs/readiness/gtbi-v7-new-reference"
PROPOSAL = OLD_READINESS / "new_reference_proposal.json"
OWNER_DECISIONS = OLD_READINESS / "owner_decisions.json"
DATA_RELEASE = OLD_READINESS / "frozen_data_lake_github_release_receipt.json"
PLAN = ROOT / "docs/plans/gtbi-v7-new-reference-campaign.md"
AUTHORIZATION = NEW_READINESS / "campaign_authorization.json"

CAMPAIGN_ID = "gtbi_v7_new_reference_v1"
AUTHORIZED_AT_UTC = "2026-08-01T12:37:48Z"
OWNER_ACTOR_ID = "github-user:271768688"
OWNER_AUTHORIZATION_TEXT = (
    "Autorizo crear GTBI V7 como una campana nueva e independiente de V6, "
    "usando el frozen data lake actual, aceptando que tiene sesgo de "
    "supervivencia y que no reproduce exactamente V6. Manten locked cerrado "
    "hasta que yo autorice abrirlo."
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _validate_sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proposal = _load(PROPOSAL)
    owner = _load(OWNER_DECISIONS)
    data_release = _load(DATA_RELEASE)
    if proposal["status"] != "proposal_only_not_designated_not_approved":
        raise ValueError("unexpected source proposal status")
    if proposal["separate_from_v6"] is not True:
        raise ValueError("new reference must remain separate from V6")
    if proposal["candidate_data_facts"]["survivorship_biased_reference"] is not True:
        raise ValueError("survivorship limitation is missing")
    if proposal["candidate_data_facts"]["point_in_time_claim_allowed"] is not False:
        raise ValueError("point-in-time claims must remain prohibited")
    if owner["decisions"]["budget"]["maximum_incremental_net_spend_usd"] != 0:
        raise ValueError("owner budget permits incremental spend")
    if data_release["status"] != "verified_published_private":
        raise ValueError("frozen data release is not verified")
    if data_release["scientific_cutoff"] != "2020-12-31":
        raise ValueError("scientific cutoff changed")
    if data_release["locked_start"] != "2021-01-01":
        raise ValueError("locked boundary changed")
    if data_release["provider_download_performed"] is not False:
        raise ValueError("campaign authorization must not download provider data")
    return proposal, owner, data_release


def build_authorization() -> dict[str, Any]:
    proposal, owner, data_release = _validate_sources()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_new_reference_campaign_authorization_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "campaign_id": CAMPAIGN_ID,
        "product_identity": "gtbi_v7_performance_engine_new_reference",
        "status": "authorized_historical_preparation",
        "owner_actor_id": OWNER_ACTOR_ID,
        "owner_authorization_text": OWNER_AUTHORIZATION_TEXT,
        "authorized_at_utc": AUTHORIZED_AT_UTC,
        "separate_from_v6": True,
        "v6_reproduction_claim_allowed": False,
        "v6_terminal_closure": {
            "state": "NO_GO_CLOSED",
            "close_id": "NO_GO_CLOSE-1",
            "run_id": 30698392125,
            "evaluated_commit_sha": "d808a0655dc2954df03067f24a148af2ed488e56",
            "receipt_digest": (
                "sha256:d22d2885a8f15a67475f779732b7d524a9af8c54fd6c5c8a74c69de3647114c8"
            ),
        },
        "source_proposal": {
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
            "sha256": raw_sha256(PROPOSAL),
        },
        "campaign_plan": {
            "path": PLAN.relative_to(ROOT).as_posix(),
            "sha256": raw_sha256(PLAN),
        },
        "frozen_data_release": {
            "repository": data_release["repository"],
            "repository_id": data_release["repository_id"],
            "release_id": data_release["release_id"],
            "release_tag": data_release["release_tag"],
            "archive_sha256": data_release["archive_sha256"],
            "archive_size_bytes": data_release["archive_size_bytes"],
            "part_count": data_release["part_count"],
            "source_file_count": data_release["source_file_count"],
            "scientific_cutoff": data_release["scientific_cutoff"],
            "receipt_sha256": raw_sha256(DATA_RELEASE),
        },
        "scientific_boundaries": {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "historical_exclusion_start": "2021-01-01",
            "locked_authorized": False,
            "locked_data_accessed": False,
            "provider_download_performed": False,
            "scientific_processing_performed": False,
            "strategy_evaluation_performed": False,
        },
        "accepted_limitations": {
            "survivorship_biased_reference": True,
            "point_in_time_universe": False,
            "historical_knowability_confirmed": False,
            "retrospectively_adjusted_reference": True,
            "causal_cross_market_alignment_confirmed": False,
        },
        "execution_policy": {
            "github_actions_only": True,
            "local_scientific_runs_allowed": False,
            "runs_on": "ubuntu-24.04",
            "maximum_incremental_net_spend_usd": owner["decisions"]["budget"][
                "maximum_incremental_net_spend_usd"
            ],
            "locked_requires_new_owner_authorization": True,
        },
        "authorized_scope": [
            "historical_data_contract",
            "reference_engine_restore",
            "v7_performance_engine_implementation",
            "one_two_four_worker_equivalence",
            "github_smoke_and_benchmark",
            "full_72000_historical_train_validation_campaign",
            "historical_result_selection_and_preservation",
        ],
        "prohibited_scope": [
            "locked_access",
            "forward_evaluation",
            "local_scientific_execution",
            "provider_refresh",
            "v6_equivalence_claim",
            "point_in_time_claim",
            "survivorship_free_claim",
            "incremental_paid_resource",
        ],
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_NEW_REFERENCE_CAMPAIGN_AUTHORIZATION_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    NEW_READINESS.mkdir(parents=True, exist_ok=True)
    authorization = build_authorization()
    AUTHORIZATION.write_bytes(canonical_bytes(authorization) + b"\n")
    print(AUTHORIZATION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
