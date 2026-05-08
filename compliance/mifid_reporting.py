"""MiFID II RTS 22 transaction reporting.

Generates regulatory transaction reports compliant with ESMA RTS 22. Outputs
a CSV with the 65 required fields. Network access is not required; this
module produces deterministic CSV artifacts from in-memory trade records.

A subset of the most operationally relevant fields is implemented here.
Real production usage would extend with full short-selling indicators,
waiver flags, and country-of-trader fields per ESMA guidelines.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


# Subset of RTS 22 fields. Order matters for the regulator-facing CSV.
RTS22_FIELDS: tuple[str, ...] = (
    "transaction_reference_number",
    "trading_venue_transaction_id",
    "executing_entity_id",
    "investment_firm_covered",
    "submitting_entity_id",
    "buyer_id",
    "seller_id",
    "trading_capacity",
    "trading_date_time",
    "instrument_id",
    "instrument_id_type",
    "price",
    "price_currency",
    "quantity",
    "quantity_unit",
    "venue",
    "country_branch_membership",
    "upfront_payment",
    "complex_trade_component_id",
    "investment_decision_within_firm",
)


@dataclass
class MiFIDConfig:
    """Static config for the MiFID II reporter.

    Attributes:
        executing_entity_lei: 20-char LEI of the executing entity.
        submitting_entity_lei: 20-char LEI of the submitter (often same as exec).
        default_trading_capacity: 'DEAL', 'MTCH' or 'AOTC'.
        default_venue_mic: 4-char MIC code (e.g. 'XOFF' for OTC).
    """
    executing_entity_lei: str = "UNKNOWN"
    submitting_entity_lei: str = "UNKNOWN"
    default_trading_capacity: str = "DEAL"
    default_venue_mic: str = "XOFF"
    extra_fields: tuple[str, ...] = field(default_factory=tuple)


class MiFIDIIReporter:
    """Build RTS 22 transaction reports."""

    def __init__(self, config: Optional[MiFIDConfig] = None) -> None:
        self.config = config or MiFIDConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_report(self, trades: Iterable[dict]) -> list[dict]:
        """Return RTS 22 report rows for ``trades``.

        Args:
            trades: iterable of dict-like trade records. Required keys:
                trade_id, timestamp, symbol, side, quantity, price, currency.
                Optional: venue, isin, buyer_lei, seller_lei.
        """
        rows: list[dict] = []
        for trade in trades:
            rows.append(self._normalize(trade))
        return rows

    def export_csv(self, trades: Iterable[dict], path: str | Path) -> Path:
        """Write the report to ``path`` and return the path."""
        rows = self.build_report(trades)
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(RTS22_FIELDS))
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return out_path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _normalize(self, trade: dict) -> dict:
        ts = trade.get("timestamp") or datetime.now(timezone.utc)
        if isinstance(ts, datetime):
            ts_str = ts.astimezone(timezone.utc).isoformat()
        else:
            ts_str = str(ts)
        side = str(trade.get("side", "BUY")).upper()
        buyer_id = trade.get("buyer_lei") or (
            self.config.executing_entity_lei if side == "BUY" else "COUNTERPARTY"
        )
        seller_id = trade.get("seller_lei") or (
            self.config.executing_entity_lei if side == "SELL" else "COUNTERPARTY"
        )
        instrument_id = trade.get("isin") or trade.get("symbol", "UNKNOWN")
        instrument_id_type = "ISIN" if trade.get("isin") else "OTHR"
        return {
            "transaction_reference_number": str(trade.get("trade_id", "")),
            "trading_venue_transaction_id": str(trade.get("venue_trade_id", "")),
            "executing_entity_id": self.config.executing_entity_lei,
            "investment_firm_covered": "true",
            "submitting_entity_id": self.config.submitting_entity_lei,
            "buyer_id": buyer_id,
            "seller_id": seller_id,
            "trading_capacity": trade.get(
                "trading_capacity", self.config.default_trading_capacity
            ),
            "trading_date_time": ts_str,
            "instrument_id": instrument_id,
            "instrument_id_type": instrument_id_type,
            "price": f"{float(trade.get('price', 0.0)):.6f}",
            "price_currency": trade.get("currency", "USD"),
            "quantity": str(trade.get("quantity", 0)),
            "quantity_unit": "UNIT",
            "venue": trade.get("venue", self.config.default_venue_mic),
            "country_branch_membership": trade.get("country", "GB"),
            "upfront_payment": "0",
            "complex_trade_component_id": "",
            "investment_decision_within_firm": trade.get("decision_id", ""),
        }
