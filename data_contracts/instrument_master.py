"""R159 - Instrument Master and symbol identity layer.

Extends the existing :mod:`aurora.data_contracts.security_master` with a
richer :class:`InstrumentRecord` plus an :class:`IdentityResolver` that
maps provider-specific symbols (e.g. ``BRK.B`` vs ``BRK-B``) to a single
canonical identity record.

Goal of this layer: every downstream check (corporate actions,
fundamentals, calendars, fallback providers) has one identity object to
reason about, with provenance attached. The resolver refuses ambiguous
matches unless the operator supplies an explicit override.

The data here is intentionally small and seeded by hand. R158 + R159
expect the operator to feed the resolver from FinanceDatabase / Nasdaq
Trader / OpenFIGI / SEC CIK in a separate ingestion step; this module
only owns the canonical model and the in-memory index.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date as _date_type
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class InstrumentProvenance:
    """Where this identity record came from and when it was last verified."""

    source: str
    retrieved_at: _date_type
    confidence: str = "high"  # "high" | "medium" | "low"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.confidence not in ("high", "medium", "low"):
            raise ValueError(f"confidence={self.confidence!r} invalid")
        if not isinstance(self.retrieved_at, _date_type):
            raise TypeError("retrieved_at must be a datetime.date")


@dataclass(frozen=True)
class InstrumentRecord:
    """Canonical identity for one tradable instrument.

    Mandatory fields are intentionally minimal. Optional fields exist for
    the cases where the operator has them (CIK for SEC filings, FIGI for
    cross-vendor mapping, ISIN/CUSIP for legal documents) but the
    resolver does not require them.
    """

    canonical_symbol: str
    asset_class: str
    exchange: str
    country: str
    currency: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    cik: Optional[str] = None
    figi: Optional[str] = None
    isin: Optional[str] = None
    cusip: Optional[str] = None
    active: bool = True
    first_seen: Optional[_date_type] = None
    last_seen: Optional[_date_type] = None
    listing_start: Optional[_date_type] = None
    listing_end: Optional[_date_type] = None
    aliases: FrozenSet[str] = field(default_factory=frozenset)
    provenance: Optional[InstrumentProvenance] = None

    def __post_init__(self) -> None:
        if not self.canonical_symbol:
            raise ValueError("canonical_symbol must be non-empty")
        if not isinstance(self.aliases, frozenset):
            object.__setattr__(self, "aliases", frozenset(self.aliases))
        valid_classes = {
            "equity", "etf", "etn", "fund", "index", "fx",
            "crypto", "bond", "future", "option", "warrant",
        }
        if self.asset_class not in valid_classes:
            raise ValueError(
                f"asset_class={self.asset_class!r} not in {sorted(valid_classes)}"
            )

    def matches(self, symbol: str) -> bool:
        return symbol == self.canonical_symbol or symbol in self.aliases

    def to_dict(self) -> dict:
        d = asdict(self)
        d["aliases"] = sorted(self.aliases)
        if self.provenance:
            d["provenance"] = asdict(self.provenance)
            d["provenance"]["retrieved_at"] = self.provenance.retrieved_at.isoformat()
        for k in ("first_seen", "last_seen", "listing_start", "listing_end"):
            v = d.get(k)
            if isinstance(v, _date_type):
                d[k] = v.isoformat()
        return d


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class IdentityResolver:
    """In-memory index keyed by canonical symbol, with alias fan-out.

    The resolver refuses to silently pick a winner when two records claim
    the same alias. Callers must either disambiguate the input or feed
    one of the colliding records as an explicit override.
    """

    def __init__(self) -> None:
        self._records: Dict[str, InstrumentRecord] = {}
        self._alias_to_canonical: Dict[str, str] = {}
        self._alias_collisions: Dict[str, List[str]] = {}

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, symbol: object) -> bool:
        if not isinstance(symbol, str):
            return False
        return (
            symbol in self._records
            or symbol in self._alias_to_canonical
        )

    def register(self, record: InstrumentRecord, *, replace: bool = False) -> None:
        canon = record.canonical_symbol
        if not replace and canon in self._records:
            raise ValueError(
                f"canonical_symbol {canon!r} already registered; "
                "pass replace=True to overwrite"
            )
        self._records[canon] = record
        self._alias_to_canonical[canon] = canon
        for alias in record.aliases:
            existing = self._alias_to_canonical.get(alias)
            if existing is None or existing == canon:
                self._alias_to_canonical[alias] = canon
                continue
            # Collision: refuse to overwrite, mark the alias ambiguous.
            self._alias_collisions.setdefault(alias, [existing]).append(canon)
            # Drop the alias-to-canonical mapping for this alias so resolve
            # raises instead of silently choosing.
            self._alias_to_canonical.pop(alias, None)

    def get(self, canonical_symbol: str) -> Optional[InstrumentRecord]:
        return self._records.get(canonical_symbol)

    def resolve(self, symbol: str) -> InstrumentRecord:
        """Return the :class:`InstrumentRecord` that ``symbol`` resolves to.

        Raises:
            KeyError: when ``symbol`` is unknown.
            AmbiguousIdentityError: when ``symbol`` is a non-canonical
                alias claimed by more than one record.
        """
        if symbol in self._alias_collisions and symbol not in self._records:
            colliders = self._alias_collisions[symbol]
            raise AmbiguousIdentityError(
                f"symbol {symbol!r} is ambiguous; matches "
                f"{sorted(colliders)}"
            )
        canon = self._alias_to_canonical.get(symbol)
        if canon is None:
            raise KeyError(f"no instrument record for {symbol!r}")
        return self._records[canon]

    def is_resolved(self, symbol: str) -> bool:
        try:
            self.resolve(symbol)
        except (KeyError, AmbiguousIdentityError):
            return False
        return True

    def aliases_of(self, canonical_symbol: str) -> FrozenSet[str]:
        rec = self._records.get(canonical_symbol)
        return rec.aliases if rec else frozenset()

    def all_records(self) -> Tuple[InstrumentRecord, ...]:
        return tuple(self._records[k] for k in sorted(self._records))

    def coverage_report(self, requested: Iterable[str]) -> Dict[str, List[str]]:
        """Return ``{status: [symbols]}`` for the input list."""
        resolved: List[str] = []
        unresolved: List[str] = []
        ambiguous: List[str] = []
        for sym in requested:
            try:
                self.resolve(sym)
            except AmbiguousIdentityError:
                ambiguous.append(sym)
            except KeyError:
                unresolved.append(sym)
            else:
                resolved.append(sym)
        return {
            "resolved": sorted(resolved),
            "unresolved": sorted(unresolved),
            "ambiguous": sorted(ambiguous),
        }


class AmbiguousIdentityError(LookupError):
    """Raised when a non-canonical alias matches more than one record."""


# ---------------------------------------------------------------------------
# Provider-symbol normalisation helpers
# ---------------------------------------------------------------------------


def normalise_symbol(symbol: str) -> str:
    """Normalise common provider variants to a canonical form.

    Handles a small set of well-known cases so callers do not silently
    drift between ``BRK-B``, ``BRK.B`` and ``BRK/B``. The returned form
    uses ``.`` as the share-class separator.
    """
    if not symbol:
        return symbol
    upper = symbol.strip().upper()
    # Fold dash and slash share-class separators to dot.
    folded = upper.replace("-", ".").replace("/", ".")
    return folded


def expand_provider_aliases(canonical: str) -> FrozenSet[str]:
    """Return common provider-specific spellings for ``canonical``.

    Currently expands the share-class separator: ``BRK.B`` -> aliases
    ``BRK-B`` (Yahoo) and ``BRK/B`` (some fundamentals feeds).
    """
    if not canonical or "." not in canonical:
        return frozenset()
    return frozenset({
        canonical.replace(".", "-"),
        canonical.replace(".", "/"),
    })


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def _seed_record(
    canonical: str,
    *,
    asset_class: str,
    exchange: str,
    country: str,
    currency: str,
    company_name: str = "",
    aliases: Iterable[str] = (),
    cik: Optional[str] = None,
    sector: str = "",
    industry: str = "",
    retrieved_at: _date_type,
    source: str = "manual_seed",
    confidence: str = "high",
) -> InstrumentRecord:
    return InstrumentRecord(
        canonical_symbol=canonical,
        asset_class=asset_class,
        exchange=exchange,
        country=country,
        currency=currency,
        company_name=company_name,
        sector=sector,
        industry=industry,
        cik=cik,
        aliases=frozenset(aliases) | expand_provider_aliases(canonical),
        provenance=InstrumentProvenance(
            source=source,
            retrieved_at=retrieved_at,
            confidence=confidence,
        ),
    )


def seed_resolver(retrieved_at: Optional[_date_type] = None) -> IdentityResolver:
    """Return a small bootstrap resolver with a few well-known records.

    This is intentionally tiny: it covers the share-class collision case
    (BRK.B), one FX pair (EURUSD) and one ETF (SPY). Real ingestion runs
    feed the resolver from FinanceDatabase / Nasdaq Trader.
    """
    if retrieved_at is None:
        from datetime import date

        retrieved_at = date.today()
    resolver = IdentityResolver()
    resolver.register(_seed_record(
        "BRK.B",
        asset_class="equity",
        exchange="NYSE",
        country="US",
        currency="USD",
        company_name="Berkshire Hathaway Class B",
        cik="1067983",
        sector="Financial Services",
        industry="Insurance - Diversified",
        retrieved_at=retrieved_at,
    ))
    resolver.register(_seed_record(
        "SPY",
        asset_class="etf",
        exchange="ARCA",
        country="US",
        currency="USD",
        company_name="SPDR S&P 500 ETF Trust",
        sector="ETF",
        retrieved_at=retrieved_at,
    ))
    resolver.register(_seed_record(
        "EURUSD",
        asset_class="fx",
        exchange="OTC",
        country="XX",
        currency="USD",
        company_name="EUR / USD spot",
        aliases=("EUR/USD", "EUR-USD"),
        retrieved_at=retrieved_at,
    ))
    return resolver


__all__ = [
    "AmbiguousIdentityError",
    "IdentityResolver",
    "InstrumentProvenance",
    "InstrumentRecord",
    "expand_provider_aliases",
    "normalise_symbol",
    "seed_resolver",
]
