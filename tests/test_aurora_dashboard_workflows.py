from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_workflow(name: str) -> tuple[dict, str]:
    path = ROOT / ".github" / "workflows" / name
    text = path.read_text(encoding="utf-8")
    data = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(data, dict)
    return data, text


def test_sync_workflow_is_scheduled_manual_and_read_only() -> None:
    workflow, text = load_workflow("aurora-dashboard-sync.yml")
    triggers = workflow["on"]
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers
    assert "*/15 * * * *" in text
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert workflow["jobs"]["sync"]["permissions"] == {"contents": "read", "actions": "read"}
    assert "AURORA_DASHBOARD_URL" in text
    assert "AURORA_DASHBOARD_SYNC_TOKEN" in text
    assert "--auto-page" in text


def test_deploy_workflow_validates_before_deploying() -> None:
    workflow, text = load_workflow("aurora-dashboard-deploy.yml")
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["jobs"]["deploy"]["needs"] == "validate"
    assert "CLOUDFLARE_API_TOKEN" in text
    assert "CLOUDFLARE_ACCOUNT_ID" in text
    assert "apply_migrations" in text


def test_dashboard_workflows_have_no_workflow_write_commands() -> None:
    for name in ("aurora-dashboard-sync.yml", "aurora-dashboard-deploy.yml"):
        _, text = load_workflow(name)
        lowered = text.lower()
        assert "gh workflow run" not in lowered
        assert "gh run cancel" not in lowered
        assert "gh run rerun" not in lowered
