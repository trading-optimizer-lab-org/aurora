"""GitHub-only acquisition probe for the free 120-lane data contract."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

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
        template = str(resource.get("url_template", ""))
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
    session = requests.Session()
    session.headers.update({"User-Agent": "Aurora-SP500-Free-Data-Audit/1.0"})
    datasets: dict[str, object] = {}
    overall_ready = True
    for dataset_id, item in sorted(source_plan.items()):
        if item.acquisition_kind in {"existing", "derived"}:
            datasets[dataset_id] = {
                "status": "ready_without_network_probe",
                "acquisition_kind": item.acquisition_kind,
                "resource_count": 0,
            }
            continue
        expanded = expand_source_urls(item.resources, secrets=secrets)
        resource_rows: list[dict[str, object]] = []
        for source in expanded:
            safe_url = source.url.replace(secrets["FRED_API_KEY"], "***") if secrets["FRED_API_KEY"] else source.url
            try:
                response = session.get(source.url, timeout=(15, 90))
                payload = response.content
                shape_valid = response.ok and _payload_shape_valid(payload, source.format)
                resource_rows.append(
                    {
                        "resource_id": source.resource_id,
                        "url": safe_url,
                        "http_status": response.status_code,
                        "byte_count": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "format": source.format,
                        "shape_valid": shape_valid,
                    }
                )
                if not shape_valid:
                    overall_ready = False
            except requests.RequestException as exc:
                overall_ready = False
                resource_rows.append(
                    {
                        "resource_id": source.resource_id,
                        "url": safe_url,
                        "format": source.format,
                        "shape_valid": False,
                        "error": type(exc).__name__,
                    }
                )
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

