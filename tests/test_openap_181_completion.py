from __future__ import annotations

import gzip
import runpy
import sys
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked
from aurora.research.openap_181.analyst_batch import (
    ANALYST_BLOCKERS,
    ANALYST_SIGNAL_FAMILIES,
    ANALYST_SIGNALS,
)
from aurora.research.openap_181.completion import (
    CURRENT_EXACT_31,
    CURRENT_EXCLUDED_27,
    CURRENT_PROXY_61,
    CompletionError,
    attach_runtime_evidence,
    build_completion_manifest,
    build_source_catalog,
    source_can_satisfy,
    write_completion_outputs,
)
from aurora.research.openap_93.registry import REQUIRED_93
from aurora.research.openap_181.official_formulas import (
    OPENAP_FORMULA_COMMIT,
    _fetch_bytes,
    build_formula_inventory,
    write_formula_bundle,
)
from aurora.research.openap_181.source_research import (
    ALLOWED_CLASSIFICATIONS,
    build_signal_resolution,
    build_signal_source_matrix,
    build_source_inventory,
    write_source_research_outputs,
)


def _signal_doc() -> pd.DataFrame:
    names = sorted(
        set(CURRENT_EXACT_31)
        | set(CURRENT_PROXY_61)
        | set(REQUIRED_93)
        | set(CURRENT_EXCLUDED_27)
    )
    return pd.DataFrame(
        {
            "Acronym": names,
            "Cat.Data": ["Accounting"] * len(names),
            "Detailed Definition": [f"Official definition for {name}" for name in names],
            "Portfolio Period": [1] * len(names),
            "tstat": [2.5] * len(names),
            "T.Stat": [2.1] * len(names),
        }
    )


def test_canonical_partition_is_31_plus_181_equals_212():
    manifest = build_completion_manifest(_signal_doc())
    assert len(CURRENT_EXACT_31) == 31
    assert len(CURRENT_PROXY_61) == 61
    assert len(REQUIRED_93) == 93
    assert len(CURRENT_EXCLUDED_27) == 27
    assert len(manifest) == 181
    assert manifest["signal"].nunique() == 181
    assert not manifest["current_usable"].any()
    assert not manifest["evidence_complete"].any()


def test_manifest_fails_when_a_canonical_signal_is_missing_from_signal_doc():
    doc = _signal_doc().iloc[:-1].copy()
    try:
        build_completion_manifest(doc)
    except CompletionError as exc:
        assert "absent from SignalDoc" in str(exc)
    else:
        raise AssertionError("Incomplete SignalDoc must fail closed")


def test_manifest_ignores_official_rows_outside_the_strict_212():
    doc = pd.concat(
        [_signal_doc(), pd.DataFrame([{"Acronym": "MethodologyOnlyExtra"}])],
        ignore_index=True,
    )
    manifest = build_completion_manifest(doc)
    assert len(manifest) == 181
    assert "MethodologyOnlyExtra" not in set(manifest["signal"])


def test_source_semantics_prevent_false_substitutions():
    assert not source_can_satisfy("ShortInterest", "finra_short_sale_volume")
    assert source_can_satisfy("ShortInterest", "finra_equity_short_interest")
    assert not source_can_satisfy("SmileSlope", "cboe_public_aggregate")
    assert not source_can_satisfy("SmileSlope", "marketdata_options_free")
    assert not source_can_satisfy("SmileSlope", "tradier_personal_api")
    assert not source_can_satisfy("SmileSlope", "occ_option_volume")
    assert not source_can_satisfy("dVolPut", "massive_options_basic")
    assert not source_can_satisfy("OptionVolume1", "cboe_public_aggregate")
    assert not source_can_satisfy("PatentsRD", "uspto_patentsview_bulk")
    assert not source_can_satisfy("CitationsRD", "kpss_patent_crsp_extended")
    assert not source_can_satisfy("PatentsRD", "kpss_patent_crsp_extended")


def test_manifest_uses_concrete_family_blockers():
    manifest = build_completion_manifest(_signal_doc()).set_index("signal")
    assert (
        manifest.loc["SmileSlope", "blocker_code"]
        == "authorized_current_option_surface_missing"
    )
    assert (
        manifest.loc["dVolPut", "blocker_code"]
        == "authorized_current_option_surface_missing"
    )
    assert (
        manifest.loc["ShortInterest", "blocker_code"]
        == "listed_short_interest_history_and_stock_validation_required"
    )
    assert manifest.loc["CitationsRD", "blocker_code"] == (
        "patent_five_year_scaled_citations_and_exact_xrd_stock_validation_required"
    )
    assert manifest.loc["PatentsRD", "blocker_code"] == (
        "patent_counts_exact_xrd_and_stock_validation_required"
    )
    assert (
        manifest.loc["zerotrade1M", "blocker_code"]
        == "daily_zero_trade_days_shares_and_calendar_validation_required"
    )


def test_source_catalog_documents_rights_and_scope():
    catalog = build_source_catalog().set_index("source_id")
    assert bool(catalog.loc["uspto_patentsview_bulk", "free"])
    assert bool(catalog.loc["uspto_patentsview_bulk", "authorized_automation"])
    assert bool(catalog.loc["google_patents_bigquery", "free"])
    assert bool(catalog.loc["google_patents_bigquery", "authorized_automation"])
    assert "assignee_to_public_issuer_crosswalk" in catalog.loc[
        "google_patents_bigquery", "cannot_satisfy"
    ]
    assert bool(catalog.loc["uspto_odp_patentsview", "authorized_automation"])
    assert bool(catalog.loc["kpss_patent_crsp_extended", "free"])
    assert bool(catalog.loc["kpss_patent_crsp_extended", "authorized_automation"])
    assert "patent_permno_permco_bridge" in catalog.loc[
        "kpss_patent_crsp_extended", "satisfies"
    ]
    assert "openap_five_year_subcategory_scaled_ncitscale" in catalog.loc[
        "kpss_patent_crsp_extended", "cannot_satisfy"
    ]
    assert "exact_xrd" in catalog.loc[
        "kpss_patent_crsp_extended", "cannot_satisfy"
    ]
    assert "raw_redistribution_without_explicit_license" in catalog.loc[
        "kpss_patent_crsp_extended", "cannot_satisfy"
    ]
    assert not bool(catalog.loc["cboe_delayed_options", "authorized_automation"])
    assert not bool(catalog.loc["marketdata_options_free", "authorized_automation"])
    assert not bool(catalog.loc["exchange_short_interest", "free"])
    assert bool(catalog.loc["finra_equity_short_interest", "free"])
    assert bool(catalog.loc["finra_equity_short_interest", "authorized_automation"])
    assert bool(catalog.loc["sec_financial_statement_datasets", "free"])
    assert bool(catalog.loc["sec_financial_statement_datasets", "authorized_automation"])
    assert bool(catalog.loc["occ_option_volume", "free"])
    assert not bool(catalog.loc["occ_option_volume", "authorized_automation"])
    assert bool(catalog.loc["tradier_personal_api", "free"])
    assert bool(catalog.loc["tradier_personal_api", "authorized_automation"])
    assert bool(catalog.loc["massive_options_basic", "free"])
    assert not bool(catalog.loc["massive_options_basic", "authorized_automation"])
    assert not bool(catalog.loc["alpha_vantage_options_premium", "free"])
    assert not bool(catalog.loc["optionmetrics_ivydb_us", "free"])
    assert not bool(catalog.loc["crsp_stock_commercial", "free"])
    assert not bool(catalog.loc["compustat_commercial", "free"])
    assert not bool(catalog.loc["lseg_ibes_commercial", "free"])
    assert not bool(catalog.loc["nyse_taq_commercial", "free"])
    assert bool(catalog.loc["edwin_hu_pin", "authorized_automation"])
    assert bool(catalog.loc["twelve_data_basic", "authorized_automation"])
    assert bool(catalog.loc["tiingo_starter", "authorized_automation"])
    assert not bool(catalog.loc["kenneth_french_factors", "authorized_automation"])
    assert "historical_point_in_time_identity_guarantee" in catalog.loc[
        "openfigi", "cannot_satisfy"
    ]
    assert "short_interest" in catalog.loc["finra_short_sale_volume", "cannot_satisfy"]


def test_outputs_never_claim_completion_for_unvalidated_baseline(tmp_path):
    summary = write_completion_outputs(build_completion_manifest(_signal_doc()), tmp_path)
    assert summary["unfinished_signals"] == 181
    assert summary["ready_after_audit"] == 0
    assert summary["completion_claimed"] is False
    assert summary["fail_closed"] is True
    assert summary["locked_opened"] is False
    assert (tmp_path / "openap_181_completion_manifest.csv").is_file()


def test_runtime_coverage_and_tstats_do_not_bypass_validation():
    manifest = build_completion_manifest(_signal_doc())
    runtime = attach_runtime_evidence(
        manifest,
        reproduction_summary=pd.DataFrame(
            {"signalname": ["BM", "ShortInterest"], "tstat": [4.2, 3.1]}
        ),
        current_features=pd.DataFrame({"BM": [1.0, None, 3.0]}),
        coverage_93=pd.DataFrame(
            {
                "signal": ["ShortInterest"],
                "status": ["research_only"],
                "fidelity_class": ["unvalidated_proxy"],
                "non_null_count": [2],
                "coverage_pct": [66.67],
                "paired_observations": [0],
                "spearman": [None],
                "extreme_decile_agreement": [None],
            }
        ),
        formula_inventory=pd.DataFrame(
            {
                "signal": ["BM"],
                "status": ["resolved"],
                "path": ["Signals/pyCode/Predictors/BM.py"],
                "commit": [OPENAP_FORMULA_COMMIT],
                "source_url": ["https://example.test/BM.py"],
                "sha256": ["a" * 64],
            }
        ),
    ).set_index("signal")
    assert runtime.loc["BM", "raw_current_non_null_count"] == 2
    assert runtime.loc["BM", "reproduction_tstat"] == 4.2
    assert runtime.loc["ShortInterest", "raw_current_non_null_count"] == 2
    assert runtime.loc["ShortInterest", "raw_status"] == "research_only"
    assert runtime.loc["BM", "formula_status"] == "resolved"
    assert runtime.loc["BM", "formula_sha256"] == "a" * 64
    assert not runtime["current_usable"].any()
    assert not runtime["evidence_complete"].any()


def test_current_185_coverage_is_attached_without_promotion():
    manifest = build_completion_manifest(_signal_doc())
    runtime = attach_runtime_evidence(
        manifest,
        current_coverage=pd.DataFrame(
            {
                "signalname": ["BM", "ShortInterest", "SmileSlope"],
                "coverage_status": ["proxy", "unavailable", "mixed"],
                "symbols_with_value": [12, 0, 4],
                "coverage_pct": [40.0, 0.0, 13.33],
                "unavailable_reasons": ["", "listed_short_interest_missing", ""],
                "value_sources": ["sec", "", "sec|yahoo"],
            }
        ),
    ).set_index("signal")
    assert runtime.loc["BM", "raw_current_non_null_count"] == 12
    assert runtime.loc["BM", "raw_fidelity"] == "unvalidated_proxy"
    assert runtime.loc["ShortInterest", "raw_status"] == "current_unavailable_unvalidated"
    assert runtime.loc["ShortInterest", "raw_unavailable_reasons"] == (
        "listed_short_interest_missing"
    )
    assert runtime.loc["SmileSlope", "raw_fidelity"] == (
        "mixed_exact_proxy_unvalidated"
    )
    assert runtime.loc["AOP", "raw_status"] == "excluded_from_current_score_universe"
    assert not runtime["current_usable"].any()
    assert not runtime["evidence_complete"].any()


def test_official_formula_fetch_decodes_gzip_responses(
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeResponse:
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return gzip.compress(b'{"tree": []}')

    monkeypatch.setattr(
        "aurora.research.openap_181.official_formulas.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    assert _fetch_bytes("https://example.test/tree", attempts=1) == b'{"tree": []}'


def test_official_formula_fetch_authenticates_only_github_api(
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeResponse:
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"{}"

    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse()

    monkeypatch.setenv("GITHUB_TOKEN", "ephemeral-actions-token")
    monkeypatch.setattr(
        "aurora.research.openap_181.official_formulas.urllib.request.urlopen",
        fake_urlopen,
    )

    _fetch_bytes("https://api.github.com/repos/example/repo/git/trees/sha", attempts=1)
    _fetch_bytes("https://raw.githubusercontent.com/example/repo/sha/a.py", attempts=1)

    api_headers = dict(requests[0].header_items())
    raw_headers = dict(requests[1].header_items())
    assert api_headers["Authorization"] == "Bearer ephemeral-actions-token"
    assert "Authorization" not in raw_headers


def test_formula_inventory_prefers_exact_and_explicit_official_outputs(tmp_path):
    sources = {
        "Signals/pyCode/Predictors/BM.py": b'save_predictor(df, "BM")\n',
        "Signals/pyCode/Predictors/ZZ1_Size_AM.py": (
            b'save_predictor(df, "Size")\nsave_predictor(df, "AM")\n'
        ),
        "Signals/pyCode/Predictors/Reference.py": b'# BM is discussed only\n',
    }
    inventory = build_formula_inventory(["BM", "AM", "Missing"], sources)
    indexed = inventory.set_index("signal")
    assert indexed.loc["BM", "status"] == "resolved"
    assert indexed.loc["BM", "match_method"] == "exact_filename"
    assert indexed.loc["AM", "status"] == "resolved"
    assert indexed.loc["AM", "match_method"] == "explicit_output"
    assert indexed.loc["Missing", "status"] == "unresolved"
    summary = write_formula_bundle(inventory, sources, tmp_path)
    assert summary["signals"] == 3
    assert summary["resolved"] == 2
    assert (tmp_path / "openap_181_formula_inventory.csv").is_file()


def test_formula_inventory_prefers_current_python_over_legacy_stata():
    sources = {
        "Signals/pyCode/Predictors/BM.py": b'save_predictor(df, "BM")\n',
        "Signals/LegacyStataCode/Predictors/BM.do": b"save BM.csv\n",
    }

    match = build_formula_inventory(["BM"], sources).iloc[0]

    assert match["status"] == "resolved"
    assert match["path"] == "Signals/pyCode/Predictors/BM.py"
    assert match["candidate_count"] == 2


def test_formula_inventory_remains_ambiguous_with_two_current_python_matches():
    sources = {
        "Signals/pyCode/Predictors/ZZ1_BM.py": b'save_predictor(df, "BM")\n',
        "Signals/pyCode/Predictors/ZZ2_BM.py": b'save_predictor(df, "BM")\n',
        "Signals/LegacyStataCode/Predictors/BM.do": b"save BM.csv\n",
    }

    match = build_formula_inventory(["BM"], sources).iloc[0]

    assert match["status"] == "ambiguous"
    assert match["candidate_count"] == 2
    assert "Signals/LegacyStataCode" not in match["path"]


def test_formula_inventory_resolves_outputs_saved_from_a_literal_loop_collection():
    path = (
        "Signals/pyCode/Predictors/"
        "ZZ1_RIO_MB_RIO_Disp_RIO_Turnover_RIO_Volatility.py"
    )
    sources = {
        path: (
            b'rio_predictors = ["RIO_MB", "RIO_Disp", "RIO_Turnover", '
            b'"RIO_Volatility"]\n'
            b"for predictor in rio_predictors:\n"
            b"    save_predictor(result, predictor)\n"
        )
    }

    inventory = build_formula_inventory(
        ["RIO_MB", "RIO_Disp", "RIO_Turnover", "RIO_Volatility"], sources
    )

    assert inventory["status"].eq("resolved").all()
    assert inventory["path"].eq(path).all()
    assert inventory["match_method"].eq("explicit_output").all()


def _formula_inventory_for_source_research(manifest: pd.DataFrame) -> pd.DataFrame:
    rio = {"RIO_Disp", "RIO_MB", "RIO_Turnover", "RIO_Volatility"}
    return pd.DataFrame(
        {
            "signal": manifest["signal"],
            "status": [
                "unresolved" if signal in rio else "resolved"
                for signal in manifest["signal"]
            ],
            "source_url": [
                "https://example.test/formula/" + signal
                for signal in manifest["signal"]
            ],
        }
    )


def test_source_research_classifies_all_181_fail_closed():
    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")

    assert len(resolution) == 181
    assert resolution.index.nunique() == 181
    assert set(resolution["final_research_classification"]).issubset(
        ALLOWED_CLASSIFICATIONS
    )
    assert resolution.loc[
        "RIO_MB", "final_research_classification"
    ] == "formula_ambiguous"
    assert resolution.loc[
        "ShortInterest", "final_research_classification"
    ] == "historical_point_in_time_missing"
    assert resolution.loc[
        "SmileSlope", "final_research_classification"
    ] == "historical_point_in_time_missing"
    assert resolution.loc[
        "CitationsRD", "final_research_classification"
    ] == "multiple_sources_required"
    assert resolution.loc[
        "PatentsRD", "final_research_classification"
    ] == "multiple_sources_required"
    assert "kpss_patent_crsp_extended" in resolution.loc[
        "PatentsRD", "best_free_source_option"
    ]
    assert resolution.loc[
        "AgeIPO", "final_research_classification"
    ] == "source_access_unverified"
    assert resolution.loc[
        "ProbInformedTrading", "final_research_classification"
    ] == "historical_point_in_time_missing"
    assert resolution.loc[
        "zerotrade1M", "final_research_classification"
    ] == "multiple_sources_required"
    assert resolution.loc[
        "CustomerMomentum", "final_research_classification"
    ] == "no_free_authorized_source"
    assert resolution.loc[
        "iomom_supp", "final_research_classification"
    ] == "identifier_bridge_missing"
    for signal in {"AnalystValue", "ChNAnalyst", "ConsRecomm", "REV6"}:
        assert resolution.loc[
            signal, "final_research_classification"
        ] == "historical_point_in_time_missing"
        assert resolution.loc[signal, "remaining_blocker"].startswith(
            "point_in_time_ibes_history_missing_or_unvalidated:"
        )
    assert resolution.loc["DivInit", "final_research_classification"] == "proxy_only"
    assert not resolution.astype(str).apply(
        lambda column: column.str.lower().eq("nan").any()
    ).any()


def test_source_research_inventory_and_matrix_cover_manifest():
    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    resolution = build_signal_resolution(manifest, formulas)
    inventory = build_source_inventory().set_index("source_id")
    matrix = build_signal_source_matrix(manifest, formulas, resolution)

    assert inventory.index.is_unique
    assert set(matrix["signal"]) == set(manifest["signal"])
    assert not bool(inventory.loc["tiingo_starter", "aurora_project_use_authorized"])
    assert not bool(inventory.loc["fmp_basic", "aurora_project_use_authorized"])
    assert bool(inventory.loc["twelve_data_basic", "aurora_project_use_authorized"])
    assert bool(inventory.loc[
        "sec_financial_statement_datasets", "aurora_project_use_authorized"
    ])
    assert not bool(inventory.loc["occ_option_volume", "aurora_project_use_authorized"])
    assert not bool(
        inventory.loc["tradier_personal_api", "aurora_project_use_authorized"]
    )
    assert not bool(
        inventory.loc["massive_options_basic", "aurora_project_use_authorized"]
    )
    assert (
        inventory.loc["alpha_vantage_options_premium", "free_access_class"]
        == "commercial"
    )
    assert inventory.loc["optionmetrics_ivydb_us", "free_access_class"] == "commercial"
    assert matrix["coverage_verified"].eq(False).all()
    matrix_sources = matrix.groupby("signal")["source_name"].agg(set)
    assert "SEC Financial Statement Data Sets" in matrix_sources["AM"]
    assert "S&P Compustat North America and historical segments" in matrix_sources["AM"]
    assert "Tradier personal brokerage API" in matrix_sources["SmileSlope"]
    assert "Massive Options Basic" in matrix_sources["SmileSlope"]
    assert "Alpha Vantage Historical Options" in matrix_sources["SmileSlope"]
    assert "OptionMetrics IvyDB US" in matrix_sources["SmileSlope"]
    assert "LSEG I/B/E/S" in matrix_sources["AnalystRevision"]


def test_analyst_source_matrix_uses_family_specific_sources_and_blockers():
    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    inventory = build_source_inventory().set_index("source_id")

    assert {
        "nasdaq_zacks_premium",
        "zacks_data_commercial",
        "intrinio_zacks_enterprise",
        "simfin_free",
    }.issubset(set(inventory.index))
    assert not bool(
        inventory.loc["nasdaq_zacks_premium", "aurora_project_use_authorized"]
    )
    assert not bool(
        inventory.loc["zacks_data_commercial", "aurora_project_use_authorized"]
    )
    assert not bool(
        inventory.loc["intrinio_zacks_enterprise", "aurora_project_use_authorized"]
    )
    assert not bool(inventory.loc["simfin_free", "aurora_project_use_authorized"])

    for signal in ANALYST_SIGNALS:
        row = resolution.loc[signal]
        sources = set(str(row["sources_required"]).split("|"))
        assert row["remaining_blocker"] == ANALYST_BLOCKERS[signal]
        assert {
            "openap_official",
            "lseg_ibes_commercial",
            "alpha_vantage_free",
            "fmp_basic",
            "twelve_data_basic",
            "nasdaq_zacks_premium",
            "zacks_data_commercial",
            "intrinio_zacks_enterprise",
        }.issubset(sources)
        assert "yahoo_public" not in sources
        assert "tiingo_starter" not in sources

        family = ANALYST_SIGNAL_FAMILIES[signal]
        if family in {
            "accounting_compustat",
            "ibes_mixed",
            "ibes_compustat_crsp_cross_section",
        }:
            assert {
                "sec_edgar",
                "sec_financial_statement_datasets",
                "simfin_free",
                "compustat_commercial",
                "crsp_stock_commercial",
                "wrds_linking_suite",
            }.issubset(sources)
        else:
            assert "sec_financial_statement_datasets" not in sources


def test_source_research_writer_creates_five_mandatory_files(tmp_path):
    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    summary = write_source_research_outputs(manifest, formulas, tmp_path)

    assert summary["signals"] == summary["unique_signals"] == 181
    assert summary["completion_claimed"] is False
    assert summary["coverage_claimed"] is False
    for name in {
        "signal_source_matrix_181.csv",
        "signal_resolution_181.csv",
        "source_inventory_free.csv",
        "unresolved_signals.csv",
        "RESEARCH_REPORT.md",
    }:
        assert (tmp_path / name).is_file()


def _implementation_status_module():
    from importlib import import_module

    return import_module("aurora.research.openap_181.implementation_status")


def _implementation_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    resolution = build_signal_resolution(manifest, formulas)
    return manifest, resolution


def _cash_evidence(*, fidelity_measured: bool) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal": "Cash",
                "formula_implemented": True,
                "data_pipeline_implemented": True,
                "point_in_time_verified": True,
                "identity_verified": True,
                "coverage_measured": True,
                "fidelity_measured": fidelity_measured,
                "coverage_result": "pass",
                "fidelity_result": "pass" if fidelity_measured else "not_measured",
                "strict_gate_result": "approved",
                "blocking_reason": "none" if fidelity_measured else "fidelity_not_measured",
                "evidence_run_url": "https://github.com/example/aurora/actions/runs/1",
                "evidence_artifact": "openap-cash-validation",
                "implementation_commit": "a" * 40,
            }
        ]
    )


def test_implementation_status_defaults_all_181_signals_fail_closed():
    module = _implementation_status_module()
    manifest, resolution = _implementation_inputs()

    status = module.build_signal_implementation_status(manifest, resolution)

    assert list(status.columns) == [
        "signal",
        "formula_implemented",
        "data_pipeline_implemented",
        "point_in_time_verified",
        "identity_verified",
        "coverage_measured",
        "fidelity_measured",
        "coverage_result",
        "fidelity_result",
        "strict_gate_result",
        "score_eligible",
        "blocking_reason",
        "evidence_run_url",
        "evidence_artifact",
        "implementation_commit",
    ]
    assert len(status) == status["signal"].nunique() == 181
    assert set(status["signal"]) == set(manifest["signal"])
    assert not status["score_eligible"].any()
    assert status["strict_gate_result"].eq("not_attempted").all()
    assert status["blocking_reason"].astype(str).str.strip().ne("").all()


def test_implementation_status_requires_every_gate_and_complete_evidence():
    module = _implementation_status_module()
    manifest, resolution = _implementation_inputs()

    partial = module.build_signal_implementation_status(
        manifest,
        resolution,
        _cash_evidence(fidelity_measured=False),
    ).set_index("signal")
    approved = module.build_signal_implementation_status(
        manifest,
        resolution,
        _cash_evidence(fidelity_measured=True),
    ).set_index("signal")

    assert not bool(partial.loc["Cash", "score_eligible"])
    assert partial.loc["Cash", "strict_gate_result"] == "blocked"
    assert partial.loc["Cash", "blocking_reason"] == "fidelity_not_measured"
    assert bool(approved.loc["Cash", "score_eligible"])
    assert approved.loc["Cash", "strict_gate_result"] == "approved"
    assert approved.loc["Cash", "blocking_reason"] == "none"


def test_documentary_blockers_create_evidence_without_promoting_plausible_routes():
    module = _implementation_status_module()
    manifest, resolution = _implementation_inputs()

    evidence = module.build_documentary_blocker_evidence(
        resolution,
        evidence_run_url="https://github.com/example/aurora/actions/runs/8",
        evidence_artifact="openap-181-completion-audit-results",
        implementation_commit="2" * 40,
    )
    status = module.build_signal_implementation_status(
        manifest,
        resolution,
        evidence,
    )

    assert len(evidence) == evidence["signal"].nunique() == 58
    assert set(
        evidence["blocking_reason"].str.split(":", n=1).str[0]
    ) == {
        "formula_ambiguous",
        "historical_point_in_time_missing",
        "identifier_bridge_missing",
        "no_free_authorized_source",
        "proxy_only",
        "source_access_unverified",
    }
    assert evidence["strict_gate_result"].eq("blocked").all()
    assert not evidence["formula_implemented"].any()
    assert not evidence["data_pipeline_implemented"].any()
    assert status["strict_gate_result"].eq("blocked").sum() == 58
    assert status["strict_gate_result"].eq("not_attempted").sum() == 123
    assert not status["score_eligible"].any()
    plausible = status.loc[status["signal"].eq("Cash")].iloc[0]
    assert plausible["strict_gate_result"] == "not_attempted"


def test_explicit_evidence_replaces_only_matching_generic_documentary_blocker():
    module = _implementation_status_module()
    _, resolution = _implementation_inputs()
    documentary = module.build_documentary_blocker_evidence(
        resolution,
        evidence_run_url="https://github.com/example/aurora/actions/runs/8",
        evidence_artifact="openap-181-completion-audit-results",
        implementation_commit="2" * 40,
    )
    explicit = documentary.loc[documentary["signal"].eq("ShortInterest")].copy()
    explicit["formula_implemented"] = True
    explicit["blocking_reason"] = (
        "short_interest_source_partial:exact_monthly_crsp_shrout_unavailable"
    )
    explicit["evidence_run_url"] = (
        "https://github.com/example/aurora/actions/runs/9"
    )
    explicit["evidence_artifact"] = "openap-181-short-interest-source-probe-results"

    merged = module.merge_generated_and_explicit_evidence(
        [documentary],
        [explicit],
    ).set_index("signal")

    assert len(merged) == 58
    assert bool(merged.loc["ShortInterest", "formula_implemented"])
    assert merged.loc["ShortInterest", "blocking_reason"].startswith(
        "short_interest_source_partial:"
    )
    assert merged.loc["ShortInterest", "evidence_run_url"].endswith("/9")
    with pytest.raises(ValueError, match="duplicate signals"):
        module.merge_generated_and_explicit_evidence(
            [documentary],
            [explicit, explicit],
        )


def test_implementation_cli_attaches_documentary_blocker_evidence(
    tmp_path,
    monkeypatch,
):
    manifest, resolution = _implementation_inputs()
    manifest_path = tmp_path / "manifest.csv"
    resolution_path = tmp_path / "resolution.csv"
    output = tmp_path / "outputs"
    manifest.to_csv(manifest_path, index=False)
    resolution.to_csv(resolution_path, index=False)
    script = Path(__file__).parents[1] / "scripts" / "run_openap_181_implementation_status.py"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--manifest",
            str(manifest_path),
            "--resolution",
            str(resolution_path),
            "--output-dir",
            str(output),
            "--documentary-blockers",
            "--evidence-run-url",
            "https://github.com/example/aurora/actions/runs/8",
            "--evidence-artifact",
            "openap-181-completion-audit-results",
            "--implementation-commit",
            "2" * 40,
        ],
    )

    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(script), run_name="__main__")

    assert result.value.code == 0
    status = pd.read_csv(output / "signal_implementation_status_181.csv")
    report = (output / "IMPLEMENTATION_VALIDATION_REPORT.md").read_text(
        encoding="utf-8"
    )
    assert status["strict_gate_result"].eq("blocked").sum() == 58
    assert status["strict_gate_result"].eq("not_attempted").sum() == 123
    assert not status["score_eligible"].any()
    assert "- Signals blocked with evidence: 58" in report
    assert "- Signals not attempted: 123" in report


def test_missing_twelve_data_credential_blocks_only_dependent_market_routes():
    module = _implementation_status_module()
    manifest, resolution = _implementation_inputs()
    common = {
        "evidence_run_url": "https://github.com/example/aurora/actions/runs/9",
        "evidence_artifact": "openap-181-completion-audit-results",
        "implementation_commit": "3" * 40,
    }

    missing = module.build_twelve_data_credential_blocker_evidence(
        resolution,
        credential_available=False,
        **common,
    )
    available = module.build_twelve_data_credential_blocker_evidence(
        resolution,
        credential_available=True,
        **common,
    )
    documentary = module.build_documentary_blocker_evidence(resolution, **common)
    status = module.build_signal_implementation_status(
        manifest,
        resolution,
        pd.concat([documentary, missing], ignore_index=True),
    )
    expected = {
        "Activism1",
        "Activism2",
        "Beta",
        "BetaFP",
        "BetaLiquidityPS",
        "BetaTailRisk",
        "BidAskSpread",
        "CoskewACX",
        "Coskewness",
        "FirmAgeMom",
        "Herf",
        "HerfAsset",
        "HerfBE",
        "High52",
        "IdioVol3F",
        "IdioVolAHT",
        "IndMom",
        "IndRetBig",
        "MomOffSeason11YrPlus",
        "MomRev",
        "MomVol",
        "PriceDelayRsq",
        "PriceDelaySlope",
        "PriceDelayTstat",
        "RealizedVol",
        "ResidualMomentum",
        "ReturnSkew3F",
        "Size",
        "TrendFactor",
        "VolMkt",
        "VolSD",
        "VolumeTrend",
        "std_turn",
        "zerotrade12M",
        "zerotrade1M",
        "zerotrade6M",
    }

    assert len(missing) == missing["signal"].nunique() == 36
    assert set(missing["signal"]) == expected
    assert missing["blocking_reason"].eq(
        "credential_missing:twelve_data_basic_api_key_not_configured"
    ).all()
    assert not missing["formula_implemented"].any()
    assert not missing["data_pipeline_implemented"].any()
    assert available.empty
    assert status["strict_gate_result"].eq("blocked").sum() == 94
    assert status["strict_gate_result"].eq("not_attempted").sum() == 87
    assert not status["score_eligible"].any()


def test_implementation_cli_attaches_missing_twelve_data_credential_blockers(
    tmp_path,
    monkeypatch,
):
    manifest, resolution = _implementation_inputs()
    manifest_path = tmp_path / "manifest.csv"
    resolution_path = tmp_path / "resolution.csv"
    output = tmp_path / "outputs"
    manifest.to_csv(manifest_path, index=False)
    resolution.to_csv(resolution_path, index=False)
    script = Path(__file__).parents[1] / "scripts" / "run_openap_181_implementation_status.py"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--manifest",
            str(manifest_path),
            "--resolution",
            str(resolution_path),
            "--output-dir",
            str(output),
            "--documentary-blockers",
            "--twelve-data-credential-check",
            "--evidence-run-url",
            "https://github.com/example/aurora/actions/runs/9",
            "--evidence-artifact",
            "openap-181-completion-audit-results",
            "--implementation-commit",
            "3" * 40,
        ],
    )

    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(script), run_name="__main__")

    assert result.value.code == 0
    status = pd.read_csv(output / "signal_implementation_status_181.csv")
    assert status["strict_gate_result"].eq("blocked").sum() == 94
    assert status["strict_gate_result"].eq("not_attempted").sum() == 87
    assert not status["score_eligible"].any()


def test_strict_inventory_starts_at_31_and_only_accepts_fully_gated_signals():
    module = _implementation_status_module()
    manifest, resolution = _implementation_inputs()
    baseline = module.build_signal_implementation_status(manifest, resolution)
    partial = module.build_signal_implementation_status(
        manifest,
        resolution,
        _cash_evidence(fidelity_measured=False),
    )
    approved = module.build_signal_implementation_status(
        manifest,
        resolution,
        _cash_evidence(fidelity_measured=True),
    )

    baseline_inventory = module.build_strict_score_inventory(baseline)
    partial_inventory = module.build_strict_score_inventory(partial)
    approved_inventory = module.build_strict_score_inventory(approved)

    assert set(baseline_inventory["signal"]) == set(CURRENT_EXACT_31)
    assert set(partial_inventory["signal"]) == set(CURRENT_EXACT_31)
    assert len(baseline_inventory) == len(partial_inventory) == 31
    assert set(approved_inventory["signal"]) == set(CURRENT_EXACT_31) | {"Cash"}
    assert len(approved_inventory) == 32
    promoted = approved_inventory.set_index("signal").loc["Cash"]
    assert promoted["eligibility_basis"] == "openap_181_complete_strict_gates"
    assert promoted["evidence_artifact"] == "openap-cash-validation"


def test_implementation_writer_creates_three_auditable_baseline_artifacts(tmp_path):
    module = _implementation_status_module()
    manifest, resolution = _implementation_inputs()

    summary = module.write_implementation_outputs(manifest, resolution, tmp_path)

    status_path = tmp_path / "signal_implementation_status_181.csv"
    inventory_path = tmp_path / "strict_score_signal_inventory.csv"
    report_path = tmp_path / "IMPLEMENTATION_VALIDATION_REPORT.md"
    status = pd.read_csv(status_path)
    inventory = pd.read_csv(inventory_path)
    report = report_path.read_text(encoding="utf-8")
    assert summary == {
        "signals": 181,
        "unique_signals": 181,
        "attempted": 0,
        "approved": 0,
        "blocked": 0,
        "not_attempted": 181,
        "strict_inventory_signals": 31,
    }
    assert len(status) == status["signal"].nunique() == 181
    assert not status["score_eligible"].any()
    assert set(inventory["signal"]) == set(CURRENT_EXACT_31)
    assert len(inventory) == 31
    assert "# OpenAP 181 Implementation Validation Report" in report
    assert "Signals approved: 0" in report
    assert "Strict score signals: 31" in report
    assert all(f"`{signal}`" in report for signal in CURRENT_EXACT_31)
    assert status_path.stat().st_size > 0
    assert inventory_path.stat().st_size > 0
    assert report_path.stat().st_size > 0


def test_implementation_cli_fails_closed_outside_github(tmp_path, monkeypatch):
    manifest, resolution = _implementation_inputs()
    manifest_path = tmp_path / "manifest.csv"
    resolution_path = tmp_path / "resolution.csv"
    manifest.to_csv(manifest_path, index=False)
    resolution.to_csv(resolution_path, index=False)
    script = Path(__file__).parents[1] / "scripts" / "run_openap_181_implementation_status.py"
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--manifest",
            str(manifest_path),
            "--resolution",
            str(resolution_path),
            "--output-dir",
            str(tmp_path / "outputs"),
        ],
    )

    with pytest.raises(LocalRunBlocked, match="OpenAP 181 implementation status"):
        runpy.run_path(str(script), run_name="__main__")


def test_relationship_source_matrix_uses_exact_family_routes_and_blockers():
    from aurora.research.openap_181.relationship_batch import (
        RELATIONSHIP_BLOCKERS,
        RELATIONSHIP_SIGNALS,
    )

    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    inventory = build_source_inventory().set_index("source_id")
    matrix = build_signal_source_matrix(
        manifest, formulas, resolution.reset_index()
    )

    assert "factset_supply_chain_commercial" in inventory.index
    assert bool(
        inventory.loc[
            "factset_supply_chain_commercial", "aurora_project_use_authorized"
        ]
    ) is False
    assert set(RELATIONSHIP_SIGNALS) == {
        "CustomerMomentum", "iomom_cust", "iomom_supp", "retConglomerate", "sinAlgo"
    }
    assert resolution.loc[
        list(RELATIONSHIP_SIGNALS), "remaining_blocker"
    ].to_dict() == RELATIONSHIP_BLOCKERS

    routes = {
        signal: set(matrix.loc[matrix["signal"].eq(signal), "source_name"])
        for signal in RELATIONSHIP_SIGNALS
    }
    assert any("BEA" in source for source in routes["iomom_cust"])
    assert any("Census" in source for source in routes["iomom_supp"])
    assert any("FactSet" in source for source in routes["CustomerMomentum"])
    assert any("Compustat" in source for source in routes["retConglomerate"])
    assert any("Compustat" in source for source in routes["sinAlgo"])

    relationship = matrix.loc[matrix["signal"].isin(RELATIONSHIP_SIGNALS)]
    assert relationship["blocking_reason"].str.startswith(
        "relationship_source_blocked:"
    ).all()
    assert relationship["blocking_reason"].nunique() == 5


def test_microstructure_source_matrix_uses_exact_family_routes_and_blockers():
    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    inventory = build_source_inventory().set_index("source_id")
    matrix = build_signal_source_matrix(
        manifest, formulas, resolution.reset_index()
    )
    signals = {
        "BidAskSpread",
        "ProbInformedTrading",
        "zerotrade1M",
        "zerotrade6M",
        "zerotrade12M",
    }
    expected_blockers = {
        "BidAskSpread": (
            "microstructure_source_blocked:exact_crsp_bidlo_askhi_prc_volume_semantics+"
            "permno_history+delistings+full_coverage_unavailable_free"
        ),
        "ProbInformedTrading": (
            "microstructure_source_blocked:exact_pin_parameters_end_2012+current_exact_pin+"
            "historical_permno_to_current_security_identity_unavailable"
        ),
        "zerotrade1M": (
            "microstructure_source_blocked:daily_crsp_zero_volume_rows+pit_shrout+"
            "permno_calendar+480000_one_month_adjustment_unavailable_free"
        ),
        "zerotrade6M": (
            "microstructure_source_blocked:daily_crsp_zero_volume_rows+pit_shrout+"
            "permno_calendar+11000_six_month_adjustment_unavailable_free"
        ),
        "zerotrade12M": (
            "microstructure_source_blocked:daily_crsp_zero_volume_rows+pit_shrout+"
            "permno_calendar+11000_twelve_month_adjustment_unavailable_free"
        ),
    }

    assert "hvidkjaer_pin_archive" in inventory.index
    assert bool(
        inventory.loc["hvidkjaer_pin_archive", "aurora_project_use_authorized"]
    ) is False
    assert resolution.loc[list(signals), "remaining_blocker"].to_dict() == (
        expected_blockers
    )

    routes = {
        signal: set(matrix.loc[matrix["signal"].eq(signal), "source_name"])
        for signal in signals
    }
    assert any("Twelve Data" in source for source in routes["BidAskSpread"])
    assert any("CRSP" in source for source in routes["BidAskSpread"])
    assert any("Hvidkjaer" in source for source in routes["ProbInformedTrading"])
    assert any("Duarte" in source for source in routes["ProbInformedTrading"])
    assert any("NYSE TAQ" in source for source in routes["ProbInformedTrading"])
    for signal in {"zerotrade1M", "zerotrade6M", "zerotrade12M"}:
        assert any("Twelve Data" in source for source in routes[signal])
        assert any("SEC EDGAR" in source for source in routes[signal])
        assert any("CRSP" in source for source in routes[signal])

    microstructure = matrix.loc[matrix["signal"].isin(signals)]
    assert microstructure["blocking_reason"].str.startswith(
        "microstructure_source_blocked:"
    ).all()
    assert microstructure["blocking_reason"].nunique() == 5


def test_rio_source_matrix_uses_exact_family_routes_and_blockers():
    from aurora.research.openap_181.rio_batch import RIO_BLOCKERS, RIO_SIGNALS

    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    formulas.loc[formulas["signal"].isin(RIO_SIGNALS), "status"] = "resolved"
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    matrix = build_signal_source_matrix(
        manifest, formulas, resolution.reset_index()
    )

    assert resolution.loc[list(RIO_SIGNALS), "remaining_blocker"].to_dict() == (
        RIO_BLOCKERS
    )
    routes = {
        signal: set(matrix.loc[matrix["signal"].eq(signal), "source_name"])
        for signal in RIO_SIGNALS
    }
    for signal in RIO_SIGNALS:
        assert any("Nagel" in source for source in routes[signal])
        assert any("SEC Form 13F" in source for source in routes[signal])
        assert any("OpenFIGI" in source for source in routes[signal])
        assert any("CRSP" in source for source in routes[signal])
    assert any("Compustat" in source for source in routes["RIO_MB"])
    assert any("I/B/E/S" in source for source in routes["RIO_Disp"])

    rio = matrix.loc[matrix["signal"].isin(RIO_SIGNALS)]
    assert rio["blocking_reason"].str.startswith("rio_source_blocked:").all()
    assert rio["blocking_reason"].nunique() == 4


def test_complex_accounting_source_matrix_uses_exact_routes_and_blockers():
    from aurora.research.openap_181.complex_accounting_batch import (
        COMPLEX_ACCOUNTING_BLOCKERS,
        COMPLEX_ACCOUNTING_SIGNALS,
    )

    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    formulas.loc[
        formulas["signal"].isin(COMPLEX_ACCOUNTING_SIGNALS), "status"
    ] = "resolved"
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    matrix = build_signal_source_matrix(
        manifest, formulas, resolution.reset_index()
    )

    assert resolution.loc[
        list(COMPLEX_ACCOUNTING_SIGNALS), "remaining_blocker"
    ].to_dict() == COMPLEX_ACCOUNTING_BLOCKERS
    routes = {
        signal: set(matrix.loc[matrix["signal"].eq(signal), "source_name"])
        for signal in COMPLEX_ACCOUNTING_SIGNALS
    }
    for signal in COMPLEX_ACCOUNTING_SIGNALS:
        assert any("SEC" in source for source in routes[signal])
        assert any("OpenFIGI" in source for source in routes[signal])
        assert any("Compustat" in source for source in routes[signal])
    assert any("CRSP" in source for source in routes["FR"])
    assert any("CRSP" in source for source in routes["VarCF"])

    attempted = matrix.loc[
        matrix["signal"].isin(COMPLEX_ACCOUNTING_SIGNALS)
    ]
    assert attempted["blocking_reason"].str.startswith(
        "complex_accounting_source_blocked:"
    ).all()
    assert attempted.groupby("signal")["blocking_reason"].nunique().eq(1).all()


def test_accruals_noa_source_matrix_uses_exact_routes_and_blockers():
    from aurora.research.openap_181.accruals_noa_batch import (
        ACCRUALS_NOA_BLOCKERS,
        ACCRUALS_NOA_SIGNALS,
    )

    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    formulas.loc[formulas["signal"].isin(ACCRUALS_NOA_SIGNALS), "status"] = (
        "resolved"
    )
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    matrix = build_signal_source_matrix(
        manifest, formulas, resolution.reset_index()
    )

    assert resolution.loc[
        list(ACCRUALS_NOA_SIGNALS), "remaining_blocker"
    ].to_dict() == ACCRUALS_NOA_BLOCKERS
    routes = {
        signal: set(matrix.loc[matrix["signal"].eq(signal), "source_name"])
        for signal in ACCRUALS_NOA_SIGNALS
    }
    for signal in ACCRUALS_NOA_SIGNALS:
        assert any("SEC" in source for source in routes[signal])
        assert any("OpenFIGI" in source for source in routes[signal])
        assert any("Compustat" in source for source in routes[signal])
        assert any("CRSP" in source for source in routes[signal])

    attempted = matrix.loc[matrix["signal"].isin(ACCRUALS_NOA_SIGNALS)]
    assert attempted["blocking_reason"].str.startswith(
        "accruals_noa_source_blocked:"
    ).all()
    assert attempted.groupby("signal")["blocking_reason"].nunique().eq(1).all()


def test_valuation_accounting_source_matrix_uses_exact_routes_and_blockers():
    from aurora.research.openap_181.valuation_accounting_batch import (
        VALUATION_ACCOUNTING_BLOCKERS,
        VALUATION_ACCOUNTING_SIGNALS,
    )

    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    formulas.loc[
        formulas["signal"].isin(VALUATION_ACCOUNTING_SIGNALS), "status"
    ] = "resolved"
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    matrix = build_signal_source_matrix(
        manifest, formulas, resolution.reset_index()
    )

    assert resolution.loc[
        list(VALUATION_ACCOUNTING_SIGNALS), "remaining_blocker"
    ].to_dict() == VALUATION_ACCOUNTING_BLOCKERS
    routes = {
        signal: set(matrix.loc[matrix["signal"].eq(signal), "source_name"])
        for signal in VALUATION_ACCOUNTING_SIGNALS
    }
    for signal in VALUATION_ACCOUNTING_SIGNALS:
        assert any("SEC" in source for source in routes[signal])
        assert any("OpenFIGI" in source for source in routes[signal])
        assert any("Compustat" in source for source in routes[signal])
        assert any("CRSP" in source for source in routes[signal])

    attempted = matrix.loc[
        matrix["signal"].isin(VALUATION_ACCOUNTING_SIGNALS)
    ]
    assert attempted["blocking_reason"].str.startswith(
        "valuation_accounting_source_blocked:"
    ).all()
    assert attempted.groupby("signal")["blocking_reason"].nunique().eq(1).all()


def test_financing_issuance_source_matrix_uses_exact_routes_and_blockers():
    from aurora.research.openap_181.financing_issuance_batch import (
        FINANCING_ISSUANCE_BLOCKERS,
        FINANCING_ISSUANCE_CRSP_ONLY_SIGNALS,
        FINANCING_ISSUANCE_SIGNALS,
    )

    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    formulas.loc[
        formulas["signal"].isin(FINANCING_ISSUANCE_SIGNALS), "status"
    ] = "resolved"
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    matrix = build_signal_source_matrix(
        manifest, formulas, resolution.reset_index()
    )

    assert resolution.loc[
        list(FINANCING_ISSUANCE_SIGNALS), "remaining_blocker"
    ].to_dict() == FINANCING_ISSUANCE_BLOCKERS
    routes = {
        signal: set(matrix.loc[matrix["signal"].eq(signal), "source_name"])
        for signal in FINANCING_ISSUANCE_SIGNALS
    }
    for signal in FINANCING_ISSUANCE_SIGNALS:
        assert any("OpenFIGI" in source for source in routes[signal])
        assert any("CRSP" in source for source in routes[signal])
        assert not any("Tiingo" in source for source in routes[signal])
        assert not any("Twelve Data" in source for source in routes[signal])
    for signal in FINANCING_ISSUANCE_SIGNALS - FINANCING_ISSUANCE_CRSP_ONLY_SIGNALS:
        assert any("SEC" in source for source in routes[signal])
        assert any("Compustat" in source for source in routes[signal])
    for signal in FINANCING_ISSUANCE_CRSP_ONLY_SIGNALS:
        assert not any("SEC" in source for source in routes[signal])
        assert not any("Compustat" in source for source in routes[signal])

    attempted = matrix.loc[
        matrix["signal"].isin(FINANCING_ISSUANCE_SIGNALS)
    ]
    assert attempted["blocking_reason"].str.startswith(
        "financing_issuance_source_blocked:"
    ).all()
    assert attempted.groupby("signal")["blocking_reason"].nunique().eq(1).all()


def test_operating_accounting_source_matrix_uses_exact_routes_and_blockers():
    from aurora.research.openap_181.operating_accounting_batch import (
        OPERATING_ACCOUNTING_BLOCKERS,
        OPERATING_ACCOUNTING_SIGNALS,
    )

    manifest = build_completion_manifest(_signal_doc())
    formulas = _formula_inventory_for_source_research(manifest)
    formulas.loc[
        formulas["signal"].isin(OPERATING_ACCOUNTING_SIGNALS), "status"
    ] = "resolved"
    resolution = build_signal_resolution(manifest, formulas).set_index("signal")
    matrix = build_signal_source_matrix(
        manifest, formulas, resolution.reset_index()
    )

    assert resolution.loc[
        list(OPERATING_ACCOUNTING_SIGNALS), "remaining_blocker"
    ].to_dict() == OPERATING_ACCOUNTING_BLOCKERS
    routes = {
        signal: set(matrix.loc[matrix["signal"].eq(signal), "source_name"])
        for signal in OPERATING_ACCOUNTING_SIGNALS
    }
    for signal in OPERATING_ACCOUNTING_SIGNALS:
        assert any("OpenFIGI" in source for source in routes[signal])
        assert any("SEC" in source for source in routes[signal])
        assert any("Compustat" in source for source in routes[signal])
        assert any("CRSP" in source for source in routes[signal])
        assert not any("Tiingo" in source for source in routes[signal])
        assert not any("Twelve Data" in source for source in routes[signal])

    attempted = matrix.loc[matrix["signal"].isin(OPERATING_ACCOUNTING_SIGNALS)]
    assert attempted["blocking_reason"].str.startswith(
        "operating_accounting_source_blocked:"
    ).all()
    assert attempted.groupby("signal")["blocking_reason"].nunique().eq(1).all()
