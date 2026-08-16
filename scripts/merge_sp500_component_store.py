"""Merge verified component partitions and attach the minimal train ledger input."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.sp500_megarun.catalog_admission import verify_catalog_plan_token
from aurora.infra.sp500_megarun.catalog_component_store import merge_component_stores
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--expected-component-count", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    verify_catalog_plan_token(
        args.run_plan,
        admission_token_sha256=args.admission_token,
    )
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    verify_runtime_input_pack(
        args.runtime_input_pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(
            campaign
        ),
    )
    roots = sorted(
        {
            path.parent
            for path in args.input_root.rglob("manifest.json")
            if (path.parent / "signals.npy").is_file()
        }
    )
    manifest = merge_component_stores(roots, args.output_dir)
    if manifest.component_count != args.expected_component_count:
        raise SystemExit(
            "COMPONENT_STORE_COUNT_INVALID:"
            f"{manifest.component_count}:{args.expected_component_count}"
        )
    source_snapshot = args.runtime_input_pack / "train_snapshot_1993_2010"
    target_snapshot = args.output_dir / "train_snapshot_1993_2010"
    target_snapshot.mkdir()
    copied: dict[str, str] = {}
    for filename in ("snapshot_manifest.json", "D_SPY.parquet"):
        source = source_snapshot / filename
        target = target_snapshot / filename
        shutil.copy2(source, target)
        copied[filename] = sha256_file(target)
    runtime_identity = {
        "schema_version": 1,
        "component_manifest_sha256": manifest.manifest_sha256,
        "train_files": copied,
        "search_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
    }
    (args.output_dir / "runtime_manifest.json").write_text(
        json.dumps(runtime_identity, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
