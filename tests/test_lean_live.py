"""Tests for exports.lean.live (R1)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aurora.core.protocol_policy import ProtocolPolicy
from aurora.exports.lean.live import (
    LiveDeployConfig,
    deploy_to_lean_cloud,
    prepare_live_deploy,
)

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _make_valid_project(root: Path) -> Path:
    """Build a minimal Lean export project that passes verify_project."""
    proj = root / "lean_export"
    proj.mkdir()
    policy = ProtocolPolicy.default()
    metadata = {
        "policy_hash": policy.policy_hash,
        "spec_hash": "test_spec_hash_abc123",
        "qf_version": "1.4.0",
        "exported_at": "2026-05-08T12:00:00",
        "translation_tier": "scaffold",
    }
    (proj / "qf_metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    (proj / "README.md").write_text(
        "# Lean export\n\nDO NOT TRUST IN ISOLATION.\n",
        encoding="utf-8",
    )
    return proj


def _make_invalid_project(root: Path) -> Path:
    """Project missing the README warning -> verify fails."""
    proj = root / "lean_export"
    proj.mkdir()
    policy = ProtocolPolicy.default()
    metadata = {
        "policy_hash": policy.policy_hash,
        "spec_hash": "test_spec_hash_abc123",
        "qf_version": "1.4.0",
        "exported_at": "2026-05-08T12:00:00",
    }
    (proj / "qf_metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    # README missing the warning string.
    (proj / "README.md").write_text("# Lean export\n", encoding="utf-8")
    return proj


# --------------------------------------------------------------------------
# prepare_live_deploy
# --------------------------------------------------------------------------


def test_prepare_passes_on_valid_project(tmp_path: Path):
    proj = _make_valid_project(tmp_path)
    res = prepare_live_deploy(proj)
    assert res.provenance_ok is True
    assert res.provenance_errors == []
    assert res.deploy_attempted is False


def test_prepare_fails_on_invalid_project(tmp_path: Path):
    proj = _make_invalid_project(tmp_path)
    res = prepare_live_deploy(proj)
    assert res.provenance_ok is False
    assert any("DO NOT TRUST" in e for e in res.provenance_errors)
    assert res.blocking_reason == "provenance_failed"


# --------------------------------------------------------------------------
# deploy_to_lean_cloud: gates
# --------------------------------------------------------------------------


def test_deploy_blocked_by_failed_provenance(tmp_path: Path):
    proj = _make_invalid_project(tmp_path)
    res = deploy_to_lean_cloud(proj)
    assert res.deploy_attempted is False
    assert res.blocking_reason == "provenance_failed"


def test_deploy_blocked_by_missing_operator_flag(tmp_path: Path, monkeypatch):
    proj = _make_valid_project(tmp_path)
    monkeypatch.delenv("QF_LEAN_LIVE_AUTH", raising=False)
    cfg = LiveDeployConfig(dry_run=False)
    res = deploy_to_lean_cloud(proj, cfg)
    assert res.deploy_attempted is False
    assert res.blocking_reason == "operator_flag_missing"


def test_deploy_blocked_by_dry_run(tmp_path: Path, monkeypatch):
    proj = _make_valid_project(tmp_path)
    monkeypatch.setenv("QF_LEAN_LIVE_AUTH", "1")
    cfg = LiveDeployConfig(dry_run=True)
    res = deploy_to_lean_cloud(proj, cfg)
    assert res.deploy_attempted is False
    assert res.blocking_reason == "dry_run_active"


# --------------------------------------------------------------------------
# deploy_to_lean_cloud: invoker pathways
# --------------------------------------------------------------------------


def test_deploy_invokes_when_all_gates_passed(tmp_path: Path, monkeypatch):
    proj = _make_valid_project(tmp_path)
    monkeypatch.setenv("QF_LEAN_LIVE_AUTH", "1")

    captured: list[list[str]] = []

    def fake_invoker(argv: list[str]) -> dict[str, Any]:
        captured.append(list(argv))
        return {"ok": True, "argv": argv, "response": {"deploy_id": "X1"}}

    cfg = LiveDeployConfig(
        dry_run=False, cloud_project_name="my-project"
    )
    res = deploy_to_lean_cloud(proj, cfg, cli_invoker=fake_invoker)
    assert res.deploy_attempted is True
    assert res.deploy_ok is True
    assert res.blocking_reason is None
    assert captured and "live" in captured[0]
    assert "my-project" in captured[0]


def test_default_invoker_refuses(tmp_path: Path, monkeypatch):
    """Without an injected invoker, the default refuses for safety."""
    proj = _make_valid_project(tmp_path)
    monkeypatch.setenv("QF_LEAN_LIVE_AUTH", "1")
    cfg = LiveDeployConfig(dry_run=False)
    res = deploy_to_lean_cloud(proj, cfg)
    assert res.deploy_attempted is False
    assert res.blocking_reason == "invoker_not_configured"


def test_invoker_exception_recorded(tmp_path: Path, monkeypatch):
    proj = _make_valid_project(tmp_path)
    monkeypatch.setenv("QF_LEAN_LIVE_AUTH", "1")

    def boom(argv: list[str]) -> dict[str, Any]:
        raise RuntimeError("simulated lean cli failure")

    cfg = LiveDeployConfig(dry_run=False)
    res = deploy_to_lean_cloud(proj, cfg, cli_invoker=boom)
    assert res.deploy_attempted is True
    assert res.deploy_ok is False
    assert res.blocking_reason == "invoker_raised"


def test_result_serializable(tmp_path: Path):
    proj = _make_valid_project(tmp_path)
    res = prepare_live_deploy(proj)
    d = res.to_dict()
    json.dumps(d)  # must not raise
