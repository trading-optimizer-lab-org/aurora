from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import pytest

from aurora.research.openap_181.sec_notes_listing_inputs import (
    load_sec_notes_listing_facts,
    load_sec_notes_listing_history,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_notes_archive(path: Path) -> None:
    submissions = pd.DataFrame(
        [
            {
                "adsh": "0000320193-25-000079",
                "cik": 320193,
                "form": "10-K",
                "accepted": "20251031100000",
                "instance": "aapl-20250927.htm",
            },
            {
                "adsh": "0000789019-25-000100",
                "cik": 789019,
                "form": "10-Q",
                "accepted": "20251030120000",
                "instance": "msft-20250930.htm",
            },
        ]
    )
    text = pd.DataFrame(
        [
            {
                "adsh": accession,
                "tag": tag,
                "version": "dei/2025",
                "context": "listing-common",
                "iprx": 1,
                "value": value,
            }
            for accession, values in (
                (
                    "0000320193-25-000079",
                    (
                        ("TradingSymbol", "AAPL"),
                        ("SecurityExchangeName", "NASDAQ"),
                        ("Security12bTitle", "Common Stock"),
                    ),
                ),
                (
                    "0000789019-25-000100",
                    (
                        ("TradingSymbol", "MSFT"),
                        ("SecurityExchangeName", "NASDAQ"),
                        ("Security12bTitle", "Common Stock"),
                    ),
                ),
            )
            for tag, value in values
        ]
    )
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("sub.txt", submissions.to_csv(sep="\t", index=False))
        archive.writestr("txt.txt", text.to_csv(sep="\t", index=False))


def _source_manifest(path: Path) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_id": "sec_notes_2026_07",
                "source_url": (
                    "https://www.sec.gov/files/dera/data/"
                    "financial-statement-notes-data-sets/2026_07_notes.zip"
                ),
                "access_url": (
                    "https://www.sec.gov/files/dera/data/"
                    "financial-statement-notes-data-sets/2026_07_notes.zip"
                ),
                "access_method": "sec_official_notes_direct_fair_access",
                "period": "2026_07",
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
                "retrieved_at": "2026-08-10T08:00:00Z",
                "status": "downloaded",
                "http_status": 200,
                "failure_reason": "",
            }
        ]
    )


def test_notes_archive_loader_filters_current_ciks_and_preserves_hash(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "2026_07_notes.zip"
    _write_notes_archive(archive)

    facts, summary = load_sec_notes_listing_facts(
        archive,
        _source_manifest(archive),
        allowed_ciks={"0000320193"},
    )

    assert len(facts) == 3
    assert facts["cik"].unique().tolist() == ["0000320193"]
    assert facts["transport_sha256"].eq(
        sha256(archive.read_bytes()).hexdigest()
    ).all()
    assert summary == {
        "archive_size_bytes": archive.stat().st_size,
        "eligible_submission_rows": 1,
        "listing_fact_rows": 3,
        "source_period": "2026_07",
        "txt_rows_scanned": 6,
    }


def test_notes_archive_loader_rejects_tampered_or_failed_source_evidence(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "2026_07_notes.zip"
    _write_notes_archive(archive)
    manifest = _source_manifest(archive)

    with pytest.raises(ValueError, match="SHA-256"):
        load_sec_notes_listing_facts(
            archive,
            manifest.assign(sha256="0" * 64),
            allowed_ciks={"0000320193"},
        )

    with pytest.raises(ValueError, match="downloaded HTTP 200"):
        load_sec_notes_listing_facts(
            archive,
            manifest.assign(status="failed", http_status=403),
            allowed_ciks={"0000320193"},
        )


def test_notes_archive_loader_rejects_nonofficial_or_mismatched_identity(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "2026_07_notes.zip"
    _write_notes_archive(archive)
    manifest = _source_manifest(archive)

    with pytest.raises(ValueError, match="exact official SEC evidence"):
        load_sec_notes_listing_facts(
            archive,
            manifest.assign(source_url="https://example.test/notes.zip"),
            allowed_ciks={"0000320193"},
        )

    with pytest.raises(ValueError, match="unique, valid SEC CIK"):
        load_sec_notes_listing_facts(
            archive,
            manifest,
            allowed_ciks={"not-a-cik"},
        )


def test_notes_history_loader_rejects_overlapping_archive_periods(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "2026_07_notes.zip"
    _write_notes_archive(archive)
    manifest = _source_manifest(archive)

    with pytest.raises(ValueError, match="periods must be unique"):
        load_sec_notes_listing_history(
            tmp_path,
            pd.concat([manifest, manifest], ignore_index=True),
            allowed_ciks={"0000320193"},
        )


def test_notes_identity_runner_and_access_workflow_remain_manual_non_strict() -> None:
    runner = (
        ROOT / "scripts" / "run_openap_149_sec_listing_identity.py"
    ).read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-sec-notes-access.yml"
    ).read_text(encoding="utf-8")
    exchange_workflow = (
        ROOT
        / ".github"
        / "workflows"
        / "openap-149-sec-exchange-switch.yml"
    ).read_text(encoding="utf-8")

    assert "require_github_actions_or_explicit_local_permission" in runner
    assert "build_current_sec_universe" in runner
    assert "validate_materialized_market_security_master_recovery" not in runner
    assert "load_sec_notes_listing_history" in runner
    assert "calculate_sec_exch_switch_current" in runner
    assert "_formula_contract" in runner
    assert "EXCH_SWITCH_FORMULA_SHA256" in runner
    assert "openap_149_sec_exch_switch_current.parquet" in runner
    assert '"historical_ticker_interval_verified": False' in runner
    assert '"market_bars_acquired": False' in runner
    assert '"signal": "ExchSwitch"' in runner
    assert '"strict_score_eligible": False' in runner
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "notes_period:" in workflow
    assert "SEC_NOTES_PERIOD: ${{ inputs.notes_period }}" in workflow
    assert "workflow_dispatch:" in exchange_workflow
    assert "push:" not in exchange_workflow
    assert "2025q3,2025q4,2026q1,2026q2,2026_07" in exchange_workflow
    assert "run_openap_149_sec_listing_identity.py" in exchange_workflow
    assert "https://www.sec.gov/files/company_tickers_exchange.json" in (
        exchange_workflow
    )
    assert "openap-149-sec-exchange-switch-current" in exchange_workflow
    assert "--formula-source-run-id" in exchange_workflow
