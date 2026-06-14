from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.execution_policy import require_github_actions_or_explicit_local_permission  # noqa: E402
from scripts.find_sp500_only_outperforming_studies import (  # noqa: E402
    NEGATIVE_OUTPERFORM_RE,
    OTHER_TRADED_ASSET_RE,
    OUTPERFORM_BENCHMARK_RE,
    SP500_RE,
    STRATEGY_RE,
)

csv.field_size_limit(sys.maxsize)

MANUAL_PDF_URLS = {
    "manual_dichtl_sp500_buy_hold_2020": "https://www.boerse-institut.de/fileadmin/pdf/Dichtl_SP500-Investing.pdf",
    "manual_gayed_leverage_long_run_2016": "https://foro.masdividendos.com/uploads/default/original/1X/a8ba34a1c6b2ff3dc74ca0689eda699a7d99a1cd.pdf",
    "manual_trend_stop_loss_frequency_sp500": "https://openaccess.city.ac.uk/id/eprint/17842/8/BLACKBOX%20%20%20SSRN-id2126476.pdf",
    "manual_hull_qiao_bakosova_one_month_2019": "https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID3050254_code1752693.pdf?abstractid=3050254",
    "manual_trainor_buy_hold_market_timer_2018": "https://www.westga.edu/~bquest/2018/buy%26hold2018.pdf",
    "manual_tang_whitelaw_time_varying_sharpe_2011": "https://pages.stern.nyu.edu/~rwhitela/papers/tv%20sharpe%20qjf%202011.pdf",
    "manual_zarattini_intraday_momentum_spy_2024": "https://alexandria.unisg.ch/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/download",
    "manual_spy_intraday_momentum_improvements_2025": "https://papers.ssrn.com/sol3/Delivery.cfm/5095349.pdf?abstractid=5095349&mirid=1",
    "manual_probability_weighting_equity_premium_2024": "https://papers.ssrn.com/sol3/Delivery.cfm/4592479.pdf?abstractid=4592479&mirid=1",
}


def main(argv: list[str] | None = None) -> int:
    require_github_actions_or_explicit_local_permission("SP500-only full-text verification")
    parser = argparse.ArgumentParser(description="Verify SP500-only outperforming study candidates.")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-pdf-mb", type=int, default=40)
    args = parser.parse_args(argv)

    candidates = _read_csv(Path(args.candidates))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [_verify(row, max_pdf_bytes=int(args.max_pdf_mb) * 1024 * 1024) for row in candidates]
    _write_csv(out / "sp500_only_full_text_verification.csv", rows)
    summary = {
        "input_candidates": len(candidates),
        "confirmed": sum(1 for row in rows if row["verification_status"] == "confirmed"),
        "confirmed_from_metadata": sum(1 for row in rows if row["verification_status"] == "confirmed_from_metadata"),
        "needs_full_text": sum(1 for row in rows if row["verification_status"] == "needs_full_text"),
        "needs_review_conflicting_evidence": sum(
            1 for row in rows if row["verification_status"] == "needs_review_conflicting_evidence"
        ),
        "rejected": sum(1 for row in rows if row["verification_status"] == "rejected"),
        "pdf_text_extracted": sum(1 for row in rows if row["text_source"] == "pdf"),
        "locked_opened": False,
        "backtest_enabled": False,
    }
    (out / "sp500_only_full_text_verification_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _verify(row: dict[str, str], *, max_pdf_bytes: int) -> dict[str, str]:
    text_source = "metadata"
    text = _join(row.get("title"), row.get("rule_or_abstract"), row.get("tradable_assets"), row.get("benchmark"))
    openalex = _openalex_work(row)
    pdf_url = ""
    if openalex:
        text = _join(text, _abstract(openalex.get("abstract_inverted_index")))
        pdf_url = _first_pdf_url(openalex)
    pdf_url = pdf_url or MANUAL_PDF_URLS.get(str(row.get("study_id") or ""), "")
    if pdf_url:
        pdf_text = _download_pdf_text(pdf_url, max_bytes=max_pdf_bytes)
        if pdf_text:
            text = _join(text, pdf_text)
            text_source = "pdf"
    cleaned_assets = SP500_RE.sub(" ", _join(row.get("tradable_assets"), row.get("rule_or_abstract")))
    reasons: list[str] = []
    if not SP500_RE.search(text):
        reasons.append("no_sp500_in_text")
    if not STRATEGY_RE.search(text):
        reasons.append("no_strategy_rule_in_text")
    if not OUTPERFORM_BENCHMARK_RE.search(text):
        reasons.append("no_outperform_vs_sp500_or_buyhold_evidence_in_text")
    if NEGATIVE_OUTPERFORM_RE.search(text):
        reasons.append("negative_or_non_outperform_result")
    if OTHER_TRADED_ASSET_RE.search(cleaned_assets):
        reasons.append("other_traded_assets_in_candidate_rule")
    has_positive_evidence = bool(OUTPERFORM_BENCHMARK_RE.search(text))
    has_core_evidence = bool(SP500_RE.search(text) and STRATEGY_RE.search(text) and has_positive_evidence)
    status = "confirmed" if not reasons and text_source == "pdf" else "confirmed_from_metadata" if not reasons else "needs_full_text"
    if "other_traded_assets_in_candidate_rule" in reasons:
        status = "rejected"
    elif "negative_or_non_outperform_result" in reasons and text_source == "pdf" and has_core_evidence:
        status = "needs_review_conflicting_evidence"
    elif "negative_or_non_outperform_result" in reasons:
        status = "rejected"
    out = dict(row)
    out.update(
        {
            "verification_status": status,
            "verification_reasons": ";".join(reasons),
            "text_source": text_source,
            "pdf_url_used": pdf_url,
            "sp500_quote": _snippet(text, SP500_RE),
            "strategy_quote": _snippet(text, STRATEGY_RE),
            "outperform_quote": _snippet(text, OUTPERFORM_BENCHMARK_RE),
            "negative_quote": _snippet(text, NEGATIVE_OUTPERFORM_RE),
            "locked_opened": "false",
            "backtest_enabled": "false",
        }
    )
    return out


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _openalex_work(row: dict[str, str]) -> dict[str, Any] | None:
    study_id = str(row.get("study_id") or "")
    doi = str(row.get("doi") or "")
    url = ""
    if re.fullmatch(r"W\d+", study_id):
        url = f"https://api.openalex.org/works/{study_id}"
    elif doi:
        url = "https://api.openalex.org/works/" + urllib.parse.quote(doi, safe="")
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _first_pdf_url(work: dict[str, Any]) -> str:
    locations = []
    best = work.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    for item in work.get("locations") or []:
        if isinstance(item, dict):
            locations.append(item)
    for location in locations:
        url = str(location.get("pdf_url") or "")
        if url:
            return url
    return ""


def _download_pdf_text(url: str, *, max_bytes: int) -> str:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Aurora SP500 study verifier/1.0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            content_type = response.headers.get("content-type", "")
            payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            return ""
        if not (payload.startswith(b"%PDF") or "pdf" in content_type.lower()):
            return ""
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(payload))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""
    except Exception:
        return ""


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


def _join(*parts: object) -> str:
    return " ".join(str(part or "") for part in parts)


def _snippet(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text or "")
    if not match:
        return ""
    start = max(0, match.start() - 120)
    end = min(len(text), match.end() + 220)
    return re.sub(r"\s+", " ", text[start:end]).strip()


if __name__ == "__main__":
    raise SystemExit(main())
