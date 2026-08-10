"""Run one official-DEHB SP500 island on GitHub Actions only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_island_runner import (
    run_official_dehb_island,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


class IslandCliError(ValueError):
    """Raised when a GitHub worker payload is incomplete or altered."""


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_payload(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IslandCliError("JOB_PAYLOAD_INVALID") from exc
    if not isinstance(value, Mapping):
        raise IslandCliError("JOB_PAYLOAD_NOT_MAPPING")
    expected = value.get("payload_sha256")
    preimage = {key: item for key, item in value.items() if key != "payload_sha256"}
    if expected != _canonical_hash(preimage):
        raise IslandCliError("JOB_PAYLOAD_SHA256_MISMATCH")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--job-payload", type=Path, required=True)
    parser.add_argument("--island-id", required=True)
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--baseline-price", type=Path, required=True)
    parser.add_argument("--baseline-market", type=Path, required=True)
    parser.add_argument("--baseline-macro", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prior-bundle", type=Path)
    parser.add_argument("--slice-seconds", type=float)
    args = parser.parse_args()

    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise IslandCliError("GITHUB_ACTIONS_REQUIRED_FOR_REAL_DEHB_ISLAND")
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(
        args.feature_contract, data_contract
    )
    payload = _load_payload(args.job_payload)
    if payload.get("campaign_contract_sha256") != campaign.sha256:
        raise IslandCliError("JOB_CAMPAIGN_SHA256_MISMATCH")
    exact_inputs = {
        "train_source_run_id": campaign.train_source_run_id,
        "train_artifact_name": campaign.train_artifact_name,
        "train_artifact_digest_sha256": campaign.train_artifact_digest_sha256,
        "train_snapshot_manifest_sha256": campaign.train_snapshot_manifest_sha256,
        "train_spy_sha256": campaign.train_spy_sha256,
        "train_partition": campaign.train_partition,
        "search_end": campaign.search_end,
        "validation_opened": False,
        "locked_opened": False,
    }
    for key, expected in exact_inputs.items():
        if payload.get(key) != expected:
            raise IslandCliError(f"JOB_SCIENTIFIC_INPUT_MISMATCH:{key}")
    islands = payload.get("islands")
    if not isinstance(islands, list) or len(islands) != 2:
        raise IslandCliError("JOB_ISLAND_ASSIGNMENTS_INVALID")
    matches = [
        row
        for row in islands
        if isinstance(row, Mapping) and row.get("island_id") == args.island_id
    ]
    if len(matches) != 1:
        raise IslandCliError(f"ISLAND_ASSIGNMENT_NOT_UNIQUE:{args.island_id}")

    manifest = run_official_dehb_island(
        campaign,
        feature_contract,
        assignment=matches[0],
        wave=int(payload["wave"]),
        train_snapshot=args.train_snapshot,
        baseline_feature_dirs={
            "price": args.baseline_price,
            "market": args.baseline_market,
            "macro": args.baseline_macro,
        },
        output_dir=args.output_dir,
        prior_bundle=args.prior_bundle,
        slice_seconds=args.slice_seconds,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
