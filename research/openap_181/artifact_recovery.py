"""Selective recovery helpers for large GitHub Actions ZIP artifacts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from hashlib import sha256
from io import RawIOBase
from typing import Any
import json
import re
from zipfile import ZipFile


class HttpRangeReader(RawIOBase):
    """Expose an exact byte-range callback as a seekable binary reader."""

    def __init__(
        self,
        size: int,
        fetch_range: Callable[[int, int], bytes],
    ) -> None:
        super().__init__()
        if size < 0:
            raise ValueError("range reader size cannot be negative")
        self._size = int(size)
        self._fetch_range = fetch_range
        self._position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            position = offset
        elif whence == 1:
            position = self._position + offset
        elif whence == 2:
            position = self._size + offset
        else:
            raise ValueError(f"unsupported seek mode: {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self._position = int(position)
        return self._position

    def read(self, size: int = -1) -> bytes:
        if self._position >= self._size or size == 0:
            return b""
        start = self._position
        end = self._size - 1 if size is None or size < 0 else min(
            self._size - 1, start + size - 1
        )
        payload = self._fetch_range(start, end)
        expected = end - start + 1
        if len(payload) != expected:
            raise OSError(
                f"range response length mismatch: expected={expected}:actual={len(payload)}"
            )
        self._position += len(payload)
        return payload


def read_zip_members(
    reader: HttpRangeReader,
    member_names: Iterable[str],
) -> dict[str, bytes]:
    """Read exact ZIP members and reject missing or duplicate archive names."""

    requested = tuple(member_names)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("requested ZIP members must be unique and non-empty")
    with ZipFile(reader) as archive:
        names = archive.namelist()
        for member_name in requested:
            if names.count(member_name) != 1:
                raise ValueError(
                    f"expected one ZIP member {member_name}, found {names.count(member_name)}"
                )
        return {member_name: archive.read(member_name) for member_name in requested}


def validate_recovered_openap_93(
    run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
    members: Mapping[str, bytes],
) -> dict[str, Any]:
    """Validate that a failed run contains previously verified OpenAP 93 outputs."""

    run_id = int(run.get("id", 0))
    head_sha = str(run.get("head_sha", ""))
    if (
        run_id <= 0
        or run.get("status") != "completed"
        or run.get("conclusion") != "failure"
        or re.fullmatch(r"[0-9a-fA-F]{40}", head_sha) is None
    ):
        raise ValueError("source run is not a completed failed run with a pinned SHA")

    pipeline_jobs = [job for job in jobs if job.get("name") == "full_pipeline"]
    if len(pipeline_jobs) != 1:
        raise ValueError("expected one full_pipeline source job")
    steps = {
        str(step.get("name", "")): str(step.get("conclusion", ""))
        for step in pipeline_jobs[0].get("steps", [])
    }
    required_successes = {
        "Verify mandatory deliverables and contracts",
        "Independently reopen and verify the complete artifact",
    }
    if any(steps.get(name) != "success" for name in required_successes):
        raise ValueError("source run lacks successful verified output steps")
    audit_step = "Build the canonical fail-closed 181-signal completion audit"
    if steps.get(audit_step) != "failure":
        raise ValueError("source run did not fail only at the later completion audit")

    artifact_id = int(artifact.get("id", 0))
    expected_name = f"openap-93-max-free-failed-output-{run_id}"
    if (
        artifact_id <= 0
        or artifact.get("name") != expected_name
        or artifact.get("expired") is not False
        or int(artifact.get("size_in_bytes", 0)) <= 0
    ):
        raise ValueError("source diagnostic artifact identity is invalid")

    required_members = {
        "coverage_93.csv",
        "signals_93_current.csv",
        "run_manifest.json",
    }
    missing = required_members.difference(members)
    if missing:
        raise ValueError(f"recovered artifact members missing: {sorted(missing)}")
    try:
        manifest = json.loads(members["run_manifest.json"])
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("recovered run manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("recovered run manifest must be a JSON object")
    output_hashes = manifest.get("output_hashes", {})
    if not isinstance(output_hashes, dict):
        raise ValueError("recovered run manifest output hashes are invalid")
    for member_name in ("coverage_93.csv", "signals_93_current.csv"):
        actual = sha256(members[member_name]).hexdigest()
        if output_hashes.get(member_name) != actual:
            raise ValueError(f"recovered member hash mismatch: {member_name}")
    if (
        manifest.get("input_signals") != 93
        or manifest.get("locked_opened") is not False
        or manifest.get("validation_used_for_selection") is not False
        or manifest.get("cost_eur") != 0
    ):
        raise ValueError("recovered OpenAP 93 safety contract is invalid")

    return {
        "source_run_id": run_id,
        "source_head_sha": head_sha.lower(),
        "source_artifact_id": artifact_id,
        "source_artifact_name": expected_name,
        "source_artifact_size_bytes": int(artifact["size_in_bytes"]),
        "input_signals": 93,
        "current_usable_signal_count": int(
            manifest.get("current_usable_signal_count", 0)
        ),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
        "recovered_hashes": {
            name: sha256(members[name]).hexdigest()
            for name in sorted(required_members)
        },
    }


__all__ = [
    "HttpRangeReader",
    "read_zip_members",
    "validate_recovered_openap_93",
]
