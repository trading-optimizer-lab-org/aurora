from __future__ import annotations

import importlib

import pandas as pd
import pytest


def _audit_api():
    try:
        return importlib.import_module("aurora.infra.sp500_megarun.feature_audit")
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"feature audit implementation is missing: {exc}")


def _frame(values: list[float], *, start: str = "2010-01-04") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame(
        {
            "date": dates,
            "available_at": dates,
            "value": values,
        }
    )


def test_audit_detects_empty_exact_and_near_duplicate_lanes() -> None:
    api = _audit_api()
    outputs = {
        "F001": _frame([1.0, 2.0, 3.0, 4.0]),
        "F002": _frame([1.0, 2.0, 3.0, 4.0]),
        "F003": _frame([1.0, 2.0, 3.0, 4.001]),
        "F004": pd.DataFrame(columns=["date", "available_at", "value"]),
    }

    report = api.audit_feature_outputs(
        outputs,
        expected_lane_ids=("F001", "F002", "F003", "F004"),
        search_start=pd.Timestamp("2010-01-04"),
        search_end=pd.Timestamp("2010-12-31"),
        near_duplicate_threshold=0.999,
    )

    assert report.ready is False
    assert report.empty_lanes == ("F004",)
    assert ("F001", "F002") in report.exact_duplicate_groups
    assert any(set(pair) == {"F001", "F003"} for pair in report.near_duplicate_pairs)


def test_audit_rejects_a_feature_that_uses_data_after_its_decision() -> None:
    api = _audit_api()
    frame = _frame([1.0, 2.0])
    frame.loc[0, "available_at"] = pd.Timestamp("2010-01-07")

    with pytest.raises(api.FeatureAuditError, match="FEATURE_LOOKAHEAD:F001"):
        api.audit_feature_outputs(
            {"F001": frame},
            expected_lane_ids=("F001",),
            search_start=pd.Timestamp("2010-01-04"),
            search_end=pd.Timestamp("2010-12-31"),
        )


def test_audit_rejects_validation_or_locked_rows() -> None:
    api = _audit_api()
    frame = _frame([1.0], start="2011-01-03")

    with pytest.raises(api.FeatureAuditError, match="NON_TRAIN_FEATURE_ROW:F001"):
        api.audit_feature_outputs(
            {"F001": frame},
            expected_lane_ids=("F001",),
            search_start=pd.Timestamp("1998-01-01"),
            search_end=pd.Timestamp("2010-12-31"),
        )
