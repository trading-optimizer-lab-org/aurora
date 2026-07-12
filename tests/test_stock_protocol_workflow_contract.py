"""Static contract checks for the GitHub-only protocol workflow."""
from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "stock-protocol-36-tests-360jobs.yml"


def test_workflow_has_two_180_matrices_and_locked_boundary():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("max-parallel: 180") >= 8
    assert "matrix_a" in text
    assert "matrix_b" in text
    assert "2021-01-01" in text
    assert "2020-12-31" in text
    assert "validation_only" in text


def test_workflow_never_uses_locked_data():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "locked_opened=false" in text or "locked_opened: false" in text
    assert "end: 2021-01-01" in text or "--end 2021-01-01" in text

