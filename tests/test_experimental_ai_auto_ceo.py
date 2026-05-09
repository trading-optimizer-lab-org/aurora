"""Tests for AIAutoCEO."""
from __future__ import annotations

import pytest

from aurora.experimental.ai_auto_ceo import AIAutoCEO, _mock_llm


def test_decide_returns_expected_keys():
    ceo = AIAutoCEO()
    res = ceo.decide(
        news=["fed pivots dovish"],
        positions={"AAPL": 0.1},
        pnl={"trend": 0.02, "meanrev": -0.01},
    )
    assert {"stance", "gross_exposure", "allocation", "promote", "demote"} <= res.keys()


def test_promote_demote_split_by_pnl_sign():
    ceo = AIAutoCEO()
    res = ceo.decide(
        news=[], positions={}, pnl={"a": 0.05, "b": -0.03, "c": 0.0}
    )
    assert "a" in res["promote"]
    assert "b" in res["demote"]
    assert "c" not in res["promote"] and "c" not in res["demote"]


def test_invalid_risk_budget_raises():
    with pytest.raises(ValueError):
        AIAutoCEO(risk_budget=0.0)
    with pytest.raises(ValueError):
        AIAutoCEO(risk_budget=1.5)


def test_custom_llm_is_honored():
    ceo = AIAutoCEO(llm=lambda p: "risk_on")
    res = ceo.decide(news=[], positions={}, pnl={"x": 0.1})
    assert res["stance"] == "risk_on"
    assert res["gross_exposure"] == pytest.approx(ceo.risk_budget)


def test_unknown_stance_falls_back_to_neutral():
    ceo = AIAutoCEO(llm=lambda p: "garbage")
    res = ceo.decide(news=[], positions={}, pnl={"x": 0.1})
    assert res["stance"] == "neutral"


def test_mock_llm_is_deterministic():
    a = _mock_llm("hello")
    b = _mock_llm("hello")
    assert a == b
