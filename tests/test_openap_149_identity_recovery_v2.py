from __future__ import annotations

import importlib
from importlib import util
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "config" / "openap_149_identity_sources_v2.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "openap-proxy-real-correlation-audit.yml"
MODULE_NAME = "aurora.research.openap_149.identity_recovery_v2"


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

