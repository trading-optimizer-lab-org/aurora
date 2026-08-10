"""Bounded one-file access to the official Field-Ritter IPO workbook."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import hashlib
import os
from pathlib import Path
import time
from typing import Any
import urllib.request

import pandas as pd

from .field_ritter_ipo import (
    FIELD_RITTER_ACCESS_METHOD,
    FIELD_RITTER_DOCUMENTATION_URL,
    FIELD_RITTER_SOURCE_ID,
    FIELD_RITTER_WORKBOOK_URL,
)


FIELD_RITTER_SOURCE_MANIFEST_COLUMNS = (
    "source_id",
    "source_url",
    "documentation_url",
    "access_url",
    "access_method",
    "published_at",
    "retrieved_at",
    "sha256",
    "size_bytes",
    "status",
    "http_status",
    "failure_reason",
)

_EXPECTED_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_MAX_WORKBOOK_BYTES = 16 * 1024**2


class _UrllibResponse:
    """Small requests-like wrapper around a stdlib HTTP response."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.status_code = int(response.status)
        self.headers = response.headers

    def __enter__(self) -> _UrllibResponse:
        return self

    def __exit__(self, *_: object) -> None:
        self._response.close()

    def raise_for_status(self) -> None:
        # urllib raises HTTPError before returning non-success responses.
        return None

    def iter_content(self, chunk_size: int) -> Any:
        while True:
            chunk = self._response.read(chunk_size)
            if not chunk:
                break
            yield chunk


class _UrllibSession:
    """Bounded stdlib transport with the subset used by this downloader."""

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        allow_redirects: bool,
        stream: bool,
        timeout: tuple[int, int],
    ) -> _UrllibResponse:
        if not allow_redirects or not stream:
            raise ValueError("Field-Ritter transport contract is invalid")
        request = urllib.request.Request(url, headers=headers, method="GET")
        response = urllib.request.urlopen(  # nosec B310 -- fixed official URL
            request,
            timeout=max(timeout),
        )
        return _UrllibResponse(response)

    def close(self) -> None:
        return None


def _timestamp(value: str | pd.Timestamp | None = None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp(datetime.now(UTC).replace(microsecond=0))
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError("Field-Ritter retrieved_at is invalid")
    return pd.Timestamp(parsed)


def _published_at(headers: Any) -> pd.Timestamp:
    raw = str(headers.get("Last-Modified", "")).strip()
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Field-Ritter response is missing a valid Last-Modified timestamp"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return pd.Timestamp(parsed).tz_convert("UTC")


def _write_manifest(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame([row], columns=FIELD_RITTER_SOURCE_MANIFEST_COLUMNS).to_csv(
        temporary,
        index=False,
    )
    os.replace(temporary, path)


def _failure_reason(status_code: int, attempts: int, error: Exception) -> str:
    if status_code:
        return f"http_{status_code}_after_{attempts}_attempts"
    return f"{type(error).__name__.lower()}_after_{attempts}_attempts"


def download_field_ritter_ipo_workbook(
    destination: Path | str,
    manifest_path: Path | str,
    *,
    user_agent: str,
    session: Any | None = None,
    retrieved_at: str | pd.Timestamp | None = None,
    retry_delays: tuple[float, ...] = (2.0, 5.0),
) -> dict[str, bool | int]:
    """Download one official workbook or persist the concrete access failure.

    The caller must enforce Aurora's execution policy.  The raw workbook is an
    internal input and is deliberately excluded from the publishable output
    contract because Field-Ritter requests citation but publishes no explicit
    redistribution license.
    """

    identity = str(user_agent).strip()
    if len(identity) < 12:
        raise ValueError("Field-Ritter access requires an identifiable User-Agent")
    output = Path(destination)
    manifest = Path(manifest_path)
    if output.name != "IPO-age.xlsx":
        raise ValueError("Field-Ritter destination filename must be IPO-age.xlsx")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    requested_at = _timestamp(retrieved_at)
    client = session if session is not None else _UrllibSession()
    owns_session = session is None
    attempts = len(retry_delays) + 1
    last_error: Exception | None = None
    last_status = 0
    published = ""
    digest_value = ""
    size = 0
    try:
        for attempt in range(attempts):
            temporary.unlink(missing_ok=True)
            try:
                with client.get(
                    FIELD_RITTER_WORKBOOK_URL,
                    headers={
                        "User-Agent": identity,
                        "Accept": _EXPECTED_CONTENT_TYPE,
                    },
                    allow_redirects=True,
                    stream=True,
                    timeout=(30, 180),
                ) as response:
                    last_status = int(response.status_code)
                    response.raise_for_status()
                    content_type = str(response.headers.get("Content-Type", ""))
                    if _EXPECTED_CONTENT_TYPE not in content_type.lower():
                        raise ValueError(
                            "Field-Ritter response has an unexpected content type"
                        )
                    published_timestamp = _published_at(response.headers)
                    if published_timestamp > requested_at:
                        raise ValueError(
                            "Field-Ritter publication timestamp follows retrieval"
                        )
                    digest = hashlib.sha256()
                    size = 0
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            size += len(chunk)
                            if size > _MAX_WORKBOOK_BYTES:
                                raise ValueError(
                                    "Field-Ritter workbook exceeds the size bound"
                                )
                            handle.write(chunk)
                            digest.update(chunk)
                    if size <= 0:
                        raise ValueError("Field-Ritter workbook response is empty")
                    os.replace(temporary, output)
                    published = published_timestamp.isoformat()
                    digest_value = digest.hexdigest()
                    last_error = None
                    break
            except Exception as exc:
                last_error = exc
                error_code = getattr(exc, "code", None)
                if error_code:
                    last_status = int(error_code)
                response = getattr(exc, "response", None)
                if response is not None and getattr(response, "status_code", None):
                    last_status = int(response.status_code)
                temporary.unlink(missing_ok=True)
                if attempt < len(retry_delays):
                    time.sleep(retry_delays[attempt])
    finally:
        if owns_session:
            client.close()

    if last_error is None:
        row = {
            "source_id": FIELD_RITTER_SOURCE_ID,
            "source_url": FIELD_RITTER_WORKBOOK_URL,
            "documentation_url": FIELD_RITTER_DOCUMENTATION_URL,
            "access_url": FIELD_RITTER_WORKBOOK_URL,
            "access_method": FIELD_RITTER_ACCESS_METHOD,
            "published_at": published,
            "retrieved_at": requested_at.isoformat(),
            "sha256": digest_value,
            "size_bytes": size,
            "status": "downloaded",
            "http_status": last_status,
            "failure_reason": "",
        }
    else:
        output.unlink(missing_ok=True)
        row = {
            "source_id": FIELD_RITTER_SOURCE_ID,
            "source_url": FIELD_RITTER_WORKBOOK_URL,
            "documentation_url": FIELD_RITTER_DOCUMENTATION_URL,
            "access_url": FIELD_RITTER_WORKBOOK_URL,
            "access_method": FIELD_RITTER_ACCESS_METHOD,
            "published_at": "",
            "retrieved_at": requested_at.isoformat(),
            "sha256": "",
            "size_bytes": 0,
            "status": "failed",
            "http_status": last_status,
            "failure_reason": _failure_reason(last_status, attempts, last_error),
        }
    _write_manifest(manifest, row)
    downloaded = int(row["status"] == "downloaded")
    failed = int(row["status"] == "failed")
    return {
        "all_downloaded": downloaded == 1 and failed == 0,
        "downloaded": downloaded,
        "failed": failed,
        "raw_workbook_redistribution_allowed": False,
    }


__all__ = [
    "FIELD_RITTER_SOURCE_MANIFEST_COLUMNS",
    "download_field_ritter_ipo_workbook",
]
