"""Local file ingestion for paper records (R174).

Two ingestion paths are supported:

- :func:`ingest_pdf` -- reads a local PDF. ``pypdf`` is used if it is
  importable; otherwise we fall back to a raw byte scan that strips
  control characters and printable-ASCII filters the result. The
  fallback is good enough for fixture PDFs but should not be trusted
  on production papers.
- :func:`ingest_text_fixture` -- reads a ``.txt`` fixture verbatim.

Both functions return a tuple ``(PaperRecord, text)`` so the caller
can pass the text to :func:`extract_claims_from_text` without re-reading
the file.

Web fetch is intentionally not exposed here; the operator must place
the file on disk first. This is a deliberate trust boundary: AURORA
will not silently pull URLs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from aurora.research.literature.papers import (
    PaperRecord,
    utc_now_isoformat,
)

# Lower-case extensions accepted by ``ingest_pdf``.
_PDF_EXTS = frozenset({".pdf"})
# Lower-case extensions accepted by ``ingest_text_fixture``.
_TEXT_EXTS = frozenset({".txt"})


def _content_hash(payload: bytes) -> str:
    """SHA-256 of ``payload`` as a lowercase hex digest."""
    return hashlib.sha256(payload).hexdigest()


def _paper_id_from_hash(content_hash: str) -> str:
    """Derive a stable paper id from the content hash.

    Using the leading 16 hex chars keeps ids short while remaining
    collision-resistant for the volume of papers a research lab will
    ever ingest.
    """
    return f"paper-{content_hash[:16]}"


def _fallback_pdf_text(payload: bytes) -> str:
    """Best-effort text extraction from raw PDF bytes.

    Strategy: decode as latin-1 so every byte maps to a character, then
    drop the obviously-binary parts (PDF stream markers and the like)
    and return the remaining ASCII printable runs separated by single
    spaces. Good enough for tests; do not trust on real papers.
    """
    decoded = payload.decode("latin-1", errors="ignore")
    # Strip PDF object / xref / stream markers; keep alphanumerics and
    # basic punctuation that shows up in claim-bearing prose.
    out: list[str] = []
    buf: list[str] = []
    for ch in decoded:
        if ch.isprintable() and ch not in {"\r"}:
            buf.append(ch)
        else:
            if buf:
                run = "".join(buf).strip()
                if len(run) > 4:
                    out.append(run)
                buf = []
    if buf:
        run = "".join(buf).strip()
        if len(run) > 4:
            out.append(run)
    return " ".join(out)


def ingest_pdf(path: Path | str) -> tuple[PaperRecord, str]:
    """Ingest a local PDF and return ``(record, extracted_text)``.

    Soft-imports ``pypdf``. If it is not available, falls back to a raw
    byte scan that is good enough for tests but should not be relied on
    for production.
    """
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"ingest_pdf: file not found: {src}")
    if src.suffix.lower() not in _PDF_EXTS:
        raise ValueError(
            f"ingest_pdf: unsupported extension {src.suffix!r}; "
            f"expected one of {sorted(_PDF_EXTS)}"
        )

    payload = src.read_bytes()
    content_hash = _content_hash(payload)
    paper_id = _paper_id_from_hash(content_hash)

    text = ""
    page_count = 0
    try:
        import pypdf  # type: ignore[import-not-found]
        reader = pypdf.PdfReader(str(src))
        page_count = len(reader.pages)
        chunks: list[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                # Some pages can fail extraction; carry on.
                chunks.append("")
        text = "\n\n".join(chunks).strip()
    except ImportError:
        # Fallback path: no pypdf available.
        text = _fallback_pdf_text(payload)
        # Page count is not knowable without a real parser.
        page_count = max(1, text.count("\f") + 1)

    record = PaperRecord(
        paper_id=paper_id,
        title=src.stem.replace("_", " ").replace("-", " ").strip() or "untitled",
        authors=(),
        year=2026,
        source="local_pdf",
        url_or_path=str(src),
        doi=None,
        ssrn_id=None,
        licence_note="local file ingestion; license not parsed",
        ingestion_time=utc_now_isoformat(),
        content_hash=content_hash,
        extraction_status="text_extracted" if text else "raw",
        page_count=page_count,
    )
    return record, text


def ingest_text_fixture(path: Path | str) -> tuple[PaperRecord, str]:
    """Ingest a local ``.txt`` fixture and return ``(record, text)``."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(
            f"ingest_text_fixture: file not found: {src}"
        )
    if src.suffix.lower() not in _TEXT_EXTS:
        raise ValueError(
            f"ingest_text_fixture: unsupported extension {src.suffix!r}; "
            f"expected one of {sorted(_TEXT_EXTS)}"
        )

    payload = src.read_bytes()
    content_hash = _content_hash(payload)
    paper_id = _paper_id_from_hash(content_hash)
    text = payload.decode("utf-8", errors="replace")

    # Approximate page count: 1 page per ~3000 characters, minimum 1.
    if text.strip():
        page_count = max(1, (len(text) + 2999) // 3000)
        status = "text_extracted"
    else:
        page_count = 0
        status = "raw"

    record = PaperRecord(
        paper_id=paper_id,
        title=src.stem.replace("_", " ").replace("-", " ").strip() or "untitled",
        authors=(),
        year=2026,
        source="local_text_fixture",
        url_or_path=str(src),
        doi=None,
        ssrn_id=None,
        licence_note="text fixture; license not parsed",
        ingestion_time=utc_now_isoformat(),
        content_hash=content_hash,
        extraction_status=status,
        page_count=page_count,
    )
    return record, text


__all__ = [
    "ingest_pdf",
    "ingest_text_fixture",
]
