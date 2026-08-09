from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

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
