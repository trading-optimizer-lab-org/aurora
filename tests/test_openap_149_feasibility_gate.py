from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "openap_149_feasibility.yaml"
ACQUISITION_PATH = ROOT / "docs" / "OPENAP_149_ACQUISITION_MATRIX.csv"
REAUDIT_PATH = ROOT / "docs" / "OPENAP_181_CURRENT_FREE_SOURCE_REAUDIT_2026-08-09.csv"
IDENTITY_SOURCES_PATH = ROOT / "config" / "openap_149_identity_sources.yaml"


def _module():
    return importlib.import_module("aurora.research.openap_149.feasibility")


def _contract() -> dict[str, object]:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _identity_module():
    return importlib.import_module("aurora.research.openap_149.identity_sources")


def _register() -> pd.DataFrame:
    module = _module()
    return module.build_feasibility_register(
        pd.read_csv(ACQUISITION_PATH),
        pd.read_csv(REAUDIT_PATH),
        _contract(),
    )


def test_feasibility_register_reconciles_exactly_149() -> None:
    register = _register()

    assert len(register) == 149
    assert register["signal"].is_unique
    assert register["feasibility_class"].value_counts().to_dict() == {
        "unproved": 142,
        "blocked_source": 6,
        "not_evaluable_reference": 1,
    }
    assert not register["strict_score_eligible"].any()


def test_previously_calculated_never_means_approved() -> None:
    register = _register()
    calculated = register["current_value_calculated"]

    assert int(calculated.sum()) == 115
    assert register.loc[calculated, "feasibility_class"].ne("approved").all()


def test_summary_uses_only_independent_approval_count() -> None:
    module = _module()
    summary = module.summarize_feasibility(_register())

    assert summary["target_count"] == 149
    assert summary["strictly_approved"] == 0
    assert summary["previously_calculated_non_strict"] == 115
    assert summary["identity_gate_status"] == "not_run"


def test_unknown_override_fails_closed() -> None:
    module = _module()
    contract = _contract()
    contract["source_blocked_signals"]["NotARealSignal"] = "invalid"

    with pytest.raises(module.FeasibilityError, match="override"):
        module.build_feasibility_register(
            pd.read_csv(ACQUISITION_PATH),
            pd.read_csv(REAUDIT_PATH),
            contract,
        )


def test_existing_strict_approval_fails_closed() -> None:
    module = _module()
    acquisition = pd.read_csv(ACQUISITION_PATH)
    acquisition.loc[0, "strict_score_eligible"] = True

    with pytest.raises(module.FeasibilityError, match="strict_score_eligible"):
        module.build_feasibility_register(
            acquisition,
            pd.read_csv(REAUDIT_PATH),
            _contract(),
        )


def test_no_declared_route_currently_passes_all_identity_requirements() -> None:
    module = _identity_module()
    sources = module.load_identity_source_catalog(IDENTITY_SOURCES_PATH)
    decisions = module.evaluate_public_identity_routes(sources)

    assert len(decisions) == 7
    assert not decisions["route_pass"].any()
    openfigi = decisions.set_index("source_id").loc["openfigi"]
    assert {"provides_permno", "historical_intervals"} <= set(
        openfigi["missing_requirements"].split("|")
    )


def test_target_derived_source_can_never_build_bridge() -> None:
    module = _identity_module()
    sources = module.load_identity_source_catalog(IDENTITY_SOURCES_PATH)
    decisions = module.evaluate_public_identity_routes(sources)

    openap = decisions.set_index("source_id").loc["openap_stock_panel"]
    assert not bool(openap["route_pass"])
    assert "target_derived" in openap["disqualifiers"].split("|")


def test_identity_catalog_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    module = _identity_module()
    contract = yaml.safe_load(IDENTITY_SOURCES_PATH.read_text(encoding="utf-8"))
    contract["sources"].append(dict(contract["sources"][0]))
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(yaml.safe_dump(contract), encoding="utf-8")

    with pytest.raises(module.IdentitySourceError, match="duplicad"):
        module.load_identity_source_catalog(duplicate)
