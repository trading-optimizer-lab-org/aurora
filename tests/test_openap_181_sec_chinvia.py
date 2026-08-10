from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.research.openap_181.sec_chinvia import (
    CHINVIA_FORMULA_SHA256,
    calculate_sec_chinvia_current,
)


FORMATION_AT = "2026-08-09T23:59:59Z"
RETRIEVED_AT = "2026-08-10T10:00:00Z"
ROOT = Path(__file__).resolve().parents[1]


def _status() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for cik, symbol in ((1, "AAA"), (2, "BBB")):
        rows.extend(
            [
                {
                    "cik": cik,
                    "symbol": symbol,
                    "surface": "companyfacts",
                    "status": "ok",
                },
                {
                    "cik": cik,
                    "symbol": symbol,
                    "surface": "submissions",
                    "status": "ok",
                },
            ]
        )
    return pd.DataFrame(rows)


def _fact(
    cik: int,
    year: int,
    value: float,
    *,
    tag: str = "PaymentsToAcquirePropertyPlantAndEquipment",
) -> dict[str, object]:
    return {
        "cik": cik,
        "taxonomy": "us-gaap",
        "tag": tag,
        "unit": "USD",
        "value": value,
        "period_start": f"{year}-01-01" if tag.startswith("Payments") else "",
        "period_end": f"{year}-12-31",
        "form": "10-K",
        "filed": f"{year + 1}-03-01",
        "accession_number": f"{cik:010d}-{year % 100:02d}-000001",
        "available_at": f"{year + 1}-03-01T12:00:00Z",
    }


def _facts() -> pd.DataFrame:
    rows = []
    for year, value in ((2025, 30.0), (2024, 20.0), (2023, 10.0)):
        rows.append(_fact(1, year, value))
    for year, value in ((2025, 12.0), (2024, 10.0), (2023, 8.0)):
        rows.append(_fact(2, year, value))
    return pd.DataFrame(rows)


def _submissions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik": cik,
                "accession_number": f"{cik:010d}-26-000001",
                "accepted_at": "2026-04-01T12:00:00Z",
                "sic": 3571,
            }
            for cik in (1, 2)
        ]
    )


def test_sec_chinvia_applies_current_two_digit_sic_industry_mean() -> None:
    result = calculate_sec_chinvia_current(
        _facts(),
        _submissions(),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).set_index("ticker")

    assert result.loc["AAA", "value"] == pytest.approx(1.0 / 3.0)
    assert result.loc["BBB", "value"] == pytest.approx(-1.0 / 3.0)
    assert result["current_usable"].all()
    assert result["fidelity_class"].eq("reconstructed").all()
    assert result["formula_sha256"].eq(CHINVIA_FORMULA_SHA256).all()


def test_sec_chinvia_uses_official_ppe_change_fallback_for_missing_capex() -> None:
    facts = _facts().loc[
        lambda frame: ~(
            frame["cik"].eq(1)
            & frame["period_end"].eq("2025-12-31")
        )
    ].copy()
    facts = pd.concat(
        [
            facts,
            pd.DataFrame(
                [
                    _fact(
                        1,
                        2025,
                        130.0,
                        tag="PropertyPlantAndEquipmentNet",
                    ),
                    _fact(
                        1,
                        2024,
                        100.0,
                        tag="PropertyPlantAndEquipmentNet",
                    ),
                ]
            ),
        ],
        ignore_index=True,
    )
    result = calculate_sec_chinvia_current(
        facts,
        _submissions(),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).set_index("ticker")

    assert result.loc["AAA", "value"] == pytest.approx(1.0 / 3.0)
    assert result.loc["AAA", "current_usable"]


def test_sec_chinvia_rejects_conflicting_latest_sic() -> None:
    submissions = pd.concat(
        [
            _submissions(),
            pd.DataFrame(
                [
                    {
                        "cik": 1,
                        "accession_number": "0000000001-26-000002",
                        "accepted_at": "2026-04-01T12:00:00Z",
                        "sic": 2082,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    result = calculate_sec_chinvia_current(
        _facts(),
        submissions,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).set_index("ticker")

    assert pd.isna(result.loc["AAA", "value"])
    assert not result.loc["AAA", "current_usable"]
    assert result.loc["AAA", "reason_if_missing"] == (
        "missing_unambiguous_current_sec_sic"
    )


def test_sec_chinvia_is_connected_to_guarded_sec_batch() -> None:
    runner = (ROOT / "scripts" / "run_openap_149_sec_companyfacts.py").read_text(
        encoding="utf-8"
    )
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-sec-companyfacts.yml"
    ).read_text(encoding="utf-8")

    assert "calculate_sec_chinvia_current" in runner
    assert "tests/test_openap_181_sec_chinvia.py" in workflow
    assert "require_github_actions_or_explicit_local_permission" in runner
