"""Minimal Security Master registry.

A Security Master maps a project-internal symbol to vendor / broker /
exchange identifiers, tracks the listing window and active state, and
holds optional ISO identifiers (ISIN, FIGI, CUSIP). It is the single
source of truth for *which* instruments the engine is allowed to talk
about. Strategy-side and validation-side code that wants to look up an
identifier MUST go through this registry, not hard-code mappings inline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date_type
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover -- import-cycle break
    from aurora.core.data_providers.openfigi_mapper import (
        FIGIMapping,
        FIGIQueryResult,
    )


@dataclass(frozen=True)
class SecurityMasterRecord:
    """One instrument record.

    Attributes:
        symbol: project-internal symbol (e.g. ``"AAPL"``).
        vendor_symbol: identifier the data vendor uses.
        broker_symbol: identifier the broker uses (may differ from vendor).
        exchange: primary listing exchange code.
        currency: ISO 4217 currency code.
        listing_window: ``(start_date, end_date)`` covering when the
            instrument was tradeable. ``None`` means "always active".
        active: ``True`` if the instrument is currently active.
        isin: optional ISIN.
        figi: optional FIGI.
        cusip: optional CUSIP.
        sedol: optional SEDOL identifier (R156 / OpenFIGI integration).
        composite_figi: optional Bloomberg composite FIGI.
        share_class_figi: optional Bloomberg share-class FIGI.
        figi_mappings: tuple of additional candidate FIGI mappings
            preserved verbatim from the OpenFIGI mapper. Stored as
            generic dicts so this module does not import the data
            provider package; callers can rebuild
            :class:`aurora.core.data_providers.openfigi_mapper.FIGIMapping`
            from the dicts if they need typed access.
    """

    symbol: str
    vendor_symbol: str
    broker_symbol: str
    exchange: str
    currency: str
    listing_window: Optional[Tuple[_date_type, _date_type]] = None
    active: bool = True
    isin: Optional[str] = None
    figi: Optional[str] = None
    cusip: Optional[str] = None
    sedol: Optional[str] = None
    composite_figi: Optional[str] = None
    share_class_figi: Optional[str] = None
    figi_mappings: Tuple[Dict[str, Any], ...] = ()


def from_openfigi_mapping(
    figi_result: "FIGIQueryResult",
    *,
    symbol: Optional[str] = None,
    broker_symbol: Optional[str] = None,
    listing_window: Optional[Tuple[_date_type, _date_type]] = None,
    active: bool = True,
) -> SecurityMasterRecord:
    """Construct a :class:`SecurityMasterRecord` from an OpenFIGI result.

    The first candidate mapping is treated as the primary. Additional
    candidates (when ``figi_result.is_ambiguous``) are preserved on
    ``figi_mappings`` so the operator can review them; nothing is
    silently dropped.

    Args:
        figi_result: a :class:`FIGIQueryResult` from
            :class:`aurora.core.data_providers.openfigi_mapper.OpenFIGIClient`.
        symbol: project-internal symbol. Defaults to the primary
            candidate's ticker.
        broker_symbol: broker identifier. Defaults to the primary
            candidate's ticker.
        listing_window: optional tradeable window.
        active: whether the instrument is currently active.

    Returns:
        A frozen :class:`SecurityMasterRecord`. When the OpenFIGI
        result has no candidates, the function still returns a record
        with empty optional ID fields and a single-element
        ``figi_mappings`` tuple capturing the warning, so the caller
        does not lose the lookup outcome.
    """
    if figi_result.mappings:
        primary = figi_result.mappings[0]
    else:
        # Synthesise an empty primary so the record can still be built.
        from aurora.core.data_providers.openfigi_mapper import FIGIMapping
        primary = FIGIMapping()
    resolved_symbol = symbol or primary.ticker or ""
    if not resolved_symbol:
        raise ValueError(
            "from_openfigi_mapping: cannot derive symbol from result with "
            "no ticker; supply symbol= explicitly."
        )
    resolved_broker = broker_symbol or primary.ticker or resolved_symbol
    # Preserve candidates as plain dicts to avoid importing the provider
    # module at SecurityMasterRecord construction time.
    extra_mappings: Tuple[Dict[str, Any], ...] = tuple(
        {
            "figi": m.figi,
            "name": m.name,
            "ticker": m.ticker,
            "exchange_code": m.exchange_code,
            "market_sector": m.market_sector,
            "security_type": m.security_type,
            "unique_id": m.unique_id,
            "unique_id_type": m.unique_id_type,
            "currency": m.currency,
            "composite_figi": m.composite_figi,
            "share_class_figi": m.share_class_figi,
        }
        for m in figi_result.mappings
    )
    # Pull ISIN/CUSIP/SEDOL out of unique_id when the unique_id_type
    # tells us. Never invent: if the type is missing or unknown, leave
    # the canonical fields as None.
    isin = cusip = sedol = None
    if primary.unique_id and primary.unique_id_type:
        kind = primary.unique_id_type.upper()
        if "ISIN" in kind:
            isin = primary.unique_id
        elif "CUSIP" in kind:
            cusip = primary.unique_id
        elif "SEDOL" in kind:
            sedol = primary.unique_id
    return SecurityMasterRecord(
        symbol=resolved_symbol,
        vendor_symbol=primary.ticker or resolved_symbol,
        broker_symbol=resolved_broker,
        exchange=primary.exchange_code or "",
        currency=primary.currency or "",
        listing_window=listing_window,
        active=active,
        isin=isin,
        figi=primary.figi,
        cusip=cusip,
        sedol=sedol,
        composite_figi=primary.composite_figi,
        share_class_figi=primary.share_class_figi,
        figi_mappings=extra_mappings,
    )


@dataclass
class SecurityMaster:
    """In-memory registry of :class:`SecurityMasterRecord`.

    The registry is intentionally kept small and synchronous -- the
    intent is for callers to load it once at engine start (from YAML /
    DB / Parquet) and pass it down. Persistent storage formats live in
    consumer-facing modules; this dataclass only stores the canonical
    records.

    The registry is a regular (mutable) dataclass because instruments
    are added at startup. The records themselves are frozen, so any
    "mutation" replaces a whole record.
    """

    _records: Dict[str, SecurityMasterRecord] = field(default_factory=dict)

    def register(self, record: SecurityMasterRecord) -> None:
        """Register or replace ``record`` keyed by its internal symbol."""
        if not record.symbol:
            raise ValueError("SecurityMasterRecord.symbol must be non-empty")
        self._records[record.symbol] = record

    def get(self, symbol: str) -> Optional[SecurityMasterRecord]:
        """Return the record for ``symbol`` or ``None``."""
        return self._records.get(symbol)

    def __contains__(self, symbol: object) -> bool:
        return isinstance(symbol, str) and symbol in self._records

    def __len__(self) -> int:
        return len(self._records)

    def all_symbols(self) -> Tuple[str, ...]:
        """Return the registered internal symbols, sorted lexicographically."""
        return tuple(sorted(self._records.keys()))

    def is_active_at(self, symbol: str, on_date: Any) -> bool:
        """Return ``True`` iff ``symbol`` is active and tradeable on ``on_date``.

        Rules:
        * Unknown symbol -> ``False``.
        * Inactive record -> ``False``.
        * No listing window -> ``True`` whenever the record is active.
        * Otherwise the inclusive window must contain ``on_date``.
        """
        rec = self._records.get(symbol)
        if rec is None:
            return False
        if not rec.active:
            return False
        if rec.listing_window is None:
            return True
        start, end = rec.listing_window
        d = _coerce_date(on_date)
        return start <= d <= end


def _coerce_date(value: Any) -> _date_type:
    """Coerce datetime-ish values to a ``date``."""
    if isinstance(value, _date_type) and not hasattr(value, "hour"):
        # Pure date (datetime is a subclass of date and has hour).
        return value
    if hasattr(value, "date") and callable(value.date):
        return value.date()
    if isinstance(value, str):
        # Accept ISO date strings.
        from datetime import date as _d
        return _d.fromisoformat(value)
    raise TypeError(f"cannot coerce {value!r} to date")


__all__ = ["SecurityMaster", "SecurityMasterRecord", "from_openfigi_mapping"]
