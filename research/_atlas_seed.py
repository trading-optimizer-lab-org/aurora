"""Canonical seed entries for the strategy atlas.

This module declares the *first slice* of strategies Aurora admits,
candidates that are still under review, ideas that are blocked because
the platform cannot honestly run them today, and a small set of
"benchmark only" entries kept for comparison reporting.

The seed is deliberately conservative. New entries should be added by
appending to :data:`SEED_ENTRIES`; do not edit existing entries
in-place once they have shipped without bumping the atlas version in
:mod:`docs/STRATEGY_ATLAS.md`.

Loading the seed is deterministic: :func:`load_seed_atlas` returns a
fresh :class:`StrategyAtlas` populated in declaration order so callers
can rely on ordering for golden tests.
"""
from __future__ import annotations

from aurora.research.strategy_atlas import (
    AtlasStatus,
    StrategyAtlas,
    StrategyAtlasEntry,
)
from aurora.research.strategy_benchmarks import BenchmarkExpectation

# ---- Canonical entries -----------------------------------------------------
#
# Each entry is fully populated. Tests treat this list as the source of
# truth for "what does the atlas ship with" -- adding a row here will
# break the seed-load test until the test is updated, which is the
# intended behaviour.

SEED_ENTRIES: tuple[StrategyAtlasEntry, ...] = (
    # ------ SUPPORTED ------------------------------------------------------
    StrategyAtlasEntry(
        name="ETF momentum rotation",
        asset_class="etf",
        data_requirements=("daily_ohlcv", "etf_universe"),
        required_engine_capabilities=("multi_asset", "monthly_rebalance"),
        cost_sensitivity="low",
        overfit_risk="medium",
        implementation_difficulty="easy",
        validation_gates=(
            "walk_forward",
            "deflated_sharpe",
            "spp",
            "monte_carlo_bootstrap",
        ),
        benchmark_expectation=BenchmarkExpectation.EQUAL_WEIGHT.value,
        status=AtlasStatus.SUPPORTED,
        owner="research",
        notes="Canonical Antonacci-style relative momentum across an "
              "ETF universe.",
    ),
    StrategyAtlasEntry(
        name="Dual momentum",
        asset_class="etf",
        data_requirements=("daily_ohlcv", "tbill_yield"),
        required_engine_capabilities=("multi_asset", "monthly_rebalance"),
        cost_sensitivity="low",
        overfit_risk="medium",
        implementation_difficulty="easy",
        validation_gates=(
            "walk_forward",
            "deflated_sharpe",
            "spp",
        ),
        benchmark_expectation=BenchmarkExpectation.BUY_AND_HOLD.value,
        status=AtlasStatus.SUPPORTED,
        owner="research",
        notes="Cross-sectional plus absolute momentum (Antonacci 2014).",
    ),
    StrategyAtlasEntry(
        name="Multi-asset trend following",
        asset_class="multi_asset",
        data_requirements=("daily_ohlcv", "futures_continuous"),
        required_engine_capabilities=(
            "multi_asset",
            "leverage_cap",
            "vol_scaling",
        ),
        cost_sensitivity="medium",
        overfit_risk="medium",
        implementation_difficulty="medium",
        validation_gates=(
            "walk_forward",
            "deflated_sharpe",
            "monte_carlo_reorder",
            "noise_injection",
        ),
        benchmark_expectation=BenchmarkExpectation.EQUAL_WEIGHT.value,
        status=AtlasStatus.SUPPORTED,
        owner="research",
        notes="Diversified trend across equities, rates, FX, commodities.",
    ),
    StrategyAtlasEntry(
        name="Volatility targeting overlay",
        asset_class="multi_asset",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("vol_scaling", "leverage_cap"),
        cost_sensitivity="low",
        overfit_risk="low",
        implementation_difficulty="easy",
        validation_gates=("walk_forward", "spp"),
        benchmark_expectation=BenchmarkExpectation.BUY_AND_HOLD.value,
        status=AtlasStatus.SUPPORTED,
        owner="risk",
        notes="Overlay only -- never standalone.",
    ),
    StrategyAtlasEntry(
        name="ETF mean reversion",
        asset_class="etf",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("multi_asset", "daily_rebalance"),
        cost_sensitivity="medium",
        overfit_risk="high",
        implementation_difficulty="medium",
        validation_gates=(
            "walk_forward",
            "deflated_sharpe",
            "spp",
            "monte_carlo_bootstrap",
            "noise_injection",
        ),
        benchmark_expectation=BenchmarkExpectation.SIMPLE_MEAN_REVERSION.value,
        status=AtlasStatus.SUPPORTED,
        owner="research",
        notes="Short-horizon ETF mean reversion. Cost-sensitive.",
    ),
    StrategyAtlasEntry(
        name="Simple pairs",
        asset_class="equity",
        data_requirements=("daily_ohlcv", "sector_classification"),
        required_engine_capabilities=("long_short", "daily_rebalance"),
        cost_sensitivity="medium",
        overfit_risk="high",
        implementation_difficulty="medium",
        validation_gates=(
            "walk_forward",
            "deflated_sharpe",
            "spp",
            "cointegration_stability",
        ),
        benchmark_expectation=BenchmarkExpectation.CASH.value,
        status=AtlasStatus.SUPPORTED,
        owner="research",
        notes="Cointegration-based pair trading on liquid equities.",
    ),

    # ------ CANDIDATE ------------------------------------------------------
    StrategyAtlasEntry(
        name="Simple stat-arb",
        asset_class="equity",
        data_requirements=("daily_ohlcv", "sector_classification"),
        required_engine_capabilities=(
            "long_short",
            "daily_rebalance",
            "cross_sectional_residualisation",
        ),
        cost_sensitivity="high",
        overfit_risk="high",
        implementation_difficulty="hard",
        validation_gates=(
            "walk_forward",
            "deflated_sharpe",
            "spp",
            "monte_carlo_bootstrap",
            "noise_injection",
            "cost_stress",
        ),
        benchmark_expectation=BenchmarkExpectation.RANDOM_COMPARABLE_TURNOVER.value,
        status=AtlasStatus.CANDIDATE,
        owner="research",
        notes="Universe-residualised mean-reversion on equity baskets. "
              "Pending cost-stress validation.",
    ),
    StrategyAtlasEntry(
        name="KNN single-stock example",
        asset_class="equity",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("single_asset",),
        cost_sensitivity="medium",
        overfit_risk="high",
        implementation_difficulty="medium",
        validation_gates=(
            "walk_forward",
            "deflated_sharpe",
            "spp",
            "noise_injection",
        ),
        benchmark_expectation=BenchmarkExpectation.SIMPLE_MOMENTUM.value,
        status=AtlasStatus.CANDIDATE,
        owner="research",
        notes="Educational ML example. Not production.",
    ),
    StrategyAtlasEntry(
        name="Controlled alpha combo",
        asset_class="multi_asset",
        data_requirements=("daily_ohlcv", "factor_returns"),
        required_engine_capabilities=(
            "multi_asset",
            "factor_neutralisation",
        ),
        cost_sensitivity="medium",
        overfit_risk="high",
        implementation_difficulty="hard",
        validation_gates=(
            "walk_forward",
            "deflated_sharpe",
            "spp",
            "monte_carlo_bootstrap",
            "regime_stability",
        ),
        benchmark_expectation=BenchmarkExpectation.CURRENT_PRODUCTION.value,
        status=AtlasStatus.CANDIDATE,
        owner="research",
        notes="Combination of validated alphas with explicit factor "
              "exposure caps.",
    ),

    # ------ BLOCKED --------------------------------------------------------
    StrategyAtlasEntry(
        name="Options-heavy strategies",
        asset_class="options",
        data_requirements=("options_chain", "implied_vol_surface"),
        required_engine_capabilities=("options_pricing", "greeks_engine"),
        cost_sensitivity="high",
        overfit_risk="high",
        implementation_difficulty="hard",
        validation_gates=(),
        benchmark_expectation=BenchmarkExpectation.CASH.value,
        status=AtlasStatus.BLOCKED,
        owner="platform",
        notes="options chain data not available",
    ),
    StrategyAtlasEntry(
        name="Convertibles",
        asset_class="convertibles",
        data_requirements=("convertible_bond_terms", "credit_spread"),
        required_engine_capabilities=("convertible_pricing",),
        cost_sensitivity="high",
        overfit_risk="high",
        implementation_difficulty="hard",
        validation_gates=(),
        benchmark_expectation=BenchmarkExpectation.CASH.value,
        status=AtlasStatus.BLOCKED,
        owner="platform",
        notes="convertible bond terms data not available",
    ),
    StrategyAtlasEntry(
        name="Structured credit",
        asset_class="credit",
        data_requirements=("structured_credit_tranches", "credit_spread"),
        required_engine_capabilities=("structured_credit_pricing",),
        cost_sensitivity="high",
        overfit_risk="high",
        implementation_difficulty="hard",
        validation_gates=(),
        benchmark_expectation=BenchmarkExpectation.CASH.value,
        status=AtlasStatus.BLOCKED,
        owner="platform",
        notes="structured credit data + pricing engine not available",
    ),
    StrategyAtlasEntry(
        name="Tax-arbitrage",
        asset_class="multi_asset",
        data_requirements=("daily_ohlcv", "tax_lot_data"),
        required_engine_capabilities=("tax_lot_engine",),
        cost_sensitivity="high",
        overfit_risk="medium",
        implementation_difficulty="hard",
        validation_gates=(),
        benchmark_expectation=BenchmarkExpectation.CASH.value,
        status=AtlasStatus.BLOCKED,
        owner="compliance",
        notes="compliance review pending",
    ),
    StrategyAtlasEntry(
        name="Exotic fixed-income",
        asset_class="rates",
        data_requirements=("yield_curve_full", "exotic_bond_terms"),
        required_engine_capabilities=("exotic_rates_pricing",),
        cost_sensitivity="high",
        overfit_risk="high",
        implementation_difficulty="hard",
        validation_gates=(),
        benchmark_expectation=BenchmarkExpectation.CASH.value,
        status=AtlasStatus.BLOCKED,
        owner="platform",
        notes="exotic rates data + pricing engine not available",
    ),

    # ------ BENCHMARK_ONLY -------------------------------------------------
    StrategyAtlasEntry(
        name="151 PDF: Strategy XYZ",
        asset_class="equity",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("single_asset",),
        cost_sensitivity="medium",
        overfit_risk="high",
        implementation_difficulty="medium",
        validation_gates=(),
        benchmark_expectation=BenchmarkExpectation.BUY_AND_HOLD.value,
        status=AtlasStatus.BENCHMARK_ONLY,
        owner="research",
        notes="Comparison baseline from 151 PDF survey, table XYZ.",
    ),
    StrategyAtlasEntry(
        name="151 PDF: Strategy ABC",
        asset_class="etf",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("multi_asset",),
        cost_sensitivity="low",
        overfit_risk="medium",
        implementation_difficulty="easy",
        validation_gates=(),
        benchmark_expectation=BenchmarkExpectation.EQUAL_WEIGHT.value,
        status=AtlasStatus.BENCHMARK_ONLY,
        owner="research",
        notes="Comparison baseline from 151 PDF survey, table ABC.",
    ),
    StrategyAtlasEntry(
        name="151 PDF: Strategy LMN",
        asset_class="multi_asset",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("multi_asset",),
        cost_sensitivity="medium",
        overfit_risk="high",
        implementation_difficulty="medium",
        validation_gates=(),
        benchmark_expectation=BenchmarkExpectation.SIMPLE_MOMENTUM.value,
        status=AtlasStatus.BENCHMARK_ONLY,
        owner="research",
        notes="Comparison baseline from 151 PDF survey, table LMN.",
    ),
)


def load_seed_atlas() -> StrategyAtlas:
    """Build a fresh :class:`StrategyAtlas` populated with the canonical seed.

    The result is deterministic: each call returns a new registry
    populated in :data:`SEED_ENTRIES` declaration order.
    """
    atlas = StrategyAtlas()
    for entry in SEED_ENTRIES:
        atlas.register(entry)
    return atlas


__all__ = [
    "SEED_ENTRIES",
    "load_seed_atlas",
]
