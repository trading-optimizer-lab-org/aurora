"""Download one chunk of literature PDFs, extract text, and delete PDFs."""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests


STATUSES = {
    "text_extracted",
    "download_failed",
    "not_pdf",
    "paywalled_or_forbidden",
    "too_large",
    "maybe_scanned_pdf",
    "parse_failed",
    "no_pdf_url",
}
MAX_QUOTE_CHARS = 240

CLAIM_PATTERNS = {
    "asset_class": re.compile(
        r"\b(stocks?|equities|bonds?|commodit(?:y|ies)|currenc(?:y|ies)|forex|FX|ETF|futures?|crypto|bitcoin)\b",
        re.I,
    ),
    "frequency": re.compile(r"\b(daily|weekly|monthly|quarterly|intraday)\b", re.I),
    "signal": re.compile(
        r"\b(momentum|reversal|carry|value|quality|volatility|trend|moving average|factor|signal|rank)\b",
        re.I,
    ),
    "costs": re.compile(r"\b(transaction costs?|commissions?|slippage|net of costs|gross of costs)\b", re.I),
    "sample_period": re.compile(r"\b(19\d{2}|20\d{2})\s*[-–—to/]+\s*(19\d{2}|20\d{2})\b"),
}


def _zstd_available() -> bool:
    try:
        import zstandard  # noqa: F401

        return True
    except ImportError:
        return False


def write_jsonl_zst(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(sanitize_json(row), ensure_ascii=False) + "\n" for row in rows
    ).encode("utf-8", errors="replace")
    if _zstd_available():
        import zstandard as zstd

        path.write_bytes(zstd.ZstdCompressor(level=6).compress(payload))
        return "zstd"
    path.write_bytes(payload)
    return "plain_fallback"


def read_manifest(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def chunk_rows(rows: list[dict[str, str]], chunk_index: int, chunk_size: int) -> list[dict[str, str]]:
    start = int(chunk_index) * int(chunk_size)
    return rows[start : start + int(chunk_size)]


def sanitize_text(value: str) -> str:
    return value.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def sanitize_json(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {str(key): sanitize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json(item) for item in value]
    return value


def parse_candidate_urls(row: dict[str, str]) -> list[str]:
    raw = row.get("candidate_pdf_urls_json") or "[]"
    try:
        urls = json.loads(raw)
    except json.JSONDecodeError:
        urls = []
    if not isinstance(urls, list):
        urls = []
    return [str(url).strip() for url in urls if str(url).strip()]


def _is_forbidden(status_code: int) -> bool:
    return status_code in {401, 402, 403, 407, 451}


def _looks_html(payload: bytes) -> bool:
    prefix = payload[:512].lstrip().lower()
    return prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html")


def _looks_pdf(payload: bytes, content_type: str) -> bool:
    return payload.startswith(b"%PDF") or "pdf" in (content_type or "").lower()


def download_pdf(
    urls: list[str],
    *,
    timeout_seconds: float,
    max_bytes: int,
    retries: int,
    session: requests.Session | None = None,
) -> tuple[str, bytes | None, str, str]:
    if not urls:
        return "no_pdf_url", None, "", "no candidate PDF URL"
    client = session or requests.Session()
    headers = {"User-Agent": "Aurora literature PDF extractor/1.0"}
    last_error = ""
    for url in urls:
        for attempt in range(max(1, retries + 1)):
            try:
                with client.get(url, stream=True, timeout=timeout_seconds, headers=headers) as response:
                    if _is_forbidden(response.status_code):
                        last_error = f"{response.status_code} forbidden"
                        break
                    if response.status_code >= 400:
                        last_error = f"HTTP {response.status_code}"
                        continue
                    length = response.headers.get("content-length")
                    if length and length.isdigit() and int(length) > max_bytes:
                        return "too_large", None, url, f"content-length {length} exceeds {max_bytes}"
                    content_type = response.headers.get("content-type", "")
                    buffer = io.BytesIO()
                    for part in response.iter_content(chunk_size=1024 * 256):
                        if not part:
                            continue
                        buffer.write(part)
                        if buffer.tell() > max_bytes:
                            return "too_large", None, url, f"download exceeds {max_bytes}"
                    payload = buffer.getvalue()
                    if _looks_html(payload):
                        last_error = "HTML response"
                        continue
                    if not _looks_pdf(payload, content_type):
                        last_error = f"not PDF content-type={content_type}"
                        continue
                    return "text_extracted", payload, url, ""
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < retries:
                    time.sleep(min(2.0, 0.25 * (attempt + 1)))
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < retries:
                    time.sleep(min(2.0, 0.25 * (attempt + 1)))
    if "forbidden" in last_error:
        return "paywalled_or_forbidden", None, "", last_error
    if "HTML response" in last_error or "not PDF" in last_error:
        return "not_pdf", None, "", last_error
    return "download_failed", None, "", last_error or "download failed"


def extract_pdf_text(payload: bytes, tmp_dir: Path) -> tuple[str, int, str]:
    pdf_hash = hashlib.sha256(payload).hexdigest()
    path = tmp_dir / f"{pdf_hash}.pdf"
    path.write_bytes(payload)
    try:
        try:
            import pypdf

            reader = pypdf.PdfReader(str(path))
            chunks: list[str] = []
            for page in reader.pages:
                try:
                    chunks.append(page.extract_text() or "")
                except Exception:
                    chunks.append("")
            return "\n\n".join(chunks).strip(), len(reader.pages), pdf_hash
        except ImportError:
            return payload.decode("utf-8", errors="ignore"), max(1, payload.count(b"/Page")), pdf_hash
    finally:
        path.unlink(missing_ok=True)


def _claim_quote(text: str, match: re.Match[str]) -> str:
    left = max(0, match.start() - 90)
    right = min(len(text), match.end() + 90)
    return re.sub(r"\s+", " ", text[left:right]).strip()[:MAX_QUOTE_CHARS]


def extract_basic_claims(row: dict[str, str], text: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    study_id = row.get("study_id") or ""
    idea_id = row.get("idea_id") or ""
    for claim_type, regex in CLAIM_PATTERNS.items():
        seen: set[str] = set()
        for match in regex.finditer(text):
            value = match.group(0).strip()
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            digest = hashlib.sha256(f"{study_id}|{idea_id}|{claim_type}|{key}".encode("utf-8")).hexdigest()[:12]
            claims.append(
                {
                    "claim_id": f"{study_id}-{claim_type}-{digest}",
                    "study_id": study_id,
                    "idea_id": idea_id,
                    "strategy_family": row.get("strategy_family", ""),
                    "claim_type": claim_type,
                    "claim_value": value,
                    "quote_excerpt": _claim_quote(text, match),
                    "locked_opened": False,
                    "extractor": "basic_regex_v1",
                }
            )
            if len(seen) >= 5:
                break
    return claims


def process_row(
    row: dict[str, str],
    *,
    timeout_seconds: float,
    max_bytes: int,
    retries: int,
    text_max_chars: int,
    tmp_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    urls = parse_candidate_urls(row)
    status, payload, used_url, error = download_pdf(
        urls,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        retries=retries,
    )
    text = ""
    pdf_hash = ""
    pages = 0
    if payload is not None and status == "text_extracted":
        try:
            with tempfile.TemporaryDirectory(dir=tmp_root) as tmp:
                text, pages, pdf_hash = extract_pdf_text(payload, Path(tmp))
        except Exception as exc:
            status = "parse_failed"
            error = f"{type(exc).__name__}: {exc}"
        if status == "text_extracted" and len(text.strip()) < 1000:
            status = "maybe_scanned_pdf"
            error = "extracted text shorter than 1000 characters"
    status_row = {
        "study_id": row.get("study_id", ""),
        "idea_id": row.get("idea_id", ""),
        "strategy_family": row.get("strategy_family", ""),
        "status": status,
        "used_url": used_url,
        "pdf_hash": pdf_hash,
        "text_chars": len(text),
        "page_count": pages,
        "candidate_url_count": len(urls),
        "error": error,
        "locked_opened": "false",
        "pdf_kept": "false",
    }
    error_row = None if status in {"text_extracted", "maybe_scanned_pdf"} else status_row.copy()
    text_row = None
    claims: list[dict[str, Any]] = []
    if text and status in {"text_extracted", "maybe_scanned_pdf"}:
        trimmed = text[:text_max_chars]
        text_row = {
            "study_id": row.get("study_id", ""),
            "idea_id": row.get("idea_id", ""),
            "strategy_family": row.get("strategy_family", ""),
            "title": row.get("study_title", ""),
            "doi": row.get("doi", ""),
            "used_url": used_url,
            "pdf_hash": pdf_hash,
            "text": trimmed,
            "text_chars_original": len(text),
            "text_chars_stored": len(trimmed),
            "page_count": pages,
            "extraction_status": status,
            "locked_opened": False,
        }
        try:
            claims = extract_basic_claims(row, trimmed)
        except Exception as exc:
            status_row["claims_error"] = f"{type(exc).__name__}: {exc}"
    return text_row, status_row, claims, error_row


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: sanitize_json(row.get(field, "")) for field in fields})


def run_chunk(args: argparse.Namespace) -> dict[str, Any]:
    rows = chunk_rows(read_manifest(Path(args.manifest)), args.chunk_index, args.chunk_size)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_root = out_dir / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    text_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    claim_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    max_bytes = int(float(args.max_pdf_mb) * 1024 * 1024)
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(args.pdfs_per_job_concurrency)) as executor:
        futures = {
            executor.submit(
                process_row,
                row,
                timeout_seconds=float(args.timeout_seconds),
                max_bytes=max_bytes,
                retries=int(args.retry_failed_downloads),
                text_max_chars=int(args.text_max_chars),
                tmp_root=tmp_root,
            ): row
            for row in rows
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                text_row, status_row, claims, error_row = future.result()
            except Exception as exc:
                row = futures[future]
                status_row = {
                    "study_id": row.get("study_id", ""),
                    "idea_id": row.get("idea_id", ""),
                    "strategy_family": row.get("strategy_family", ""),
                    "status": "download_failed",
                    "used_url": "",
                    "pdf_hash": "",
                    "text_chars": 0,
                    "page_count": 0,
                    "candidate_url_count": len(parse_candidate_urls(row)),
                    "error": f"worker exception {type(exc).__name__}: {exc}",
                    "locked_opened": "false",
                    "pdf_kept": "false",
                }
                text_row = None
                claims = []
                error_row = status_row.copy()
            if text_row:
                text_rows.append(text_row)
            status_rows.append(status_row)
            claim_rows.extend(claims)
            if error_row:
                error_rows.append(error_row)
    chunk = int(args.chunk_index)
    codec = write_jsonl_zst(out_dir / f"chunk_{chunk:03d}_text.jsonl.zst", text_rows)
    write_csv(
        out_dir / f"chunk_{chunk:03d}_status.csv",
        status_rows,
        [
            "study_id",
            "idea_id",
            "strategy_family",
            "status",
            "used_url",
            "pdf_hash",
            "text_chars",
            "page_count",
            "candidate_url_count",
            "error",
            "locked_opened",
            "pdf_kept",
            "claims_error",
        ],
    )
    write_csv(
        out_dir / f"chunk_{chunk:03d}_errors.csv",
        error_rows,
        [
            "study_id",
            "idea_id",
            "strategy_family",
            "status",
            "used_url",
            "pdf_hash",
            "text_chars",
            "page_count",
            "candidate_url_count",
            "error",
            "locked_opened",
            "pdf_kept",
        ],
    )
    claims_path = out_dir / f"chunk_{chunk:03d}_claims.jsonl"
    claims_payload = "".join(
        json.dumps(sanitize_json(row), ensure_ascii=False) + "\n" for row in claim_rows
    )
    claims_path.write_bytes(claims_payload.encode("utf-8", errors="replace"))
    shutil.rmtree(tmp_root, ignore_errors=True)
    summary = {
        "chunk_index": chunk,
        "input_rows": len(rows),
        "text_rows": len(text_rows),
        "status_rows": len(status_rows),
        "error_rows": len(error_rows),
        "claim_rows": len(claim_rows),
        "compression": codec,
        "locked_opened": False,
        "pdfs_kept": False,
    }
    (out_dir / f"chunk_{chunk:03d}_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--chunk-index", type=int, required=True)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--max-pdf-mb", type=float, default=80)
    parser.add_argument("--retry-failed-downloads", type=int, default=2)
    parser.add_argument("--pdfs-per-job-concurrency", type=int, default=2)
    parser.add_argument("--text-max-chars", type=int, default=250_000)
    parser.add_argument("--keep-pdfs", action="store_true")
    args = parser.parse_args(argv)
    if args.keep_pdfs:
        raise ValueError("keep_pdfs is forbidden for this pipeline")
    summary = run_chunk(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
