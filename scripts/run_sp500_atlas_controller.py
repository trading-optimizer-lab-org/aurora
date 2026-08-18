"""Dispatch, supervise, recover, and reduce immutable Atlas segments."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.atlas_segments import load_segment_manifest


def segment_dispatch_inputs(
    *,
    commit_sha: str,
    preflight_run_id: str,
    runtime_input_run_id: str,
    segment_index: int,
    controller_run_id: str,
    attempt: int,
) -> dict[str, str]:
    return {
        "commit_sha": commit_sha,
        "preflight_run_id": preflight_run_id,
        "runtime_input_run_id": runtime_input_run_id,
        "segment_index": str(segment_index),
        "controller_run_id": controller_run_id,
        "attempt": str(attempt),
    }


def _command(args: list[str]) -> str:
    completed = subprocess.run(args, check=True, text=True, capture_output=True)
    return completed.stdout.strip()


def _dispatch(
    *,
    repository: str,
    commit_sha: str,
    dispatch_ref: str,
    values: dict[str, str],
) -> None:
    args = ["gh", "workflow", "run", "sp500-atlas-segment.yml", "--repo", repository, "--ref", dispatch_ref]
    for key, value in values.items():
        args.extend(["-f", f"{key}={value}"])
    _command(args)


def _find_run_id(
    *,
    repository: str,
    commit_sha: str,
    before: datetime,
    used: set[str],
) -> str:
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        raw = _command([
            "gh", "run", "list", "--repo", repository,
            "--workflow", "sp500-atlas-segment.yml", "--limit", "100",
            "--json", "databaseId,headSha,createdAt",
        ])
        for item in json.loads(raw or "[]"):
            created = datetime.fromisoformat(str(item["createdAt"]).replace("Z", "+00:00"))
            run_id = str(item["databaseId"])
            if (
                run_id not in used
                and item.get("headSha") == commit_sha
                and created >= before - timedelta(seconds=10)
            ):
                return run_id
        time.sleep(5)
    raise RuntimeError("ATLAS_CONTROLLER_DISPATCH_RUN_ID_MISSING")


def _run_status(*, repository: str, run_id: str) -> tuple[str, str | None]:
    raw = _command([
        "gh", "run", "view", run_id, "--repo", repository,
        "--json", "status,conclusion",
    ])
    value = json.loads(raw)
    return str(value.get("status", "")), value.get("conclusion")


def _download_segment(
    *,
    repository: str,
    run_id: str,
    controller_run_id: str,
    segment_index: int,
    attempt: int,
    output_dir: Path,
) -> Path:
    target = output_dir / f"segment-{segment_index}-attempt-{attempt}"
    target.mkdir(parents=True, exist_ok=False)
    artifact = f"sp500-atlas-segment-result-{controller_run_id}-{segment_index}-{attempt}"
    _command(["gh", "run", "download", run_id, "--repo", repository, "--name", artifact, "--dir", str(target)])
    receipt = next(target.rglob("segment_receipt.json"), None)
    if receipt is None:
        raise RuntimeError("ATLAS_CONTROLLER_SEGMENT_RECEIPT_MISSING")
    return target


def run_controller(
    *,
    repository: str,
    commit_sha: str,
    dispatch_ref: str,
    preflight_run_id: str,
    runtime_input_run_id: str,
    controller_run_id: str,
    plan_path: Path,
    segment_manifest_path: Path,
    output_dir: Path,
    target_end_iso: str,
    launch_authorization: str,
    parallel_segments: int = 3,
    max_attempts: int = 3,
    poll_seconds: int = 30,
) -> dict[str, Any]:
    if launch_authorization != "AUTHORIZE_SP500_ATLAS_FULL_RUN":
        raise ValueError("ATLAS_CONTROLLER_AUTHORIZATION_INVALID")
    if parallel_segments <= 0 or max_attempts <= 0:
        raise ValueError("ATLAS_CONTROLLER_LIMIT_INVALID")
    plan = load_plan(plan_path)
    manifest = load_segment_manifest(segment_manifest_path.read_text("utf-8"), plan=plan)
    if plan.validation_opened or plan.locked_opened:
        raise ValueError("ATLAS_CONTROLLER_BOUNDARY_OPEN")
    target = datetime.fromisoformat(target_end_iso.replace("Z", "+00:00")) - timedelta(minutes=90)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    segment_root = output / "segments"
    segment_root.mkdir()

    pending = [int(item["segment_index"]) for item in manifest["segments"]]
    attempts: dict[int, int] = {index: 0 for index in pending}
    active: dict[str, tuple[int, int]] = {}
    successful: dict[int, dict[str, Any]] = {}
    used_run_ids: set[str] = set()
    started_at = datetime.now(timezone.utc)
    while pending or active:
        if datetime.now(timezone.utc) >= target:
            raise RuntimeError("ATLAS_CONTROLLER_REDUCTION_RESERVE_DEADLINE")
        while pending and len(active) < parallel_segments:
            index = pending.pop(0)
            attempts[index] += 1
            values = segment_dispatch_inputs(
                commit_sha=commit_sha,
                preflight_run_id=preflight_run_id,
                runtime_input_run_id=runtime_input_run_id,
                segment_index=index,
                controller_run_id=controller_run_id,
                attempt=attempts[index],
            )
            before = datetime.now(timezone.utc)
            _dispatch(repository=repository, commit_sha=commit_sha, dispatch_ref=dispatch_ref, values=values)
            run_id = _find_run_id(
                repository=repository,
                commit_sha=commit_sha,
                before=before,
                used=used_run_ids,
            )
            used_run_ids.add(run_id)
            active[run_id] = (index, attempts[index])

        for run_id, (index, attempt) in list(active.items()):
            status, conclusion = _run_status(repository=repository, run_id=run_id)
            if status != "completed":
                continue
            del active[run_id]
            if conclusion == "success":
                path = _download_segment(
                    repository=repository,
                    run_id=run_id,
                    controller_run_id=controller_run_id,
                    segment_index=index,
                    attempt=attempt,
                    output_dir=segment_root,
                )
                successful[index] = {"run_id": run_id, "attempt": attempt, "path": str(path)}
            elif attempt < max_attempts:
                pending.insert(0, index)
            else:
                raise RuntimeError(f"ATLAS_CONTROLLER_SEGMENT_FAILED:{index}:{run_id}:{conclusion}")
        if pending or active:
            time.sleep(poll_seconds)

    final_dir = output / "final"
    reduce_args = [
        sys.executable,
        "scripts/reduce_sp500_atlas_run.py",
        "--plan", str(plan_path),
        "--partitions-root", str(segment_root),
        "--output-dir", str(final_dir),
    ]
    subprocess.run(reduce_args, check=True)
    receipt = {
        "schema_version": 1,
        "controller_run_id": controller_run_id,
        "commit_sha": commit_sha,
        "plan_sha256": plan.plan_sha256,
        "segment_manifest_sha256": manifest["manifest_sha256"],
        "segment_count": len(manifest["segments"]),
        "successful_segments": sorted(successful),
        "attempts": attempts,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "controller_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--dispatch-ref", required=True)
    parser.add_argument("--preflight-run-id", required=True)
    parser.add_argument("--runtime-input-run-id", required=True)
    parser.add_argument("--controller-run-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--segment-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-end-iso", required=True)
    parser.add_argument("--launch-authorization", required=True)
    parser.add_argument("--parallel-segments", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(run_controller(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
