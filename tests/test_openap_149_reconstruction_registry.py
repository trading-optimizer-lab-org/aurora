from pathlib import Path

import pandas as pd
import pytest

from aurora.research.openap_149.reconstruction_registry import (
    RegistryError,
    build_registry,
    load_policy,
    validate_registry,
)


POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "openap_149_autonomous_reconstruction.yaml"
)


def _complete_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    acquisition_rows: list[dict[str, object]] = []
    formula_rows: list[dict[str, object]] = []
    for index in range(149):
        signal = f"Signal{index:03d}"
        acquisition_rows.append(
            {
                "signal": signal,
                "category": "Accounting",
                "official_formula_url": f"https://example.test/formulas/{signal}.do",
                "official_formula_sha256": "a" * 64,
                "required_inputs": "assets|sales",
                "source_used": "sec_companyfacts",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/",
                "license_terms": "SEC public data",
                "current_value_calculated": True,
                "strict_score_eligible": False,
                "status": "current_signal_computed",
                "remaining_blocker": "",
            }
        )
        formula_rows.append(
            {
                "signal": signal,
                "orientation": 1,
                "lookback": "12m",
                "point_in_time_rule": "filing_acceptance_time_before_formation",
                "maximum_staleness_days": 550,
                "source_eligible_universe_rule": "sec_filers_with_required_tags",
                "applicability_class": "broad",
                "implementation_id": f"accounting:{signal}:v1",
                "formula_semantics_match": True,
                "independent_source_allowed": True,
                "point_in_time_implemented": True,
                "proxy_economically_close": False,
                "semantic_difference": "",
                "terminal_free_blocker": "",
            }
        )

    formula_rows[1]["formula_semantics_match"] = False
    formula_rows[1]["proxy_economically_close"] = True
    formula_rows[1]["semantic_difference"] = "uses_public_total_debt_for_wrds_debt"

    acquisition_rows[2]["current_value_calculated"] = False
    acquisition_rows[2]["status"] = "blocked_source_failure"
    acquisition_rows[2]["remaining_blocker"] = "required_history_not_public"
    formula_rows[2]["formula_semantics_match"] = False
    formula_rows[2]["independent_source_allowed"] = False
    formula_rows[2]["point_in_time_implemented"] = False
    formula_rows[2]["terminal_free_blocker"] = "required_history_not_public"

    return pd.DataFrame(acquisition_rows), pd.DataFrame(formula_rows)


def test_registry_reconciles_149_unique_signals_into_three_honest_classes() -> None:
    """Catches dropped targets or legacy proxies promoted without a declared class."""
    acquisition, formulas = _complete_inputs()
    policy = load_policy(POLICY_PATH)

    registry = build_registry(acquisition, formulas, policy)

    assert len(registry) == 149
    assert registry["signal"].nunique() == 149
    assert registry["calculation_class"].value_counts().to_dict() == {
        "formula_exacta": 147,
        "aproximacion_solida": 1,
        "bloqueada_gratis": 1,
    }
    assert not registry["strict_score_eligible"].any()
    assert set(registry["score_admission_state"]) == {"pending_quality_gate"}


def test_registry_retains_formula_source_and_point_in_time_contract() -> None:
    """Catches a registry that cannot reproduce why a signal was classified."""
    acquisition, formulas = _complete_inputs()

    registry = build_registry(acquisition, formulas, load_policy(POLICY_PATH))
    row = registry.set_index("signal").loc["Signal000"]

    assert row["official_formula_sha256"] == "a" * 64
    assert row["required_inputs"] == "assets|sales"
    assert row["orientation"] == 1
    assert row["point_in_time_rule"] == "filing_acceptance_time_before_formation"
    assert row["source_eligible_universe_rule"] == "sec_filers_with_required_tags"
    assert row["implementation_id"] == "accounting:Signal000:v1"


def test_registry_rejects_duplicate_or_missing_targets() -> None:
    """Catches silent one-to-many merges and incomplete 149-row campaigns."""
    acquisition, formulas = _complete_inputs()
    acquisition.loc[148, "signal"] = "Signal147"

    with pytest.raises(RegistryError, match="149 unique"):
        build_registry(acquisition, formulas, load_policy(POLICY_PATH))


def test_registry_rejects_blank_or_malformed_formula_hashes() -> None:
    """Catches formula drift hidden behind an unpinned URL."""
    acquisition, formulas = _complete_inputs()
    acquisition.loc[0, "official_formula_sha256"] = ""

    with pytest.raises(RegistryError, match="formula SHA-256"):
        build_registry(acquisition, formulas, load_policy(POLICY_PATH))


def test_registry_rejects_unvalidated_proxy_instead_of_guessing() -> None:
    """Catches an old numeric proxy being called solid without semantic evidence."""
    acquisition, formulas = _complete_inputs()
    formulas.loc[1, "proxy_economically_close"] = False

    with pytest.raises(RegistryError, match="cannot be classified"):
        build_registry(acquisition, formulas, load_policy(POLICY_PATH))


def test_registry_rejects_any_preapproved_strict_signal() -> None:
    """Catches stock-level equivalence entering through an old ledger boolean."""
    acquisition, formulas = _complete_inputs()
    acquisition.loc[0, "strict_score_eligible"] = True

    with pytest.raises(RegistryError, match="strict"):
        build_registry(acquisition, formulas, load_policy(POLICY_PATH))


def test_validate_registry_rejects_tampered_terminal_rows() -> None:
    """Catches post-build changes that remove the exact blocker or formula pin."""
    acquisition, formulas = _complete_inputs()
    policy = load_policy(POLICY_PATH)
    registry = build_registry(acquisition, formulas, policy)
    registry.loc[registry["signal"].eq("Signal002"), "classification_reason"] = ""

    with pytest.raises(RegistryError, match="classification reason"):
        validate_registry(registry, policy)
