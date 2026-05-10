"""Tests for R181 point-in-time feature store."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.core.feature_store import (
    FeatureDefinition,
    FeatureStore,
    FeatureUnavailable,
    FeatureValue,
    cache_key,
)


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def _make_definition(name: str = "rsi14", version: str = "v1") -> FeatureDefinition:
    return FeatureDefinition(
        name=name,
        version=version,
        inputs=("close",),
        lookback=14,
        owner="op",
        frequency="daily",
        null_policy="drop",
    )


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------


def test_definition_requires_name_and_version():
    with pytest.raises(ValueError):
        FeatureDefinition(name="", version="v1", inputs=(), lookback=1)
    with pytest.raises(ValueError):
        FeatureDefinition(name="x", version="", inputs=(), lookback=1)


def test_definition_rejects_bad_null_policy():
    with pytest.raises(ValueError):
        FeatureDefinition(
            name="x", version="v1", inputs=(), lookback=1,
            null_policy="bogus",
        )


def test_code_hash_changes_when_signature_changes():
    a = _make_definition()
    b = FeatureDefinition(
        name="rsi14", version="v1", inputs=("open",), lookback=14,
    )
    assert a.code_hash() != b.code_hash()


# ---------------------------------------------------------------------------
# Registration / put / read
# ---------------------------------------------------------------------------


def test_register_blocks_duplicates_unless_replace():
    store = FeatureStore()
    store.register(_make_definition())
    with pytest.raises(ValueError):
        store.register(_make_definition())
    store.register(_make_definition(), replace=True)


def test_put_requires_registration():
    store = FeatureStore()
    val = FeatureValue(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_time=_ts("2024-01-02"), available_time=_ts("2024-01-02"),
        value=55.0, inputs_hash="h",
    )
    with pytest.raises(KeyError):
        store.put(val)


def test_put_blocks_when_available_before_decision():
    store = FeatureStore()
    store.register(_make_definition())
    bad = FeatureValue(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_time=_ts("2024-01-03"),
        available_time=_ts("2024-01-02"),
        value=55.0, inputs_hash="h",
    )
    with pytest.raises(ValueError):
        store.put(bad)


def test_feature_at_returns_latest_available_value():
    store = FeatureStore()
    store.register(_make_definition())
    store.put_series(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_times=[_ts("2024-01-02"), _ts("2024-01-03")],
        available_times=[_ts("2024-01-03"), _ts("2024-01-04")],
        values=[55.0, 60.0],
        inputs_hash="h",
    )
    result = store.feature_at(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_time=_ts("2024-01-03"),
    )
    assert result.value == 55.0


def test_feature_at_refuses_future_values():
    store = FeatureStore()
    store.register(_make_definition())
    store.put(FeatureValue(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_time=_ts("2024-01-02"),
        available_time=_ts("2024-01-05"),
        value=55.0, inputs_hash="h",
    ))
    with pytest.raises(FeatureUnavailable):
        store.feature_at(
            feature_name="rsi14", feature_version="v1", symbol="SPY",
            decision_time=_ts("2024-01-04"),
        )


def test_feature_at_returns_value_when_available_equal_to_decision():
    store = FeatureStore()
    store.register(_make_definition())
    store.put(FeatureValue(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_time=_ts("2024-01-02"),
        available_time=_ts("2024-01-02"),
        value=55.0, inputs_hash="h",
    ))
    result = store.feature_at(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_time=_ts("2024-01-02"),
    )
    assert result.value == 55.0


def test_history_returns_all_values_for_symbol():
    store = FeatureStore()
    store.register(_make_definition())
    store.put_series(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_times=[_ts("2024-01-02"), _ts("2024-01-03")],
        available_times=[_ts("2024-01-02"), _ts("2024-01-03")],
        values=[55.0, 60.0],
        inputs_hash="h",
    )
    history = store.history(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
    )
    assert [v.value for v in history] == [55.0, 60.0]


def test_missingness_counts_nans():
    store = FeatureStore()
    store.register(_make_definition())
    store.put_series(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_times=[_ts("2024-01-02"), _ts("2024-01-03"), _ts("2024-01-04")],
        available_times=[_ts("2024-01-02"), _ts("2024-01-03"), _ts("2024-01-04")],
        values=[55.0, float("nan"), 60.0],
        inputs_hash="h",
    )
    miss = store.missingness(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
    )
    assert miss == 1


def test_content_hash_changes_when_value_changes():
    store_a = FeatureStore()
    store_b = FeatureStore()
    for s in (store_a, store_b):
        s.register(_make_definition())
    store_a.put(FeatureValue(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_time=_ts("2024-01-02"),
        available_time=_ts("2024-01-02"),
        value=55.0, inputs_hash="h",
    ))
    store_b.put(FeatureValue(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
        decision_time=_ts("2024-01-02"),
        available_time=_ts("2024-01-02"),
        value=60.0, inputs_hash="h",
    ))
    assert store_a.content_hash(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
    ) != store_b.content_hash(
        feature_name="rsi14", feature_version="v1", symbol="SPY",
    )


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def test_cache_key_deterministic_for_same_inputs():
    f = _make_definition()
    inputs = [("snapshot_v1", "abc"), ("policy_v1", "def")]
    a = cache_key(f, inputs, policy_hash="P")
    b = cache_key(f, inputs, policy_hash="P")
    assert a == b


def test_cache_key_changes_when_policy_changes():
    f = _make_definition()
    a = cache_key(f, [("snapshot", "abc")], policy_hash="P1")
    b = cache_key(f, [("snapshot", "abc")], policy_hash="P2")
    assert a != b


def test_cache_key_changes_when_inputs_change():
    f = _make_definition()
    a = cache_key(f, [("snapshot", "abc")], policy_hash="P")
    b = cache_key(f, [("snapshot", "xyz")], policy_hash="P")
    assert a != b
