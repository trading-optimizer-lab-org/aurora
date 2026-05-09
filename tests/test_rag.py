"""Tests for research.rag (R9)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from aurora.research.rag import ResearchIndex

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


@pytest.fixture
def populated_paths(tmp_path: Path):
    archive = tmp_path / "archive.jsonl"
    review = tmp_path / "review.jsonl"
    _write_jsonl(
        archive,
        [
            {
                "candidate_id": "C1",
                "spec": {"name": "MACross"},
                "stage": "archived",
                "rejection_reason": "oos_dev_failure",
                "rejection_detail": "lookahead leakage detected in feature pipeline",
                "timestamp_iso": "2026-01-15T10:00:00",
                "is_metrics": {"sharpe": 0.4},
            },
            {
                "candidate_id": "C2",
                "spec": {"name": "BollingerMR"},
                "stage": "archived",
                "rejection_reason": "is_drawdown_too_high",
                "rejection_detail": "drawdown 38% exceeded policy max",
                "timestamp_iso": "2026-02-20T10:00:00",
                "is_metrics": {"mdd": 0.38},
            },
            {
                "candidate_id": "C3",
                "spec": {"name": "TSMomentum"},
                "stage": "archived",
                "rejection_reason": "wf_instability",
                "rejection_detail": "walk-forward calmar variance high across windows",
                "timestamp_iso": "2026-03-10T10:00:00",
            },
        ],
    )
    _write_jsonl(
        review,
        [
            {
                "candidate_id": "Q1",
                "spec": {"name": "DonchianBreakout"},
                "stage": "review_queue",
                "rejection_reason": None,
                "rejection_detail": None,
                "timestamp_iso": "2026-04-01T10:00:00",
            },
        ],
    )
    return archive, review


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def test_index_loads_archive_and_review(populated_paths):
    archive, review = populated_paths
    idx = ResearchIndex.from_paths(archive, review)
    assert len(idx.records) == 4
    sources = {r.source for r in idx.records}
    assert sources == {"archive", "review_queue"}


def test_index_empty_paths_returns_empty(tmp_path):
    idx = ResearchIndex.from_paths(
        archive_path=tmp_path / "missing.jsonl",
        review_queue_path=tmp_path / "missing2.jsonl",
    )
    assert idx.records == []


def test_index_skips_malformed_lines(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(
        '{"candidate_id": "ok", "spec": {"name": "A"}, "stage": "archived"}\n'
        "this is not json\n"
        '{"candidate_id": "ok2", "spec": {"name": "B"}, "stage": "review_queue"}\n',
        encoding="utf-8",
    )
    idx = ResearchIndex.from_paths(archive_path=p, review_queue_path=None)
    assert len(idx.records) == 2


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


def test_search_finds_leakage(populated_paths):
    archive, review = populated_paths
    idx = ResearchIndex.from_paths(archive, review)
    hits = idx.search("lookahead leakage")
    assert len(hits) >= 1
    assert hits[0].candidate_id == "C1"


def test_search_empty_query_returns_empty(populated_paths):
    archive, review = populated_paths
    idx = ResearchIndex.from_paths(archive, review)
    assert idx.search("") == []


def test_search_top_k_caps_results(populated_paths):
    archive, review = populated_paths
    idx = ResearchIndex.from_paths(archive, review)
    hits = idx.search("calmar walk forward instability", top_k=1)
    assert len(hits) <= 1


def test_search_deterministic_under_same_input(populated_paths):
    archive, review = populated_paths
    idx = ResearchIndex.from_paths(archive, review)
    h1 = idx.search("drawdown")
    h2 = idx.search("drawdown")
    assert [r.candidate_id for r in h1] == [r.candidate_id for r in h2]


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


def test_filter_by_rejection_reason(populated_paths):
    archive, review = populated_paths
    idx = ResearchIndex.from_paths(archive, review)
    matched = idx.filter_by_rejection_reason("is_drawdown_too_high")
    assert len(matched) == 1
    assert matched[0].candidate_id == "C2"


def test_failed_due_to_leak_helper(populated_paths):
    archive, review = populated_paths
    idx = ResearchIndex.from_paths(archive, review)
    leaked = idx.failed_due_to_leak()
    assert any(r.candidate_id == "C1" for r in leaked)


def test_stats_aggregates(populated_paths):
    archive, review = populated_paths
    idx = ResearchIndex.from_paths(archive, review)
    stats = idx.stats()
    assert stats["total"] == 4
    assert stats["by_stage"].get("archived") == 3
    assert stats["by_stage"].get("review_queue") == 1
    assert "is_drawdown_too_high" in stats["by_rejection_reason"]
