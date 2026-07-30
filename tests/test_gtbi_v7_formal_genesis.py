from __future__ import annotations

import csv
import json
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.gtbi_v7_readiness.formal_genesis import (
    ATTEMPT_ID,
    TASK_ID,
    validate_formal_genesis_records,
)
from infra.gtbi_v7_readiness.genesis import build_initial_records

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"


def _csv_rows(name: str) -> list[dict[str, str]]:
    with (READINESS / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _jsonl_rows(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (READINESS / name).read_text(
            encoding="utf-8"
        ).splitlines()
        if line
    ]


def test_formal_genesis_projection_is_exact_and_only_completes_prev7_0000() -> None:
    result = validate_formal_genesis_records(ROOT)
    assert result == {
        "formal_genesis_complete": True,
        "completed_task_ids": [TASK_ID],
        "merge_sha": "177b9d3f4ed4f784c8b682e50d7ccca5bf79ba16",
        "task_event_rows": 114,
        "task_attempt_rows": 4,
    }
    statuses = _csv_rows("task_status.csv")
    current = next(row for row in statuses if row["id"] == TASK_ID)
    assert current["status"] == "done"
    assert current["current_attempt_id"] == ATTEMPT_ID
    assert current["planning_state"] == "complete"
    assert {
        row["status"] for row in statuses if row["id"] != TASK_ID
    } == {"blocked"}


def test_formal_genesis_preserves_initial_task_event_bytes_as_prefix() -> None:
    initial = build_initial_records(ROOT)["task_events.jsonl"]
    expected_prefix = b"".join(canonical_bytes(row) + b"\n" for row in initial)
    assert (READINESS / "task_events.jsonl").read_bytes().startswith(
        expected_prefix
    )


def test_formal_genesis_attempt_reaches_succeeded_without_rewriting_history() -> None:
    attempts = _jsonl_rows("task_attempts.jsonl")
    assert [row["attempt_status"] for row in attempts] == [
        "created",
        "in_progress",
        "review",
        "succeeded",
    ]
    assert all(row["task_attempt_id"] == ATTEMPT_ID for row in attempts)
    assert attempts[-1]["terminal_reason_or_null"] == (
        "pr1_merged_with_all_checks_success"
    )


def test_formal_genesis_does_not_green_any_gate() -> None:
    assert {row["status"] for row in _csv_rows("gate_status.csv")} == {"red"}
