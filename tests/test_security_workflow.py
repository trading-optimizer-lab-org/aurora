"""Static contract for the repository security baseline workflow."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/security.yml"


def test_security_workflow_is_pinned_and_least_privilege() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in text
    assert text.count("runs-on: ubuntu-24.04") == 2
    assert "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803" in text
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in text
    assert "actions/checkout@v" not in text
    assert "actions/setup-python@v" not in text
    assert "bandit==1.9.4" in text
    assert "pip-audit==2.10.1" in text
