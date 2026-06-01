"""Merge literature PDF text extraction chunks."""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path
from typing import Any


def read_jsonl_zst(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = path.read_bytes()
    try:
        if data.startswith(b"\x28\xb5\x2f\xfd"):
            import zstandard as zstd

            raw = zstd.ZstdDecompressor().decompress(data)
        else:
            raw = data
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = data.decode("utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                {
                    "path": str(path),
                    "line_number": line_number,
                    "error": f"{type(exc).__name__}: {exc}",
                    "line_prefix": line[:500],
                }
            )
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
        else:
            errors.append(
                {
                    "path": str(path),
                    "line_number": line_number,
                    "error": "non-dict jsonl row",
                    "line_prefix": line[:500],
                }
            )
    return rows, errors


def write_jsonl_zst(path: Path, rows: list[dict[str, Any]]) -> str:
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode(
        "utf-8",
        errors="replace",
    )
    try:
        import zstandard as zstd

        path.write_bytes(zstd.ZstdCompressor(level=9).compress(payload))
        return "zstd"
    except ImportError:
        path.write_bytes(payload)
        return "plain_fallback"


def read_csvs(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    csv.field_size_limit(sys.maxsize)
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def merge(args: argparse.Namespace) -> dict[str, Any]:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    text_paths = sorted(input_dir.rglob("chunk_*_text.jsonl.zst"))
    status_paths = sorted(input_dir.rglob("chunk_*_status.csv"))
    error_paths = sorted(input_dir.rglob("chunk_*_errors.csv"))
    claim_paths = sorted(input_dir.rglob("chunk_*_claims.jsonl"))
    expected = int(args.expected_chunks)
    if not status_paths:
        raise ValueError("no chunk status files found")
    missing_ratio = 1.0 - (len(status_paths) / expected)
    if missing_ratio > float(args.max_missing_chunk_ratio):
        raise ValueError(f"missing chunk ratio {missing_ratio:.4f} exceeds limit")
    text_rows: list[dict[str, Any]] = []
    merge_errors: list[dict[str, Any]] = []
    for path in text_paths:
        rows, errors = read_jsonl_zst(path)
        text_rows.extend(rows)
        merge_errors.extend(errors)
    status_rows = read_csvs(status_paths)
    error_rows = read_csvs(error_paths) if error_paths else []
    claim_lines: list[str] = []
    for path in claim_paths:
        claim_lines.extend(path.read_text(encoding="utf-8").splitlines())
    if any(str(row.get("locked_opened", "")).lower() not in {"false", "0", ""} for row in status_rows):
        raise ValueError("locked_opened must remain false")
    if any(str(row.get("pdf_kept", "")).lower() not in {"false", "0", ""} for row in status_rows):
        raise ValueError("pdf_kept must remain false")
    status_by_study: dict[str, dict[str, str]] = {}
    for row in status_rows:
        study_id = row.get("study_id", "")
        if study_id and study_id not in status_by_study:
            status_by_study[study_id] = row
    success_rows = [row for row in status_rows if row.get("status") == "text_extracted"]
    failure_rows = [row for row in status_rows if row.get("status") != "text_extracted"]
    codec = write_jsonl_zst(output_dir / "literature_full_text_corpus.jsonl.zst", text_rows)
    write_csv(output_dir / "literature_pdf_text_status.csv", list(status_by_study.values()))
    write_csv(output_dir / "literature_pdf_text_failures.csv", failure_rows)
    write_csv(output_dir / "literature_pdf_text_success.csv", success_rows)
    write_csv(output_dir / "literature_pdf_text_merge_errors.csv", merge_errors)
    (output_dir / "literature_pdf_text_claims.jsonl").write_text(
        "\n".join(line for line in claim_lines if line.strip()) + ("\n" if claim_lines else ""),
        encoding="utf-8",
    )
    write_csv(
        output_dir / "literature_pdf_text_manifest_resolved.csv",
        [
            {
                "study_id": row.get("study_id", ""),
                "idea_id": row.get("idea_id", ""),
                "status": row.get("status", ""),
                "used_url": row.get("used_url", ""),
                "pdf_hash": row.get("pdf_hash", ""),
            }
            for row in status_rows
        ],
    )
    source_ideas = int(args.source_ideas)
    partial = (
        len(status_paths) != expected
        or len(status_by_study) != source_ideas
        or bool(merge_errors)
    )
    summary = {
        "source_ideas": source_ideas,
        "chunks_expected": expected,
        "chunks_found": len(status_paths),
        "partial": bool(partial),
        "pdfs_kept": False,
        "locked_opened": False,
        "backtest_enabled": False,
        "exact_replication_claimed": False,
        "success_count": len(success_rows),
        "failure_count": len(failure_rows),
        "status_rows": len(status_rows),
        "unique_status_studies": len(status_by_study),
        "text_rows": len(text_rows),
        "claims_rows": len([line for line in claim_lines if line.strip()]),
        "merge_error_count": len(merge_errors),
        "compression": codec,
    }
    (output_dir / "literature_pdf_text_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if args.fail_on_partial and partial:
        raise ValueError(f"partial merge: {summary}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-chunks", type=int, default=299)
    parser.add_argument("--source-ideas", type=int, default=29_855)
    parser.add_argument("--max-missing-chunk-ratio", type=float, default=0.02)
    parser.add_argument("--fail-on-partial", action="store_true")
    args = parser.parse_args(argv)
    summary = merge(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
