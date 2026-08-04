from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked
from aurora.research.openap_93.market import (
    beta_liquidity_ps,
    beta_vix,
    compound_lags,
    coskew_acx,
    coskewness_60m,
    ff3_month_residual_moments,
    price_delay_rsq,
    residual_momentum,
    zero_trade_measure,
)
from aurora.research.openap_93.models import SignalObservation
from aurora.research.openap_93.registry import REQUIRED_93, FidelityClass, load_signal_registry
from aurora.research.openap_93.sources import (
    IMPLEMENTED_SIGNAL_SOURCES,
    PUBLIC_SOURCES,
    select_sources_lexicographically,
    source_coverage_matrix,
)


CONFIG = Path("config/openap_93/signals_93.yaml")


def test_registry_contains_exactly_the_required_93() -> None:
    registry = load_signal_registry(CONFIG)
    assert set(REQUIRED_93) == set(registry)
    assert len(registry) == 93
    assert len(set(REQUIRED_93)) == 93


def test_every_signal_has_formula_inputs_sources_and_fidelity() -> None:
    registry = load_signal_registry(CONFIG)
    for signal in registry.values():
        assert signal.openap_script.startswith("Signals/pyCode/Predictors/")
        assert signal.required_inputs
        assert signal.natural_frequency
        assert isinstance(signal.expected_best_class, FidelityClass)
        if signal.expected_best_class is not FidelityClass.UNAVAILABLE:
            assert signal.candidate_sources


def test_every_candidate_source_is_registered() -> None:
    registry = load_signal_registry(CONFIG)
    source_ids = {source.source_id for source in PUBLIC_SOURCES}
    referenced = {item for signal in registry.values() for item in signal.candidate_sources}
    assert referenced <= source_ids


def test_source_selection_is_deterministic_and_reports_ablation() -> None:
    registry = load_signal_registry(CONFIG)
    probes = pd.DataFrame(
        {"source_id": [source.source_id for source in PUBLIC_SOURCES], "probe_ok": True}
    )
    matrix = source_coverage_matrix(registry, probes)
    selected_a, ablation_a = select_sources_lexicographically(matrix)
    selected_b, ablation_b = select_sources_lexicographically(matrix)
    assert selected_a == selected_b
    pd.testing.assert_frame_equal(ablation_a, ablation_b)
    assert selected_a["candidate_signals_covered"] == 0
    assert selected_a["candidate_signals_uncovered"] == sorted(REQUIRED_93)
    assert selected_a["selected_source_ids"] == []


def test_reachable_source_is_not_mistaken_for_implemented_signal() -> None:
    registry = load_signal_registry(CONFIG)
    probes = pd.DataFrame(
        {"source_id": [source.source_id for source in PUBLIC_SOURCES], "probe_ok": True}
    )
    matrix = source_coverage_matrix(registry, probes)
    assert IMPLEMENTED_SIGNAL_SOURCES == frozenset()
    assert matrix["candidate_match"].any()
    assert not matrix["formula_implemented"].any()
    assert not matrix["required_fields_verified"].any()
    assert not matrix["can_produce_value"].any()


def test_no_source_requires_registration_or_payment() -> None:
    assert all(not source.registration_required for source in PUBLIC_SOURCES)
    assert all(source.access_mode for source in PUBLIC_SOURCES)


def test_script_is_blocked_locally_without_explicit_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    from scripts.run_openap_93_max_free import main

    monkeypatch.setattr("sys.argv", ["run_openap_93_max_free.py", "probe-sources", "--output-dir", "unused"])
    with pytest.raises(LocalRunBlocked):
        main()


def test_signal_observation_only_marks_evidenced_classes_usable() -> None:
    observation = SignalObservation(
        formation_date="2026-07-31",
        symbol="AAPL",
        signal="Coskewness",
        value=0.25,
        fidelity=FidelityClass.RECONSTRUCTED,
        current_usable=True,
        formula_id="openap_coskewness_60m",
        source_ids=("yahoo_public", "kenneth_french"),
        data_available_at="2026-08-01T00:00:00Z",
        observation_count=60,
    )
    assert observation.to_record()["fidelity"] == "reconstructed"
    assert observation.to_record()["source_ids"] == "yahoo_public|kenneth_french"
    with pytest.raises(ValueError, match="current_usable"):
        SignalObservation(
            formation_date="2026-07-31",
            symbol="AAPL",
            signal="AOP",
            value=1.0,
            fidelity=FidelityClass.UNVALIDATED_PROXY,
            current_usable=True,
            formula_id="proxy",
            source_ids=("yahoo_public",),
            data_available_at="2026-08-01T00:00:00Z",
            observation_count=1,
        )


def test_market_formula_helpers_match_simple_known_cases() -> None:
    values = pd.Series([0.01] * 40)
    assert compound_lags(values, [1, 2, 3, 4, 5]) == pytest.approx(1.01**5 - 1)

    market = np.linspace(-0.04, 0.05, 60)
    stock = 0.5 * market + 4.0 * market**2
    assert coskewness_60m(stock, market) > 0

    daily_market = np.linspace(-0.03, 0.03, 252)
    daily_stock = 0.6 * daily_market + 3.0 * daily_market**2
    assert coskew_acx(daily_stock, daily_market) > 0


def test_factor_and_delay_formulas_are_causal_and_finite() -> None:
    rng = np.random.default_rng(7)
    n = 260
    market = rng.normal(0, 0.01, n)
    lagged = np.r_[0.0, market[:-1]]
    stock = 0.4 * market + 0.6 * lagged + rng.normal(0, 0.002, n)
    delay = price_delay_rsq(stock, market)
    assert delay is not None and delay > 0

    vix = rng.normal(0, 0.05, n)
    stock_vix = 0.3 * market - 0.8 * vix + rng.normal(0, 0.002, n)
    assert beta_vix(stock_vix, market, vix) == pytest.approx(-0.8, abs=0.15)

    smb = rng.normal(0, 0.01, n)
    hml = rng.normal(0, 0.01, n)
    idio, skew = ff3_month_residual_moments(
        stock_vix[-21:], market[-21:], smb[-21:], hml[-21:]
    )
    assert idio is not None and idio > 0
    assert skew is not None and np.isfinite(skew)


def test_long_window_formulas_and_zero_trade_measure() -> None:
    rng = np.random.default_rng(11)
    n = 90
    ps = rng.normal(0, 0.02, n)
    market = rng.normal(0, 0.03, n)
    smb = rng.normal(0, 0.02, n)
    hml = rng.normal(0, 0.02, n)
    stock = 1.7 * ps + 0.3 * market + rng.normal(0, 0.003, n)
    assert beta_liquidity_ps(stock, ps, market, smb, hml) == pytest.approx(1.7, abs=0.1)
    assert residual_momentum(stock, market, smb, hml) is not None

    volume = np.ones(21)
    volume[[1, 4, 9]] = 0
    turnover = np.full(21, 0.01)
    value = zero_trade_measure(volume, turnover, expected_days=21, deflator=480_000)
    assert value is not None and value > 2.9
