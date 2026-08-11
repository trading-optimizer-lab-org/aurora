"""GitHub-only acquisition and normalization for the SP500 mega-run inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

from aurora.infra.sp500_megarun.data_contract import FreeDataContract, SourcePlanItem
from aurora.infra.sp500_megarun.source_adapters import (
    SourceAdapterError,
    normalize_resource_payload,
)


class MaterializationError(RuntimeError):
    """Raised when a source cannot become a bounded runnable table."""


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


def discover_official_data_links(
    payload: bytes, *, base_url: str, allowed_hosts: set[str]
) -> tuple[str, ...]:
    """Find direct tabular downloads without leaving the official source hosts."""

    parser = _LinkCollector()
    parser.feed(payload.decode("utf-8", errors="replace"))
    accepted: set[str] = set()
    for raw_link in parser.links:
        resolved = urljoin(base_url, raw_link)
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in allowed_hosts:
            continue
        if not parsed.path.lower().endswith((".csv", ".xls", ".xlsx", ".zip")):
            continue
        accepted.add(resolved)
    return tuple(sorted(accepted))


@dataclass(frozen=True)
class MaterializedResource:
    resource_id: str
    url: str
    raw_sha256: str
    raw_byte_count: int
    row_count: int
    minimum_date: str
    maximum_date: str
    normalized_sha256: str


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    suffix = Path(urlparse(url).path).suffix.lower() or ".bin"
    return cache_dir / f"{digest}{suffix}"


def _request_headers(url: str) -> dict[str, str]:
    host = urlparse(url).netloc.casefold()
    if host == "sec.gov" or host.endswith(".sec.gov"):
        return {
            "User-Agent": (
                "trading-optimizer-lab-org Aurora research "
                "aurora-research@users.noreply.github.com"
            ),
            "Accept-Encoding": "gzip, deflate",
        }
    return {"User-Agent": "Aurora-SP500-Free-Data-Materializer/1.0"}


def _download(url: str, *, cache_dir: Path) -> tuple[bytes, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _cache_path(cache_dir, url)
    if target.exists() and target.stat().st_size > 0:
        payload = target.read_bytes()
        return payload, hashlib.sha256(payload).hexdigest()
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            if urlparse(url).netloc.casefold().endswith("sec.gov"):
                time.sleep(0.12)
            with requests.get(
                url,
                headers=_request_headers(url),
                timeout=(20, 180),
                stream=True,
            ) as response:
                response.raise_for_status()
                hasher = hashlib.sha256()
                temporary = target.with_suffix(target.suffix + ".part")
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            hasher.update(chunk)
                            handle.write(chunk)
                temporary.replace(target)
                return target.read_bytes(), hasher.hexdigest()
        except (OSError, requests.RequestException) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(float(attempt * 2))
    raise MaterializationError(f"DOWNLOAD_FAILED:{url}:{type(last_error).__name__}") from last_error


def _expand_resource(
    resource: Mapping[str, Any],
) -> tuple[tuple[str, str, str, Mapping[str, Any]], ...]:
    resource_id = str(resource.get("id", "resource"))
    format_name = str(resource.get("format", ""))
    if resource.get("url"):
        return ((resource_id, str(resource["url"]), format_name, resource),)
    expanded: list[tuple[str, str, str, Mapping[str, Any]]] = []
    template = str(resource.get("url_template", ""))
    for series_id in resource.get("series_ids", []):
        expanded.append(
            (
                f"{resource_id}:{series_id}",
                template.replace("{series_id}", str(series_id)),
                format_name,
                resource,
            )
        )
    year_template = str(resource.get("year_url_template", template))
    quarters = tuple(resource.get("quarters", ()))
    for year in resource.get("years", []):
        if quarters:
            for quarter in quarters:
                expanded.append(
                    (
                        f"{resource_id}:{year}:Q{quarter}",
                        year_template.replace("{year}", str(year)).replace(
                            "{quarter}", str(quarter)
                        ),
                        format_name,
                        resource,
                    )
                )
            continue
        expanded.append(
            (
                f"{resource_id}:{year}",
                year_template.replace("{year}", str(year)),
                format_name,
                resource,
            )
        )
    return tuple(expanded)


def _frame_hash(frame: pd.DataFrame) -> str:
    canonical = frame.copy()
    canonical.columns = [str(column) for column in canonical.columns]
    canonical = canonical.reindex(sorted(canonical.columns), axis=1)
    payload = canonical.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parquet_safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Stabilize mixed spreadsheet columns before Arrow conversion."""

    safe = frame.copy()
    for column in safe.columns:
        if pd.api.types.is_object_dtype(safe[column].dtype):
            safe[column] = safe[column].astype("string")
    return safe


def coverage_spans_research_window(
    *,
    minimum_date: str | date,
    maximum_date: str | date,
    search_start: str | date,
    evaluation_end: str | date,
    evaluation_end_tolerance_days: int = 31,
) -> bool:
    """Accept the first/last scheduled observation near calendar boundaries."""

    def parsed(value: str | date) -> date:
        return value if isinstance(value, date) else date.fromisoformat(value)

    return parsed(minimum_date) <= parsed(search_start) + timedelta(days=31) and parsed(
        maximum_date
    ) >= parsed(evaluation_end) - timedelta(days=evaluation_end_tolerance_days)


def _write_report(report: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "primary_materialization_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )


def _normalize_download(
    *,
    dataset_id: str,
    adapter: str,
    resource_id: str,
    url: str,
    format_name: str,
    resource_metadata: Mapping[str, Any],
    maximum_observation_date: str,
    cache_dir: Path,
) -> tuple[pd.DataFrame, MaterializedResource]:
    payload, raw_sha256 = _download(url, cache_dir=cache_dir)
    targets: tuple[tuple[str, str, str, bytes, str], ...] = (
        (resource_id, url, format_name, payload, raw_sha256),
    )
    if format_name.startswith("html") and bool(
        resource_metadata.get("discover_tabular_links", True)
    ):
        host = urlparse(url).netloc.lower()
        links = discover_official_data_links(payload, base_url=url, allowed_hosts={host})
        if links:
            resolved: list[tuple[str, str, str, bytes, str]] = []
            for index, link in enumerate(links):
                linked_payload, linked_hash = _download(link, cache_dir=cache_dir)
                suffix = Path(urlparse(link).path).suffix.lower()
                linked_format = "zip_csv" if suffix == ".zip" else suffix.lstrip(".")
                resolved.append(
                    (f"{resource_id}:link{index:03d}", link, linked_format, linked_payload, linked_hash)
                )
            targets = tuple(resolved)

    frames: list[pd.DataFrame] = []
    receipts: list[MaterializedResource] = []
    for target_id, target_url, target_format, target_payload, target_hash in targets:
        frame = normalize_resource_payload(
            adapter,
            target_payload,
            format_name=target_format,
            resource_id=target_id,
            maximum_observation_date=maximum_observation_date,
            resource_metadata=resource_metadata,
        )
        frames.append(frame)
        receipts.append(
            MaterializedResource(
                resource_id=target_id,
                url=target_url,
                raw_sha256=target_hash,
                raw_byte_count=len(target_payload),
                row_count=len(frame),
                minimum_date=frame["date"].min().date().isoformat(),
                maximum_date=frame["date"].max().date().isoformat(),
                normalized_sha256=_frame_hash(frame),
            )
        )
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if len(receipts) == 1:
        return combined, receipts[0]
    aggregate = MaterializedResource(
        resource_id=resource_id,
        url=url,
        raw_sha256=hashlib.sha256(
            "".join(row.raw_sha256 for row in receipts).encode("ascii")
        ).hexdigest(),
        raw_byte_count=sum(row.raw_byte_count for row in receipts),
        row_count=len(combined),
        minimum_date=combined["date"].min().date().isoformat(),
        maximum_date=combined["date"].max().date().isoformat(),
        normalized_sha256=_frame_hash(combined),
    )
    return combined, aggregate


def materialize_primary_sources(
    contract: FreeDataContract,
    source_plan: Mapping[str, SourcePlanItem],
    *,
    output_dir: Path,
    cache_dir: Path,
) -> Mapping[str, Any]:
    """Download every non-derived source and record all parse/coverage failures."""

    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise MaterializationError("GITHUB_ACTIONS_ONLY")
    normalized_dir = output_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "contract_sha256": contract.sha256,
        "maximum_observation_date": contract.boundaries.evaluation_end.isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "datasets": {},
    }
    _write_report(report, output_dir)
    for dataset_id in sorted(source_plan):
        item = source_plan[dataset_id]
        print(f"MATERIALIZE_DATASET_START:{dataset_id}", flush=True)
        if item.acquisition_kind in {"existing", "derived"}:
            report["datasets"][dataset_id] = {
                "status": f"awaiting_{item.acquisition_kind}_materialization"
            }
            _write_report(report, output_dir)
            print(f"MATERIALIZE_DATASET_AWAITING:{dataset_id}", flush=True)
            continue
        frames: list[pd.DataFrame] = []
        receipts: list[MaterializedResource] = []
        failures: list[str] = []
        for resource in item.resources:
            for resource_id, url, format_name, resource_metadata in _expand_resource(resource):
                try:
                    frame, receipt = _normalize_download(
                        dataset_id=dataset_id,
                        adapter=item.adapter,
                        resource_id=resource_id,
                        url=url,
                        format_name=format_name,
                        resource_metadata=resource_metadata,
                        maximum_observation_date=item.maximum_observation_date.isoformat(),
                        cache_dir=cache_dir,
                    )
                    frames.append(frame)
                    receipts.append(receipt)
                except Exception as exc:
                    failures.append(f"{resource_id}:{type(exc).__name__}:{exc}")
        if failures or not frames:
            report["datasets"][dataset_id] = {
                "status": "failed",
                "failures": failures or ["NO_NORMALIZED_RESOURCES"],
                "resources": [asdict(row) for row in receipts],
            }
            _write_report(report, output_dir)
            print(
                f"MATERIALIZE_DATASET_FAILED:{dataset_id}:{'|'.join(failures)[:500]}",
                flush=True,
            )
            continue
        combined = pd.concat(frames, ignore_index=True, sort=False)
        combined = combined.loc[combined["date"].notna()].sort_values("date", kind="mergesort")
        minimum = combined["date"].min().date()
        maximum = combined["date"].max().date()
        coverage_valid = coverage_spans_research_window(
            minimum_date=minimum,
            maximum_date=maximum,
            search_start=contract.boundaries.search_start,
            evaluation_end=contract.boundaries.evaluation_end,
            evaluation_end_tolerance_days=100 if dataset_id == "D_SPF" else 31,
        )
        target = normalized_dir / f"{dataset_id}.parquet"
        combined = parquet_safe_frame(combined)
        combined.to_parquet(target, index=False)
        report["datasets"][dataset_id] = {
            "status": "ready" if coverage_valid else "failed",
            "coverage_valid": coverage_valid,
            "row_count": len(combined),
            "minimum_date": minimum.isoformat(),
            "maximum_date": maximum.isoformat(),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "resources": [asdict(row) for row in receipts],
            "failures": [] if coverage_valid else ["SEARCH_OR_EVALUATION_COVERAGE_GAP"],
        }
        _write_report(report, output_dir)
        print(
            f"MATERIALIZE_DATASET_DONE:{dataset_id}:{report['datasets'][dataset_id]['status']}",
            flush=True,
        )
    ready = all(
        row.get("status") in {"ready", "awaiting_existing_materialization", "awaiting_derived_materialization"}
        for row in report["datasets"].values()
    )
    report["primary_sources_ready"] = ready
    _write_report(report, output_dir)
    return report
