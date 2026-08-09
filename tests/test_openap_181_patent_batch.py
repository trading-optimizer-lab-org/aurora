from __future__ import annotations

import pandas as pd
import pytest

from aurora.research.openap_181.patent_batch import (
    KPSS_ARCHIVES,
    KPSS_COMMIT,
    KPSS_REPOSITORY,
    build_patent_batch_evidence,
    parse_lfs_pointer,
    summarize_kpss_patent_chunks,
)


def test_kpss_source_is_pinned_to_a_complete_integrity_contract():
    assert KPSS_REPOSITORY == (
        "KPSS2017/Technological-Innovation-Resource-Allocation-and-Growth-"
        "Extended-Data"
    )
    assert KPSS_COMMIT == "2ee29097f7ca05fc0e56905e82474ad426c387b9"
    assert KPSS_ARCHIVES == {
        "KPSS_2024.zip": {
            "sha256": "60215d8db687b0c40060de1649cf0f14364cbac2cbdd16b5cb3dee2dcdb85f27",
            "size": 57199194,
        },
        "Match_patent_permco_permno_2024.zip": {
            "sha256": "4686ee4383bfc8bf43b7721766f28e04e331ea02bbffe4dd1358d5c02b5e675a",
            "size": 16776297,
        },
        "Match_patent_cpc_2024.zip": {
            "sha256": "a43de8ee5d43b3c0840f11540d0468febccad0d378dc372b4aee803aefce4257",
            "size": 74407853,
        },
    }


def test_lfs_pointer_parser_fails_closed():
    pointer = "\n".join(
        (
            "version https://git-lfs.github.com/spec/v1",
            "oid sha256:" + "a" * 64,
            "size 123",
        )
    )
    assert parse_lfs_pointer(pointer) == {"sha256": "a" * 64, "size": 123}
    with pytest.raises(ValueError, match="Git LFS pointer"):
        parse_lfs_pointer("not a pointer")


def test_patent_panel_summary_measures_the_source_without_claiming_signal_coverage():
    chunks = [
        pd.DataFrame(
            {
                "patent_num": [1, 2],
                "permno": [10001, 10002],
                "issue_date": ["01/03/1976", "06/02/1977"],
                "filing_date": ["01/03/1974", "06/02/1975"],
                "xi_nominal": [1.0, 2.0],
                "xi_real": [0.5, 1.0],
                "cites": [3, 4],
            }
        ),
        pd.DataFrame(
            {
                "patent_num": [3],
                "permno": [pd.NA],
                "issue_date": ["07/04/1978"],
                "filing_date": [pd.NA],
                "xi_nominal": [3.0],
                "xi_real": [1.5],
                "cites": [pd.NA],
            }
        ),
    ]
    summary = summarize_kpss_patent_chunks(chunks)
    assert summary["rows"] == 3
    assert summary["unique_patents"] == 3
    assert summary["unique_permnos"] == 2
    assert summary["missing_permno"] == 1
    assert summary["missing_filing_date"] == 1
    assert summary["missing_cites"] == 1
    assert summary["first_issue_date"] == "1976-01-03"
    assert summary["last_issue_date"] == "1978-07-04"
    assert summary["signal_coverage_measured"] is False


def test_patent_evidence_is_partial_and_fail_closed_for_both_signals():
    probe = {
        "source_commit": KPSS_COMMIT,
        "archives_verified": True,
        "schema_verified": True,
        "readme_use_with_citation": True,
        "formal_license_detected": False,
        "raw_redistribution_authorized": False,
    }
    evidence = build_patent_batch_evidence(
        probe,
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-patent-source-probe-results",
        implementation_commit="1" * 40,
    ).set_index("signal")

    assert set(evidence.index) == {"CitationsRD", "PatentsRD"}
    assert evidence["formula_implemented"].all()
    assert not evidence["data_pipeline_implemented"].any()
    assert not evidence["point_in_time_verified"].any()
    assert not evidence["identity_verified"].any()
    assert not evidence["coverage_measured"].any()
    assert not evidence["fidelity_measured"].any()
    assert evidence["strict_gate_result"].eq("blocked").all()
    assert evidence["coverage_result"].eq("not_measured").all()
    assert evidence["fidelity_result"].eq("not_measured").all()
    assert "five_year_subcategory_scaled_ncitscale" in evidence.loc[
        "CitationsRD", "blocking_reason"
    ]
    assert "exact_xrd" in evidence.loc["PatentsRD", "blocking_reason"]


def test_patent_evidence_rejects_unverified_or_mismatched_probe():
    base = {
        "source_commit": KPSS_COMMIT,
        "archives_verified": True,
        "schema_verified": True,
        "readme_use_with_citation": True,
        "formal_license_detected": False,
        "raw_redistribution_authorized": False,
    }
    for field in ("archives_verified", "schema_verified", "readme_use_with_citation"):
        probe = dict(base)
        probe[field] = False
        with pytest.raises(ValueError, match="patent probe"):
            build_patent_batch_evidence(
                probe,
                evidence_run_url="https://github.com/example/aurora/actions/runs/123",
                evidence_artifact="artifact",
                implementation_commit="1" * 40,
            )
    probe = dict(base, source_commit="0" * 40)
    with pytest.raises(ValueError, match="patent probe"):
        build_patent_batch_evidence(
            probe,
            evidence_run_url="https://github.com/example/aurora/actions/runs/123",
            evidence_artifact="artifact",
            implementation_commit="1" * 40,
        )
