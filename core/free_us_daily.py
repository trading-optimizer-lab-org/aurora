"""Free US daily equity data lake helpers.

This module builds a zero-cost, active-US-stock daily price lake from
Nasdaq Trader symbol files plus yfinance history. It is intentionally
marked as research-grade: active listings only, no complete delisted
history, and yfinance is an unofficial source.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import pandas as pd

from aurora.core import runtime_paths
from aurora.core.data_providers.nasdaq_trader_universe import (
    NASDAQ_LISTED_FILE,
    OTHER_LISTED_FILE,
    _default_client as _nasdaq_default_client,
    _parse_nasdaq_pipe_file,
)


DATASET_NAME = "free_us_daily"
SOURCE_YFINANCE = "yfinance"
SOURCE_YFINANCE_INFO = "yfinance_info"
SOURCE_YAHOO_SCREENER = "yahoo_screener"
MIN_ROWS_DEFAULT = 30
ASSET_TYPE_COMMON_STOCK = "COMMON_STOCK"
ASSET_TYPE_ADR = "ADR"
ASSET_TYPE_FOREIGN_COMMON_STOCK = "FOREIGN_COMMON_STOCK"

METADATA_COLUMNS = [
    "symbol",
    "provider_symbol",
    "yfinance_symbol",
    "company_name",
    "security_name",
    "sector",
    "industry",
    "exchange",
    "quote_type",
    "market_cap",
    "shares_outstanding",
    "country",
    "website",
    "status",
    "source",
    "retrieved_at",
    "error",
]

_EXCLUDE_SECURITY_RE = re.compile(
    r"\b("
    r"warrants?|rights?|units?|preferred|preferences?|depositary|"
    r"notes?|bonds?|funds?|etfs?|etns?"
    r")\b",
    re.IGNORECASE,
)
_ADR_SECURITY_RE = re.compile(
    r"\bamerican\s+depositary\s+(shares?|receipts?)\b|\badr\b|\bads\b",
    re.IGNORECASE,
)
_FOREIGN_EXCLUDE_SECURITY_RE = re.compile(
    r"\b("
    r"warrants?|rights?|units?|preferred|preferences?|depositary|"
    r"depository|notes?|bonds?|funds?|etfs?|etns?|trusts?|"
    r"certificates?|adr|gdr|ads|receipts?|spac|"
    r"acquisition\s+(corp|company)"
    r")\b",
    re.IGNORECASE,
)


FOREIGN_YAHOO_MARKETS: tuple[dict[str, str], ...] = (
    {"priority": "alta", "country": "Canada", "region": "ca", "suffix": ".TO"},
    {"priority": "alta", "country": "Canada", "region": "ca", "suffix": ".V"},
    {"priority": "alta", "country": "United Kingdom", "region": "gb", "suffix": ".L"},
    {"priority": "alta", "country": "Germany", "region": "de", "suffix": ".DE"},
    {"priority": "alta", "country": "Germany", "region": "de", "suffix": ".F"},
    {"priority": "alta", "country": "France", "region": "fr", "suffix": ".PA"},
    {"priority": "alta", "country": "Spain", "region": "es", "suffix": ".MC"},
    {"priority": "alta", "country": "Italy", "region": "it", "suffix": ".MI"},
    {"priority": "alta", "country": "Netherlands", "region": "nl", "suffix": ".AS"},
    {"priority": "alta", "country": "Switzerland", "region": "ch", "suffix": ".SW"},
    {"priority": "alta", "country": "Sweden", "region": "se", "suffix": ".ST"},
    {"priority": "alta", "country": "Japan", "region": "jp", "suffix": ".T"},
    {"priority": "alta", "country": "Australia", "region": "au", "suffix": ".AX"},
    {"priority": "alta", "country": "Hong Kong", "region": "hk", "suffix": ".HK"},
    {"priority": "alta", "country": "Singapore", "region": "sg", "suffix": ".SI"},
    {"priority": "media", "country": "Belgium", "region": "be", "suffix": ".BR"},
    {"priority": "media", "country": "Austria", "region": "at", "suffix": ".VI"},
    {"priority": "media", "country": "Denmark", "region": "dk", "suffix": ".CO"},
    {"priority": "media", "country": "Finland", "region": "fi", "suffix": ".HE"},
    {"priority": "media", "country": "Norway", "region": "no", "suffix": ".OL"},
    {"priority": "media", "country": "Portugal", "region": "pt", "suffix": ".LS"},
    {"priority": "media", "country": "Ireland", "region": "ie", "suffix": ".IR"},
    {"priority": "media", "country": "Poland", "region": "pl", "suffix": ".WA"},
    {"priority": "media", "country": "Greece", "region": "gr", "suffix": ".AT"},
    {"priority": "media", "country": "Israel", "region": "il", "suffix": ".TA"},
    {"priority": "media", "country": "New Zealand", "region": "nz", "suffix": ".NZ"},
    {"priority": "media", "country": "Mexico", "region": "mx", "suffix": ".MX"},
    {"priority": "media", "country": "Brazil", "region": "br", "suffix": ".SA"},
    {"priority": "media", "country": "South Africa", "region": "za", "suffix": ".JO"},
    {"priority": "media", "country": "South Korea", "region": "kr", "suffix": ".KS"},
    {"priority": "media", "country": "South Korea", "region": "kr", "suffix": ".KQ"},
    {"priority": "media", "country": "Taiwan", "region": "tw", "suffix": ".TW"},
    {"priority": "media", "country": "Taiwan", "region": "tw", "suffix": ".TWO"},
    {"priority": "media", "country": "India", "region": "in", "suffix": ".NS"},
    {"priority": "media", "country": "India", "region": "in", "suffix": ".BO"},
    {"priority": "baja", "country": "China", "region": "cn", "suffix": ".SS"},
    {"priority": "baja", "country": "China", "region": "cn", "suffix": ".SZ"},
    {"priority": "baja", "country": "Indonesia", "region": "id", "suffix": ".JK"},
    {"priority": "baja", "country": "Malaysia", "region": "my", "suffix": ".KL"},
    {"priority": "baja", "country": "Thailand", "region": "th", "suffix": ".BK"},
    {"priority": "baja", "country": "Philippines", "region": "ph", "suffix": ".PS"},
    {"priority": "baja", "country": "Turkey", "region": "tr", "suffix": ".IS"},
    {"priority": "baja", "country": "Saudi Arabia", "region": "sa", "suffix": ".SAU"},
    {"priority": "baja", "country": "United Arab Emirates", "region": "ae", "suffix": ".AE"},
    {"priority": "baja", "country": "Qatar", "region": "qa", "suffix": ".QA"},
    {"priority": "baja", "country": "Kuwait", "region": "kw", "suffix": ".KW"},
    {"priority": "baja", "country": "Romania", "region": "ro", "suffix": ".RO"},
    {"priority": "baja", "country": "Hungary", "region": "hu", "suffix": ".BD"},
    {"priority": "baja", "country": "Czech Republic", "region": "cz", "suffix": ".PR"},
    {"priority": "baja", "country": "Iceland", "region": "is", "suffix": ".IC"},
    {"priority": "baja", "country": "Estonia", "region": "ee", "suffix": ".TL"},
    {"priority": "baja", "country": "Latvia", "region": "lv", "suffix": ".RG"},
    {"priority": "baja", "country": "Lithuania", "region": "lt", "suffix": ".VS"},
    {"priority": "baja", "country": "Chile", "region": "cl", "suffix": ".SN"},
    {"priority": "baja", "country": "Colombia", "region": "co", "suffix": ".CL"},
    {"priority": "baja", "country": "Argentina", "region": "ar", "suffix": ".BA"},
    {"priority": "baja", "country": "Egypt", "region": "eg", "suffix": ".CA"},
    {"priority": "baja", "country": "Vietnam", "region": "vn", "suffix": ".VN"},
    {"priority": "baja", "country": "Venezuela", "region": "ve", "suffix": ".CR"},
)


DEFAULT_USD_PER_UNIT: dict[str, float] = {
    "USD": 1.0,
    "CAD": 0.729,
    "GBP": 1.344,
    "GBp": 0.01344,
    "EUR": 1.152,
    "CHF": 1.25,
    "SEK": 0.104,
    "JPY": 0.00691,
    "AUD": 0.650,
    "HKD": 0.128,
    "SGD": 0.778,
    "DKK": 0.154,
    "NOK": 0.101,
    "PLN": 0.274,
    "ILS": 0.288,
    "ILA": 0.00288,
    "NZD": 0.602,
    "MXN": 0.0534,
    "BRL": 0.184,
    "ZAR": 0.0574,
    "ZAc": 0.000574,
    "KRW": 0.000724,
    "TWD": 0.0310,
    "INR": 0.0116,
    "CNY": 0.139,
    "IDR": 0.0000604,
    "MYR": 0.237,
    "THB": 0.0307,
    "PHP": 0.0170,
    "TRY": 0.0230,
    "SAR": 0.2667,
    "AED": 0.2723,
    "QAR": 0.2747,
    "KWD": 3.27,
    "RON": 0.227,
    "HUF": 0.00289,
    "CZK": 0.0475,
    "ISK": 0.00813,
    "CLP": 0.00106,
    "COP": 0.000245,
    "ARS": 0.00082,
    "EGP": 0.0202,
    "VND": 0.0000383,
}


@dataclass(frozen=True)
class PriceValidation:
    """Validation result for one symbol's normalised daily frame."""

    ok: bool
    status: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    rows: int = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    years: Optional[float] = None


@dataclass(frozen=True)
class DownloadResult:
    """Persisted download outcome for one symbol."""

    symbol: str
    provider_symbol: str
    yfinance_symbol: str
    status: str
    rows: int = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    years: Optional[float] = None
    error: Optional[str] = None
    warnings: tuple[str, ...] = ()
    raw_path: Optional[str] = None
    normalized_path: Optional[str] = None


@dataclass(frozen=True)
class CompanyMetadataResult:
    """Current company metadata snapshot for one symbol."""

    symbol: str
    provider_symbol: str
    yfinance_symbol: str
    company_name: Optional[str] = None
    security_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    exchange: Optional[str] = None
    quote_type: Optional[str] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    country: Optional[str] = None
    website: Optional[str] = None
    status: str = "ok"
    source: str = SOURCE_YFINANCE_INFO
    retrieved_at: Optional[str] = None
    error: Optional[str] = None


def dataset_root(root: Optional[Path] = None) -> Path:
    """Return the dataset root under Aurora's runtime data directory."""

    base = Path(root) if root is not None else runtime_paths.base_data_dir()
    return base / "prices" / DATASET_NAME


def layout(root: Optional[Path] = None) -> dict[str, Path]:
    """Return all filesystem locations used by the free-US-daily lake."""

    base = dataset_root(root)
    return {
        "root": base,
        "universe_dir": base / "universe",
        "raw_dir": base / "raw" / SOURCE_YFINANCE,
        "normalized_dir": base / "normalized",
        "metadata_dir": base / "metadata",
        "reports_dir": base / "reports",
        "exports_dir": base / "exports",
        "benchmarks_dir": base / "benchmarks",
        "universe_path": base / "universe" / "us_stock_like_universe.parquet",
        "catalog_path": base / "catalog.sqlite",
        "coverage_report": base / "reports" / "coverage_report.json",
        "failures_csv": base / "reports" / "failures.csv",
        "quality_report": base / "reports" / "quality_report.csv",
        "company_metadata_path": base / "metadata" / "company_metadata.parquet",
        "metadata_coverage": base / "reports" / "metadata_coverage.json",
        "metadata_failures_csv": base / "reports" / "metadata_failures.csv",
        "market_cap_filter_report": base / "reports" / "market_cap_filter_report.json",
        "foreign_universe_report": base / "reports" / "foreign_universe_report.json",
        "duckdb_path": base / "exports" / "free_us_daily.duckdb",
        "all_prices_path": base / "exports" / "all_prices.parquet",
        "benchmark_manifest": base / "benchmarks" / "benchmark_manifest.json",
    }


def ensure_layout(root: Optional[Path] = None) -> dict[str, Path]:
    """Create dataset directories and return the resolved layout."""

    paths = layout(root)
    for key in (
        "universe_dir",
        "raw_dir",
        "normalized_dir",
        "metadata_dir",
        "reports_dir",
        "exports_dir",
        "benchmarks_dir",
    ):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def normalise_symbol_for_yfinance(symbol: str) -> str:
    """Normalise Nasdaq symbols to the form yfinance usually expects."""

    sym = str(symbol).strip().upper()
    return sym.replace(".", "-")


def is_adr_security_name(security_name: str) -> bool:
    """Return True for US-listed American Depositary Receipt/Shares names."""

    return bool(_ADR_SECURITY_RE.search(str(security_name or "")))


def infer_asset_type(security_name: str) -> str:
    """Classify stock-like rows without expanding into ETFs/funds/etc."""

    if is_adr_security_name(security_name):
        return ASSET_TYPE_ADR
    return ASSET_TYPE_COMMON_STOCK


def _is_stock_like(row: dict[str, Any]) -> bool:
    provider_symbol = str(
        row.get("Symbol")
        or row.get("ACT Symbol")
        or row.get("CQS Symbol")
        or ""
    ).strip()
    if "$" in provider_symbol:
        return False
    test_issue = str(row.get("Test Issue", "N")).strip().upper()
    if test_issue == "Y":
        return False
    etf = str(row.get("ETF", "N")).strip().upper()
    if etf == "Y":
        return False
    security_name = str(row.get("Security Name", ""))
    if is_adr_security_name(security_name):
        return True
    if _EXCLUDE_SECURITY_RE.search(security_name):
        return False
    return True


def build_us_stock_like_universe(
    *,
    client: Optional[Callable[[str], str]] = None,
    retrieved_at: Optional[str] = None,
) -> pd.DataFrame:
    """Download and filter the current active US stock-like universe."""

    loader = client or _nasdaq_default_client
    timestamp = retrieved_at or pd.Timestamp.utcnow().isoformat()
    rows: list[dict[str, Any]] = []
    for filename in (NASDAQ_LISTED_FILE, OTHER_LISTED_FILE):
        parsed = _parse_nasdaq_pipe_file(loader(filename))
        for raw in parsed:
            if not _is_stock_like(raw):
                continue
            provider_symbol = (
                raw.get("Symbol")
                or raw.get("ACT Symbol")
                or raw.get("CQS Symbol")
                or ""
            )
            provider_symbol = str(provider_symbol).strip().upper()
            if not provider_symbol:
                continue
            canonical_symbol = provider_symbol.replace(".", "-")
            security_name = str(raw.get("Security Name", "")).strip()
            rows.append(
                {
                    "provider_symbol": provider_symbol,
                    "canonical_symbol": canonical_symbol,
                    "yfinance_symbol": normalise_symbol_for_yfinance(
                        provider_symbol
                    ),
                    "security_name": security_name,
                    "asset_type": infer_asset_type(security_name),
                    "exchange": str(
                        raw.get("Exchange")
                        or raw.get("Listing Exchange")
                        or raw.get("Market Category")
                        or ""
                    ).strip(),
                    "source_file": filename,
                    "source": "nasdaq_trader",
                    "retrieved_at": timestamp,
                }
            )
    df = pd.DataFrame(rows)
    columns = [
        "provider_symbol",
        "canonical_symbol",
        "yfinance_symbol",
        "security_name",
        "asset_type",
        "exchange",
        "source_file",
        "source",
        "retrieved_at",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)
    df = df.drop_duplicates("canonical_symbol").sort_values(
        "canonical_symbol"
    )
    return df[columns].reset_index(drop=True)


def normalise_yahoo_symbol_for_canonical(symbol: str) -> str:
    """Return Aurora's filesystem-safe canonical form for Yahoo symbols."""

    return str(symbol).strip().upper().replace(".", "-")


def _market_suffix_by_region(
    *,
    priorities: Iterable[str],
) -> dict[str, dict[str, dict[str, str]]]:
    wanted_priorities = {str(p).strip().lower() for p in priorities}
    out: dict[str, dict[str, dict[str, str]]] = {}
    for market in FOREIGN_YAHOO_MARKETS:
        if str(market["priority"]).lower() not in wanted_priorities:
            continue
        out.setdefault(market["region"], {})[market["suffix"]] = market
    return out


def _symbol_market(
    symbol: str,
    markets_by_suffix: dict[str, dict[str, str]],
) -> Optional[dict[str, str]]:
    for suffix in sorted(markets_by_suffix, key=len, reverse=True):
        if str(symbol).upper().endswith(suffix):
            return markets_by_suffix[suffix]
    return None


def _usd_value(
    value: Any,
    currency: Any,
    rates: dict[str, float],
) -> Optional[float]:
    if value is None or currency is None:
        return None
    try:
        rate = rates[str(currency)]
        number = float(value)
    except (KeyError, TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number * rate


def _quote_timestamp(value: Any) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    try:
        return pd.Timestamp.fromtimestamp(float(value), tz="UTC").tz_convert(None)
    except (TypeError, ValueError, OSError):
        return None


def _default_yahoo_screen_client(
    region: str,
    *,
    size: int,
    offset: int,
) -> dict[str, Any]:
    try:
        import yfinance as yf
        from yfinance import EquityQuery
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "yfinance is required for Yahoo foreign universe screening"
        ) from exc
    query = EquityQuery("eq", ["region", region])
    return yf.screen(
        query,
        size=size,
        offset=offset,
        sortField="ticker",
        sortAsc=True,
    )


def build_yahoo_foreign_stock_universe(
    *,
    priorities: Iterable[str] = ("alta", "media", "baja"),
    min_market_cap_usd: float = 50_000_000,
    min_price_usd: float = 1.0,
    min_avg_dollar_volume_3m: float = 100_000,
    max_quote_age_days: int = 10,
    page_size: int = 250,
    retrieved_at: Optional[str] = None,
    reference_time: Optional[pd.Timestamp | str] = None,
    fx_rates: Optional[dict[str, float]] = None,
    screen_client: Optional[Callable[..., dict[str, Any]]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build a filtered Yahoo foreign stock universe and metadata snapshot.

    The screener provides average 3-month volume, not true 90-day median
    dollar volume. This function uses price * averageDailyVolume3Month as a
    fast liquidity proxy; exact median liquidity belongs in a historical pass.
    """

    timestamp = retrieved_at or pd.Timestamp.utcnow().isoformat()
    ref = (
        pd.Timestamp(reference_time)
        if reference_time is not None
        else pd.Timestamp.utcnow()
    )
    if getattr(ref, "tz", None) is not None:
        ref = ref.tz_convert(None)
    cutoff = ref - pd.Timedelta(days=int(max_quote_age_days))
    rates = dict(DEFAULT_USD_PER_UNIT)
    if fx_rates:
        rates.update({str(k): float(v) for k, v in fx_rates.items()})
    client = screen_client or _default_yahoo_screen_client
    markets = _market_suffix_by_region(priorities=priorities)
    universe_rows: dict[str, dict[str, Any]] = {}
    metadata_rows: dict[str, dict[str, Any]] = {}
    rejected: dict[str, int] = {
        "not_equity": 0,
        "suffix": 0,
        "market_cap": 0,
        "price": 0,
        "liquidity": 0,
        "stale": 0,
        "name": 0,
    }
    scanned = 0
    per_region: dict[str, int] = {}
    for region, suffix_map in markets.items():
        offset = 0
        seen_region: set[str] = set()
        while True:
            payload = client(region, size=int(page_size), offset=offset)
            total = int(payload.get("total") or 0)
            quotes = payload.get("quotes") or []
            if not quotes:
                break
            page_new = 0
            for quote in quotes:
                symbol = str(quote.get("symbol") or "").strip().upper()
                if not symbol or symbol in seen_region:
                    continue
                seen_region.add(symbol)
                page_new += 1
                scanned += 1
                if str(quote.get("quoteType") or "").upper() != "EQUITY":
                    rejected["not_equity"] += 1
                    continue
                market = _symbol_market(symbol, suffix_map)
                if market is None:
                    rejected["suffix"] += 1
                    continue
                market_cap = (
                    quote.get("marketCap")
                    or quote.get("intradayMarketCap")
                    or quote.get("intradaymarketcap")
                )
                market_cap_currency = (
                    quote.get("financialCurrency") or quote.get("currency")
                )
                market_cap_usd = _usd_value(market_cap, market_cap_currency, rates)
                if market_cap_usd is None or market_cap_usd < min_market_cap_usd:
                    rejected["market_cap"] += 1
                    continue
                price = (
                    quote.get("regularMarketPrice")
                    or quote.get("regularMarketPreviousClose")
                )
                quote_currency = quote.get("currency") or market_cap_currency
                price_usd = _usd_value(price, quote_currency, rates)
                if price_usd is None or price_usd < min_price_usd:
                    rejected["price"] += 1
                    continue
                try:
                    avg_volume = float(quote.get("averageDailyVolume3Month"))
                except (TypeError, ValueError):
                    avg_volume = 0.0
                dollar_volume = price_usd * avg_volume
                if dollar_volume < min_avg_dollar_volume_3m:
                    rejected["liquidity"] += 1
                    continue
                quote_time = _quote_timestamp(quote.get("regularMarketTime"))
                if quote_time is None or quote_time < cutoff:
                    rejected["stale"] += 1
                    continue
                security_name = (
                    _clean_optional_str(quote.get("longName"))
                    or _clean_optional_str(quote.get("shortName"))
                    or symbol
                )
                if _FOREIGN_EXCLUDE_SECURITY_RE.search(security_name):
                    rejected["name"] += 1
                    continue
                canonical = normalise_yahoo_symbol_for_canonical(symbol)
                universe_rows[canonical] = {
                    "provider_symbol": symbol,
                    "canonical_symbol": canonical,
                    "yfinance_symbol": symbol,
                    "security_name": security_name,
                    "asset_type": ASSET_TYPE_FOREIGN_COMMON_STOCK,
                    "exchange": _clean_optional_str(quote.get("exchange"))
                    or _clean_optional_str(quote.get("fullExchangeName"))
                    or market["suffix"],
                    "source_file": f"yahoo_region:{region}",
                    "source": SOURCE_YAHOO_SCREENER,
                    "retrieved_at": timestamp,
                }
                metadata_rows[canonical] = {
                    "symbol": canonical,
                    "provider_symbol": symbol,
                    "yfinance_symbol": symbol,
                    "company_name": security_name,
                    "security_name": security_name,
                    "sector": pd.NA,
                    "industry": pd.NA,
                    "exchange": universe_rows[canonical]["exchange"],
                    "quote_type": _clean_optional_str(quote.get("quoteType")),
                    "market_cap": market_cap_usd,
                    "shares_outstanding": _numeric_or_none(
                        quote.get("sharesOutstanding")
                    ),
                    "country": market["country"],
                    "website": pd.NA,
                    "status": "ok",
                    "source": SOURCE_YAHOO_SCREENER,
                    "retrieved_at": timestamp,
                    "error": None,
                }
                per_region[market["country"]] = per_region.get(market["country"], 0) + 1
            offset += len(quotes)
            if offset >= total or len(quotes) < page_size or page_new == 0:
                break
            time.sleep(0.05)
    universe_columns = [
        "provider_symbol",
        "canonical_symbol",
        "yfinance_symbol",
        "security_name",
        "asset_type",
        "exchange",
        "source_file",
        "source",
        "retrieved_at",
    ]
    universe = pd.DataFrame(universe_rows.values(), columns=universe_columns)
    metadata = pd.DataFrame(metadata_rows.values(), columns=METADATA_COLUMNS)
    if not universe.empty:
        universe = universe.sort_values("canonical_symbol").reset_index(drop=True)
    if not metadata.empty:
        metadata = metadata.sort_values("symbol").reset_index(drop=True)
    report = {
        "dataset": DATASET_NAME,
        "source": SOURCE_YAHOO_SCREENER,
        "created_at": timestamp,
        "filters": {
            "priorities": sorted({str(p) for p in priorities}),
            "min_market_cap_usd": float(min_market_cap_usd),
            "min_price_usd": float(min_price_usd),
            "min_avg_dollar_volume_3m": float(min_avg_dollar_volume_3m),
            "max_quote_age_days": int(max_quote_age_days),
        },
        "scanned_quotes": int(scanned),
        "foreign_symbols": int(len(universe)),
        "rejected": rejected,
        "by_country": dict(sorted(per_region.items())),
    }
    return universe, metadata, report


def persist_universe(df: pd.DataFrame, root: Optional[Path] = None) -> Path:
    """Persist the filtered universe parquet and update the catalog."""

    paths = ensure_layout(root)
    df.to_parquet(paths["universe_path"], index=False)
    _init_catalog(paths["catalog_path"])
    with sqlite3.connect(paths["catalog_path"]) as con:
        con.execute("DELETE FROM universe")
        rows = [
            (
                r.provider_symbol,
                r.canonical_symbol,
                r.yfinance_symbol,
                r.security_name,
                r.asset_type,
                r.exchange,
                r.source_file,
                r.source,
                r.retrieved_at,
            )
            for r in df.itertuples(index=False)
        ]
        con.executemany(
            """
            INSERT INTO universe (
                provider_symbol, canonical_symbol, yfinance_symbol,
                security_name, asset_type, exchange, source_file, source,
                retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.execute(
            "DELETE FROM downloads WHERE symbol NOT IN "
            "(SELECT canonical_symbol FROM universe)"
        )
    return paths["universe_path"]


def persist_foreign_universe_merge(
    foreign_universe: pd.DataFrame,
    foreign_metadata: pd.DataFrame,
    report: dict[str, Any],
    *,
    root: Optional[Path] = None,
    merge_existing: bool = True,
) -> Path:
    """Persist foreign symbols, optionally merging them into the existing lake."""

    paths = ensure_layout(root)
    if merge_existing and paths["universe_path"].exists():
        existing_universe = load_universe(root=root)
    else:
        existing_universe = pd.DataFrame(columns=foreign_universe.columns)
    combined_universe = pd.concat(
        [existing_universe, foreign_universe],
        ignore_index=True,
    )
    if not combined_universe.empty:
        combined_universe = (
            combined_universe.drop_duplicates("canonical_symbol", keep="last")
            .sort_values("canonical_symbol")
            .reset_index(drop=True)
        )
    path = persist_universe(combined_universe, root=root)
    existing_metadata = load_company_metadata(root=root) if merge_existing else pd.DataFrame(columns=METADATA_COLUMNS)
    combined_metadata = pd.concat(
        [existing_metadata, foreign_metadata],
        ignore_index=True,
    )
    persist_company_metadata_frame(combined_metadata, root=root)
    payload = dict(report)
    payload.update(
        {
            "merge_existing": bool(merge_existing),
            "universe_before": int(len(existing_universe)),
            "universe_after": int(len(combined_universe)),
        }
    )
    paths["foreign_universe_report"].write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_coverage_report(root=root)
    return path


def load_universe(root: Optional[Path] = None) -> pd.DataFrame:
    """Load the persisted stock-like universe."""

    path = layout(root)["universe_path"]
    if not path.exists():
        raise FileNotFoundError(
            f"free_us_daily universe not found: {path}. "
            "Run `forge data free-us-daily build-universe` first."
        )
    df = pd.read_parquet(path)
    if "asset_type" not in df.columns:
        df["asset_type"] = df["security_name"].map(infer_asset_type)
    return df


def fetch_yfinance_metadata(
    symbol: str,
    *,
    client: Optional[Callable[[str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Fetch current yfinance company metadata for one symbol."""

    if client is not None:
        return client(symbol)
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "yfinance is required for free-us-daily metadata enrichment"
        ) from exc
    ticker = yf.Ticker(symbol)
    if hasattr(ticker, "get_info"):
        info = ticker.get_info()
    else:  # pragma: no cover - compatibility with older yfinance
        info = ticker.info
    return info if isinstance(info, dict) else {}


def enrich_one_company_metadata(
    row: pd.Series | dict[str, Any],
    *,
    retries: int = 3,
    retry_wait_seconds: float = 1.0,
    client: Optional[Callable[[str], dict[str, Any]]] = None,
) -> CompanyMetadataResult:
    """Download and normalise current metadata for one universe symbol."""

    record = dict(row)
    symbol = str(record["canonical_symbol"])
    provider_symbol = str(record.get("provider_symbol") or symbol)
    yfinance_symbol = str(record.get("yfinance_symbol") or symbol)
    security_name = _clean_optional_str(record.get("security_name"))
    fallback_exchange = _clean_optional_str(record.get("exchange"))
    retrieved_at = pd.Timestamp.utcnow().isoformat()
    last_error: Optional[str] = None
    info: dict[str, Any] = {}
    for attempt in range(1, retries + 1):
        try:
            info = fetch_yfinance_metadata(yfinance_symbol, client=client)
            break
        except Exception as exc:  # pragma: no cover - network path
            last_error = str(exc)
            if attempt < retries:
                time.sleep(retry_wait_seconds * attempt)
    else:
        return CompanyMetadataResult(
            symbol=symbol,
            provider_symbol=provider_symbol,
            yfinance_symbol=yfinance_symbol,
            security_name=security_name,
            exchange=fallback_exchange,
            status="error",
            retrieved_at=retrieved_at,
            error=last_error or "metadata download failed",
        )
    return _metadata_result_from_info(
        symbol=symbol,
        provider_symbol=provider_symbol,
        yfinance_symbol=yfinance_symbol,
        security_name=security_name,
        fallback_exchange=fallback_exchange,
        info=info,
        retrieved_at=retrieved_at,
    )


def enrich_company_metadata(
    universe: pd.DataFrame,
    *,
    root: Optional[Path] = None,
    symbols: Optional[Iterable[str]] = None,
    workers: int = 2,
    batch_size: int = 25,
    retries: int = 3,
    retry_wait_seconds: float = 1.0,
    sleep_between_batches: float = 2.0,
    max_symbols: Optional[int] = None,
    offset: int = 0,
    skip_existing: bool = True,
    client: Optional[Callable[[str], dict[str, Any]]] = None,
) -> list[CompanyMetadataResult]:
    """Enrich the persisted universe with current company metadata."""

    df = universe.copy()
    if symbols:
        wanted = {s.strip().upper() for s in symbols if str(s).strip()}
        df = df[df["canonical_symbol"].isin(wanted)]
    if skip_existing:
        existing = load_company_metadata(root=root)
        if not existing.empty:
            done = set(
                existing.loc[
                    existing["status"].isin(("ok", "no_data")),
                    "symbol",
                ].astype(str)
            )
            df = df[~df["canonical_symbol"].astype(str).isin(done)]
    if offset:
        df = df.iloc[int(offset):]
    if max_symbols is not None:
        df = df.head(max_symbols)
    rows = [r._asdict() for r in df.itertuples(index=False)]
    results: list[CompanyMetadataResult] = []
    workers = max(1, int(workers))
    batch_size = max(1, int(batch_size))
    for batch_offset in range(0, len(rows), batch_size):
        batch = rows[batch_offset:batch_offset + batch_size]
        batch_results: list[CompanyMetadataResult] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    enrich_one_company_metadata,
                    row,
                    retries=retries,
                    retry_wait_seconds=retry_wait_seconds,
                    client=client,
                )
                for row in batch
            ]
            for fut in as_completed(futures):
                batch_results.append(fut.result())
        results.extend(batch_results)
        persist_company_metadata_results(batch_results, root=root)
        if (
            batch_offset + batch_size < len(rows)
            and sleep_between_batches > 0
        ):
            time.sleep(sleep_between_batches)
    write_metadata_coverage(root=root)
    write_metadata_failure_report(root=root)
    return results


def _metadata_result_from_info(
    *,
    symbol: str,
    provider_symbol: str,
    yfinance_symbol: str,
    security_name: Optional[str],
    fallback_exchange: Optional[str],
    info: dict[str, Any],
    retrieved_at: str,
) -> CompanyMetadataResult:
    if not info:
        return CompanyMetadataResult(
            symbol=symbol,
            provider_symbol=provider_symbol,
            yfinance_symbol=yfinance_symbol,
            security_name=security_name,
            exchange=fallback_exchange,
            status="no_data",
            retrieved_at=retrieved_at,
            error="empty metadata",
        )
    company_name = (
        _clean_optional_str(info.get("longName"))
        or _clean_optional_str(info.get("shortName"))
        or security_name
    )
    exchange = (
        _clean_optional_str(info.get("exchange"))
        or _clean_optional_str(info.get("fullExchangeName"))
        or fallback_exchange
    )
    return CompanyMetadataResult(
        symbol=symbol,
        provider_symbol=provider_symbol,
        yfinance_symbol=yfinance_symbol,
        company_name=company_name,
        security_name=security_name,
        sector=_clean_optional_str(info.get("sector")),
        industry=_clean_optional_str(info.get("industry")),
        exchange=exchange,
        quote_type=_clean_optional_str(info.get("quoteType")),
        market_cap=_numeric_or_none(info.get("marketCap")),
        shares_outstanding=_numeric_or_none(info.get("sharesOutstanding")),
        country=_clean_optional_str(info.get("country")),
        website=_clean_optional_str(info.get("website")),
        status="ok",
        retrieved_at=retrieved_at,
    )


def _clean_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _numeric_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def load_company_metadata(root: Optional[Path] = None) -> pd.DataFrame:
    """Load current company metadata snapshot if it exists."""

    path = layout(root)["company_metadata_path"]
    if not path.exists():
        return pd.DataFrame(columns=METADATA_COLUMNS)
    df = pd.read_parquet(path)
    for col in METADATA_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[METADATA_COLUMNS]


def persist_company_metadata_results(
    results: Iterable[CompanyMetadataResult],
    *,
    root: Optional[Path] = None,
) -> Path:
    """Append/update company metadata parquet from result objects."""

    paths = ensure_layout(root)
    rows = [asdict(r) for r in results]
    if not rows:
        if not paths["company_metadata_path"].exists():
            pd.DataFrame(columns=METADATA_COLUMNS).to_parquet(
                paths["company_metadata_path"],
                index=False,
            )
        return paths["company_metadata_path"]
    new_df = pd.DataFrame(rows)
    for col in METADATA_COLUMNS:
        if col not in new_df.columns:
            new_df[col] = pd.NA
    existing = load_company_metadata(root=root)
    combined = pd.concat([existing, new_df[METADATA_COLUMNS]], ignore_index=True)
    combined = combined.drop_duplicates("symbol", keep="last")
    combined = combined.sort_values("symbol").reset_index(drop=True)
    combined.to_parquet(paths["company_metadata_path"], index=False)
    return paths["company_metadata_path"]


def persist_company_metadata_frame(
    df: pd.DataFrame,
    *,
    root: Optional[Path] = None,
) -> Path:
    """Persist a full company metadata frame with the stable schema."""

    paths = ensure_layout(root)
    out = df.copy()
    for col in METADATA_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[METADATA_COLUMNS]
    out = out.drop_duplicates("symbol", keep="last")
    out = out.sort_values("symbol").reset_index(drop=True)
    out.to_parquet(paths["company_metadata_path"], index=False)
    write_metadata_coverage(root=root)
    write_metadata_failure_report(root=root)
    return paths["company_metadata_path"]


def filter_universe_by_market_cap(
    *,
    root: Optional[Path] = None,
    min_market_cap: float,
    drop_missing_market_cap: bool = False,
) -> dict[str, Any]:
    """Prune universe and metadata using current company market cap."""

    paths = ensure_layout(root)
    universe = load_universe(root=root)
    metadata = load_company_metadata(root=root)
    if metadata.empty:
        raise FileNotFoundError(
            "company metadata not found. Run "
            "`forge data free-us-daily enrich-metadata` first."
        )
    meta = metadata.copy()
    meta["market_cap_num"] = pd.to_numeric(meta["market_cap"], errors="coerce")
    market_cap_by_symbol = meta.set_index("symbol")["market_cap_num"]
    universe_caps = universe["canonical_symbol"].map(market_cap_by_symbol)
    below_min = universe_caps.notna() & (universe_caps < float(min_market_cap))
    missing = universe_caps.isna() | (universe_caps <= 0)
    remove_mask = below_min | (missing if drop_missing_market_cap else False)
    removed_symbols = set(universe.loc[remove_mask, "canonical_symbol"].astype(str))
    kept_universe = universe.loc[~remove_mask].copy().reset_index(drop=True)
    kept_metadata = metadata[
        metadata["symbol"].astype(str).isin(set(kept_universe["canonical_symbol"]))
    ].copy()
    persist_universe(kept_universe, root=root)
    persist_company_metadata_frame(kept_metadata, root=root)
    payload = {
        "dataset": DATASET_NAME,
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "min_market_cap": float(min_market_cap),
        "drop_missing_market_cap": bool(drop_missing_market_cap),
        "universe_before": int(len(universe)),
        "metadata_before": int(len(metadata)),
        "removed_total": int(len(removed_symbols)),
        "removed_below_min_market_cap": int(below_min.sum()),
        "removed_missing_market_cap": int((missing & remove_mask).sum()),
        "kept_missing_market_cap": int((missing & ~remove_mask).sum()),
        "universe_after": int(len(kept_universe)),
        "metadata_after": int(len(kept_metadata)),
        "removed_symbols": sorted(removed_symbols),
    }
    paths["market_cap_filter_report"].write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_coverage_report(root=root)
    return payload


def _init_catalog(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS universe (
                provider_symbol TEXT,
                canonical_symbol TEXT PRIMARY KEY,
                yfinance_symbol TEXT,
                security_name TEXT,
                asset_type TEXT,
                exchange TEXT,
                source_file TEXT,
                source TEXT,
                retrieved_at TEXT
            )
            """
        )
        _ensure_sqlite_column(con, "universe", "asset_type", "TEXT")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                symbol TEXT PRIMARY KEY,
                provider_symbol TEXT,
                yfinance_symbol TEXT,
                status TEXT,
                rows INTEGER,
                first_date TEXT,
                last_date TEXT,
                years REAL,
                error TEXT,
                warnings_json TEXT,
                raw_path TEXT,
                normalized_path TEXT,
                retrieved_at TEXT
            )
            """
        )


def _ensure_sqlite_column(
    con: sqlite3.Connection,
    table: str,
    column: str,
    column_type: str,
) -> None:
    cols = {
        str(row[1])
        for row in con.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def fetch_yfinance_raw(
    symbol: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    client: Optional[Callable[..., pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Fetch one symbol's full yfinance daily history."""

    if client is not None:
        return client(
            symbol,
            period="max" if start in (None, "max") else None,
            start=None if start in (None, "max") else start,
            end=end,
            interval="1d",
            auto_adjust=False,
            actions=True,
        )
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "yfinance is required for free-us-daily downloads"
        ) from exc
    kwargs: dict[str, Any] = {
        "interval": "1d",
        "auto_adjust": False,
        "actions": True,
        "progress": False,
        "threads": False,
    }
    if start in (None, "max"):
        kwargs["period"] = "max"
    else:
        kwargs["start"] = start
    if end:
        kwargs["end"] = end
    return yf.download(symbol, **kwargs)


def normalise_yfinance_history(
    raw: pd.DataFrame,
    *,
    symbol: str,
    retrieved_at: Optional[str] = None,
) -> pd.DataFrame:
    """Normalise yfinance output to the free-US-daily daily schema."""

    timestamp = retrieved_at or pd.Timestamp.utcnow().isoformat()
    if raw is None or len(raw) == 0:
        return _empty_price_frame()
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            str(c[0]).strip() if isinstance(c, tuple) else str(c).strip()
            for c in df.columns
        ]
    df = df.reset_index()
    rename = {
        "Date": "date",
        "Datetime": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
        "Dividends": "dividends",
        "Stock Splits": "stock_splits",
    }
    df = df.rename(columns=rename)
    if "date" not in df.columns:
        first = df.columns[0] if len(df.columns) else "index"
        df = df.rename(columns={first: "date"})
    for col in (
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "dividends",
        "stock_splits",
    ):
        if col not in df.columns:
            df[col] = 0.0 if col in ("dividends", "stock_splits") else pd.NA
    out = df[
        [
            "date",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
            "dividends",
            "stock_splits",
        ]
    ].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
    for col in ("open", "high", "low", "close", "adj_close", "dividends", "stock_splits"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0)
    out["source"] = SOURCE_YFINANCE
    out["retrieved_at"] = timestamp
    out["symbol"] = symbol
    return out.dropna(subset=["date"]).reset_index(drop=True)


def _empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
            "dividends",
            "stock_splits",
            "source",
            "retrieved_at",
            "symbol",
        ]
    )


def validate_price_frame(
    df: pd.DataFrame,
    *,
    min_rows: int = MIN_ROWS_DEFAULT,
) -> PriceValidation:
    """Validate one normalised daily price frame."""

    required = {
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "dividends",
        "stock_splits",
        "source",
        "retrieved_at",
        "symbol",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        return PriceValidation(False, "invalid", (f"missing columns: {missing}",))
    rows = len(df)
    if rows == 0:
        return PriceValidation(False, "no_data", rows=0)
    errors: list[str] = []
    warnings: list[str] = []
    dates = pd.to_datetime(df["date"], errors="coerce")
    if dates.isna().any():
        errors.append("invalid dates")
    if dates.duplicated().any():
        errors.append("duplicate dates")
    if not dates.is_monotonic_increasing:
        errors.append("dates not sorted")
    for col in ("open", "high", "low", "close", "adj_close"):
        vals = pd.to_numeric(df[col], errors="coerce")
        if vals.isna().any():
            errors.append(f"{col} contains null/non-numeric values")
        if (vals <= 0).any():
            errors.append(f"{col} contains non-positive values")
    volume = pd.to_numeric(df["volume"], errors="coerce")
    if volume.isna().any() or (volume < 0).any():
        errors.append("volume contains null or negative values")
    if (pd.to_numeric(df["high"], errors="coerce") < pd.to_numeric(df["low"], errors="coerce")).any():
        errors.append("high below low")
    if rows < min_rows:
        errors.append(f"row count below minimum {min_rows}")
    if len(dates.dropna()) >= 2:
        gaps = dates.sort_values().diff().dt.days.dropna()
        if len(gaps) and gaps.max() > 14:
            warnings.append(f"large calendar gap detected: {int(gaps.max())} days")
    close = pd.to_numeric(df["close"], errors="coerce")
    splits = pd.to_numeric(df["stock_splits"], errors="coerce").fillna(0)
    returns = close.pct_change().abs()
    suspicious = (returns > 0.80) & (splits == 0)
    if suspicious.fillna(False).any():
        warnings.append("large close jump without split event")
    first = dates.min().date().isoformat() if not dates.dropna().empty else None
    last = dates.max().date().isoformat() if not dates.dropna().empty else None
    years = None
    if first and last:
        years = round((dates.max() - dates.min()).days / 365.25, 2)
    ok = not errors
    return PriceValidation(
        ok=ok,
        status="ok" if ok else "invalid",
        errors=tuple(errors),
        warnings=tuple(warnings),
        rows=rows,
        first_date=first,
        last_date=last,
        years=years,
    )


def download_one_symbol(
    row: pd.Series | dict[str, Any],
    *,
    root: Optional[Path] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    retries: int = 3,
    retry_wait_seconds: float = 1.0,
    min_rows: int = MIN_ROWS_DEFAULT,
    client: Optional[Callable[..., pd.DataFrame]] = None,
) -> DownloadResult:
    """Download, validate, persist, and catalogue one symbol."""

    record = dict(row)
    symbol = str(record["canonical_symbol"])
    provider_symbol = str(record.get("provider_symbol") or symbol)
    yfinance_symbol = str(record.get("yfinance_symbol") or symbol)
    paths = ensure_layout(root)
    _init_catalog(paths["catalog_path"])
    last_error: Optional[str] = None
    raw = pd.DataFrame()
    for attempt in range(1, retries + 1):
        try:
            raw = fetch_yfinance_raw(
                yfinance_symbol,
                start=start,
                end=end,
                client=client,
            )
            break
        except Exception as exc:  # pragma: no cover - network path
            last_error = str(exc)
            if attempt < retries:
                time.sleep(retry_wait_seconds * attempt)
    else:
        result = DownloadResult(
            symbol=symbol,
            provider_symbol=provider_symbol,
            yfinance_symbol=yfinance_symbol,
            status="error",
            error=last_error or "download failed",
        )
        _record_download(paths["catalog_path"], result)
        return result

    retrieved_at = pd.Timestamp.utcnow().isoformat()
    normalised = normalise_yfinance_history(
        raw,
        symbol=symbol,
        retrieved_at=retrieved_at,
    )
    validation = validate_price_frame(normalised, min_rows=min_rows)
    if validation.status == "no_data":
        result = DownloadResult(
            symbol=symbol,
            provider_symbol=provider_symbol,
            yfinance_symbol=yfinance_symbol,
            status="no_data",
            rows=0,
        )
        _record_download(paths["catalog_path"], result)
        return result
    raw_path = paths["raw_dir"] / f"{symbol}.parquet"
    normalised_path = paths["normalized_dir"] / f"{symbol}.parquet"
    _raw_to_parquet(raw, raw_path)
    normalised.to_parquet(normalised_path, index=False)
    result = DownloadResult(
        symbol=symbol,
        provider_symbol=provider_symbol,
        yfinance_symbol=yfinance_symbol,
        status="ok" if validation.ok else "invalid",
        rows=validation.rows,
        first_date=validation.first_date,
        last_date=validation.last_date,
        years=validation.years,
        error="; ".join(validation.errors) if validation.errors else None,
        warnings=validation.warnings,
        raw_path=str(raw_path),
        normalized_path=str(normalised_path),
    )
    _record_download(paths["catalog_path"], result)
    return result


def _raw_to_parquet(raw: pd.DataFrame, path: Path) -> None:
    raw_out = raw.copy() if raw is not None else pd.DataFrame()
    if isinstance(raw_out.columns, pd.MultiIndex):
        raw_out.columns = ["|".join(map(str, c)).strip() for c in raw_out.columns]
    raw_out = raw_out.reset_index()
    raw_out.to_parquet(path, index=False)


def _record_download(path: Path, result: DownloadResult) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            """
            INSERT INTO downloads (
                symbol, provider_symbol, yfinance_symbol, status, rows,
                first_date, last_date, years, error, warnings_json,
                raw_path, normalized_path, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                provider_symbol=excluded.provider_symbol,
                yfinance_symbol=excluded.yfinance_symbol,
                status=excluded.status,
                rows=excluded.rows,
                first_date=excluded.first_date,
                last_date=excluded.last_date,
                years=excluded.years,
                error=excluded.error,
                warnings_json=excluded.warnings_json,
                raw_path=excluded.raw_path,
                normalized_path=excluded.normalized_path,
                retrieved_at=excluded.retrieved_at
            """,
            (
                result.symbol,
                result.provider_symbol,
                result.yfinance_symbol,
                result.status,
                result.rows,
                result.first_date,
                result.last_date,
                result.years,
                result.error,
                json.dumps(list(result.warnings)),
                result.raw_path,
                result.normalized_path,
                pd.Timestamp.utcnow().isoformat(),
            ),
        )


def download_prices(
    universe: pd.DataFrame,
    *,
    root: Optional[Path] = None,
    symbols: Optional[Iterable[str]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    workers: int = 4,
    batch_size: int = 75,
    retries: int = 3,
    retry_wait_seconds: float = 1.0,
    sleep_between_batches: float = 2.0,
    max_symbols: Optional[int] = None,
    offset: int = 0,
    shard_count: int = 1,
    shard_index: int = 0,
    skip_existing: bool = False,
    client: Optional[Callable[..., pd.DataFrame]] = None,
) -> list[DownloadResult]:
    """Download a universe in batches with bounded parallelism."""

    df = universe.copy()
    if symbols:
        wanted = {s.strip().upper() for s in symbols if str(s).strip()}
        df = df[df["canonical_symbol"].isin(wanted)]
    if skip_existing:
        existing = read_download_results(root)
        if not existing.empty:
            done = set(
                existing.loc[
                    existing["status"].isin(("ok", "invalid", "no_data")),
                    "symbol",
                ].astype(str)
            )
            df = df[~df["canonical_symbol"].astype(str).isin(done)]
    if offset:
        df = df.iloc[int(offset):]
    shard_count = max(1, int(shard_count))
    shard_index = int(shard_index)
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must satisfy 0 <= shard_index < shard_count")
    if shard_count > 1:
        positions = pd.Series(range(len(df)), index=df.index)
        df = df[positions.mod(shard_count) == shard_index]
    if max_symbols is not None:
        df = df.head(max_symbols)
    rows = [r._asdict() for r in df.itertuples(index=False)]
    results: list[DownloadResult] = []
    workers = max(1, int(workers))
    batch_size = max(1, int(batch_size))
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    download_one_symbol,
                    row,
                    root=root,
                    start=start,
                    end=end,
                    retries=retries,
                    retry_wait_seconds=retry_wait_seconds,
                    client=client,
                )
                for row in batch
            ]
            for fut in as_completed(futures):
                results.append(fut.result())
        if offset + batch_size < len(rows) and sleep_between_batches > 0:
            time.sleep(sleep_between_batches)
    write_failure_report(results, root=root)
    write_coverage_report(root=root)
    return results


def validate_persisted_prices(
    *,
    root: Optional[Path] = None,
    min_rows: int = MIN_ROWS_DEFAULT,
) -> list[DownloadResult]:
    """Validate all persisted normalised parquet files and update catalog."""

    paths = ensure_layout(root)
    _init_catalog(paths["catalog_path"])
    results: list[DownloadResult] = []
    for path in sorted(paths["normalized_dir"].glob("*.parquet")):
        symbol = path.stem
        df = pd.read_parquet(path)
        validation = validate_price_frame(df, min_rows=min_rows)
        provider_symbol = symbol
        yfinance_symbol = symbol
        if "symbol" in df.columns and len(df):
            provider_symbol = str(df["symbol"].iloc[0])
            yfinance_symbol = provider_symbol
        result = DownloadResult(
            symbol=symbol,
            provider_symbol=provider_symbol,
            yfinance_symbol=yfinance_symbol,
            status="ok" if validation.ok else validation.status,
            rows=validation.rows,
            first_date=validation.first_date,
            last_date=validation.last_date,
            years=validation.years,
            error="; ".join(validation.errors) if validation.errors else None,
            warnings=validation.warnings,
            normalized_path=str(path),
        )
        _record_download(paths["catalog_path"], result)
        results.append(result)
    write_failure_report(results, root=root)
    write_coverage_report(root=root)
    return results


def read_download_results(root: Optional[Path] = None) -> pd.DataFrame:
    """Read download catalog rows as a DataFrame."""

    paths = ensure_layout(root)
    _init_catalog(paths["catalog_path"])
    with sqlite3.connect(paths["catalog_path"]) as con:
        return pd.read_sql_query("SELECT * FROM downloads", con)


def ok_price_paths(root: Optional[Path] = None) -> list[Path]:
    """Return normalised parquet paths catalogued as valid."""

    paths = ensure_layout(root)
    downloads = read_download_results(root)
    if downloads.empty:
        return []
    ok = downloads[downloads["status"] == "ok"].copy()
    out: list[Path] = []
    for raw_path in ok["normalized_path"].dropna().astype(str):
        p = Path(raw_path)
        if p.exists():
            out.append(p)
    return sorted(out)


def export_duckdb(root: Optional[Path] = None) -> Path:
    """Create a DuckDB file with the valid daily price table."""

    paths = ensure_layout(root)
    price_paths = ok_price_paths(root)
    if not price_paths:
        raise FileNotFoundError("no valid normalised price parquet files found")
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for export-duckdb") from exc
    if paths["duckdb_path"].exists():
        paths["duckdb_path"].unlink()
    con = duckdb.connect(str(paths["duckdb_path"]))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS free_us_daily")
        con.execute(
            """
            CREATE TABLE prices_daily AS
            SELECT
                CAST(date AS DATE) AS date,
                CAST(symbol AS VARCHAR) AS symbol,
                CAST(open AS DOUBLE) AS open,
                CAST(high AS DOUBLE) AS high,
                CAST(low AS DOUBLE) AS low,
                CAST(close AS DOUBLE) AS close,
                CAST(adj_close AS DOUBLE) AS adj_close,
                CAST(volume AS DOUBLE) AS volume,
                CAST(dividends AS DOUBLE) AS dividends,
                CAST(stock_splits AS DOUBLE) AS stock_splits,
                CAST(source AS VARCHAR) AS source,
                CAST(retrieved_at AS VARCHAR) AS retrieved_at
            FROM read_parquet(?)
            """,
            [[str(p) for p in price_paths]],
        )
        con.execute(
            "CREATE INDEX idx_prices_daily_symbol_date "
            "ON prices_daily(symbol, date)"
        )
        universe = load_universe(root)
        con.register("universe_df", universe)
        con.execute("CREATE TABLE universe AS SELECT * FROM universe_df")
        downloads = read_download_results(root)
        con.register("downloads_df", downloads)
        con.execute("CREATE TABLE downloads AS SELECT * FROM downloads_df")
        company_metadata = load_company_metadata(root)
        con.register("company_metadata_df", company_metadata)
        con.execute(
            "CREATE TABLE company_metadata AS SELECT * FROM company_metadata_df"
        )
        con.execute(
            """
            CREATE TABLE metadata AS
            SELECT
                ? AS dataset,
                ? AS created_at,
                ? AS valid_symbols,
                (SELECT COUNT(*) FROM prices_daily) AS price_rows
            """,
            [
                DATASET_NAME,
                pd.Timestamp.utcnow().isoformat(),
                len(price_paths),
            ],
        )
    finally:
        con.close()
    return paths["duckdb_path"]


def export_all_prices_parquet(root: Optional[Path] = None) -> Path:
    """Create one combined parquet with all valid daily prices."""

    paths = ensure_layout(root)
    price_paths = ok_price_paths(root)
    if not price_paths:
        raise FileNotFoundError("no valid normalised price parquet files found")
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for export-all-parquet") from exc
    if paths["all_prices_path"].exists():
        paths["all_prices_path"].unlink()
    con = duckdb.connect()
    try:
        target = _duckdb_path_literal(paths["all_prices_path"])
        con.execute(
            f"""
            COPY (
                SELECT
                    CAST(date AS DATE) AS date,
                    CAST(symbol AS VARCHAR) AS symbol,
                    CAST(open AS DOUBLE) AS open,
                    CAST(high AS DOUBLE) AS high,
                    CAST(low AS DOUBLE) AS low,
                    CAST(close AS DOUBLE) AS close,
                    CAST(adj_close AS DOUBLE) AS adj_close,
                    CAST(volume AS DOUBLE) AS volume,
                    CAST(dividends AS DOUBLE) AS dividends,
                    CAST(stock_splits AS DOUBLE) AS stock_splits,
                    CAST(source AS VARCHAR) AS source,
                    CAST(retrieved_at AS VARCHAR) AS retrieved_at
                FROM read_parquet(?)
            )
            TO {target} (FORMAT PARQUET)
            """,
            [[str(p) for p in price_paths]],
        )
    finally:
        con.close()
    return paths["all_prices_path"]


def _duckdb_path_literal(path: Path) -> str:
    raw = str(path).replace("\\", "/").replace("'", "''")
    return f"'{raw}'"


def update_daily_prices(
    *,
    root: Optional[Path] = None,
    symbols: Optional[Iterable[str]] = None,
    workers: int = 2,
    batch_size: int = 20,
    retries: int = 3,
    retry_wait_seconds: float = 1.0,
    sleep_between_batches: float = 2.0,
    client: Optional[Callable[..., pd.DataFrame]] = None,
) -> list[DownloadResult]:
    """Refresh current universe symbols from their latest saved date."""

    universe = load_universe(root)
    downloads = read_download_results(root)
    start_by_symbol: dict[str, str] = {}
    if not downloads.empty:
        for row in downloads.itertuples(index=False):
            last = getattr(row, "last_date", None)
            status = getattr(row, "status", None)
            symbol = str(getattr(row, "symbol"))
            if status == "ok" and last:
                next_day = pd.Timestamp(last) + pd.Timedelta(days=1)
                start_by_symbol[symbol] = next_day.date().isoformat()
    if symbols:
        wanted = {s.strip().upper() for s in symbols if str(s).strip()}
        universe = universe[universe["canonical_symbol"].isin(wanted)]
    rows = [r._asdict() for r in universe.itertuples(index=False)]
    results: list[DownloadResult] = []
    for offset in range(0, len(rows), max(1, batch_size)):
        batch = rows[offset:offset + max(1, batch_size)]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [
                pool.submit(
                    update_one_symbol,
                    row,
                    root=root,
                    start=start_by_symbol.get(str(row["canonical_symbol"])),
                    retries=retries,
                    retry_wait_seconds=retry_wait_seconds,
                    client=client,
                )
                for row in batch
            ]
            for fut in as_completed(futures):
                results.append(fut.result())
        if offset + batch_size < len(rows) and sleep_between_batches > 0:
            time.sleep(sleep_between_batches)
    write_failure_report(results, root=root)
    write_coverage_report(root=root)
    return results


def update_one_symbol(
    row: pd.Series | dict[str, Any],
    *,
    root: Optional[Path] = None,
    start: Optional[str] = None,
    retries: int = 3,
    retry_wait_seconds: float = 1.0,
    min_rows: int = MIN_ROWS_DEFAULT,
    client: Optional[Callable[..., pd.DataFrame]] = None,
) -> DownloadResult:
    """Refresh one symbol without replacing a valid full history by a shard."""

    record = dict(row)
    symbol = str(record["canonical_symbol"])
    provider_symbol = str(record.get("provider_symbol") or symbol)
    yfinance_symbol = str(record.get("yfinance_symbol") or symbol)
    paths = ensure_layout(root)
    _init_catalog(paths["catalog_path"])
    existing_path = paths["normalized_dir"] / f"{symbol}.parquet"
    if start is None or not existing_path.exists():
        return download_one_symbol(
            row,
            root=root,
            start=None,
            retries=retries,
            retry_wait_seconds=retry_wait_seconds,
            min_rows=min_rows,
            client=client,
        )
    last_error: Optional[str] = None
    raw = pd.DataFrame()
    for attempt in range(1, retries + 1):
        try:
            raw = fetch_yfinance_raw(
                yfinance_symbol,
                start=start,
                client=client,
            )
            break
        except Exception as exc:  # pragma: no cover - network path
            last_error = str(exc)
            if attempt < retries:
                time.sleep(retry_wait_seconds * attempt)
    else:
        existing = pd.read_parquet(existing_path)
        validation = validate_price_frame(existing, min_rows=min_rows)
        result = DownloadResult(
            symbol=symbol,
            provider_symbol=provider_symbol,
            yfinance_symbol=yfinance_symbol,
            status="ok" if validation.ok else "invalid",
            rows=validation.rows,
            first_date=validation.first_date,
            last_date=validation.last_date,
            years=validation.years,
            error=last_error or "incremental update failed",
            warnings=validation.warnings,
            normalized_path=str(existing_path),
        )
        _record_download(paths["catalog_path"], result)
        return result
    incremental = normalise_yfinance_history(
        raw,
        symbol=symbol,
        retrieved_at=pd.Timestamp.utcnow().isoformat(),
    )
    existing = pd.read_parquet(existing_path)
    if incremental.empty:
        validation = validate_price_frame(existing, min_rows=min_rows)
        result = DownloadResult(
            symbol=symbol,
            provider_symbol=provider_symbol,
            yfinance_symbol=yfinance_symbol,
            status="ok" if validation.ok else "invalid",
            rows=validation.rows,
            first_date=validation.first_date,
            last_date=validation.last_date,
            years=validation.years,
            warnings=tuple(list(validation.warnings) + ["no_new_rows"]),
            normalized_path=str(existing_path),
        )
        _record_download(paths["catalog_path"], result)
        return result
    combined = pd.concat([existing, incremental], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.date
    combined = combined.dropna(subset=["date"])
    combined = combined.drop_duplicates("date", keep="last")
    combined = combined.sort_values("date").reset_index(drop=True)
    validation = validate_price_frame(combined, min_rows=min_rows)
    combined.to_parquet(existing_path, index=False)
    result = DownloadResult(
        symbol=symbol,
        provider_symbol=provider_symbol,
        yfinance_symbol=yfinance_symbol,
        status="ok" if validation.ok else "invalid",
        rows=validation.rows,
        first_date=validation.first_date,
        last_date=validation.last_date,
        years=validation.years,
        error="; ".join(validation.errors) if validation.errors else None,
        warnings=validation.warnings,
        normalized_path=str(existing_path),
    )
    _record_download(paths["catalog_path"], result)
    return result


def build_quality_report(root: Optional[Path] = None) -> pd.DataFrame:
    """Build one row per universe symbol with quality/download status."""

    universe = load_universe(root)
    downloads = read_download_results(root)
    if downloads.empty:
        merged = universe.copy()
        merged["status"] = "missing"
        merged["rows"] = 0
        merged["first_date"] = None
        merged["last_date"] = None
        merged["years"] = None
        merged["error"] = "not downloaded"
    else:
        merged = universe.merge(
            downloads,
            how="left",
            left_on="canonical_symbol",
            right_on="symbol",
            suffixes=("", "_download"),
        )
        merged["status"] = merged["status"].fillna("missing")
        merged["rows"] = merged["rows"].fillna(0).astype(int)
        merged["error"] = merged["error"].fillna("")
    merged["usable"] = merged["status"] == "ok"
    cols = [
        "canonical_symbol",
        "provider_symbol",
        "yfinance_symbol",
        "security_name",
        "asset_type",
        "exchange",
        "status",
        "usable",
        "rows",
        "first_date",
        "last_date",
        "years",
        "error",
    ]
    return merged[cols].sort_values(["status", "canonical_symbol"])


def write_quality_report(root: Optional[Path] = None) -> Path:
    """Persist the per-symbol quality report CSV."""

    paths = ensure_layout(root)
    report = build_quality_report(root)
    report.to_csv(paths["quality_report"], index=False)
    return paths["quality_report"]


def build_benchmarks(
    *,
    root: Optional[Path] = None,
    symbols: Iterable[str] = ("SPY", "^GSPC"),
) -> dict[str, Any]:
    """Download benchmark/index histories into a separate benchmark area."""

    paths = ensure_layout(root)
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        sym = str(symbol).strip().upper()
        if not sym:
            continue
        raw = fetch_yfinance_raw(sym, start=None)
        normalised = normalise_yfinance_history(raw, symbol=sym)
        validation = validate_price_frame(normalised, min_rows=MIN_ROWS_DEFAULT)
        out_path = paths["benchmarks_dir"] / f"{sym.replace('^', '')}.parquet"
        if len(normalised):
            normalised.to_parquet(out_path, index=False)
        rows.append(
            {
                "symbol": sym,
                "status": "ok" if validation.ok else validation.status,
                "rows": validation.rows,
                "first_date": validation.first_date,
                "last_date": validation.last_date,
                "years": validation.years,
                "errors": list(validation.errors),
                "warnings": list(validation.warnings),
                "path": str(out_path) if len(normalised) else None,
            }
        )
    payload = {
        "dataset": DATASET_NAME,
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "benchmarks": rows,
    }
    paths["benchmark_manifest"].write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def build_coverage_report(root: Optional[Path] = None) -> dict[str, Any]:
    """Build a compact coverage report from universe + download catalog."""

    paths = ensure_layout(root)
    universe_count = 0
    if paths["universe_path"].exists():
        universe_count = len(pd.read_parquet(paths["universe_path"]))
    downloads = read_download_results(root)
    if downloads.empty:
        payload: dict[str, Any] = {
            "dataset": DATASET_NAME,
            "universe_symbols": universe_count,
            "downloaded_ok": 0,
            "no_data": 0,
            "invalid": 0,
            "errors": 0,
            "coverage_mean_years": None,
            "top_20_most_history": [],
            "top_20_least_history": [],
        }
        return payload
    ok = downloads[downloads["status"] == "ok"].copy()
    top_most = ok.sort_values("years", ascending=False).head(20)
    top_least = ok.sort_values("years", ascending=True).head(20)
    return {
        "dataset": DATASET_NAME,
        "universe_symbols": universe_count,
        "downloaded_ok": int((downloads["status"] == "ok").sum()),
        "no_data": int((downloads["status"] == "no_data").sum()),
        "invalid": int((downloads["status"] == "invalid").sum()),
        "errors": int((downloads["status"] == "error").sum()),
        "coverage_mean_years": (
            round(float(ok["years"].dropna().mean()), 2)
            if len(ok) and ok["years"].notna().any()
            else None
        ),
        "top_20_most_history": _history_rows(top_most),
        "top_20_least_history": _history_rows(top_least),
    }


def build_metadata_coverage(root: Optional[Path] = None) -> dict[str, Any]:
    """Build coverage report for current company metadata snapshot."""

    paths = ensure_layout(root)
    universe_count = 0
    if paths["universe_path"].exists():
        universe_count = len(pd.read_parquet(paths["universe_path"]))
    metadata = load_company_metadata(root=root)
    if metadata.empty:
        return {
            "dataset": DATASET_NAME,
            "universe_symbols": universe_count,
            "metadata_rows": 0,
            "ok": 0,
            "no_data": 0,
            "errors": 0,
            "sector_populated": 0,
            "industry_populated": 0,
            "market_cap_populated": 0,
            "shares_outstanding_populated": 0,
            "country_populated": 0,
            "website_populated": 0,
            "top_20_sectors": [],
            "top_20_industries": [],
        }
    ok = metadata[metadata["status"] == "ok"].copy()
    return {
        "dataset": DATASET_NAME,
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "universe_symbols": universe_count,
        "metadata_rows": int(len(metadata)),
        "ok": int((metadata["status"] == "ok").sum()),
        "no_data": int((metadata["status"] == "no_data").sum()),
        "errors": int((metadata["status"] == "error").sum()),
        "sector_populated": _populated_count(ok, "sector"),
        "industry_populated": _populated_count(ok, "industry"),
        "market_cap_populated": int(ok["market_cap"].notna().sum()),
        "shares_outstanding_populated": int(ok["shares_outstanding"].notna().sum()),
        "country_populated": _populated_count(ok, "country"),
        "website_populated": _populated_count(ok, "website"),
        "top_20_sectors": _value_count_rows(ok, "sector", 20),
        "top_20_industries": _value_count_rows(ok, "industry", 20),
    }


def _populated_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns or df.empty:
        return 0
    vals = df[column].dropna().astype(str).str.strip()
    return int((vals != "").sum())


def _value_count_rows(
    df: pd.DataFrame,
    column: str,
    limit: int,
) -> list[dict[str, Any]]:
    if column not in df.columns or df.empty:
        return []
    counts = df[column].dropna().astype(str).str.strip()
    counts = counts[counts != ""].value_counts().head(limit)
    return [
        {column: str(name), "count": int(count)}
        for name, count in counts.items()
    ]


def _history_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols = ["symbol", "rows", "first_date", "last_date", "years"]
    return df[cols].to_dict("records") if len(df) else []


def write_coverage_report(root: Optional[Path] = None) -> Path:
    """Write the JSON coverage report and return its path."""

    paths = ensure_layout(root)
    payload = build_coverage_report(root)
    paths["coverage_report"].write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return paths["coverage_report"]


def write_metadata_coverage(root: Optional[Path] = None) -> Path:
    """Write metadata coverage JSON and return its path."""

    paths = ensure_layout(root)
    payload = build_metadata_coverage(root=root)
    paths["metadata_coverage"].write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return paths["metadata_coverage"]


def write_metadata_failure_report(root: Optional[Path] = None) -> Path:
    """Write metadata_failures.csv from the current metadata snapshot."""

    paths = ensure_layout(root)
    metadata = load_company_metadata(root=root)
    if metadata.empty:
        failed = pd.DataFrame(columns=METADATA_COLUMNS)
    else:
        failed = metadata[metadata["status"] != "ok"].copy()
    failed.to_csv(paths["metadata_failures_csv"], index=False)
    return paths["metadata_failures_csv"]


def write_failure_report(
    results: Iterable[DownloadResult],
    *,
    root: Optional[Path] = None,
) -> Path:
    """Write failures.csv from the supplied result iterable."""

    paths = ensure_layout(root)
    failed = [asdict(r) for r in results if r.status != "ok"]
    df = pd.DataFrame(failed)
    df.to_csv(paths["failures_csv"], index=False)
    return paths["failures_csv"]
