from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pytest
import yaml

from scripts import build_literature_pdf_manifest as manifest
from scripts import extract_literature_pdf_text_chunk as extract
from scripts import extract_literature_strategy_rules_from_text as exactness
from scripts import merge_literature_pdf_text_chunks as merge


def test_manifest_resolves_openalex_pdf_urls() -> None:
    raw = {
        "content_urls": {"pdf": "https://content.openalex.org/works/W1.pdf"},
        "best_oa_location": {"pdf_url": "https://example.org/best.pdf"},
        "locations": [{"pdf_url": "https://example.org/location.pdf"}],
    }
    study = {
        "raw_json": json.dumps(raw),
        "oa_url": "https://example.org/article",
    }

    assert manifest.openalex_primary_pdf_url(study) == "https://content.openalex.org/works/W1.pdf"
    assert manifest.candidate_pdf_urls(study) == [
        "https://content.openalex.org/works/W1.pdf",
        "https://example.org/best.pdf",
        "https://example.org/location.pdf",
    ]


def test_manifest_uses_oa_url_when_it_looks_like_pdf() -> None:
    study = {"raw_json": "{}", "oa_url": "https://journal.example/articlepdf/123"}

    assert manifest.candidate_pdf_urls(study) == ["https://journal.example/articlepdf/123"]


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def iter_content(self, chunk_size: int = 1) -> list[bytes]:
        return self._chunks


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def get(self, *_: object, **__: object) -> FakeResponse:
        return self.response


def test_download_pdf_rejects_html() -> None:
    response = FakeResponse(
        headers={"content-type": "text/html"},
        chunks=[b"<!doctype html><html>not a pdf</html>"],
    )

    status, payload, used_url, error = extract.download_pdf(
        ["https://example.org/paper"],
        timeout_seconds=1,
        max_bytes=1024 * 1024,
        retries=0,
        session=FakeSession(response),
    )

    assert status == "not_pdf"
    assert payload is None
    assert used_url == ""
    assert "HTML" in error


def test_download_pdf_rejects_too_large_before_download() -> None:
    response = FakeResponse(
        headers={"content-type": "application/pdf", "content-length": str(81 * 1024 * 1024)},
        chunks=[],
    )

    status, payload, _, error = extract.download_pdf(
        ["https://example.org/paper.pdf"],
        timeout_seconds=1,
        max_bytes=80 * 1024 * 1024,
        retries=0,
        session=FakeSession(response),
    )

    assert status == "too_large"
    assert payload is None
    assert "exceeds" in error


def test_download_pdf_classifies_non_requests_exception() -> None:
    class BrokenSession:
        def get(self, *_: object, **__: object) -> FakeResponse:
            raise UnicodeDecodeError("utf-8", b"\xf1", 0, 1, "bad redirect")

    status, payload, _, error = extract.download_pdf(
        ["https://example.org/bad-redirect"],
        timeout_seconds=1,
        max_bytes=80 * 1024 * 1024,
        retries=0,
        session=BrokenSession(),
    )

    assert status == "download_failed"
    assert payload is None
    assert "UnicodeDecodeError" in error


def test_process_row_marks_short_text_as_scanned_and_keeps_no_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_download(*_: object, **__: object) -> tuple[str, bytes, str, str]:
        return "text_extracted", b"%PDF short", "https://example.org/paper.pdf", ""

    def fake_extract(payload: bytes, tmp_dir: Path) -> tuple[str, int, str]:
        pdf_path = tmp_dir / "temporary.pdf"
        pdf_path.write_bytes(payload)
        pdf_path.unlink()
        return "too short", 1, "a" * 64

    monkeypatch.setattr(extract, "download_pdf", fake_download)
    monkeypatch.setattr(extract, "extract_pdf_text", fake_extract)

    text_row, status_row, _, _ = extract.process_row(
        {
            "study_id": "W1",
            "idea_id": "lit_w1_momentum",
            "candidate_pdf_urls_json": json.dumps(["https://example.org/paper.pdf"]),
            "study_title": "Paper",
            "study_year": "2020",
        },
        timeout_seconds=1,
        max_bytes=1024,
        retries=0,
        text_max_chars=250_000,
        tmp_root=tmp_path,
    )

    assert status_row["status"] == "maybe_scanned_pdf"
    assert status_row["pdf_kept"] == "false"
    assert text_row is not None
    assert not list(tmp_path.rglob("*.pdf"))


def test_jsonl_writer_replaces_invalid_unicode(tmp_path: Path) -> None:
    out = tmp_path / "bad_unicode.jsonl.zst"

    codec = extract.write_jsonl_zst(out, [{"text": "bad\ud800char"}])

    assert codec in {"zstd", "plain_fallback"}
    assert out.exists()


def test_merge_reader_handles_unicode_line_separator_inside_json(tmp_path: Path) -> None:
    path = tmp_path / "chunk_000_text.jsonl.zst"
    path.write_text('{"study_id":"W1","text":"alpha\u2028beta"}\n', encoding="utf-8")

    rows, errors = merge.read_jsonl_zst(path)

    assert errors == []
    assert rows == [{"study_id": "W1", "text": "alpha\u2028beta"}]


def test_exactness_does_not_claim_exact_when_required_fields_missing() -> None:
    row = {
        "study_id": "W1",
        "idea_id": "lit_w1_momentum",
        "strategy_family": "momentum",
        "text": "The strategy uses a momentum signal and ranks stocks by a factor.",
    }

    out = exactness.classify_text(row)

    assert out["paper_exact_replication"] == "0"
    assert out["exactness_status"] in {"template_replicable", "needs_review"}
    assert "frequency" in json.loads(out["missing_fields_json"])


def test_merge_fails_if_too_many_chunks_missing(tmp_path: Path) -> None:
    status = tmp_path / "chunk_000_status.csv"
    with status.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["study_id", "status", "locked_opened", "pdf_kept"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "study_id": "W1",
                "status": "text_extracted",
                "locked_opened": "false",
                "pdf_kept": "false",
            }
        )

    args = argparse.Namespace(
        input_dir=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        expected_chunks=299,
        source_ideas=1,
        max_missing_chunk_ratio=0.02,
        fail_on_partial=False,
    )

    with pytest.raises(ValueError, match="missing chunk ratio"):
        merge.merge(args)


def test_workflow_shape() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/literature-pdf-text-extract-29855.yml").read_text(
            encoding="utf-8"
        )
    )
    jobs = workflow["jobs"]

    assert jobs["extract_chunk_a"]["strategy"]["max-parallel"] == 154
    assert jobs["extract_chunk_b"]["strategy"]["max-parallel"] == 26
    assert (
        jobs["extract_chunk_a"]["strategy"]["max-parallel"]
        + jobs["extract_chunk_b"]["strategy"]["max-parallel"]
        == 180
    )
    merge_step = next(
        step for step in jobs["merge_text"]["steps"] if step.get("name") == "Merge text chunks"
    )
    assert "--expected-chunks 299" in merge_step["run"]
    assert "--source-ideas 29855" in merge_step["run"]
