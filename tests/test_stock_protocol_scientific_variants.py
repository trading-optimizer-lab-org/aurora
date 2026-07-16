"""Explicit variant handlers: no generic execution fallbacks are permitted."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.research.stock_protocol.entries import apply_entry_rule
from aurora.research.stock_protocol.learning import learn_nonnegative_weights
from aurora.research.stock_protocol.manifest import load_protocol_manifest
from aurora.research.stock_protocol.variants import (
    executable_variant_registry,
    map_exit_rule,
)


MANIFEST = Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"


def test_every_executable_manifest_variant_has_explicit_handler():
    manifest = load_protocol_manifest(MANIFEST)
    registry = executable_variant_registry(manifest)
    expected = {
        (test.test_id, index)
        for test in manifest.tests
        if test.status == "executable"
        for index, _ in enumerate(test.variants)
    }
    assert set(registry) == expected
    assert all(record["handler"] != "generic" for record in registry.values())
    assert all(
        record["implementation_status"]
        in {"fully_implemented", "implemented_with_documented_limitation"}
        for record in registry.values()
    )


def _features() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=6)
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": ["AAA"] * len(dates),
            "breakout_20": [False, False, True, False, False, False],
            "rvol50": [1.0, 1.1, 2.0, 1.0, 1.0, 1.0],
            "adj_close": [100, 101, 104, 103, 102, 101],
            "sma_150": [99] * len(dates),
            "sma_200": [105] * len(dates),
            "sma_250": [98] * len(dates),
            "consolidation_20": [0.10] * len(dates),
            "consolidation_40": [0.20] * len(dates),
            "consolidation_60": [0.30] * len(dates),
        }
    )


def _candidate() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_date": [pd.Timestamp("2020-01-02")],
            "available_at": [pd.Timestamp("2020-01-02")],
            "symbol": ["AAA"],
            "score": [1.0],
        }
    )


def test_breakout_entry_waits_for_first_causal_breakout_close():
    result = apply_entry_rule(
        _candidate(),
        _features(),
        {"kind": "breakout", "window": 20, "max_wait_sessions": 5},
    )
    assert result.iloc[0]["signal_date"] == pd.Timestamp("2020-01-06")
    assert result.iloc[0]["available_at"] == pd.Timestamp("2020-01-06")
    assert result.iloc[0]["entry_rule"] == "breakout_20"


def test_rvol_and_sma_entries_apply_real_filters():
    rvol = apply_entry_rule(
        _candidate(),
        _features(),
        {"kind": "breakout_rvol", "window": 20, "threshold": 1.5, "max_wait_sessions": 5},
    )
    assert len(rvol) == 1
    assert rvol.iloc[0]["signal_date"] == pd.Timestamp("2020-01-06")
    above = apply_entry_rule(_candidate(), _features(), {"kind": "sma_filter", "window": 150})
    below = apply_entry_rule(_candidate(), _features(), {"kind": "sma_filter", "window": 200})
    assert len(above) == 1
    assert below.empty


def test_unknown_entry_or_exit_cannot_fall_back_to_generic_rule():
    with pytest.raises(NotImplementedError, match="entry"):
        apply_entry_rule(_candidate(), _features(), {"kind": "invented"})
    with pytest.raises(NotImplementedError, match="exit"):
        map_exit_rule(999, {"anything": True})


@pytest.mark.parametrize(
    ("test_id", "variant", "kind", "holding"),
    [
        (22, {"failure_window": 3}, "breakout_failure", 252),
        (23, {"exit": "min_10"}, "min_10", 252),
        (23, {"exit": "min_20"}, "min_20", 252),
        (23, {"exit": "sma_50"}, "sma_50", 252),
        (23, {"exit": "trailing_atr", "atr_k": 3.0}, "trailing_atr", 252),
        (24, {"stop_atr": 3}, "catastrophe_atr", 252),
        (25, {"holding_sessions": 126}, "none", 126),
        (26, {"target_pct": 20}, "take_profit", 252),
    ],
)
def test_exit_variants_map_to_specific_rules(
    test_id: int, variant: dict[str, object], kind: str, holding: int
):
    rule = map_exit_rule(test_id, variant)
    assert rule["kind"] == kind
    assert rule["holding_sessions"] == holding


def test_learned_weights_only_use_rows_available_before_training_cutoff():
    dates = pd.bdate_range("2010-01-01", periods=8)
    returns = pd.DataFrame(
        {
            "date": dates,
            "momentum": [0.01, 0.02, 0.01, -0.01, 0.99, -0.99, 0.99, -0.99],
            "h52": [0.0, 0.01, 0.02, 0.01, -0.99, 0.99, -0.99, 0.99],
        }
    )
    cutoff = dates[3]
    first = learn_nonnegative_weights(returns, train_end=cutoff)
    mutated = returns.copy()
    mutated.loc[mutated["date"] > cutoff, ["momentum", "h52"]] *= -1000
    second = learn_nonnegative_weights(mutated, train_end=cutoff)
    assert first == second
    assert sum(first.values()) == pytest.approx(1.0)
    assert all(value >= 0 for value in first.values())

