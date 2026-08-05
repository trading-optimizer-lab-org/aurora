"""CPU-heavy deterministic candidate sweep using Aurora's backtest engine."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.core.costs import CostModel
from aurora.core.engine import run_backtest
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.metric_verifier import MetricInputRecord
from aurora.infra.github_performance.workloads.common import (
    FrozenScientificWorkload,
    logical_table_sha256,
    metrics_for_row,
    primary_metric_record,
)


SEED = 20_260_801
COSTS = CostModel(
    commission_bps=0.5,
    spread_bps=0.5,
    slippage_bps=0.5,
)
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
        pa.field("fast_window", pa.int32(), nullable=False),
        pa.field("slow_window", pa.int32(), nullable=False),
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


def _generate_prices() -> pd.DataFrame:
    train_dates = pd.bdate_range("1995-01-02", "2010-12-31")
    validation_dates = pd.bdate_range("2011-01-03", "2020-12-31")
    dates = train_dates.append(validation_dates)
    rng = np.random.default_rng(SEED)
    phase = np.linspace(0.0, 32.0 * math.pi, len(dates))
    returns = (
        rng.normal(0.00025, 0.0105, len(dates))
        + 0.0002 * np.sin(phase)
        + 0.0001 * np.cos(phase / 5.0)
    )
    close = 100.0 * np.exp(np.cumsum(np.log1p(np.clip(returns, -0.2, 0.2))))
    return pd.DataFrame(
        {
            "date": dates,
            "close": close,
            "period": (
                ["train"] * len(train_dates)
                + ["validation"] * len(validation_dates)
            ),
        }
    )


def _signal(prices: pd.Series, fast: int, slow: int) -> np.ndarray:
    fast_mean = prices.rolling(fast, min_periods=fast).mean()
    slow_mean = prices.rolling(slow, min_periods=slow).mean()
    signal = np.where(fast_mean > slow_mean, 1.0, 0.0)
    signal[np.isnan(fast_mean) | np.isnan(slow_mean)] = 0.0
    return signal


class CandidateSweepWorkload(FrozenScientificWorkload):
    workload_name = "aurora_candidate_sweep_cpu"
    workload_family = "candidate_sweep"
    dataset_name = "frozen_candidate_sweep_market"
    result_filename = "candidate_sweep_results.parquet"
    result_schema = _result_schema()
    seed = SEED

    def _prepare_dataset(self, root: Path) -> tuple[tuple[str, ...], str]:
        path = root / "candidate_sweep_prices.parquet"
        table = pa.Table.from_pandas(_generate_prices(), preserve_index=False)
        pq.write_table(
            table,
            path,
            compression="zstd",
            version="2.6",
        )
        return (path.name,), logical_table_sha256(table)

    def _load_dataset(self, root: Path) -> pd.DataFrame:
        path = Path(root) / "candidate_sweep_prices.parquet"
        frame = pq.read_table(
            path,
            columns=["date", "close", "period"],
        ).to_pandas()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date", kind="mergesort")
        if frame["date"].max() > pd.Timestamp("2020-12-31"):
            raise ValueError("candidate sweep crossed locked boundary")
        return frame

    def _unit_definitions(
        self,
    ) -> Sequence[tuple[str, Mapping[str, Any], float]]:
        definitions = []
        for fast in range(4, 36):
            for slow in range(50, 114, 4):
                definitions.append(
                    (
                        f"candidate-f{fast:03d}-s{slow:03d}",
                        {"fast_window": fast, "slow_window": slow},
                        0.01 + slow / 100_000.0,
                    )
                )
        if len(definitions) != 512:
            raise AssertionError("candidate sweep must have 512 units")
        return tuple(definitions)

    def _evaluate(
        self,
        data: pd.DataFrame,
        unit_key: str,
        parameters: Mapping[str, Any],
        attempt_id: str,
    ) -> tuple[dict[str, Any], tuple[MetricInputRecord, ...]]:
        fast = int(parameters["fast_window"])
        slow = int(parameters["slow_window"])
        row: dict[str, Any] = {
            "unit_key": unit_key,
            "source_attempt_id": attempt_id,
            "family": self.workload_family,
            "fast_window": fast,
            "slow_window": slow,
        }
        records = []
        for split in ("train", "validation"):
            selected = data.loc[data["period"] == split]
            prices = pd.Series(
                selected["close"].to_numpy(dtype=float),
                index=pd.DatetimeIndex(selected["date"]),
                name="FROZEN_MARKET",
            )
            result = run_backtest(
                prices,
                _signal,
                costs=COSTS,
                ppy=252,
                fast=fast,
                slow=slow,
            )
            record = primary_metric_record(
                unit_key,
                split,
                np.asarray(result.rets[1:], dtype=np.float64),
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


WORKLOAD = CandidateSweepWorkload()
