"""PineScript exporter (R80 slice 1).

Translates a :class:`quantforge.strategies.rules.Rule` (R78) into a
TradingView PineScript v5 script. Provenance metadata identical to
the Lean exporter (R1): policy_hash, spec_hash, forge_version,
exported_at, README warning.

The exporter is deliberately conservative -- it only handles the
indicators currently supported by the rule compiler (RSI, EMA, SMA).
Adding a new indicator means extending both the rule compiler and
this exporter together so the round-trip stays consistent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

from aurora.strategies.rules.ir import (
    Action,
    ActionKind,
    BoolExpr,
    Comparator,
    ComparisonOp,
    Indicator,
    Logical,
    LogicalOp,
    PriceRef,
    Rule,
    ValueExpr,
)


@dataclass(frozen=True)
class PineScriptManifest:
    """Metadata bundled with a PineScript export."""

    policy_hash: str
    spec_hash: str
    forge_version: str
    exported_at: str


_INDICATOR_PINE = {
    "rsi": "ta.rsi(close, {0})",
    "ema": "ta.ema(close, {0})",
    "sma": "ta.sma(close, {0})",
    "ma": "ta.sma(close, {0})",
}

_OP_PINE = {
    ComparisonOp.GT: ">",
    ComparisonOp.GTE: ">=",
    ComparisonOp.LT: "<",
    ComparisonOp.LTE: "<=",
    ComparisonOp.EQ: "==",
}


def _value_pine(v: ValueExpr) -> str:
    if isinstance(v, (int, float)):
        return str(float(v))
    if isinstance(v, PriceRef):
        return v.field
    if isinstance(v, Indicator):
        tmpl = _INDICATOR_PINE.get(v.name.lower())
        if tmpl is None:
            raise KeyError(f"unsupported indicator for PineScript: {v.name}")
        return tmpl.format(*[int(a) for a in v.args])
    raise TypeError(f"unsupported value: {v!r}")


def _bool_pine(b: BoolExpr) -> str:
    if isinstance(b, Comparator):
        if b.op == ComparisonOp.CROSSES_ABOVE:
            return f"ta.crossover({_value_pine(b.left)}, {_value_pine(b.right)})"
        if b.op == ComparisonOp.CROSSES_BELOW:
            return f"ta.crossunder({_value_pine(b.left)}, {_value_pine(b.right)})"
        op = _OP_PINE.get(b.op)
        if op is None:
            raise KeyError(f"unsupported comparator: {b.op}")
        return f"({_value_pine(b.left)} {op} {_value_pine(b.right)})"
    if isinstance(b, Logical):
        if b.op == LogicalOp.NOT:
            return f"not ({_bool_pine(b.operands[0])})"
        joiner = " and " if b.op == LogicalOp.AND else " or "
        return "(" + joiner.join(_bool_pine(o) for o in b.operands) + ")"
    raise TypeError(f"unsupported bool: {b!r}")


def export_pinescript(
    *,
    rule: Rule,
    manifest: PineScriptManifest,
) -> str:
    """Return the PineScript v5 source for ``rule`` with header provenance."""
    cond = _bool_pine(rule.condition)
    action = rule.action.kind
    if action == ActionKind.BUY:
        action_block = (
            "if condition\n"
            "    strategy.entry(\"long\", strategy.long)\n"
        )
    elif action == ActionKind.SELL:
        action_block = (
            "if condition\n"
            "    strategy.entry(\"short\", strategy.short)\n"
        )
    else:
        action_block = (
            "if condition\n"
            "    strategy.close_all(comment=\"flat\")\n"
        )
    header = (
        "//@version=5\n"
        f"// QuantForge export -- DO NOT EDIT BY HAND\n"
        f"// rule_name: {rule.name}\n"
        f"// policy_hash: {manifest.policy_hash}\n"
        f"// spec_hash:   {manifest.spec_hash}\n"
        f"// forge_version: {manifest.forge_version}\n"
        f"// exported_at:   {manifest.exported_at}\n"
        f"strategy(\"{rule.name}\", overlay=true)\n"
    )
    return header + f"condition = {cond}\n" + action_block


def verify_pinescript(source: str, *, manifest: PineScriptManifest) -> bool:
    """Verify the source contains the manifest provenance comments."""
    expected = [
        f"policy_hash: {manifest.policy_hash}",
        f"spec_hash:   {manifest.spec_hash}",
        f"forge_version: {manifest.forge_version}",
        f"exported_at:   {manifest.exported_at}",
    ]
    return all(line in source for line in expected)


def make_manifest(
    *,
    policy_hash: str,
    spec_hash: str,
    forge_version: str = "1.4.0",
) -> PineScriptManifest:
    return PineScriptManifest(
        policy_hash=policy_hash,
        spec_hash=spec_hash,
        forge_version=forge_version,
        exported_at=datetime.now(timezone.utc).isoformat(),
    )


__all__ = [
    "PineScriptManifest",
    "export_pinescript",
    "verify_pinescript",
    "make_manifest",
]
