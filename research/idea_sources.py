"""Idea source registry (R173).

Curated metadata pointing to *where* a strategy idea came from -- a paper,
a textbook chapter, a blog post, or an open-source reference. This module
intentionally stores **metadata only**: the presence of an entry here does
not imply the idea has been validated, and it cannot promote any
:class:`~aurora.research.strategy_atlas.StrategyAtlasEntry` on its own.

Why a dedicated registry: the strategy atlas itself is a list of
*on-platform* ideas with status flags (supported / candidate / blocked /
benchmark-only). Idea sources are upstream of the atlas: they are the raw
material a researcher reads before *proposing* an atlas entry. Keeping
them separate means we can ingest survey papers, textbooks, and blog
posts without polluting the atlas with unverified claims.

Each :class:`IdeaSource` records:

- ``name`` -- short slug, unique across the registry
- ``url`` -- canonical reference URL (preserved verbatim)
- ``claim`` -- the headline claim made in the source, as plain text
- ``asset_class`` -- the asset class the claim targets (``equity``,
  ``etf``, ``multi_asset`` etc.); free-form because sources can be
  cross-asset surveys
- ``data_needs`` -- tuple of data labels the claim implicitly requires
- ``assumptions`` -- tuple of explicit assumptions the source makes
  (e.g. ``"frictionless trading"``, ``"daily rebalance"``)
- ``testability_score`` -- 0.0-1.0 estimate of how testable the claim
  is on AURORA's data and engine. Pure metadata, not used in any gate.
- ``confidence`` -- 0.0-1.0 estimate of how robust the source itself
  is (peer-reviewed paper > preprint > blog post). Pure metadata.

The registry is in-memory and deterministic: :func:`load_seed_sources`
returns a fresh :class:`IdeaSourceRegistry` populated in declaration
order so callers can rely on ordering for golden tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class IdeaSource:
    """Metadata-only record describing an upstream strategy reference."""

    name: str
    url: str
    claim: str
    asset_class: str
    data_needs: tuple[str, ...]
    assumptions: tuple[str, ...]
    testability_score: float
    confidence: float

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("IdeaSource.name must be non-empty")
        if not self.url or not self.url.strip():
            raise ValueError(
                f"IdeaSource({self.name!r}): url must be non-empty"
            )
        if not self.claim or not self.claim.strip():
            raise ValueError(
                f"IdeaSource({self.name!r}): claim must be non-empty"
            )
        if not self.asset_class or not self.asset_class.strip():
            raise ValueError(
                f"IdeaSource({self.name!r}): asset_class must be non-empty"
            )
        if not isinstance(self.data_needs, tuple):
            raise TypeError(
                f"IdeaSource({self.name!r}): data_needs must be a tuple"
            )
        if not isinstance(self.assumptions, tuple):
            raise TypeError(
                f"IdeaSource({self.name!r}): assumptions must be a tuple"
            )
        if not (0.0 <= self.testability_score <= 1.0):
            raise ValueError(
                f"IdeaSource({self.name!r}): testability_score must be "
                f"in [0.0, 1.0], got {self.testability_score!r}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"IdeaSource({self.name!r}): confidence must be in "
                f"[0.0, 1.0], got {self.confidence!r}"
            )


@dataclass
class IdeaSourceRegistry:
    """In-memory registry of :class:`IdeaSource` keyed by name.

    Deterministic: insertion order is preserved by the underlying dict.
    """

    _entries: dict[str, IdeaSource] = field(default_factory=dict)

    def register(self, source: IdeaSource) -> None:
        if source.name in self._entries:
            raise ValueError(
                f"IdeaSourceRegistry: source {source.name!r} already "
                "registered"
            )
        self._entries[source.name] = source

    def get(self, name: str) -> IdeaSource:
        if name not in self._entries:
            raise KeyError(
                f"IdeaSourceRegistry: unknown source {name!r}"
            )
        return self._entries[name]

    def has(self, name: str) -> bool:
        return name in self._entries

    def all_sources(self) -> list[IdeaSource]:
        return list(self._entries.values())

    def filter_by_asset_class(self, asset_class: str) -> list[IdeaSource]:
        return [
            s for s in self._entries.values()
            if s.asset_class == asset_class
        ]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._entries

    def __iter__(self) -> Iterable[IdeaSource]:
        return iter(self._entries.values())


# ---- Seed entries ----------------------------------------------------------
#
# These are *references* only. Adding a row here does not authorise an
# atlas entry. The seed deliberately mixes paper-style, textbook-style,
# and open-source repository references to make the testability/
# confidence distinction visible.

SEED_SOURCES: tuple[IdeaSource, ...] = (
    IdeaSource(
        name="quantstart_pairs",
        url="https://www.quantstart.com/articles/Cointegration-Approach-to-Pairs-Trading",
        claim="Cointegration-based pairs trading on liquid equities can "
              "produce positive risk-adjusted returns when costs are low.",
        asset_class="equity",
        data_needs=("daily_ohlcv", "sector_classification"),
        assumptions=(
            "frictionless trading",
            "stationary spread within trading window",
            "no regime change",
        ),
        testability_score=0.7,
        confidence=0.55,
    ),
    IdeaSource(
        name="quantpedia_dual_momentum",
        url="https://quantpedia.com/strategies/dual-momentum-strategy",
        claim="Combining cross-sectional and absolute momentum across "
              "asset classes (Antonacci 2014) historically outperformed "
              "passive buy-and-hold benchmarks on a risk-adjusted basis.",
        asset_class="multi_asset",
        data_needs=("daily_ohlcv", "tbill_yield"),
        assumptions=(
            "monthly rebalance",
            "low transaction costs at ETF level",
            "no regime change since publication",
        ),
        testability_score=0.85,
        confidence=0.7,
    ),
    IdeaSource(
        name="epchan_mean_reversion",
        url="https://epchan.blogspot.com/",
        claim="Short-horizon ETF mean reversion captures liquidity-driven "
              "overshoots and reverts within 1-5 days, before transaction "
              "costs.",
        asset_class="etf",
        data_needs=("daily_ohlcv",),
        assumptions=(
            "daily rebalance",
            "low slippage on highly liquid ETFs",
            "no structural break in mean-reversion signal",
        ),
        testability_score=0.8,
        confidence=0.5,
    ),
    IdeaSource(
        name="elitequant_trend_following",
        url="https://github.com/EliteQuant/EliteQuant",
        claim="Diversified trend following across equities, rates, FX and "
              "commodities (managed-futures style) historically reduced "
              "tail risk and added uncorrelated returns.",
        asset_class="multi_asset",
        data_needs=("daily_ohlcv", "futures_continuous"),
        assumptions=(
            "vol-scaled position sizing",
            "monthly to weekly rebalance",
            "futures roll handled deterministically",
        ),
        testability_score=0.75,
        confidence=0.6,
    ),
    IdeaSource(
        name="151_pdf_survey",
        url="https://example.org/151-strategies-survey.pdf",
        claim="Survey paper enumerating 151 published strategies across "
              "asset classes; results are reported pre-cost and without "
              "out-of-sample correction.",
        asset_class="multi_asset",
        data_needs=("daily_ohlcv",),
        assumptions=(
            "results are pre-cost",
            "no walk-forward correction",
            "no penalty for selection bias",
        ),
        testability_score=0.4,
        confidence=0.3,
    ),
)


def load_seed_sources() -> IdeaSourceRegistry:
    """Build a fresh :class:`IdeaSourceRegistry` populated with the seed.

    Deterministic: each call returns a new registry populated in
    :data:`SEED_SOURCES` declaration order.
    """
    registry = IdeaSourceRegistry()
    for source in SEED_SOURCES:
        registry.register(source)
    return registry


__all__ = [
    "IdeaSource",
    "IdeaSourceRegistry",
    "SEED_SOURCES",
    "load_seed_sources",
]
