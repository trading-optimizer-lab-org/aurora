"""Tests for aurora.ml.llm_portfolio_manager."""
from __future__ import annotations

import json

import pytest

from aurora.ml.llm_portfolio_manager import (
    LLMPortfolioConfig,
    LLMPortfolioManager,
    MockAnthropicClient,
)


def _make_manager(reply: str, **cfg_kwargs) -> LLMPortfolioManager:
    client = MockAnthropicClient(reply_text=reply)
    cfg = LLMPortfolioConfig(**cfg_kwargs) if cfg_kwargs else LLMPortfolioConfig()
    return LLMPortfolioManager(client, cfg)


def test_decide_normalises_to_unity():
    mgr = _make_manager('{"SPY": 0.5, "TLT": 0.5}')
    weights = mgr.decide(news=["earnings beat"], macro={"cpi": 3.1})
    assert set(weights.keys()) == set(mgr.config.universe)
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert all(0.0 <= v <= 1.0 for v in weights.values())


def test_clips_to_max_weight():
    mgr = _make_manager(
        '{"SPY": 0.99, "TLT": 0.01}',
        universe=("SPY", "TLT", "GLD"),
        max_weight=0.4,
    )
    weights = mgr.decide(news=[], macro={})
    # SPY weight should be clipped to <= 0.4 then renormalised
    assert weights["SPY"] <= 0.4 + 1e-6


def test_falls_back_to_equal_weight_when_parse_fails():
    mgr = _make_manager(
        "this is not JSON at all",
        universe=("SPY", "TLT", "GLD", "USO"),
        max_weight=0.5,
    )
    weights = mgr.decide(news=[], macro={})
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    # All weights equal-ish
    vals = list(weights.values())
    assert max(vals) - min(vals) < 1e-6


def test_allow_shorts():
    mgr = _make_manager(
        '{"SPY": 0.5, "TLT": -0.5}',
        universe=("SPY", "TLT"),
        max_weight=0.6,
        allow_shorts=True,
    )
    weights = mgr.decide(news=[], macro={})
    assert weights["TLT"] < 0
    # |w|_1 <= 1
    assert sum(abs(v) for v in weights.values()) <= 1.0 + 1e-6


def test_reject_invalid_input():
    mgr = _make_manager('{"SPY": 1.0}')
    with pytest.raises(TypeError):
        mgr.decide(news="not a list", macro={})
    with pytest.raises(TypeError):
        mgr.decide(news=[], macro="not a dict")


def test_constructor_validates():
    with pytest.raises(ValueError):
        LLMPortfolioManager(client=None)
    with pytest.raises(ValueError):
        LLMPortfolioManager(MockAnthropicClient(), LLMPortfolioConfig(max_weight=0.0))
    with pytest.raises(ValueError):
        LLMPortfolioManager(MockAnthropicClient(), LLMPortfolioConfig(universe=()))


def test_call_log_records_request():
    client = MockAnthropicClient(reply_text='{"SPY": 1.0}')
    mgr = LLMPortfolioManager(client, LLMPortfolioConfig(universe=("SPY",)))
    mgr.decide(news=["fed cuts rates"], macro={"unemployment": 4.1})
    assert len(client.call_log) == 1
    assert "messages" in client.call_log[0]
    user_msg = client.call_log[0]["messages"][0]["content"]
    assert "fed cuts rates" in user_msg
    assert "unemployment" in user_msg


def test_extracts_json_from_surrounding_prose():
    mgr = _make_manager('Sure, here are the weights:\n{"SPY": 1.0}\nLet me know if...')
    weights = mgr.decide(news=[], macro={})
    assert weights["SPY"] > 0
