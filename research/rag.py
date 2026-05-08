"""RAG over research archive (R9).

Indexes :mod:`quantforge.research.factory` archive and review-queue JSONL
files for keyword search and category filtering. Pure stdlib, no external
embedding dependencies. Local by default; the index is rebuilt from JSONL
on every load so callers always see current archive state.

Design choices
--------------

* Keyword retrieval, not embeddings. The archive is text-rich and the
  query patterns operators actually use ("which strategies failed by
  leakage?", "what rejected for cost reasons?") map cleanly to keyword
  + category filtering. Embedding-based RAG would add a heavy
  dependency for marginal recall gains on this corpus shape.
* Deterministic ranking. Two records with the same score break ties by
  ``timestamp_iso`` (newer first), then by ``candidate_id``.
* Tier-safe: this module only reads the factory archive, which already
  excludes OOS_LOCKED / FORWARD reads by construction.
* Strict input validation: malformed JSONL rows are skipped with a
  warning rather than aborting the load.

Usage::

    from quantforge.research.rag import ResearchIndex

    idx = ResearchIndex.from_default_paths()
    hits = idx.search("lookahead leakage")
    leaked = idx.filter_by_rejection_reason("oos_dev_failure")
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quantforge.core.runtime_paths import (
    research_archive_path,
    review_queue_path,
)

_log = logging.getLogger("quantforge.research.rag")

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "this", "that", "into",
        "are", "was", "were", "have", "has", "had", "but", "not",
        "can", "any", "all", "their", "there", "than", "then", "when",
    }
)


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenize a string, dropping short stopwords."""
    if not text:
        return []
    return [
        m.group(0).lower()
        for m in _TOKEN_RE.finditer(text)
        if m.group(0).lower() not in _STOPWORDS and len(m.group(0)) >= 3
    ]


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexedRecord:
    """Frozen retrieval-side projection of a CandidateRun JSONL row.

    Only the fields a query engine needs are kept here; the original row
    is preserved in ``raw`` for callers that need full detail.
    """

    candidate_id: str
    spec_name: str
    stage: str
    rejection_reason: str | None
    rejection_detail: str | None
    timestamp_iso: str
    source: str  # "archive" or "review_queue"
    raw: dict[str, Any]
    tokens: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], source: str) -> IndexedRecord:
        spec = raw.get("spec") or {}
        spec_name = str(spec.get("name") or raw.get("spec_name") or "unknown")
        stage = str(raw.get("stage") or "unknown")
        rejection_reason = raw.get("rejection_reason")
        rejection_detail = raw.get("rejection_detail")
        ts = (
            raw.get("timestamp_iso")
            or raw.get("submitted_at")
            or raw.get("finished_at")
            or ""
        )
        # Build the search corpus per record. Concatenating spec, rejection
        # detail and the metric dicts gives the best signal for "which
        # strategy failed because of X" style queries.
        corpus = " ".join(
            str(x)
            for x in (
                spec_name,
                stage,
                rejection_reason or "",
                rejection_detail or "",
                json.dumps(spec, default=str, sort_keys=True),
                json.dumps(raw.get("is_metrics") or {}, default=str),
                json.dumps(raw.get("wf_metrics") or {}, default=str),
                json.dumps(raw.get("oos_dev_metrics") or {}, default=str),
            )
        )
        tokens = frozenset(_tokenize(corpus))
        return cls(
            candidate_id=str(raw.get("candidate_id") or ""),
            spec_name=spec_name,
            stage=stage,
            rejection_reason=str(rejection_reason) if rejection_reason else None,
            rejection_detail=str(rejection_detail) if rejection_detail else None,
            timestamp_iso=str(ts),
            source=source,
            raw=dict(raw),
            tokens=tokens,
        )


# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------


@dataclass
class ResearchIndex:
    """In-memory keyword index over factory archive + review queue.

    Build with :meth:`from_default_paths` (uses ``QF_RESEARCH_ARCHIVE`` and
    ``QF_REVIEW_QUEUE`` env vars via ``runtime_paths``) or :meth:`from_paths`
    for explicit paths (tests).
    """

    records: list[IndexedRecord] = field(default_factory=list)

    # ---- construction ------------------------------------------------------

    @classmethod
    def from_default_paths(cls) -> ResearchIndex:
        return cls.from_paths(
            archive_path=research_archive_path(),
            review_queue_path=review_queue_path(),
        )

    @classmethod
    def from_paths(
        cls,
        archive_path: Path | None = None,
        review_queue_path: Path | None = None,
    ) -> ResearchIndex:
        records: list[IndexedRecord] = []
        if archive_path is not None:
            records.extend(
                cls._load_jsonl(Path(archive_path), source="archive")
            )
        if review_queue_path is not None:
            records.extend(
                cls._load_jsonl(Path(review_queue_path), source="review_queue")
            )
        return cls(records=records)

    @staticmethod
    def _load_jsonl(path: Path, source: str) -> list[IndexedRecord]:
        if not path.exists():
            return []
        out: list[IndexedRecord] = []
        with path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    _log.warning(
                        "rag: skipping malformed line %d in %s: %s",
                        lineno, path, exc,
                    )
                    continue
                if not isinstance(raw, dict):
                    continue
                out.append(IndexedRecord.from_raw(raw, source=source))
        return out

    # ---- retrieval ---------------------------------------------------------

    def search(self, query: str, top_k: int = 10) -> list[IndexedRecord]:
        """Return up to ``top_k`` records ranked by token-overlap score.

        Score is the number of distinct query tokens present in the
        record's token set, with a tiny inverse-frequency factor so a
        rare term outranks a frequent one. Ties broken by timestamp
        (newer first) then candidate_id.
        """
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        # Document frequency for IDF-ish weighting.
        df: dict[str, int] = {}
        for r in self.records:
            for tok in set(q_tokens) & r.tokens:
                df[tok] = df.get(tok, 0) + 1
        total = max(1, len(self.records))

        scored: list[tuple[float, IndexedRecord]] = []
        for r in self.records:
            overlap = set(q_tokens) & r.tokens
            if not overlap:
                continue
            s = sum(
                math.log(1.0 + total / (1 + df.get(tok, 0)))
                for tok in overlap
            )
            scored.append((s, r))

        scored.sort(
            key=lambda item: (
                -item[0],
                # Newer first: invert lexical sort by negating string
                # comparison via ordinal -- simpler to flip with reverse
                # inside the secondary key.
                -_iso_to_float(item[1].timestamp_iso),
                item[1].candidate_id,
            )
        )
        return [r for _, r in scored[:top_k]]

    def filter_by_rejection_reason(
        self, reason: str
    ) -> list[IndexedRecord]:
        """Return all records archived under the given rejection reason."""
        return [
            r for r in self.records if r.rejection_reason == reason
        ]

    def filter_by_stage(self, stage: str) -> list[IndexedRecord]:
        """Return records whose ``stage`` matches exactly."""
        return [r for r in self.records if r.stage == stage]

    def failed_due_to_leak(self) -> list[IndexedRecord]:
        """Convenience filter for lookahead / data-leak failures."""
        keys = {"data_leak", "lookahead", "leak"}
        out: list[IndexedRecord] = []
        for r in self.records:
            text = " ".join(
                str(x).lower()
                for x in (r.rejection_reason or "", r.rejection_detail or "")
            )
            if any(k in text for k in keys):
                out.append(r)
        return out

    def stats(self) -> dict[str, Any]:
        """Aggregate counts useful for quick triage."""
        by_stage: dict[str, int] = {}
        by_reason: dict[str, int] = {}
        for r in self.records:
            by_stage[r.stage] = by_stage.get(r.stage, 0) + 1
            if r.rejection_reason:
                by_reason[r.rejection_reason] = (
                    by_reason.get(r.rejection_reason, 0) + 1
                )
        return {
            "total": len(self.records),
            "by_stage": dict(sorted(by_stage.items())),
            "by_rejection_reason": dict(sorted(by_reason.items())),
        }


def _iso_to_float(s: str) -> float:
    """Convert ISO timestamp to a comparable float; 0.0 on failure."""
    if not s:
        return 0.0
    try:
        import pandas as pd

        return float(pd.Timestamp(s).value)
    except Exception:
        return 0.0


__all__ = ["ResearchIndex", "IndexedRecord"]
