"""Cross-validated development metrics must come only from purged test folds."""

from __future__ import annotations

import pandas as pd
import pytest

from aurora.research.stock_protocol.scientific_evaluation import stitch_fold_curves


def _curve(dates: list[str], equity: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "equity": equity,
            "cash": [0.0] * len(dates),
            "market_value": equity,
            "gross_exposure": [1.0] * len(dates),
            "turnover": [0.0] * len(dates),
            "costs": [0.0] * len(dates),
        }
    )


def test_fold_curves_are_chained_without_inventing_inter_fold_returns():
    first = _curve(["2008-01-02", "2008-01-03"], [100.0, 110.0])
    second = _curve(["2010-01-04", "2010-01-05"], [100.0, 90.0])
    stitched = stitch_fold_curves([first, second], initial_capital=100.0)
    assert stitched["date"].tolist() == pd.to_datetime(
        ["2008-01-02", "2008-01-03", "2010-01-04", "2010-01-05"]
    ).tolist()
    assert stitched["equity"].tolist() == pytest.approx([100.0, 110.0, 110.0, 99.0])
    assert stitched["date"].is_unique


def test_fold_stitch_rejects_overlap_and_locked_dates():
    first = _curve(["2020-12-30", "2020-12-31"], [100.0, 101.0])
    locked = _curve(["2021-01-04", "2021-01-05"], [100.0, 101.0])
    with pytest.raises(ValueError, match="locked"):
        stitch_fold_curves([first, locked])
    overlap = _curve(["2020-12-31", "2021-01-01"], [100.0, 101.0])
    with pytest.raises(ValueError, match="overlap|locked"):
        stitch_fold_curves([first, overlap])
