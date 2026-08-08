from __future__ import annotations

import pandas as pd

from aurora.research.openap_181.completion import (
    CURRENT_EXACT_31,
    CURRENT_EXCLUDED_27,
    CURRENT_PROXY_61,
    CompletionError,
    build_completion_manifest,
    build_source_catalog,
    source_can_satisfy,
    write_completion_outputs,
)
from aurora.research.openap_93.registry import REQUIRED_93


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
    assert not source_can_satisfy("SmileSlope", "cboe_public_aggregate")
    assert source_can_satisfy("PatentsRD", "uspto_patentsview_bulk")


def test_source_catalog_documents_rights_and_scope():
    catalog = build_source_catalog().set_index("source_id")
    assert bool(catalog.loc["uspto_patentsview_bulk", "free"])
    assert bool(catalog.loc["uspto_patentsview_bulk", "authorized_automation"])
    assert not bool(catalog.loc["exchange_short_interest", "free"])
    assert "short_interest" in catalog.loc["finra_short_sale_volume", "cannot_satisfy"]


def test_outputs_never_claim_completion_for_unvalidated_baseline(tmp_path):
    summary = write_completion_outputs(build_completion_manifest(_signal_doc()), tmp_path)
    assert summary["unfinished_signals"] == 181
    assert summary["ready_after_audit"] == 0
    assert summary["completion_claimed"] is False
    assert summary["fail_closed"] is True
    assert summary["locked_opened"] is False
    assert (tmp_path / "openap_181_completion_manifest.csv").is_file()
