"""I/O-heavy partitioned event-study workload with causal event outcomes."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.metric_verifier import MetricInputRecord
from aurora.infra.github_performance.workloads.common import (
    FrozenScientificWorkload,
    metrics_for_row,
    primary_metric_record,
)


SEED = 20_260_802
SYMBOLS = tuple(f"EVENT_{index:02d}" for index in range(12))
METRIC_FIELDS = (
    "cagr_pct",
    "sharpe",
    "sortino",
    "max_drawdown_pct",
    "calmar",
    "profit_factor",
    "win_rate",
    "average_return_pct",
    "median_return_pct",
    "period_count",
)


def _result_schema() -> pa.Schema:
    fields = [
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("source_attempt_id", pa.string(), nullable=False),
        pa.field("family", pa.string(), nullable=False),
        pa.field("direction", pa.string(), nullable=False),
        pa.field("shock_threshold", pa.float64(), nullable=False),
        pa.field("forward_horizon", pa.int32(), nullable=False),
        pa.field("volume_multiplier", pa.float64(), nullable=False),
        pa.field("symbol_bucket", pa.int32(), nullable=False),
    ]
    for split in ("train", "validation"):
        for name in METRIC_FIELDS:
            kind = pa.int32() if name == "period_count" else pa.float64()
            fields.append(pa.field(f"{split}_{name}", kind))
    fields.extend(
        [
            pa.field("selected_on", pa.string(), nullable=False),
            pa.field("causal_lag_periods", pa.int32(), nullable=False),
            pa.field("locked_opened", pa.bool_(), nullable=False),
            pa.field(
                "validation_used_for_selection",
                pa.bool_(),
                nullable=False,
            ),
            pa.field("unit_output_sha256", pa.string(), nullable=False),
        ]
    )
    return pa.schema(fields)


def _generate_panel() -> pd.DataFrame:
    train_dates = pd.bdate_range("1995-01-02", "2010-12-31")
    validation_dates = pd.bdate_range("2011-01-03", "2020-12-31")
    dates = train_dates.append(validation_dates)
    rows = []
    for symbol_index, symbol in enumerate(SYMBOLS):
        rng = np.random.default_rng(SEED + symbol_index)
        phase = np.linspace(0.0, 20.0 * math.pi, len(dates))
        returns = (
            rng.normal(0.0002, 0.012 + symbol_index * 0.0002, len(dates))
            + 0.0003 * np.sin(phase + symbol_index / 3.0)
        )
        close = (
            (30.0 + symbol_index * 5.0)
            * np.exp(np.cumsum(np.log1p(np.clip(returns, -0.25, 0.25))))
        )
        volume = rng.lognormal(
            mean=13.0 + symbol_index * 0.02,
            sigma=0.35,
            size=len(dates),
        )
        rows.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": symbol,
                    "symbol_bucket": symbol_index % 2,
                    "close": close,
                    "volume": volume,
                    "period": (
                        ["train"] * len(train_dates)
                        + ["validation"] * len(validation_dates)
                    ),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


class EventStudyWorkload(FrozenScientificWorkload):
    workload_name = "aurora_partitioned_event_study"
    workload_family = "event_study"
    dataset_name = "frozen_partitioned_event_panel"
    result_filename = "event_study_results.parquet"
    result_schema = _result_schema()
    seed = SEED

    def _prepare_dataset(self, root: Path) -> tuple[tuple[str, ...], str]:
        dataset_root = root / "event_panel"
        table = pa.Table.from_pandas(_generate_panel(), preserve_index=False)
        ds.write_dataset(
            table,
            dataset_root,
            format="parquet",
            partitioning=["period", "symbol_bucket"],
            existing_data_behavior="delete_matching",
        )
        files = tuple(sorted(dataset_root.rglob("*.parquet")))
        identities = {
            str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in files
        }
        return tuple(identities), canonical_sha256(identities)

    def _load_dataset(self, root: Path) -> pd.DataFrame:
        dataset = ds.dataset(
            Path(root) / "event_panel",
            format="parquet",
            partitioning=["period", "symbol_bucket"],
        )
        frame = dataset.to_table(
            columns=[
                "date",
                "symbol",
                "symbol_bucket",
                "close",
                "volume",
                "period",
            ]
        ).to_pandas()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values(["symbol", "date"], kind="mergesort")
        if frame["date"].max() > pd.Timestamp("2020-12-31"):
            raise ValueError("event study crossed locked boundary")
        return frame

    def _unit_definitions(
        self,
    ) -> Sequence[tuple[str, Mapping[str, Any], float]]:
        definitions = []
        thresholds = (0.008, 0.012, 0.016, 0.020)
        horizons = (2, 5, 10, 20)
        volume_multipliers = (
            0.70,
            0.80,
            0.90,
            1.00,
            1.10,
            1.20,
            1.35,
            1.50,
        )
        for direction in ("down", "up"):
            for threshold in thresholds:
                for horizon in horizons:
                    for volume_multiplier in volume_multipliers:
                        for bucket in (0, 1):
                            token = (
                                f"{direction}-t{threshold:.3f}-h{horizon:02d}-"
                                f"v{volume_multiplier:.2f}-b{bucket}"
                            )
                            definitions.append(
                                (
                                    f"event-{token}",
                                    {
                                        "direction": direction,
                                        "shock_threshold": threshold,
                                        "forward_horizon": horizon,
                                        "volume_multiplier": volume_multiplier,
                                        "symbol_bucket": bucket,
                                    },
                                    0.02 + horizon / 10_000.0,
                                )
                            )
        if len(definitions) != 512:
            raise AssertionError("event study must have 512 units")
        return tuple(definitions)

    @staticmethod
    def _event_returns(
        data: pd.DataFrame,
        *,
        split: str,
        bucket: int,
        direction: str,
        threshold: float,
        horizon: int,
        volume_multiplier: float,
    ) -> np.ndarray:
        selected = data.loc[
            (data["period"] == split)
            & (data["symbol_bucket"] == bucket)
        ].copy()
        outcomes = []
        for _, frame in selected.groupby("symbol", sort=True):
            close = frame["close"].astype(float)
            daily = close.pct_change()
            average_volume = frame["volume"].rolling(
                20,
                min_periods=20,
            ).mean()
            liquid = frame["volume"] >= average_volume * volume_multiplier
            if direction == "down":
                event = daily <= -threshold
            else:
                event = daily >= threshold
            forward = close.shift(-horizon) / close - 1.0
            values = forward.loc[event & liquid].dropna().to_numpy(dtype=float)
            outcomes.append(values)
        if not outcomes:
            return np.asarray([], dtype=np.float64)
        return np.concatenate(outcomes).astype(np.float64, copy=False)

    def _evaluate(
        self,
        data: pd.DataFrame,
        unit_key: str,
        parameters: Mapping[str, Any],
        attempt_id: str,
    ) -> tuple[dict[str, Any], tuple[MetricInputRecord, ...]]:
        direction = str(parameters["direction"])
        threshold = float(parameters["shock_threshold"])
        horizon = int(parameters["forward_horizon"])
        volume_multiplier = float(parameters["volume_multiplier"])
        bucket = int(parameters["symbol_bucket"])
        row: dict[str, Any] = {
            "unit_key": unit_key,
            "source_attempt_id": attempt_id,
            "family": self.workload_family,
            "direction": direction,
            "shock_threshold": threshold,
            "forward_horizon": horizon,
            "volume_multiplier": volume_multiplier,
            "symbol_bucket": bucket,
        }
        records = []
        for split in ("train", "validation"):
            returns = self._event_returns(
                data,
                split=split,
                bucket=bucket,
                direction=direction,
                threshold=threshold,
                horizon=horizon,
                volume_multiplier=volume_multiplier,
            )
            record = primary_metric_record(
                unit_key,
                split,
                returns,
                periods_per_year=252,
            )
            records.append(record)
            row.update(
                {
                    f"{split}_{key}": value
                    for key, value in metrics_for_row(record).items()
                }
            )
        row.update(
            {
                "selected_on": "train_only",
                "causal_lag_periods": 1,
                "locked_opened": False,
                "validation_used_for_selection": False,
            }
        )
        row["unit_output_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in row.items()
                if key != "source_attempt_id"
            }
        )
        return row, tuple(records)

    def _access_ranges(
        self,
        data: pd.DataFrame,
    ) -> Mapping[str, tuple[Any, Any, int]]:
        result = {}
        for split in ("train", "validation"):
            dates = data.loc[data["period"] == split, "date"]
            result[split] = (
                dates.min().date(),
                dates.max().date(),
                len(dates),
            )
        return result


WORKLOAD = EventStudyWorkload()
