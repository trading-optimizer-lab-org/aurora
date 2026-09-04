"""Fail-closed verification of a reusable optimized catalog component store."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from aurora.infra.github_performance.contracts import canonical_sha256
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
    expected_manifest_sha256: str | None = None,
    require_runtime_ledger: bool = False,
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
    if (
        expected_manifest_sha256 is not None
        and manifest.manifest_sha256 != expected_manifest_sha256
    ):
        raise ValueError("COMPONENT_STORE_MANIFEST_IDENTITY_INVALID")
    if manifest.validation_opened or manifest.locked_opened:
        raise ValueError("COMPONENT_STORE_PROTECTED_PERIOD_OPENED")
    for entry in manifest.entries:
        store.get(entry.component_id)

    if not require_runtime_ledger:
        return {
            "component_count": manifest.component_count,
            "manifest_sha256": manifest.manifest_sha256,
            "validation_opened": False,
            "locked_opened": False,
        }

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


def seal_component_bundle(
    root: Path,
    *,
    resolved_contract: Path,
    assignment_file: Path,
    bundle_identity_sha256: str,
    expected_component_count: int,
    expected_bundle_manifest_sha256: str | None = None,
) -> dict[str, object]:
    """Bind rich component identities to the exact stored signal rows."""

    verified = verify_component_store(
        root,
        resolved_contract=resolved_contract,
        expected_component_count=expected_component_count,
    )
    try:
        assignment = json.loads(assignment_file.read_text("utf-8"))
        store_manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("COMPONENT_BUNDLE_ASSIGNMENT_INVALID") from exc
    required_assignment = {
        "schema_version",
        "worker_id",
        "component_ids",
        "component_sources",
        "component_schedule",
        "validation_opened",
        "locked_opened",
    }
    if (
        not isinstance(assignment, dict)
        or set(assignment) != required_assignment
        or assignment.get("schema_version") != "1"
        or assignment.get("validation_opened") is not False
        or assignment.get("locked_opened") is not False
    ):
        raise ValueError("COMPONENT_BUNDLE_ASSIGNMENT_INVALID")
    component_ids = tuple(str(item) for item in assignment["component_ids"])
    component_sources = assignment["component_sources"]
    if not isinstance(component_sources, list):
        raise ValueError("COMPONENT_BUNDLE_ASSIGNMENT_INVALID")
    source_by_component = {
        str(item.get("component_id")): str(
            item.get("source_configuration_sha256")
        )
        for item in component_sources
        if isinstance(item, dict)
        and set(item)
        == {"component_id", "source_configuration_sha256"}
    }
    source_ids = tuple(sorted(source_by_component.values()))
    if (
        component_ids != tuple(sorted(set(component_ids)))
        or source_ids != tuple(sorted(set(source_ids)))
        or tuple(sorted(source_by_component)) != component_ids
        or len(source_by_component) != len(component_sources)
        or len(component_ids) != expected_component_count
        or len(source_ids) != expected_component_count
    ):
        raise ValueError("COMPONENT_BUNDLE_ASSIGNMENT_INVALID")
    store_entries = {
        str(item["component_id"]): str(item["result_sha256"])
        for item in store_manifest.get("entries", ())
        if isinstance(item, dict)
    }
    if set(store_entries) != set(source_ids):
        raise ValueError("COMPONENT_BUNDLE_STORE_COVERAGE_INVALID")
    components = [
        {
            "component_id": component_id,
            "source_configuration_sha256": source_id,
            "result_sha256": store_entries[source_id],
        }
        for component_id in component_ids
        for source_id in (source_by_component[component_id],)
    ]
    identity = {
        "schema_version": "1",
        "bundle_identity_sha256": bundle_identity_sha256,
        "component_store_manifest_sha256": verified["manifest_sha256"],
        "component_count": expected_component_count,
        "components": components,
        "validation_opened": False,
        "locked_opened": False,
    }
    bundle_manifest = {
        **identity,
        "manifest_sha256": canonical_sha256(identity),
    }
    if (
        expected_bundle_manifest_sha256 is not None
        and bundle_manifest["manifest_sha256"]
        != expected_bundle_manifest_sha256
    ):
        raise ValueError("COMPONENT_BUNDLE_MANIFEST_IDENTITY_INVALID")
    target = root / "component_bundle_manifest.json"
    if target.exists():
        existing = json.loads(target.read_text("utf-8"))
        if existing != bundle_manifest:
            raise ValueError("COMPONENT_BUNDLE_MANIFEST_CONFLICT")
    else:
        target.write_text(
            json.dumps(bundle_manifest, indent=2, sort_keys=True) + "\n",
            "utf-8",
        )
    return {
        **bundle_manifest,
        "content_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component-store", type=Path, required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--expected-component-count", type=int, required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--assignment-file", type=Path)
    parser.add_argument("--bundle-identity-sha256")
    parser.add_argument("--cache-key-prefix")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--require-runtime-ledger", action="store_true")
    args = parser.parse_args()
    if (args.assignment_file is None) != (args.bundle_identity_sha256 is None):
        raise SystemExit("COMPONENT_BUNDLE_SEAL_ARGUMENTS_INCOMPLETE")
    if args.assignment_file is not None:
        result = seal_component_bundle(
            args.component_store,
            resolved_contract=args.resolved_contract,
            assignment_file=args.assignment_file,
            bundle_identity_sha256=args.bundle_identity_sha256,
            expected_component_count=args.expected_component_count,
            expected_bundle_manifest_sha256=(
                args.expected_manifest_sha256 or None
            ),
        )
        if args.github_output is not None:
            if not args.cache_key_prefix:
                raise SystemExit("COMPONENT_CACHE_KEY_PREFIX_MISSING")
            cache_key = (
                f"{args.cache_key_prefix}{result['manifest_sha256']}-main"
            )
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"cache_key={cache_key}\n")
                output.write(
                    f"bundle_manifest_sha256={result['manifest_sha256']}\n"
                )
    else:
        result = verify_component_store(
            args.component_store,
            resolved_contract=args.resolved_contract,
            expected_component_count=args.expected_component_count,
            expected_manifest_sha256=(args.expected_manifest_sha256 or None),
            require_runtime_ledger=args.require_runtime_ledger,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
