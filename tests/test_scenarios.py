"""Tests for aurora.validation.scenarios."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.costs import ZERO_costs
from aurora.strategies.library.ma_cross import MACross
from aurora.validation.scenarios import (
    CrashScenario,
    KNOWN_CRASHES,
    StressResult,
    amplify_scenario,
    custom_scenario,
    replay_crash,
    stress_test_all_known,
)


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2010-01-01", periods=2000, freq="B")
    rets = np.random.default_rng(42).normal(0.0005, 0.012, 2000)
    p = 100 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _factory():
    return lambda: MACross(fast=10, slow=50)


def test_known_crashes_exist():
    """All 6 expected scenario keys must be present and well-formed."""
    expected = {
        "1987_black_monday",
        "1998_ltcm",
        "2000_dotcom",
        "2008_gfc",
        "2020_covid",
        "2022_drawdown",
    }
    assert expected.issubset(set(KNOWN_CRASHES.keys()))
    for key in expected:
        s = KNOWN_CRASHES[key]
        assert isinstance(s, CrashScenario)
        assert s.duration_days == len(s.return_path)
        assert s.duration_days > 0
        assert s.peak_to_trough < 0.0, f"{key} should have negative cumulative drop"


def test_replay_crash_basic(fake_prices):
    """Synthetic strategy + crash injection => StressResult with changed metrics."""
    set_global_seed(42)
    res = replay_crash(_factory(), fake_prices, KNOWN_CRASHES["2020_covid"])
    assert isinstance(res, StressResult)
    assert res.scenario_name == "2020_covid"
    assert "cagr" in res.base_metrics
    assert "mdd" in res.stressed_metrics
    # Metrics should differ (crash actually injected)
    assert res.base_metrics != res.stressed_metrics


def test_replay_increases_mdd(fake_prices):
    """For a long-only strategy, splicing a crash must not improve MDD."""
    set_global_seed(42)
    long_only_factory = lambda: MACross(fast=10, slow=50, allow_short=False)
    res = replay_crash(long_only_factory, fake_prices, KNOWN_CRASHES["2008_gfc"])
    base_mdd = res.base_metrics["mdd"]
    s_mdd = res.stressed_metrics["mdd"]
    # mdd is negative; "deeper" = smaller (more negative). A long-only strategy
    # cannot benefit from extra downside, so the stressed MDD must be <= base.
    assert s_mdd <= base_mdd + 1e-9, (
        f"stressed mdd {s_mdd} should be <= base mdd {base_mdd}"
    )


def test_stress_test_all_known(fake_prices):
    """stress_test_all_known returns a result for every fitting scenario."""
    set_global_seed(42)
    results = stress_test_all_known(_factory(), fake_prices)
    assert isinstance(results, dict)
    # All 7 scenarios fit in a 2000-bar series (1987, 1998 LTCM, 2000 dotcom,
    # 2008 GFC, 2010 flash crash, 2020 COVID, 2022 drawdown)
    assert len(results) == 7
    for key, res in results.items():
        assert isinstance(res, StressResult)
        assert res.scenario_name == key


def test_custom_scenario_built_from_returns():
    """custom_scenario wraps a returns series into a CrashScenario."""
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    rets = pd.Series([-0.02, -0.03, -0.05, 0.01, -0.04,
                      -0.02, -0.06, 0.03, -0.05, -0.02], index=idx)
    s = custom_scenario(rets, name="my_scenario", description="test")
    assert s.name == "my_scenario"
    assert s.duration_days == 10
    assert s.peak_to_trough < 0.0
    assert np.allclose(s.return_path, rets.values)
    assert s.description == "test"


def test_amplify_scenario_doubles_drop(fake_prices):
    """Amplifying a scenario by 2.0 should roughly double the cumulative drop."""
    base = KNOWN_CRASHES["2020_covid"]
    amp = amplify_scenario(base, factor=2.0)
    assert amp.duration_days == base.duration_days
    # Each return doubled, so cumulative drop is more severe
    assert amp.peak_to_trough < base.peak_to_trough
    assert np.allclose(amp.return_path, base.return_path * 2.0)


def test_survived_threshold(fake_prices):
    """A heavily amplified crash should fail the survived flag."""
    set_global_seed(42)
    # Amplify GFC by 3x and use a strict threshold so it cannot survive
    deep = amplify_scenario(KNOWN_CRASHES["2008_gfc"], factor=3.0)
    res = replay_crash(_factory(), fake_prices, deep, survived_threshold=-0.30)
    # Stressed mdd should be deeper than -30%, so survived is False
    assert res.stressed_metrics["mdd"] < -0.30
    assert res.survived is False


def test_replay_inject_at_specific_date(fake_prices):
    """Explicit inject_at timestamp routes to a different splice index."""
    set_global_seed(42)
    early_ts = fake_prices.index[200]
    late_ts = fake_prices.index[1500]
    r_early = replay_crash(_factory(), fake_prices, KNOWN_CRASHES["2020_covid"],
                           inject_at=early_ts)
    r_late = replay_crash(_factory(), fake_prices, KNOWN_CRASHES["2020_covid"],
                          inject_at=late_ts)
    # At minimum, stressed metrics should differ when crash hits at different times
    assert r_early.stressed_metrics != r_late.stressed_metrics
