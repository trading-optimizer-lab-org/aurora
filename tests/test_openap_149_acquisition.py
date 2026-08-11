from __future__ import annotations

from hashlib import sha256
from importlib import util
from importlib import import_module
import json
from pathlib import Path
import sys

import pandas as pd
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
ROUTE_MATRIX = ROOT / "docs" / "OPENAP_181_CURRENT_FREE_SOURCE_REAUDIT_2026-08-09.csv"


def _module():
    return import_module("aurora.research.openap_181.acquisition_149")


def _routes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal": "Cash",
                "category": "Accounting",
                "current_free_data_feasibility": "free_route_documented",
                "current_route_quality": "reconstructed_current_not_compustat_exact",
                "primary_free_sources": "sec_edgar|sec_financial_statement_datasets",
                "current_remaining_blocker": "implementation_pending",
                "strict_score_eligible": False,
                "official_formula_url": "https://example.test/Cash.py",
                "source_checked_at": "2026-08-09",
            },
            {
                "signal": "Mom6m",
                "category": "Price",
                "current_free_data_feasibility": "free_route_documented",
                "current_route_quality": "market_data_equivalent_or_proxy",
                "primary_free_sources": "twelve_data_basic|kenneth_french_factors",
                "current_remaining_blocker": "implementation_pending",
                "strict_score_eligible": False,
                "official_formula_url": "https://example.test/Mom6m.py",
                "source_checked_at": "2026-08-09",
            },
            {
                "signal": "AgeIPO",
                "category": "Event",
                "current_free_data_feasibility": "free_route_documented",
                "current_route_quality": "filing_event_reconstruction",
                "primary_free_sources": "sec_edgar|field_ritter_ipo",
                "current_remaining_blocker": "implementation_pending",
                "strict_score_eligible": False,
                "official_formula_url": "https://example.test/AgeIPO.py",
                "source_checked_at": "2026-08-09",
            },
        ]
    )


def _current_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "security_id": "cik:1",
                "ticker": "AAA",
                "cik": "0000000001",
                "signal": "Cash",
                "formation_at": "2026-08-09",
                "period_end": "2025-12-31",
                "filed_at": "2026-02-01",
                "available_at": "2026-02-01",
                "retrieved_at": "2026-08-09T10:00:00Z",
                "value": 0.25,
                "fidelity_class": "reconstructed",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
                "coverage_flag": "covered",
                "formula_id": "cash_over_assets",
                "openap_script": "Signals/pyCode/Predictors/Cash.py",
                "natural_frequency": "annual",
                "staleness_days": 189,
                "is_current_for_natural_frequency": True,
                "observation_count": 2,
                "reason_if_missing": "",
                "caveat": "SEC reconstruction",
            },
            {
                "security_id": "cik:2",
                "ticker": "BBB",
                "cik": "0000000002",
                "signal": "Cash",
                "formation_at": "2026-08-09",
                "period_end": "2025-12-31",
                "filed_at": "2026-02-03",
                "available_at": "2026-02-03",
                "retrieved_at": "2026-08-09T10:00:00Z",
                "value": 0.5,
                "fidelity_class": "reconstructed",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000002.json",
                "coverage_flag": "covered",
                "formula_id": "cash_over_assets",
                "openap_script": "Signals/pyCode/Predictors/Cash.py",
                "natural_frequency": "annual",
                "staleness_days": 187,
                "is_current_for_natural_frequency": True,
                "observation_count": 2,
                "reason_if_missing": "",
                "caveat": "SEC reconstruction",
            },
            {
                "security_id": "cik:1",
                "ticker": "AAA",
                "cik": "0000000001",
                "signal": "Mom6m",
                "formation_at": "2026-08-09",
                "period_end": "2026-07-31",
                "filed_at": "",
                "available_at": "2026-08-01",
                "retrieved_at": "2026-08-09T10:00:00Z",
                "value": 0.1,
                "fidelity_class": "reconstructed",
                "current_usable": True,
                "source_id": "yahoo_public",
                "source_url": "https://query1.finance.yahoo.com",
                "coverage_flag": "covered",
                "formula_id": "return_months_7_to_1",
                "openap_script": "Signals/pyCode/Predictors/Mom6m.py",
                "natural_frequency": "monthly",
                "staleness_days": 8,
                "is_current_for_natural_frequency": True,
                "observation_count": 7,
                "reason_if_missing": "",
                "caveat": "",
            },
        ]
    )


def test_authoritative_route_matrix_contains_exactly_149_unique_free_routes() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX)

    assert len(routes) == routes["signal"].nunique() == 149
    assert routes["current_free_data_feasibility"].eq("free_route_documented").all()


def test_current_sec_event_source_aliases_match_documented_free_routes() -> None:
    module = _module()

    assert module._source_allowed(
        "sec_edgar_notes|sec_company_tickers_exchange",
        "sec_edgar|sec_financial_statement_notes|sec_company_tickers_exchange",
    )
    assert module._source_allowed(
        "sec_edgar_submissions_and_filings|sec_company_tickers_exchange",
        "sec_edgar|sec_company_tickers_exchange",
    )
    assert module._source_allowed(
        "recovered_yfinance_artifacts_31256096194|kenneth_french|pastor_stambaugh",
        "recovered_yfinance_artifacts|kenneth_french_factors|pastor_stambaugh",
    )
    assert module._source_allowed(
        "recovered_openap_features_31388342037|sec_edgar|"
        "recovered_yfinance_artifacts_31256096194",
        "recovered_openap_features|sec_edgar|recovered_yfinance_artifacts",
    )
    assert module.SOURCE_TERMS["recovered_yfinance_artifacts"] != (
        "terms_not_yet_verified"
    )
    assert module.SOURCE_TERMS["recovered_openap_features"] != (
        "terms_not_yet_verified"
    )
    assert module.SOURCE_TERMS["pastor_stambaugh"] != "terms_not_yet_verified"


def test_seventeen_recovered_accounting_routes_remain_prepared_and_non_strict() -> None:
    root = Path(__file__).resolve().parents[1]
    routes = pd.read_csv(
        root / "docs/OPENAP_181_CURRENT_FREE_SOURCE_REAUDIT_2026-08-09.csv"
    ).set_index("signal")
    targets = {
        "AccrualsBM",
        "AM",
        "BM",
        "BMdec",
        "CashProd",
        "CF",
        "cfp",
        "EntMult",
        "EP",
        "Leverage",
        "NetDebtPrice",
        "NetPayoutYield",
        "PayoutYield",
        "PS",
        "RD",
        "SP",
        "AdExp",
    }

    selected = routes.loc[sorted(targets)]
    assert len(selected) == 17
    assert selected["primary_free_sources"].str.contains(
        "recovered_openap_features", regex=False
    ).all()
    assert selected["primary_free_sources"].str.contains(
        "recovered_yfinance_artifacts", regex=False
    ).all()
    assert selected["current_remaining_blocker"].eq(
        "audited_run_31388342037_hash_bound_current_feature_route_"
        "prepared_unexecuted_source_as_of_retained_sec_and_market_available_at_"
        "identity_coverage_and_strict_fidelity_pending"
    ).all()
    assert selected["strict_score_eligible"].eq(False).all()  # noqa: E712
    assert selected.drop(index="BetaLiquidityPS")["source_checked_at"].eq(
        "2026-08-10"
    ).all()
    assert selected.loc["BetaLiquidityPS", "source_checked_at"] == "2026-08-11"


def test_all_31_frozen_market_routes_record_the_recovered_artifact_route() -> None:
    from aurora.research.openap_181.implementation_status import (
        TWELVE_DATA_MARKET_SIGNALS,
    )
    from aurora.research.openap_181.twelve_data_market_signals import (
        TWELVE_DATA_DIRECT_SIGNAL_TARGETS,
    )
    from aurora.research.openap_181.twelve_data_factor_signals import (
        TWELVE_DATA_FACTOR_SIGNAL_TARGETS,
    )

    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")
    selected = routes.loc[sorted(TWELVE_DATA_MARKET_SIGNALS)]

    assert len(selected) == 31
    assert selected["primary_free_sources"].str.contains(
        "recovered_yfinance_artifacts",
        regex=False,
    ).all()
    direct = selected.loc[list(TWELVE_DATA_DIRECT_SIGNAL_TARGETS)]
    factor = selected.loc[list(TWELVE_DATA_FACTOR_SIGNAL_TARGETS)]
    prepared = [
        *TWELVE_DATA_DIRECT_SIGNAL_TARGETS,
        *TWELVE_DATA_FACTOR_SIGNAL_TARGETS,
    ]
    additional = selected.drop(index=prepared)
    assert len(direct) == 12
    assert len(factor) == 11
    assert len(additional) == 8
    recovered_openap93_direct = {
        "BetaTailRisk": "recovered_openap93_betatailrisk",
        "MomRev": "recovered_openap93_momrev",
        "MomVol": "recovered_openap93_momvol",
    }
    pending_direct = direct.drop(
        index=["BidAskSpread", *recovered_openap93_direct]
    )
    prepared_direct = [
        "High52",
        "MomOffSeason11YrPlus",
        "RealizedVol",
        "VolSD",
        "VolumeTrend",
    ]
    assert pending_direct.loc[prepared_direct, "current_remaining_blocker"].eq(
        "recovered_yfinance_48_shards_hash_bound_route_and_8_direct_ohlcv_"
        "formula_calculators_prepared_unexecuted_historical_ticker_intervals_"
        "coverage_and_fidelity_pending"
    ).all()
    zero_trade = ["zerotrade1M", "zerotrade6M", "zerotrade12M"]
    assert pending_direct.loc[zero_trade, "current_remaining_blocker"].str.startswith(
        "openap93_2150_finite_values_rejected_and_recovered_yfinance_formula_blocked"
    ).all()
    for signal, recovery_source in recovered_openap93_direct.items():
        sources = set(direct.loc[signal, "primary_free_sources"].split("|"))
        assert recovery_source in sources
        assert direct.loc[signal, "current_remaining_blocker"].startswith(
            "openap93_run_31341580689_hash_bound_current_usable_count_"
        )
    assert direct.loc["BidAskSpread", "current_remaining_blocker"] == (
        "recovered_yfinance_48_shards_hash_bound_route_and_1_corwin_schultz_"
        "proxy_calculator_prepared_unexecuted_openap_"
        "sas_preprocessing_historical_ticker_intervals_coverage_and_fidelity_"
        "pending"
    )
    recovered_openap93 = {
        "CoskewACX": "recovered_openap93_coskewacx",
        "Coskewness": "recovered_openap93_coskewness",
        "PriceDelayRsq": "recovered_openap93_pricedelayrsq",
        "ResidualMomentum": "recovered_openap93_residualmomentum",
    }
    pending_factor = factor.drop(index=["IdioVolAHT", *recovered_openap93])
    assert pending_factor["current_remaining_blocker"].eq(
        "recovered_yfinance_48_shards_hash_bound_route_and_10_french_factor_"
        "calculators_prepared_unexecuted_"
        "historical_ticker_intervals_coverage_and_fidelity_pending"
    ).all()
    for signal, recovery_source in recovered_openap93.items():
        sources = set(factor.loc[signal, "primary_free_sources"].split("|"))
        assert recovery_source in sources
        assert factor.loc[signal, "current_remaining_blocker"].startswith(
            "openap93_run_31341580689_hash_bound_current_usable_count_"
        )
    assert factor.loc["IdioVolAHT", "current_remaining_blocker"] == (
        "recovered_yfinance_48_shards_hash_bound_route_and_1_capm_rmse_"
        "calculator_prepared_unexecuted_historical_"
        "ticker_intervals_coverage_and_fidelity_pending"
    )
    prepared_extended = [
        "IndMom",
        "Size",
        "TrendFactor",
        "VolMkt",
        "std_turn",
    ]
    assert additional.loc[prepared_extended, "current_remaining_blocker"].eq(
        "recovered_yfinance_48_shards_hash_bound_route_and_7_other_extended_"
        "calculators_prepared_unexecuted_historical_ticker_intervals_coverage_"
        "and_fidelity_pending"
    ).all()
    assert additional.loc["FirmAgeMom", "current_remaining_blocker"].startswith(
        "official_age_first_clean_permno_appearance_12m"
    )
    assert additional.loc["IndRetBig", "current_remaining_blocker"].startswith(
        "blocked_formula_fidelity"
    )
    assert additional.loc["BetaLiquidityPS", "current_remaining_blocker"] == (
        "blocked_source_staleness;official_pastor_stambaugh_innovation_latest_"
        "2025_12_not_current_for_2026_07_or_2026_08;openap93_2134_finite_rows_"
        "are_stale_reference_only;current_factor_release_historical_ticker_"
        "intervals_coverage_and_fidelity_pending"
    )
    assert selected["source_checked_at"].eq("2026-08-10").all()
    assert selected["strict_score_eligible"].astype(str).str.lower().eq(
        "false"
    ).all()


def test_authoritative_oscore_and_orgcap_routes_accept_fred() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")

    oscore_sources = set(routes.loc["OScore", "primary_free_sources"].split("|"))
    orgcap_sources = set(routes.loc["OrgCap", "primary_free_sources"].split("|"))

    assert "fred_public_csv" in oscore_sources
    assert "recovered_openap93_oscore" in oscore_sources
    assert "fred_public_csv" in orgcap_sources


def test_custom_xbrl_accounting_routes_do_not_require_market_data() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")

    for signal in (
        "ChInvIA",
        "ConvDebt",
        "DelDRC",
        "OrgCap",
        "OrderBacklog",
        "OrderBacklogChg",
    ):
        sources = set(routes.loc[signal, "primary_free_sources"].split("|"))
        assert "sec_edgar" in sources
        assert "sec_financial_statement_notes" in sources
        assert "twelve_data_basic" not in sources

    convdebt_blocker = routes.loc["ConvDebt", "current_remaining_blocker"]
    assert "positive_only_sec_companyfacts_reconstruction_executed" in convdebt_blocker
    assert "exact_dc_cshrc_semantics" in convdebt_blocker


def test_patent_routes_record_complementary_free_sources_and_concrete_gaps() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")

    for signal in ("CitationsRD", "PatentsRD"):
        sources = set(routes.loc[signal, "primary_free_sources"].split("|"))
        assert {"uspto_patentsview", "kpss_patent_crsp_extended", "sec_edgar"} <= sources
        assert routes.loc[signal, "current_remaining_blocker"] != (
            "implementation_pit_identity_coverage_and_fidelity_pending"
        )
        assert str(routes.loc[signal, "strict_score_eligible"]).lower() == "false"


def test_io_short_interest_route_uses_acquired_regulatory_inputs_not_market_data() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")

    sources = set(routes.loc["IO_ShortInterest", "primary_free_sources"].split("|"))
    blocker = routes.loc["IO_ShortInterest", "current_remaining_blocker"]

    assert sources == {
        "sec_13f",
        "sec_edgar",
        "finra_equity_short_interest",
        "openfigi",
    }
    assert "twelve_data_basic" not in sources
    assert "current_reconstruction_executed_run_31384007094" in blocker
    assert "current_value_count_1" in blocker
    assert "coverage_too_low_for_strict" in blocker
    assert "prepared_unexecuted" not in blocker
    assert str(routes.loc["IO_ShortInterest", "strict_score_eligible"]).lower() == "false"


def test_current_companyfacts_routes_record_executed_batch() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")
    expected_counts = {
        "ChInvIA": 3124,
        "ConvDebt": 265,
        "DelDRC": 1949,
        "DelNetFin": 36,
        "DivOmit": 13,
        "DivSeason": 3,
        "EarningsConsistency": 1441,
        "EarningsSurprise": 2132,
        "RevenueSurprise": 1828,
        "sinAlgo": 22,
    }

    for signal, count in expected_counts.items():
        blocker = routes.loc[signal, "current_remaining_blocker"]
        assert (
            f"companyfacts_run_31490896342_current_value_count_{count}"
            in blocker
        )
        assert "prepared_unexecuted" not in blocker
        assert str(routes.loc[signal, "strict_score_eligible"]).lower() == "false"


def test_current_event_routes_record_executed_batches() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")
    expected = {
        "AgeIPO": ("field_ritter_run_31395454942", 0),
        "IndIPO": ("field_ritter_run_31395454942", 701),
        "RDIPO": ("field_ritter_run_31395454942", 700),
        "ExchSwitch": ("sec_exchange_run_31389285731", 2869),
        "Spinoff": ("sec_spinoff_run_31393646423", 8),
    }

    for signal, (run_marker, count) in expected.items():
        blocker = routes.loc[signal, "current_remaining_blocker"]
        assert run_marker in blocker
        assert f"current_value_count_{count}" in blocker
        assert "prepared_unexecuted" not in blocker
        assert str(routes.loc[signal, "strict_score_eligible"]).lower() == "false"

    assert "data_acquired_but_blocked_coverage" in routes.loc[
        "AgeIPO", "current_remaining_blocker"
    ]


def test_dividend_event_routes_record_recovered_current_batches() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")
    expected = {
        "DivInit": "recovered_openap93_divinit",
        "DivOmit": "recovered_openap93_divomit",
    }

    for signal, recovery_source in expected.items():
        sources = set(routes.loc[signal, "primary_free_sources"].split("|"))
        blocker = routes.loc[signal, "current_remaining_blocker"]
        assert recovery_source in sources
        assert (
            "openap93_run_31341580689_hash_bound_current_usable_count_2157"
            in blocker
        )
        assert "superseded_at_consolidation" in blocker
        assert "prepared_unexecuted" not in blocker
        assert str(routes.loc[signal, "strict_score_eligible"]).lower() == "false"


def test_hire_route_and_consolidation_quarantine_stale_rows() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")
    blocker = routes.loc["hire", "current_remaining_blocker"]

    assert "openap93_run_31341580689_current_usable_value_count_40" in blocker
    assert "24_stale_reference_rows_quarantined" in blocker
    assert str(routes.loc["hire", "strict_score_eligible"]).lower() == "false"

    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    steps = {
        step["name"]: step
        for step in workflow["jobs"]["consolidate"]["steps"]
        if "name" in step
    }
    verify = steps["Verify consolidated result"]["run"]
    assert 'hire["current_value_count"] == 40' in verify
    assert 'hire["fidelity"] == "reconstructed"' in verify
    assert 'hire["source_used"] == "sec_edgar"' in verify
    assert 'not bool(hire["strict_score_eligible"])' in verify
    assert 'len(hire_values) == 40' in verify
    assert 'hire_values["fidelity_class"].eq("reconstructed").all()' in verify
    assert 'hire_values["formula_id"].eq("openap_employee_growth_sec").all()' in verify


def test_io_short_interest_runner_uses_bounded_selective_institutional_recovery() -> None:
    runner = (ROOT / "scripts" / "run_openap_149_finra_short_interest.py").read_text(
        encoding="utf-8"
    )
    calculator = (
        ROOT / "research" / "openap_181" / "short_interest_batch.py"
    ).read_text(encoding="utf-8")
    recovery = (ROOT / "scripts" / "recover_openap_93_failed_artifact.py").read_text(
        encoding="utf-8"
    )
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-finra-short-interest.yml"
    ).read_text(encoding="utf-8")

    assert "calculate_finra_io_short_interest_current" in runner
    assert "--institutional-root" in runner
    assert '"identity_bridge"' in runner
    assert '"openfigi_exchange_constraint": "exchCode_US"' in runner
    assert "_unique_openfigi_share_class_figi" in calculator
    assert 'left_on=["ticker", "issuer_identity_key"]' in calculator
    assert '"entity_name"' in calculator
    assert '"institutional_inputs"' in recovery
    assert "inspect_zip_members" in recovery
    assert "--profile institutional_inputs" in workflow
    assert "--maximum-compressed-bytes 134217728" in workflow
    assert "full_artifact_downloaded" in workflow


def test_acquisition_matrix_counts_only_approved_causal_current_values() -> None:
    module = _module()
    formula_inventory = pd.DataFrame(
        [
            {"signal": "Cash", "formula_sha256": "a" * 64},
            {"signal": "Mom6m", "formula_sha256": "b" * 64},
            {"signal": "AgeIPO", "formula_sha256": "c" * 64},
        ]
    )

    matrix, values = module.build_acquisition_matrix(
        _routes(),
        _current_rows(),
        formula_inventory=formula_inventory,
        evidence_run_url="https://github.com/org/repo/actions/runs/123",
        evidence_artifact="openap-93-max-free-full-results",
    )

    assert matrix["signal"].tolist() == ["AgeIPO", "Cash", "Mom6m"]
    cash = matrix.set_index("signal").loc["Cash"]
    assert bool(cash["data_acquired"])
    assert bool(cash["current_value_calculated"])
    assert cash["current_value_count"] == 2
    assert cash["coverage"] == pytest.approx(1.0)
    assert cash["fidelity"] == "reconstructed"
    assert cash["status"] == "current_signal_computed"
    assert not bool(cash["strict_score_eligible"])
    assert cash["official_formula_sha256"] == "a" * 64

    mom = matrix.set_index("signal").loc["Mom6m"]
    assert not bool(mom["data_acquired"])
    assert not bool(mom["current_value_calculated"])
    assert mom["status"] == "blocked_fidelity"
    assert "yahoo_public" in mom["remaining_blocker"]

    age = matrix.set_index("signal").loc["AgeIPO"]
    assert age["status"] == "blocked_source_failure"
    assert not bool(age["current_value_calculated"])

    assert set(values["signal"]) == {"Cash"}
    assert values["value"].tolist() == [0.25, 0.5]


def test_acquisition_matrix_rejects_lookahead_and_conflicting_duplicates() -> None:
    module = _module()
    future = _current_rows().iloc[[0]].copy()
    future.loc[:, "available_at"] = "2026-08-10"
    with pytest.raises(module.AcquisitionContractError, match="lookahead"):
        module.build_acquisition_matrix(_routes().iloc[[0]], future)

    duplicate = pd.concat([_current_rows().iloc[[0]], _current_rows().iloc[[0]]])
    duplicate.iloc[1, duplicate.columns.get_loc("value")] = 0.75
    with pytest.raises(module.AcquisitionContractError, match="duplicate"):
        module.build_acquisition_matrix(_routes().iloc[[0]], duplicate)


def test_acquisition_matrix_quarantines_pre_period_availability() -> None:
    module = _module()
    invalid = _current_rows().iloc[[0]].copy()
    invalid.loc[:, "period_end"] = "2026-03-31"
    invalid.loc[:, "available_at"] = "2026-03-30"
    formulas = pd.DataFrame([{"signal": "Cash", "formula_sha256": "a" * 64}])

    matrix, values = module.build_acquisition_matrix(
        _routes().iloc[[0]],
        invalid,
        formula_inventory=formulas,
    )

    row = matrix.iloc[0]
    assert row["status"] == "blocked_fidelity"
    assert "available_at_precedes_effective_period" in row["remaining_blocker"]
    assert not bool(row["data_acquired"])
    assert not bool(row["current_value_calculated"])
    assert values.empty


def test_acquisition_matrix_quarantines_missing_available_at() -> None:
    module = _module()
    invalid = _current_rows().iloc[[0]].copy()
    invalid.loc[:, "available_at"] = ""
    formulas = pd.DataFrame([{"signal": "Cash", "formula_sha256": "a" * 64}])

    matrix, values = module.build_acquisition_matrix(
        _routes().iloc[[0]],
        invalid,
        formula_inventory=formulas,
    )

    row = matrix.iloc[0]
    assert row["status"] == "blocked_fidelity"
    assert "available_at_missing" in row["remaining_blocker"]
    assert not bool(row["data_acquired"])
    assert not bool(row["current_value_calculated"])
    assert values.empty


def test_acquisition_matrix_quarantines_explicitly_unusable_current_rows() -> None:
    module = _module()
    unusable = _current_rows().iloc[[0]].copy()
    unusable.loc[:, "current_usable"] = False
    formulas = pd.DataFrame([{"signal": "Cash", "formula_sha256": "a" * 64}])

    matrix, values = module.build_acquisition_matrix(
        _routes().iloc[[0]],
        unusable,
        formula_inventory=formulas,
    )

    row = matrix.iloc[0]
    assert row["status"] == "blocked_fidelity"
    assert "declared_current_unusable" in row["remaining_blocker"]
    assert not bool(row["data_acquired"])
    assert not bool(row["current_value_calculated"])
    assert values.empty


def test_acquisition_matrix_allows_missing_optional_current_usable_flag() -> None:
    module = _module()
    undeclared = _current_rows().iloc[[0]].copy()
    undeclared["current_usable"] = undeclared["current_usable"].astype("object")
    undeclared.loc[:, "current_usable"] = pd.NA
    formulas = pd.DataFrame([{"signal": "Cash", "formula_sha256": "a" * 64}])

    matrix, values = module.build_acquisition_matrix(
        _routes().iloc[[0]],
        undeclared,
        formula_inventory=formulas,
    )

    row = matrix.iloc[0]
    assert row["status"] == "current_signal_computed"
    assert bool(row["data_acquired"])
    assert bool(row["current_value_calculated"])
    assert len(values) == 1


def test_acquisition_status_discloses_latest_formation_date_without_trailing_spaces(
    tmp_path: Path,
) -> None:
    module = _module()
    formulas = pd.DataFrame([{"signal": "Cash", "formula_sha256": "a" * 64}])
    matrix, values = module.build_acquisition_matrix(
        _routes().iloc[[0]],
        _current_rows().iloc[[0]],
        formula_inventory=formulas,
    )

    summary = module.write_acquisition_outputs(
        matrix,
        values,
        tmp_path,
        source_values_sha256="b" * 64,
        formula_inventory_sha256="c" * 64,
    )
    status = (tmp_path / "OPENAP_149_ACQUISITION_STATUS.md").read_text(
        encoding="utf-8"
    )

    assert summary["latest_formation_at"] == "2026-08-09T00:00:00+00:00"
    assert "Fecha maxima de formacion: `2026-08-09T00:00:00+00:00`" in status
    assert not any(line.endswith(" ") for line in status.splitlines())


def test_current_evidence_merge_uses_only_latest_complete_signal_formation() -> None:
    old = _current_rows().iloc[[0]].copy()
    old.loc[:, "formation_at"] = "2026-08-05"
    old.loc[:, "retrieved_at"] = "2026-08-05T10:00:00Z"
    fresh = _current_rows().iloc[[0]].copy()
    fresh.loc[:, "formation_at"] = "2026-08-09"
    fresh.loc[:, "retrieved_at"] = "2026-08-08T18:44:14Z"
    fresh.loc[:, "value"] = 0.30

    merged = _module().merge_current_evidence([old, fresh])

    assert len(merged) == 1
    assert merged.iloc[0]["value"] == 0.30
    assert pd.Timestamp(merged.iloc[0]["formation_at"]) == pd.Timestamp(
        "2026-08-09T00:00:00Z"
    )


def test_current_evidence_merge_rejects_conflicts_at_same_formation() -> None:
    left = _current_rows().iloc[[0]].copy()
    right = left.copy()
    right.loc[:, "value"] = 0.75

    with pytest.raises(_module().AcquisitionContractError, match="conflicting evidence"):
        _module().merge_current_evidence([left, right])


def test_current_evidence_overlay_prefers_93_and_fills_only_its_gaps() -> None:
    primary = _current_rows().iloc[[0, 1]].copy()
    primary.loc[:, "source_id"] = "primary_93"
    primary.loc[primary["security_id"].eq("cik:2"), "value"] = None
    primary.loc[primary["security_id"].eq("cik:2"), "current_usable"] = False
    primary.loc[primary["security_id"].eq("cik:2"), "fidelity_class"] = (
        "unavailable"
    )

    fallback = _current_rows().iloc[[0, 1]].copy()
    fallback.loc[:, "source_id"] = "sec_fallback"
    fallback.loc[:, "value"] = [0.75, 0.60]

    overlaid = _module().overlay_preferred_current_evidence(primary, fallback)
    indexed = overlaid.set_index("security_id")

    assert len(overlaid) == 2
    assert indexed.loc["cik:1", "value"] == pytest.approx(0.25)
    assert indexed.loc["cik:1", "source_id"] == "primary_93"
    assert indexed.loc["cik:2", "value"] == pytest.approx(0.60)
    assert indexed.loc["cik:2", "source_id"] == "sec_fallback"


def test_current_evidence_replacement_swaps_complete_signal_batches() -> None:
    primary = _current_rows().iloc[[0, 2]].copy()
    primary.loc[primary["signal"].eq("Mom6m"), "signal"] = "ShortInterest"
    primary.loc[primary["signal"].eq("ShortInterest"), "formula_id"] = (
        "legacy_short_interest_proxy"
    )

    replacement = primary.loc[primary["signal"].eq("ShortInterest")].copy()
    replacement.loc[:, "source_id"] = "finra_equity_short_interest|sec_edgar"
    replacement.loc[:, "source_url"] = "https://cdn.finra.org/equity/example.csv"
    replacement.loc[:, "formula_id"] = "openap_shortinterest_finra_sec_current_proxy"
    replacement.loc[:, "value"] = 0.12

    replaced = _module().replace_current_signal_batches(primary, replacement)

    assert set(replaced["signal"]) == {"Cash", "ShortInterest"}
    short_interest = replaced.loc[replaced["signal"].eq("ShortInterest")]
    assert len(short_interest) == 1
    assert short_interest.iloc[0]["source_id"] == (
        "finra_equity_short_interest|sec_edgar"
    )
    assert short_interest.iloc[0]["value"] == pytest.approx(0.12)

    unchanged = _module().replace_current_signal_batches(
        primary, replacement.iloc[0:0]
    )
    assert unchanged.reset_index(drop=True).equals(primary.reset_index(drop=True))


def test_consolidation_recovered_loaders_bind_csv_hash_and_source_revision(
    tmp_path: Path,
) -> None:
    script_path = ROOT / "scripts" / "run_openap_149_consolidate.py"
    spec = util.spec_from_file_location("run_openap_149_consolidate", script_path)
    assert spec is not None and spec.loader is not None
    script = util.module_from_spec(spec)
    spec.loader.exec_module(script)

    from aurora.research.openap_181.recovered_current_features import (
        RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION,
        RECOVERED_CURRENT_FEATURE_TARGETS,
    )
    from aurora.research.openap_181.recovered_yfinance_extended_signals import (
        RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS,
    )
    from aurora.research.openap_181.twelve_data_factor_signals import (
        TWELVE_DATA_FACTOR_SIGNAL_TARGETS,
    )
    from aurora.research.openap_181.twelve_data_market_signals import (
        TWELVE_DATA_DIRECT_SIGNAL_TARGETS,
    )

    implementation_sha = "b" * 40
    columns = [
        "security_id",
        "ticker",
        "cik",
        "signal",
        "formation_at",
        "period_end",
        "filed_at",
        "available_at",
        "retrieved_at",
        "value",
        "fidelity_class",
        "current_usable",
        "source_id",
        "source_url",
        "formula_id",
        "observation_count",
        "caveat",
        "strict_score_eligible",
    ]
    base = {
        "security_id": "US-SEC-0000000001-AAA",
        "ticker": "AAA",
        "cik": "1",
        "formation_at": "2026-07-31T00:00:00Z",
        "period_end": "2026-07-31T00:00:00Z",
        "filed_at": "",
        "available_at": "2026-07-31T00:00:00Z",
        "retrieved_at": "2026-08-08T12:00:00Z",
        "value": 0.5,
        "fidelity_class": "reconstructed",
        "current_usable": True,
        "source_id": "recovered_yfinance_artifacts_31256096194",
        "source_url": "https://github.com/org/repo/actions/runs/10",
        "formula_id": "openap_high52_recovered_history",
        "observation_count": 252,
        "caveat": "recovered_not_strict",
        "strict_score_eligible": False,
    }
    market_root = tmp_path / "market"
    features_root = tmp_path / "features"
    market_root.mkdir()
    features_root.mkdir()
    market_csv = market_root / "recovered_yfinance_market_current.csv"
    pd.DataFrame([{**base, "signal": "High52"}], columns=columns).to_csv(
        market_csv, index=False
    )
    market_manifest = {
        "contract_version": 1,
        "implementation_sha": implementation_sha,
        "direct_signal_targets": list(TWELVE_DATA_DIRECT_SIGNAL_TARGETS),
        "factor_signal_targets": list(TWELVE_DATA_FACTOR_SIGNAL_TARGETS),
        "extended_signal_targets": list(
            RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS
        ),
        "signal_target_count": 31,
        "current_value_rows": 1,
        "current_signal_count": 1,
        "current_csv_sha256": sha256(market_csv.read_bytes()).hexdigest(),
        "historical_ticker_interval_verified": False,
        "raw_market_data_internal_use_only": True,
        "raw_market_data_redistribution_allowed": False,
        "fresh_provider_request_made": False,
        "strict_score_eligible": False,
        "strict_score_increment": 0,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
    }
    market_manifest_path = market_root / "recovered_yfinance_market_manifest.json"
    market_manifest_path.write_text(
        json.dumps(market_manifest, sort_keys=True), encoding="utf-8"
    )

    feature_csv = features_root / "recovered_current_features_current.csv"
    feature_row = {
        **base,
        "signal": "AccrualsBM",
        "period_end": "2025-12-31T00:00:00Z",
        "filed_at": "2026-07-31T00:00:00Z",
        "available_at": "2026-07-31T20:00:00Z",
        "fidelity_class": "unvalidated_proxy",
        "source_id": (
            "recovered_openap_features_31388342037|sec_edgar|"
            "recovered_yfinance_artifacts"
        ),
        "formula_id": "openap_accrualsbm_sec_ocf_double_sort_proxy",
    }
    pd.DataFrame([feature_row], columns=columns).to_csv(feature_csv, index=False)
    feature_manifest = {
        "contract_version": RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION,
        "implementation_sha": implementation_sha,
        "target_signals": list(RECOVERED_CURRENT_FEATURE_TARGETS),
        "target_signal_count": 17,
        "current_value_rows": 1,
        "current_signal_count": 1,
        "current_csv_sha256": sha256(feature_csv.read_bytes()).hexdigest(),
        "formula_recomputed_during_recovery": False,
        "source_values_revalidated": True,
        "source_age_laundered": False,
        "fresh_provider_request_made": False,
        "historical_ticker_interval_verified": False,
        "strict_score_eligible": False,
        "strict_score_increment": 0,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
    }
    feature_manifest_path = (
        features_root / "recovered_current_features_manifest.json"
    )
    feature_manifest_path.write_text(
        json.dumps(feature_manifest, sort_keys=True), encoding="utf-8"
    )

    market, market_paths = script._load_recovered_market_batch(
        market_root,
        expected_implementation_sha=implementation_sha,
    )
    features, feature_paths = script._load_recovered_current_feature_batch(
        features_root,
        expected_implementation_sha=implementation_sha,
    )
    assert market["signal"].tolist() == ["High52"]
    assert features["signal"].tolist() == ["AccrualsBM"]
    assert {path.name for path in market_paths} == {
        "recovered_yfinance_market_current.csv",
        "recovered_yfinance_market_manifest.json",
    }
    assert {path.name for path in feature_paths} == {
        "recovered_current_features_current.csv",
        "recovered_current_features_manifest.json",
    }

    market_csv.write_bytes(market_csv.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="SHA-256"):
        script._load_recovered_market_batch(
            market_root,
            expected_implementation_sha=implementation_sha,
        )
    with pytest.raises(RuntimeError, match="implementation SHA"):
        script._load_recovered_current_feature_batch(
            features_root,
            expected_implementation_sha="c" * 40,
        )


def test_consolidation_cli_includes_realestate_and_audited_event_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = ROOT / "scripts" / "run_openap_149_consolidate.py"
    spec = util.spec_from_file_location("run_openap_149_consolidate", script_path)
    assert spec is not None and spec.loader is not None
    script = util.module_from_spec(spec)
    spec.loader.exec_module(script)

    def fake_verified_loader(filename: str, batch_id: str):
        def load(
            root: Path,
            *,
            evidence_run_url: str,
            expected_formula_inventory_sha256: str,
        ):
            path = script._find_one(root, filename)
            frame = pd.read_csv(path, low_memory=False)
            return frame, [path], {
                "batch_id": batch_id,
                "run_url": evidence_run_url,
                "formula_inventory_sha256": (
                    expected_formula_inventory_sha256
                ),
                "strict_score_increment": 0,
            }

        return load

    monkeypatch.setattr(
        script,
        "load_verified_sec_companyfacts_batch",
        fake_verified_loader(
            "openap_149_sec_companyfacts_current.csv",
            "sec_companyfacts",
        ),
    )
    monkeypatch.setattr(
        script,
        "load_verified_finra_short_interest_batch",
        fake_verified_loader(
            "openap_149_finra_short_interest_current.csv",
            "finra_short_interest",
        ),
    )
    monkeypatch.setattr(
        script,
        "load_verified_realestate_batch",
        fake_verified_loader(
            "openap_149_realestate_current.csv",
            "realestate",
        ),
    )
    monkeypatch.setattr(
        script,
        "load_verified_exchange_switch_batch",
        fake_verified_loader(
            "openap_149_sec_exch_switch_current.csv",
            "exchange_switch",
        ),
    )
    monkeypatch.setattr(
        script,
        "load_verified_field_ritter_ipo_batch",
        fake_verified_loader(
            "openap_149_field_ritter_ipo_current.csv",
            "field_ritter_ipo",
        ),
    )
    monkeypatch.setattr(
        script,
        "load_verified_spinoff_batch",
        fake_verified_loader(
            "openap_149_sec_spinoff_current.csv",
            "spinoff",
        ),
    )

    columns = [
        "security_id",
        "ticker",
        "cik",
        "signal",
        "formation_at",
        "period_end",
        "filed_at",
        "available_at",
        "retrieved_at",
        "value",
        "fidelity_class",
        "current_usable",
        "source_id",
        "source_url",
        "formula_id",
        "observation_count",
        "caveat",
        "strict_score_eligible",
    ]
    cash = {
        "security_id": "US-SEC-0000000001-CASH",
        "ticker": "CASH",
        "cik": "1",
        "signal": "Cash",
        "formation_at": "2026-08-09T23:59:59Z",
        "period_end": "2025-12-31",
        "filed_at": "2026-02-01T12:00:00Z",
        "available_at": "2026-02-01T12:00:00Z",
        "retrieved_at": "2026-08-09T12:00:00Z",
        "value": 0.25,
        "fidelity_class": "reconstructed",
        "current_usable": True,
        "source_id": "sec_edgar",
        "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        "formula_id": "cash_over_assets",
        "observation_count": 1,
        "caveat": "SEC reconstruction",
    }
    realestate = {
        "security_id": "US-SEC-0000320193-AAPL",
        "ticker": "AAPL",
        "cik": "320193",
        "signal": "realestate",
        "formation_at": "2026-08-09T23:59:59Z",
        "period_end": "2025-09-27",
        "filed_at": "2025-10-31T10:01:26Z",
        "available_at": "2025-10-31T10:01:26Z",
        "retrieved_at": "2026-08-08T18:15:54Z",
        "value": -0.024747824396012474,
        "fidelity_class": "reconstructed",
        "current_usable": True,
        "source_id": "sec_edgar",
        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/report.htm",
        "formula_id": "realestate",
        "observation_count": 7,
        "caveat": "reconstructed_not_strict",
        "strict_score_eligible": False,
    }
    exchange_switch = {
        **realestate,
        "security_id": "US-SEC-0000000002-EXCH",
        "ticker": "EXCH",
        "cik": "2",
        "signal": "ExchSwitch",
        "formation_at": "2026-08-10T23:59:59Z",
        "value": 1.0,
        "source_id": "sec_edgar_notes|sec_company_tickers_exchange",
        "source_url": "https://www.sec.gov/files/company_tickers_exchange.json",
        "formula_id": "openap_exchswitch_current_exchange_lag_1_12",
        "observation_count": 2,
    }
    indipo = {
        **realestate,
        "security_id": "US-SEC-0000000003-IPO",
        "ticker": "IPO",
        "cik": "3",
        "signal": "IndIPO",
        "formation_at": "2026-08-10T13:58:05Z",
        "value": 1.0,
        "source_id": "field_ritter_ipo|openfigi|sec_edgar",
        "source_url": "https://site.warrington.ufl.edu/ritter/files/IPO-age.xlsx",
        "formula_id": "openap_indipo_field_ritter_calendar_month_3_36",
        "observation_count": 701,
    }
    ageipo = {
        **indipo,
        "security_id": "US-SEC-0000000005-AGEIPO",
        "ticker": "AGEIPO",
        "cik": "5",
        "signal": "AgeIPO",
        "value": float("nan"),
        "fidelity_class": "unavailable",
        "current_usable": False,
        "formula_id": "openap_ageipo_field_ritter_year_age_3_36m_min100",
        "reason_if_missing": "confirmed_recent_ipo_cohort_below_100",
    }
    rdipo = {
        **indipo,
        "security_id": "US-SEC-0000000006-RDIPO",
        "ticker": "RDIPO",
        "cik": "6",
        "signal": "RDIPO",
        "value": 0.0,
        "formula_id": "openap_rdipo_field_ritter_sec_explicit_rd_zero_7_36m",
        "observation_count": 700,
    }
    spinoff = {
        **realestate,
        "security_id": "US-SEC-0000000004-SPIN",
        "ticker": "SPIN",
        "cik": "4",
        "signal": "Spinoff",
        "formation_at": "2026-08-10T23:59:59Z",
        "value": 1.0,
        "source_id": "sec_edgar_submissions_and_filings",
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/4/"
            "000000000425000001/spinoff.htm"
        ),
        "formula_id": "openap_spinoff_completed_event_age_le_24",
        "observation_count": 1,
    }

    current_93_root = tmp_path / "current_93"
    sec_root = tmp_path / "sec"
    finra_root = tmp_path / "finra"
    realestate_root = tmp_path / "realestate"
    exchange_switch_root = tmp_path / "exchange_switch"
    field_ritter_root = tmp_path / "field_ritter"
    spinoff_root = tmp_path / "spinoff"
    recovered_market_root = tmp_path / "recovered_market"
    recovered_features_root = tmp_path / "recovered_features"
    formula_root = tmp_path / "formulas"
    output_root = tmp_path / "output"
    for root in (
        current_93_root,
        sec_root,
        finra_root,
        realestate_root,
        exchange_switch_root,
        field_ritter_root,
        spinoff_root,
        recovered_market_root,
        recovered_features_root,
        formula_root,
    ):
        root.mkdir()
    pd.DataFrame([cash], columns=columns).to_csv(
        current_93_root / "signals_93_current.csv", index=False
    )
    pd.DataFrame(columns=columns).to_csv(
        sec_root / "openap_149_sec_companyfacts_current.csv", index=False
    )
    pd.DataFrame(columns=columns).to_csv(
        finra_root / "openap_149_finra_short_interest_current.csv", index=False
    )
    pd.DataFrame([realestate], columns=columns).to_csv(
        realestate_root / "openap_149_realestate_current.csv", index=False
    )
    pd.DataFrame([exchange_switch], columns=columns).to_csv(
        exchange_switch_root / "openap_149_sec_exch_switch_current.csv",
        index=False,
    )
    pd.DataFrame([ageipo, indipo, rdipo], columns=columns).to_csv(
        field_ritter_root / "openap_149_field_ritter_ipo_current.csv",
        index=False,
    )
    pd.DataFrame([spinoff], columns=columns).to_csv(
        spinoff_root / "openap_149_sec_spinoff_current.csv",
        index=False,
    )
    recovered_market = {
        **realestate,
        "security_id": "US-SEC-0000000007-MARKET",
        "ticker": "MARKET",
        "cik": "7",
        "signal": "High52",
        "formation_at": "2026-07-31T00:00:00Z",
        "period_end": "2026-07-31T00:00:00Z",
        "filed_at": "",
        "available_at": "2026-07-31T00:00:00Z",
        "value": 0.8,
        "source_id": "recovered_yfinance_artifacts_31256096194",
        "source_url": "https://github.com/org/repo/actions/runs/10",
        "formula_id": "openap_high52_recovered_history",
        "observation_count": 252,
    }
    recovered_feature = {
        **realestate,
        "security_id": "US-SEC-0000000008-FEATURE",
        "ticker": "FEATURE",
        "cik": "8",
        "signal": "AccrualsBM",
        "formation_at": "2026-08-08T16:00:00Z",
        "period_end": "2025-12-31T00:00:00Z",
        "filed_at": "2026-07-31T00:00:00Z",
        "available_at": "2026-07-31T20:00:00Z",
        "value": 1.0,
        "fidelity_class": "unvalidated_proxy",
        "source_id": (
            "recovered_openap_features_31388342037|sec_edgar|"
            "recovered_yfinance_artifacts"
        ),
        "source_url": "https://github.com/org/repo/actions/runs/10",
        "formula_id": "openap_accrualsbm_sec_ocf_double_sort_proxy",
        "observation_count": 5,
    }
    recovered_market_csv = (
        recovered_market_root / "recovered_yfinance_market_current.csv"
    )
    recovered_feature_csv = (
        recovered_features_root / "recovered_current_features_current.csv"
    )
    pd.DataFrame([recovered_market], columns=columns).to_csv(
        recovered_market_csv, index=False
    )
    pd.DataFrame([recovered_feature], columns=columns).to_csv(
        recovered_feature_csv, index=False
    )

    from aurora.research.openap_181.recovered_current_features import (
        RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION,
        RECOVERED_CURRENT_FEATURE_TARGETS,
    )
    from aurora.research.openap_181.recovered_yfinance_extended_signals import (
        RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS,
    )
    from aurora.research.openap_181.twelve_data_factor_signals import (
        TWELVE_DATA_FACTOR_SIGNAL_TARGETS,
    )
    from aurora.research.openap_181.twelve_data_market_signals import (
        TWELVE_DATA_DIRECT_SIGNAL_TARGETS,
    )

    implementation_sha = "b" * 40
    recovered_market_manifest = {
        "contract_version": 1,
        "implementation_sha": implementation_sha,
        "direct_signal_targets": list(TWELVE_DATA_DIRECT_SIGNAL_TARGETS),
        "factor_signal_targets": list(TWELVE_DATA_FACTOR_SIGNAL_TARGETS),
        "extended_signal_targets": list(
            RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS
        ),
        "signal_target_count": 31,
        "current_value_rows": 1,
        "current_signal_count": 1,
        "current_csv_sha256": sha256(
            recovered_market_csv.read_bytes()
        ).hexdigest(),
        "historical_ticker_interval_verified": False,
        "raw_market_data_internal_use_only": True,
        "raw_market_data_redistribution_allowed": False,
        "fresh_provider_request_made": False,
        "strict_score_eligible": False,
        "strict_score_increment": 0,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
    }
    (
        recovered_market_root / "recovered_yfinance_market_manifest.json"
    ).write_text(
        json.dumps(recovered_market_manifest, sort_keys=True), encoding="utf-8"
    )
    recovered_feature_manifest = {
        "contract_version": RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION,
        "implementation_sha": implementation_sha,
        "target_signals": list(RECOVERED_CURRENT_FEATURE_TARGETS),
        "target_signal_count": 17,
        "current_value_rows": 1,
        "current_signal_count": 1,
        "current_csv_sha256": sha256(
            recovered_feature_csv.read_bytes()
        ).hexdigest(),
        "formula_recomputed_during_recovery": False,
        "source_values_revalidated": True,
        "source_age_laundered": False,
        "fresh_provider_request_made": False,
        "historical_ticker_interval_verified": False,
        "strict_score_eligible": False,
        "strict_score_increment": 0,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
    }
    (
        recovered_features_root / "recovered_current_features_manifest.json"
    ).write_text(
        json.dumps(recovered_feature_manifest, sort_keys=True), encoding="utf-8"
    )
    routes = _module().load_target_routes(ROUTE_MATRIX)
    pd.DataFrame(
        {
            "signal": routes["signal"],
            "formula_sha256": ["a" * 64] * len(routes),
        }
    ).to_csv(formula_root / "openap_181_formula_inventory.csv", index=False)

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "--route-matrix",
            str(ROUTE_MATRIX),
            "--current-93-root",
            str(current_93_root),
            "--sec-current-root",
            str(sec_root),
            "--finra-current-root",
            str(finra_root),
            "--realestate-current-root",
            str(realestate_root),
            "--exchange-switch-current-root",
            str(exchange_switch_root),
            "--field-ritter-current-root",
            str(field_ritter_root),
            "--spinoff-current-root",
            str(spinoff_root),
            "--recovered-market-root",
            str(recovered_market_root),
            "--recovered-current-features-root",
            str(recovered_features_root),
            "--formula-root",
            str(formula_root),
            "--expected-source-sha",
            implementation_sha,
            "--signals-93",
            str(ROOT / "config" / "openap_93" / "signals_93.yaml"),
            "--current-93-run-url",
            "https://github.com/org/repo/actions/runs/1",
            "--sec-current-run-url",
            "https://github.com/org/repo/actions/runs/2",
            "--finra-current-run-url",
            "https://github.com/org/repo/actions/runs/3",
            "--realestate-current-run-url",
            "https://github.com/org/repo/actions/runs/4",
            "--exchange-switch-current-run-url",
            "https://github.com/org/repo/actions/runs/5",
            "--field-ritter-current-run-url",
            "https://github.com/org/repo/actions/runs/6",
            "--spinoff-current-run-url",
            "https://github.com/org/repo/actions/runs/7",
            "--recovered-current-run-url",
            "https://github.com/org/repo/actions/runs/10",
            "--evidence-run-url",
            "https://github.com/org/repo/actions/runs/8",
            "--evidence-artifact",
            "openap-149-current-consolidated-results",
            "--output-dir",
            str(output_root),
        ],
    )

    assert script.main() == 0

    matrix = pd.read_csv(output_root / "OPENAP_149_ACQUISITION_MATRIX.csv")
    manifest = json.loads(
        (output_root / "openap_149_consolidation_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    row = matrix.set_index("signal").loc["realestate"]
    assert bool(row["data_acquired"])
    assert bool(row["current_value_calculated"])
    assert row["current_value_count"] == 1
    assert row["fidelity"] == "reconstructed"
    assert row["source_evidence_run"] == "https://github.com/org/repo/actions/runs/4"
    assert not bool(row["strict_score_eligible"])
    assert manifest["realestate_current_run_url"] == (
        "https://github.com/org/repo/actions/runs/4"
    )
    assert "openap_149_realestate_current.csv" in manifest["source_files"]
    expected_event_runs = {
        "ExchSwitch": "https://github.com/org/repo/actions/runs/5",
        "IndIPO": "https://github.com/org/repo/actions/runs/6",
        "RDIPO": "https://github.com/org/repo/actions/runs/6",
        "Spinoff": "https://github.com/org/repo/actions/runs/7",
    }
    for signal, run_url in expected_event_runs.items():
        event = matrix.set_index("signal").loc[signal]
        assert bool(event["data_acquired"])
        assert bool(event["current_value_calculated"])
        assert event["current_value_count"] == 1
        assert event["fidelity"] == "reconstructed"
        assert event["source_evidence_run"] == run_url
        assert not bool(event["strict_score_eligible"])
    ageipo_event = matrix.set_index("signal").loc["AgeIPO"]
    assert bool(ageipo_event["data_acquired"])
    assert not bool(ageipo_event["current_value_calculated"])
    assert ageipo_event["current_value_count"] == 0
    assert ageipo_event["status"] == "blocked_coverage"
    assert ageipo_event["source_evidence_run"] == (
        "https://github.com/org/repo/actions/runs/6"
    )
    assert not bool(ageipo_event["strict_score_eligible"])
    recovered_run = "https://github.com/org/repo/actions/runs/10"
    matrix_by_signal = matrix.set_index("signal")
    high52 = matrix_by_signal.loc["High52"]
    assert bool(high52["data_acquired"])
    assert bool(high52["current_value_calculated"])
    assert high52["current_value_count"] == 1
    assert high52["source_evidence_run"] == recovered_run
    assert not bool(high52["strict_score_eligible"])
    accruals_bm = matrix_by_signal.loc["AccrualsBM"]
    assert bool(accruals_bm["data_acquired"])
    assert bool(accruals_bm["current_value_calculated"])
    assert accruals_bm["current_value_count"] == 1
    assert accruals_bm["fidelity"] == "unvalidated_proxy"
    assert accruals_bm["source_evidence_run"] == recovered_run
    assert not bool(accruals_bm["strict_score_eligible"])
    assert manifest["recovered_current_run_url"] == recovered_run
    assert set(manifest["verified_current_batches"]) == {
        "sec_companyfacts",
        "finra_short_interest",
        "realestate",
        "exchange_switch",
        "field_ritter_ipo",
        "spinoff",
    }
    assert {
        "recovered_yfinance_market_current.csv",
        "recovered_yfinance_market_manifest.json",
        "recovered_current_features_current.csv",
        "recovered_current_features_manifest.json",
    }.issubset(set(manifest["source_files"]))


def test_consolidation_workflow_pins_verified_source_runs() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    expected = {
        "current_93_run_id": "31341580689",
        "sec_current_run_id": "31490896342",
        "finra_current_run_id": "31384007094",
        "realestate_current_run_id": "31384049772",
        "exchange_switch_current_run_id": "31389285731",
        "field_ritter_current_run_id": "31395454942",
        "spinoff_current_run_id": "31393646423",
        "formula_evidence_run_id": "31396163422",
    }
    assert {
        input_name: dispatch_inputs[input_name].get("default")
        for input_name in expected
    } == expected


def test_consolidation_workflow_wires_both_recovered_batches() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    recovered_input = dispatch_inputs["recovered_current_run_id"]
    assert recovered_input["required"] == "true"
    assert not recovered_input.get("default")
    steps = {
        step["name"]: step
        for step in workflow["jobs"]["consolidate"]["steps"]
        if "name" in step
    }
    expected = {
        "Download recovered YFinance market values": (
            "openap-149-recovered-yfinance-market-results",
            "inputs/recovered_market",
        ),
        "Download recovered accounting feature values": (
            "openap-149-recovered-current-feature-results",
            "inputs/recovered_current_features",
        ),
    }
    for step_name, (artifact_name, path) in expected.items():
        download = steps[step_name]
        assert download["with"]["name"] == artifact_name
        assert download["with"]["path"] == path
        assert download["with"]["run-id"] == (
            "${{ inputs.recovered_current_run_id }}"
        )
    command = steps["Consolidate latest current evidence"]["run"]
    assert "--expected-source-sha \"$SOURCE_SHA\"" in command
    assert "--recovered-market-root inputs/recovered_market" in command
    assert (
        "--recovered-current-features-root inputs/recovered_current_features"
        in command
    )
    assert "--recovered-current-run-url" in command
    verify = steps["Verify consolidated result"]["run"]
    assert "recovered_yfinance_market_current.csv" in verify
    assert "recovered_current_features_current.csv" in verify
    assert "recovered_market_counts" in verify
    assert "recovered_feature_counts" in verify
    assert "not strict_eligible.any()" in verify


def test_consolidation_workflow_recovers_missing_batches_in_authorized_run() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch_inputs["yfinance_source_run_id"]["default"] == "31256096194"
    assert dispatch_inputs["audited_market_run_id"]["default"] == "31388342037"
    steps = {
        step["name"]: step
        for step in workflow["jobs"]["consolidate"]["steps"]
        if "name" in step
    }
    for step_name, step_id in (
        ("Download recovered YFinance market values", "recovered_market_download"),
        ("Download recovered accounting feature values", "recovered_features_download"),
    ):
        download = steps[step_name]
        assert download["id"] == step_id
        assert download["continue-on-error"] == "true"
    fallback = steps["Recover missing current free inputs in this run"]
    assert "recovered_market_download.outcome" in fallback["if"]
    assert "recovered_features_download.outcome" in fallback["if"]
    assert "recover_openap_yfinance_price_shards.py" in fallback["run"]
    assert "--sec-identity-evidence" in fallback["run"]
    assert "inputs/exchange_switch_current/sec_listing_identity_manifest.json" in fallback["run"]
    assert "run_openap_149_recovered_yfinance_market.py" in fallback["run"]
    assert "run_openap_149_recovered_current_features.py" in fallback["run"]
    command = steps["Consolidate latest current evidence"]["run"]
    assert '--recovered-current-run-url "$RECOVERED_CURRENT_RUN_URL"' in command
    assert "always()" in workflow["jobs"]["consolidate"]["if"]


def test_consolidation_workflow_downloads_and_verifies_realestate_evidence() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert "realestate_current_run_id" in dispatch_inputs
    consolidate = workflow["jobs"]["consolidate"]
    steps = {step["name"]: step for step in consolidate["steps"] if "name" in step}
    download = steps["Download rendered realestate current values"]
    assert download["with"]["name"] == "openap-149-realestate-rendered-current"
    assert download["with"]["path"] == "inputs/realestate_current"
    assert download["with"]["run-id"] == "${{ inputs.realestate_current_run_id }}"
    command = steps["Consolidate latest current evidence"]["run"]
    assert "--realestate-current-root inputs/realestate_current" in command
    assert "--realestate-current-run-url" in command
    verify = steps["Verify consolidated result"]["run"]
    assert 'matrix.set_index("signal").loc["realestate"]' in verify
    assert 'realestate["current_value_count"] == 7' in verify
    assert 'realestate["fidelity"] == "reconstructed"' in verify
    assert 'not bool(realestate["strict_score_eligible"])' in verify


def test_consolidation_workflow_verifies_audited_finra_evidence() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch_inputs["finra_current_run_id"]["default"] == "31384007094"
    steps = {
        step["name"]: step
        for step in workflow["jobs"]["consolidate"]["steps"]
        if "name" in step
    }
    download = steps["Download official FINRA ShortInterest values"]
    assert download["with"]["name"] == "openap-149-finra-short-interest-current"
    assert download["with"]["path"] == "inputs/finra_current"
    assert download["with"]["run-id"] == "${{ inputs.finra_current_run_id }}"
    command = steps["Consolidate latest current evidence"]["run"]
    assert "--finra-current-root inputs/finra_current" in command
    assert "--finra-current-run-url" in command
    verify = steps["Verify consolidated result"]["run"]
    assert 'short_interest["current_value_count"] == 2988' in verify
    assert 'short_interest["fidelity"] == "unvalidated_proxy"' in verify
    assert 'io_short_interest["current_value_count"] == 1' in verify
    assert 'io_short_interest["fidelity"] == "reconstructed"' in verify
    assert (
        'io_short_interest["source_used"] '
        '== "finra_equity_short_interest|openfigi|sec_13f|sec_edgar"'
        in verify
    )
    assert 'not bool(io_short_interest["strict_score_eligible"])' in verify
    assert 'len(io_short_interest_values) == 1' in verify
    assert 'io_short_interest_values["source_id"].eq(' in verify
    assert (
        '"finra_equity_short_interest|sec_edgar|sec_13f|openfigi_public"'
        in verify
    )
    assert 'io_short_interest_values["formula_id"].eq(' in verify
    assert (
        '"openap_io_shortinterest_finra_sec13f_current_reconstruction"'
        in verify
    )


def test_consolidation_workflow_downloads_audited_event_batches() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch_inputs["formula_evidence_run_id"]["default"] == "31396163422"
    expected = {
        "exchange_switch_current_run_id": (
            "Download SEC exchange-switch current values",
            "openap-149-sec-exchange-switch-current",
            "inputs/exchange_switch_current",
            "exchange-switch-current",
        ),
        "field_ritter_current_run_id": (
            "Download Field-Ritter IPO current values",
            "openap-149-field-ritter-ipo-current",
            "inputs/field_ritter_current",
            "field-ritter-current",
        ),
        "spinoff_current_run_id": (
            "Download SEC Spinoff current values",
            "openap-149-sec-spinoff-current",
            "inputs/spinoff_current",
            "spinoff-current",
        ),
    }
    steps = {
        step["name"]: step
        for step in workflow["jobs"]["consolidate"]["steps"]
        if "name" in step
    }
    command = steps["Consolidate latest current evidence"]["run"]
    for input_name, (step_name, artifact_name, path, flag) in expected.items():
        assert input_name in dispatch_inputs
        download = steps[step_name]
        assert download["with"]["name"] == artifact_name
        assert download["with"]["path"] == path
        assert download["with"]["run-id"] == f"${{{{ inputs.{input_name} }}}}"
        assert f"--{flag}-root {path}" in command
        assert f"--{flag}-run-url" in command

    verify = steps["Verify consolidated result"]["run"]
    assert 'exch_switch["current_value_count"] == 2869' in verify
    assert 'indipo["current_value_count"] == 701' in verify
    assert 'rdipo["current_value_count"] == 700' in verify
    assert 'spinoff["current_value_count"] == 8' in verify
    assert 'not bool(ageipo["current_value_calculated"])' in verify
    assert 'ageipo["status"] == "blocked_coverage"' in verify


def test_consolidation_workflow_verifies_causal_firmage_evidence() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    steps = {
        step["name"]: step
        for step in workflow["jobs"]["consolidate"]["steps"]
        if "name" in step
    }
    verify = steps["Verify consolidated result"]["run"]
    assert 'summary["data_acquired"] == int(data_acquired.sum())' in verify
    assert (
        'summary["current_values_calculated"] == int(current_calculated.sum())'
        in verify
    )
    assert (
        'summary["reconstructed_not_strict"] '
        '== int((current_calculated & reconstructed).sum())'
        in verify
    )
    assert (
        'summary["blocked"] == summary["pending"] '
        '== int((~current_calculated).sum())'
        in verify
    )
    assert 'summary["value_rows"] == len(values)' in verify
    assert 'matrix.set_index("signal").loc["FirmAge"]' in verify
    assert 'firm_age["current_value_count"] == 4434' in verify
    assert 'firm_age["fidelity"] == "unvalidated_proxy"' in verify
    assert 'not bool(firm_age["strict_score_eligible"])' in verify
    assert 'matrix_by_signal.loc["CBOperProf"]' in verify
    assert '"CBOperProf", "DelNetFin", "EarningsConsistency"' not in verify
    assert '"declared_current_unusable" in quarantined["remaining_blocker"]' in verify
    assert 'matrix.set_index("signal").loc["OScore"]' in verify
    assert 'oscore["current_value_count"] == 1100' in verify
    assert 'oscore["source_used"] == "recovered_openap93_oscore"' in verify
    assert '"recovered_openap93_oscore"' in verify
    upload = steps["Upload consolidated current evidence"]
    assert upload["if"] == "always()"
    for recovery_source in (
        "recovered_openap93_pricedelayrsq",
        "recovered_openap93_coskewacx",
        "recovered_openap93_coskewness",
        "recovered_openap93_residualmomentum",
        "recovered_openap93_betatailrisk",
        "recovered_openap93_divyieldst",
        "recovered_openap93_momvol",
        "recovered_openap93_momrev",
        "recovered_openap93_divinit",
        "recovered_openap93_divomit",
    ):
        assert f'"{recovery_source}"' in verify


def test_consolidation_workflow_accepts_current_companyfacts_evidence() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    steps = {
        step["name"]: step
        for step in workflow["jobs"]["consolidate"]["steps"]
        if "name" in step
    }
    verify = steps["Verify consolidated result"]["run"]
    expected = {
        "ChInvIA": (
            3124,
            "reconstructed",
            "openap_chinvia_capex_growth_sic2d_mean_sec",
        ),
        "ConvDebt": (
            265,
            "reconstructed",
            "openap_convdebt_positive_only_sec_companyfacts_reconstruction",
        ),
        "DelDRC": (
            1949,
            "unvalidated_proxy",
            "change_deferred_revenue_over_average_assets",
        ),
        "DelNetFin": (
            36,
            "reconstructed",
            "openap_delnetfin_sec_aggregate_components_6m_lag",
        ),
        "DivSeason": (
            3,
            "reconstructed",
            "openap_divseason_positive_sec_direct_month_frequency",
        ),
        "EarningsConsistency": (
            1441,
            "reconstructed",
            "openap_earnings_consistency_sec_basic_eps_6m_lag",
        ),
        "EarningsSurprise": (
            2132,
            "reconstructed",
            "openap_eps_yoy_drift_standardized_8q_sec_21q",
        ),
        "RevenueSurprise": (
            1828,
            "reconstructed",
            "openap_revenue_per_share_yoy_standardized_8q_sec_21q",
        ),
        "sinAlgo": (
            22,
            "reconstructed",
            "openap_sinalgo_positive_current_sec_sic",
        ),
    }
    for signal, (count, fidelity, formula_id) in expected.items():
        assert (
            f'"{signal}": ({count}, "{fidelity}", "{formula_id}")'
            in verify
        )

    assert "companyfacts_expected = {" in verify
    assert (
        "for signal, (expected_count, expected_fidelity, expected_formula) "
        "in companyfacts_expected.items():"
    ) in verify
    assert 'bool(companyfacts["data_acquired"])' in verify
    assert 'bool(companyfacts["current_value_calculated"])' in verify
    assert 'companyfacts["current_value_count"] == expected_count' in verify
    assert 'companyfacts["fidelity"] == expected_fidelity' in verify
    assert 'companyfacts["source_used"] == "sec_edgar"' in verify
    assert 'not bool(companyfacts["strict_score_eligible"])' in verify
    assert "len(companyfacts_values) == expected_count" in verify
    assert 'companyfacts_values["source_id"].eq("sec_edgar").all()' in verify
    assert (
        'companyfacts_values["formula_id"].eq(expected_formula).all()'
        in verify
    )
