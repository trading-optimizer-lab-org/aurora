"""Bounded official-SEC document access for the Spinoff reconstruction."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import re
import time
from typing import Any
import urllib.request
from urllib.parse import urlparse

import pandas as pd

from .sec_spinoff import extract_sec_spinoff_completion_evidence


SEC_SPINOFF_ACCESS_METHOD = "sec_official_filing_direct_fair_access"
SEC_SPINOFF_ACCESS_MANIFEST_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "accession_number",
    "form",
    "source_url",
    "access_method",
    "retrieved_at",
    "sha256",
    "size_bytes",
    "status",
    "http_status",
    "failure_reason",
    "completion_evidence_detected",
)
_CANDIDATE_REQUIRED = frozenset(
    {
        "security_id",
        "ticker",
        "cik",
        "accession_number",
        "accepted_at",
        "form",
        "primary_document",
        "source_url",
    }
)
_MAX_DOCUMENT_BYTES = 32 * 1024**2
_MAX_DOCUMENTS = 2_000
_MAX_DOCUMENTS_PER_SECURITY = 24
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class _UrllibResponse:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.status_code = int(response.status)
        self.headers = response.headers

    def __enter__(self) -> _UrllibResponse:
        return self

    def __exit__(self, *_: object) -> None:
        self._response.close()

    def raise_for_status(self) -> None:
        return None

    @property
    def content(self) -> bytes:
        payload = self._response.read(_MAX_DOCUMENT_BYTES + 1)
        return payload


class _UrllibSession:
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: tuple[int, int],
    ) -> _UrllibResponse:
        request = urllib.request.Request(url, headers=headers, method="GET")
        response = urllib.request.urlopen(  # nosec B310 -- validated SEC URL
            request,
            timeout=max(timeout),
        )
        return _UrllibResponse(response)

    def close(self) -> None:
        return None


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _timestamp(value: object | None = None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp(datetime.now(UTC).replace(microsecond=0))
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError("SEC Spinoff retrieved_at is invalid")
    return pd.Timestamp(parsed)


def _official_url(value: object, cik: object) -> bool:
    url = _clean_text(value)
    cik_text = _clean_text(cik)
    if re.fullmatch(r"[0-9]{10}", cik_text) is None:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "www.sec.gov"
        and parsed.path.startswith(
            f"/Archives/edgar/data/{int(cik_text)}/"
        )
        and not parsed.query
        and not parsed.fragment
    )


def _failure_reason(status_code: int, attempts: int, error: Exception) -> str:
    if status_code:
        return f"http_{status_code}_after_{attempts}_attempts"
    return f"{type(error).__name__.lower()}_after_{attempts}_attempts"


def _decoded_document(payload: bytes, content_type: str) -> str:
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        raise ValueError("SEC filing response has an unexpected content type")
    if not payload or len(payload) > _MAX_DOCUMENT_BYTES:
        raise ValueError("SEC filing response is empty or exceeds the size bound")
    return payload.decode("utf-8", errors="replace")


def download_sec_spinoff_candidate_documents(
    candidates: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    user_agent: str,
    session: Any | None = None,
    retrieved_at: str | pd.Timestamp | None = None,
    retry_delays: tuple[float, ...] = (1.0, 2.0),
    request_interval_seconds: float = 0.12,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int | bool]]:
    """Download bounded candidate filings and retain only hashes and evidence."""

    missing = sorted(_CANDIDATE_REQUIRED.difference(candidates.columns))
    if missing:
        raise ValueError(f"SEC Spinoff candidates are missing columns: {missing}")
    identity = str(user_agent).strip()
    if len(identity) < 20 or ("@" not in identity and "https://" not in identity):
        raise ValueError("SEC User-Agent requires a declared identity and contact")
    if request_interval_seconds < 0.1:
        raise ValueError("SEC request interval must remain within fair-access bounds")
    if len(candidates) > _MAX_DOCUMENTS:
        raise ValueError("SEC Spinoff candidate count exceeds the safety bound")
    if (
        not candidates.empty
        and candidates.groupby("security_id").size().gt(
            _MAX_DOCUMENTS_PER_SECURITY
        ).any()
    ):
        raise ValueError("SEC Spinoff per-security candidate count is unbounded")
    requested_at = _timestamp(retrieved_at)
    client = session if session is not None else _UrllibSession()
    owns_session = session is None
    document_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    attempts = len(retry_delays) + 1
    try:
        for index, candidate in enumerate(
            candidates.sort_values(
                ["security_id", "accepted_at", "accession_number"]
            ).to_dict(orient="records")
        ):
            source_url = _clean_text(candidate["source_url"])
            cik = _clean_text(candidate["cik"])
            if not _official_url(source_url, cik):
                raise ValueError("SEC Spinoff candidate URL is not exact official SEC")
            last_error: Exception | None = None
            last_status = 0
            digest = ""
            size = 0
            text = ""
            for attempt in range(attempts):
                try:
                    with client.get(
                        source_url,
                        headers={
                            "User-Agent": identity,
                            "Accept": "text/html,text/plain;q=0.9",
                        },
                        timeout=(30, 180),
                    ) as response:
                        last_status = int(response.status_code)
                        response.raise_for_status()
                        payload = bytes(response.content)
                        size = len(payload)
                        text = _decoded_document(
                            payload,
                            str(response.headers.get("Content-Type", "")),
                        )
                        digest = hashlib.sha256(payload).hexdigest()
                        last_error = None
                        break
                except Exception as exc:
                    last_error = exc
                    error_code = getattr(exc, "code", None)
                    if error_code:
                        last_status = int(error_code)
                    response = getattr(exc, "response", None)
                    if response is not None and getattr(
                        response, "status_code", None
                    ):
                        last_status = int(response.status_code)
                    if attempt < len(retry_delays):
                        time.sleep(retry_delays[attempt])
            base = {
                "security_id": _clean_text(candidate["security_id"]),
                "ticker": _clean_text(candidate["ticker"]).upper(),
                "cik": cik,
                "accession_number": _clean_text(
                    candidate["accession_number"]
                ),
                "form": _clean_text(candidate["form"]).upper(),
                "source_url": source_url,
                "access_method": SEC_SPINOFF_ACCESS_METHOD,
                "retrieved_at": requested_at.isoformat(),
            }
            if last_error is None:
                if _SHA256_RE.fullmatch(digest) is None:
                    raise RuntimeError("SEC filing digest contract failed")
                document_rows.append(
                    {
                        **candidate,
                        "retrieved_at": requested_at,
                        "transport_sha256": digest,
                        "document_text": text,
                    }
                )
                manifest_rows.append(
                    {
                        **base,
                        "sha256": digest,
                        "size_bytes": size,
                        "status": "downloaded",
                        "http_status": last_status,
                        "failure_reason": "",
                        "completion_evidence_detected": False,
                    }
                )
            else:
                manifest_rows.append(
                    {
                        **base,
                        "sha256": "",
                        "size_bytes": 0,
                        "status": "failed",
                        "http_status": last_status,
                        "failure_reason": _failure_reason(
                            last_status, attempts, last_error
                        ),
                        "completion_evidence_detected": False,
                    }
                )
            if index + 1 < len(candidates):
                time.sleep(request_interval_seconds)
    finally:
        if owns_session:
            client.close()

    documents = pd.DataFrame(document_rows)
    if documents.empty:
        documents = pd.DataFrame(columns=tuple(_CANDIDATE_REQUIRED) + (
            "retrieved_at",
            "transport_sha256",
            "document_text",
        ))
    evidence = extract_sec_spinoff_completion_evidence(
        documents,
        formation_at=formation_at,
    )
    manifest = pd.DataFrame(
        manifest_rows,
        columns=SEC_SPINOFF_ACCESS_MANIFEST_COLUMNS,
    )
    if not evidence.empty and not manifest.empty:
        detected = set(evidence["accession_number"].astype(str))
        manifest["completion_evidence_detected"] = manifest[
            "accession_number"
        ].astype(str).isin(detected)
    downloaded = int(manifest["status"].eq("downloaded").sum())
    failed = int(manifest["status"].eq("failed").sum())
    summary: dict[str, int | bool] = {
        "candidates_requested": int(len(candidates)),
        "downloaded": downloaded,
        "failed": failed,
        "completion_evidence_rows": int(len(evidence)),
        "all_downloaded": downloaded == len(candidates) and failed == 0,
        "raw_filing_documents_retained": False,
    }
    return documents, evidence, manifest, summary


__all__ = [
    "SEC_SPINOFF_ACCESS_MANIFEST_COLUMNS",
    "SEC_SPINOFF_ACCESS_METHOD",
    "download_sec_spinoff_candidate_documents",
]
