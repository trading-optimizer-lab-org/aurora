"""Exercise terminal output when an admitted engine loses its outcome artifact."""

import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_fast_path import (
    parse_catalog_terminal_receipt, decide_fast_catalog_launch,
)
from scripts.finalize_catalog_fast_run import finalize_fast_run
from tests.test_catalog_fast_path import NOW, _entry, _identity, _prepared, _request, _snapshot
from tests.test_catalog_engine_outcome import _base
from aurora.infra.sp500_megarun.catalog_engine_outcome import select_catalog_engine_outcome


@pytest.mark.parametrize("gate_result", [None, "failure", "science_missing", "science_file_absent", "science_invalid", "science_malformed", "science_valid", "science_recovered", "science_no_recovery", "gate_failure_invalid", "science_unindexed"])
def test_missing_engine_outcome_produces_bound_blocked_receipt(tmp_path: Path, gate_result) -> None:
    unindexed = gate_result == "science_unindexed"
    recovered = gate_result == "science_recovered"
    no_recovery = gate_result == "science_no_recovery"
    valid_science = gate_result in {"science_valid", "science_recovered", "science_no_recovery", "science_unindexed"}
    failed_gate = gate_result == "gate_failure_invalid"
    invalid_science = gate_result in {"science_invalid", "science_malformed", "gate_failure_invalid"}
    missing_science = gate_result in {"science_missing", "science_file_absent"}
    science_path = tmp_path / "absent-science.json" if gate_result == "science_file_absent" else None
    if invalid_science:
        science_path = tmp_path / "invalid-science.json"
        science_path.write_text("{" if gate_result == "science_malformed" else "{}")
    if missing_science or invalid_science or valid_science:
        gate_result = "failure" if failed_gate else None
    request = _request()
    decision = decide_fast_catalog_launch(
        request=request, registry_entry=_entry(), prepared_receipt=_prepared(),
        expected_preparation_identity=_identity(), snapshot=_snapshot(), issue_created_at=NOW,
    )
    context = {"request": request.model_dump(mode="json"), "logical_recipe_count": 37258}
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps({**context, "content_sha256": canonical_sha256(context)}))
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(decision.model_dump_json())
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps({"id":123, "html_url":"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/123", "created_at":"2026-09-03T12:00:00Z"}))
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"jobs":[{"name":"engine / evaluate_a", "started_at":"2026-09-03T12:00:02Z", "completed_at":"2026-09-03T12:00:05Z", "conclusion":"failure"}]}))
    output = tmp_path / "terminal.json"
    outcome_path = tmp_path / "missing-outcome.json"
    if missing_science or invalid_science or valid_science:
        outcome = select_catalog_engine_outcome(**_base(request_sha256=request.request_sha256, engine_run_id=123))
        outcome_path.write_text(outcome.model_dump_json())
    if valid_science:
        # Synthetic transport fixture, not evidence of scientific equivalence.
        import hashlib
        audit = {"strategy_count": 37258, "scientific_results_sha256": "a" * 64,
                 "execution_metrics": {"schema_version": "1", "worker_evaluation_seconds": 17.25,
                                       "basis": "sum_of_verified_worker_evaluation_durations"}}
        audit_path = tmp_path / "catalog_scientific_audit_receipt_v1.json"
        if recovered or no_recovery:
            audit["recovery_metrics"] = {"schema_version": "1",
                "verified_block_ids": ["b" * 64, "c" * 64],
                "recovered_block_ids": ["c" * 64] if recovered else []}
        audit_path.write_text(json.dumps({**audit, "receipt_sha256": canonical_sha256(audit)}))
        index = {"request_sha256": request.request_sha256, "science_sha256": outcome.science_sha256,
                 "files": [{"path": audit_path.name, "size_bytes": audit_path.stat().st_size,
                            "sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest()}]}
        if unindexed:
            # A self-hashed file next to an index is not indexed evidence.
            index['files'] = []
            valid_science = False
            invalid_science = True
        science_path = tmp_path / "science.json"
        science_path.write_text(json.dumps({**index, "index_sha256": canonical_sha256(index)}))
    receipt = finalize_fast_run(
        request_context_path=context_path, decision_path=decision_path,
        run_path=run_path, jobs_path=jobs_path,
        engine_outcome_path=outcome_path, science_index_path=science_path,
        output_path=output, comment_output_path=tmp_path / "comment.json",
        github_output=tmp_path / "github-output",
        **({"gate_result": gate_result} if gate_result else {}),
    )
    reopened = parse_catalog_terminal_receipt(json.loads(output.read_text()))
    assert reopened.schema_version == "2"
    assert reopened.recovered_block_count == (1 if recovered else 0 if no_recovery else None)
    if recovered:
        assert reopened.recovered_block_ids == ("c" * 64,)
    assert receipt == reopened
    assert receipt.state == ("SUCCESS" if valid_science else "BLOCKED")
    assert receipt.reason_code == ("CATALOG_RUN_SUCCESS" if valid_science else
        "CATALOG_GATE_PUBLICATION_FAILED" if failed_gate else
        "CATALOG_FAST_TERMINAL_SCIENCE_INVALID" if invalid_science else
        "CATALOG_FAST_TERMINAL_SCIENCE_MISSING" if missing_science else
        "CATALOG_GATE_PUBLICATION_FAILED" if gate_result else "CATALOG_ENGINE_OUTCOME_MISSING")
    assert receipt.engine_run_id == 123
    assert receipt.request_sha256 == request.request_sha256
    assert receipt.observed_recipe_count == (37258 if valid_science else 0)
    assert receipt.result_science_sha256 == ("a" * 64 if valid_science else None)
    if valid_science:
        comment = json.loads((tmp_path / "comment.json").read_text())["body"]
        assert "Worker evaluation (aggregate): `17.250s`" in comment
        assert "Evaluation jobs window:" in comment


@pytest.mark.parametrize('timing_case,diagnostic', [
    ('reversed', 'CLOCK_SKEW'), ('missing_start', 'TIMING_METADATA_MISSING'),
    ('invalid_date', 'TIMING_METADATA_INVALID'), ('before_run', 'CLOCK_SKEW'),
])
def test_invalid_job_timing_is_explicit_without_changing_verified_science(tmp_path, timing_case, diagnostic):
    test_missing_engine_outcome_produces_bound_blocked_receipt(tmp_path, 'science_valid')
    job = {'name': 'engine / evaluate_a', 'started_at': '2026-09-03T12:00:02Z',
           'completed_at': '2026-09-03T12:00:05Z', 'conclusion': 'success'}
    if timing_case == 'reversed':
        job['completed_at'] = '2026-09-03T12:00:01Z'
    elif timing_case == 'missing_start':
        job.pop('started_at')
    elif timing_case == 'invalid_date':
        job['started_at'] = 'not-a-date'
    else:
        job['started_at'] = '2026-09-03T11:59:59Z'
    (tmp_path / 'jobs.json').write_text(json.dumps({'jobs': [job]}))
    receipt = finalize_fast_run(request_context_path=tmp_path / 'context.json',
        decision_path=tmp_path / 'decision.json', run_path=tmp_path / 'run.json',
        jobs_path=tmp_path / 'jobs.json', engine_outcome_path=tmp_path / 'missing-outcome.json',
        science_index_path=tmp_path / 'science.json', output_path=tmp_path / 'timing-terminal.json',
        comment_output_path=tmp_path / 'timing-comment.json', github_output=tmp_path / 'timing-output')
    assert receipt.state == 'SUCCESS'
    assert receipt.observed_recipe_count == 37258
    assert receipt.result_science_sha256 == 'a' * 64
    assert diagnostic in json.loads((tmp_path / 'timing-comment.json').read_text())['body']
    if timing_case == 'before_run':
        assert receipt.timing.initial_queue_seconds is None
    else:
        assert receipt.timing.evaluation_jobs_window_seconds is None
    assert parse_catalog_terminal_receipt(json.loads((tmp_path / 'timing-terminal.json').read_text())) == receipt


@pytest.mark.parametrize('failed_destination', ['terminal', 'comment'])
def test_publication_failure_reports_primary_outcome_and_preserves_written_receipt(tmp_path, capsys, failed_destination):
    test_missing_engine_outcome_produces_bound_blocked_receipt(tmp_path, None)
    blocked_destination = tmp_path / 'cannot-write-a-file-here'
    blocked_destination.mkdir()
    terminal = blocked_destination if failed_destination == 'terminal' else tmp_path / 'publication-terminal.json'
    comment = blocked_destination if failed_destination == 'comment' else tmp_path / 'publication-comment.json'
    with pytest.raises(ValueError, match='CATALOG_FAST_TERMINAL_PUBLICATION_FAILED'):
        finalize_fast_run(request_context_path=tmp_path / 'context.json', decision_path=tmp_path / 'decision.json',
            run_path=tmp_path / 'run.json', jobs_path=tmp_path / 'jobs.json',
            engine_outcome_path=tmp_path / 'missing-outcome.json', science_index_path=None,
            output_path=terminal, comment_output_path=comment, github_output=tmp_path / 'publication-output')
    diagnostic = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert diagnostic['reason_code'] == 'CATALOG_FAST_TERMINAL_PUBLICATION_FAILED'
    assert diagnostic['primary_reason_code'] == 'CATALOG_ENGINE_OUTCOME_MISSING'
    assert diagnostic['reservation_release_allowed'] is False
    assert not (tmp_path / 'publication-output').exists()
    if failed_destination == 'comment':
        receipt = parse_catalog_terminal_receipt(json.loads(terminal.read_text()))
        assert receipt.state == 'BLOCKED'
        assert receipt.reason_code == diagnostic['primary_reason_code']


@pytest.mark.parametrize(("gate_result", "reserved", "existing", "expected"), [
    ("success", "false", "", True), ("failure", "true", "", True),
    ("cancelled", "true", "", True), ("failure", "false", "", False),
    ("skipped", "false", "", False), ("failure", "true", "123", False),
])
def test_verified_reservation_can_finalize_after_gate_failure(gate_result, reserved, existing, expected):
    root = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(root / ".github/workflows/catalog-fast-controller.yml")
    expression = workflow["jobs"]["finalize"]["if"].removeprefix("${{").removesuffix("}}")
    expression = expression.replace("&&", " and ").replace("||", " or ")
    outputs = SimpleNamespace(valid_request="true", admission_completed="true", existing_run_id=existing,
        preserve_issue="false", authority_reserved=reserved)
    needs = SimpleNamespace(gate=SimpleNamespace(result=gate_result, outputs=outputs))
    assert eval(expression, {"__builtins__": {}}, {"always": lambda: True, "needs": needs}) is expected


def test_workflow_allows_missing_outcome_to_reach_real_finalizer() -> None:
    # Complementary workflow contract; the test above checks the real receipt.
    # Real GitHub job execution is still required by T13.
    root = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(root / ".github/workflows/catalog-fast-controller.yml")
    steps = workflow["jobs"]["finalize"]["steps"]
    download = next(step for step in steps if step.get("name") == "Download the unique engine outcome")
    assert download.get("continue-on-error") is True
    science_download = next(step for step in steps if step.get("name") == "Download terminal science only for a successful engine candidate")
    assert science_download.get("continue-on-error") is True
    terminal = next(step for step in steps if step.get("id") == "terminal")
    assert "scripts/finalize_catalog_fast_run.py" in terminal["run"]


def test_admission_and_terminal_writers_share_only_the_control_lock() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(root / ".github/workflows/catalog-fast-controller.yml")
    jobs = workflow["jobs"]
    admission = jobs["gate"]["concurrency"]
    terminal = jobs["finalize"].get("concurrency")
    assert terminal == admission
    assert terminal["cancel-in-progress"] is False
    assert terminal["queue"] == "max"
    assert workflow["concurrency"]["group"] != terminal["group"]
    assert jobs["engine"].get("concurrency", {}).get("group") != terminal["group"]
