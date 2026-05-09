"""Tests for quantforge.dataeng.great_expectations."""
from __future__ import annotations

import pandas as pd
import pytest

from aurora.dataeng.great_expectations import (
    DataQualityValidator,
    Expectation,
    GEConfig,
)


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "id": [1, 2, 3, 4],
        "side": ["buy", "sell", "buy", "sell"],
        "qty": [10.0, 20.0, 30.0, 40.0],
        "ticker": ["AAPL", "MSFT", "GOOG", "TSLA"],
    })


def test_not_null_passes(df):
    v = DataQualityValidator(GEConfig(suite_name="t"))
    v.add(Expectation("not_null", "id"))
    res = v.validate(df)
    assert res.success
    assert res.n_passed == 1


def test_not_null_fails(df):
    df_with_null = df.copy()
    df_with_null.loc[0, "id"] = None
    v = DataQualityValidator()
    v.add(Expectation("not_null", "id"))
    res = v.validate(df_with_null)
    assert not res.success
    assert res.failures[0]["expectation"] == "not_null"


def test_unique_detects_duplicates(df):
    df_dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    v = DataQualityValidator()
    v.add(Expectation("unique", "id"))
    res = v.validate(df_dup)
    assert not res.success


def test_in_set(df):
    v = DataQualityValidator()
    v.add(Expectation("in_set", "side", {"values": ["buy", "sell"]}))
    res = v.validate(df)
    assert res.success


def test_between_and_regex(df):
    v = DataQualityValidator()
    v.add(Expectation("between", "qty", {"min": 0.0, "max": 100.0}))
    v.add(Expectation("regex", "ticker", {"pattern": r"^[A-Z]{2,5}$"}))
    res = v.validate(df)
    assert res.success
    assert res.n_passed == 2


def test_unknown_kind_rejected():
    v = DataQualityValidator()
    with pytest.raises(ValueError):
        v.add(Expectation("nonsense", "x"))
