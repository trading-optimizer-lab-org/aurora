"""R178 - Provider terms, licence posture and allowed-usage registry.

Each data provider AURORA contacts has its own licence and acceptable-use
policy. This module records that posture in a machine-readable form so:

* CLI output can warn the operator before live use of personal-use data.
* Evidence packs and provenance can include the terms as of the moment a
  dataset was used.
* Validation gates can block disallowed use without depending on a human
  reading the provider's website.

Usage labels follow the roadmap:

* ``smoke_test`` -- one-off connectivity / format check.
* ``personal_research`` -- single-operator backtests, no redistribution.
* ``internal_research`` -- multi-operator (currently identical to
  ``personal_research`` for AURORA, kept for forward compatibility).
* ``redistribution`` -- exporting the raw data outside AURORA.
* ``paper_trading`` -- driving simulated trades from this dataset.
* ``live_trading`` -- driving real broker orders from this dataset.
* ``report_export`` -- including raw data in shared / external reports.

The registry is intentionally small. Real licence text is not parsed; the
operator records the licence URL and reviewer-validated posture flags.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date_type
from enum import Enum
from typing import Dict, FrozenSet, Iterable, List, Optional


class UsageLabel(str, Enum):
    """Discrete categories the operator may want to perform with a dataset."""

    SMOKE_TEST = "smoke_test"
    PERSONAL_RESEARCH = "personal_research"
    INTERNAL_RESEARCH = "internal_research"
    REDISTRIBUTION = "redistribution"
    PAPER_TRADING = "paper_trading"
    LIVE_TRADING = "live_trading"
    REPORT_EXPORT = "report_export"


@dataclass(frozen=True)
class ProviderTerms:
    """Licence and usage posture for one provider.

    All boolean fields are conservative: ``False`` means "not approved".
    No usage is implicitly allowed if the operator has not reviewed the
    licence.
    """

    provider: str
    source_url: str
    licence_url: str
    licence_summary: str
    cost_tier: str  # "free", "free_with_token", "paid", "unknown"
    reviewed_at: _date_type
    allowed_usage: FrozenSet[UsageLabel]
    personal_use_only: bool = False
    non_commercial_only: bool = False
    requires_attribution: bool = False
    redistribution_allowed: bool = False
    rate_limit_note: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("provider must be non-empty")
        if not isinstance(self.allowed_usage, frozenset):
            object.__setattr__(
                self, "allowed_usage", frozenset(self.allowed_usage)
            )
        for u in self.allowed_usage:
            if not isinstance(u, UsageLabel):
                raise TypeError(
                    f"allowed_usage entry {u!r} must be UsageLabel"
                )
        if self.cost_tier not in ("free", "free_with_token", "paid", "unknown"):
            raise ValueError(f"cost_tier={self.cost_tier!r} invalid")
        if not isinstance(self.reviewed_at, _date_type):
            raise TypeError("reviewed_at must be a datetime.date")

    def permits(self, usage: UsageLabel) -> bool:
        """Return True iff ``usage`` is in the approved set."""
        return usage in self.allowed_usage

    def explain(self, usage: UsageLabel) -> str:
        """Plain-language explanation for ``permits(usage)``."""
        if self.permits(usage):
            return f"{self.provider}: {usage.value} permitted"
        reasons: List[str] = []
        if self.personal_use_only and usage in (
            UsageLabel.LIVE_TRADING,
            UsageLabel.REDISTRIBUTION,
            UsageLabel.REPORT_EXPORT,
        ):
            reasons.append("personal-use-only")
        if self.non_commercial_only and usage == UsageLabel.LIVE_TRADING:
            reasons.append("non-commercial-only")
        if usage == UsageLabel.REDISTRIBUTION and not self.redistribution_allowed:
            reasons.append("redistribution not allowed")
        if not reasons:
            reasons.append("not in allowed_usage")
        return f"{self.provider}: {usage.value} blocked ({', '.join(reasons)})"

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "source_url": self.source_url,
            "licence_url": self.licence_url,
            "licence_summary": self.licence_summary,
            "cost_tier": self.cost_tier,
            "reviewed_at": self.reviewed_at.isoformat(),
            "allowed_usage": sorted(u.value for u in self.allowed_usage),
            "personal_use_only": self.personal_use_only,
            "non_commercial_only": self.non_commercial_only,
            "requires_attribution": self.requires_attribution,
            "redistribution_allowed": self.redistribution_allowed,
            "rate_limit_note": self.rate_limit_note,
            "notes": self.notes,
        }


class ProviderTermsBlocked(RuntimeError):
    """Raised when a usage is attempted that the provider terms forbid."""


@dataclass
class ProviderTermsRegistry:
    """In-memory registry of :class:`ProviderTerms`."""

    _terms: Dict[str, ProviderTerms] = field(default_factory=dict)

    def register(self, terms: ProviderTerms, *, replace: bool = False) -> None:
        if not replace and terms.provider in self._terms:
            raise ValueError(
                f"terms for provider {terms.provider!r} already registered"
            )
        self._terms[terms.provider] = terms

    def get(self, provider: str) -> Optional[ProviderTerms]:
        return self._terms.get(provider)

    def __contains__(self, provider: object) -> bool:
        return isinstance(provider, str) and provider in self._terms

    def __len__(self) -> int:
        return len(self._terms)

    def providers(self) -> List[str]:
        return sorted(self._terms.keys())

    def require(self, provider: str) -> ProviderTerms:
        """Return the terms record for ``provider`` or raise."""
        terms = self._terms.get(provider)
        if terms is None:
            raise KeyError(f"no provider terms registered for {provider!r}")
        return terms

    def assert_allowed(self, provider: str, usage: UsageLabel) -> None:
        """Raise :class:`ProviderTermsBlocked` when ``usage`` is not approved.

        A provider with no registered terms is treated as blocked rather
        than implicitly allowed -- this is the conservative default so a
        missing review never silently authorises live or redistribution
        usage.
        """
        terms = self._terms.get(provider)
        if terms is None:
            raise ProviderTermsBlocked(
                f"no provider terms registered for {provider!r}; "
                f"refuse {usage.value} until reviewed"
            )
        if not terms.permits(usage):
            raise ProviderTermsBlocked(terms.explain(usage))

    def is_allowed(self, provider: str, usage: UsageLabel) -> bool:
        """Boolean form of :meth:`assert_allowed`."""
        try:
            self.assert_allowed(provider, usage)
        except ProviderTermsBlocked:
            return False
        return True


# ---------------------------------------------------------------------------
# Seed registry. Reviewed labels reflect the public licence posture of each
# provider AURORA already integrates with. The dates record when the operator
# last refreshed the review; they are updated when the provider's terms page
# changes or when the operator reconfirms.
# ---------------------------------------------------------------------------


def _seed(reviewed: _date_type) -> ProviderTermsRegistry:
    reg = ProviderTermsRegistry()
    reg.register(
        ProviderTerms(
            provider="yahoo",
            source_url="https://finance.yahoo.com/",
            licence_url=(
                "https://legal.yahoo.com/us/en/yahoo/terms/product-atos/"
                "apiforydn/index.html"
            ),
            licence_summary=(
                "Yahoo Finance market data is provided for personal, "
                "non-commercial use. The public web endpoints used by "
                "yfinance / pandas_datareader are unofficial."
            ),
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset({
                UsageLabel.SMOKE_TEST,
                UsageLabel.PERSONAL_RESEARCH,
            }),
            personal_use_only=True,
            redistribution_allowed=False,
            rate_limit_note="unofficial endpoint; throttle and expect breakage",
            notes="treat as best-effort fallback, not approved live source",
        )
    )
    reg.register(
        ProviderTerms(
            provider="snapshot",
            source_url="local snapshot store",
            licence_url="",
            licence_summary=(
                "Local SnapshotStore content is whatever the operator put in "
                "it; usage is gated by the source provider, not by SnapshotStore."
            ),
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset(UsageLabel),
            redistribution_allowed=True,
            notes="usage inherits from the snapshot's source provider",
        )
    )
    reg.register(
        ProviderTerms(
            provider="csv",
            source_url="local csv files",
            licence_url="",
            licence_summary="Operator-provided CSV; AURORA does not gate it.",
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset(UsageLabel),
            redistribution_allowed=True,
        )
    )
    reg.register(
        ProviderTerms(
            provider="synthetic",
            source_url="aurora.core.data_providers.synthetic",
            licence_url="",
            licence_summary="Generated locally; not real market data.",
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset({
                UsageLabel.SMOKE_TEST,
                UsageLabel.PERSONAL_RESEARCH,
                UsageLabel.INTERNAL_RESEARCH,
            }),
            redistribution_allowed=True,
            notes="never use synthetic series for live or paper trading",
        )
    )
    reg.register(
        ProviderTerms(
            provider="ccxt",
            source_url="https://github.com/ccxt/ccxt",
            licence_url="https://github.com/ccxt/ccxt/blob/master/LICENSE.txt",
            licence_summary=(
                "MIT-licensed library; usage of any specific exchange is "
                "subject to that exchange's terms."
            ),
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset({
                UsageLabel.SMOKE_TEST,
                UsageLabel.PERSONAL_RESEARCH,
                UsageLabel.INTERNAL_RESEARCH,
                UsageLabel.PAPER_TRADING,
                UsageLabel.LIVE_TRADING,
            }),
            requires_attribution=False,
            redistribution_allowed=False,
            rate_limit_note="per-exchange limits enforced by ccxt",
            notes=(
                "review the specific exchange terms before live use; ccxt "
                "itself does not warrant data accuracy"
            ),
        )
    )
    reg.register(
        ProviderTerms(
            provider="dukascopy",
            source_url="https://www.dukascopy.com/swiss/english/",
            licence_url="https://www.dukascopy.com/swiss/english/marketwatch/historical/",
            licence_summary=(
                "Dukascopy provides historical FX tick data for personal "
                "research; commercial redistribution requires permission."
            ),
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset({
                UsageLabel.SMOKE_TEST,
                UsageLabel.PERSONAL_RESEARCH,
            }),
            personal_use_only=True,
            redistribution_allowed=False,
        )
    )
    reg.register(
        ProviderTerms(
            provider="marketdata_app",
            source_url="https://www.marketdata.app/",
            licence_url="https://www.marketdata.app/terms/",
            licence_summary=(
                "Free tier limited to personal use with throttled rate; "
                "paid tier required for commercial / live."
            ),
            cost_tier="free_with_token",
            reviewed_at=reviewed,
            allowed_usage=frozenset({
                UsageLabel.SMOKE_TEST,
                UsageLabel.PERSONAL_RESEARCH,
            }),
            personal_use_only=True,
            redistribution_allowed=False,
            rate_limit_note="free tier rate-limited; refer to dashboard",
        )
    )
    reg.register(
        ProviderTerms(
            provider="sec_edgar",
            source_url="https://www.sec.gov/edgar.shtml",
            licence_url="https://www.sec.gov/about/policies-regulations/website-disclaimer/website-policies",
            licence_summary=(
                "SEC EDGAR data is in the public domain in the US; the SEC "
                "requires identifying User-Agent strings and rate limits."
            ),
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset(UsageLabel),
            requires_attribution=False,
            redistribution_allowed=True,
            rate_limit_note="10 requests / second cap; identify User-Agent",
        )
    )
    reg.register(
        ProviderTerms(
            provider="dbnomics",
            source_url="https://db.nomics.world/",
            licence_url="https://db.nomics.world/legal",
            licence_summary=(
                "DBnomics aggregates third-party series; each underlying "
                "source has its own licence."
            ),
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset({
                UsageLabel.SMOKE_TEST,
                UsageLabel.PERSONAL_RESEARCH,
                UsageLabel.INTERNAL_RESEARCH,
            }),
            requires_attribution=True,
            redistribution_allowed=False,
            notes=(
                "downstream uses must respect the upstream source's licence; "
                "AURORA must record the underlying source for every series"
            ),
        )
    )
    reg.register(
        ProviderTerms(
            provider="ecb",
            source_url="https://data.ecb.europa.eu/",
            licence_url=(
                "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html"
            ),
            licence_summary=(
                "ECB statistical data may be reused subject to attribution "
                "and the source disclaimer."
            ),
            cost_tier="free",
            reviewed_at=reviewed,
            allowed_usage=frozenset(UsageLabel),
            requires_attribution=True,
            redistribution_allowed=True,
        )
    )
    return reg


def default_registry(reviewed: Optional[_date_type] = None) -> ProviderTermsRegistry:
    """Return the seeded :class:`ProviderTermsRegistry`.

    ``reviewed`` defaults to today; tests should pass an explicit date for
    deterministic output.
    """
    if reviewed is None:
        from datetime import date

        reviewed = date.today()
    return _seed(reviewed)


def render_table(registry: ProviderTermsRegistry) -> str:
    """Return a fixed-width table summary suitable for ``aurora`` CLI."""
    rows = [(
        "PROVIDER", "COST", "PERSONAL_ONLY", "REDIST", "ALLOWED_USAGE",
    )]
    for name in registry.providers():
        t = registry.require(name)
        rows.append((
            t.provider,
            t.cost_tier,
            "yes" if t.personal_use_only else "no",
            "yes" if t.redistribution_allowed else "no",
            ",".join(sorted(u.value for u in t.allowed_usage)),
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for r in rows:
        lines.append("  ".join(r[i].ljust(widths[i]) for i in range(len(r))))
    return "\n".join(lines)


def render_provider_detail(
    registry: ProviderTermsRegistry, provider: str
) -> str:
    """Return a detailed multi-line summary for a single provider."""
    terms = registry.require(provider)
    rows = [
        ("provider", terms.provider),
        ("cost_tier", terms.cost_tier),
        ("source_url", terms.source_url),
        ("licence_url", terms.licence_url),
        ("licence_summary", terms.licence_summary),
        ("reviewed_at", terms.reviewed_at.isoformat()),
        ("personal_use_only", str(terms.personal_use_only)),
        ("non_commercial_only", str(terms.non_commercial_only)),
        ("requires_attribution", str(terms.requires_attribution)),
        ("redistribution_allowed", str(terms.redistribution_allowed)),
        ("rate_limit_note", terms.rate_limit_note),
        ("allowed_usage", ",".join(sorted(u.value for u in terms.allowed_usage))),
        ("notes", terms.notes),
    ]
    width = max(len(r[0]) for r in rows)
    return "\n".join(f"{k.ljust(width)}  {v}" for k, v in rows)


def assert_usage_allowed(
    provider: str,
    usage: UsageLabel,
    registry: Optional[ProviderTermsRegistry] = None,
) -> None:
    """Convenience wrapper used by validation gates and CLI calls."""
    reg = registry if registry is not None else default_registry()
    reg.assert_allowed(provider, usage)


def explain_usages(
    provider: str,
    usages: Iterable[UsageLabel],
    registry: Optional[ProviderTermsRegistry] = None,
) -> Dict[str, str]:
    """Map each requested usage to a human reason."""
    reg = registry if registry is not None else default_registry()
    terms = reg.require(provider)
    return {u.value: terms.explain(u) for u in usages}


__all__ = [
    "ProviderTerms",
    "ProviderTermsBlocked",
    "ProviderTermsRegistry",
    "UsageLabel",
    "assert_usage_allowed",
    "default_registry",
    "explain_usages",
    "render_provider_detail",
    "render_table",
]
