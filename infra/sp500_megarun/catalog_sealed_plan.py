"""Lightweight verification for immutable catalog execution plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from aurora.infra.github_performance.contracts import canonical_sha256


def verify_sealed_global_reuse_execution_plan(
    root: Path,
    *,
    expected_bindings: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Read back every sealed byte and every compact descriptor route."""

    sealed = Path(root).resolve(strict=True)
    required_files = {
        "resolved_contract.json",
        "controller_binding.json",
        "rebuildable_store_plan.json",
        "logical_recipe_manifest.json",
        "component_requirement_manifest.json",
        "component_store_input_manifest.json",
        "pending_component_manifest.json",
        "cached_component_manifest.json",
        "component_matrix_a.json",
        "component_matrix_b.json",
        "cached_component_matrix_a.json",
        "cached_component_matrix_b.json",
        "recipe_assignment_bundle.zip",
        "recipe_matrix_a.json",
        "recipe_matrix_b.json",
        "recipe_matrix_c.json",
        "payload_bundle_manifest.json",
        "checkpoint_policy.json",
        "reduction_plan.json",
        "artifact_plan.json",
        "source_artifacts.json",
        "execution_plan_receipt.json",
    }
    present = {path.name for path in sealed.iterdir() if path.is_file()}
    if not required_files.issubset(present):
        raise ValueError("CATALOG_SEALED_PLAN_FILES_MISSING")
    try:
        receipt = json.loads(
            (sealed / "execution_plan_receipt.json").read_text("utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ValueError("CATALOG_SEALED_PLAN_RECEIPT_INVALID") from exc
    if not isinstance(receipt, dict):
        raise ValueError("CATALOG_SEALED_PLAN_RECEIPT_INVALID")
    receipt_identity = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    if canonical_sha256(receipt_identity) != receipt.get("receipt_sha256"):
        raise ValueError("CATALOG_SEALED_PLAN_RECEIPT_HASH_INVALID")
    if (
        receipt.get("schema_version") != "1"
        or receipt.get("validation_opened") is not False
        or receipt.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_SEALED_PLAN_BOUNDARY_INVALID")
    if expected_bindings is not None and any(
        receipt.get(key) != value for key, value in expected_bindings.items()
    ):
        raise ValueError("CATALOG_SEALED_PLAN_BINDING_INVALID")
    manifest = receipt.get("content_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_INVALID")
    seen_paths: set[str] = set()
    for item in manifest:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_INVALID")
        relative = Path(str(item["path"]))
        relative_text = relative.as_posix()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative_text in seen_paths
        ):
            raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_INVALID")
        seen_paths.add(relative_text)
        target = sealed / relative
        if (
            not target.is_file()
            or target.stat().st_size != item["size_bytes"]
            or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("CATALOG_SEALED_PLAN_CONTENT_INVALID")
    all_sealed_files = {
        path.relative_to(sealed).as_posix()
        for path in sealed.rglob("*")
        if path.is_file() and path.name != "execution_plan_receipt.json"
    }
    if seen_paths != all_sealed_files:
        raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_COVERAGE_INVALID")
    if canonical_sha256(tuple(manifest)) != receipt.get(
        "content_manifest_sha256"
    ):
        raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_HASH_INVALID")

    matrix_names = (
        "component_matrix_a",
        "component_matrix_b",
        "cached_component_matrix_a",
        "cached_component_matrix_b",
        "recipe_matrix_a",
        "recipe_matrix_b",
        "recipe_matrix_c",
    )
    combined_utf16 = 0
    route_keys: set[tuple[str, str]] = set()
    for name in matrix_names:
        try:
            matrix = json.loads((sealed / f"{name}.json").read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("CATALOG_MATRIX_SCHEMA_INVALID") from exc
        rows = matrix.get("include") if isinstance(matrix, dict) else None
        if set(matrix) != {"include"} or not isinstance(rows, list):
            raise ValueError("CATALOG_MATRIX_SCHEMA_INVALID")
        canonical_output = json.dumps(
            matrix,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        combined_utf16 += len(canonical_output.encode("utf-16-le"))
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "worker_id",
                "descriptor_bundle_artifact",
                "descriptor_member",
                "descriptor_sha256",
            }:
                raise ValueError("CATALOG_MATRIX_ROW_INVALID")
            route = (
                str(row["descriptor_bundle_artifact"]),
                str(row["descriptor_member"]),
            )
            if route in route_keys:
                raise ValueError("CATALOG_MATRIX_ROUTE_DUPLICATE")
            route_keys.add(route)
            descriptor = sealed / "payload_artifacts" / route[0] / route[1]
            if (
                not descriptor.is_file()
                or hashlib.sha256(descriptor.read_bytes()).hexdigest()
                != row["descriptor_sha256"]
            ):
                raise ValueError("CATALOG_SEALED_PLAN_CONTENT_INVALID")
    if combined_utf16 > 512 * 1024:
        raise ValueError("CATALOG_MATRIX_OUTPUT_BUDGET_EXCEEDED")

    payload_manifest = json.loads(
        (sealed / "payload_bundle_manifest.json").read_text("utf-8")
    )
    payload_rows = payload_manifest.get("payloads")
    if not isinstance(payload_rows, list) or not payload_rows:
        raise ValueError("CATALOG_PAYLOAD_BUNDLE_MANIFEST_INVALID")
    for item in payload_rows:
        if not isinstance(item, dict) or set(item) != {
            "artifact",
            "member",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("CATALOG_PAYLOAD_BUNDLE_MANIFEST_INVALID")
        target = (
            sealed
            / "payload_artifacts"
            / str(item["artifact"])
            / str(item["member"])
        )
        if (
            not target.is_file()
            or target.stat().st_size != item["size_bytes"]
            or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("CATALOG_SEALED_PLAN_CONTENT_INVALID")
    return receipt


__all__ = ["verify_sealed_global_reuse_execution_plan"]
