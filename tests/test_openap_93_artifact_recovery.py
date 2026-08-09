from __future__ import annotations

from importlib import import_module
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


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
