from __future__ import annotations

import hashlib
import json
import runpy
import sys
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked


class _ReadthroughResponse:
    def __init__(self, payload: bytes, status_code: int = 200) -> None:
        self.content = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(
                f"{self.status_code} response",
                response=self,
            )


class _ReadthroughSession:
    def __init__(self, responses: list[_ReadthroughResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return next(self.responses)


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


def test_acquire_rendered_filing_preserves_origin_access_hashes_and_text(
    tmp_path,
) -> None:
    module = _module()
    summary = b"""Markdown Content:
R43.htm
Cash and Marketable Securities (Details)
R46.htm
Gross Property, Plant and Equipment by Major Asset Class (Details)
"""
    report = b"""Markdown Content:
| Property, Plant and Equipment - USD ($) $ in Millions | Sep. 27, 2025 |
| --- | --- |
| Property, Plant and Equipment [Line Items] |  |
| Gross property, plant and equipment | $ 125,848 |
| Total property, plant and equipment, net | 49,834 |
| Land and buildings |  |
| Property, Plant and Equipment [Line Items] |  |
| Gross property, plant and equipment | 27,337 |
"""
    session = _ReadthroughSession(
        [_ReadthroughResponse(summary), _ReadthroughResponse(report)]
    )
    selected = {
        "cik": "320193",
        "accession_number": "0000320193-25-000079",
        "form": "10-K",
        "report_date": "2025-09-27",
        "filing_date": "2025-10-31",
        "accepted_at": "2025-10-31T10:01:26Z",
        "formation_at": "2026-08-09T23:59:59Z",
    }

    evidence = module.acquire_rendered_realestate_filing(
        selected,
        output_dir=tmp_path,
        session=session,
        retry_delays=(),
        retrieved_at="2026-08-10T01:00:00Z",
    )

    origin = (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019325000079"
    )
    assert [call["url"] for call in session.calls] == [
        f"https://r.jina.ai/http://{origin.removeprefix('https://')}/FilingSummary.xml",
        f"https://r.jina.ai/http://{origin.removeprefix('https://')}/R46.htm",
    ]
    assert evidence["raw_data_acquired"] is True
    assert evidence["current_signal_computed"] is False
    assert evidence["strict_score_eligible"] is False
    assert [row["filename"] for row in evidence["source_files"]] == [
        "FilingSummary.xml",
        "R46.htm",
    ]
    assert evidence["source_files"][1]["source_url"] == f"{origin}/R46.htm"
    assert evidence["source_files"][1]["access_method"] == (
        "sec_via_jina_readthrough"
    )
    assert evidence["source_files"][1]["sha256"] == hashlib.sha256(
        report
    ).hexdigest()
    assert evidence["source_files"][1]["retrieved_at"] == (
        "2026-08-10T01:00:00Z"
    )
    assert evidence["records"][0]["realestate_raw"] == pytest.approx(
        27337.0 / 125848.0
    )
    assert evidence["records"][0]["source_sha256"] == hashlib.sha256(
        report
    ).hexdigest()
    stored = tmp_path / "CIK0000320193"
    assert (stored / "FilingSummary.xml.txt").read_bytes() == summary
    assert (stored / "R46.htm.txt").read_bytes() == report


def test_run_sector_batch_preserves_failures_and_publishes_current_values(
    tmp_path,
    monkeypatch,
) -> None:
    module = _module()
    formation_at = "2026-08-09T23:59:59Z"
    candidates = []
    for index in range(1, 7):
        candidates.append(
            {
                "cik": str(index),
                "security_id": f"US-SEC-{index:010d}-S{index}",
                "symbol": f"S{index}",
                "sic2": "35",
                "accession_number": f"{index:010d}-25-000001",
                "report_date": f"2025-12-{index:02d}",
                "formation_at": formation_at,
                "assets": 1_000.0 + index,
                "assets_available_at": "2026-02-02T12:00:00Z",
                "assets_source_sha256": f"{index:x}" * 64,
                "fidelity": "reconstructed_not_strict",
                "strict_score_eligible": False,
            }
        )

    monkeypatch.setattr(
        module,
        "select_realestate_sector_pilot_candidates",
        lambda *args, **kwargs: candidates,
    )

    def acquire(selected, **kwargs):
        index = int(selected["cik"])
        if index == 6:
            raise RuntimeError("bounded transport failure")
        return {
            "signal": "realestate",
            "status": "raw_data_acquired",
            "raw_data_acquired": True,
            "current_signal_computed": False,
            "strict_score_eligible": False,
            "fidelity": "reconstructed_not_strict",
            "source_files": [
                {
                    "filename": "R1.htm",
                    "source_url": f"https://www.sec.gov/{index}/R1.htm",
                    "access_url": (
                        f"https://r.jina.ai/http://www.sec.gov/{index}/R1.htm"
                    ),
                    "access_method": "sec_via_jina_readthrough",
                    "status": "downloaded",
                    "http_status": 200,
                    "failure_reason": "",
                    "sha256": f"{index + 6:x}" * 64,
                    "size_bytes": 123,
                    "retrieved_at": kwargs["retrieved_at"],
                }
            ],
            "records": [
                {
                    "cik": str(index),
                    "period_end": selected["report_date"],
                    "available_at": "2026-02-01T12:00:00Z",
                    "realestate_raw": index / 10.0,
                    "source_sha256": f"{index + 6:x}" * 64,
                }
            ],
        }

    monkeypatch.setattr(module, "acquire_rendered_realestate_filing", acquire)

    result = module.run_rendered_realestate_sector_batch(
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        formation_at=formation_at,
        target_sic2="35",
        anchor_cik="320193",
        source_run_id="31270341796",
        output_dir=tmp_path,
        minimum_issuers=5,
        maximum_issuers=12,
        retrieved_at="2026-08-10T01:00:00Z",
    )

    assert result["status"] == "current_signal_computed"
    assert result["candidates_selected"] == 6
    assert result["raw_issuers_acquired"] == 5
    assert result["current_values_computed"] == 5
    assert result["source_run_id"] == "31270341796"
    assert result["strict_score_eligible"] is False
    assert result["locked_opened"] is False
    assert result["forward_opened"] is False
    assert result["validation_used_for_selection"] is False
    assert result["cost_eur"] == 0
    assert result["failed_issuers"] == [
        {"cik": "6", "reason": "acquisition_error:RuntimeError"}
    ]

    current = pd.read_csv(tmp_path / "openap_149_realestate_current.csv")
    manifest = pd.read_csv(
        tmp_path / "openap_149_realestate_acquisition_manifest.csv"
    )
    stored_summary = json.loads(
        (tmp_path / "openap_149_realestate_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(current) == 5
    assert current["signal"].eq("realestate").all()
    assert current["current_signal_computed"].all()
    assert not current["strict_score_eligible"].any()
    assert len(manifest) == 6
    assert manifest["status"].value_counts().to_dict() == {
        "raw_data_acquired": 5,
        "acquisition_error": 1,
    }
    assert stored_summary == result
    assert (tmp_path / "openap_149_realestate_candidates.json").is_file()
    assert (tmp_path / "openap_149_realestate_issuer_evidence.json").is_file()
    assert (tmp_path / "openap_149_realestate_raw_records.csv").is_file()
    assert (tmp_path / "openap_149_realestate_current.parquet").is_file()


def test_realestate_sector_batch_cli_fails_closed_outside_github(
    tmp_path,
    monkeypatch,
) -> None:
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "run_openap_149_realestate_rendered_batch.py"
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(tmp_path)])

    with pytest.raises(
        LocalRunBlocked,
        match="OpenAP 149 rendered realestate sector batch",
    ):
        runpy.run_path(str(script), run_name="__main__")


def _write_complete_sector_lake(root: Path) -> None:
    fact_columns = [
        "cik",
        "taxonomy",
        "tag",
        "unit",
        "value",
        "period_end",
        "form",
        "accession_number",
        "available_at",
        "source",
        "source_mode",
    ]
    submission_columns = [
        "cik",
        "accession_number",
        "filing_date",
        "accepted_at",
        "report_date",
        "form",
        "primary_document",
        "is_xbrl",
        "sic",
    ]
    status_columns = [
        "cik",
        "symbol",
        "surface",
        "status",
        "canonical_json_sha256",
        "source_mode",
        "source_url",
    ]
    ciks = (320193, 100, 101, 102, 103)
    for shard in range(48):
        directory = root / f"openap-sec-repair-lake-{shard}"
        directory.mkdir(parents=True)
        facts = []
        submissions = []
        statuses = []
        if shard < len(ciks):
            cik = ciks[shard]
            report_date = "2025-09-27" if cik == 320193 else "2025-12-31"
            accession = f"{cik:010d}-25-{shard + 1:06d}"
            source = (
                "https://data.sec.gov/api/xbrl/companyfacts/"
                f"CIK{cik:010d}.json"
            )
            facts.append(
                {
                    "cik": cik,
                    "taxonomy": "us-gaap",
                    "tag": "Assets",
                    "unit": "USD",
                    "value": float(10_000 - shard * 100),
                    "period_end": report_date,
                    "form": "10-K",
                    "accession_number": accession,
                    "available_at": "2026-02-01T12:00:00Z",
                    "source": source,
                    "source_mode": "sec_official_api",
                }
            )
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
            for surface in ("companyfacts", "submissions"):
                statuses.append(
                    {
                        "cik": cik,
                        "symbol": "AAPL" if cik == 320193 else f"S{cik}",
                        "surface": surface,
                        "status": "ok",
                        "canonical_json_sha256": f"{shard + 1:x}" * 64,
                        "source_mode": "sec_official_api",
                        "source_url": source,
                    }
                )
        pd.DataFrame(facts, columns=fact_columns).to_parquet(
            directory / f"sec_companyfacts_{shard}.parquet",
            index=False,
        )
        pd.DataFrame(submissions, columns=submission_columns).to_parquet(
            directory / f"sec_submissions_{shard}.parquet",
            index=False,
        )
        pd.DataFrame(statuses, columns=status_columns).to_csv(
            directory / f"sec_status_{shard}.csv",
            index=False,
        )
        (directory / f"sec_summary_{shard}.json").write_text(
            json.dumps({"retrieved_at": "2026-08-10T00:00:00Z"}) + "\n",
            encoding="utf-8",
        )


def test_realestate_sector_batch_cli_reads_complete_lake_and_writes_runtime_output(
    tmp_path,
    monkeypatch,
) -> None:
    module = _module()
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "run_openap_149_realestate_rendered_batch.py"
    )
    sec_root = tmp_path / "sec"
    runtime_root = tmp_path / "runtime"
    _write_complete_sector_lake(sec_root)

    def acquire(selected, **kwargs):
        cik = str(int(selected["cik"]))
        raw = (int(cik) % 10) / 10.0
        return {
            "signal": "realestate",
            "status": "raw_data_acquired",
            "raw_data_acquired": True,
            "current_signal_computed": False,
            "strict_score_eligible": False,
            "fidelity": "reconstructed_not_strict",
            "source_files": [],
            "records": [
                {
                    "cik": cik,
                    "period_end": selected["report_date"],
                    "available_at": "2026-02-01T12:00:00Z",
                    "realestate_raw": raw,
                    "source_sha256": "a" * 64,
                }
            ],
        }

    monkeypatch.setattr(module, "acquire_rendered_realestate_filing", acquire)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AU_DATA_DIR", str(runtime_root))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--sec-root",
            str(sec_root),
            "--formation-at",
            "2026-08-09T23:59:59Z",
            "--target-sic2",
            "35",
            "--anchor-cik",
            "320193",
            "--minimum-issuers",
            "5",
            "--maximum-issuers",
            "5",
            "--source-run-id",
            "31270341796",
            "--output-dir",
            "openap_149_realestate_rendered_batch",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(script), run_name="__main__")

    assert exit_info.value.code == 0
    output = runtime_root / "openap_149_realestate_rendered_batch"
    summary = json.loads(
        (output / "openap_149_realestate_summary.json").read_text(
            encoding="utf-8"
        )
    )
    current = pd.read_csv(output / "openap_149_realestate_current.csv")
    assert summary["source_file_counts"] == {
        "companyfacts": 48,
        "submissions": 48,
        "status": 48,
        "summary": 48,
    }
    assert summary["source_run_id"] == "31270341796"
    assert summary["current_values_computed"] == 5
    assert len(current) == 5
    assert not current["strict_score_eligible"].any()
