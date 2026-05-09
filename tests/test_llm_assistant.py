"""Tests for quantforge.research.llm_assistant."""
from __future__ import annotations

import ast
import os
from typing import Any

import pytest

from aurora.research.llm_assistant import (
    ANTHROPIC_AVAILABLE,
    LLMConfig,
    LLMResearchAssistant,
)


# ---- Mock Anthropic client -------------------------------------------------


class _Block:
    def __init__(self, text: str):
        self.text = text


class _Message:
    def __init__(self, text: str):
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.calls: list[dict] = []

    def create(self, **kwargs: Any) -> _Message:
        self.calls.append(kwargs)
        text = self._response_text
        if callable(text):
            text = text(**kwargs)
        return _Message(text)


class MockAnthropicClient:
    def __init__(self, response_text: str | Any = ""):
        self.messages = _Messages(response_text)


# ---- Tests -----------------------------------------------------------------


def test_init_with_mock_client():
    """A mock client lets us instantiate without ANTHROPIC_API_KEY."""
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        cfg = LLMConfig()
        a = LLMResearchAssistant(cfg, client=MockAnthropicClient("ok"))
        assert a.config.model == "claude-sonnet-4-5"
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_init_real_no_api_key(monkeypatch):
    """Without env var and without mock, a clear error is raised."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = LLMConfig()
    if not ANTHROPIC_AVAILABLE:
        with pytest.raises(ImportError):
            LLMResearchAssistant(cfg)
    else:
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            LLMResearchAssistant(cfg)


def test_read_research_log(tmp_path):
    p = tmp_path / "log.md"
    p.write_text("Hypothesis: momentum decays after 252d.\n", encoding="utf-8")
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient("x"))
    assert a.read_research_log(str(p)) == "Hypothesis: momentum decays after 252d.\n"


def test_propose_ideas_parses_json():
    payload = """[
        {"name": "MR1", "hypothesis": "h", "signal_logic": "s",
         "params": {"n": 20}, "rationale": "r"},
        {"name": "MR2", "hypothesis": "h2", "signal_logic": "s2",
         "params": {"k": 5}, "rationale": "r2"}
    ]"""
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(payload))
    ideas = a.propose_ideas("context", n=2)
    assert isinstance(ideas, list)
    assert len(ideas) == 2
    assert ideas[0]["name"] == "MR1"
    assert ideas[1]["params"] == {"k": 5}


def test_propose_ideas_invalid_json():
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient("not json {"))
    with pytest.raises(ValueError, match="valid JSON"):
        a.propose_ideas("context", n=2)


VALID_STRATEGY_CODE = '''from __future__ import annotations
import numpy as np
import pandas as pd
from aurora.strategies.base import Strategy, StrategySpec


class DemoStrat(Strategy):
    def __init__(self, period: int = 20):
        self.period = int(period)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="DemoStrat",
            params={"period": 20},
            param_ranges={"period": (5, 60)},
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        return np.zeros(len(p))
'''


def test_draft_strategy_returns_str():
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(VALID_STRATEGY_CODE))
    code = a.draft_strategy({"name": "DemoStrat", "hypothesis": "h"})
    assert isinstance(code, str)
    assert "class DemoStrat" in code


def test_draft_strategy_valid_python():
    fenced = "```python\n" + VALID_STRATEGY_CODE + "\n```"
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(fenced))
    code = a.draft_strategy({"name": "DemoStrat"})
    ast.parse(code)


def test_draft_strategy_invalid_python_raises():
    bogus = "class Broken(:\n    pass"
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(bogus))
    with pytest.raises(ValueError, match="not valid Python"):
        a.draft_strategy({"name": "Broken"})


def test_critique_strategy():
    a = LLMResearchAssistant(
        LLMConfig(),
        client=MockAnthropicClient("Critique: high turnover; suggest cooldown."),
    )
    out = a.critique_strategy(VALID_STRATEGY_CODE, {"sharpe": 0.4, "max_dd": -0.3})
    assert isinstance(out, str)
    assert "Critique" in out


def test_summarize_research_log(tmp_path):
    p = tmp_path / "log.md"
    p.write_text("ten ideas were tested. five worked. five failed.", encoding="utf-8")
    long_response = " ".join(["word"] * 500)
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(long_response))
    summary = a.summarize_research_log(str(p), max_words=50)
    assert isinstance(summary, str)
    assert len(summary.split()) <= 50


def test_draft_strategy_rejects_disallowed_imports():
    """Imports outside the allowlist must be rejected at AST-walk time."""
    bad = '''import os
import numpy as np

class S:
    pass
'''
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(bad))
    with pytest.raises(ValueError, match="not allowed"):
        a.draft_strategy({"name": "S"})

    bad_from = '''from subprocess import run
import numpy as np

class S:
    pass
'''
    a2 = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(bad_from))
    with pytest.raises(ValueError, match="not allowed"):
        a2.draft_strategy({"name": "S"})


def test_draft_strategy_rejects_exec_eval():
    """Calls to ``exec``/``eval``/``__import__`` must be rejected."""
    for forbidden in ("exec(\"print(1)\")", "eval(\"1+1\")",
                      "__import__('os')"):
        snippet = f"import numpy as np\nclass S:\n    def f(self):\n        {forbidden}\n"
        a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(snippet))
        with pytest.raises(ValueError, match="forbidden"):
            a.draft_strategy({"name": "S"})


def test_draft_strategy_rejects_dunder_access():
    """Dunder attribute access (e.g. ``x.__class__``) must be rejected."""
    bad = '''import numpy as np

class S:
    def f(self, x):
        return x.__class__.__bases__[0].__subclasses__()
'''
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(bad))
    with pytest.raises(ValueError, match="dunder"):
        a.draft_strategy({"name": "S"})


def test_propose_ideas_error_does_not_leak_raw():
    """The raised ValueError on bad JSON must not echo the raw LLM text."""
    leak = "MUST_NOT_APPEAR not_json {"
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(leak))
    with pytest.raises(ValueError) as ei:
        a.propose_ideas("ctx", n=1)
    assert "MUST_NOT_APPEAR" not in str(ei.value)


def test_anthropic_optional():
    """Smoke test: real anthropic client construction (no API call)."""
    pytest.importorskip("anthropic")
    import anthropic as _a  # noqa: F401
    # Just verify the SDK exposes the Anthropic class we rely on.
    assert hasattr(_a, "Anthropic")


# ---- Round V regression tests ---------------------------------------------


@pytest.mark.parametrize("call_expr", [
    "pd.read_csv('x.csv')",
    "pd.read_json('x.json')",
    "pd.read_parquet('x.parquet')",
    "pd.read_excel('x.xlsx')",
    "pd.read_pickle('x.pkl')",
    "df.to_csv('x.csv')",
    "df.to_json('x.json')",
    "df.to_parquet('x.parquet')",
    "df.to_pickle('x.pkl')",
    "np.load('x.npy')",
    "np.save('x.npy', a)",
    "np.fromfile('x.bin')",
    "arr.tofile('x.bin')",
    "np.memmap('x.bin', dtype='f4', mode='r', shape=(10,))",
])
def test_draft_strategy_rejects_runtime_io_calls(call_expr: str) -> None:
    """Pandas/Numpy filesystem IO calls must be rejected at AST-walk time."""
    snippet = (
        "import numpy as np\n"
        "import pandas as pd\n"
        "class S:\n"
        "    def f(self, df, arr):\n"
        f"        return {call_expr}\n"
    )
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(snippet))
    with pytest.raises(ValueError, match="not allowed|runtime IO"):
        a.draft_strategy({"name": "S"})


def test_draft_strategy_rejects_bare_load_call() -> None:
    """``from numpy import load; load(...)`` must also be rejected."""
    snippet = (
        "from numpy import load\n"
        "import numpy as np\n"
        "class S:\n"
        "    def f(self):\n"
        "        return load('x.npy')\n"
    )
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(snippet))
    with pytest.raises(ValueError, match="not allowed|runtime IO"):
        a.draft_strategy({"name": "S"})


def test_propose_ideas_debug_log_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    """DEBUG log on JSON-decode failure must be ASCII-sanitised + truncated."""
    import logging as _logging
    # Smuggle non-ASCII control characters and a long suffix.
    leak = "\x00\x01‮malicious " + ("X" * 1000) + " not_json {"
    a = LLMResearchAssistant(LLMConfig(), client=MockAnthropicClient(leak))
    with caplog.at_level(_logging.DEBUG, logger="aurora.research.llm_assistant"):
        with pytest.raises(ValueError):
            a.propose_ideas("ctx", n=1)
    debug_lines = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert debug_lines, "expected a DEBUG log entry"
    blob = " ".join(debug_lines)
    # Only ASCII characters survive sanitisation, and truncation caps at 200.
    assert blob.isascii()
    # The right-half must contain only '?' substitutions for the U+202E char.
    assert "‮" not in blob
    # The trailing tail of the leak must NOT appear (truncation worked).
    assert ("X" * 500) not in blob
