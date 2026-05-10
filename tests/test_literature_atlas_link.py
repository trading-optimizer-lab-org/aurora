"""Tests for R174 atlas <-> paper-claim linkage.

Atlas entries can list 1+ paper claim ids as **unvalidated source
evidence**. Paper claims must NEVER be enough on their own to promote
an atlas entry from CANDIDATE to SUPPORTED -- promotion still requires
the regular validation evidence path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from aurora.research._atlas_seed import load_seed_atlas
from aurora.research.literature import (
    AtlasPaperLink,
    AtlasPaperLinkRegistry,
    extract_claims_from_text,
    ingest_text_fixture,
    is_atlas_promotable_with_paper_evidence,
)
from aurora.research.strategy_atlas import (
    AtlasStatus,
    StrategyAtlas,
    StrategyAtlasEntry,
)
from aurora.research.strategy_benchmarks import BenchmarkExpectation

FIXTURES = Path(__file__).parent / "fixtures" / "literature"


def _candidate_entry(name: str = "Lit-paper candidate") -> StrategyAtlasEntry:
    return StrategyAtlasEntry(
        name=name,
        asset_class="equity",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("multi_asset",),
        cost_sensitivity="low",
        overfit_risk="medium",
        implementation_difficulty="easy",
        validation_gates=("walk_forward",),
        benchmark_expectation=BenchmarkExpectation.BUY_AND_HOLD.value,
        status=AtlasStatus.CANDIDATE,
        owner="research",
        notes="",
    )


def test_link_registry_accepts_one_or_more_claim_ids() -> None:
    registry = AtlasPaperLinkRegistry()
    registry.link("Some atlas entry", "claim-1")
    registry.link("Some atlas entry", "claim-2")
    registry.link("Some atlas entry", "claim-3")
    assert sorted(registry.claim_ids_for("Some atlas entry")) == [
        "claim-1", "claim-2", "claim-3",
    ]
    assert len(registry) == 3


def test_link_registry_dedupes_repeat_links() -> None:
    registry = AtlasPaperLinkRegistry()
    registry.link("entry", "claim-1")
    registry.link("entry", "claim-1")
    assert registry.claim_ids_for("entry") == ["claim-1"]
    assert len(registry) == 1


def test_paper_only_evidence_does_not_promote_candidate() -> None:
    """A CANDIDATE entry with paper-claim links must stay non-promotable."""
    atlas = StrategyAtlas()
    atlas.register(_candidate_entry())
    record, text = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    claims = extract_claims_from_text(record, text)
    assert claims, "fixture must produce at least one claim"

    link_registry = AtlasPaperLinkRegistry()
    for c in claims:
        link_registry.link("Lit-paper candidate", c.claim_id)

    # The link registry has multiple supportive paper claims, but the
    # atlas entry is still CANDIDATE, so promotion is refused.
    assert atlas.is_promotable("Lit-paper candidate") is False
    assert is_atlas_promotable_with_paper_evidence(
        atlas, "Lit-paper candidate", link_registry=link_registry,
    ) is False


def test_paper_only_evidence_does_not_unblock_blocked_entry() -> None:
    """The seed atlas's BLOCKED entry stays BLOCKED even with claim links."""
    atlas = load_seed_atlas()
    blocked_name = "Options-heavy strategies"
    assert atlas.get(blocked_name).status is AtlasStatus.BLOCKED

    link_registry = AtlasPaperLinkRegistry()
    link_registry.link(blocked_name, "claim-fake-1")
    link_registry.link(blocked_name, "claim-fake-2")

    assert is_atlas_promotable_with_paper_evidence(
        atlas, blocked_name, link_registry=link_registry,
    ) is False


def test_supported_entry_promotability_unchanged_by_paper_links() -> None:
    """A SUPPORTED entry remains promotable; the link registry doesn't change it."""
    atlas = load_seed_atlas()
    supported_name = "ETF momentum rotation"
    assert atlas.get(supported_name).status is AtlasStatus.SUPPORTED

    link_registry = AtlasPaperLinkRegistry()
    # Even an empty link registry must give the same answer as no registry.
    a = is_atlas_promotable_with_paper_evidence(
        atlas, supported_name, link_registry=link_registry,
    )
    b = is_atlas_promotable_with_paper_evidence(atlas, supported_name)
    assert a is True
    assert b is True


def test_unknown_atlas_entry_is_not_promotable() -> None:
    atlas = StrategyAtlas()
    link_registry = AtlasPaperLinkRegistry()
    link_registry.link("non-existent", "claim-1")
    assert is_atlas_promotable_with_paper_evidence(
        atlas, "non-existent", link_registry=link_registry,
    ) is False


def test_atlas_paper_link_rejects_empty_fields() -> None:
    with pytest.raises(ValueError, match="atlas_name"):
        AtlasPaperLink(atlas_name="", claim_id="claim-1")
    with pytest.raises(ValueError, match="claim_id"):
        AtlasPaperLink(atlas_name="entry", claim_id="")
