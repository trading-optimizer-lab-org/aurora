from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.check_mypy_baseline import (
    baseline_payload,
    compare_errors,
    load_baseline,
    parse_mypy_errors,
)


def test_parse_mypy_errors_ignores_line_numbers() -> None:
    output = "\n".join(
        [
            "core/example.py:10: error: Bad value  [assignment]",
            "core/example.py:99: error: Bad value  [assignment]",
            "Found 2 errors in 1 file",
        ]
    )

    assert parse_mypy_errors(output) == Counter(
        {("core/example.py", "assignment", "Bad value"): 2}
    )


def test_compare_mypy_errors_rejects_only_new_fingerprints() -> None:
    allowed = Counter({("old.py", "arg-type", "Old debt"): 2})
    current = Counter(
        {
            ("old.py", "arg-type", "Old debt"): 1,
            ("new.py", "assignment", "New regression"): 1,
        }
    )

    new_errors, resolved_errors = compare_errors(current, allowed)

    assert new_errors == Counter(
        {("new.py", "assignment", "New regression"): 1}
    )
    assert resolved_errors == Counter(
        {("old.py", "arg-type", "Old debt"): 1}
    )


def test_baseline_round_trip_and_duplicate_rejection(tmp_path: Path) -> None:
    errors = Counter({("old.py", "arg-type", "Old debt"): 2})
    payload = baseline_payload(
        errors,
        run_id=123,
        commit_sha="a" * 40,
    )
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    loaded_payload, loaded_errors = load_baseline(path)
    assert loaded_payload["source"]["error_count"] == 2
    assert loaded_errors == errors

    payload["errors"].append(dict(payload["errors"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_baseline(path)
