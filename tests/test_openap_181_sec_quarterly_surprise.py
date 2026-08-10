from __future__ import annotations

from pathlib import Path
from statistics import mean, stdev

import pandas as pd
import pytest

from aurora.research.openap_181.sec_quarterly_surprise import (
    EARNINGS_SURPRISE_FORMULA_SHA256,
    REVENUE_SURPRISE_FORMULA_SHA256,
    calculate_sec_quarterly_surprises_current,
)


FORMATION_AT = "2026-08-09T23:59:59Z"
RETRIEVED_AT = "2026-08-10T10:00:00Z"
ROOT = Path(__file__).resolve().parents[1]


def _status() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik": 1,
                "symbol": "AAA",
                "surface": "companyfacts",
                "status": "ok",
            },
            {
                "cik": 1,
                "symbol": "AAA",
                "surface": "submissions",
                "status": "ok",
            },
        ]
    )


def _quarter_values() -> tuple[list[float], list[float]]:
    income = [
        8.0 + 0.7 * index + (index % 5) * 1.3 + (index % 3) ** 2
        for index in range(24)
    ]
    revenue = [
        80.0 + 2.1 * index + (index % 4) * 3.7 + (index % 7) ** 2
        for index in range(24)
    ]
    return income, revenue


def _facts() -> pd.DataFrame:
    income, revenue = _quarter_values()
    rows: list[dict[str, object]] = []
    quarter_ends = ((3, 31), (6, 30), (9, 30), (12, 31))
    for index in range(24):
        year = 2020 + index // 4
        quarter = index % 4 + 1
        month, day = quarter_ends[quarter - 1]
        period_end = pd.Timestamp(year, month, day)
        filed_at = period_end + pd.Timedelta(days=60 if quarter == 4 else 42)
        fp = "FY" if quarter == 4 else f"Q{quarter}"
        form = "10-K" if quarter == 4 else "10-Q"
        start_index = index - (quarter - 1)
        cumulative_income = sum(income[start_index : index + 1])
        cumulative_revenue = sum(revenue[start_index : index + 1])
        for tag, unit, value in (
            ("IncomeLossFromContinuingOperations", "USD", cumulative_income),
            (
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "USD",
                cumulative_revenue,
            ),
            ("WeightedAverageNumberOfSharesOutstandingBasic", "shares", 10.0),
        ):
            rows.append(
                {
                    "cik": 1,
                    "taxonomy": "us-gaap",
                    "tag": tag,
                    "unit": unit,
                    "value": value,
                    "period_start": f"{year}-01-01",
                    "period_end": period_end.date().isoformat(),
                    "fy": year,
                    "fp": fp,
                    "form": form,
                    "filed": filed_at.date().isoformat(),
                    "accession_number": f"0000000001-{year % 100:02d}-{quarter:06d}",
                    "available_at": filed_at.tz_localize("UTC").isoformat(),
                }
            )
    return pd.DataFrame(rows)


def _expected_standardized(values: list[float]) -> float:
    values = values[-21:]
    yoy: list[float | None] = [None] * 4
    yoy.extend(values[index] - values[index - 4] for index in range(4, 21))

    surprises: list[float | None] = [None] * 21
    for index in range(12, 21):
        history = [float(yoy[position]) for position in range(index - 8, index)]
        surprises[index] = float(yoy[index]) - mean(history)

    scale_history = [float(value) for value in surprises[12:20]]
    return float(surprises[20]) / stdev(scale_history)


def test_sec_quarterly_surprises_reconstruct_full_discrete_quarters() -> None:
    result = calculate_sec_quarterly_surprises_current(
        _facts(),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).set_index("signal")
    income, revenue = _quarter_values()

    assert result.loc["EarningsSurprise", "value"] == pytest.approx(
        _expected_standardized([value / 10.0 for value in income])
    )
    assert result.loc["RevenueSurprise", "value"] == pytest.approx(
        _expected_standardized([value / 10.0 for value in revenue])
    )
    assert result["current_usable"].all()
    assert result["fidelity_class"].eq("reconstructed").all()
    assert result["observation_count"].eq(21).all()
    assert result.loc["EarningsSurprise", "formula_sha256"] == (
        EARNINGS_SURPRISE_FORMULA_SHA256
    )
    assert result.loc["RevenueSurprise", "formula_sha256"] == (
        REVENUE_SURPRISE_FORMULA_SHA256
    )


def test_sec_quarterly_surprises_fail_closed_for_a_recent_quarter_gap() -> None:
    facts = _facts()
    facts = facts.loc[facts["period_end"].ne("2024-09-30")].copy()

    result = calculate_sec_quarterly_surprises_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    )

    assert result["value"].isna().all()
    assert result["current_usable"].eq(False).all()
    assert result["reason_if_missing"].eq(
        "insufficient_21_contiguous_quarters"
    ).all()


def test_sec_quarterly_surprises_do_not_treat_sec_fy_as_period_identity() -> None:
    facts = _facts()
    quarter_number = pd.to_datetime(facts["period_end"]).dt.quarter
    facts["fy"] = pd.to_numeric(facts["fy"]) + quarter_number - 1

    result = calculate_sec_quarterly_surprises_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    )

    assert result["current_usable"].all()
    assert result["observation_count"].eq(21).all()


def test_sec_quarterly_surprises_accept_valid_contexts_without_sec_fy() -> None:
    facts = _facts()
    facts["fy"] = pd.NA

    result = calculate_sec_quarterly_surprises_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    )

    assert result["current_usable"].all()
    assert result["observation_count"].eq(21).all()


def test_sec_quarterly_surprises_ignore_facts_available_after_formation() -> None:
    facts = _facts()
    facts.loc[facts["period_end"].eq("2025-12-31"), "available_at"] = (
        "2026-09-01T12:00:00Z"
    )

    result = calculate_sec_quarterly_surprises_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    )

    assert result["current_usable"].all()
    assert result["period_end"].eq("2025-09-30").all()
    assert pd.to_datetime(result["available_at"], utc=True).le(
        pd.Timestamp(FORMATION_AT)
    ).all()


def test_sec_quarterly_surprises_are_connected_to_the_guarded_sec_batch() -> None:
    source_runner = (
        ROOT / "scripts" / "run_openap_yfinance_sec_current.py"
    ).read_text(encoding="utf-8")
    calculation_runner = (
        ROOT / "scripts" / "run_openap_149_sec_companyfacts.py"
    ).read_text(encoding="utf-8")

    assert "QUARTERLY_SURPRISE_COMPANYFACT_TAGS" in source_runner
    assert "calculate_sec_quarterly_surprises_current" in calculation_runner
    assert "require_github_actions_or_explicit_local_permission" in (
        calculation_runner
    )
