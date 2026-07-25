"""Read-only GitHub Actions timing collection with bounded serialization."""

from __future__ import annotations

import json
import math
import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import pyarrow as pa


GITHUB_API_VERSION = "2022-11-28"
EXCLUDED_TIMELINE_JOBS = frozenset(
    {
        "Collect GitHub timeline",
        "Publish final artifact",
    }
)
JOBS_SCHEMA = pa.schema(
    [
        pa.field("job_id", pa.int64(), nullable=False),
        pa.field("run_id", pa.int64(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("conclusion", pa.string()),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("started_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("completed_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("queue_seconds", pa.float64(), nullable=False),
        pa.field("duration_seconds", pa.float64(), nullable=False),
        pa.field("runner_name", pa.string(), nullable=False),
        pa.field("labels_json", pa.string(), nullable=False),
        pa.field("runner_bootstrap_proxy_seconds", pa.float64()),
    ]
)
PARALLELISM_SCHEMA = pa.schema(
    [
        pa.field(
            "interval_start",
            pa.timestamp("us", tz="UTC"),
            nullable=False,
        ),
        pa.field(
            "interval_end",
            pa.timestamp("us", tz="UTC"),
            nullable=False,
        ),
        pa.field("interval_seconds", pa.float64(), nullable=False),
        pa.field("observed_parallelism", pa.int32(), nullable=False),
        pa.field("jobs_started", pa.int32(), nullable=False),
        pa.field("jobs_completed", pa.int32(), nullable=False),
        pa.field("queue_seconds", pa.float64(), nullable=False),
    ]
)
RUNTIME_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.int64(), nullable=False),
        pa.field("job_id", pa.int64(), nullable=False),
        pa.field("job_name", pa.string(), nullable=False),
        pa.field("phase", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("conclusion", pa.string()),
        pa.field("started_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("completed_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("duration_seconds", pa.float64(), nullable=False),
    ]
)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _seconds(started: datetime, completed: datetime) -> float:
    return max(0.0, (completed - started).total_seconds())


def _safe_step(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": str(raw.get("name") or "")[:200],
        "number": int(raw.get("number") or 0),
        "status": str(raw.get("status") or ""),
        "conclusion": (
            str(raw["conclusion"])
            if raw.get("conclusion") is not None
            else None
        ),
        "started_at": raw.get("started_at"),
        "completed_at": raw.get("completed_at"),
    }


def _safe_job(raw: Mapping[str, Any]) -> dict[str, Any]:
    labels = raw.get("labels")
    if not isinstance(labels, list):
        labels = []
    steps = raw.get("steps")
    if not isinstance(steps, list):
        steps = []
    return {
        "id": int(raw["id"]),
        "run_id": int(raw.get("run_id") or 0),
        "name": str(raw.get("name") or "")[:300],
        "status": str(raw.get("status") or ""),
        "conclusion": (
            str(raw["conclusion"])
            if raw.get("conclusion") is not None
            else None
        ),
        "created_at": raw.get("created_at"),
        "started_at": raw.get("started_at"),
        "completed_at": raw.get("completed_at"),
        "runner_name": str(raw.get("runner_name") or "")[:200],
        "labels": [str(value)[:100] for value in labels[:20]],
        "steps": [
            _safe_step(step)
            for step in steps[:100]
            if isinstance(step, Mapping)
        ],
    }


def _next_link(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', part)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


def fetch_run_jobs(
    api_url: str,
    repository: str,
    run_id: int | str,
    token: str,
    opener: Callable[[Request], Any] = urlopen,
) -> tuple[Mapping[str, Any], ...]:
    """Fetch every job page and retain only explicitly safe fields."""

    if not token:
        raise ValueError("GitHub token is required")
    safe_repository = quote(repository.strip("/"), safe="/")
    next_url: str | None = (
        f"{api_url.rstrip('/')}/repos/{safe_repository}/actions/runs/"
        f"{int(run_id)}/jobs?per_page=100"
    )
    seen_urls: set[str] = set()
    jobs: list[Mapping[str, Any]] = []
    while next_url is not None:
        if next_url in seen_urls:
            raise RuntimeError("GitHub jobs pagination loop detected")
        if len(seen_urls) >= 1_000:
            raise RuntimeError("GitHub jobs pagination exceeded safety limit")
        seen_urls.add(next_url)
        request = Request(
            next_url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "User-Agent": "aurora-github-performance",
            },
        )
        with opener(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
            raw_jobs = payload.get("jobs", [])
            if not isinstance(raw_jobs, list):
                raise ValueError("GitHub jobs response has no jobs list")
            jobs.extend(
                _safe_job(job)
                for job in raw_jobs
                if isinstance(job, Mapping)
            )
            next_url = _next_link(response.headers.get("Link"))
    return tuple(sorted(jobs, key=lambda job: int(job["id"])))


def _completed_jobs(
    jobs: Sequence[Mapping[str, Any]],
) -> tuple[tuple[Mapping[str, Any], datetime, datetime, datetime], ...]:
    completed = []
    for job in jobs:
        name = str(job.get("name") or "")
        if any(
            name == excluded or name.endswith(f" / {excluded}")
            for excluded in EXCLUDED_TIMELINE_JOBS
        ):
            continue
        created = _timestamp(job.get("created_at"))
        started = _timestamp(job.get("started_at"))
        finished = _timestamp(job.get("completed_at"))
        if created is None or started is None or finished is None:
            continue
        completed.append((job, created, started, finished))
    return tuple(
        sorted(
            completed,
            key=lambda item: (item[2], int(item[0]["id"])),
        )
    )


def scope_jobs_to_current_invocation(
    jobs: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Keep only the reusable-workflow call owning the active collector."""

    marker = "Collect GitHub timeline"
    collectors = [
        job
        for job in jobs
        if (
            str(job.get("name") or "") == marker
            or str(job.get("name") or "").endswith(f" / {marker}")
        )
        and str(job.get("status") or "") == "in_progress"
    ]
    if not collectors:
        return tuple(jobs)
    collector = max(
        collectors,
        key=lambda job: (
            str(job.get("started_at") or ""),
            int(job.get("id") or 0),
        ),
    )
    name = str(collector.get("name") or "")
    suffix = f" / {marker}"
    if not name.endswith(suffix):
        return tuple(jobs)
    prefix = name[: -len(suffix)]
    scoped_prefix = f"{prefix} / "
    return tuple(
        job
        for job in jobs
        if str(job.get("name") or "").startswith(scoped_prefix)
    )


def _bootstrap_proxy(
    job: Mapping[str, Any],
    started: datetime,
) -> float | None:
    steps = job.get("steps")
    if not isinstance(steps, list):
        return None
    candidates = []
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        name = str(step.get("name") or "").lower()
        if "aurora runtime" not in name:
            continue
        timestamp = _timestamp(step.get("started_at"))
        if timestamp is not None:
            candidates.append(timestamp)
    if not candidates:
        return None
    return _seconds(started, min(candidates))


def build_jobs_timeline(
    jobs: Sequence[Mapping[str, Any]],
) -> pa.Table:
    """Build one bounded row per completed job."""

    rows = []
    for job, created, started, completed in _completed_jobs(jobs):
        labels = job.get("labels")
        if not isinstance(labels, list):
            labels = []
        rows.append(
            {
                "job_id": int(job["id"]),
                "run_id": int(job.get("run_id") or 0),
                "name": str(job.get("name") or ""),
                "status": str(job.get("status") or ""),
                "conclusion": job.get("conclusion"),
                "created_at": created,
                "started_at": started,
                "completed_at": completed,
                "queue_seconds": _seconds(created, started),
                "duration_seconds": _seconds(started, completed),
                "runner_name": str(job.get("runner_name") or ""),
                "labels_json": json.dumps(
                    labels,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "runner_bootstrap_proxy_seconds": _bootstrap_proxy(
                    job,
                    started,
                ),
            }
        )
    return pa.Table.from_pylist(rows, schema=JOBS_SCHEMA)


def build_parallelism_timeline(
    jobs: Sequence[Mapping[str, Any]],
) -> pa.Table:
    """Sweep actual job intervals into deterministic concurrency segments."""

    completed = _completed_jobs(jobs)
    boundaries = sorted(
        {
            boundary
            for _, _, started, finished in completed
            for boundary in (started, finished)
        }
    )
    rows = []
    for interval_start, interval_end in zip(
        boundaries,
        boundaries[1:],
        strict=False,
    ):
        if interval_end <= interval_start:
            continue
        active = [
            item
            for item in completed
            if item[2] <= interval_start < item[3]
        ]
        if not active:
            continue
        started_here = [
            item for item in completed if item[2] == interval_start
        ]
        completed_here = [
            item for item in completed if item[3] == interval_start
        ]
        rows.append(
            {
                "interval_start": interval_start,
                "interval_end": interval_end,
                "interval_seconds": _seconds(
                    interval_start,
                    interval_end,
                ),
                "observed_parallelism": len(active),
                "jobs_started": len(started_here),
                "jobs_completed": len(completed_here),
                "queue_seconds": sum(
                    _seconds(created, started)
                    for _, created, started, _ in started_here
                ),
            }
        )
    return pa.Table.from_pylist(rows, schema=PARALLELISM_SCHEMA)


def _phase_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized[:100] or "unnamed"


def _is_fanout_or_retry_job(name: str) -> bool:
    leaf = name.rsplit(" / ", 1)[-1]
    return leaf.startswith(("fanout_a", "fanout_b", "retry_a", "retry_b"))


def build_runtime_breakdown(
    jobs: Sequence[Mapping[str, Any]],
) -> pa.Table:
    """Build measured step durations, without logs or arbitrary payloads."""

    rows = []
    for job, _, _, _ in _completed_jobs(jobs):
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            name = str(step.get("name") or "")
            if name in {"Set up job", "Complete job"}:
                continue
            started = _timestamp(step.get("started_at"))
            completed = _timestamp(step.get("completed_at"))
            if started is None or completed is None:
                continue
            rows.append(
                {
                    "run_id": int(job.get("run_id") or 0),
                    "job_id": int(job["id"]),
                    "job_name": str(job.get("name") or ""),
                    "phase": _phase_name(name),
                    "status": str(step.get("status") or ""),
                    "conclusion": step.get("conclusion"),
                    "started_at": started,
                    "completed_at": completed,
                    "duration_seconds": _seconds(started, completed),
                }
            )
    rows.sort(
        key=lambda row: (
            row["started_at"],
            row["job_id"],
            row["phase"],
        )
    )
    return pa.Table.from_pylist(rows, schema=RUNTIME_SCHEMA)


def _step_category(name: str, job_name: str) -> str:
    step = name.lower()
    job = job_name.lower()
    if "execute_retry" in step:
        return "retry"
    if (
        "download" in step
        or "upload" in step
        or "publish" in step
        or "salvage" in step
    ):
        return "transfer"
    if "build_canonical_aurora_runtime" in step:
        return "canonical_setup"
    if "restore_aurora_runtime" in step:
        return "restore_setup"
    if (
        "checkout" in step
        or "runtime" in step
        or "setup" in step
        or "install" in step
    ):
        return "setup"
    if "merge" in step or "verify" in step or "reconcil" in step:
        return "merge"
    if (
        "execute_shard" in step
        or "prepare_immutable_data" in step
        or "measure_real_pilot" in step
        or "run_bounded_smoke" in step
    ):
        return "compute"
    if "retry" in job and "execute" in step:
        return "retry"
    return "other"


def summarize_timeline(
    jobs: Sequence[Mapping[str, Any]],
    requested_parallelism: int,
) -> Mapping[str, Any]:
    """Summarize measured GitHub timing without claiming API provisioning."""

    completed = _completed_jobs(jobs)
    job_table = build_jobs_timeline(jobs)
    parallel = build_parallelism_timeline(jobs)
    runtime = build_runtime_breakdown(jobs)
    job_rows = job_table.to_pylist()
    runtime_rows = runtime.to_pylist()
    category_seconds = {
        category: 0.0
        for category in (
            "setup",
            "canonical_setup",
            "restore_setup",
            "transfer",
            "compute",
            "retry",
            "merge",
            "other",
        )
    }
    for row in runtime_rows:
        category = _step_category(row["phase"], row["job_name"])
        category_seconds[category] += float(row["duration_seconds"])
    if completed:
        workflow_start = min(item[1] for item in completed)
        execution_start = min(item[2] for item in completed)
        completed_at = max(item[3] for item in completed)
        workflow_wall = _seconds(workflow_start, completed_at)
        execution_wall = _seconds(execution_start, completed_at)
    else:
        workflow_wall = 0.0
        execution_wall = 0.0
    fanout_durations = [
        float(row["duration_seconds"])
        for row in job_rows
        if _is_fanout_or_retry_job(str(row["name"]))
    ]
    if not fanout_durations:
        fanout_durations = [
            float(row["duration_seconds"]) for row in job_rows
        ]
    median_duration = (
        statistics.median(fanout_durations)
        if fanout_durations
        else 0.0
    )
    straggler_ratio = (
        max(fanout_durations) / median_duration
        if median_duration > 0
        else 0.0
    )
    peak = (
        max(parallel.column("observed_parallelism").to_pylist())
        if parallel.num_rows
        else 0
    )
    parallel_rows = parallel.to_pylist()
    parallel_seconds = sum(
        float(row["interval_seconds"]) for row in parallel_rows
    )
    average_parallelism = (
        sum(
            int(row["observed_parallelism"])
            * float(row["interval_seconds"])
            for row in parallel_rows
        )
        / parallel_seconds
        if parallel_seconds > 0
        else 0.0
    )
    setup_seconds = (
        category_seconds["setup"]
        + category_seconds["canonical_setup"]
        + category_seconds["restore_setup"]
    )
    return {
        "schema_version": "1",
        "complete": bool(job_rows),
        "requested_parallelism": int(requested_parallelism),
        "observed_peak_parallelism": int(peak),
        "observed_average_parallelism": average_parallelism,
        "workflow_wall_seconds": workflow_wall,
        "execution_wall_seconds": execution_wall,
        "estimated_billable_minutes": sum(
            math.ceil(float(row["duration_seconds"]) / 60.0)
            for row in job_rows
        ),
        "billable_minutes_source": "ceil_completed_job_durations",
        "queue_seconds_total": sum(
            float(row["queue_seconds"]) for row in job_rows
        ),
        "setup_seconds_total": setup_seconds,
        "canonical_setup_seconds_total": (
            category_seconds["canonical_setup"]
        ),
        "restore_setup_seconds_total": category_seconds["restore_setup"],
        "transfer_seconds_total": category_seconds["transfer"],
        "compute_seconds_total": category_seconds["compute"],
        "retry_seconds_total": category_seconds["retry"],
        "merge_seconds_total": category_seconds["merge"],
        "other_seconds_total": category_seconds["other"],
        "job_seconds_total": sum(
            float(row["duration_seconds"]) for row in job_rows
        ),
        "straggler_ratio": straggler_ratio,
        "runner_bootstrap_measurement": (
            "proxy_from_job_start_to_first_aurora_runtime_step"
        ),
        "excluded_jobs": sorted(EXCLUDED_TIMELINE_JOBS),
    }
