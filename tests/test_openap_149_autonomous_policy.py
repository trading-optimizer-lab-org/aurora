from pathlib import Path

import yaml


POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "openap_149_autonomous_reconstruction.yaml"
)


def _load_policy() -> dict:
    with POLICY_PATH.open("r", encoding="utf-8") as handle:
        policy = yaml.safe_load(handle)
    assert isinstance(policy, dict)
    return policy


def test_policy_fails_closed_instead_of_claiming_openap_equivalence() -> None:
    """Catches a policy that admits reconstructed values as strict OpenAP values."""
    policy = _load_policy()

    assert policy["target_count"] == 149
    assert policy["calculation_classes"] == [
        "formula_exacta",
        "aproximacion_solida",
        "bloqueada_gratis",
    ]
    assert policy["strict_stock_level_equivalence"] is False
    assert policy["strict_score_eligible_default"] is False


def test_policy_uses_signal_specific_coverage_for_broad_signals() -> None:
    """Catches reuse of the old global-universe coverage denominator."""
    policy = _load_policy()

    assert policy["broad_signal_gate"] == {
        "minimum_valid_securities": 500,
        "minimum_source_eligible_coverage": 0.70,
        "denominator": "signal_source_eligible_universe",
    }


def test_policy_caps_approximations_and_freezes_portfolio_diagnostic() -> None:
    """Catches an extended score that lets proxies dominate or tunes on OpenAP."""
    policy = _load_policy()

    assert 0.0 < policy["extended_score"]["approximation_weight_cap"] <= 0.25
    assert policy["portfolio_behaviour"]["minimum_overlap_months"] >= 24
    assert policy["portfolio_behaviour"]["high_similarity_spearman"] == 0.90
    assert policy["portfolio_behaviour"]["may_tune_formula_or_source"] is False
    assert policy["portfolio_behaviour"]["implies_stock_level_fidelity"] is False


def test_policy_keeps_protected_tiers_closed() -> None:
    """Catches accidental OOS or forward access in the reconstruction campaign."""
    policy = _load_policy()

    assert policy["oos_locked"] is True
    assert policy["forward_locked"] is True
    assert "unlock" not in " ".join(policy.keys()).lower()


def test_policy_prioritises_authorised_zero_cost_sources() -> None:
    """Catches paid or formula-target data being promoted ahead of public sources."""
    policy = _load_policy()

    assert policy["source_priority"] == [
        "official_public_api_or_bulk",
        "official_public_html_or_filing",
        "public_academic_with_affirmative_terms",
        "preserved_licensed_internal_artifact",
        "terminal_evidence_backed_block",
    ]
    assert policy["openap_usage"] == [
        "pinned_formula",
        "orientation",
        "public_portfolio_rules",
        "public_portfolio_returns_diagnostic_only",
    ]
    assert policy["openap_stock_level_values_allowed"] is False

