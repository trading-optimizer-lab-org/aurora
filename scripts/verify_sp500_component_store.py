"""Fail-closed verification of a reusable optimized catalog component store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.sp500_megarun.catalog_component_store import CatalogComponentStore
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)


def verify_component_store(
    root: Path,
    *,
    resolved_contract: Path,
    expected_component_count: int,
) -> dict[str, object]:
    resolved = RunOptimizationContractV1.model_validate_json(
        resolved_contract.read_text("utf-8")
    )
    store = CatalogComponentStore.open(
        root,
        expected_data_snapshot_sha256=resolved.science.data_snapshot_sha256,
        expected_evaluator_sha256=resolved.science.evaluator_sha256,
    )
    manifest = store.manifest
    if manifest.component_count != expected_component_count:
        raise ValueError("COMPONENT_STORE_COUNT_INVALID")
    if manifest.validation_opened or manifest.locked_opened:
        raise ValueError("COMPONENT_STORE_PROTECTED_PERIOD_OPENED")
    for entry in manifest.entries:
        store.get(entry.component_id)

    runtime_path = root / "runtime_manifest.json"
    try:
        runtime = json.loads(runtime_path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("COMPONENT_RUNTIME_MANIFEST_INVALID") from exc
    if (
        runtime.get("component_manifest_sha256") != manifest.manifest_sha256
        or runtime.get("search_end") != "2010-12-31"
        or runtime.get("validation_opened") is not False
        or runtime.get("locked_opened") is not False
    ):
        raise ValueError("COMPONENT_RUNTIME_MANIFEST_INCOMPATIBLE")
    train_files = runtime.get("train_files")
    if not isinstance(train_files, dict):
        raise ValueError("COMPONENT_RUNTIME_MANIFEST_INVALID")
    for filename in ("snapshot_manifest.json", "D_SPY.parquet"):
        expected = train_files.get(filename)
        path = root / "train_snapshot_1993_2010" / filename
        if not isinstance(expected, str) or sha256_file(path) != expected:
            raise ValueError("COMPONENT_RUNTIME_FILE_HASH_INVALID")
    return {
        "component_count": manifest.component_count,
        "manifest_sha256": manifest.manifest_sha256,
        "validation_opened": False,
        "locked_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component-store", type=Path, required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--expected-component-count", type=int, required=True)
    args = parser.parse_args()
    result = verify_component_store(
        args.component_store,
        resolved_contract=args.resolved_contract,
        expected_component_count=args.expected_component_count,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
