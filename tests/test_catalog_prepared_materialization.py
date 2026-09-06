"""Exercise the actual prepared-template writer/reader, not scientific execution."""

from hashlib import sha256
import json

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_optimization_contract import RunOptimizationContractV1
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    materialize_prepared_catalog_plan, write_prepared_catalog_bundle_manifest,
)
from aurora.infra.sp500_megarun.catalog_sealed_plan import verify_sealed_global_reuse_execution_plan
from aurora.tests.test_catalog_fast_path import _identity, _prepared
from aurora.tests.test_sp500_catalog_optimization_contract import _task10_contract_payload, _task10_plan_fixture
from scripts.plan_sp500_optimized_catalog_run import write_sealed_global_reuse_execution_plan


def prepared_transport_fixture(tmp_path, mismatch=None):
    """Real writer output with explicitly synthetic scientific inputs."""
    bundle = tmp_path / "bundle"
    template = bundle / "templates/workers-007"
    template.parent.mkdir(parents=True)
    plan = _task10_plan_fixture(warm_component_ordinals=set(range(12)), worker_count_override=7, qualify_layout=False)
    contract = RunOptimizationContractV1.model_validate(_task10_contract_payload())
    source_identity = {"schema_version": "1", "document_type": "catalog_source_artifacts_v1",
                       "payload": {"artifacts": [{"contract_name": "reference_oracle_v1",
                           "run_id": 31948898747, "artifact_id": 9264302413,
                           "artifact_name": "sp500-strategy-catalog-final-results",
                           "artifact_digest": "sha256:" + "f" * 64,
                           "validation_opened": False, "locked_opened": False}]}}
    original = write_sealed_global_reuse_execution_plan(
        output_dir=template, contract=contract, plan=plan,
        request_sha256="a" * 64, execution_protocol_sha256="b" * 64,
        protected_commit_sha="a" * 40, decision_sha256="d" * 64, admission_token_sha256="e" * 64,
        controller_binding={"schema_version": "1", "request_sha256": "a" * 64,
                            "authority_id": plan.authority_id, "campaign_id": plan.campaign_id},
        run_plan={"schema_version": "1", "admission_token_sha256": "e" * 64},
        resume_work_manifest={"schema_version": "1", "pending_strategy_ids": [r.strategy_id for r in plan.recipe_requirements]},
        # Only byte transport is under test; this is explicitly NOT a real DAG.
        recipe_dag_bytes=b"PAR1-transport-fixture-not-scientific-data",
        recipe_dag_manifest={"schema_version": "1", "recipe_count": len(plan.recipe_requirements),
                             "validation_opened": False, "locked_opened": False},
        source_artifacts={**source_identity, "content_sha256": canonical_sha256(source_identity)},
    )
    identity = _identity(scientific_contract_sha256="f" * 64 if mismatch == "science" else plan.science_sha256,
                         protected_commit_sha="f" * 40 if mismatch == "commit" else "a" * 40)
    prepared = _prepared(identity=identity, execution_plan_template_sha256=original["global_reuse_plan_sha256"],
                         logical_recipe_count=24, unique_component_count=12, qualified_worker_ceiling=7)
    (bundle / "prepared-receipt.json").write_text(prepared.model_dump_json(), encoding="utf-8")
    write_prepared_catalog_bundle_manifest(bundle_dir=bundle, prepared_receipt=prepared)
    return bundle, template, plan, identity, prepared


@pytest.mark.parametrize("mismatch", (None, "science", "commit"))
def test_materialization_binds_prepared_identity_before_copying(tmp_path, mismatch):
    """Accepting only a template hash must not permit a different science/commit."""
    bundle, template, plan, identity, prepared = prepared_transport_fixture(tmp_path, mismatch)
    before = {p.relative_to(template).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in template.rglob("*") if p.is_file()}
    target = tmp_path / "sealed"
    args = dict(bundle_dir=bundle, expected_identity=identity, request_sha256="1" * 64,
                decision_sha256="2" * 64, output_dir=target)
    if mismatch:
        with pytest.raises(ValueError, match="CATALOG_PREPARED_TEMPLATE_IDENTITY_MISMATCH"):
            materialize_prepared_catalog_plan(**args)
        assert not target.exists()
    else:
        result = materialize_prepared_catalog_plan(**args)
        assert result["request_sha256"] == "1" * 64
        assert result["decision_sha256"] == "2" * 64
        assert result["science_sha256"] == plan.science_sha256
        verify_sealed_global_reuse_execution_plan(target, expected_bindings={"request_sha256": "1" * 64})
        changed = {name for name, digest in before.items() if sha256((target / name).read_bytes()).hexdigest() != digest}
        assert changed == {"controller_binding.json", "execution_plan_receipt.json"}
        binding = json.loads((target / "controller_binding.json").read_text("utf-8"))
        assert binding["binding"]["prepared_receipt_sha256"] == prepared.receipt_sha256
    assert before == {p.relative_to(template).as_posix(): sha256(p.read_bytes()).hexdigest()
                      for p in template.rglob("*") if p.is_file()}
