"""Auditable source discovery for future research inputs.

This module is deliberately conservative. It does not pretend to crawl the
whole internet without a search API. It maintains a curated, extendable catalog
of useful public sources, marks what Aurora already supports, optionally checks
that URLs are reachable, and writes a report that can feed later connector work.
"""
from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aurora.core.runtime_paths import base_data_dir


UrlChecker = Callable[[str], bool]


_INTEGRATED_SOURCE_IDS = frozenset({
    "akshare",
    "binance_public_data",
    "bls_public_api",
    "ccxt",
    "cftc_cot",
    "coingecko",
    "coinmetrics_community",
    "dbnomics",
    "dukascopy",
    "ecb_data_portal",
    "finance_database",
    "fred",
    "federal_reserve_h15",
    "kenneth_french",
    "marketdata_app",
    "nasdaq_trader",
    "openfigi",
    "sec_edgar_companyfacts",
    "stooq",
    "tiingo",
    "yahooquery",
    "yfinance",
    "yale_shiller",
})


@dataclass(frozen=True)
class SourceCandidate:
    """One possible data source Aurora may use in research."""

    source_id: str
    name: str
    category: str
    asset_classes: tuple[str, ...]
    signal_types: tuple[str, ...]
    url: str
    free_access: bool
    requires_key: bool
    history_start_year: int | None
    update_frequency: str
    useful_for_sp500: bool
    integration_status: str
    connector_hint: str
    access_notes: str
    terms_notes: str
    priority: int
    already_integrated: bool = False
    url_status: str = "not_checked"

    def with_status(self, *, already_integrated: bool, url_status: str) -> SourceCandidate:
        return SourceCandidate(
            source_id=self.source_id,
            name=self.name,
            category=self.category,
            asset_classes=self.asset_classes,
            signal_types=self.signal_types,
            url=self.url,
            free_access=self.free_access,
            requires_key=self.requires_key,
            history_start_year=self.history_start_year,
            update_frequency=self.update_frequency,
            useful_for_sp500=self.useful_for_sp500,
            integration_status=self.integration_status,
            connector_hint=self.connector_hint,
            access_notes=self.access_notes,
            terms_notes=self.terms_notes,
            priority=self.priority,
            already_integrated=already_integrated,
            url_status=url_status,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SourceDiscoveryConfig:
    """Filters for source discovery."""

    categories: tuple[str, ...] = ()
    free_only: bool = True
    useful_for_sp500_only: bool = False
    min_history_year: int | None = None
    verify_urls: bool = False
    output_dir: str | None = None
    include_integrated: bool = True

    def run_root(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        return base_data_dir() / "research" / "source_discovery"


@dataclass(frozen=True)
class SourceDiscoveryReport:
    """Result of one discovery pass."""

    generated_at: str
    candidates: tuple[SourceCandidate, ...]
    recommended_new_sources: tuple[SourceCandidate, ...]
    rejected_count: int
    output_dir: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "policy": {
                "does_not_open_locked": True,
                "does_not_select_strategy": True,
                "purpose": "discover_candidate_sources_only",
            },
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "recommended_new_sources": [
                candidate.to_dict() for candidate in self.recommended_new_sources
            ],
            "rejected_count": self.rejected_count,
            "output_dir": str(self.output_dir),
        }


def discover_sources(
    config: SourceDiscoveryConfig | None = None,
    *,
    url_checker: UrlChecker | None = None,
) -> SourceDiscoveryReport:
    """Filter the curated source catalog and write an auditable report."""

    cfg = config or SourceDiscoveryConfig()
    checker = url_checker or _default_url_checker
    selected: list[SourceCandidate] = []
    rejected_count = 0

    for candidate in _catalog():
        if cfg.categories and candidate.category not in cfg.categories:
            rejected_count += 1
            continue
        if cfg.free_only and not candidate.free_access:
            rejected_count += 1
            continue
        if cfg.useful_for_sp500_only and not candidate.useful_for_sp500:
            rejected_count += 1
            continue
        if (
            cfg.min_history_year is not None
            and candidate.history_start_year is not None
            and candidate.history_start_year > cfg.min_history_year
        ):
            rejected_count += 1
            continue

        already_integrated = candidate.source_id in _INTEGRATED_SOURCE_IDS
        if already_integrated and not cfg.include_integrated:
            rejected_count += 1
            continue

        url_status = "not_checked"
        if cfg.verify_urls:
            url_status = "ok" if checker(candidate.url) else "failed"

        selected.append(candidate.with_status(
            already_integrated=already_integrated,
            url_status=url_status,
        ))

    selected.sort(key=lambda item: (item.already_integrated, item.priority, item.name))
    recommended = tuple(
        candidate
        for candidate in selected
        if not candidate.already_integrated and candidate.free_access
    )
    report = SourceDiscoveryReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        candidates=tuple(selected),
        recommended_new_sources=recommended,
        rejected_count=rejected_count,
        output_dir=cfg.run_root(),
    )
    _write_report(report)
    return report


def source_report_to_markdown(report: SourceDiscoveryReport) -> str:
    """Render a compact human-readable report."""

    lines = [
        "# Aurora Source Discovery",
        "",
        f"Generated: {report.generated_at}",
        f"Candidates: {len(report.candidates)}",
        f"Recommended new sources: {len(report.recommended_new_sources)}",
        "",
        "| Source | Category | Integrated | Priority | Notes |",
        "|---|---|---:|---:|---|",
    ]
    for candidate in report.candidates:
        integrated = "yes" if candidate.already_integrated else "no"
        lines.append(
            f"| {candidate.name} | {candidate.category} | {integrated} | "
            f"{candidate.priority} | {candidate.connector_hint} |"
        )
    return "\n".join(lines)


def _write_report(report: SourceDiscoveryReport) -> None:
    output_dir = report.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "source_discovery_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    candidate_config = {
        "notes": [
            "Candidate source list only. A connector still needs tests, "
            "terms review, and protocol wiring before live research use.",
        ],
        "sources": [
            {
                "source_id": item.source_id,
                "name": item.name,
                "category": item.category,
                "connector_hint": item.connector_hint,
                "url": item.url,
            }
            for item in report.recommended_new_sources
        ],
    }
    (output_dir / "autosearch_source_candidates.json").write_text(
        json.dumps(candidate_config, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _default_url_checker(url: str) -> bool:
    try:
        request = Request(url, method="HEAD", headers={"User-Agent": "aurora-source-discovery"})
        with urlopen(request, timeout=8) as response:
            return 200 <= int(response.status) < 400
    except HTTPError as exc:
        if exc.code in {403, 405}:
            return _get_url(url)
        return False
    except (OSError, socket.timeout, URLError, ValueError):
        return False


def _get_url(url: str) -> bool:
    try:
        request = Request(url, headers={"User-Agent": "aurora-source-discovery"})
        with urlopen(request, timeout=8) as response:
            return 200 <= int(response.status) < 400
    except (OSError, socket.timeout, HTTPError, URLError, ValueError):
        return False


def _src(
    source_id: str,
    name: str,
    category: str,
    asset_classes: Iterable[str],
    signal_types: Iterable[str],
    url: str,
    *,
    free_access: bool,
    requires_key: bool,
    history_start_year: int | None,
    update_frequency: str,
    useful_for_sp500: bool,
    integration_status: str,
    connector_hint: str,
    access_notes: str,
    terms_notes: str,
    priority: int,
) -> SourceCandidate:
    return SourceCandidate(
        source_id=source_id,
        name=name,
        category=category,
        asset_classes=tuple(asset_classes),
        signal_types=tuple(signal_types),
        url=url,
        free_access=free_access,
        requires_key=requires_key,
        history_start_year=history_start_year,
        update_frequency=update_frequency,
        useful_for_sp500=useful_for_sp500,
        integration_status=integration_status,
        connector_hint=connector_hint,
        access_notes=access_notes,
        terms_notes=terms_notes,
        priority=priority,
    )


def _catalog() -> tuple[SourceCandidate, ...]:
    return (
        _src(
            "fred",
            "FRED",
            "macro",
            ("macro", "rates", "credit"),
            ("rates", "spreads", "macro"),
            "https://fred.stlouisfed.org/docs/api/fred/",
            free_access=True,
            requires_key=True,
            history_start_year=None,
            update_frequency="mixed",
            useful_for_sp500=True,
            integration_status="connector_exists",
            connector_hint="Already covered by fred_daily; extend series list first.",
            access_notes="Free key; broad macro and rates coverage.",
            terms_notes="Official St Louis Fed API terms apply.",
            priority=1,
        ),
        _src(
            "cftc_cot",
            "CFTC Commitments of Traders",
            "positioning",
            ("futures", "macro"),
            ("positioning", "risk_appetite", "crowding"),
            "https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm",
            free_access=True,
            requires_key=False,
            history_start_year=1986,
            update_frequency="weekly",
            useful_for_sp500=True,
            integration_status="connector_exists",
            connector_hint="Covered by cftc_cot_weekly; extend feature wiring next.",
            access_notes="Historical compressed files are publicly available.",
            terms_notes="Official CFTC public reports; preserve release timing.",
            priority=1,
        ),
        _src(
            "kenneth_french",
            "Kenneth French Data Library",
            "factors",
            ("equities",),
            ("value", "size", "momentum", "profitability", "investment"),
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
            free_access=True,
            requires_key=False,
            history_start_year=1926,
            update_frequency="monthly_daily_mixed",
            useful_for_sp500=True,
            integration_status="connector_exists",
            connector_hint="Covered by kenneth_french_factors; extend feature wiring next.",
            access_notes="Public academic factor files.",
            terms_notes="Academic data library; cite source in reports.",
            priority=1,
        ),
        _src(
            "cboe_market_statistics",
            "Cboe Market Statistics",
            "sentiment",
            ("options", "equities"),
            ("put_call", "volume", "volatility"),
            "https://www.cboe.com/us/options/market_statistics/daily/",
            free_access=True,
            requires_key=False,
            history_start_year=None,
            update_frequency="daily",
            useful_for_sp500=True,
            integration_status="missing_connector",
            connector_hint="Add scraper/downloader only if terms and history are acceptable.",
            access_notes="Daily statistics page; bulk history may be limited.",
            terms_notes="Cboe states data is furnished for visitor convenience.",
            priority=2,
        ),
        _src(
            "federal_reserve_h15",
            "Federal Reserve H15",
            "rates",
            ("rates",),
            ("rates", "yield_curve"),
            "https://www.federalreserve.gov/releases/h15/data.htm",
            free_access=True,
            requires_key=False,
            history_start_year=None,
            update_frequency="business_daily",
            useful_for_sp500=True,
            integration_status="connector_exists",
            connector_hint="Covered by federal_reserve_h15; extend rate feature wiring next.",
            access_notes="Official downloadable interest-rate release.",
            terms_notes="Official Federal Reserve statistical release.",
            priority=2,
        ),
        _src(
            "bls_public_api",
            "BLS Public Data API",
            "macro",
            ("macro", "labor"),
            ("employment", "inflation", "wages"),
            "https://www.bls.gov/bls/api_features.htm",
            free_access=True,
            requires_key=False,
            history_start_year=None,
            update_frequency="monthly_weekly_mixed",
            useful_for_sp500=True,
            integration_status="connector_exists",
            connector_hint="Covered by bls_public_api; extend macro feature wiring next.",
            access_notes="Public API; published limits apply.",
            terms_notes="Official BLS public API.",
            priority=3,
        ),
        _src(
            "bea_api",
            "BEA API",
            "macro",
            ("macro",),
            ("gdp", "income", "industry"),
            "https://www.bea.gov/open-data",
            free_access=True,
            requires_key=True,
            history_start_year=None,
            update_frequency="monthly_quarterly_mixed",
            useful_for_sp500=True,
            integration_status="missing_connector",
            connector_hint="Add BEA connector for GDP and profits with release-date lag.",
            access_notes="Free API key; official US macro data.",
            terms_notes="Official BEA open data API.",
            priority=4,
        ),
        _src(
            "nasdaq_trader",
            "Nasdaq Trader Symbol Directory",
            "identity",
            ("equities", "etfs"),
            ("universe", "symbol_status"),
            "https://nasdaqtrader.com/Trader.aspx?id=symbollookup",
            free_access=True,
            requires_key=False,
            history_start_year=None,
            update_frequency="daily",
            useful_for_sp500=False,
            integration_status="connector_exists",
            connector_hint="Already covered by nasdaq_trader_universe.",
            access_notes="Public symbol directory.",
            terms_notes="Nasdaq terms apply.",
            priority=5,
        ),
        _src(
            "aaii_sentiment",
            "AAII Investor Sentiment Survey",
            "sentiment",
            ("equities",),
            ("sentiment", "survey"),
            "https://www.aaii.com/sentimentsurvey",
            free_access=True,
            requires_key=False,
            history_start_year=1987,
            update_frequency="weekly",
            useful_for_sp500=True,
            integration_status="missing_connector",
            connector_hint="Add manual/import connector if redistribution terms are acceptable.",
            access_notes="Survey page is public; export terms need human review.",
            terms_notes="Do not scrape aggressively; confirm allowed use first.",
            priority=5,
        ),
        _src(
            "yale_shiller",
            "Robert Shiller Data",
            "valuation",
            ("equities", "rates"),
            ("cape", "earnings", "dividends", "rates"),
            "http://www.econ.yale.edu/~shiller/data.htm",
            free_access=True,
            requires_key=False,
            history_start_year=1871,
            update_frequency="monthly",
            useful_for_sp500=True,
            integration_status="connector_exists",
            connector_hint="Covered by yale_shiller; extend valuation feature wiring next.",
            access_notes="Public academic spreadsheet.",
            terms_notes="Academic source; cite in reports.",
            priority=5,
        ),
    )


__all__ = [
    "SourceCandidate",
    "SourceDiscoveryConfig",
    "SourceDiscoveryReport",
    "discover_sources",
    "source_report_to_markdown",
]
