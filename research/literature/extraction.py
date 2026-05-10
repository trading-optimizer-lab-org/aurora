"""Deterministic claim extraction from paper text (R174).

The extractor walks a small set of regex / heuristic rules over a piece
of paper text and emits :class:`PaperClaim` records. It is intentionally
deterministic and offline: no LLM calls, no network, no ML model.

Rationale: the goal is *extracting structure already in the prose*, not
inventing claims. A regex pass over the paper text produces a stable,
reviewable corpus that can be diffed across re-runs. If the heuristics
miss a claim that exists in the paper, the fix is to add another rule
and re-extract; we never want a freshly-trained model to silently
"discover" new claims between runs.

The hard quote-length limit (``MAX_QUOTE_LENGTH``) protects against
fair-use over-quoting and accidental inclusion of paragraphs of source
text in our archive. Construction raises ``ValueError`` if a claim
exceeds the cap.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora.research.literature.papers import PaperRecord

# Hard cap on extracted quote length. Anything longer is rejected at
# construction time so we never build a record that would over-quote.
MAX_QUOTE_LENGTH: int = 500


# ---- Heuristic rule tables -------------------------------------------------
#
# Each rule fires on a regex match against the paper text. The matched
# fragment becomes ``quote_excerpt`` (truncated to MAX_QUOTE_LENGTH).
# A rule produces one claim per match, deduped by claim_id.

_ASSET_CLASS_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("equity", re.compile(r"\b(?:stocks?|equit(?:y|ies))\b", re.I)),
    ("etf", re.compile(r"\bETFs?\b")),
    ("commodity", re.compile(r"\bcommodit(?:y|ies)\b", re.I)),
    ("currency", re.compile(r"\b(?:FX|currenc(?:y|ies)|forex)\b", re.I)),
    ("rates", re.compile(r"\b(?:treasur(?:y|ies)|bonds?|rates?)\b", re.I)),
    ("crypto", re.compile(r"\b(?:crypto|bitcoin|ethereum)\b", re.I)),
)

_FREQUENCY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("daily", re.compile(r"\bdaily\b", re.I)),
    ("weekly", re.compile(r"\bweekly\b", re.I)),
    ("monthly", re.compile(r"\bmonthly\b", re.I)),
    ("intraday", re.compile(r"\bintraday\b", re.I)),
)

_SAMPLE_PERIOD_RE = re.compile(
    r"\b(19\d{2}|20\d{2})\s*[-–—to/]+\s*(19\d{2}|20\d{2})\b"
)

# Metric phrases. Each rule emits a (label, value) pair when matched.
# We keep the regex narrow so we get a numeric capture or skip.
_METRIC_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sharpe", re.compile(
        r"\bSharpe(?:\s+ratio)?\s*(?:of|=|:)?\s*([0-9]+\.?[0-9]*)",
        re.I,
    )),
    ("annual_return", re.compile(
        r"\b(?:annual(?:ised|ized)?\s+return|CAGR)\s*(?:of|=|:)?\s*"
        r"([0-9]+\.?[0-9]*)\s*%",
        re.I,
    )),
    ("max_drawdown", re.compile(
        r"\bmax(?:imum)?\s*drawdown\s*(?:of|=|:)?\s*([0-9]+\.?[0-9]*)\s*%",
        re.I,
    )),
    ("hit_rate", re.compile(
        r"\bhit\s*rate\s*(?:of|=|:)?\s*([0-9]+\.?[0-9]*)\s*%",
        re.I,
    )),
)

_COSTS_INCLUDED_RE = re.compile(
    r"\b(?:net\s+of\s+(?:transaction\s+)?costs|transaction\s+costs?\s+"
    r"(?:are\s+|were\s+)?(?:included|applied|deducted))\b",
    re.I,
)
_COSTS_EXCLUDED_RE = re.compile(
    r"\b(?:gross\s+of\s+costs|before\s+(?:transaction\s+)?costs|"
    r"costs?\s+(?:are\s+)?not\s+included|excluding\s+costs)\b",
    re.I,
)
_OOS_INCLUDED_RE = re.compile(
    r"\b(?:out[-\s]of[-\s]sample|OOS|walk[-\s]forward)\b", re.I
)
_PAGE_REF_RE = re.compile(r"\(?p(?:age|p?\.)\s*(\d{1,4})\)?", re.I)

# Red-flag phrases. Any occurrence flips the claim to "needs scrutiny".
_RED_FLAG_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("guaranteed_returns", re.compile(r"\bguaranteed\s+returns?\b", re.I)),
    ("no_drawdown", re.compile(r"\bno\s+drawdown(?:s)?\b", re.I)),
    ("risk_free_alpha", re.compile(
        r"\brisk[-\s]free\s+alpha\b", re.I
    )),
    ("never_loses", re.compile(r"\bnever\s+loses\b", re.I)),
    ("perfect_foresight", re.compile(r"\bperfect\s+foresight\b", re.I)),
    ("survivorship_unaddressed", re.compile(
        r"\bsurvivorship[-\s]bias\s+is\s+not\s+addressed\b", re.I
    )),
    ("no_costs", re.compile(
        r"\bno\s+(?:transaction\s+)?costs?\b", re.I
    )),
)


@dataclass(frozen=True)
class PaperClaim:
    """One extracted claim from a paper.

    A claim is a single quotable assertion. Multiple claims per paper
    are normal: a typical paper makes a primary metric claim, an OOS
    claim, and a transaction-cost claim, each of which becomes its own
    record so reviewers can score them independently.
    """

    claim_id: str
    paper_id: str
    claim_text: str
    asset_class: str
    sample_period: str
    universe: str
    data_frequency: str
    reported_metrics: dict[str, float]
    transaction_costs_included: bool
    oos_included: bool
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    replication_requirements: tuple[str, ...]
    red_flags: tuple[str, ...]
    page_reference: str
    quote_excerpt: str

    def __post_init__(self) -> None:
        if not self.claim_id or not self.claim_id.strip():
            raise ValueError("PaperClaim.claim_id must be non-empty")
        if not self.paper_id or not self.paper_id.strip():
            raise ValueError(
                f"PaperClaim({self.claim_id!r}): paper_id must be non-empty"
            )
        if not isinstance(self.reported_metrics, dict):
            raise TypeError(
                f"PaperClaim({self.claim_id!r}): reported_metrics must be "
                "a dict"
            )
        for tup_name in (
            "assumptions", "limitations", "replication_requirements",
            "red_flags",
        ):
            tup = getattr(self, tup_name)
            if not isinstance(tup, tuple):
                raise TypeError(
                    f"PaperClaim({self.claim_id!r}): {tup_name} must be a "
                    "tuple"
                )
        if len(self.quote_excerpt) > MAX_QUOTE_LENGTH:
            raise ValueError(
                f"PaperClaim({self.claim_id!r}): quote_excerpt length "
                f"{len(self.quote_excerpt)} exceeds MAX_QUOTE_LENGTH "
                f"({MAX_QUOTE_LENGTH}); truncate before constructing"
            )


def _truncate_quote(text: str, *, limit: int = MAX_QUOTE_LENGTH) -> str:
    """Return ``text`` truncated to ``limit`` characters, preserving prefix."""
    if len(text) <= limit:
        return text
    return text[:limit]


def _sentence_around(text: str, match_start: int, match_end: int) -> str:
    """Return the sentence containing the match, clipped to MAX_QUOTE_LENGTH.

    Best-effort sentence boundary detection using ``.``, ``!`` and ``?``.
    """
    left = match_start
    while left > 0 and text[left - 1] not in ".!?\n":
        left -= 1
    right = match_end
    while right < len(text) and text[right] not in ".!?\n":
        right += 1
    if right < len(text):
        right += 1  # include the terminator
    snippet = text[left:right].strip()
    return _truncate_quote(snippet)


def _make_claim_id(paper_id: str, kind: str, anchor: str) -> str:
    """Build a deterministic claim id from paper + kind + anchor text."""
    digest = hashlib.sha256(
        f"{paper_id}|{kind}|{anchor}".encode("utf-8")
    ).hexdigest()[:12]
    return f"{paper_id}-{kind}-{digest}"


def _detect_asset_class(text: str) -> str:
    """Return the first matching asset class label, or ``"unknown"``."""
    for label, regex in _ASSET_CLASS_RULES:
        if regex.search(text):
            return label
    return "unknown"


def _detect_frequency(text: str) -> str:
    """Return the first matching data frequency label, or ``"unspecified"``."""
    for label, regex in _FREQUENCY_RULES:
        if regex.search(text):
            return label
    return "unspecified"


def _detect_sample_period(text: str) -> str:
    """Return ``"YYYY-YYYY"`` for the first range found, or empty string."""
    m = _SAMPLE_PERIOD_RE.search(text)
    if not m:
        return ""
    return f"{m.group(1)}-{m.group(2)}"


def _detect_universe(text: str) -> str:
    """Heuristic universe label.

    Look for common universe phrases; fall back to ``"unspecified"``.
    """
    patterns = [
        (r"\bS&P\s*500\b", "S&P 500"),
        (r"\bRussell\s*1000\b", "Russell 1000"),
        (r"\bRussell\s*2000\b", "Russell 2000"),
        (r"\bNASDAQ\b", "NASDAQ"),
        (r"\bDow\s*Jones\b", "Dow Jones"),
        (r"\bcrypto(?:currency|currencies)?\b", "crypto majors"),
    ]
    for pat, label in patterns:
        if re.search(pat, text, re.I):
            return label
    return "unspecified"


def _detect_metrics(text: str) -> dict[str, float]:
    """Extract numeric metrics by name. Returns ``{}`` if none match."""
    out: dict[str, float] = {}
    for label, regex in _METRIC_RULES:
        m = regex.search(text)
        if not m:
            continue
        try:
            out[label] = float(m.group(1))
        except (ValueError, IndexError):
            continue
    return out


def _detect_costs_included(text: str) -> bool:
    """True if the text explicitly states costs are included."""
    if _COSTS_EXCLUDED_RE.search(text):
        return False
    return bool(_COSTS_INCLUDED_RE.search(text))


def _detect_oos_included(text: str) -> bool:
    """True if the text mentions out-of-sample / walk-forward testing."""
    return bool(_OOS_INCLUDED_RE.search(text))


def _detect_red_flags(text: str) -> tuple[str, ...]:
    """Return tuple of red-flag labels found in the text."""
    flags: list[str] = []
    for label, regex in _RED_FLAG_RULES:
        if regex.search(text):
            flags.append(label)
    return tuple(flags)


def _detect_page_reference(text: str) -> str:
    """Return the first page-reference token, or empty string."""
    m = _PAGE_REF_RE.search(text)
    if not m:
        return ""
    return f"p.{m.group(1)}"


# ---- Public extractor ------------------------------------------------------


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text on blank lines; trim whitespace; drop empty paragraphs."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def extract_claims_from_text(
    paper: "PaperRecord",
    text: str,
    *,
    paragraph_min_length: int = 30,
) -> list[PaperClaim]:
    """Extract :class:`PaperClaim` records from ``text``.

    Deterministic: identical inputs produce identical outputs (claim
    ids are SHA-256-derived from the paper id + claim kind + anchor
    string).

    Strategy: split the text into paragraphs and keep paragraphs that
    look "claim-bearing" -- they mention either a numeric metric, OOS
    testing, transaction-costs language, or a sample-period range.
    Each surviving paragraph becomes one claim.
    """
    if not isinstance(text, str):
        raise TypeError("extract_claims_from_text: text must be str")

    paragraphs = _split_into_paragraphs(text)
    seen_ids: set[str] = set()
    claims: list[PaperClaim] = []

    for paragraph in paragraphs:
        if len(paragraph) < paragraph_min_length:
            # Too short to carry a structured claim.
            continue

        metrics = _detect_metrics(paragraph)
        oos = _detect_oos_included(paragraph)
        costs = _detect_costs_included(paragraph)
        sample = _detect_sample_period(paragraph)
        red_flags = _detect_red_flags(paragraph)

        is_claim_bearing = bool(
            metrics
            or oos
            or _COSTS_INCLUDED_RE.search(paragraph)
            or _COSTS_EXCLUDED_RE.search(paragraph)
            or sample
            or red_flags
        )
        if not is_claim_bearing:
            continue

        # Determine claim "kind" so multiple claims per paragraph stay
        # distinct (and so the claim_id is reviewable).
        if metrics:
            kind = "metric"
        elif oos:
            kind = "oos"
        elif _COSTS_INCLUDED_RE.search(paragraph) or \
                _COSTS_EXCLUDED_RE.search(paragraph):
            kind = "costs"
        elif sample:
            kind = "sample"
        elif red_flags:
            kind = "red_flag"
        else:  # pragma: no cover - guarded above
            kind = "claim"

        anchor = paragraph[:80]
        cid = _make_claim_id(paper.paper_id, kind, anchor)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        quote = _truncate_quote(paragraph)
        claim = PaperClaim(
            claim_id=cid,
            paper_id=paper.paper_id,
            claim_text=quote,
            asset_class=_detect_asset_class(paragraph),
            sample_period=sample,
            universe=_detect_universe(paragraph),
            data_frequency=_detect_frequency(paragraph),
            reported_metrics=metrics,
            transaction_costs_included=costs,
            oos_included=oos,
            assumptions=_detect_assumptions(paragraph),
            limitations=_detect_limitations(paragraph),
            replication_requirements=_detect_replication(paragraph),
            red_flags=red_flags,
            page_reference=_detect_page_reference(paragraph),
            quote_excerpt=quote,
        )
        claims.append(claim)

    return claims


# ---- Soft-heuristic detectors -------------------------------------------


_ASSUMPTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("frictionless_trading", re.compile(
        r"\bfrictionless\s+(?:trading|markets?)\b", re.I
    )),
    ("no_borrow_constraints", re.compile(
        r"\bno\s+borrow\s+constraints?\b", re.I
    )),
    ("daily_rebalance", re.compile(r"\bdaily\s+rebalanc(?:e|ing)\b", re.I)),
    ("monthly_rebalance", re.compile(
        r"\bmonthly\s+rebalanc(?:e|ing)\b", re.I
    )),
    ("equal_weight", re.compile(r"\bequal[-\s]weight(?:ed)?\b", re.I)),
)

_LIMITATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("limited_sample", re.compile(
        r"\blimited\s+(?:sample|history|data)\b", re.I
    )),
    ("survivorship_unaddressed", re.compile(
        r"\bsurvivorship[-\s]bias\s+is\s+not\s+addressed\b", re.I
    )),
    ("regime_dependent", re.compile(r"\bregime[-\s]dependent\b", re.I)),
    ("backtest_only", re.compile(
        r"\bbacktest[-\s]only\b|\bnot\s+traded\s+live\b", re.I
    )),
)

_REPLICATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("daily_ohlcv", re.compile(
        r"\b(?:daily\s+OHLCV?|daily\s+(?:open|close|prices?))\b", re.I
    )),
    ("fundamentals", re.compile(
        r"\b(?:fundamental|book[-\s]value|earnings)\b", re.I
    )),
    ("options_chain", re.compile(r"\boptions?\s+chain\b", re.I)),
    ("intraday_quotes", re.compile(r"\bintraday\s+quotes?\b", re.I)),
    ("public_universe", re.compile(
        r"\b(?:S&P\s*500|Russell\s*\d+|NASDAQ)\b", re.I
    )),
)


def _detect_assumptions(text: str) -> tuple[str, ...]:
    """Return assumption labels found in the text."""
    return tuple(
        label for label, regex in _ASSUMPTION_PATTERNS if regex.search(text)
    )


def _detect_limitations(text: str) -> tuple[str, ...]:
    """Return limitation labels found in the text."""
    return tuple(
        label for label, regex in _LIMITATION_PATTERNS if regex.search(text)
    )


def _detect_replication(text: str) -> tuple[str, ...]:
    """Return replication-requirement labels found in the text."""
    return tuple(
        label for label, regex in _REPLICATION_PATTERNS if regex.search(text)
    )


__all__ = [
    "MAX_QUOTE_LENGTH",
    "PaperClaim",
    "extract_claims_from_text",
]
