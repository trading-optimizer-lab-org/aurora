"""Layered scientific campaign orchestration contracts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import aurora.research.stock_protocol.campaign as campaign_module
import aurora.research.stock_protocol.signals as signals_module

from aurora.research.stock_protocol.campaign import (
    DEVELOPMENT_END,
    HOLDOUT_END,
    HOLDOUT_START,
    canonical_candidate_id,
    evaluate_spec,
    expand_layer_specs,
    initial_signal_specs,
)
from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel
from aurora.research.stock_protocol.manifest import load_protocol_manifest


MANIFEST = Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"


def _panel() -> ResearchPanel:
    dates = pd.bdate_range("2000-01-03", periods=420)
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(("AAA", "BBB", "CCC")):
        trend = 0.0008 - symbol_index * 0.00025
        close = 100.0 * np.cumprod(np.full(len(dates), 1.0 + trend))
        for index, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close[index] * 0.999,
                    "high": close[index] * 1.01,
                    "low": close[index] * 0.99,
                    "close": close[index],
                    "adj_close": close[index],
                    "volume": 1_000_000.0 + index,
                    "dividends": 0.0,
                    "stock_splits": 0.0,
                }
            )
    frame = pd.DataFrame(rows)
    audit = PackAudit(
        "source", "pack", str(dates.min().date()), "2020-12-31",
        len(frame), 3, 0, False, False, "dataset-hash"
    )
    return ResearchPanel(frame, audit)


def test_initial_signal_specs_cover_all_selection_shapes():
    manifest = load_protocol_manifest(MANIFEST)
    specs = initial_signal_specs(manifest)
    kinds = {spec["selection"]["kind"] for spec in specs}
    percentages = {
        float(spec["selection"]["value"])
        for spec in specs
        if spec["selection"]["kind"] == "top_percent"
    }
    assert {"top_percent", "top_n", "quintile", "decile"} <= kinds
    assert {5.0, 10.0, 20.0, 30.0} <= percentages
    assert {int(spec["signal_test_id"]) for spec in specs} == {1, 2, 3, 8, 9}
    assert len({canonical_candidate_id(spec) for spec in specs}) == len(specs)


def test_candidate_id_is_canonical_and_independent_of_key_order():
    left = {"signal_test_id": 1, "selection": {"kind": "top_percent", "value": 10}}
    right = {"selection": {"value": 10, "kind": "top_percent"}, "signal_test_id": 1}
    assert canonical_candidate_id(left) == canonical_candidate_id(right)


@pytest.mark.parametrize("phase", ["entry", "exit", "portfolio", "cost"])
def test_each_layer_expansion_preserves_frozen_upstream_identity(phase: str):
    manifest = load_protocol_manifest(MANIFEST)
    upstream = {
        "signal_test_id": 1,
        "signal_variant": {"lookback": 252, "skip": 21},
        "selection": {"kind": "top_percent", "value": 10},
    }
    upstream_id = canonical_candidate_id(upstream)
    expanded = expand_layer_specs([upstream], phase, manifest)
    assert expanded
    assert all(spec["upstream_candidate_id"] == upstream_id for spec in expanded)
    assert len({canonical_candidate_id(spec) for spec in expanded}) == len(expanded)


def test_unknown_layer_cannot_reuse_a_generic_expansion():
    manifest = load_protocol_manifest(MANIFEST)
    with pytest.raises(ValueError, match="unknown layer"):
        expand_layer_specs([{"signal_test_id": 1}], "invented", manifest)


def test_weight_layer_builds_one_real_ensemble_per_weighting_method():
    manifest = load_protocol_manifest(MANIFEST)
    upstream = [
        {
            "signal_test_id": 1,
            "signal_variant": {"lookback": 252, "skip": 21},
            "selection": {"kind": "top_percent", "value": 10},
        },
        {
            "signal_test_id": 8,
            "signal_variant": {"lookback": 252},
            "selection": {"kind": "top_percent", "value": 10},
        },
    ]
    expanded = expand_layer_specs(upstream, "weight", manifest)
    assert len(expanded) == 2
    assert {spec["signal_weights"]["weights"] for spec in expanded} == {
        "equal",
        "ridge_nonnegative",
    }
    assert all(len(spec["component_signals"]) == 2 for spec in expanded)
    assert all(len(spec["upstream_candidate_ids"]) == 2 for spec in expanded)


def test_evaluation_produces_daily_equity_and_real_ledgers():
    spec = {
        "signal_test_id": 1,
        "signal_variant": {"lookback": 252, "skip": 21},
        "selection": {"kind": "top_n", "value": 1},
        "entry": {"kind": "immediate_next_open", "max_wait_sessions": 0},
        "exit": {"kind": "none", "holding_sessions": 20},
        "portfolio": {"sizing": "equal", "asset_cap": 1.0},
        "cost_bps": 10,
    }
    result = evaluate_spec(
        _panel(),
        spec,
        start="2000-01-03",
        end=str(_panel().frame["date"].max().date()),
    )
    assert result.status == "evaluated"
    assert not result.equity_curve.empty
    assert result.equity_curve["date"].is_monotonic_increasing
    assert not result.trade_ledger.empty
    assert not result.position_ledger.empty
    assert result.metrics["trades"] > 0
    assert result.locked_opened is False
    assert result.candidate_id == canonical_candidate_id(spec)


def test_evaluation_computes_the_feature_panel_only_once(monkeypatch):
    original = signals_module.compute_features
    calls = 0

    def counted(panel):
        nonlocal calls
        calls += 1
        return original(panel)

    monkeypatch.setattr(campaign_module, "compute_features", counted)
    monkeypatch.setattr(signals_module, "compute_features", counted)
    spec = {
        "signal_test_id": 1,
        "signal_variant": {"lookback": 252, "skip": 21},
        "selection": {"kind": "top_n", "value": 1},
        "entry": {"kind": "immediate_next_open", "max_wait_sessions": 0},
        "exit": {"kind": "none", "holding_sessions": 20},
        "portfolio": {"sizing": "equal", "asset_cap": 1.0},
        "cost_bps": 10,
    }

    result = evaluate_spec(
        _panel(),
        spec,
        start="2000-01-03",
        end=str(_panel().frame["date"].max().date()),
    )

    assert result.status == "evaluated"
    assert calls == 1


def test_development_and_holdout_boundaries_are_disjoint_and_pre_locked():
    assert DEVELOPMENT_END == pd.Timestamp("2015-12-31")
    assert HOLDOUT_START == pd.Timestamp("2016-01-01")
    assert HOLDOUT_END == pd.Timestamp("2020-12-31")
    assert DEVELOPMENT_END < HOLDOUT_START <= HOLDOUT_END < pd.Timestamp("2021-01-01")
