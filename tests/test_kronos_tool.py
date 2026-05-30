from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.cli.forge import build_parser
from aurora.data_contracts.timeseries_store import TimeSeriesStore
from aurora.research import kronos_tool as kt
from aurora.research.agent_loop.actions import AgentActionType
from aurora.research.agent_loop.executor import AgentActionExecutor
from aurora.research.agent_loop.goal import load_goal_spec
from aurora.research.agent_loop.state import new_agent_state


def _ohlcv(rows: int = 900) -> pd.DataFrame:
    idx = pd.date_range("2010-01-04", periods=rows, freq="B")
    drift = np.linspace(0.0, 80.0, rows)
    wave = 2.0 * np.sin(np.arange(rows) / 21.0)
    close = 100.0 + drift + wave
    open_ = close * 0.999
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": close,
            "volume": np.full(rows, 1_000_000.0),
        },
        index=idx,
    )


class _FakePredictor:
    def predict(
        self,
        *,
        df,
        x_timestamp,
        y_timestamp,
        pred_len,
        T,
        top_p,
        sample_count,
    ):
        close = float(df["close"].iloc[-1])
        return pd.DataFrame(
            {
                "open": [close * 1.001],
                "high": [close * 1.003],
                "low": [close * 0.999],
                "close": [close * 1.002],
            },
            index=pd.to_datetime(y_timestamp),
        )


class _DirectionalFakePredictor:
    def predict(
        self,
        *,
        df,
        x_timestamp,
        y_timestamp,
        pred_len,
        T,
        top_p,
        sample_count,
    ):
        close = float(df["close"].iloc[-1])
        scale = 1.001 if float(T) < 0.8 else 0.999
        return pd.DataFrame(
            {
                "open": [close],
                "high": [close * max(scale, 1.0)],
                "low": [close * min(scale, 1.0)],
                "close": [close * scale],
                "volume": [float(df.get("volume", pd.Series([0.0])).iloc[-1])],
            },
            index=pd.to_datetime(y_timestamp),
        )


def _crypto_5m(start: str = "2023-05-01", periods: int = 800) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="5min", tz="UTC")
    drift = np.linspace(0.0, 25.0, periods)
    wave = np.sin(np.arange(periods) / 11.0)
    close = 25_000.0 + drift + wave
    open_ = close * 0.9999
    high = np.maximum(open_, close) * 1.0008
    low = np.minimum(open_, close) * 0.9992
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(periods, 12.0),
        },
        index=idx,
    )


def _rising_crypto_5m(start: str = "2023-05-01", periods: int = 800) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="5min", tz="UTC")
    close = np.linspace(25_000.0, 26_000.0, periods)
    open_ = close * 0.9999
    high = close * 1.0005
    low = open_ * 0.9995
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(periods, 12.0),
        },
        index=idx,
    )


def test_kronos_install_writes_manifest(tmp_path):
    manifest = kt.run_kronos_install(
        kt.KronosInstallConfig(
            model="Kronos-mini",
            tools_root=str(tmp_path),
            clone_repo=False,
        )
    )

    assert manifest["model"] == "Kronos-mini"
    assert (tmp_path / "kronos_tool.json").exists()


def test_kronos_adapter_rejects_missing_ohlc():
    frame = pd.DataFrame({"open": [1.0], "high": [1.0], "close": [1.0]})

    with pytest.raises(ValueError, match="missing"):
        kt.validate_kronos_source_frame(frame)


def test_kronos_adapter_rejects_external_features():
    frame = _ohlcv()
    frame["vix_level"] = 20.0

    with pytest.raises(ValueError, match="forbidden"):
        kt.validate_kronos_source_frame(frame)


def test_kronos_adapter_can_run_without_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("prices_daily", "SPY", _ohlcv().drop(columns=["volume"]), version="v1")

    frame = kt.load_kronos_frame("SPY", allow_volume=False)

    assert tuple(frame.columns) == ("open", "high", "low", "close")


def test_kronos_search_never_opens_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("prices_daily", "SPY", _ohlcv(), version="v1")

    report = kt.run_kronos_search(
        kt.KronosToolConfig(
            run_id="kronos-test",
            target_calmar=-999.0,
            validation_target_calmar=-999.0,
            run_root=str(tmp_path),
            train_only=True,
            no_costs=True,
            lookback=20,
            forecast_step=50,
            max_windows=5,
        ),
        predictor=_FakePredictor(),
    )

    assert report.locked_opened is False
    assert (tmp_path / "kronos-test" / "kronos" / "status.json").exists()


def test_kronos_signal_is_shifted_one_day():
    idx = pd.date_range("2020-01-01", periods=3, freq="B")
    frame = pd.DataFrame(
        {"open": [100.0, 110.0, 121.0], "high": [100.0, 110.0, 121.0], "low": [100.0, 110.0, 121.0], "close": [100.0, 110.0, 121.0]},
        index=idx,
    )
    forecasts = pd.DataFrame({"pred_close": [90.0]}, index=[idx[1]])

    positions = kt.positions_from_forecast(frame, forecasts)
    metrics = kt._metrics_for_positions(frame["close"].to_numpy(), positions, years=2 / 252)

    assert positions[0] == -1.0
    assert metrics.final_nav < 1.0


def test_kronos_train_selection_does_not_use_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("prices_daily", "SPY", _ohlcv(), version="v1")

    report = kt.run_kronos_search(
        kt.KronosToolConfig(
            run_id="selection-test",
            target_calmar=999.0,
            validation_target_calmar=1.0,
            run_root=str(tmp_path),
            lookback=20,
            forecast_step=50,
            max_windows=5,
            train_only=True,
            no_costs=True,
        ),
        predictor=_FakePredictor(),
    )
    status = json.loads(
        (tmp_path / "selection-test" / "kronos" / "status.json").read_text(encoding="utf-8")
    )

    assert report.validation_best is None
    assert status["locked_opened"] is False


def test_kronos_cli_writes_status_and_report(tmp_path, monkeypatch):
    from aurora.research import kronos_tool

    def fake_search(config):
        out = Path(config.run_root) / config.run_id / "kronos"
        out.mkdir(parents=True)
        report = kronos_tool.KronosReport(
            status="completed",
            locked_opened=False,
            objective_met=False,
            run_id=config.run_id,
            output_dir=str(out),
            model=config.model,
            symbol=config.symbol,
            used_columns=("open", "high", "low", "close"),
            volume_used=False,
            train_period=("2010-01-04", "2013-10-18"),
            validation_period=("2013-10-21", "2020-01-28"),
            locked_period=("2020-01-29", "closed"),
            forecasts_generated=0,
            best=None,
            top=tuple(),
            validation_best=None,
        )
        (out / "status.json").write_text(json.dumps(report.to_dict()), encoding="utf-8")
        return report

    monkeypatch.setattr(kronos_tool, "run_kronos_search", fake_search)
    parser = build_parser()
    args = parser.parse_args(
        [
            "research",
            "kronos",
            "search",
            "--run-id",
            "cli-test",
            "--run-root",
            str(tmp_path),
            "--train-only",
            "--no-costs",
            "--no-locked",
        ]
    )

    rc = args.func(args)

    assert rc == 1
    assert (tmp_path / "cli-test" / "kronos" / "status.json").exists()


def test_kronos_missing_dependency_error_is_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)

    with pytest.raises(kt.KronosDependencyError, match="Kronos is not installed"):
        kt.KronosAdapter().predictor()


def test_agent_loop_can_dispatch_kronos_search(tmp_path, monkeypatch):
    goal_path = tmp_path / "goal.yaml"
    goal_path.write_text(
        """
goal_id: kronos_goal
instrument: SPY
target_metric: calmar
target_value: 1.0
constraints:
  only_long_or_short: true
  always_fully_invested: true
  leverage_allowed: false
  cash_allowed: false
  traded_assets: [SPY]
  external_signals_allowed: true
protocol:
  optimise_on: train
  validation_role: exam_only
  locked_role: final_only
  open_locked: false
  robustness_required: true
  trial_logging_required: true
loop:
  stop_when_objective_met: true
  continue_on_failure: true
  pause_only_when_all_routes_blocked: false
""".strip(),
        encoding="utf-8",
    )
    goal = load_goal_spec(goal_path)
    state = new_agent_state(tmp_path / "run", goal_id=goal.goal_id, run_id="agent-kronos")

    @dataclass(frozen=True)
    class _Report:
        objective_met: bool = True

        def to_dict(self):
            return {
                "locked_opened": False,
                "objective_met": True,
                "best": {"metrics": {"calmar": 1.2}},
            }

    from aurora.research import kronos_tool

    monkeypatch.setattr(kronos_tool, "run_kronos_search", lambda _config: _Report())

    result = AgentActionExecutor().execute(
        action={"action": AgentActionType.RUN_KRONOS_SEARCH.value},
        goal=goal,
        state=state,
    )

    assert result["objective_met"] is True
    assert state.objective_met is True


def test_crypto_5m_ingestion_keeps_existing_version(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    existing = _crypto_5m(periods=12)
    store.put("crypto_5m", "BTCUSDT", existing, version="existing-v1")

    def fake_fetcher(symbol, year, month, interval):
        return _crypto_5m("2023-05-01", periods=12), True

    report = kt.ingest_binance_crypto_5m(
        kt.Crypto5mIngestionConfig(
            symbol="BTCUSDT",
            start="2023-05-01 00:00:00+00:00",
            end="2023-05-01 00:55:00+00:00",
            version="binance_5m_36m",
        ),
        monthly_fetcher=fake_fetcher,
    )

    assert report.version == "binance_5m_36m"
    assert "existing-v1" in store.list_versions("crypto_5m", "BTCUSDT")
    assert "binance_5m_36m" in store.list_versions("crypto_5m", "BTCUSDT")


def test_crypto_5m_ingestion_writes_new_version(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)

    def fake_fetcher(symbol, year, month, interval):
        return _crypto_5m("2023-05-01", periods=12), True

    report = kt.ingest_binance_crypto_5m(
        kt.Crypto5mIngestionConfig(
            start="2023-05-01 00:00:00+00:00",
            end="2023-05-01 00:55:00+00:00",
            version="binance_5m_36m",
        ),
        monthly_fetcher=fake_fetcher,
    )
    stored = TimeSeriesStore(tmp_path / "timeseries").read("crypto_5m", "BTCUSDT", version="binance_5m_36m")

    assert report.rows == 12
    assert len(stored) == 12
    assert list(stored.columns) == ["open", "high", "low", "close", "volume"]


def test_crypto_5m_ingestion_detects_missing_candles():
    frame = _crypto_5m(periods=12).drop(index=_crypto_5m(periods=12).index[4])

    status = kt.validate_crypto_5m_frame(
        frame,
        start="2023-05-01 00:00:00+00:00",
        end="2023-05-01 00:55:00+00:00",
    )

    assert status.missing_candles == 1


def test_crypto_5m_ingestion_rejects_duplicate_timestamps():
    frame = _crypto_5m(periods=12)
    duplicated = pd.concat([frame, frame.iloc[[0]]]).sort_index()

    status = kt.validate_crypto_5m_frame(
        duplicated,
        start="2023-05-01 00:00:00+00:00",
        end="2023-05-01 00:55:00+00:00",
    )

    assert status.duplicate_candles == 1


def test_kronos_direction_uses_36m_dataset():
    cfg = kt.Crypto5mIngestionConfig()

    assert cfg.start == "2023-05-01 00:00:00+00:00"
    assert cfg.end == "2026-04-30 23:55:00+00:00"
    assert cfg.version == "binance_5m_36m"


def test_kronos_direction_never_opens_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("crypto_5m", "BTCUSDT", _crypto_5m(periods=900), version="binance_5m_36m")

    report = kt.run_kronos_direction_backtest(
        kt.KronosDirectionBacktestConfig(
            run_id="direction-test",
            run_root=str(tmp_path),
            max_train_windows=8,
            max_validation_windows=4,
            lookbacks=(20,),
            temperatures=(0.5,),
            top_ps=(0.9,),
            sample_counts=(1,),
            confidence_bps=(0.0,),
        ),
        predictor=_DirectionalFakePredictor(),
    )

    assert report.locked_opened is False
    assert report.validation_used_for_selection is False


def test_kronos_direction_train_selects_without_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("crypto_5m", "BTCUSDT", _crypto_5m(periods=900), version="binance_5m_36m")

    report = kt.run_kronos_direction_backtest(
        kt.KronosDirectionBacktestConfig(
            run_id="selection-direction-test",
            run_root=str(tmp_path),
            max_train_windows=8,
            max_validation_windows=4,
            lookbacks=(20,),
            temperatures=(0.5, 1.0),
            top_ps=(0.9,),
            sample_counts=(1,),
            confidence_bps=(0.0,),
        ),
        predictor=_DirectionalFakePredictor(),
    )

    assert report.selected_on == "train"
    assert report.validation_used_for_selection is False
    assert report.best_train.config["temperature"] in (0.5, 1.0)


def test_kronos_direction_can_calibrate_inverted_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("crypto_5m", "BTCUSDT", _rising_crypto_5m(periods=900), version="binance_5m_36m")

    report = kt.run_kronos_direction_backtest(
        kt.KronosDirectionBacktestConfig(
            run_id="inverted-direction-test",
            run_root=str(tmp_path),
            max_train_windows=8,
            max_validation_windows=4,
            min_train_predictions=4,
            lookbacks=(20,),
            temperatures=(1.0,),
            top_ps=(0.9,),
            sample_counts=(1,),
            confidence_bps=(0.0,),
            direction_rules=("raw", "inverted"),
        ),
        predictor=_DirectionalFakePredictor(),
    )
    train_preds = pd.read_parquet(Path(report.output_dir) / "predictions_train.parquet")

    assert report.best_train.config["direction_rule"] == "inverted"
    assert report.best_train.metrics["accuracy"] == 1.0
    assert report.validation_result.metrics["accuracy"] == 1.0
    assert set(train_preds["direction_rule"]) == {"inverted"}


def test_kronos_direction_can_use_adaptive_past_only_rule():
    predictions = pd.DataFrame(
        {
            "predicted_direction": [1, 1, 1, -1, -1],
            "actual_direction": [-1, -1, -1, 1, 1],
            "predicted_label": ["up", "up", "up", "down", "down"],
            "actual_label": ["down", "down", "down", "up", "up"],
            "hit": [False, False, False, False, False],
            "predicted_return_bps": [1.0, 1.0, 1.0, -1.0, -1.0],
            "actual_return_bps": [-1.0, -1.0, -1.0, 1.0, 1.0],
            "abs_predicted_return_bps": [1.0, 1.0, 1.0, 1.0, 1.0],
        }
    )

    calibrated = kt._apply_direction_rule(predictions, "adaptive_2")

    assert list(calibrated["predicted_direction"]) == [1, 1, -1, 1, 1]
    assert list(calibrated["hit"]) == [False, False, True, True, True]


def test_kronos_direction_filters_by_side_and_hour():
    predictions = pd.DataFrame(
        {
            "target_time": pd.to_datetime([
                "2023-05-01 01:00:00+00:00",
                "2023-05-01 09:00:00+00:00",
                "2023-05-01 10:00:00+00:00",
            ]),
            "predicted_direction": [1, -1, -1],
            "actual_direction": [1, -1, 1],
            "predicted_label": ["up", "down", "down"],
            "actual_label": ["up", "down", "up"],
            "hit": [True, True, False],
            "predicted_return_bps": [1.0, -2.0, -5.0],
            "actual_return_bps": [1.0, -1.0, 1.0],
            "abs_predicted_return_bps": [1.0, 2.0, 5.0],
        }
    )

    filtered = kt._apply_direction_candidate_filters(
        predictions,
        confidence_bps=1.5,
        max_confidence_bps=3.0,
        prediction_side="down",
        hour_window="utc_8_12",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["target_time"].hour == 9


def test_kronos_direction_signal_uses_only_past_candles(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("crypto_5m", "BTCUSDT", _crypto_5m(periods=900), version="binance_5m_36m")

    report = kt.run_kronos_direction_backtest(
        kt.KronosDirectionBacktestConfig(
            run_id="past-only-test",
            run_root=str(tmp_path),
            max_train_windows=3,
            max_validation_windows=2,
            lookbacks=(20,),
            temperatures=(0.5,),
            top_ps=(0.9,),
            sample_counts=(1,),
            confidence_bps=(0.0,),
        ),
        predictor=_DirectionalFakePredictor(),
    )
    train_preds = pd.read_parquet(Path(report.output_dir) / "predictions_train.parquet")

    assert (pd.to_datetime(train_preds["decision_time"]) < pd.to_datetime(train_preds["target_time"])).all()
    assert (pd.to_datetime(train_preds["last_input_time"]) == pd.to_datetime(train_preds["decision_time"])).all()


def test_kronos_direction_prediction_target_is_next_5m_bar(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("crypto_5m", "BTCUSDT", _crypto_5m(periods=900), version="binance_5m_36m")

    report = kt.run_kronos_direction_backtest(
        kt.KronosDirectionBacktestConfig(
            run_id="next-bar-test",
            run_root=str(tmp_path),
            max_train_windows=3,
            max_validation_windows=2,
            lookbacks=(20,),
            temperatures=(0.5,),
            top_ps=(0.9,),
            sample_counts=(1,),
            confidence_bps=(0.0,),
        ),
        predictor=_DirectionalFakePredictor(),
    )
    train_preds = pd.read_parquet(Path(report.output_dir) / "predictions_train.parquet")
    delta = pd.to_datetime(train_preds["target_time"]) - pd.to_datetime(train_preds["decision_time"])

    assert set(delta.dt.total_seconds()) == {300.0}


def test_kronos_direction_uses_crypto_5m_annualisation():
    metrics = kt.direction_strategy_metrics(
        close=np.array([100.0, 101.0, 102.0, 103.0]),
        positions=np.array([1.0, 1.0, 1.0, 1.0]),
        bars_per_year=105_120,
    )

    assert metrics["bars_per_year"] == 105_120


def test_kronos_direction_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "base_data_dir", lambda: tmp_path)
    store = TimeSeriesStore(tmp_path / "timeseries")
    store.put("crypto_5m", "BTCUSDT", _crypto_5m(periods=900), version="binance_5m_36m")

    report = kt.run_kronos_direction_backtest(
        kt.KronosDirectionBacktestConfig(
            run_id="report-test",
            run_root=str(tmp_path),
            max_train_windows=5,
            max_validation_windows=3,
            lookbacks=(20,),
            temperatures=(0.5,),
            top_ps=(0.9,),
            sample_counts=(1,),
            confidence_bps=(0.0,),
        ),
        predictor=_DirectionalFakePredictor(),
    )

    out = Path(report.output_dir)
    assert (out / "status.json").exists()
    assert (out / "progress.jsonl").exists()
    assert (out / "best_config.json").exists()
    assert (out / "backtest_report.md").exists()
