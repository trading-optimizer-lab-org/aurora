"""Synthetic contracts for the final original-290 merge and verifier."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.merge_stock_protocol_290_event_study import (
    AUDIT_SUMMARY_NAME,
    CUTOFF,
    EXPECTED_CORRECTED_SHARDS,
    EXPECTED_HISTORICAL_SHARDS,
    FINAL_MANIFEST_NAME,
    FINAL_REPORT_NAME,
    FUNCTIONAL_DUPLICATES_NAME,
    PAIRED_ENTRY_METRICS,
    PAIRED_EXIT_METRICS,
    RECONCILIATION_NAME,
    SEMANTIC_AUDIT_NAME,
    STATISTIC_FILES,
    _artifact_manifest,
    _apply_robust_leader_gates,
    _bounded_cluster_bootstrap,
    _bounded_robust_inference,
    _discover_shards,
    _global_functional_mapping,
    _initialize_estimable_columns,
    _remove_technical_duplicates,
    _report,
    _two_sided_sign_pvalue,
    enrich_fx_causally,
    reconcile_prior_financing,
    _concatenate_parquet_files,
    reconcile_all_combinations,
)
from scripts.verify_stock_protocol_290_event_study import (
    EventStudy290VerificationError,
    _verify_manifest,
    _verify_report,
    _verify_summary,
)


def _manifest() -> pd.DataFrame:
    rows = []
    for entry in range(10):
        for exit_index in range(29):
            rows.append(
                {
                    "combination_id": f"c-{entry:02d}-{exit_index:02d}",
                    "entry_spec_id": f"entry-{entry:02d}",
                    "exit_spec_id": f"exit-{exit_index:02d}",
                }
            )
    return pd.DataFrame(rows)


def test_bounded_bootstrap_preserves_combinations_without_complete_events() -> None:
    rows = []
    for combination_index in range(290):
        censored = combination_index == 289
        rows.append(
            {
                "combination_id": f"c-{combination_index:03d}",
                "opportunity_id": f"o-{combination_index:03d}",
                "symbol": "SPY",
                "entry_date": pd.Timestamp("2000-01-03"),
                "gross_return": np.nan if censored else 0.01,
                "holding_sessions": 5,
                "censored": censored,
            }
        )

    summary, samples = _bounded_cluster_bootstrap(
        pd.DataFrame(rows), bootstrap_samples=1
    )

    assert summary["combination_id"].nunique() == 289
    assert samples["combination_id"].nunique() == 289
    assert "c-289" not in set(summary["combination_id"].astype(str))


def test_bounded_robust_inference_marks_censored_only_combinations() -> None:
    rows = []
    for combination_index in range(290):
        censored = combination_index == 289
        rows.append(
            {
                "combination_id": f"c-{combination_index:03d}",
                "opportunity_id": f"o-{combination_index:03d}",
                "symbol": "SPY",
                "entry_date": pd.Timestamp("2000-01-03"),
                "gross_return": np.nan if censored else 0.01,
                "holding_sessions": 5,
                "censored": censored,
            }
        )

    result = _bounded_robust_inference(pd.DataFrame(rows))

    assert len(result) == 290
    unavailable = result.loc[result["combination_id"].eq("c-289")].iloc[0]
    assert unavailable["complete_events"] == 0
    assert (
        unavailable["analysis_status"]
        == "not_estimable_no_complete_opportunities"
    )
    assert result.loc[
        result["combination_id"].ne("c-289"), "analysis_status"
    ].eq("supported").all()


@pytest.mark.parametrize(
    ("positive", "negative"),
    ((0, 0), (1, 0), (3, 2), (8, 4), (10, 10)),
)
def test_vectorized_sign_pvalue_matches_exact_symmetric_tail(
    positive: int,
    negative: int,
) -> None:
    nonzero = positive + negative
    expected = 1.0
    if nonzero:
        expected = min(
            1.0,
            2.0
            * sum(
                math.comb(nonzero, index)
                for index in range(min(positive, negative) + 1)
            )
            / (2**nonzero),
        )

    assert _two_sided_sign_pvalue(positive, negative) == pytest.approx(expected)


def test_vectorized_sign_pvalue_handles_large_paired_samples() -> None:
    value = _two_sided_sign_pvalue(14_000, 13_000)

    assert np.isfinite(value)
    assert 0.0 <= value <= 1.0


def test_estimable_columns_accept_mixed_numeric_and_status_values() -> None:
    frame = pd.DataFrame({"combination_id": ["a", "b"]})
    columns = ("mean_return", "cluster_pvalue_one_sided")

    _initialize_estimable_columns(frame, columns)
    frame.loc[frame["combination_id"].eq("a"), "mean_return"] = 0.015
    frame.loc[frame["combination_id"].eq("a"), "cluster_pvalue_one_sided"] = 0.25

    assert frame["mean_return"].dtype == object
    assert frame["cluster_pvalue_one_sided"].dtype == object
    assert frame.loc[0, "mean_return"] == pytest.approx(0.015)
    assert frame.loc[0, "cluster_pvalue_one_sided"] == pytest.approx(0.25)
    assert frame.loc[1, "mean_return"] == "not_estimable"


def test_robust_leader_requires_every_explicit_gate() -> None:
    ranked = pd.DataFrame(
        {
            "combination_id": ["pass", "period-fail"],
            "selection_eligible": [True, True],
            "pareto_rank": pd.Series([1, 1], dtype="Int64"),
            "classification": ["pareto_promising", "pareto_promising"],
        }
    )
    all_summary = pd.DataFrame(
        {
            "combination_id": ["pass", "period-fail"],
            "cost_bps_per_side": [0, 0],
            "complete_events": [600, 600],
            "median_return": [0.08, 0.08],
            "positive_years_pct": [0.75, 0.75],
            "censoring_rate": [0.05, 0.05],
        }
    )
    period_rows = []
    for combination_id in ("pass", "period-fail"):
        for period_name in ("A", "B", "C"):
            period_rows.append(
                {
                    "combination_id": combination_id,
                    "cut_value": period_name,
                    "cost_bps_per_side": 0,
                    "complete_events": 200,
                    "median_return": (
                        -0.01
                        if combination_id == "period-fail" and period_name == "C"
                        else 0.05
                    ),
                }
            )
    cluster = pd.DataFrame(
        {
            "combination_id": ["pass", "period-fail"],
            "method": ["hierarchical_year_symbol"] * 2,
            "metric": ["median_return"] * 2,
            "ci_low95": [0.02, 0.02],
            "ci_high95": [0.10, 0.10],
        }
    )
    multiple = pd.DataFrame(
        {
            "combination_id": ["pass", "period-fail"],
            "bh_declared_290_pvalue": [0.04, 0.04],
            "holm_declared_290_pvalue": [0.08, 0.08],
            "westfall_young_pvalue": [0.06, 0.06],
        }
    )
    leave_rows = []
    for combination_id in ("pass", "period-fail"):
        for omission, values in (("year", ("2008", "2009")), ("country", ("US", "GB"))):
            for value in values:
                leave_rows.append(
                    {
                        "combination_id": combination_id,
                        "omission": omission,
                        "omitted_value": value,
                        "leave_out_mean_return": 0.03,
                    }
                )

    result = _apply_robust_leader_gates(
        ranked,
        all_period_summary=all_summary,
        period_results=pd.DataFrame(period_rows),
        global_cluster_summary=cluster,
        multiple_testing=multiple,
        leave_out=pd.DataFrame(leave_rows),
    ).set_index("combination_id")

    assert result.loc["pass", "classification"] == "robust_leader"
    assert result.loc["pass", "robust_gate_all_passed"]
    assert result.loc["period-fail", "classification"] == "period_dependent"
    assert not result.loc[
        "period-fail", "robust_gate_all_three_periods_positive"
    ]


def _summary() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract": "290-10-29",
        "combination_count": 290,
        "entry_spec_count": 10,
        "exit_spec_count": 29,
        "historical_shard_count": 10,
        "corrected_shard_count": 30,
        "opportunity_count": 870,
        "completed": 290,
        "censored": 290,
        "failed_due_to_data": 290,
        "technical_input_rows": 870,
        "technical_duplicates_removed": 0,
        "all_combinations_reconciled": True,
        "historical_replication_passed": True,
        "semantic_audit_preserved": True,
        "functional_duplicates_preserved": True,
        "semantic_not_applicable_count": 3,
        "functional_duplicate_rows": 6,
        "fx_currency_unknown_count": 4,
        "fx_dividend_detail_missing_count": 5,
        "declared_tests": 290,
        "eligible_tests": 260,
        "functionally_unique_tests": 240,
        "manifest_sha256": "a" * 64,
        "dataset_hash": "b" * 64,
        "policy_hash": "c" * 64,
        "source_snapshot_sha256": "d" * 64,
        "new_oos_claimed": False,
        "optimization_performed_on_opened_data": False,
        "validation_used_for_selection": False,
        "no_portfolio_simulation": True,
        "no_capital_exclusions": True,
        "cutoff": "2026-07-17",
        "selection_period": "A",
        "diagnostic_periods": ["B", "C"],
        "shard_reconciliation_rows": 870,
        "exact_strategy_candidate_id": "exact-combination",
        "prior_audit_financing_reconciled": True,
        "financing_information_only": True,
        "financed_in_old_portfolio": 12,
        "not_financed_in_old_portfolio": 8,
        "source_lock_sha256": "e" * 64,
        "exact_strategy_sha256": "f" * 64,
        "frozen_fx_rates_sha256": "1" * 64,
        "classification_counts": {"robust_leader": 1, "not_supported": 289},
    }


def test_concatenate_parquet_files_unions_columns_without_losing_rows(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    output = tmp_path / "combined.parquet"
    pd.DataFrame(
        {"id": [1, 2], "value": [None, None], "left_only": ["a", "b"]}
    ).to_parquet(
        first, index=False
    )
    pd.DataFrame({"id": [3], "value": [4.5], "right_only": [4.5]}).to_parquet(
        second, index=False
    )

    rows = _concatenate_parquet_files([first, second], output)
    combined = pd.read_parquet(output)

    assert rows == 3
    assert combined["id"].tolist() == [1, 2, 3]
    assert combined.loc[2, "value"] == pytest.approx(4.5)
    assert combined["left_only"].tolist()[:2] == ["a", "b"]
    assert pd.isna(combined.loc[2, "left_only"])
    assert combined.loc[2, "right_only"] == pytest.approx(4.5)


def _report_statistics() -> dict[str, pd.DataFrame]:
    combination = pd.DataFrame(
        {
            "combination_id": ["best"],
            "cost_bps_per_side": [0],
            "complete_events": [250],
            "mean_return": [0.2],
            "median_return": [0.18],
            "expected_shortfall_10_abs": [0.04],
            "mae_median_abs": [0.03],
            "duration_median": [12.0],
            "median_return_per_session": [0.01],
        }
    )
    cut = pd.DataFrame(
        {
            "combination_id": ["best"],
            "cut_value": ["A"],
            "median_return": [0.15],
        }
    )
    objective_rows = [
        ("01_highest_median_return", "best", 0.18, None),
        ("03_highest_event_speed", "best", 0.02, None),
        ("04_lowest_mae", "best", 0.03, None),
        ("05_lowest_expected_shortfall", "best", 0.04, None),
        ("15_most_stable_across_periods", "best", 0.01, None),
        ("11_best_at_25_bps_per_side", "best", 0.17, 25),
        ("12_best_at_50_bps_per_side", "best", 0.16, 50),
        ("13_best_at_100_bps_per_side", "best", 0.14, 100),
    ]
    return {
        "summary": combination,
        "period": cut,
        "multiple_testing": pd.DataFrame(
            {
                "combination_id": ["best"],
                "westfall_young_pvalue": [0.04],
                "bh_declared_290_pvalue": [0.05],
                "holm_declared_290_pvalue": [0.06],
            }
        ),
        "pareto": pd.DataFrame(
            {
                "combination_id": ["best"],
                "balanced_score": [0.85],
                "ideal_distance": [0.1],
            }
        ),
        "ideal": pd.DataFrame(
            {"combination_id": ["best"], "ideal_distance": [0.1]}
        ),
        "balanced": pd.DataFrame(
            {"combination_id": ["best"], "balanced_score": [0.9]}
        ),
        "top_objectives": pd.DataFrame(
            objective_rows,
            columns=(
                "objective",
                "combination_id",
                "objective_value",
                "cost_bps_per_side",
            ),
        ),
        "concentration": pd.DataFrame(
            {"combination_id": ["best"], "concentration_hhi": [0.4]}
        ),
        "leave_out": pd.DataFrame(
            {
                "combination_id": ["best", "best"],
                "omission": ["year", "symbol"],
                "omitted_value": [2012, "AAA"],
                "change_from_baseline": [-0.04, -0.05],
            }
        ),
        "functional_duplicates": pd.DataFrame(
            {
                "combination_id": ["best", "other"],
                "global_functional_canonical_combination_id": ["best", "other"],
            }
        ),
        "classifications": pd.DataFrame(
            {
                "combination_id": ["best"],
                "classification": ["robust_leader"],
                "ideal_distance": [0.1],
            }
        ),
    }


def test_minimum_output_names_match_the_frozen_specification() -> None:
    assert SEMANTIC_AUDIT_NAME == "combination_semantic_audit.csv"
    assert FUNCTIONAL_DUPLICATES_NAME == "functional_duplicate_groups.csv"
    assert RECONCILIATION_NAME == "opportunity_reconciliation.csv"
    assert set(STATISTIC_FILES.values()) >= {
        "censoring_audit.csv",
        "combination_summary_results.csv",
        "combination_period_results.csv",
        "combination_yearly_results.csv",
        "combination_decade_results.csv",
        "combination_country_results.csv",
        "combination_market_results.csv",
        "combination_currency_results.csv",
        "paired_entry_comparisons.csv",
        "paired_exit_comparisons.csv",
        "clustered_bootstrap_results.csv",
        "robust_inference_diagnostics.csv",
        "multiple_testing_results.csv",
        "cscv_pbo_results.csv",
        "leave_one_group_out_results.csv",
        "return_concentration_results.csv",
        "opportunity_pareto_frontier.csv",
        "opportunity_ideal_point_ranking.csv",
        "balanced_opportunity_ranking.csv",
        "top_combinations_by_objective.csv",
        "survival_analysis_by_combination.csv",
    }
    assert STATISTIC_FILES["survival"] == "survival_analysis_by_combination.csv"
    assert set(PAIRED_EXIT_METRICS) == {
        "return", "loss", "mae", "duration", "return_per_session"
    }
    assert set(PAIRED_ENTRY_METRICS) == {
        "trigger_probability", "entry_price", "entry_delay_sessions", "return",
        "mae", "duration", "coverage",
    }
    assert not any(name.startswith("event_study_") for name in STATISTIC_FILES.values())


def test_discovery_requires_exactly_ten_and_thirty_unique_audit_files(
    tmp_path: Path,
) -> None:
    historical = tmp_path / "historical"
    corrected = tmp_path / "corrected"
    for index in range(EXPECTED_HISTORICAL_SHARDS):
        root = historical / f"shard-{index}"
        root.mkdir(parents=True)
        (root / "historical.json").write_text(
            json.dumps({"entry_index": index}), encoding="utf-8"
        )
    for index in range(EXPECTED_CORRECTED_SHARDS):
        root = corrected / f"shard-{index}"
        root.mkdir(parents=True)
        (root / "corrected.json").write_text(
            json.dumps({"coordinate": index}), encoding="utf-8"
        )

    assert len(_discover_shards(historical, "historical.json", 10)) == 10
    assert len(_discover_shards(corrected, "corrected.json", 30)) == 30

    (corrected / "shard-29" / "corrected.json").unlink()
    with pytest.raises(ValueError, match="exactly 30"):
        _discover_shards(corrected, "corrected.json", 30)


def test_technical_deduplication_keeps_functionally_equal_combinations() -> None:
    frame = pd.DataFrame(
        {
            "opportunity_id": ["technical-a", "technical-a", "functional-b"],
            "combination_id": ["c-00-00", "c-00-00", "c-00-01"],
            "symbol": ["AAA", "AAA", "AAA"],
            "entry_date": pd.to_datetime(["2020-01-02"] * 3),
            "gross_return": [0.1, 0.1, 0.1],
        }
    )

    result = _remove_technical_duplicates(frame)

    assert list(result["opportunity_id"]) == ["technical-a", "functional-b"]
    assert set(result["combination_id"]) == {"c-00-00", "c-00-01"}


def test_conflicting_technical_duplicate_fails() -> None:
    frame = pd.DataFrame(
        {
            "opportunity_id": ["same", "same"],
            "combination_id": ["c-00-00", "c-00-00"],
            "gross_return": [0.1, 0.2],
        }
    )

    with pytest.raises(ValueError, match="conflicting"):
        _remove_technical_duplicates(frame)


def test_every_combination_reconciles_completed_censored_and_failed() -> None:
    manifest = _manifest()
    rows = []
    statuses = {"A": "completed", "B": "right_censored", "C": "failed_due_to_data"}
    for combination in manifest["combination_id"]:
        for period, status in statuses.items():
            rows.append(
                {
                    "combination_id": combination,
                    "period": period,
                    "status": status,
                }
            )
    opportunities = pd.DataFrame(rows)

    result = reconcile_all_combinations(opportunities, manifest)

    assert len(result) == 290 * 4
    assert result.groupby("period")["combination_id"].nunique().to_dict() == {
        "A": 290,
        "ALL": 290,
        "B": 290,
        "C": 290,
    }
    assert (
        result["opportunities"]
        == result["completed"] + result["censored"] + result["failed_due_to_data"]
    ).all()
    aggregate = result.loc[result["period"].eq("ALL")]
    assert aggregate[["completed", "censored", "failed_due_to_data"]].eq(1).all().all()


def test_fx_enrichment_is_causal_and_never_invents_currency() -> None:
    opportunities = pd.DataFrame(
        {
            "opportunity_id": ["usd", "eur", "dividend", "unknown"],
            "combination_id": ["c-00-00"] * 4,
            "status": ["completed"] * 4,
            "symbol": ["US", "EU", "EU2", "ZZ"],
            "currency": ["USD", "EUR", "EUR", None],
            "currency_unknown": [False, False, False, True],
            "entry_date": pd.to_datetime(["2020-01-02"] * 4),
            "entry_price": [100.0] * 4,
            "entry_value_local_per_initial_share": [100.0] * 4,
            "exit_date": pd.to_datetime(["2020-01-06"] * 4),
            "exit_price": [110.0] * 4,
            "exit_value_local_per_initial_share": [110.0] * 4,
            "mtm_date": pd.to_datetime([None] * 4),
            "mtm_price": [np.nan] * 4,
            "dividends_local": [0.0, 0.0, 2.0, 0.0],
            "dividend_payments_local_json": [
                "[]",
                "[]",
                json.dumps(
                    [
                        {
                            "date": "2020-01-03",
                            "cash_local_per_initial_share": 2.0,
                        }
                    ]
                ),
                "[]",
            ],
            "total_return_local": [0.1, 0.1, 0.12, 0.1],
            "price_scale_to_currency_unit": [1.0] * 4,
            "return_usd": [np.nan] * 4,
        }
    )
    rates = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-03", "2020-01-06"]),
            "currency": ["EUR", "EUR", "EUR"],
            "usd_per_local": [1.10, 1.20, 1.30],
        }
    )

    result, _ = enrich_fx_causally(opportunities, rates)
    indexed = result.set_index("opportunity_id")

    assert indexed.loc["usd", "return_usd"] == pytest.approx(0.1)
    assert indexed.loc["eur", "fx_entry_date"] == pd.Timestamp("2020-01-01")
    assert indexed.loc["eur", "fx_exit_date"] == pd.Timestamp("2020-01-06")
    assert indexed.loc["eur", "return_usd"] == pytest.approx(110 * 1.30 / (100 * 1.10) - 1)
    assert indexed.loc["dividend", "fx_merge_status"] == "causal_enriched"
    assert indexed.loc["dividend", "dividend_value_usd_per_share"] == pytest.approx(2.4)
    assert indexed.loc["dividend", "return_usd"] == pytest.approx(
        (110 * 1.30 + 2 * 1.20) / (100 * 1.10) - 1
    )
    assert indexed.loc["dividend", "primary_event_return"] == indexed.loc[
        "dividend", "return_usd"
    ]
    assert indexed.loc["dividend", "gross_return_basis"] == "total_return_usd"
    assert indexed.loc["unknown", "fx_merge_status"] == "currency_unknown"
    assert pd.isna(indexed.loc["unknown", "currency"])
    assert indexed.loc["unknown", "primary_event_return"] == pytest.approx(0.1)
    assert indexed.loc["unknown", "gross_return"] == pytest.approx(0.1)
    assert indexed.loc["unknown", "gross_return_basis"] == "total_return_local"
    assert not result["fx_values_invented"].any()
    assert pd.to_datetime(result["fx_exit_date"], errors="coerce").max() <= CUTOFF


def test_fx_enrichment_requires_frozen_cli_rates() -> None:
    opportunities = pd.DataFrame(
        {
            "currency": ["USD"],
            "currency_unknown": [False],
            "entry_date": ["2020-01-02"],
            "entry_price": [100.0],
            "entry_value_local_per_initial_share": [100.0],
            "exit_date": ["2020-01-03"],
            "exit_price": [101.0],
            "exit_value_local_per_initial_share": [101.0],
            "mtm_date": [None],
            "mtm_price": [np.nan],
            "dividends_local": [0.0],
            "dividend_payments_local_json": ["[]"],
            "total_return_local": [0.01],
            "status": ["completed"],
            "return_usd": [0.01],
            "price_scale_to_currency_unit": [1.0],
        }
    )

    with pytest.raises(ValueError, match="frozen FX rates are required"):
        enrich_fx_causally(opportunities, None)


def test_global_functional_count_comes_from_all_duplicate_audit_layers() -> None:
    audit = pd.DataFrame(
        {
            "combination_id": ["a", "b", "c", "a", "b", "c"],
            "functionally_duplicated": [True, True, False, False, False, True],
            "canonical_combination_id": ["a", "a", "c", "a", "b", "b"],
        }
    )

    mapping = _global_functional_mapping(audit, ["a", "b", "c"])

    assert mapping == {"a": "a", "b": "a", "c": "a"}
    assert len(set(mapping.values())) == 1


def test_prior_financing_is_reconciled_without_filtering_opportunities() -> None:
    manifest = pd.DataFrame(
        {
            "combination_id": ["exact", "other"],
            "entry_spec_id": ["entry-exact", "entry-other"],
        }
    )
    opportunities = pd.DataFrame(
        {
            "combination_id": ["exact", "other"],
            "entry_spec_id": ["entry-exact", "entry-other"],
            "symbol": ["AAA", "BBB"],
            "selection_date": ["2020-01-02", "2020-01-02"],
            "entry_date": ["2020-01-03", "2020-01-03"],
        }
    )
    prior = pd.DataFrame(
        {
            "opportunity_id": ["old-a"],
            "symbol": ["AAA"],
            "selection_date": ["2020-01-02"],
            "entry_date": ["2020-01-03"],
            "originally_financed": [True],
            "not_financed_reason": [""],
        }
    )

    result, reconciliation = reconcile_prior_financing(
        opportunities, manifest, {"candidate_id": "exact"}, prior
    )

    assert len(result) == len(opportunities)
    assert result.loc[0, "financed_in_old_portfolio"]
    assert result.loc[1, "financing_reconciliation_status"] == "not_applicable_different_entry_spec"
    assert reconciliation["informational_only"].all()


def test_prior_financing_reconciles_a_corrected_entry_date_by_selection() -> None:
    manifest = pd.DataFrame(
        {"combination_id": ["exact"], "entry_spec_id": ["entry-exact"]}
    )
    opportunities = pd.DataFrame(
        {
            "combination_id": ["exact"],
            "entry_spec_id": ["entry-exact"],
            "symbol": ["AAA"],
            "selection_date": ["2020-01-02"],
            "entry_date": ["2020-01-06"],
        }
    )
    prior = pd.DataFrame(
        {
            "opportunity_id": ["old-a"],
            "symbol": ["AAA"],
            "selection_date": ["2020-01-02"],
            "entry_date": ["2020-01-03"],
            "originally_financed": [True],
            "not_financed_reason": [""],
        }
    )

    result, reconciliation = reconcile_prior_financing(
        opportunities, manifest, {"candidate_id": "exact"}, prior
    )

    assert result.loc[0, "financed_in_old_portfolio"]
    assert (
        reconciliation.loc[0, "reconciliation_match_basis"]
        == "symbol_selection_date_entry_date_corrected"
    )


def test_prior_financing_keeps_new_corrected_opportunities_as_unfinanced() -> None:
    manifest = pd.DataFrame(
        {"combination_id": ["exact"], "entry_spec_id": ["entry-exact"]}
    )
    opportunities = pd.DataFrame(
        {
            "combination_id": ["exact", "exact"],
            "entry_spec_id": ["entry-exact", "entry-exact"],
            "symbol": ["AAA", "NEW"],
            "selection_date": ["2020-01-02", "2020-02-03"],
            "entry_date": ["2020-01-03", "2020-02-04"],
        }
    )
    prior = pd.DataFrame(
        {
            "opportunity_id": ["old-a"],
            "symbol": ["AAA"],
            "selection_date": ["2020-01-02"],
            "entry_date": ["2020-01-03"],
            "originally_financed": [True],
            "not_financed_reason": [""],
        }
    )

    result, reconciliation = reconcile_prior_financing(
        opportunities, manifest, {"candidate_id": "exact"}, prior
    )

    assert len(result) == 2
    assert not result.loc[1, "financed_in_old_portfolio"]
    assert (
        result.loc[1, "financing_reconciliation_status"]
        == "new_corrected_opportunity_not_in_prior_audit"
    )
    assert reconciliation["reconciled"].all()
    assert reconciliation["present_in_prior_audit"].tolist() == [True, False]


def test_prior_unresolved_gap_is_retained_as_failed_due_to_data() -> None:
    manifest = pd.DataFrame(
        {
            "combination_id": ["exact"],
            "entry_spec_id": ["entry-exact"],
            "exit_spec_id": ["exit-exact"],
        }
    )
    opportunities = pd.DataFrame(
        {
            "opportunity_id": ["new-a"],
            "combination_id": ["exact"],
            "entry_spec_id": ["entry-exact"],
            "exit_spec_id": ["exit-exact"],
            "period": ["A"],
            "status": ["completed"],
            "symbol": ["AAA"],
            "selection_date": ["2009-01-02"],
            "signal_date": ["2009-01-02"],
            "entry_signal_date": ["2009-01-02"],
            "entry_date": ["2009-01-05"],
        }
    )
    prior = pd.DataFrame(
        {
            "opportunity_id": ["old-a", "old-gap"],
            "symbol": ["AAA", "GAP"],
            "selection_date": ["2009-01-02", None],
            "signal_date": ["2009-01-02", "2009-02-02"],
            "entry_date": ["2009-01-05", "2009-02-03"],
            "originally_financed": [True, False],
            "not_financed_reason": ["", "rejected_insufficient_capital"],
        }
    )

    result, reconciliation = reconcile_prior_financing(
        opportunities, manifest, {"candidate_id": "exact"}, prior
    )

    gap = result.loc[result["symbol"].eq("GAP")].iloc[0]
    assert gap["status"] == "failed_due_to_data"
    assert gap["period"] == "A"
    assert not gap["capital_rejected"]
    assert gap["prior_audit_opportunity_id"] == "old-gap"
    assert pd.isna(gap["selection_date"])
    assert gap["signal_date"] == "2009-02-02"
    assert gap["entry_signal_date"] == "2009-02-02"
    assert gap["entry_date"] == "2009-02-03"
    assert " " not in gap["signal_date"]
    assert " " not in gap["entry_date"]
    assert result["entry_date"].dropna().map(type).eq(str).all()
    assert reconciliation["entry_date"].dropna().map(type).eq(str).all()
    pd.to_datetime(result["selection_date"], errors="raise")
    pd.to_datetime(result["entry_date"], errors="raise")
    assert reconciliation["reconciled"].all()


def test_summary_verifier_rejects_wrong_contract_and_selection_claim(tmp_path: Path) -> None:
    summary = _summary()
    (tmp_path / AUDIT_SUMMARY_NAME).write_text(json.dumps(summary), encoding="utf-8")
    assert _verify_summary(tmp_path)["contract"] == "290-10-29"

    summary["exit_spec_count"] = 28
    (tmp_path / AUDIT_SUMMARY_NAME).write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(EventStudy290VerificationError, match="exit_spec_count"):
        _verify_summary(tmp_path)

    summary["exit_spec_count"] = 29
    summary["validation_used_for_selection"] = True
    (tmp_path / AUDIT_SUMMARY_NAME).write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(EventStudy290VerificationError, match="validation_used_for_selection"):
        _verify_summary(tmp_path)


def test_manifest_verifier_rejects_hash_mutation(tmp_path: Path) -> None:
    payload = tmp_path / "payload.csv"
    payload.write_text("value\n1\n", encoding="utf-8")
    manifest = _artifact_manifest(tmp_path)
    (tmp_path / FINAL_MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    _verify_manifest(tmp_path)

    payload.write_text("value\n2\n", encoding="utf-8")
    with pytest.raises(EventStudy290VerificationError, match="sha256"):
        _verify_manifest(tmp_path)


def test_report_has_exactly_25_questions_and_separate_epistemic_sections(
    tmp_path: Path,
) -> None:
    report = _report(
        _summary(),
        {
            "matrix_rows": 12,
            "pbo": 0.25,
            "entry_spec_id": "entry-00",
            "declared_tests": 290,
            "eligible_tests": 260,
            "functionally_unique_tests": 240,
        },
        _report_statistics(),
        pd.DataFrame(
            {
                "entry_spec_id": ["entry-00", "entry-00"],
                "triggered": [True, False],
                "wait_sessions": [1, 21],
            }
        ),
        pd.DataFrame(
            {
                "combination_id": ["best"],
                "entry_spec_id": ["entry-00"],
                "exit_spec_id": ["exit-00"],
            }
        ),
    )
    (tmp_path / FINAL_REPORT_NAME).write_text(report, encoding="utf-8")

    _verify_report(tmp_path)

    assert report.count("¿") == 25
    assert report.count("Resultado:") == 25
    assert all(f"[Q{number:02d}]" in report for number in range(1, 26))
    assert "## Hechos" in report
    assert "## Inferencias" in report
    assert "## Limitaciones" in report
    assert "`best`" in report
    assert "¿Qué entrada activó más oportunidades?" in report
    assert "¿Qué salida mejoró más el retorno por sesión?" in report
    assert "¿Cuál sería la mejor candidata para congelar prospectivamente?" in report
    assert "ninguna oportunidad fue excluida por capital" in report


def test_fx_rate_after_cutoff_fails() -> None:
    opportunities = pd.DataFrame(
        {
            "opportunity_id": ["eur"],
            "combination_id": ["c-00-00"],
            "status": ["completed"],
            "symbol": ["EU"],
            "currency": ["EUR"],
            "currency_unknown": [False],
            "entry_date": pd.to_datetime(["2026-07-16"]),
            "entry_price": [100.0],
            "entry_value_local_per_initial_share": [100.0],
            "exit_date": pd.to_datetime(["2026-07-17"]),
            "exit_price": [101.0],
            "exit_value_local_per_initial_share": [101.0],
            "mtm_date": pd.to_datetime([None]),
            "mtm_price": [np.nan],
            "dividends_local": [0.0],
            "dividend_payments_local_json": ["[]"],
            "total_return_local": [0.01],
            "price_scale_to_currency_unit": [1.0],
            "return_usd": [np.nan],
        }
    )
    rates = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-18"]),
            "currency": ["EUR"],
            "usd_per_local": [1.2],
        }
    )

    with pytest.raises(ValueError, match="cutoff"):
        enrich_fx_causally(opportunities, rates)
