"""Build one self-verifying train-only input pack for all DEHB workers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence


class RuntimeInputPackError(ValueError):
    """Raised when a runtime input pack could mix or alter scientific inputs."""


# These are the only files large enough to dominate aggregate worker transfer
# in the frozen train-only pack.  The list is part of the infrastructure
# contract, not a heuristic chosen by an individual worker.
RUNTIME_FRAGMENT_DATASET_IDS: tuple[str, ...] = (
    "D_CBOE_PCR",
    "D_CFTC_LEGACY",
    "D_CFTC",
    "D_Z1",
    "D_FED_H3_H6_H8_G19_CP",
    "D_MACRO_PIT",
    "D_FRENCH_US",
    "D_FED_H15_H10",
)


def scientific_input_binding_sha256(contract: Any) -> str:
    """Hash immutable science without creating a campaign/artifact hash cycle."""

    payload = {
        "data_contract_file_sha256": contract.data_contract_file_sha256,
        "data_contract_canonical_sha256": contract.data_contract_canonical_sha256,
        "feature_contract_sha256": contract.feature_contract_sha256,
        "dehb_lock_domain_sha256": contract.dehb_lock_domain_sha256,
        "train_source_run_id": contract.train_source_run_id,
        "train_artifact_digest_sha256": contract.train_artifact_digest_sha256,
        "train_snapshot_manifest_sha256": contract.train_snapshot_manifest_sha256,
        "train_spy_sha256": contract.train_spy_sha256,
        "train_partition": contract.train_partition,
        "search_start": contract.search_start,
        "search_end": contract.search_end,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeInputPackError(f"RUNTIME_INPUT_READ_FAILED:{path.name}") from exc
    return digest.hexdigest()


def package_runtime_inputs(
    *,
    contract: Any,
    train_snapshot: Path,
    baseline_feature_dirs: Mapping[str, Path],
    registry_report: Path,
    baseline_run_id: str,
    output_dir: Path,
) -> Mapping[str, Any]:
    """Copy only verified train inputs and bind every byte into one manifest."""

    roots = {str(name): Path(path).resolve() for name, path in baseline_feature_dirs.items()}
    if set(roots) != {"price", "market", "macro"}:
        raise RuntimeInputPackError("BASELINE_RUNTIME_INPUTS_INCOMPLETE")
    try:
        registry = json.loads(Path(registry_report).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeInputPackError("REGISTRY_REPORT_INVALID") from exc
    if (
        registry.get("ready") is not True
        or registry.get("lane_count") != 240
        or registry.get("campaign_contract_sha256") != contract.sha256
        or registry.get("validation_opened") is not False
        or registry.get("locked_opened") is not False
    ):
        raise RuntimeInputPackError("REGISTRY_REPORT_NOT_READY")
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeInputPackError("RUNTIME_INPUT_OUTPUT_MUST_START_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    copies = {
        "train_snapshot_1993_2010": Path(train_snapshot).resolve(),
        "baseline_price": roots["price"],
        "baseline_market": roots["market"],
        "baseline_macro": roots["macro"],
    }
    for name, source in copies.items():
        if not source.is_dir():
            raise RuntimeInputPackError(f"RUNTIME_INPUT_DIRECTORY_MISSING:{name}")
        shutil.copytree(source, output / name)
    shutil.copy2(Path(registry_report), output / "registry_preflight_report.json")
    files = sorted(path for path in output.rglob("*") if path.is_file())
    inventory = [
        {
            "path": path.relative_to(output).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in files
    ]
    aggregate = hashlib.sha256(
        json.dumps(
            inventory,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": 1,
        "scientific_input_binding_sha256": scientific_input_binding_sha256(contract),
        "source_run_id": contract.train_source_run_id,
        "baseline_run_id": str(baseline_run_id),
        "train_artifact_digest_sha256": contract.train_artifact_digest_sha256,
        "train_snapshot_manifest_sha256": contract.train_snapshot_manifest_sha256,
        "train_spy_sha256": contract.train_spy_sha256,
        "file_count": len(inventory),
        "total_bytes": sum(path.stat().st_size for path in files),
        "aggregate_sha256": aggregate,
        "files": inventory,
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "runtime_input_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def verify_runtime_input_pack(
    root: Path,
    *,
    expected_scientific_input_binding_sha256: str,
    expected_aggregate_sha256: str | None = None,
) -> Mapping[str, Any]:
    """Verify the complete worker input pack before any DEHB process starts."""

    pack = Path(root).resolve()
    try:
        manifest = json.loads((pack / "runtime_input_manifest.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeInputPackError("RUNTIME_INPUT_MANIFEST_INVALID") from exc
    if (
        manifest.get("scientific_input_binding_sha256")
        != expected_scientific_input_binding_sha256
        or manifest.get("validation_opened") is not False
        or manifest.get("locked_opened") is not False
    ):
        raise RuntimeInputPackError("RUNTIME_INPUT_BOUNDARY_OR_CAMPAIGN_MISMATCH")
    inventory = manifest.get("files")
    if not isinstance(inventory, list):
        raise RuntimeInputPackError("RUNTIME_INPUT_INVENTORY_INVALID")
    for row in inventory:
        if not isinstance(row, Mapping):
            raise RuntimeInputPackError("RUNTIME_INPUT_INVENTORY_INVALID")
        target = (pack / str(row.get("path"))).resolve()
        if pack not in target.parents or not target.is_file():
            raise RuntimeInputPackError("RUNTIME_INPUT_FILE_MISSING")
        if target.stat().st_size != row.get("bytes") or _sha256_file(target) != row.get("sha256"):
            raise RuntimeInputPackError(f"RUNTIME_INPUT_FILE_MISMATCH:{target.name}")
    aggregate = hashlib.sha256(
        json.dumps(
            inventory,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if aggregate != manifest.get("aggregate_sha256"):
        raise RuntimeInputPackError("RUNTIME_INPUT_AGGREGATE_MISMATCH")
    if expected_aggregate_sha256 is not None and aggregate != expected_aggregate_sha256:
        raise RuntimeInputPackError("RUNTIME_INPUT_EXPECTED_AGGREGATE_MISMATCH")
    return manifest


def split_runtime_input_pack(
    root: Path,
    output_dir: Path,
    *,
    expected_scientific_input_binding_sha256: str,
    runtime_source_run_id: str,
    selected_partition_ids: Sequence[str] | None = None,
) -> Mapping[str, Any]:
    """Create a verified common core and immutable per-dataset fragments.

    The complete source pack is verified before it is split.  Every output
    byte remains bound to the complete parent inventory; workers may later
    assemble only the core plus the datasets required by their assigned
    components.
    """

    source = Path(root).resolve()
    parent = verify_runtime_input_pack(
        source,
        expected_scientific_input_binding_sha256=(
            expected_scientific_input_binding_sha256
        ),
    )
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeInputPackError("RUNTIME_FRAGMENT_OUTPUT_MUST_START_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    all_partition_ids = (
        "runtime-fragment-core",
        *(f"runtime-fragment-{item}" for item in RUNTIME_FRAGMENT_DATASET_IDS),
    )
    selected = (
        all_partition_ids
        if selected_partition_ids is None
        else tuple(sorted(set(str(item) for item in selected_partition_ids)))
    )
    if not selected or not set(selected).issubset(all_partition_ids):
        raise RuntimeInputPackError("RUNTIME_FRAGMENT_PARTITION_SET_INVALID")
    core = output / "runtime-fragment-core"
    inventory = {
        str(row["path"]): row
        for row in parent["files"]
        if isinstance(row, Mapping)
    }
    split_paths: dict[str, str] = {}
    for dataset_id in RUNTIME_FRAGMENT_DATASET_IDS:
        relative = f"train_snapshot_1993_2010/{dataset_id}.parquet"
        if relative not in inventory:
            raise RuntimeInputPackError(
                f"RUNTIME_FRAGMENT_DATASET_MISSING:{dataset_id}"
            )
        split_paths[dataset_id] = relative

    if "runtime-fragment-core" in selected:
        core.mkdir()
        for relative, row in inventory.items():
            if relative in split_paths.values():
                continue
            source_file = source / relative
            target = core / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
        # The complete manifest is metadata for the fragment verifier and is
        # intentionally not part of its own inventory.
        shutil.copy2(
            source / "runtime_input_manifest.json",
            core / "runtime_input_manifest.json",
        )

    for dataset_id, relative in split_paths.items():
        if f"runtime-fragment-{dataset_id}" not in selected:
            continue
        target_root = output / f"runtime-fragment-{dataset_id}"
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)

    fragment_manifest = {
        "schema_version": 1,
        "runtime_source_run_id": str(runtime_source_run_id),
        "parent_scientific_input_binding_sha256": parent[
            "scientific_input_binding_sha256"
        ],
        "parent_aggregate_sha256": parent["aggregate_sha256"],
        "parent_file_count": parent["file_count"],
        "parent_total_bytes": parent["total_bytes"],
        "split_dataset_ids": list(RUNTIME_FRAGMENT_DATASET_IDS),
        "split_paths": split_paths,
        "validation_opened": False,
        "locked_opened": False,
    }
    if core.is_dir():
        (core / "runtime_fragment_manifest.json").write_text(
            json.dumps(fragment_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {**fragment_manifest, "selected_partition_ids": list(selected)}


def verify_runtime_input_fragments(
    root: Path,
    *,
    expected_scientific_input_binding_sha256: str,
    required_dataset_ids: Sequence[str],
    expected_runtime_source_run_id: str | None = None,
) -> Mapping[str, Any]:
    """Verify an assembled core plus only the required immutable datasets."""

    pack = Path(root).resolve()
    try:
        parent = json.loads((pack / "runtime_input_manifest.json").read_text("utf-8"))
        fragments = json.loads(
            (pack / "runtime_fragment_manifest.json").read_text("utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeInputPackError("RUNTIME_FRAGMENT_MANIFEST_INVALID") from exc
    if (
        parent.get("scientific_input_binding_sha256")
        != expected_scientific_input_binding_sha256
        or fragments.get("parent_scientific_input_binding_sha256")
        != expected_scientific_input_binding_sha256
        or parent.get("validation_opened") is not False
        or parent.get("locked_opened") is not False
        or fragments.get("validation_opened") is not False
        or fragments.get("locked_opened") is not False
    ):
        raise RuntimeInputPackError("RUNTIME_FRAGMENT_BOUNDARY_OR_CAMPAIGN_MISMATCH")
    if expected_runtime_source_run_id is not None and str(
        fragments.get("runtime_source_run_id")
    ) != str(expected_runtime_source_run_id):
        raise RuntimeInputPackError("RUNTIME_FRAGMENT_SOURCE_RUN_MISMATCH")
    parent_files = parent.get("files")
    if not isinstance(parent_files, list):
        raise RuntimeInputPackError("RUNTIME_INPUT_INVENTORY_INVALID")
    parent_by_path = {
        str(row.get("path")): row
        for row in parent_files
        if isinstance(row, Mapping)
    }
    available_dataset_ids = {
        Path(relative).stem
        for relative in parent_by_path
        if relative.startswith("train_snapshot_1993_2010/")
        and relative.endswith(".parquet")
    }
    parent_aggregate = hashlib.sha256(
        json.dumps(
            parent_files,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if parent_aggregate != parent.get("aggregate_sha256"):
        raise RuntimeInputPackError("RUNTIME_FRAGMENT_PARENT_AGGREGATE_MISMATCH")
    if fragments.get("parent_aggregate_sha256") != parent_aggregate:
        raise RuntimeInputPackError("RUNTIME_FRAGMENT_PARENT_BINDING_MISMATCH")
    split_ids = tuple(str(item) for item in fragments.get("split_dataset_ids", ()))
    split_paths = fragments.get("split_paths")
    if not isinstance(split_paths, Mapping) or set(split_paths) != set(split_ids):
        raise RuntimeInputPackError("RUNTIME_FRAGMENT_SPLIT_MANIFEST_INVALID")
    required = tuple(sorted({str(item) for item in required_dataset_ids}))
    for dataset_id in required:
        if dataset_id not in available_dataset_ids and dataset_id not in split_ids:
            raise RuntimeInputPackError(
                f"RUNTIME_FRAGMENT_REQUIRED_DATASET_UNKNOWN:{dataset_id}"
            )
    actual_files = {
        path.relative_to(pack).as_posix(): path
        for path in pack.rglob("*")
        if path.is_file() and path.name != "runtime_fragment_manifest.json"
    }
    # The core must contain every parent file except the explicitly split
    # datasets; it is never allowed to silently omit a small shared input.
    for relative, row in parent_by_path.items():
        is_split = relative in {str(value) for value in split_paths.values()}
        if is_split:
            continue
        target = actual_files.get(relative)
        if target is None:
            raise RuntimeInputPackError(f"RUNTIME_FRAGMENT_CORE_FILE_MISSING:{relative}")
        if target.stat().st_size != row.get("bytes") or _sha256_file(target) != row.get(
            "sha256"
        ):
            raise RuntimeInputPackError(f"RUNTIME_INPUT_FILE_MISMATCH:{target.name}")
    allowed_split_paths = {
        str(split_paths[dataset_id])
        for dataset_id in required
        if dataset_id in split_ids
    }
    for relative, target in actual_files.items():
        row = parent_by_path.get(relative)
        if row is None and relative == "runtime_input_manifest.json":
            continue
        if row is None:
            raise RuntimeInputPackError(f"RUNTIME_FRAGMENT_EXTRA_FILE:{relative}")
        if relative in {str(value) for value in split_paths.values()} and relative not in allowed_split_paths:
            raise RuntimeInputPackError(f"RUNTIME_FRAGMENT_UNREQUESTED_DATASET:{relative}")
        if target.stat().st_size != row.get("bytes") or _sha256_file(target) != row.get(
            "sha256"
        ):
            raise RuntimeInputPackError(f"RUNTIME_INPUT_FILE_MISMATCH:{target.name}")
    for dataset_id in required:
        expected_path = str(split_paths[dataset_id]) if dataset_id in split_ids else None
        if expected_path is not None and expected_path not in actual_files:
            raise RuntimeInputPackError(
                f"RUNTIME_FRAGMENT_REQUIRED_FILE_MISSING:{dataset_id}"
            )
    return {
        **fragments,
        "required_dataset_ids": list(required),
        "assembled_file_count": len(actual_files),
        "assembled_bytes": sum(path.stat().st_size for path in actual_files.values()),
    }


__all__ = [
    "RuntimeInputPackError",
    "package_runtime_inputs",
    "RUNTIME_FRAGMENT_DATASET_IDS",
    "split_runtime_input_pack",
    "scientific_input_binding_sha256",
    "verify_runtime_input_fragments",
    "verify_runtime_input_pack",
]
