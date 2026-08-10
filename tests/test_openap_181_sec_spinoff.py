from __future__ import annotations

from pathlib import Path

import pandas as pd

from aurora.research.openap_181.sec_spinoff import (
    SPINOFF_FORMULA_SHA256,
    calculate_sec_spinoff_current,
    detect_sec_spinoff_completion_date,
    extract_sec_spinoff_completion_evidence,
    select_sec_spinoff_filing_candidates,
)
from aurora.research.openap_181.sec_spinoff_access import (
    download_sec_spinoff_candidate_documents,
)


ROOT = Path(__file__).resolve().parents[1]
FORMATION_AT = "2026-08-09T23:59:59Z"


def _current_universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000000001-SPIN",
                "ticker": "SPIN",
                "cik": "0000000001",
                "exchange_family": "NYSE",
                "issuer_share_class_count": 1,
                "identity_available_at": "2026-08-07T20:06:32Z",
                "identity_source_url": (
                    "https://www.sec.gov/files/company_tickers_exchange.json"
                ),
            },
            {
                "security_id": "US-SEC-0000000002-PLAIN",
                "ticker": "PLAIN",
                "cik": "0000000002",
                "exchange_family": "NASDAQ",
                "issuer_share_class_count": 1,
                "identity_available_at": "2026-08-07T20:06:32Z",
                "identity_source_url": (
                    "https://www.sec.gov/files/company_tickers_exchange.json"
                ),
            },
        ]
    )


def _submission(
    *,
    cik: int = 1,
    accession: str,
    accepted_at: str,
    form: str,
    primary_document: str,
) -> dict[str, object]:
    return {
        "cik": cik,
        "accession_number": accession,
        "accepted_at": accepted_at,
        "filing_date": accepted_at[:10],
        "form": form,
        "primary_document": primary_document,
        "source": "sec_submissions_bulk",
    }


def test_spinoff_candidates_require_causal_initial_form_10() -> None:
    submissions = pd.DataFrame(
        [
            _submission(
                accession="0000000001-25-000001",
                accepted_at="2025-04-01T12:00:00Z",
                form="10-12B",
                primary_document="spin-20250401.htm",
            ),
            _submission(
                accession="0000000001-25-000002",
                accepted_at="2025-07-15T12:00:00Z",
                form="10-Q",
                primary_document="spin-20250630.htm",
            ),
            _submission(
                accession="0000000001-26-000003",
                accepted_at="2026-08-10T12:00:00Z",
                form="8-K",
                primary_document="future.htm",
            ),
            _submission(
                cik=2,
                accession="0000000002-25-000001",
                accepted_at="2025-04-01T12:00:00Z",
                form="10-K",
                primary_document="plain.htm",
            ),
        ]
    )

    candidates = select_sec_spinoff_filing_candidates(
        submissions,
        _current_universe(),
        formation_at=FORMATION_AT,
    )

    assert candidates["accession_number"].tolist() == [
        "0000000001-25-000001",
        "0000000001-25-000002",
    ]
    assert candidates["source_url"].tolist() == [
        (
            "https://www.sec.gov/Archives/edgar/data/1/"
            "000000000125000001/spin-20250401.htm"
        ),
        (
            "https://www.sec.gov/Archives/edgar/data/1/"
            "000000000125000002/spin-20250630.htm"
        ),
    ]
    assert candidates["security_id"].eq("US-SEC-0000000001-SPIN").all()


def test_completion_detector_rejects_plans_and_requires_completed_event_date() -> None:
    assert detect_sec_spinoff_completion_date(
        "The proposed spin-off may not be completed on the expected terms."
    ) is None
    assert detect_sec_spinoff_completion_date(
        "On May 15, 2025, Parent completed the spin-off of Child as an "
        "independent publicly traded company."
    ) == pd.Timestamp("2025-05-15").date()
    assert detect_sec_spinoff_completion_date(
        "<p>The spin-off was completed on 2025-05-15 through a pro rata "
        "distribution of common stock.</p>"
    ) == pd.Timestamp("2025-05-15").date()


def test_completion_evidence_is_causal_hashed_and_fail_closed() -> None:
    candidates = pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000000001-SPIN",
                "ticker": "SPIN",
                "cik": "0000000001",
                "accession_number": "0000000001-25-000001",
                "accepted_at": "2025-04-01T12:00:00Z",
                "form": "10-12B",
                "primary_document": "spin-20250401.htm",
                "source_url": (
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    "000000000125000001/spin-20250401.htm"
                ),
                "retrieved_at": "2026-08-10T10:00:00Z",
                "transport_sha256": "a" * 64,
                "document_text": "The proposed spin-off remains subject to approval.",
            },
            {
                "security_id": "US-SEC-0000000001-SPIN",
                "ticker": "SPIN",
                "cik": "0000000001",
                "accession_number": "0000000001-25-000002",
                "accepted_at": "2025-07-15T12:00:00Z",
                "form": "10-Q",
                "primary_document": "spin-20250630.htm",
                "source_url": (
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    "000000000125000002/spin-20250630.htm"
                ),
                "retrieved_at": "2026-08-10T10:00:00Z",
                "transport_sha256": "b" * 64,
                "document_text": (
                    "On May 15, 2025, Parent completed the spin-off of Child "
                    "as an independent publicly traded company."
                ),
            },
            {
                "security_id": "US-SEC-0000000001-SPIN",
                "ticker": "SPIN",
                "cik": "0000000001",
                "accession_number": "0000000001-26-000003",
                "accepted_at": "2026-08-10T12:00:00Z",
                "form": "8-K",
                "primary_document": "future.htm",
                "source_url": (
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    "000000000126000003/future.htm"
                ),
                "retrieved_at": "2026-08-10T13:00:00Z",
                "transport_sha256": "c" * 64,
                "document_text": (
                    "On August 10, 2026, Parent completed the spin-off of Child."
                ),
            },
        ]
    )

    evidence = extract_sec_spinoff_completion_evidence(
        candidates,
        formation_at=FORMATION_AT,
    )

    assert len(evidence) == 1
    assert evidence.loc[0, "event_date"] == pd.Timestamp("2025-05-15").date()
    assert evidence.loc[0, "transport_sha256"] == "b" * 64
    assert evidence.loc[0, "evidence_quality"] == (
        "sec_filing_explicit_completed_spinoff_with_event_date"
    )


class _StaticResponse:
    def __init__(self, payload: bytes) -> None:
        self.status_code = 200
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.content = payload

    def __enter__(self) -> _StaticResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None


class _StaticSession:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: tuple[int, int],
    ) -> _StaticResponse:
        assert "User-Agent" in headers
        assert timeout == (30, 180)
        self.urls.append(url)
        return _StaticResponse(self.payload)


def test_sec_spinoff_access_is_bounded_and_retains_no_raw_document() -> None:
    candidates = pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000000001-SPIN",
                "ticker": "SPIN",
                "cik": "0000000001",
                "accession_number": "0000000001-25-000002",
                "accepted_at": "2025-07-15T12:00:00Z",
                "form": "10-Q",
                "primary_document": "spin-20250630.htm",
                "source_url": (
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    "000000000125000002/spin-20250630.htm"
                ),
            }
        ]
    )
    session = _StaticSession(
        b"<p>On May 15, 2025, Parent completed the spin-off of Child as an "
        b"independent publicly traded company.</p>"
    )

    documents, evidence, manifest, summary = (
        download_sec_spinoff_candidate_documents(
            candidates,
            formation_at=FORMATION_AT,
            user_agent="Aurora Research research@example.com",
            session=session,
            retrieved_at="2026-08-10T10:00:00Z",
            retry_delays=(),
            request_interval_seconds=0.1,
        )
    )

    assert len(documents) == 1
    assert len(evidence) == 1
    assert manifest.loc[0, "status"] == "downloaded"
    assert manifest.loc[0, "completion_evidence_detected"]
    assert summary["all_downloaded"] is True
    assert summary["raw_filing_documents_retained"] is False
    assert "document_text" not in manifest.columns
    assert session.urls == candidates["source_url"].tolist()


def test_spinoff_current_uses_proven_event_age_and_never_promotes_strict() -> None:
    evidence = pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000000001-SPIN",
                "ticker": "SPIN",
                "cik": "0000000001",
                "accession_number": "0000000001-25-000002",
                "accepted_at": "2025-07-15T12:00:00Z",
                "event_date": "2025-05-15",
                "source_url": (
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    "000000000125000002/spin-20250630.htm"
                ),
                "retrieved_at": "2026-08-10T10:00:00Z",
                "transport_sha256": "b" * 64,
                "evidence_quality": (
                    "sec_filing_explicit_completed_spinoff_with_event_date"
                ),
            }
        ]
    )

    result = calculate_sec_spinoff_current(
        evidence,
        _current_universe(),
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T10:00:00Z",
    )
    by_ticker = result.set_index("ticker")

    assert by_ticker.loc["SPIN", "value"] == 1.0
    assert by_ticker.loc["SPIN", "current_usable"]
    assert by_ticker.loc["SPIN", "event_age_months"] == 15
    assert by_ticker.loc["SPIN", "formula_sha256"] == SPINOFF_FORMULA_SHA256
    assert not by_ticker.loc["SPIN", "strict_score_eligible"]
    assert pd.isna(by_ticker.loc["PLAIN", "value"])
    assert by_ticker.loc["PLAIN", "reason_if_missing"] == (
        "completed_spinoff_event_not_proven"
    )

    older = evidence.copy()
    older.loc[0, "event_date"] = "2024-06-15"
    older.loc[0, "accepted_at"] = "2024-07-15T12:00:00Z"
    old_result = calculate_sec_spinoff_current(
        older,
        _current_universe().iloc[[0]].copy(),
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T10:00:00Z",
    )
    assert old_result.loc[0, "event_age_months"] == 26
    assert old_result.loc[0, "value"] == 0.0


def test_spinoff_current_fails_closed_for_invalid_event_date() -> None:
    evidence = pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000000001-SPIN",
                "ticker": "SPIN",
                "cik": "0000000001",
                "accession_number": "0000000001-25-000002",
                "accepted_at": "2025-07-15T12:00:00Z",
                "event_date": "not-a-date",
                "source_url": (
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    "000000000125000002/spin-20250630.htm"
                ),
                "retrieved_at": "2026-08-10T10:00:00Z",
                "transport_sha256": "b" * 64,
                "evidence_quality": (
                    "sec_filing_explicit_completed_spinoff_with_event_date"
                ),
            }
        ]
    )

    result = calculate_sec_spinoff_current(
        evidence,
        _current_universe().iloc[[0]].copy(),
        formation_at=FORMATION_AT,
        retrieved_at="2026-08-10T10:00:00Z",
    )

    assert pd.isna(result.loc[0, "value"])
    assert result.loc[0, "reason_if_missing"] == (
        "completed_spinoff_event_not_proven"
    )


def test_spinoff_runner_and_workflow_are_manual_guarded_and_non_strict() -> None:
    runner = (
        ROOT / "scripts" / "run_openap_149_sec_spinoff.py"
    ).read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-sec-spinoff.yml"
    ).read_text(encoding="utf-8")

    assert "require_github_actions_or_explicit_local_permission" in runner
    assert "SPINOFF_FORMULA_SHA256" in runner
    assert "select_sec_spinoff_filing_candidates" in runner
    assert "download_sec_spinoff_candidate_documents" in runner
    assert "calculate_sec_spinoff_current" in runner
    assert '"strict_score_eligible": False' in runner
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "AU_DATA_DIR:" in workflow
    assert "--formula-source-run-id" in workflow
    assert "openap-149-sec-spinoff-current" in workflow
