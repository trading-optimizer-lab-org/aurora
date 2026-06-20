from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml
from pathlib import Path

from scripts.summarize_spy_train_yearly_calmar_survivors import (
    ARTIFACT_NAME,
    annual_beat_counts,
)


def test_annual_beat_counts_reports_strict_beats_equals_and_lags() -> None:
    index = pd.date_range("2019-01-04", periods=156, freq="W-FRI")
    mask = np.ones(len(index), dtype=bool)
    spy = np.full(len(index), 0.001)
    strategy = spy.copy()
    strategy[index.year == 2019] = 0.002
    strategy[index.year == 2021] = 0.0

    result = annual_beat_counts(index, strategy, spy, mask)

    assert result["years_total"] == 3
    assert result["years_beaten"] == 1
    assert result["years_equalled"] == 1
    assert result["years_lagged"] == 1
    assert result["beaten_years"] == "2019"
    assert result["equalled_years"] == "2020"
    assert result["lagged_years"] == "2021"
    assert result["min_annual_excess_vs_spy"] < 0
    assert result["max_annual_excess_vs_spy"] > 0


def test_train_yearly_calmar_beat_counts_workflow_is_manual_postprocess() -> None:
    path = Path(".github/workflows/spy-weekly-global-random-train-yearly-calmar-beat-counts.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Weekly Global Random Train Yearly Calmar Beat Counts"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]

    text = path.read_text(encoding="utf-8")
    assert "27809257841" in text
    assert "27873129720" in text
    assert ARTIFACT_NAME in text
    assert "summarize_spy_train_yearly_calmar_survivors.py" in text
