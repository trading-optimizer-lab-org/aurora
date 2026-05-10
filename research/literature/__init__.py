"""Literature scout and full-paper ingestion (R174).

Sub-package that turns local PDFs and text fixtures into structured
research inputs without letting them bypass validation. The public
surface is intentionally narrow:

- :class:`PaperRecord` and :class:`PaperRegistry` -- minimal metadata
  registry persisted as JSONL.
- :class:`PaperClaim` and :func:`extract_claims_from_text` --
  deterministic regex/heuristic extractor with a hard quote-length cap.
- :class:`ReliabilityScore` and :func:`score_paper` -- a 7-flag
  reproducibility checklist mapped to a 0..1 score.
- :func:`ingest_pdf` and :func:`ingest_text_fixture` -- two ingestion
  paths. ``ingest_pdf`` soft-imports ``pypdf`` and falls back to a raw
  byte scan if it is not installed.
- :class:`AtlasPaperLink` and :class:`AtlasPaperLinkRegistry` -- a
  side-mapping that links atlas entries to one or more paper claim ids
  *as unvalidated source evidence*. The link is metadata only; promotion
  logic ignores it on purpose.

Anything in this sub-package is treated as **upstream evidence**: it
cannot promote a strategy on its own. A claim that "this paper found
sharpe=2 net of costs" is a claim, not validation.
"""
from __future__ import annotations

from aurora.research.literature.atlas_link import (
    AtlasPaperLink,
    AtlasPaperLinkRegistry,
    is_atlas_promotable_with_paper_evidence,
)
from aurora.research.literature.extraction import (
    MAX_QUOTE_LENGTH,
    PaperClaim,
    extract_claims_from_text,
)
from aurora.research.literature.ingest import (
    ingest_pdf,
    ingest_text_fixture,
)
from aurora.research.literature.papers import (
    EXTRACTION_STATUSES,
    PaperRecord,
    PaperRegistry,
)
from aurora.research.literature.reliability import (
    ReliabilityScore,
    score_paper,
)

__all__ = [
    "AtlasPaperLink",
    "AtlasPaperLinkRegistry",
    "EXTRACTION_STATUSES",
    "MAX_QUOTE_LENGTH",
    "PaperClaim",
    "PaperRecord",
    "PaperRegistry",
    "ReliabilityScore",
    "extract_claims_from_text",
    "ingest_pdf",
    "ingest_text_fixture",
    "is_atlas_promotable_with_paper_evidence",
    "score_paper",
]
