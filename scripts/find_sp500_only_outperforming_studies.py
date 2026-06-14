from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.execution_policy import require_github_actions_or_explicit_local_permission  # noqa: E402


DEFAULT_EXACTNESS = (
    "outputs/literature/pdf_text_pipeline_29855/manual_review_needs_review/"
    "literature_strategy_exactness_after_manual_review.csv"
)
DEFAULT_IMPORT = (
    "outputs/literature/aurora_strategy_import_26638765315/"
    "aurora_replicable_ideas_29855_import_manifest.csv"
)

SP500_RE = re.compile(
    r"\b(spy|spdr\s+s&p|s\s*&\s*p\s*500|s&p\s*500|s&p500|sp500|spx|\^gspc|standard\s+and\s+poor'?s?\s+500)\b",
    re.I,
)
STRATEGY_RE = re.compile(
    r"\b(trading rule|trading rules|market timing|tactical allocation|trend following|moving average|"
    r"time.series momentum|momentum rule|seasonal trading|seasonality effect|volatility managed|volatility timing|"
    r"vix.*timing|risk-on|risk-off|long.*s&p|short.*s&p|long.*spy|short.*spy|cash.*s&p|"
    r"buy.?and.?hold|allocation rule|switching rule|technical trading|technical rule)\b",
    re.I,
)
MARKET_CONTEXT_RE = re.compile(
    r"\b(stock market|equity market|market return|market returns|index return|index returns|portfolio return|"
    r"s&p\s*500|sp500|spy|spx|buy.?and.?hold|market timing|trading rule)\b",
    re.I,
)
NON_FINANCE_RE = re.compile(
    r"\b(bacterial|streptococc|neonatal|clinical|patient|consumer engagement|brand affinity|business strategy|"
    r"mass customization|infrastructure policy|climate resilient infrastructure)\b",
    re.I,
)
OUTPERFORM_RE = re.compile(
    r"\b(outperform|outperforms|beat|beats|beating|superior|excess return|abnormal return|alpha|higher sharpe|"
    r"improve.?risk.?adjusted|lower drawdown|drawdown reduction|better performance|profitable)\b",
    re.I,
)
NEGATIVE_OUTPERFORM_RE = re.compile(
    r"\b(no evidence[^.]{0,120}outperform|none[^.]{0,120}outperform|does not[^.]{0,80}outperform|"
    r"do not[^.]{0,80}outperform|did not[^.]{0,80}outperform|would not[^.]{0,80}beat|"
    r"not beat[^.]{0,80}buy.?and.?hold|under.?performs?[^.]{0,120}buy.?and.?hold|"
    r"fails?[^.]{0,120}beat|struggle[^.]{0,120}surpass)\b",
    re.I,
)
GENERIC_RULE_RE = re.compile(r"convert the documented signal into a causal rule", re.I)
OTHER_TRADED_ASSET_RE = re.compile(
    r"\b(qqq|nasdaq|iwm|russell|efa|eem|acwi|world|global equity|international|developed markets|emerging markets|"
    r"tlt|ief|agg|bnd|ewy|bond etf|treasury etf|gold|gld|commodity etf|dbc|forex|currency pair|futures markets|"
    r"multi.?asset|cross.?asset|sector etf|sector rotation|individual stocks|single stocks|stock portfolio|"
    r"equities portfolio|vix futures|option portfolio|options strategy|put option|call option|credit portfolio|reit)\b",
    re.I,
)


QUERY_BANK = [
    "S&P 500 market timing strategy outperforms buy and hold",
    "S&P 500 trading rule beats buy and hold",
    "SPY trading strategy outperforms S&P 500",
    "S&P 500 moving average trading rule outperform",
    "S&P 500 200 day moving average strategy study",
    "S&P 500 10 month moving average strategy paper",
    "S&P 500 trend following strategy paper",
    "S&P 500 time series momentum strategy paper",
    "S&P 500 volatility managed portfolio outperform",
    "S&P 500 volatility timing strategy paper",
    "VIX market timing S&P 500 strategy outperform",
    "VIX predicts S&P 500 returns trading strategy",
    "S&P 500 seasonal trading strategy sell in May outperform",
    "S&P 500 turn of the month strategy paper",
    "S&P 500 presidential cycle trading strategy",
    "S&P 500 technical trading rules outperform paper",
    "S&P 500 long short market timing strategy paper",
    "S&P 500 crash prediction trading strategy outperforms",
    "S&P 500 risk on risk off market timing strategy",
    "S&P 500 macro market timing strategy outperform",
    "Investing in the S&P 500 index can anything beat buy and hold",
    "Leverage for the Long Run S&P 500 200-day moving average rotation",
    "S&P 500 Halloween indicator strategy buy and hold paper",
    "S&P 500 sell in May go away strategy buy and hold study",
    "S&P 500 turn of the month effect switching strategy outperform",
    "S&P 500 futures Halloween effect buy and hold Maberly Pierce",
    "S&P 500 200 day moving average rotation buy and hold study",
    "S&P 500 fed model market timing strategy buy and hold",
    "S&P 500 earnings yield interest rates market timing strategy worked",
    "S&P 500 technical analysis relative maxima minima buy and hold",
]


@dataclass(frozen=True)
class Candidate:
    source: str
    study_id: str
    title: str
    year: str
    doi: str
    url: str
    query: str
    strategy_family: str
    rule_or_abstract: str
    tradable_assets: str
    benchmark: str
    evidence_strength: str
    sp500_only_evidence: str
    outperform_evidence: str
    reject_reasons: str = ""

    def as_row(self) -> dict[str, str]:
        return {
            "source": self.source,
            "study_id": self.study_id,
            "title": self.title,
            "year": self.year,
            "doi": self.doi,
            "url": self.url,
            "query": self.query,
            "strategy_family": self.strategy_family,
            "rule_or_abstract": self.rule_or_abstract,
            "tradable_assets": self.tradable_assets,
            "benchmark": self.benchmark,
            "evidence_strength": self.evidence_strength,
            "sp500_only_evidence": self.sp500_only_evidence,
            "outperform_evidence": self.outperform_evidence,
            "reject_reasons": self.reject_reasons,
        }


def main(argv: list[str] | None = None) -> int:
    require_github_actions_or_explicit_local_permission("SP500-only literature study finder")
    parser = argparse.ArgumentParser(description="Find studies with SP500-only strategies that claim to beat SP500.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--exactness-csv", default=DEFAULT_EXACTNESS)
    parser.add_argument("--import-manifest", default=DEFAULT_IMPORT)
    parser.add_argument("--pages-per-query", type=int, default=5)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args(argv)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    candidates: list[Candidate] = []
    rejected: list[Candidate] = []
    candidates.extend(_scan_exactness(Path(args.exactness_csv), rejected))
    candidates.extend(_scan_import_manifest(Path(args.import_manifest), rejected))
    if not args.local_only:
        candidates.extend(
            _search_openalex(
                pages_per_query=int(args.pages_per_query),
                per_page=int(args.per_page),
                sleep_seconds=float(args.sleep_seconds),
                rejected=rejected,
            )
        )
    candidates = _dedupe(candidates)
    rejected = _dedupe(rejected)

    _write_csv(out / "sp500_only_outperforming_study_candidates.csv", candidates)
    _write_csv(out / "sp500_only_outperforming_study_rejected.csv", rejected)
    _write_csv(
        out / "sp500_only_outperforming_query_bank.csv",
        [
            Candidate(
                source="query_bank",
                study_id="",
                title=query,
                year="",
                doi="",
                url="",
                query=query,
                strategy_family="",
                rule_or_abstract="",
                tradable_assets="",
                benchmark="S&P 500",
                evidence_strength="query",
                sp500_only_evidence="",
                outperform_evidence="",
            )
            for query in QUERY_BANK
        ],
    )
    summary = {
        "candidate_count": len(candidates),
        "rejected_or_review_count": len(rejected),
        "queries": len(QUERY_BANK),
        "pages_per_query": int(args.pages_per_query),
        "per_page": int(args.per_page),
        "local_only": bool(args.local_only),
        "locked_opened": False,
        "backtest_enabled": False,
        "definition": "Study must mention an S&P 500/SPY/SPX tradable rule and evidence of outperforming/beating/improving versus S&P 500 or buy-and-hold. Other traded assets reject it.",
        "important_caveat": "This is a discovery classifier. Strong candidates still require full-text verification before claiming the paper truly proves the rule.",
    }
    (out / "sp500_only_outperforming_study_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _scan_exactness(path: Path, rejected: list[Candidate]) -> list[Candidate]:
    if not path.exists():
        return []
    rows: list[Candidate] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            text = _join(
                row.get("study_title"),
                row.get("strategy_family"),
                row.get("signal_formula"),
                row.get("asset_universe"),
                row.get("tradable_assets"),
                row.get("position_rule"),
                row.get("benchmark"),
                row.get("review_reason"),
                row.get("evidence_quote_refs"),
            )
            candidate = _classify(
                source="local_exactness",
                study_id=row.get("study_id", ""),
                title=row.get("study_title", ""),
                year="",
                doi="",
                url="",
                query="local exactness csv",
                strategy_family=row.get("strategy_family", ""),
                rule_or_abstract=_join(row.get("signal_formula"), row.get("position_rule"), row.get("thresholds")),
                tradable_assets=_join(row.get("asset_universe"), row.get("tradable_assets")),
                benchmark=row.get("benchmark", ""),
                text=text,
            )
            if candidate.reject_reasons:
                rejected.append(candidate)
            else:
                rows.append(candidate)
    return rows


def _scan_import_manifest(path: Path, rejected: list[Candidate]) -> list[Candidate]:
    if not path.exists():
        return []
    rows: list[Candidate] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            text = _join(
                row.get("study_title"),
                row.get("strategy_family"),
                row.get("hypothesis"),
                row.get("rule_plain_extracted"),
                row.get("tradable_assets_json"),
                row.get("required_features_json"),
                row.get("reason_to_test"),
            )
            candidate = _classify(
                source="local_import_manifest",
                study_id=row.get("study_id", ""),
                title=row.get("study_title", ""),
                year=row.get("study_year", ""),
                doi=row.get("doi", ""),
                url=row.get("oa_url", ""),
                query="local import manifest",
                strategy_family=row.get("strategy_family", ""),
                rule_or_abstract=_join(row.get("hypothesis"), row.get("rule_plain_extracted")),
                tradable_assets=row.get("tradable_assets_json", ""),
                benchmark="",
                text=text,
            )
            if candidate.reject_reasons:
                rejected.append(candidate)
            else:
                rows.append(candidate)
    return rows


def _search_openalex(*, pages_per_query: int, per_page: int, sleep_seconds: float, rejected: list[Candidate]) -> list[Candidate]:
    rows: list[Candidate] = []
    for query in QUERY_BANK:
        for page in range(1, pages_per_query + 1):
            payload = _openalex_search(query, page=page, per_page=per_page)
            for work in payload.get("results", []) or []:
                if not isinstance(work, dict):
                    continue
                abstract = _abstract(work.get("abstract_inverted_index"))
                text = _join(work.get("display_name"), abstract)
                doi = str(work.get("doi") or "")
                url = str(work.get("primary_location", {}).get("landing_page_url") or work.get("id") or "")
                candidate = _classify(
                    source="openalex",
                    study_id=str(work.get("id", "")).rsplit("/", 1)[-1],
                    title=str(work.get("display_name") or ""),
                    year=str(work.get("publication_year") or ""),
                    doi=doi,
                    url=url,
                    query=query,
                    strategy_family="external_search",
                    rule_or_abstract=abstract,
                    tradable_assets="",
                    benchmark="",
                    text=text,
                )
                if candidate.reject_reasons:
                    rejected.append(candidate)
                else:
                    rows.append(candidate)
            time.sleep(sleep_seconds)
    return rows


def _classify(
    *,
    source: str,
    study_id: str,
    title: str,
    year: str,
    doi: str,
    url: str,
    query: str,
    strategy_family: str,
    rule_or_abstract: str,
    tradable_assets: str,
    benchmark: str,
    text: str,
) -> Candidate:
    reasons: list[str] = []
    title_rule_assets = _join(title, rule_or_abstract, tradable_assets, benchmark)
    full_text = _join(text, title_rule_assets)
    if not SP500_RE.search(full_text):
        reasons.append("no_explicit_sp500_spy_spx_in_source_text")
    if not SP500_RE.search(title_rule_assets):
        reasons.append("no_explicit_sp500_spy_spx_in_rule_title_assets")
    if not MARKET_CONTEXT_RE.search(full_text):
        reasons.append("no_financial_market_context")
    if not STRATEGY_RE.search(full_text):
        reasons.append("no_explicit_trading_strategy_rule")
    if not OUTPERFORM_RE.search(text):
        reasons.append("no_outperform_claim_found")
    if NEGATIVE_OUTPERFORM_RE.search(full_text):
        reasons.append("negative_or_non_outperform_result")
    if NON_FINANCE_RE.search(full_text):
        reasons.append("non_finance_or_non_trading_context")
    cleaned_assets = SP500_RE.sub(" ", _join(tradable_assets, rule_or_abstract))
    if OTHER_TRADED_ASSET_RE.search(cleaned_assets):
        reasons.append("mentions_other_traded_assets")
    if GENERIC_RULE_RE.search(rule_or_abstract):
        reasons.append("generic_template_rule_not_paper_specific")
    if source.startswith("local_") and not _clean(title):
        reasons.append("local_row_missing_clean_title")
    strength = "strong" if not reasons and OUTPERFORM_RE.search(rule_or_abstract) else "medium" if not reasons else "rejected"
    return Candidate(
        source=source,
        study_id=study_id,
        title=_clean(title),
        year=year,
        doi=doi,
        url=url,
        query=query,
        strategy_family=strategy_family,
        rule_or_abstract=_clean(rule_or_abstract)[:4000],
        tradable_assets=_clean(tradable_assets)[:1000],
        benchmark=_clean(benchmark)[:500],
        evidence_strength=strength,
        sp500_only_evidence=_snippet(title_rule_assets, SP500_RE),
        outperform_evidence=_snippet(text, OUTPERFORM_RE),
        reject_reasons=";".join(reasons),
    )


def _openalex_search(query: str, *, page: int, per_page: int) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "search": query,
            "per-page": max(1, min(200, per_page)),
            "page": page,
            "filter": "type:article|preprint|book-chapter",
            "mailto": "aurora-research@example.com",
        }
    )
    url = f"https://api.openalex.org/works?{params}"
    with urllib.request.urlopen(url, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _abstract(index: Any) -> str:
    if not isinstance(index, dict):
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in index.items():
        if isinstance(positions, list):
            for pos in positions:
                if isinstance(pos, int):
                    pairs.append((pos, str(word)))
    return " ".join(word for _, word in sorted(pairs))


def _dedupe(rows: list[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for row in sorted(rows, key=lambda item: (item.study_id or item.doi or item.title).lower()):
        key = (row.doi or row.study_id or re.sub(r"\W+", " ", row.title).lower()).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _write_csv(path: Path, rows: list[Candidate]) -> None:
    cols = list(Candidate("", "", "", "", "", "", "", "", "", "", "", "", "", "").as_row().keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_row())


def _join(*parts: object) -> str:
    return " ".join(str(part or "") for part in parts)


def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _snippet(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    start = max(0, match.start() - 120)
    end = min(len(text), match.end() + 180)
    return _clean(text[start:end])


if __name__ == "__main__":
    raise SystemExit(main())
