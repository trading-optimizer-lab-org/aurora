"""CFTC Form CTA position reporting.

Aggregates futures and options positions for a Commodity Trading Advisor
filing per CFTC Part 4 rules. Output is a normalized list of position rows
suitable for inclusion in a Form 7-R or for periodic NFA reporting.

This module produces the data payload only. Real submissions go through
NFA EasyFile or CFTC Portal and require operator review.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


CTA_FIELDS: tuple[str, ...] = (
    "report_date",
    "filer_nfa_id",
    "account_id",
    "contract_market",
    "contract_symbol",
    "contract_month",
    "long_positions",
    "short_positions",
    "net_position",
    "notional_usd",
    "currency",
    "is_speculative",
)


@dataclass
class CTAFormConfig:
    """Static config for the CFTC CTA reporter.

    Attributes:
        filer_nfa_id: NFA-assigned ID of the filing CTA.
        report_period: ISO date string for the as-of date.
        speculative_threshold_pct: net pos / open interest treated as speculative.
        default_currency: base currency for notional valuation.
    """
    filer_nfa_id: str = "UNKNOWN"
    report_period: str = "2025-03-31"
    speculative_threshold_pct: float = 5.0
    default_currency: str = "USD"
    extra_fields: tuple[str, ...] = field(default_factory=tuple)


class CTAFormReporter:
    """Build CFTC Form CTA position reports."""

    def __init__(self, config: Optional[CTAFormConfig] = None) -> None:
        self.config = config or CTAFormConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_report(self, positions: Iterable[dict]) -> list[dict]:
        """Aggregate positions into CTA report rows.

        Args:
            positions: iterable of dicts with keys: account_id, contract_symbol,
                contract_market, contract_month, long, short, notional, currency.
        """
        rows: list[dict] = []
        for pos in positions:
            rows.append(self._normalize(pos))
        return rows

    def export_csv(self, positions: Iterable[dict], path: str | Path) -> Path:
        """Write the report to ``path`` and return the path."""
        rows = self.build_report(positions)
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(CTA_FIELDS))
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return out_path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _normalize(self, pos: dict) -> dict:
        long_qty = int(pos.get("long", 0))
        short_qty = int(pos.get("short", 0))
        net = long_qty - short_qty
        notional = float(pos.get("notional", 0.0))
        open_interest = max(int(pos.get("open_interest", 0)), 1)
        is_spec = abs(net) / open_interest * 100.0 >= self.config.speculative_threshold_pct
        return {
            "report_date": self.config.report_period,
            "filer_nfa_id": self.config.filer_nfa_id,
            "account_id": str(pos.get("account_id", "MAIN")),
            "contract_market": pos.get("contract_market", "CME"),
            "contract_symbol": pos.get("contract_symbol", "UNKNOWN"),
            "contract_month": pos.get("contract_month", ""),
            "long_positions": long_qty,
            "short_positions": short_qty,
            "net_position": net,
            "notional_usd": f"{notional:.2f}",
            "currency": pos.get("currency", self.config.default_currency),
            "is_speculative": "Y" if is_spec else "N",
        }

    @staticmethod
    def now_utc() -> datetime:
        """Return current UTC time. Hook for tests if needed."""
        return datetime.now(timezone.utc)
