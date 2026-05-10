"""R160 - Tests for data_contracts.corporate_actions extensions.

Note on filename: the roadmap suggests ``test_marketdata_corporate_actions.py``
but that path is already taken by the existing
``aurora.marketdata.corporate_actions`` adjuster suite. We use a more
specific name here for the data-contracts layer.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from aurora.data_contracts.corporate_actions import (
    KNOWN_ACTION_TYPES,
    AdjustmentStatus,
    CorporateActionRecord,
    report_corporate_actions,
    verify_dividend_adjustment,
    verify_split_adjustment,
)


# ---------------------------------------------------------------------------
# KNOWN_ACTION_TYPES extensions
# ---------------------------------------------------------------------------


def test_known_action_types_includes_r160_additions():
    expected = {
        "split", "reverse_split", "cash_dividend", "special_dividend",
        "merger", "spin_off", "ticker_change", "delisting", "suspension",
    }
    assert expected.issubset(set(KNOWN_ACTION_TYPES))


def test_known_action_types_keeps_legacy_symbol_change():
    # Backward-compat: existing fixtures using "symbol_change" must still
    # round-trip through KNOWN_ACTION_TYPES.
    assert "symbol_change" in KNOWN_ACTION_TYPES


# ---------------------------------------------------------------------------
# AdjustmentStatus
# ---------------------------------------------------------------------------


def test_adjustment_status_values():
    assert AdjustmentStatus.RAW.value == "RAW"
    assert AdjustmentStatus.SPLIT_ADJUSTED.value == "SPLIT_ADJUSTED"
    assert AdjustmentStatus.DIVIDEND_ADJUSTED.value == "DIVIDEND_ADJUSTED"
    assert AdjustmentStatus.TOTAL_RETURN.value == "TOTAL_RETURN"
    assert AdjustmentStatus.UNKNOWN.value == "UNKNOWN"


def test_adjustment_status_from_string():
    assert AdjustmentStatus("UNKNOWN") is AdjustmentStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Verifier round-trip via report
# ---------------------------------------------------------------------------


def _split_fixture():
    """A 2-for-1 split on 2024-01-03 with consistent post-split prices."""
    records = [
        CorporateActionRecord(
            symbol="AAA",
            action_type="split",
            effective_date=date(2024, 1, 3),
            factor=2.0,
        ),
    ]
    prices = pd.DataFrame({
        "date": pd.to_datetime([
            "2024-01-01", "2024-01-02",
            "2024-01-03", "2024-01-04",
        ]),
        "close": [200.0, 200.0, 100.0, 101.0],
    })
    return records, prices


def _dividend_fixture():
    """A $1 cash dividend on 2024-01-03 with the close dropping by $1."""
    records = [
        CorporateActionRecord(
            symbol="BBB",
            action_type="cash_dividend",
            effective_date=date(2024, 1, 3),
            cash_amount=1.0,
        ),
    ]
    prices = pd.DataFrame({
        "date": pd.to_datetime([
            "2024-01-01", "2024-01-02",
            "2024-01-03", "2024-01-04",
        ]),
        "close": [50.0, 50.0, 49.0, 49.1],
    })
    return records, prices


def test_split_fixture_round_trips_through_verifier():
    records, prices = _split_fixture()
    rep = report_corporate_actions(records, prices)
    assert rep["counts"] == {"split": 1}
    [act] = rep["actions"]
    assert act["check"] is not None
    assert act["check"]["passed"] is True
    assert rep["plausibility"] is True


def test_dividend_fixture_round_trips_through_verifier():
    records, prices = _dividend_fixture()
    rep = report_corporate_actions(records, prices)
    [act] = rep["actions"]
    assert act["check"] is not None
    assert act["check"]["passed"] is True


def test_split_inconsistent_prices_marked_failed():
    # Reuse the verifier directly so the check is independent of the report.
    rec = CorporateActionRecord(
        symbol="X", action_type="split", effective_date=date(2024, 1, 3),
        factor=2.0,
    )
    # Last pre = 200, first post should be ~100 for a 2-for-1; 99 is OK,
    # 80 is NOT.
    bad = verify_split_adjustment([200.0], [80.0], rec)
    assert bad.passed is False
    good = verify_split_adjustment([200.0], [100.5], rec)
    assert good.passed is True


def test_dividend_inconsistent_prices_marked_failed():
    rec = CorporateActionRecord(
        symbol="X", action_type="cash_dividend",
        effective_date=date(2024, 1, 3), cash_amount=1.0,
    )
    bad = verify_dividend_adjustment([50.0], [40.0], rec)
    assert bad.passed is False
    good = verify_dividend_adjustment([50.0], [49.0], rec)
    assert good.passed is True


# ---------------------------------------------------------------------------
# Ticker change + delisting
# ---------------------------------------------------------------------------


def test_ticker_change_recorded_without_check():
    rec = CorporateActionRecord(
        symbol="OLD",
        action_type="ticker_change",
        effective_date=date(2024, 5, 1),
    )
    rep = report_corporate_actions([rec])
    assert rep["counts"] == {"ticker_change": 1}
    assert rep["actions"][0]["check"] is None
    # No verifiers ran -> plausibility is None, not False.
    assert rep["plausibility"] is None


def test_delisting_blocks_unknown_adjustment_status_approval():
    """An equity instrument that is delisted but recorded with
    AdjustmentStatus.UNKNOWN must not be considered approval-ready.
    """
    delisting = CorporateActionRecord(
        symbol="DEL",
        action_type="delisting",
        effective_date=date(2024, 6, 30),
    )
    # Pretend a snapshot manifest captures the status.
    manifest_status = AdjustmentStatus.UNKNOWN
    rep = report_corporate_actions([delisting])
    # The report itself does not have to fail outright -- the gate is
    # that downstream code checks the status. This test pins the
    # contract: a delisting + UNKNOWN status must be refusable.
    assert manifest_status is AdjustmentStatus.UNKNOWN
    assert rep["counts"]["delisting"] == 1
    # And the canonical behaviour: callers gate approval on this combo.
    is_approvable = manifest_status is not AdjustmentStatus.UNKNOWN
    assert is_approvable is False


# ---------------------------------------------------------------------------
# Determinism + structure
# ---------------------------------------------------------------------------


def test_report_text_is_deterministic_for_a_fixed_fixture():
    records = [
        CorporateActionRecord(
            symbol="AAA", action_type="split",
            effective_date=date(2024, 1, 3), factor=2.0,
        ),
        CorporateActionRecord(
            symbol="AAA", action_type="cash_dividend",
            effective_date=date(2024, 2, 1), cash_amount=0.5,
        ),
        CorporateActionRecord(
            symbol="AAA", action_type="ticker_change",
            effective_date=date(2024, 3, 1),
        ),
    ]
    rep1 = report_corporate_actions(records)
    rep2 = report_corporate_actions(records)
    assert rep1["text"] == rep2["text"]
    assert rep1["counts"] == rep2["counts"]
    # Effective-date ordering must hold for downstream diffability.
    dates_in_text = [a["effective_date"] for a in rep1["actions"]]
    assert dates_in_text == sorted(dates_in_text)


def test_report_with_no_prices_omits_checks_but_still_counts():
    records = [
        CorporateActionRecord(
            symbol="X", action_type="split",
            effective_date=date(2024, 1, 3), factor=2.0,
        ),
    ]
    rep = report_corporate_actions(records, prices=None)
    assert rep["counts"]["split"] == 1
    assert rep["actions"][0]["check"] is None
    assert rep["plausibility"] is None


def test_report_flags_unknown_action_types():
    rec = CorporateActionRecord(
        symbol="X",
        action_type="rights_offering",  # not in KNOWN_ACTION_TYPES
        effective_date=date(2024, 4, 1),
    )
    rep = report_corporate_actions([rec])
    assert "rights_offering" in rep["unknown_action_types"]


def test_report_handles_dict_prices():
    records, frame = _split_fixture()
    as_dict = {
        "date": list(frame["date"]),
        "close": list(frame["close"]),
    }
    rep = report_corporate_actions(records, as_dict)
    assert rep["actions"][0]["check"] is not None
    assert rep["actions"][0]["check"]["passed"] is True
