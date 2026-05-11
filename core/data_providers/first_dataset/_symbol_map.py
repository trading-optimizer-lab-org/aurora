"""R158 per-provider symbol normalisation.

Different vendors spell the same instrument differently. The orchestrator
keeps the canonical (Aurora) spelling everywhere and asks this module
to translate just before the wire call.

Examples:
    BRK-B -> Stooq:    "BRK-B.US"
    BRK-B -> yfinance: "BRK-B"
    EURUSD -> yfinance: "EURUSD=X"
    EURUSD -> Stooq:    "EURUSD.FX"
    DXY    -> yfinance: "DX-Y.NYB"
    DXY    -> Stooq:    "^DXY"

When no mapping is registered the canonical symbol is returned
unchanged. The orchestrator records the original -> normalised pair in
the lineage extras (``symbol_normalised_from``) when normalisation
actually changes the spelling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


__all__ = [
    "SymbolNormalisation",
    "lookup_normalisation",
    "normalise_symbol",
    "apply_normalisation",
]


@dataclass(frozen=True)
class SymbolNormalisation:
    """Frozen record of a canonical -> provider-specific spelling."""

    canonical: str
    provider: str
    provider_symbol: str
    notes: Optional[str] = None


# (canonical, provider) -> SymbolNormalisation
_NORMALISATIONS: dict[tuple[str, str], SymbolNormalisation] = {}


def _register(
    canonical: str,
    provider: str,
    provider_symbol: str,
    notes: Optional[str] = None,
) -> None:
    key = (canonical.upper(), provider)
    _NORMALISATIONS[key] = SymbolNormalisation(
        canonical=canonical.upper(),
        provider=provider,
        provider_symbol=provider_symbol,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Equities -- BRK-B is the only large cap that needs vendor-specific spelling.
# Stooq prefers a ``-B.US`` suffix so it does not look like a strike.
# ---------------------------------------------------------------------------

_register("BRK-B", "stooq", "BRK-B.US", notes="Stooq US suffix")
_register("BRK-B", "yfinance_daily", "BRK-B", notes="Yahoo dash form")
_register("BRK-B", "yahooquery_daily", "BRK-B", notes="yahooquery dash form")


# ---------------------------------------------------------------------------
# FX majors. yfinance uses ``=X`` for spot pairs, Stooq tags FX with
# ``.FX``, Dukascopy slashes the pair.
# ---------------------------------------------------------------------------

_FX_PAIRS = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
)

for _pair in _FX_PAIRS:
    _register(_pair, "yfinance_daily", f"{_pair}=X", notes="Yahoo FX spot")
    _register(_pair, "yahooquery_daily", f"{_pair}=X", notes="yahooquery FX spot")
    _register(_pair, "stooq", f"{_pair}.FX", notes="Stooq FX tag")
    # Dukascopy uses BASE/QUOTE.
    _register(
        _pair,
        "dukascopy_fx_history",
        f"{_pair[:3]}/{_pair[3:]}",
        notes="Dukascopy slash form",
    )


# ---------------------------------------------------------------------------
# Dollar Index. Yahoo serves it as DX-Y.NYB; Stooq uses ^DXY.
# ---------------------------------------------------------------------------

_register("DXY", "yfinance_daily", "DX-Y.NYB", notes="Yahoo dollar index")
_register("DXY", "yahooquery_daily", "DX-Y.NYB", notes="yahooquery dollar index")
_register("DXY", "stooq", "^DXY", notes="Stooq dollar index")
_register("DXY", "dukascopy_fx_history", "DXY", notes="Dukascopy DXY symbol")


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def lookup_normalisation(
    canonical: str, provider: str,
) -> Optional[SymbolNormalisation]:
    """Return the registered normalisation, or ``None`` if no mapping."""
    return _NORMALISATIONS.get((canonical.upper(), provider))


def normalise_symbol(canonical: str, provider: str) -> str:
    """Return the provider-specific spelling, falling back to ``canonical``.

    Case-insensitive on the canonical side; provider names match exactly
    against the orchestrator's chain entries.
    """
    rec = lookup_normalisation(canonical, provider)
    if rec is None:
        return canonical
    return rec.provider_symbol


def apply_normalisation(
    canonical: str, provider: str,
) -> tuple[str, Optional[SymbolNormalisation]]:
    """Return ``(provider_symbol, record_or_None)``.

    Useful when the caller wants to record the mapping in lineage
    extras only when normalisation actually changed the spelling.
    """
    rec = lookup_normalisation(canonical, provider)
    if rec is None:
        return canonical, None
    return rec.provider_symbol, rec
