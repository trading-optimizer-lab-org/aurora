"""Notebook Template Engine.

Generate Jupyter ipynb files from a small set of canned templates:

    backtest_report      -- single strategy summary with metrics + equity plot
    strategy_comparison  -- side by side metrics for several strategies
    factor_analysis      -- factor exposure / attribution writeup

Notebooks are emitted as plain JSON in the v4 nbformat. The engine never
imports ``nbformat`` or ``jupyter`` -- the spec is small enough to build
by hand and keeps test-time dependencies trivial.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any


_VALID_TEMPLATES = {"backtest_report", "strategy_comparison", "factor_analysis"}


@dataclass
class NotebookSpec:
    template: str
    title: str
    params: dict[str, Any] = field(default_factory=dict)


def _md(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def _code(source: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


class NotebookTemplateEngine:
    """Build ipynb JSON for a small set of canned research notebooks."""

    def __init__(self, kernel_name: str = "python3"):
        if not kernel_name:
            raise ValueError("kernel_name must be non-empty")
        self.kernel_name = str(kernel_name)

    def build(self, spec: NotebookSpec) -> dict:
        if spec.template not in _VALID_TEMPLATES:
            raise ValueError(
                f"unknown template {spec.template!r}; "
                f"allowed: {sorted(_VALID_TEMPLATES)}"
            )
        if not spec.title:
            raise ValueError("title must be non-empty")
        if spec.template == "backtest_report":
            cells = self._backtest_report(spec)
        elif spec.template == "strategy_comparison":
            cells = self._strategy_comparison(spec)
        else:
            cells = self._factor_analysis(spec)
        return {
            "cells": cells,
            "metadata": {
                "kernelspec": {
                    "name": self.kernel_name,
                    "display_name": "Python 3",
                    "language": "python",
                },
                "language_info": {"name": "python"},
                "quantforge_template": spec.template,
                "quantforge_title": spec.title,
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }

    def write(self, spec: NotebookSpec, path: str | Path) -> Path:
        nb = self.build(spec)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(nb, indent=2), encoding="utf-8")
        return out

    # --- private builders -------------------------------------------------

    def _backtest_report(self, spec: NotebookSpec) -> list[dict]:
        sym = spec.params.get("symbol", "SPY")
        return [
            _md(f"# {spec.title}\n\nBacktest report for `{sym}`."),
            _md("## Setup"),
            _code("import pandas as pd, numpy as np\nfrom aurora.core.engine import run_backtest"),
            _md("## Metrics"),
            _code("# result = run_backtest(prices, signal_fn)\n# print(result.metrics)"),
            _md("## Equity Curve"),
            _code("# result.equity.plot()"),
        ]

    def _strategy_comparison(self, spec: NotebookSpec) -> list[dict]:
        names = spec.params.get("strategies", ["strategy_a", "strategy_b"])
        names_str = ", ".join(repr(n) for n in names)
        return [
            _md(f"# {spec.title}\n\nComparison of {names_str}."),
            _md("## Load Strategies"),
            _code(f"strategies = {names!r}"),
            _md("## Compare Metrics"),
            _code("# build a DataFrame of metrics by strategy"),
            _md("## Compare Equity"),
            _code("# overlay equity curves on one axis"),
        ]

    def _factor_analysis(self, spec: NotebookSpec) -> list[dict]:
        factors = spec.params.get("factors", ["MKT", "SMB", "HML"])
        return [
            _md(f"# {spec.title}\n\nFactor analysis."),
            _md("## Factors"),
            _code(f"factors = {factors!r}"),
            _md("## Exposures"),
            _code("# regress strategy returns on factor returns"),
            _md("## Attribution"),
            _code("# decompose returns into factor contributions"),
        ]
