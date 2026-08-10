from __future__ import annotations

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


def test_all_31_frozen_market_routes_record_the_prepared_free_key_blocker() -> None:
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
        "twelve_data_basic",
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
    assert direct.drop(index="BidAskSpread")["current_remaining_blocker"].eq(
        "twelve_data_basic_free_api_key_missing_4314_credit_resumable_private_"
        "route_and_11_direct_formula_calculators_prepared_unexecuted_historical_"
        "ticker_intervals_coverage_and_fidelity_pending"
    ).all()
    assert direct.loc["BidAskSpread", "current_remaining_blocker"] == (
        "twelve_data_basic_free_api_key_missing_4314_credit_resumable_private_"
        "route_and_1_corwin_schultz_proxy_calculator_prepared_unexecuted_openap_"
        "sas_preprocessing_historical_ticker_intervals_coverage_and_fidelity_"
        "pending"
    )
    assert factor.drop(index="IdioVolAHT")["current_remaining_blocker"].eq(
        "twelve_data_basic_free_api_key_missing_4314_credit_resumable_private_"
        "route_and_10_free_french_factor_calculators_prepared_unexecuted_"
        "historical_ticker_intervals_coverage_and_fidelity_pending"
    ).all()
    assert factor.loc["IdioVolAHT", "current_remaining_blocker"] == (
        "twelve_data_basic_free_api_key_missing_4314_credit_resumable_private_"
        "route_and_1_capm_rmse_calculator_prepared_unexecuted_historical_"
        "ticker_intervals_coverage_and_fidelity_pending"
    )
    assert additional["current_remaining_blocker"].eq(
        "twelve_data_basic_free_api_key_missing_4314_credit_resumable_private_"
        "route_prepared_unexecuted_historical_ticker_intervals_formula_coverage_"
        "and_fidelity_pending"
    ).all()
    assert selected["strict_score_eligible"].astype(str).str.lower().eq(
        "false"
    ).all()


def test_authoritative_oscore_and_orgcap_routes_accept_fred() -> None:
    routes = _module().load_target_routes(ROUTE_MATRIX).set_index("signal")

    oscore_sources = set(routes.loc["OScore", "primary_free_sources"].split("|"))
    orgcap_sources = set(routes.loc["OrgCap", "primary_free_sources"].split("|"))

    assert "fred_public_csv" in oscore_sources
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
    assert "existing_sec_shards_filtered_out_convdebt_candidate_tags" in convdebt_blocker
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
    assert "acquired_separately" in blocker
    assert "selective_13f_recovery_and_join_prepared_unexecuted" in blocker
    assert "coverage_measurement_pending" in blocker
    assert str(routes.loc["IO_ShortInterest", "strict_score_eligible"]).lower() == "false"


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


def test_consolidation_cli_includes_realestate_and_audited_event_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = ROOT / "scripts" / "run_openap_149_consolidate.py"
    spec = util.spec_from_file_location("run_openap_149_consolidate", script_path)
    assert spec is not None and spec.loader is not None
    script = util.module_from_spec(spec)
    spec.loader.exec_module(script)

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
            "--formula-root",
            str(formula_root),
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
    assert 'summary["data_acquired"] == 57' in verify
    assert 'summary["current_values_calculated"] == 51' in verify
    assert 'summary["reconstructed_not_strict"] == 19' in verify
    assert 'summary["blocked"] == summary["pending"] == 98' in verify
    assert 'summary["value_rows"] == 97914' in verify
    assert 'matrix.set_index("signal").loc["FirmAge"]' in verify
    assert 'firm_age["current_value_count"] == 4434' in verify
    assert 'firm_age["fidelity"] == "unvalidated_proxy"' in verify
    assert 'not bool(firm_age["strict_score_eligible"])' in verify
    assert 'matrix_by_signal.loc["CBOperProf"]' in verify
    assert '"CBOperProf", "DelNetFin", "EarningsConsistency"' not in verify
    assert '"declared_current_unusable" in quarantined["remaining_blocker"]' in verify
    assert 'matrix.set_index("signal").loc["OScore"]' in verify
    assert 'oscore["current_value_count"] == 1100' in verify
    assert 'oscore["source_used"] == "fred|sec_edgar"' in verify
    assert 'oscore_values["source_id"].eq("sec_edgar|fred_public_csv").all()' in verify


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
        "DivOmit": (
            14,
            "reconstructed",
            "openap_divomit_positive_sec_6q_regular_then_zero_2m",
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
