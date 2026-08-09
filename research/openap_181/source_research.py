"""Evidence-backed source research outputs for the 181 unfinished signals.

The classifications in this module describe source feasibility, not signal
readiness.  Every signal remains fail-closed until coverage, point-in-time
handling and independent stock-level fidelity are measured in GitHub Actions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
import json

import pandas as pd

from aurora.research.openap_181.completion import SOURCE_CATALOG


RESEARCH_CHECKED_DATE = "2026-08-09"
SIGNALDOC_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/SignalDoc.csv"
)

ALLOWED_CLASSIFICATIONS = frozenset(
    {
        "exact_free_source_candidate",
        "multiple_sources_required",
        "proxy_only",
        "formula_ambiguous",
        "identifier_bridge_missing",
        "historical_point_in_time_missing",
        "no_free_authorized_source",
        "source_access_unverified",
    }
)


@dataclass(frozen=True)
class SourceResearchMetadata:
    source_id: str
    source_owner: str
    documentation_url: str
    terms_or_license_url: str
    account_required: bool
    payment_card_required: bool
    authentication_method: str
    rate_limit: str
    historical_start: str
    historical_end: str
    update_frequency: str
    publication_lag: str
    identifier_types: str
    available_at_supported: str
    point_in_time_quality: str
    redistribution: str


def _meta(
    source_id: str,
    owner: str,
    documentation_url: str,
    terms_url: str,
    *,
    account: bool = False,
    card: bool = False,
    auth: str = "none",
    rate: str = "not_verified",
    start: str = "not_verified",
    end: str = "current_or_not_verified",
    frequency: str = "not_verified",
    lag: str = "not_verified",
    identifiers: str = "not_verified",
    available_at: str = "not_verified",
    pit: str = "not_verified",
    redistribution: str = "not_verified",
) -> SourceResearchMetadata:
    return SourceResearchMetadata(
        source_id=source_id,
        source_owner=owner,
        documentation_url=documentation_url,
        terms_or_license_url=terms_url,
        account_required=account,
        payment_card_required=card,
        authentication_method=auth,
        rate_limit=rate,
        historical_start=start,
        historical_end=end,
        update_frequency=frequency,
        publication_lag=lag,
        identifier_types=identifiers,
        available_at_supported=available_at,
        point_in_time_quality=pit,
        redistribution=redistribution,
    )


SOURCE_METADATA = {
    item.source_id: item
    for item in (
        _meta(
            "openap_official",
            "OpenSourceAP",
            "https://github.com/OpenSourceAP/CrossSection",
            "https://github.com/OpenSourceAP/CrossSection/blob/master/LICENSE",
            start="published_sample_specific",
            frequency="repository_release",
            identifiers="PERMNO in published stock-level files",
            available_at="formula documents lags; values require separate audit",
            pit="historical_reference_not_current_feed",
            redistribution="GPL-2.0 code; data terms require source-page review",
        ),
        _meta(
            "sec_edgar",
            "US Securities and Exchange Commission",
            "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
            "https://www.sec.gov/about/webmaster-frequently-asked-questions",
            rate="maximum 10 requests per second",
            start="filing and taxonomy dependent",
            frequency="real time plus nightly bulk archives",
            lag="generally under one minute for API; filing availability may take 1-3 minutes",
            identifiers="CIK,ticker,exchange,accession number",
            available_at="filing acceptance timestamp",
            pit="strong when original filing accession and acceptance time are retained",
            redistribution="public filing content free to access and reuse",
        ),
        _meta(
            "sec_financial_statement_datasets",
            "US Securities and Exchange Commission",
            "https://www.sec.gov/files/fsds.pdf",
            "https://www.sec.gov/about/webmaster-frequently-asked-questions",
            rate="bulk quarterly ZIP downloads under SEC fair-access policy",
            start="April 2009; 2009 Q1 is headers only",
            frequency="quarterly",
            lag="submissions after quarter cutoff appear in the next quarterly file",
            identifiers="CIK,accession number,SIC,XBRL tag,taxonomy version",
            available_at="acceptance datetime in SUB plus accession-level amendment history",
            pit="as-filed numeric face statements; retain original and amended submissions",
            redistribution="public filing content free to access and reuse",
        ),
        _meta(
            "yahoo_public",
            "Yahoo",
            "https://query1.finance.yahoo.com/",
            "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
            rate="not documented as a stable public research API",
            start="symbol dependent",
            identifiers="ticker",
            available_at="not_verified",
            pit="snapshot and schema stability unverified",
            redistribution="not_verified",
        ),
        _meta(
            "cboe_delayed_options",
            "Cboe Global Markets",
            "https://www.cboe.com/delayed_quotes/API/quote_table/",
            "https://www.cboe.com/delayed_quotes/API/quote_table/",
            start="current delayed snapshot",
            frequency="intraday delayed",
            lag="at least 15 minutes",
            identifiers="ticker,OCC option symbol",
            available_at="quote timestamp",
            pit="no authorized archive through this page",
            redistribution="automated extraction expressly prohibited",
        ),
        _meta(
            "cboe_public_aggregate",
            "Cboe Global Markets",
            "https://www.cboe.com/us/options/market_statistics/historical_data/",
            "https://www.cboe.com/terms/",
            start="dataset dependent",
            frequency="daily or monthly depending on file",
            identifiers="aggregate market or published symbol fields",
            available_at="publication date",
            pit="aggregate history only",
            redistribution="subject to Cboe terms",
        ),
        _meta(
            "occ_option_volume",
            "The Options Clearing Corporation",
            "https://www.theocc.com/market-data/market-data-reports/other-market-data-info/batch-processing/volume-query-batch-processing",
            "https://www.theocc.com/specialpages/legal/terms-and-conditions",
            start="past 24 months on the interactive query; older batch availability not verified",
            frequency="daily,weekly,monthly",
            lag="report publication date",
            identifiers="underlying symbol,OCC option product type,call/put,account type",
            available_at="report date",
            pit="recent volume reports only; no IV surface or permanent identity",
            redistribution="website data may not be copied or commercially exploited; automation prohibited",
        ),
        _meta(
            "marketdata_options_free",
            "Market Data",
            "https://www.marketdata.app/docs/api/options/chain/",
            "https://www.marketdata.app/terms/",
            account=True,
            auth="bearer token delivered by email",
            rate="100 daily API credits; one IP at a time",
            start="one rolling year",
            frequency="daily historical snapshots; current data delayed 24 hours",
            lag="24 hours on Free Forever",
            identifiers="ticker,OCC option symbol",
            available_at="updated timestamp",
            pit="one year of end-of-day option chains",
            redistribution="no raw redistribution; personal/non-professional license",
        ),
        _meta(
            "tradier_personal_api",
            "Tradier Brokerage",
            "https://docs.tradier.com/docs/historical-data",
            "https://docs.tradier.com/docs/faq",
            account=True,
            auth="personal brokerage bearer token",
            rate="120 requests/minute production; 60 requests/minute sandbox",
            start="equities usually company lifetime; options only while contract remains unexpired",
            frequency="daily historical plus live or 15-minute-delayed current data",
            lag="sandbox market data delayed 15 minutes",
            identifiers="ticker,OCC option symbol",
            available_at="quote or candle timestamp; revision vintage not exposed",
            pit="no expired-option history; no sandbox Greeks; personal-use entitlement only",
            redistribution="personal use only unless approved as a Tradier Partner",
        ),
        _meta(
            "optionmetrics_ivydb_us",
            "OptionMetrics LLC",
            "https://optionmetrics.com/data-products/",
            "https://optionmetrics.com/contact-us/",
            account=True,
            card=True,
            auth="commercial customer delivery",
            rate="contract dependent",
            start="January 1996",
            frequency="daily end-of-day with correction patches",
            lag="daily vendor delivery",
            identifiers="permanent security ID,ticker,option contract,underlying security",
            available_at="daily observation and vendor correction files",
            pit="complete commercial EOD option panel with corporate-action continuity",
            redistribution="commercial license required",
        ),
        _meta(
            "finra_short_sale_volume",
            "FINRA",
            "https://www.finra.org/finra-data/browse-catalog/short-sale-volume",
            "https://developer.finra.org/specific-terms-equity-data",
            account=True,
            auth="free FINRA API credentials for Query API",
            start="dataset dependent",
            frequency="daily",
            identifiers="trade-reporting symbol",
            available_at="publication date",
            pit="historical transaction-volume files",
            redistribution="subject to FINRA Equity Data specific terms",
        ),
        _meta(
            "finra_equity_short_interest",
            "FINRA",
            "https://www.finra.org/finra-data/browse-catalog/equity-short-interest",
            "https://developer.finra.org/specific-terms-equity-data",
            account=True,
            auth="public files or free FINRA API credentials",
            rate="Query API limit documented in developer account",
            start="2014 archive; exchange-listed coverage begins June 2021",
            frequency="twice monthly",
            lag="seventh business day after settlement date",
            identifiers="symbol,issue name,market classification",
            available_at="FINRA dissemination date",
            pit="as-published observation; only latest revision retained",
            redistribution="subject to FINRA Equity Data specific terms",
        ),
        _meta(
            "exchange_short_interest",
            "NYSE and Nasdaq",
            "https://www.nyse.com/data-products/catalog/nyse-group-short-interest",
            "https://www.nyse.com/market-data/pricing-policies-contracts-guidelines",
            account=True,
            card=True,
            auth="commercial order",
            start="NYSE product January 1988",
            frequency="twice monthly",
            identifiers="exchange symbol and product fields",
            available_at="product dissemination date",
            pit="commercial historical product",
            redistribution="commercial license required",
        ),
        _meta(
            "twelve_data_basic",
            "Twelve Data",
            "https://twelvedata.com/docs/introduction/overview",
            "https://twelvedata.com/terms",
            account=True,
            auth="free API key",
            rate="8 credits per minute and 800 per day",
            start="most symbols from first trading date",
            frequency="daily after midnight US Eastern on Basic",
            lag="end-of-day",
            identifiers="ticker,exchange,MIC",
            available_at="provider response timestamp; corporate-action vintage not verified",
            pit="price history; permanent identity and delisting history unverified",
            redistribution="internal non-display use; no raw redistribution",
        ),
        _meta(
            "tiingo_starter",
            "Tiingo",
            "https://www.tiingo.com/documentation/end-of-day",
            "https://api.tiingo.com/tos/",
            account=True,
            auth="free API token",
            rate="500 unique symbols/month; 50 requests/hour; 1000/day; 1 GB/month",
            start="30+ years advertised; symbol-specific verification required",
            frequency="end-of-day",
            lag="end-of-day corrections possible",
            identifiers="ticker,exchange",
            available_at="priceDate and provider update; revision vintage not exposed",
            pit="raw and adjusted prices plus dividend and split fields",
            redistribution=(
                "internal use only; written approval required to create or retain "
                "derived data under terms updated 2026-07-18"
            ),
        ),
        _meta(
            "fmp_basic",
            "Financial Modeling Prep",
            "https://site.financialmodelingprep.com/developer/docs/stable",
            "https://site.financialmodelingprep.com/terms-of-service",
            account=True,
            auth="free API key",
            rate="250 calls/day and 500 MB per trailing 30 days",
            start="five rolling years on Basic",
            frequency="end-of-day",
            lag="endpoint dependent",
            identifiers="ticker and provider reference fields",
            available_at="not_verified per endpoint",
            pit="five-year recent window; analyst endpoint entitlement unverified",
            redistribution=(
                "individual use; derivative works, display and redistribution require "
                "prior written approval"
            ),
        ),
        _meta(
            "openfigi",
            "Bloomberg OpenFIGI",
            "https://www.openfigi.com/api/documentation",
            "https://www.openfigi.com/docs/terms-of-service",
            account=False,
            auth="none or optional free API key",
            rate="25/min and 10 jobs/request without key; 25/6 sec and 100 jobs with key",
            start="current mapping service",
            frequency="continuous service",
            identifiers="FIGI,CUSIP,ISIN,ticker,exchange",
            available_at="mapping response time; historical validity not guaranteed",
            pit="not a historical point-in-time identity master",
            redistribution="FIGI identifiers are public-domain; API terms apply",
        ),
        _meta(
            "kenneth_french_factors",
            "Kenneth R. French",
            "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
            "not_verified",
            start="July 1926",
            frequency="daily and monthly files",
            lag="release schedule not explicitly documented",
            identifiers="factor name and date",
            available_at="dated release archives available from 2005",
            pit="current files plus selected release archives",
            redistribution="not_verified",
        ),
        _meta(
            "fred_vxo_vix",
            "Federal Reserve Bank of St. Louis / Cboe",
            "https://fred.stlouisfed.org/docs/api/fred/",
            "https://fred.stlouisfed.org/docs/api/terms_of_use.html",
            account=True,
            auth="free FRED API key",
            rate="subject to FRED bandwidth limits",
            start="VXO 1986; VIX 1990",
            end="VXO September 2021; VIX current",
            frequency="daily",
            lag="source-series update schedule",
            identifiers="FRED series ID,date",
            available_at="FRED observation and realtime/vintage fields",
            pit="VXO exact history ends in 2021; VIX is not an exact replacement",
            redistribution="attribution and third-party Cboe rights apply",
        ),
        _meta(
            "uspto_patentsview_bulk",
            "United States Patent and Trademark Office",
            "https://www.uspto.gov/ip-policy/economic-research/patentsview",
            "https://zenodo.org/records/15058362",
            start="patent-history dependent",
            end="final static metadata through 2024",
            frequency="static official release",
            identifiers="patent,assignee,inventor,location",
            available_at="grant/publication date",
            pit="historical records with entity-resolution revisions",
            redistribution="CC BY 4.0 on official Zenodo release",
        ),
        _meta(
            "google_patents_bigquery",
            "Google Cloud Public Datasets",
            "https://console.cloud.google.com/marketplace/product/google_patents_public_datasets/google-patents-public-data",
            "https://cloud.google.com/terms",
            account=True,
            auth="Google Cloud project credentials",
            rate="first 1 TB queried per month free under BigQuery free tier",
            start="patent-history dependent",
            frequency="provider maintained",
            identifiers="patent,publication,assignee,citation",
            available_at="publication/grant fields; ingestion vintage needs audit",
            pit="historical patent records; issuer bridge absent",
            redistribution="Google Cloud and underlying-data terms apply",
        ),
        _meta(
            "uspto_odp_patentsview",
            "United States Patent and Trademark Office",
            "https://data.uspto.gov/apis/bulk-data/search",
            "https://www.uspto.gov/terms-use-uspto-websites",
            account=True,
            auth="free USPTO.gov account and API key",
            rate="documented in ODP API account",
            start="dataset dependent",
            frequency="quarterly/annual PatentsView releases",
            identifiers="patent,assignee,inventor,location",
            available_at="publication/grant date and release date",
            pit="current official release; entity resolution may revise",
            redistribution="USPTO data policy applies",
        ),
        _meta(
            "sec_13f",
            "US Securities and Exchange Commission",
            "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets",
            "https://www.sec.gov/about/webmaster-frequently-asked-questions",
            start="May 2013 for flattened structured datasets",
            frequency="quarterly",
            lag="up to 45 days after quarter-end",
            identifiers="filer CIK,CUSIP,accession number",
            available_at="filing acceptance timestamp",
            pit="as-filed quarterly holdings; amendments must be preserved",
            redistribution="public filing content free to access and reuse",
        ),
        _meta(
            "alpha_vantage_free",
            "Alpha Vantage",
            "https://www.alphavantage.co/documentation/",
            "https://www.alphavantage.co/terms_of_service/",
            account=True,
            auth="free API key",
            rate="25 requests/day",
            start="20+ years for selected price endpoints; estimate history not stated",
            frequency="daily or report-driven",
            lag="endpoint dependent",
            identifiers="ticker",
            available_at="not_verified for estimate revisions",
            pit="aggregate revision fields do not establish an IBES-equivalent vintage panel",
            redistribution="personal non-commercial license; broader research requires permission",
        ),
        _meta(
            "field_ritter_ipo",
            "Jay R. Ritter / University of Florida",
            "https://site.warrington.ufl.edu/ritter/files/founding-dates.pdf",
            "not_verified",
            start="1975",
            end="2025",
            frequency="author updates",
            lag="research release; not a live feed",
            identifiers="PERMNO,CUSIP,ticker,company name,offer date",
            available_at="dataset publication vintage; historical revisions occur",
            pit="author-maintained research dataset",
            redistribution="citation requested; automated-download permission not explicit",
        ),
        _meta(
            "yale_governance",
            "Andrew Metrick / Yale School of Management",
            "https://faculty.som.yale.edu/andrewmetrick/data/",
            "not_verified",
            start="1990",
            end="2006",
            frequency="static",
            identifiers="firm fields in Governance.xlsx",
            available_at="survey-year observations every 2-3 years",
            pit="historical source dataset only",
            redistribution="license and automated-download permission not explicit",
        ),
        _meta(
            "edwin_hu_pin",
            "Jefferson Duarte, Edwin Hu and Lance Young",
            "https://edwinhu.github.io/pin/",
            "https://github.com/edwinhu/pin-code/blob/master/LICENSE",
            start="1993 for published PIN parameters; Hvidkjaer covers 1983-2001",
            end="2012 for exact published PIN parameters",
            frequency="annual stock-year estimates",
            lag="year t parameters forecast year t+1 in OpenAP",
            identifiers="PERMNO,year",
            available_at="author dataset publication; use one-year lag",
            pit="exact historical parameter panel, no exact PIN continuation after 2012",
            redistribution="MIT repository terms",
        ),
        _meta(
            "bea_input_output",
            "US Bureau of Economic Analysis",
            "https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf",
            "https://www.commerce.gov/page/application-programming-interface-api-terms-service",
            account=True,
            auth="free 36-character BEA API key or static files",
            rate="reasonable-use API limits",
            start="historical benchmarks from 1947; exact table/vintage varies",
            frequency="annual, with detailed benchmark tables about every five years",
            lag="annual release each September",
            identifiers="BEA industry/commodity codes,NAICS/SIC concordance",
            available_at="release and archive vintage",
            pit="previously published estimates are archived; revisions must be frozen",
            redistribution="BEA information public-domain unless stated otherwise",
        ),
        _meta(
            "census_naics_concordance",
            "US Census Bureau",
            "https://www.census.gov/naics/concordances/concordances.html",
            "https://www.census.gov/about/policies/copyright.html",
            start="1987 SIC to 1997/2002 NAICS concordances",
            frequency="classification revision",
            identifiers="SIC,NAICS",
            available_at="published classification vintage",
            pit="vintage-specific but often many-to-many",
            redistribution="US government public information",
        ),
        _meta(
            "crsp_stock_commercial",
            "Center for Research in Security Prices / Morningstar",
            "https://wrds-www.wharton.upenn.edu/pages/grid-items/crsp-basics/",
            "https://wrds-www.wharton.upenn.edu/pages/about/what-wrds/",
            account=True,
            card=True,
            auth="institutional WRDS subscription plus CRSP vendor license",
            rate="contract dependent",
            start="exchange and product dependent; long US history",
            frequency="daily and monthly products",
            lag="vendor release schedule",
            identifiers="PERMNO,PERMCO,CUSIP,ticker,exchange code",
            available_at="vendor dates and event records",
            pit="commercial security master with delistings and corporate actions",
            redistribution="separate CRSP license required",
        ),
        _meta(
            "compustat_commercial",
            "S&P Global Market Intelligence",
            "https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/sp-global-market-intelligence/",
            "https://wrds-www.wharton.upenn.edu/pages/about/what-wrds/",
            account=True,
            card=True,
            auth="institutional WRDS subscription plus S&P vendor license",
            rate="contract dependent",
            start="product dependent; North America and PIT products include long histories",
            frequency="daily,monthly or quarterly by product",
            lag="vendor release schedule",
            identifiers="GVKEY,CIK,CUSIP,ticker,SIC",
            available_at="PIT,preliminary and unrestated products are separately licensed",
            pit="commercial current, historical, PIT and segment products",
            redistribution="separate S&P Global license required",
        ),
        _meta(
            "lseg_ibes_commercial",
            "LSEG",
            "https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/vendor-partner-ibes/",
            "https://wrds-www.wharton.upenn.edu/pages/about/what-wrds/",
            account=True,
            card=True,
            auth="institutional WRDS subscription plus LSEG vendor license",
            rate="contract dependent",
            start="product and region dependent",
            frequency="vendor updates",
            lag="estimate and recommendation announcement timestamps",
            identifiers="IBES ticker,CUSIP,analyst ID,broker ID",
            available_at="detail-history announcement and activation dates",
            pit="vintages required because broker and analyst IDs can be reassigned",
            redistribution="separate LSEG license required",
        ),
        _meta(
            "nyse_taq_commercial",
            "NYSE",
            "https://www.nyse.com/market-data/historical/daily-taq",
            "https://wrds-www.wharton.upenn.edu/pages/about/what-wrds/",
            account=True,
            card=True,
            auth="commercial NYSE or institutional WRDS license",
            rate="contract and delivery dependent",
            start="product vintage dependent",
            frequency="daily files",
            lag="vendor publication schedule",
            identifiers="symbol root,suffix,exchange,trade and quote timestamps",
            available_at="event timestamps and file publication date",
            pit="commercial consolidated intraday trades and quotes",
            redistribution="separate NYSE TAQ license required",
        ),
        _meta(
            "wrds_linking_suite",
            "Wharton Research Data Services",
            "https://wrds-www.wharton.upenn.edu/pages/grid-items/linking-suite-wrds/",
            "https://wrds-www.wharton.upenn.edu/pages/about/what-wrds/",
            account=True,
            card=True,
            auth="institutional WRDS plus every linked vendor license",
            rate="contract dependent",
            start="link and source-product dependent",
            frequency="WRDS updates",
            lag="source-product dependent",
            identifiers="PERMNO,GVKEY,IBES ticker,OptionMetrics SECID,TAQ symbol",
            available_at="link validity fields depend on each product",
            pit="historical commercial cross-database identity links",
            redistribution="WRDS and all linked vendor licenses required",
        ),
    )
}


RIO_SIGNALS = frozenset({"RIO_Disp", "RIO_MB", "RIO_Turnover", "RIO_Volatility"})
PATENT_SIGNALS = frozenset({"CitationsRD", "PatentsRD"})
OPTION_SIGNALS = frozenset(
    {
        "CPVolSpread", "RIVolSpread", "SmileSlope", "skew1", "dCPVolSpread",
        "dVolCall", "dVolPut", "OptionVolume1", "OptionVolume2",
    }
)
SHORT_INTEREST_SIGNALS = frozenset(
    {"ShortInterest", "IO_ShortInterest", "Recomm_ShortInterest"}
)
IPO_SIGNALS = frozenset({"AgeIPO", "IndIPO", "RDIPO"})
BEA_NETWORK_SIGNALS = frozenset({"iomom_cust", "iomom_supp"})
ZERO_TRADE_SIGNALS = frozenset({"zerotrade1M", "zerotrade6M", "zerotrade12M"})

PROXY_ONLY_SIGNALS = frozenset(
    {"DivYieldST", "DivInit", "DivOmit", "DivSeason", "Spinoff"}
)
NO_FREE_AUTHORIZED_SIGNALS = frozenset(
    {"CredRatDG", "CustomerMomentum", "retConglomerate", "sinAlgo"}
)
IDENTIFIER_BLOCKED_SIGNALS = frozenset(
    {"FirmAge", "CitationsRD", "PatentsRD", "iomom_cust", "iomom_supp"}
)
HISTORICAL_BLOCKED_SIGNALS = frozenset(
    {
        "AnnouncementReturn", "DelBreadth", "ExchSwitch", "Governance",
        "ProbInformedTrading", "betaVIX",
    }
) | OPTION_SIGNALS | SHORT_INTEREST_SIGNALS


def _clean_text(value: Any, fallback: str) -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return fallback
    return text


def _formula_record(
    signal: str, formula_inventory: pd.DataFrame
) -> tuple[str, str]:
    if formula_inventory.empty:
        return "unresolved", SIGNALDOC_URL
    indexed = formula_inventory.drop_duplicates("signal").set_index("signal")
    if signal not in indexed.index:
        return "unresolved", SIGNALDOC_URL
    row = indexed.loc[signal]
    status = _clean_text(row.get("status"), "unresolved")
    url = _clean_text(row.get("source_url"), SIGNALDOC_URL)
    return status, url


def classify_signal(
    signal: str,
    *,
    blocker_code: str,
    formula_status: str,
) -> str:
    if formula_status != "resolved":
        return "formula_ambiguous"
    if signal in PROXY_ONLY_SIGNALS:
        return "proxy_only"
    if signal in NO_FREE_AUTHORIZED_SIGNALS:
        return "no_free_authorized_source"
    if signal in IPO_SIGNALS:
        return "source_access_unverified"
    if signal in IDENTIFIER_BLOCKED_SIGNALS:
        return "identifier_bridge_missing"
    if signal in HISTORICAL_BLOCKED_SIGNALS:
        return "historical_point_in_time_missing"
    if blocker_code == "point_in_time_analyst_history_missing_or_unvalidated":
        return "historical_point_in_time_missing"
    if blocker_code in {
        "authorized_current_option_surface_missing",
        "issuer_option_volume_definition_and_validation_missing",
        "free_listed_short_interest_source_missing",
        "listed_short_interest_history_and_stock_validation_required",
    }:
        return "historical_point_in_time_missing"
    if blocker_code == "patent_assignee_to_public_issuer_crosswalk_missing":
        return "identifier_bridge_missing"
    if blocker_code == "firm_relationship_panel_missing_or_unvalidated":
        return "no_free_authorized_source"
    return "multiple_sources_required"


def _route_source_ids(signal: str, row: Mapping[str, Any]) -> tuple[str, ...]:
    category = _clean_text(row.get("category"), "not_documented")
    blocker = _clean_text(row.get("blocker_code"), "not_documented")
    sources: list[str] = ["openap_official"]
    if signal in OPTION_SIGNALS:
        sources += [
            "marketdata_options_free", "tradier_personal_api", "occ_option_volume",
            "cboe_delayed_options", "cboe_public_aggregate", "optionmetrics_ivydb_us",
            "wrds_linking_suite",
        ]
    elif signal in SHORT_INTEREST_SIGNALS:
        sources += [
            "finra_equity_short_interest", "exchange_short_interest", "sec_13f",
            "openfigi", "tiingo_starter", "crsp_stock_commercial",
        ]
        if signal == "Recomm_ShortInterest":
            sources += ["alpha_vantage_free", "fmp_basic", "lseg_ibes_commercial"]
    elif signal in PATENT_SIGNALS:
        sources += ["uspto_patentsview_bulk", "uspto_odp_patentsview", "google_patents_bigquery", "sec_edgar", "openfigi"]
    elif signal in RIO_SIGNALS or signal == "DelBreadth":
        sources += [
            "sec_13f", "openfigi", "tiingo_starter", "crsp_stock_commercial",
            "compustat_commercial", "wrds_linking_suite",
        ]
        if signal == "RIO_Disp":
            sources += ["alpha_vantage_free", "fmp_basic", "lseg_ibes_commercial"]
    elif signal in IPO_SIGNALS:
        sources += [
            "field_ritter_ipo", "sec_edgar", "tiingo_starter",
            "crsp_stock_commercial", "wrds_linking_suite",
        ]
    elif signal == "Governance":
        sources += ["yale_governance"]
    elif signal == "ProbInformedTrading":
        sources += [
            "edwin_hu_pin", "openfigi", "nyse_taq_commercial",
            "crsp_stock_commercial", "wrds_linking_suite",
        ]
    elif signal in BEA_NETWORK_SIGNALS:
        sources += [
            "bea_input_output", "census_naics_concordance", "sec_edgar",
            "tiingo_starter", "compustat_commercial", "wrds_linking_suite",
        ]
    elif signal == "CustomerMomentum" or signal == "sinAlgo":
        sources += ["sec_edgar", "openfigi", "compustat_commercial", "wrds_linking_suite"]
    elif signal == "betaVIX":
        sources += ["fred_vxo_vix", "tiingo_starter"]
    elif signal in ZERO_TRADE_SIGNALS:
        sources += [
            "tiingo_starter", "twelve_data_basic", "sec_edgar", "openfigi",
            "crsp_stock_commercial",
        ]
    elif blocker == "point_in_time_analyst_history_missing_or_unvalidated" or category == "Analyst":
        sources += [
            "alpha_vantage_free", "fmp_basic", "sec_edgar", "tiingo_starter",
            "lseg_ibes_commercial", "wrds_linking_suite",
        ]
    elif category == "Event":
        sources += [
            "sec_edgar", "tiingo_starter", "twelve_data_basic",
            "crsp_stock_commercial",
        ]
    elif category == "Accounting" or blocker == "sec_xbrl_formula_mapping_and_stock_validation_required":
        sources += [
            "sec_edgar", "sec_financial_statement_datasets", "tiingo_starter",
            "twelve_data_basic", "openfigi", "compustat_commercial",
            "crsp_stock_commercial", "wrds_linking_suite",
        ]
    else:
        sources += ["tiingo_starter", "twelve_data_basic", "fmp_basic", "sec_edgar", "openfigi"]
        if category in {"Price", "Trading"}:
            sources += ["kenneth_french_factors", "crsp_stock_commercial"]
        if blocker == "classified_intraday_trade_data_missing":
            sources += ["nyse_taq_commercial", "wrds_linking_suite"]
    return tuple(dict.fromkeys(sources))


def _next_action(signal: str, classification: str) -> str:
    if signal in RIO_SIGNALS:
        return "Reconcile SignalDoc typos with Nagel 2005 Table 2 and freeze an exact executable formula."
    if signal in OPTION_SIGNALS:
        return "Prove an authorized source preserves expired contracts and required IV fields, then compare its history with the OptionMetrics benchmark."
    if signal in SHORT_INTEREST_SIGNALS:
        return "Measure FINRA listed coverage from June 2021 and validate causal publication dates, shares and identifiers."
    if signal in PATENT_SIGNALS:
        return "Build and manually audit a historical assignee-to-CIK/FIGI bridge before computing the signal."
    if signal in IPO_SIGNALS:
        return "Obtain explicit scheduled-download permission and audit Field-Ritter PERMNO/CUSIP coverage against the 181-stock identity spine."
    if signal == "ProbInformedTrading":
        return "Reproduce PIN from author parameters through 2012 and document that GPIN/OWR after 2012 are not exact substitutes."
    if signal in ZERO_TRADE_SIGNALS:
        return "Verify that daily sources preserve active no-trade days and point-in-time shares, then compare with CRSP reference ranks."
    if signal in BEA_NETWORK_SIGNALS:
        return "Freeze a vintage-aware firm SIC/NAICS-to-BEA bridge and test many-to-many mappings before calculating returns."
    actions = {
        "multiple_sources_required": "Normalize exact inputs, run causal joins in GitHub and compare coverage and ranks with OpenAP.",
        "proxy_only": "Locate a primary exact event taxonomy; keep the current reconstruction labelled proxy until then.",
        "formula_ambiguous": "Resolve the official formula from primary code/paper evidence before testing any data source.",
        "identifier_bridge_missing": "Build a historical identity bridge and manually audit ambiguous mappings.",
        "historical_point_in_time_missing": "Locate an authorized vintage archive or prove the exact historical gap explicitly.",
        "no_free_authorized_source": "Seek a new primary zero-cost authorized source; do not automate the known restricted alternatives.",
        "source_access_unverified": "Obtain and record explicit automation/license evidence before scheduled access.",
        "exact_free_source_candidate": "Run independent stock-level coverage, rank-correlation and extreme-decile validation.",
    }
    return actions[classification]


def _classification_detail(classification: str) -> str:
    return {
        "multiple_sources_required": "A plausible free route exists only after causal joins and empirical fidelity validation.",
        "proxy_only": "Available public fields do not preserve the exact OpenAP/CRSP event taxonomy.",
        "formula_ambiguous": "No single executable official formula has yet been frozen.",
        "identifier_bridge_missing": "Required historical entity or security mapping is not proven.",
        "historical_point_in_time_missing": "The exact source is incomplete, stale or lacks the required historical vintages.",
        "no_free_authorized_source": "No zero-cost authorized source currently supplies the exact required panel.",
        "source_access_unverified": "The data are downloadable, but scheduled automation rights are not explicit.",
        "exact_free_source_candidate": "Source route is plausible but still requires independent validation.",
    }[classification]


def _source_is_project_usable(source_id: str) -> bool:
    source = next(item for item in SOURCE_CATALOG if item.source_id == source_id)
    project_use_blockers = {
        "aurora_project_use_without_written_permission",
        "signal_derivation_without_written_permission",
    }
    return (
        source.free
        and source.authorized_automation
        and project_use_blockers.isdisjoint(source.cannot_satisfy)
    )


def build_source_inventory() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for source in SOURCE_CATALOG:
        metadata = SOURCE_METADATA.get(source.source_id)
        if metadata is None:
            raise ValueError(f"Missing research metadata for source {source.source_id}")
        meta = asdict(metadata)
        rows.append(
            {
                "source_id": source.source_id,
                "source_name": source.source_name,
                "source_owner": meta["source_owner"],
                "source_url": source.url,
                "documentation_url": meta["documentation_url"],
                "terms_or_license_url": meta["terms_or_license_url"],
                "source_type": source.access_mode,
                "free_access_class": "free" if source.free else "commercial",
                "account_required": meta["account_required"],
                "payment_card_required": meta["payment_card_required"],
                "cost_eur": 0 if source.free else "commercial",
                "automation_allowed": source.authorized_automation,
                "aurora_project_use_authorized": _source_is_project_usable(
                    source.source_id
                ),
                "authentication_method": meta["authentication_method"],
                "rate_limit": meta["rate_limit"],
                "historical_start": meta["historical_start"],
                "historical_end": meta["historical_end"],
                "update_frequency": meta["update_frequency"],
                "publication_lag": meta["publication_lag"],
                "universe": source.coverage,
                "fields_available": "|".join(source.satisfies) or "not_verified",
                "identifier_types": meta["identifier_types"],
                "available_at_supported": meta["available_at_supported"],
                "point_in_time_quality": meta["point_in_time_quality"],
                "cannot_satisfy": "|".join(source.cannot_satisfy) or "none_documented",
                "redistribution": meta["redistribution"],
                "access_checked_at": RESEARCH_CHECKED_DATE,
                "notes": source.notes,
            }
        )
    result = pd.DataFrame(rows).sort_values("source_id").reset_index(drop=True)
    if result["source_id"].duplicated().any():
        raise ValueError("Source inventory contains duplicate source IDs")
    return result


def build_signal_resolution(
    manifest: pd.DataFrame,
    formula_inventory: pd.DataFrame,
) -> pd.DataFrame:
    if len(manifest) != 181 or manifest["signal"].nunique() != 181:
        raise ValueError("Source research requires exactly 181 unique manifest signals")
    rows: list[dict[str, Any]] = []
    for record in manifest.sort_values("signal").to_dict(orient="records"):
        signal = str(record["signal"])
        formula_status, formula_url = _formula_record(signal, formula_inventory)
        classification = classify_signal(
            signal,
            blocker_code=_clean_text(record.get("blocker_code"), "not_documented"),
            formula_status=formula_status,
        )
        sources = _route_source_ids(signal, record)
        authorized = [
            source_id for source_id in sources if _source_is_project_usable(source_id)
        ]
        restricted = [
            source_id
            for source_id in sources
            if not _source_is_project_usable(source_id)
        ]
        rows.append(
            {
                "signal": signal,
                "current_status": _clean_text(
                    record.get("raw_status"),
                    _clean_text(record.get("baseline_group"), "not_ready"),
                ),
                "best_free_source_option": "|".join(authorized) or "none_verified",
                "sources_required": "|".join(sources),
                "formula_status": formula_status,
                "official_formula_url": formula_url,
                "data_status": _classification_detail(classification),
                "identifier_status": (
                    "missing"
                    if classification == "identifier_bridge_missing"
                    else "requires_empirical_audit"
                ),
                "point_in_time_status": (
                    "missing_or_incomplete"
                    if classification == "historical_point_in_time_missing"
                    else "requires_causal_audit"
                ),
                "automation_status": (
                    "restricted_or_unverified:" + "|".join(restricted)
                    if restricted
                    else "candidate_sources_authorized"
                ),
                "final_research_classification": classification,
                "remaining_blocker": _clean_text(
                    record.get("blocker_code"), "not_documented"
                )
                + ": "
                + _classification_detail(classification),
                "next_exact_action": _next_action(signal, classification),
                "access_checked_at": RESEARCH_CHECKED_DATE,
            }
        )
    result = pd.DataFrame(rows)
    if len(result) != 181 or result["signal"].nunique() != 181:
        raise ValueError("Resolution output must contain exactly 181 unique signals")
    if not set(result["final_research_classification"]).issubset(ALLOWED_CLASSIFICATIONS):
        raise ValueError("Resolution output contains an unsupported classification")
    if result.fillna("").astype(str).apply(lambda col: col.str.strip().eq("").any()).any():
        raise ValueError("Resolution output contains blank required fields")
    return result


def build_signal_source_matrix(
    manifest: pd.DataFrame,
    formula_inventory: pd.DataFrame,
    resolution: pd.DataFrame,
) -> pd.DataFrame:
    inventory = build_source_inventory().set_index("source_id")
    resolved = resolution.set_index("signal")
    rows: list[dict[str, Any]] = []
    for record in manifest.sort_values("signal").to_dict(orient="records"):
        signal = str(record["signal"])
        formula_status, formula_url = _formula_record(signal, formula_inventory)
        classification = str(resolved.loc[signal, "final_research_classification"])
        for source_id in _route_source_ids(signal, record):
            source = inventory.loc[source_id]
            rows.append(
                {
                    "signal": signal,
                    "official_formula_status": formula_status,
                    "official_formula_url": formula_url,
                    "required_fields": _clean_text(
                        record.get("required_inputs"), "not_normalized"
                    ),
                    "source_name": source["source_name"],
                    "source_owner": source["source_owner"],
                    "source_url": source["source_url"],
                    "documentation_url": source["documentation_url"],
                    "terms_or_license_url": source["terms_or_license_url"],
                    "source_type": source["source_type"],
                    "free_access_class": source["free_access_class"],
                    "account_required": source["account_required"],
                    "payment_card_required": source["payment_card_required"],
                    "automation_allowed": source["automation_allowed"],
                    "aurora_project_use_authorized": source[
                        "aurora_project_use_authorized"
                    ],
                    "authentication_method": source["authentication_method"],
                    "rate_limit": source["rate_limit"],
                    "historical_start": source["historical_start"],
                    "historical_end": source["historical_end"],
                    "update_frequency": source["update_frequency"],
                    "universe": source["universe"],
                    "fields_available": source["fields_available"],
                    "identifier_types": source["identifier_types"],
                    "available_at_supported": source["available_at_supported"],
                    "point_in_time_quality": source["point_in_time_quality"],
                    "expected_formula_fidelity": _classification_detail(classification),
                    "coverage_verified": False,
                    "coverage_evidence": "not measured; requires a GitHub stock-level coverage run",
                    "classification": classification,
                    "blocking_reason": resolved.loc[signal, "remaining_blocker"],
                    "access_checked_at": RESEARCH_CHECKED_DATE,
                    "next_empirical_test": resolved.loc[signal, "next_exact_action"],
                }
            )
    result = pd.DataFrame(rows)
    if set(result["signal"]) != set(manifest["signal"]):
        raise ValueError("Source matrix does not cover all 181 signals")
    return result


def build_unresolved_signals(
    resolution: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in resolution.to_dict(orient="records"):
        classification = str(row["final_research_classification"])
        if classification == "exact_free_source_candidate":
            continue
        rows.append(
            {
                "signal": row["signal"],
                "classification": classification,
                "missing_formula": classification == "formula_ambiguous",
                "missing_inputs": classification in {"multiple_sources_required", "no_free_authorized_source"},
                "missing_source": classification in {"no_free_authorized_source", "source_access_unverified"},
                "missing_history": classification == "historical_point_in_time_missing",
                "missing_identifier_bridge": classification == "identifier_bridge_missing",
                "missing_permission": classification == "source_access_unverified",
                "missing_validation": True,
                "failed_sources": row["automation_status"],
                "why_proxies_are_not_exact": _classification_detail(classification),
                "next_research_action": row["next_exact_action"],
            }
        )
    return pd.DataFrame(rows)


def render_research_report(
    resolution: pd.DataFrame,
    source_inventory: pd.DataFrame,
) -> str:
    counts = resolution["final_research_classification"].value_counts().sort_index()
    signals_by_class = {
        classification: "`, `".join(
            resolution.loc[
                resolution["final_research_classification"].eq(classification),
                "signal",
            ].sort_values()
        )
        for classification in counts.index
    }
    account_sources = source_inventory.loc[
        source_inventory["free_access_class"].eq("free")
        & source_inventory["account_required"].eq(True),
        "source_name",
    ].sort_values()
    commercial_sources = source_inventory.loc[
        source_inventory["free_access_class"].eq("commercial"), "source_name"
    ].sort_values()
    restricted_sources = source_inventory.loc[
        source_inventory["aurora_project_use_authorized"].eq(False), "source_name"
    ].sort_values()
    lines = [
        "# OpenAP 181: investigación de fuentes gratuitas",
        "",
        f"Comprobado: {RESEARCH_CHECKED_DATE}. Señales: {len(resolution)}. Coste objetivo: 0 EUR.",
        "",
        "## Estado ejecutivo",
        "",
        "Ninguna señal se promueve a fiable por esta investigación. Las clasificaciones describen rutas y bloqueos; cobertura, causalidad y fidelidad siguen pendientes de medición independiente.",
        "",
        "| Clasificación | Señales |",
        "|---|---:|",
    ]
    for classification, count in counts.items():
        lines.append(f"| `{classification}` | {int(count)} |")
    lines += [
        "",
        "## Señales por resultado",
        "",
    ]
    for classification in counts.index:
        lines.append(f"- `{classification}`: `{signals_by_class[classification]}`")
    lines += [
        "",
        "## Hallazgos determinantes",
        "",
        "- [OpenSourceAP](https://github.com/OpenSourceAP/CrossSection) identifica `Signals/pyCode/Predictors/` como la construcción actual; el Stata duplicado es legado.",
        "- Los [SEC Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets) aportan estados primarios XBRL `as filed` desde abril de 2009, con accession y fecha de aceptación. No incluyen todas las notas ni demuestran equivalencia uno-a-uno con partidas Compustat.",
        "- [FINRA Equity Short Interest](https://www.finra.org/finra-data/browse-catalog/equity-short-interest) publica acciones cotizadas desde junio de 2021; el archivo anterior es OTC y no resuelve la historia listada.",
        "- La [tabla retrasada de Cboe](https://www.cboe.com/delayed_quotes/API/quote_table/) prohíbe extracción automática. [Market Data](https://www.marketdata.app/docs/api/options/chain/) ofrece una API de opciones de un año, pero sus [términos](https://www.marketdata.app/terms/) no autorizan todavía el uso de Aurora.",
        "- [OCC](https://www.theocc.com/market-data/market-data-reports/other-market-data-info/batch-processing/volume-query-batch-processing) documenta parámetros batch para volumen por emisor, pero sus [términos del sitio](https://www.theocc.com/specialpages/legal/terms-and-conditions) prohíben sistemas automatizados. No es una fuente programable autorizada.",
        "- [Tradier](https://docs.tradier.com/docs/historical-data) permite automatización personal y cadenas actuales, pero no conserva precios históricos de opciones expiradas y no ofrece Greeks en sandbox; no reproduce el panel histórico requerido.",
        "- [OptionMetrics IvyDB US](https://optionmetrics.com/data-products/) es la referencia comercial desde 1996 para bid/ask, volumen, open interest, IV, Greeks, superficies y continuidad de identidad. No es una solución de coste cero.",
        "- [WRDS](https://wrds-www.wharton.upenn.edu/pages/about/what-wrds/) confirma que CRSP, S&P/Compustat, LSEG I/B/E/S, NYSE TAQ y OptionMetrics requieren licencias separadas. Se conservan únicamente como benchmarks comerciales.",
        "- [Field-Ritter](https://site.warrington.ufl.edu/ritter/files/IPO-age.xlsx) cubre IPO y años de fundación de 1975-2025; la autorización de descarga programada no es explícita.",
        "- [Yale](https://faculty.som.yale.edu/andrewmetrick/data/) mantiene el índice Governance original solo para 1990-2006.",
        "- Los [autores de PIN](https://edwinhu.github.io/pin/) publican parámetros exactos hasta 2012; la extensión 2003-2024 contiene GPIN/OWR, que no son sustitutos exactos.",
        "- [BEA](https://www.bea.gov/data/industries/input-output-accounts-data) ofrece Make/Use e históricos en dominio público, pero el puente firma-año SIC/NAICS/BEA sigue sin probarse.",
        "- [SEC EDGAR](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) es gratuito y causal por fecha de aceptación, pero no convierte automáticamente conceptos Compustat en etiquetas XBRL equivalentes.",
        "- [Tiingo](https://api.tiingo.com/tos/) y [FMP](https://site.financialmodelingprep.com/terms-of-service) permiten acceso API, pero exigen permiso escrito para crear derivados; no son rutas legales actuales para señales Aurora.",
        "",
        "## Fuentes",
        "",
    ]
    for row in source_inventory.sort_values("source_id").to_dict(orient="records"):
        lines.append(
            f"- [{row['source_name']}]({row['source_url']}) — {row['free_access_class']}; "
            f"automatización={str(row['automation_allowed']).lower()}; "
            f"uso_Aurora={str(row['aurora_project_use_authorized']).lower()}; "
            f"{row['notes']}"
        )
    lines += [
        "",
        "## Acceso, licencias y cuentas",
        "",
        "- Fuentes gratuitas que requieren cuenta o clave: "
        + ", ".join(account_sources)
        + ".",
        "- Fuentes comerciales descartadas como solución: "
        + (", ".join(commercial_sources) or "ninguna")
        + ".",
        "- Fuentes no utilizables todavía por permisos, licencia o alcance: "
        + ", ".join(restricted_sources)
        + ".",
        "",
        "## Método y límites",
        "",
        f"Se revisaron {len(source_inventory)} fuentes: fórmulas oficiales, documentación, términos, cobertura declarada, identificadores y reglas available-at. Las afirmaciones de cobertura empírica permanecen en `false` hasta ejecutarse en GitHub Actions. No se usaron datos OOS bloqueados para seleccionar candidatos, ni fuentes de pago como solución gratuita, ni scraping prohibido.",
        "",
        "Los campos `not_verified` son bloqueos explícitos, no valores inferidos. Un proxy nunca cuenta como exacto.",
        "",
        "## Prioridades recomendadas",
        "",
        "1. SEC EDGAR y 13F: congelar conceptos, aceptación, enmiendas e identidad y validar primero la cobertura por señal.",
        "2. FINRA short interest: medir el periodo cotizado desde junio de 2021 sin extenderlo retrospectivamente.",
        "3. USPTO y BEA: construir y auditar puentes históricos antes de calcular cualquier señal.",
        "4. Opciones y analistas: mantener bloqueados hasta disponer de historia exacta y licencia compatible; Tradier y OCC no cubren esas brechas.",
        "",
    ]
    return "\n".join(lines)


def write_source_research_outputs(
    manifest: pd.DataFrame,
    formula_inventory: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inventory = build_source_inventory()
    resolution = build_signal_resolution(manifest, formula_inventory)
    matrix = build_signal_source_matrix(manifest, formula_inventory, resolution)
    unresolved = build_unresolved_signals(resolution)
    inventory.to_csv(output / "source_inventory_free.csv", index=False)
    resolution.to_csv(output / "signal_resolution_181.csv", index=False)
    matrix.to_csv(output / "signal_source_matrix_181.csv", index=False)
    unresolved.to_csv(output / "unresolved_signals.csv", index=False)
    (output / "RESEARCH_REPORT.md").write_text(
        render_research_report(resolution, inventory), encoding="utf-8"
    )
    summary = {
        "signals": int(len(resolution)),
        "unique_signals": int(resolution["signal"].nunique()),
        "source_matrix_rows": int(len(matrix)),
        "sources": int(len(inventory)),
        "unresolved_signals": int(len(unresolved)),
        "classifications": {
            str(key): int(value)
            for key, value in resolution["final_research_classification"]
            .value_counts()
            .sort_index()
            .items()
        },
        "checked_at": RESEARCH_CHECKED_DATE,
        "completion_claimed": False,
        "coverage_claimed": False,
        "cost_eur": 0,
    }
    (output / "source_research_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


__all__ = [
    "ALLOWED_CLASSIFICATIONS",
    "RESEARCH_CHECKED_DATE",
    "build_signal_resolution",
    "build_signal_source_matrix",
    "build_source_inventory",
    "build_unresolved_signals",
    "classify_signal",
    "render_research_report",
    "write_source_research_outputs",
]
