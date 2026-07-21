from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research.stock_protocol.event_study_290_statistics import (
    COSTS_BPS_PER_SIDE,
    CONTRACT_CLASSIFICATIONS,
    PILLARS,
    REQUIRED_OBJECTIVES,
    add_event_efficiency_metrics,
    benjamini_hochberg,
    censoring_audit,
    cluster_bootstrap_confidence_intervals,
    concentration_statistics,
    cscv_pbo,
    deflated_event_statistic,
    detect_functional_duplicates,
    event_study_290_statistics,
    holm_adjust,
    leave_one_out_audit,
    metric_cuts,
    metrics_by_combination,
    objective_winners,
    paired_variant_comparison,
    prepare_opportunity_ledger,
    rank_combinations,
    survival_incidence_table,
    westfall_young_max_t,
    white_spa_equivalent,
)


def _ledger() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    countries = (("US", "NYSE", "USD"), ("GB", "LSE", "GBP"))
    for combination_index, combination in enumerate(("A", "B")):
        for index in range(12):
            year = 2018 + index // 3
            censored = index == 11
            gross_return = 0.02 + combination_index * 0.01 + (index % 4 - 1) * 0.01
            if index in (3, 7):
                gross_return = -0.03 + combination_index * 0.005
            country, market, currency = countries[index % 2]
            rows.append(
                {
                    "combination_id": combination,
                    "opportunity_id": f"{combination}-{index}",
                    "symbol": f"S{index % 4}",
                    "signal_date": pd.Timestamp(f"{year}-01-{index % 3 + 2:02d}"),
                    "entry_date": pd.Timestamp(f"{year}-01-{index % 3 + 3:02d}"),
                    "gross_return": np.nan if censored else gross_return,
                    "holding_sessions": 5 + index % 3,
                    "maximum_adverse_excursion": -(0.02 + index % 3 * 0.01),
                    "event_type": "censored" if censored else ("target" if index % 3 == 0 else "stop" if index % 5 == 0 else "time"),
                    "censored": censored,
                    "period": "development",
                    "country": country,
                    "market": market,
                    "currency": currency,
                }
            )
    return pd.DataFrame(rows)


def _protocol_ledger() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for combination_index in range(290):
        combination = f"C{combination_index:03d}"
        for index in range(8):
            date = pd.Timestamp(f"{2018 + index}-01-02")
            rows.append(
                {
                    "combination_id": combination,
                    "opportunity_id": f"{combination}-{index}",
                    "symbol": f"S{index}",
                    "signal_date": date,
                    "entry_date": date + pd.Timedelta(days=1),
                    "gross_return": 0.01 + combination_index * 1e-6 + index * 1e-4,
                    "holding_sessions": 2 + index % 3,
                    "maximum_adverse_excursion": -0.02,
                    "event_type": "target" if index % 2 == 0 else "time",
                    "censored": False,
                    "period": "development",
                    "selection_role": "development",
                    "country": "US",
                    "market": "NYSE",
                    "currency": "USD",
                }
            )
    return pd.DataFrame(rows)


def test_prepare_and_efficiency_metrics_cover_complete_and_censored_events() -> None:
    prepared = prepare_opportunity_ledger(_ledger())
    assert prepared["censored"].sum() == 2
    assert prepared.loc[prepared["censored"], "event_return"].isna().all()

    enriched = add_event_efficiency_metrics(_ledger(), cost_bps_per_side=25)
    first = enriched.iloc[0]
    assert first["net_event_return"] == pytest.approx(first["gross_return"] - 0.005)
    assert first["event_return_to_mae"] == pytest.approx(
        first["net_event_return"] / abs(first["maximum_adverse_excursion"])
    )
    assert first["event_speed"] == pytest.approx(
        np.log1p(first["net_event_return"]) / first["holding_sessions"]
    )
    assert first["event_risk_adjusted_speed"] == pytest.approx(
        first["event_return_to_risk"] / first["holding_sessions"]
    )


def test_required_cost_grid_and_combination_metrics_exclude_portfolio_metrics() -> None:
    metrics = metrics_by_combination(_ledger())
    assert tuple(sorted(metrics["cost_bps_per_side"].unique())) == COSTS_BPS_PER_SIDE
    assert len(metrics) == 2 * len(COSTS_BPS_PER_SIDE)
    assert not {"cagr", "sharpe", "portfolio_sharpe"} & set(metrics.columns)
    zero = metrics.loc[
        metrics["combination_id"].eq("A") & metrics["cost_bps_per_side"].eq(0),
        "mean_return",
    ].iloc[0]
    expensive = metrics.loc[
        metrics["combination_id"].eq("A") & metrics["cost_bps_per_side"].eq(200),
        "mean_return",
    ].iloc[0]
    assert expensive == pytest.approx(zero - 0.04)
    non_bootstrap = {
        objective
        for objective in REQUIRED_OBJECTIVES
        if not objective.startswith("bootstrap_")
    }
    assert non_bootstrap <= set(metrics.columns)


def test_contractual_tail_risk_speed_mae_and_duration_formulas_are_literal() -> None:
    metrics = metrics_by_combination(
        _ledger().loc[lambda frame: frame["combination_id"].eq("A")],
        costs_bps_per_side=(0,),
    ).iloc[0]
    observed = add_event_efficiency_metrics(
        _ledger().loc[lambda frame: frame["combination_id"].eq("A")]
    ).loc[lambda frame: frame["event_observed"]]
    returns = observed["net_event_return"].to_numpy(dtype=float)
    downside = returns[returns < 0.0]
    es05 = np.sort(returns)[: max(1, int(np.ceil(len(returns) * 0.05)))].mean()
    es10 = np.sort(returns)[: max(1, int(np.ceil(len(returns) * 0.10)))].mean()
    median_return = np.median(returns)
    median_mae_abs = add_event_efficiency_metrics(
        _ledger().loc[lambda frame: frame["combination_id"].eq("A")]
    )["event_mae"].abs().median()

    assert metrics["event_speed"] == pytest.approx(
        np.median(np.log1p(returns) / observed["event_duration"].to_numpy())
    )
    assert metrics["semivariance"] == pytest.approx(np.mean(downside**2))
    assert metrics["downside_deviation"] == pytest.approx(
        np.sqrt(np.mean(downside**2))
    )
    assert metrics["expected_shortfall_5"] == pytest.approx(es05)
    assert metrics["expected_shortfall_05"] == pytest.approx(es05)
    assert metrics["expected_shortfall_10"] == pytest.approx(es10)
    assert metrics["event_return_to_risk"] == pytest.approx(
        median_return / abs(es10)
    )
    assert metrics["event_return_to_mae"] == pytest.approx(
        median_return / median_mae_abs
    )
    assert metrics["duration_p90"] == pytest.approx(
        np.quantile(_ledger().query("combination_id == 'A'")["holding_sessions"], 0.9)
    )


def test_period_geography_cuts_and_censoring_audit_are_complete() -> None:
    cuts = metric_cuts(_ledger())
    assert {"period", "year", "decade", "country", "market", "currency"} == set(cuts["cut"])
    audit = censoring_audit(_ledger(), group_columns=("country",))
    assert int(audit["opportunities"].sum()) == len(_ledger())
    assert int(audit["censored_events"].sum()) == 2


def test_kaplan_meier_and_competing_incidence_handle_ties_and_censoring() -> None:
    ledger = pd.DataFrame(
        {
            "combination_id": ["A"] * 4,
            "opportunity_id": ["A-1", "A-2", "A-3", "A-4"],
            "symbol": ["A", "B", "C", "D"],
            "entry_date": ["2020-01-01"] * 4,
            "gross_return": [0.5, -0.2, np.nan, 0.1],
            "holding_sessions": [1, 2, 2, 3],
            "maximum_adverse_excursion": [-0.1] * 4,
            "event_type": ["target", "stop", "censored", "other"],
            "censored": [False, False, True, False],
        }
    )
    table = survival_incidence_table(ledger)
    first = table.iloc[0]
    second = table.iloc[1]
    assert first["kaplan_meier_survival"] == pytest.approx(0.75)
    assert first["target_cumulative_incidence"] == pytest.approx(0.25)
    assert second["stop_cumulative_incidence"] == pytest.approx(0.25)
    assert table["kaplan_meier_survival"].is_monotonic_decreasing


def test_paired_comparison_uses_causal_keys_and_seeded_paired_bootstrap() -> None:
    base = _ledger().loc[lambda frame: frame["combination_id"].eq("A")].copy()
    baseline = base.assign(
        variant="baseline",
        combination_id="pair",
        opportunity_id=base["opportunity_id"] + "-baseline",
    )
    challenger = base.assign(
        variant="challenger",
        combination_id="pair",
        opportunity_id=base["opportunity_id"] + "-challenger",
        gross_return=base["gross_return"] + 0.01,
    )
    paired = pd.concat([baseline, challenger], ignore_index=True)
    first_summary, first_records = paired_variant_comparison(
        paired,
        variant_column="variant",
        baseline="baseline",
        challenger="challenger",
        causal_keys=("symbol", "signal_date"),
        bootstrap_samples=40,
        seed=7,
    )
    second_summary, second_records = paired_variant_comparison(
        paired,
        variant_column="variant",
        baseline="baseline",
        challenger="challenger",
        causal_keys=("symbol", "signal_date"),
        bootstrap_samples=40,
        seed=7,
    )
    pd.testing.assert_frame_equal(first_summary, second_summary)
    pd.testing.assert_frame_equal(first_records, second_records)
    assert first_summary.iloc[0]["mean_delta"] == pytest.approx(0.01)
    assert first_summary.iloc[0]["pairs"] == 11
    assert first_summary.iloc[0]["primary_inference_method"].endswith(
        "cluster_centered_bootstrap"
    )
    assert 0 <= first_summary.iloc[0]["primary_pvalue"] <= 1
    assert first_summary.iloc[0]["sign_test_evidence_role"].startswith("diagnostic_")
    assert str(first_summary.iloc[0]["wilcoxon_method"]).startswith(("scipy_", "explicit_"))


def test_cluster_bootstrap_is_reproducible_for_all_required_clusters() -> None:
    first_summary, first_records = cluster_bootstrap_confidence_intervals(
        _ledger(), bootstrap_samples=20, seed=11
    )
    second_summary, second_records = cluster_bootstrap_confidence_intervals(
        _ledger(), bootstrap_samples=20, seed=11
    )
    pd.testing.assert_frame_equal(first_summary, second_summary)
    pd.testing.assert_frame_equal(first_records, second_records)
    assert set(first_summary["method"]) == {"symbol", "year", "hierarchical_year_symbol"}
    assert set(first_summary["metric"]) == {"mean_return", "median_return", "event_speed"}
    assert isinstance(first_records["combination_id"].dtype, pd.CategoricalDtype)
    assert isinstance(first_records["method"].dtype, pd.CategoricalDtype)
    assert len(first_records) == 2 * 3 * 20


def test_cluster_bootstrap_array_path_matches_degenerate_cluster_estimates() -> None:
    ledger = _ledger().loc[lambda frame: frame["combination_id"].eq("A")].copy()
    ledger["symbol"] = "ONLY"
    ledger["entry_date"] = pd.Timestamp("2020-01-02")
    summary, records = cluster_bootstrap_confidence_intervals(
        ledger, bootstrap_samples=25, seed=19
    )
    expected = add_event_efficiency_metrics(ledger).loc[
        lambda frame: frame["event_observed"]
    ]
    assert np.allclose(records["mean_return"], expected["net_event_return"].mean())
    assert np.allclose(records["median_return"], expected["net_event_return"].median())
    assert np.allclose(records["event_speed"], expected["event_speed"].median())
    assert summary["ci_low95"].equals(summary["ci_high95"])


def test_leave_one_out_and_concentration_cover_requested_stress_tests() -> None:
    leave_out = leave_one_out_audit(_ledger())
    assert {"year", "symbol", "country", "market", "top5_symbols", "top20_symbols"} <= set(
        leave_out["omission"]
    )
    concentration = concentration_statistics(_ledger())
    assert concentration["concentration_hhi"].between(0, 1).all()
    assert concentration["concentration_top5"].between(0, 1).all()
    assert concentration["concentration_top20"].between(0, 1).all()


def test_multiple_testing_adjustments_are_monotone_and_bounded() -> None:
    pvalues = np.array([0.01, 0.04, 0.03, 0.20])
    bh = benjamini_hochberg(pvalues)
    holm = holm_adjust(pvalues)
    assert np.all((0 <= bh) & (bh <= 1))
    assert np.all((0 <= holm) & (holm <= 1))
    assert np.all(bh >= pvalues)
    assert np.all(holm >= pvalues)
    assert bh[0] == pytest.approx(0.04)
    assert holm[0] == pytest.approx(0.04)


def test_max_t_white_spa_cscv_and_deflated_event_statistic_are_reproducible() -> None:
    returns = pd.DataFrame(
        {
            "A": [0.03, 0.01, -0.01, 0.02, 0.01, 0.04, -0.02, 0.03],
            "B": [0.01, -0.02, 0.01, 0.00, -0.01, 0.02, 0.01, 0.00],
            "C": [-0.01, 0.00, -0.02, 0.01, -0.01, 0.00, -0.03, 0.01],
        }
    )
    returns.index = pd.date_range("2018-01-01", periods=len(returns), freq="YS")
    clusters = pd.DataFrame(
        {
            "symbol": ["X", "X", "Y", "Y", "Z", "Z", "W", "W"],
            "entry_year": [2019, 2019, 2019, 2019, 2020, 2020, 2020, 2020],
        }
    )
    max_t_a = westfall_young_max_t(
        returns, cluster_frame=clusters, bootstrap_samples=30, seed=5
    )
    max_t_b = westfall_young_max_t(
        returns, cluster_frame=clusters, bootstrap_samples=30, seed=5
    )
    pd.testing.assert_frame_equal(max_t_a, max_t_b)
    assert max_t_a["method"].str.contains("equivalent").all()

    white_spa = white_spa_equivalent(
        returns, cluster_frame=clusters, bootstrap_samples=30, seed=5
    )
    assert set(white_spa["test"]) == {"white_reality_check", "spa"}
    assert white_spa["method"].str.contains("equivalent").all()
    pbo = cscv_pbo(returns, partitions=4)
    assert 0 <= pbo["pbo"] <= 1
    assert pbo["splits"] == 6
    assert pbo["rank_method"] == "average"

    few = deflated_event_statistic(returns["A"], trials=2)
    many = deflated_event_statistic(returns["A"], trials=290)
    assert many["deflated_event_statistic"] < few["deflated_event_statistic"]
    assert not many["cluster_robust"]
    assert str(many["evidence_role"]).startswith("diagnostic_non_cluster_robust")


def test_functional_duplicates_are_detected_independently() -> None:
    specs = pd.DataFrame(
        {
            "combination_id": ["A", "B", "C"],
            "entry": ["next_open", "next_open", "breakout"],
            "exit": ["target", "target", "target"],
        }
    )
    trades = pd.DataFrame(
        {
            "combination_id": ["A", "B", "C"],
            "symbol": ["X", "X", "Y"],
            "gross_return": [0.1, 0.1, 0.1],
        }
    )
    results = pd.DataFrame(
        {
            "combination_id": ["A", "B", "C"],
            "mean_return": [0.1, 0.1, 0.2],
        }
    )
    duplicates = detect_functional_duplicates(specs, trades, results)
    duplicated = duplicates.loc[duplicates["combination_id"].isin(["A", "B"])]
    assert duplicated["functionally_duplicated"].all()
    assert set(duplicated["duplicate_type"]) == {"spec", "trades", "results"}
    assert not duplicates.loc[duplicates["combination_id"].eq("C"), "functionally_duplicated"].any()


def _ranking_metrics() -> pd.DataFrame:
    rows = []
    for index, combination in enumerate(("balanced", "specialist", "locked_best")):
        row: dict[str, object] = {
            "combination_id": combination,
            "selection_role": "locked" if combination == "locked_best" else "development",
            "opportunities": 240,
            "complete_events": 240,
            "minimum_period_opportunities": 60,
            "minimum_period_complete_events": 60,
        }
        for objective, direction in REQUIRED_OBJECTIVES.items():
            if combination == "balanced":
                value = 0.7 if direction > 0 else 0.3
            elif combination == "specialist":
                value = 0.9 if objective == "mean_return" else (0.5 if direction > 0 else 0.5)
            else:
                value = 1.0 if direction > 0 else 0.0
            row[objective] = value
        rows.append(row)
    return pd.DataFrame(rows)


def test_pareto_uses_six_contractual_pillars_and_winners_exclude_locked() -> None:
    ranked = rank_combinations(_ranking_metrics())
    locked = ranked.loc[ranked["combination_id"].eq("locked_best")].iloc[0]
    assert not locked["selection_eligible"]
    assert locked["classification"] == "not_supported"
    assert pd.isna(locked["pareto_rank"])
    assert {
        "return_percentile",
        "risk_percentile",
        "time_percentile",
        "stability_percentile",
        "concentration_percentile",
        "bootstrap_percentile",
    } <= set(ranked.columns)
    assert set(PILLARS) == {
        "return",
        "risk",
        "time",
        "stability",
        "concentration",
        "bootstrap",
    }
    assert ranked.loc[ranked["selection_eligible"], "balanced_score"].between(0, 1).all()
    assert ranked.loc[ranked["selection_eligible"], "ideal_distance"].ge(0).all()

    winners = objective_winners(ranked)
    assert winners["objective"].nunique() == len(REQUIRED_OBJECTIVES)
    assert "locked_best" not in set(winners["combination_id"])


def test_ranking_respects_aggregated_development_eligibility_without_roles() -> None:
    aggregated = _ranking_metrics().drop(columns=["selection_role"])
    aggregated["selection_eligible"] = [True, True, False]

    ranked = rank_combinations(aggregated)

    assert ranked["selection_eligible"].tolist() == [True, True, False]
    assert ranked.loc[ranked["selection_eligible"], "pareto_rank"].notna().all()
    assert ranked.loc[~ranked["selection_eligible"], "classification"].eq(
        "not_supported"
    ).all()


def test_contractual_terminal_classifications_have_explicit_precedence() -> None:
    base = pd.concat([_ranking_metrics().iloc[[0]]] * 7, ignore_index=True)
    base["combination_id"] = [
        "supported",
        "small",
        "thin-period",
        "duplicate",
        "not-applicable",
        "invalid",
        "unsupported",
    ]
    base["selection_role"] = "development"
    base["functionally_duplicated"] = [
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    base["applicability"] = [
        "applicable",
        "applicable",
        "applicable",
        "applicable",
        "not_applicable",
        "applicable",
        "applicable",
    ]
    base.loc[base["combination_id"].eq("small"), "opportunities"] = 199
    base.loc[base["combination_id"].eq("small"), "complete_events"] = 199
    base.loc[
        base["combination_id"].eq("thin-period"),
        "minimum_period_complete_events",
    ] = 29
    base.loc[base["combination_id"].eq("invalid"), "mean_return"] = np.nan
    base.loc[
        base["combination_id"].eq("unsupported"),
        "bootstrap_mean_return_ci_low95",
    ] = -0.01

    ranked = rank_combinations(base).set_index("combination_id")

    assert ranked.loc["supported", "classification"] == "robust_leader"
    assert ranked.loc["small", "classification"] == "insufficient_sample"
    assert ranked.loc["thin-period", "classification"] == "insufficient_sample"
    assert ranked.loc["duplicate", "classification"] == "functionally_duplicate"
    assert ranked.loc["not-applicable", "classification"] == "not_applicable"
    assert ranked.loc["invalid", "classification"] == "invalid_due_to_data"
    assert ranked.loc["unsupported", "classification"] == "not_supported"
    assert set(CONTRACT_CLASSIFICATIONS) == {
        "robust_leader",
        "pareto_promising",
        "high_return_high_risk",
        "low_risk_low_return",
        "fast_but_unstable",
        "period_dependent",
        "not_supported",
        "not_applicable",
        "functionally_duplicate",
        "invalid_due_to_data",
        "insufficient_sample",
    }


def test_invalid_complete_return_and_duplicate_causal_keys_fail_closed() -> None:
    invalid = _ledger().copy()
    invalid.loc[0, "gross_return"] = np.nan
    invalid.loc[0, "censored"] = False
    with pytest.raises(ValueError, match="complete opportunities"):
        prepare_opportunity_ledger(invalid)

    pair = _ledger().loc[lambda frame: frame["combination_id"].eq("A")].copy()
    pair["variant"] = "baseline"
    pair["opportunity_id"] = pair["opportunity_id"] + "-baseline"
    duplicate = pd.concat([pair, pair.iloc[[0]]], ignore_index=True)
    duplicate.loc[duplicate.index[-1], "opportunity_id"] += "-duplicate"
    challenger = pair.assign(
        variant="challenger",
        opportunity_id=pair["opportunity_id"] + "-challenger",
        gross_return=pair["gross_return"] + 0.01,
    )
    with pytest.raises(ValueError, match="causal keys"):
        paired_variant_comparison(
            pd.concat([duplicate, challenger], ignore_index=True),
            variant_column="variant",
            baseline="baseline",
            challenger="challenger",
            bootstrap_samples=10,
        )


def test_identifiers_are_required_non_null_and_unique_per_combination() -> None:
    for column in ("combination_id", "opportunity_id"):
        invalid = _ledger().copy()
        invalid.loc[0, column] = None
        with pytest.raises(ValueError, match="null or empty identifiers"):
            prepare_opportunity_ledger(invalid)

    blank = _ledger().copy()
    blank.loc[0, "opportunity_id"] = "  "
    with pytest.raises(ValueError, match="null or empty identifiers"):
        prepare_opportunity_ledger(blank)

    duplicate = _ledger().copy()
    duplicate.loc[1, "opportunity_id"] = duplicate.loc[0, "opportunity_id"]
    with pytest.raises(ValueError, match="unique within each combination"):
        prepare_opportunity_ledger(duplicate)


def test_all_role_columns_are_checked_and_unknown_roles_fail_closed() -> None:
    no_role = prepare_opportunity_ledger(_ledger().drop(columns=["period"]))
    assert not no_role["selection_eligible"].any()

    ledger = pd.concat([_ledger().iloc[[0]]] * 5, ignore_index=True)
    ledger["opportunity_id"] = [f"role-{index}" for index in range(5)]
    ledger["selection_role"] = "development"
    ledger["period_role"] = "IS_TRAIN"
    ledger["period"] = "development"
    ledger["tier"] = ["OOS_DEV", "IS_VALID", "OOS_LOCKED", "FORWARD", "mystery"]
    prepared = prepare_opportunity_ledger(ledger)
    assert prepared["selection_eligible"].tolist() == [True, False, False, False, False]

    ledger["validation_used_for_selection"] = [False, False, False, False, True]
    prepared = prepare_opportunity_ledger(ledger)
    assert not prepared.iloc[-1]["selection_eligible"]


def test_event_state_indicators_are_normalized_or_rejected_as_one_contract() -> None:
    valid = _ledger().copy()
    valid["event_observed"] = ~valid["censored"]
    prepared = prepare_opportunity_ledger(valid)
    assert (prepared["event_observed"] == ~prepared["censored"]).all()
    assert prepared["event_type"].eq("censored").equals(prepared["censored"])

    contradictory_observed = valid.copy()
    contradictory_observed.loc[0, "event_observed"] = False
    with pytest.raises(ValueError, match="exact complements"):
        prepare_opportunity_ledger(contradictory_observed)

    contradictory_type = valid.copy()
    contradictory_type.loc[0, "event_type"] = "censored"
    with pytest.raises(ValueError, match="event_type and censoring"):
        prepare_opportunity_ledger(contradictory_type)

    contradictory_alias = valid.copy()
    contradictory_alias["is_censored"] = contradictory_alias["censored"]
    contradictory_alias.loc[0, "is_censored"] = True
    with pytest.raises(ValueError, match="censored aliases disagree"):
        prepare_opportunity_ledger(contradictory_alias)

    realized_censor = valid.copy()
    realized_censor.loc[realized_censor["censored"].idxmax(), "gross_return"] = 0.1
    with pytest.raises(ValueError, match="censored opportunities"):
        prepare_opportunity_ledger(realized_censor)

    contradictory_outcome = valid.copy()
    contradictory_outcome["outcome"] = contradictory_outcome["event_type"]
    contradictory_outcome.loc[0, "outcome"] = "stop"
    with pytest.raises(ValueError, match="event outcome aliases disagree"):
        prepare_opportunity_ledger(contradictory_outcome)

    contradictory_exit = valid.copy()
    contradictory_exit["exit_reason"] = contradictory_exit["event_type"]
    contradictory_exit.loc[0, "exit_reason"] = "stop"
    with pytest.raises(ValueError, match="event outcome aliases disagree"):
        prepare_opportunity_ledger(contradictory_exit)

    target_censor = valid.iloc[[0]].drop(columns=["event_type"]).copy()
    target_censor["gross_return"] = np.nan
    target_censor["censored"] = True
    target_censor["event_observed"] = False
    target_censor["target_hit"] = True
    with pytest.raises(ValueError, match="target_hit contradicts censoring"):
        prepare_opportunity_ledger(target_censor)

    stop_censor = target_censor.assign(target_hit=False, stop_hit=True)
    with pytest.raises(ValueError, match="stop_hit contradicts censoring"):
        prepare_opportunity_ledger(stop_censor)


def test_costs_require_gross_returns_and_never_double_charge_net_returns() -> None:
    ambiguous = _ledger().rename(columns={"gross_return": "event_return"})
    with pytest.raises(ValueError, match="explicitly gross or net"):
        prepare_opportunity_ledger(ambiguous)

    net_only = _ledger().rename(columns={"gross_return": "net_return"})
    unchanged = add_event_efficiency_metrics(net_only, cost_bps_per_side=0)
    assert unchanged.iloc[0]["net_event_return"] == pytest.approx(net_only.iloc[0]["net_return"])
    with pytest.raises(ValueError, match="gross returns"):
        add_event_efficiency_metrics(net_only, cost_bps_per_side=5)
    with pytest.raises(ValueError, match="gross returns"):
        add_event_efficiency_metrics(unchanged, cost_bps_per_side=5)

    both = _ledger().copy()
    both["net_return"] = both["gross_return"] - 0.50
    charged_from_gross = add_event_efficiency_metrics(both, cost_bps_per_side=25)
    assert charged_from_gross.iloc[0]["net_event_return"] == pytest.approx(
        both.iloc[0]["gross_return"] - 0.005
    )


def test_ranking_survival_objectives_use_km_and_common_horizon() -> None:
    ledger = pd.DataFrame(
        {
            "combination_id": ["A"] * 4,
            "opportunity_id": ["A-1", "A-2", "A-3", "A-4"],
            "symbol": ["A", "B", "C", "D"],
            "entry_date": ["2020-01-01"] * 4,
            "gross_return": [np.nan, 0.4, 0.1, -0.1],
            "holding_sessions": [1, 2, 3, 3],
            "maximum_adverse_excursion": [-0.1] * 4,
            "event_type": ["censored", "target", "other", "other"],
            "censored": [True, False, False, False],
            "period": ["development"] * 4,
        }
    )
    metrics = metrics_by_combination(ledger, costs_bps_per_side=(0,)).iloc[0]
    assert metrics["common_horizon"] == 3
    assert metrics["target_cumulative_incidence"] == pytest.approx(1 / 3)
    assert metrics["target_cumulative_incidence"] != pytest.approx(1 / 4)
    assert metrics["km_median_duration"] == 3
    assert metrics["km_median_duration"] != metrics["duration_median"]
    assert {
        "target_cumulative_incidence",
        "stop_cumulative_incidence",
        "km_median_duration",
    } <= set(REQUIRED_OBJECTIVES)


def test_missing_mandatory_cut_fails_instead_of_silently_disappearing() -> None:
    with pytest.raises(ValueError, match="mandatory cuts"):
        metric_cuts(_ledger().drop(columns=["currency"]))
    with pytest.raises(ValueError, match="mandatory cuts omitted"):
        metric_cuts(_ledger(), cuts=("period", "year", "decade", "country", "market"))
    for value in (None, ""):
        invalid = _ledger().copy()
        invalid.loc[0, "country"] = value
        with pytest.raises(ValueError, match="mandatory cut country"):
            metric_cuts(invalid)


def test_pbo_collapses_functional_duplicates_and_uses_average_tie_ranks() -> None:
    returns = pd.DataFrame(
        {
            "A": [0.1, 0.0, 0.1, 0.0, 0.1, 0.0, 0.1, 0.0],
            "B": [0.1, 0.0, 0.1, 0.0, 0.1, 0.0, 0.1, 0.0],
            "C": [0.0, 0.1, 0.0, 0.1, 0.0, 0.1, 0.0, 0.1],
            "D": [-0.1, 0.0, -0.1, 0.0, -0.1, 0.0, -0.1, 0.0],
        }
    )
    returns.index = pd.date_range("2018-01-01", periods=len(returns), freq="YS")
    result = cscv_pbo(returns, partitions=4)
    assert result["effective_combinations"] == 3
    assert result["rank_method"] == "average"
    duplicate = next(
        group for group in result["duplicate_groups"] if group["canonical_combination_id"] == "A"
    )
    assert duplicate["members"] == ["A", "B"]
    assert duplicate["excluded_duplicates"] == ["B"]

    audit = pd.DataFrame(
        {
            "combination_id": ["A", "C"],
            "functionally_duplicated": [True, True],
            "canonical_combination_id": ["A", "A"],
        }
    )
    audited = cscv_pbo(returns, partitions=4, functional_duplicates=audit)
    assert audited["effective_combinations"] == 2
    assert any(
        group["source"] == "functional_duplicate_audit"
        and group["excluded_duplicates"] == ["C"]
        for group in audited["duplicate_groups"]
    )


def test_pbo_is_tie_symmetric_order_invariant_and_keeps_dates_whole() -> None:
    dates = pd.to_datetime(
        ["2020-01-01", "2020-01-01", "2020-02-01", "2020-02-01",
         "2020-03-01", "2020-03-01", "2020-04-01", "2020-04-01"]
    )
    returns = pd.DataFrame(
        {
            "A": [1.1, 0.9, 1.2, 0.8, 0.1, -0.1, 0.2, -0.2],
            "B": [0.9, 1.1, 0.8, 1.2, 1.1, 0.9, -0.9, -1.1],
            "C": [-0.2, -0.1, -0.3, -0.2, -0.1, -0.2, -0.3, -0.1],
        },
        index=dates,
    )
    first = cscv_pbo(returns, partitions=4)
    reordered = returns.iloc[[7, 2, 5, 0, 6, 1, 4, 3]][["C", "B", "A"]]
    second = cscv_pbo(reordered, partitions=4)

    assert first["pbo"] == second["pbo"]
    np.testing.assert_allclose(first["logits"], second["logits"])
    assert first["selected_combinations"] == second["selected_combinations"]
    assert any(len(winners) > 1 for winners in first["selected_combinations"])
    assert all(partition["dates"] == 1 for partition in first["partition_date_ranges"])
    assert all(partition["rows"] == 2 for partition in first["partition_date_ranges"])


def test_paired_and_multiple_testing_bootstraps_report_cluster_methods() -> None:
    base = _ledger().loc[lambda frame: frame["combination_id"].eq("A")].copy()
    paired = pd.concat(
        [
            base.assign(
                variant="base",
                combination_id="pair",
                opportunity_id=base["opportunity_id"] + "-base",
            ),
            base.assign(
                variant="new",
                combination_id="pair",
                opportunity_id=base["opportunity_id"] + "-new",
                gross_return=base["gross_return"] + 0.01,
            ),
        ],
        ignore_index=True,
    )
    summary, records = paired_variant_comparison(
        paired,
        variant_column="variant",
        baseline="base",
        challenger="new",
        bootstrap_cluster="hierarchical_year_symbol",
        bootstrap_samples=20,
        seed=13,
    )
    assert summary.iloc[0]["bootstrap_method"] == "paired_hierarchical_year_symbol_cluster"
    assert np.allclose(records["paired_mean_delta"], 0.01)

    matrix = pd.DataFrame({"A": np.arange(8) / 100, "B": np.arange(8, 16) / 100})
    clusters = pd.DataFrame(
        {"symbol": ["X", "X", "Y", "Y", "Z", "Z", "W", "W"], "entry_year": [2019] * 4 + [2020] * 4}
    )
    max_t = westfall_young_max_t(
        matrix, cluster_frame=clusters, bootstrap_samples=20, seed=13
    )
    spa = white_spa_equivalent(
        matrix, cluster_frame=clusters, bootstrap_samples=20, seed=13
    )
    assert max_t["method"].str.contains("hierarchical_year_symbol_cluster").all()
    assert spa["method"].str.contains("hierarchical_year_symbol_cluster").all()


def test_entrypoint_requires_declared_290_and_returns_all_inference_tables() -> None:
    with pytest.raises(ValueError, match="exactly 290"):
        event_study_290_statistics(_ledger(), bootstrap_samples=10)
    with pytest.raises(ValueError, match="production event study"):
        event_study_290_statistics(
            _ledger(), declared_combination_count=2, bootstrap_samples=10
        )
    with pytest.raises(TypeError, match="_expected_combination_count_for_tests"):
        event_study_290_statistics(
            _ledger(),
            _expected_combination_count_for_tests=2,  # type: ignore[call-arg]
            bootstrap_samples=10,
        )

    development = _protocol_ledger()
    locked = development.assign(
        opportunity_id=development["opportunity_id"] + "-locked",
        gross_return=0.99,
        period="locked",
        selection_role="locked",
    )
    artifact = event_study_290_statistics(
        pd.concat([development, locked], ignore_index=True),
        bootstrap_samples=1,
        seed=17,
    )
    assert {
        "diagnostic_combination_metrics",
        "diagnostic_cuts",
        "cluster_multiple_testing",
        "westfall_young_max_t",
        "white_spa",
        "cscv_pbo_summary",
        "cscv_pbo_splits",
        "pbo_duplicate_groups",
        "diagnostic_deflated_event_statistics",
    } <= set(artifact)
    assert {
        "pvalue_one_sided",
        "benjamini_hochberg_pvalue",
        "holm_pvalue",
    } <= set(artifact["cluster_multiple_testing"].columns)
    assert artifact["westfall_young_max_t"]["method"].str.contains("cluster").all()
    assert artifact["white_spa"]["method"].str.contains("cluster").all()
    assert int(artifact["protocol_counts"].iloc[0]["actual_combinations"]) == 290
    selected = artifact["combination_metrics"].query(
        "combination_id == 'C000' and cost_bps_per_side == 0"
    ).iloc[0]
    diagnostic = artifact["diagnostic_combination_metrics"].query(
        "combination_id == 'C000' and cost_bps_per_side == 0"
    ).iloc[0]
    assert selected["opportunities"] == 8
    assert diagnostic["opportunities"] == 16
    assert selected["mean_return"] < diagnostic["mean_return"]
    assert artifact["combination_metrics"]["evidence_role"].eq(
        "development_selection"
    ).all()
    assert artifact["diagnostic_combination_metrics"]["evidence_role"].eq(
        "all_periods_diagnostic"
    ).all()
    assert not artifact["ranked_combinations"]["selection_eligible"].any()
    assert artifact["ranked_combinations"]["classification"].eq(
        "insufficient_sample"
    ).all()
    assert artifact["objective_winners"].empty
    assert not artifact["diagnostic_deflated_event_statistics"]["cluster_robust"].any()
