"""GitHub-only workload for the frozen SPY V2 campaign."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import RunSpec, SmokeResult
from aurora.infra.github_performance.metric_verifier import MetricInputRecord
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.github_performance.workloads.common import atomic_json, primary_metric_record
from aurora.infra.sp500_long_short_daily.data import PreparedMarketData
from aurora.infra.sp500_long_short_daily.ledger import apply_positions
from aurora.infra.sp500_long_short_daily.signals import CandidateRejected, benchmark_decisions
from aurora.infra.sp500_long_short_daily.workload import (
    BENCHMARK_IDS,
    METRIC_FIELDS,
    Sp500LongShortTrainWorkload,
    _annual_rows,
    _extended_metrics,
    _market_regime_states,
    _nullable_metrics,
    _result_schema,
)
from aurora.infra.sp500_long_short_daily_v2.contracts import (
    CampaignPackage,
    EXPECTED_CANDIDATES,
    EXPECTED_TERMINAL_UNITS,
    EXPECTED_V1_RESULTS_SHA256,
    VALIDATION_ACK,
    canonical_json_hash,
    validate_exact_coverage,
)
from aurora.infra.sp500_long_short_daily_v2.data import load_market_snapshot, prepare_market_snapshot
from aurora.infra.sp500_long_short_daily_v2.signals import FeatureStore, candidate_decisions
from aurora.infra.sp500_long_short_daily_v2.statistics import cumulative_train_ranking

SEED = 20_260_805
SMOKE_IDS = ("V2STRAT0001", "V2STRAT0031", "V2STRAT0091", "V2STRAT0103", "V2STRAT0139")


def _repo_root() -> Path:
    for root in (Path.cwd(), Path(__file__).resolve().parents[2]):
        if (root / "campaigns" / "sp500_long_short_daily_v2" / "research_input").is_dir():
            return root.resolve()
    raise RuntimeError("SP500_V2_CAMPAIGN_PACKAGE_NOT_FOUND")


def _campaign_root() -> Path:
    return _repo_root() / "campaigns" / "sp500_long_short_daily_v2"


@lru_cache(maxsize=1)
def _package() -> CampaignPackage:
    root = _campaign_root()
    return CampaignPackage.load_zip(
        root / "input_package" / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_V2_NEW_STRATEGIES.zip"
    )


def _json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", date_format="iso"))


class Sp500LongShortV2TrainWorkload(Sp500LongShortTrainWorkload):
    workload_name = "sp500_long_short_daily_v2_train"
    workload_family = "sp500_long_short_daily_v2_train"
    dataset_name = "bounded_spy_v2_train_market"
    result_filename = "sp500_long_short_v2_train_results.parquet"
    result_schema = _result_schema()
    seed = SEED
    checkpoint_interval = 8
    phase_name = "train"
    data_start = "1993-01-22"
    data_end = "2010-12-31"
    evaluation_start = "1998-01-01"
    minimum_rows = 1000
    minimum_years = 5
    candidate_ids: tuple[str, ...] | None = None
    representative_families: tuple[str, ...] = ()

    def _prepare_dataset(self, root: Path) -> tuple[tuple[str, ...], str]:
        manifest = prepare_market_snapshot(
            root, _package(), start=self.data_start, end=self.data_end, split="train"
        )
        return (
            "market_data_manifest.json", "raw_manifest.jsonl", "spy_ledger.parquet",
            "causal_series.parquet", "v2_fixed_etf_ohlcv.parquet",
        ), str(manifest["snapshot_sha256"])

    def _load_dataset(self, root: Path) -> PreparedMarketData:
        data = load_market_snapshot(root)
        if data.split != "train" or data.ledger.index.max() > pd.Timestamp(self.data_end):
            raise RuntimeError("TRAIN_DATA_BOUNDARY_MISMATCH")
        return data

    def _unit_definitions(self) -> Sequence[tuple[str, Mapping[str, Any], float]]:
        candidates = list(_package().candidates)
        if self.representative_families:
            candidates = [
                sorted(
                    (row for row in candidates if row["family"] == family),
                    key=lambda row: (-int(row["priority_score"]), str(row["strategy_id"])),
                )[0]
                for family in self.representative_families
            ]
        if self.candidate_ids is not None:
            lookup = _package().candidate_by_id()
            candidates = [lookup[key] for key in self.candidate_ids]
        rows = [
            (str(candidate["strategy_id"]), dict(candidate), 0.5 + float(candidate["complexity_score"]) * 0.25)
            for candidate in candidates
        ]
        rows.extend(
            (f"BENCHMARK::{benchmark}", {"benchmark_id": benchmark, "unit_type": "benchmark"}, 0.2)
            for benchmark in BENCHMARK_IDS
        )
        if self.phase_name == "train" and self.candidate_ids is None and not self.representative_families and len(rows) != EXPECTED_TERMINAL_UNITS:
            raise AssertionError("V2 campaign must expose 144 candidates and five benchmarks")
        return tuple(rows)

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
                else candidate_decisions(parameters, data, feature_store=FeatureStore.build(data))
            )
            if signal.first_evaluable_date is None:
                raise CandidateRejected("NO_EVALUABLE_SESSION")
            if signal.missing_fraction > 0.02 + 1e-12:
                raise CandidateRejected("DATA_INELIGIBLE:CAUSAL_COVERAGE_LT_98_PERCENT")
            applied = apply_positions(data.ledger, signal.decisions)
            first = pd.Timestamp(signal.first_evaluable_date)
            returns = applied.loc[
                (applied.index > first)
                & (applied.index >= pd.Timestamp(self.evaluation_start))
                & (applied.index <= pd.Timestamp(self.data_end)),
                "strategy_return",
            ].dropna().astype(float)
            positions = applied.loc[returns.index, "position"].astype(np.int8)
            if len(returns) < self.minimum_rows or len(set(returns.index.year)) < self.minimum_years:
                raise CandidateRejected("DATA_INELIGIBLE:MINIMUM_TRAIN_COVERAGE")
            if not positions.isin((-1, 1)).all():
                raise CandidateRejected("TECHNICAL_FAILURE_POSITION")
            record = primary_metric_record(unit_key, "train", returns.to_numpy(dtype=float), periods_per_year=252)
            row.update({f"train_{key}": record.reported.get(key) for key in METRIC_FIELDS})
            row.update(_extended_metrics(returns, positions, _market_regime_states(data, returns.index)))
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
        from aurora.infra.github_performance.contracts import canonical_sha256
        row["unit_output_sha256"] = canonical_sha256(
            {key: value for key, value in row.items() if key != "source_attempt_id"}
        )
        return row, records

    def smoke(self, spec: RunSpec, prepared: Any) -> SmokeResult:
        del spec
        data = self._load_dataset(self._prepared_root(prepared))
        lookup = {key: (key, payload, cost) for key, payload, cost in self._unit_definitions()}
        selected = [lookup[key] for key in (*SMOKE_IDS, *(f"BENCHMARK::{b}" for b in BENCHMARK_IDS))]
        first = [self._evaluate(data, key, payload, "smoke-a")[0] for key, payload, _ in selected]
        second = [self._evaluate(data, key, payload, "smoke-b")[0] for key, payload, _ in selected]
        first_hashes = [row["unit_output_sha256"] for row in first]
        second_hashes = [row["unit_output_sha256"] for row in second]
        reasons: list[str] = []
        if first_hashes != second_hashes:
            reasons.append("NONDETERMINISTIC_SMOKE")
        if any(row["locked_opened"] or row["validation_used_for_selection"] for row in first):
            reasons.append("BOUNDARY_BREACH")
        by_id = {row["strategy_id"]: row for row in first}
        if by_id["always_long"]["train_returns"] != by_id["buy_and_hold_spy_total_return"]["train_returns"]:
            reasons.append("BUY_HOLD_ALWAYS_LONG_MISMATCH")
        if not np.array_equal(
            np.asarray(by_id["always_long"]["train_returns"]),
            -np.asarray(by_id["always_short"]["train_returns"]),
        ):
            reasons.append("ALWAYS_SHORT_RECONCILIATION_MISMATCH")
        return SmokeResult(
            passed=not reasons,
            output_sha256=canonical_json_hash(first_hashes),
            reason_codes=tuple(reasons),
        )

    def _write_reduction(self, rows: Sequence[Mapping[str, Any]], root: Path) -> None:
        ordered = sorted(rows, key=lambda row: str(row["unit_key"]))
        expected = [key for key, _, _ in self._unit_definitions()]
        completed = [str(row["unit_key"]) for row in ordered if row["status"] == "evaluated"]
        rejected = [str(row["unit_key"]) for row in ordered if row["status"] == "rejected"]
        validate_exact_coverage(expected, completed, rejected)
        root.mkdir(parents=True, exist_ok=True)
        if self.phase_name != "train":
            pd.DataFrame(ordered).drop(columns=["train_dates", "train_returns", "train_positions"], errors="ignore").to_csv(root / "diagnostic_metrics.csv", index=False)
            atomic_json(root / f"sp500_long_short_daily_v2_{self.phase_name}_summary.json", {"phase": self.phase_name, "expected_units": len(expected), "completed_units": len(ordered), "locked_opened": False, "validation_opened": False})
            return

        candidates = [row for row in ordered if row["unit_type"] == "candidate"]
        benchmarks = [row for row in ordered if row["unit_type"] == "benchmark"]
        candidate_frame = pd.DataFrame(candidates).drop(columns=["train_dates", "train_returns", "train_positions"], errors="ignore")
        eligibility = pd.DataFrame([{"unit_key": row["unit_key"], "status": row["status"], "reason": row["rejection_reason"], "family": row["family"]} for row in ordered])
        eligibility.to_csv(root / "eligibility_and_rejections.csv", index=False)
        daily_rows: list[dict[str, Any]] = []
        annual_rows: list[dict[str, Any]] = []
        for row in ordered:
            if row["status"] != "evaluated":
                continue
            for date, value, position in zip(row["train_dates"], row["train_returns"], row["train_positions"], strict=True):
                daily_rows.append({"unit_key": row["unit_key"], "date": date, "return": value, "position": position})
            annual_rows.extend({"unit_key": row["unit_key"], **annual} for annual in json.loads(row["annual_metrics_json"]))
        daily = pd.DataFrame(daily_rows)
        annual = pd.DataFrame(annual_rows)
        pq.write_table(pa.Table.from_pandas(daily, preserve_index=False), root / "v2_train_daily_returns.parquet")
        annual.to_csv(root / "annual_returns.csv", index=False)
        folds = annual.copy()
        if len(folds):
            folds["outer_fold_id"] = folds["year"].map(lambda year: f"calendar_year_{int(year)}")
            folds["out_of_fold"] = True
            folds["validation_used"] = False
        folds.to_csv(root / "fold_metrics.csv", index=False)
        candidate_keys = set(candidate_frame.loc[candidate_frame["status"] == "evaluated", "unit_key"])
        benchmark_keys = {str(row["unit_key"]) for row in benchmarks if row["status"] == "evaluated"}
        prior_zip = _campaign_root() / "prior_campaign" / "sp500-ls-train-yahoo-fallback-r8-results.zip"
        ranking, multiple, trial_ledger, v1_audit = cumulative_train_ranking(
            candidate_frame,
            annual,
            daily.loc[daily["unit_key"].isin(candidate_keys)],
            daily.loc[daily["unit_key"].isin(benchmark_keys)],
            v1_results_zip=prior_zip,
            seed=SEED,
        )
        ranking.to_csv(root / "train_ranking.csv", index=False)
        trial_ledger.to_csv(root / "cumulative_trial_ledger.csv", index=False)
        atomic_json(root / "combined_multiple_testing_results.json", multiple)
        atomic_json(root / "v1_ingestion_audit.json", v1_audit)
        candidate_frame = candidate_frame.merge(
            ranking.drop(columns=[column for column in candidate_frame.columns if column in ranking.columns and column != "unit_key"]),
            on="unit_key", how="left", validate="one_to_one",
        )
        compact_rows = pd.DataFrame(ordered).drop(
            columns=["train_dates", "train_returns", "train_positions"], errors="ignore"
        )
        candidate_ranking = ranking.drop(
            columns=[
                column
                for column in compact_rows.columns
                if column in ranking.columns and column != "unit_key"
            ],
            errors="ignore",
        )
        compact_rows = compact_rows.merge(
            candidate_ranking,
            on="unit_key",
            how="left",
            validate="one_to_one",
        )
        compact_rows.to_csv(root / "candidate_and_benchmark_metrics.csv", index=False)

        eligible = ranking.loc[ranking["hard_train_eligible"]].copy()
        pareto_fields = ["train_cagr_pct", "train_calmar", "train_max_drawdown_pct", "train_worst_year_return_pct", "train_min_outer_fold_cagr_pct"]
        pareto_rows = []
        for index, row in eligible.iterrows():
            others = eligible.drop(index=index)[pareto_fields].astype(float)
            values = row[pareto_fields].astype(float)
            if not bool(((others >= values).all(axis=1) & (others > values).any(axis=1)).any()):
                pareto_rows.append(row)
        pareto = pd.DataFrame(pareto_rows)
        pareto.to_csv(root / "pareto_frontier.csv", index=False)
        finalists = (
            ranking.loc[ranking["eligible_for_freeze"] & ranking["evidence_track"].eq("pre_2011_evidence")]
            .sort_values(["train_selection_score", "unit_key"], ascending=[False, True], kind="mergesort")
            .groupby("family", sort=False).head(1).head(20).to_dict("records")
        )
        lookup = _package().candidate_by_id()
        freeze = {
            "schema_version": "2",
            "campaign_id": "sp500_long_short_daily_zero_cost_v2_new_strategies",
            "freeze_created_at_utc": datetime.now(timezone.utc).isoformat(),
            "selection_closed": True,
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "validation_opened": False,
            "locked_opened": False,
            "validation_authorization_required": VALIDATION_ACK,
            "validation_authorization_used": False,
            "code_sha": os.environ.get("GITHUB_SHA", "LOCAL_TEST_ONLY"),
            "candidate_pack_sha256": canonical_json_hash(list(_package().candidates)),
            "v1_results_sha256": EXPECTED_V1_RESULTS_SHA256,
            "terminal_units": EXPECTED_TERMINAL_UNITS,
            "cumulative_declared_trials": 312,
            "ranking": _json_records(ranking),
            "pareto_frontier": _json_records(pareto),
            "finalists": [
                {"order": i, "strategy_id": row["strategy_id"], "family": row["family"], "canonical_hash": row["canonical_hash"], "candidate_rules": lookup[str(row["strategy_id"])], "train_metrics": {key: row.get(key) for key in ("train_cagr_pct", "train_sharpe", "train_calmar", "train_max_drawdown_pct", "train_selection_score")}, "eligible_for_validation": True}
                for i, row in enumerate(finalists, 1)
            ],
        }
        freeze["freeze_sha256"] = canonical_json_hash(freeze)
        atomic_json(root / "v2_train_selection_freeze.json", freeze)
        summary = {
            "result_status": "TRAIN_SELECTION_FROZEN_VALIDATION_NOT_OPENED" if finalists else "NEGATIVE_RESULT",
            "expected_candidates": EXPECTED_CANDIDATES,
            "expected_benchmarks": 5,
            "evaluated_candidates": sum(row["status"] == "evaluated" for row in candidates),
            "rejected_candidates": sum(row["status"] == "rejected" for row in candidates),
            "evaluated_benchmarks": sum(row["status"] == "evaluated" for row in benchmarks),
            "frozen_finalists": len(finalists),
            "validation_opened": False,
            "locked_opened": False,
            "cumulative_declared_trials": 312,
            "v1_daily_streams_loaded": v1_audit["v1_daily_streams_loaded"],
        }
        summary["summary_sha256"] = canonical_json_hash(summary)
        atomic_json(root / "sp500_long_short_daily_v2_train_summary.json", summary)
        ranking.loc[~ranking["eligible_for_freeze"]].head(30).to_csv(root / "near_misses.csv", index=False)
        family = eligibility.loc[~eligibility["unit_key"].astype(str).str.startswith("BENCHMARK::")].groupby("family")["status"].agg(expected_candidates="size", evaluated_candidates=lambda x: int((x == "evaluated").sum()), rejected_candidates=lambda x: int((x == "rejected").sum())).reset_index()
        family.to_csv(root / "family_coverage.csv", index=False)
        rolling_columns = [
            "unit_key", "strategy_id", "unit_type", "family", "status",
            "train_median_rolling_1y_cagr_pct", "train_median_rolling_3y_cagr_pct",
            "train_median_rolling_5y_cagr_pct", "train_worst_rolling_1y_cagr_pct",
            "train_worst_rolling_3y_cagr_pct", "train_worst_rolling_5y_cagr_pct",
        ]
        compact_rows.reindex(columns=rolling_columns).to_csv(root / "rolling_metrics.csv", index=False)
        regime_columns = [
            column for column in compact_rows.columns
            if column in {"unit_key", "strategy_id", "unit_type", "family", "status"}
            or "regime" in column
            or "above_sma200" in column
            or "below_sma200" in column
        ]
        compact_rows.reindex(columns=regime_columns).to_csv(root / "regime_metrics.csv", index=False)
        shutil.copy2(root / "combined_multiple_testing_results.json", root / "multiple_testing_results.json")
        atomic_json(root / "causality_audit.json", {"decision": "after_close_t", "execution": "next_open_t_plus_1", "validation_opened": False, "locked_opened": False})
        raw_manifest = self._prepared_root() / "raw_manifest.jsonl"
        shutil.copy2(raw_manifest, root / "raw_manifest.jsonl")
        shutil.copy2(self._prepared_root() / "market_data_manifest.json", root / "market_data_manifest.json")
        shutil.copy2(root / "raw_manifest.jsonl", root / "data_lineage.jsonl")
        (root / "RESULT_STATUS.md").write_text(f"# {summary['result_status']}\n\n- Frozen finalists: {len(finalists)}\n- Validation opened: false\n- Locked opened: false\n", encoding="utf-8")
        (root / "environment_lock.txt").write_text(f"code_sha={os.environ.get('GITHUB_SHA', 'LOCAL_TEST_ONLY')}\ngithub_actions_only=true\nlocked_opened=false\n", encoding="utf-8")
        shutil.copy2(_campaign_root() / "implementation_mapping.md", root / "implementation_mapping.md")
        shutil.copy2(
            _campaign_root() / "prior_campaign" / "sp500-ls-train-yahoo-fallback-r8-results.zip",
            root / "prior_v1_results.zip",
        )
        (root / "scientific_warnings.md").write_text("# Scientific warnings\n\nValidation remains unopened until a frozen eligible finalist exists. Locked 2021+ remains closed.\n", encoding="utf-8")
        manifest_files = sorted(path.name for path in root.iterdir() if path.is_file())
        final_manifest = {"result_status": summary["result_status"], "code_sha": os.environ.get("GITHUB_SHA", "LOCAL_TEST_ONLY"), "train_end": "2010-12-31", "validation_opened": False, "locked_start": "2021-01-01", "locked_opened": False, "files": {name: sha256_file(root / name) for name in manifest_files}}
        final_manifest["manifest_sha256"] = canonical_json_hash(final_manifest)
        atomic_json(root / "final_manifest.json", final_manifest)


class Sp500LongShortV2SmokeWorkload(Sp500LongShortV2TrainWorkload):
    workload_name = "sp500_long_short_daily_v2_smoke"
    workload_family = "sp500_long_short_daily_v2_smoke"
    dataset_name = "bounded_spy_v2_smoke_market"
    result_filename = "sp500_long_short_v2_smoke_results.parquet"
    phase_name = "smoke"
    data_start = "2005-10-01"
    data_end = "2009-09-30"
    evaluation_start = "2006-10-01"
    minimum_rows = 200
    minimum_years = 1
    candidate_ids = SMOKE_IDS


class Sp500LongShortV2PilotWorkload(Sp500LongShortV2TrainWorkload):
    workload_name = "sp500_long_short_daily_v2_pilot"
    workload_family = "sp500_long_short_daily_v2_pilot"
    dataset_name = "bounded_spy_v2_pilot_market"
    result_filename = "sp500_long_short_v2_pilot_results.parquet"
    phase_name = "pilot"
    representative_families = tuple(sorted({str(row["family"]) for row in _package().candidates}))


SMOKE_WORKLOAD = Sp500LongShortV2SmokeWorkload()
PILOT_WORKLOAD = Sp500LongShortV2PilotWorkload()
TRAIN_WORKLOAD = Sp500LongShortV2TrainWorkload()
