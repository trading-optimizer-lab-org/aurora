from __future__ import annotations

import hashlib
import runpy
import sys
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked


class _Response:
    def __init__(self, status_code: int, payload: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(
                f"{self.status_code} response",
                response=self,
            )

    def iter_content(self, chunk_size: int):
        assert chunk_size > 0
        yield self._payload


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return next(self.responses)


def _module():
    return import_module("aurora.research.openap_181.sec_fsd_access")


def _filing_module():
    return import_module("aurora.research.openap_181.sec_filing_access")


def _rendered_module():
    return import_module("aurora.research.openap_181.sec_rendered_reports")


def test_official_fsd_download_records_origin_access_headers_hash_and_size(tmp_path):
    module = _module()
    payload = b"PK\x03\x04fixture-sec-fsd"
    session = _Session([_Response(200, payload)])

    summary = module.download_official_sec_fsd_archives(
        ("2024q1",),
        tmp_path / "zips",
        tmp_path / "manifest.csv",
        user_agent="Aurora Research https://github.com/example/aurora",
        session=session,
        retry_delays=(),
    )

    expected_url = (
        "https://www.sec.gov/files/dera/data/"
        "financial-statement-data-sets/2024q1.zip"
    )
    assert summary == {
        "all_downloaded": True,
        "downloaded": 1,
        "failed": 0,
        "quarters_requested": 1,
    }
    assert (tmp_path / "zips" / "2024q1.zip").read_bytes() == payload
    manifest = pd.read_csv(tmp_path / "manifest.csv", keep_default_na=False)
    assert manifest.to_dict(orient="records") == [
        {
            "source_id": "sec_fsd_2024q1",
            "source_url": expected_url,
            "access_url": expected_url,
            "access_method": "sec_official_direct_fair_access",
            "period": "2024q1",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "retrieved_at": manifest.loc[0, "retrieved_at"],
            "status": "downloaded",
            "http_status": 200,
            "failure_reason": "",
        }
    ]
    call = session.calls[0]
    assert call["url"] == expected_url
    assert call["headers"] == {
        "User-Agent": "Aurora Research https://github.com/example/aurora",
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    assert call["allow_redirects"] is True
    assert call["stream"] is True


def test_official_fsd_http_403_is_bounded_and_persisted_as_a_blocker(tmp_path):
    module = _module()
    session = _Session([_Response(403), _Response(403)])

    summary = module.download_official_sec_fsd_archives(
        ("2021q1", "2021q2"),
        tmp_path / "zips",
        tmp_path / "manifest.csv",
        user_agent="Aurora Research https://github.com/example/aurora",
        session=session,
        retry_delays=(0,),
    )

    assert summary == {
        "all_downloaded": False,
        "downloaded": 0,
        "failed": 1,
        "quarters_requested": 2,
    }
    assert len(session.calls) == 2
    assert not list((tmp_path / "zips").glob("*.part"))
    assert not list((tmp_path / "zips").glob("*.zip"))
    manifest = pd.read_csv(tmp_path / "manifest.csv", keep_default_na=False)
    assert manifest["period"].tolist() == ["2021q1"]
    assert manifest.loc[0, "status"] == "failed"
    assert manifest.loc[0, "http_status"] == 403
    assert manifest.loc[0, "failure_reason"] == "http_403_after_2_attempts"


def test_official_notes_download_records_origin_hash_and_size(tmp_path):
    module = _module()
    payload = b"PK\x03\x04fixture-sec-notes"
    session = _Session([_Response(200, payload)])

    summary = module.download_official_sec_notes_archives(
        ("2026_07",),
        tmp_path / "zips",
        tmp_path / "manifest.csv",
        user_agent="Aurora Research https://github.com/example/aurora",
        session=session,
        retry_delays=(),
    )

    expected_url = (
        "https://www.sec.gov/files/dera/data/"
        "financial-statement-notes-data-sets/2026_07_notes.zip"
    )
    assert summary == {
        "all_downloaded": True,
        "downloaded": 1,
        "failed": 0,
        "periods_requested": 1,
    }
    assert (tmp_path / "zips" / "2026_07_notes.zip").read_bytes() == payload
    manifest = pd.read_csv(tmp_path / "manifest.csv", keep_default_na=False)
    assert manifest.to_dict(orient="records") == [
        {
            "source_id": "sec_notes_2026_07",
            "source_url": expected_url,
            "access_url": expected_url,
            "access_method": "sec_official_notes_direct_fair_access",
            "period": "2026_07",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "retrieved_at": manifest.loc[0, "retrieved_at"],
            "status": "downloaded",
            "http_status": 200,
            "failure_reason": "",
        }
    ]
    assert session.calls[0]["url"] == expected_url


def test_sec_fsd_access_cli_fails_closed_outside_github(tmp_path, monkeypatch):
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "run_openap_181_sec_fsd_access.py"
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(tmp_path)])

    with pytest.raises(LocalRunBlocked, match="OpenAP 181 SEC FSD access"):
        runpy.run_path(str(script), run_name="__main__")


def test_sec_notes_access_cli_fails_closed_outside_github(tmp_path, monkeypatch):
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "run_openap_149_sec_notes_access.py"
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(tmp_path)])

    with pytest.raises(LocalRunBlocked, match="OpenAP 149 SEC Notes access"):
        runpy.run_path(str(script), run_name="__main__")


def test_official_filing_download_records_identity_origin_hash_and_size(tmp_path):
    module = _filing_module()
    payload = b"<html xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'></html>"
    session = _Session([_Response(200, payload)])

    summary = module.download_official_sec_filing(
        cik="320193",
        accession_number="0000320193-25-000079",
        primary_document="aapl-20250927.htm",
        output_dir=tmp_path / "filing",
        manifest_path=tmp_path / "manifest.csv",
        user_agent="Aurora Research https://github.com/example/aurora",
        session=session,
        retry_delays=(),
    )

    expected_url = (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019325000079/aapl-20250927.htm"
    )
    expected_path = tmp_path / "filing" / "aapl-20250927.htm"
    assert summary == {
        "all_downloaded": True,
        "downloaded": 1,
        "failed": 0,
        "filings_requested": 1,
    }
    assert expected_path.read_bytes() == payload
    manifest = pd.read_csv(
        tmp_path / "manifest.csv", keep_default_na=False, dtype={"cik": str}
    )
    assert manifest.to_dict(orient="records") == [
        {
            "source_id": "sec_filing_0000320193-25-000079",
            "source_url": expected_url,
            "access_url": expected_url,
            "access_method": "sec_official_filing_fair_access",
            "cik": "0000320193",
            "accession_number": "0000320193-25-000079",
            "primary_document": "aapl-20250927.htm",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "retrieved_at": manifest.loc[0, "retrieved_at"],
            "status": "downloaded",
            "http_status": 200,
            "failure_reason": "",
        }
    ]
    call = session.calls[0]
    assert call["url"] == expected_url
    assert call["headers"] == {
        "User-Agent": "Aurora Research https://github.com/example/aurora",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


def test_locate_nearest_rendered_ppe_report_from_filing_summary():
    module = _rendered_module()
    summary = """
      R43.htm
      Financial Instruments - Cash and Marketable Securities (Details)
      R46.htm
      Disclosure - Property, Plant and Equipment - Gross Property, Plant and
      Equipment by Major Asset Class and Accumulated Depreciation (Details)
      R47.htm
      Property, Plant and Equipment - Additional Information (Details)
    """

    assert module.locate_rendered_ppe_report(summary) == "R46.htm"


def test_parse_rendered_ppe_report_extracts_exact_realestate_inputs():
    module = _rendered_module()
    report = """
| Property, Plant and Equipment - USD ($) $ in Millions | Sep. 27, 2025 | Sep. 28, 2024 |
| --- | --- | --- |
| Property, Plant and Equipment [Line Items] |  |  |
| Gross property, plant and equipment | $ 125,848 | $ 119,128 |
| Accumulated depreciation | (76,014) | (73,448) |
| Total property, plant and equipment, net | 49,834 | 45,680 |
| Land and buildings |  |  |
| Property, Plant and Equipment [Line Items] |  |  |
| Gross property, plant and equipment | 27,337 | 24,690 |
| Machinery, equipment and internal-use software |  |  |
| Property, Plant and Equipment [Line Items] |  |  |
| Gross property, plant and equipment | 83,420 | 80,205 |
"""

    rows = module.extract_rendered_realestate_inputs(report)

    assert rows == [
        {
            "period_end": "2025-09-27",
            "land_gross": None,
            "buildings_gross": None,
            "land_and_buildings_gross": 27337.0,
            "ppe_gross": 125848.0,
            "ppe_net": 49834.0,
            "realestate_numerator": 27337.0,
            "realestate_raw": pytest.approx(27337.0 / 125848.0),
            "formula_variant": "combined_land_and_buildings_over_gross_ppe",
        },
        {
            "period_end": "2024-09-28",
            "land_gross": None,
            "buildings_gross": None,
            "land_and_buildings_gross": 24690.0,
            "ppe_gross": 119128.0,
            "ppe_net": 45680.0,
            "realestate_numerator": 24690.0,
            "realestate_raw": pytest.approx(24690.0 / 119128.0),
            "formula_variant": "combined_land_and_buildings_over_gross_ppe",
        },
    ]


def test_parse_rendered_ppe_report_accepts_jina_javascript_links():
    module = _rendered_module()
    report = """
| **Property, Plant and Equipment - USD ($) $ in Millions** | Sep. 27, 2025 |
| --- | --- |
| [**Property, Plant and Equipment [Line Items]**](javascript:void(0);) |  |
| [Gross property, plant and equipment](javascript:void(0);) | $ 125,848 |
| [Total property, plant and equipment, net](javascript:void(0);) | 49,834 |
| [Land and buildings](javascript:void(0);) |  |
| [**Property, Plant and Equipment [Line Items]**](javascript:void(0);) |  |
| [Gross property, plant and equipment](javascript:void(0);) | 27,337 |
"""

    rows = module.extract_rendered_realestate_inputs(report)

    assert len(rows) == 1
    assert rows[0]["period_end"] == "2025-09-27"
    assert rows[0]["ppe_gross"] == 125848.0
    assert rows[0]["ppe_net"] == 49834.0
    assert rows[0]["land_and_buildings_gross"] == 27337.0
    assert rows[0]["realestate_raw"] == pytest.approx(27337.0 / 125848.0)


def test_build_rendered_realestate_evidence_preserves_pit_and_stays_uncomputed():
    module = _rendered_module()
    report = """
| Property, Plant and Equipment - USD ($) $ in Millions | Sep. 27, 2025 |
| --- | --- |
| Property, Plant and Equipment [Line Items] |  |
| Gross property, plant and equipment | $ 125,848 |
| Total property, plant and equipment, net | 49,834 |
| Land and buildings |  |
| Property, Plant and Equipment [Line Items] |  |
| Gross property, plant and equipment | 27,337 |
"""

    evidence = module.build_rendered_realestate_evidence(
        selected_filing={
            "cik": "320193",
            "accession_number": "0000320193-25-000079",
            "form": "10-K",
            "report_date": "2025-09-27",
            "filing_date": "2025-10-31",
            "accepted_at": "2025-10-31T10:00:00+00:00",
            "formation_at": "2026-08-09T23:59:59+00:00",
        },
        report_metadata={
            "report_filename": "R46.htm",
            "source_url": (
                "https://www.sec.gov/Archives/edgar/data/320193/"
                "000032019325000079/R46.htm"
            ),
            "access_url": (
                "https://r.jina.ai/http://www.sec.gov/Archives/edgar/data/"
                "320193/000032019325000079/R46.htm"
            ),
            "access_method": "sec_via_jina_readthrough",
            "sha256": "e" * 64,
            "size_bytes": 7136,
        },
        report_text=report,
    )

    assert evidence == {
        "signal": "realestate",
        "status": "raw_data_acquired",
        "raw_data_acquired": True,
        "realestate_raw_computed": True,
        "current_signal_computed": False,
        "strict_score_eligible": False,
        "fidelity": "reconstructed_not_strict",
        "proxy_used": True,
        "minimum_industry_observations": 5,
        "remaining_blocker": "sic2_month_mean_requires_at_least_5_issuers",
        "records": [
            {
                "cik": "320193",
                "accession_number": "0000320193-25-000079",
                "form": "10-K",
                "report_date": "2025-09-27",
                "filing_date": "2025-10-31",
                "available_at": "2025-10-31T10:00:00+00:00",
                "formation_at": "2026-08-09T23:59:59+00:00",
                "period_end": "2025-09-27",
                "land_gross": None,
                "buildings_gross": None,
                "land_and_buildings_gross": 27337.0,
                "ppe_gross": 125848.0,
                "ppe_net": 49834.0,
                "realestate_numerator": 27337.0,
                "realestate_raw": pytest.approx(27337.0 / 125848.0),
                "formula_variant": "combined_land_and_buildings_over_gross_ppe",
                "report_filename": "R46.htm",
                "source_url": (
                    "https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000079/R46.htm"
                ),
                "access_url": (
                    "https://r.jina.ai/http://www.sec.gov/Archives/edgar/data/"
                    "320193/000032019325000079/R46.htm"
                ),
                "access_method": "sec_via_jina_readthrough",
                "source_sha256": "e" * 64,
                "source_size_bytes": 7136,
            }
        ],
    }


def test_select_current_realestate_pilot_uses_latest_causal_same_sic2_filings():
    module = _rendered_module()
    common = {
        "form": "10-K",
        "is_xbrl": True,
        "sic": "3571",
        "report_date": "2025-12-31",
        "filing_date": "2026-02-01",
        "primary_document": "annual.htm",
    }
    submissions = [
        {
            **common,
            "cik": "320193",
            "accession_number": "anchor-old",
            "accepted_at": "2025-02-01T12:00:00Z",
        },
        {
            **common,
            "cik": "320193",
            "accession_number": "anchor-current",
            "accepted_at": "2026-02-01T12:00:00Z",
        },
        *[
            {
                **common,
                "cik": str(cik),
                "accession_number": f"peer-{cik}",
                "accepted_at": "2026-03-01T12:00:00Z",
            }
            for cik in (100, 200, 300, 400)
        ],
        {
            **common,
            "cik": "500",
            "accession_number": "future",
            "accepted_at": "2026-09-01T12:00:00Z",
        },
        {
            **common,
            "cik": "600",
            "accession_number": "quarterly",
            "accepted_at": "2026-03-01T12:00:00Z",
            "form": "10-Q",
        },
        {
            **common,
            "cik": "700",
            "accession_number": "other-sector",
            "accepted_at": "2026-03-01T12:00:00Z",
            "sic": "3674",
        },
    ]

    selected = module.select_current_realestate_pilot_filings(
        submissions,
        formation_at="2026-08-09T23:59:59Z",
        target_sic2="35",
        anchor_cik="320193",
        minimum_issuers=5,
        maximum_issuers=5,
    )

    assert [row["cik"] for row in selected] == [
        "320193",
        "100",
        "200",
        "300",
        "400",
    ]
    assert selected[0]["accession_number"] == "anchor-current"
    assert all(row["sic2"] == "35" for row in selected)
    assert all(row["formation_at"] == "2026-08-09T23:59:59Z" for row in selected)


def test_compute_current_realestate_cross_section_demeans_only_groups_of_five():
    module = _rendered_module()
    records = [
        {
            "cik": str(index),
            "symbol": f"S{index}",
            "sic2": "35",
            "formation_at": f"2026-08-0{index}T23:59:59Z",
            "available_at": "2026-07-31T12:00:00Z",
            "assets": 1000.0 + index,
            "realestate_raw": raw,
        }
        for index, raw in enumerate((0.1, 0.2, 0.3, 0.4, 0.5), start=1)
    ]
    records.append(
        {
            "cik": "99",
            "symbol": "OTHER",
            "sic2": "36",
            "formation_at": "2026-08-09T23:59:59Z",
            "available_at": "2026-07-31T12:00:00Z",
            "assets": 500.0,
            "realestate_raw": 0.9,
        }
    )

    adjusted = module.compute_current_realestate_cross_section(
        records,
        minimum_observations=5,
    )
    by_symbol = {row["symbol"]: row for row in adjusted}

    assert by_symbol["S1"]["industry_observations"] == 5
    assert by_symbol["S1"]["industry_mean_realestate_raw"] == pytest.approx(0.3)
    assert by_symbol["S1"]["realestate_value"] == pytest.approx(-0.2)
    assert by_symbol["S5"]["realestate_value"] == pytest.approx(0.2)
    assert by_symbol["S3"]["status"] == "current_signal_computed"
    assert by_symbol["S3"]["current_signal_computed"] is True
    assert by_symbol["S3"]["strict_score_eligible"] is False
    assert by_symbol["S3"]["fidelity"] == "reconstructed_not_strict"
    assert by_symbol["OTHER"]["industry_observations"] == 1
    assert by_symbol["OTHER"]["realestate_value"] is None
    assert by_symbol["OTHER"]["status"] == "blocked_coverage"
    assert by_symbol["OTHER"]["current_signal_computed"] is False
