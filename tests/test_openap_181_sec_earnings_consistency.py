from __future__ import annotations

from pathlib import Path
from statistics import mean

import pandas as pd
import pytest

from aurora.research.openap_181.sec_earnings_consistency import (
    EARNINGS_CONSISTENCY_FORMULA_SHA256,
    calculate_sec_earnings_consistency_current,
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


def _eps_values() -> list[float]:
    return [1.0, 1.35, 1.6, 2.05, 2.4, 3.0, 3.45]


def _facts() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, value in enumerate(_eps_values()):
        year = 2019 + index
        filed_at = pd.Timestamp(year + 1, 2, 20, tz="UTC")
        rows.append(
            {
                "cik": 1,
                "taxonomy": "us-gaap",
                "tag": "EarningsPerShareBasic",
                "unit": "USD/shares",
                "value": value,
                "period_start": f"{year}-01-01",
                "period_end": f"{year}-12-31",
                "fy": year,
                "fp": "FY",
                "form": "10-K",
                "filed": filed_at.date().isoformat(),
                "accession_number": f"0000000001-{(year + 1) % 100:02d}-000001",
                "available_at": filed_at.isoformat(),
            }
        )
    return pd.DataFrame(rows)


def _expected(values: list[float]) -> float:
    growth = []
    newest_first = list(reversed(values))
    for index in range(min(5, len(newest_first) - 2)):
        current = newest_first[index]
        lag12 = newest_first[index + 1]
        lag24 = newest_first[index + 2]
        growth.append(
            (current - lag12) / (0.5 * (abs(lag12) + abs(lag24)))
        )
    return mean(growth)


def test_sec_earnings_consistency_replicates_official_annual_formula() -> None:
    result = calculate_sec_earnings_consistency_current(
        _facts(),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert result["value"] == pytest.approx(_expected(_eps_values()))
    assert result["current_usable"]
    assert result["fidelity_class"] == "reconstructed"
    assert result["observation_count"] == 7
    assert result["period_end"] == "2025-12-31"
    assert result["formula_sha256"] == EARNINGS_CONSISTENCY_FORMULA_SHA256


def test_sec_earnings_consistency_applies_official_six_month_lag() -> None:
    result = calculate_sec_earnings_consistency_current(
        _facts(),
        _status(),
        formation_at="2026-05-31T23:59:59Z",
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert result["value"] == pytest.approx(_expected(_eps_values()[:-1]))
    assert result["current_usable"]
    assert result["period_end"] == "2024-12-31"


def test_sec_earnings_consistency_applies_official_exception_filter() -> None:
    facts = _facts()
    facts.loc[facts["period_end"].eq("2025-12-31"), "value"] = 25.0

    result = calculate_sec_earnings_consistency_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]
    assert result["reason_if_missing"] == "official_exception_filter"


def test_sec_earnings_consistency_ignores_quarterly_eps_contexts() -> None:
    facts = _facts()
    quarter = facts.iloc[-1].copy()
    quarter["value"] = 999.0
    quarter["period_start"] = "2026-01-01"
    quarter["period_end"] = "2026-03-31"
    quarter["fp"] = "Q1"
    quarter["form"] = "10-Q"
    quarter["filed"] = "2026-05-01"
    quarter["available_at"] = "2026-05-01T12:00:00Z"

    result = calculate_sec_earnings_consistency_current(
        pd.concat([facts, pd.DataFrame([quarter])], ignore_index=True),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert result["value"] == pytest.approx(_expected(_eps_values()))


def test_sec_earnings_consistency_is_connected_to_guarded_sec_batch() -> None:
    source_runner = (
        ROOT / "scripts" / "run_openap_yfinance_sec_current.py"
    ).read_text(encoding="utf-8")
    calculation_runner = (
        ROOT / "scripts" / "run_openap_149_sec_companyfacts.py"
    ).read_text(encoding="utf-8")

    assert "EARNINGS_CONSISTENCY_COMPANYFACT_TAGS" in source_runner
    assert "calculate_sec_earnings_consistency_current" in calculation_runner
    assert "companyfacts_retention_contract" in source_runner
    assert "companyfacts_retention_contract" in calculation_runner
    assert "require_github_actions_or_explicit_local_permission" in (
        calculation_runner
    )
