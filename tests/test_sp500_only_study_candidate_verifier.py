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
