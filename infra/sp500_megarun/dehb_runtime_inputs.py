"""Build one self-verifying train-only input pack for all DEHB workers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping


class RuntimeInputPackError(ValueError):
    """Raised when a runtime input pack could mix or alter scientific inputs."""


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


__all__ = [
    "RuntimeInputPackError",
    "package_runtime_inputs",
    "scientific_input_binding_sha256",
    "verify_runtime_input_pack",
]
