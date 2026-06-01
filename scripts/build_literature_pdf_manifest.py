"""Build a PDF download manifest for Aurora literature ideas.

The script accepts either the Aurora import manifest created from literature
ideas or the raw `strategy_ideas_all.csv` exported by the literature corpus
workflow. Study metadata should come from `studies_all.csv` when available so
PDF URLs can be resolved from OpenAlex raw JSON.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


PDF_HINTS = (".pdf", "/pdf", "pdfdirect", "articlepdf")
DEFAULT_SOURCE_RUN_ID = "26638765315"


def looks_like_pdf_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(hint in lower for hint in PDF_HINTS)


def study_id_from_idea_id(idea_id: str) -> str:
    match = re.match(r"lit_(w\d+)_", (idea_id or "").lower())
    return match.group(1).upper() if match else ""


def load_studies(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not path or not path.exists():
        return out
    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            study_id = str(row.get("study_id") or row.get("openalex_id") or "").strip()
            if study_id:
                out[study_id.upper()] = row
                out[study_id.lower()] = row
    return out


def _walk_pdf_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        content_urls = value.get("content_urls")
        if isinstance(content_urls, dict) and isinstance(content_urls.get("pdf"), str):
            urls.append(content_urls["pdf"])
        best = value.get("best_oa_location")
        if isinstance(best, dict) and isinstance(best.get("pdf_url"), str):
            urls.append(best["pdf_url"])
        for location in value.get("locations") or ():
            if isinstance(location, dict) and isinstance(location.get("pdf_url"), str):
                urls.append(location["pdf_url"])
        for child in value.values():
            if isinstance(child, (dict, list)):
                urls.extend(_walk_pdf_urls(child))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_walk_pdf_urls(item))
    return urls


def raw_json_to_pdf_urls(raw_json: str) -> list[str]:
    if not raw_json:
        return []
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    return _dedupe(_walk_pdf_urls(payload))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = (value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def openalex_primary_pdf_url(study: dict[str, str]) -> str:
    urls = raw_json_to_pdf_urls(study.get("raw_json", ""))
    return urls[0] if urls else ""


def candidate_pdf_urls(study: dict[str, str]) -> list[str]:
    urls = raw_json_to_pdf_urls(study.get("raw_json", ""))
    oa_url = str(study.get("oa_url") or "").strip()
    if oa_url and looks_like_pdf_url(oa_url):
        urls.append(oa_url)
    return _dedupe(urls)


def infer_priority_bucket(row: dict[str, str]) -> str:
    value = row.get("soft_bucket") or row.get("priority_bucket") or ""
    if value:
        return value
    status = row.get("status") or row.get("data_status") or ""
    if status == "ready_to_test":
        return "A_prioridad_alta"
    if status == "pending_data":
        return "B_prioridad_media"
    return "C_revision_blanda"


def iter_idea_rows(path: Path, *, include_all: bool = False) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            supported = str(row.get("aurora_supported", "")).strip().lower() in {
                "1",
                "true",
                "yes",
            }
            ready = (row.get("status") or row.get("data_status")) == "ready_to_test"
            if include_all or (supported and ready):
                rows.append(row)
    return rows


def build_manifest_rows(
    ideas: list[dict[str, str]],
    studies: dict[str, dict[str, str]],
    *,
    source_run_id: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for idea in ideas:
        study_id = str(idea.get("study_id") or "").strip()
        if not study_id:
            study_id = study_id_from_idea_id(str(idea.get("idea_id") or ""))
        study = studies.get(study_id.upper()) or studies.get(study_id.lower()) or {}
        urls = candidate_pdf_urls(study)
        oa_url = str(study.get("oa_url") or idea.get("oa_url") or "").strip()
        if oa_url and looks_like_pdf_url(oa_url):
            urls = _dedupe([*urls, oa_url])
        pdf_status = "pdf_url_ready" if urls else "needs_indirect_resolution"
        rows.append(
            {
                "study_id": study_id,
                "idea_id": str(idea.get("idea_id") or ""),
                "strategy_family": str(idea.get("strategy_family") or ""),
                "study_title": str(idea.get("study_title") or study.get("title") or ""),
                "doi": str(study.get("doi") or idea.get("doi") or ""),
                "oa_url": oa_url,
                "openalex_pdf_url": openalex_primary_pdf_url(study),
                "candidate_pdf_urls_json": json.dumps(urls, ensure_ascii=False),
                "priority_bucket": infer_priority_bucket(idea),
                "paper_exact_replication": "0",
                "source_run_id": source_run_id,
                "pdf_resolution_status": pdf_status,
                "study_year": str(idea.get("study_year") or study.get("year") or ""),
                "study_venue": str(idea.get("study_venue") or study.get("venue") or ""),
            }
        )
    return rows


def write_manifest(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "study_id",
        "idea_id",
        "strategy_family",
        "study_title",
        "doi",
        "oa_url",
        "openalex_pdf_url",
        "candidate_pdf_urls_json",
        "priority_bucket",
        "paper_exact_replication",
        "source_run_id",
        "pdf_resolution_status",
        "study_year",
        "study_venue",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ideas-csv", required=True)
    parser.add_argument("--studies-csv", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-run-id", default=DEFAULT_SOURCE_RUN_ID)
    parser.add_argument("--include-all", action="store_true")
    args = parser.parse_args(argv)

    ideas = iter_idea_rows(Path(args.ideas_csv), include_all=args.include_all)
    studies = load_studies(Path(args.studies_csv)) if args.studies_csv else {}
    rows = build_manifest_rows(ideas, studies, source_run_id=args.source_run_id)
    write_manifest(rows, Path(args.output))
    summary = {
        "ideas_input": len(ideas),
        "manifest_rows": len(rows),
        "with_pdf_url": sum(1 for row in rows if row["candidate_pdf_urls_json"] != "[]"),
        "needs_indirect_resolution": sum(
            1 for row in rows if row["pdf_resolution_status"] == "needs_indirect_resolution"
        ),
        "source_run_id": args.source_run_id,
        "output": args.output,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
