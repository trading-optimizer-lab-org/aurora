"""Cross-validated development metrics must come only from purged test folds."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import aurora.research.stock_protocol.scientific_evaluation as evaluation_module
from aurora.research.stock_protocol.campaign import EvaluationResult
from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel
from aurora.research.stock_protocol.scientific_evaluation import (
    evaluate_development_walk_forward_from_pack,
    stitch_fold_curves,
)


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


def test_pack_walk_forward_reads_only_bounded_fold_windows(
    tmp_path: Path,
    monkeypatch,
):
    dates = pd.bdate_range("1995-01-02", "2015-12-31")
    pd.DataFrame({"date": dates}).to_parquet(tmp_path / "trading_calendar.parquet", index=False)
    audit = PackAudit(
        "source", str(tmp_path), "1995-01-02", "2020-12-31",
        1_000_000, 4_828, 0, False, False, "full-dataset-hash",
    )
    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def bounded_loader(root, *, start_date, end_date):
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        windows.append((start, end))
        frame = pd.DataFrame(
            {
                "date": [start, end],
                "symbol": ["AAA", "AAA"],
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.0, 101.0],
                "adj_close": [100.0, 101.0],
                "volume": [1_000.0, 1_000.0],
                "dividends": [0.0, 0.0],
                "stock_splits": [0.0, 0.0],
            }
        )
        return ResearchPanel(frame, audit)

    def evaluated(panel, spec, *, start, end, initial_capital=100_000.0):
        start_date = pd.Timestamp(start)
        curve = _curve(
            [str(start_date.date()), str((start_date + pd.Timedelta(days=1)).date())],
            [initial_capital, initial_capital * 1.01],
        )
        return EvaluationResult(
            candidate_id="stock_test",
            spec=dict(spec),
            status="evaluated",
            metrics={"sharpe": 1.0},
            equity_curve=curve,
            trade_ledger=pd.DataFrame(
                {
                    "entry_date": [start_date],
                    "exit_date": [start_date + pd.Timedelta(days=1)],
                    "weight": [1.0],
                }
            ),
            position_ledger=pd.DataFrame({"date": [start_date], "weight": [1.0]}),
            yearly=pd.DataFrame({"year": [start_date.year], "return": [0.01]}),
            locked_opened=False,
            data_end=str(pd.Timestamp(end).date()),
        )

    monkeypatch.setattr(evaluation_module, "read_pack_range", bounded_loader)
    monkeypatch.setattr(evaluation_module, "evaluate_spec", evaluated)

    result = evaluate_development_walk_forward_from_pack(
        tmp_path,
        {"horizon_sessions": 63},
        start="1995-01-01",
        end="2015-12-31",
    )

    assert result.result.status == "evaluated"
    assert len(windows) == len(result.folds)
    assert windows
    assert all((end - start).days <= 1_100 for start, end in windows)
    assert all(end <= pd.Timestamp("2015-12-31") for _, end in windows)
