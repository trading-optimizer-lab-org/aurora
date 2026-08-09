from __future__ import annotations

import gzip

import pandas as pd
import pytest

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
    assert source_can_satisfy("PatentsRD", "uspto_patentsview_bulk")


def test_manifest_uses_concrete_family_blockers():
    manifest = build_completion_manifest(_signal_doc()).set_index("signal")
    assert (
        manifest.loc["SmileSlope", "blocker_code"]
        == "authorized_current_option_surface_missing"
    )
    assert (
        manifest.loc["ShortInterest", "blocker_code"]
        == "listed_short_interest_history_and_stock_validation_required"
    )
    assert (
        manifest.loc["PatentsRD", "blocker_code"]
        == "patent_assignee_to_public_issuer_crosswalk_missing"
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
    assert not bool(catalog.loc["cboe_delayed_options", "authorized_automation"])
    assert not bool(catalog.loc["marketdata_options_free", "authorized_automation"])
    assert not bool(catalog.loc["exchange_short_interest", "free"])
    assert bool(catalog.loc["finra_equity_short_interest", "free"])
    assert bool(catalog.loc["finra_equity_short_interest", "authorized_automation"])
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
        "PatentsRD", "final_research_classification"
    ] == "identifier_bridge_missing"
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
    assert matrix["coverage_verified"].eq(False).all()


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
