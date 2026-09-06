from copy import deepcopy
import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun import catalog_runtime_audit as audit
from aurora.infra.github_performance.preflight import load_github_yaml


def _evidence():
    return {
        "binding": {"execution_plan_sha256": "a" * 64},
        "matrix_counts": {
            "component_matrix_a_count": 0,
            "component_matrix_b_count": 0,
            "cached_component_matrix_a_count": 5,
            "cached_component_matrix_b_count": 0,
            "recipe_matrix_a_count": 4,
            "recipe_matrix_b_count": 0,
            "recipe_matrix_c_count": 0,
            "payload_artifact_count": 1,
            "reduction_matrix_count": 1,
        },
        "reconcile_status": "retry",
        "recovery": [
            {"status": "complete", "has_matrix_a": "false", "has_matrix_b": "false"},
            {"status": "", "has_matrix_a": "", "has_matrix_b": ""},
        ],
    }


def test_skip_policy_uses_empty_plan_matrices_and_verified_recovery_outputs() -> None:
    evidence = _evidence()
    result = audit.allowed_skips_from_verified_outputs(evidence, binding=evidence["binding"])
    assert result == frozenset({
        "engine / build_components_a", "engine / build_components_b",
        "engine / materialize_cached_components_b",
        "engine / evaluate_b", "engine / evaluate_c",
        "engine / recovery_wave_1 / retry_a", "engine / recovery_wave_1 / retry_b",
        "engine / recovery_wave_2",
    })


@pytest.mark.parametrize("mutation", ("binding", "negative", "bool", "missing", "unknown", "recovery_incomplete", "missing_matrix_evidence"))
def test_skip_policy_rejects_unbound_or_incomplete_evidence(mutation: str) -> None:
    evidence = _evidence()
    binding = deepcopy(evidence["binding"])
    if mutation == "binding":
        evidence["binding"]["execution_plan_sha256"] = "b" * 64
    elif mutation == "negative":
        evidence["matrix_counts"]["recipe_matrix_a_count"] = -1
    elif mutation == "bool":
        evidence["matrix_counts"]["recipe_matrix_a_count"] = False
    elif mutation == "missing":
        evidence["matrix_counts"].pop("recipe_matrix_a_count")
    elif mutation == "unknown":
        evidence["matrix_counts"]["arbitrary_job"] = 0
    elif mutation == "recovery_incomplete":
        evidence["recovery"][0]["status"] = "blocked"
    else:
        evidence["recovery"][0]["has_matrix_a"] = ""
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_SKIP_POLICY_INVALID"):
        audit.allowed_skips_from_verified_outputs(evidence, binding=binding)


def test_skip_policy_keeps_required_recovery_wave_when_first_wave_needs_retry() -> None:
    evidence = _evidence()
    evidence["recovery"] = [
        {"status": "retry", "has_matrix_a": "true", "has_matrix_b": "false"},
        {"status": "complete", "has_matrix_a": "true", "has_matrix_b": "false"},
    ]
    result = audit.allowed_skips_from_verified_outputs(evidence, binding=evidence["binding"])
    assert "engine / recovery_wave_2" not in result
    assert "engine / recovery_wave_1 / retry_a" not in result
    assert "engine / recovery_wave_2 / retry_b" in result


@pytest.mark.parametrize("wrong_binding", (False, True))
def test_runtime_audit_cli_consumes_bound_skip_evidence(tmp_path: Path, wrong_binding: bool) -> None:
    from scripts.audit_catalog_runtime import main
    from test_catalog_runtime_audit import BINDING, NOW, _pages, _run

    evidence = _evidence()
    evidence["binding"] = dict(BINDING)
    if wrong_binding:
        evidence["binding"]["execution_plan_sha256"] = "f" * 64
    jobs = _pages("jobs")
    job_rows = jobs[0]["jobs"]
    assert isinstance(job_rows, list)
    job_rows.append({"id": 12, "name": "engine / build_components_b", "conclusion": "skipped", "labels": []})
    documents = {
        "binding": BINDING,
        "verified-skip-evidence": evidence,
        "run": _run(),
        "repository": {"full_name": "trading-optimizer-lab-org/aurora", "visibility": "public", "private": False},
        "jobs": jobs, "jobs-confirmation": jobs,
        "artifacts": _pages("artifacts"), "artifacts-confirmation": _pages("artifacts"),
    }
    arguments: list[str] = []
    for name, payload in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        arguments.extend((f"--{name}", str(path)))
    output = tmp_path / "audit.json"
    arguments.extend(("--run-id", "100", "--run-attempt", "2", "--audited-at", NOW.isoformat(), "--output", str(output)))
    assert main(arguments) == (2 if wrong_binding else 0)
    if wrong_binding:
        assert not output.exists()
    else:
        assert json.loads(output.read_text("utf-8"))["job_ids"] == [10, 11, 12]


def test_workflow_supplies_skip_evidence_only_from_protected_outputs() -> None:
    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    engine = load_github_yaml(workflows / "catalog-optimized-run.yml")
    runtime = engine["jobs"]["audit_runtime"]
    assert {"engine_verify_sealed_plan", "reconcile_wave_0", "recovery_wave_1", "recovery_wave_2"} <= set(runtime["needs"])
    step = next(row for row in runtime["steps"] if row.get("name") == "Collect complete current-run metadata")
    assert step["env"]["VERIFIED_MATRIX_COUNTS"] == "${{ needs.engine_verify_sealed_plan.outputs.runtime_skip_matrix_counts }}"
    assert step["env"]["VERIFIED_RECONCILE_STATUS"] == "${{ needs.reconcile_wave_0.outputs.status }}"
    for wave in (1, 2):
        for suffix, field in (("STATUS", "status"), ("MATRIX_A", "has_matrix_a"), ("MATRIX_B", "has_matrix_b")):
            assert step["env"][f"VERIFIED_WAVE_{wave}_{suffix}"] == "${{ needs.recovery_wave_" + str(wave) + ".outputs." + field + " }}"
    assert "--verified-skip-evidence runtime-skip-evidence.json" in step["run"]
    recovery = load_github_yaml(workflows / "catalog-recovery-wave.yml")
    for suffix in ("a", "b"):
        assert recovery["on"]["workflow_call"]["outputs"][f"has_matrix_{suffix}"]["value"] == "${{ jobs.reconcile.outputs.has_matrix_" + suffix + " }}"
