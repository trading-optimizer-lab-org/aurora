"""Tests for quantforge.research.notebook_templates."""
from __future__ import annotations
import json
import pytest

from quantforge.research.notebook_templates import (
    NotebookTemplateEngine,
    NotebookSpec,
)


def test_build_backtest_report():
    eng = NotebookTemplateEngine()
    nb = eng.build(NotebookSpec(template="backtest_report",
                                title="SPY Report",
                                params={"symbol": "SPY"}))
    assert nb["nbformat"] == 4
    assert nb["metadata"]["quantforge_template"] == "backtest_report"
    assert any("SPY" in "".join(c["source"])
               for c in nb["cells"] if c["cell_type"] == "markdown")


def test_build_strategy_comparison():
    eng = NotebookTemplateEngine()
    nb = eng.build(NotebookSpec(template="strategy_comparison",
                                title="Compare",
                                params={"strategies": ["s1", "s2", "s3"]}))
    assert nb["metadata"]["quantforge_template"] == "strategy_comparison"
    src = "".join("".join(c["source"]) for c in nb["cells"])
    assert "s1" in src and "s2" in src and "s3" in src


def test_build_factor_analysis():
    eng = NotebookTemplateEngine()
    nb = eng.build(NotebookSpec(template="factor_analysis", title="Factors"))
    assert nb["metadata"]["quantforge_template"] == "factor_analysis"


def test_invalid_template_rejected():
    eng = NotebookTemplateEngine()
    with pytest.raises(ValueError):
        eng.build(NotebookSpec(template="nope", title="x"))


def test_empty_title_rejected():
    eng = NotebookTemplateEngine()
    with pytest.raises(ValueError):
        eng.build(NotebookSpec(template="backtest_report", title=""))


def test_write_produces_valid_json(tmp_path):
    eng = NotebookTemplateEngine()
    out = eng.write(NotebookSpec(template="backtest_report",
                                 title="t1"),
                    tmp_path / "nb.ipynb")
    assert out.exists()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["nbformat"] == 4


def test_kernel_name_required():
    with pytest.raises(ValueError):
        NotebookTemplateEngine(kernel_name="")
