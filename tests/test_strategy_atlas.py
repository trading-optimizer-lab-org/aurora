"""Tests for the strategy atlas + benchmark catalogue (Candidate E)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from aurora.research._atlas_seed import SEED_ENTRIES, load_seed_atlas
from aurora.research.strategy_atlas import (
    AtlasStatus,
    StrategyAtlas,
    StrategyAtlasEntry,
    query_before_promote,
)
from aurora.research.strategy_benchmarks import (
    BenchmarkExpectation,
    evaluate_against_benchmark,
)


def _good_kwargs(**overrides: object) -> dict[str, object]:
    """Minimal valid kwargs for :class:`StrategyAtlasEntry`."""
    base: dict[str, object] = dict(
        name="Test entry",
        asset_class="etf",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("multi_asset",),
        cost_sensitivity="low",
        overfit_risk="low",
        implementation_difficulty="easy",
        validation_gates=("walk_forward",),
        benchmark_expectation=BenchmarkExpectation.BUY_AND_HOLD.value,
        status=AtlasStatus.SUPPORTED,
        owner="research",
        notes="",
    )
    base.update(overrides)
    return base


# ---- Promotion gating ------------------------------------------------------


def test_blocked_entry_is_not_promotable() -> None:
    atlas = StrategyAtlas()
    entry = StrategyAtlasEntry(
        **_good_kwargs(
            name="Options-heavy",
            status=AtlasStatus.BLOCKED,
            notes="options chain data not available",
        )
    )
    atlas.register(entry)
    assert atlas.is_promotable("Options-heavy") is False


def test_benchmark_only_entry_cannot_become_production() -> None:
    atlas = StrategyAtlas()
    entry = StrategyAtlasEntry(
        **_good_kwargs(
            name="151 PDF baseline",
            status=AtlasStatus.BENCHMARK_ONLY,
        )
    )
    atlas.register(entry)
    assert atlas.is_promotable("151 PDF baseline") is False
    # And the seed has at least three benchmark-only entries.
    seeded = load_seed_atlas()
    benchmark_only = seeded.list_by_status(AtlasStatus.BENCHMARK_ONLY)
    assert len(benchmark_only) >= 3
    for e in benchmark_only:
        assert seeded.is_promotable(e.name) is False


def test_supported_entry_is_promotable() -> None:
    atlas = StrategyAtlas()
    entry = StrategyAtlasEntry(**_good_kwargs(name="Sup", status=AtlasStatus.SUPPORTED))
    atlas.register(entry)
    assert atlas.is_promotable("Sup") is True


def test_unknown_entry_is_not_promotable() -> None:
    atlas = StrategyAtlas()
    assert atlas.is_promotable("does-not-exist") is False


# ---- Constructor validation -----------------------------------------------


def test_entry_without_data_requirements_is_rejected() -> None:
    with pytest.raises(ValueError, match="data_requirements"):
        StrategyAtlasEntry(**_good_kwargs(data_requirements=()))


def test_entry_without_benchmark_expectation_is_rejected() -> None:
    with pytest.raises(ValueError, match="benchmark_expectation"):
        StrategyAtlasEntry(**_good_kwargs(benchmark_expectation=""))


def test_blocked_entry_requires_notes() -> None:
    with pytest.raises(ValueError, match="BLOCKED"):
        StrategyAtlasEntry(
            **_good_kwargs(status=AtlasStatus.BLOCKED, notes="")
        )


def test_invalid_cost_sensitivity_is_rejected() -> None:
    with pytest.raises(ValueError, match="cost_sensitivity"):
        StrategyAtlasEntry(**_good_kwargs(cost_sensitivity="extreme"))


def test_invalid_implementation_difficulty_is_rejected() -> None:
    with pytest.raises(ValueError, match="implementation_difficulty"):
        StrategyAtlasEntry(**_good_kwargs(implementation_difficulty="impossible"))


def test_duplicate_register_raises() -> None:
    atlas = StrategyAtlas()
    entry = StrategyAtlasEntry(**_good_kwargs(name="dup"))
    atlas.register(entry)
    with pytest.raises(ValueError, match="already registered"):
        atlas.register(entry)


# ---- Seed determinism ------------------------------------------------------


def test_seed_atlas_loads_deterministically() -> None:
    a1 = load_seed_atlas()
    a2 = load_seed_atlas()
    names_1 = [e.name for e in a1.all_entries()]
    names_2 = [e.name for e in a2.all_entries()]
    assert names_1 == names_2
    assert names_1 == [e.name for e in SEED_ENTRIES]
    # Spot-check that representative entries are present with the right status.
    assert a1.get("ETF momentum rotation").status is AtlasStatus.SUPPORTED
    assert a1.get("Tax-arbitrage").status is AtlasStatus.BLOCKED
    assert a1.get("Tax-arbitrage").notes == "compliance review pending"
    blocked_options = a1.get("Options-heavy strategies")
    assert blocked_options.notes == "options chain data not available"


def test_seed_includes_all_required_buckets() -> None:
    atlas = load_seed_atlas()
    supported = {e.name for e in atlas.list_by_status(AtlasStatus.SUPPORTED)}
    candidates = {e.name for e in atlas.list_by_status(AtlasStatus.CANDIDATE)}
    blocked = {e.name for e in atlas.list_by_status(AtlasStatus.BLOCKED)}
    benchmarks = atlas.list_by_status(AtlasStatus.BENCHMARK_ONLY)

    # Required SUPPORTED entries from the spec.
    for name in (
        "ETF momentum rotation",
        "Dual momentum",
        "Multi-asset trend following",
        "Volatility targeting overlay",
        "ETF mean reversion",
        "Simple pairs",
    ):
        assert name in supported, name

    # Required CANDIDATE entries.
    for name in (
        "Simple stat-arb",
        "KNN single-stock example",
        "Controlled alpha combo",
    ):
        assert name in candidates, name

    # Required BLOCKED entries.
    for name in (
        "Options-heavy strategies",
        "Convertibles",
        "Structured credit",
        "Tax-arbitrage",
        "Exotic fixed-income",
    ):
        assert name in blocked, name

    assert len(benchmarks) >= 3


# ---- query_before_promote --------------------------------------------------


def test_query_before_promote_with_no_refs_returns_no_concrete_warnings() -> None:
    rng = np.random.default_rng(0)
    sig = rng.standard_normal(64)
    eq = np.cumsum(rng.standard_normal(64))
    warnings = query_before_promote(
        "test_candidate",
        sig,
        {"window": 20.0},
        eq,
    )
    # No archive_path and no reference_strategies => similarity check has
    # nothing to compare against and graveyard check is skipped. The
    # function must not raise. It MAY return a degradation note about the
    # graveyard, but it must not flag the candidate.
    assert all("test_candidate" not in w or "previously archived" not in w
               for w in warnings)


def test_query_before_promote_flags_similar_candidate() -> None:
    rng = np.random.default_rng(7)
    base_signal = rng.standard_normal(128)
    base_equity = np.cumsum(rng.standard_normal(128))
    base_params = {"window": 20.0, "threshold": 0.01}
    refs = [
        ("existing_strategy", base_signal, base_params, base_equity),
    ]
    # Candidate is identical to the reference. Composite similarity ~1.
    warnings = query_before_promote(
        "near_clone",
        base_signal,
        base_params,
        base_equity,
        reference_strategies=refs,
        similarity_threshold=0.85,
    )
    flagged = [w for w in warnings if "too similar" in w]
    # If dna_fingerprint is not importable in this deployment, the test
    # accepts the explicit degradation warning instead.
    if not flagged:
        assert any("similarity check skipped" in w for w in warnings)
    else:
        assert any("existing_strategy" in w for w in flagged)


def test_query_before_promote_flags_graveyard_match(tmp_path: Path) -> None:
    archive = tmp_path / "research_archive.jsonl"
    rows = [
        {
            "event": "rejected",
            "strategy_id": "ghost_strategy",
            "version": "v3",
            "reason": "deflated_sharpe failed",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    ]
    archive.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    rng = np.random.default_rng(0)
    sig = rng.standard_normal(32)
    eq = np.cumsum(rng.standard_normal(32))
    warnings = query_before_promote(
        "ghost_strategy",
        sig,
        {"x": 1.0},
        eq,
        archive_path=archive,
    )
    flagged = [w for w in warnings if "previously archived" in w]
    if not flagged:
        # graveyard module not importable in this deployment; accept
        # explicit degradation warning.
        assert any("graveyard check skipped" in w for w in warnings)
    else:
        assert any("ghost_strategy" in w for w in flagged)


def test_query_before_promote_degrades_when_archive_missing(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    sig = rng.standard_normal(16)
    eq = np.cumsum(rng.standard_normal(16))
    # No archive_path => graveyard check is a no-op (no warning required).
    warnings = query_before_promote(
        "fresh",
        sig,
        {"x": 1.0},
        eq,
    )
    # Either skipped (module missing) or no graveyard match. Must not raise.
    assert isinstance(warnings, list)


# ---- evaluate_against_benchmark -------------------------------------------


def test_evaluate_returns_finite_for_normal_returns() -> None:
    rng = np.random.default_rng(42)
    asset = rng.normal(0.0005, 0.01, 252)
    strategy = asset + rng.normal(0.0001, 0.005, 252)
    result = evaluate_against_benchmark(
        strategy,
        BenchmarkExpectation.BUY_AND_HOLD,
        asset,
    )
    assert np.isfinite(result.sharpe_diff)
    assert np.isfinite(result.alpha_annualised)
    assert isinstance(result.beats_benchmark, bool)


def test_buy_and_hold_identical_strategy_has_zero_sharpe_diff() -> None:
    rng = np.random.default_rng(123)
    asset = rng.normal(0.0005, 0.01, 504)
    result = evaluate_against_benchmark(
        asset.copy(),
        BenchmarkExpectation.BUY_AND_HOLD,
        asset,
    )
    assert result.sharpe_diff == pytest.approx(0.0, abs=1e-12)
    assert result.alpha_annualised == pytest.approx(0.0, abs=1e-12)
    assert result.beats_benchmark is False


def test_cash_benchmark_sees_positive_strategy_as_winner() -> None:
    rng = np.random.default_rng(7)
    strategy = rng.normal(0.001, 0.005, 252)
    asset = rng.normal(0.0, 0.01, 252)
    result = evaluate_against_benchmark(
        strategy,
        BenchmarkExpectation.CASH,
        asset,
    )
    # Sharpe vs zero-return baseline equals strategy Sharpe; with positive
    # mean it should be positive.
    assert result.sharpe_diff > 0
    assert result.beats_benchmark is True


def test_cash_benchmark_sees_negative_strategy_as_loser() -> None:
    rng = np.random.default_rng(11)
    strategy = rng.normal(-0.001, 0.005, 252)
    asset = rng.normal(0.0, 0.01, 252)
    result = evaluate_against_benchmark(
        strategy,
        BenchmarkExpectation.CASH,
        asset,
    )
    assert result.sharpe_diff < 0
    assert result.beats_benchmark is False


def test_random_baseline_evaluates_finitely() -> None:
    rng = np.random.default_rng(99)
    strategy = rng.normal(0.0002, 0.01, 252)
    asset = rng.normal(0.0, 0.01, 252)
    result = evaluate_against_benchmark(
        strategy,
        BenchmarkExpectation.RANDOM_COMPARABLE_TURNOVER,
        asset,
    )
    assert np.isfinite(result.sharpe_diff)
    assert np.isfinite(result.alpha_annualised)


def test_current_production_with_no_reference_treats_as_cash() -> None:
    rng = np.random.default_rng(5)
    strategy = rng.normal(0.001, 0.005, 252)
    asset = rng.normal(0.0, 0.01, 252)
    result = evaluate_against_benchmark(
        strategy,
        BenchmarkExpectation.CURRENT_PRODUCTION,
        asset,
    )
    # Production reference omitted => degrades to cash.
    assert np.isfinite(result.sharpe_diff)
    assert np.isfinite(result.alpha_annualised)


def test_simple_momentum_baseline_runs() -> None:
    rng = np.random.default_rng(13)
    asset = rng.normal(0.0005, 0.01, 504)
    strategy = asset.copy()
    result = evaluate_against_benchmark(
        strategy,
        BenchmarkExpectation.SIMPLE_MOMENTUM,
        asset,
    )
    assert np.isfinite(result.sharpe_diff)


def test_simple_mean_reversion_baseline_runs() -> None:
    rng = np.random.default_rng(15)
    asset = rng.normal(0.0, 0.01, 504)
    strategy = asset.copy()
    result = evaluate_against_benchmark(
        strategy,
        BenchmarkExpectation.SIMPLE_MEAN_REVERSION,
        asset,
    )
    assert np.isfinite(result.sharpe_diff)
