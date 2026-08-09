"""GitHub-only acquisition probe for the free 120-lane data contract."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import calendar
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from threading import BoundedSemaphore
from typing import Mapping, Sequence
from urllib.parse import urlsplit

import requests

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.data_contract import SourcePlanItem


@dataclass(frozen=True)
class ExpandedSource:
    resource_id: str
    url: str
    format: str


def _replace_secrets(template: str, secrets: Mapping[str, str]) -> str:
    result = template
    for name, value in secrets.items():
        result = result.replace("{" + name + "}", value)
    return result


def _expand_vintage_schedule(resource: Mapping[str, object], template: str) -> str:
    raw_schedule = resource.get("vintage_schedule")
    if not isinstance(raw_schedule, Mapping):
        return template
    if raw_schedule.get("frequency") != "month_end":
        raise ValueError("UNSUPPORTED_VINTAGE_FREQUENCY")
    start = dt.date.fromisoformat(str(raw_schedule["start"]))
    end = dt.date.fromisoformat(str(raw_schedule["end"]))
    if end > dt.date(2010, 12, 31):
        raise ValueError(f"POST_EVALUATION_VINTAGE_DATE:{end.isoformat()}")
    cursor = dt.date(start.year, start.month, 1)
    vintages: list[str] = []
    while cursor <= end:
        month_end = dt.date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        if start <= month_end <= end:
            vintages.append(month_end.isoformat())
        cursor = dt.date(cursor.year + (cursor.month == 12), (cursor.month % 12) + 1, 1)
    if not vintages:
        raise ValueError("EMPTY_VINTAGE_SCHEDULE")
    return template.replace("{vintage_dates}", "%2C".join(vintages))


def expand_source_urls(
    resources: Sequence[Mapping[str, object]], *, secrets: Mapping[str, str]
) -> tuple[ExpandedSource, ...]:
    """Expand deterministic series/year source templates into concrete URLs."""

    expanded: list[ExpandedSource] = []
    for resource in resources:
        resource_id = str(resource.get("id", "resource"))
        format_name = str(resource.get("format", "binary"))
        if "url" in resource:
            expanded.append(
                ExpandedSource(
                    resource_id=resource_id,
                    url=_replace_secrets(str(resource["url"]), secrets),
                    format=format_name,
                )
            )
            continue
        template = _expand_vintage_schedule(resource, str(resource.get("url_template", "")))
        for series_id in resource.get("series_ids", []):
            url = template.replace("{series_id}", str(series_id))
            expanded.append(
                ExpandedSource(
                    resource_id=f"{resource_id}:{series_id}",
                    url=_replace_secrets(url, secrets),
                    format=format_name,
                )
            )
        for raw_year in resource.get("years", []):
            year = int(raw_year)
            if year > 2010:
                raise ValueError(f"POST_EVALUATION_SOURCE_YEAR:{resource_id}:{year}")
            year_template = str(resource.get("url_template_2010", template)) if year == 2010 else template
            expanded.append(
                ExpandedSource(
                    resource_id=f"{resource_id}:{year}",
                    url=_replace_secrets(year_template.replace("{year}", str(year)), secrets),
                    format=format_name,
                )
            )
    return tuple(expanded)


def _payload_shape_valid(payload: bytes, format_name: str) -> bool:
    prefix = payload[:512].lstrip().lower()
    if not payload:
        return False
    if format_name in {"csv", "zip_csv"}:
        return payload.startswith(b"PK\x03\x04") if format_name == "zip_csv" else b"\n" in payload
    if format_name == "json":
        try:
            json.loads(payload)
        except json.JSONDecodeError:
            return False
        return True
    if format_name == "xls":
        return payload.startswith(b"\xd0\xcf\x11\xe0")
    if format_name == "xlsx":
        return payload.startswith(b"PK\x03\x04")
    if format_name.startswith("html"):
        return prefix.startswith((b"<!doctype html", b"<html")) or b"<html" in prefix
    return True


def _probe_one_source(source: ExpandedSource, *, fred_api_key: str) -> dict[str, object]:
    safe_url = source.url.replace(fred_api_key, "***") if fred_api_key else source.url
    try:
        response = requests.get(
            source.url,
            headers={"User-Agent": "Aurora-SP500-Free-Data-Audit/1.0"},
            timeout=(15, 45),
        )
        payload = response.content
        shape_valid = response.ok and _payload_shape_valid(payload, source.format)
        return {
            "resource_id": source.resource_id,
            "url": safe_url,
            "http_status": response.status_code,
            "byte_count": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "format": source.format,
            "shape_valid": shape_valid,
        }
    except requests.RequestException as exc:
        return {
            "resource_id": source.resource_id,
            "url": safe_url,
            "format": source.format,
            "shape_valid": False,
            "error": type(exc).__name__,
        }


def probe_expanded_sources(
    sources: Sequence[ExpandedSource],
    *,
    fred_api_key: str = "",
    max_workers: int = 16,
    per_host_workers: int = 4,
) -> tuple[dict[str, object], ...]:
    """Probe one source bundle concurrently while preserving declared order."""

    if not sources:
        return ()
    worker_count = max(1, min(max_workers, len(sources)))
    host_limiters = {
        host: BoundedSemaphore(max(1, per_host_workers))
        for host in {urlsplit(source.url).netloc for source in sources}
    }

    def run_bounded(source: ExpandedSource) -> dict[str, object]:
        with host_limiters[urlsplit(source.url).netloc]:
            return _probe_one_source(source, fred_api_key=fred_api_key)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        rows = executor.map(run_bounded, sources)
        return tuple(rows)


def probe_sources(
    source_plan: Mapping[str, SourcePlanItem],
    *,
    output_path: Path,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    """Download each declared raw resource on GitHub and preserve a hash-only report."""

    env = os.environ if environ is None else environ
    require_github_only_execution("SP500_MEGARUN_FREE_DATA_SOURCE_PROBE", env)
    secrets = {"FRED_API_KEY": env.get("FRED_API_KEY", "")}
    datasets: dict[str, object] = {}
    expanded_by_dataset: dict[str, tuple[ExpandedSource, ...]] = {}
    for dataset_id, item in sorted(source_plan.items()):
        if item.acquisition_kind in {"existing", "derived"}:
            datasets[dataset_id] = {
                "status": "ready_without_network_probe",
                "acquisition_kind": item.acquisition_kind,
                "resource_count": 0,
            }
            continue
        expanded_by_dataset[dataset_id] = expand_source_urls(item.resources, secrets=secrets)

    flat_sources = tuple(
        source
        for dataset_id in sorted(expanded_by_dataset)
        for source in expanded_by_dataset[dataset_id]
    )
    flat_rows = probe_expanded_sources(
        flat_sources,
        fred_api_key=secrets["FRED_API_KEY"],
        max_workers=24,
    )
    row_offset = 0
    overall_ready = True
    for dataset_id in sorted(expanded_by_dataset):
        item = source_plan[dataset_id]
        resource_count = len(expanded_by_dataset[dataset_id])
        resource_rows = flat_rows[row_offset : row_offset + resource_count]
        row_offset += resource_count
        dataset_ready = bool(resource_rows) and all(row["shape_valid"] for row in resource_rows)
        datasets[dataset_id] = {
            "status": "source_reachable" if dataset_ready else "source_failed",
            "acquisition_kind": item.acquisition_kind,
            "resource_count": len(resource_rows),
            "resources": resource_rows,
        }
        overall_ready = overall_ready and dataset_ready
    report: Mapping[str, object] = {
        "schema_version": 1,
        "ready": overall_ready,
        "validation_opened": False,
        "locked_opened": False,
        "maximum_observation_date": "2010-12-31",
        "datasets": datasets,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
