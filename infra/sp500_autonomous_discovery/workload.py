"""Aurora workload for autonomous train-only SPY discovery batches."""

from __future__ import annotations

import json
import os
import time
import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from aurora.infra.github_performance.contracts import (
    PreparedInputs,
    RunSpec,
    SmokeResult,
    canonical_sha256,
)
from aurora.infra.github_performance.metric_verifier import MetricInputRecord
from aurora.infra.github_performance.workloads.common import primary_metric_record
from aurora.infra.sp500_long_short_daily.contracts import CampaignPackage
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
from aurora.infra.sp500_long_short_daily.workload import (
    METRIC_FIELDS,
    Sp500LongShortTrainWorkload,
    _result_schema,
    _extended_metrics,
    _market_regime_states,
)

from .contracts import LOCKED_START, TRAIN_END
from .dedupe import build_dedupe_map
from .registry import (
    base_package,
    generate_candidates,
    read_batch_registry,
    get_previous_trial_count,
    repo_root,
    write_batch_registry,
)
from .statistics import evaluate_batch
from .scheduling import assign_by_cost, cost_score


BENCHMARK_IDS = (
    "buy_and_hold_spy_total_return",
    "always_long",
    "always_short",
    "symmetric_sma_200",
    "symmetric_momentum_12m",
)


def _batch_id() -> int:
    value = os.environ.get("AURORA_AUTONOMOUS_BATCH_ID", "0").strip()
    if not value.isdigit():
        raise ValueError("AURORA_AUTONOMOUS_BATCH_ID_MUST_BE_INTEGER")
    return int(value)


def _candidate_count(default: int) -> int:
    value = os.environ.get("AURORA_AUTONOMOUS_CANDIDATE_COUNT", str(default)).strip()
    if not value.isdigit() or int(value) < 1:
        raise ValueError("AURORA_AUTONOMOUS_CANDIDATE_COUNT_MUST_BE_POSITIVE")
    return int(value)


def _light_package(candidates: Sequence[Mapping[str, Any]]) -> CampaignPackage:
    package = base_package()
    return CampaignPackage(
        root=package.root,
        zip_path=package.zip_path,
        spec=package.spec,
        candidates=tuple(candidates),
        features=package.features,
        datasets=package.datasets,
        research=package.research,
    )


class AutonomousDiscoveryWorkload(Sp500LongShortTrainWorkload):
    """Evaluate one pre-registered batch without accessing validation or locked data."""

    workload_name = "sp500_autonomous_discovery_train"
    workload_family = "sp500_autonomous_discovery"
    dataset_name = "bounded_spy_autonomous_train_market"
    result_filename = "sp500_autonomous_train_results.parquet"
    phase_name = "train"
    data_start = "1993-01-22"
    data_end = TRAIN_END
    evaluation_start = "1998-01-01"
    minimum_rows = 2500
    minimum_years = 10
    default_candidate_count = 96
    result_schema = _result_schema().append(pa.field("seconds_total", pa.float64()))
    result_schema = result_schema.append(pa.field("seconds_signal", pa.float64()))
    result_schema = result_schema.append(pa.field("seconds_simulation", pa.float64()))

    def describe_contract(self) -> Mapping[str, Any]:
        payload = dict(super().describe_contract())
        payload["name"] = self.workload_name
        payload["scientific_contract"] = {
            **dict(payload["scientific_contract"]),
            "oof_method": "chronological_calendar_year_outer_folds_static_rules",
            "global_trial_count_includes_previous_campaigns": 312,
            "validation_opened": False,
            "locked_opened": False,
        }
        return payload

    def _registry_path(self, root: Path) -> Path:
        return Path(root).resolve() / "candidate_registry.jsonl"

    def _prepare_dataset(self, root: Path) -> tuple[tuple[str, ...], str]:
        batch_id = _batch_id()
        count = _candidate_count(self.default_candidate_count)
        candidates = generate_candidates(batch_id, count=count)
        write_batch_registry(
            root,
            batch_id=batch_id,
            candidates=candidates,
            previous_trial_count=get_previous_trial_count(),
        )
        with (Path(root) / "dedupe_map.csv").open("w", newline="", encoding="utf-8") as handle:
            dedupe_rows = build_dedupe_map(candidates)
            writer = csv.DictWriter(handle, fieldnames=["strategy_id", "canonical_hash", "canonical_strategy_id", "deduped"])
            writer.writeheader()
            writer.writerows(dedupe_rows)
        priced = [
            {
                **candidate,
                "cost_score": cost_score(
                    family_timeout_rate=float(candidate.get("complexity_score", 1)) / 10.0,
                    concept_timeout_rate=float(candidate.get("complexity_score", 1)) / 20.0,
                ),
            }
            for candidate in candidates
        ]
        with (Path(root) / "job_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
            manifest_rows = assign_by_cost(priced, max(1, min(360, len(priced))))
            writer = csv.DictWriter(handle, fieldnames=["job_id", "strategy_id", "canonical_hash", "cost_score", "estimated_cost_bucket"])
            writer.writeheader()
            writer.writerows(manifest_rows)
        package = _light_package(candidates)
        manifest = prepare_market_snapshot(
            root,
            package,
            start=self.data_start,
            end=self.data_end,
            split="train",
        )
        # These files are immutable provenance inputs, not performance results.
        registry_root = repo_root() / "campaigns" / "sp500_long_short_daily" / "research_input"
        for source_name, target_name in (
            ("research_library.csv", "research_registry_source.csv"),
            ("feature_catalog.csv", "feature_registry_source.csv"),
            ("data_source_inventory.csv", "dataset_registry_source.csv"),
        ):
            target = Path(root) / target_name
            target.write_bytes((registry_root / source_name).read_bytes())
        return (
            "market_data_manifest.json",
            "raw_manifest.jsonl",
            "spy_ledger.parquet",
            "causal_series.parquet",
            "candidate_registry.jsonl",
            "candidate_registry_manifest.json",
            "dedupe_map.csv",
            "job_manifest.csv",
            "research_registry.csv",
            "feature_registry.csv",
            "dataset_registry.csv",
            "research_registry_source.csv",
            "feature_registry_source.csv",
            "dataset_registry_source.csv",
        ), str(manifest["snapshot_sha256"])

    def _load_dataset(self, root: Path) -> PreparedMarketData:
        data = load_market_snapshot(root)
        if data.split != "train" or data.ledger.index.max() >= pd.Timestamp(LOCKED_START):
            raise RuntimeError("TRAIN_DATA_BOUNDARY_MISMATCH")
        return data

    def _candidate_rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(read_batch_registry(self._prepared_root()))

    def _candidate_lookup(self) -> dict[str, Mapping[str, Any]]:
        package = base_package()
        return {**package.candidate_by_id(), **{row["strategy_id"]: row for row in self._candidate_rows()}}

    def _unit_definitions(self) -> Sequence[tuple[str, Mapping[str, Any], float]]:
        definitions: list[tuple[str, Mapping[str, Any], float]] = []
        candidates = self._candidate_rows()
        for candidate in candidates:
            estimate = 0.5 + float(candidate.get("complexity_score", 1)) * 0.25
            definitions.append((str(candidate["strategy_id"]), dict(candidate), estimate))
        for benchmark in BENCHMARK_IDS:
            definitions.append((
                f"BENCHMARK::{benchmark}",
                {"benchmark_id": benchmark, "unit_type": "benchmark"},
                0.2,
            ))
        return tuple(definitions)

    def _evaluate(
        self,
        data: PreparedMarketData,
        unit_key: str,
        parameters: Mapping[str, Any],
        attempt_id: str,
    ) -> tuple[dict[str, Any], tuple[MetricInputRecord, ...]]:
        started = time.perf_counter()
        benchmark = parameters.get("unit_type") == "benchmark"
        row = self._base_row(unit_key, parameters, attempt_id)
        row.update(
            {
                "seconds_total": None,
                "seconds_signal": None,
                "seconds_simulation": None,
            }
        )
        records: tuple[MetricInputRecord, ...] = ()
        try:
            signal_started = time.perf_counter()
            signal = (
                benchmark_decisions(str(parameters["benchmark_id"]), data)
                if benchmark
                else candidate_decisions(
                    parameters,
                    data,
                    candidate_lookup=self._candidate_lookup(),
                )
            )
            row["seconds_signal"] = time.perf_counter() - signal_started
            if signal.first_evaluable_date is None:
                raise CandidateRejected("NO_EVALUABLE_SESSION")
            if signal.missing_fraction > 0.02 + 1e-12:
                raise CandidateRejected("DATA_INELIGIBLE:CAUSAL_COVERAGE_LT_98_PERCENT")
            simulation_started = time.perf_counter()
            applied = apply_positions(data.ledger, signal.decisions)
            first_decision = pd.Timestamp(signal.first_evaluable_date)
            later = data.ledger.index[data.ledger.index > first_decision]
            evaluation = applied.loc[later]
            evaluation = evaluation.loc[
                (evaluation.index >= pd.Timestamp(self.evaluation_start))
                & (evaluation.index <= pd.Timestamp(self.data_end))
            ]
            returns = evaluation["strategy_return"].dropna().astype(float)
            positions = evaluation.loc[returns.index, "position"].astype(np.int8)
            if len(returns) < self.minimum_rows or len(set(returns.index.year)) < self.minimum_years:
                raise CandidateRejected("DATA_INELIGIBLE:MINIMUM_TRAIN_OOF_COVERAGE")
            if not positions.isin((-1, 1)).all():
                raise CandidateRejected("TECHNICAL_FAILURE_POSITION")
            record = primary_metric_record(unit_key, "train_oof", returns.to_numpy(dtype=float), periods_per_year=252)
            row.update({f"train_{key}": record.reported.get(key) for key in METRIC_FIELDS})
            regimes = _market_regime_states(data, returns.index)
            row.update(_extended_metrics(returns, positions, regimes))
            row.update({
                "first_evaluable_date": signal.first_evaluable_date,
                "missing_fraction": float(signal.missing_fraction),
                "train_dates": [date.date().isoformat() for date in returns.index],
                "train_returns": [float(value) for value in returns],
                "train_positions": [int(value) for value in positions],
                "out_of_fold": True,
                "oof_method": "calendar_year_outer_fold_static_rule",
            })
            records = (record,)
        except CandidateRejected as exc:
            row["status"] = "rejected"
            row["rejection_reason"] = str(exc)
            records = ()
        else:
            row["seconds_simulation"] = time.perf_counter() - simulation_started
        row["seconds_total"] = time.perf_counter() - started
        row["unit_output_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in row.items()
                if key not in {"source_attempt_id", "seconds_total", "seconds_signal", "seconds_simulation"}
            }
        )
        return row, records

    def _write_reduction(self, rows: Sequence[Mapping[str, Any]], root: Path) -> None:
        expected = {key for key, _, _ in self._unit_definitions()}
        observed = {str(row["unit_key"]) for row in rows}
        if expected != observed:
            raise RuntimeError(f"INCOMPLETE_BATCH_COVERAGE:expected={len(expected)}:observed={len(observed)}")
        root = Path(root)
        summary = evaluate_batch(
            rows,
            root,
            batch_id=_batch_id(),
            previous_trial_count=get_previous_trial_count(),
        )
        (root / "candidate_registry.jsonl").write_text(
            self._registry_path(self._prepared_root()).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (root / "autonomous_batch_identity.json").write_text(
            json.dumps({
                "batch_id": _batch_id(),
                "locked_opened": False,
                "validation_used_for_selection": False,
                "train_end": TRAIN_END,
                "validation_start": "2011-01-01",
                "validation_end": "2020-12-31",
                "summary": summary,
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def smoke(self, spec: RunSpec, prepared: PreparedInputs) -> SmokeResult:
        result = super().smoke(spec, prepared)
        if result.passed and result.output_sha256 is not None:
            return result
        return result


class AutonomousDiscoverySmokeWorkload(AutonomousDiscoveryWorkload):
    workload_name = "sp500_autonomous_discovery_smoke"
    workload_family = "sp500_autonomous_discovery_smoke"
    dataset_name = "bounded_spy_autonomous_smoke_market"
    result_filename = "sp500_autonomous_smoke_results.parquet"
    data_start = "2005-10-01"
    data_end = "2009-09-30"
    evaluation_start = "2006-10-01"
    minimum_rows = 200
    minimum_years = 1
    default_candidate_count = 8


class AutonomousDiscoveryPilotWorkload(AutonomousDiscoveryWorkload):
    workload_name = "sp500_autonomous_discovery_pilot"
    workload_family = "sp500_autonomous_discovery_pilot"
    dataset_name = "bounded_spy_autonomous_pilot_market"
    result_filename = "sp500_autonomous_pilot_results.parquet"
    default_candidate_count = 24


SMOKE_WORKLOAD = AutonomousDiscoverySmokeWorkload()
PILOT_WORKLOAD = AutonomousDiscoveryPilotWorkload()
TRAIN_WORKLOAD = AutonomousDiscoveryWorkload()
