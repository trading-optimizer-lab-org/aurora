"""Reliability scoring for ingested papers (R174).

Maps a small reproducibility checklist to a 0..1 score so triage and the
research factory can sort papers by how trustworthy their headline
claims are. Each flag is binary: either the paper meets the bar or it
does not. Missing flags are treated as **zero** (not 0.5) -- if a paper
does not say it covered transaction costs, we assume it did not.

The score is the unweighted mean of the seven flags. A paper that
checks every box scores 1.0; a paper that checks none scores 0.0.
The score is intentionally a coarse summary; downstream review must
look at the individual flags rather than only the scalar.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from aurora.research.literature.extraction import PaperClaim
    from aurora.research.literature.papers import PaperRecord

# Number of flags contributing to the score. Update if you add a flag.
_NUM_FLAGS: int = 7


@dataclass(frozen=True)
class ReliabilityScore:
    """Reproducibility / reliability checklist for one paper."""

    paper_id: str
    reproducible_data: bool
    costs_included: bool
    oos_included: bool
    multiple_testing_addressed: bool
    survivorship_handled: bool
    code_available: bool
    sample_size_adequate: bool
    score: float

    def __post_init__(self) -> None:
        if not self.paper_id or not self.paper_id.strip():
            raise ValueError("ReliabilityScore.paper_id must be non-empty")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(
                f"ReliabilityScore({self.paper_id!r}): score must be in "
                f"[0.0, 1.0], got {self.score!r}"
            )


def _looks_reproducible_data(claims: list["PaperClaim"]) -> bool:
    """Return True if any claim references a public-universe replication.

    ``public_universe`` in ``replication_requirements`` is the heuristic.
    """
    for claim in claims:
        if "public_universe" in claim.replication_requirements:
            return True
    return False


def _looks_oos(claims: list["PaperClaim"]) -> bool:
    """Return True iff at least one claim was tagged out-of-sample."""
    return any(claim.oos_included for claim in claims)


def _looks_costs_included(claims: list["PaperClaim"]) -> bool:
    """Return True iff at least one claim was tagged as net of costs."""
    return any(claim.transaction_costs_included for claim in claims)


def _looks_multiple_testing(claims: list["PaperClaim"]) -> bool:
    """Return True if any claim text mentions deflated / Bonferroni / FDR."""
    for claim in claims:
        body = claim.claim_text.lower()
        if any(
            token in body
            for token in (
                "deflated sharpe",
                "bonferroni",
                "false discovery",
                "fdr",
                "multiple testing",
                "haircut",
            )
        ):
            return True
    return False


def _looks_survivorship_handled(claims: list["PaperClaim"]) -> bool:
    """Return True if claims state survivorship bias is handled.

    Conservative: any claim with the ``survivorship_unaddressed`` red
    flag or limitation forces a False; we only return True if the body
    text explicitly says it was handled.
    """
    handled = False
    for claim in claims:
        if "survivorship_unaddressed" in claim.red_flags:
            return False
        if "survivorship_unaddressed" in claim.limitations:
            return False
        body = claim.claim_text.lower()
        if "survivorship-bias-free" in body or \
                "survivorship bias free" in body or \
                "survivorship bias is addressed" in body or \
                "survivorship bias has been addressed" in body:
            handled = True
    return handled


def _looks_code_available(claims: list["PaperClaim"]) -> bool:
    """True if any claim text mentions a code/repo URL token."""
    for claim in claims:
        body = claim.claim_text.lower()
        urls = re.findall(r"https?://[^\s<>\"']+", body)
        github_url = any(
            (urlsplit(url.rstrip(".,;:!?)")).hostname or "").lower()
            in {"github.com", "www.github.com"}
            for url in urls
        )
        if github_url or "code is available" in body or \
                "code available at" in body or "replication code" in body:
            return True
    return False


def _looks_sample_size_adequate(claims: list["PaperClaim"]) -> bool:
    """Heuristic: at least one claim has a sample period >= 10 years."""
    for claim in claims:
        sp = claim.sample_period
        if "-" not in sp:
            continue
        try:
            start, end = sp.split("-", 1)
            years = int(end) - int(start)
        except ValueError:
            continue
        if years >= 10:
            return True
    return False


def score_paper(
    paper: "PaperRecord",
    claims: list["PaperClaim"],
) -> ReliabilityScore:
    """Compute a :class:`ReliabilityScore` for ``paper`` from its claims."""
    flags = (
        _looks_reproducible_data(claims),
        _looks_costs_included(claims),
        _looks_oos(claims),
        _looks_multiple_testing(claims),
        _looks_survivorship_handled(claims),
        _looks_code_available(claims),
        _looks_sample_size_adequate(claims),
    )
    score = sum(1 for f in flags if f) / float(_NUM_FLAGS)
    return ReliabilityScore(
        paper_id=paper.paper_id,
        reproducible_data=flags[0],
        costs_included=flags[1],
        oos_included=flags[2],
        multiple_testing_addressed=flags[3],
        survivorship_handled=flags[4],
        code_available=flags[5],
        sample_size_adequate=flags[6],
        score=score,
    )


__all__ = [
    "ReliabilityScore",
    "score_paper",
]
