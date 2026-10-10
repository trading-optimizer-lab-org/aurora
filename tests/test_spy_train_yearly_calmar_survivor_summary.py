from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.summarize_spy_train_yearly_calmar_survivors import (
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


