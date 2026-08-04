from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked
from aurora.research.openap_93.registry import REQUIRED_93, FidelityClass, load_signal_registry
from aurora.research.openap_93.sources import PUBLIC_SOURCES, select_sources_lexicographically, source_coverage_matrix


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
    assert selected_a["candidate_signals_covered"] == 92
    assert selected_a["candidate_signals_uncovered"] == ["ProbInformedTrading"]


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
