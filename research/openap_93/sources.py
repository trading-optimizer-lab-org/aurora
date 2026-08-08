"""Public no-key source registry, probes and source-selection reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import time

import pandas as pd
import requests

from .accounting_pipeline import implemented_source_pairs as accounting_source_pairs
from .advanced_accounting_pipeline import (
    implemented_source_pairs as advanced_accounting_source_pairs,
)
from .analyst_pipeline import implemented_source_pairs as analyst_source_pairs
from .event_pipeline import implemented_source_pairs as event_source_pairs
from .http import public_headers
from .institutional_pipeline import (
    OPENFIGI_MAPPING_URL,
    implemented_source_pairs as institutional_source_pairs,
)
from .market_pipeline import implemented_source_pairs as market_source_pairs
from .quarterly_pipeline import implemented_source_pairs as quarterly_source_pairs
from .short_interest_pipeline import (
    implemented_source_pairs as short_interest_source_pairs,
)
from .registry import FidelityClass, SignalSpec


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    domain: str
    probe_url: str
    terms_url: str
    license: str
    access_mode: str
    registration_required: bool
    scraping_required: bool
    automation_status: str
    risk_score: int
    symbol_template: str = ""


PUBLIC_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec("openap_reference", "raw.githubusercontent.com", "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/8db892442c2c3a3779b0f1eac4370d3655be15a1/SignalDoc.csv", "https://github.com/OpenSourceAP/CrossSection/blob/master/LICENSE", "GPL-2.0 reference code/data", "public_file", False, False, "authorized_public", 1),
    SourceSpec("sec_edgar", "sec.gov", "https://www.sec.gov/files/company_tickers_exchange.json", "https://www.sec.gov/os/accessing-edgar-data", "US government public data", "official_api_and_bulk", False, False, "authorized_public_rate_limited", 1),
    SourceSpec("yahoo_public", "query1.finance.yahoo.com", "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=5d&interval=1d", "https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html", "Public endpoint; terms must be reviewed", "public_endpoint", False, False, "terms_review_required", 4, "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"),
    SourceSpec("nasdaq_public", "api.nasdaq.com", "https://api.nasdaq.com/api/analyst/AAPL/earnings-forecast", "https://www.nasdaq.com/terms-of-use", "Nasdaq website terms", "public_endpoint", False, True, "terms_restrictive_review_required", 7, "https://api.nasdaq.com/api/analyst/{symbol}/earnings-forecast"),
    SourceSpec("fred_public_csv", "fred.stlouisfed.org", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS,GNPDEF", "https://fred.stlouisfed.org/legal/", "Federal Reserve public series; per-series rights apply", "public_csv", False, False, "authorized_public", 1),
    SourceSpec("kenneth_french", "mba.tuck.dartmouth.edu", "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip", "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html", "Academic public download", "public_zip", False, False, "authorized_public", 1),
    SourceSpec("cboe_public", "cdn.cboe.com", "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", "https://www.cboe.com/terms/", "Cboe website terms", "public_csv", False, False, "public_download_terms_review", 3),
    SourceSpec("sec_13f", "sec.gov", "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip", "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets", "US government public data", "official_bulk_zip", False, False, "authorized_public_rate_limited", 1),
    SourceSpec("openfigi_public", "api.openfigi.com", OPENFIGI_MAPPING_URL, "https://www.openfigi.com/api/documentation", "OpenFIGI public API terms", "official_public_api", False, False, "authorized_public_rate_limited", 2),
    SourceSpec("bea_public", "apps.bea.gov", "https://apps.bea.gov/industry/xls/io-annual/IxI_TR_1997-2024_Summary.xlsx", "https://apps.bea.gov/terms-of-service/index.htm", "US government public data", "official_bulk_file", False, False, "authorized_public", 1),
    SourceSpec("patentsview_public", "data.uspto.gov", "https://data.uspto.gov/bulkdata/datasets/pvannual", "https://www.uspto.gov/terms-use-uspto-websites", "USPTO public research data", "official_bulk_download", False, False, "authorized_public", 1),
    SourceSpec("pastor_stambaugh", "faculty.chicagobooth.edu", "https://faculty.chicagobooth.edu/-/media/faculty/lubos-pastor/data/liq_data_1962_2024.txt", "https://faculty.chicagobooth.edu/lubos-pastor/research", "Academic public download", "public_file", False, False, "authorized_public", 1),
)

TEST_SYMBOLS = ("AAPL", "CARR", "KOP", "META", "RDDT")
TEST_CUSIPS = {
    "AAPL": "037833100",
    "CARR": "14448C104",
    "KOP": "50060P106",
    "META": "30303M102",
    "RDDT": "75734B100",
}

# A reachable endpoint is evidence that a source exists, not evidence that the
# source can calculate a predictor. Entries are added only after an adapter has
# verified every required field and produced a value under tests.
IMPLEMENTED_SIGNAL_SOURCES: frozenset[tuple[str, str]] = frozenset(
    market_source_pairs()
    | accounting_source_pairs()
    | advanced_accounting_source_pairs()
    | analyst_source_pairs()
    | event_source_pairs()
    | quarterly_source_pairs()
    | short_interest_source_pairs()
    | institutional_source_pairs()
)


def implemented_signal_requirements() -> dict[str, frozenset[str]]:
    """Return the complete source bundle required by each implemented signal."""

    requirements: dict[str, set[str]] = {}
    for signal, source_id in IMPLEMENTED_SIGNAL_SOURCES:
        requirements.setdefault(signal, set()).add(source_id)
    return {
        signal: frozenset(sorted(source_ids))
        for signal, source_ids in requirements.items()
    }


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_sample(response: requests.Response, limit: int = 512) -> str:
    text = response.text[:limit]
    return " ".join(text.replace("\x00", "").split())


def probe_source(
    source: SourceSpec,
    *,
    session: requests.Session,
    timeout: int = 45,
) -> dict[str, Any]:
    started = time.monotonic()
    headers = public_headers(sec=source.source_id in {"sec_edgar", "sec_13f"})
    result: dict[str, Any] = {**asdict(source), "tested_at": _utcnow()}
    try:
        if source.source_id == "openfigi_public":
            response = session.post(
                source.probe_url,
                headers={**headers, "Content-Type": "application/json"},
                json=[{"idType": "ID_CUSIP", "idValue": "037833100"}],
                timeout=timeout,
                stream=True,
            )
        else:
            response = session.get(
                source.probe_url, headers=headers, timeout=timeout, stream=True
            )
        prefix = response.raw.read(4096, decode_content=True)
        digest = hashlib.sha256(prefix).hexdigest()
        content_type = response.headers.get("Content-Type", "")
        sample = prefix.decode(response.encoding or "utf-8", errors="replace")[:512]
        result.update(
            status_code=response.status_code,
            content_type=content_type,
            content_length=response.headers.get("Content-Length", ""),
            elapsed_seconds=round(time.monotonic() - started, 3),
            prefix_sha256=digest,
            schema_sample=" ".join(sample.replace("\x00", "").split()),
            requires_cookies=bool(response.cookies),
            probe_ok=200 <= response.status_code < 300 and bool(prefix),
            error="",
        )
    except requests.RequestException as exc:
        result.update(
            status_code=0,
            content_type="",
            content_length="",
            elapsed_seconds=round(time.monotonic() - started, 3),
            prefix_sha256="",
            schema_sample="",
            requires_cookies=False,
            probe_ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    return result


def probe_symbol_coverage(
    source: SourceSpec,
    *,
    session: requests.Session,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 Aurora-OpenAP-Research/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.8",
    }
    rows: list[dict[str, Any]] = []
    if source.source_id == "openfigi_public":
        for symbol in TEST_SYMBOLS:
            cusip = TEST_CUSIPS[symbol]
            try:
                response = session.post(
                    source.probe_url,
                    headers={**headers, "Content-Type": "application/json"},
                    json=[
                        {
                            "idType": "ID_CUSIP",
                            "idValue": cusip,
                            "marketSecDes": "Equity",
                        }
                    ],
                    timeout=timeout,
                )
                payload = response.json() if response.content else []
                candidates = (
                    payload[0].get("data", [])
                    if isinstance(payload, list)
                    and payload
                    and isinstance(payload[0], dict)
                    else []
                )
                tickers = {
                    str(candidate.get("ticker", "")).upper().strip()
                    for candidate in candidates
                    if isinstance(candidate, dict)
                    and str(candidate.get("marketSector", "")).lower() == "equity"
                    and str(candidate.get("exchCode", "")).upper() == "US"
                    and (
                        "common stock"
                        in str(candidate.get("securityType2", "")).lower()
                        or "common stock"
                        in str(candidate.get("securityType", "")).lower()
                    )
                }
                rows.append(
                    {
                        "source_id": source.source_id,
                        "symbol": symbol,
                        "url": source.probe_url,
                        "probe_applicable": True,
                        "probe_key": cusip,
                        "status_code": response.status_code,
                        "content_type": response.headers.get("Content-Type", ""),
                        "nonempty": bool(response.content),
                        "looks_like_error_html": False,
                        "probe_ok": (
                            200 <= response.status_code < 300
                            and symbol in tickers
                        ),
                        "tested_at": _utcnow(),
                        "error": "",
                    }
                )
            except (requests.RequestException, ValueError, TypeError) as exc:
                rows.append(
                    {
                        "source_id": source.source_id,
                        "symbol": symbol,
                        "url": source.probe_url,
                        "probe_applicable": True,
                        "probe_key": cusip,
                        "status_code": 0,
                        "content_type": "",
                        "nonempty": False,
                        "looks_like_error_html": False,
                        "probe_ok": False,
                        "tested_at": _utcnow(),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            time.sleep(0.25)
        return rows
    if not source.symbol_template:
        return [
            {
                "source_id": source.source_id,
                "symbol": symbol,
                "url": source.probe_url,
                "probe_applicable": False,
                "probe_key": "",
                "status_code": "",
                "content_type": "",
                "nonempty": "",
                "looks_like_error_html": False,
                "probe_ok": "",
                "tested_at": _utcnow(),
                "error": "source_is_not_symbol_scoped; see source-level probe",
            }
            for symbol in TEST_SYMBOLS
        ]
    for symbol in TEST_SYMBOLS:
        url = source.symbol_template.format(symbol=symbol)
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            content_type = response.headers.get("Content-Type", "")
            sample = _safe_sample(response)
            looks_like_error_html = "text/html" in content_type.lower() and (
                "access denied" in sample.lower() or "captcha" in sample.lower()
            )
            rows.append({
                "source_id": source.source_id,
                "symbol": symbol,
                "url": url,
                "probe_applicable": True,
                "probe_key": symbol,
                "status_code": response.status_code,
                "content_type": content_type,
                "nonempty": bool(response.content),
                "looks_like_error_html": looks_like_error_html,
                "probe_ok": 200 <= response.status_code < 300 and bool(response.content) and not looks_like_error_html,
                "tested_at": _utcnow(),
            })
        except requests.RequestException as exc:
            rows.append({
                "source_id": source.source_id, "symbol": symbol, "url": url,
                "probe_applicable": True, "probe_key": symbol,
                "status_code": 0, "content_type": "", "nonempty": False,
                "looks_like_error_html": False, "probe_ok": False,
                "tested_at": _utcnow(), "error": f"{type(exc).__name__}: {exc}",
            })
        time.sleep(0.25)
    return rows


def write_source_evidence(output_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    output = Path(output_dir)
    evidence = output / "evidence" / "source_tests"
    evidence.mkdir(parents=True, exist_ok=True)
    source_rows: list[dict[str, Any]] = []
    symbol_rows: list[dict[str, Any]] = []
    with requests.Session() as session:
        for source in PUBLIC_SOURCES:
            row = probe_source(source, session=session)
            source_rows.append(row)
            source_symbol_rows = probe_symbol_coverage(source, session=session)
            symbol_rows.extend(source_symbol_rows)
            (evidence / f"{source.source_id}.json").write_text(
                json.dumps(
                    {**row, "five_company_probe": source_symbol_rows},
                    indent=2,
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )
    source_frame = pd.DataFrame(source_rows)
    symbol_frame = pd.DataFrame(symbol_rows)
    source_frame.to_csv(output / "source_probe_results.csv", index=False)
    symbol_frame.to_csv(output / "source_symbol_probe_results.csv", index=False)
    return source_frame, symbol_frame


def source_coverage_matrix(
    registry: dict[str, SignalSpec],
    probe_results: pd.DataFrame,
) -> pd.DataFrame:
    probe_ok = probe_results.set_index("source_id")["probe_ok"].to_dict()
    requirements = implemented_signal_requirements()
    rows: list[dict[str, Any]] = []
    for signal in registry.values():
        for source in PUBLIC_SOURCES:
            candidate = source.source_id in signal.candidate_sources
            required_bundle = requirements.get(signal.name, frozenset())
            signal_formula_implemented = bool(required_bundle)
            source_required = source.source_id in required_bundle
            formula_implemented = source_required
            required_fields_verified = bool(
                signal_formula_implemented
                and source_required
                and all(bool(probe_ok.get(item, False)) for item in required_bundle)
            )
            rows.append({
                "candidate_source": source.source_id,
                "domain": source.domain,
                "signal": signal.name,
                "candidate_match": candidate,
                "formula_implemented": formula_implemented,
                "signal_formula_implemented": signal_formula_implemented,
                "source_required_by_formula": source_required,
                "required_source_bundle": "|".join(sorted(required_bundle)),
                "required_fields_verified": required_fields_verified,
                "can_produce_value": (
                    candidate
                    and formula_implemented
                    and source_required
                    and required_fields_verified
                    and not source.registration_required
                    and not source.automation_status.startswith("not_eligible_")
                ),
                "expected_fidelity": signal.expected_best_class.value if candidate else "unavailable",
                "source_probe_ok": bool(probe_ok.get(source.source_id, False)),
                "scraping_required": source.scraping_required,
                "registration_required": source.registration_required,
                "automation_status": source.automation_status,
                "cost_eur": 0,
                "risk_score": source.risk_score,
            })
    return pd.DataFrame(rows)


def select_sources_lexicographically(matrix: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    viable = matrix.loc[matrix["can_produce_value"]].copy()
    viable_signals = set(viable["signal"].unique())
    selected = sorted(set(viable["candidate_source"]))
    ablation_rows: list[dict[str, Any]] = []
    for source in selected:
        lost = sorted(set(viable.loc[viable["candidate_source"].eq(source), "signal"]))
        ablation_rows.append({
            "source_id": source,
            "signals_lost_count": len(lost),
            "signals_lost": "|".join(lost),
        })
    payload = {
        "selected_source_ids": selected,
        "selected_domains": sorted({
            source.domain for source in PUBLIC_SOURCES if source.source_id in selected
        }),
        "candidate_signals_covered": len(viable_signals),
        "candidate_signals_uncovered": sorted(set(matrix["signal"].unique()) - viable_signals),
        "selection_method": "exact_required_source_union_after_maximum_coverage",
        "created_at": _utcnow(),
    }
    return payload, pd.DataFrame(ablation_rows)
