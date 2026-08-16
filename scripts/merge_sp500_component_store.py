"""Merge verified component partitions and attach the minimal train ledger input."""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
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


def merge_component_performance(input_root: Path) -> dict[str, object]:
    profiles: dict[str, dict[str, object]] = {}
    shard_seconds: list[float] = []
    for path in sorted(Path(input_root).rglob("component_performance.json")):
        payload = json.loads(path.read_text("utf-8"))
        if (
            payload.get("validation_opened") is not False
            or payload.get("locked_opened") is not False
            or not isinstance(payload.get("component_profiles"), dict)
        ):
            raise ValueError("COMPONENT_PERFORMANCE_INVALID")
        shard_seconds.append(float(payload["shard_seconds"]))
        for key, profile in payload["component_profiles"].items():
            previous = profiles.get(str(key))
            if previous is not None and previous != profile:
                raise ValueError("COMPONENT_PERFORMANCE_CONFLICT")
            profiles[str(key)] = dict(profile)
    if not profiles or not shard_seconds:
        raise ValueError("COMPONENT_PERFORMANCE_MISSING")
    ordered = sorted(shard_seconds)
    p50 = float(statistics.median(ordered))
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {
        "schema_version": 1,
        "component_profiles": profiles,
        "physical_component_builds": len(profiles),
        "physical_component_seconds": sum(
            float(row["physical_seconds"]) for row in profiles.values()
        ),
        "component_worker_seconds": sum(shard_seconds),
        "component_worker_p50_seconds": p50,
        "component_worker_p95_seconds": p95,
        "component_worker_tail_ratio": p95 / p50 if p50 else 1.0,
        "validation_opened": False,
        "locked_opened": False,
    }


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
    performance = merge_component_performance(args.input_root)
    (args.output_dir / "component_performance.json").write_text(
        json.dumps(performance, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
