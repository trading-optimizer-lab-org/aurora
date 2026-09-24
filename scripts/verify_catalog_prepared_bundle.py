#!/usr/bin/env python3
"""Verify one restored PREPARED bundle against the checked-out catalog inputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogPreparedReceiptV1,
    CatalogPreparationIdentityV1,
    build_catalog_preparation_identity,
)
from aurora.infra.sp500_megarun.catalog_atlas_cloud_identity import (
    AtlasPreparedReceiptV1,
    AtlasPreparationIdentityV1,
)
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.catalog_atlas_calibration import (
    target_minutes,
    target_recipe_count,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    verify_prepared_catalog_bundle,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract


_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify one PREPARED bundle.")
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--require-live-caches", action="store_true")
    parser.add_argument("--restore-artifact-on-miss", action="store_true")
    return parser


def missing_required_cache_keys(
    required_cache_keys: tuple[str, ...],
    cache_rows: tuple[Mapping[str, Any], ...],
) -> tuple[str, ...]:
    live = {
        str(row.get("key"))
        for row in cache_rows
        if row.get("ref") == "refs/heads/main" and isinstance(row.get("key"), str)
    }
    return tuple(sorted(set(required_cache_keys) - live))


def _verify_live_caches(receipt: CatalogPreparedReceiptV1) -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if not _REPOSITORY.fullmatch(repository) or not token:
        raise ValueError("CATALOG_PREPARED_CACHE_VERIFY_INVOCATION_INVALID")
    client = CatalogGitHubReadOnlyClient(repository, token)
    inventory = client.stable_paginated(
        f"/repos/{repository}/actions/caches?ref=refs/heads/main",
        root="actions_caches",
    ).collection
    missing = missing_required_cache_keys(receipt.required_cache_keys, inventory.rows)
    if missing:
        raise ValueError(f"CATALOG_PREPARED_CACHE_MISSING:{len(missing)}")


_ATLAS_RECEIPT_PATH = "atlas_prepared_receipt.json"
_ATLAS_PLAN_PATH = "plan/atlas_run_plan.json"
_ATLAS_CATALOG_MANIFEST_PATH = "atlas/manifest.json"
_ATLAS_CALIBRATION_PATH = "calibration/calibration_receipt.json"
_ATLAS_SELECTION_PATH = "plan/atlas_campaign_selection.json"
_ATLAS_SUMMARY_PATH = "plan/atlas_plan_summary.json"
_ATLAS_MATRIX_PATH = "plan/atlas_worker_matrices.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_ATLAS_BUNDLE_BYTES = 256 * 1024 * 1024


def _atlas_strict_json(path: Path) -> object:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("CATALOG_ATLAS_BUNDLE_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_ATLAS_BUNDLE_FILE_INVALID")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"CATALOG_ATLAS_BUNDLE_NONFINITE_JSON:{value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("CATALOG_ATLAS_BUNDLE_FILE_INVALID") from exc


def _atlas_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError("CATALOG_ATLAS_BUNDLE_FILE_INVALID") from exc
    return digest.hexdigest()


def _atlas_required_file(root: Path, relative: str) -> Path:
    target = root.joinpath(*relative.split("/"))
    if (
        target.is_symlink()
        or not target.is_file()
        or not target.resolve(strict=True).is_relative_to(root.resolve(strict=True))
    ):
        raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_FILE_MISSING")
    return target


def _atlas_verify_layout(root: Path) -> None:
    """Verify the exact layout emitted by ``prepare_catalog_atlas_bundle``."""

    if root.is_symlink() or not root.is_dir():
        raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_PATH_INVALID")
    required = (
        _ATLAS_RECEIPT_PATH,
        _ATLAS_PLAN_PATH,
        _ATLAS_CATALOG_MANIFEST_PATH,
        _ATLAS_CALIBRATION_PATH,
        _ATLAS_SELECTION_PATH,
        _ATLAS_SUMMARY_PATH,
        _ATLAS_MATRIX_PATH,
    )
    for relative in required:
        _atlas_required_file(root, relative)
    total_bytes = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_SYMLINK_FORBIDDEN")
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            if relative not in {"atlas", "calibration", "plan"}:
                raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_LAYOUT_INVALID")
        elif relative not in required and not relative.startswith("atlas/"):
            # Atlas catalog artifacts are enumerated and hash-bound by its
            # manifest below.  No optimized templates, stores, or arbitrary
            # transport files are part of the Laplace producer schema.
            raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_LAYOUT_INVALID")
        if path.is_file():
            total_bytes += path.stat().st_size
            if total_bytes > _MAX_ATLAS_BUNDLE_BYTES:
                raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_TOO_LARGE")


def _atlas_aware_time(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(code)
    return parsed.astimezone(timezone.utc)


def _atlas_verify_fresh_window(
    *,
    calibration: Mapping[str, object],
    target_end_iso: str,
    requested_recipe_count: int,
    now: datetime,
) -> None:
    """Re-size the cached calibration from the request-time clock.

    The producer's ``available_minutes_to_target`` is measured from the
    calibration stop time.  It is therefore not sufficient evidence for a
    later request: a static bundle may otherwise retain enough capacity for a
    target that is now expired or no longer has room for the full 209906
    recipe plan.
    """

    current = _atlas_aware_time(now.isoformat(), "CATALOG_ATLAS_CLOCK_INVALID")
    target = _atlas_aware_time(target_end_iso, "CATALOG_ATLAS_PREPARED_TARGET_INVALID")
    if target <= current:
        raise ValueError("CATALOG_ATLAS_PREPARED_TARGET_EXPIRED")
    recipes_per_minute = calibration.get("recipes_per_minute")
    safety_fraction = calibration.get("safety_fraction")
    if (
        not isinstance(recipes_per_minute, (int, float))
        or isinstance(recipes_per_minute, bool)
        or not math.isfinite(float(recipes_per_minute))
        or not isinstance(safety_fraction, (int, float))
        or isinstance(safety_fraction, bool)
        or not math.isfinite(float(safety_fraction))
    ):
        raise ValueError("CATALOG_ATLAS_PREPARED_CALIBRATION_INVALID")
    remaining_minutes = target_minutes(
        now_iso=current.isoformat(), target_end_iso=target.isoformat()
    )
    try:
        remaining_capacity = target_recipe_count(
            available_minutes=remaining_minutes,
            recipes_per_minute=float(recipes_per_minute),
            safety_fraction=float(safety_fraction),
        )
    except ValueError as exc:
        raise ValueError("CATALOG_ATLAS_PREPARED_CALIBRATION_INVALID") from exc
    if remaining_capacity < requested_recipe_count:
        raise ValueError("CATALOG_ATLAS_PREPARED_WINDOW_INSUFFICIENT")


def _atlas_identity_hashes_match(
    *, source_root: Path, expected_identity: AtlasPreparationIdentityV1,
    verified: Mapping[str, object],
) -> bool:
    # The preparation identity binds raw repository bytes; the frozen Atlas
    # catalog records the validated contract's canonical semantic hash. Check
    # both representations against the same protected data contract file.
    data_path = source_root / "config/sp500_megarun_free_data_240.json"
    data_semantic_sha256 = load_and_validate_contract(data_path).sha256
    return (
        _atlas_sha256(data_path) == expected_identity.data_contract_sha256
        and verified.get("data_contract_sha256") == data_semantic_sha256
        and all(
            verified.get(key) == getattr(expected_identity, key)
            for key in (
                "scientific_contract_sha256",
                "freeze_manifest_sha256",
                "feature_contract_sha256",
                "selection_sha256",
            )
        )
    )


def verify_atlas_prepared_bundle(
    *,
    bundle_dir: Path,
    expected_identity: AtlasPreparationIdentityV1,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> tuple[AtlasPreparedReceiptV1, Mapping[str, object]]:
    """Verify Atlas PREPARED receipt, finite plan, and exact bundle bytes."""

    bundle_input = Path(bundle_dir)
    if bundle_input.is_symlink():
        raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_PATH_INVALID")
    root = bundle_input.resolve(strict=True)
    source_input = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    if source_input.is_symlink():
        raise ValueError("CATALOG_ATLAS_PREPARATION_REPOSITORY_INVALID")
    source_root = source_input.resolve(strict=True)
    _atlas_verify_layout(root)
    receipt = AtlasPreparedReceiptV1.model_validate(
        _atlas_strict_json(root / _ATLAS_RECEIPT_PATH)
    )
    if receipt.identity != expected_identity:
        raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_STALE")
    calibration = _atlas_strict_json(root / _ATLAS_CALIBRATION_PATH)
    if not isinstance(calibration, Mapping):
        raise ValueError("CATALOG_ATLAS_PREPARED_CALIBRATION_INVALID")
    current = now or datetime.now(timezone.utc)
    _atlas_verify_fresh_window(
        calibration=calibration,
        target_end_iso=receipt.target_end_iso,
        requested_recipe_count=int(_atlas_freeze_value(source_root, "requested_recipe_count")),
        now=current,
    )
    try:
        from aurora.infra.sp500_megarun.catalog_atlas_cloud_identity import (
            verify_atlas_cloud_identity,
        )

        verified = verify_atlas_cloud_identity(
            root / "atlas",
            calibration,
            planned_target_end_iso=receipt.target_end_iso,
            now=current,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        code = str(exc).split(":", 1)[0]
        if code in {
            "ATLAS_CLOUD_IDENTITY_PLANNED_TARGET_EXPIRED",
            "ATLAS_CLOUD_IDENTITY_CALIBRATION_TARGET_EXPIRED",
            "ATLAS_CLOUD_IDENTITY_CALIBRATION_CAPACITY_INSUFFICIENT",
        }:
            mapped = (
                "CATALOG_ATLAS_PREPARED_TARGET_EXPIRED"
                if code.endswith("TARGET_EXPIRED")
                else "CATALOG_ATLAS_PREPARED_WINDOW_INSUFFICIENT"
            )
            raise ValueError(mapped) from exc
        raise ValueError("CATALOG_ATLAS_PREPARED_IDENTITY_INVALID") from exc
    try:
        hashes_match = _atlas_identity_hashes_match(
            source_root=source_root, expected_identity=expected_identity,
            verified=verified,
        )
    except (OSError, ValueError) as exc:
        raise ValueError("CATALOG_ATLAS_PREPARED_IDENTITY_INVALID") from exc
    if not hashes_match:
        raise ValueError("CATALOG_ATLAS_PREPARED_IDENTITY_STALE")
    catalog_manifest = _atlas_strict_json(root / _ATLAS_CATALOG_MANIFEST_PATH)
    if not isinstance(catalog_manifest, Mapping):
        raise ValueError("CATALOG_ATLAS_CATALOG_MANIFEST_INVALID")
    if (
        catalog_manifest.get("manifest_sha256") != _atlas_freeze_value(source_root, "catalog_manifest_sha256", text=True)
        or catalog_manifest.get("target_end_iso") != _atlas_freeze_value(source_root, "target_end_iso", text=True)
        or catalog_manifest.get("validation_opened") is not False
        or catalog_manifest.get("locked_opened") is not False
        or catalog_manifest.get("execution_authorized") is not False
    ):
        raise ValueError("CATALOG_ATLAS_CATALOG_MANIFEST_INVALID")
    _verify_atlas_catalog_artifacts(root / "atlas", catalog_manifest)
    plan_path = root / _ATLAS_PLAN_PATH
    try:
        plan = load_plan(plan_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("CATALOG_ATLAS_PREPARED_PLAN_INVALID") from exc
    if (
        plan.plan_sha256 != receipt.plan_sha256
        or plan.calibration_receipt_sha256 != str(verified["calibration_receipt_sha256"])
        or plan.target_end_iso != receipt.target_end_iso
        or plan.selection_sha256 != receipt.selection_sha256
        or plan.catalog_manifest_sha256 != catalog_manifest.get("manifest_sha256")
        or plan.catalog_space_sha256 != _atlas_freeze_value(source_root, "catalog_space_sha256", text=True)
        or plan.implementation_commit_sha != _atlas_scientific_commit(source_root)
        or plan.validation_opened is not False
        or plan.locked_opened is not False
        or plan.total_shards != _atlas_freeze_value(source_root, "total_shards")
        or plan.requested_recipe_count != _atlas_freeze_value(source_root, "requested_recipe_count")
        or plan.train_end != _atlas_freeze_value(source_root, "train_end", text=True)
    ):
        raise ValueError("CATALOG_ATLAS_PREPARED_PLAN_BINDING_INVALID")
    selection = _atlas_strict_json(root / _ATLAS_SELECTION_PATH)
    summary = _atlas_strict_json(root / _ATLAS_SUMMARY_PATH)
    matrices = _atlas_strict_json(root / _ATLAS_MATRIX_PATH)
    if (
        not isinstance(selection, Mapping)
        or selection.get("selection_sha256") != plan.selection_sha256
        or selection.get("requested_recipe_count") != plan.requested_recipe_count
        or selection.get("seed") != plan.selection_seed
        or not isinstance(summary, Mapping)
        or summary.get("plan_sha256") != plan.plan_sha256
        or summary.get("requested_recipe_count") != plan.requested_recipe_count
        or summary.get("total_shards") != plan.total_shards
        or summary.get("validation_opened") is not False
        or summary.get("locked_opened") is not False
        or summary.get("execution_authorized") is not False
        or not isinstance(matrices, Mapping)
        or tuple(sorted(matrices)) != ("matrix_a", "matrix_b", "matrix_c")
    ):
        raise ValueError("CATALOG_ATLAS_PREPARED_PLAN_OUTPUTS_INVALID")
    return receipt, {
        "manifest_sha256": str(catalog_manifest["manifest_sha256"]),
        "plan_sha256": receipt.plan_sha256,
        "catalog_manifest_sha256": str(catalog_manifest["manifest_sha256"]),
    }


def _atlas_scientific_commit(root: Path) -> str:
    freeze = _atlas_strict_json(root / "config/sp500_atlas_1/freeze_manifest_v1.json")
    if not isinstance(freeze, Mapping):
        raise ValueError("CATALOG_ATLAS_FREEZE_INVALID")
    value = freeze.get("scientific_implementation_commit_sha")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("CATALOG_ATLAS_FREEZE_INVALID")
    return value


def _atlas_freeze_value(root: Path, key: str, *, text: bool = False) -> int | str:
    freeze = _atlas_strict_json(root / "config/sp500_atlas_1/freeze_manifest_v1.json")
    if not isinstance(freeze, Mapping):
        raise ValueError("CATALOG_ATLAS_FREEZE_INVALID")
    value = freeze.get(key)
    if text:
        if not isinstance(value, str):
            raise ValueError("CATALOG_ATLAS_FREEZE_INVALID")
        return value
    if type(value) is not int:
        raise ValueError("CATALOG_ATLAS_FREEZE_INVALID")
    return int(value)


def _verify_atlas_catalog_artifacts(
    catalog_root: Path, manifest: Mapping[str, object]
) -> None:
    artifacts = manifest.get("artifacts_sha256")
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise ValueError("CATALOG_ATLAS_CATALOG_ARTIFACTS_INVALID")
    expected: set[str] = set()
    for relative, digest in artifacts.items():
        if (
            not isinstance(relative, str)
            or not relative
            or relative.replace("\\", "/") != relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
        ):
            raise ValueError("CATALOG_ATLAS_CATALOG_ARTIFACTS_INVALID")
        target = _atlas_required_file(catalog_root, relative)
        if _atlas_sha256(target) != digest:
            raise ValueError("CATALOG_ATLAS_CATALOG_ARTIFACT_HASH_INVALID")
        expected.add(relative)
    actual = {
        path.relative_to(catalog_root).as_posix()
        for path in catalog_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != expected:
        raise ValueError("CATALOG_ATLAS_CATALOG_ARTIFACT_COVERAGE_INVALID")


def verify_bundle(
    *,
    campaign_key: str,
    repo_root: Path,
    bundle: Path,
    github_output: Path | None,
    require_live_caches: bool = False,
    restore_artifact_on_miss: bool = False,
) -> str:
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    if not _COMMIT.fullmatch(expected_commit):
        raise ValueError("CATALOG_PREPARED_VERIFY_INVOCATION_INVALID")
    root = repo_root.resolve(strict=True)
    checked_out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if checked_out != expected_commit:
        raise ValueError("CATALOG_PREPARED_VERIFY_COMMIT_MISMATCH")
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    entry = resolve_catalog_campaign(registry, campaign_key, root)
    identity = build_catalog_preparation_identity(
        repo_root=root,
        registry_entry=entry,
        protected_commit_sha=expected_commit,
    )
    if entry.engine_id == "atlas_static_v1":
        if restore_artifact_on_miss and not bundle.exists():
            # The optimized artifact reader authenticates optimized producer
            # job names and receipt types.  Reusing it for Atlas would be a
            # false component/template fallback, so a missing Atlas bundle is
            # blocked until its own producer/restore protocol is available.
            raise ValueError("CATALOG_ATLAS_PREPARED_BUNDLE_MISSING")
        atlas_receipt, atlas_manifest = verify_atlas_prepared_bundle(
            bundle_dir=bundle,
            expected_identity=identity,
            repo_root=root,
        )
        if github_output is not None:
            if github_output.is_symlink():
                raise ValueError("CATALOG_PREPARED_VERIFY_OUTPUT_INVALID")
            with github_output.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write("prepared_valid=true\n")
                stream.write(f"prepared_receipt_sha256={atlas_receipt.receipt_sha256}\n")
                stream.write(
                    f"prepared_bundle_manifest_sha256={atlas_manifest['manifest_sha256']}\n"
                )
        return atlas_receipt.receipt_sha256

    if restore_artifact_on_miss and not bundle.exists():
        if bundle.is_symlink():
            raise ValueError("CATALOG_PREPARED_BUNDLE_PATH_INVALID")
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GH_TOKEN", "")
        if not _REPOSITORY.fullmatch(repository) or not token:
            raise ValueError("CATALOG_PREPARED_ARTIFACT_INVOCATION_INVALID")
        from aurora.infra.sp500_megarun.catalog_prepared_artifact import restore_prepared_artifact

        restore_prepared_artifact(
            client=CatalogGitHubReadOnlyClient(repository, token),
            expected_identity=identity,
            destination=bundle,
        )
    receipt, manifest = verify_prepared_catalog_bundle(
        bundle_dir=bundle,
        expected_identity=identity,
    )
    if require_live_caches:
        _verify_live_caches(receipt)
    if github_output is not None:
        if github_output.is_symlink():
            raise ValueError("CATALOG_PREPARED_VERIFY_OUTPUT_INVALID")
        with github_output.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("prepared_valid=true\n")
            stream.write(f"prepared_receipt_sha256={receipt.receipt_sha256}\n")
            stream.write(
                f"prepared_bundle_manifest_sha256={manifest.manifest_sha256}\n"
            )
    return receipt.receipt_sha256


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify_bundle(
            campaign_key=args.campaign_key,
            repo_root=args.repo_root,
            bundle=args.bundle,
            github_output=args.github_output,
            require_live_caches=args.require_live_caches,
            restore_artifact_on_miss=args.restore_artifact_on_miss,
        )
        return 0
    except (
        CatalogGitHubSnapshotError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
