"""Fail-closed identity check for a frozen Atlas-1 cloud preparation.

This module only reads manifests and calibration evidence.  It does not launch
work, open protected data, or grant execution authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Literal, Mapping, NoReturn, TypedDict

from pydantic import Field, StringConstraints, field_validator, model_validator

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CAMPAIGN_KEY_PATTERN,
    FrozenModel,
    Sha256,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogAtlasCampaignEntryV1,
)
from aurora.infra.sp500_megarun.atlas_campaign_selection import (
    build_campaign_selection,
)
from aurora.infra.sp500_megarun.catalog_atlas_calibration import (
    target_minutes,
    target_recipe_count,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ATLAS_DATA_CONTRACT_PATH = _REPOSITORY_ROOT / "config" / "sp500_megarun_free_data_240.json"
_ATLAS_FEATURE_CONTRACT_PATH = (
    _REPOSITORY_ROOT / "config" / "sp500_megarun_feature_contract_240.json"
)
_EXPECTED_RUNTIME_INPUT_RUN_ID = 31418682679
FREEZE_MANIFEST_PATH = (
    _REPOSITORY_ROOT / "config" / "sp500_atlas_1" / "freeze_manifest_v1.json"
)


class _AtlasFreezeExpectation(TypedDict):
    catalog_id: str
    catalog_manifest_sha256: str
    catalog_space_sha256: str
    requested_recipe_count: int
    total_shards: int
    selection_seed: int
    selection_sha256: str
    train_end: str
    scientific_implementation_commit_sha: str


_EXPECTED_FREEZE: _AtlasFreezeExpectation = {
    "catalog_id": "sp500-atlas-1",
    "catalog_manifest_sha256": "09068cf0b0ff716075bdd693dbdfbdcf3779c7cb326a92aca11d9ab22b577f08",
    "catalog_space_sha256": "c5a29064acd626a0aa67559222789022aecd253cb9ab011bd6e7e4bb2253be63",
    "requested_recipe_count": 209906,
    "total_shards": 360,
    "selection_seed": 20260818,
    "selection_sha256": "8fc537ed98a04b74ae37529fe7659a49432b2d36d1b38de1998d5f5e6771e3a1",
    "train_end": "2010-12-31",
    "scientific_implementation_commit_sha": "0b654f1d25588cfca55c449e3634dd392e62e8f3",
}
_OBJECTIVE_EVALUATOR_FILES = (
    "scripts/run_sp500_atlas_worker.py",
    "scripts/run_sp500_strategy_catalog_shard.py",
    "infra/sp500_megarun/catalog_atlas_objective.py",
    "infra/sp500_megarun/catalog_fast_objective.py",
    "infra/sp500_megarun/dehb_lane_registry.py",
    "infra/sp500_megarun/dehb_worker.py",
)
_CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


def _fail(code: str) -> NoReturn:
    raise ValueError(f"ATLAS_CLOUD_IDENTITY_{code}")


def _read_json(path: Path, code: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ATLAS_CLOUD_IDENTITY_{code}") from exc
    if not isinstance(value, dict):
        _fail(code)
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError("ATLAS_CLOUD_IDENTITY_ARTIFACT_MISSING") from exc
    return digest.hexdigest()


def _parse_aware(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        _fail(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"ATLAS_CLOUD_IDENTITY_{code}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(code)
    return parsed


class AtlasPreparationIdentityV1(FrozenModel):
    """Atlas scientific identity plus its protected preparation context."""

    schema_version: Literal["1"] = "1"
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    engine_id: Literal["atlas_static_v1"] = "atlas_static_v1"
    protected_commit_sha: _CommitSha
    campaign_definition_sha256: Sha256
    scientific_contract_sha256: Sha256
    dependency_lock_sha256: Sha256
    freeze_manifest_sha256: Sha256
    data_contract_sha256: Sha256
    feature_contract_sha256: Sha256
    runtime_input_run_id: int = Field(ge=1)
    selection_sha256: Sha256

    @property
    def preparation_key_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class AtlasPreparedReceiptV1(FrozenModel):
    """Self-hashing PREPARED proof with independently supplied worker ceiling."""

    schema_version: Literal["1"] = "1"
    status: Literal["PREPARED"] = "PREPARED"
    identity: AtlasPreparationIdentityV1
    receipt_sha256: Sha256
    qualified_worker_ceiling: int = Field(ge=1, le=360, strict=True)
    target_end_iso: str = Field(min_length=1)
    calibration_receipt_sha256: Sha256
    selection_sha256: Sha256
    plan_sha256: Sha256
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def _generated_at_is_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ATLAS_PREPARED_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc)

    @field_validator("target_end_iso")
    @classmethod
    def _target_end_is_timezone_aware(cls, value: str) -> str:
        _parse_aware(value, "PLANNED_TARGET_END_INVALID")
        return value

    @model_validator(mode="after")
    def _verify_binding_and_hash(self) -> "AtlasPreparedReceiptV1":
        if (
            self.selection_sha256 != self.identity.selection_sha256
        ):
            raise ValueError("ATLAS_PREPARED_RECEIPT_BINDING_INVALID")
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if canonical_sha256(payload) != self.receipt_sha256:
            raise ValueError("ATLAS_PREPARED_RECEIPT_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        identity: AtlasPreparationIdentityV1,
        qualified_worker_ceiling: int,
        target_end_iso: str,
        calibration_receipt_sha256: str,
        plan_sha256: str,
        generated_at: datetime,
    ) -> "AtlasPreparedReceiptV1":
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("ATLAS_PREPARED_TIMEZONE_REQUIRED")
        values: dict[str, object] = {
            "schema_version": "1",
            "status": "PREPARED",
            "identity": identity.model_dump(mode="json"),
            "qualified_worker_ceiling": qualified_worker_ceiling,
            "target_end_iso": target_end_iso,
            "calibration_receipt_sha256": calibration_receipt_sha256,
            "selection_sha256": identity.selection_sha256,
            "plan_sha256": plan_sha256,
            "generated_at": generated_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        return cls(
            **values,
            receipt_sha256=canonical_sha256(values),
        )


def create_atlas_prepared_receipt(
    verification: Mapping[str, object],
    *,
    identity: AtlasPreparationIdentityV1,
    qualified_worker_ceiling: int,
    plan_sha256: str,
    generated_at: datetime,
) -> AtlasPreparedReceiptV1:
    """Create a typed gate receipt from verified identity and explicit evidence."""

    expected_bindings = {
        "scientific_contract_sha256": verification["scientific_contract_sha256"],
        "freeze_manifest_sha256": verification["freeze_manifest_sha256"],
        "selection_sha256": verification["selection_sha256"],
    }
    if any(getattr(identity, key) != value for key, value in expected_bindings.items()):
        raise ValueError("ATLAS_PREPARED_STATIC_IDENTITY_MISMATCH")
    return AtlasPreparedReceiptV1.create(
        identity=identity,
        qualified_worker_ceiling=qualified_worker_ceiling,
        target_end_iso=str(verification["planned_target_end_iso"]),
        calibration_receipt_sha256=str(verification["calibration_receipt_sha256"]),
        plan_sha256=plan_sha256,
        generated_at=generated_at,
    )


def build_atlas_preparation_identity(
    repo_root: Path,
    registry_entry: CatalogAtlasCampaignEntryV1,
    protected_commit_sha: str,
) -> AtlasPreparationIdentityV1:
    """Verify protected repository inputs and build the static Atlas identity."""

    from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
        verify_catalog_campaign_definition,
    )
    from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
        parse_catalog_campaign_definition_bytes,
    )

    root_input = Path(repo_root)
    try:
        root = root_input.resolve(strict=True)
    except OSError as exc:
        raise ValueError("ATLAS_PREPARATION_REPOSITORY_INVALID") from exc
    if root_input.is_symlink() or not root.is_dir():
        raise ValueError("ATLAS_PREPARATION_REPOSITORY_INVALID")
    if registry_entry.engine_id != "atlas_static_v1":
        raise ValueError("ATLAS_PREPARATION_ENGINE_INVALID")

    def repository_file(relative_path: str) -> Path:
        candidate_input = root / relative_path
        try:
            candidate = candidate_input.resolve(strict=True)
        except OSError as exc:
            raise ValueError("ATLAS_PREPARATION_INPUT_MISSING") from exc
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError("ATLAS_PREPARATION_INPUT_PATH_INVALID")
        return candidate

    definition_path = repository_file(registry_entry.definition_manifest_path)
    try:
        definition = parse_catalog_campaign_definition_bytes(definition_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ValueError("ATLAS_PREPARATION_DEFINITION_INVALID") from exc
    try:
        verified_definition = verify_catalog_campaign_definition(
            repo_root=root,
            registry_entry=registry_entry,
            manifest=definition,
        )
    except ValueError as exc:
        raise ValueError("ATLAS_PREPARATION_DEFINITION_INVALID") from exc

    freeze_path = repository_file(registry_entry.freeze_manifest_path)
    freeze = _read_json(freeze_path, "FREEZE_UNREADABLE")
    _verify_freeze(freeze)
    raw_run_id = freeze.get("runtime_input_run_id")
    if isinstance(raw_run_id, bool) or not isinstance(raw_run_id, (str, int)):
        _fail("PREPARATION_RUNTIME_INPUT_ID_INVALID")
    try:
        frozen_runtime_input_run_id = int(raw_run_id)
    except ValueError as exc:
        raise ValueError("ATLAS_PREPARATION_RUNTIME_INPUT_ID_INVALID") from exc
    if registry_entry.runtime_input_run_id != frozen_runtime_input_run_id:
        _fail("PREPARATION_RUNTIME_INPUT_ID_MISMATCH")
    data_path = repository_file(registry_entry.data_contract_path)
    feature_path = repository_file(registry_entry.feature_contract_path)
    dependency_lock_path = repository_file("requirements/catalog-optimized.lock")

    return AtlasPreparationIdentityV1(
        campaign_key=registry_entry.campaign_key,
        engine_id="atlas_static_v1",
        protected_commit_sha=protected_commit_sha,
        campaign_definition_sha256=verified_definition.campaign_definition_sha256,
        scientific_contract_sha256=registry_entry.scientific_contract_sha256,
        dependency_lock_sha256=_file_sha256(dependency_lock_path),
        freeze_manifest_sha256=_file_sha256(freeze_path),
        data_contract_sha256=_file_sha256(data_path),
        feature_contract_sha256=_file_sha256(feature_path),
        runtime_input_run_id=registry_entry.runtime_input_run_id,
        selection_sha256=str(freeze["selection_sha256"]),
    )


def _verify_freeze(freeze: Mapping[str, object]) -> None:
    for key, expected in _EXPECTED_FREEZE.items():
        if freeze.get(key) != expected:
            _fail(f"FREEZE_{key.upper()}_MISMATCH")
    counts = freeze.get("catalog_counts")
    raw_capacity = (
        counts.get("canonical_recipe_count") if isinstance(counts, dict) else None
    )
    frozen_capacity = (
        raw_capacity
        if isinstance(raw_capacity, int) and not isinstance(raw_capacity, bool)
        else -1
    )
    if frozen_capacity < int(_EXPECTED_FREEZE["requested_recipe_count"]):
        _fail("FREEZE_CAPACITY_INVALID")
    raw_runtime_input_run_id = freeze.get("runtime_input_run_id")
    if isinstance(raw_runtime_input_run_id, bool) or not isinstance(raw_runtime_input_run_id, (str, int)):
        _fail("FREEZE_RUNTIME_INPUT_ID_INVALID")
    try:
        runtime_input_run_id = int(raw_runtime_input_run_id)
    except ValueError:
        _fail("FREEZE_RUNTIME_INPUT_ID_INVALID")
    if runtime_input_run_id != _EXPECTED_RUNTIME_INPUT_RUN_ID:
        _fail("FREEZE_RUNTIME_INPUT_ID_MISMATCH")
    for key in ("validation_opened", "locked_opened"):
        if freeze.get(key) is not False:
            _fail("FREEZE_BOUNDARY_OPEN")


def _verify_frozen_catalog(
    catalog_dir: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Verify frozen catalog bytes and reproduce its finite selection."""

    root = Path(catalog_dir)
    manifest = _read_json(root / "manifest.json", "CATALOG_MANIFEST_UNREADABLE")
    if manifest.get("manifest_sha256") != _EXPECTED_FREEZE["catalog_manifest_sha256"]:
        _fail("CATALOG_MANIFEST_HASH_MISMATCH")
    manifest_identity = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if canonical_sha256(manifest_identity) != manifest.get("manifest_sha256"):
        _fail("CATALOG_MANIFEST_HASH_INVALID")
    if manifest.get("catalog_id") != _EXPECTED_FREEZE["catalog_id"]:
        _fail("CATALOG_ID_MISMATCH")
    if manifest.get("search_end") != _EXPECTED_FREEZE["train_end"]:
        _fail("CATALOG_TRAIN_END_MISMATCH")
    if manifest.get("validation_opened") is not False or manifest.get("locked_opened") is not False:
        _fail("CATALOG_BOUNDARY_OPEN")
    if manifest.get("execution_authorized") is not False:
        _fail("CATALOG_ALREADY_AUTHORIZED")

    artifact_hashes = manifest.get("artifacts_sha256")
    if not isinstance(artifact_hashes, dict):
        _fail("ARTIFACT_HASHES_MISSING")
    recipe_space_path = root / "recipe_space.json"
    recipe_space_file_sha256 = _file_sha256(recipe_space_path)
    if (
        recipe_space_file_sha256 != _EXPECTED_FREEZE["catalog_space_sha256"]
        or artifact_hashes.get("recipe_space.json") != recipe_space_file_sha256
    ):
        _fail("RECIPE_SPACE_FILE_HASH_INVALID")
    space = _read_json(recipe_space_path, "RECIPE_SPACE_UNREADABLE")
    space_identity = {key: value for key, value in space.items() if key != "space_sha256"}
    if canonical_sha256(space_identity) != space.get("space_sha256"):
        _fail("RECIPE_SPACE_HASH_INVALID")
    if space.get("train_end") != _EXPECTED_FREEZE["train_end"]:
        _fail("RECIPE_SPACE_TRAIN_END_MISMATCH")
    if space.get("validation_opened") is not False or space.get("locked_opened") is not False:
        _fail("RECIPE_SPACE_BOUNDARY_OPEN")
    ranges = space.get("ranges")
    if not isinstance(ranges, list):
        _fail("RECIPE_SPACE_RANGES_MISSING")
    try:
        selection = build_campaign_selection(
            space,
            requested_recipe_count=int(_EXPECTED_FREEZE["requested_recipe_count"]),
            seed=int(_EXPECTED_FREEZE["selection_seed"]),
        )
    except (KeyError, TypeError, ValueError, AssertionError) as exc:
        raise ValueError("ATLAS_CLOUD_IDENTITY_SELECTION_REPRODUCTION_FAILED") from exc
    if selection.get("requested_recipe_count") != _EXPECTED_FREEZE["requested_recipe_count"]:
        _fail("SELECTION_COUNT_MISMATCH")
    if selection.get("seed") != _EXPECTED_FREEZE["selection_seed"]:
        _fail("SELECTION_SEED_MISMATCH")
    if selection.get("selection_sha256") != _EXPECTED_FREEZE["selection_sha256"]:
        _fail("SELECTION_HASH_MISMATCH")
    return manifest, space, selection


def verify_atlas_cloud_identity(
    catalog_dir: Path,
    calibration_receipt: Path | Mapping[str, object],
    *,
    planned_target_end_iso: str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Verify generated catalog and fresh calibration against the Atlas-1 freeze.

    ``now`` is injectable for deterministic offline verification.  The returned
    receipt contains no wall-clock field, so repeated successful verification
    of the same inputs produces identical bytes after canonical JSON encoding.
    """

    freeze = _read_json(FREEZE_MANIFEST_PATH, "FREEZE_UNREADABLE")
    _verify_freeze(freeze)
    freeze_manifest_sha256 = _file_sha256(FREEZE_MANIFEST_PATH)
    manifest, _space, _selection = _verify_frozen_catalog(catalog_dir)

    if isinstance(calibration_receipt, Path):
        calibration = _read_json(calibration_receipt, "CALIBRATION_UNREADABLE")
    elif isinstance(calibration_receipt, Mapping):
        calibration = dict(calibration_receipt)
    else:
        _fail("CALIBRATION_INVALID")
    if calibration.get("catalog_sha256") != _EXPECTED_FREEZE[
        "catalog_manifest_sha256"
    ]:
        _fail("CALIBRATION_CATALOG_MISMATCH")
    if calibration.get("hard_limit_seconds") != 1200.0:
        _fail("CALIBRATION_LIMIT_INVALID")
    wall_seconds = calibration.get("wall_seconds")
    if (
        not isinstance(wall_seconds, (int, float))
        or isinstance(wall_seconds, bool)
        or not math.isfinite(float(wall_seconds))
        or wall_seconds > 1200.0
    ):
        _fail("CALIBRATION_WALL_TIME_EXCEEDED")
    if calibration.get("recommended_mode") != "cold":
        _fail("CALIBRATION_MODE_INVALID")
    if calibration.get("validation_opened") is not False or calibration.get(
        "locked_opened"
    ) is not False:
        _fail("CALIBRATION_BOUNDARY_OPEN")
    required_count = int(_EXPECTED_FREEZE["requested_recipe_count"])
    target_capacity = calibration.get("target_recipe_count_with_margin")
    if (
        not isinstance(target_capacity, int)
        or isinstance(target_capacity, bool)
    ):
        _fail("CALIBRATION_CAPACITY_INVALID")
    available_minutes = calibration.get("available_minutes_to_target")
    if (
        not isinstance(available_minutes, (int, float))
        or isinstance(available_minutes, bool)
        or not math.isfinite(float(available_minutes))
        or available_minutes <= 0
    ):
        _fail("CALIBRATION_TARGET_EXPIRED")

    target_end = _parse_aware(planned_target_end_iso, "PLANNED_TARGET_END_INVALID")
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        _fail("CLOCK_TIMEZONE_REQUIRED")
    started = _parse_aware(calibration.get("started_at_iso"), "CALIBRATION_START_INVALID")
    stopped = _parse_aware(calibration.get("stopped_at_iso"), "CALIBRATION_STOP_INVALID")
    if stopped < started or stopped > current_time:
        _fail("CALIBRATION_TIME_ORDER_INVALID")
    if target_end <= current_time:
        _fail("PLANNED_TARGET_EXPIRED")

    try:
        expected_available_minutes = target_minutes(
            now_iso=stopped.isoformat(), target_end_iso=target_end.isoformat()
        )
    except ValueError as exc:
        raise ValueError("ATLAS_CLOUD_IDENTITY_PLANNED_TARGET_INVALID") from exc
    if not math.isclose(
        float(available_minutes), expected_available_minutes, rel_tol=0.0, abs_tol=1e-9
    ):
        _fail("CALIBRATION_AVAILABLE_MINUTES_MISMATCH")
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
        _fail("CALIBRATION_SIZING_INPUT_INVALID")
    try:
        expected_capacity = target_recipe_count(
            available_minutes=float(available_minutes),
            recipes_per_minute=float(recipes_per_minute),
            safety_fraction=float(safety_fraction),
        )
    except ValueError as exc:
        raise ValueError("ATLAS_CLOUD_IDENTITY_CALIBRATION_SIZING_INVALID") from exc
    if target_capacity != expected_capacity:
        _fail("CALIBRATION_CAPACITY_MISMATCH")
    if target_capacity < required_count:
        _fail("CALIBRATION_CAPACITY_INSUFFICIENT")

    calibration_identity = {
        key: value for key, value in calibration.items() if key != "receipt_sha256"
    }
    calibration_sha256 = canonical_sha256(calibration_identity)
    if calibration.get("receipt_sha256") not in (None, calibration_sha256):
        _fail("CALIBRATION_RECEIPT_HASH_INVALID")

    data_contract_sha256 = manifest.get("data_contract_sha256")
    feature_contract_sha256 = manifest.get("feature_contract_sha256")
    if not isinstance(data_contract_sha256, str) or not isinstance(
        feature_contract_sha256, str
    ):
        _fail("CATALOG_CONTRACT_HASHES_MISSING")
    try:
        data_contract = load_and_validate_contract(_ATLAS_DATA_CONTRACT_PATH)
        feature_contract = load_and_validate_feature_contract(
            _ATLAS_FEATURE_CONTRACT_PATH, data_contract
        )
    except (OSError, ValueError) as exc:
        raise ValueError("ATLAS_CLOUD_IDENTITY_CONTRACT_UNREADABLE") from exc
    if data_contract.sha256 != data_contract_sha256:
        _fail("CATALOG_DATA_CONTRACT_HASH_MISMATCH")
    if feature_contract.sha256 != feature_contract_sha256:
        _fail("CATALOG_FEATURE_CONTRACT_HASH_MISMATCH")
    try:
        objective_evaluator_code = {
            name: _file_sha256(_REPOSITORY_ROOT / name)
            for name in _OBJECTIVE_EVALUATOR_FILES
        }
    except ValueError as exc:
        raise ValueError("ATLAS_CLOUD_IDENTITY_OBJECTIVE_EVALUATOR_IDENTITY_MISSING") from exc
    scientific_identity = {
        "catalog_manifest_sha256": _EXPECTED_FREEZE["catalog_manifest_sha256"],
        "catalog_space_sha256": _EXPECTED_FREEZE["catalog_space_sha256"],
        "selection_sha256": _EXPECTED_FREEZE["selection_sha256"],
        "requested_recipe_count": required_count,
        "selection_seed": int(_EXPECTED_FREEZE["selection_seed"]),
        "train_end": _EXPECTED_FREEZE["train_end"],
        "data_contract_sha256": data_contract_sha256,
        "feature_contract_sha256": feature_contract_sha256,
        "scientific_implementation_commit_sha": _EXPECTED_FREEZE[
            "scientific_implementation_commit_sha"
        ],
        "objective_evaluator_code_sha256": canonical_sha256(objective_evaluator_code),
    }
    scientific_contract_sha256 = canonical_sha256(scientific_identity)
    identity: dict[str, object] = {
        "schema_version": "1",
        "kind": "atlas_cloud_prepared_identity",
        "catalog_id": _EXPECTED_FREEZE["catalog_id"],
        "catalog_manifest_sha256": _EXPECTED_FREEZE["catalog_manifest_sha256"],
        "catalog_space_sha256": _EXPECTED_FREEZE["catalog_space_sha256"],
        "freeze_manifest_sha256": freeze_manifest_sha256,
        "calibration_receipt_sha256": calibration_sha256,
        "requested_recipe_count": required_count,
        "total_shards": int(_EXPECTED_FREEZE["total_shards"]),
        "selection_seed": int(_EXPECTED_FREEZE["selection_seed"]),
        "selection_sha256": _EXPECTED_FREEZE["selection_sha256"],
        "train_end": _EXPECTED_FREEZE["train_end"],
        "data_contract_sha256": data_contract_sha256,
        "feature_contract_sha256": feature_contract_sha256,
        "scientific_implementation_commit_sha": _EXPECTED_FREEZE[
            "scientific_implementation_commit_sha"
        ],
        "objective_evaluator_code_sha256": scientific_identity[
            "objective_evaluator_code_sha256"
        ],
        "scientific_contract_sha256": scientific_contract_sha256,
        "planned_target_end_iso": planned_target_end_iso,
        "validation_opened": False,
        "locked_opened": False,
        "execution_authorized": False,
    }
    return {
        **identity,
        "prepared_identity_sha256": canonical_sha256(identity),
    }


__all__ = [
    "AtlasPreparationIdentityV1",
    "AtlasPreparedReceiptV1",
    "build_atlas_preparation_identity",
    "create_atlas_prepared_receipt",
    "verify_atlas_cloud_identity",
]
