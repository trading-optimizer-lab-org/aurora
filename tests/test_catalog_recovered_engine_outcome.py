"""Recovery10 stage regression with real seals and synthetic evidence, no science."""
import json
from hashlib import sha256

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun import catalog_engine_outcome as outcome
from aurora.infra.sp500_megarun.catalog_worker_failure import build_catalog_worker_failure_receipt
from aurora.tests.test_catalog_engine_outcome import _base, NOW
from aurora.tests.test_catalog_prepared_materialization import prepared_transport_fixture


def _proof_fixture(tmp_path):
    _, sealed, _, _, _ = prepared_transport_fixture(tmp_path)
    receipt = json.loads((sealed / "execution_plan_receipt.json").read_text())
    bindings = {key: receipt[key] for key in (
        "request_sha256", "authority_id", "campaign_id", "science_sha256",
        "execution_plan_sha256", "execution_protocol_sha256", "protected_commit_sha",
    )}
    policy = json.loads((sealed / "checkpoint_policy.json").read_text())
    blocks = policy["recovery_blocks_v1"]["blocks"]
    worker = blocks[0]["worker_id"]
    failed_blocks = [b["block_id"] for b in blocks if b["worker_id"] == worker]
    science = tmp_path / "science"
    science.mkdir()
    documents = {
        "catalog_scientific_audit_receipt_v1.json": {
            "schema_version": "1", **bindings, "strategy_count": 24,
            "scientific_results_sha256": "a" * 64, "reduction_receipt_sha256": "b" * 64,
            "schemas_valid": True, "recovery_metrics": {
                "schema_version": "1", "verified_block_ids": [b["block_id"] for b in blocks],
                "recovered_block_ids": failed_blocks,
            },
        },
        "catalog_equivalence_receipt_v1.json": {
            "schema_version": 1, **bindings, "equivalent": True,
            "expected_count": 24, "observed_count": 24, "difference_count": 0,
        },
        "catalog_regression_receipt_v1.json": {
            "schema_version": "1", **bindings, "no_regression": True,
        },
    }
    for doc in documents.values():
        doc.update(validation_opened=False, locked_opened=False)
    failure_root = tmp_path / "failures"
    failure_root.mkdir()
    failure = build_catalog_worker_failure_receipt(
        authority_id=bindings["authority_id"], campaign_id=bindings["campaign_id"],
        execution_plan_sha256=bindings["execution_plan_sha256"],
        protected_commit_sha=bindings["protected_commit_sha"], worker_id=worker,
        attempt_id=f'{bindings["authority_id"]}:worker:{worker:03d}:attempt:1',
        stage="recipe_worker", reason_code="CONNECTION_RESET", exit_code=1,
        exception_type="ConnectionResetError", source_error_code="CATALOG_CANARY_CONTROLLED_TRANSIENT_FAILURE",
        normalized_frame=None, created_at=NOW,
    )
    (failure_root / "failure.json").write_text(failure.model_dump_json())
    stages = {**_base()["stage_results"], "publish_sealed_payload_artifacts": "success",
              "evaluate_a": "failure", "evaluate_b": "skipped", "evaluate_c": "skipped",
              "ready_to_merge": "success", "reduce_groups": "success",
              "recovery_wave_1": "success", "recovery_wave_2": "success"}
    payload = _base(**bindings, stage_results=stages, recovery_statuses=("retry", "retry", "complete"))
    return sealed, science, failure_root, documents, bindings, payload


def _write_science(science, documents, bindings):
    for name, doc in documents.items():
        if name == "catalog_regression_receipt_v1.json":
            doc["equivalence_receipt_sha256"] = documents["catalog_equivalence_receipt_v1.json"]["receipt_sha256"]
        doc.pop("receipt_sha256", None)
        doc["receipt_sha256"] = canonical_sha256(doc)
        (science / name).write_text(json.dumps(doc))
    index = {"schema_version": "1", **bindings, "validation_opened": False, "locked_opened": False,
             "files": [{"path": name, "size_bytes": (science / name).stat().st_size,
                        "sha256": sha256((science / name).read_bytes()).hexdigest()} for name in documents]}
    index["index_sha256"] = canonical_sha256(index)
    path = science / "catalog_terminal_science_index_v1.json"
    path.write_text(json.dumps(index))
    return path


def _verify(fixture):
    sealed, science, failures, documents, bindings, payload = fixture
    index = _write_science(science, documents, bindings)
    return outcome.verify_recovered_evaluation_evidence(
        science_index=index, sealed_plan=sealed, failure_root=failures,
        expected=payload,
    )


def test_historical_failed_matrix_is_preserved_but_complete_proof_allows_candidate(tmp_path):
    fixture = _proof_fixture(tmp_path)
    proof = _verify(fixture)
    result = outcome.select_catalog_engine_outcome(**fixture[-1], recovered_evaluation_evidence=proof)
    assert result.state.value == "TERMINAL_CANDIDATE"
    assert result.stage_results["evaluate_a"] == "failure"


def test_complete_status_without_proof_keeps_old_block(tmp_path):
    fixture = _proof_fixture(tmp_path)
    result = outcome.select_catalog_engine_outcome(**fixture[-1])
    assert result.reason_code == "CATALOG_ENGINE_STAGE_FAILED"


@pytest.mark.parametrize("field", ["request_sha256", "authority_id", "campaign_id", "science_sha256", "execution_plan_sha256", "execution_protocol_sha256", "protected_commit_sha"])
def test_rehashed_science_equivocation_is_rejected(tmp_path, field):
    fixture = _proof_fixture(tmp_path)
    fixture[3]["catalog_scientific_audit_receipt_v1.json"][field] = "0" * 64
    with pytest.raises(ValueError):
        _verify(fixture)


@pytest.mark.parametrize("mutation", ["partial", "no_recovery", "missing_block", "missing_failure", "equivalence", "regression"])
def test_incomplete_or_unproven_recovery_is_rejected(tmp_path, mutation):
    fixture = _proof_fixture(tmp_path)
    audit = fixture[3]["catalog_scientific_audit_receipt_v1.json"]
    if mutation == "partial":
        audit["strategy_count"] = 23
    elif mutation == "no_recovery":
        audit["recovery_metrics"]["recovered_block_ids"] = []
    elif mutation == "missing_block":
        audit["recovery_metrics"]["verified_block_ids"].pop()
    elif mutation == "missing_failure":
        (fixture[2] / "failure.json").unlink()
    elif mutation == "equivalence":
        fixture[3]["catalog_equivalence_receipt_v1.json"]["equivalent"] = False
    else:
        fixture[3]["catalog_regression_receipt_v1.json"]["no_regression"] = False
    with pytest.raises(ValueError):
        _verify(fixture)


@pytest.mark.parametrize("stage,result", [("evaluate_a", "cancelled"), ("prepare_runtime_and_inputs", "failure"), ("engine_verify_sealed_plan", "failure"), ("reduce", "failure"), ("verify_terminal_science", "skipped"), ("audit_runtime", "failure"), ("recovery_wave_2", "cancelled")])
def test_proof_never_excuses_other_failures_or_cancellation(tmp_path, stage, result):
    fixture = _proof_fixture(tmp_path)
    proof = _verify(fixture)
    fixture[-1]["stage_results"][stage] = result
    selected = outcome.select_catalog_engine_outcome(**fixture[-1], recovered_evaluation_evidence=proof)
    assert selected.state.value == "BLOCKED"


@pytest.mark.parametrize("field", ["engine_run_id", "engine_run_attempt", "request_sha256"])
def test_proof_cannot_be_reused_for_another_invocation(tmp_path, field):
    fixture = _proof_fixture(tmp_path)
    proof = _verify(fixture)
    fixture[-1][field] = 2 if field != "request_sha256" else "0" * 64
    with pytest.raises(ValueError):
        outcome.select_catalog_engine_outcome(**fixture[-1], recovered_evaluation_evidence=proof)


@pytest.mark.parametrize("mutation", [None, "run", "attempt", "commit", "missing_argument", "tamper"])
def test_cli_proof_is_opt_in_and_bound_to_current_run(tmp_path, monkeypatch, mutation):
    from scripts.prepare_catalog_engine_outcome import main
    fixture = _proof_fixture(tmp_path)
    sealed, science, failures, documents, bindings, payload = fixture
    index = _write_science(science, documents, bindings)
    monkeypatch.setenv("GITHUB_RUN_ID", str(payload["engine_run_id"]))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", bindings["protected_commit_sha"])
    if mutation in {"run", "attempt", "commit"}:
        monkeypatch.setenv({"run": "GITHUB_RUN_ID", "attempt": "GITHUB_RUN_ATTEMPT", "commit": "GITHUB_SHA"}[mutation], "999")
    if mutation == "tamper":
        (science / "catalog_scientific_audit_receipt_v1.json").write_text("{}")
    input_path, output_path = tmp_path / "input.json", tmp_path / "output.json"
    input_path.write_text(json.dumps(payload, default=str))
    args = ["--input", str(input_path), "--output", str(output_path),
            "--recovered-science-index", str(index), "--sealed-plan", str(sealed)]
    if mutation != "missing_argument":
        args += ["--recovered-failure-root", str(failures)]
    assert main(args) == (0 if mutation is None else 2)
    if mutation is None:
        assert json.loads(output_path.read_text())["state"] == "TERMINAL_CANDIDATE"
    else:
        assert not output_path.exists()


@pytest.mark.parametrize("status", [(), ("retry",), ("retry", "blocked")])
def test_proof_does_not_replace_final_complete_reconciliation(tmp_path, status):
    fixture = _proof_fixture(tmp_path)
    proof = _verify(fixture)
    fixture[-1]["recovery_statuses"] = status
    assert outcome.select_catalog_engine_outcome(**fixture[-1], recovered_evaluation_evidence=proof).state.value == "BLOCKED"


def test_nontransient_failure_receipt_is_not_recoverable(tmp_path):
    fixture = _proof_fixture(tmp_path)
    path = fixture[2] / "failure.json"
    original = json.loads(path.read_text())
    from aurora.infra.sp500_megarun.catalog_worker_failure import build_catalog_worker_failure_receipt
    failure = build_catalog_worker_failure_receipt(
        **{key: original[key] for key in ("authority_id", "campaign_id", "execution_plan_sha256", "protected_commit_sha", "worker_id", "attempt_id", "stage")},
        reason_code="POLICY_VIOLATION", created_at=NOW,
    )
    path.write_text(failure.model_dump_json())
    with pytest.raises(ValueError):
        _verify(fixture)


@pytest.mark.parametrize("mutation", [None, "missing_initial_checkpoint", "other_worker_only"])
def test_multiblock_worker_keeps_initial_checkpoints_and_recovers_only_pending(
    tmp_path, monkeypatch, mutation,
):
    from functools import partial
    from aurora.tests import test_catalog_prepared_materialization as transport
    from aurora.infra.sp500_megarun.catalog_recovery_blocks import recovery_metrics_from_checkpoints

    # Real planner/writer: longer projected recipes require multiple checkpoint
    # slots. This changes fixture inputs, not any verifier or recovery decision.
    monkeypatch.setattr(transport, "_task10_plan_fixture",
                        partial(transport._task10_plan_fixture, recipe_seconds=250.0))
    fixture = _proof_fixture(tmp_path)
    sealed, _, _, documents, bindings, payload = fixture
    blocks = json.loads((sealed / "checkpoint_policy.json").read_text())["recovery_blocks_v1"]["blocks"]
    worker = blocks[0]["worker_id"]
    own_blocks = [row for row in blocks if row["worker_id"] == worker]
    assert len(own_blocks) >= 2
    recovered = own_blocks[-1]["block_id"]
    if mutation == "other_worker_only":
        recovered = next(row["block_id"] for row in blocks if row["worker_id"] != worker)
    records = [{"recovery_block_id": row["block_id"], "worker_id": row["worker_id"],
                "attempt_id": f'{bindings["authority_id"]}:worker:{row["worker_id"]:03d}:attempt:{2 if row["block_id"] == recovered else 1}'}
               for row in blocks]
    if mutation == "missing_initial_checkpoint":
        records = [row for row in records if row["recovery_block_id"] != own_blocks[0]["block_id"]]
    metrics = recovery_metrics_from_checkpoints(records, authority_id=bindings["authority_id"])
    assert metrics["recovered_block_ids"] == [recovered]
    documents["catalog_scientific_audit_receipt_v1.json"]["recovery_metrics"] = metrics
    if mutation is not None:
        with pytest.raises(ValueError):
            _verify(fixture)
    else:
        proof = _verify(fixture)
        selected = outcome.select_catalog_engine_outcome(**payload, recovered_evaluation_evidence=proof)
        assert selected.state.value == "TERMINAL_CANDIDATE"
        assert selected.stage_results["evaluate_a"] == "failure"


@pytest.mark.parametrize("size,tamper", [(9_881_185, False), (9_881_185, True), (16 * 1024 * 1024 + 1, False)])
def test_large_logical_manifest_keeps_seal_and_contextual_size_bound(tmp_path, size, tamper):
    fixture = _proof_fixture(tmp_path)
    sealed = fixture[0]
    path = sealed / "logical_recipe_manifest.json"
    # Preserve the real planner's logical content; JSON whitespace isolates byte
    # size from recipe count and avoids fabricating a scientific evaluation.
    raw = path.read_bytes()
    path.write_bytes(raw + b" " * (size - len(raw)))
    receipt_path = sealed / "execution_plan_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    row = next(row for row in receipt["content_manifest"] if row["path"] == path.name)
    row.update(size_bytes=size, sha256=sha256(path.read_bytes()).hexdigest())
    receipt["content_manifest_sha256"] = canonical_sha256(tuple(receipt["content_manifest"]))
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    receipt_path.write_text(json.dumps(receipt))
    if tamper:
        path.write_bytes(path.read_bytes()[:-1] + b"\n")
    if tamper or size > 16 * 1024 * 1024:
        code = "CATALOG_SEALED_PLAN_CONTENT_INVALID" if tamper else "CATALOG_RECOVERED_EVIDENCE_FILE_INVALID"
        with pytest.raises(ValueError, match=code):
            _verify(fixture)
    else:
        proof = _verify(fixture)
        assert outcome.select_catalog_engine_outcome(
            **fixture[-1], recovered_evaluation_evidence=proof,
        ).state.value == "TERMINAL_CANDIDATE"


@pytest.mark.parametrize("name", ["catalog_terminal_science_index_v1.json", "failure.json", "logical_recipe_manifest.json"])
def test_default_document_limit_is_not_inferred_from_filename(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"{}" + b" " * (2 * 1024 * 1024 - 1))
    with pytest.raises(ValueError, match="CATALOG_RECOVERED_EVIDENCE_FILE_INVALID"):
        outcome._recovery_document(path)
