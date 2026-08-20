from scripts.aurora_dashboard_archive import archive_decision, is_readable_artifact


def test_readable_formats_include_reports_and_structured_outputs() -> None:
    assert is_readable_artifact("summary.json")
    assert is_readable_artifact("report.md")
    assert is_readable_artifact("stdout.txt", "text/plain")
    assert not is_readable_artifact("candidate-matrix.parquet", "application/octet-stream")


def test_quota_gate_never_crosses_reserved_budget() -> None:
    decision = archive_decision("summary.json", 11, "application/json", 89, 100)
    blocked = archive_decision("next.json", 2, "application/json", 99, 100)

    assert decision.state == "archived"
    assert decision.should_archive is True
    assert blocked.state == "quota_blocked"
    assert blocked.should_archive is False


def test_duplicate_binary_and_expired_artifacts_keep_source_states() -> None:
    assert archive_decision("summary.json", 10, "application/json", 0, duplicate=True).state == "source_only"
    assert archive_decision("summary.json", 10, "application/json", 0, expired=True).state == "expired"
    assert archive_decision("matrix.parquet", 10, "application/octet-stream", 0).state == "source_only"
