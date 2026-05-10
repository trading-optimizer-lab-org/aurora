"""Tests for R174 ingestion paths (.txt fixtures, missing files, bad ext)."""
from __future__ import annotations

from pathlib import Path

import pytest
from aurora.research.literature import (
    ingest_pdf,
    ingest_text_fixture,
)

FIXTURES = Path(__file__).parent / "fixtures" / "literature"


def test_text_fixture_round_trip() -> None:
    record, text = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    assert record.paper_id.startswith("paper-")
    assert record.source == "local_text_fixture"
    assert record.extraction_status == "text_extracted"
    assert "S&P 500" in text


def test_text_fixture_paper_id_is_stable_across_calls() -> None:
    a, _ = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    b, _ = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    assert a.paper_id == b.paper_id
    assert a.content_hash == b.content_hash


def test_text_fixture_distinct_files_have_distinct_paper_ids() -> None:
    a, _ = ingest_text_fixture(FIXTURES / "sample_paper.txt")
    b, _ = ingest_text_fixture(FIXTURES / "red_flag_paper.txt")
    assert a.paper_id != b.paper_id
    assert a.content_hash != b.content_hash


def test_nonexistent_path_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-file.txt"
    with pytest.raises(FileNotFoundError):
        ingest_text_fixture(missing)


def test_unsupported_extension_for_text_raises(tmp_path: Path) -> None:
    f = tmp_path / "thing.csv"
    f.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported extension"):
        ingest_text_fixture(f)


def test_unsupported_extension_for_pdf_raises(tmp_path: Path) -> None:
    f = tmp_path / "thing.txt"
    f.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported extension"):
        ingest_pdf(f)


def test_ingest_pdf_nonexistent_path_raises(tmp_path: Path) -> None:
    missing = tmp_path / "no-such.pdf"
    with pytest.raises(FileNotFoundError):
        ingest_pdf(missing)


def test_empty_fixture_status_raw() -> None:
    """An effectively empty fixture must come back with status 'raw'."""
    record, text = ingest_text_fixture(FIXTURES / "empty_paper.txt")
    assert text.strip() == ""
    assert record.extraction_status == "raw"
    assert record.page_count == 0
