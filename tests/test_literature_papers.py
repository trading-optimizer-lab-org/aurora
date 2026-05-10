"""Tests for R174 PaperRecord + PaperRegistry (registry round-trip + persistence)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from aurora.research.literature import (
    EXTRACTION_STATUSES,
    PaperRecord,
    PaperRegistry,
)


def _make_record(
    *,
    paper_id: str = "paper-aaa111",
    title: str = "Cross-sectional momentum study",
    content_hash: str = "a" * 64,
    extraction_status: str = "text_extracted",
) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        title=title,
        authors=("Doe", "Smith"),
        year=2020,
        source="local_text_fixture",
        url_or_path="/tmp/example.txt",
        doi=None,
        ssrn_id=None,
        licence_note="fixture",
        ingestion_time="2026-05-10T00:00:00Z",
        content_hash=content_hash,
        extraction_status=extraction_status,
        page_count=5,
    )


def test_paper_record_rejects_empty_title() -> None:
    with pytest.raises(ValueError, match="title"):
        _make_record(title="")


def test_paper_record_rejects_invalid_extraction_status() -> None:
    with pytest.raises(ValueError, match="extraction_status"):
        _make_record(extraction_status="not_a_status")


def test_extraction_statuses_enumerated() -> None:
    expected = {
        "raw", "text_extracted", "claims_extracted", "scored", "failed",
    }
    assert expected == set(EXTRACTION_STATUSES)


def test_registry_register_and_get_round_trip() -> None:
    registry = PaperRegistry()
    record = _make_record()
    registry.register(record)
    assert registry.has(record.paper_id)
    assert registry.get(record.paper_id) == record


def test_registry_duplicate_register_raises() -> None:
    registry = PaperRegistry()
    record = _make_record()
    registry.register(record)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(record)


def test_registry_list_papers_sorted_by_ingestion_time() -> None:
    registry = PaperRegistry()
    early = _make_record(paper_id="paper-xxx111", content_hash="b" * 64)
    late = PaperRecord(
        paper_id="paper-yyy222",
        title="Later paper",
        authors=(),
        year=2021,
        source="local_text_fixture",
        url_or_path="/tmp/late.txt",
        doi=None,
        ssrn_id=None,
        licence_note="",
        ingestion_time="2026-06-01T00:00:00Z",
        content_hash="c" * 64,
        extraction_status="text_extracted",
        page_count=1,
    )
    # Register out-of-order to check the sort behaviour.
    registry.register(late)
    registry.register(early)
    listed = registry.list_papers()
    assert [p.paper_id for p in listed] == [
        early.paper_id,
        late.paper_id,
    ]


def test_registry_jsonl_round_trip(tmp_path: Path) -> None:
    registry = PaperRegistry()
    r1 = _make_record(paper_id="paper-aaa111", content_hash="a" * 64)
    r2 = _make_record(paper_id="paper-bbb222", content_hash="b" * 64)
    registry.register(r1)
    registry.register(r2)

    out = tmp_path / "papers.jsonl"
    registry.save(out)

    loaded = PaperRegistry.load(out)
    assert len(loaded) == 2
    assert loaded.get("paper-aaa111") == r1
    assert loaded.get("paper-bbb222") == r2


def test_registry_load_missing_file_returns_empty(tmp_path: Path) -> None:
    loaded = PaperRegistry.load(tmp_path / "does-not-exist.jsonl")
    assert len(loaded) == 0
    assert loaded.list_papers() == []


def test_content_hash_deterministic_for_same_bytes(tmp_path: Path) -> None:
    """Re-ingesting identical bytes must produce the same hash + paper_id."""
    from aurora.research.literature import ingest_text_fixture
    src = tmp_path / "same.txt"
    src.write_text("Deterministic content.\nLine 2.\n", encoding="utf-8")

    rec1, _t1 = ingest_text_fixture(src)
    rec2, _t2 = ingest_text_fixture(src)

    expected = hashlib.sha256(src.read_bytes()).hexdigest()
    assert rec1.content_hash == expected
    assert rec2.content_hash == expected
    assert rec1.paper_id == rec2.paper_id


def test_paper_record_to_dict_round_trip() -> None:
    record = _make_record()
    payload = record.to_dict()
    rebuilt = PaperRecord.from_dict(payload)
    assert rebuilt == record


def test_paper_record_authors_must_be_tuple() -> None:
    with pytest.raises(TypeError, match="authors"):
        PaperRecord(
            paper_id="paper-bad-list",
            title="bad",
            authors=["should", "be", "tuple"],  # type: ignore[arg-type]
            year=2020,
            source="local_text_fixture",
            url_or_path="/tmp/x.txt",
            doi=None,
            ssrn_id=None,
            licence_note="",
            ingestion_time="2026-05-10T00:00:00Z",
            content_hash="d" * 64,
            extraction_status="raw",
            page_count=1,
        )
