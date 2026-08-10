from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pandas as pd
import pytest


def _module():
    return import_module("aurora.research.openap_181.artifact_recovery")


def _archive_payload() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("padding.bin", b"x" * 200_000, compress_type=ZIP_STORED)
        archive.writestr(
            "signals_93_current.csv",
            b"security_id,signal,value\ncik:1,DelBreadth,0.25\n",
            compress_type=ZIP_DEFLATED,
        )
        archive.writestr(
            "run_manifest.json",
            b'{"locked_opened": false, "validation_used_for_selection": false}',
            compress_type=ZIP_DEFLATED,
        )
    return buffer.getvalue()


def test_remote_range_reader_recovers_only_requested_zip_members() -> None:
    module = _module()
    payload = _archive_payload()
    ranges: list[tuple[int, int]] = []

    def fetch_range(start: int, end: int) -> bytes:
        ranges.append((start, end))
        return payload[start : end + 1]

    reader = module.HttpRangeReader(len(payload), fetch_range)
    recovered = module.read_zip_members(
        reader,
        ("signals_93_current.csv", "run_manifest.json"),
    )

    assert recovered["signals_93_current.csv"].startswith(b"security_id,signal")
    assert b'"locked_opened": false' in recovered["run_manifest.json"]
    assert ranges
    assert all(0 <= start <= end < len(payload) for start, end in ranges)
    assert sum(end - start + 1 for start, end in ranges) < len(payload)


def test_remote_range_reader_inspects_declared_member_sizes_before_download() -> None:
    module = _module()
    payload = _archive_payload()
    ranges: list[tuple[int, int]] = []

    def fetch_range(start: int, end: int) -> bytes:
        ranges.append((start, end))
        return payload[start : end + 1]

    reader = module.HttpRangeReader(len(payload), fetch_range)
    inspected = module.inspect_zip_members(
        reader,
        ("signals_93_current.csv", "run_manifest.json"),
    )

    assert set(inspected) == {"signals_93_current.csv", "run_manifest.json"}
    assert inspected["signals_93_current.csv"]["file_size"] > 0
    assert inspected["signals_93_current.csv"]["compress_size"] > 0
    assert reader.bytes_fetched < len(payload)
    assert ranges


def test_recovery_requires_verified_outputs_and_matching_manifest_hashes() -> None:
    module = _module()
    coverage = b"signal,non_null_count\nDelBreadth,10\n"
    signals = b"security_id,signal,value\ncik:1,DelBreadth,0.25\n"
    manifest = json.dumps(
        {
            "input_signals": 93,
            "current_usable_signal_count": 34,
            "locked_opened": False,
            "validation_used_for_selection": False,
            "cost_eur": 0,
            "output_hashes": {
                "coverage_93.csv": sha256(coverage).hexdigest(),
                "signals_93_current.csv": sha256(signals).hexdigest(),
            },
        }
    ).encode()
    members = {
        "coverage_93.csv": coverage,
        "signals_93_current.csv": signals,
        "run_manifest.json": manifest,
    }
    run = {
        "id": 123,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": "a" * 40,
    }
    artifact = {
        "id": 456,
        "name": "openap-93-max-free-failed-output-123",
        "expired": False,
        "size_in_bytes": 2_000_000,
    }
    jobs = [
        {
            "name": "full_pipeline",
            "steps": [
                {
                    "name": "Verify mandatory deliverables and contracts",
                    "conclusion": "success",
                },
                {
                    "name": "Independently reopen and verify the complete artifact",
                    "conclusion": "success",
                },
                {
                    "name": "Build the canonical fail-closed 181-signal completion audit",
                    "conclusion": "failure",
                },
            ],
        }
    ]

    verified = module.validate_recovered_openap_93(run, jobs, artifact, members)

    assert verified["source_run_id"] == 123
    assert verified["source_artifact_id"] == 456
    assert verified["current_usable_signal_count"] == 34
    assert verified["locked_opened"] is False
    assert verified["validation_used_for_selection"] is False

    jobs[0]["steps"][1]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="verified output steps"):
        module.validate_recovered_openap_93(run, jobs, artifact, members)


def test_institutional_recovery_requires_three_hash_bound_normalized_inputs() -> None:
    module = _module()
    filings = b"PAR1-filings"
    holdings = b"PAR1-holdings"
    mapping = b"PAR1-mapping"
    member_payloads = {
        "public_inputs/normalized/sec_13f_filings.parquet": filings,
        "public_inputs/normalized/sec_13f_holdings.parquet": holdings,
        "public_inputs/normalized/openfigi_cusip_map.parquet": mapping,
    }
    manifest = json.dumps(
        {
            "input_signals": 93,
            "locked_opened": False,
            "validation_used_for_selection": False,
            "cost_eur": 0,
            "public_input_row_counts": {
                "sec_13f_filings": 26_709,
                "sec_13f_holdings": 6_975_953,
                "openfigi_cusip_map": 29_103,
            },
            "institutional_inputs": {
                "mapped_holding_rows": 4_182_960,
                "latest_report_period": "2026-03-31T00:00:00",
                "latest_filing_date": "2026-05-29T00:00:00",
            },
            "output_hashes": {
                name: sha256(payload).hexdigest()
                for name, payload in member_payloads.items()
            },
        }
    ).encode()
    members = {**member_payloads, "run_manifest.json": manifest}
    run = {
        "id": 123,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": "a" * 40,
    }
    artifact = {
        "id": 456,
        "name": "openap-93-max-free-failed-output-123",
        "expired": False,
        "size_in_bytes": 2_000_000,
    }
    jobs = [
        {
            "name": "full_pipeline",
            "steps": [
                {
                    "name": "Verify mandatory deliverables and contracts",
                    "conclusion": "success",
                },
                {
                    "name": "Independently reopen and verify the complete artifact",
                    "conclusion": "success",
                },
                {
                    "name": "Build the canonical fail-closed 181-signal completion audit",
                    "conclusion": "failure",
                },
            ],
        }
    ]

    verified = module.validate_recovered_openap_93_institutional_inputs(
        run, jobs, artifact, members
    )

    assert verified["source_run_id"] == 123
    assert verified["sec_13f_holding_rows"] == 6_975_953
    assert verified["mapped_holding_rows"] == 4_182_960
    assert verified["latest_report_period"] == "2026-03-31T00:00:00"

    members["public_inputs/normalized/sec_13f_holdings.parquet"] += b"tampered"
    with pytest.raises(ValueError, match="hash mismatch"):
        module.validate_recovered_openap_93_institutional_inputs(
            run, jobs, artifact, members
        )


def test_market_security_master_recovery_requires_success_and_safe_summary() -> None:
    module = _module()
    security_master = pd.DataFrame(
        [
            {
                "security_id": "US-SEC-0000320193-AAPL",
                "symbol": "AAPL",
                "cik": 320193,
                "exchange_sec": "Nasdaq",
                "eligible_common_stock": True,
                "issuer_primary_security": True,
                "issuer_share_class_count": 1,
                "ranking_eligible": True,
                "source_sec": "sec_company_tickers_exchange",
                "retrieved_at_sec": "2026-08-07T20:06:32Z",
            }
        ]
    )
    parquet = BytesIO()
    security_master.to_parquet(parquet, index=False)
    source_manifest = pd.DataFrame(
        [
            {
                "source": "company_tickers_exchange.json",
                "source_url": (
                    "https://www.sec.gov/files/company_tickers_exchange.json"
                ),
                "source_mode": "sec_official_live",
                "sha256": "a" * 64,
                "role": "ticker_cik_universe",
            }
        ]
    ).to_csv(index=False).encode("utf-8")
    summary = json.dumps(
        {
            "eligible_symbols": 2157,
            "security_master_rows": 1,
            "locked_opened": False,
            "backtest_enabled": False,
            "validation_used_for_selection": False,
            "partial": False,
            "database_contract_violations": 0,
        }
    ).encode()
    members = {
        "security_master.parquet": parquet.getvalue(),
        "execution_summary.json": summary,
        "source_manifest.csv": source_manifest,
    }
    run = {
        "id": 31270341796,
        "status": "completed",
        "conclusion": "success",
        "head_sha": "b" * 40,
    }
    artifact = {
        "id": 999,
        "name": "openap-yfinance-sec-current-score-results",
        "expired": False,
        "size_in_bytes": 1_000_000_000,
    }
    jobs = [
        {
            "name": "merge",
            "conclusion": "success",
            "steps": [
                {
                    "name": "Merge lake and calculate current scores",
                    "conclusion": "success",
                },
                {
                    "name": "Validate final acceptance contract",
                    "conclusion": "success",
                },
            ],
        }
    ]

    verified = module.validate_recovered_market_security_master(
        run, jobs, artifact, members
    )

    assert verified["source_run_id"] == 31270341796
    assert verified["source_head_sha"] == "b" * 40
    assert verified["security_master_rows"] == 1
    assert verified["eligible_symbols"] == 2157
    assert verified["identity_source_url"] == (
        "https://www.sec.gov/files/company_tickers_exchange.json"
    )
    assert verified["recovered_hashes"]["security_master.parquet"] == sha256(
        parquet.getvalue()
    ).hexdigest()

    jobs[0]["steps"][1]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="acceptance steps"):
        module.validate_recovered_market_security_master(
            run, jobs, artifact, members
        )

    jobs[0]["steps"][1]["conclusion"] = "success"
    fallback_manifest = pd.DataFrame(
        [
            {
                "source": "sec_cik_mapper_mappings.csv",
                "source_url": "https://raw.githubusercontent.com/example/fallback.csv",
                "source_mode": "pinned_sec_derived_fallback",
                "sha256": "c" * 64,
                "role": "ticker_cik_universe",
            }
        ]
    ).to_csv(index=False).encode("utf-8")
    with pytest.raises(ValueError, match="official SEC ticker source"):
        module.validate_recovered_market_security_master(
            run,
            jobs,
            artifact,
            {**members, "source_manifest.csv": fallback_manifest},
        )
