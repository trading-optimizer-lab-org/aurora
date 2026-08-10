from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.research.openap_181.sec_delnetfin import (
    DELNETFIN_FORMULA_SHA256,
    calculate_sec_delnetfin_current,
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
            {"cik": 1, "symbol": "AAA", "surface": "submissions", "status": "ok"},
        ]
    )


def _facts(*, include_preferred: bool = True) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = {
        2024: {
            "Assets": 100.0,
            "ShortTermInvestments": 12.0,
            "LongTermInvestments": 9.0,
            "LongTermDebtNoncurrent": 25.0,
            "LongTermDebtCurrent": 4.0,
            "PreferredStockValue": 2.0,
        },
        2025: {
            "Assets": 120.0,
            "ShortTermInvestments": 17.0,
            "LongTermInvestments": 11.0,
            "LongTermDebtNoncurrent": 28.0,
            "LongTermDebtCurrent": 3.0,
            "PreferredStockValue": 1.0,
        },
    }
    for year, concepts in values.items():
        filed_at = pd.Timestamp(year + 1, 2, 20, tz="UTC")
        for tag, value in concepts.items():
            if tag == "PreferredStockValue" and not include_preferred:
                continue
            rows.append(
                {
                    "cik": 1,
                    "taxonomy": "us-gaap",
                    "tag": tag,
                    "unit": "USD",
                    "value": value,
                    "period_start": "",
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


def _expected(*, preferred: bool) -> float:
    current_preferred = 1.0 if preferred else 0.0
    lag_preferred = 2.0 if preferred else 0.0
    current = (17.0 + 11.0) - (28.0 + 3.0 + current_preferred)
    lagged = (12.0 + 9.0) - (25.0 + 4.0 + lag_preferred)
    return (current - lagged) / (0.5 * (120.0 + 100.0))


@pytest.mark.parametrize("include_preferred", [True, False])
def test_sec_delnetfin_replicates_formula_and_missing_preferred_zero(
    include_preferred: bool,
) -> None:
    result = calculate_sec_delnetfin_current(
        _facts(include_preferred=include_preferred),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert result["value"] == pytest.approx(
        _expected(preferred=include_preferred)
    )
    assert result["current_usable"]
    assert result["fidelity_class"] == "reconstructed"
    assert result["period_end"] == "2025-12-31"
    assert result["formula_sha256"] == DELNETFIN_FORMULA_SHA256


def test_sec_delnetfin_fails_closed_when_required_component_is_missing() -> None:
    facts = _facts()
    facts = facts.loc[facts["tag"].ne("LongTermInvestments")].copy()

    result = calculate_sec_delnetfin_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]
    assert result["reason_if_missing"] == "missing_required_annual_component"


def test_sec_delnetfin_fails_closed_on_misaligned_fiscal_periods() -> None:
    facts = _facts()
    facts.loc[
        facts["tag"].eq("LongTermInvestments")
        & facts["period_end"].eq("2025-12-31"),
        "period_end",
    ] = "2025-11-30"

    result = calculate_sec_delnetfin_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]
    assert result["reason_if_missing"] in {
        "missing_required_annual_component",
        "misaligned_annual_periods",
    }


def test_sec_delnetfin_is_connected_to_guarded_sec_batch() -> None:
    runner = (ROOT / "scripts" / "run_openap_149_sec_companyfacts.py").read_text(
        encoding="utf-8"
    )
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-sec-companyfacts.yml"
    ).read_text(encoding="utf-8")

    assert "calculate_sec_delnetfin_current" in runner
    assert "tests/test_openap_181_sec_delnetfin.py" in workflow
    assert "require_github_actions_or_explicit_local_permission" in runner
