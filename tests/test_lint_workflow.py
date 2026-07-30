"""Static contract for the repository lint workflow."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/lint.yml"


def test_lint_workflow_is_pinned_and_least_privilege() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in text
    assert text.count("runs-on: ubuntu-24.04") == 3
    assert text.count(
        "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
    ) == 3
    assert text.count(
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
    ) == 3
    assert "actions/checkout@v" not in text
    assert "actions/setup-python@v" not in text
    assert text.count("pip install ruff==0.15.12") == 2
    assert "pip install pre-commit==4.6.0" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text
