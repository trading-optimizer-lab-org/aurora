"""Paper records + in-memory registry with JSONL persistence (R174).

A :class:`PaperRecord` is the minimal metadata describing one ingested
paper. It is intentionally light: title, authors, publication metadata,
local source path or URL, an optional DOI / SSRN id, a free-form
license note, the time the file was first seen, the SHA-256 content
hash of the underlying bytes, the extraction status, and a coarse page
count.

The :class:`PaperRegistry` is in-memory only; persistence is via the
:meth:`PaperRegistry.save` / :meth:`PaperRegistry.load` JSONL helpers
so the registry can be checked into a git-friendly, line-oriented file
on disk without pulling in a database dependency.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

# Allowed extraction status values. Stored as a frozenset so misspelled
# values fail loudly at construction time.
EXTRACTION_STATUSES: frozenset[str] = frozenset({
    "raw",
    "text_extracted",
    "claims_extracted",
    "scored",
    "failed",
})


@dataclass(frozen=True)
class PaperRecord:
    """Frozen metadata record for one ingested paper."""

    paper_id: str
    title: str
    authors: tuple[str, ...]
    year: int
    source: str
    url_or_path: str
    doi: str | None
    ssrn_id: str | None
    licence_note: str
    ingestion_time: str  # ISO-8601
    content_hash: str
    extraction_status: str
    page_count: int

    def __post_init__(self) -> None:
        if not self.paper_id or not self.paper_id.strip():
            raise ValueError("PaperRecord.paper_id must be non-empty")
        if not self.title or not self.title.strip():
            raise ValueError(
                f"PaperRecord({self.paper_id!r}): title must be non-empty"
            )
        if not isinstance(self.authors, tuple):
            raise TypeError(
                f"PaperRecord({self.paper_id!r}): authors must be a tuple"
            )
        if not isinstance(self.year, int):
            raise TypeError(
                f"PaperRecord({self.paper_id!r}): year must be an int"
            )
        if self.year < 1900 or self.year > 2100:
            raise ValueError(
                f"PaperRecord({self.paper_id!r}): year {self.year!r} is "
                "outside the supported range [1900, 2100]"
            )
        if not self.source or not self.source.strip():
            raise ValueError(
                f"PaperRecord({self.paper_id!r}): source must be non-empty"
            )
        if not self.url_or_path or not self.url_or_path.strip():
            raise ValueError(
                f"PaperRecord({self.paper_id!r}): url_or_path must be "
                "non-empty"
            )
        if not isinstance(self.licence_note, str):
            raise TypeError(
                f"PaperRecord({self.paper_id!r}): licence_note must be a "
                "string"
            )
        if not self.ingestion_time or not self.ingestion_time.strip():
            raise ValueError(
                f"PaperRecord({self.paper_id!r}): ingestion_time must be "
                "non-empty ISO-8601"
            )
        if not self.content_hash or not self.content_hash.strip():
            raise ValueError(
                f"PaperRecord({self.paper_id!r}): content_hash must be "
                "non-empty"
            )
        if self.extraction_status not in EXTRACTION_STATUSES:
            raise ValueError(
                f"PaperRecord({self.paper_id!r}): extraction_status "
                f"{self.extraction_status!r} is not one of "
                f"{sorted(EXTRACTION_STATUSES)}"
            )
        if not isinstance(self.page_count, int) or self.page_count < 0:
            raise ValueError(
                f"PaperRecord({self.paper_id!r}): page_count must be a "
                f"non-negative int, got {self.page_count!r}"
            )

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict."""
        d = asdict(self)
        # JSON has no tuple type. Authors -> list.
        d["authors"] = list(self.authors)
        return d

    @classmethod
    def from_dict(cls, payload: dict) -> "PaperRecord":
        """Build a :class:`PaperRecord` from a JSON dict."""
        authors = payload.get("authors", ())
        return cls(
            paper_id=payload["paper_id"],
            title=payload["title"],
            authors=tuple(authors),
            year=int(payload["year"]),
            source=payload["source"],
            url_or_path=payload["url_or_path"],
            doi=payload.get("doi"),
            ssrn_id=payload.get("ssrn_id"),
            licence_note=payload.get("licence_note", ""),
            ingestion_time=payload["ingestion_time"],
            content_hash=payload["content_hash"],
            extraction_status=payload["extraction_status"],
            page_count=int(payload.get("page_count", 0)),
        )


@dataclass
class PaperRegistry:
    """In-memory registry of :class:`PaperRecord` keyed by ``paper_id``."""

    _entries: dict[str, PaperRecord] = field(default_factory=dict)

    def register(self, record: PaperRecord) -> None:
        if record.paper_id in self._entries:
            raise ValueError(
                f"PaperRegistry: paper {record.paper_id!r} already registered"
            )
        self._entries[record.paper_id] = record

    def get(self, paper_id: str) -> PaperRecord:
        if paper_id not in self._entries:
            raise KeyError(f"PaperRegistry: unknown paper {paper_id!r}")
        return self._entries[paper_id]

    def has(self, paper_id: str) -> bool:
        return paper_id in self._entries

    def list_papers(self) -> list[PaperRecord]:
        """Return all records sorted by ingestion time (oldest first)."""
        return sorted(
            self._entries.values(),
            key=lambda r: r.ingestion_time,
        )

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, paper_id: object) -> bool:
        return isinstance(paper_id, str) and paper_id in self._entries

    def __iter__(self) -> Iterable[PaperRecord]:
        return iter(self.list_papers())

    def save(self, path: Path | str) -> None:
        """Write the registry to a JSONL file (one record per line)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Persist in deterministic ingestion-time order so the file
        # diff is stable across runs.
        lines = [
            json.dumps(r.to_dict(), sort_keys=True)
            for r in self.list_papers()
        ]
        target.write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | str) -> "PaperRegistry":
        """Read a JSONL file produced by :meth:`save` into a fresh registry."""
        registry = cls()
        source = Path(path)
        if not source.exists():
            return registry
        text = source.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            record = PaperRecord.from_dict(payload)
            # Preserve insertion behaviour but tolerate duplicates from
            # a corrupt file by keeping the first-seen record.
            if record.paper_id not in registry._entries:
                registry._entries[record.paper_id] = record
        return registry


def utc_now_isoformat() -> str:
    """Return the current UTC time as an ISO-8601 string with second precision.

    Wrapped so tests can monkeypatch a deterministic clock if needed.
    """
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


__all__ = [
    "EXTRACTION_STATUSES",
    "PaperRecord",
    "PaperRegistry",
    "utc_now_isoformat",
]
