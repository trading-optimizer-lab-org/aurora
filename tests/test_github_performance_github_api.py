from __future__ import annotations

import json
from datetime import datetime, timezone
from email.message import Message
from typing import Any

from aurora.infra.github_performance.github_api import (
    build_jobs_timeline,
    build_parallelism_timeline,
    build_runtime_breakdown,
    fetch_run_jobs,
    scope_jobs_to_current_invocation,
    summarize_timeline,
)


def _job(
    job_id: int,
    name: str,
    created: str,
    started: str,
    completed: str,
) -> dict[str, Any]:
    return {
        "id": job_id,
        "run_id": 77,
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "created_at": created,
        "started_at": started,
        "completed_at": completed,
        "runner_name": f"GitHub Actions {job_id}",
        "labels": ["ubuntu-24.04"],
        "actor": {"email": "must-not-survive@example.com"},
        "steps": [
            {
                "name": "Set up job",
                "number": 1,
                "status": "completed",
                "conclusion": "success",
                "started_at": started,
                "completed_at": started,
            },
            {
                "name": "Restore Aurora runtime",
                "number": 2,
                "status": "completed",
                "conclusion": "success",
                "started_at": started,
                "completed_at": completed,
            },
        ],
    }


class _Response:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        link: str | None = None,
    ) -> None:
        self._payload = json.dumps(payload).encode("utf-8")
        self.headers = Message()
        if link:
            self.headers["Link"] = link

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_fetch_run_jobs_paginates_and_never_serializes_token() -> None:
    first = [
        _job(
            index,
            f"job-{index}",
            "2026-07-25T00:00:00Z",
            "2026-07-25T00:00:10Z",
            "2026-07-25T00:00:40Z",
        )
        for index in range(100)
    ]
    second = [
        _job(
            index,
            f"job-{index}",
            "2026-07-25T00:00:00Z",
            "2026-07-25T00:00:10Z",
            "2026-07-25T00:00:40Z",
        )
        for index in range(100, 103)
    ]
    requests = []

    def opener(request):
        requests.append(request)
        if len(requests) == 1:
            return _Response(
                {"total_count": 103, "jobs": first},
                link=(
                    '<https://api.github.test/repos/o/r/actions/runs/'
                    '77/jobs?per_page=100&page=2>; rel="next"'
                ),
            )
        return _Response({"total_count": 103, "jobs": second})

    jobs = fetch_run_jobs(
        "https://api.github.test",
        "o/r",
        77,
        "secret-token",
        opener,
    )
    assert len(jobs) == 103
    assert requests[0].get_header("Authorization") == "Bearer secret-token"
    encoded = json.dumps(jobs, sort_keys=True)
    assert "secret-token" not in encoded
    assert "must-not-survive@example.com" not in encoded


def test_timeline_uses_real_job_intervals() -> None:
    jobs = [
        _job(
            1,
            "a",
            "2026-07-25T00:00:00Z",
            "2026-07-25T00:00:10Z",
            "2026-07-25T00:00:40Z",
        ),
        _job(
            2,
            "b",
            "2026-07-25T00:00:05Z",
            "2026-07-25T00:00:20Z",
            "2026-07-25T00:00:30Z",
        ),
    ]
    table = build_parallelism_timeline(jobs)
    assert table.column("observed_parallelism").to_pylist() == [1, 2, 1]
    assert table.column("queue_seconds").to_pylist()[0] == 10.0
    assert table.column("interval_seconds").to_pylist() == [
        10.0,
        10.0,
        10.0,
    ]


def test_job_and_step_tables_are_bounded_and_explicit() -> None:
    jobs = [
        _job(
            1,
            "fanout_a (s001)",
            "2026-07-25T00:00:00Z",
            "2026-07-25T00:00:10Z",
            "2026-07-25T00:00:40Z",
        )
    ]
    job_table = build_jobs_timeline(jobs)
    assert "actor" not in job_table.schema.names
    assert "runner_bootstrap_proxy_seconds" in job_table.schema.names
    assert job_table.column(
        "runner_bootstrap_proxy_seconds"
    ).to_pylist() == [0.0]
    runtime = build_runtime_breakdown(jobs)
    assert runtime.column("phase").to_pylist() == [
        "restore_aurora_runtime"
    ]
    assert runtime.column("duration_seconds").to_pylist() == [30.0]
    assert runtime.column("started_at").to_pylist()[0] == datetime(
        2026,
        7,
        25,
        0,
        0,
        10,
        tzinfo=timezone.utc,
    )


def test_reusable_invocations_do_not_contaminate_each_other() -> None:
    optimized = _job(
        1,
        "optimized / fanout_a (s001)",
        "2026-07-25T00:00:00Z",
        "2026-07-25T00:00:10Z",
        "2026-07-25T00:00:40Z",
    )
    baseline = _job(
        2,
        "baseline / fanout_a (s001)",
        "2026-07-25T00:01:00Z",
        "2026-07-25T00:01:10Z",
        "2026-07-25T00:01:40Z",
    )
    collector = _job(
        3,
        "baseline / Collect GitHub timeline",
        "2026-07-25T00:01:40Z",
        "2026-07-25T00:01:41Z",
        "2026-07-25T00:01:42Z",
    )
    collector["status"] = "in_progress"
    collector["completed_at"] = None
    scoped = scope_jobs_to_current_invocation(
        [optimized, baseline, collector]
    )
    assert {job["id"] for job in scoped} == {2, 3}


def test_reusable_prefix_still_selects_only_fanout_for_stragglers() -> None:
    jobs = [
        _job(
            1,
            "optimized / validate",
            "2026-07-25T00:00:00Z",
            "2026-07-25T00:00:00Z",
            "2026-07-25T00:10:00Z",
        ),
        _job(
            2,
            "optimized / fanout_a (s001)",
            "2026-07-25T00:10:00Z",
            "2026-07-25T00:10:00Z",
            "2026-07-25T00:11:00Z",
        ),
        _job(
            3,
            "optimized / fanout_a (s002)",
            "2026-07-25T00:10:00Z",
            "2026-07-25T00:10:00Z",
            "2026-07-25T00:12:00Z",
        ),
    ]
    summary = summarize_timeline(jobs, 360)
    assert summary["straggler_ratio"] == 2.0
    assert summary["observed_peak_parallelism"] == 2
    assert summary["observed_average_parallelism"] > 0
    assert summary["restore_setup_seconds_total"] == 780.0
