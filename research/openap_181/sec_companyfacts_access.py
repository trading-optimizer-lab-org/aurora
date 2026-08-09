"""Bounded, auditable access to the official SEC CompanyFacts API."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import requests


OFFICIAL_COMPANYFACTS_URL_TEMPLATE = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)
SEC_COMPANYFACTS_ACCESS_METHOD = "sec_official_companyfacts_fair_access"
SEC_COMPANYFACTS_MANIFEST_COLUMNS = [
    "source_id",
    "source_url",
    "access_url",
    "access_method",
    "cik",
    "sha256",
    "size_bytes",
    "retrieved_at",
    "status",
    "http_status",
    "failure_reason",
    "entity_name",
    "us_gaap_concepts",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _normalize_cik(value: object) -> str:
    text = str(value).strip()
    if not text.isdigit() or not 1 <= len(text) <= 10:
        raise ValueError("SEC CIK must contain 1 to 10 numeric digits")
    return text.zfill(10)


def _write_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=SEC_COMPANYFACTS_MANIFEST_COLUMNS).to_csv(
        path, index=False
    )


def _failure_reason(status_code: int, attempts: int, error: Exception) -> str:
    if status_code:
        return f"http_{status_code}_after_{attempts}_attempts"
    return f"{type(error).__name__.lower()}_after_{attempts}_attempts"


def _validate_payload(payload: object, expected_cik: str) -> tuple[str, int]:
    if not isinstance(payload, Mapping):
        raise ValueError("Official SEC CompanyFacts response must be a JSON object")
    if _normalize_cik(payload.get("cik", "")) != expected_cik:
        raise ValueError(
            "Official SEC CompanyFacts response CIK does not match request"
        )
    entity_name = str(payload.get("entityName", "")).strip()
    if not entity_name:
        raise ValueError("Official SEC CompanyFacts response lacks entityName")
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        raise ValueError("Official SEC CompanyFacts response lacks facts")
    us_gaap = facts.get("us-gaap", {})
    if not isinstance(us_gaap, Mapping):
        raise ValueError("Official SEC CompanyFacts us-gaap facts must be an object")
    return entity_name, len(us_gaap)


def download_official_sec_companyfacts(
    ciks: Iterable[str],
    raw_dir: Path | str,
    manifest_path: Path | str,
    *,
    user_agent: str,
    session: Any | None = None,
    retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
) -> dict[str, int | bool]:
    """Download a bounded CIK list or persist the first concrete access blocker."""

    requested = tuple(_normalize_cik(cik) for cik in ciks)
    if not requested:
        raise ValueError("SEC CompanyFacts access requires at least one CIK")
    if len(set(requested)) != len(requested):
        raise ValueError("SEC CompanyFacts access requires unique CIKs")
    identity = str(user_agent).strip()
    if len(identity) < 20 or ("@" not in identity and "https://" not in identity):
        raise ValueError("SEC User-Agent requires a declared identity and contact")
    raw = Path(raw_dir)
    manifest = Path(manifest_path)
    raw.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    client = session if session is not None else requests.Session()
    owns_session = session is None
    headers = {
        "User-Agent": identity,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }
    try:
        for cik in requested:
            source_url = OFFICIAL_COMPANYFACTS_URL_TEMPLATE.format(cik=cik)
            destination = raw / f"CIK{cik}.json"
            temporary = destination.with_suffix(".json.part")
            last_error: Exception | None = None
            last_status = 0
            attempts = len(retry_delays) + 1
            for attempt in range(attempts):
                temporary.unlink(missing_ok=True)
                try:
                    with client.get(
                        source_url,
                        headers=headers,
                        allow_redirects=True,
                        timeout=(30, 120),
                    ) as response:
                        last_status = int(response.status_code)
                        response.raise_for_status()
                        content = bytes(response.content)
                        if not content:
                            raise ValueError(
                                "Official SEC CompanyFacts response was empty"
                            )
                        payload = json.loads(content.decode("utf-8"))
                        entity_name, concept_count = _validate_payload(payload, cik)
                        temporary.write_bytes(content)
                        temporary.replace(destination)
                        rows.append(
                            {
                                "source_id": f"sec_companyfacts_CIK{cik}",
                                "source_url": source_url,
                                "access_url": source_url,
                                "access_method": SEC_COMPANYFACTS_ACCESS_METHOD,
                                "cik": cik,
                                "sha256": hashlib.sha256(content).hexdigest(),
                                "size_bytes": len(content),
                                "retrieved_at": _utc_now(),
                                "status": "downloaded",
                                "http_status": last_status,
                                "failure_reason": "",
                                "entity_name": entity_name,
                                "us_gaap_concepts": concept_count,
                            }
                        )
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
                rows.append(
                    {
                        "source_id": f"sec_companyfacts_CIK{cik}",
                        "source_url": source_url,
                        "access_url": source_url,
                        "access_method": SEC_COMPANYFACTS_ACCESS_METHOD,
                        "cik": cik,
                        "sha256": "",
                        "size_bytes": 0,
                        "retrieved_at": _utc_now(),
                        "status": "failed",
                        "http_status": last_status,
                        "failure_reason": _failure_reason(
                            last_status, attempts, last_error
                        ),
                        "entity_name": "",
                        "us_gaap_concepts": 0,
                    }
                )
                break
    finally:
        if owns_session:
            client.close()
        _write_manifest(rows, manifest)
    downloaded = sum(row["status"] == "downloaded" for row in rows)
    failed = sum(row["status"] == "failed" for row in rows)
    return {
        "all_downloaded": downloaded == len(requested) and failed == 0,
        "downloaded": downloaded,
        "failed": failed,
        "ciks_requested": len(requested),
    }


__all__ = [
    "OFFICIAL_COMPANYFACTS_URL_TEMPLATE",
    "SEC_COMPANYFACTS_ACCESS_METHOD",
    "SEC_COMPANYFACTS_MANIFEST_COLUMNS",
    "download_official_sec_companyfacts",
]
