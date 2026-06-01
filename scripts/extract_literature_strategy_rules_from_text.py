"""Classify whether extracted paper text supports exact strategy replication."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_literature_pdf_text_chunks import read_jsonl_zst


FIELD_PATTERNS = {
    "frequency": re.compile(r"\b(daily|weekly|monthly|quarterly|intraday)\b", re.I),
    "direction": re.compile(
        r"\b(long|short|buy|sell|overweight|underweight|increase exposure|reduce exposure)\b",
        re.I,
    ),
    "formula": re.compile(
        r"\b(signal|factor|score|spread|momentum|moving average|regression|rank|threshold)\b",
        re.I,
    ),
    "universe": re.compile(
        r"\b(universe|stocks?|equities|sectors?|bonds?|currenc(?:y|ies)|commodit(?:y|ies)|"
        r"SPY|S&P 500|ETF|futures?)\b",
        re.I,
    ),
    "costs": re.compile(r"\b(transaction costs?|costs?|commissions?|slippage)\b", re.I),
    "benchmark": re.compile(r"\b(benchmark|S&P 500|SPY|market portfolio|risk-free)\b", re.I),
    "sample_period": re.compile(r"\b(19\d{2}|20\d{2})\s*[-–—to/]+\s*(19\d{2}|20\d{2})\b"),
    "lookback": re.compile(r"\b(\d{1,3})\s*(day|week|month|year)s?\b", re.I),
}


def evidence(text: str, pattern: re.Pattern[str], limit: int = 220) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    start = max(0, match.start() - 90)
    end = min(len(text), match.end() + 90)
    return re.sub(r"\s+", " ", text[start:end]).strip()[:limit]


def classify_text(row: dict[str, Any]) -> dict[str, Any]:
    text = str(row.get("text") or "")
    found = {name: bool(regex.search(text)) for name, regex in FIELD_PATTERNS.items()}
    missing = [
        field
        for field in ("formula", "universe", "direction", "frequency")
        if not found.get(field)
    ]
    if not missing:
        status = "exact_replicable"
    elif found["formula"] and found["direction"] and found["universe"]:
        status = "template_replicable"
    elif found["formula"] or found["direction"] or found["universe"]:
        status = "needs_review"
    else:
        status = "not_replicable"
    quotes = {
        name: evidence(text, regex)
        for name, regex in FIELD_PATTERNS.items()
        if regex.search(text)
    }
    return {
        "study_id": row.get("study_id", ""),
        "idea_id": row.get("idea_id", ""),
        "strategy_family": row.get("strategy_family", ""),
        "signal_formula": quotes.get("formula", ""),
        "asset_universe": quotes.get("universe", ""),
        "tradable_assets": row.get("title", ""),
        "frequency": quotes.get("frequency", ""),
        "rebalance_rule": quotes.get("frequency", ""),
        "position_rule": quotes.get("direction", ""),
        "thresholds": quotes.get("formula", ""),
        "lookback_windows": quotes.get("lookback", ""),
        "lags_required": "",
        "costs_assumption": quotes.get("costs", ""),
        "sample_period": quotes.get("sample_period", ""),
        "benchmark": quotes.get("benchmark", ""),
        "exactness_status": status,
        "missing_fields_json": json.dumps(missing, ensure_ascii=False),
        "evidence_quote_refs": json.dumps(quotes, ensure_ascii=False),
        "paper_exact_replication": "1" if status == "exact_replicable" else "0",
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "study_id",
        "idea_id",
        "strategy_family",
        "signal_formula",
        "asset_universe",
        "tradable_assets",
        "frequency",
        "rebalance_rule",
        "position_rule",
        "thresholds",
        "lookback_windows",
        "lags_required",
        "costs_assumption",
        "sample_period",
        "benchmark",
        "exactness_status",
        "missing_fields_json",
        "evidence_quote_refs",
        "paper_exact_replication",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", default="")
    args = parser.parse_args(argv)
    corpus_rows, _errors = read_jsonl_zst(Path(args.corpus))
    rows = [classify_text(row) for row in corpus_rows]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_csv(out, rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["exactness_status"]] = counts.get(row["exactness_status"], 0) + 1
    summary = {
        "rows": len(rows),
        "exactness_counts": counts,
        "paper_exact_replication_true": sum(1 for row in rows if row["paper_exact_replication"] == "1"),
        "paper_exact_replication_false": sum(1 for row in rows if row["paper_exact_replication"] == "0"),
        "output": str(out),
    }
    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
