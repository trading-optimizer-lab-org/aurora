"""GitHub-only train workload for the frozen daily SPY campaign."""

from __future__ import annotations

import json
import math
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    PilotResult,
    PreparedInputs,
    RunSpec,
    SmokeResult,
    canonical_sha256,
)
from aurora.infra.github_performance.metric_verifier import MetricInputRecord
from aurora.infra.github_performance.workloads.common import (
    FrozenScientificWorkload,
    atomic_json,
    primary_metric_record,
)
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.sp500_long_short_daily.contracts import (
    CampaignPackage,
    canonical_json_hash,
    validate_exact_coverage,
)
from aurora.infra.sp500_long_short_daily.data import (
    PreparedMarketData,
    load_market_snapshot,
    prepare_market_snapshot,
)
from aurora.infra.sp500_long_short_daily.ledger import apply_positions
from aurora.infra.sp500_long_short_daily.signals import (
    CandidateRejected,
    benchmark_decisions,
    candidate_decisions,
)
from aurora.infra.sp500_long_short_daily.statistics import frozen_train_ranking


SEED = 20_260_803
BENCHMARK_IDS = (
    "buy_and_hold_spy_total_return",
    "always_long",
    "always_short",
    "symmetric_sma_200",
    "symmetric_momentum_12m",
)
METRIC_FIELDS = (
    "total_return_pct",
    "cagr_pct",
    "annualized_return_pct",
    "annualized_volatility_pct",
    "sharpe",
    "sortino",
    "max_drawdown_pct",
    "calmar",
    "profit_factor",
    "win_rate",
    "average_return_pct",
    "median_return_pct",
    "final_nav",
    "period_count",
)


def _repo_root() -> Path:
    candidates = (Path.cwd(), Path(__file__).resolve().parents[2])
    for root in candidates:
        if (root / "campaigns" / "sp500_long_short_daily" / "research_input").is_dir():
            return root.resolve()
    raise RuntimeError("SP500_CAMPAIGN_PACKAGE_NOT_FOUND")


def _package() -> CampaignPackage:
    campaign = _repo_root() / "campaigns" / "sp500_long_short_daily"
    return CampaignPackage.load(
        campaign / "research_input",
        campaign / "input_package" / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip",
    )


def _result_schema() -> pa.Schema:
    fields = [
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("source_attempt_id", pa.string(), nullable=False),
        pa.field("unit_type", pa.string(), nullable=False),
        pa.field("strategy_id", pa.string(), nullable=False),
        pa.field("family", pa.string(), nullable=False),
        pa.field("variant_label", pa.string(), nullable=False),
        pa.field("canonical_hash", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("rejection_reason", pa.string()),
        pa.field("evidence_track", pa.string(), nullable=False),
        pa.field("complexity_score", pa.int32(), nullable=False),
        pa.field("first_evaluable_date", pa.string()),
        pa.field("missing_fraction", pa.float64()),
    ]
    for name in METRIC_FIELDS:
        kind = pa.int32() if name == "period_count" else pa.float64()
        fields.append(pa.field(f"train_{name}", kind))
    fields.extend(
        [
            pa.field("train_positive_year_fraction", pa.float64()),
            pa.field("train_positive_years", pa.int32()),
            pa.field("train_worst_year_return_pct", pa.float64()),
            pa.field("train_rolling_1y_median_cagr_pct", pa.float64()),
            pa.field("train_median_rolling_3y_cagr_pct", pa.float64()),
            pa.field("train_rolling_5y_median_cagr_pct", pa.float64()),
            pa.field("train_min_outer_fold_cagr_pct", pa.float64()),
            pa.field("train_turnover", pa.float64()),
            pa.field("train_turnover_instability", pa.float64()),
            pa.field("train_long_days", pa.int32()),
            pa.field("train_short_days", pa.int32()),
            pa.field("train_position_switches", pa.int32()),
            pa.field("train_daily_hit_rate", pa.float64()),
            pa.field("train_monthly_hit_rate", pa.float64()),
            pa.field("train_average_holding_days", pa.float64()),
            pa.field("train_gain_concentration", pa.float64()),
            pa.field("train_skew", pa.float64()),
            pa.field("train_cvar_5_pct", pa.float64()),
            pa.field("train_worst_day_pct", pa.float64()),
            pa.field("train_worst_month_pct", pa.float64()),
            pa.field("performance_by_market_regime_json", pa.string()),
            pa.field("train_dates", pa.list_(pa.string())),
            pa.field("train_returns", pa.list_(pa.float64())),
            pa.field("train_positions", pa.list_(pa.int8())),
            pa.field("annual_metrics_json", pa.string()),
            pa.field("selected_on", pa.string(), nullable=False),
            pa.field("causal_lag_periods", pa.int32(), nullable=False),
            pa.field("locked_opened", pa.bool_(), nullable=False),
            pa.field("validation_used_for_selection", pa.bool_(), nullable=False),
            pa.field("unit_output_sha256", pa.string(), nullable=False),
        ]
    )
    return pa.schema(fields)


def _nullable_metrics() -> dict[str, Any]:
    result = {f"train_{name}": None for name in METRIC_FIELDS}
    result.update(
        {
            "train_positive_year_fraction": None,
            "train_positive_years": None,
            "train_worst_year_return_pct": None,
            "train_rolling_1y_median_cagr_pct": None,
            "train_median_rolling_3y_cagr_pct": None,
            "train_rolling_5y_median_cagr_pct": None,
            "train_min_outer_fold_cagr_pct": None,
            "train_turnover": None,
            "train_turnover_instability": None,
            "train_long_days": None,
            "train_short_days": None,
            "train_position_switches": None,
            "train_daily_hit_rate": None,
            "train_monthly_hit_rate": None,
            "train_average_holding_days": None,
            "train_gain_concentration": None,
            "train_skew": None,
            "train_cvar_5_pct": None,
            "train_worst_day_pct": None,
            "train_worst_month_pct": None,
            "performance_by_market_regime_json": None,
            "train_dates": None,
            "train_returns": None,
            "train_positions": None,
            "annual_metrics_json": None,
        }
    )
    return result


def _annual_rows(returns: pd.Series) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year, values in returns.groupby(returns.index.year, sort=True):
        raw = values.dropna().to_numpy(dtype=float)
        if not len(raw):
            continue
        nav = np.cumprod(1.0 + raw)
        total = float(nav[-1] - 1.0)
        std = float(np.std(raw, ddof=0))
        sharpe = float(np.mean(raw) / std * np.sqrt(252.0)) if std > 1e-12 else 0.0
        rows.append(
            {
                "year": int(year),
                "sessions": len(raw),
                "return_pct": total * 100.0,
                "cagr_pct": total * 100.0,
                "sharpe": sharpe,
                "positive": bool(total > 0.0),
            }
        )
    return rows


def _market_regime_states(
    data: PreparedMarketData,
    index: pd.DatetimeIndex,
) -> pd.Series:
    """Frozen non-selection diagnostic based on the mandatory SMA-200 benchmark."""

    signal = benchmark_decisions("symmetric_sma_200", data)
    applied = apply_positions(data.ledger, signal.decisions)
    states = applied.loc[index, "position"].map(
        {1: "spy_above_sma200", -1: "spy_at_or_below_sma200"}
    )
    if states.isna().any():
        raise CandidateRejected("DIAGNOSTIC_REGIME_STATE_MISSING")
    return states.astype(str)


def _regime_performance_rows(
    returns: pd.Series,
    regimes: pd.Series,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    aligned = pd.DataFrame({"return": returns, "regime": regimes}).dropna()
    for label, group in aligned.groupby("regime", sort=True):
        raw = group["return"].to_numpy(dtype=float)
        if not len(raw):
            continue
        nav = np.cumprod(1.0 + raw)
        total = float(nav[-1] - 1.0)
        years = len(raw) / 252.0
        annualized = float(nav[-1] ** (1.0 / years) - 1.0) if years > 0 and nav[-1] > 0 else -1.0
        std = float(np.std(raw, ddof=0))
        running_peak = np.maximum.accumulate(nav)
        drawdown = nav / running_peak - 1.0
        rows.append(
            {
                "regime": str(label),
                "sessions": int(len(raw)),
                "total_return_pct": total * 100.0,
                "annualized_return_pct": annualized * 100.0,
                "sharpe": (float(np.mean(raw) / std * np.sqrt(252.0)) if std > 1e-12 else 0.0),
                "max_drawdown_pct": float(drawdown.min() * 100.0),
                "definition": "mandatory_symmetric_sma_200_executed_next_open_state",
                "selection_binding": False,
            }
        )
    return rows


def _extended_metrics(
    returns: pd.Series,
    positions: pd.Series,
    regimes: pd.Series | None = None,
) -> dict[str, Any]:
    annual = _annual_rows(returns)
    annual_returns = pd.Series(
        {row["year"]: row["return_pct"] / 100.0 for row in annual}, dtype=float
    )
    rolling_3y = (1.0 + annual_returns).rolling(3, min_periods=3).apply(np.prod, raw=True) ** (
        1.0 / 3.0
    ) - 1.0
    rolling_5y = (1.0 + annual_returns).rolling(5, min_periods=5).apply(np.prod, raw=True) ** (
        1.0 / 5.0
    ) - 1.0
    switches = positions.ne(positions.shift(1))
    if len(switches):
        switches.iloc[0] = False
    holding_lengths = []
    if len(positions):
        groups = switches.cumsum()
        holding_lengths = positions.groupby(groups).size().tolist()
    monthly = (1.0 + returns).groupby(returns.index.to_period("M")).prod() - 1.0
    positive_log = np.log1p(annual_returns.clip(lower=-0.999999))
    positive_log = positive_log[positive_log > 0]
    concentration = (
        float(positive_log.max() / positive_log.sum())
        if len(positive_log) and positive_log.sum() > 0
        else 1.0
    )
    years = max(len(returns) / 252.0, 1.0 / 252.0)
    yearly_switches = switches.groupby(switches.index.year).sum().astype(float)
    return {
        "train_positive_year_fraction": float((annual_returns > 0).mean())
        if len(annual_returns)
        else None,
        "train_positive_years": int((annual_returns > 0).sum()),
        "train_worst_year_return_pct": float(annual_returns.min() * 100.0)
        if len(annual_returns)
        else None,
        "train_rolling_1y_median_cagr_pct": float(annual_returns.median() * 100.0)
        if len(annual_returns)
        else None,
        "train_median_rolling_3y_cagr_pct": float(rolling_3y.median() * 100.0)
        if rolling_3y.notna().any()
        else None,
        "train_rolling_5y_median_cagr_pct": float(rolling_5y.median() * 100.0)
        if rolling_5y.notna().any()
        else None,
        "train_min_outer_fold_cagr_pct": float(annual_returns.min() * 100.0)
        if len(annual_returns)
        else None,
        "train_turnover": float(switches.sum() / years),
        "train_turnover_instability": float(
            yearly_switches.std(ddof=0) / max(yearly_switches.mean(), 1.0)
        )
        if len(yearly_switches)
        else 0.0,
        "train_long_days": int((positions == 1).sum()),
        "train_short_days": int((positions == -1).sum()),
        "train_position_switches": int(switches.sum()),
        "train_daily_hit_rate": float((returns > 0).mean()),
        "train_monthly_hit_rate": float((monthly > 0).mean()) if len(monthly) else None,
        "train_average_holding_days": float(np.mean(holding_lengths)) if holding_lengths else None,
        "train_gain_concentration": concentration,
        "train_skew": float(returns.skew()),
        "train_cvar_5_pct": float(returns[returns <= returns.quantile(0.05)].mean() * 100.0),
        "train_worst_day_pct": float(returns.min() * 100.0),
        "train_worst_month_pct": float(monthly.min() * 100.0) if len(monthly) else None,
        "performance_by_market_regime_json": json.dumps(
            (
                _regime_performance_rows(returns, regimes)
                if regimes is not None
                else {
                    "status": "not_calculated",
                    "reason": "REGIME_SERIES_NOT_SUPPLIED",
                }
            ),
            sort_keys=True,
            separators=(",", ":"),
        ),
        "annual_metrics_json": json.dumps(annual, sort_keys=True, separators=(",", ":")),
    }


class Sp500LongShortTrainWorkload(FrozenScientificWorkload):
    workload_name = "sp500_long_short_daily_train"
    workload_family = "sp500_long_short_daily_train"
    dataset_name = "bounded_spy_train_market"
    result_filename = "sp500_long_short_train_results.parquet"
    result_schema = _result_schema()
    seed = SEED
    checkpoint_interval = 8
    phase_name = "train"
    data_start = "1993-01-22"
    data_end = "2010-12-31"
    evaluation_start = "1998-01-01"
    minimum_rows = 1000
    minimum_years = 5
    candidate_limit: int | None = None
    representative_families: tuple[str, ...] = ()

    def describe_contract(self) -> Mapping[str, Any]:
        contract = dict(super().describe_contract())
        scientific = dict(contract["scientific_contract"])
        scientific.update(
            {
                "selection_split": "train_only",
                "validation_role": "not_opened",
                "maximum_date": self.data_end,
                "position_values": [-1, 1],
                "absolute_exposure": 1.0,
                "all_costs_bps": 0,
            }
        )
        contract["scientific_contract"] = scientific
        return contract

    def prepare_shared_inputs(
        self,
        spec: RunSpec,
        output_dir: Path,
    ) -> PreparedInputs:
        """Write a phase-accurate bounded manifest.

        The generic workload advertises a 2020 maximum because it serves
        train/validation examples. This campaign must never imply that
        validation has been opened during smoke, pilot, or train.
        """

        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        artifact_names, snapshot_hash = self._prepare_dataset(root)
        manifest_path = atomic_json(
            root / f"{self.workload_family}_data_manifest.json",
            {
                "schema_version": "1",
                "dataset": self.dataset_name,
                "campaign_phase": self.phase_name,
                "seed": self.seed,
                "min_date": self.data_start,
                "max_date": self.data_end,
                "locked_opened": False,
                "validation_opened": False,
                "validation_used_for_selection": False,
                "artifact_names": list(artifact_names),
                "snapshot_sha256": snapshot_hash,
            },
        )
        return PreparedInputs(
            manifest_path=str(manifest_path),
            manifest_sha256=sha256_file(manifest_path),
            snapshot_hash=snapshot_hash,
            policy_hash=str(spec.policy["policy_hash"]),
            artifact_names=(manifest_path.name, *artifact_names),
        )

    def _prepare_dataset(self, root: Path) -> tuple[tuple[str, ...], str]:
        manifest = prepare_market_snapshot(
            root,
            _package(),
            start=self.data_start,
            end=self.data_end,
            split="train",
        )
        return (
            "market_data_manifest.json",
            "raw_manifest.jsonl",
            "spy_ledger.parquet",
            "causal_series.parquet",
        ), str(manifest["snapshot_sha256"])

    def _load_dataset(self, root: Path) -> PreparedMarketData:
        data = load_market_snapshot(root)
        if data.split != "train" or data.ledger.index.max() > pd.Timestamp(self.data_end):
            raise RuntimeError("TRAIN_DATA_BOUNDARY_MISMATCH")
        return data

    def _unit_definitions(self) -> Sequence[tuple[str, Mapping[str, Any], float]]:
        package = _package()
        definitions: list[tuple[str, Mapping[str, Any], float]] = []
        candidates = list(package.candidates)
        if self.representative_families:
            chosen = []
            for family in self.representative_families:
                family_rows = [row for row in candidates if row["family"] == family]
                if not family_rows:
                    raise AssertionError(f"missing representative family {family}")
                chosen.append(
                    sorted(
                        family_rows,
                        key=lambda row: (-int(row["priority_score"]), str(row["strategy_id"])),
                    )[0]
                )
            candidates = chosen
        if self.candidate_limit is not None:
            candidates = candidates[: self.candidate_limit]
        for candidate in candidates:
            estimate = 0.5 + float(candidate["complexity_score"]) * 0.25
            definitions.append((str(candidate["strategy_id"]), dict(candidate), estimate))
        for benchmark in BENCHMARK_IDS:
            definitions.append(
                (
                    f"BENCHMARK::{benchmark}",
                    {"benchmark_id": benchmark, "unit_type": "benchmark"},
                    0.2,
                )
            )
        if self.phase_name == "train" and len(definitions) != 173:
            raise AssertionError("campaign must expose 168 candidates and five benchmarks")
        return tuple(definitions)

    def _base_row(
        self,
        unit_key: str,
        parameters: Mapping[str, Any],
        attempt_id: str,
    ) -> dict[str, Any]:
        benchmark = parameters.get("unit_type") == "benchmark"
        return {
            "unit_key": unit_key,
            "source_attempt_id": attempt_id,
            "unit_type": "benchmark" if benchmark else "candidate",
            "strategy_id": str(
                parameters.get("benchmark_id", parameters.get("strategy_id", unit_key))
            ),
            "family": "benchmark" if benchmark else str(parameters["family"]),
            "variant_label": str(
                parameters.get("benchmark_id", parameters.get("variant_label", ""))
            ),
            "canonical_hash": (
                canonical_json_hash(parameters) if benchmark else str(parameters["canonical_hash"])
            ),
            "status": "evaluated",
            "rejection_reason": None,
            "evidence_track": "benchmark" if benchmark else str(parameters["evidence_track"]),
            "complexity_score": 0 if benchmark else int(parameters["complexity_score"]),
            "first_evaluable_date": None,
            "missing_fraction": None,
            **_nullable_metrics(),
            "selected_on": "train_only",
            "causal_lag_periods": 1,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }

    def _evaluate(
        self,
        data: PreparedMarketData,
        unit_key: str,
        parameters: Mapping[str, Any],
        attempt_id: str,
    ) -> tuple[dict[str, Any], tuple[MetricInputRecord, ...]]:
        row = self._base_row(unit_key, parameters, attempt_id)
        try:
            signal = (
                benchmark_decisions(str(parameters["benchmark_id"]), data)
                if parameters.get("unit_type") == "benchmark"
                else candidate_decisions(
                    parameters,
                    data,
                    candidate_lookup=_package().candidate_by_id(),
                )
            )
            if signal.first_evaluable_date is None:
                raise CandidateRejected("NO_EVALUABLE_SESSION")
            if signal.missing_fraction > 0.02 + 1e-12:
                raise CandidateRejected("DATA_INELIGIBLE:CAUSAL_COVERAGE_LT_98_PERCENT")
            applied = apply_positions(data.ledger, signal.decisions)
            first_decision = pd.Timestamp(signal.first_evaluable_date)
            later = data.ledger.index[data.ledger.index > first_decision]
            if not len(later):
                raise CandidateRejected("NO_POST_DECISION_RETURN")
            evaluation = applied.loc[later]
            evaluation = evaluation.loc[
                (evaluation.index >= pd.Timestamp(self.evaluation_start))
                & (evaluation.index <= pd.Timestamp(self.data_end))
            ]
            returns = evaluation["strategy_return"].dropna().astype(float)
            positions = evaluation.loc[returns.index, "position"].astype(np.int8)
            if (
                len(returns) < self.minimum_rows
                or len(set(returns.index.year)) < self.minimum_years
            ):
                raise CandidateRejected("DATA_INELIGIBLE:MINIMUM_TRAIN_COVERAGE")
            if not positions.isin((-1, 1)).all():
                raise CandidateRejected("TECHNICAL_FAILURE_POSITION")
            record = primary_metric_record(
                unit_key,
                "train",
                returns.to_numpy(dtype=float),
                periods_per_year=252,
            )
            row.update({f"train_{key}": record.reported.get(key) for key in METRIC_FIELDS})
            regimes = _market_regime_states(data, returns.index)
            row.update(_extended_metrics(returns, positions, regimes))
            row.update(
                {
                    "first_evaluable_date": signal.first_evaluable_date,
                    "missing_fraction": float(signal.missing_fraction),
                    "train_dates": [date.date().isoformat() for date in returns.index],
                    "train_returns": [float(value) for value in returns],
                    "train_positions": [int(value) for value in positions],
                }
            )
            records: tuple[MetricInputRecord, ...] = (record,)
        except CandidateRejected as exc:
            row["status"] = "rejected"
            row["rejection_reason"] = str(exc)
            records = ()
        row["unit_output_sha256"] = canonical_sha256(
            {key: value for key, value in row.items() if key != "source_attempt_id"}
        )
        return row, records

    def _access_ranges(
        self,
        data: PreparedMarketData,
    ) -> Mapping[str, tuple[Any, Any, int]]:
        dates = data.ledger.index
        return {"train": (dates.min().date(), dates.max().date(), len(dates))}

    def smoke(self, spec: RunSpec, prepared: Any) -> SmokeResult:
        del spec
        data = self._load_dataset(self._prepared_root(prepared))
        definitions = self._unit_definitions()
        selected = (
            list(definitions)
            if len(definitions) <= 7
            else [definitions[0], definitions[3], *definitions[-5:]]
        )
        selected = list({row[0]: row for row in selected}.values())
        first = [self._evaluate(data, key, payload, "smoke-a")[0] for key, payload, _ in selected]
        second = [self._evaluate(data, key, payload, "smoke-b")[0] for key, payload, _ in selected]
        first_hashes = [row["unit_output_sha256"] for row in first]
        second_hashes = [row["unit_output_sha256"] for row in second]
        reasons = []
        if first_hashes != second_hashes:
            reasons.append("NONDETERMINISTIC_SMOKE")
        if any(row["locked_opened"] or row["validation_used_for_selection"] for row in first):
            reasons.append("BOUNDARY_BREACH")
        by_id = {row["strategy_id"]: row for row in first}
        long_row = by_id.get("always_long")
        buy_row = by_id.get("buy_and_hold_spy_total_return")
        short_row = by_id.get("always_short")
        if not long_row or not buy_row or long_row["train_returns"] != buy_row["train_returns"]:
            reasons.append("BUY_HOLD_ALWAYS_LONG_MISMATCH")
        if (
            long_row
            and short_row
            and not np.allclose(
                np.asarray(long_row["train_returns"]),
                -np.asarray(short_row["train_returns"]),
                rtol=0,
                atol=0,
            )
        ):
            reasons.append("ALWAYS_SHORT_RECONCILIATION_MISMATCH")
        return SmokeResult(
            passed=not reasons,
            output_sha256=canonical_json_hash(first_hashes),
            reason_codes=tuple(reasons),
        )

    def pilot(self, spec: RunSpec, prepared: Any) -> PilotResult:
        # The universal planner consumes these measured estimates and performs
        # weighted LPT scheduling. Static/fitted unit cost is preserved in the
        # work-unit manifest; no candidate is dropped by the scheduler.
        result = super().pilot(spec, prepared)
        return result

    def merge_group(self, inputs: Sequence[Path], output_dir: Path) -> Path:
        """Merge partial groups cheaply; reduce only at exact full coverage."""

        rows_by_key: dict[str, dict[str, Any]] = {}
        for source in sorted(Path(path) for path in inputs):
            candidates = (
                (source,)
                if source.is_file() and source.name == self.result_filename
                else tuple(source.rglob(self.result_filename))
            )
            if len(candidates) != 1:
                raise ValueError(f"expected one {self.result_filename} in {source}")
            for row in pq.read_table(candidates[0], schema=self.result_schema).to_pylist():
                key = str(row["unit_key"])
                previous = rows_by_key.get(key)
                if (
                    previous is not None
                    and previous["unit_output_sha256"] != row["unit_output_sha256"]
                ):
                    raise ValueError(f"conflicting result for {key}")
                rows_by_key[key] = row
        root = Path(output_dir)
        output = self._write_results(tuple(rows_by_key.values()), root / self.result_filename)
        if len(rows_by_key) == len(self._unit_definitions()):
            self._write_reduction(tuple(rows_by_key.values()), root)
        return output

    def _write_reduction(self, rows: Sequence[Mapping[str, Any]], root: Path) -> None:
        ordered = sorted(rows, key=lambda row: str(row["unit_key"]))
        expected = [key for key, _, _ in self._unit_definitions()]
        completed = [str(row["unit_key"]) for row in ordered if row["status"] == "evaluated"]
        rejected = [str(row["unit_key"]) for row in ordered if row["status"] == "rejected"]
        validate_exact_coverage(expected, completed, rejected)
        root.mkdir(parents=True, exist_ok=True)

        if self.phase_name != "train":
            self._write_diagnostic_reduction(ordered, root)
            return

        candidates = [row for row in ordered if row["unit_type"] == "candidate"]
        benchmarks = [row for row in ordered if row["unit_type"] == "benchmark"]
        candidate_frame = pd.DataFrame(candidates).drop(
            columns=["train_dates", "train_returns", "train_positions"]
        )
        pd.DataFrame(
            [
                {
                    "unit_key": row["unit_key"],
                    "status": row["status"],
                    "reason": row["rejection_reason"],
                    "family": row["family"],
                }
                for row in ordered
            ]
        ).to_csv(root / "eligibility_and_rejections.csv", index=False)

        metadata_path = root / "candidate_metadata.jsonl"
        metadata_path.write_text(
            "".join(
                json.dumps(
                    {
                        "strategy_id": row["strategy_id"],
                        "canonical_hash": row["canonical_hash"],
                        "family": row["family"],
                        "variant_label": row["variant_label"],
                        "status": row["status"],
                    },
                    sort_keys=True,
                )
                + "\n"
                for row in ordered
            ),
            encoding="utf-8",
        )
        daily_rows = []
        annual_rows = []
        for row in ordered:
            if row["status"] != "evaluated":
                continue
            for date, value, position in zip(
                row["train_dates"], row["train_returns"], row["train_positions"], strict=True
            ):
                daily_rows.append(
                    {
                        "unit_key": row["unit_key"],
                        "date": date,
                        "return": value,
                        "position": position,
                    }
                )
            for annual in json.loads(row["annual_metrics_json"]):
                annual_rows.append({"unit_key": row["unit_key"], **annual})
        pq.write_table(pa.Table.from_pylist(daily_rows), root / "train_daily_returns.parquet")
        annual_frame = pd.DataFrame(annual_rows)
        fold_frame = annual_frame.copy()
        if len(fold_frame):
            fold_frame["outer_fold_id"] = fold_frame["year"].map(
                lambda year: f"calendar_year_{int(year)}"
            )
            fold_frame["outer_train_start"] = "1993-01-22"
            fold_frame["outer_train_end"] = fold_frame["year"].map(
                lambda year: f"{int(year) - 1}-12-31"
            )
            fold_frame["outer_test_start"] = fold_frame["year"].map(
                lambda year: f"{int(year)}-01-01"
            )
            fold_frame["outer_test_end"] = fold_frame["year"].map(lambda year: f"{int(year)}-12-31")
            fold_frame["embargo_sessions"] = 1
            fold_frame["fit_mode"] = "static_rule_no_fit"
            fold_frame["out_of_fold"] = True
            fold_frame["validation_used"] = False
        fold_frame.to_csv(root / "train_fold_metrics.csv", index=False)

        daily_frame = pd.DataFrame(daily_rows)
        candidate_keys = set(
            candidate_frame.loc[candidate_frame["status"] == "evaluated", "unit_key"]
        )
        benchmark_keys = {
            str(row["unit_key"]) for row in benchmarks if row["status"] == "evaluated"
        }
        proxy_families = {
            str(candidate["family"])
            for candidate in _package().candidates
            if "DS071" in candidate["required_datasets"]
        }
        ranking, multiple_testing = frozen_train_ranking(
            candidate_frame,
            annual_frame,
            daily_frame.loc[daily_frame["unit_key"].isin(candidate_keys)],
            daily_frame.loc[daily_frame["unit_key"].isin(benchmark_keys)],
            proxy_families=proxy_families,
            seed=SEED,
        )
        ranking.to_csv(root / "train_ranking.csv", index=False)
        candidate_frame = candidate_frame.merge(
            ranking.drop(
                columns=[
                    column
                    for column in candidate_frame.columns
                    if column in ranking.columns and column != "unit_key"
                ]
            ),
            on="unit_key",
            how="left",
            validate="one_to_one",
        )
        candidate_frame.to_csv(root / "candidate_metrics.csv", index=False)
        (root / "multiple_testing.json").write_text(
            json.dumps(multiple_testing, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

        pareto_fields = [
            "train_cagr_pct",
            "train_calmar",
            "train_max_drawdown_pct",
            "train_worst_year_return_pct",
            "train_min_outer_fold_cagr_pct",
        ]
        eligible = ranking.loc[ranking["hard_train_eligible"]].copy()
        pareto = []
        for index, row in eligible.iterrows():
            values = row[pareto_fields].astype(float)
            others = eligible.drop(index=index)[pareto_fields].astype(float)
            dominated = bool(((others >= values).all(axis=1) & (others > values).any(axis=1)).any())
            if not dominated:
                pareto.append(row)
        pareto_frame = pd.DataFrame(pareto)
        pareto_frame.to_csv(root / "pareto_frontier.csv", index=False)

        finalists = []
        for family, group in ranking.loc[ranking["eligible_for_freeze"]].groupby(
            "family", sort=True
        ):
            finalists.extend(group.head(2).to_dict("records"))
        diagnostic_representatives = []
        for family, group in ranking.loc[ranking["hard_train_eligible"]].groupby(
            "family", sort=True
        ):
            if not any(str(row["family"]) == str(family) for row in finalists):
                diagnostic = group.head(1).to_dict("records")
                if diagnostic:
                    diagnostic[0]["diagnostic_family_representative"] = True
                    diagnostic_representatives.extend(diagnostic)
        finalists = sorted(
            finalists,
            key=lambda row: (-float(row["train_selection_score"]), str(row["unit_key"])),
        )[:30]
        diagnostic_representatives = sorted(
            diagnostic_representatives,
            key=lambda row: (-float(row["train_selection_score"]), str(row["unit_key"])),
        )[:30]

        manifest_path = root.parent / "market_data_manifest.json"
        if not manifest_path.is_file():
            manifest_path = self._prepared_root() / "market_data_manifest.json"
        dependency_lock = _repo_root() / "requirements" / "github-performance.lock"
        campaign_root = _repo_root() / "campaigns" / "sp500_long_short_daily"
        acceptance_gates = campaign_root / "research_input" / "acceptance_gates.md"
        selection_protocol = campaign_root / "research_input" / "train_selection_protocol.md"
        source_audit = campaign_root / "official_inputs" / "official_source_audit.json"
        candidate_lookup = _package().candidate_by_id()
        ranking_by_id = {str(row["strategy_id"]): row for row in ranking.to_dict("records")}
        freeze = {
            "schema_version": "1",
            "campaign_id": "sp500_long_short_daily_zero_cost_v1",
            "selection_closed": True,
            "validation_opened": False,
            "locked_opened": False,
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "candidate_pack_sha256": canonical_json_hash(list(_package().candidates)),
            "code_sha": os.environ.get("GITHUB_SHA", "LOCAL_TEST_ONLY"),
            "data_manifest_sha256": sha256_file(manifest_path),
            "dependency_lock_sha256": sha256_file(dependency_lock),
            "multiple_testing_sha256": sha256_file(root / "multiple_testing.json"),
            "train_ranking_sha256": sha256_file(root / "train_ranking.csv"),
            "pareto_frontier_sha256": sha256_file(root / "pareto_frontier.csv"),
            "acceptance_gates_sha256": sha256_file(acceptance_gates),
            "train_selection_protocol_sha256": sha256_file(selection_protocol),
            "official_source_audit_sha256": sha256_file(source_audit),
            "selection_scope": "train_only_outer_oof_static_rules_1998_2010",
            "candidate_count": 168,
            "benchmark_count": 5,
            "costs": {
                "commission_bps": 0,
                "spread_bps": 0,
                "slippage_bps": 0,
                "market_impact_bps": 0,
                "borrow_bps": 0,
                "financing_bps": 0,
            },
            "position_contract": {
                "allowed_values": [-1, 1],
                "always_invested": True,
                "leverage": 1.0,
                "decision": "after_close_t",
                "execution": "next_tradable_open_t_plus_1",
            },
            "finalists": [
                {
                    "order": order,
                    "strategy_id": row["strategy_id"],
                    "canonical_hash": row["canonical_hash"],
                    "family": row["family"],
                    "train_selection_score": row["train_selection_score"],
                    "candidate_rules": candidate_lookup[str(row["strategy_id"])],
                    "train_metrics": {
                        "cagr_pct": row["train_cagr_pct"],
                        "sharpe": row["train_sharpe"],
                        "calmar": row["train_calmar"],
                        "max_drawdown_pct": row["train_max_drawdown_pct"],
                        "positive_year_fraction": row["train_positive_year_fraction"],
                        "median_rolling_3y_cagr_pct": row["train_median_rolling_3y_cagr_pct"],
                        "worst_year_return_pct": row["train_worst_year_return_pct"],
                        "min_outer_fold_cagr_pct": row["train_min_outer_fold_cagr_pct"],
                        "sortino": row["train_sortino"],
                        "turnover": row["train_turnover"],
                    },
                    "annual_oof_metrics": annual_frame.loc[
                        annual_frame["unit_key"] == str(row["unit_key"])
                    ]
                    .sort_values("year", kind="mergesort")
                    .to_dict("records"),
                    "selection_gate_results": {
                        key: bool(value)
                        for key, value in ranking_by_id[str(row["strategy_id"])].items()
                        if str(key).startswith("gate_")
                    },
                    "multiple_testing": {
                        "deflated_sharpe_probability": row["deflated_sharpe_probability"],
                        "spa_pvalue": row["spa_pvalue"],
                        "fdr_qvalue": row.get("fdr_qvalue"),
                        "pbo": row["pbo"],
                    },
                    "diagnostic_only": False,
                    "eligible_for_validation": True,
                }
                for order, row in enumerate(finalists, start=1)
            ],
            "diagnostic_representatives": [
                {
                    "order": order,
                    "strategy_id": row["strategy_id"],
                    "canonical_hash": row["canonical_hash"],
                    "family": row["family"],
                    "train_selection_score": row["train_selection_score"],
                    "candidate_rules": candidate_lookup[str(row["strategy_id"])],
                    "train_metrics": {
                        "cagr_pct": row["train_cagr_pct"],
                        "sharpe": row["train_sharpe"],
                        "calmar": row["train_calmar"],
                        "max_drawdown_pct": row["train_max_drawdown_pct"],
                        "positive_year_fraction": row["train_positive_year_fraction"],
                        "median_rolling_3y_cagr_pct": row[
                            "train_median_rolling_3y_cagr_pct"
                        ],
                        "worst_year_return_pct": row["train_worst_year_return_pct"],
                        "min_outer_fold_cagr_pct": row["train_min_outer_fold_cagr_pct"],
                        "sortino": row["train_sortino"],
                        "turnover": row["train_turnover"],
                    },
                    "annual_oof_metrics": annual_frame.loc[
                        annual_frame["unit_key"] == str(row["unit_key"])
                    ]
                    .sort_values("year", kind="mergesort")
                    .to_dict("records"),
                    "selection_gate_results": {
                        key: bool(value)
                        for key, value in ranking_by_id[str(row["strategy_id"])].items()
                        if str(key).startswith("gate_")
                    },
                    "multiple_testing": {
                        "deflated_sharpe_probability": row[
                            "deflated_sharpe_probability"
                        ],
                        "spa_pvalue": row["spa_pvalue"],
                        "fdr_qvalue": row.get("fdr_qvalue"),
                        "pbo": row["pbo"],
                    },
                    "diagnostic_only": True,
                    "eligible_for_validation": False,
                    "ineligibility_reason": "MULTIPLE_TESTING_GATE_NOT_PASSED",
                }
                for order, row in enumerate(diagnostic_representatives, start=1)
            ],
        }
        freeze["freeze_sha256"] = canonical_json_hash(freeze)
        (root / "train_selection_freeze.json").write_text(
            json.dumps(freeze, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

        summary = {
            "schema_version": "1",
            "campaign_id": "sp500_long_short_daily_zero_cost_v1",
            "result_status": (
                "TRAIN_SELECTION_FROZEN_VALIDATION_NOT_OPENED" if finalists else "NEGATIVE_RESULT"
            ),
            "expected_candidates": 168,
            "expected_benchmarks": 5,
            "evaluated_candidates": sum(row["status"] == "evaluated" for row in candidates),
            "rejected_candidates": sum(row["status"] == "rejected" for row in candidates),
            "evaluated_benchmarks": sum(row["status"] == "evaluated" for row in benchmarks),
            "hard_train_eligible_candidates": int(ranking["hard_train_eligible"].sum())
            if len(ranking)
            else 0,
            "multiple_testing_eligible_candidates": int(ranking["eligible_for_freeze"].sum())
            if len(ranking)
            else 0,
            "frozen_finalists": len(finalists),
            "diagnostic_representatives": len(diagnostic_representatives),
            "locked_opened": False,
            "validation_opened": False,
            "validation_used_for_selection": False,
            "train_end": "2010-12-31",
            "candidate_pack_sha256": canonical_json_hash(list(_package().candidates)),
        }
        summary["summary_sha256"] = canonical_json_hash(summary)
        (root / "sp500_long_short_daily_train_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (root / "causality_audit.json").write_text(
            json.dumps(
                {
                    "decision": "after_close_t",
                    "execution": "next_open_t_plus_1",
                    "causal_lag_periods": 1,
                    "locked_opened": False,
                    "validation_opened": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self._write_required_train_deliverables(
            ordered,
            candidate_frame,
            annual_frame,
            ranking,
            summary,
            root,
        )

    def _write_required_train_deliverables(
        self,
        rows: Sequence[Mapping[str, Any]],
        candidate_frame: pd.DataFrame,
        annual_frame: pd.DataFrame,
        ranking: pd.DataFrame,
        summary: Mapping[str, Any],
        root: Path,
    ) -> None:
        """Write the frozen package's reader-facing train contract.

        These are aliases and diagnostics derived from the exact merged rows.
        They do not alter selection, metrics, dates, or candidate decisions.
        """

        compact_rows = pd.DataFrame(rows).drop(
            columns=["train_dates", "train_returns", "train_positions"],
            errors="ignore",
        )
        compact_rows.to_csv(root / "candidate_and_benchmark_metrics.csv", index=False)
        annual_frame.to_csv(root / "annual_returns.csv", index=False)
        shutil.copy2(root / "train_fold_metrics.csv", root / "fold_metrics.csv")

        rolling_columns = [
            "unit_key",
            "strategy_id",
            "family",
            "status",
            "train_rolling_1y_median_cagr_pct",
            "train_median_rolling_3y_cagr_pct",
            "train_rolling_5y_median_cagr_pct",
        ]
        compact_rows.reindex(columns=rolling_columns).to_csv(
            root / "rolling_metrics.csv", index=False
        )
        regime_rows = []
        for row in rows:
            if row["status"] != "evaluated":
                continue
            decoded = json.loads(row["performance_by_market_regime_json"])
            if not isinstance(decoded, list):
                raise RuntimeError(f"REGIME_DIAGNOSTIC_MISSING:{row['unit_key']}")
            for regime in decoded:
                regime_rows.append(
                    {
                        "unit_key": row["unit_key"],
                        "strategy_id": row["strategy_id"],
                        "family": row["family"],
                        "status": "calculated",
                        **regime,
                    }
                )
        pd.DataFrame(regime_rows).to_csv(root / "regime_metrics.csv", index=False)

        multiple_source = root / "multiple_testing.json"
        shutil.copy2(multiple_source, root / "multiple_testing_results.json")

        prepared_root = self._prepared_root()
        for name in ("raw_manifest.jsonl", "market_data_manifest.json"):
            source = prepared_root / name
            if not source.is_file():
                raise RuntimeError(f"REQUIRED_PREPARED_EVIDENCE_MISSING:{name}")
            shutil.copy2(source, root / name)
        raw_rows = [
            json.loads(line)
            for line in (root / "raw_manifest.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        lineage_path = root / "data_lineage.jsonl"
        lineage_path.write_text(
            "".join(
                json.dumps(
                    {
                        "dataset_id": row.get("dataset_id"),
                        "source": row.get("url_template"),
                        "sha256": row.get("sha256"),
                        "minimum_date": row.get("minimum_date"),
                        "maximum_date": row.get("maximum_date"),
                        "status": row.get("status"),
                        "locked_opened": False,
                    },
                    sort_keys=True,
                )
                + "\n"
                for row in raw_rows
            ),
            encoding="utf-8",
        )

        implementation = (
            _repo_root() / "campaigns" / "sp500_long_short_daily" / "implementation_mapping.md"
        )
        shutil.copy2(implementation, root / "implementation_mapping.md")
        official_source_audit = (
            _repo_root()
            / "campaigns"
            / "sp500_long_short_daily"
            / "official_inputs"
            / "official_source_audit.json"
        )
        shutil.copy2(official_source_audit, root / "official_source_audit.json")
        dependency_lock = _repo_root() / "requirements" / "github-performance.lock"
        (root / "environment_lock.txt").write_text(
            "\n".join(
                (
                    "python=3.12",
                    "runner=ubuntu-24.04",
                    f"dependency_lock_sha256={sha256_file(dependency_lock)}",
                    f"code_sha={os.environ.get('GITHUB_SHA', 'LOCAL_TEST_ONLY')}",
                    "github_actions_only=true",
                    "locked_opened=false",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        scheduler = {
            "schema_version": "1",
            "source": "aurora_universal_measured_planner",
            "authoritative_plan_files": [
                "performance_plan.json",
                "execution_plan.json",
                "balanced_shard_plan.json",
                "work_unit_manifest.json",
            ],
            "expected_units": len(rows),
            "unit_cost_policy": "frozen_complexity_weighted_lpt",
            "maximum_concurrent_standard_jobs": 360,
            "locked_opened": False,
        }
        atomic_json(root / "scheduler_plan.json", scheduler)

        near_misses = ranking.loc[~ranking["eligible_for_freeze"]].head(30)
        near_misses.to_csv(root / "near_misses.csv", index=False)
        status = str(summary["result_status"])
        (root / "RESULT_STATUS.md").write_text(
            "\n".join(
                (
                    f"# {status}",
                    "",
                    f"- Candidates evaluated: {summary['evaluated_candidates']}",
                    f"- Candidates rejected technically/data: {summary['rejected_candidates']}",
                    f"- Frozen finalists: {summary['frozen_finalists']}",
                    "- Validation opened: false",
                    "- Locked observations opened: false",
                    "- Latest train observation: 2010-12-31",
                )
            )
            + "\n",
            encoding="utf-8",
        )

        required = (
            "RESULT_STATUS.md",
            "train_selection_freeze.json",
            "candidate_and_benchmark_metrics.csv",
            "train_daily_returns.parquet",
            "annual_returns.csv",
            "rolling_metrics.csv",
            "regime_metrics.csv",
            "fold_metrics.csv",
            "eligibility_and_rejections.csv",
            "multiple_testing_results.json",
            "causality_audit.json",
            "data_lineage.jsonl",
            "raw_manifest.jsonl",
            "scheduler_plan.json",
            "environment_lock.txt",
            "implementation_mapping.md",
            "official_source_audit.json",
        )
        missing = [name for name in required if not (root / name).is_file()]
        if missing:
            raise RuntimeError(f"FINAL_DELIVERABLES_MISSING:{','.join(missing)}")
        manifest = {
            "schema_version": "1",
            "campaign_id": "sp500_long_short_daily_zero_cost_v1",
            "result_status": status,
            "train_end": "2010-12-31",
            "validation_opened": False,
            "locked_start": "2021-01-01",
            "locked_opened": False,
            "files": {name: sha256_file(root / name) for name in sorted(required)},
        }
        manifest["manifest_sha256"] = canonical_json_hash(manifest)
        atomic_json(root / "final_manifest.json", manifest)

    def _write_diagnostic_reduction(
        self,
        rows: Sequence[Mapping[str, Any]],
        root: Path,
    ) -> None:
        eligibility = pd.DataFrame(
            [
                {
                    "unit_key": row["unit_key"],
                    "unit_type": row["unit_type"],
                    "status": row["status"],
                    "reason": row["rejection_reason"],
                    "family": row["family"],
                }
                for row in rows
            ]
        )
        eligibility.to_csv(root / "eligibility_and_rejections.csv", index=False)
        summary = {
            "schema_version": "1",
            "campaign_id": "sp500_long_short_daily_zero_cost_v1",
            "campaign_phase": self.phase_name,
            "result_status": f"{self.phase_name.upper()}_COMPLETE_TRAIN_NOT_OPENED",
            "expected_units": len(self._unit_definitions()),
            "evaluated_units": int((eligibility["status"] == "evaluated").sum()),
            "rejected_units": int((eligibility["status"] == "rejected").sum()),
            "minimum_date": self.data_start,
            "maximum_date": self.data_end,
            "locked_opened": False,
            "validation_opened": False,
            "validation_used_for_selection": False,
        }
        summary["summary_sha256"] = canonical_json_hash(summary)
        (root / f"sp500_long_short_daily_{self.phase_name}_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class Sp500LongShortSmokeWorkload(Sp500LongShortTrainWorkload):
    workload_name = "sp500_long_short_daily_smoke"
    workload_family = "sp500_long_short_daily_smoke"
    dataset_name = "bounded_spy_smoke_market"
    result_filename = "sp500_long_short_smoke_results.parquet"
    phase_name = "smoke"
    data_start = "2005-10-01"
    data_end = "2009-09-30"
    evaluation_start = "2006-10-01"
    minimum_rows = 200
    minimum_years = 1
    candidate_limit = 2


class Sp500LongShortPilotWorkload(Sp500LongShortTrainWorkload):
    workload_name = "sp500_long_short_daily_pilot"
    workload_family = "sp500_long_short_daily_pilot"
    dataset_name = "bounded_spy_pilot_market"
    result_filename = "sp500_long_short_pilot_results.parquet"
    phase_name = "pilot"
    representative_families = (
        "price_trend_sma",
        "time_series_momentum",
        "short_horizon_reversal",
        "trend_ensemble",
        "dual_ma_cross",
        "price_breakout",
        "volume_conditioned_reversal",
        "realized_volatility_state",
        "overnight_futures_proxy",
        "volatility_conditioned_trend",
        "vix_term_structure",
        "variance_risk_premium_proxy",
        "vix_extreme_reversal",
        "vix_level_change",
        "yield_curve_regime",
        "credit_spread_regime",
        "financial_conditions_regime",
        "calendar_seasonality",
    )


SMOKE_WORKLOAD = Sp500LongShortSmokeWorkload()
PILOT_WORKLOAD = Sp500LongShortPilotWorkload()
TRAIN_WORKLOAD = Sp500LongShortTrainWorkload()
