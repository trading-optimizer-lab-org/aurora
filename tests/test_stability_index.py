"""Tests for validation.stability_index (R98)."""
from __future__ import annotations

from aurora.validation.stability_index import (
    StabilityComponents,
    stability_index,
)


def test_full_inputs_produce_composite_in_unit_interval():
    comps = StabilityComponents(
        spp_cv=0.15,
        wf_calmar_std=0.20,
        mc_trade_reorder_spread=0.10,
        scenarios_pass_rate=0.85,
        pbo_probability=0.20,
    )
    s = stability_index(comps)
    assert 0.0 <= s.composite <= 1.0
    assert all(
        0.0 <= sub <= 1.0
        for sub in (s.spp_subscore, s.wf_subscore, s.mc_subscore,
                    s.scenario_subscore, s.pbo_subscore)
    )


def test_lower_spp_cv_yields_higher_subscore():
    a = stability_index(StabilityComponents(spp_cv=0.05))
    b = stability_index(StabilityComponents(spp_cv=0.50))
    assert a.spp_subscore > b.spp_subscore


def test_higher_scenario_pass_rate_yields_higher_subscore():
    a = stability_index(StabilityComponents(scenarios_pass_rate=0.95))
    b = stability_index(StabilityComponents(scenarios_pass_rate=0.30))
    assert a.scenario_subscore > b.scenario_subscore


def test_missing_components_collapse_to_neutral_composite():
    s = stability_index(StabilityComponents())
    # All neutral 0.5 -> geometric mean = 0.5.
    assert abs(s.composite - 0.5) < 1e-9


def test_one_very_weak_component_drags_composite():
    """Geometric mean penalises a single weak sub-score harder than
    the arithmetic mean would."""
    strong = StabilityComponents(
        spp_cv=0.05,
        wf_calmar_std=0.05,
        mc_trade_reorder_spread=0.05,
        scenarios_pass_rate=0.95,
        pbo_probability=0.05,
    )
    one_weak = StabilityComponents(
        spp_cv=0.05,
        wf_calmar_std=0.05,
        mc_trade_reorder_spread=0.05,
        scenarios_pass_rate=0.05,
        pbo_probability=0.05,
    )
    s_strong = stability_index(strong)
    s_weak = stability_index(one_weak)
    assert s_strong.composite > s_weak.composite + 0.1
