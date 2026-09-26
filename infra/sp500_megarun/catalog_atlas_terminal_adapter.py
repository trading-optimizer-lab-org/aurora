"""Fail-closed terminal verifier for the in-run Atlas-1 reusable workflow.

The reusable workflow is called inside the same parent run as
``catalog-fast-controller.yml``.  The finalizer materialises the following
*read-only* inputs before invoking this adapter:

* ``run.json`` and ``jobs.json``: fresh GitHub API responses for the parent run;
* extracted roots for ``sp500-atlas-preflight`` and
  ``sp500-atlas-final-results``.  No invocation snapshot, artifact inventory,
  or shard downloads are required.

The adapter never calls GitHub, starts work, reads market data, or opens
``validation``/``locked`` data.  It verifies the frozen Atlas contract,
plan/commit/authority bindings, exact reducer coverage, row hashes and final
results.  Its success output is the common ``CatalogTerminalReceiptV2``
shape consumed by catalog authority/routing.  Missing, incomplete, or
inconsistent evidence is represented as ``BLOCKED`` by the caller.

The authority context uses campaign key ``sp500-atlas-v1`` and the campaign
definition contract is ``config/catalog_campaign_definitions/sp500-atlas-v1.manifest.json``;
the frozen scientific ``catalog_id`` remains ``sp500-atlas-1``.

The reducer's ``reduction_receipt.json`` and combined result manifest bind the
normal full result to the frozen plan and every shard/row.  A
``source_results_index.json`` is validated when supplied (it belongs to the
reference-only recovery shape), but is not required for a normal combined
full run.  Missing reducer traceability is a stable ``BLOCKED`` result; it is
never replaced by a synthetic optimized-stage success.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal, Mapping, Sequence

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.catalog_atlas_cloud_identity import (
    AtlasPreparationIdentityV1,
    AtlasPreparedReceiptV1,
    build_atlas_preparation_identity,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogAtlasCampaignEntryV1,
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastLaunchDecisionV1,
    CatalogTerminalReceiptV2,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1


CONTROLLER_WORKFLOW_PATH = ".github/workflows/catalog-fast-controller.yml"
CAMPAIGN_KEY = "sp500-atlas-v1"
CATALOG_ID = "sp500-atlas-1"
EXPECTED_RECIPE_COUNT = 209_906
EXPECTED_SHARD_COUNT = 360
EXPECTED_TRAIN_END = "2010-12-31"
EXPECTED_SELECTION_SEED = 20260818
EXPECTED_SELECTION_SHA256 = "8fc537ed98a04b74ae37529fe7659a49432b2d36d1b38de1998d5f5e6771e3a1"
EXPECTED_CATALOG_MANIFEST_SHA256 = "09068cf0b0ff716075bdd693dbdfbdcf3779c7cb326a92aca11d9ab22b577f08"
EXPECTED_CATALOG_SPACE_SHA256 = "c5a29064acd626a0aa67559222789022aecd253cb9ab011bd6e7e4bb2253be63"
EXPECTED_IMPLEMENTATION_COMMIT_SHA = "0b654f1d25588cfca55c449e3634dd392e62e8f3"
EXPECTED_CALIBRATION_RUN_ID = 32137133180
EXPECTED_RUNTIME_INPUT_RUN_ID = 31418682679
EXPECTED_CALIBRATION_RECEIPT_SHA256 = "33bd4de291021733c7d9204d1eaf2832f06db4aa8e9088fd488e2ef32e100e8b"
EXPECTED_TARGET_END_ISO = "2026-08-20T07:31:00+02:00"
EXPECTED_PLAN_SHA256 = "064a7116240e2b43a53c69404f30a2b4cd5c4e90a280ee535636927cb2214d12"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class AtlasTerminalEvidenceError(ValueError):
    """A stable fail-closed code for one rejected evidence contract."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AtlasTerminalVerification:
    state: Literal["SUCCESS", "BLOCKED"]
    reason_code: str
    expected_recipe_count: int
    observed_recipe_count: int
    run_id: int | None
    run_url: str | None
    plan_sha256: str | None
    result_science_sha256: str | None
    artifact_count: int
    timing: Mapping[str, float | None]
    diagnostics: tuple[str, ...] = ()


def _canonical(value: object) -> str:
    return canonical_sha256(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_ARTIFACT_UNREADABLE") from exc
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise AtlasTerminalEvidenceError(f"ATLAS_TERMINAL_NONFINITE_JSON:{value}")


def read_json(path: Path, code: str = "ATLAS_TERMINAL_JSON_INVALID") -> object:
    if path.is_symlink() or not path.is_file():
        raise AtlasTerminalEvidenceError(code)
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except AtlasTerminalEvidenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AtlasTerminalEvidenceError(code) from exc


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AtlasTerminalEvidenceError(code)
    return value


def _sequence(value: object, code: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise AtlasTerminalEvidenceError(code)
    return value


def _positive_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AtlasTerminalEvidenceError(code)
    return value


def _sha(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise AtlasTerminalEvidenceError(code)
    return value


def _commit(value: object, code: str) -> str:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        raise AtlasTerminalEvidenceError(code)
    return value


def _false_boundaries(value: Mapping[str, Any], code: str) -> None:
    if value.get("validation_opened") is not False or value.get("locked_opened") is not False:
        raise AtlasTerminalEvidenceError(code)


def _self_hash(value: Mapping[str, Any], field: str, code: str) -> str:
    expected = _sha(value.get(field), code)
    identity = {key: item for key, item in value.items() if key != field}
    if _canonical(identity) != expected:
        raise AtlasTerminalEvidenceError(code)
    return expected


def _relative(root: Path, relative: str, code: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise AtlasTerminalEvidenceError(code)
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise AtlasTerminalEvidenceError(code)
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise AtlasTerminalEvidenceError(code)
    return candidate


def _parse_aware(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise AtlasTerminalEvidenceError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AtlasTerminalEvidenceError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AtlasTerminalEvidenceError(code)
    return parsed.astimezone(timezone.utc)


def _parse_run(run_path: Path) -> tuple[Mapping[str, Any], int, str, str]:
    run = _mapping(read_json(run_path, "ATLAS_TERMINAL_RUN_INVALID"), "ATLAS_TERMINAL_RUN_INVALID")
    run_id = _positive_int(run.get("id"), "ATLAS_TERMINAL_RUN_INVALID")
    run_url = run.get("html_url")
    if not isinstance(run_url, str) or not run_url.startswith("https://"):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_RUN_INVALID")
    head_sha = _commit(run.get("head_sha"), "ATLAS_TERMINAL_RUN_COMMIT_INVALID")
    path = run.get("path", run.get("workflow_path"))
    if path != CONTROLLER_WORKFLOW_PATH:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_WORKFLOW_INVALID")
    return run, run_id, run_url, head_sha


def _job_rows(value: object) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Mapping):
        pages: Sequence[object] = (value,)
    else:
        pages = _sequence(value, "ATLAS_TERMINAL_JOBS_INVALID")
    rows: list[Mapping[str, Any]] = []
    for page in pages:
        payload = _mapping(page, "ATLAS_TERMINAL_JOBS_INVALID")
        for raw in _sequence(payload.get("jobs"), "ATLAS_TERMINAL_JOBS_INVALID"):
            rows.append(_mapping(raw, "ATLAS_TERMINAL_JOBS_INVALID"))
    return tuple(rows)


def _job_base_name(name: object) -> str:
    if not isinstance(name, str):
        return ""
    lowered = name.casefold().strip()
    for candidate in (
        "preflight", "reduce", "evaluate_a", "evaluate_b", "evaluate_c",
        "gate", "finalize", "engine",
    ):
        # Jobs from a reusable workflow are exposed by GitHub with the
        # caller prefix, for example ``engine_atlas / evaluate_a (17)``.
        if re.search(rf"(?:^|/)\s*{re.escape(candidate)}(?:\s|\(|$)", lowered):
            return candidate
    return ""


def _validate_jobs(value: object) -> tuple[Mapping[str, Any], ...]:
    rows = _job_rows(value)
    expected_single = {"preflight", "reduce"}
    successful_single: set[str] = set()
    seen_gate = 0
    seen_engine = 0
    seen_engine_atlas = 0
    seen_finalize = 0
    matrix_rows: list[Mapping[str, Any]] = []
    for row in rows:
        raw_name = row.get("name", row.get("job_id"))
        base = _job_base_name(raw_name)
        conclusion = row.get("conclusion")
        if isinstance(raw_name, str) and raw_name.casefold().strip() == "engine_atlas":
            seen_engine_atlas += 1
            if seen_engine_atlas > 1 or conclusion != "success":
                raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_ENGINE_ATLAS_JOB_INVALID")
            continue
        if base == "gate":
            seen_gate += 1
            if conclusion != "success":
                raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_GATE_JOB_INVALID")
            continue
        if base == "engine":
            # The optimized reusable branch can expose skipped descendants
            # such as ``engine / engine_verify_sealed_plan`` in the parent
            # jobs API.  They are allowed evidence of the non-selected branch,
            # but only the exact ``engine`` job counts toward the required
            # optimized-branch assertion.
            if isinstance(raw_name, str) and "/" in raw_name:
                if conclusion != "skipped":
                    raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_OPTIMIZED_JOB_INVALID")
                continue
            seen_engine += 1
            if seen_engine > 1 or conclusion != "skipped":
                raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_OPTIMIZED_JOB_INVALID")
            continue
        if base == "finalize":
            seen_finalize += 1
            # The finalizer is the current job.  It is allowed to be absent
            # from a paginated snapshot, but never to report a terminal result
            # before this verifier has emitted its receipt.
            if seen_finalize > 1 or conclusion is not None:
                raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_FINALIZE_JOB_INVALID")
            continue
        if not base:
            if conclusion not in {"skipped", None}:
                raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_UNEXPECTED_JOB")
            continue
        if conclusion == "skipped":
            continue
        if conclusion != "success":
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_JOB_FAILED")
        if base in expected_single:
            if base in successful_single:
                raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_DUPLICATE_JOB")
            successful_single.add(base)
        else:
            matrix_rows.append(row)
    # GitHub does not guarantee that a skipped reusable-workflow caller is
    # present in the jobs snapshot. Its absence is safe; a non-skipped one is not.
    if successful_single != expected_single or seen_gate != 1:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_JOB_EVIDENCE_MISSING")
    if len(matrix_rows) != EXPECTED_SHARD_COUNT:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_MATRIX_JOB_COVERAGE_INVALID")
    bases = [_job_base_name(row.get("name", row.get("job_id"))) for row in matrix_rows]
    if set(bases) != {"evaluate_a", "evaluate_b", "evaluate_c"}:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_MATRIX_JOB_COVERAGE_INVALID")
    return rows


def _span_seconds(jobs: Sequence[Mapping[str, Any]], markers: tuple[str, ...]) -> float | None:
    intervals: list[tuple[datetime, datetime]] = []
    for job in jobs:
        name = str(job.get("name", "")).casefold()
        if not any(marker in name for marker in markers):
            continue
        if job.get("conclusion") == "skipped":
            continue
        try:
            start = _parse_aware(job.get("started_at"), "ATLAS_TERMINAL_JOB_TIME_INVALID")
            end = _parse_aware(job.get("completed_at"), "ATLAS_TERMINAL_JOB_TIME_INVALID")
        except AtlasTerminalEvidenceError:
            return None
        if end < start:
            return None
        intervals.append((start, end))
    if not intervals:
        return None
    return (max(end for _, end in intervals) - min(start for start, _ in intervals)).total_seconds()


def _validate_request_and_decision(
    context_path: Path,
    decision_path: Path,
) -> tuple[Mapping[str, Any], CatalogRunRequestV1, CatalogFastLaunchDecisionV1, int]:
    context = _mapping(read_json(context_path, "ATLAS_TERMINAL_REQUEST_CONTEXT_INVALID"), "ATLAS_TERMINAL_REQUEST_CONTEXT_INVALID")
    identity = {key: value for key, value in context.items() if key != "content_sha256"}
    if context.get("content_sha256") != _canonical(identity):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_REQUEST_CONTEXT_INVALID")
    try:
        request = CatalogRunRequestV1.model_validate(context.get("request"))
        decision = CatalogFastLaunchDecisionV1.model_validate(read_json(decision_path, "ATLAS_TERMINAL_DECISION_INVALID"))
    except Exception as exc:
        code = "ATLAS_TERMINAL_REQUEST_CONTEXT_INVALID" if "request" in str(exc).lower() else "ATLAS_TERMINAL_DECISION_INVALID"
        raise AtlasTerminalEvidenceError(code) from exc
    if request.campaign_key != context.get("identity", {}).get("campaign_key"):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_AUTHORITY_BINDING_INVALID")
    context_identity = _mapping(context.get("identity"), "ATLAS_TERMINAL_AUTHORITY_BINDING_INVALID")
    if (
        context_identity.get("engine_id") != "atlas_static_v1"
        or context_identity.get("campaign_key") != CAMPAIGN_KEY
        or context.get("logical_recipe_count") != EXPECTED_RECIPE_COUNT
    ):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_ATLAS_IDENTITY_INVALID")
    if (
        decision.request_sha256 != request.request_sha256
        or decision.submission_key_sha256 != request.submission_key_sha256
        or decision.campaign_key != request.campaign_key
        or not decision.launch_required
        or decision.state != "QUEUED"
        or decision.prepared_receipt_sha256 is None
    ):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_AUTHORITY_BINDING_INVALID")
    return context, request, decision, EXPECTED_RECIPE_COUNT


def _validate_freeze(repo_root: Path, plan: Any, prepared: AtlasPreparedReceiptV1) -> None:
    freeze_path = repo_root / "config" / "sp500_atlas_1" / "freeze_manifest_v1.json"
    freeze = _mapping(read_json(freeze_path, "ATLAS_TERMINAL_FREEZE_INVALID"), "ATLAS_TERMINAL_FREEZE_INVALID")
    expected = {
        "catalog_id": CATALOG_ID,
        "catalog_manifest_sha256": EXPECTED_CATALOG_MANIFEST_SHA256,
        "catalog_space_sha256": EXPECTED_CATALOG_SPACE_SHA256,
        "requested_recipe_count": EXPECTED_RECIPE_COUNT,
        "total_shards": EXPECTED_SHARD_COUNT,
        "selection_seed": EXPECTED_SELECTION_SEED,
        "selection_sha256": EXPECTED_SELECTION_SHA256,
        "train_end": EXPECTED_TRAIN_END,
        "scientific_implementation_commit_sha": EXPECTED_IMPLEMENTATION_COMMIT_SHA,
        "calibration_run_id": str(EXPECTED_CALIBRATION_RUN_ID),
        "runtime_input_run_id": str(EXPECTED_RUNTIME_INPUT_RUN_ID),
        "calibration_receipt_sha256": EXPECTED_CALIBRATION_RECEIPT_SHA256,
        "frozen_plan_sha256": EXPECTED_PLAN_SHA256,
        "target_end_iso": EXPECTED_TARGET_END_ISO,
    }
    for key, value in expected.items():
        if str(freeze.get(key)) != str(value):
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_FREEZE_BINDING_INVALID")
    if freeze.get("launch_authorized") is not True or freeze.get("execution_authorized") is not False:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_AUTHORIZATION_INVALID")
    _false_boundaries(freeze, "ATLAS_TERMINAL_BOUNDARY_OPEN")
    if (
        plan.catalog_id != CATALOG_ID
        or plan.catalog_manifest_sha256 != EXPECTED_CATALOG_MANIFEST_SHA256
        or plan.catalog_space_sha256 != EXPECTED_CATALOG_SPACE_SHA256
        or plan.plan_sha256 != prepared.plan_sha256
        or plan.calibration_receipt_sha256 != prepared.calibration_receipt_sha256
        or plan.implementation_commit_sha != EXPECTED_IMPLEMENTATION_COMMIT_SHA
        or plan.train_end != EXPECTED_TRAIN_END
        or plan.target_end_iso != prepared.target_end_iso
        or plan.target_end_iso == EXPECTED_TARGET_END_ISO
        or plan.requested_recipe_count != EXPECTED_RECIPE_COUNT
        or plan.total_shards != EXPECTED_SHARD_COUNT
        or plan.selection_seed != EXPECTED_SELECTION_SEED
        or plan.selection_sha256 != EXPECTED_SELECTION_SHA256
    ):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_PLAN_BINDING_INVALID")
    _false_boundaries(plan.model_dump(mode="json"), "ATLAS_TERMINAL_BOUNDARY_OPEN")


def _load_bound_prepared_receipt(
    preflight_root: Path,
    *,
    expected_receipt_sha256: str,
    expected_identity: AtlasPreparationIdentityV1,
) -> AtlasPreparedReceiptV1:
    path = _relative(
        preflight_root / "plan",
        "atlas_prepared_receipt.json",
        "ATLAS_TERMINAL_PREPARED_RECEIPT_INVALID",
    )
    try:
        prepared = AtlasPreparedReceiptV1.model_validate(
            read_json(path, "ATLAS_TERMINAL_PREPARED_RECEIPT_INVALID")
        )
    except (ValueError, TypeError) as exc:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_PREPARED_RECEIPT_INVALID") from exc
    if (
        prepared.receipt_sha256 != expected_receipt_sha256
        or prepared.identity != expected_identity
    ):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_PREPARED_BINDING_INVALID")
    return prepared


def _validate_preflight(
    preflight_root: Path,
    repo_root: Path,
    decision: CatalogFastLaunchDecisionV1,
    protected_commit_sha: str,
) -> tuple[Any, str]:
    if preflight_root.is_symlink() or not preflight_root.is_dir():
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_PREFLIGHT_MISSING")
    plan_path = preflight_root / "plan" / "atlas_run_plan.json"
    try:
        plan = load_plan(plan_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_PLAN_INVALID") from exc
    try:
        registry = load_catalog_campaign_registry(
            repo_root / "config" / "catalog_campaign_registry_v1.json"
        )
        entry = resolve_catalog_campaign(registry, CAMPAIGN_KEY, repo_root)
        if not isinstance(entry, CatalogAtlasCampaignEntryV1):
            raise ValueError("ATLAS_TERMINAL_ENGINE_INVALID")
        expected_identity = build_atlas_preparation_identity(
            repo_root, entry, protected_commit_sha
        )
    except (OSError, ValueError) as exc:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_PREPARATION_IDENTITY_INVALID") from exc
    if decision.prepared_receipt_sha256 is None:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_PREPARED_BINDING_INVALID")
    prepared = _load_bound_prepared_receipt(
        preflight_root,
        expected_receipt_sha256=decision.prepared_receipt_sha256,
        expected_identity=expected_identity,
    )
    _validate_freeze(repo_root, plan, prepared)
    manifest_path = _relative(preflight_root / "atlas", "manifest.json", "ATLAS_TERMINAL_CATALOG_INVALID")
    space_path = _relative(preflight_root / "atlas", "recipe_space.json", "ATLAS_TERMINAL_CATALOG_INVALID")
    manifest = _mapping(read_json(manifest_path, "ATLAS_TERMINAL_CATALOG_INVALID"), "ATLAS_TERMINAL_CATALOG_INVALID")
    space = _mapping(read_json(space_path, "ATLAS_TERMINAL_CATALOG_INVALID"), "ATLAS_TERMINAL_CATALOG_INVALID")
    if manifest.get("manifest_sha256") != EXPECTED_CATALOG_MANIFEST_SHA256:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_CATALOG_HASH_INVALID")
    if _canonical({key: value for key, value in manifest.items() if key != "manifest_sha256"}) != manifest.get("manifest_sha256"):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_CATALOG_HASH_INVALID")
    if _sha256_file(space_path) != EXPECTED_CATALOG_SPACE_SHA256:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_SPACE_HASH_INVALID")
    if _canonical({key: value for key, value in space.items() if key != "space_sha256"}) != space.get("space_sha256"):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_SPACE_HASH_INVALID")
    _false_boundaries(manifest, "ATLAS_TERMINAL_BOUNDARY_OPEN")
    _false_boundaries(space, "ATLAS_TERMINAL_BOUNDARY_OPEN")
    if manifest.get("catalog_id") != CATALOG_ID or manifest.get("execution_authorized") is not False:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_CATALOG_IDENTITY_INVALID")
    artifacts = manifest.get("artifacts_sha256")
    if not isinstance(artifacts, Mapping) or artifacts.get("recipe_space.json") != EXPECTED_CATALOG_SPACE_SHA256:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_CATALOG_HASH_INVALID")
    selection_path = _relative(preflight_root / "plan", "atlas_campaign_selection.json", "ATLAS_TERMINAL_SELECTION_INVALID")
    selection = _mapping(read_json(selection_path, "ATLAS_TERMINAL_SELECTION_INVALID"), "ATLAS_TERMINAL_SELECTION_INVALID")
    if selection.get("requested_recipe_count") != EXPECTED_RECIPE_COUNT or selection.get("seed") != EXPECTED_SELECTION_SEED or selection.get("selection_sha256") != EXPECTED_SELECTION_SHA256:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_SELECTION_INVALID")
    return plan, plan.plan_sha256


def _read_result_row(raw: bytes, code: str) -> Mapping[str, Any]:
    if not raw.endswith(b"\n") or raw == b"\n":
        raise AtlasTerminalEvidenceError(code)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite)
    except (UnicodeError, json.JSONDecodeError, AtlasTerminalEvidenceError) as exc:
        raise AtlasTerminalEvidenceError(code) from exc
    return _mapping(value, code)


def _verify_results_file(path: Path, *, start: int, stop: int, plan_sha256: str, code: str) -> tuple[int, float]:
    if path.is_symlink() or not path.is_file():
        raise AtlasTerminalEvidenceError(code)
    seen: set[int] = set()
    count = 0
    elapsed = 0.0
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for raw in stream:
                digest.update(raw)
                row = _read_result_row(raw, code)
                ordinal = row.get("ordinal")
                if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < start or ordinal >= stop or ordinal in seen:
                    raise AtlasTerminalEvidenceError(code)
                if row.get("plan_sha256") != plan_sha256 or row.get("validation_opened") is not False or row.get("locked_opened") is not False:
                    raise AtlasTerminalEvidenceError(code)
                result_hash = row.get("result_sha256")
                if not isinstance(result_hash, str) or _canonical({key: value for key, value in row.items() if key != "result_sha256"}) != result_hash:
                    raise AtlasTerminalEvidenceError(code)
                seen.add(ordinal)
                count += 1
    except AtlasTerminalEvidenceError:
        raise
    except OSError as exc:
        raise AtlasTerminalEvidenceError(code) from exc
    if count != stop - start or seen != set(range(start, stop)):
        raise AtlasTerminalEvidenceError(code)
    return count, elapsed


def _verify_source_index(final_root: Path, plan: Any) -> None:
    """Verify the reducer's compact proof of all source shard bindings.

    This is intentionally the only shard-level evidence consumed by the
    finalizer.  The reducer has already downloaded and verified each shard;
    this index preserves the exact ranges and result digests without making
    the finalizer perform 360 REST downloads again.
    """

    source_path = _relative(
        final_root,
        "source_results_index.json",
        "ATLAS_TERMINAL_SOURCE_INDEX_MISSING",
    )
    source = _mapping(
        read_json(source_path, "ATLAS_TERMINAL_SOURCE_INDEX_INVALID"),
        "ATLAS_TERMINAL_SOURCE_INDEX_INVALID",
    )
    _self_hash(source, "source_index_sha256", "ATLAS_TERMINAL_SOURCE_INDEX_HASH_INVALID")
    if (
        source.get("plan_sha256") != plan.plan_sha256
        or source.get("catalog_manifest_sha256") != plan.catalog_manifest_sha256
        or source.get("row_count") != EXPECTED_RECIPE_COUNT
        or source.get("shard_count") != EXPECTED_SHARD_COUNT
    ):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_SOURCE_INDEX_BINDING_INVALID")
    _false_boundaries(source, "ATLAS_TERMINAL_BOUNDARY_OPEN")
    rows = _sequence(source.get("shards"), "ATLAS_TERMINAL_SOURCE_INDEX_INVALID")
    if len(rows) != EXPECTED_SHARD_COUNT:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_SOURCE_INDEX_COVERAGE_INVALID")
    expected_by_index = {shard.shard_index: shard for shard in plan.shards}
    seen: set[int] = set()
    for raw in rows:
        row = _mapping(raw, "ATLAS_TERMINAL_SOURCE_INDEX_INVALID")
        index = row.get("shard_index")
        if isinstance(index, bool) or not isinstance(index, int) or index in seen or index not in expected_by_index:
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_SOURCE_INDEX_COVERAGE_INVALID")
        shard = expected_by_index[index]
        if (
            row.get("start_ordinal") != shard.start_ordinal
            or row.get("stop_ordinal") != shard.stop_ordinal
            or row.get("expected_recipe_count") != shard.expected_recipe_count
            or _sha(row.get("result_sha256"), "ATLAS_TERMINAL_SOURCE_INDEX_DIGEST_INVALID")
            != row.get("result_sha256")
        ):
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_SOURCE_INDEX_BINDING_INVALID")
        seen.add(index)
    if seen != set(expected_by_index):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_SOURCE_INDEX_COVERAGE_INVALID")


def _verify_final(final_root: Path, plan: Any) -> tuple[int, str]:
    if final_root.is_symlink() or not final_root.is_dir():
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_FINAL_ARTIFACT_MISSING")
    reduction = _mapping(read_json(_relative(final_root, "reduction_receipt.json", "ATLAS_TERMINAL_REDUCTION_INVALID"), "ATLAS_TERMINAL_REDUCTION_INVALID"), "ATLAS_TERMINAL_REDUCTION_INVALID")
    coverage = _mapping(read_json(_relative(final_root, "coverage_report.json", "ATLAS_TERMINAL_COVERAGE_INVALID"), "ATLAS_TERMINAL_COVERAGE_INVALID"), "ATLAS_TERMINAL_COVERAGE_INVALID")
    manifest = _mapping(read_json(_relative(final_root, "all_results_manifest.json", "ATLAS_TERMINAL_RESULT_MANIFEST_INVALID"), "ATLAS_TERMINAL_RESULT_MANIFEST_INVALID"), "ATLAS_TERMINAL_RESULT_MANIFEST_INVALID")
    reduction_exact = {"plan_sha256": plan.plan_sha256, "requested_recipe_count": EXPECTED_RECIPE_COUNT, "verified_recipe_count": EXPECTED_RECIPE_COUNT, "verified_shard_count": EXPECTED_SHARD_COUNT}
    coverage_exact = {"requested_recipe_count": EXPECTED_RECIPE_COUNT, "verified_recipe_count": EXPECTED_RECIPE_COUNT, "verified_shard_count": EXPECTED_SHARD_COUNT}
    if any(reduction.get(key) != value for key, value in reduction_exact.items()) or reduction.get("accepted") is not True or reduction.get("missing_ordinals") not in (None, 0) or reduction.get("duplicate_ordinals") not in (None, 0) or reduction.get("conflicts") not in (None, 0):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_REDUCTION_INVALID")
    if (
        reduction.get("catalog_manifest_sha256") != plan.catalog_manifest_sha256
        or reduction.get("selection_sha256") != plan.selection_sha256
        or reduction.get("storage_mode") != "combined_results_file"
        or reduction.get("row_hash_verification_mode") != "canonical_row_hash"
        or reduction.get("row_hashes_recomputed") is not True
        or reduction.get("result_file_hashes_verified") is not True
    ):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_REDUCTION_INVALID")
    if any(coverage.get(key) != value for key, value in coverage_exact.items()) or any(coverage.get(key) != 0 for key in ("missing_ordinals", "duplicate_ordinals", "conflicts")):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_COVERAGE_INVALID")
    if manifest.get("storage_mode") != "combined_results_file" or manifest.get("row_count") != EXPECTED_RECIPE_COUNT or manifest.get("results_path") != "../results.jsonl" or manifest.get("row_hash_verification_mode") != "canonical_row_hash" or manifest.get("row_hashes_recomputed") is not True or manifest.get("result_file_hashes_verified") is not True:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_RESULT_MANIFEST_INVALID")
    for value in (reduction, coverage, manifest):
        _false_boundaries(value, "ATLAS_TERMINAL_BOUNDARY_OPEN")
    # The normal full reducer stores one combined results.jsonl and therefore
    # does not emit source_results_index.json.  Validate that optional index
    # when present, without making it a hidden prerequisite for full runs.
    optional_source_index = final_root / "source_results_index.json"
    if optional_source_index.exists() or optional_source_index.is_symlink():
        _verify_source_index(final_root, plan)
    result_path = _relative(final_root, "results.jsonl", "ATLAS_TERMINAL_FINAL_RESULT_INVALID")
    count, _ = _verify_results_file(result_path, start=0, stop=EXPECTED_RECIPE_COUNT, plan_sha256=plan.plan_sha256, code="ATLAS_TERMINAL_FINAL_RESULT_INVALID")
    results_hash = _sha(reduction.get("results_sha256"), "ATLAS_TERMINAL_RESULT_HASH_INVALID")
    if results_hash != _sha256_file(result_path) or manifest.get("results_sha256") != results_hash:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_RESULT_HASH_INVALID")
    return count, results_hash


def verify_atlas_terminal_evidence(
    *,
    repo_root: Path,
    context_path: Path,
    decision_path: Path,
    run_path: Path,
    jobs_path: Path,
    preflight_root: Path,
    final_root: Path,
    gate_result: str | None = None,
    expected_plan_sha256: str | None = None,
    final_results_artifact: str = "sp500-atlas-final-results",
) -> tuple[Mapping[str, Any], CatalogRunRequestV1, CatalogFastLaunchDecisionV1, AtlasTerminalVerification]:
    context, request, decision, expected = _validate_request_and_decision(context_path, decision_path)
    run, run_id, run_url, head_sha = _parse_run(run_path)
    timing: dict[str, float | None] = {"initial_queue_seconds": None, "preparation_jobs_window_seconds": None, "evaluation_jobs_window_seconds": None, "recovery_jobs_window_seconds": None, "reduction_jobs_window_seconds": None, "worker_evaluation_seconds": None}
    try:
        if context.get("protected_commit_sha") != head_sha:
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_COMMIT_BINDING_INVALID")
        jobs = _validate_jobs(read_json(jobs_path, "ATLAS_TERMINAL_JOBS_INVALID"))
        if final_results_artifact != "sp500-atlas-final-results":
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_FINAL_ARTIFACT_NAME_INVALID")
        timing["preparation_jobs_window_seconds"] = _span_seconds(jobs, ("preflight",))
        timing["evaluation_jobs_window_seconds"] = _span_seconds(jobs, ("evaluate_a", "evaluate_b", "evaluate_c"))
        timing["reduction_jobs_window_seconds"] = _span_seconds(jobs, ("reduce",))
        created = _parse_aware(run.get("created_at"), "ATLAS_TERMINAL_RUN_TIME_INVALID")
        starts = [_parse_aware(row["started_at"], "ATLAS_TERMINAL_JOB_TIME_INVALID") for row in jobs if row.get("started_at")]
        if starts:
            timing["initial_queue_seconds"] = max(0.0, (min(starts) - created).total_seconds())
        plan, plan_sha = _validate_preflight(
            preflight_root, repo_root, decision, head_sha
        )
        if expected_plan_sha256 is not None and expected_plan_sha256 != plan_sha:
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_PLAN_OUTPUT_MISMATCH")
        final_count, result_hash = _verify_final(final_root, plan)
        if gate_result in {"failure", "cancelled", "skipped"}:
            raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_GATE_NOT_SUCCESS")
        # The controller finalizer runs in the same parent workflow run.  The
        # parent may still be in_progress and has no conclusion yet; successful
        # required jobs plus reducer evidence are the terminal proof.
        return context, request, decision, AtlasTerminalVerification("SUCCESS", "CATALOG_RUN_SUCCESS", expected, final_count, run_id, run_url, plan_sha, result_hash, 2, timing)
    except AtlasTerminalEvidenceError as exc:
        return context, request, decision, AtlasTerminalVerification("BLOCKED", exc.code, expected, 0, run_id, run_url, None, None, 0, timing, (exc.code,))


def build_terminal_receipt(
    *,
    request: CatalogRunRequestV1,
    decision: CatalogFastLaunchDecisionV1,
    verification: AtlasTerminalVerification,
    created_at: datetime | None = None,
) -> CatalogTerminalReceiptV2:
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    state = verification.state
    return CatalogTerminalReceiptV2.create(
        state=state,
        reason_code=verification.reason_code,
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256=decision.prepared_receipt_sha256,
        engine_run_id=verification.run_id if decision.launch_required else None,
        run_url=verification.run_url if decision.launch_required else None,
        expected_recipe_count=verification.expected_recipe_count,
        observed_recipe_count=min(verification.observed_recipe_count, verification.expected_recipe_count),
        timing=dict(verification.timing),
        recovered_block_ids=None,
        failure_class=None if state == "SUCCESS" else "infrastructure",
        result_science_sha256=verification.result_science_sha256,
        created_at=created_at,
    )


__all__ = [
    "CATALOG_ID",
    "CAMPAIGN_KEY",
    "AtlasTerminalEvidenceError",
    "AtlasTerminalVerification",
    "EXPECTED_RECIPE_COUNT",
    "EXPECTED_SHARD_COUNT",
    "CONTROLLER_WORKFLOW_PATH",
    "build_terminal_receipt",
    "read_json",
    "verify_atlas_terminal_evidence",
]
