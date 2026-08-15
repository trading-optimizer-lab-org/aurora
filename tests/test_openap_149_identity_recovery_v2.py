from __future__ import annotations

import argparse
import importlib
from dataclasses import replace
from datetime import datetime, timezone
from importlib import util
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "config" / "openap_149_identity_sources_v2.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "openap-proxy-real-correlation-audit.yml"
MODULE_NAME = "aurora.research.openap_149.identity_recovery_v2"
RUNNER = ROOT / "scripts" / "run_openap_149_identity_recovery_v2.py"


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        url: str = "https://example.test/data.csv",
        status_code: int = 200,
        content_type: str = "text/csv; charset=utf-8",
    ) -> None:
        self._body = body
        self.url = url
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.history: list[object] = []

    def iter_content(self, chunk_size: int = 65_536):
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset : offset + chunk_size]


def _module():
    assert util.find_spec(MODULE_NAME) is not None, (
        "identity_recovery_v2 must implement the frozen recovery contract"
    )
    return importlib.import_module(MODULE_NAME)


def _runner_module():
    assert RUNNER.exists(), "the v2 GitHub-only runner must exist"
    spec = util.spec_from_file_location("run_openap_149_identity_recovery_v2", RUNNER)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_catalogue_has_fifteen_explicit_unique_routes() -> None:
    module = _module()
    sources = module.load_recovery_catalog(CATALOGUE)

    assert len(sources) == 15
    assert len({source.source_id for source in sources}) == 15
    assert all(source.documentary_blocker for source in sources)


def test_v2_catalogue_reconciles_to_fail_closed_terminal_classes() -> None:
    module = _module()
    sources = module.load_recovery_catalog(CATALOGUE)
    classes: dict[str, int] = {}
    for source in sources:
        terminal = module.classify_source(source, None)
        classes[terminal] = classes.get(terminal, 0) + 1

    assert classes == {
        "blocked_access": 4,
        "blocked_rights": 3,
        "blocked_schema": 5,
        "blocked_semantics": 2,
        "blocked_target_derived": 1,
    }


def test_target_fingerprint_is_always_disqualified() -> None:
    module = _module()
    source = next(
        item
        for item in module.load_recovery_catalog(CATALOGUE)
        if item.source_id == "openap_characteristic_fingerprint"
    )

    assert module.classify_source(source, None) == "blocked_target_derived"


def test_static_wrds_derived_table_is_not_licensed_by_repository_license() -> None:
    module = _module()
    source = next(
        item
        for item in module.load_recovery_catalog(CATALOGUE)
        if item.source_id == "std_security_code"
    )

    assert module.classify_source(source, None) == "blocked_rights"


def test_small_michels_table_is_rejected_for_identity_semantics() -> None:
    module = _module()
    source = next(
        item
        for item in module.load_recovery_catalog(CATALOGUE)
        if item.source_id == "michels_2017"
    )

    assert module.classify_source(source, None) == "blocked_semantics"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"public_zero_cost": "yes"}, "boolean"),
        ({"evidence_url": "http://example.test/data"}, "HTTPS"),
        ({"probe_policy": "unbounded"}, "probe_policy"),
        ({"parser": "guess_columns"}, "parser"),
        ({"documentary_blocker": ""}, "documentary_blocker"),
    ],
)
def test_catalogue_rejects_implicit_or_unsafe_contract_values(
    tmp_path: Path,
    mutation: dict[str, object],
    match: str,
) -> None:
    module = _module()
    payload = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    payload["sources"][0].update(mutation)
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(module.IdentityRecoveryError, match=match):
        module.load_recovery_catalog(path)


def test_catalogue_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    module = _module()
    payload = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    payload["sources"][1]["source_id"] = payload["sources"][0]["source_id"]
    path = tmp_path / "duplicate.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(module.IdentityRecoveryError, match="duplicate"):
        module.load_recovery_catalog(path)


def test_documentary_only_source_never_calls_the_network() -> None:
    module = _module()
    source = next(
        item
        for item in module.load_recovery_catalog(CATALOGUE)
        if item.source_id == "crsp_research_products"
    )

    def forbidden_getter(*args, **kwargs):
        raise AssertionError("documentary-only routes must not call the network")

    receipt = module.probe_source(
        source,
        getter=forbidden_getter,
        now=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
    )

    assert receipt.attempted is False
    assert receipt.bytes_observed == 0
    assert receipt.error == "documentary_only"


def test_small_csv_probe_is_bounded_hashed_and_schema_observed() -> None:
    module = _module()
    source = next(
        item
        for item in module.load_recovery_catalog(CATALOGUE)
        if item.source_id == "michels_2017"
    )
    body = b"cusip,cik,permno\r\n12345678,1,10001\r\n"

    receipt = module.probe_source(
        source,
        getter=lambda *args, **kwargs: _Response(body),
        now=lambda: datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    assert receipt.attempted is True
    assert receipt.status_code == 200
    assert receipt.bytes_observed == 36
    assert receipt.sha256 == (
        "b2c3a9d40afea0dcd349b131efd8498cf9df7f3a07bcff2be195ef712f8b60e2"
    )
    assert receipt.observed_columns == ("cusip", "cik", "permno")
    assert receipt.error == ""


def test_probe_rejects_redirect_to_login_or_payment() -> None:
    module = _module()
    source = next(
        item
        for item in module.load_recovery_catalog(CATALOGUE)
        if item.source_id == "michels_2017"
    )
    response = _Response(
        b"login required",
        url="https://vendor.example/account/login?next=data",
        content_type="text/html",
    )

    receipt = module.probe_source(
        replace(source, retrieval_url="https://vendor.example/data.csv"),
        getter=lambda *args, **kwargs: response,
        now=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
    )

    assert receipt.attempted is True
    assert receipt.final_url == "https://vendor.example/account/login"
    assert receipt.error == "redirected_to_login_or_payment"


def test_no_passing_route_builds_canonical_empty_bridge() -> None:
    module = _module()
    audit = pd.DataFrame(
        [{"source_id": "blocked", "terminal_class": "blocked_schema"}]
    )

    bridge = module.build_candidate_bridge(audit, {})

    assert bridge.empty
    assert list(bridge.columns) == list(module.BRIDGE_COLUMNS)


def _source_response(url: str) -> _Response:
    if url.endswith("company_tickers_exchange.json"):
        return _Response(
            b'{"fields":["cik","name","ticker","exchange"],"data":[]}',
            url=url,
            content_type="application/json",
        )
    if url.endswith("michels-2017.csv"):
        return _Response(
            b"cusip,eventdate,cik,permno,gvkey\r\n12345678,2016-01-01,1,10001,1\r\n",
            url=url,
        )
    if url.endswith(".pdf"):
        return _Response(
            b"%PDF-1.4 bounded sample evidence",
            url=url,
            content_type="application/pdf",
        )
    if url.endswith(".md"):
        return _Response(
            b"Public project evidence page",
            url=url,
            content_type="text/plain",
        )
    return _Response(
        b"<html><body>Public evidence page</body></html>",
        url=url,
        content_type="text/html",
    )


def test_runner_emits_reconciled_no_candidate_bundle(tmp_path: Path) -> None:
    runner = _runner_module()
    output = tmp_path / "out"
    args = argparse.Namespace(
        catalogue=CATALOGUE,
        output_dir=output,
        repository_sha="f" * 40,
        reference_spine=None,
    )

    assert runner.run(
        args,
        getter=lambda url, **kwargs: _source_response(url),
        now=lambda: datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    ) == 0

    decision = json.loads(
        (output / "openap_149_identity_recovery_v2_decision.json").read_text(
            encoding="utf-8"
        )
    )
    audit = pd.read_csv(output / "openap_149_identity_sources_v2_audit.csv")
    receipts = [
        json.loads(line)
        for line in (
            output / "openap_149_identity_source_probe_receipts.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(
        (output / "openap_149_identity_source_evidence_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    bridge = pd.read_parquet(output / "openap_permno_bridge_v2.parquet")
    coverage = pd.read_csv(
        output / "openap_permno_bridge_v2_monthly_coverage.csv"
    )

    assert decision["status"] == "blocked_identity_v2"
    assert decision["pilot_authorized"] is False
    assert decision["strictly_approved"] == 0
    assert decision["candidate_routes"] == 0
    assert decision["bridge_rows"] == 0
    assert decision["locked_opened"] is False
    assert decision["target_derived_used_for_identity"] is False
    assert decision["repository_sha"] == "f" * 40
    assert decision["route_class_counts"] == {
        "blocked_access": 4,
        "blocked_rights": 3,
        "blocked_schema": 5,
        "blocked_semantics": 2,
        "blocked_target_derived": 1,
    }
    assert len(audit) == 15
    assert len(receipts) == 15
    assert sum(decision["route_class_counts"].values()) == 15
    assert manifest["catalogue_source_count"] == 15
    assert manifest["probe_receipt_count"] == 15
    assert manifest["evidence_snapshot_count"] == 10
    assert bridge.empty
    assert list(bridge.columns) == list(_module().BRIDGE_COLUMNS)
    assert coverage.empty
    assert (output / "openap_149_identity_recovery_v2_summary.md").stat().st_size > 0


def _passing_catalogue(path: Path) -> None:
    payload = {
        "dataset_id": "openap_149_identity_sources_v2",
        "checked_at": "2026-08-15",
        "sources": [
            {
                "source_id": "public_direct_history",
                "evidence_url": "https://example.test/evidence",
                "retrieval_url": "https://example.test/bridge.csv",
                "probe_policy": "download_small",
                "expected_media_type": "csv",
                "parser": "canonical_bridge_csv",
                "public_access_without_login": True,
                "public_zero_cost": True,
                "authorized_for_internal_research": True,
                "upstream_license_required": False,
                "provides_permno": True,
                "provides_public_security_id": True,
                "historical_intervals": True,
                "share_class_specific": True,
                "covers_2023_2024": True,
                "broad_universe": True,
                "target_derived": False,
                "upstream_provenance": "Direct public identifier history",
                "universe_limit": "Broad US equity security universe",
                "documentary_blocker": "none_after_executable_probe",
            }
        ],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _canonical_bridge_csv() -> bytes:
    columns = list(_module().BRIDGE_COLUMNS)
    rows = []
    for index, permno in enumerate((10001, 10002, 10003), start=1):
        rows.append(
            {
                "canonical_security_id": f"sec:{index}",
                "permno": permno,
                "valid_from": "2023-01-01",
                "valid_to": "2024-12-31",
                "share_class_id": "A",
                "evidence_url": "https://example.test/evidence",
                "evidence_kind": "direct_identifier_history",
                "source_id": "public_direct_history",
                "source_retrieved_at": "2026-08-15T12:00:00Z",
                "source_sha256": str(index) * 64,
                "zero_cost_authorized": True,
            }
        )
    return pd.DataFrame(rows, columns=columns).to_csv(index=False).encode("utf-8")


def test_runner_freezes_bridge_before_identifier_only_coverage(tmp_path: Path) -> None:
    runner = _runner_module()
    catalogue = tmp_path / "passing.yaml"
    _passing_catalogue(catalogue)
    reference = tmp_path / "reference.csv"
    reference_rows = [
        {"permno": permno, "yyyymm": month.strftime("%Y%m")}
        for month in pd.period_range("2023-01", "2024-12", freq="M")
        for permno in (10001, 10002, 10003, 10004)
    ]
    pd.DataFrame(reference_rows).to_csv(reference, index=False)
    output = tmp_path / "pass"
    args = argparse.Namespace(
        catalogue=catalogue,
        output_dir=output,
        repository_sha="e" * 40,
        reference_spine=reference,
    )
    bridge_body = _canonical_bridge_csv()

    assert runner.run(
        args,
        getter=lambda url, **kwargs: _Response(bridge_body, url=url),
        now=lambda: datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    ) == 0

    decision = json.loads(
        (output / "openap_149_identity_recovery_v2_decision.json").read_text(
            encoding="utf-8"
        )
    )
    bridge_manifest = json.loads(
        (output / "openap_permno_bridge_v2_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    coverage = pd.read_csv(
        output / "openap_permno_bridge_v2_monthly_coverage.csv"
    )

    assert decision["status"] == "identity_pass"
    assert decision["pilot_authorized"] is True
    assert decision["candidate_routes"] == 1
    assert decision["bridge_rows"] == 3
    assert decision["minimum_monthly_coverage"] == pytest.approx(0.75)
    assert bridge_manifest["frozen_before_reference_read"] is True
    assert len(coverage) == 24
    assert coverage["coverage"].eq(0.75).all()


def test_workflow_routes_v2_to_an_isolated_job() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    recovery = jobs["identity_source_recovery_v2"]

    assert recovery["needs"] == "validate"
    assert recovery["if"] == (
        "${{ inputs.proxy_panel_url == 'IDENTITY_SOURCE_RECOVERY_V2' }}"
    )
    assert jobs["audit"]["if"] == (
        "${{ inputs.proxy_panel_url != 'IDENTITY_FEASIBILITY_ONLY' && "
        "inputs.proxy_panel_url != 'IDENTITY_SOURCE_RECOVERY_V2' }}"
    )
    upload = next(
        step
        for step in recovery["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["with"]["name"] == "openap-149-identity-recovery-v2-results"
    assert upload["with"]["retention-days"] == "30"
