from __future__ import annotations

from datetime import datetime, timezone

from scripts.summarize_sp500_atlas_pilot import summarize_worker_intervals


def test_pilot_effective_concurrency_uses_worker_seconds_over_wall_seconds() -> None:
    intervals = [
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc), 10.0),
        (datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, 0, 12, tzinfo=timezone.utc), 10.0),
    ]
    summary = summarize_worker_intervals(intervals)
    assert summary["worker_seconds"] == 20.0
    assert summary["wall_seconds"] == 12.0
    assert summary["effective_concurrency"] == 20.0 / 12.0
