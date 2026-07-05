from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARTIFACT_NAME = "global-technical-buy-indicator-external-pack-72000-results"
WORKFLOW_FILE = "global-technical-buy-indicator-external-pack-360jobs.yml"
BRANCH = "codex/gtbi-github-only-external-pack-72000"
PACK_PATH = "scripts/strategy_packs/gtbi_long_hold_fundamental_timing_v1"
VALIDATED_SHA = "c834095b309cb56491f411c67ea5a280bbd70e81"
ORIGINAL_SHARDS = 360
STRATEGIES_PER_SHARD = 200
WAVE_LOGICAL_JOBS = 180
TOTAL_WAVES = 40


RUN_BLOCK_RE = re.compile(r"run_block \((\d+),\s*([^,]+),\s*(\d+),\s*(\d+)\)")


@dataclass(frozen=True)
class RunBlock:
    logical: int
    status: str
    conclusion: str | None


@dataclass
class RunInfo:
    run_id: int
    status: str
    conclusion: str | None
    created_at: str
    updated_at: str
    url: str
    head_sha: str
    blocks: list[RunBlock]
    job_names: set[str]
    has_final_artifact: bool = False

    @property
    def is_active(self) -> bool:
        return self.status in {"queued", "in_progress", "waiting", "requested", "pending"}

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def logicals(self) -> list[int]:
        return sorted(block.logical for block in self.blocks)

    @property
    def first_logical(self) -> int | None:
        values = self.logicals
        return values[0] if values else None

    @property
    def last_logical(self) -> int | None:
        values = self.logicals
        return values[-1] if values else None

    @property
    def is_full_wave_shape(self) -> bool:
        values = self.logicals
        return (
            len(values) == WAVE_LOGICAL_JOBS
            and values == list(range(values[0], values[0] + WAVE_LOGICAL_JOBS))
            and values[0] % WAVE_LOGICAL_JOBS == 0
        )

    @property
    def wave_index(self) -> int | None:
        if self.first_logical is None or not self.is_full_wave_shape:
            return None
        return self.first_logical // WAVE_LOGICAL_JOBS

    @property
    def failed_logicals(self) -> list[int]:
        failed: list[int] = []
        for block in self.blocks:
            if block.status == "completed" and block.conclusion not in {"success", "skipped"}:
                failed.append(block.logical)
        return sorted(failed)


def run_cmd(args: list[str], *, check: bool = True) -> str:
    attempts = 4 if check else 1
    last_proc: subprocess.CompletedProcess[str] | None = None
    for attempt in range(attempts):
        proc = subprocess.run(args, check=False, text=True, capture_output=True)
        last_proc = proc
        if proc.returncode == 0:
            return proc.stdout
        transient = any(
            token in proc.stderr
            for token in (
                "HTTP 500",
                "HTTP 502",
                "HTTP 503",
                "HTTP 504",
                "Server Error",
                "Bad Gateway",
            )
        )
        if not check or not transient or attempt == attempts - 1:
            break
        sleep_for = 10 * (attempt + 1)
        print(f"transient gh failure, retrying in {sleep_for}s: {' '.join(args)}", flush=True)
        time.sleep(sleep_for)
    assert last_proc is not None
    if check and last_proc.returncode != 0:
        raise RuntimeError(
            "command failed: "
            + " ".join(args)
            + f"\nstdout:\n{last_proc.stdout}\nstderr:\n{last_proc.stderr}"
        )
    return last_proc.stdout


def gh_json(args: list[str]) -> Any:
    return json.loads(run_cmd(["gh", *args]))


def parse_blocks(jobs: list[dict[str, Any]]) -> list[RunBlock]:
    blocks: list[RunBlock] = []
    for job in jobs:
        name = str(job.get("name", ""))
        match = RUN_BLOCK_RE.match(name)
        if not match:
            continue
        blocks.append(
            RunBlock(
                logical=int(match.group(3)),
                status=str(job.get("status") or ""),
                conclusion=job.get("conclusion"),
            )
        )
    return sorted(blocks, key=lambda block: block.logical)


def list_runs(repo: str, workflow: str, branch: str, limit: int) -> list[dict[str, Any]]:
    output = run_cmd(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            workflow,
            "--branch",
            branch,
            "--limit",
            str(limit),
            "--json",
            "databaseId,status,conclusion,createdAt,updatedAt,url,headSha",
        ]
    )
    return json.loads(output)


def artifact_exists(repo: str, run_id: int) -> bool:
    data = gh_json(["api", f"/repos/{repo}/actions/runs/{run_id}/artifacts"])
    for artifact in data.get("artifacts", []):
        if artifact.get("name") == ARTIFACT_NAME and not artifact.get("expired", False):
            return True
    return False


def load_run_info(repo: str, run: dict[str, Any], artifact_cache: dict[int, bool]) -> RunInfo:
    run_id = int(run["databaseId"])
    view = gh_json(
        [
            "run",
            "view",
            str(run_id),
            "--repo",
            repo,
            "--json",
            "jobs,status,conclusion,createdAt,updatedAt,url,headSha",
        ]
    )
    has_artifact = False
    if view.get("status") == "completed":
        if run_id not in artifact_cache:
            artifact_cache[run_id] = artifact_exists(repo, run_id)
        has_artifact = artifact_cache[run_id]
    return RunInfo(
        run_id=run_id,
        status=str(view.get("status") or ""),
        conclusion=view.get("conclusion"),
        created_at=str(view.get("createdAt") or run.get("createdAt") or ""),
        updated_at=str(view.get("updatedAt") or run.get("updatedAt") or ""),
        url=str(view.get("url") or run.get("url") or ""),
        head_sha=str(view.get("headSha") or run.get("headSha") or ""),
        blocks=parse_blocks(view.get("jobs") or []),
        job_names={str(job.get("name") or "") for job in (view.get("jobs") or [])},
        has_final_artifact=has_artifact,
    )


def load_runs_info(
    repo: str,
    raw_runs: list[dict[str, Any]],
    artifact_cache: dict[int, bool],
    *,
    max_workers: int = 8,
) -> tuple[list[RunInfo], int]:
    infos: list[RunInfo] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(load_run_info, repo, raw, artifact_cache): int(raw["databaseId"])
            for raw in raw_runs
        }
        for future in as_completed(futures):
            run_id = futures[future]
            try:
                infos.append(future.result())
            except Exception as exc:  # noqa: BLE001 - keep GitHub hiccups from killing orchestration
                failures += 1
                print(f"warning: could not inspect run {run_id}: {exc}", flush=True)
    return infos, failures


def slots_for_logical_job(logical_job: int, candidate_limit: int = 10) -> list[int]:
    shard = logical_job // (STRATEGIES_PER_SHARD // candidate_limit)
    chunk = logical_job % (STRATEGIES_PER_SHARD // candidate_limit)
    first_slot = shard * STRATEGIES_PER_SHARD + chunk * candidate_limit
    return list(range(first_slot, first_slot + candidate_limit))


def run_workflow(
    repo: str,
    branch: str,
    *,
    mode: str,
    candidate_count_per_job: int,
    job_start_index: int = 0,
    job_count: int = 0,
    recovery_job_indices: str = "",
) -> None:
    args = [
        "gh",
        "workflow",
        "run",
        WORKFLOW_FILE,
        "--repo",
        repo,
        "--ref",
        branch,
        "-f",
        "data_run_id=27936694743",
        "-f",
        "data_artifact_name=free-global-yahoo-daily-data-lake",
        "-f",
        f"external_strategy_pack_path={PACK_PATH}",
        "-f",
        f"candidate_count_per_job={candidate_count_per_job}",
        "-f",
        "candidate_timeout_seconds=300",
        "-f",
        "job_wall_clock_seconds=300",
        "-f",
        f"optimized_evaluation_mode={mode}",
        "-f",
        "enable_feature_cache=true",
        "-f",
        "enable_dedupe=true",
        "-f",
        "enable_safe_prefilter=true",
        "-f",
        "enable_early_stopping=true",
        "-f",
        "enable_cost_scheduling=false",
        "-f",
        "min_market_cap=2000000000",
        "-f",
        "train_end=2010-12-31",
        "-f",
        "validation_start=2011-01-01",
        "-f",
        "validation_end=2020-12-31",
        "-f",
        "locked_start=2021-01-01",
        "-f",
        "fail_on_unsupported=false",
        "-f",
        "logical_jobs_per_block=1",
        "-f",
        "test_mode=false",
        "-f",
        "test_max_jobs=100",
        "-f",
        f"job_start_index={job_start_index}",
        "-f",
        f"job_count={job_count}",
    ]
    if recovery_job_indices:
        args.extend(["-f", f"recovery_job_indices={recovery_job_indices}"])
    run_cmd(args)


def cancel_run(repo: str, run_id: int) -> None:
    run_cmd(["gh", "run", "cancel", str(run_id), "--repo", repo], check=False)


def wave_range(wave_index: int) -> tuple[int, int]:
    first = wave_index * WAVE_LOGICAL_JOBS
    return first, first + WAVE_LOGICAL_JOBS - 1


def choose_wave_runs(runs: list[RunInfo], excluded: set[int]) -> dict[int, RunInfo]:
    chosen: dict[int, RunInfo] = {}
    for run in sorted(runs, key=lambda item: item.created_at):
        if run.run_id in excluded or not run.is_full_wave_shape:
            continue
        wave = run.wave_index
        if wave is None or wave < 0 or wave >= TOTAL_WAVES:
            continue
        usable_completed = run.is_completed and run.has_final_artifact and run.conclusion != "cancelled"
        usable_active = run.is_active
        if not usable_completed and not usable_active:
            continue
        previous = chosen.get(wave)
        if previous is None:
            chosen[wave] = run
            continue
        if previous.is_active and run.is_completed and usable_completed:
            chosen[wave] = run
        elif previous.is_completed and run.is_completed and run.conclusion == "success":
            chosen[wave] = run
    return chosen


def cancel_duplicate_active_waves(repo: str, runs: list[RunInfo], excluded: set[int]) -> list[int]:
    by_wave: dict[int, list[RunInfo]] = {}
    for run in runs:
        if run.run_id in excluded or not run.is_full_wave_shape or not run.is_active:
            continue
        wave = run.wave_index
        if wave is None:
            continue
        by_wave.setdefault(wave, []).append(run)
    cancelled: list[int] = []
    for wave_runs in by_wave.values():
        if len(wave_runs) < 2:
            continue
        keep = sorted(wave_runs, key=lambda item: item.created_at)[0]
        for duplicate in sorted(wave_runs, key=lambda item: item.created_at)[1:]:
            print(f"cancel duplicate active wave run {duplicate.run_id}; keeping {keep.run_id}")
            cancel_run(repo, duplicate.run_id)
            cancelled.append(duplicate.run_id)
    return cancelled


def recovery_slots_covered(runs: list[RunInfo], excluded: set[int], *, completed_only: bool = False) -> set[int]:
    covered: set[int] = set()
    for run in runs:
        if run.run_id in excluded or run.is_full_wave_shape:
            continue
        completed = run.is_completed and run.has_final_artifact and run.conclusion != "cancelled"
        if completed_only:
            if not completed:
                continue
        elif not (run.is_active or completed):
            continue
        for logical in run.logicals:
            if 0 <= logical < ORIGINAL_SHARDS * STRATEGIES_PER_SHARD:
                covered.add(logical)
    return covered


def active_logical_jobs(runs: list[RunInfo], excluded: set[int]) -> int:
    total = 0
    for run in runs:
        if run.run_id in excluded:
            continue
        if run.is_active:
            total += len(run.blocks)
    return total


def completed_merge_run(runs: list[RunInfo], excluded: set[int]) -> RunInfo | None:
    for run in sorted(runs, key=lambda item: item.created_at, reverse=True):
        if run.run_id in excluded or run.blocks:
            continue
        if (
            "merge_cross_run" in run.job_names
            and run.is_completed
            and run.conclusion == "success"
            and run.has_final_artifact
        ):
            return run
    return None


def dispatch_next_actions(
    *,
    repo: str,
    branch: str,
    runs: list[RunInfo],
    excluded: set[int],
    max_parallel_logical_jobs: int,
    max_new_waves: int,
) -> bool:
    changed = False
    cancel_duplicate_active_waves(repo, runs, excluded)
    chosen_waves = choose_wave_runs(runs, excluded)
    recovery_covered = recovery_slots_covered(runs, excluded)
    recovery_completed = recovery_slots_covered(runs, excluded, completed_only=True)

    for wave, run in sorted(chosen_waves.items()):
        if not (run.is_completed and run.has_final_artifact and run.conclusion not in {None, "cancelled"}):
            continue
        failed_logicals = run.failed_logicals
        if not failed_logicals:
            continue
        missing_slots: list[int] = []
        for logical in failed_logicals:
            for slot in slots_for_logical_job(logical):
                if slot not in recovery_covered:
                    missing_slots.append(slot)
        if missing_slots:
            slots_csv = ",".join(str(slot) for slot in sorted(set(missing_slots)))
            print(f"dispatch recovery for wave {wave}, run {run.run_id}, slots={slots_csv}")
            run_workflow(
                repo,
                branch,
                mode="optimized_evaluation_v5_event_first",
                candidate_count_per_job=1,
                job_start_index=0,
                job_count=0,
                recovery_job_indices=slots_csv,
            )
            return True

    active_count = active_logical_jobs(runs, excluded)
    launched = 0
    for wave in range(TOTAL_WAVES):
        if wave in chosen_waves:
            continue
        if active_count + WAVE_LOGICAL_JOBS > max_parallel_logical_jobs and launched > 0:
            break
        if active_count >= max_parallel_logical_jobs:
            break
        first, last = wave_range(wave)
        print(f"dispatch missing wave {wave}: logical jobs {first}-{last}")
        run_workflow(
            repo,
            branch,
            mode="optimized_evaluation_v5_event_first",
            candidate_count_per_job=10,
            job_start_index=first,
            job_count=WAVE_LOGICAL_JOBS,
        )
        active_count += WAVE_LOGICAL_JOBS
        launched += 1
        changed = True
        if launched >= max_new_waves:
            break
    if changed:
        return True

    if len(chosen_waves) < TOTAL_WAVES:
        print(f"waiting: {len(chosen_waves)}/{TOTAL_WAVES} waves have usable active/completed runs")
        return False

    source_run_ids: list[int] = []
    recoveries_needed = False
    for wave in range(TOTAL_WAVES):
        run = chosen_waves[wave]
        if not (run.is_completed and run.has_final_artifact and run.conclusion != "cancelled"):
            print(f"waiting: wave {wave} run {run.run_id} is not completed with artifact")
            return False
        source_run_ids.append(run.run_id)
        for logical in run.failed_logicals:
            for slot in slots_for_logical_job(logical):
                if slot not in recovery_completed:
                    recoveries_needed = True
    if recoveries_needed:
        print("waiting: recoveries still needed")
        return False

    recovery_source_ids = [
        run.run_id
        for run in sorted(runs, key=lambda item: item.created_at)
        if run.run_id not in excluded
        and not run.is_full_wave_shape
        and run.is_completed
        and run.has_final_artifact
        and run.conclusion != "cancelled"
        and run.blocks
    ]
    source_run_ids.extend(recovery_source_ids)
    source_csv = ",".join(str(run_id) for run_id in dict.fromkeys(source_run_ids))

    if completed_merge_run(runs, excluded) is not None:
        print("merge already completed")
        return False

    active_merge = [
        run
        for run in runs
        if run.run_id not in excluded and not run.blocks and "merge_cross_run" in run.job_names and run.is_active
    ]
    if active_merge:
        print(f"waiting: merge already active: {[run.run_id for run in active_merge]}")
        return False

    print(f"dispatch final cross-run merge with {len(source_run_ids)} source runs")
    run_workflow(
        repo,
        branch,
        mode="merge_cross_run",
        candidate_count_per_job=10,
        recovery_job_indices=source_csv,
    )
    return True


def self_dispatch(repo: str, branch: str) -> None:
    print("dispatch successor orchestrator run")
    run_workflow(
        repo,
        branch,
        mode="orchestrate_longhold_72k",
        candidate_count_per_job=10,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "trading-optimizer-lab-org/aurora"))
    parser.add_argument("--branch", default=BRANCH)
    parser.add_argument("--workflow", default=WORKFLOW_FILE)
    parser.add_argument("--loop-minutes", type=int, default=300)
    parser.add_argument("--sleep-seconds", type=int, default=300)
    parser.add_argument("--run-list-limit", type=int, default=200)
    parser.add_argument("--min-run-created-at", default="2026-07-04T00:00:00Z")
    parser.add_argument("--inspect-workers", type=int, default=8)
    parser.add_argument("--max-parallel-logical-jobs", type=int, default=360)
    parser.add_argument("--max-new-waves-per-pass", type=int, default=2)
    parser.add_argument(
        "--exclude-run-ids",
        default="28666430744,28701453837,28701456697,28716016695,28717957514",
    )
    parser.add_argument("--self-dispatch", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main() -> int:
    args = parse_args()
    excluded = {
        int(item.strip())
        for item in str(args.exclude_run_ids).split(",")
        if item.strip()
    }
    deadline = time.monotonic() + max(args.loop_minutes, 1) * 60
    artifact_cache: dict[int, bool] = {}

    while True:
        print(f"orchestrator pass at {datetime.now(timezone.utc).isoformat()}")
        raw_runs = list_runs(args.repo, args.workflow, args.branch, args.run_list_limit)
        min_created_at = parse_utc(args.min_run_created_at)
        raw_runs = [
            raw
            for raw in raw_runs
            if parse_utc(str(raw.get("createdAt") or "1970-01-01T00:00:00Z")) >= min_created_at
        ]
        runs, load_failures = load_runs_info(
            args.repo,
            raw_runs,
            artifact_cache,
            max_workers=max(args.inspect_workers, 1),
        )
        if load_failures:
            print(f"warning: skipped {load_failures} runs due to inspect errors", flush=True)
        runs = [run for run in runs if run.head_sha == VALIDATED_SHA or run.is_active or run.has_final_artifact]
        changed = dispatch_next_actions(
            repo=args.repo,
            branch=args.branch,
            runs=runs,
            excluded=excluded,
            max_parallel_logical_jobs=args.max_parallel_logical_jobs,
            max_new_waves=args.max_new_waves_per_pass,
        )
        merge = completed_merge_run(runs, excluded)
        if merge is not None:
            print(f"completed merge detected: {merge.run_id} {merge.url}")
            return 0
        if args.once:
            return 0
        if time.monotonic() + args.sleep_seconds > deadline:
            if args.self_dispatch:
                self_dispatch(args.repo, args.branch)
            return 0
        if changed:
            time.sleep(min(args.sleep_seconds, 120))
        else:
            time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    sys.exit(main())
