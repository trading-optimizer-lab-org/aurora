from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.summarize_sp500_atlas_pilot import summarize_worker_intervals
from scripts.summarize_sp500_atlas_pilot import main


def test_pilot_effective_concurrency_uses_worker_seconds_over_wall_seconds() -> None:
    intervals = [
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc), 10.0),
        (datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, 0, 12, tzinfo=timezone.utc), 10.0),
    ]
    summary = summarize_worker_intervals(intervals)
    assert summary["worker_seconds"] == 20.0
    assert summary["wall_seconds"] == 12.0
    assert summary["effective_concurrency"] == 20.0 / 12.0


def test_pilot_cli_maps_argument_names_to_summary_api(monkeypatch) -> None:
    captured = {}

    def fake_summary(**kwargs):
        captured.update(kwargs)
        return {"accepted": True}

    monkeypatch.setattr("scripts.summarize_sp500_atlas_pilot.summarize_pilot", fake_summary)
    monkeypatch.setattr(
        "sys.argv",
        [
            "summarize_sp500_atlas_pilot.py",
            "--plan", "plan.json",
            "--pilot-manifest", "pilot.json",
            "--partitions-root", "parts",
            "--fault-receipt", "fault.json",
            "--output", "out.json",
        ],
    )
    assert main() == 0
    assert captured == {
        "plan_path": Path("plan.json"),
        "pilot_manifest_path": Path("pilot.json"),
        "partitions_root": Path("parts"),
        "fault_receipt_path": Path("fault.json"),
        "output_path": Path("out.json"),
    }
