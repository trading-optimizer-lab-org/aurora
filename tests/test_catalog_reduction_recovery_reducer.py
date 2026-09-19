import json
import sys
import shutil
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun import catalog_reduction_recovery_profile as recovery
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.tests.test_catalog_reduction_recovery_source import build_historical_reduction_source_fixture, _reseal_member
from scripts import reduce_sp500_optimized_catalog_run as reducer


@pytest.mark.parametrize("mutation", ["none", "protocol_only", "infrastructure_only", "contract_drift", "token", "plan_receipt", "group_receipt", "coverage", "input_root"])
def test_reduction_only_uses_prior_results_with_current_authorization(tmp_path, monkeypatch, mutation):
    fixture = build_historical_reduction_source_fixture(tmp_path / "source", cached_count=0)
    sealed = tmp_path / "current-sealed-plan"
    shutil.copytree(fixture["sealed_plan"], sealed)
    if mutation == "protocol_only":
        receipt_path = sealed / "execution_plan_receipt.json"
        payload = json.loads(receipt_path.read_text("utf-8"))
        payload["execution_protocol_sha256"] = "f" * 64
        payload["receipt_sha256"] = canonical_sha256({key: value for key, value in payload.items() if key != "receipt_sha256"})
        receipt_path.write_text(json.dumps(payload), "utf-8")
    if mutation in {"infrastructure_only", "contract_drift"}:
        current_fixture = {**fixture, "sealed_plan": sealed}
        contract = json.loads((sealed / "resolved_contract.json").read_text("utf-8"))
        if mutation == "infrastructure_only":
            contract["infrastructure_sha256"] = "0" * 64
        else:
            contract["limits"]["max_result_bytes_per_recipe"] *= 2
        _reseal_member(current_fixture, "resolved_contract.json", contract)
        plan = json.loads((sealed / "run_plan.json").read_text("utf-8"))
        plan["contract_sha256"] = canonical_sha256(contract)
        _reseal_member(current_fixture, "run_plan.json", plan)
    receipts = [json.loads(path.read_text("utf-8")) for path in fixture["groups"].glob("*/receipt.json")]
    profile = SimpleNamespace(
        source_plan_bindings=fixture["bindings"],
        source_plan_receipt_sha256="0" * 64 if mutation == "plan_receipt" else fixture["plan_receipt"]["receipt_sha256"],
        strategy_ids=fixture["strategy_ids"][:-1] if mutation == "coverage" else fixture["strategy_ids"],
        science_sha256=fixture["science"], catalog_manifest_sha256=fixture["catalog"],
        artifacts=tuple(SimpleNamespace(role="group", receipt_sha256="0" * 64 if mutation == "group_receipt" else row["receipt_sha256"]) for row in receipts),
        source_request_sha256="a" * 64, source_run_id=17, source_run_attempt=1,
        source_terminal_receipt_sha256="c" * 64, profile_sha256="d" * 64,
    )
    # The protected-profile boundary has separate byte-level tests. Everything
    # below it uses the real sealed-plan, Parquet and reduction consumers.
    monkeypatch.setattr(recovery, "read_sealed_reduction_recovery_profile", lambda *args, **kwargs: profile)
    monkeypatch.setattr(reducer, "resolve_registered_selected_result_keys", lambda **kwargs: ())
    catalog = tmp_path / "catalog.jsonl"
    catalog.write_text("".join(json.dumps({"strategy_id": item, "strategy_kind": "fixture"}) + "\n" for item in fixture["strategy_ids"]), "utf-8")
    output = tmp_path / "result"
    argv = ["reduce", "--input-root", str(tmp_path if mutation == "input_root" else fixture["groups"]),
            "--catalog", str(catalog), "--resolved-contract", str(sealed / "resolved_contract.json"),
            "--resume-work-manifest", str(sealed / "resume_work_manifest.json"),
            "--run-plan", str(sealed / "run_plan.json"),
            "--admission-token", "0" * 64 if mutation == "token" else fixture["run_plan"].admission_token_sha256,
            "--reduction-plan", str(sealed / "reduction_plan.json"),
            "--sealed-plan", str(sealed), "--recovery-source-root", str(tmp_path / "source"),
            "--output-dir", str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    if mutation not in {"none", "protocol_only", "infrastructure_only"}:
        expected_error = "CATALOG_REDUCTION_RECOVERY_CONTRACT_INCOMPATIBLE" if mutation == "contract_drift" else "CATALOG_|OPTIMIZED_"
        with pytest.raises((ValueError, SystemExit), match=expected_error):
            reducer.main()
        assert not output.exists()
        return
    assert reducer.main() == 0
    receipt = json.loads((output / "receipt.json").read_text("utf-8"))
    assert receipt["strategy_count"] == 24
    assert receipt["physical_recipe_evaluations"] == 0
    assert receipt["prior_result_cache_hits"] == 24
    assert receipt["workers"] == receipt["worker_receipt_count"] == 0
    assert receipt["execution_metrics"]["worker_evaluation_seconds"] is None
    assert receipt["execution_metrics"]["basis"] == "unavailable"
    assert receipt["root_node_descriptor_sha256"] is None
    assert receipt["recovery_source"]["source_root_node_descriptor_sha256"]
    assert receipt["recovery_source"]["source_run_id"] == 17
    if mutation == "protocol_only":
        assert receipt["recovery_source"]["current_execution_protocol_sha256"] == "f" * 64
        assert receipt["recovery_source"]["source_execution_protocol_sha256"] != "f" * 64
