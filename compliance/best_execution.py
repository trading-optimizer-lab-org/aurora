"""SEC Rule 605/606 best execution reporting.

Rule 605 covers market center execution quality (effective spreads, price
improvement, fill rates). Rule 606 covers broker-dealer order routing
disclosures by venue and security category.

This module aggregates executed orders into the metrics required by both
rules and produces a JSON-serializable report.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class BestExecutionConfig:
    """Static config for the best execution reporter.

    Attributes:
        report_period: ISO date string identifying the reporting period.
        size_buckets: order size buckets for Rule 605 disaggregation.
        price_improvement_bps_threshold: bps gain treated as price improvement.
    """
    report_period: str = "2025-Q1"
    size_buckets: tuple[tuple[int, int], ...] = (
        (100, 499), (500, 1999), (2000, 4999), (5000, 9999),
    )
    price_improvement_bps_threshold: float = 0.0
    extra_fields: tuple[str, ...] = field(default_factory=tuple)


class BestExecutionReporter:
    """Build SEC Rule 605/606 reports."""

    def __init__(self, config: Optional[BestExecutionConfig] = None) -> None:
        self.config = config or BestExecutionConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_605_report(self, orders: Iterable[dict]) -> dict:
        """Return Rule 605 execution-quality summary.

        Args:
            orders: iterable of dicts with keys: symbol, side, size,
                quoted_spread_bps, effective_spread_bps, executed_price,
                nbbo_mid, fill_status ('filled'|'partial'|'unfilled').
        """
        orders = list(orders)
        n = len(orders)
        if n == 0:
            return {"period": self.config.report_period, "n_orders": 0, "buckets": []}
        bucket_rows: list[dict] = []
        for low, high in self.config.size_buckets:
            subset = [o for o in orders if low <= int(o.get("size", 0)) <= high]
            bucket_rows.append(self._summarize(subset, low, high))
        return {
            "period": self.config.report_period,
            "n_orders": n,
            "fill_rate_pct": self._fill_rate(orders),
            "avg_effective_spread_bps": self._avg(
                orders, "effective_spread_bps"
            ),
            "avg_quoted_spread_bps": self._avg(orders, "quoted_spread_bps"),
            "buckets": bucket_rows,
        }

    def build_606_report(self, orders: Iterable[dict]) -> dict:
        """Return Rule 606 order-routing summary by venue.

        Args:
            orders: iterable of dicts with keys: venue, security_category
                ('NMS'|'OPT'|'FI'), size, payment_for_order_flow_cents.
        """
        orders = list(orders)
        venues: dict[str, dict] = defaultdict(lambda: {
            "n_orders": 0, "total_size": 0, "pfof_cents": 0.0,
        })
        cat_totals: dict[str, int] = defaultdict(int)
        for o in orders:
            venue = str(o.get("venue", "UNKNOWN"))
            cat = str(o.get("security_category", "NMS"))
            size = int(o.get("size", 0))
            venues[venue]["n_orders"] += 1
            venues[venue]["total_size"] += size
            venues[venue]["pfof_cents"] += float(
                o.get("payment_for_order_flow_cents", 0.0)
            )
            cat_totals[cat] += size
        return {
            "period": self.config.report_period,
            "n_orders": len(orders),
            "venues": [
                {"venue": v, **stats} for v, stats in sorted(venues.items())
            ],
            "category_totals": dict(cat_totals),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _summarize(self, orders: list[dict], low: int, high: int) -> dict:
        n = len(orders)
        improved = sum(
            1 for o in orders
            if float(o.get("price_improvement_bps", 0.0))
            > self.config.price_improvement_bps_threshold
        )
        return {
            "size_low": low,
            "size_high": high,
            "n_orders": n,
            "fill_rate_pct": self._fill_rate(orders),
            "avg_effective_spread_bps": self._avg(orders, "effective_spread_bps"),
            "n_price_improved": improved,
            "price_improvement_pct": (improved / n * 100.0) if n else 0.0,
        }

    @staticmethod
    def _avg(orders: list[dict], key: str) -> float:
        vals = [float(o.get(key, 0.0)) for o in orders]
        return float(statistics.fmean(vals)) if vals else 0.0

    @staticmethod
    def _fill_rate(orders: list[dict]) -> float:
        if not orders:
            return 0.0
        filled = sum(1 for o in orders if o.get("fill_status") == "filled")
        return filled / len(orders) * 100.0
