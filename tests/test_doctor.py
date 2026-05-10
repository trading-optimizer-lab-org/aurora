"""Tests for R187 operator doctor."""
from __future__ import annotations

import json

import pytest

from aurora.monitoring.doctor import (
    DoctorReport,
    HealthCheck,
    HealthStatus,
    default_checks,
    run_doctor,
)


# ---------------------------------------------------------------------------
# Pure model tests
# ---------------------------------------------------------------------------


def test_health_status_to_dict_minimal():
    status = HealthStatus(name="x", severity="pass", message="ok")
    assert status.to_dict() == {"name": "x", "severity": "pass", "message": "ok"}


def test_health_status_to_dict_full():
    status = HealthStatus(
        name="x",
        severity="warn",
        message="something",
        remediation="do this",
        detail="more",
    )
    assert status.to_dict() == {
        "name": "x",
        "severity": "warn",
        "message": "something",
        "remediation": "do this",
        "detail": "more",
    }


def test_doctor_report_overall_severity_pass():
    rep = DoctorReport()
    rep.add(HealthStatus(name="a", severity="pass", message="ok"))
    rep.add(HealthStatus(name="b", severity="skip", message="skipped"))
    assert rep.overall_severity() == "pass"


def test_doctor_report_overall_severity_warn():
    rep = DoctorReport()
    rep.add(HealthStatus(name="a", severity="pass", message="ok"))
    rep.add(HealthStatus(name="b", severity="warn", message="meh"))
    assert rep.overall_severity() == "warn"


def test_doctor_report_overall_severity_fail():
    rep = DoctorReport()
    rep.add(HealthStatus(name="a", severity="warn", message="meh"))
    rep.add(HealthStatus(name="b", severity="fail", message="bad"))
    assert rep.overall_severity() == "fail"


def test_doctor_report_to_json_is_stable():
    rep = DoctorReport()
    rep.add(HealthStatus(name="a", severity="pass", message="ok"))
    payload = json.loads(rep.to_json())
    assert payload["overall"] == "pass"
    assert payload["counts"] == {"pass": 1, "warn": 0, "fail": 0, "skip": 0}
    assert payload["checks"] == [{"name": "a", "severity": "pass", "message": "ok"}]


def test_doctor_report_to_table_includes_overall():
    rep = DoctorReport()
    rep.add(HealthStatus(name="a", severity="pass", message="ok"))
    text = rep.to_table()
    assert "overall: pass" in text
    assert "CHECK" in text


# ---------------------------------------------------------------------------
# Driver tests
# ---------------------------------------------------------------------------


def test_run_doctor_skips_network_checks_by_default():
    network_check = HealthCheck(
        name="net",
        description="needs internet",
        run=lambda: HealthStatus(name="net", severity="pass", message="online"),
        requires_network=True,
    )
    rep = run_doctor(checks=[network_check])
    assert rep.statuses[0].severity == "skip"


def test_run_doctor_runs_network_checks_when_allowed():
    network_check = HealthCheck(
        name="net",
        description="needs internet",
        run=lambda: HealthStatus(name="net", severity="pass", message="online"),
        requires_network=True,
    )
    rep = run_doctor(checks=[network_check], allow_network=True)
    assert rep.statuses[0].severity == "pass"


def test_run_doctor_captures_check_exceptions():
    def boom() -> HealthStatus:
        raise RuntimeError("explode")

    rep = run_doctor(
        checks=[HealthCheck(name="boom", description="d", run=boom)]
    )
    assert rep.statuses[0].severity == "fail"
    assert "explode" in rep.statuses[0].message


def test_run_doctor_filters_by_only():
    a = HealthCheck(
        "a", "d", lambda: HealthStatus(name="a", severity="pass", message="")
    )
    b = HealthCheck(
        "b", "d", lambda: HealthStatus(name="b", severity="pass", message="")
    )
    rep = run_doctor(checks=[a, b], only=["b"])
    assert [s.name for s in rep.statuses] == ["b"]


# ---------------------------------------------------------------------------
# Built-in registry tests
# ---------------------------------------------------------------------------


def test_default_checks_have_unique_names():
    names = [c.name for c in default_checks()]
    assert len(names) == len(set(names))


def test_default_checks_include_required_set():
    names = {c.name for c in default_checks()}
    required = {
        "package_import",
        "python_version",
        "runtime_paths",
        "audit_log",
        "oos_lock",
        "optional_deps",
        "first_dataset",
        "provider_credentials",
    }
    assert required.issubset(names)


def test_run_doctor_with_defaults_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    rep = run_doctor()
    # The python and import checks are deterministic; the rest may pass or
    # warn depending on environment, but nothing should fail catastrophically.
    statuses = {s.name: s.severity for s in rep.statuses}
    assert statuses["python_version"] == "pass"
    assert statuses["package_import"] == "pass"


def test_default_runtime_paths_check_passes_in_temp_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AU_CACHE_DIR", str(tmp_path / "cache"))
    rep = run_doctor(only=["runtime_paths"])
    assert rep.statuses[0].severity == "pass"


def test_oos_lock_check_warns_when_lock_file_present(monkeypatch, tmp_path):
    lock = tmp_path / "lock.json"
    lock.write_text('{"phase": "explicit_unlock_oos_locked"}', encoding="utf-8")
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AU_OOS_LOCK", str(lock))
    rep = run_doctor(only=["oos_lock"])
    assert rep.statuses[0].severity == "warn"


def test_oos_lock_check_passes_when_no_lock_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AU_OOS_LOCK", str(tmp_path / "missing.json"))
    rep = run_doctor(only=["oos_lock"])
    assert rep.statuses[0].severity == "pass"


def test_first_dataset_warns_when_snapshot_root_empty(monkeypatch, tmp_path):
    snap = tmp_path / "snapshots"
    snap.mkdir()
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AU_SNAPSHOT_ROOT", str(snap))
    rep = run_doctor(only=["first_dataset"])
    assert rep.statuses[0].severity == "warn"


def test_first_dataset_passes_when_snapshot_present(monkeypatch, tmp_path):
    snap = tmp_path / "snapshots"
    snap.mkdir()
    (snap / "stub").mkdir()
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AU_SNAPSHOT_ROOT", str(snap))
    rep = run_doctor(only=["first_dataset"])
    assert rep.statuses[0].severity == "pass"


# ---------------------------------------------------------------------------
# CLI registration smoke test
# ---------------------------------------------------------------------------


def test_doctor_cli_is_registered():
    from aurora.cli.forge import build_parser

    parser = build_parser()
    # Walk into the subparser registry to confirm doctor is wired.
    actions = [a for a in parser._actions if hasattr(a, "choices")]
    sub_choices = {}
    for a in actions:
        if isinstance(a.choices, dict):
            sub_choices.update(a.choices)
    assert "doctor" in sub_choices
