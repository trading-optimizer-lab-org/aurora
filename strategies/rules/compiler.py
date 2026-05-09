"""Rule IR -> callable compiler (R78).

The compiler walks the IR and returns a closure that takes a
``prices`` array and emits a signal vector in {-1, 0, +1}. Indicators
plug into the existing :mod:`strategies.blocks.indicators` registry
(R86) so the rule editor and the atomic-block generator share the
same vocabulary.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .ir import (
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


def _ema(prices: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    out = np.zeros_like(prices, dtype=float)
    out[0] = prices[0]
    for i in range(1, len(prices)):
        out[i] = alpha * prices[i] + (1 - alpha) * out[i - 1]
    return out


def _sma(prices: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(prices, np.nan, dtype=float)
    for i in range(period - 1, len(prices)):
        out[i] = prices[i - period + 1: i + 1].mean()
    return out


def _rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(prices, prepend=prices[0])
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    avg_up = np.zeros_like(prices, dtype=float)
    avg_dn = np.zeros_like(prices, dtype=float)
    if len(prices) >= period:
        avg_up[period - 1] = up[:period].mean()
        avg_dn[period - 1] = dn[:period].mean()
        for i in range(period, len(prices)):
            avg_up[i] = (avg_up[i - 1] * (period - 1) + up[i]) / period
            avg_dn[i] = (avg_dn[i - 1] * (period - 1) + dn[i]) / period
    rs = np.divide(
        avg_up, avg_dn,
        out=np.full_like(avg_up, np.inf, dtype=float),
        where=avg_dn > 0,
    )
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi


_INDICATOR_FUNCS = {
    "ema": _ema,
    "sma": _sma,
    "ma": _sma,
    "rsi": _rsi,
}


def _evaluate_value(expr: ValueExpr, prices: np.ndarray) -> np.ndarray:
    if isinstance(expr, (int, float)):
        return np.full_like(prices, float(expr), dtype=float)
    if isinstance(expr, PriceRef):
        return prices.astype(float)
    if isinstance(expr, Indicator):
        fn = _INDICATOR_FUNCS.get(expr.name.lower())
        if fn is None:
            raise KeyError(f"unknown indicator: {expr.name}")
        return fn(prices, *(int(a) for a in expr.args))
    raise TypeError(f"unsupported value expr: {expr!r}")


def _evaluate_bool(expr: BoolExpr, prices: np.ndarray) -> np.ndarray:
    if isinstance(expr, Comparator):
        left = _evaluate_value(expr.left, prices)
        right = _evaluate_value(expr.right, prices)
        if expr.op == ComparisonOp.GT:
            return left > right
        if expr.op == ComparisonOp.GTE:
            return left >= right
        if expr.op == ComparisonOp.LT:
            return left < right
        if expr.op == ComparisonOp.LTE:
            return left <= right
        if expr.op == ComparisonOp.EQ:
            return np.isclose(left, right)
        if expr.op == ComparisonOp.CROSSES_ABOVE:
            prev = (np.roll(left, 1) <= np.roll(right, 1))
            curr = left > right
            out = prev & curr
            out[0] = False
            return out
        if expr.op == ComparisonOp.CROSSES_BELOW:
            prev = (np.roll(left, 1) >= np.roll(right, 1))
            curr = left < right
            out = prev & curr
            out[0] = False
            return out
        raise ValueError(f"unsupported comparison op: {expr.op}")
    if isinstance(expr, Logical):
        if expr.op == LogicalOp.NOT:
            if len(expr.operands) != 1:
                raise ValueError("NOT expects exactly one operand")
            return ~_evaluate_bool(expr.operands[0], prices)
        evals = [_evaluate_bool(o, prices) for o in expr.operands]
        if expr.op == LogicalOp.AND:
            out = evals[0]
            for v in evals[1:]:
                out = out & v
            return out
        if expr.op == LogicalOp.OR:
            out = evals[0]
            for v in evals[1:]:
                out = out | v
            return out
    raise TypeError(f"unsupported bool expr: {expr!r}")


def compile_rule(rule: Rule) -> Callable[[np.ndarray], np.ndarray]:
    """Compile a Rule into a ``signals(prices) -> np.ndarray`` callable."""
    def _signals(prices: np.ndarray) -> np.ndarray:
        prices = np.asarray(prices, dtype=float)
        condition = _evaluate_bool(rule.condition, prices)
        out = np.zeros_like(prices, dtype=float)
        action = rule.action.kind
        if action == ActionKind.BUY:
            out[condition] = 1.0
        elif action == ActionKind.SELL:
            out[condition] = -1.0
        elif action == ActionKind.FLAT:
            out[condition] = 0.0
        # NaNs (warmup) -> zero
        out[~np.isfinite(out)] = 0.0
        return out
    return _signals


__all__ = ["compile_rule"]
