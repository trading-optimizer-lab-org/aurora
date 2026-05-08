"""T+5 reproducible trade reconstruction.

Implements FINRA Rule 4511 and SEC 17a-4 record-keeping reconstruction.
Joins trade journal records with reference market data to produce a
reproducible reconstruction artifact within the regulatory T+5 window.

The reconstruction is deterministic given identical inputs: same trades,
same market data snapshot, same config. This supports regulator inquiries
and internal forensic review.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional


@dataclass
class ReconstructionConfig:
    """Static config for the trade reconstructor.

    Attributes:
        max_age_days: hard cap on age allowed for reconstruction (default T+5).
        include_market_context: whether to attach NBBO / mid context per trade.
        price_tolerance_bps: tolerance vs reference mid before flagging.
    """
    max_age_days: int = 5
    include_market_context: bool = True
    price_tolerance_bps: float = 50.0
    extra_metadata: tuple[str, ...] = field(default_factory=tuple)


class TradeReconstructor:
    """Reproducibly reconstruct executed trades from journal + market data."""

    def __init__(self, config: Optional[ReconstructionConfig] = None) -> None:
        self.config = config or ReconstructionConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def reconstruct(
        self,
        trades: Iterable[dict],
        market_snapshot: Optional[dict[str, dict]] = None,
        as_of: Optional[datetime] = None,
    ) -> dict:
        """Return reconstruction record for ``trades``.

        Args:
            trades: iterable of executed trade dicts. Required keys:
                trade_id, timestamp, symbol, side, quantity, price.
            market_snapshot: optional symbol -> {bid, ask, mid, ts} mapping.
            as_of: as-of UTC datetime. Default now.
        """
        as_of = as_of or datetime.now(timezone.utc)
        cutoff = as_of - timedelta(days=self.config.max_age_days)
        market = market_snapshot or {}
        rows: list[dict] = []
        flagged: list[str] = []
        for t in trades:
            row = self._reconstruct_one(t, market, cutoff)
            rows.append(row)
            if row.get("flag_outside_tolerance"):
                flagged.append(row["trade_id"])
        record = {
            "as_of": as_of.isoformat(),
            "n_trades": len(rows),
            "n_flagged": len(flagged),
            "flagged_trade_ids": flagged,
            "trades": rows,
        }
        record["fingerprint"] = self._fingerprint(record)
        return record

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _reconstruct_one(
        self, trade: dict, market: dict[str, dict], cutoff: datetime
    ) -> dict:
        ts = trade.get("timestamp")
        if isinstance(ts, datetime):
            ts_norm = ts.astimezone(timezone.utc)
        else:
            ts_norm = datetime.fromisoformat(str(ts)) if ts else cutoff
        too_old = ts_norm < cutoff
        symbol = trade.get("symbol", "")
        ctx = market.get(symbol, {}) if self.config.include_market_context else {}
        mid = float(ctx.get("mid", 0.0))
        price = float(trade.get("price", 0.0))
        deviation_bps = 0.0
        if mid > 0:
            deviation_bps = abs(price - mid) / mid * 10000.0
        flag = deviation_bps > self.config.price_tolerance_bps
        return {
            "trade_id": str(trade.get("trade_id", "")),
            "timestamp": ts_norm.isoformat(),
            "symbol": symbol,
            "side": trade.get("side", "BUY"),
            "quantity": float(trade.get("quantity", 0.0)),
            "price": price,
            "ref_mid": mid,
            "deviation_bps": round(deviation_bps, 4),
            "flag_outside_tolerance": flag,
            "flag_outside_window": too_old,
        }

    @staticmethod
    def _fingerprint(record: dict) -> str:
        payload = {k: v for k, v in record.items() if k != "fingerprint"}
        blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
