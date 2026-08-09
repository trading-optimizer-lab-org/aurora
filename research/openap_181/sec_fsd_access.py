"""Bounded, auditable access to the official SEC FSD quarterly archives."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests


OFFICIAL_FSD_URL_TEMPLATE = (
    "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip"
)
SEC_FSD_ACCESS_METHOD = "sec_official_direct_fair_access"
SEC_FSD_MANIFEST_COLUMNS = [
    "source_id",
    "source_url",
    "access_url",
    "access_method",
    "period",
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


def _write_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=SEC_FSD_MANIFEST_COLUMNS).to_csv(path, index=False)


def _failure_reason(status_code: int, attempts: int, error: Exception) -> str:
    if status_code:
        return f"http_{status_code}_after_{attempts}_attempts"
    return f"{type(error).__name__.lower()}_after_{attempts}_attempts"


def download_official_sec_fsd_archives(
    quarters: Iterable[str],
    zip_dir: Path | str,
    manifest_path: Path | str,
    *,
    user_agent: str,
    session: Any | None = None,
    retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0),
) -> dict[str, int | bool]:
    """Download a bounded quarter list or persist the first concrete access blocker."""

    requested = tuple(str(quarter).strip().lower() for quarter in quarters)
    if not requested:
        raise ValueError("SEC FSD access requires at least one quarter")
    identity = str(user_agent).strip()
    if len(identity) < 20 or ("@" not in identity and "https://" not in identity):
        raise ValueError("SEC User-Agent requires a declared identity and contact")
    archives = Path(zip_dir)
    manifest = Path(manifest_path)
    archives.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    client = session if session is not None else requests.Session()
    owns_session = session is None
    headers = {
        "User-Agent": identity,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    try:
        for quarter in requested:
            source_url = OFFICIAL_FSD_URL_TEMPLATE.format(quarter=quarter)
            destination = archives / f"{quarter}.zip"
            temporary = destination.with_suffix(".zip.part")
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
                        stream=True,
                        timeout=(30, 900),
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
                            raise ValueError("Official SEC FSD response was empty")
                        temporary.replace(destination)
                        rows.append(
                            {
                                "source_id": f"sec_fsd_{quarter}",
                                "source_url": source_url,
                                "access_url": source_url,
                                "access_method": SEC_FSD_ACCESS_METHOD,
                                "period": quarter,
                                "sha256": digest.hexdigest(),
                                "size_bytes": size,
                                "retrieved_at": _utc_now(),
                                "status": "downloaded",
                                "http_status": last_status,
                                "failure_reason": "",
                            }
                        )
                        last_error = None
                        break
                except Exception as exc:
                    last_error = exc
                    response = getattr(exc, "response", None)
                    if response is not None and getattr(response, "status_code", None):
                        last_status = int(response.status_code)
                    temporary.unlink(missing_ok=True)
                    if attempt < len(retry_delays):
                        time.sleep(retry_delays[attempt])
            if last_error is not None:
                rows.append(
                    {
                        "source_id": f"sec_fsd_{quarter}",
                        "source_url": source_url,
                        "access_url": source_url,
                        "access_method": SEC_FSD_ACCESS_METHOD,
                        "period": quarter,
                        "sha256": "",
                        "size_bytes": 0,
                        "retrieved_at": _utc_now(),
                        "status": "failed",
                        "http_status": last_status,
                        "failure_reason": _failure_reason(
                            last_status,
                            attempts,
                            last_error,
                        ),
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
        "quarters_requested": len(requested),
    }


__all__ = [
    "OFFICIAL_FSD_URL_TEMPLATE",
    "SEC_FSD_ACCESS_METHOD",
    "SEC_FSD_MANIFEST_COLUMNS",
    "download_official_sec_fsd_archives",
]
