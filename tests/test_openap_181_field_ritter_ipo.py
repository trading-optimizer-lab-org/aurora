from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd
import pytest

from aurora.research.openap_181.field_ritter_ipo import (
    FIELD_RITTER_DOCUMENTATION_URL,
    FIELD_RITTER_WORKBOOK_URL,
    build_field_ritter_current_identity,
    calculate_field_ritter_ipo_signals,
    extract_causal_sec_rd_expense,
    load_field_ritter_ipo_workbook,
    select_openap_ipo_rows,
)
from aurora.research.openap_181.field_ritter_access import (
    download_field_ritter_ipo_workbook,
)


HEADERS = (
    "offer date",
    "IPO name",
    "Ticker",
    "CUSIP",
    "ADR (2=ADR)",
    "VC",
    "Dual",
    "Post-issue shares",
    "Internet",
    "CRSP Perm",
    "Founding",
    "Rollup",
)
FORMATION_AT = "2026-08-10T12:00:00Z"
ROOT = Path(__file__).resolve().parents[1]


def _column_name(index: int) -> str:
    result = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _inline_cell(reference: str, value: object) -> str:
    if value is None:
        return f'<c r="{reference}" t="inlineStr"><is><t></t></is></c>'
    text = escape(str(value))
    return f'<c r="{reference}" t="inlineStr"><is><t>{text}</t></is></c>'


def _write_workbook(
    path: Path,
    rows: list[tuple[object, ...]],
    *,
    headers: tuple[str, ...] = HEADERS,
) -> None:
    all_rows = [headers, *rows]
    xml_rows: list[str] = []
    for row_number, values in enumerate(all_rows, start=1):
        cells = "".join(
            _inline_cell(f"{_column_name(index)}{row_number}", value)
            for index, value in enumerate(values)
        )
        xml_rows.append(f'<row r="{row_number}">{cells}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="1975-2025" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def _manifest(path: Path) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_id": "field_ritter_ipo_1975_2025",
                "source_url": FIELD_RITTER_WORKBOOK_URL,
                "documentation_url": FIELD_RITTER_DOCUMENTATION_URL,
                "access_url": FIELD_RITTER_WORKBOOK_URL,
                "access_method": "manual_official_static_excel",
                "published_at": "2026-01-19T16:47:15Z",
                "retrieved_at": "2026-08-10T10:00:00Z",
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
                "status": "downloaded",
                "http_status": 200,
                "failure_reason": "",
            }
        ]
    )


def _sample_rows() -> list[tuple[object, ...]]:
    return [
        (
            29567,
            "APPLE INC",
            "AAPL",
            "03783310",
            1,
            1,
            0,
            ".",
            0,
            14593,
            1976,
            ".",
        ),
        (
            19860313,
            "MICROSOFT CORP",
            "MSFT",
            "594918104",
            1,
            1,
            0,
            ".",
            0,
            10107,
            1975,
            ".",
        ),
        (
            19900101,
            "APPLE RELISTING",
            "AAPL",
            "037833100",
            1,
            0,
            0,
            ".",
            0,
            14593,
            1976,
            ".",
        ),
    ]


def test_loader_validates_transport_and_normalizes_real_workbook_schema(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "IPO-age.xlsx"
    _write_workbook(workbook, _sample_rows())

    rows, rejected, summary = load_field_ritter_ipo_workbook(
        workbook,
        _manifest(workbook),
    )
    selected = select_openap_ipo_rows(rows)

    assert rejected.empty
    assert rows["source_row"].tolist() == [2, 3, 4]
    assert rows["cusip"].tolist() == ["037833100", "594918104", "037833100"]
    assert rows["ipo_offer_date"].astype(str).tolist() == [
        "1980-12-12",
        "1986-03-13",
        "1990-01-01",
    ]
    assert selected[["permno", "company_name"]].to_dict(orient="records") == [
        {"permno": 10107, "company_name": "MICROSOFT CORP"},
        {"permno": 14593, "company_name": "APPLE INC"},
    ]
    assert selected.loc[selected["permno"].eq(14593), "source_row"].item() == 2
    assert rows["transport_sha256"].eq(
        sha256(workbook.read_bytes()).hexdigest()
    ).all()
    assert summary == {
        "source_rows": 3,
        "normalized_rows": 3,
        "rejected_rows": 0,
        "openap_selected_permnos": 2,
        "source_published_at": "2026-01-19T16:47:15+00:00",
        "workbook_size_bytes": workbook.stat().st_size,
    }


def test_loader_rejects_tampered_nonofficial_or_schema_drifted_input(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "IPO-age.xlsx"
    _write_workbook(workbook, _sample_rows())
    manifest = _manifest(workbook)

    with pytest.raises(ValueError, match="SHA-256"):
        load_field_ritter_ipo_workbook(
            workbook,
            manifest.assign(sha256="0" * 64),
        )
    with pytest.raises(ValueError, match="official Field-Ritter"):
        load_field_ritter_ipo_workbook(
            workbook,
            manifest.assign(source_url="https://example.test/IPO-age.xlsx"),
        )

    changed = tmp_path / "schema-drift" / "IPO-age.xlsx"
    changed.parent.mkdir()
    _write_workbook(
        changed,
        _sample_rows(),
        headers=("IPO date", *HEADERS[1:]),
    )
    with pytest.raises(ValueError, match="header contract"):
        load_field_ritter_ipo_workbook(changed, _manifest(changed))


class _StaticResponse:
    def __init__(self, payload: bytes, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = {
            "Content-Type": (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            "Last-Modified": "Mon, 19 Jan 2026 16:47:15 GMT",
        }

    def __enter__(self) -> _StaticResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code != 200:
            error = RuntimeError(f"HTTP {self.status_code}")
            error.response = self  # type: ignore[attr-defined]
            raise error

    def iter_content(self, chunk_size: int) -> list[bytes]:
        assert chunk_size > 0
        return [self.payload]


class _StaticSession:
    def __init__(self, response: _StaticResponse) -> None:
        self.response = response
        self.requested_url = ""

    def get(self, url: str, **_: object) -> _StaticResponse:
        self.requested_url = url
        return self.response


def test_field_ritter_access_writes_hash_bound_manifest_without_redistribution(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.xlsx"
    _write_workbook(source, _sample_rows())
    payload = source.read_bytes()
    session = _StaticSession(_StaticResponse(payload))
    destination = tmp_path / "download" / "IPO-age.xlsx"
    manifest = tmp_path / "download" / "source_manifest.csv"

    summary = download_field_ritter_ipo_workbook(
        destination,
        manifest,
        user_agent="AuroraOpenAP/1.0 research",
        session=session,
        retrieved_at="2026-08-10T10:00:00Z",
        retry_delays=(),
    )
    evidence = pd.read_csv(manifest, keep_default_na=False)

    assert session.requested_url == FIELD_RITTER_WORKBOOK_URL
    assert destination.read_bytes() == payload
    assert summary == {
        "all_downloaded": True,
        "downloaded": 1,
        "failed": 0,
        "raw_workbook_redistribution_allowed": False,
    }
    assert evidence.loc[0, "sha256"] == sha256(payload).hexdigest()
    assert evidence.loc[0, "published_at"] == "2026-01-19T16:47:15+00:00"
    assert evidence.loc[0, "access_method"] == "manual_official_static_excel"


def test_field_ritter_access_persists_concrete_http_failure(tmp_path: Path) -> None:
    destination = tmp_path / "IPO-age.xlsx"
    manifest = tmp_path / "source_manifest.csv"

    summary = download_field_ritter_ipo_workbook(
        destination,
        manifest,
        user_agent="AuroraOpenAP/1.0 research",
        session=_StaticSession(_StaticResponse(b"blocked", status_code=403)),
        retrieved_at="2026-08-10T10:00:00Z",
        retry_delays=(),
    )
    evidence = pd.read_csv(manifest, keep_default_na=False)

    assert summary["all_downloaded"] is False
    assert summary["failed"] == 1
    assert not destination.exists()
    assert evidence.loc[0, "status"] == "failed"
    assert evidence.loc[0, "http_status"] == 403
    assert evidence.loc[0, "failure_reason"] == "http_403_after_1_attempts"


def _status(ticker: str = "AAPL", cik: int = 320193) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"cik": cik, "symbol": ticker, "surface": surface, "status": "ok"}
            for surface in ("companyfacts", "submissions")
        ]
    )


def _companyfacts_name(
    name: str = "Apple Inc.",
    cik: int = 320193,
) -> pd.DataFrame:
    return pd.DataFrame([{"cik": cik, "entity_name": name}])


def _openfigi_mapping(
    *,
    ticker: str = "AAPL",
    figis: tuple[str, ...] = ("BBG000B9XRY4",),
    exchange: str = "US",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cusip": "037833100",
                "ticker": ticker,
                "mapping_status": "mapped_unique",
                "candidates_json": json.dumps(
                    [
                        {
                            "ticker": ticker,
                            "name": "Apple Inc",
                            "marketSector": "Equity",
                            "securityType2": "Common Stock",
                            "exchCode": exchange,
                            "shareClassFIGI": figi,
                        }
                        for figi in figis
                    ]
                ),
            }
        ]
    )


def _normalized_apple_ipo() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_row": 2,
                "ipo_offer_date": pd.Timestamp("1980-12-12").date(),
                "company_name": "APPLE INC",
                "ticker": "AAPL",
                "cusip": "037833100",
                "permno": 14593,
                "founding_year": 1976,
                "source_available_at": pd.Timestamp(
                    "2026-01-19T16:47:15Z"
                ),
                "source_retrieved_at": pd.Timestamp(
                    "2026-08-10T10:00:00Z"
                ),
                "source_url": FIELD_RITTER_WORKBOOK_URL,
                "documentation_url": FIELD_RITTER_DOCUMENTATION_URL,
                "transport_sha256": "a" * 64,
                "openap_first_permno": True,
            }
        ]
    )


def test_identity_requires_cusip_openfigi_ticker_and_sec_name_agreement() -> None:
    linked, rejected = build_field_ritter_current_identity(
        _normalized_apple_ipo(),
        _openfigi_mapping(),
        _companyfacts_name(),
        _status(),
        formation_at=FORMATION_AT,
        identity_available_at="2026-08-09T20:00:00Z",
    )

    assert rejected.empty
    assert linked[
        ["security_id", "ticker", "cik", "permno", "share_class_figi"]
    ].to_dict(orient="records") == [
        {
            "security_id": "US-SEC-0000320193-AAPL",
            "ticker": "AAPL",
            "cik": "0000320193",
            "permno": 14593,
            "share_class_figi": "BBG000B9XRY4",
        }
    ]
    assert linked["identity_quality"].eq(
        "field_ritter_cusip_openfigi_sec_ticker_name_current_bridge"
    ).all()
    assert not linked["historical_ticker_interval_verified"].any()
    assert not linked["strict_score_eligible"].any()


@pytest.mark.parametrize(
    ("mapping", "companyfacts", "reason"),
    [
        (
            _openfigi_mapping(figis=("BBG000B9XRY4", "BBG000B9XRY5")),
            _companyfacts_name(),
            "openfigi_mapping_not_unique_us_common_stock",
        ),
        (
            _openfigi_mapping(),
            _companyfacts_name("Unrelated Issuer Inc"),
            "field_ritter_and_sec_issuer_name_disagree",
        ),
        (
            _openfigi_mapping(ticker="APPL"),
            _companyfacts_name(),
            "field_ritter_and_openfigi_ticker_disagree",
        ),
    ],
)
def test_identity_fails_closed_instead_of_joining_by_ticker_alone(
    mapping: pd.DataFrame,
    companyfacts: pd.DataFrame,
    reason: str,
) -> None:
    linked, rejected = build_field_ritter_current_identity(
        _normalized_apple_ipo(),
        mapping,
        companyfacts,
        _status(),
        formation_at=FORMATION_AT,
        identity_available_at="2026-08-09T20:00:00Z",
    )

    assert linked.empty
    assert rejected["reason_if_rejected"].tolist() == [reason]


def _rd_fact(
    *,
    value: float,
    available_at: str,
    accession: str,
    filed: str | None = None,
) -> dict[str, object]:
    return {
        "cik": 320193,
        "taxonomy": "us-gaap",
        "tag": "ResearchAndDevelopmentExpense",
        "unit": "USD",
        "value": value,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "form": "10-K",
        "filed": filed or available_at,
        "available_at": available_at,
        "accession_number": accession,
        "fy": 2025,
        "fp": "FY",
    }


def test_sec_rd_extractor_uses_explicit_latest_causal_annual_fact_only() -> None:
    facts = pd.DataFrame(
        [
            _rd_fact(
                value=0.0,
                available_at="2026-02-01T12:00:00Z",
                accession="0000320193-26-000001",
            ),
            _rd_fact(
                value=50.0,
                available_at="2026-08-11T12:00:00Z",
                accession="0000320193-26-000002",
            ),
            _rd_fact(
                value=25.0,
                available_at="2026-08-01T12:00:00Z",
                filed="2026-08-11T12:00:00Z",
                accession="0000320193-26-000003",
            ),
            _rd_fact(
                value=25.0,
                available_at="2026-08-02T12:00:00Z",
                accession="",
            ),
        ]
    )

    result = extract_causal_sec_rd_expense(
        facts,
        _status(),
        formation_at=FORMATION_AT,
    )

    assert result[["security_id", "rd_expense", "accession_number"]].to_dict(
        orient="records"
    ) == [
        {
            "security_id": "US-SEC-0000320193-AAPL",
            "rd_expense": 0.0,
            "accession_number": "0000320193-26-000001",
        }
    ]
    assert result["explicit_zero"].tolist() == [True]


def _current_identity(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "security_id": f"US-SEC-{index:010d}-T{index:04d}",
                "ticker": f"T{index:04d}",
                "cik": f"{index:010d}",
            }
            for index in range(1, count + 1)
        ]
    )


def _linked_recent_ipos(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "security_id": f"US-SEC-{index:010d}-T{index:04d}",
                "ticker": f"T{index:04d}",
                "cik": f"{index:010d}",
                "permno": 10000 + index,
                "ipo_offer_date": pd.Timestamp("2024-01-15").date(),
                "founding_year": 2000,
                "cusip": f"00000{index:04d}"[-9:],
                "share_class_figi": f"BBG{index:09d}",
                "source_available_at": pd.Timestamp(
                    "2026-01-19T16:47:15Z"
                ),
                "identity_available_at": pd.Timestamp(
                    "2026-08-09T20:00:00Z"
                ),
                "source_url": FIELD_RITTER_WORKBOOK_URL,
                "documentation_url": FIELD_RITTER_DOCUMENTATION_URL,
                "transport_sha256": "a" * 64,
                "identity_quality": (
                    "field_ritter_cusip_openfigi_sec_ticker_name_current_bridge"
                ),
                "historical_ticker_interval_verified": False,
                "strict_score_eligible": False,
            }
            for index in range(1, count + 1)
        ]
    )


def test_ipo_signals_apply_official_windows_age_cohort_and_explicit_rd_zero() -> None:
    current = _current_identity(100)
    linked = _linked_recent_ipos(100)
    rd = pd.DataFrame(
        [
            {
                "security_id": current.loc[index, "security_id"],
                "rd_expense": value,
                "period_end": pd.Timestamp("2025-12-31T00:00:00Z"),
                "filed_at": pd.Timestamp("2026-02-01T12:00:00Z"),
                "available_at": pd.Timestamp("2026-02-01T12:00:00Z"),
                "accession_number": f"accession-{index}",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{index + 1:010d}.json"
                ),
                "explicit_zero": value == 0.0,
            }
            for index, value in ((0, 0.0), (1, 50.0))
        ]
    )

    values = calculate_field_ritter_ipo_signals(
        current,
        linked,
        rd,
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T10:00:00Z",
    )
    by_key = values.set_index(["security_id", "signal"])
    first = current.loc[0, "security_id"]
    second = current.loc[1, "security_id"]
    third = current.loc[2, "security_id"]

    assert len(values) == 300
    assert by_key.loc[(first, "AgeIPO"), "value"] == 26.0
    assert by_key.loc[(first, "IndIPO"), "value"] == 1.0
    assert by_key.loc[(first, "RDIPO"), "value"] == 1.0
    assert by_key.loc[(second, "RDIPO"), "value"] == 0.0
    assert np.isnan(by_key.loc[(third, "RDIPO"), "value"])
    assert by_key.loc[(third, "RDIPO"), "reason_if_missing"] == (
        "explicit_sec_rd_expense_missing"
    )
    assert values.loc[values["signal"].eq("AgeIPO"), "observation_count"].eq(
        100
    ).all()
    assert values["fidelity_class"].isin({"reconstructed", "unavailable"}).all()
    assert not values["strict_score_eligible"].any()


def test_ipo_signals_do_not_turn_incomplete_ipo_coverage_into_zero() -> None:
    current = _current_identity(100)
    linked = _linked_recent_ipos(99)

    values = calculate_field_ritter_ipo_signals(
        current,
        linked,
        pd.DataFrame(
            columns=[
                "security_id",
                "rd_expense",
                "period_end",
                "filed_at",
                "available_at",
                "accession_number",
                "source_url",
                "explicit_zero",
            ]
        ),
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T10:00:00Z",
    )
    unmatched = current.iloc[-1]["security_id"]
    by_key = values.set_index(["security_id", "signal"])

    assert values.loc[values["signal"].eq("AgeIPO"), "value"].isna().all()
    assert by_key.loc[(current.iloc[0]["security_id"], "AgeIPO"), "reason_if_missing"] == (
        "confirmed_recent_ipo_cohort_below_100"
    )
    assert np.isnan(by_key.loc[(unmatched, "IndIPO"), "value"])
    assert by_key.loc[(unmatched, "IndIPO"), "reason_if_missing"] == (
        "ipo_identity_not_corroborated"
    )


def test_field_ritter_runner_is_guarded_hash_bound_and_non_strict() -> None:
    runner = (
        ROOT / "scripts" / "run_openap_149_field_ritter_ipo.py"
    ).read_text(encoding="utf-8")

    assert "require_github_actions_or_explicit_local_permission" in runner
    assert "load_field_ritter_ipo_workbook" in runner
    assert "build_field_ritter_current_identity" in runner
    assert "calculate_field_ritter_ipo_signals" in runner
    assert "_sec_source_contract" in runner
    assert '"sec_source_evidence": sec_source_evidence' in runner
    assert '"status_rows": status_rows' in runner
    assert 'status["status"].eq("ok").all()' in runner
    assert 'values == {"companyfacts", "submissions"}' in runner
    assert '"formula_source_run_id"' in runner
    assert '"ticker_only_join_allowed": False' in runner
    assert '"field_ritter_raw_workbook_in_output": False' in runner
    assert '"strict_score_eligible": False' in runner
    assert "requests.get" not in runner
    assert "urlopen(" not in runner

    access_runner = (
        ROOT / "scripts" / "run_openap_149_field_ritter_access.py"
    ).read_text(encoding="utf-8")
    assert "require_github_actions_or_explicit_local_permission" in access_runner
    assert "base_data_dir" in access_runner
    assert "download_field_ritter_ipo_workbook" in access_runner
    assert "requested_output.is_absolute()" in access_runner

    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-field-ritter-ipo.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "AU_DATA_DIR:" in workflow
    assert "--formula-source-run-id" in workflow
    assert "field_ritter_source_manifest.csv" in workflow
    assert "IPO-age.xlsx" in workflow
    assert "raw_workbook_redistribution_allowed" in workflow
    assert "openap-149-field-ritter-ipo-current" in workflow
