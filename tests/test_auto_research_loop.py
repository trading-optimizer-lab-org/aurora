"""Tests for quantforge.research.auto_research_loop."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.research.auto_research_loop import (
    AutoResearchLoop,
    IterationRecord,
    LoopReport,
    MockLLM,
)


def test_loop_runs_with_default_mock(synthetic_prices_daily):
    loop = AutoResearchLoop(n_iterations=3)
    rep = loop.run(synthetic_prices_daily)
    assert isinstance(rep, LoopReport)
    assert rep.n_iterations == 3
    assert len(rep.trail) == 3
    for r in rep.trail:
        assert isinstance(r, IterationRecord)


def test_loop_records_metrics(synthetic_prices_daily):
    loop = AutoResearchLoop(n_iterations=2)
    rep = loop.run(synthetic_prices_daily)
    for r in rep.trail:
        assert "sharpe" in r.metrics
        assert "calmar" in r.metrics


def test_best_by_returns_record(synthetic_prices_daily):
    loop = AutoResearchLoop(n_iterations=3)
    rep = loop.run(synthetic_prices_daily)
    best = rep.best_by("sharpe")
    assert best is not None


def test_invalid_n_iterations():
    with pytest.raises(ValueError):
        AutoResearchLoop(n_iterations=0)


def test_invalid_prices_type():
    loop = AutoResearchLoop(n_iterations=1)
    with pytest.raises(TypeError):
        loop.run(np.zeros(100))


def test_unknown_template_recorded_as_rejected(synthetic_prices_daily):
    bad = MockLLM(hypotheses=[
        {"name": "bogus", "template": "ghost_template", "params": {}},
    ])
    loop = AutoResearchLoop(llm=bad, n_iterations=1)
    rep = loop.run(synthetic_prices_daily)
    assert len(rep.trail) == 1
    assert rep.trail[0].metrics == {}
    assert "rejected" in rep.trail[0].critique


def test_custom_mock_llm_propose_called(synthetic_prices_daily):
    custom = MockLLM(hypotheses=[
        {"name": "long_only", "template": "all_long", "params": {}},
    ])
    loop = AutoResearchLoop(llm=custom, n_iterations=2)
    rep = loop.run(synthetic_prices_daily)
    assert len(rep.trail) == 2
    assert rep.trail[0].hypothesis["template"] == "all_long"


def test_critique_present_in_trail(synthetic_prices_daily):
    loop = AutoResearchLoop(n_iterations=1)
    rep = loop.run(synthetic_prices_daily)
    assert isinstance(rep.trail[0].critique, str)
    assert len(rep.trail[0].critique) > 0


def test_loop_report_best_when_empty():
    rep = LoopReport(n_iterations=0)
    assert rep.best_by("sharpe") is None


def test_propose_must_return_dict(synthetic_prices_daily):
    class _BadLLM:
        def propose(self, context):
            return "not a dict"

        def critique(self, h, r):
            return ""
    loop = AutoResearchLoop(llm=_BadLLM(), n_iterations=1)
    with pytest.raises(TypeError):
        loop.run(synthetic_prices_daily)
