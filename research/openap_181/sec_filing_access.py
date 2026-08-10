"""Bounded, auditable access to one official SEC filing document."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


OFFICIAL_FILING_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_compact}/"
    "{primary_document}"
)
SEC_FILING_ACCESS_METHOD = "sec_official_filing_fair_access"
SEC_FILING_MANIFEST_COLUMNS = [
    "source_id",
    "source_url",
    "access_url",
    "access_method",
    "cik",
    "accession_number",
    "primary_document",
    "sha256",
    "size_bytes",
    "retrieved_at",
    "status",
    "http_status",
    "failure_reason",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _normalize_identity(
    cik: object,
    accession_number: object,
    primary_document: object,
) -> tuple[str, str, str]:
    cik_text = str(cik).strip()
    if not cik_text.isdigit() or not 1 <= len(cik_text) <= 10:
        raise ValueError("SEC CIK must contain 1 to 10 numeric digits")
    normalized_cik = cik_text.zfill(10)
    accession = str(accession_number).strip()
    if re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) is None:
        raise ValueError("SEC accession number must match 0000000000-00-000000")
    document = str(primary_document).strip()
    if (
        re.fullmatch(r"[A-Za-z0-9._-]+", document) is None
        or not document.lower().endswith((".htm", ".html"))
    ):
        raise ValueError("SEC primary document must be one safe HTML filename")
    return normalized_cik, accession, document


def _write_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=SEC_FILING_MANIFEST_COLUMNS).to_csv(
        path, index=False
    )


def _failure_reason(status_code: int, attempts: int, error: Exception) -> str:
    if status_code:
        return f"http_{status_code}_after_{attempts}_attempts"
    return f"{type(error).__name__.lower()}_after_{attempts}_attempts"


def download_official_sec_filing(
    *,
    cik: object,
    accession_number: object,
    primary_document: object,
    output_dir: Path | str,
    manifest_path: Path | str,
    user_agent: str,
    session: Any | None = None,
    retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0),
) -> dict[str, int | bool]:
    """Download one canonical filing or persist its concrete access blocker."""

    cik_text, accession, document = _normalize_identity(
        cik, accession_number, primary_document
    )
    identity = str(user_agent).strip()
    if len(identity) < 20 or ("@" not in identity and "https://" not in identity):
        raise ValueError("SEC User-Agent requires a declared identity and contact")
    source_url = OFFICIAL_FILING_URL_TEMPLATE.format(
        cik_int=int(cik_text),
        accession_compact=accession.replace("-", ""),
        primary_document=document,
    )
    output = Path(output_dir)
    manifest = Path(manifest_path)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / document
    temporary = destination.with_suffix(destination.suffix + ".part")
    client = session if session is not None else requests.Session()
    owns_session = session is None
    headers = {
        "User-Agent": identity,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    attempts = len(retry_delays) + 1
    last_error: Exception | None = None
    last_status = 0
    row: dict[str, Any] | None = None
    try:
        for attempt in range(attempts):
            temporary.unlink(missing_ok=True)
            try:
                with client.get(
                    source_url,
                    headers=headers,
                    allow_redirects=True,
                    stream=True,
                    timeout=(30, 300),
                ) as response:
                    last_status = int(response.status_code)
                    response.raise_for_status()
                    digest = hashlib.sha256()
                    size = 0
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    if size <= 0:
                        raise ValueError("Official SEC filing response was empty")
                    temporary.replace(destination)
                    row = {
                        "source_id": f"sec_filing_{accession}",
                        "source_url": source_url,
                        "access_url": source_url,
                        "access_method": SEC_FILING_ACCESS_METHOD,
                        "cik": cik_text,
                        "accession_number": accession,
                        "primary_document": document,
                        "sha256": digest.hexdigest(),
                        "size_bytes": size,
                        "retrieved_at": _utc_now(),
                        "status": "downloaded",
                        "http_status": last_status,
                        "failure_reason": "",
                    }
                    last_error = None
                    break
            except Exception as exc:
                last_error = exc
                error_response = getattr(exc, "response", None)
                if error_response is not None and getattr(
                    error_response, "status_code", None
                ):
                    last_status = int(error_response.status_code)
                temporary.unlink(missing_ok=True)
                if attempt < len(retry_delays):
                    time.sleep(retry_delays[attempt])
        if last_error is not None:
            row = {
                "source_id": f"sec_filing_{accession}",
                "source_url": source_url,
                "access_url": source_url,
                "access_method": SEC_FILING_ACCESS_METHOD,
                "cik": cik_text,
                "accession_number": accession,
                "primary_document": document,
                "sha256": "",
                "size_bytes": 0,
                "retrieved_at": _utc_now(),
                "status": "failed",
                "http_status": last_status,
                "failure_reason": _failure_reason(
                    last_status, attempts, last_error
                ),
            }
    finally:
        if owns_session:
            client.close()
        _write_manifest([row] if row is not None else [], manifest)
    downloaded = int(row is not None and row["status"] == "downloaded")
    failed = int(row is not None and row["status"] == "failed")
    return {
        "all_downloaded": downloaded == 1 and failed == 0,
        "downloaded": downloaded,
        "failed": failed,
        "filings_requested": 1,
    }


__all__ = [
    "OFFICIAL_FILING_URL_TEMPLATE",
    "SEC_FILING_ACCESS_METHOD",
    "SEC_FILING_MANIFEST_COLUMNS",
    "download_official_sec_filing",
]
