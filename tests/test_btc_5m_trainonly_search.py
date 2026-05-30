from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.data_contracts.timeseries_store import TimeSeriesStore
from aurora.research.btc_5m_trainonly_search import (
    BTC5mSearchConfig,
    _profit_factor,
    choose_train_size,
    evaluate_spec,
    positions_from_scores,
    run_stage,
    strategy_metrics,
)


def _btc_5m_frame(rows: int = 3_800) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=rows, freq="5min", tz="UTC")
    trend = np.linspace(0.0, 400.0, rows)
    wave = np.sin(np.arange(rows) / 17.0) * 80.0
    close = 20_000.0 + trend + wave
    open_ = close + np.sin(np.arange(rows) / 5.0) * 5.0
    high = np.maximum(open_, close) + 20.0
    low = np.minimum(open_, close) - 20.0
    volume = 100.0 + np.abs(np.sin(np.arange(rows) / 11.0)) * 10.0
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=index,
    )


def _write_store(tmp_path: Path) -> None:
    store = TimeSeriesStore(tmp_path / "timeseries")
    frame = _btc_5m_frame()
    store.put("crypto_5m", "BTCUSDT", frame, version="binance_5m_36m", replace=True)
    external = pd.DataFrame(index=frame.index)
    external["funding_rate"] = np.sin(np.arange(len(frame)) / 13.0) * 0.0001
    external["open_interest"] = 1_000.0 + np.arange(len(frame), dtype=float)
    store.put(
        "crypto_5m_external",
        "BTCUSDT",
        external,
        version="binance_5m_36m_phase12_v2",
        replace=True,
    )


def _small_config() -> BTC5mSearchConfig:
    return BTC5mSearchConfig(
        train_start="2023-01-01",
        train_end="2023-01-07 23:55:00+00:00",
        validation_start="2023-01-08",
        validation_end="2023-01-11 23:55:00+00:00",
        locked_start="2023-01-12",
        min_train_non_null=20,
        max_feature_columns=40,
        top_rows_per_stage=10,
        min_train_trades_per_month=0.0,
    )


def test_profit_factor_handles_normal_no_loss_and_flat_cases() -> None:
    assert _profit_factor(np.array([0.10, -0.05, 0.05])) == pytest.approx(3.0)
    assert _profit_factor(np.array([0.01, 0.02])) == float("inf")
    assert _profit_factor(np.array([0.0, 0.0])) == 0.0


def test_strategy_metrics_reports_trades_per_month_and_profit_factor() -> None:
    index = pd.date_range("2023-01-01", periods=12, freq="5min", tz="UTC")
    returns = np.array([0.01, -0.005, 0.002, -0.001, 0.003, -0.002, 0.001, -0.001, 0.002, -0.001, 0.001, -0.001])
    positions = np.array([0, 1, 1, -1, -1, 0, 1, 1, 0, -1, -1, 0], dtype=float)

    metrics = strategy_metrics(returns, positions, index, size=1.0)

    assert metrics["profit_factor"] > 0.0
    assert metrics["trades"] == 7.0
    assert metrics["trades_per_month"] > 0.0


def test_choose_size_uses_train_only_not_validation() -> None:
    index = pd.date_range("2023-01-01", periods=20, freq="5min", tz="UTC")
    train_returns = np.array([0.002, -0.001, 0.003, -0.001, 0.002] * 4)
    positions = np.ones(len(train_returns))
    config = _small_config()

    size_a, metrics_a = choose_train_size(train_returns, positions, index, config)
    size_b, metrics_b = choose_train_size(train_returns, positions, index, config)

    assert size_a == size_b
    assert metrics_a["final_nav"] == pytest.approx(metrics_b["final_nav"])
    assert size_a <= 5.0


def test_evaluate_spec_keeps_validation_report_only() -> None:
    index = pd.date_range("2023-01-01", periods=20, freq="5min", tz="UTC")
    train_x = pd.DataFrame({"f": np.linspace(-2.0, 2.0, 20)}, index=index)
    valid_x = pd.DataFrame({"f": np.linspace(2.0, -2.0, 20)}, index=index)
    spec = {
        "method": "beam",
        "route": "linear_feature_rule",
        "features": ("f",),
        "weights": (1.0,),
        "threshold": 0.0,
    }
    dataset_a = {
        "train_x": train_x,
        "valid_x": valid_x,
        "train_returns": np.linspace(-0.001, 0.002, 20),
        "valid_returns": np.linspace(0.002, -0.001, 20),
        "train_index": index,
        "valid_index": index,
        "feature_names": ("f",),
    }
    dataset_b = dict(dataset_a)
    dataset_b["valid_returns"] = -dataset_a["valid_returns"]

    row_a = evaluate_spec(dataset_a, _small_config(), spec)
    row_b = evaluate_spec(dataset_b, _small_config(), spec)

    assert row_a["position_size"] == row_b["position_size"]
    assert row_a["train_score"] == pytest.approx(row_b["train_score"])
    assert row_a["validation_used_for_selection"] is False
    assert row_a["locked_opened"] is False


def test_run_stage_uses_all_features_and_keeps_locked_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    _write_store(tmp_path)

    rows, meta, audit = run_stage(
        _small_config(),
        method="beam",
        stage=0,
        total_stages=2,
        time_budget_minutes=0.0,
    )

    assert rows
    assert meta["locked_opened"] is False
    assert meta["validation_used_for_selection"] is False
    assert audit["feature_columns_used"] > 0
    assert "funding_rate" in audit["feature_columns_used_names"] or audit["feature_columns_raw"] > audit["feature_columns_used"]


def test_positions_from_scores_can_hold_cash_long_and_short() -> None:
    positions = positions_from_scores(np.array([-2.0, -0.1, 0.0, 0.1, 2.0]), threshold=0.5)

    assert positions.tolist() == [-1.0, 0.0, 0.0, 0.0, 1.0]


def test_btc_trainonly_workflow_shape() -> None:
    workflow = Path(".github/workflows/btc-5m-all-features-5methods-trainonly-1h-180jobs.yml").read_text(encoding="utf-8")

    assert "method: [dehb_real, genetic, beam, bandit, github_ml]" in workflow
    assert "max-parallel: ${{ fromJSON(inputs.max_parallel) }}" in workflow
    assert 'test "${{ inputs.max_parallel }}" -le 180' in workflow
    assert "--total-stages 36" in workflow
    assert "--time-budget-minutes \"${{ inputs.minutes_per_method_stage }}\"" in workflow
    assert "wave" not in workflow.lower()
    assert "btc_5m_all_features_5methods_trainonly_1h_180jobs_validation_report.csv" in workflow
