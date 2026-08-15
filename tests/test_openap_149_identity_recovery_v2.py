from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import datetime, timezone
from importlib import util
from pathlib import Path

import pandas as pd
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "config" / "openap_149_identity_sources_v2.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "openap-proxy-real-correlation-audit.yml"
MODULE_NAME = "aurora.research.openap_149.identity_recovery_v2"


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
