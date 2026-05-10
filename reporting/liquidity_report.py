"""R163 - Operator-facing liquidity report.

Renders a :class:`LiquidityReport` from the per-symbol records produced
by :mod:`aurora.data_contracts.liquidity`.

The report is **deterministic by construction**: rows are sorted by
symbol and the markdown body never embeds wall-clock timestamps or
hashes derived from runtime state. ``policy_hash`` is carried through
verbatim so the operator can match a report against the policy that
generated it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from aurora.data_contracts.liquidity import LiquidityRecord, flag_thin_symbols


# Placeholder used when no policy hash is supplied. Never silently
# mutated; callers must pass the real hash to suppress the placeholder.
_POLICY_HASH_PLACEHOLDER = "policy-hash-pending"


@dataclass(frozen=True)
class LiquidityReport:
    """Operator-facing snapshot of the liquidity dataset."""

    records: Tuple[LiquidityRecord, ...]
    policy_hash: str
    min_dollar_volume: float
    min_adv: float
    low_volume_symbols: Tuple[str, ...] = field(default_factory=tuple)
    thin_symbols: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict:
        return {
            "policy_hash": self.policy_hash,
            "min_dollar_volume": self.min_dollar_volume,
            "min_adv": self.min_adv,
            "low_volume_symbols": list(self.low_volume_symbols),
            "thin_symbols": list(self.thin_symbols),
            "records": [r.to_dict() for r in self.records],
        }

    def to_markdown(self) -> str:
        lines: List[str] = []
        lines.append("# Liquidity Report")
        lines.append("")
        lines.append(f"- policy_hash: `{self.policy_hash}`")
        lines.append(f"- min_dollar_volume: {self.min_dollar_volume:,.0f}")
        lines.append(f"- min_adv: {self.min_adv:,.0f}")
        lines.append(f"- symbols: {len(self.records)}")
        lines.append("")
        lines.append("## Low-volume symbols")
        if self.low_volume_symbols:
            for sym in self.low_volume_symbols:
                lines.append(f"- {sym}")
        else:
            lines.append("- (none)")
        lines.append("")
        lines.append("## Thin symbols (failed floor)")
        if self.thin_symbols:
            for sym in self.thin_symbols:
                lines.append(f"- {sym}")
        else:
            lines.append("- (none)")
        lines.append("")
        lines.append("## Per-symbol detail")
        lines.append("")
        lines.append(
            "| symbol | asof | rolling_adv | dollar_volume | "
            "vol_ann | turnover | spread_bps | slippage_bps | capacity_usd | "
            "low_vol | source |"
        )
        lines.append(
            "|---|---|---|---|---|---|---|---|---|---|---|"
        )
        for r in self.records:
            lines.append(
                "| {sym} | {asof} | {adv:,.0f} | {dv:,.0f} | "
                "{vol:.4f} | {turn:.4f} | {spread:.2f} | {slip:.2f} | "
                "{cap:,.0f} | {flag} | {src} |".format(
                    sym=r.symbol,
                    asof=r.asof_date.date().isoformat(),
                    adv=r.rolling_adv,
                    dv=r.dollar_volume,
                    vol=r.volatility_annualised,
                    turn=r.turnover,
                    spread=r.estimated_spread_bps,
                    slip=r.estimated_slippage_bps,
                    cap=r.capacity_usd,
                    flag="yes" if r.low_volume_flag else "no",
                    src=r.source or "-",
                )
            )
        lines.append("")
        return "\n".join(lines)


def render_liquidity_report(
    records: Sequence[LiquidityRecord],
    *,
    policy_hash: str = _POLICY_HASH_PLACEHOLDER,
    min_dollar_volume: float = 0.0,
    min_adv: float = 0.0,
) -> LiquidityReport:
    """Build a :class:`LiquidityReport` from a sequence of records.

    The records are sorted alphabetically by symbol so the rendered
    markdown is byte-for-byte deterministic across runs.
    """
    if min_dollar_volume < 0.0:
        raise ValueError("min_dollar_volume must be >= 0")
    if min_adv < 0.0:
        raise ValueError("min_adv must be >= 0")

    sorted_records = tuple(sorted(records, key=lambda r: r.symbol))
    low_volume_symbols = tuple(
        sorted(r.symbol for r in sorted_records if r.low_volume_flag)
    )
    thin_symbols = tuple(
        flag_thin_symbols(
            sorted_records,
            min_dollar_volume=min_dollar_volume,
            min_adv=min_adv,
        )
    )
    return LiquidityReport(
        records=sorted_records,
        policy_hash=policy_hash,
        min_dollar_volume=float(min_dollar_volume),
        min_adv=float(min_adv),
        low_volume_symbols=low_volume_symbols,
        thin_symbols=thin_symbols,
    )


__all__ = [
    "LiquidityReport",
    "render_liquidity_report",
]
