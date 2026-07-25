"""``aurora github`` commands for the reusable performance framework."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from aurora.core.execution_policy import require_github_execution
from aurora.infra.github_performance.contracts import (
    CheckpointManifest,
    RunSpec,
    ShardDefinition,
    ShardPlan,
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
from aurora.infra.github_performance.preflight import (
    load_github_yaml,
    validate_run_spec,
    write_preflight_report,
)
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
    return RunSpec.model_validate(load_github_yaml(Path(path)))


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


def cmd_github_validate(args: argparse.Namespace) -> int:
    report = validate_run_spec(Path(args.spec))
    output_dir = Path(args.output_dir)
    path = write_preflight_report(report, output_dir)
    _print({"valid": report.valid, "report": str(path)})
    return 0 if report.valid else 2


def cmd_github_plan(args: argparse.Namespace) -> int:
    require_github_execution("github plan")
    spec = _load_spec(args.spec)
    workload = load_workload(args.workload)
    output_dir = Path(args.output_dir)
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
    pilot = workload.pilot(spec, prepared)
    manifest = workload.enumerate_units(
        spec,
        prepared,
        output_dir / "work_units.parquet",
    )
    plan = build_execution_plan(spec, manifest, pilot, output_dir)
    paths = write_execution_plan(plan, output_dir)
    pilot_path = write_pilot_result(
        pilot,
        output_dir / "performance_pilot.json",
    )
    _print(
        {
            "selected_jobs": plan.job_count.selected_jobs,
            "plans": [str(path) for path in paths],
            "pilot": str(pilot_path),
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
    checkpoint = None
    if args.checkpoint:
        checkpoint = CheckpointManifest.model_validate_json(
            Path(args.checkpoint).read_text(encoding="utf-8")
        )
    output_dir = Path(args.output_dir)
    attempt = run_shard_with_lineage_check(
        workload,
        spec,
        shard,
        output_dir,
        checkpoint,
    )
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

    plan = commands.add_parser("plan")
    plan.add_argument("--spec", required=True)
    plan.add_argument("--workload", required=True)
    plan.add_argument("--output-dir", required=True)
    plan.set_defaults(func=cmd_github_plan)

    run_shard = commands.add_parser("run-shard")
    run_shard.add_argument("--spec", required=True)
    run_shard.add_argument("--workload", required=True)
    run_shard.add_argument("--shard", required=True)
    run_shard.add_argument("--output-dir", required=True)
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
