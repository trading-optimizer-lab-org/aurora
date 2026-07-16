"""Explicit handler registry for every executable stock-protocol variant."""

from __future__ import annotations

from collections.abc import Mapping

from .manifest import ProtocolManifest


_LIMITED_TESTS = {13, 17, 21, 28, 29}


def _handler(test_id: int, variant: Mapping[str, object]) -> str:
    if test_id in {1, 2, 3, 8, 9}:
        return f"signals.test_{test_id}"
    if test_id == 13:
        return "learning.equal" if variant.get("weights") == "equal" else "learning.nonnegative_train_only"
    if test_id == 15:
        return "entries.immediate_next_open"
    if test_id == 16:
        return "entries.breakout"
    if test_id == 17:
        return "entries.consolidation"
    if test_id == 18:
        return "entries.breakout_rvol"
    if test_id == 19:
        return "entries.close_vs_next_open_audit"
    if test_id == 20:
        return "entries.sma_filter"
    if test_id == 21:
        return "exits.ranking_hysteresis"
    if test_id == 22:
        return "exits.breakout_failure"
    if test_id == 23:
        return f"exits.{variant.get('exit')}"
    if test_id == 24:
        return "exits.catastrophe_atr"
    if test_id == 25:
        return "exits.time"
    if test_id == 26:
        return "exits.take_profit"
    if test_id == 27:
        return f"portfolio.sizing.{variant.get('sizing')}"
    if test_id == 28:
        return "portfolio.constraints"
    if test_id == 29:
        return f"portfolio.regime.{variant.get('regime')}"
    if test_id == 32:
        return "portfolio.two_sided_costs"
    if test_id == 34:
        return "validation.purged_walk_forward"
    if test_id == 35:
        return f"robustness.{variant.get('method')}"
    if test_id == 36:
        return "pareto.non_dominated_front"
    raise NotImplementedError(f"test {test_id} has no executable handler")


def executable_variant_registry(
    manifest: ProtocolManifest,
) -> dict[tuple[int, int], dict[str, object]]:
    registry: dict[tuple[int, int], dict[str, object]] = {}
    for test in manifest.tests:
        if test.status != "executable":
            continue
        for index, variant in enumerate(test.variants):
            registry[(test.test_id, index)] = {
                "test_id": test.test_id,
                "variant_index": index,
                "variant": dict(variant),
                "handler": _handler(test.test_id, variant),
                "implementation_status": (
                    "implemented_with_documented_limitation"
                    if test.test_id in _LIMITED_TESTS
                    else "fully_implemented"
                ),
            }
    return registry


def map_entry_rule(test_id: int, variant: Mapping[str, object]) -> dict[str, object]:
    if test_id == 15:
        return {"kind": "immediate_next_open", "max_wait_sessions": 0}
    if test_id == 16:
        return {"kind": "breakout", "window": int(variant["window"]), "max_wait_sessions": 21}
    if test_id == 17:
        return {"kind": "consolidation", "window": int(variant["window"]), "max_width": 0.15}
    if test_id == 18:
        return {"kind": "breakout_rvol", "window": 20, "threshold": float(variant["threshold"]), "max_wait_sessions": 21}
    if test_id == 19:
        return {"kind": "close_vs_next_open", "max_wait_sessions": 0}
    if test_id == 20:
        return {"kind": "sma_filter", "window": int(variant["sma"]), "max_wait_sessions": 0}
    raise NotImplementedError(f"entry test {test_id} is not implemented")


def map_exit_rule(test_id: int, variant: Mapping[str, object]) -> dict[str, object]:
    if test_id == 21:
        return {
            "kind": "ranking_hysteresis",
            "entry_percentile": float(variant["entry_percentile"]),
            "keep_percentile": float(variant["keep_percentile"]),
            "holding_sessions": 252,
        }
    if test_id == 22:
        return {
            "kind": "breakout_failure",
            "failure_window": int(variant["failure_window"]),
            "holding_sessions": 252,
        }
    if test_id == 23:
        kind = str(variant["exit"])
        rule = {"kind": kind, "holding_sessions": 252}
        if kind == "trailing_atr":
            rule["k"] = float(variant["atr_k"])
        return rule
    if test_id == 24:
        value = variant.get("stop_atr")
        if isinstance(value, str) and value.lower() == "none":
            return {"kind": "none", "holding_sessions": 252}
        return {"kind": "catastrophe_atr", "k": float(value), "holding_sessions": 252}
    if test_id == 25:
        return {"kind": "none", "holding_sessions": int(variant["holding_sessions"])}
    if test_id == 26:
        return {"kind": "take_profit", "target_pct": float(variant["target_pct"]), "holding_sessions": 252}
    raise NotImplementedError(f"exit test {test_id} is not implemented")
