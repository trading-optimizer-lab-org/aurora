import pandas as pd

from scripts.run_sp500_strategy_catalog_shard import compose_signals


def _s(values):
    return pd.Series(values, index=pd.date_range("2000-01-01", periods=len(values)))


def test_catalog_compositions_follow_frozen_semantics():
    left, right = _s([1, 1, -1, -1]), _s([1, -1, -1, 0])
    assert compose_signals([left, right], {"kind": "and"}).tolist()[:1] == [1.0]
    assert compose_signals([left, right], {"kind": "gate", "base_component_index": 0}).fillna(0).tolist() == [1, 0, -1, 0]
    assert compose_signals([left, right], {"kind": "override", "base_component_index": 0, "priority_component_index": 1}).fillna(0).tolist() == [1, -1, -1, -1]
    assert compose_signals([left, right], {"kind": "weighted_score", "weights": [1, -2]}).fillna(0).tolist() == [-1, 1, 1, -1]
