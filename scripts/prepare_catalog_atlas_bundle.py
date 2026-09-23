"""Build a fail-closed, train-only Atlas PREPARED bundle from official evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
from typing import Mapping, NoReturn

from aurora.infra.sp500_megarun.atlas_execution_contract import AtlasRunPlanV1
from aurora.infra.sp500_megarun.catalog_atlas_cloud_identity import (
    AtlasPreparationIdentityV1,
    create_atlas_prepared_receipt,
    verify_atlas_cloud_identity,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
    verify_catalog_campaign_definition,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogAtlasCampaignEntryV1,
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract
from scripts.plan_sp500_atlas_run import plan_atlas_run


REPOSITORY = "trading-optimizer-lab-org/aurora"
PLANNING_DAYS = 7
CATALOG_TARGET_END_ISO = "2026-08-20T07:31:00+02:00"
REQUESTED_RECIPE_COUNT = 209906
TOTAL_SHARDS = 360
SELECTION_SEED = 20260818
TRAIN_END = "2010-12-31"
EXPECTED_FREEZE = {
    "catalog_id": "sp500-atlas-1",
    "catalog_manifest_sha256": "09068cf0b0ff716075bdd693dbdfbdcf3779c7cb326a92aca11d9ab22b577f08",
    "catalog_space_sha256": "c5a29064acd626a0aa67559222789022aecd253cb9ab011bd6e7e4bb2253be63",
    "selection_sha256": "8fc537ed98a04b74ae37529fe7659a49432b2d36d1b38de1998d5f5e6771e3a1",
    "runtime_input_run_id": "31418682679",
    "pilot_source_run_id": "32142082213",
    "pilot_verify_run_id": "32152459079",
    "pilot_receipt_sha256": "9d72807e6f27a8aec11fe3defd8b005bccc96555d8fac66d65ad94209bfcdad6",
    "pilot_manifest_sha256": "8c6eeb0a79c3c1c5769f15beb70734e8781393afd4aa95a04a48c40d47f4e420",
    "pilot_fault_fixture_receipt_sha256": "fe49ec1b750a8b52c72abbeb727c3319f18aacb34f3df869a66b4731641618c4",
    "pilot_verified_recipe_count": 34985,
    "pilot_verified_shard_count": 60,
    "pilot_effective_concurrency": 20.490609608222336,
    "pilot_validation_opened": False,
    "pilot_locked_opened": False,
}
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CampaignContext:
    entry: CatalogAtlasCampaignEntryV1
    campaign_definition_sha256: str
    freeze_manifest_sha256: str
    dependency_lock_sha256: str
    data_contract_sha256: str
    feature_contract_sha256: str
    freeze: Mapping[str, object]


def _qualified_worker_ceiling(context: CampaignContext) -> int:
    pilot_concurrency = context.freeze.get("pilot_effective_concurrency")
    if (
        isinstance(pilot_concurrency, bool)
        or not isinstance(pilot_concurrency, (int, float))
        or not math.isfinite(float(pilot_concurrency))
        or pilot_concurrency != EXPECTED_FREEZE["pilot_effective_concurrency"]
    ):
        _fail("PILOT_CONCURRENCY_EVIDENCE_INVALID")
    ceiling = context.entry.max_free_workers
    if isinstance(ceiling, bool) or not isinstance(ceiling, int):
        _fail("QUALIFIED_WORKER_CEILING_INVALID")
    if ceiling > math.floor(float(pilot_concurrency)):
        _fail("QUALIFIED_WORKER_CEILING_EXCEEDS_PILOT")
    return ceiling


def _fail(code: str) -> NoReturn:
    raise ValueError(f"ATLAS_PREPARE_{code}")


def _read_object(path: Path, code: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ATLAS_PREPARE_{code}") from exc
    if not isinstance(payload, dict):
        _fail(code)
    return payload


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_repo_file(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(
        part in {".", ".."} for part in parts
    ):
        _fail("REPOSITORY_PATH_INVALID")
    try:
        resolved = root.joinpath(*parts).resolve(strict=True)
    except OSError as exc:
        raise ValueError("ATLAS_PREPARE_REPOSITORY_FILE_MISSING") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        _fail("REPOSITORY_PATH_INVALID")
    return resolved


def resolve_preparation_context(repo_root: Path, campaign_key: str) -> CampaignContext:
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        _fail("REPOSITORY_ROOT_INVALID")
    registry = load_catalog_campaign_registry(
        _safe_repo_file(root, "config/catalog_campaign_registry_v1.json")
    )
    entry = resolve_catalog_campaign(registry, campaign_key, root)
    if not isinstance(entry, CatalogAtlasCampaignEntryV1):
        _fail("CAMPAIGN_ENGINE_INVALID")
    expected_paths = {
        "campaign_contract_path": "config/sp500_megarun_dehb_campaign_v1.json",
        "freeze_manifest_path": "config/sp500_atlas_1/freeze_manifest_v1.json",
        "data_contract_path": "config/sp500_megarun_free_data_240.json",
        "feature_contract_path": "config/sp500_megarun_feature_contract_240.json",
    }
    if any(getattr(entry, field) != expected for field, expected in expected_paths.items()):
        _fail("CAMPAIGN_DEFINITION_PATH_MISMATCH")
    if entry.allowed_protected_branch != "main" or entry.source_artifact_contracts != (
        "runtime_input_pack_v1",
    ):
        _fail("CAMPAIGN_POLICY_MISMATCH")

    definition_path = _safe_repo_file(root, entry.definition_manifest_path)
    definition = parse_catalog_campaign_definition_bytes(definition_path.read_bytes())
    if definition.campaign_key != campaign_key:
        _fail("DEFINITION_CAMPAIGN_MISMATCH")
    checked_definition = verify_catalog_campaign_definition(
        repo_root=root,
        registry_entry=entry,
        manifest=definition,
    )

    freeze_path = _safe_repo_file(root, entry.freeze_manifest_path)
    freeze_bytes = freeze_path.read_bytes()
    freeze = _read_object(freeze_path, "FREEZE_UNREADABLE")
    for key, expected in EXPECTED_FREEZE.items():
        if freeze.get(key) != expected:
            _fail(f"FREEZE_{key.upper()}_MISMATCH")
    if (
        freeze.get("requested_recipe_count") != REQUESTED_RECIPE_COUNT
        or freeze.get("total_shards") != TOTAL_SHARDS
        or freeze.get("selection_seed") != SELECTION_SEED
        or freeze.get("train_end") != TRAIN_END
        or freeze.get("validation_opened") is not False
        or freeze.get("locked_opened") is not False
    ):
        _fail("FREEZE_PLAN_OR_BOUNDARY_MISMATCH")
    if str(entry.runtime_input_run_id) != EXPECTED_FREEZE["runtime_input_run_id"]:
        _fail("RUNTIME_INPUT_ID_MISMATCH")

    lock_path = _safe_repo_file(root, "requirements/catalog-optimized.lock")
    data_path = _safe_repo_file(root, entry.data_contract_path)
    feature_path = _safe_repo_file(root, entry.feature_contract_path)
    data_contract = load_and_validate_contract(data_path)
    feature_contract = load_and_validate_feature_contract(feature_path, data_contract)
    context = CampaignContext(
        entry=entry,
        campaign_definition_sha256=checked_definition.campaign_definition_sha256,
        freeze_manifest_sha256=_sha256_bytes(freeze_bytes),
        dependency_lock_sha256=_sha256_bytes(lock_path.read_bytes()),
        data_contract_sha256=_sha256_bytes(data_path.read_bytes()),
        feature_contract_sha256=_sha256_bytes(feature_path.read_bytes()),
        freeze=freeze,
    )
    _qualified_worker_ceiling(context)
    return context


def _require_protected_main(repository: str, ref: str, commit_sha: str) -> None:
    if repository != REPOSITORY or ref != "refs/heads/main":
        _fail("PROTECTED_MAIN_REQUIRED")
    if len(commit_sha) != 40 or any(char not in "0123456789abcdef" for char in commit_sha):
        _fail("PROTECTED_COMMIT_SHA_INVALID")


def _aware_datetime(value: str, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ATLAS_PREPARE_{code}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(code)
    return parsed


def planning_window(now: datetime | None = None) -> tuple[str, str]:
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        _fail("PLANNING_CLOCK_TIMEZONE_REQUIRED")
    anchor = anchor.astimezone(timezone.utc).replace(microsecond=0)
    target = anchor + timedelta(days=PLANNING_DAYS)
    return (
        anchor.isoformat().replace("+00:00", "Z"),
        target.isoformat().replace("+00:00", "Z"),
    )


def _validate_planning_window(
    started_at_iso: str, target_end_iso: str, now: datetime
) -> None:
    started = _aware_datetime(started_at_iso, "PLANNING_START_INVALID")
    target = _aware_datetime(target_end_iso, "PLANNING_TARGET_INVALID")
    current = now
    if current.tzinfo is None or current.utcoffset() is None:
        _fail("PLANNING_CLOCK_TIMEZONE_REQUIRED")
    current = current.astimezone(timezone.utc)
    if started > current:
        _fail("PLANNING_START_IN_FUTURE")
    if target != started + timedelta(days=PLANNING_DAYS):
        _fail("PLANNING_TARGET_OFFSET_INVALID")
    if target <= current:
        _fail("PLANNING_TARGET_EXPIRED")


def preflight(
    *,
    repo_root: Path,
    campaign_key: str,
    protected_commit_sha: str,
    repository: str,
    ref: str,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_protected_main(repository, ref, protected_commit_sha)
    context = resolve_preparation_context(repo_root, campaign_key)
    started_at_iso, target_end_iso = planning_window(now)
    static_identity = _build_static_identity(context, protected_commit_sha)
    return {
        "planning_started_at_iso": started_at_iso,
        "planned_target_end_iso": target_end_iso,
        "runtime_input_run_id": context.entry.runtime_input_run_id,
        "qualified_worker_ceiling": _qualified_worker_ceiling(context),
        "campaign_definition_sha256": context.campaign_definition_sha256,
        "preparation_key_sha256": static_identity.preparation_key_sha256,
    }


def _append_github_output(path: Path | None, values: Mapping[str, object]) -> None:
    if path is None:
        return
    with Path(path).open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in values.items():
            text = str(value)
            if "\n" in text or "\r" in text:
                _fail("OUTPUT_VALUE_INVALID")
            stream.write(f"{key}={text}\n")


def _verify_plan_and_selection(
    bundle: Path,
    summary: Mapping[str, object],
    context: CampaignContext,
    target_end_iso: str,
    verified: Mapping[str, object] | None = None,
) -> tuple[AtlasRunPlanV1, dict[str, object]]:
    expected_summary = {
        "accepted": True,
        "requested_recipe_count": REQUESTED_RECIPE_COUNT,
        "total_shards": TOTAL_SHARDS,
        "target_end_iso": target_end_iso,
        "selection_seed": SELECTION_SEED,
        "validation_opened": False,
        "locked_opened": False,
        "execution_authorized": False,
    }
    if any(summary.get(key) != expected for key, expected in expected_summary.items()):
        _fail("PLAN_SUMMARY_MISMATCH")
    selection = _read_object(bundle / "plan/atlas_campaign_selection.json", "SELECTION_UNREADABLE")
    if (
        selection.get("requested_recipe_count") != REQUESTED_RECIPE_COUNT
        or selection.get("seed") != SELECTION_SEED
        or selection.get("selection_sha256") != EXPECTED_FREEZE["selection_sha256"]
    ):
        _fail("SELECTION_MISMATCH")
    try:
        plan = AtlasRunPlanV1.model_validate(
            _read_object(bundle / "plan/atlas_run_plan.json", "PLAN_UNREADABLE")
        )
    except Exception as exc:
        raise ValueError("ATLAS_PREPARE_PLAN_INVALID") from exc
    expected_plan = {
        "catalog_id": EXPECTED_FREEZE["catalog_id"],
        "catalog_manifest_sha256": EXPECTED_FREEZE["catalog_manifest_sha256"],
        "catalog_space_sha256": EXPECTED_FREEZE["catalog_space_sha256"],
        "train_end": TRAIN_END,
        "requested_recipe_count": REQUESTED_RECIPE_COUNT,
        "total_shards": TOTAL_SHARDS,
        "selection_seed": SELECTION_SEED,
        "selection_sha256": EXPECTED_FREEZE["selection_sha256"],
        "target_end_iso": target_end_iso,
        "validation_opened": False,
        "locked_opened": False,
    }
    if any(getattr(plan, key) != expected for key, expected in expected_plan.items()):
        _fail("PLAN_CONTENT_MISMATCH")
    if plan.plan_sha256 != summary.get("plan_sha256"):
        _fail("PLAN_HASH_MISMATCH")
    if verified is not None and (
        plan.calibration_receipt_sha256 != verified.get("calibration_receipt_sha256")
        or plan.selection_sha256 != verified.get("selection_sha256")
    ):
        _fail("PLAN_EVIDENCE_BINDING_INVALID")
    return plan, selection


def _build_static_identity(
    context: CampaignContext,
    protected_commit_sha: str,
    verified: Mapping[str, object] | None = None,
) -> AtlasPreparationIdentityV1:
    # PREPARED tracks repository bytes; the science verifier separately checks
    # the canonical hashes embedded in the generated catalog manifest.
    data_hash = context.data_contract_sha256
    feature_hash = context.feature_contract_sha256
    selection_hash = (
        verified["selection_sha256"]
        if verified is not None
        else EXPECTED_FREEZE["selection_sha256"]
    )
    return AtlasPreparationIdentityV1(
        campaign_key=context.entry.campaign_key,
        engine_id="atlas_static_v1",
        protected_commit_sha=protected_commit_sha,
        campaign_definition_sha256=context.campaign_definition_sha256,
        scientific_contract_sha256=context.entry.scientific_contract_sha256,
        dependency_lock_sha256=context.dependency_lock_sha256,
        freeze_manifest_sha256=context.freeze_manifest_sha256,
        data_contract_sha256=str(data_hash),
        feature_contract_sha256=str(feature_hash),
        runtime_input_run_id=context.entry.runtime_input_run_id,
        selection_sha256=str(selection_hash),
    )


def prepare_catalog_atlas_bundle(
    *,
    repo_root: Path,
    campaign_key: str,
    protected_commit_sha: str,
    repository: str,
    ref: str,
    planning_started_at_iso: str,
    planned_target_end_iso: str,
    expected_campaign_definition_sha256: str,
    expected_preparation_key_sha256: str,
    calibration_output_dir: Path,
    bundle_dir: Path,
    previous_bundle_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_protected_main(repository, ref, protected_commit_sha)
    current = now or datetime.now(timezone.utc)
    _validate_planning_window(planning_started_at_iso, planned_target_end_iso, current)
    root = Path(repo_root).resolve(strict=True)
    context = resolve_preparation_context(root, campaign_key)
    if context.campaign_definition_sha256 != expected_campaign_definition_sha256:
        _fail("DEFINITION_IDENTITY_CHANGED")
    qualified_worker_ceiling = _qualified_worker_ceiling(context)
    calibration_root = Path(calibration_output_dir)
    source_receipt = calibration_root / "calibration/calibration_receipt.json"
    source_catalog = calibration_root / "atlas"
    if not source_receipt.is_file():
        _fail("CALIBRATION_ARTIFACT_INCOMPLETE")
    if not (source_catalog / "manifest.json").is_file() or not (
        source_catalog / "recipe_space.json"
    ).is_file():
        cached_catalog = (
            Path(previous_bundle_dir) / "atlas" if previous_bundle_dir is not None else None
        )
        if cached_catalog is None or not (cached_catalog / "manifest.json").is_file() or not (
            cached_catalog / "recipe_space.json"
        ).is_file():
            _fail("CALIBRATION_ARTIFACT_INCOMPLETE")
        source_catalog = cached_catalog
    output = Path(bundle_dir)
    if output.exists():
        _fail("BUNDLE_DESTINATION_EXISTS")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source_catalog, output / "atlas")
    calibration_path = output / "calibration/calibration_receipt.json"
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_receipt, calibration_path)

    summary = plan_atlas_run(
        catalog_dir=output / "atlas",
        calibration_receipt_path=calibration_path,
        output_dir=output / "plan",
        target_end_iso=planned_target_end_iso,
        implementation_commit_sha=str(context.freeze["scientific_implementation_commit_sha"]),
        total_shards=360,
        recipe_count=209906,
        selection_seed=20260818,
    )
    verified = verify_atlas_cloud_identity(
        output / "atlas",
        calibration_path,
        planned_target_end_iso=planned_target_end_iso,
        now=current,
    )
    expected_identity = {
        "catalog_id": EXPECTED_FREEZE["catalog_id"],
        "catalog_manifest_sha256": EXPECTED_FREEZE["catalog_manifest_sha256"],
        "catalog_space_sha256": EXPECTED_FREEZE["catalog_space_sha256"],
        "requested_recipe_count": REQUESTED_RECIPE_COUNT,
        "total_shards": TOTAL_SHARDS,
        "selection_seed": SELECTION_SEED,
        "selection_sha256": EXPECTED_FREEZE["selection_sha256"],
        "train_end": TRAIN_END,
        "planned_target_end_iso": planned_target_end_iso,
        "validation_opened": False,
        "locked_opened": False,
        "execution_authorized": False,
    }
    if any(verified.get(key) != expected for key, expected in expected_identity.items()):
        _fail("VERIFIED_IDENTITY_MISMATCH")
    if verified.get("scientific_contract_sha256") != context.entry.scientific_contract_sha256:
        _fail("SCIENTIFIC_CONTRACT_MISMATCH")
    if verified.get("freeze_manifest_sha256") != context.freeze_manifest_sha256:
        _fail("FREEZE_IDENTITY_MISMATCH")
    plan, _selection = _verify_plan_and_selection(
        output, summary, context, planned_target_end_iso, verified
    )
    static_identity = _build_static_identity(context, protected_commit_sha, verified)
    if static_identity.preparation_key_sha256 != expected_preparation_key_sha256:
        _fail("PREPARATION_KEY_CHANGED")
    prepared = create_atlas_prepared_receipt(
        verified,
        identity=static_identity,
        qualified_worker_ceiling=qualified_worker_ceiling,
        plan_sha256=plan.plan_sha256,
        generated_at=current,
    )
    receipt_path = output / "atlas_prepared_receipt.json"
    receipt_path.write_text(
        json.dumps(prepared.model_dump(mode="json"), ensure_ascii=True, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "preparation_key_sha256": static_identity.preparation_key_sha256,
        "receipt_sha256": prepared.receipt_sha256,
        "plan_sha256": plan.plan_sha256,
        "campaign_definition_sha256": context.campaign_definition_sha256,
        "artifact_name": (
            f"catalog-atlas-prepared-{campaign_key}-{static_identity.preparation_key_sha256}"
        ),
    }


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--protected-commit-sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    preflight_parser = commands.add_parser("preflight")
    _common_arguments(preflight_parser)
    preflight_parser.add_argument("--github-output", type=Path)
    prepare_parser = commands.add_parser("prepare")
    _common_arguments(prepare_parser)
    prepare_parser.add_argument("--planning-started-at-iso", required=True)
    prepare_parser.add_argument("--planned-target-end-iso", required=True)
    prepare_parser.add_argument("--expected-campaign-definition-sha256", required=True)
    prepare_parser.add_argument("--expected-preparation-key-sha256", required=True)
    prepare_parser.add_argument("--calibration-output-dir", type=Path, required=True)
    prepare_parser.add_argument("--bundle-dir", type=Path, required=True)
    prepare_parser.add_argument("--previous-bundle-dir", type=Path)
    prepare_parser.add_argument("--github-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(
                repo_root=args.repo_root,
                campaign_key=args.campaign_key,
                protected_commit_sha=args.protected_commit_sha,
                repository=args.repository,
                ref=args.ref,
            )
            _append_github_output(args.github_output, result)
        else:
            result = prepare_catalog_atlas_bundle(
                repo_root=args.repo_root,
                campaign_key=args.campaign_key,
                protected_commit_sha=args.protected_commit_sha,
                repository=args.repository,
                ref=args.ref,
                planning_started_at_iso=args.planning_started_at_iso,
                planned_target_end_iso=args.planned_target_end_iso,
                expected_campaign_definition_sha256=args.expected_campaign_definition_sha256,
                expected_preparation_key_sha256=args.expected_preparation_key_sha256,
                calibration_output_dir=args.calibration_output_dir,
                bundle_dir=args.bundle_dir,
                previous_bundle_dir=args.previous_bundle_dir,
            )
            result["run_id"] = os.environ.get("GITHUB_RUN_ID", "")
            if args.github_output is not None and not result["run_id"]:
                _fail("WORKFLOW_RUN_ID_REQUIRED")
            _append_github_output(args.github_output, result)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
