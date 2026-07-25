"""``aurora github`` commands for the reusable performance framework."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from aurora.core.execution_policy import require_github_execution
from aurora.infra.github_performance.checkpoint import load_checkpoint
from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    CheckpointManifest,
    PilotResult,
    PreparedInputs,
    RunSpec,
    RuntimeEvidence,
    ShardDefinition,
    ShardPlan,
    TerminalState,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.execution_planner import (
    build_execution_plan,
    write_execution_plan,
    write_pilot_result,
)
from aurora.infra.github_performance.merge_planner import (
    build_merge_plan,
    write_merge_plan,
    write_shard_attempt_manifest,
)
from aurora.infra.github_performance.merge_runtime import (
    final_merge,
    merge_attempt_group,
)
from aurora.infra.github_performance.preflight import (
    freeze_resolved_contract,
    load_github_yaml,
    validate_run_spec,
    write_preflight_report,
)
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.github_performance.verifier import (
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
    if not isinstance(payload, dict) or key not in payload:
        raise ValueError(f"{path} does not contain {key}")
    return payload[key]


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


def _matrix_descriptor(shard: ShardDefinition) -> dict[str, Any]:
    return {
        "shard_id": shard.shard_id,
        "attempt_id": f"a-{uuid.uuid4()}",
        "merge_group": shard.merge_group,
        "assignment_artifact": shard.assignment_artifact,
        "assignment_member": shard.assignment_member,
        "assignment_sha256": shard.assignment_sha256,
    }


def _write_matrix_outputs(plan, output_dir: Path, max_bytes: int) -> Path:
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
    }
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
    os.environ["AURORA_ATTEMPT_ID"] = args.attempt_id
    os.environ["AURORA_ARTIFACT_NAME"] = args.artifact_name
    if args.prepared_root:
        os.environ["AURORA_PREPARED_ROOT"] = str(
            Path(args.prepared_root).resolve()
        )
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
    _print({"final_artifact_manifest": str(path)})
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

    plan = commands.add_parser("plan")
    plan.add_argument("--spec", required=True)
    plan.add_argument("--workload", required=True)
    plan.add_argument("--output-dir", required=True)
    plan.add_argument("--prepared")
    plan.add_argument("--pilot")
    plan.add_argument(
        "--execution-mode",
        choices=("optimized", "baseline"),
        default="optimized",
    )
    plan.add_argument("--forced-job-count", type=int, default=0)
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

    verify = commands.add_parser("verify")
    verify.add_argument("--spec", required=True)
    verify.add_argument("--root", required=True)
    verify.set_defaults(func=cmd_github_verify)


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
