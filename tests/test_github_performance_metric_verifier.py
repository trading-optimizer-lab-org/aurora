from __future__ import annotations

import math

import numpy as np
import pytest

from aurora.infra.github_performance.metric_verifier import (
    MetricInputRecord,
    read_metric_inputs,
    recompute_metrics,
    verify_metric_inputs,
    verify_metric_table,
    write_metric_inputs,
)


def test_independent_metrics_recompute_known_return_series() -> None:
    returns = np.array([0.10, -0.05, 0.02, -0.01], dtype=float)

    metrics = recompute_metrics(
        returns,
        periods_per_year=4,
        undefined_policy="null",
    )

    nav = np.cumprod(1.0 + returns)
    expected_total = (nav[-1] - 1.0) * 100.0
    expected_cagr = (nav[-1] - 1.0) * 100.0
    expected_std = returns.std(ddof=0)
    expected_sharpe = returns.mean() / expected_std * math.sqrt(4)
    downside_std = returns[returns < 0].std(ddof=0)
    expected_sortino = returns.mean() / downside_std * math.sqrt(4)
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    expected_mdd = drawdown.min() * 100.0

    assert metrics["total_return_pct"] == pytest.approx(expected_total)
    assert metrics["cagr_pct"] == pytest.approx(expected_cagr)
    assert metrics["annualized_return_pct"] == pytest.approx(expected_cagr)
    assert metrics["annualized_volatility_pct"] == pytest.approx(
        expected_std * math.sqrt(4) * 100.0
    )
    assert metrics["sharpe"] == pytest.approx(expected_sharpe)
    assert metrics["sortino"] == pytest.approx(expected_sortino)
    assert metrics["max_drawdown_pct"] == pytest.approx(expected_mdd)
    assert metrics["calmar"] == pytest.approx(
        expected_cagr / abs(expected_mdd)
    )
    assert metrics["profit_factor"] == pytest.approx(0.12 / 0.06)
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["period_count"] == 4
    assert metrics["average_return_pct"] == pytest.approx(1.5)


def test_independent_metrics_keep_raw_length_for_cagr() -> None:
    returns = np.array([np.nan, 0.10, -0.05, 0.02], dtype=float)

    metrics = recompute_metrics(
        returns,
        periods_per_year=4,
        undefined_policy="null",
    )

    final_nav = (1.10 * 0.95 * 1.02)
    assert metrics["cagr_pct"] == pytest.approx(
        (final_nav - 1.0) * 100.0
    )
    assert metrics["period_count_raw"] == 4
    assert metrics["period_count"] == 3


@pytest.mark.parametrize("returns", [[], [0.01]])
def test_independent_metrics_apply_null_policy_to_short_series(
    returns: list[float],
) -> None:
    metrics = recompute_metrics(
        returns,
        periods_per_year=252,
        undefined_policy="null",
    )
    assert metrics["cagr_pct"] is None
    assert metrics["sharpe"] is None
    assert metrics["max_drawdown_pct"] is None


def test_independent_metric_comparison_accepts_explicit_tolerance() -> None:
    recomputed = {
        "cagr_pct": 12.345678,
        "sharpe": 1.234567,
        "period_count": 252,
    }
    reported = {
        "cagr_pct": 12.3457,
        "sharpe": 1.2346,
        "period_count": 252,
    }

    report = verify_metric_table(
        reported,
        recomputed,
        tolerances={
            "cagr_pct": {"absolute": 0.0001, "relative": 0.0},
            "sharpe": {"absolute": 0.0001, "relative": 0.0},
            "period_count": {"absolute": 0.0, "relative": 0.0},
        },
    )

    assert report.passed is True
    assert report.mismatched_fields == ()


def test_independent_metric_comparison_reports_real_mismatch() -> None:
    report = verify_metric_table(
        {"sharpe": 1.4},
        {"sharpe": 1.1},
        tolerances={
            "sharpe": {"absolute": 0.0001, "relative": 0.0001},
        },
    )

    assert report.passed is False
    assert report.mismatched_fields == ("sharpe",)
    field = report.fields[0]
    assert field.field == "sharpe"
    assert field.reported == 1.4
    assert field.recomputed == 1.1
    assert field.absolute_error == pytest.approx(0.3)


def test_nan_infinity_and_signed_zero_are_not_silently_equivalent() -> None:
    nan_report = verify_metric_table(
        {"sharpe": None},
        {"sharpe": float("nan")},
        tolerances={
            "sharpe": {"absolute": 0.0, "relative": 0.0},
        },
    )
    infinity_report = verify_metric_table(
        {"calmar": None},
        {"calmar": float("inf")},
        tolerances={
            "calmar": {"absolute": 0.0, "relative": 0.0},
        },
    )
    signed_zero_report = verify_metric_table(
        {"max_drawdown_pct": -0.0},
        {"max_drawdown_pct": 0.0},
        tolerances={
            "max_drawdown_pct": {"absolute": 0.0, "relative": 0.0},
        },
    )

    assert nan_report.passed is False
    assert infinity_report.passed is False
    assert signed_zero_report.passed is False


def test_metric_input_file_recomputes_every_reported_field(
    tmp_path,
) -> None:
    returns = (0.02, -0.01, 0.03, -0.02)
    reported = recompute_metrics(
        returns,
        periods_per_year=4,
        undefined_policy="null",
    )
    path = write_metric_inputs(
        tmp_path / "metric_verification_inputs.parquet",
        (
            MetricInputRecord(
                unit_key="u001",
                split="validation",
                returns=returns,
                periods_per_year=4,
                undefined_policy="null",
                reported=reported,
            ),
        ),
    )

    records = read_metric_inputs(path)
    report = verify_metric_inputs(records)

    assert len(records) == 1
    assert report.passed is True
    assert report.records_verified == 1
    assert report.fields_compared == len(reported)
    assert report.mismatches == ()


def test_metric_input_file_detects_tampered_reported_metric(
    tmp_path,
) -> None:
    returns = (0.02, -0.01, 0.03, -0.02)
    reported = dict(
        recompute_metrics(
            returns,
            periods_per_year=4,
            undefined_policy="null",
        )
    )
    reported["sharpe"] = float(reported["sharpe"]) + 0.5
    path = write_metric_inputs(
        tmp_path / "metric_verification_inputs.parquet",
        (
            MetricInputRecord(
                unit_key="u001",
                split="validation",
                returns=returns,
                periods_per_year=4,
                undefined_policy="null",
                reported=reported,
            ),
        ),
    )

    report = verify_metric_inputs(read_metric_inputs(path))

    assert report.passed is False
    assert report.records_verified == 1
    assert len(report.mismatches) == 1
    assert report.mismatches[0].unit_key == "u001"
    assert report.mismatches[0].split == "validation"
    assert report.mismatches[0].field == "sharpe"
