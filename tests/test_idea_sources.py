"""Tests for R173 idea source registry.

Idea sources are metadata only. These tests assert that:
- The seed registry is deterministic across calls.
- URLs round-trip verbatim.
- Adding an :class:`IdeaSource` does not promote any atlas entry.
- The seed contains the expected curated references.
- Validation rejects out-of-range testability / confidence scores.
"""
from __future__ import annotations

import pytest
from aurora.research._atlas_seed import load_seed_atlas
from aurora.research.idea_sources import (
    SEED_SOURCES,
    IdeaSource,
    IdeaSourceRegistry,
    load_seed_sources,
)
from aurora.research.strategy_atlas import AtlasStatus


def test_registry_is_deterministic_across_calls() -> None:
    r1 = load_seed_sources()
    r2 = load_seed_sources()
    names_1 = [s.name for s in r1.all_sources()]
    names_2 = [s.name for s in r2.all_sources()]
    assert names_1 == names_2
    assert names_1 == [s.name for s in SEED_SOURCES]


def test_url_is_preserved_verbatim() -> None:
    registry = load_seed_sources()
    for source in registry:
        # Lookup must return the same string we registered.
        assert registry.get(source.name).url == source.url
        assert source.url.startswith("http")


def test_source_claim_does_not_promote_strategy() -> None:
    """A source claim is metadata only. Registering a source must not
    change any atlas entry's status, and the atlas's promotability gate
    must stay anchored on the entry's own status -- not on whether a
    matching source exists.
    """
    atlas = load_seed_atlas()
    registry = load_seed_sources()

    blocked_before = atlas.get("Options-heavy strategies").status
    assert blocked_before is AtlasStatus.BLOCKED
    assert atlas.is_promotable("Options-heavy strategies") is False

    # Add a source whose claim is exactly that options-heavy strategies
    # work. This is the worst-case "claim should never auto-promote".
    new_source = IdeaSource(
        name="suspicious_options_pdf",
        url="https://example.org/options-claim.pdf",
        claim="Options-heavy strategies are profitable on the AURORA "
              "platform with no caveats.",
        asset_class="options",
        data_needs=("options_chain",),
        assumptions=("frictionless options trading",),
        testability_score=0.9,
        confidence=0.9,
    )
    registry.register(new_source)

    # Atlas must be unchanged.
    blocked_after = atlas.get("Options-heavy strategies").status
    assert blocked_after is AtlasStatus.BLOCKED
    assert atlas.is_promotable("Options-heavy strategies") is False
    assert blocked_after is blocked_before


def test_seed_contains_expected_curated_references() -> None:
    registry = load_seed_sources()
    names = {s.name for s in registry.all_sources()}
    # At least four of the five canonical references must be present.
    expected = {
        "quantstart_pairs",
        "quantpedia_dual_momentum",
        "epchan_mean_reversion",
        "elitequant_trend_following",
    }
    assert expected.issubset(names), expected - names
    assert len(registry) >= 4


def test_invalid_testability_score_is_rejected() -> None:
    with pytest.raises(ValueError, match="testability_score"):
        IdeaSource(
            name="bad_score",
            url="https://example.org/x",
            claim="claim",
            asset_class="equity",
            data_needs=("daily_ohlcv",),
            assumptions=("none",),
            testability_score=1.5,
            confidence=0.5,
        )


def test_invalid_confidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="confidence"):
        IdeaSource(
            name="bad_conf",
            url="https://example.org/x",
            claim="claim",
            asset_class="equity",
            data_needs=("daily_ohlcv",),
            assumptions=("none",),
            testability_score=0.5,
            confidence=-0.1,
        )


def test_duplicate_register_raises() -> None:
    registry = IdeaSourceRegistry()
    s = IdeaSource(
        name="dup",
        url="https://example.org/x",
        claim="claim",
        asset_class="equity",
        data_needs=("daily_ohlcv",),
        assumptions=("none",),
        testability_score=0.5,
        confidence=0.5,
    )
    registry.register(s)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(s)
