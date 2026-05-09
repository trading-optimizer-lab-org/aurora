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
from typing import Any, Dict, Optional, Tuple


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


__all__ = ["SecurityMaster", "SecurityMasterRecord"]
