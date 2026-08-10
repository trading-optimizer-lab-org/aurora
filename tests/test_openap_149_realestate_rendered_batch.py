from __future__ import annotations

from importlib import import_module

import pandas as pd
import pytest


def _module():
    return import_module("aurora.research.openap_181.realestate_rendered_batch")


def test_select_sector_pilot_uses_causal_assets_and_complete_sec_identity() -> None:
    module = _module()
    formation_at = "2026-08-09T23:59:59Z"
    ciks = (320193, 101, 102, 103, 104, 105)
    submissions: list[dict[str, object]] = []
    facts: list[dict[str, object]] = []
    status: list[dict[str, object]] = []

    for position, cik in enumerate(ciks):
        accession = f"{cik:010d}-25-{position + 1:06d}"
        report_date = "2025-09-27" if cik == 320193 else "2025-12-31"
        submissions.append(
            {
                "cik": cik,
                "accession_number": accession,
                "filing_date": "2026-02-01",
                "accepted_at": "2026-02-01T12:00:00Z",
                "report_date": report_date,
                "form": "10-K",
                "primary_document": f"issuer-{cik}.htm",
                "is_xbrl": True,
                "sic": "3571",
            }
        )
        facts.append(
            {
                "cik": cik,
                "taxonomy": "us-gaap",
                "tag": "Assets",
                "unit": "USD",
                "value": 1_000.0 if cik == 320193 else float((cik - 100) * 100),
                "period_end": report_date,
                "form": "10-K",
                "accession_number": accession,
                "available_at": "2026-02-01T12:00:00Z",
                "source": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                "source_mode": "sec_official_api",
            }
        )
        for surface in ("companyfacts", "submissions"):
            status.append(
                {
                    "cik": cik,
                    "symbol": "AAPL" if cik == 320193 else f"S{cik}",
                    "surface": surface,
                    "status": "ok",
                    "canonical_json_sha256": f"{position + 1:x}" * 64,
                    "source_mode": "sec_official_api",
                    "source_url": (
                        f"https://data.sec.gov/{surface}/CIK{cik:010d}.json"
                    ),
                }
            )

    submissions.append(
        {
            **submissions[-1],
            "accession_number": "0000000105-26-999999",
            "accepted_at": "2026-09-01T12:00:00Z",
            "report_date": "2026-06-30",
        }
    )
    facts.append(
        {
            **facts[-1],
            "accession_number": "0000000105-26-999999",
            "available_at": "2026-09-01T12:00:00Z",
            "period_end": "2026-06-30",
            "value": 99_999.0,
        }
    )

    selected = module.select_realestate_sector_pilot_candidates(
        pd.DataFrame(facts),
        pd.DataFrame(submissions),
        pd.DataFrame(status),
        formation_at=formation_at,
        target_sic2="35",
        anchor_cik="320193",
        minimum_issuers=5,
        maximum_issuers=5,
    )

    assert [row["cik"] for row in selected] == [
        "320193",
        "105",
        "104",
        "103",
        "102",
    ]
    assert [row["assets"] for row in selected] == [
        1_000.0,
        500.0,
        400.0,
        300.0,
        200.0,
    ]
    assert selected[0]["security_id"] == "US-SEC-0000320193-AAPL"
    assert selected[1]["symbol"] == "S105"
    assert selected[1]["assets_tag"] == "Assets"
    assert selected[1]["assets_unit"] == "USD"
    assert selected[1]["assets_source_sha256"] == "6" * 64
    assert selected[1]["accession_number"] != "0000000105-26-999999"
    assert all(row["formation_at"] == formation_at for row in selected)
    assert all(row["fidelity"] == "reconstructed_not_strict" for row in selected)
    assert all(row["strict_score_eligible"] is False for row in selected)


def test_assemble_sector_pilot_computes_only_matching_annual_periods() -> None:
    module = _module()
    formation_at = "2026-08-09T23:59:59Z"
    candidates = []
    evidence = []
    for index, raw in enumerate((0.1, 0.2, 0.3, 0.4, 0.5), start=1):
        cik = str(index)
        report_date = f"2025-12-{index:02d}"
        candidates.append(
            {
                "cik": cik,
                "security_id": f"US-SEC-{index:010d}-S{index}",
                "symbol": f"S{index}",
                "sic2": "35",
                "accession_number": f"{index:010d}-25-000001",
                "report_date": report_date,
                "formation_at": formation_at,
                "assets": 1_000.0 + index,
                "assets_available_at": "2026-02-02T12:00:00Z",
                "assets_source_sha256": f"{index:x}" * 64,
                "fidelity": "reconstructed_not_strict",
                "strict_score_eligible": False,
            }
        )
        evidence.append(
            {
                "signal": "realestate",
                "status": "raw_data_acquired",
                "raw_data_acquired": True,
                "records": [
                    {
                        "cik": cik,
                        "period_end": "2024-12-31",
                        "available_at": "2025-02-01T12:00:00Z",
                        "realestate_raw": 9.9,
                        "source_sha256": "f" * 64,
                    },
                    {
                        "cik": cik,
                        "period_end": report_date,
                        "available_at": "2026-02-01T12:00:00Z",
                        "realestate_raw": raw,
                        "source_sha256": f"{index + 5:x}" * 64,
                    },
                ],
            }
        )

    result = module.assemble_realestate_sector_pilot(candidates, evidence)
    by_symbol = {row["symbol"]: row for row in result["records"]}

    assert result["signal"] == "realestate"
    assert result["status"] == "current_signal_computed"
    assert result["candidates_selected"] == 5
    assert result["raw_issuers_acquired"] == 5
    assert result["current_values_computed"] == 5
    assert result["strict_score_eligible"] is False
    assert result["fidelity"] == "reconstructed_not_strict"
    assert result["remaining_blocker"] == (
        "strict_crsp_sic_and_compustat_equivalence_unvalidated"
    )
    assert by_symbol["S1"]["industry_mean_realestate_raw"] == pytest.approx(0.3)
    assert by_symbol["S1"]["realestate_value"] == pytest.approx(-0.2)
    assert by_symbol["S5"]["realestate_value"] == pytest.approx(0.2)
    assert by_symbol["S1"]["period_end"] == "2025-12-01"
    assert by_symbol["S1"]["available_at"] == "2026-02-02T12:00:00+00:00"
    assert by_symbol["S1"]["source_sha256"] == "6" * 64
    assert all(row["realestate_raw"] != 9.9 for row in result["records"])
