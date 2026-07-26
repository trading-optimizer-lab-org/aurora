"""``aurora github`` commands for the reusable performance framework."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aurora.core.execution_policy import require_github_execution
from aurora.infra.github_performance.checkpoint import load_checkpoint
from aurora.infra.github_performance.campaign import (
    CampaignPhase,
    begin_merge_only,
    initialize_campaign_state,
    replan_campaign_state,
    resume_campaign_state,
    transition_campaign_state,
    write_campaign_state,
)
from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    CheckpointManifest,
    PerformanceContract,
    PilotResult,
    PlanningPilotResolution,
    PreparedInputs,
    RunSpec,
    RuntimeEvidence,
    ShardDefinition,
    ShardPlan,
    TerminalState,
    WorkUnitManifest,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.execution_planner import (
    PilotRequired,
    build_execution_plan,
    resolve_planning_pilot,
    write_execution_plan,
    write_pilot_result,
)
from aurora.infra.github_performance.guardrails import (
    PlanGuardrailViolation,
    assess_plan_guardrails,
    write_budget_audit,
    write_deadline_audit,
)
from aurora.infra.github_performance.merge_planner import (
    build_merge_level_matrices,
    build_merge_plan,
    write_merge_plan,
    write_shard_attempt_manifest,
)
from aurora.infra.github_performance.merge_runtime import (
    final_merge,
    merge_attempt_group,
    merge_plan_group,
)
from aurora.infra.github_performance.recovery import (
    RecoveryLoopStatus,
    build_terminal_unit_evidence_from_paths,
    build_recovery_loop_from_paths,
    write_recovery_loop,
)
from aurora.infra.github_performance.preflight import (
    freeze_resolved_contract,
    load_github_yaml,
    validate_run_spec,
    write_preflight_report,
)
from aurora.infra.github_performance.profiles import (
    build_performance_profile,
    load_performance_profile,
    performance_profile_key,
    write_performance_profile,
)
from aurora.infra.github_performance.shard_planner import (
    encode_matrix_outputs,
    replan_pending_units,
    sha256_file,
    split_matrices,
)
from aurora.infra.github_performance.telemetry import ResourceMonitor
from aurora.infra.github_performance.verifier import (
    seal_final_artifact,
    verify_final_artifact,
    write_campaign_closure,
    write_verification_report,
)
from aurora.infra.github_performance.workload import (
    load_workload,
    prepare_with_canonical_services,
    run_shard_with_lineage_check,
)


def _load_spec(path: str | Path) -> RunSpec:
    spec = RunSpec.model_validate(load_github_yaml(Path(path)))
    expected = str(spec.execution["environment_sha256"])
    if expected:
        manifest_path = Path(
            os.environ.get(
                "AURORA_ENVIRONMENT_MANIFEST",
                "environment_manifest.json",
            )
        )
        observed = _verified_environment_sha256(manifest_path)
        if observed != expected:
            raise ValueError("runtime environment sha256 mismatch")
    return spec


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            deep_thaw_json(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _print(payload: Any) -> None:
    print(
        json.dumps(
            deep_thaw_json(payload),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _normalise_prepared(
    prepared: PreparedInputs,
    root: Path,
) -> PreparedInputs:
    manifest = Path(prepared.manifest_path)
    if not manifest.is_absolute():
        manifest = root / manifest
    manifest = manifest.resolve()
    if not manifest.is_file():
        fallback = (root / Path(prepared.manifest_path).name).resolve()
        if fallback.is_file():
            manifest = fallback
        else:
            raise FileNotFoundError(
                f"prepared manifest is missing: {manifest}"
            )
    if sha256_file(manifest) != prepared.manifest_sha256:
        raise ValueError("prepared manifest sha256 mismatch")
    return prepared.model_copy(update={"manifest_path": str(manifest)})


def _load_prepared(path: str | Path) -> PreparedInputs:
    source = Path(path).resolve()
    prepared = PreparedInputs.model_validate_json(
        source.read_text(encoding="utf-8")
    )
    return _normalise_prepared(prepared, source.parent)


def _portable_prepared(
    prepared: PreparedInputs,
    root: Path,
) -> PreparedInputs:
    manifest = Path(prepared.manifest_path).resolve()
    relative = manifest.relative_to(root.resolve())
    return prepared.model_copy(update={"manifest_path": relative.as_posix()})


def _runtime_value(path: Path, key: str) -> Any:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not contain {key}")
    if key in payload:
        return payload[key]
    identity = payload.get("identity")
    if isinstance(identity, dict) and key in identity:
        return identity[key]
    legacy_aliases = {
        "dependency_lock_sha256": "installed_wheel_sha256",
    }
    legacy_key = legacy_aliases.get(key)
    if legacy_key is not None and legacy_key in payload:
        return payload[legacy_key]
    raise ValueError(f"{path} does not contain {key}")


def _verified_environment_sha256(path: Path) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("environment manifest is not an object")
    claimed = payload.pop("environment_sha256", None)
    if not isinstance(claimed, str):
        raise ValueError("environment manifest has no identity hash")
    if payload.get("schema_version") == "2":
        identity = payload.get("identity")
        if not isinstance(identity, dict):
            raise ValueError("environment manifest has no version-2 identity")
        hashed_payload = identity
    else:
        cache = payload.get("cache")
        if isinstance(cache, dict):
            cache.pop("hit", None)
        hashed_payload = payload
    encoded = json.dumps(
        hashed_payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    observed = hashlib.sha256(encoded).hexdigest()
    if observed != claimed:
        raise ValueError("environment manifest identity hash mismatch")
    return claimed


def _normalise_shard_assignment(
    shard: ShardDefinition,
    assignment_root: Path | None,
) -> ShardDefinition:
    member = Path(shard.assignment_member)
    if not member.is_absolute():
        if assignment_root is None:
            raise ValueError(
                "relative shard assignment requires --assignment-root"
            )
        member = Path(assignment_root).resolve() / member
    member = member.resolve()
    if not member.is_file():
        raise FileNotFoundError(f"shard assignment is missing: {member}")
    if sha256_file(member) != shard.assignment_sha256:
        raise ValueError("shard assignment sha256 mismatch")
    return shard.model_copy(update={"assignment_member": str(member)})


def _load_runtime_checkpoint(path: Path) -> CheckpointManifest:
    source = Path(path).resolve()
    checkpoint = load_checkpoint(source)
    payload = Path(checkpoint.payload_path)
    if not payload.is_absolute():
        payload = source.parent / payload
    return checkpoint.model_copy(
        update={"payload_path": str(payload.resolve())}
    )


def cmd_github_validate(args: argparse.Namespace) -> int:
    report = validate_run_spec(Path(args.spec))
    output_dir = Path(args.output_dir)
    path = write_preflight_report(report, output_dir)
    _print({"valid": report.valid, "report": str(path)})
    return 0 if report.valid else 2


def cmd_github_prepare(args: argparse.Namespace) -> int:
    require_github_execution("github prepare")
    spec = _load_spec(args.spec)
    workload = load_workload(args.workload)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared = prepare_with_canonical_services(
        workload,
        spec,
        output_dir,
    )
    normalised = _normalise_prepared(prepared, output_dir)
    portable = _portable_prepared(normalised, output_dir)
    path = _write_json(output_dir / "prepared_inputs.json", portable)
    _print({"prepared_inputs": str(path)})
    return 0


def cmd_github_freeze_contract(args: argparse.Namespace) -> int:
    require_github_execution("github freeze-contract")
    requested = _load_spec(args.spec)
    prepared = _load_prepared(args.prepared)
    environment_path = Path(args.environment_manifest)
    evidence = RuntimeEvidence(
        code_sha=args.code_sha,
        workflow_sha256=sha256_file(Path(args.workflow)),
        policy_hash=prepared.policy_hash,
        dependency_lock_sha256=str(
            _runtime_value(
                environment_path,
                "dependency_lock_sha256",
            )
        ),
        capacity_profile_sha256=sha256_file(
            Path(args.capacity_profile)
        ),
        data_manifest_sha256=prepared.manifest_sha256,
        snapshot_hash=prepared.snapshot_hash,
        metric_contract_sha256=sha256_file(
            Path(args.metric_contract)
        ),
        environment_sha256=_verified_environment_sha256(environment_path),
    )
    output_dir = Path(args.output_dir)
    paths = list(freeze_resolved_contract(
        requested,
        evidence,
        output_dir,
    ))
    copied = (
        (environment_path, output_dir / "environment_manifest.json"),
        (
            Path(args.metric_contract),
            output_dir / "metric_contract.json",
        ),
        (
            Path(args.capacity_profile),
            output_dir / "capacity_profile.json",
        ),
    )
    for source, destination in copied:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        paths.append(destination)
    _print({"contract_paths": [str(path) for path in paths]})
    return 0


def cmd_github_smoke(args: argparse.Namespace) -> int:
    require_github_execution("github smoke")
    spec = _load_spec(args.spec)
    prepared = _load_prepared(args.prepared)
    result = load_workload(args.workload).smoke(spec, prepared)
    path = _write_json(Path(args.output), result)
    _print({"passed": result.passed, "smoke_result": str(path)})
    return 0 if result.passed else 4


def cmd_github_pilot(args: argparse.Namespace) -> int:
    require_github_execution("github pilot")
    spec = _load_spec(args.spec)
    prepared = _load_prepared(args.prepared)
    result = load_workload(args.workload).pilot(spec, prepared)
    path = write_pilot_result(result, Path(args.output))
    _print({"performance_pilot": str(path)})
    return 0


def cmd_github_resolve_pilot(args: argparse.Namespace) -> int:
    """Reuse one exact profile or measure a fresh representative pilot."""

    require_github_execution("github resolve-pilot")
    spec = _load_spec(args.spec)
    prepared = _load_prepared(args.prepared)
    workload = load_workload(args.workload)
    contract = PerformanceContract.model_validate_json(
        Path(args.contract).read_text(encoding="utf-8")
    )
    profile = (
        load_performance_profile(Path(args.performance_profile))
        if args.performance_profile
        else None
    )
    observed_seconds = {
        key: value
        for key, value in (
            ("cold", args.observed_cold_seconds),
            ("warm", args.observed_warm_seconds),
        )
        if value is not None
    }
    requested_key = performance_profile_key(contract)
    try:
        resolution = resolve_planning_pilot(
            profile=profile,
            requested_key=requested_key,
            fresh_pilot=None,
            observed_seconds=observed_seconds,
        )
    except PilotRequired:
        fresh = workload.pilot(spec, prepared)
        resolution = resolve_planning_pilot(
            profile=profile,
            requested_key=requested_key,
            fresh_pilot=fresh,
            observed_seconds=observed_seconds,
        )
    pilot_path = write_pilot_result(
        resolution.pilot_result,
        Path(args.output),
    )
    resolution_path = _write_json(
        Path(args.resolution_output),
        resolution,
    )
    _print(
        {
            "performance_pilot": str(pilot_path),
            "planning_pilot_resolution": str(resolution_path),
            "profile_reused": resolution.profile_reused,
            "source": resolution.source,
            "reason_codes": list(resolution.reason_codes),
        }
    )
    return 0


def cmd_github_build_performance_profile(
    args: argparse.Namespace,
) -> int:
    """Publish an immutable exact-key profile from measured GitHub evidence."""

    require_github_execution("github build-performance-profile")
    contract = PerformanceContract.model_validate_json(
        Path(args.contract).read_text(encoding="utf-8")
    )
    pilot = PilotResult.model_validate_json(
        Path(args.pilot).read_text(encoding="utf-8")
    )
    setup_benchmark = json.loads(
        Path(args.environment_setup_benchmark).read_text(encoding="utf-8")
    )
    profile = build_performance_profile(
        contract=contract,
        pilot_result=pilot,
        environment_setup_benchmark=setup_benchmark,
        source_run_id=args.source_run_id,
        created_at=datetime.now(timezone.utc),
    )
    path = write_performance_profile(profile, Path(args.output))
    _print(
        {
            "performance_profile": str(path),
            "performance_profile_sha256": profile.profile_sha256,
            "source_run_id": profile.source_run_id,
        }
    )
    return 0


def _matrix_descriptor(shard: ShardDefinition) -> dict[str, Any]:
    return {
        "shard_id": shard.shard_id,
        "attempt_id": f"a-{uuid.uuid4()}",
        "merge_group": shard.merge_group,
        "assignment_artifact": shard.assignment_artifact,
        "assignment_member": shard.assignment_member,
        "assignment_sha256": shard.assignment_sha256,
    }


def _write_matrix_outputs(
    plan,
    merge_plan,
    output_dir: Path,
    max_bytes: int,
) -> Path:
    matrix_a = tuple(
        _matrix_descriptor(shard)
        for shard in plan.matrix_split.matrix_a
    )
    matrix_b = tuple(
        _matrix_descriptor(shard)
        for shard in plan.matrix_split.matrix_b
    )
    merge_groups = sorted(
        {shard.merge_group for shard in plan.shard_plan.shards}
    )
    payload = {
        "matrix_a_json": json.dumps(
            {"include": matrix_a},
            sort_keys=True,
            separators=(",", ":"),
        ),
        "matrix_b_json": json.dumps(
            {"include": matrix_b},
            sort_keys=True,
            separators=(",", ":"),
        ),
        "has_matrix_b": "true" if matrix_b else "false",
        "merge_matrix_json": json.dumps(
            {
                "include": [
                    {"merge_group": group} for group in merge_groups
                ]
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "selected_jobs": str(plan.job_count.selected_jobs),
        "merge_root_artifact": merge_plan.root_artifact,
        "merge_root_level": str(merge_plan.root_level),
    }
    for level, descriptors in build_merge_level_matrices(
        merge_plan
    ).items():
        payload[f"merge_level_{level}_matrix_json"] = json.dumps(
            {"include": descriptors},
            sort_keys=True,
            separators=(",", ":"),
        )
        payload[f"merge_level_{level}_count"] = str(len(descriptors))
    encoded_bytes = sum(
        len(str(value).encode("utf-8")) for value in payload.values()
    )
    if encoded_bytes >= max_bytes:
        raise ValueError("compact plan outputs exceed GitHub output limit")
    return _write_json(output_dir / "plan_outputs.json", payload)


def cmd_github_plan(args: argparse.Namespace) -> int:
    require_github_execution("github plan")
    spec = _load_spec(args.spec)
    workload = load_workload(args.workload)
    output_dir = Path(args.output_dir)
    if args.prepared:
        prepared = _load_prepared(args.prepared)
    else:
        prepared = prepare_with_canonical_services(
            workload,
            spec,
            output_dir / "prepared",
        )
        smoke = workload.smoke(spec, prepared)
        if not smoke.passed:
            raise RuntimeError(
                "SMOKE_FAILED: " + ",".join(smoke.reason_codes)
            )
    if args.pilot:
        pilot = PilotResult.model_validate_json(
            Path(args.pilot).read_text(encoding="utf-8")
        )
    else:
        pilot = workload.pilot(spec, prepared)
    if args.pilot_resolution:
        pilot_resolution = PlanningPilotResolution.model_validate_json(
            Path(args.pilot_resolution).read_text(encoding="utf-8")
        )
        if pilot_resolution.pilot_result != pilot:
            raise ValueError(
                "pilot resolution does not match performance pilot"
            )
    else:
        pilot_resolution = PlanningPilotResolution(
            pilot_result=pilot,
            source="fresh_pilot",
            profile_reused=False,
            reason_codes=("PLANNING_PILOT_RESOLUTION_NOT_SUPPLIED",),
            performance_profile_sha256=None,
        )
    _write_json(
        output_dir / "planning_pilot_resolution.json",
        pilot_resolution,
    )
    manifest = workload.enumerate_units(
        spec,
        prepared,
        output_dir / "work_units.parquet",
    )
    portable_manifest = manifest.model_copy(
        update={"path": Path(manifest.path).name}
    )
    _write_json(
        output_dir / "work_unit_manifest.json",
        portable_manifest,
    )
    plan = build_execution_plan(
        spec,
        manifest,
        pilot,
        output_dir,
        mode=args.execution_mode,
        forced_job_count=(
            args.forced_job_count
            if args.forced_job_count > 0
            else None
        ),
        performance_profile_sha256=(
            pilot_resolution.performance_profile_sha256
            if pilot_resolution.profile_reused
            else None
        ),
    )
    paths = write_execution_plan(plan, output_dir)
    merge_fan_in = (
        max(2, len(plan.shard_plan.shards))
        if args.execution_mode == "baseline"
        else int(spec.performance["merge_fan_in"])
    )
    merge_plan = build_merge_plan(
        plan.shard_plan.shards,
        fan_in=merge_fan_in,
        disk_budget_bytes=14 * 1024**3,
        run_id=str(spec.identity["campaign_id"]),
        source_artifact_prefix=(
            args.artifact_prefix
            or str(spec.identity["campaign_id"])
        ),
    )
    merge_plan_path = write_merge_plan(
        merge_plan,
        output_dir / "merge_plan.json",
    )
    pilot_path = write_pilot_result(
        pilot,
        output_dir / "performance_pilot.json",
    )
    matrix_path = _write_matrix_outputs(
        plan,
        merge_plan,
        output_dir,
        max_bytes=int(spec.performance["max_github_output_kb"]) * 1024,
    )
    _print(
        {
            "selected_jobs": plan.job_count.selected_jobs,
            "plans": [str(path) for path in paths],
            "pilot": str(pilot_path),
            "matrix_outputs": str(matrix_path),
            "merge_plan": str(merge_plan_path),
        }
    )
    return 0


def cmd_github_run_shard(args: argparse.Namespace) -> int:
    require_github_execution("github run-shard")
    spec = _load_spec(args.spec)
    workload = load_workload(args.workload)
    shard = ShardDefinition.model_validate_json(
        Path(args.shard).read_text(encoding="utf-8")
    )
    shard = _normalise_shard_assignment(
        shard,
        Path(args.assignment_root) if args.assignment_root else None,
    )
    checkpoint = None
    if args.checkpoint:
        checkpoint = _load_runtime_checkpoint(Path(args.checkpoint))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AURORA_ATTEMPT_ID"] = args.attempt_id
    os.environ["AURORA_ARTIFACT_NAME"] = args.artifact_name
    if args.prepared_root:
        os.environ["AURORA_PREPARED_ROOT"] = str(
            Path(args.prepared_root).resolve()
        )
    monitor = ResourceMonitor(
        workspace=output_dir,
        interval_seconds=5.0,
    )
    first_sample = monitor.sample_once()
    if first_sample is None or not first_sample.child_aware:
        raise RuntimeError("RESOURCE_EVIDENCE_MISSING")
    monitor.start()
    try:
        try:
            attempt = run_shard_with_lineage_check(
                workload,
                spec,
                shard,
                output_dir,
                checkpoint,
                expected_attempt_id=args.attempt_id,
                expected_artifact_name=args.artifact_name,
            )
        finally:
            monitor.stop()
            monitor.write_parquet(
                output_dir / "resource_samples.parquet"
            )
    except BaseException as exc:
        reason = "DETERMINISTIC_CODE_ERROR"
        if isinstance(exc, MemoryError):
            reason = "OUT_OF_MEMORY"
        elif isinstance(exc, ConnectionError):
            reason = "TRANSIENT_NETWORK"
        elif isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
            reason = "DISK_EXHAUSTED"
        attempt = AttemptManifest(
            shard_id=shard.shard_id,
            attempt_id=args.attempt_id,
            state=TerminalState.FAILED_TECHNICAL,
            spec_hash=canonical_sha256(spec),
            policy_hash=str(spec.policy["policy_hash"]),
            snapshot_hash=str(spec.data["snapshot_hash"]),
            code_sha=str(spec.identity["code_sha"]),
            dependency_lock_sha256=str(
                spec.execution["dependency_lock_sha256"]
            ),
            capacity_profile_sha256=str(
                spec.performance["capacity_profile_sha256"]
            ),
            output_sha256=None,
            reason_code=reason,
            artifact_name=args.artifact_name,
            unit_attempts_path=None,
            unit_attempts_sha256=None,
            checkpoint_artifact=None,
            completed_unit_count=0,
            output_rows=0,
            output_bytes=0,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            output_dir / "technical_error.json",
            {
                "error_type": type(exc).__name__,
                "reason_code": reason,
                "message": str(exc),
            },
        )
        _write_json(
            output_dir / "shard_attempt_manifest.json",
            attempt,
        )
        write_shard_attempt_manifest(
            [attempt],
            output_dir / "shard_attempt_manifest.parquet",
        )
        raise
    json_path = _write_json(
        output_dir / "shard_attempt_manifest.json",
        attempt,
    )
    parquet_path = write_shard_attempt_manifest(
        [attempt],
        output_dir / "shard_attempt_manifest.parquet",
    )
    _print(
        {
            "attempt": str(json_path),
            "attempt_parquet": str(parquet_path),
            "state": attempt.state.value,
        }
    )
    return 0


def cmd_github_recover_plan(args: argparse.Namespace) -> int:
    require_github_execution("github recover-plan")
    _load_spec(args.spec)
    from aurora.infra.github_performance.recovery import (
        build_recovery_plan_from_paths,
        write_recovery_plan,
    )

    plan = build_recovery_plan_from_paths(
        Path(args.shard_plan),
        tuple(Path(path) for path in args.attempt),
        tuple(Path(path) for path in args.checkpoint),
        Path(args.spec),
    )
    paths = write_recovery_plan(plan, Path(args.output_dir))
    _print({"paths": [str(path) for path in paths]})
    return 0


def cmd_github_merge_plan(args: argparse.Namespace) -> int:
    require_github_execution("github merge-plan")
    shard_plan = ShardPlan.model_validate_json(
        Path(args.shard_plan).read_text(encoding="utf-8")
    )
    plan = build_merge_plan(
        shard_plan.shards,
        fan_in=args.fan_in,
        disk_budget_bytes=args.disk_budget_bytes,
        run_id=args.run_id,
    )
    path = write_merge_plan(plan, Path(args.output))
    _print({"merge_plan": str(path), "groups": len(plan.groups)})
    return 0


def cmd_github_merge_group(args: argparse.Namespace) -> int:
    require_github_execution("github merge-group")
    _load_spec(args.spec)
    shard_plan = ShardPlan.model_validate_json(
        Path(args.shard_plan).read_text(encoding="utf-8")
    )
    workload = load_workload(args.workload)
    path = merge_attempt_group(
        workload,
        shard_plan,
        args.merge_group,
        Path(args.inputs_root),
        Path(args.output_dir),
    )
    _print({"partial_merge_manifest": str(path)})
    return 0


def cmd_github_merge_plan_group(args: argparse.Namespace) -> int:
    require_github_execution("github merge-plan-group")
    _load_spec(args.spec)
    shard_plan = ShardPlan.model_validate_json(
        Path(args.shard_plan).read_text(encoding="utf-8")
    )
    from aurora.infra.github_performance.contracts import MergePlan

    merge_plan = MergePlan.model_validate_json(
        Path(args.merge_plan).read_text(encoding="utf-8")
    )
    path = merge_plan_group(
        load_workload(args.workload),
        shard_plan,
        merge_plan,
        args.group_id,
        Path(args.inputs_root),
        Path(args.output_dir),
    )
    _print({"merge_node_manifest": str(path)})
    return 0


def cmd_github_final_merge(args: argparse.Namespace) -> int:
    require_github_execution("github final-merge")
    spec = _load_spec(args.spec)
    path = final_merge(
        load_workload(args.workload),
        spec,
        Path(args.partials_root),
        Path(args.plan_root),
        Path(args.contract_root),
        Path(args.output_dir),
        (
            Path(args.preflight_root)
            if args.preflight_root
            else None
        ),
        (
            Path(args.recovery_root)
            if args.recovery_root
            else None
        ),
    )
    _print({"final_merge_summary": str(path), "sealed": False})
    return 0


def cmd_github_seal_final_artifact(
    args: argparse.Namespace,
) -> int:
    require_github_execution("github seal-final-artifact")
    spec = _load_spec(args.spec)
    path = seal_final_artifact(Path(args.root), spec)
    _print({"final_artifact_manifest": str(path), "sealed": True})
    return 0


def cmd_github_verify(args: argparse.Namespace) -> int:
    require_github_execution("github verify")
    spec = _load_spec(args.spec)
    root = Path(args.root)
    report = verify_final_artifact(root, spec)
    report_path = write_verification_report(
        report,
        root / "final_verification_report.json",
    )
    closure_path = write_campaign_closure(
        report,
        root / "campaign_closure.json",
    )
    _print(
        {
            "passed": report.passed,
            "report": str(report_path),
            "closure": str(closure_path),
        }
    )
    return 0 if report.passed else 3


def cmd_github_guardrail_check(args: argparse.Namespace) -> int:
    require_github_execution("github guardrail-check")
    spec = _load_spec(args.spec)
    now_raw = getattr(args, "now", "")
    now = (
        datetime.fromisoformat(now_raw.replace("Z", "+00:00"))
        if now_raw
        else datetime.now(timezone.utc)
    )
    deadline, ledger, budget = assess_plan_guardrails(
        spec,
        now=now,
        projected_wall_seconds=args.projected_wall_seconds,
        projected_billable_minutes=args.projected_billable_minutes,
        cost_per_billable_minute=args.cost_per_billable_minute,
        checkpoint_margin_seconds=args.checkpoint_margin_seconds,
        consumed_billable_minutes=args.consumed_billable_minutes,
        committed_billable_minutes=args.committed_billable_minutes,
    )
    output_dir = Path(args.output_dir)
    budget_path = write_budget_audit(
        ledger,
        budget,
        output_dir / "budget_audit.json",
    )
    deadline_path = write_deadline_audit(
        deadline,
        output_dir / "deadline_audit.json",
    )
    reasons = (*deadline.reason_codes, *budget.reason_codes)
    if reasons:
        raise PlanGuardrailViolation(",".join(reasons))
    _print(
        {
            "budget_audit": str(budget_path),
            "deadline_audit": str(deadline_path),
            "route_allowed": True,
        }
    )
    return 0


def _command_now(args: argparse.Namespace) -> datetime:
    raw = str(getattr(args, "created_at", "") or "")
    if not raw:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return parsed


def cmd_github_campaign_update(args: argparse.Namespace) -> int:
    require_github_execution("github campaign-update")
    spec = _load_spec(args.spec)
    root = Path(args.state_root)
    campaign_id = str(spec.identity["campaign_id"])
    now = _command_now(args)
    pointer = root / "campaign_state_latest.json"
    if pointer.is_file():
        previous = resume_campaign_state(root, campaign_id=campaign_id)
    else:
        if not args.logical_unit_manifest_sha256:
            raise ValueError(
                "initial campaign state requires logical unit manifest sha256"
            )
        if not args.active_plan_sha256:
            raise ValueError(
                "initial campaign state requires active plan sha256"
            )
        previous = initialize_campaign_state(
            campaign_id=campaign_id,
            scientific_contract_sha256=canonical_sha256(spec),
            logical_unit_manifest_sha256=(
                args.logical_unit_manifest_sha256
            ),
            logical_unit_count=args.logical_unit_count,
            active_plan_sha256=args.active_plan_sha256,
            created_at=now,
        )
        path = write_campaign_state(previous, root)
        if args.phase == CampaignPhase.PLANNED.value:
            _print({"campaign_state": str(path), "version": 0})
            return 0
    phase = CampaignPhase(args.phase)
    completed_sha = args.completed_unit_manifest_sha256 or None
    state = transition_campaign_state(
        previous,
        phase=phase,
        completed_unit_count=args.completed_unit_count,
        completed_unit_manifest_sha256=completed_sha,
        pending_unit_count=args.pending_unit_count,
        active_plan_sha256=args.active_plan_sha256 or None,
        verified_source_artifacts=(
            tuple(args.verified_source_artifact)
            if args.verified_source_artifact
            else None
        ),
        active_attempt_ids=(
            tuple(args.active_attempt_id)
            if args.active_attempt_id
            else None
        ),
        wave=args.wave,
        hard_failure_reason=args.hard_failure_reason or None,
        created_at=now,
    )
    path = write_campaign_state(state, root)
    _print(
        {
            "campaign_state": str(path),
            "phase": state.phase.value,
            "version": state.version,
        }
    )
    return 0


def cmd_github_recovery_loop(args: argparse.Namespace) -> int:
    require_github_execution("github recovery-loop")
    spec = _load_spec(args.spec)
    result = build_recovery_loop_from_paths(
        Path(args.shard_plan),
        tuple(Path(path) for path in args.attempt),
        tuple(Path(path) for path in args.checkpoint),
        Path(args.spec),
        current_wave=args.current_wave,
        max_waves=args.max_waves,
        unit_attempt_paths=tuple(
            Path(path) for path in args.unit_attempt
        ),
    )
    paths = write_recovery_loop(result, Path(args.output_dir))
    state_root = Path(args.state_root)
    previous = resume_campaign_state(
        state_root,
        campaign_id=str(spec.identity["campaign_id"]),
    )
    phase_by_status = {
        RecoveryLoopStatus.RETRY: CampaignPhase.RECOVERING,
        RecoveryLoopStatus.REPLAN: CampaignPhase.REPLANNING,
        RecoveryLoopStatus.COMPLETE: CampaignPhase.READY_TO_MERGE,
        RecoveryLoopStatus.BLOCKED_HARD_FAILURE: (
            CampaignPhase.BLOCKED_HARD_FAILURE
        ),
        RecoveryLoopStatus.BUDGET_EXHAUSTED: (
            CampaignPhase.BLOCKED_HARD_FAILURE
        ),
    }
    next_state = transition_campaign_state(
        previous,
        phase=phase_by_status[result.status],
        completed_unit_count=result.terminal_unit_count,
        completed_unit_manifest_sha256=(
            result.terminal_unit_manifest_sha256
        ),
        pending_unit_count=(
            previous.logical_unit_count - result.terminal_unit_count
        ),
        verified_source_artifacts=result.verified_source_artifacts,
        active_attempt_ids=tuple(
            item.next_attempt_id
            for item in result.plan.decisions
            if item.next_attempt_id is not None
        ),
        wave=(
            result.current_wave
            if result.next_wave is None
            else result.next_wave
        ),
        hard_failure_reason=(
            ",".join(result.reason_codes)
            if result.reason_codes
            else None
        ),
        created_at=_command_now(args),
    )
    state_path = write_campaign_state(next_state, state_root)
    _print(
        {
            "paths": [str(path) for path in paths],
            "campaign_state": str(state_path),
            "status": result.status.value,
            "next_wave": result.next_wave,
            "retry_count": result.retry_count,
        }
    )
    return 0


def _load_operational_overrides(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    path = Path(raw)
    payload = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.is_file()
        else json.loads(raw)
    )
    if not isinstance(payload, dict):
        raise ValueError("operational overrides must be a JSON object")
    return payload


def cmd_github_replan(args: argparse.Namespace) -> int:
    require_github_execution("github replan")
    spec = _load_spec(args.spec)
    root = Path(args.state_root)
    previous = resume_campaign_state(
        root,
        campaign_id=str(spec.identity["campaign_id"]),
    )
    state = replan_campaign_state(
        previous,
        new_plan_sha256=args.new_plan_sha256,
        logical_unit_manifest_sha256=(
            args.logical_unit_manifest_sha256
        ),
        completed_unit_manifest_sha256=(
            args.completed_unit_manifest_sha256 or None
        ),
        operational_overrides=_load_operational_overrides(
            args.operational_overrides
        ),
        created_at=_command_now(args),
    )
    state_path = write_campaign_state(state, root)
    descriptor = _write_json(
        Path(args.output_dir) / "replan.json",
        {
            "campaign_state_sha256": state.state_sha256,
            "compute_scheduled": state.compute_scheduled,
            "logical_unit_manifest_sha256": (
                state.logical_unit_manifest_sha256
            ),
            "completed_unit_manifest_sha256": (
                state.completed_unit_manifest_sha256
            ),
            "new_plan_sha256": state.active_plan_sha256,
            "operational_overrides": state.operational_overrides,
        },
    )
    _print(
        {
            "campaign_state": str(state_path),
            "replan": str(descriptor),
        }
    )
    return 0


def cmd_github_replan_pending(args: argparse.Namespace) -> int:
    require_github_execution("github replan-pending")
    spec = _load_spec(args.spec)
    root = Path(args.state_root)
    previous = resume_campaign_state(
        root,
        campaign_id=str(spec.identity["campaign_id"]),
    )
    if previous.phase is not CampaignPhase.REPLANNING:
        raise ValueError("replan-pending requires campaign phase replanning")

    manifest_payload = json.loads(
        Path(args.work_unit_manifest).read_text(encoding="utf-8")
    )
    manifest_payload["path"] = str(Path(args.work_units))
    manifest = WorkUnitManifest.model_validate(manifest_payload)
    if manifest.sha256 != previous.logical_unit_manifest_sha256:
        raise ValueError("logical work-unit manifest changed during replan")
    evidence = build_terminal_unit_evidence_from_paths(
        tuple(Path(path) for path in args.attempt),
        tuple(Path(path) for path in args.unit_attempt),
    )
    if evidence.unit_count != previous.completed_unit_count:
        raise ValueError("terminal unit count does not match campaign state")
    if (
        evidence.unit_manifest_sha256
        != previous.completed_unit_manifest_sha256
    ):
        raise ValueError(
            "terminal unit evidence does not match campaign state"
        )

    output_dir = Path(args.output_dir)
    plan_root = output_dir / "plan"
    plan = replan_pending_units(
        manifest,
        evidence.unit_keys,
        args.requested_jobs,
        plan_root,
        wave=previous.wave + 1,
    )
    copied_units = plan_root / "work_units.parquet"
    shutil.copy2(Path(args.work_units), copied_units)
    output_manifest = manifest.model_copy(
        update={"path": str(copied_units)}
    )
    _write_json(plan_root / "work_unit_manifest.json", output_manifest)
    _write_json(plan_root / "balanced_shard_plan.json", plan)
    matrix_outputs = encode_matrix_outputs(split_matrices(plan.shards))
    _write_json(plan_root / "plan_outputs.json", matrix_outputs)

    overrides = _load_operational_overrides(
        args.operational_overrides
    )
    supplied_parallelism = overrides.get("requested_parallelism")
    if (
        supplied_parallelism is not None
        and int(supplied_parallelism) != args.requested_jobs
    ):
        raise ValueError(
            "requested_parallelism conflicts with requested_jobs"
        )
    overrides["requested_parallelism"] = args.requested_jobs
    state = replan_campaign_state(
        previous,
        new_plan_sha256=plan.plan_sha256,
        logical_unit_manifest_sha256=manifest.sha256,
        completed_unit_manifest_sha256=(
            evidence.unit_manifest_sha256
        ),
        operational_overrides=overrides,
        created_at=_command_now(args),
    )
    state_path = write_campaign_state(state, root)
    descriptor = _write_json(
        output_dir / "replan.json",
        {
            "campaign_state_sha256": state.state_sha256,
            "previous_plan_sha256": previous.active_plan_sha256,
            "new_plan_sha256": plan.plan_sha256,
            "logical_unit_manifest_sha256": manifest.sha256,
            "completed_unit_manifest_sha256": (
                evidence.unit_manifest_sha256
            ),
            "completed_unit_count": evidence.unit_count,
            "pending_unit_count": (
                manifest.unit_count - evidence.unit_count
            ),
            "selected_jobs": plan.selected_jobs,
            "operational_overrides": state.operational_overrides,
            "scientific_contract_unchanged": (
                state.scientific_contract_sha256
                == previous.scientific_contract_sha256
            ),
            "logical_units_unchanged": (
                state.logical_unit_manifest_sha256
                == previous.logical_unit_manifest_sha256
            ),
            "completed_evidence_unchanged": (
                state.completed_unit_manifest_sha256
                == previous.completed_unit_manifest_sha256
            ),
        },
    )
    _print(
        {
            "campaign_state": str(state_path),
            "replan": str(descriptor),
            "plan": str(plan_root / "balanced_shard_plan.json"),
        }
    )
    return 0


def cmd_github_merge_only(args: argparse.Namespace) -> int:
    require_github_execution("github merge-only")
    spec = _load_spec(args.spec)
    root = Path(args.state_root)
    previous = resume_campaign_state(
        root,
        campaign_id=str(spec.identity["campaign_id"]),
    )
    sources = tuple(args.source_artifact)
    state = begin_merge_only(
        previous,
        source_artifacts=sources,
        created_at=_command_now(args),
    )
    state_path = write_campaign_state(state, root)
    descriptor = _write_json(
        Path(args.output_dir) / "merge_only_plan.json",
        {
            "campaign_state_sha256": state.state_sha256,
            "source_artifacts": state.verified_source_artifacts,
            "compute_scheduled": False,
            "merge_only": True,
        },
    )
    _print(
        {
            "campaign_state": str(state_path),
            "merge_only_plan": str(descriptor),
        }
    )
    return 0


def register(subparsers, parent_parser=None) -> None:
    parser = subparsers.add_parser(
        "github",
        help="Plan and execute immutable GitHub-only workloads",
    )
    commands = parser.add_subparsers(dest="github_cmd", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--spec", required=True)
    validate.add_argument("--output-dir", default=".")
    validate.set_defaults(func=cmd_github_validate)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--spec", required=True)
    prepare.add_argument("--workload", required=True)
    prepare.add_argument("--output-dir", required=True)
    prepare.set_defaults(func=cmd_github_prepare)

    freeze = commands.add_parser("freeze-contract")
    freeze.add_argument("--spec", required=True)
    freeze.add_argument("--prepared", required=True)
    freeze.add_argument("--environment-manifest", required=True)
    freeze.add_argument("--workflow", required=True)
    freeze.add_argument("--metric-contract", required=True)
    freeze.add_argument("--capacity-profile", required=True)
    freeze.add_argument("--code-sha", required=True)
    freeze.add_argument("--output-dir", required=True)
    freeze.set_defaults(func=cmd_github_freeze_contract)

    smoke = commands.add_parser("smoke")
    smoke.add_argument("--spec", required=True)
    smoke.add_argument("--workload", required=True)
    smoke.add_argument("--prepared", required=True)
    smoke.add_argument("--output", required=True)
    smoke.set_defaults(func=cmd_github_smoke)

    pilot_command = commands.add_parser("pilot")
    pilot_command.add_argument("--spec", required=True)
    pilot_command.add_argument("--workload", required=True)
    pilot_command.add_argument("--prepared", required=True)
    pilot_command.add_argument("--output", required=True)
    pilot_command.set_defaults(func=cmd_github_pilot)

    resolve_pilot = commands.add_parser("resolve-pilot")
    resolve_pilot.add_argument("--spec", required=True)
    resolve_pilot.add_argument("--workload", required=True)
    resolve_pilot.add_argument("--prepared", required=True)
    resolve_pilot.add_argument("--contract", required=True)
    resolve_pilot.add_argument("--performance-profile")
    resolve_pilot.add_argument("--observed-cold-seconds", type=float)
    resolve_pilot.add_argument("--observed-warm-seconds", type=float)
    resolve_pilot.add_argument("--output", required=True)
    resolve_pilot.add_argument("--resolution-output", required=True)
    resolve_pilot.set_defaults(func=cmd_github_resolve_pilot)

    build_profile = commands.add_parser("build-performance-profile")
    build_profile.add_argument("--contract", required=True)
    build_profile.add_argument("--pilot", required=True)
    build_profile.add_argument(
        "--environment-setup-benchmark",
        required=True,
    )
    build_profile.add_argument("--source-run-id", required=True)
    build_profile.add_argument("--output", required=True)
    build_profile.set_defaults(
        func=cmd_github_build_performance_profile
    )

    plan = commands.add_parser("plan")
    plan.add_argument("--spec", required=True)
    plan.add_argument("--workload", required=True)
    plan.add_argument("--output-dir", required=True)
    plan.add_argument("--prepared")
    plan.add_argument("--pilot")
    plan.add_argument("--pilot-resolution")
    plan.add_argument(
        "--execution-mode",
        choices=("optimized", "baseline"),
        default="optimized",
    )
    plan.add_argument("--forced-job-count", type=int, default=0)
    plan.add_argument("--artifact-prefix", default="")
    plan.set_defaults(func=cmd_github_plan)

    run_shard = commands.add_parser("run-shard")
    run_shard.add_argument("--spec", required=True)
    run_shard.add_argument("--workload", required=True)
    run_shard.add_argument("--shard", required=True)
    run_shard.add_argument("--output-dir", required=True)
    run_shard.add_argument("--attempt-id", required=True)
    run_shard.add_argument("--artifact-name", required=True)
    run_shard.add_argument("--assignment-root")
    run_shard.add_argument("--prepared-root")
    run_shard.add_argument("--checkpoint")
    run_shard.set_defaults(func=cmd_github_run_shard)

    recover = commands.add_parser("recover-plan")
    recover.add_argument("--spec", required=True)
    recover.add_argument("--shard-plan", required=True)
    recover.add_argument("--attempt", action="append", default=[])
    recover.add_argument("--checkpoint", action="append", default=[])
    recover.add_argument("--output-dir", required=True)
    recover.set_defaults(func=cmd_github_recover_plan)

    merge = commands.add_parser("merge-plan")
    merge.add_argument("--shard-plan", required=True)
    merge.add_argument("--fan-in", type=int, required=True)
    merge.add_argument("--disk-budget-bytes", type=int, required=True)
    merge.add_argument("--run-id", required=True)
    merge.add_argument("--output", required=True)
    merge.set_defaults(func=cmd_github_merge_plan)

    merge_group = commands.add_parser("merge-group")
    merge_group.add_argument("--spec", required=True)
    merge_group.add_argument("--workload", required=True)
    merge_group.add_argument("--shard-plan", required=True)
    merge_group.add_argument("--merge-group", required=True)
    merge_group.add_argument("--inputs-root", required=True)
    merge_group.add_argument("--output-dir", required=True)
    merge_group.set_defaults(func=cmd_github_merge_group)

    merge_plan_group_command = commands.add_parser("merge-plan-group")
    merge_plan_group_command.add_argument("--spec", required=True)
    merge_plan_group_command.add_argument("--workload", required=True)
    merge_plan_group_command.add_argument("--shard-plan", required=True)
    merge_plan_group_command.add_argument("--merge-plan", required=True)
    merge_plan_group_command.add_argument("--group-id", required=True)
    merge_plan_group_command.add_argument("--inputs-root", required=True)
    merge_plan_group_command.add_argument("--output-dir", required=True)
    merge_plan_group_command.set_defaults(
        func=cmd_github_merge_plan_group
    )

    final_merge_command = commands.add_parser("final-merge")
    final_merge_command.add_argument("--spec", required=True)
    final_merge_command.add_argument("--workload", required=True)
    final_merge_command.add_argument("--partials-root", required=True)
    final_merge_command.add_argument("--plan-root", required=True)
    final_merge_command.add_argument("--contract-root", required=True)
    final_merge_command.add_argument("--preflight-root")
    final_merge_command.add_argument("--recovery-root")
    final_merge_command.add_argument("--output-dir", required=True)
    final_merge_command.set_defaults(func=cmd_github_final_merge)

    seal_final = commands.add_parser("seal-final-artifact")
    seal_final.add_argument("--spec", required=True)
    seal_final.add_argument("--root", required=True)
    seal_final.set_defaults(func=cmd_github_seal_final_artifact)

    verify = commands.add_parser("verify")
    verify.add_argument("--spec", required=True)
    verify.add_argument("--root", required=True)
    verify.set_defaults(func=cmd_github_verify)

    guardrail = commands.add_parser("guardrail-check")
    guardrail.add_argument("--spec", required=True)
    guardrail.add_argument(
        "--projected-wall-seconds",
        type=float,
        required=True,
    )
    guardrail.add_argument(
        "--projected-billable-minutes",
        type=float,
        required=True,
    )
    guardrail.add_argument("--output-dir", required=True)
    guardrail.add_argument("--cost-per-billable-minute", type=float)
    guardrail.add_argument(
        "--checkpoint-margin-seconds",
        type=float,
        default=60.0,
    )
    guardrail.add_argument(
        "--consumed-billable-minutes",
        type=float,
        default=0.0,
    )
    guardrail.add_argument(
        "--committed-billable-minutes",
        type=float,
        default=0.0,
    )
    guardrail.add_argument("--now", default="")
    guardrail.set_defaults(func=cmd_github_guardrail_check)

    campaign = commands.add_parser("campaign-update")
    campaign.add_argument("--spec", required=True)
    campaign.add_argument("--state-root", required=True)
    campaign.add_argument(
        "--phase",
        choices=tuple(item.value for item in CampaignPhase),
        required=True,
    )
    campaign.add_argument("--logical-unit-manifest-sha256", default="")
    campaign.add_argument("--logical-unit-count", type=int, default=0)
    campaign.add_argument("--active-plan-sha256", default="")
    campaign.add_argument("--completed-unit-manifest-sha256", default="")
    campaign.add_argument("--completed-unit-count", type=int)
    campaign.add_argument("--pending-unit-count", type=int)
    campaign.add_argument(
        "--verified-source-artifact",
        action="append",
        default=[],
    )
    campaign.add_argument(
        "--active-attempt-id",
        action="append",
        default=[],
    )
    campaign.add_argument("--wave", type=int)
    campaign.add_argument("--hard-failure-reason", default="")
    campaign.add_argument("--created-at", default="")
    campaign.set_defaults(func=cmd_github_campaign_update)

    recovery_loop = commands.add_parser("recovery-loop")
    recovery_loop.add_argument("--spec", required=True)
    recovery_loop.add_argument("--shard-plan", required=True)
    recovery_loop.add_argument("--attempt", action="append", default=[])
    recovery_loop.add_argument(
        "--unit-attempt",
        action="append",
        default=[],
    )
    recovery_loop.add_argument("--checkpoint", action="append", default=[])
    recovery_loop.add_argument("--state-root", required=True)
    recovery_loop.add_argument("--output-dir", required=True)
    recovery_loop.add_argument("--current-wave", type=int, default=0)
    recovery_loop.add_argument("--max-waves", type=int, default=4)
    recovery_loop.add_argument("--created-at", default="")
    recovery_loop.set_defaults(func=cmd_github_recovery_loop)

    replan = commands.add_parser("replan")
    replan.add_argument("--spec", required=True)
    replan.add_argument("--state-root", required=True)
    replan.add_argument("--new-plan-sha256", required=True)
    replan.add_argument(
        "--logical-unit-manifest-sha256",
        required=True,
    )
    replan.add_argument(
        "--completed-unit-manifest-sha256",
        default="",
    )
    replan.add_argument("--operational-overrides", default="{}")
    replan.add_argument("--output-dir", required=True)
    replan.add_argument("--created-at", default="")
    replan.set_defaults(func=cmd_github_replan)

    replan_pending = commands.add_parser("replan-pending")
    replan_pending.add_argument("--spec", required=True)
    replan_pending.add_argument("--state-root", required=True)
    replan_pending.add_argument("--work-unit-manifest", required=True)
    replan_pending.add_argument("--work-units", required=True)
    replan_pending.add_argument(
        "--attempt",
        action="append",
        default=[],
    )
    replan_pending.add_argument(
        "--unit-attempt",
        action="append",
        default=[],
    )
    replan_pending.add_argument("--requested-jobs", type=int, required=True)
    replan_pending.add_argument(
        "--operational-overrides",
        default="{}",
    )
    replan_pending.add_argument("--output-dir", required=True)
    replan_pending.add_argument("--created-at", default="")
    replan_pending.set_defaults(func=cmd_github_replan_pending)

    merge_only = commands.add_parser("merge-only")
    merge_only.add_argument("--spec", required=True)
    merge_only.add_argument("--state-root", required=True)
    merge_only.add_argument(
        "--source-artifact",
        action="append",
        required=True,
    )
    merge_only.add_argument("--output-dir", required=True)
    merge_only.add_argument("--created-at", default="")
    merge_only.set_defaults(func=cmd_github_merge_only)


def script_main(command: str, argv: list[str] | None = None) -> int:
    from aurora.cli.forge import main

    try:
        result = main(["github", command, *(argv or [])])
        return int(result or 0)
    except BaseException as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
