from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest

from aurora.data_contracts.timeseries_store import TimeSeriesStore
from aurora.research import crypto_direction_ml as ml


def _crypto_5m_frame(rows: int = 900) -> pd.DataFrame:
    index = pd.date_range("2023-05-01", periods=rows, freq="5min", tz="UTC")
    base = 27_000.0 + np.cumsum(np.sin(np.arange(rows) / 9.0) * 4.0 + 0.5)
    open_ = base + np.sin(np.arange(rows) / 7.0)
    close = base + np.cos(np.arange(rows) / 11.0)
    high = np.maximum(open_, close) + 6.0
    low = np.minimum(open_, close) - 6.0
    volume = 100.0 + np.abs(np.sin(np.arange(rows) / 5.0)) * 20.0
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


def _write_series(tmp_path, frame: pd.DataFrame | None = None) -> None:
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put(
        "crypto_5m",
        "BTCUSDT",
        _crypto_5m_frame() if frame is None else frame,
        version="binance_5m_36m",
        replace=True,
    )


def test_crypto_direction_ml_uses_36m_dataset():
    config = ml.CryptoDirectionMLConfig(run_id="test")

    assert config.library == "crypto_5m"
    assert config.version == "binance_5m_36m"


def test_crypto_direction_ml_uses_only_ohlcv(tmp_path, monkeypatch):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    _write_series(tmp_path)

    frame = ml.load_crypto_direction_frame()

    assert tuple(frame.columns) == ml.CRYPTO_5M_COLUMNS


def test_crypto_direction_ml_rejects_external_features(tmp_path, monkeypatch):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    frame = _crypto_5m_frame()
    frame["vix"] = 12.0
    _write_series(tmp_path, frame)

    with pytest.raises(ValueError, match="unsupported columns"):
        ml.load_crypto_direction_frame()


def test_crypto_direction_ml_target_is_next_5m_bar():
    index = pd.date_range("2023-05-01", periods=4, freq="5min", tz="UTC")
    features = pd.DataFrame({"feature": [1.0, 2.0, 3.0, 4.0]}, index=index)
    close = pd.Series([100.0, 101.0, 99.0, 100.0], index=index)

    dataset = ml.build_direction_dataset(features, close)

    assert dataset["target_up"].tolist() == [1, 0, 1]


def test_crypto_direction_ml_no_future_leakage():
    frame = _crypto_5m_frame(700)
    changed = frame.copy()
    changed.iloc[400:, changed.columns.get_loc("close")] *= 3.0

    original_features = ml.build_crypto_direction_features(frame).iloc[:350]
    changed_features = ml.build_crypto_direction_features(changed).iloc[:350]

    pd.testing.assert_frame_equal(original_features, changed_features)


def test_crypto_direction_features_include_phase_1_to_11_sets():
    frame = _crypto_5m_frame(5_000)

    features = ml.build_crypto_direction_features(frame)

    expected = {
        "ret_288",
        "log_ret_1",
        "close_to_open",
        "close_position_in_bar",
        "momentum_2016",
        "sma_288",
        "ema_cross_48_288",
        "trend_slope_288",
        "realized_vol_2016",
        "parkinson_vol_288",
        "atr_288",
        "vol_ratio_48_2016",
        "downside_vol_288",
        "rolling_max_2016",
        "drawdown_2016",
        "breakout_high_288",
        "regime_trend_up",
        "volume_z_288",
        "dollar_volume_z_288",
        "amihud_288",
        "hl_spread_proxy",
        "rsi_48",
        "macd_12_26_9",
        "bollinger_width_20",
        "adx_14",
        "is_weekend",
        "asia_session",
        "session_overlap_eu_us",
        "ret_1h",
        "trend_1d",
        "vol_1d",
    }

    assert expected <= set(features.columns)
    assert not any(
        column.startswith(("funding", "open_interest", "orderbook", "liquidations"))
        for column in features.columns
    )


def test_crypto_direction_external_feature_backlog_is_explicit():
    assert "funding_rate" in ml.EXTERNAL_CRYPTO_FEATURE_BACKLOG
    assert "orderbook_imbalance" in ml.EXTERNAL_CRYPTO_FEATURE_BACKLOG
    assert "dxy_return" in ml.EXTERNAL_CRYPTO_FEATURE_BACKLOG


def test_crypto_phase12_external_features_use_available_store_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    store = TimeSeriesStore(tmp_path / "timeseries")
    index = pd.date_range("2023-05-01", periods=4, freq="D", tz="UTC")
    store.put(
        "crypto_daily",
        "BTCUSDT",
        pd.DataFrame({"close": [100.0, 110.0, 105.0, 120.0]}, index=index),
        version="daily",
    )
    store.put(
        "crypto_daily",
        "ETHUSDT",
        pd.DataFrame({"close": [10.0, 11.5, 11.0, 13.0]}, index=index),
        version="daily",
    )
    store.put(
        "fx_daily",
        "DXY",
        pd.DataFrame({"close": [100.0, 101.0, 102.0, 100.0]}, index=index),
        version="daily",
    )
    store.put(
        "prices_daily",
        "QQQ",
        pd.DataFrame({"close": [200.0, 202.0, 204.0, 208.0]}, index=index),
        version="daily",
    )
    store.put(
        "prices_daily",
        "GLD",
        pd.DataFrame({"close": [180.0, 181.0, 179.0, 182.0]}, index=index),
        version="daily",
    )
    store.put(
        "macro_daily",
        "DGS10",
        pd.DataFrame({"value": [4.0, 4.1, 4.2, 4.0]}, index=index),
        version="daily",
    )
    frame = _crypto_5m_frame(900)

    external = ml.build_crypto_phase12_external_features(frame, store=store)

    assert set(ml.EXTERNAL_CRYPTO_FEATURE_BACKLOG) <= set(external.columns)
    assert external["ethbtc_return"].notna().any()
    assert external["dxy_return"].notna().any()
    assert external["nasdaq_return"].notna().any()
    assert external["gold_return"].notna().any()
    assert external["us_10y_yield_change"].notna().any()
    assert external["funding_rate"].isna().all()
    assert external["orderbook_imbalance"].isna().all()


def test_crypto_all_features_include_all_12_groups_without_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    store = TimeSeriesStore(tmp_path / "timeseries")
    frame = _crypto_5m_frame(900)

    features = ml.build_crypto_all_features(frame, store=store)

    assert "ret_1" in features.columns
    assert "rsi_48" in features.columns
    assert "funding_rate" in features.columns
    assert "dxy_return" in features.columns
    assert set(ml.EXTERNAL_CRYPTO_FEATURE_BACKLOG) <= set(features.columns)
    assert not any(column.startswith("future_") for column in features.columns)


def test_crypto_phase12_prefers_downloaded_external_panel(tmp_path, monkeypatch):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    store = TimeSeriesStore(tmp_path / "timeseries")
    frame = _crypto_5m_frame(900)
    downloaded = pd.DataFrame(index=frame.index)
    downloaded["funding_rate"] = 0.001
    downloaded["open_interest"] = np.arange(len(frame), dtype=float)
    store.put(
        "crypto_5m_external",
        "BTCUSDT",
        downloaded,
        version="phase12",
        replace=True,
    )

    external = ml.build_crypto_phase12_external_features(
        frame,
        store=store,
        external_version="phase12",
    )

    assert external["funding_rate"].notna().all()
    assert external["funding_rate"].iloc[0] == pytest.approx(0.001)
    assert external["open_interest"].iloc[-1] == pytest.approx(float(len(frame) - 1))


def test_crypto_5m_targets_are_future_only_and_separate_from_features():
    index = pd.date_range("2023-05-01", periods=20, freq="5min", tz="UTC")
    close = pd.Series(np.linspace(100.0, 119.0, 20), index=index)
    high = close + 1.0
    low = close - 1.0
    frame = pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )

    targets = ml.build_crypto_5m_targets(frame)
    features = ml.build_crypto_direction_features(frame)

    assert "future_ret_12" in targets.columns
    assert "future_direction_12" in targets.columns
    assert "future_max_up_12" in targets.columns
    assert "future_max_down_12" in targets.columns
    assert "future_risk_adjusted_ret_12" in targets.columns
    assert not any(column.startswith("future_") for column in features.columns)
    assert targets.loc[index[0], "future_ret_1"] == pytest.approx(0.01)
    assert targets.loc[index[0], "future_direction_1"] == 1


def test_crypto_direction_ml_train_selects_without_validation_and_writes_outputs(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    _write_series(tmp_path)
    monkeypatch.setattr(ml, "_ensure_optional_models_available", lambda models: None)

    class FakeModel:
        def __init__(self, feature_count: int) -> None:
            self.feature_importances_ = np.arange(feature_count, dtype=float)

        def predict_proba(self, x_predict):
            values = np.asarray(x_predict)
            score = 1.0 / (1.0 + np.exp(-values[:, 0]))
            return np.column_stack([1.0 - score, score])

    def fake_fit(spec, x_train, y_train, *, workers):
        assert workers == 2
        return FakeModel(np.asarray(x_train).shape[1])

    monkeypatch.setattr(ml, "_fit_model", fake_fit)

    report = ml.run_crypto_direction_ml(
        ml.CryptoDirectionMLConfig(
            run_id="btc-test",
            models=("lightgbm",),
            workers=2,
            max_candidates=1,
            run_root=str(tmp_path / "runs"),
            no_locked=True,
        )
    )

    output_dir = tmp_path / "runs" / "btc-test" / "crypto_direction_ml"
    assert report.validation_used_for_selection is False
    assert report.locked_opened is False
    assert report.candidates_evaluated == 1
    assert (output_dir / "status.json").exists()
    assert (output_dir / "predictions_train.parquet").exists()
    assert (output_dir / "predictions_validation.parquet").exists()


def test_crypto_direction_ml_never_opens_locked_by_default():
    config = ml.CryptoDirectionMLConfig(run_id="test")

    assert config.no_locked is True


def test_crypto_direction_ml_reports_all_baselines():
    index = pd.date_range("2023-05-01", periods=5, freq="5min", tz="UTC")
    baselines = ml.direction_baselines(np.array([1, 0, 0, 1, 1]), index)

    assert set(baselines) == {
        "random_accuracy",
        "always_up_accuracy",
        "previous_direction_accuracy",
        "inverse_previous_direction_accuracy",
    }


def test_crypto_direction_ml_can_use_lightgbm_if_installed():
    pytest.importorskip("lightgbm")

    ml._ensure_optional_models_available(("lightgbm",))


def test_crypto_direction_ml_can_use_xgboost_if_installed():
    pytest.importorskip("xgboost")

    ml._ensure_optional_models_available(("xgboost",))


def test_crypto_direction_ml_can_use_logistic_model_if_sklearn_installed():
    pytest.importorskip("sklearn")

    ml._ensure_optional_models_available(("logistic",))


def test_crypto_direction_ml_clear_error_if_optional_model_missing(monkeypatch):
    real_import_module = importlib.import_module

    def fake_import_module(name: str):
        if name == "lightgbm":
            raise ImportError("missing")
        return real_import_module(name)

    monkeypatch.setattr(ml.importlib, "import_module", fake_import_module)

    with pytest.raises(ml.OptionalModelMissing, match="pip install lightgbm xgboost"):
        ml._ensure_optional_models_available(("lightgbm",))


def test_crypto_direction_ml_regime_masks_cover_every_row_once():
    frame = _crypto_5m_frame(900)
    features = ml.build_crypto_direction_features(frame)
    dataset = ml.build_direction_dataset(features, frame["close"])

    masks = ml.build_regime_masks(dataset, "hour_3")

    covered = sum(mask.astype(int) for mask in masks.values())
    assert set(masks) == {"utc_00_08", "utc_08_16", "utc_16_24"}
    assert covered.min() == 1
    assert covered.max() == 1


def test_crypto_direction_ml_regime_search_writes_outputs_and_keeps_locked_closed(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    _write_series(tmp_path, _crypto_5m_frame(1_600))
    monkeypatch.setattr(ml, "_ensure_optional_models_available", lambda models: None)

    class FakeModel:
        def predict_proba(self, x_predict):
            values = np.asarray(x_predict)
            score = 1.0 / (1.0 + np.exp(-values[:, 0]))
            return np.column_stack([1.0 - score, score])

    monkeypatch.setattr(ml, "_fit_model", lambda spec, x_train, y_train, workers: FakeModel())

    report = ml.run_crypto_direction_ml_regime_search(
        ml.CryptoDirectionMLRegimeConfig(
            run_id="btc-regime-test",
            models=("lightgbm",),
            workers=2,
            max_candidates=1,
            partitions=("hour_3",),
            feature_sets=("short_price",),
            min_bucket_rows=20,
            run_root=str(tmp_path / "runs"),
            no_locked=True,
        )
    )

    output_dir = tmp_path / "runs" / "btc-regime-test" / "crypto_direction_ml_regime"
    assert report.locked_opened is False
    assert report.validation_used_for_selection is False
    assert report.candidates_evaluated == 1
    assert (output_dir / "status.json").exists()
    assert (output_dir / "predictions_train.parquet").exists()
    assert (output_dir / "predictions_validation.parquet").exists()


def test_crypto_direction_signal_labels_use_future_horizon():
    index = pd.date_range("2023-05-01", periods=5, freq="5min", tz="UTC")
    features = pd.DataFrame({"feature": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=index)
    close = pd.Series([100.0, 101.0, 103.0, 102.0, 104.0], index=index)

    dataset = ml.build_signal_dataset(features, close, horizon=2)

    assert dataset["future_return"].round(6).tolist() == [0.03, 0.009901, 0.009709]
    assert dataset["target_up"].tolist() == [1, 1, 1]


def test_crypto_direction_signal_rules_select_subset_without_touching_validation():
    index = pd.date_range("2023-05-01", periods=6, freq="5min", tz="UTC")
    proba = np.array([0.90, 0.80, 0.45, 0.20, 0.10, 0.55])
    future_return = np.array([0.003, -0.001, 0.002, -0.004, 0.001, -0.002])

    metrics = ml.evaluate_signal_rule(
        proba,
        future_return,
        index,
        side="up",
        confidence_threshold=0.75,
        move_threshold_bps=5.0,
        hour_window="all",
    )

    assert metrics.signal_count == 2
    assert metrics.precision == 0.5


def test_crypto_direction_signal_search_writes_outputs_and_keeps_locked_closed(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    _write_series(tmp_path, _crypto_5m_frame(1_600))
    monkeypatch.setattr(ml, "_ensure_optional_models_available", lambda models: None)

    class FakeModel:
        def predict_proba(self, x_predict):
            values = np.asarray(x_predict)
            score = 1.0 / (1.0 + np.exp(-values[:, 0]))
            return np.column_stack([1.0 - score, score])

    monkeypatch.setattr(ml, "_fit_model", lambda spec, x_train, y_train, workers: FakeModel())

    report = ml.run_crypto_direction_signal_search(
        ml.CryptoDirectionSignalSearchConfig(
            run_id="btc-signal-test",
            models=("lightgbm",),
            workers=2,
            max_candidates=2,
            horizons=(1,),
            move_threshold_bps=(0.0,),
            confidence_thresholds=(0.50, 0.55),
            hour_windows=("all",),
            sides=("up", "down"),
            min_train_signals=20,
            min_validation_signals=5,
            run_root=str(tmp_path / "runs"),
            no_locked=True,
        )
    )

    output_dir = tmp_path / "runs" / "btc-signal-test" / "crypto_direction_signal_search"
    assert report.locked_opened is False
    assert report.validation_used_for_selection is False
    assert report.candidates_evaluated > 0
    assert (output_dir / "status.json").exists()
    assert (output_dir / "signals_train.parquet").exists()
    assert (output_dir / "signals_validation.parquet").exists()
