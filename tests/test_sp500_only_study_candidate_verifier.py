from __future__ import annotations

from scripts.verify_sp500_only_study_candidates import _verify


def test_verify_confirms_metadata_candidate() -> None:
    row = {
        "study_id": "manual_test",
        "title": "S&P 500 market timing rule",
        "rule_or_abstract": "A trading rule holds SPY when above a moving average and outperforms buy-and-hold S&P 500.",
        "tradable_assets": "SPY",
        "benchmark": "S&P 500 buy-and-hold",
    }

    out = _verify(row, max_pdf_bytes=1)

    assert out["verification_status"] == "confirmed_from_metadata"
    assert out["locked_opened"] == "false"
    assert out["backtest_enabled"] == "false"


def test_verify_rejects_negative_outperform_result() -> None:
    row = {
        "study_id": "manual_bad",
        "title": "S&P 500 market timing rule",
        "rule_or_abstract": "A trading rule for SPY does not outperform buy-and-hold S&P 500.",
        "tradable_assets": "SPY",
        "benchmark": "S&P 500 buy-and-hold",
    }

    out = _verify(row, max_pdf_bytes=1)

    assert out["verification_status"] == "rejected"
    assert "negative_or_non_outperform_result" in out["verification_reasons"]


def test_verify_marks_pdf_positive_and_negative_as_needs_review(monkeypatch) -> None:
    row = {
        "study_id": "manual_pdf",
        "title": "Trend following rules for the S&P 500",
        "rule_or_abstract": "Tests moving average trading rules on SPY.",
        "tradable_assets": "SPY",
        "benchmark": "S&P 500 buy-and-hold",
    }

    import scripts.verify_sp500_only_study_candidates as verifier

    monkeypatch.setitem(verifier.MANUAL_PDF_URLS, "manual_pdf", "https://example.test/paper.pdf")
    monkeypatch.setattr(
        verifier,
        "_download_pdf_text",
        lambda url, max_bytes: (
            (
                "The S&P 500 trend following trading rule outperforms buy-and-hold by a considerable margin. "
                "However, once costs are included profits disappear for the shortest technical rule variant."
            ),
            "text_extracted",
        ),
    )

    out = _verify(row, max_pdf_bytes=1024)

    assert out["verification_status"] == "needs_review_conflicting_evidence"
    assert "negative_or_non_outperform_result" in out["verification_reasons"]
