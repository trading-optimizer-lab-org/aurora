from __future__ import annotations

import argparse
import importlib
from importlib import util
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "openap-proxy-real-correlation-audit.yml"


def _module():
    return importlib.import_module("aurora.research.openap_149.identity_gate")


def _runner_module():
    path = ROOT / "scripts" / "run_openap_149_identity_gate.py"
    spec = util.spec_from_file_location("run_openap_149_identity_gate", path)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_bridge() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "canonical_security_id": ["sec:a", "sec:b", "sec:c"],
            "permno": [10001, 10002, 10003],
            "valid_from": ["2023-01-01"] * 3,
            "valid_to": ["2024-12-31"] * 3,
            "share_class_id": ["A", "A", "A"],
            "evidence_url": ["https://example.org/direct"] * 3,
            "evidence_kind": ["direct_identifier_history"] * 3,
            "source_id": ["public_direct_history"] * 3,
            "source_retrieved_at": ["2026-08-15T00:00:00Z"] * 3,
            "source_sha256": ["a" * 64, "b" * 64, "c" * 64],
            "zero_cost_authorized": [True] * 3,
        }
    )


def _reference_spine() -> pd.DataFrame:
    rows = []
    for month in pd.period_range("2023-01", "2024-12", freq="M"):
        for permno in (10001, 10002, 10003, 10004):
            rows.append({"permno": permno, "yyyymm": month.strftime("%Y%m")})
    return pd.DataFrame(rows)


def test_bridge_rejects_ticker_only_and_target_derived_evidence() -> None:
    module = _module()
    with pytest.raises(module.IdentityGateError, match="canonical_security_id"):
        module.validate_bridge(pd.DataFrame({"ticker": ["AAA"], "permno": [10001]}))

    frame = _valid_bridge()
    frame["evidence_kind"] = "openap_characteristic_match"
    with pytest.raises(module.IdentityGateError, match="target-derived"):
        module.validate_bridge(frame)


def test_bridge_rejects_overlapping_many_to_one_intervals() -> None:
    module = _module()
    frame = pd.concat([_valid_bridge(), _valid_bridge().iloc[[0]]], ignore_index=True)
    frame.loc[3, "canonical_security_id"] = "sec:other"
    frame.loc[3, "source_sha256"] = "d" * 64

    with pytest.raises(module.IdentityGateError, match="overlap"):
        module.validate_bridge(frame)


def test_bridge_rejects_non_free_and_invalid_hash() -> None:
    module = _module()
    frame = _valid_bridge()
    frame.loc[0, "zero_cost_authorized"] = False
    with pytest.raises(module.IdentityGateError, match="zero-cost"):
        module.validate_bridge(frame)

    frame = _valid_bridge()
    frame.loc[0, "source_sha256"] = "not-a-hash"
    with pytest.raises(module.IdentityGateError, match="SHA-256"):
        module.validate_bridge(frame)


def test_freeze_is_stable_across_input_row_order(tmp_path: Path) -> None:
    module = _module()
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    manifest_a = module.freeze_bridge(_valid_bridge(), first)
    manifest_b = module.freeze_bridge(
        _valid_bridge().sample(frac=1.0, random_state=7), second
    )

    assert manifest_a.bridge_sha256 == manifest_b.bridge_sha256
    assert manifest_a.rows == 3
    assert manifest_a.frozen_before_reference_read is True
    assert first.read_bytes() == second.read_bytes()


def test_coverage_requires_every_month_and_seventy_percent(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "bridge.parquet"
    manifest = module.freeze_bridge(_valid_bridge(), output)
    frozen = pd.read_parquet(output)

    decision = module.evaluate_bridge_coverage(
        frozen, _reference_spine(), manifest=manifest
    )

    assert decision.minimum_monthly_coverage == pytest.approx(0.75)
    assert decision.median_monthly_coverage == pytest.approx(0.75)
    assert decision.ambiguous_links == 0
    assert decision.required_months == 24
    assert decision.status == "pass"


def test_coverage_fails_if_one_month_is_below_threshold(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "bridge.parquet"
    manifest = module.freeze_bridge(_valid_bridge(), output)
    reference = _reference_spine()
    extra = pd.DataFrame(
        {"permno": range(20000, 20020), "yyyymm": ["202401"] * 20}
    )

    decision = module.evaluate_bridge_coverage(
        pd.read_parquet(output),
        pd.concat([reference, extra], ignore_index=True),
        manifest=manifest,
    )

    assert decision.minimum_monthly_coverage < 0.70
    assert decision.status == "blocked_identity"


def test_coverage_rejects_unfrozen_bridge() -> None:
    module = _module()
    manifest = module.BridgeManifest(
        rows=3,
        min_valid_from="2023-01-01T00:00:00+00:00",
        max_valid_to="2024-12-31T00:00:00+00:00",
        bridge_sha256="a" * 64,
        frozen_before_reference_read=False,
    )

    with pytest.raises(module.IdentityGateError, match="frozen"):
        module.evaluate_bridge_coverage(
            _valid_bridge(), _reference_spine(), manifest=manifest
        )


def _runner_args(output_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        acquisition_matrix=ROOT / "docs" / "OPENAP_149_ACQUISITION_MATRIX.csv",
        reaudit=ROOT / "docs" / "OPENAP_181_CURRENT_FREE_SOURCE_REAUDIT_2026-08-09.csv",
        feasibility_contract=ROOT / "config" / "openap_149_feasibility.yaml",
        identity_sources=ROOT / "config" / "openap_149_identity_sources.yaml",
        candidate_bridge=None,
        reference_spine=None,
        output_dir=output_dir,
        repository_sha="f" * 40,
    )


def test_runner_without_candidate_bridge_emits_valid_no_go(tmp_path: Path) -> None:
    runner = _runner_module()

    assert runner.run(_runner_args(tmp_path)) == 0

    decision = json.loads(
        (tmp_path / "openap_identity_gate_decision.json").read_text(encoding="utf-8")
    )
    assert decision["status"] == "blocked_identity"
    assert decision["strictly_approved"] == 0
    assert decision["pilot_authorized"] is False
    assert decision["reason"] == (
        "no_authorized_zero_cost_historical_permno_bridge"
    )
    assert decision["locked_opened"] is False
    assert decision["validation_used_for_identity"] is False


def test_runner_artifacts_reconcile_and_remain_fail_closed(tmp_path: Path) -> None:
    runner = _runner_module()
    assert runner.run(_runner_args(tmp_path)) == 0

    register = pd.read_csv(tmp_path / "openap_149_feasibility_register.csv")
    sources = pd.read_csv(tmp_path / "openap_149_identity_source_audit.csv")
    bridge = pd.read_parquet(tmp_path / "openap_permno_bridge.parquet")
    audit = pd.read_csv(tmp_path / "openap_permno_bridge_audit.csv")
    summary = json.loads(
        (tmp_path / "openap_149_feasibility_summary.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(
        (tmp_path / "openap_permno_bridge_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(register) == 149
    assert register["feasibility_class"].value_counts().to_dict() == {
        "unproved": 142,
        "blocked_source": 6,
        "not_evaluable_reference": 1,
    }
    assert summary["strictly_approved"] == 0
    assert summary["previously_calculated_non_strict"] == 115
    assert len(sources) == 7 and not sources["route_pass"].any()
    assert bridge.empty and audit.empty
    assert manifest["rows"] == 0
    assert manifest["frozen_before_reference_read"] is False
    assert len(manifest["bridge_sha256"]) == 64
    assert (tmp_path / "openap_149_feasibility_summary.md").stat().st_size > 0


def test_existing_workflow_has_isolated_identity_mode() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]

    identity = jobs["identity_feasibility"]
    assert identity["needs"] == "validate"
    assert identity["if"] == (
        "${{ inputs.proxy_panel_url == 'IDENTITY_FEASIBILITY_ONLY' }}"
    )
    assert "run_openap_149_identity_gate.py" in workflow_text
    assert jobs["audit"]["if"] == (
        "${{ inputs.proxy_panel_url != 'IDENTITY_FEASIBILITY_ONLY' }}"
    )
    upload = next(
        step
        for step in identity["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["with"]["name"] == "openap-149-identity-feasibility-results"
    assert upload["with"]["retention-days"] == "30"
