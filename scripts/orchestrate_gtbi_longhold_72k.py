from __future__ import annotations

import argparse
import csv
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
from urllib.parse import quote


ARTIFACT_NAME = "global-technical-buy-indicator-external-pack-72000-results"
WORKFLOW_FILE = "global-technical-buy-indicator-external-pack-360jobs.yml"
BRANCH = "codex/gtbi-github-only-external-pack-72000"
PACK_PATH = "scripts/strategy_packs/gtbi_long_hold_fundamental_timing_v1"
VALIDATED_SHA = ""
ORIGINAL_SHARDS = 360
STRATEGIES_PER_SHARD = 200
WAVE_LOGICAL_JOBS = 180
TOTAL_WAVES = 40
DEFAULT_RECOVERY_TIMEOUT_SECONDS = 1800
DEFAULT_RECOVERY_WALL_CLOCK_SECONDS = 2100
DEFAULT_RECOVERY_LOGICAL_JOBS_PER_BLOCK = 1
RECOVERY_MANIFEST_COLUMNS = [
    "strategy_id",
    "logical_job_id",
    "block_id",
    "concept",
    "family",
    "signal_hash",
    "exit_hash",
    "timeout_reason",
    "previous_runtime_seconds",
    "recovery_round",
    "partition_type",
    "subgroup_index",
    "subgroup_count",
    "symbol_bucket_index",
    "symbol_bucket_count",
    "candidate_timeout_seconds",
    "job_wall_clock_seconds",
]


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


@dataclass(frozen=True)
class ArtifactInspection:
    run_id: int
    timeout_slots: set[int]
    slow_deferred_slots: set[int]
    runtime_error_slots: set[int]
    unsupported_slots: set[int]
    recoverable_records: dict[int, StrategyRecoveryRecord]
    synthetic_missing_timeout_rows: int
    fill_missing_timeouts_enabled: bool

    @property
    def recoverable_slots(self) -> set[int]:
        return set(self.timeout_slots) | set(self.slow_deferred_slots)

    @property
    def unresolved_slots(self) -> set[int]:
        return (
            set(self.timeout_slots)
            | set(self.slow_deferred_slots)
            | set(self.runtime_error_slots)
            | set(self.unsupported_slots)
        )


@dataclass(frozen=True)
class StrategyRecoveryRecord:
    strategy_id: str
    slot: int
    shard_id: int
    slot_in_shard: int
    family: str = ""
    concept: str = ""
    market_overlay: str = ""
    trend_filter: str = ""
    relative_strength_filter: str = ""
    exit_rule: str = ""
    signal_hash: str = ""
    exit_hash: str = ""
    timeout_reason: str = ""
    previous_runtime_seconds: str = ""


@dataclass(frozen=True)
class RecoveryRoundConfig:
    recovery_round: int
    partition_type: str
    subgroup_count: int
    symbol_bucket_count: int
    candidate_timeout_seconds: int
    job_wall_clock_seconds: int


def recovery_config_for_round(recovery_round: int) -> RecoveryRoundConfig:
    round_number = max(1, min(int(recovery_round), 4))
    if round_number == 1:
        return RecoveryRoundConfig(1, "signal_subgroup", 5, 0, 900, 1200)
    if round_number == 2:
        return RecoveryRoundConfig(2, "signal_subgroup", 10, 0, 1800, 2100)
    if round_number == 3:
        return RecoveryRoundConfig(3, "signal_subgroup", 20, 0, 1800, 2100)
    return RecoveryRoundConfig(4, "symbol_bucket", 0, 10, 1800, 2100)


def run_cmd(
    args: list[str],
    *,
    check: bool = True,
    timeout_seconds: int = 120,
    attempts: int | None = None,
) -> str:
    attempts = (12 if check else 1) if attempts is None else max(int(attempts), 1)
    last_proc: subprocess.CompletedProcess[str] | None = None
    for attempt in range(attempts):
        try:
            proc = subprocess.run(args, check=False, text=True, capture_output=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(
                args=args,
                returncode=124,
                stdout=exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or ""),
                stderr=exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "command timed out"),
            )
        last_proc = proc
        if proc.returncode == 0:
            return proc.stdout
        transient = any(
            token in proc.stderr
            for token in (
                "rate limit exceeded",
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
        sleep_for = min(900, 120 * (attempt + 1)) if "rate limit exceeded" in proc.stderr else 10 * (attempt + 1)
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


def gh_json(args: list[str], *, timeout_seconds: int = 120, attempts: int | None = None) -> Any:
    return json.loads(run_cmd(["gh", *args], timeout_seconds=timeout_seconds, attempts=attempts))


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


def list_runs(
    repo: str,
    workflow: str,
    branch: str,
    limit: int,
    min_created_at: str | None = None,
) -> list[dict[str, Any]]:
    del limit  # Historical CLI option; the orchestrator must not lose old runs.
    runs: list[dict[str, Any]] = []
    encoded_branch = quote(branch, safe="")
    encoded_workflow = quote(workflow, safe="")
    min_created = parse_utc(min_created_at) if min_created_at else None
    page = 1
    while True:
        data = gh_json(
            [
                "api",
                f"/repos/{repo}/actions/workflows/{encoded_workflow}/runs"
                f"?branch={encoded_branch}&per_page=100&page={page}",
            ]
        )
        page_runs = data.get("workflow_runs", [])
        if not page_runs:
            break
        reached_older_run = False
        for raw in page_runs:
            created_at = str(raw.get("created_at") or "1970-01-01T00:00:00Z")
            if min_created is not None and parse_utc(created_at) < min_created:
                reached_older_run = True
                continue
            runs.append(
                {
                    "databaseId": raw.get("id"),
                    "status": raw.get("status"),
                    "conclusion": raw.get("conclusion"),
                    "createdAt": raw.get("created_at"),
                    "updatedAt": raw.get("updated_at"),
                    "url": raw.get("html_url"),
                    "headSha": raw.get("head_sha"),
                }
            )
        if len(page_runs) < 100:
            break
        if reached_older_run:
            break
        page += 1
    return runs


def artifact_exists(repo: str, run_id: int) -> bool:
    data = gh_json(["api", f"/repos/{repo}/actions/runs/{run_id}/artifacts"])
    for artifact in data.get("artifacts", []):
        if artifact.get("name") == ARTIFACT_NAME and not artifact.get("expired", False):
            return True
    return False


def run_jobs(repo: str, run_id: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    page = 1
    while True:
        data = gh_json(
            ["api", f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}"],
            timeout_seconds=30,
            attempts=1,
        )
        batch = data.get("jobs", [])
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return jobs


def _int_from_row(row: dict[str, str], key: str) -> int | None:
    value = str(row.get(key, "")).strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def slot_from_strategy_row(row: dict[str, str], *, candidate_limit: int = 10) -> int | None:
    shard_id = _int_from_row(row, "shard_id")
    slot_in_shard = _int_from_row(row, "slot_in_shard")
    if shard_id is not None and slot_in_shard is not None:
        if shard_id < 0 or shard_id >= ORIGINAL_SHARDS:
            return None
        if slot_in_shard < 0 or slot_in_shard >= STRATEGIES_PER_SHARD:
            return None
        return shard_id * STRATEGIES_PER_SHARD + slot_in_shard
    logical_job_id = _int_from_row(row, "logical_job_id")
    if logical_job_id is not None and candidate_limit == 1:
        if 0 <= logical_job_id < ORIGINAL_SHARDS * STRATEGIES_PER_SHARD:
            return logical_job_id
    return None


def _slots_from_csv(path: Path) -> set[int]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    slots: set[int] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            slot = slot_from_strategy_row(row)
            if slot is not None:
                slots.add(slot)
    return slots


def _text_from_row(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def _recovery_records_from_csv(path: Path) -> dict[int, StrategyRecoveryRecord]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    records: dict[int, StrategyRecoveryRecord] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            slot = slot_from_strategy_row(row)
            if slot is None:
                continue
            shard_id = slot // STRATEGIES_PER_SHARD
            slot_in_shard = slot % STRATEGIES_PER_SHARD
            records[slot] = StrategyRecoveryRecord(
                strategy_id=_text_from_row(row, "strategy_id") or f"slot_{slot}",
                slot=int(slot),
                shard_id=int(shard_id),
                slot_in_shard=int(slot_in_shard),
                family=_text_from_row(row, "family"),
                concept=_text_from_row(row, "concept"),
                market_overlay=_text_from_row(row, "market_overlay", "market_overlay_id"),
                trend_filter=_text_from_row(row, "trend_filter", "trend_profile_id"),
                relative_strength_filter=_text_from_row(row, "relative_strength_filter", "rs_profile_id"),
                exit_rule=_text_from_row(row, "exit_rule", "exit_profile_id"),
                signal_hash=_text_from_row(row, "signal_hash"),
                exit_hash=_text_from_row(row, "exit_hash"),
                timeout_reason=_text_from_row(row, "reason", "reject_reason", "result_status"),
                previous_runtime_seconds=_text_from_row(
                    row,
                    "seconds_until_timeout",
                    "seconds_until_deferred",
                    "seconds_total",
                ),
            )
    return records


def inspect_artifact_dir(path: Path, *, run_id: int = 0) -> ArtifactInspection:
    path = Path(path)
    summary_path = path / "summary.json"
    summary: dict[str, Any] = {}
    if summary_path.exists() and summary_path.stat().st_size:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {}
    timeout_records = _recovery_records_from_csv(path / "timeout_strategies.csv")
    slow_deferred_records = _recovery_records_from_csv(path / "slow_deferred_strategies.csv")
    recoverable_records = {**slow_deferred_records, **timeout_records}
    return ArtifactInspection(
        run_id=int(run_id),
        timeout_slots=set(timeout_records),
        slow_deferred_slots=set(slow_deferred_records),
        runtime_error_slots=_slots_from_csv(path / "runtime_errors.csv"),
        unsupported_slots=_slots_from_csv(path / "unsupported_strategies.csv"),
        recoverable_records=recoverable_records,
        synthetic_missing_timeout_rows=int(summary.get("synthetic_missing_timeout_rows", 0) or 0),
        fill_missing_timeouts_enabled=bool(summary.get("fill_missing_timeouts_enabled", False)),
    )


def download_and_inspect_artifact(
    repo: str,
    run_id: int,
    artifact_root: Path,
    cache: dict[int, ArtifactInspection],
) -> ArtifactInspection:
    if run_id in cache:
        return cache[run_id]
    target = Path(artifact_root) / f"run-{run_id}"
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        run_cmd(
            [
                "gh",
                "run",
                "download",
                str(run_id),
                "--repo",
                repo,
                "--name",
                ARTIFACT_NAME,
                "--dir",
                str(target),
            ]
        )
    inspection = inspect_artifact_dir(target, run_id=run_id)
    cache[run_id] = inspection
    return inspection


def load_run_info(repo: str, run: dict[str, Any], artifact_cache: dict[int, bool]) -> RunInfo:
    run_id = int(run["databaseId"])
    jobs = run_jobs(repo, run_id)
    has_artifact = False
    status = str(run.get("status") or "")
    conclusion = run.get("conclusion")
    if status == "completed" and conclusion != "cancelled":
        if run_id not in artifact_cache:
            artifact_cache[run_id] = artifact_exists(repo, run_id)
        has_artifact = artifact_cache[run_id]
    return RunInfo(
        run_id=run_id,
        status=status,
        conclusion=conclusion,
        created_at=str(run.get("createdAt") or ""),
        updated_at=str(run.get("updatedAt") or ""),
        url=str(run.get("url") or ""),
        head_sha=str(run.get("headSha") or ""),
        blocks=parse_blocks(jobs),
        job_names={str(job.get("name") or "") for job in jobs},
        has_final_artifact=has_artifact,
    )


def load_runs_info(
    repo: str,
    raw_runs: list[dict[str, Any]],
    artifact_cache: dict[int, bool],
    run_info_cache: dict[int, RunInfo] | None = None,
    *,
    max_workers: int = 8,
) -> tuple[list[RunInfo], int]:
    infos: list[RunInfo] = []
    failures = 0
    run_info_cache = run_info_cache if run_info_cache is not None else {}
    to_load: list[dict[str, Any]] = []
    for raw in raw_runs:
        run_id = int(raw["databaseId"])
        cached = run_info_cache.get(run_id)
        raw_updated_at = str(raw.get("updatedAt") or "")
        if (
            cached is not None
            and cached.is_completed
            and cached.updated_at == raw_updated_at
            and (cached.has_final_artifact or cached.conclusion == "cancelled")
        ):
            infos.append(cached)
        else:
            to_load.append(raw)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(load_run_info, repo, raw, artifact_cache): int(raw["databaseId"])
            for raw in to_load
        }
        for future in as_completed(futures):
            run_id = futures[future]
            try:
                info = future.result()
                infos.append(info)
                if info.is_completed and (info.has_final_artifact or info.conclusion == "cancelled"):
                    run_info_cache[run_id] = info
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
    candidate_timeout_seconds: int = 300,
    job_wall_clock_seconds: int = 300,
    logical_jobs_per_block: int = 1,
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
        f"candidate_timeout_seconds={candidate_timeout_seconds}",
        "-f",
        f"job_wall_clock_seconds={job_wall_clock_seconds}",
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
        f"logical_jobs_per_block={logical_jobs_per_block}",
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


def write_recovery_manifest(
    *,
    manifest_dir: Path,
    slots: list[int],
    records: dict[int, StrategyRecoveryRecord],
    config: RecoveryRoundConfig,
) -> Path:
    manifest_dir = Path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"recovery_manifest_round_{config.recovery_round}.csv"
    rows: list[dict[str, Any]] = []
    subgroup_indices = range(max(config.subgroup_count, 1))
    symbol_bucket_indices = range(max(config.symbol_bucket_count, 1))
    for slot in slots:
        record = records.get(slot)
        if record is None:
            record = StrategyRecoveryRecord(
                strategy_id=f"slot_{slot}",
                slot=int(slot),
                shard_id=int(slot) // STRATEGIES_PER_SHARD,
                slot_in_shard=int(slot) % STRATEGIES_PER_SHARD,
                timeout_reason="missing_or_failed_logical_job",
            )
        partitions = subgroup_indices if config.partition_type == "signal_subgroup" else symbol_bucket_indices
        for partition_index in partitions:
            rows.append(
                {
                    "strategy_id": record.strategy_id,
                    "logical_job_id": int(slot),
                    "block_id": int(slot),
                    "concept": record.concept,
                    "family": record.family,
                    "signal_hash": record.signal_hash,
                    "exit_hash": record.exit_hash,
                    "timeout_reason": record.timeout_reason,
                    "previous_runtime_seconds": record.previous_runtime_seconds,
                    "recovery_round": int(config.recovery_round),
                    "partition_type": config.partition_type,
                    "subgroup_index": int(partition_index) if config.partition_type == "signal_subgroup" else 0,
                    "subgroup_count": int(config.subgroup_count),
                    "symbol_bucket_index": int(partition_index) if config.partition_type == "symbol_bucket" else 0,
                    "symbol_bucket_count": int(config.symbol_bucket_count),
                    "candidate_timeout_seconds": int(config.candidate_timeout_seconds),
                    "job_wall_clock_seconds": int(config.job_wall_clock_seconds),
                }
            )
    write_header = not manifest_path.exists()
    with manifest_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECOVERY_MANIFEST_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    return manifest_path


def dispatch_recovery_slots(
    *,
    repo: str,
    branch: str,
    slots: list[int],
    records: dict[int, StrategyRecoveryRecord],
    recovery_round_by_slot: dict[int, int],
    max_parallel_logical_jobs: int,
    active_count: int,
    manifest_dir: Path,
) -> list[int]:
    if not slots:
        return []
    slots_by_round: dict[int, list[int]] = {}
    for slot in sorted(dict.fromkeys(slots)):
        round_number = min(recovery_round_by_slot.get(slot, 0) + 1, 4)
        slots_by_round.setdefault(round_number, []).append(slot)
    round_number = min(slots_by_round)
    config = recovery_config_for_round(round_number)
    fanout = max(config.subgroup_count or config.symbol_bucket_count or 1, 1)
    available = max(max_parallel_logical_jobs - active_count, 0)
    if available <= 0:
        return []
    max_slots = max(available // fanout, 1)
    launch_slots = slots_by_round[round_number][:max_slots]
    if not launch_slots:
        return []
    write_recovery_manifest(manifest_dir=manifest_dir, slots=launch_slots, records=records, config=config)
    slots_csv = ",".join(str(slot) for slot in launch_slots)
    if config.partition_type == "signal_subgroup":
        for subgroup_index in range(max(config.subgroup_count, 1)):
            run_workflow(
                repo,
                branch,
                mode="optimized_evaluation_v5_event_first",
                candidate_count_per_job=1,
                candidate_timeout_seconds=config.candidate_timeout_seconds,
                job_wall_clock_seconds=config.job_wall_clock_seconds,
                logical_jobs_per_block=DEFAULT_RECOVERY_LOGICAL_JOBS_PER_BLOCK,
                job_start_index=subgroup_index,
                job_count=max(config.subgroup_count, 1),
                recovery_job_indices=slots_csv,
            )
    else:
        for symbol_bucket_index in range(max(config.symbol_bucket_count, 1)):
            run_workflow(
                repo,
                branch,
                mode="optimized_evaluation_v5_event_first_symbol_bucket",
                candidate_count_per_job=1,
                candidate_timeout_seconds=config.candidate_timeout_seconds,
                job_wall_clock_seconds=config.job_wall_clock_seconds,
                logical_jobs_per_block=DEFAULT_RECOVERY_LOGICAL_JOBS_PER_BLOCK,
                job_start_index=symbol_bucket_index,
                job_count=max(config.symbol_bucket_count, 1),
                recovery_job_indices=slots_csv,
            )
    for slot in launch_slots:
        recovery_round_by_slot[slot] = int(config.recovery_round)
    print(
        f"dispatch recovery round {config.recovery_round} partition={config.partition_type} "
        f"slots={len(launch_slots)} fanout={fanout}",
        flush=True,
    )
    return launch_slots


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


def cancel_duplicate_active_recoveries(repo: str, runs: list[RunInfo], excluded: set[int]) -> list[int]:
    by_slots: dict[tuple[int, ...], list[RunInfo]] = {}
    for run in runs:
        if run.run_id in excluded or run.is_full_wave_shape or not run.is_active:
            continue
        logicals = tuple(run.logicals)
        if not logicals:
            continue
        by_slots.setdefault(logicals, []).append(run)
    cancelled: list[int] = []
    for recovery_runs in by_slots.values():
        if len(recovery_runs) < 2:
            continue
        keep = sorted(recovery_runs, key=lambda item: item.created_at)[0]
        for duplicate in sorted(recovery_runs, key=lambda item: item.created_at)[1:]:
            print(f"cancel duplicate active recovery run {duplicate.run_id}; keeping {keep.run_id}")
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


def failed_recovery_slots(runs: list[RunInfo], excluded: set[int]) -> set[int]:
    failed: set[int] = set()
    for run in runs:
        if run.run_id in excluded or run.is_full_wave_shape or not run.is_completed:
            continue
        if run.conclusion != "failure" and run.has_final_artifact:
            continue
        for logical in run.logicals:
            if 0 <= logical < ORIGINAL_SHARDS * STRATEGIES_PER_SHARD:
                failed.add(logical)
    return failed


def active_logical_jobs(runs: list[RunInfo], excluded: set[int]) -> int:
    total = 0
    for run in runs:
        if run.run_id in excluded:
            continue
        if run.is_active:
            total += sum(1 for block in run.blocks if block.status != "completed")
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


def artifact_inspection_candidates(runs: list[RunInfo], excluded: set[int]) -> list[RunInfo]:
    return [
        run
        for run in runs
        if run.run_id not in excluded
        and run.is_completed
        and run.has_final_artifact
        and run.conclusion != "cancelled"
        and bool(run.blocks)
    ]


def preload_artifact_inspections(
    *,
    repo: str,
    runs: list[RunInfo],
    excluded: set[int],
    artifact_root: Path,
    artifact_inspection_cache: dict[int, ArtifactInspection],
    max_workers: int = 8,
) -> int:
    candidates = [
        run
        for run in artifact_inspection_candidates(runs, excluded)
        if run.run_id not in artifact_inspection_cache
    ]
    if not candidates:
        return 0
    print(
        f"preloading {len(candidates)} artifact inspections with {max_workers} workers",
        flush=True,
    )
    failures = 0
    with ThreadPoolExecutor(max_workers=max(max_workers, 1)) as pool:
        futures = {
            pool.submit(
                download_and_inspect_artifact,
                repo,
                run.run_id,
                artifact_root,
                artifact_inspection_cache,
            ): run.run_id
            for run in candidates
        }
        for future in as_completed(futures):
            run_id = futures[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - transient artifact failures are retried next pass
                failures += 1
                print(f"warning: could not preload artifact {run_id}: {exc}", flush=True)
    return failures


def dispatch_next_actions(
    *,
    repo: str,
    branch: str,
    runs: list[RunInfo],
    excluded: set[int],
    max_parallel_logical_jobs: int,
    max_new_waves: int,
    pending_recovery_slots: set[int],
    pending_waves: set[int],
    artifact_root: Path,
    artifact_inspection_cache: dict[int, ArtifactInspection],
    recovery_round_by_slot: dict[int, int],
    recovery_manifest_dir: Path,
    artifact_workers: int = 8,
) -> bool:
    changed = False
    cancel_duplicate_active_waves(repo, runs, excluded)
    # Intentional subgroup recoveries share the same logical slots, so the old
    # duplicate-canceller would kill valid round fanout.
    chosen_waves = choose_wave_runs(runs, excluded)
    active_count = active_logical_jobs(runs, excluded)

    launched = 0
    for wave in range(TOTAL_WAVES):
        if wave in chosen_waves or wave in pending_waves:
            continue
        if active_count + WAVE_LOGICAL_JOBS > max_parallel_logical_jobs:
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
        pending_waves.add(wave)
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

    completed_recovery_slots = recovery_slots_covered(runs, excluded, completed_only=True)
    retry_failed_recovery_slots = failed_recovery_slots(runs, excluded)
    if retry_failed_recovery_slots:
        print(
            f"retrying {len(retry_failed_recovery_slots)} slots from failed recovery runs",
            flush=True,
        )
    pending_recovery_slots.difference_update(completed_recovery_slots)
    pending_recovery_slots.difference_update(retry_failed_recovery_slots)
    recovery_covered = recovery_slots_covered(runs, excluded)
    recovery_covered |= pending_recovery_slots
    recovery_covered.difference_update(retry_failed_recovery_slots)
    recovery_completed = recovery_slots_covered(runs, excluded, completed_only=True)
    recovery_completed.difference_update(retry_failed_recovery_slots)
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
            unique_missing_slots = sorted(set(missing_slots))
            launched_slots = dispatch_recovery_slots(
                repo=repo,
                branch=branch,
                slots=unique_missing_slots,
                records={},
                recovery_round_by_slot=recovery_round_by_slot,
                max_parallel_logical_jobs=max_parallel_logical_jobs,
                active_count=active_count,
                manifest_dir=recovery_manifest_dir,
            )
            if not launched_slots:
                print(f"waiting: failed logical jobs need recovery but capacity is full: wave={wave}")
                return False
            pending_recovery_slots.update(launched_slots)
            return True

    # Base wave artifacts are the only artifacts needed to discover original
    # timeout slots. Completed recovery artifacts are intentionally not scanned
    # here: there can be hundreds of subgroup artifacts, and the strict final
    # merge validates that they removed every timeout before accepting output.
    base_wave_runs = list(chosen_waves.values())
    preload_failures = preload_artifact_inspections(
        repo=repo,
        runs=base_wave_runs,
        excluded=excluded,
        artifact_root=artifact_root,
        artifact_inspection_cache=artifact_inspection_cache,
        max_workers=artifact_workers,
    )
    if preload_failures:
        print(f"warning: {preload_failures} artifact inspections failed during preload", flush=True)

    recoverable_timeout_slots: set[int] = set()
    recoverable_records: dict[int, StrategyRecoveryRecord] = {}
    for run in sorted(base_wave_runs, key=lambda item: item.created_at):
        if (
            run.run_id in excluded
            or not run.is_completed
            or not run.has_final_artifact
            or run.conclusion == "cancelled"
            or not run.blocks
        ):
            continue
        if not run.is_full_wave_shape and not run.logicals:
            continue
        try:
            inspection = download_and_inspect_artifact(repo, run.run_id, artifact_root, artifact_inspection_cache)
        except Exception as exc:  # noqa: BLE001 - leave the run for a later orchestrator pass
            print(f"warning: could not inspect artifact {run.run_id}: {exc}", flush=True)
            continue
        if inspection.synthetic_missing_timeout_rows or inspection.fill_missing_timeouts_enabled:
            print(
                f"run {run.run_id} has synthetic/fill-missing rows; strict merge will not use it "
                f"(synthetic={inspection.synthetic_missing_timeout_rows}, fill={inspection.fill_missing_timeouts_enabled})",
                flush=True,
            )
        recoverable_timeout_slots.update(inspection.recoverable_slots)
        recoverable_records.update(inspection.recoverable_records)
    pending_timeout_slots = sorted(slot for slot in recoverable_timeout_slots if slot not in recovery_covered)
    if pending_timeout_slots:
        launched_slots = dispatch_recovery_slots(
            repo=repo,
            branch=branch,
            slots=pending_timeout_slots,
            records=recoverable_records,
            recovery_round_by_slot=recovery_round_by_slot,
            max_parallel_logical_jobs=max_parallel_logical_jobs,
            active_count=active_count,
            manifest_dir=recovery_manifest_dir,
        )
        if not launched_slots:
            print(f"waiting: {len(pending_timeout_slots)} timeout slots need recovery but capacity is full")
            return False
        pending_recovery_slots.update(launched_slots)
        return True

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
    parser.add_argument("--recovery-timeout-seconds", type=int, default=DEFAULT_RECOVERY_TIMEOUT_SECONDS)
    parser.add_argument("--recovery-wall-clock-seconds", type=int, default=DEFAULT_RECOVERY_WALL_CLOCK_SECONDS)
    parser.add_argument("--artifact-inspection-root", type=Path, default=Path(".gtbi-orchestrator-artifacts"))
    parser.add_argument("--recovery-manifest-dir", type=Path, default=Path("recovery-manifests"))
    parser.add_argument("--validated-sha", default=os.environ.get("GITHUB_SHA", VALIDATED_SHA))
    parser.add_argument(
        "--exclude-run-ids",
        default=(
            "28666430744,28701453837,28701456697,28716016695,28717957514,"
            "28718300497,28730731060,28730858683,28730950197"
        ),
    )
    parser.add_argument("--self-dispatch", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_validated_shas(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def main() -> int:
    args = parse_args()
    validated_sha = str(args.validated_sha or os.environ.get("GITHUB_SHA") or VALIDATED_SHA)
    validated_shas = parse_validated_shas(validated_sha)
    excluded = {
        int(item.strip())
        for item in str(args.exclude_run_ids).split(",")
        if item.strip()
    }
    deadline = time.monotonic() + max(args.loop_minutes, 1) * 60
    artifact_cache: dict[int, bool] = {}
    run_info_cache: dict[int, RunInfo] = {}
    artifact_inspection_cache: dict[int, ArtifactInspection] = {}
    recovery_round_by_slot: dict[int, int] = {}
    pending_recovery_slots: set[int] = set()
    pending_waves: set[int] = set()
    current_run_id = int(os.environ.get("GITHUB_RUN_ID", "0") or 0)

    while True:
        print(f"orchestrator pass at {datetime.now(timezone.utc).isoformat()}")
        min_created_at = parse_utc(args.min_run_created_at)
        raw_runs = list_runs(
            args.repo,
            args.workflow,
            args.branch,
            args.run_list_limit,
            args.min_run_created_at,
        )
        raw_runs = [
            raw
            for raw in raw_runs
            if parse_utc(str(raw.get("createdAt") or "1970-01-01T00:00:00Z")) >= min_created_at
        ]
        if validated_shas:
            raw_runs = [
                raw
                for raw in raw_runs
                if str(raw.get("headSha") or "") in validated_shas
            ]
        if current_run_id:
            raw_runs = [
                raw
                for raw in raw_runs
                if int(raw.get("databaseId") or 0) != current_run_id
            ]
        print(f"candidate runs after filters: {len(raw_runs)}", flush=True)
        runs, load_failures = load_runs_info(
            args.repo,
            raw_runs,
            artifact_cache,
            run_info_cache,
            max_workers=max(args.inspect_workers, 1),
        )
        print(f"inspected runs: {len(runs)}", flush=True)
        if load_failures:
            print(f"warning: skipped {load_failures} runs due to inspect errors", flush=True)
        if validated_shas:
            runs = [run for run in runs if run.head_sha in validated_shas]
        changed = dispatch_next_actions(
            repo=args.repo,
            branch=args.branch,
            runs=runs,
            excluded=excluded,
            max_parallel_logical_jobs=args.max_parallel_logical_jobs,
            max_new_waves=args.max_new_waves_per_pass,
            pending_recovery_slots=pending_recovery_slots,
            pending_waves=pending_waves,
            artifact_root=args.artifact_inspection_root,
            artifact_inspection_cache=artifact_inspection_cache,
            recovery_round_by_slot=recovery_round_by_slot,
            recovery_manifest_dir=args.recovery_manifest_dir,
            artifact_workers=max(args.inspect_workers, 1),
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
        time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    sys.exit(main())
