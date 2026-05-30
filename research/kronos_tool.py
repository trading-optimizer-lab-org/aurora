"""Optional Kronos integration for Aurora research.

Kronos is treated as an external tool. This module validates Aurora data,
loads Kronos lazily only when needed, and writes auditable train/validation
artifacts without opening locked data.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np
import pandas as pd

from aurora.core.runtime_paths import base_data_dir
from aurora.data_contracts.timeseries_store import TimeSeriesStore


KRONOS_REPO_URL = "https://github.com/shiyu-coder/Kronos"
ALLOWED_SOURCE_COLUMNS = {"open", "high", "low", "close", "adj_close", "volume"}
REQUIRED_SOURCE_COLUMNS = {"open", "high", "low", "close", "adj_close"}
OHLC_COLUMNS = ("open", "high", "low", "close")
CRYPTO_5M_COLUMNS = ("open", "high", "low", "close", "volume")
FORBIDDEN_FEATURE_NAMES = ("vix", "fred", "sector", "breadth", "ratio", "amount")
BARS_PER_YEAR_CRYPTO_5M = 365 * 24 * 12
MODEL_SPECS = {
    "Kronos-mini": {
        "model_id": "NeoQuasar/Kronos-mini",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-2k",
        "max_context": 2048,
    },
    "Kronos-small": {
        "model_id": "NeoQuasar/Kronos-small",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "max_context": 512,
    },
    "Kronos-base": {
        "model_id": "NeoQuasar/Kronos-base",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "max_context": 512,
    },
}


class KronosDependencyError(RuntimeError):
    """Raised when the optional external Kronos tool is not installed."""


class KronosPredictorProtocol(Protocol):
    def predict(
        self,
        *,
        df: pd.DataFrame,
        x_timestamp: pd.Series,
        y_timestamp: pd.Series,
        pred_len: int,
        T: float,
        top_p: float,
        sample_count: int,
    ) -> pd.DataFrame:
        ...


@dataclass(frozen=True)
class KronosInstallConfig:
    model: str = "Kronos-mini"
    repo_url: str = KRONOS_REPO_URL
    tools_root: str | None = None
    clone_repo: bool = False
    force: bool = False


@dataclass(frozen=True)
class KronosToolConfig:
    run_id: str
    symbol: str = "SPY"
    library: str = "prices_daily"
    model: str = "Kronos-mini"
    target_calmar: float = 1.0
    validation_target_calmar: float | None = None
    train_end: str = "2013-10-18"
    validation_start: str = "2013-10-21"
    validation_end: str = "2020-01-28"
    locked_start: str = "2020-01-29"
    run_root: str | None = None
    allow_volume: bool = False
    train_only: bool = True
    no_costs: bool = True
    lookback: int = 256
    forecast_step: int = 5
    max_windows: int = 400
    threshold_bps: tuple[float, ...] = (0.0, 5.0, 10.0, 25.0, 50.0)
    temperature: float = 1.0
    top_p: float = 0.9
    sample_count: int = 1
    device: str = "auto"
    workers: int = 1


@dataclass(frozen=True)
class Crypto5mIngestionConfig:
    symbol: str = "BTCUSDT"
    library: str = "crypto_5m"
    interval: str = "5m"
    start: str = "2023-05-01 00:00:00+00:00"
    end: str = "2026-04-30 23:55:00+00:00"
    version: str = "binance_5m_36m"
    run_id: str = "kronos-btc-5m-base-direction-36m"
    run_root: str | None = None
    replace: bool = False


@dataclass(frozen=True)
class Crypto5mDataStatus:
    symbol: str
    source: str
    interval: str
    version: str
    rows: int
    start: str
    end: str
    expected_rows: int
    missing_candles: int
    duplicate_candles: int
    columns: tuple[str, ...]
    checksum_available: bool
    locked_opened: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KronosDirectionBacktestConfig:
    run_id: str = "kronos-btc-5m-base-direction-36m"
    symbol: str = "BTCUSDT"
    library: str = "crypto_5m"
    version: str = "binance_5m_36m"
    model: str = "Kronos-base"
    run_root: str | None = None
    allow_volume: bool = True
    lookbacks: tuple[int, ...] = (128, 256, 512)
    temperatures: tuple[float, ...] = (0.3, 0.5, 0.7, 1.0)
    top_ps: tuple[float, ...] = (0.85, 0.90, 0.95)
    sample_counts: tuple[int, ...] = (1, 4, 8)
    confidence_bps: tuple[float, ...] = (0.0, 2.0, 5.0, 10.0)
    max_confidence_bps: tuple[float, ...] = (1_000_000.0,)
    prediction_sides: tuple[str, ...] = ("both",)
    hour_windows: tuple[str, ...] = ("all",)
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    max_train_windows: int = 0
    max_validation_windows: int = 0
    min_train_predictions: int = 30
    direction_rules: tuple[str, ...] = ("raw", "inverted", "adaptive_25", "adaptive_50")
    selection_mode: str = "stable"
    device: str = "auto"


@dataclass(frozen=True)
class KronosDirectionCandidate:
    candidate_id: str
    config: dict[str, Any]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "config": self.config,
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class KronosDirectionReport:
    status: str
    locked_opened: bool
    validation_used_for_selection: bool
    selected_on: str
    run_id: str
    output_dir: str
    symbol: str
    library: str
    version: str
    model: str
    train_period: tuple[str, str]
    validation_period: tuple[str, str]
    locked_period: tuple[str, str]
    train_rows: int
    validation_rows: int
    locked_rows: int
    best_train: KronosDirectionCandidate
    validation_result: KronosDirectionCandidate
    baseline_train: dict[str, Any]
    baseline_validation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "locked_opened": self.locked_opened,
            "validation_used_for_selection": self.validation_used_for_selection,
            "selected_on": self.selected_on,
            "run_id": self.run_id,
            "output_dir": self.output_dir,
            "symbol": self.symbol,
            "library": self.library,
            "version": self.version,
            "model": self.model,
            "train_period": self.train_period,
            "validation_period": self.validation_period,
            "locked_period": self.locked_period,
            "train_rows": self.train_rows,
            "validation_rows": self.validation_rows,
            "locked_rows": self.locked_rows,
            "best_train": self.best_train.to_dict(),
            "validation_result": self.validation_result.to_dict(),
            "baseline_train": self.baseline_train,
            "baseline_validation": self.baseline_validation,
        }


@dataclass(frozen=True)
class KronosMetrics:
    calmar: float
    cagr: float
    mdd: float
    trades: int
    trades_per_year: float
    long_fraction: float
    final_nav: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KronosCandidate:
    candidate_id: str
    threshold_bps: float
    metrics: KronosMetrics
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "threshold_bps": self.threshold_bps,
            "metrics": self.metrics.to_dict(),
            "rule": self.rule,
        }


@dataclass(frozen=True)
class KronosReport:
    status: str
    locked_opened: bool
    objective_met: bool
    run_id: str
    output_dir: str
    model: str
    symbol: str
    used_columns: tuple[str, ...]
    volume_used: bool
    train_period: tuple[str, str]
    validation_period: tuple[str, str]
    locked_period: tuple[str, str]
    forecasts_generated: int
    best: KronosCandidate | None
    top: tuple[KronosCandidate, ...]
    validation_best: KronosCandidate | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "locked_opened": self.locked_opened,
            "objective_met": self.objective_met,
            "run_id": self.run_id,
            "output_dir": self.output_dir,
            "model": self.model,
            "symbol": self.symbol,
            "used_columns": list(self.used_columns),
            "volume_used": self.volume_used,
            "train_period": self.train_period,
            "validation_period": self.validation_period,
            "locked_period": self.locked_period,
            "forecasts_generated": self.forecasts_generated,
            "best": None if self.best is None else self.best.to_dict(),
            "top": [candidate.to_dict() for candidate in self.top],
            "validation_best": (
                None if self.validation_best is None else self.validation_best.to_dict()
            ),
        }


def kronos_tools_dir() -> Path:
    path = base_data_dir() / "tools" / "kronos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def kronos_manifest_path(tools_root: str | None = None) -> Path:
    root = Path(tools_root) if tools_root else kronos_tools_dir()
    return root / "kronos_tool.json"


def run_kronos_install(config: KronosInstallConfig) -> dict[str, Any]:
    """Prepare the external Kronos tool folder and write a manifest."""

    spec = _model_spec(config.model)
    root = Path(config.tools_root) if config.tools_root else kronos_tools_dir()
    root.mkdir(parents=True, exist_ok=True)
    repo_dir = root / "repo"
    if config.clone_repo:
        if repo_dir.exists() and config.force:
            shutil.rmtree(repo_dir)
        if not repo_dir.exists():
            git = shutil.which("git")
            if git is None:
                raise KronosDependencyError(
                    "git is required to install Kronos. Install git or clone "
                    f"{config.repo_url} manually into {repo_dir}."
                )
            subprocess.run(
                [git, "clone", "--depth", "1", config.repo_url, str(repo_dir)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
    manifest = {
        "tool": "kronos",
        "repo_url": config.repo_url,
        "repo_dir": str(repo_dir),
        "model": config.model,
        "model_id": spec["model_id"],
        "tokenizer_id": spec["tokenizer_id"],
        "max_context": spec["max_context"],
        "installed_at_utc": _now(),
        "clone_repo": config.clone_repo,
    }
    _write_json(kronos_manifest_path(str(root)), manifest)
    return manifest


def validate_kronos_source_frame(source: pd.DataFrame, *, allow_volume: bool = False) -> tuple[str, ...]:
    columns = {str(column) for column in source.columns}
    unknown = columns - ALLOWED_SOURCE_COLUMNS
    if unknown:
        raise ValueError(f"kronos source has forbidden columns: {sorted(unknown)}")
    missing = REQUIRED_SOURCE_COLUMNS - columns
    if missing:
        raise ValueError(f"kronos source missing columns: {sorted(missing)}")
    lowered = " ".join(columns).lower()
    for forbidden in FORBIDDEN_FEATURE_NAMES:
        if forbidden in lowered:
            raise ValueError(f"forbidden feature/data column for Kronos search: {forbidden}")
    consumed = list(OHLC_COLUMNS)
    if allow_volume and "volume" in columns:
        consumed.append("volume")
    return tuple(consumed)


def load_kronos_frame(
    symbol: str = "SPY",
    *,
    library: str = "prices_daily",
    allow_volume: bool = False,
    end: str | None = None,
) -> pd.DataFrame:
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    source = store.read(library=library, symbol=symbol, end=end)
    used = validate_kronos_source_frame(source, allow_volume=allow_volume)

    frame = source[["open", "high", "low", "close", "adj_close", *(
        ["volume"] if "volume" in used else []
    )]].copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "adj_close"])
    ratio = frame["adj_close"] / frame["close"]
    adjusted = pd.DataFrame(index=frame.index)
    for column in OHLC_COLUMNS:
        adjusted[column] = frame[column] * ratio
    if "volume" in used:
        adjusted["volume"] = frame["volume"].fillna(0.0)
    return adjusted.dropna()


def validate_crypto_5m_frame(
    frame: pd.DataFrame,
    *,
    start: str,
    end: str,
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    version: str = "binance_5m_36m",
    checksum_available: bool = False,
) -> Crypto5mDataStatus:
    columns = tuple(str(column) for column in frame.columns)
    if set(columns) != set(CRYPTO_5M_COLUMNS):
        raise ValueError(f"crypto 5m frame must contain exactly {CRYPTO_5M_COLUMNS}")
    out = frame.copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out = out.sort_index()
    for column in CRYPTO_5M_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if out[list(CRYPTO_5M_COLUMNS)].isna().any().any():
        raise ValueError("crypto 5m frame contains null OHLCV values")
    if (out[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise ValueError("crypto 5m frame contains non-positive prices")

    start_ts = pd.Timestamp(start).tz_convert("UTC") if pd.Timestamp(start).tzinfo else pd.Timestamp(start).tz_localize("UTC")
    end_ts = pd.Timestamp(end).tz_convert("UTC") if pd.Timestamp(end).tzinfo else pd.Timestamp(end).tz_localize("UTC")
    expected_index = pd.date_range(start_ts, end_ts, freq="5min", tz="UTC")
    unique_index = pd.DatetimeIndex(out.index[~out.index.duplicated(keep="first")])
    missing = expected_index.difference(unique_index)
    duplicates = int(out.index.duplicated(keep="first").sum())
    return Crypto5mDataStatus(
        symbol=symbol,
        source="Binance public data",
        interval=interval,
        version=version,
        rows=int(len(out)),
        start=str(out.index.min()) if len(out) else str(start_ts),
        end=str(out.index.max()) if len(out) else str(end_ts),
        expected_rows=int(len(expected_index)),
        missing_candles=int(len(missing)),
        duplicate_candles=duplicates,
        columns=columns,
        checksum_available=bool(checksum_available),
        locked_opened=False,
    )


MonthlyFetcher = Callable[[str, int, int, str], tuple[pd.DataFrame, bool]]


def ingest_binance_crypto_5m(
    config: Crypto5mIngestionConfig,
    *,
    monthly_fetcher: MonthlyFetcher | None = None,
) -> Crypto5mDataStatus:
    frames: list[pd.DataFrame] = []
    checksum_flags: list[bool] = []
    for year, month in _month_pairs(config.start, config.end):
        if monthly_fetcher is None:
            frame, checksum_available = _fetch_binance_month(
                config.symbol, year, month, config.interval
            )
        else:
            frame, checksum_available = monthly_fetcher(
                config.symbol, year, month, config.interval
            )
        frames.append(_normalise_crypto_5m_frame(frame))
        checksum_flags.append(bool(checksum_available))

    if not frames:
        raise ValueError("no crypto 5m frames fetched")
    combined = pd.concat(frames).sort_index()
    start_ts = _utc_timestamp(config.start)
    end_ts = _utc_timestamp(config.end)
    combined = combined.loc[(combined.index >= start_ts) & (combined.index <= end_ts)]
    combined = combined[list(CRYPTO_5M_COLUMNS)]
    status = validate_crypto_5m_frame(
        combined,
        start=config.start,
        end=config.end,
        symbol=config.symbol,
        interval=config.interval,
        version=config.version,
        checksum_available=all(checksum_flags) if checksum_flags else False,
    )
    if status.missing_candles or status.duplicate_candles:
        raise ValueError(
            "crypto 5m validation failed: "
            f"missing={status.missing_candles}, duplicates={status.duplicate_candles}"
        )

    store = TimeSeriesStore(base_data_dir() / "timeseries")
    store.put(
        config.library,
        config.symbol,
        combined,
        version=config.version,
        replace=config.replace,
        metadata={
            "source": "Binance public data",
            "interval": config.interval,
            "start": config.start,
            "end": config.end,
            "checksum_available": status.checksum_available,
            "locked_opened": False,
        },
    )
    output_dir = _direction_output_dir(config.run_id, config.run_root)
    _write_json(output_dir / "data_status.json", status.to_dict())
    return status


class KronosAdapter:
    """Lazy adapter around the external Kronos repository."""

    def __init__(self, *, model: str = "Kronos-mini", device: str = "auto") -> None:
        self.model = model
        self.device = device
        self._predictor: KronosPredictorProtocol | None = None

    def predictor(self) -> KronosPredictorProtocol:
        if self._predictor is None:
            self._predictor = self._load_predictor()
        return self._predictor

    def predict(self, **kwargs: Any) -> pd.DataFrame:
        return self.predictor().predict(**kwargs)

    def _load_predictor(self) -> KronosPredictorProtocol:
        manifest_path = kronos_manifest_path()
        if not manifest_path.exists():
            raise KronosDependencyError(
                "Kronos is not installed for Aurora. Run: "
                "python -m aurora.cli.forge research kronos install --model Kronos-mini"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        repo_dir = Path(manifest.get("repo_dir", ""))
        if not repo_dir.exists():
            raise KronosDependencyError(
                f"Kronos repo not found at {repo_dir}. Re-run `research kronos install`."
            )
        if str(repo_dir) not in sys.path:
            sys.path.insert(0, str(repo_dir))
        try:
            from model import Kronos, KronosPredictor, KronosTokenizer
            import torch
        except Exception as exc:
            raise KronosDependencyError(
                "Kronos dependencies are missing. Install optional dependencies "
                "with `pip install -e .[kronos]` and re-run `research kronos install`."
            ) from exc

        spec = _model_spec(self.model)
        device = self.device
        if device == "auto":
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        tokenizer = KronosTokenizer.from_pretrained(spec["tokenizer_id"])
        model = Kronos.from_pretrained(spec["model_id"])
        model.to(device)
        model.eval()
        return KronosPredictor(model, tokenizer, max_context=int(spec["max_context"]))


def run_kronos_forecast(
    config: KronosToolConfig,
    *,
    predictor: KronosPredictorProtocol | None = None,
) -> pd.DataFrame:
    frame = load_kronos_frame(
        config.symbol,
        library=config.library,
        allow_volume=config.allow_volume,
        end=config.validation_end,
    )
    active_predictor = predictor or (
        None if config.workers > 1 else KronosAdapter(model=config.model, device=config.device)
    )
    return generate_rolling_forecasts(frame, config, active_predictor)


def run_kronos_search(
    config: KronosToolConfig,
    *,
    predictor: KronosPredictorProtocol | None = None,
) -> KronosReport:
    if not config.no_costs:
        raise ValueError("Kronos search v1 only supports --no-costs")
    if not config.train_only:
        raise ValueError("Kronos search v1 requires --train-only")
    _model_spec(config.model)

    output_dir = _output_dir(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    progress_path = output_dir / "progress.jsonl"
    forecast_path = output_dir / "forecasts.parquet"
    signals_path = output_dir / "signals.parquet"
    candidates_path = output_dir / "candidates.json"
    best_md_path = output_dir / "best_candidates.md"
    stderr_path = output_dir / "stderr.log"
    for path in (status_path, progress_path, candidates_path, best_md_path, stderr_path):
        if path.exists():
            path.unlink()

    _write_json(status_path, {
        "status": "running",
        "locked_opened": False,
        "selection_phase": "train",
        "validation_used_for_selection": False,
        "run_id": config.run_id,
        "model": config.model,
        "symbol": config.symbol,
        "allow_volume": config.allow_volume,
        "started_at_utc": _now(),
    })
    stderr_path.write_text("", encoding="utf-8")

    started = time.perf_counter()
    try:
        frame = load_kronos_frame(
            config.symbol,
            library=config.library,
            allow_volume=config.allow_volume,
            end=config.validation_end,
        )
        used_columns = tuple(frame.columns)
        train = frame.loc[: config.train_end]
        validation = frame.loc[config.validation_start: config.validation_end]
        active_predictor = predictor or (
            None if config.workers > 1 else KronosAdapter(model=config.model, device=config.device)
        )
        train_forecasts = generate_rolling_forecasts(train, config, active_predictor)
        forecasts = train_forecasts.copy()
        candidates = _evaluate_thresholds(
            train,
            train_forecasts,
            tuple(float(x) for x in config.threshold_bps),
            prefix="train",
        )
        candidates = tuple(sorted(candidates, key=lambda item: item.metrics.calmar, reverse=True))
        best = candidates[0] if candidates else None
        validation_best = None
        validation_forecasts = pd.DataFrame()
        if best is not None and best.metrics.calmar >= config.target_calmar:
            validation_forecasts = generate_rolling_forecasts(validation, config, active_predictor)
            forecasts = pd.concat([forecasts, validation_forecasts]).sort_index()
            validation_candidates = _evaluate_thresholds(
                validation,
                validation_forecasts,
                (best.threshold_bps,),
                prefix="validation",
            )
            validation_best = validation_candidates[0] if validation_candidates else None

        objective_met = bool(best and best.metrics.calmar >= config.target_calmar)
        if config.validation_target_calmar is not None:
            objective_met = bool(
                objective_met
                and validation_best
                and validation_best.metrics.calmar >= config.validation_target_calmar
            )

        signals = _signals_frame(frame, forecasts, candidates)
        _write_parquet(forecast_path, forecasts)
        _write_parquet(signals_path, signals)
        report = KronosReport(
            status="objective_met" if objective_met else "completed",
            locked_opened=False,
            objective_met=objective_met,
            run_id=config.run_id,
            output_dir=str(output_dir),
            model=config.model,
            symbol=config.symbol,
            used_columns=used_columns,
            volume_used="volume" in used_columns,
            train_period=_period_tuple(train),
            validation_period=_period_tuple(validation),
            locked_period=(config.locked_start, "closed"),
            forecasts_generated=int(len(forecasts)),
            best=best,
            top=candidates[:10],
            validation_best=validation_best,
        )
        _write_json(candidates_path, report.to_dict())
        best_md_path.write_text(report_to_markdown(report), encoding="utf-8")
        _append_jsonl(progress_path, {
            "event": "completed",
            "elapsed_seconds": time.perf_counter() - started,
            "forecasts_generated": len(forecasts),
            "best": None if best is None else best.to_dict(),
            "validation_best": None if validation_best is None else validation_best.to_dict(),
            "objective_met": objective_met,
            "locked_opened": False,
            "updated_at_utc": _now(),
        })
        _write_json(status_path, report.to_dict() | {
            "elapsed_seconds": time.perf_counter() - started,
            "completed_at_utc": _now(),
        })
        return report
    except Exception as exc:
        stderr_path.write_text(traceback.format_exc(), encoding="utf-8")
        _write_json(status_path, {
            "status": "error",
            "locked_opened": False,
            "objective_met": False,
            "run_id": config.run_id,
            "error": str(exc),
            "updated_at_utc": _now(),
        })
        raise


def run_kronos_direction_backtest(
    config: KronosDirectionBacktestConfig,
    *,
    predictor: KronosPredictorProtocol | None = None,
) -> KronosDirectionReport:
    _model_spec(config.model)
    output_dir = _direction_output_dir(config.run_id, config.run_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    progress_path = output_dir / "progress.jsonl"
    best_config_path = output_dir / "best_config.json"
    candidates_path = output_dir / "candidates.json"
    report_path = output_dir / "backtest_report.md"
    stderr_path = output_dir / "stderr.log"
    train_pred_path = output_dir / "predictions_train.parquet"
    validation_pred_path = output_dir / "predictions_validation.parquet"
    raw_train_pred_path = output_dir / "raw_predictions_train.parquet"
    raw_validation_pred_path = output_dir / "raw_predictions_validation.parquet"
    for path in (
        status_path,
        progress_path,
        best_config_path,
        candidates_path,
        report_path,
        stderr_path,
        train_pred_path,
        validation_pred_path,
        raw_train_pred_path,
        raw_validation_pred_path,
    ):
        if path.exists():
            path.unlink()

    _write_json(status_path, {
        "status": "running",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "selected_on": "train",
        "run_id": config.run_id,
        "symbol": config.symbol,
        "library": config.library,
        "version": config.version,
        "model": config.model,
        "started_at_utc": _now(),
    })
    stderr_path.write_text("", encoding="utf-8")
    started = time.perf_counter()
    try:
        frame = load_crypto_5m_frame(
            config.symbol,
            library=config.library,
            version=config.version,
            allow_volume=config.allow_volume,
        )
        status = validate_crypto_5m_frame(
            frame,
            start=str(frame.index.min()),
            end=str(frame.index.max()),
            symbol=config.symbol,
            version=config.version,
            checksum_available=False,
        )
        _write_json(output_dir / "data_status.json", status.to_dict())
        train, validation, locked = _split_direction_periods(frame, config)
        active_predictor = predictor or KronosAdapter(model=config.model, device=config.device)
        candidates: list[KronosDirectionCandidate] = []
        raw_train_by_config: dict[str, pd.DataFrame] = {}

        for candidate_config in _direction_config_grid(config):
            raw_predictions = _generate_direction_predictions(
                train,
                active_predictor,
                candidate_config,
                max_windows=config.max_train_windows,
            )
            raw_train_by_config[_candidate_config_id(candidate_config)] = raw_predictions
            for confidence in config.confidence_bps:
                for max_confidence in config.max_confidence_bps:
                    if float(max_confidence) < float(confidence):
                        continue
                    for prediction_side in config.prediction_sides:
                        for hour_window in config.hour_windows:
                            for direction_rule in config.direction_rules:
                                evaluated = _evaluate_direction_candidate(
                                    raw_predictions,
                                    candidate_config,
                                    confidence_bps=float(confidence),
                                    max_confidence_bps=float(max_confidence),
                                    prediction_side=str(prediction_side),
                                    hour_window=str(hour_window),
                                    direction_rule=direction_rule,
                                    prefix="train",
                                )
                                candidates.append(evaluated)
            _append_jsonl(progress_path, {
                "event": "train_config_completed",
                "config": candidate_config,
                "raw_predictions": int(len(raw_predictions)),
                "elapsed_seconds": time.perf_counter() - started,
                "updated_at_utc": _now(),
            })

        if not candidates:
            raise ValueError("no Kronos direction candidates were evaluated")
        candidates = sorted(candidates, key=_direction_candidate_sort_key(config), reverse=True)
        best_train = candidates[0]
        best_raw_train = raw_train_by_config[_candidate_config_id(best_train.config)]
        raw_train_predictions = pd.concat(
            raw_train_by_config.values(), ignore_index=True
        ) if raw_train_by_config else pd.DataFrame()
        train_predictions = _apply_direction_candidate_filters(
            best_raw_train,
            confidence_bps=float(best_train.config["confidence_bps"]),
            max_confidence_bps=float(best_train.config["max_confidence_bps"]),
            prediction_side=str(best_train.config["prediction_side"]),
            hour_window=str(best_train.config["hour_window"]),
        )
        train_predictions = _apply_direction_rule(
            train_predictions, str(best_train.config["direction_rule"])
        )
        validation_raw = _generate_direction_predictions(
            validation,
            active_predictor,
            {k: v for k, v in best_train.config.items() if k != "confidence_bps"},
            max_windows=config.max_validation_windows,
        )
        validation_result = _evaluate_direction_candidate(
            validation_raw,
            {k: v for k, v in best_train.config.items() if k != "confidence_bps"},
            confidence_bps=float(best_train.config["confidence_bps"]),
            max_confidence_bps=float(best_train.config["max_confidence_bps"]),
            prediction_side=str(best_train.config["prediction_side"]),
            hour_window=str(best_train.config["hour_window"]),
            direction_rule=str(best_train.config["direction_rule"]),
            prefix="validation",
        )
        validation_predictions = _apply_direction_candidate_filters(
            validation_raw,
            confidence_bps=float(best_train.config["confidence_bps"]),
            max_confidence_bps=float(best_train.config["max_confidence_bps"]),
            prediction_side=str(best_train.config["prediction_side"]),
            hour_window=str(best_train.config["hour_window"]),
        )
        validation_predictions = _apply_direction_rule(
            validation_predictions, str(best_train.config["direction_rule"])
        )
        baseline_train = direction_baselines(train_predictions)
        baseline_validation = direction_baselines(validation_predictions)

        _write_parquet(raw_train_pred_path, raw_train_predictions)
        _write_parquet(raw_validation_pred_path, validation_raw)
        _write_parquet(train_pred_path, train_predictions)
        _write_parquet(validation_pred_path, validation_predictions)
        _write_json(best_config_path, best_train.to_dict())
        _write_json(candidates_path, {
            "top": [candidate.to_dict() for candidate in candidates[:25]],
            "validation": validation_result.to_dict(),
            "baseline_train": baseline_train,
            "baseline_validation": baseline_validation,
            "selection_rules": {
                "min_train_predictions": int(config.min_train_predictions),
                "direction_rules": list(config.direction_rules),
                "max_confidence_bps": list(config.max_confidence_bps),
                "prediction_sides": list(config.prediction_sides),
                "hour_windows": list(config.hour_windows),
                "selection_mode": config.selection_mode,
            },
        })

        report = KronosDirectionReport(
            status="completed",
            locked_opened=False,
            validation_used_for_selection=False,
            selected_on="train",
            run_id=config.run_id,
            output_dir=str(output_dir),
            symbol=config.symbol,
            library=config.library,
            version=config.version,
            model=config.model,
            train_period=_period_tuple(train),
            validation_period=_period_tuple(validation),
            locked_period=_period_tuple(locked),
            train_rows=int(len(train)),
            validation_rows=int(len(validation)),
            locked_rows=int(len(locked)),
            best_train=best_train,
            validation_result=validation_result,
            baseline_train=baseline_train,
            baseline_validation=baseline_validation,
        )
        report_path.write_text(direction_report_to_markdown(report), encoding="utf-8")
        _append_jsonl(progress_path, {
            "event": "completed",
            "elapsed_seconds": time.perf_counter() - started,
            "best_train": best_train.to_dict(),
            "validation_result": validation_result.to_dict(),
            "locked_opened": False,
            "updated_at_utc": _now(),
        })
        _write_json(status_path, report.to_dict() | {
            "completed_at_utc": _now(),
            "elapsed_seconds": time.perf_counter() - started,
        })
        return report
    except Exception as exc:
        stderr_path.write_text(traceback.format_exc(), encoding="utf-8")
        _write_json(status_path, {
            "status": "error",
            "locked_opened": False,
            "validation_used_for_selection": False,
            "run_id": config.run_id,
            "error": str(exc),
            "updated_at_utc": _now(),
        })
        raise


def generate_rolling_forecasts(
    frame: pd.DataFrame,
    config: KronosToolConfig,
    predictor: KronosPredictorProtocol | None = None,
) -> pd.DataFrame:
    if len(frame) <= config.lookback + 1:
        return pd.DataFrame(columns=["pred_open", "pred_high", "pred_low", "pred_close"])
    indices = _forecast_indices(frame, config)
    if predictor is None and int(config.workers) > 1 and len(indices) > 1:
        rows = _generate_rolling_forecasts_parallel(frame, config, indices)
    else:
        active_predictor = predictor or KronosAdapter(model=config.model, device=config.device)
        rows = _generate_forecast_rows(frame, config, indices, active_predictor)
    if not rows:
        return pd.DataFrame(columns=["pred_open", "pred_high", "pred_low", "pred_close"])
    out = pd.DataFrame(rows).set_index("target_date").sort_index()
    return out.dropna(subset=["pred_close"])


def _forecast_indices(frame: pd.DataFrame, config: KronosToolConfig) -> list[int]:
    step = max(1, int(config.forecast_step))
    start = max(int(config.lookback), 1)
    indices = list(range(start, len(frame), step))
    if config.max_windows > 0:
        indices = indices[-int(config.max_windows):]
    return indices


def _generate_forecast_rows(
    frame: pd.DataFrame,
    config: KronosToolConfig,
    indices: list[int],
    predictor: KronosPredictorProtocol,
) -> list[dict[str, float | pd.Timestamp]]:
    rows: list[dict[str, float | pd.Timestamp]] = []
    for target_pos in indices:
        x_start = max(0, target_pos - int(config.lookback))
        history = frame.iloc[x_start:target_pos]
        target_index = frame.index[target_pos:target_pos + 1]
        if history.empty or len(target_index) != 1:
            continue
        pred = predictor.predict(
            df=history.copy(),
            x_timestamp=pd.Series(history.index),
            y_timestamp=pd.Series(target_index),
            pred_len=1,
            T=float(config.temperature),
            top_p=float(config.top_p),
            sample_count=int(config.sample_count),
        )
        if pred.empty:
            continue
        first = pred.iloc[0]
        rows.append({
            "target_date": pd.Timestamp(target_index[0]),
            "pred_open": float(first.get("open", np.nan)),
            "pred_high": float(first.get("high", np.nan)),
            "pred_low": float(first.get("low", np.nan)),
            "pred_close": float(first.get("close", np.nan)),
        })
    return rows


def _generate_rolling_forecasts_parallel(
    frame: pd.DataFrame,
    config: KronosToolConfig,
    indices: list[int],
) -> list[dict[str, float | pd.Timestamp]]:
    workers = max(1, int(config.workers))
    chunks = [indices[pos::workers] for pos in range(workers)]
    chunks = [chunk for chunk in chunks if chunk]
    rows: list[dict[str, float | pd.Timestamp]] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(chunks))) as executor:
        futures = [
            executor.submit(_kronos_forecast_worker, frame, config, chunk)
            for chunk in chunks
        ]
        for future in as_completed(futures):
            rows.extend(future.result())
    rows.sort(key=lambda row: pd.Timestamp(row["target_date"]))
    return rows


def _kronos_forecast_worker(
    frame: pd.DataFrame,
    config: KronosToolConfig,
    indices: list[int],
) -> list[dict[str, float | pd.Timestamp]]:
    predictor = KronosAdapter(model=config.model, device=config.device)
    return _generate_forecast_rows(frame, config, indices, predictor)


def positions_from_forecast(
    frame: pd.DataFrame,
    forecasts: pd.DataFrame,
    *,
    threshold_bps: float = 0.0,
    initial_side: float = 1.0,
) -> np.ndarray:
    positions = np.full(len(frame), float(initial_side), dtype=np.float64)
    index = pd.Index(frame.index)
    threshold = float(threshold_bps) / 10_000.0
    for target_date, row in forecasts.iterrows():
        loc = index.get_indexer([pd.Timestamp(target_date)])
        if len(loc) != 1 or loc[0] <= 0:
            continue
        target_pos = int(loc[0])
        decision_pos = target_pos - 1
        reference_close = float(frame["close"].iloc[decision_pos])
        predicted_close = float(row["pred_close"])
        desired = 1.0 if predicted_close / reference_close - 1.0 >= threshold else -1.0
        positions[decision_pos:] = desired
    return positions


def report_to_markdown(report: KronosReport) -> str:
    lines = [
        "# Aurora Kronos Search",
        "",
        f"Run ID: `{report.run_id}`",
        f"Model: `{report.model}`",
        f"Symbol: `{report.symbol}`",
        f"Locked opened: `{report.locked_opened}`",
        f"Objective met: `{report.objective_met}`",
        f"Used columns: {', '.join(report.used_columns)}",
        "",
        "| Rank | Candidate | Train Calmar | CAGR | MDD | Trades/year | Long % | Rule |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for rank, candidate in enumerate(report.top, start=1):
        metrics = candidate.metrics
        lines.append(
            f"| {rank} | {candidate.candidate_id} | {metrics.calmar:.3f} | "
            f"{metrics.cagr * 100:.2f}% | {metrics.mdd * 100:.2f}% | "
            f"{metrics.trades_per_year:.1f} | {metrics.long_fraction * 100:.1f}% | "
            f"{candidate.rule} |"
        )
    if report.validation_best is not None:
        metrics = report.validation_best.metrics
        lines.extend([
            "",
            "## Validation Exam",
            "",
            "| Candidate | Validation Calmar | CAGR | MDD | Trades/year | Long % |",
            "|---|---:|---:|---:|---:|---:|",
            f"| {report.validation_best.candidate_id} | {metrics.calmar:.3f} | "
            f"{metrics.cagr * 100:.2f}% | {metrics.mdd * 100:.2f}% | "
            f"{metrics.trades_per_year:.1f} | {metrics.long_fraction * 100:.1f}% |",
        ])
    return "\n".join(lines) + "\n"


def _evaluate_thresholds(
    frame: pd.DataFrame,
    forecasts: pd.DataFrame,
    thresholds: tuple[float, ...],
    *,
    prefix: str,
) -> tuple[KronosCandidate, ...]:
    out: list[KronosCandidate] = []
    years = max((len(frame) - 1) / 252.0, 1e-9)
    for threshold in thresholds:
        positions = positions_from_forecast(frame, forecasts, threshold_bps=threshold)
        metrics = _metrics_for_positions(frame["close"].to_numpy(dtype=np.float64), positions, years)
        out.append(KronosCandidate(
            candidate_id=f"kronos-{prefix}-{int(round(threshold)):04d}bps",
            threshold_bps=float(threshold),
            metrics=metrics,
            rule=(
                "long if Kronos predicted next close is above current close "
                f"by at least {threshold:.1f} bps, else short"
            ),
        ))
    return tuple(out)


def _signals_frame(
    frame: pd.DataFrame,
    forecasts: pd.DataFrame,
    candidates: tuple[KronosCandidate, ...],
) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for candidate in candidates[:10]:
        out[candidate.candidate_id] = positions_from_forecast(
            frame,
            forecasts,
            threshold_bps=candidate.threshold_bps,
        )
    return out


def _metrics_for_positions(close: np.ndarray, positions: np.ndarray, years: float) -> KronosMetrics:
    returns = np.zeros(len(close), dtype=np.float64)
    returns[1:] = close[1:] / close[:-1] - 1.0
    strategy_returns = np.zeros(len(close), dtype=np.float64)
    strategy_returns[1:] = positions[:-1] * returns[1:]
    equity = np.cumprod(1.0 + strategy_returns)
    final = float(equity[-1]) if len(equity) else 1.0
    peak = np.maximum.accumulate(equity) if len(equity) else np.asarray([1.0])
    mdd = float((equity / peak - 1.0).min()) if len(equity) else 0.0
    if final > 0.0:
        annual_log_growth = np.log(final) / years
        cagr = float(np.exp(annual_log_growth) - 1.0) if annual_log_growth < 700.0 else float("inf")
    else:
        cagr = -999.0
    calmar = float(cagr / abs(mdd)) if mdd < -1e-12 else -999.0
    trades = int(np.count_nonzero(np.diff(positions) != 0.0))
    return KronosMetrics(
        calmar=calmar,
        cagr=cagr,
        mdd=mdd,
        trades=trades,
        trades_per_year=trades / years,
        long_fraction=float(np.mean(positions > 0.0)) if len(positions) else 0.0,
        final_nav=final,
    )


def load_crypto_5m_frame(
    symbol: str = "BTCUSDT",
    *,
    library: str = "crypto_5m",
    version: str = "binance_5m_36m",
    allow_volume: bool = True,
) -> pd.DataFrame:
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    source = store.read(library=library, symbol=symbol, version=version)
    columns = set(str(column) for column in source.columns)
    required = set(CRYPTO_5M_COLUMNS if allow_volume else OHLC_COLUMNS)
    missing = required - columns
    if missing:
        raise ValueError(f"crypto 5m source missing columns: {sorted(missing)}")
    unknown = columns - set(CRYPTO_5M_COLUMNS)
    if unknown:
        raise ValueError(f"crypto 5m source has forbidden columns: {sorted(unknown)}")
    frame = source[list(CRYPTO_5M_COLUMNS if allow_volume else OHLC_COLUMNS)].copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.sort_index()
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna()


def direction_strategy_metrics(
    *,
    close: np.ndarray,
    positions: np.ndarray,
    bars_per_year: int = BARS_PER_YEAR_CRYPTO_5M,
) -> dict[str, Any]:
    close = np.asarray(close, dtype=np.float64)
    positions = np.asarray(positions, dtype=np.float64)
    if len(close) == 0:
        return {
            "return_total": 0.0,
            "cagr": 0.0,
            "mdd": 0.0,
            "calmar": -999.0,
            "position_changes_per_day": 0.0,
            "bars_per_year": int(bars_per_year),
        }
    returns = np.zeros(len(close), dtype=np.float64)
    returns[1:] = close[1:] / close[:-1] - 1.0
    strategy_returns = positions * returns
    equity = np.cumprod(1.0 + strategy_returns)
    final = float(equity[-1])
    years = max(len(close) / float(bars_per_year), 1e-9)
    if final > 0.0:
        annual_log_growth = np.log(final) / years
        cagr = float(np.exp(annual_log_growth) - 1.0) if annual_log_growth < 700.0 else float("inf")
    else:
        cagr = -999.0
    peak = np.maximum.accumulate(equity)
    mdd = float((equity / peak - 1.0).min())
    calmar = float(cagr / abs(mdd)) if mdd < -1e-12 else -999.0
    position_changes = int(np.count_nonzero(np.diff(positions) != 0.0))
    days = max(len(close) / (24.0 * 12.0), 1e-9)
    return {
        "return_total": final - 1.0,
        "cagr": cagr,
        "mdd": mdd,
        "calmar": calmar,
        "position_changes_per_day": position_changes / days,
        "bars_per_year": int(bars_per_year),
    }


def _direction_output_dir(run_id: str, run_root: str | None = None) -> Path:
    root = Path(run_root) if run_root else base_data_dir() / "agent_loop"
    return root / run_id / "kronos_direction"


def _fetch_binance_month(
    symbol: str,
    year: int,
    month: int,
    interval: str,
) -> tuple[pd.DataFrame, bool]:
    import csv
    import hashlib
    import io
    import zipfile
    from urllib.request import urlopen

    symbol = symbol.upper()
    base = (
        "https://data.binance.vision/data/spot/monthly/klines/"
        f"{symbol}/{interval}/"
    )
    name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
    zip_url = base + name
    checksum_url = zip_url + ".CHECKSUM"
    with urlopen(zip_url, timeout=60) as response:  # nosec B310 -- official URL
        zip_bytes = response.read()
    checksum_available = False
    try:
        with urlopen(checksum_url, timeout=15) as response:  # nosec B310 -- official URL
            checksum_text = response.read().decode("ascii", errors="replace")
            expected = checksum_text.strip().split()[0] if checksum_text else ""
            checksum_available = bool(expected)
            if expected and hashlib.sha256(zip_bytes).hexdigest().lower() != expected.lower():
                raise ValueError(f"checksum mismatch for {name}")
    except Exception:
        checksum_available = False

    rows: list[list[str]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for member in zf.namelist():
            if not member.lower().endswith(".csv"):
                continue
            text = zf.read(member).decode("utf-8", errors="replace")
            rows.extend(row for row in csv.reader(io.StringIO(text)) if row and len(row) >= 6)
    if not rows:
        return pd.DataFrame(columns=CRYPTO_5M_COLUMNS), checksum_available
    raw = pd.DataFrame(rows)
    open_time = pd.to_numeric(raw[0], errors="coerce")
    max_open_time = float(open_time.max())
    unit = "us" if max_open_time > 10_000_000_000_000 else "ms"
    frame = pd.DataFrame({
        "open": pd.to_numeric(raw[1], errors="coerce"),
        "high": pd.to_numeric(raw[2], errors="coerce"),
        "low": pd.to_numeric(raw[3], errors="coerce"),
        "close": pd.to_numeric(raw[4], errors="coerce"),
        "volume": pd.to_numeric(raw[5], errors="coerce"),
    })
    frame.index = pd.to_datetime(open_time, unit=unit, utc=True)
    frame.index.name = "timestamp"
    return frame.dropna(subset=["open", "high", "low", "close"]), checksum_available


def _month_pairs(start: str, end: str) -> list[tuple[int, int]]:
    start_ts = _utc_timestamp(start)
    end_ts = _utc_timestamp(end)
    periods = pd.period_range(
        start_ts.tz_localize(None).to_period("M"),
        end_ts.tz_localize(None).to_period("M"),
        freq="M",
    )
    return [(int(period.year), int(period.month)) for period in periods]


def _normalise_crypto_5m_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "timestamp" in out.columns:
        out.index = pd.to_datetime(out.pop("timestamp"), utc=True)
    out.index = pd.to_datetime(out.index, utc=True)
    out = out.sort_index()
    out = out[list(CRYPTO_5M_COLUMNS)]
    for column in CRYPTO_5M_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.dropna(subset=["open", "high", "low", "close"])


def _utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _split_direction_periods(
    frame: pd.DataFrame,
    config: KronosDirectionBacktestConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(frame)
    if n < max(config.lookbacks) + 10:
        raise ValueError("not enough crypto 5m rows for requested Kronos lookback")
    train_end = int(n * config.train_fraction)
    validation_end = int(n * (config.train_fraction + config.validation_fraction))
    if train_end <= max(config.lookbacks) or validation_end <= train_end:
        raise ValueError("invalid train/validation fractions for crypto 5m frame")
    return frame.iloc[:train_end], frame.iloc[train_end:validation_end], frame.iloc[validation_end:]


def _direction_config_grid(config: KronosDirectionBacktestConfig) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lookback in config.lookbacks:
        for temperature in config.temperatures:
            for top_p in config.top_ps:
                for sample_count in config.sample_counts:
                    out.append({
                        "lookback": int(lookback),
                        "temperature": float(temperature),
                        "top_p": float(top_p),
                        "sample_count": int(sample_count),
                    })
    return out


def _candidate_config_id(config: dict[str, Any]) -> str:
    return (
        f"lb{int(config['lookback'])}_"
        f"t{float(config['temperature']):.3f}_"
        f"p{float(config['top_p']):.3f}_"
        f"s{int(config['sample_count'])}"
    )


def _target_positions(frame: pd.DataFrame, lookback: int, max_windows: int) -> list[int]:
    positions = list(range(int(lookback), len(frame)))
    if max_windows > 0:
        positions = positions[-int(max_windows):]
    return positions


def _generate_direction_predictions(
    frame: pd.DataFrame,
    predictor: KronosPredictorProtocol,
    config: dict[str, Any],
    *,
    max_windows: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    lookback = int(config["lookback"])
    for target_pos in _target_positions(frame, lookback, max_windows):
        history = frame.iloc[target_pos - lookback:target_pos]
        decision_time = pd.Timestamp(frame.index[target_pos - 1])
        target_time = pd.Timestamp(frame.index[target_pos])
        pred = predictor.predict(
            df=history.copy(),
            x_timestamp=pd.Series(history.index),
            y_timestamp=pd.Series([target_time]),
            pred_len=1,
            T=float(config["temperature"]),
            top_p=float(config["top_p"]),
            sample_count=int(config["sample_count"]),
        )
        if pred.empty:
            continue
        current_close = float(frame["close"].iloc[target_pos - 1])
        actual_close = float(frame["close"].iloc[target_pos])
        predicted_close = float(pred["close"].iloc[0])
        predicted_return_bps = (predicted_close / current_close - 1.0) * 10_000.0
        actual_return_bps = (actual_close / current_close - 1.0) * 10_000.0
        predicted_direction = 1 if predicted_return_bps >= 0.0 else -1
        actual_direction = 1 if actual_return_bps >= 0.0 else -1
        rows.append({
            "last_input_time": decision_time,
            "decision_time": decision_time,
            "target_time": target_time,
            "current_close": current_close,
            "predicted_close": predicted_close,
            "actual_close": actual_close,
            "predicted_direction": predicted_direction,
            "actual_direction": actual_direction,
            "predicted_label": "up" if predicted_direction > 0 else "down",
            "actual_label": "up" if actual_direction > 0 else "down",
            "hit": bool(predicted_direction == actual_direction),
            "predicted_return_bps": predicted_return_bps,
            "actual_return_bps": actual_return_bps,
            "abs_predicted_return_bps": abs(predicted_return_bps),
            "lookback": lookback,
            "temperature": float(config["temperature"]),
            "top_p": float(config["top_p"]),
            "sample_count": int(config["sample_count"]),
        })
    return pd.DataFrame(rows)


def _apply_confidence_filter(predictions: pd.DataFrame, confidence_bps: float) -> pd.DataFrame:
    if predictions.empty:
        return predictions.copy()
    out = predictions.loc[predictions["abs_predicted_return_bps"] >= float(confidence_bps)].copy()
    out["confidence_bps"] = float(confidence_bps)
    return out


def _hour_window_mask(times: pd.Series, hour_window: str) -> np.ndarray:
    window = str(hour_window).lower()
    hours = pd.to_datetime(times).dt.hour.to_numpy()
    if window == "all":
        return np.ones(len(hours), dtype=bool)
    if not window.startswith("utc_"):
        raise ValueError(f"unknown hour window: {hour_window}")
    try:
        start_text, end_text = window.removeprefix("utc_").split("_", 1)
        start = int(start_text)
        end = int(end_text)
    except ValueError as exc:
        raise ValueError(f"unknown hour window: {hour_window}") from exc
    if start < 0 or start > 23 or end < 1 or end > 24 or start == end:
        raise ValueError(f"invalid hour window: {hour_window}")
    if start < end:
        return (hours >= start) & (hours < end)
    return (hours >= start) | (hours < end)


def _apply_direction_candidate_filters(
    predictions: pd.DataFrame,
    *,
    confidence_bps: float,
    max_confidence_bps: float,
    prediction_side: str,
    hour_window: str,
) -> pd.DataFrame:
    out = _apply_confidence_filter(predictions, confidence_bps)
    if out.empty:
        out["max_confidence_bps"] = float(max_confidence_bps)
        out["prediction_side"] = str(prediction_side).lower()
        out["hour_window"] = str(hour_window).lower()
        return out
    mask = out["abs_predicted_return_bps"].astype(float) <= float(max_confidence_bps)
    side = str(prediction_side).lower()
    if side == "up":
        mask &= out["predicted_direction"].astype(int) > 0
    elif side == "down":
        mask &= out["predicted_direction"].astype(int) < 0
    elif side != "both":
        raise ValueError(f"unknown prediction side: {prediction_side}")
    mask &= _hour_window_mask(out["target_time"], str(hour_window))
    filtered = out.loc[mask].copy()
    filtered["max_confidence_bps"] = float(max_confidence_bps)
    filtered["prediction_side"] = side
    filtered["hour_window"] = str(hour_window).lower()
    return filtered


def _apply_direction_rule(predictions: pd.DataFrame, direction_rule: str) -> pd.DataFrame:
    rule = str(direction_rule).lower()
    adaptive_window: int | None = None
    if rule.startswith("adaptive_"):
        try:
            adaptive_window = int(rule.split("_", 1)[1])
        except ValueError as exc:
            raise ValueError(f"unknown direction rule: {direction_rule}") from exc
        if adaptive_window < 2:
            raise ValueError(f"adaptive direction rule window too small: {direction_rule}")
    elif rule not in {"raw", "inverted"}:
        raise ValueError(f"unknown direction rule: {direction_rule}")
    out = predictions.copy()
    if out.empty:
        out["direction_rule"] = rule
        return out
    if rule == "inverted":
        out["predicted_direction"] = -out["predicted_direction"].astype(int)
    elif adaptive_window is not None:
        raw_direction = out["predicted_direction"].astype(int).to_numpy()
        actual_direction = out["actual_direction"].astype(int).to_numpy()
        calibrated = raw_direction.copy()
        for idx in range(len(raw_direction)):
            start = max(0, idx - adaptive_window)
            if idx - start < adaptive_window:
                continue
            recent_raw_hit_rate = (
                raw_direction[start:idx] == actual_direction[start:idx]
            ).mean()
            if recent_raw_hit_rate < 0.5:
                calibrated[idx] = -raw_direction[idx]
        out["predicted_direction"] = calibrated
    out["predicted_label"] = np.where(
        out["predicted_direction"].astype(int) > 0, "up", "down"
    )
    out["hit"] = out["predicted_direction"].astype(int) == out["actual_direction"].astype(int)
    out["direction_rule"] = rule
    return out


def _direction_candidate_sort_key(
    config: KronosDirectionBacktestConfig,
) -> Callable[[KronosDirectionCandidate], tuple[bool, float, float, int, float]]:
    mode = str(config.selection_mode).lower()
    if mode not in {"stable", "recent"}:
        raise ValueError(f"unknown Kronos direction selection mode: {config.selection_mode}")

    def key(item: KronosDirectionCandidate) -> tuple[bool, float, float, int, float]:
        enough_predictions = item.metrics.get("prediction_count", 0) >= int(
            config.min_train_predictions
        )
        if mode == "recent":
            primary = float(item.metrics.get("second_half_accuracy", -1.0))
            secondary = float(item.metrics.get("accuracy", -1.0))
        else:
            primary = float(item.metrics.get("stability_accuracy", -1.0))
            secondary = float(item.metrics.get("accuracy", -1.0))
        return (
            enough_predictions,
            primary,
            secondary,
            int(item.metrics.get("prediction_count", 0)),
            float(item.metrics.get("strategy_calmar", -999.0)),
        )

    return key


def _evaluate_direction_candidate(
    predictions: pd.DataFrame,
    config: dict[str, Any],
    *,
    confidence_bps: float,
    max_confidence_bps: float,
    prediction_side: str,
    hour_window: str,
    direction_rule: str,
    prefix: str,
) -> KronosDirectionCandidate:
    filtered = _apply_direction_candidate_filters(
        predictions,
        confidence_bps=confidence_bps,
        max_confidence_bps=max_confidence_bps,
        prediction_side=prediction_side,
        hour_window=hour_window,
    )
    filtered = _apply_direction_rule(filtered, direction_rule)
    metrics = _direction_metrics(filtered)
    candidate_config = dict(config) | {
        "confidence_bps": float(confidence_bps),
        "max_confidence_bps": float(max_confidence_bps),
        "prediction_side": str(prediction_side).lower(),
        "hour_window": str(hour_window).lower(),
        "direction_rule": str(direction_rule).lower(),
    }
    return KronosDirectionCandidate(
        candidate_id=(
            f"kronos-direction-{prefix}-{_candidate_config_id(config)}"
            f"-c{confidence_bps:g}-{max_confidence_bps:g}"
            f"-{str(prediction_side).lower()}-{str(hour_window).lower()}"
            f"-{str(direction_rule).lower()}"
        ),
        config=candidate_config,
        metrics=metrics,
    )


def _direction_metrics(predictions: pd.DataFrame) -> dict[str, Any]:
    if predictions.empty:
        return {
            "prediction_count": 0,
            "accuracy": 0.0,
            "up_accuracy": None,
            "down_accuracy": None,
            "first_half_accuracy": None,
            "second_half_accuracy": None,
            "stability_accuracy": 0.0,
            "strategy_return_total": 0.0,
            "strategy_cagr": 0.0,
            "strategy_mdd": 0.0,
            "strategy_calmar": -999.0,
            "position_changes_per_day": 0.0,
        }
    hit = predictions["hit"].astype(bool)
    split = max(len(hit) // 2, 1)
    first_half_accuracy = float(hit.iloc[:split].mean()) if split > 0 else None
    second_half_accuracy = float(hit.iloc[split:].mean()) if len(hit) > split else None
    stability_accuracy = min(
        first_half_accuracy if first_half_accuracy is not None else 0.0,
        second_half_accuracy if second_half_accuracy is not None else 0.0,
    )
    up = predictions["predicted_direction"].astype(int) > 0
    down = ~up
    positions = predictions["predicted_direction"].astype(float).to_numpy()
    actual_returns = predictions["actual_return_bps"].astype(float).to_numpy() / 10_000.0
    strategy_returns = positions * actual_returns
    equity = np.cumprod(1.0 + strategy_returns)
    final = float(equity[-1]) if len(equity) else 1.0
    years = max(len(strategy_returns) / float(BARS_PER_YEAR_CRYPTO_5M), 1e-9)
    if final > 0.0:
        annual_log_growth = np.log(final) / years
        strategy_cagr = (
            float(np.exp(annual_log_growth) - 1.0)
            if annual_log_growth < 700.0
            else float("inf")
        )
    else:
        strategy_cagr = -999.0
    peak = np.maximum.accumulate(equity) if len(equity) else np.asarray([1.0])
    strategy_mdd = float((equity / peak - 1.0).min()) if len(equity) else 0.0
    strategy_calmar = (
        float(strategy_cagr / abs(strategy_mdd))
        if strategy_mdd < -1e-12
        else -999.0
    )
    days = max(len(strategy_returns) / (24.0 * 12.0), 1e-9)
    position_changes_per_day = int(np.count_nonzero(np.diff(positions) != 0.0)) / days
    return {
        "prediction_count": int(len(predictions)),
        "accuracy": float(hit.mean()),
        "up_accuracy": float(hit[up].mean()) if up.any() else None,
        "down_accuracy": float(hit[down].mean()) if down.any() else None,
        "first_half_accuracy": first_half_accuracy,
        "second_half_accuracy": second_half_accuracy,
        "stability_accuracy": stability_accuracy,
        "avg_abs_predicted_bps": float(predictions["abs_predicted_return_bps"].mean()),
        "strategy_return_total": final - 1.0,
        "strategy_cagr": strategy_cagr,
        "strategy_mdd": strategy_mdd,
        "strategy_calmar": strategy_calmar,
        "position_changes_per_day": position_changes_per_day,
    }


def direction_baselines(predictions: pd.DataFrame) -> dict[str, Any]:
    if predictions.empty:
        return {
            "always_up_accuracy": 0.0,
            "previous_direction_accuracy": 0.0,
            "random_baseline_accuracy": 0.5,
        }
    actual = predictions["actual_direction"].astype(int)
    actual_return = predictions["actual_return_bps"].astype(float)
    previous_direction = np.sign(actual_return.shift(1).fillna(0.0)).replace(0.0, 1.0)
    return {
        "always_up_accuracy": float((actual > 0).mean()),
        "previous_direction_accuracy": float((previous_direction.astype(int) == actual).mean()),
        "random_baseline_accuracy": 0.5,
    }


def direction_report_to_markdown(report: KronosDirectionReport) -> str:
    train = report.best_train.metrics
    validation = report.validation_result.metrics
    lines = [
        "# Kronos BTC 5m Direction Backtest",
        "",
        f"Run ID: `{report.run_id}`",
        f"Symbol: `{report.symbol}`",
        f"Model: `{report.model}`",
        f"Locked opened: `{report.locked_opened}`",
        f"Selection: `{report.selected_on}`",
        "",
        "| Phase | Predictions | Accuracy | Up accuracy | Down accuracy | Calmar | Return |",
        "|---|---:|---:|---:|---:|---:|---:|",
        (
            f"| Train | {train['prediction_count']} | {train['accuracy']:.3f} | "
            f"{_fmt_optional(train['up_accuracy'])} | {_fmt_optional(train['down_accuracy'])} | "
            f"{train['strategy_calmar']:.3f} | {train['strategy_return_total'] * 100:.2f}% |"
        ),
        (
            f"| Validation | {validation['prediction_count']} | {validation['accuracy']:.3f} | "
            f"{_fmt_optional(validation['up_accuracy'])} | "
            f"{_fmt_optional(validation['down_accuracy'])} | "
            f"{validation['strategy_calmar']:.3f} | "
            f"{validation['strategy_return_total'] * 100:.2f}% |"
        ),
        "",
        f"Best config: `{json.dumps(report.best_train.config, sort_keys=True)}`",
    ]
    return "\n".join(lines) + "\n"


def _fmt_optional(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def _output_dir(config: KronosToolConfig) -> Path:
    root = Path(config.run_root) if config.run_root else base_data_dir() / "agent_loop"
    return root / config.run_id / "kronos"


def _model_spec(model: str) -> dict[str, object]:
    try:
        return dict(MODEL_SPECS[model])
    except KeyError as exc:
        raise ValueError(f"unknown Kronos model {model!r}; supported: {sorted(MODEL_SPECS)}") from exc


def _period_tuple(frame: pd.DataFrame) -> tuple[str, str]:
    if frame.empty:
        return ("empty", "empty")
    return (str(frame.index.min().date()), str(frame.index.max().date()))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, engine="pyarrow", compression="snappy")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "Crypto5mDataStatus",
    "Crypto5mIngestionConfig",
    "KronosAdapter",
    "KronosCandidate",
    "KronosDependencyError",
    "KronosDirectionBacktestConfig",
    "KronosDirectionCandidate",
    "KronosDirectionReport",
    "KronosInstallConfig",
    "KronosMetrics",
    "KronosReport",
    "KronosToolConfig",
    "direction_baselines",
    "direction_report_to_markdown",
    "direction_strategy_metrics",
    "generate_rolling_forecasts",
    "ingest_binance_crypto_5m",
    "kronos_manifest_path",
    "kronos_tools_dir",
    "load_crypto_5m_frame",
    "load_kronos_frame",
    "positions_from_forecast",
    "report_to_markdown",
    "run_kronos_direction_backtest",
    "run_kronos_forecast",
    "run_kronos_install",
    "run_kronos_search",
    "validate_crypto_5m_frame",
    "validate_kronos_source_frame",
]
