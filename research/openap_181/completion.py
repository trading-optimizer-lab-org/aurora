"""Canonical inventory and evidence gates for the unfinished OpenAP signals.

The module deliberately does not promote a value merely because a scraper or
formula produced a number.  A signal becomes ready only when the official
formula, causal inputs, current coverage, source rights and an independent
validation are all evidenced.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
import json

import pandas as pd

from aurora.research.openap_93.registry import REQUIRED_93, SignalSpec


class CompletionError(ValueError):
    """Raised when the official 212-signal universe cannot be reconciled."""


CURRENT_EXACT_31 = frozenset(
    {
        "AssetGrowth", "ChEQ", "ChInv", "ChNWC", "DolVol", "GrAdExp",
        "Illiquidity", "IntMom", "InvestPPEInv", "LRreversal", "MRreversal",
        "MaxRet", "Mom12m", "Mom12mOffSeason", "Mom6m", "MomOffSeason",
        "MomOffSeason06YrPlus", "MomOffSeason16YrPlus", "MomSeason",
        "MomSeason06YrPlus", "MomSeason11YrPlus", "MomSeason16YrPlus",
        "MomSeasonShort", "PctAcc", "Price", "ReturnSkew", "RoE",
        "STreversal", "ShareVol", "grcapx", "grcapx3y",
    }
)

CURRENT_PROXY_61 = frozenset(
    {
        "AM", "Accruals", "AdExp", "AnalystRevision", "BM", "BookLeverage",
        "CF", "CPVolSpread", "Cash", "CashProd", "ChAssetTurnover",
        "ChForecastAccrual", "ChTax", "CompositeDebtIssuance", "DebtIssuance",
        "DelCOA", "DelCOL", "DelEqu", "DelFINL", "DelLTI", "DownRecomm",
        "EP", "GP", "GrSaleToGrInv", "IdioVolAHT", "IndMom", "InvGrowth",
        "Investment", "Leverage", "NOA", "NetDebtFinance", "NetDebtPrice",
        "NetEquityFinance", "NetPayoutYield", "OPLeverage", "OperProf",
        "OptionVolume1", "OptionVolume2", "PayoutYield", "RD", "RDcap",
        "REV6", "RIVolSpread", "RealizedVol", "SP", "ShareIss1Y",
        "ShareIss5Y", "Size", "SmileSlope", "SurpriseRD", "TotalAccruals",
        "TrendFactor", "UpRecomm", "VolSD", "VolumeTrend", "XFIN", "cfp",
        "sfe", "skew1", "std_turn", "tang",
    }
)

CURRENT_EXCLUDED_27 = frozenset(
    {
        "Activism1", "Activism2", "AnalystValue", "Beta", "BetaFP",
        "BidAskSpread", "ChNAnalyst", "ConsRecomm", "DelDRC", "FR", "FirmAge",
        "GrSaleToGrOverhead", "HerfAsset", "High52", "MomOffSeason11YrPlus",
        "OperProfRD", "PredictedFE", "PriceDelaySlope", "PriceDelayTstat",
        "RDAbility", "ShareRepurchase", "VarCF", "VolMkt", "dVolPut",
        "iomom_cust", "realestate", "sinAlgo",
    }
)


OPTION_IV_SIGNALS = frozenset(
    {
        "CPVolSpread", "RIVolSpread", "SmileSlope", "skew1", "dCPVolSpread",
        "dVolCall", "dVolPut",
    }
)
OPTION_VOLUME_SIGNALS = frozenset({"OptionVolume1", "OptionVolume2"})
OPTION_SIGNALS = OPTION_IV_SIGNALS | OPTION_VOLUME_SIGNALS
SHORT_INTEREST_SIGNALS = frozenset(
    {"ShortInterest", "IO_ShortInterest", "Recomm_ShortInterest"}
)
PATENT_SIGNALS = frozenset({"CitationsRD", "PatentsRD"})
ANALYST_SIGNALS = frozenset(
    {
        "AOP", "AnalystRevision", "ChangeInRecommendation", "ChForecastAccrual",
        "DownRecomm", "EarningsForecastDisparity", "EarningsStreak",
        "EarningsSurprise", "EarnSupBig", "ExclExp", "FEPS",
        "ForecastDispersion", "NumEarnIncrease", "PredictedFE",
        "RevenueSurprise", "UpRecomm", "fgr5yrLag", "sfe",
    }
)
INSTITUTIONAL_SIGNALS = frozenset(
    {"IO_ShortInterest", "RIO_Disp", "RIO_MB", "RIO_Turnover", "RIO_Volatility"}
)
ZERO_TRADE_SIGNALS = frozenset({"zerotrade1M", "zerotrade6M", "zerotrade12M"})


@dataclass(frozen=True)
class SourceEvidence:
    source_id: str
    source_name: str
    url: str
    access_mode: str
    free: bool
    authorized_automation: bool
    coverage: str
    satisfies: tuple[str, ...]
    cannot_satisfy: tuple[str, ...]
    notes: str


SOURCE_CATALOG: tuple[SourceEvidence, ...] = (
    SourceEvidence(
        "openap_official", "Open Asset Pricing official data and code",
        "https://www.openassetpricing.com/data/", "public_download", True, True,
        "Official formulas, metadata and firm-level values through the published cutoff",
        ("formula_reference", "historical_validation_reference"),
        ("current_values_after_official_cutoff", "ticker_permno_crosswalk"),
        "Reference truth, not a current live feed.",
    ),
    SourceEvidence(
        "sec_edgar", "SEC EDGAR APIs and bulk files",
        "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "official_api_and_bulk", True, True,
        "US issuer filings, submissions and XBRL facts",
        ("accounting", "filing_events", "issuer_identity"),
        ("analyst_consensus", "listed_short_interest", "option_surface"),
        "Requires a declared User-Agent and at most 10 requests per second.",
    ),
    SourceEvidence(
        "sec_financial_statement_datasets", "SEC Financial Statement Data Sets",
        "https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets",
        "official_quarterly_bulk_zip", True, True,
        "As-filed XBRL face-financial numeric data from April 2009, flattened by quarter",
        (
            "as_filed_primary_financial_statement_facts", "filing_accession",
            "filing_acceptance_time", "sic", "xbrl_tags",
        ),
        (
            "pre_2009_history", "all_footnote_disclosures", "compustat_item_equivalence",
            "security_returns", "shares_outstanding_between_filings",
        ),
        "Official quarterly ZIPs preserve accession-level as-filed values and amendments. "
        "They do not contain every disclosure or establish a one-to-one Compustat mapping.",
    ),
    SourceEvidence(
        "yahoo_public", "Yahoo Finance public endpoints",
        "https://query1.finance.yahoo.com/", "public_endpoint_terms_review", True, False,
        "Current and historical prices plus selected snapshots",
        ("market_prices", "current_snapshot_proxy"),
        ("audited_point_in_time_analyst_history", "official_short_interest_history"),
        "Useful as a secondary source; terms and schema stability prevent exact-source status.",
    ),
    SourceEvidence(
        "cboe_delayed_options", "Cboe delayed options quotes",
        "https://www.cboe.com/delayed_quotes/", "public_delayed_quotes_terms_review",
        True, False, "Current delayed listed-option chains where available",
        ("current_option_chain_candidate",),
        ("historical_option_surface", "prior_month_iv_without_archived_snapshot"),
        "Cboe explicitly prohibits automated extraction of the delayed quote table; "
        "it cannot be used by the autonomous pipeline.",
    ),
    SourceEvidence(
        "cboe_public_aggregate", "Cboe public option volume and index histories",
        "https://www.cboe.com/us/options/market_statistics/historical_data/",
        "public_download_terms_review", True, True,
        "Aggregate option volume and public index histories",
        ("aggregate_option_volume", "vix_history"),
        ("firm_option_iv", "firm_option_greeks", "firm_option_smile"),
        "Aggregate volume is not an option chain or volatility surface.",
    ),
    SourceEvidence(
        "occ_option_volume", "OCC public option volume reports",
        "https://www.theocc.com/market-data/market-data-reports/volume-and-open-interest/volume-query",
        "public_web_and_documented_batch_urls", True, False,
        "Issuer-level calls and puts in daily, weekly and monthly public volume queries",
        ("recent_issuer_option_volume", "call_put_volume", "account_type_volume"),
        (
            "authorized_automation", "historical_option_surface", "implied_volatility",
            "greeks", "permanent_security_identity", "full_openap_sample_history",
        ),
        "OCC documents batch URL parameters, but its website terms updated 5 February 2025 "
        "expressly prohibit automated systems. It is reference evidence only unless OCC grants "
        "written permission.",
    ),
    SourceEvidence(
        "marketdata_options_free", "Market Data Free Forever options API",
        "https://www.marketdata.app/pricing/", "account_bearer_token_api",
        True, False, "US-listed option chains, delayed 24 hours, one year of history",
        (
            "recent_option_chain", "option_iv", "option_delta", "option_volume",
            "option_open_interest",
        ),
        (
            "option_history_before_one_year", "aurora_project_use_without_written_permission",
            "raw_data_redistribution",
        ),
        "The API is technically automatable at 100 daily credits, but the self-service "
        "license is personal/non-professional and defines broader research or testing as "
        "professional use. Treat Aurora use as unauthorized until written permission exists.",
    ),
    SourceEvidence(
        "massive_options_basic", "Massive Options Basic",
        "https://massive.com/options", "free_individual_api", True, False,
        "All US option tickers with two years of end-of-day OHLCV aggregates",
        ("option_contract_reference", "option_ohlcv", "option_volume"),
        (
            "historical_option_iv", "historical_option_open_interest",
            "historical_option_surface", "history_before_two_years",
            "permanent_security_identity", "aurora_project_use_without_written_permission",
        ),
        "The free individual plan omits the historical IV, open interest and long history "
        "required by OpenAP and is not licensed for project use.",
    ),
    SourceEvidence(
        "tradier_personal_api", "Tradier personal brokerage API",
        "https://docs.tradier.com/docs/market-data", "free_brokerage_account_api",
        True, True, "US equities and options; delayed sandbox and real-time brokerage data",
        (
            "current_option_chains", "option_contract_daily_ohlcv", "daily_equity_ohlcv",
            "market_calendar", "occ_option_symbol",
        ),
        (
            "historical_chain_enumeration", "historical_option_iv",
            "historical_option_open_interest", "historical_option_surface",
            "sandbox_greeks", "permanent_security_identity",
            "aurora_project_use_without_written_permission",
        ),
        "Tradier now documents OHLCV history for a known OCC option symbol, but does not "
        "provide the historical chain, IV, open interest, surface and identity panel required "
        "by OpenAP. Its self-service API entitlement is personal unless Partner approval exists.",
    ),
    SourceEvidence(
        "optionmetrics_ivydb_us", "OptionMetrics IvyDB US",
        "https://optionmetrics.com/data-products/", "commercial_subscription", False, False,
        "Complete US exchange-listed equity and index option history from January 1996",
        (
            "option_bid_ask", "option_volume", "option_open_interest", "implied_volatility",
            "greeks", "constant_maturity_volatility_surface", "permanent_option_identity",
            "corporate_actions",
        ),
        (),
        "Exact commercial benchmark for the OpenAP option families; contact-sales access is "
        "not a zero-cost source.",
    ),
    SourceEvidence(
        "alpha_vantage_options_premium", "Alpha Vantage Historical Options",
        "https://www.alphavantage.co/documentation/", "premium_api", False, False,
        "Full historical option chains with IV and Greeks for dates after 2008-01-01",
        ("historical_option_chain", "implied_volatility", "greeks"),
        (
            "zero_cost_access", "history_1996_to_2007", "optionmetrics_surface_equivalence",
            "permanent_security_identity",
        ),
        "Historical Options is explicitly premium and starts after the beginning of every "
        "OpenAP option study sample.",
    ),
    SourceEvidence(
        "finra_short_sale_volume", "FINRA daily short-sale volume",
        "https://www.finra.org/finra-data/browse-catalog/short-sale-volume",
        "official_api", True, True, "FINRA-reported short-sale transaction volume",
        ("short_sale_volume",), ("short_interest",),
        "FINRA explicitly states that short-sale volume is not short interest.",
    ),
    SourceEvidence(
        "finra_equity_short_interest", "FINRA Equity Short Interest",
        "https://www.finra.org/finra-data/browse-catalog/equity-short-interest",
        "official_grid_files_and_authenticated_api", True, True,
        "All exchange-listed and OTC equities from June 2021; archive files reach 2014, "
        "but files before June 2021 are OTC-only",
        ("listed_equity_short_interest_since_2021_06", "otc_short_interest"),
        (
            "listed_equity_short_interest_before_2021_06", "historical_revisions",
            "shares_outstanding",
        ),
        "Published twice monthly on the seventh business day after settlement. The public "
        "grid/files are free; Query API automation uses free FINRA credentials.",
    ),
    SourceEvidence(
        "exchange_short_interest", "NYSE and Nasdaq listed short interest products",
        "https://www.nyse.com/data-products/catalog/nyse-group-short-interest",
        "commercial_feed", False, False, "Listed exchange short interest",
        ("listed_equity_short_interest",), (),
        "The complete listed feed is commercial, so it cannot satisfy the free-only goal.",
    ),
    SourceEvidence(
        "twelve_data_basic", "Twelve Data Basic API",
        "https://twelvedata.com/pricing", "free_account_api_key",
        True, True, "US-listed equities; end-of-day history for most symbols from first trade",
        ("daily_ohlcv", "split_adjusted_prices", "exchange_and_mic_metadata"),
        (
            "otc_equities", "survivorship_free_permanent_identity",
            "free_dividend_adjustment_verified", "raw_data_redistribution",
        ),
        "Basic provides 8 credits per minute and 800 per day for internal non-display use. "
        "Daily data are split-adjusted; dividend-adjusted access on Basic needs an empirical gate.",
    ),
    SourceEvidence(
        "tiingo_starter", "Tiingo Starter API",
        "https://www.tiingo.com/about/pricing", "free_account_api_token",
        True, True, "US-focused end-of-day equities with 30+ years advertised depth",
        ("raw_ohlcv", "adjusted_ohlcv", "dividend", "split_factor", "exchange"),
        (
            "full_us_historical_universe_verified", "permanent_security_identity",
            "more_than_500_unique_symbols_per_month", "raw_data_redistribution",
            "signal_derivation_without_written_permission",
        ),
        "Free internal-use plan: 500 unique symbols per month, 50 requests per hour, "
        "1,000 requests per day and 1 GB per month. The terms updated 18 July 2026 "
        "require written approval to create or retain derived data, so Tiingo cannot "
        "currently supply Aurora signals even though its API itself is automatable.",
    ),
    SourceEvidence(
        "fmp_basic", "Financial Modeling Prep Basic API",
        "https://site.financialmodelingprep.com/developer/docs/pricing",
        "free_account_api_key", True, True,
        "US end-of-day and reference endpoints with a five-year free historical window",
        ("recent_eod_prices", "company_profile", "selected_reference_endpoints"),
        (
            "history_before_five_years", "full_analyst_endpoint_entitlement_verified",
            "ibes_definition_equivalence", "commercial_or_redistribution_use",
            "signal_derivation_without_written_permission",
        ),
        "Basic is free for individual use at 250 calls per day and 500 MB per trailing 30 "
        "days. Its terms prohibit derivative works without written approval; each analyst "
        "endpoint also needs an entitlement test before use.",
    ),
    SourceEvidence(
        "openfigi", "OpenFIGI mapping API",
        "https://www.openfigi.com/api/documentation", "public_api_optional_free_key",
        True, True, "Global instrument mappings for CUSIP, ISIN, ticker and other identifiers",
        ("cusip_figi_mapping", "isin_figi_mapping", "ticker_exchange_metadata"),
        ("cik_mapping", "historical_point_in_time_identity_guarantee"),
        "No key allows 25 requests per minute and 10 jobs per request; a free key allows "
        "25 requests per six seconds and 100 jobs. FIGI identifiers are public-domain.",
    ),
    SourceEvidence(
        "kenneth_french_factors", "Kenneth French Data Library",
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
        "public_static_download", True, False,
        "Daily and monthly US Fama-French factors from July 1926 with release archives",
        ("market_excess_return", "smb", "hml", "factor_validation"),
        ("stock_level_returns", "explicit_automation_permission"),
        "Direct files and dated archives are public, but explicit automated-download terms "
        "were not found. Treat scheduled collection as unverified until permission is established.",
    ),
    SourceEvidence(
        "fred_vxo_vix", "FRED VXO and VIX series",
        "https://fred.stlouisfed.org/series/VXOCLS", "free_api_key",
        True, True, "Daily VXO from 1986 through September 2021 and daily VIX from 1990",
        ("vxo_history", "vix_history"),
        ("exact_vxo_after_2021_09", "vix_as_exact_vxo_substitute"),
        "FRED permits automated API use with attribution and source-specific rights. VXO is "
        "the OpenAP betaVIX input; substituting VIX after VXO ended would be a proxy.",
    ),
    SourceEvidence(
        "uspto_patentsview_bulk", "USPTO PatentsView bulk datasets",
        "https://zenodo.org/records/15058362", "official_static_archive",
        True, True, "Final official PatentsView metadata release through 2024",
        ("patent_counts", "patent_citations", "assignee_identity"),
        ("assignee_to_public_issuer_crosswalk",),
        "USPTO-authored CC BY 4.0 archive; issuer linkage still needs a separately "
        "validated bridge.",
    ),
    SourceEvidence(
        "kpss_patent_crsp_extended", "KPSS patent-CRSP extended data",
        "https://github.com/KPSS2017/Technological-Innovation-Resource-Allocation-and-Growth-Extended-Data",
        "pinned_github_lfs_download_with_citation", True, True,
        "Patent-level panel and patent-to-PERMCO/PERMNO matches from 1926 through 2024",
        (
            "patent_counts_candidate", "total_forward_citations",
            "patent_permno_permco_bridge", "issue_date", "filing_date",
        ),
        (
            "openap_five_year_subcategory_scaled_ncitscale", "exact_xrd",
            "gvkey", "historical_crosswalk_vintages",
            "raw_redistribution_without_explicit_license",
        ),
        "The authors explicitly invite use with citation and document Git cloning. The "
        "repository has no formal license, so raw redistribution is not authorized. Its "
        "updated forward-citation total is not OpenAP's five-year subcategory-scaled input.",
    ),
    SourceEvidence(
        "google_patents_bigquery", "Google Patents Public Datasets",
        "https://cloud.google.com/blog/topics/public-datasets/google-patents-public-datasets-connecting-public-paid-and-private-patent-data",
        "public_bigquery_free_tier", True, True,
        "Worldwide patent publications, citations and assignee names maintained in BigQuery",
        ("patent_counts", "patent_citations", "assignee_identity"),
        ("assignee_to_public_issuer_crosswalk", "anonymous_access_without_google_project"),
        "Google hosts the public data and the first 1 TB of queries per month is free, "
        "but a Google Cloud project and credentials are still required for autonomous GitHub use.",
    ),
    SourceEvidence(
        "uspto_odp_patentsview", "USPTO Open Data Portal PatentsView datasets",
        "https://data.uspto.gov/bulkdata/datasets/pvannual", "account_and_api_key",
        True, True, "Current official PatentsView releases",
        ("patent_counts", "patent_citations", "assignee_identity"),
        ("assignee_to_public_issuer_crosswalk",),
        "Since 18 June 2026 ODP requires a free USPTO.gov account and API key. The "
        "official API authorizes automation, but credentials must be supplied by the user.",
    ),
    SourceEvidence(
        "sec_13f", "SEC Form 13F structured datasets",
        "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets",
        "official_bulk_download", True, True, "Quarterly institutional holdings",
        ("institutional_holdings",), ("complete_beneficial_ownership",),
        "CUSIP mapping and quarter availability must be handled causally.",
    ),
    SourceEvidence(
        "alpha_vantage_free", "Alpha Vantage free API",
        "https://www.alphavantage.co/documentation/", "free_api_key",
        True, False, "Ticker-level market, listing, shares and aggregate estimate endpoints",
        (
            "daily_ohlcv", "listing_status", "quarterly_shares_outstanding",
            "aggregate_earnings_estimates", "analyst_count_and_revision_snapshot",
        ),
        (
            "individual_analyst_recommendation_history", "ibes_definition_equivalence",
            "permanent_security_identity", "aurora_project_use_without_written_permission",
        ),
        "Most endpoints are free at 25 calls per day, but the free terms are personal and "
        "non-commercial and classify broader research/testing as commercial. Do not use in "
        "Aurora without written permission.",
    ),
    SourceEvidence(
        "nasdaq_zacks_premium", "Nasdaq Data Link Zacks analyst products",
        "https://docs.data.nasdaq.com/docs/data-organization", "premium_subscription",
        False, False, "Zacks earnings estimates and analyst ratings products",
        ("aggregate_earnings_estimates", "analyst_ratings"),
        ("zero_cost_access", "ibes_definition_equivalence", "permanent_free_access"),
        "Nasdaq Data Link classifies Zacks Earnings Estimates and Zacks Analyst Ratings "
        "as premium products, so they are references only for the zero-cost objective.",
    ),
    SourceEvidence(
        "zacks_data_commercial", "Zacks Investment Research Data",
        "https://zacksdata.com/consensus/faq/", "direct_or_wrds_vendor_license",
        False, False, "Point-in-time estimate, surprise and recommendation histories",
        ("estimate_vintages", "recommendations", "individual_contributors"),
        ("zero_cost_access", "ibes_definition_equivalence"),
        "Zacks documents long point-in-time history, but access requires a direct research "
        "system license or WRDS subscription.",
    ),
    SourceEvidence(
        "intrinio_zacks_enterprise", "Intrinio Zacks analyst products",
        "https://account.intrinio.com/pricing", "enterprise_or_temporary_trial",
        False, False, "Zacks EPS, growth, surprise and analyst-rating products",
        ("eps_estimates", "long_term_growth", "surprises", "analyst_ratings"),
        ("permanent_free_access", "ibes_definition_equivalence"),
        "The analyst products are enterprise datasets. A temporary trial is not a "
        "permanent free source for the Aurora pipeline.",
    ),
    SourceEvidence(
        "simfin_free", "SimFin free fundamentals",
        "https://www.simfin.com/en/prices/", "free_account_api",
        True, True, "Five recent years of standardized and as-reported fundamentals",
        ("recent_financial_statements", "as_reported_fundamentals"),
        (
            "history_before_five_years", "analyst_estimate_vintages",
            "analyst_recommendations", "compustat_definition_equivalence",
            "aurora_project_use_without_written_permission",
        ),
        "The free tier is automatable for recent fundamentals but lacks the historical "
        "depth and analyst records required by the OpenAP analyst families. Project signal "
        "derivation rights remain unverified, so this route is fail-closed.",
    ),
    SourceEvidence(
        "field_ritter_ipo", "Field-Ritter IPO founding dates",
        "https://site.warrington.ufl.edu/ritter/files/IPO-age.xlsx",
        "official_static_excel", True, False,
        "US IPOs and direct listings from 1975 through 2025",
        ("ipo_offer_date", "founding_year", "permno", "cusip", "ticker"),
        (
            "spac_merger_new_lists", "all_new_listings", "post_2025_updates",
            "explicit_automation_permission",
        ),
        "The author links the workbook for research and documents its construction, but no "
        "explicit automated-download terms were found. Validate permission before scheduled use.",
    ),
    SourceEvidence(
        "yale_governance", "Gompers-Ishii-Metrick Governance Index",
        "https://faculty.som.yale.edu/andrewmetrick/data/", "official_static_excel",
        True, False, "Firm-level Governance Index observations from 1990 through 2006",
        ("governance_index_1990_2006",),
        ("governance_index_after_2006", "explicit_automation_permission"),
        "Yale provides the original workbook directly. The page states the years and source "
        "paper but does not state a reusable license or automated-download permission.",
    ),
    SourceEvidence(
        "edwin_hu_pin", "Duarte-Hu-Young PIN model data",
        "https://edwinhu.github.io/pin/", "github_and_zenodo_public_download",
        True, True, "PIN-family stock-year estimates keyed by PERMNO",
        ("pin_parameters_1993_2012", "gpin_owr_parameters_2003_2024"),
        ("exact_pin_parameters_after_2012", "ticker_permno_crosswalk"),
        "The authors publish code and data under MIT terms. Their recent 2003-2024 release "
        "contains GPIN and OWR, not the exact PIN model required by ProbInformedTrading.",
    ),
    SourceEvidence(
        "bea_input_output", "BEA input-output accounts",
        "https://www.bea.gov/data/industries/input-output-accounts-data",
        "official_bulk_download", True, True, "US industry supplier-use relationships",
        ("industry_supplier_links",), ("firm_customer_links",),
        "Public-domain data are downloadable and available through a free API key. Needs an "
        "audited SIC/NAICS-to-BEA bridge for firm-level use and vintage-aware handling.",
    ),
    SourceEvidence(
        "census_naics_concordance", "US Census SIC-NAICS concordances",
        "https://www.census.gov/naics/concordances/concordances.html",
        "official_static_download", True, True,
        "Official classification-system concordances for published SIC and NAICS vintages",
        ("sic_naics_concordance",),
        ("unique_firm_naics", "point_in_time_company_classification"),
        "The concordance is frequently many-to-many; it cannot by itself assign an exact NAICS "
        "code to a firm-year.",
    ),
    SourceEvidence(
        "crsp_stock_commercial", "CRSP US Stock Databases",
        "https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/center-for-research-in-security-prices-crsp/",
        "wrds_subscription_and_vendor_license", False, False,
        "NYSE, AMEX and Nasdaq security prices, returns and volume with permanent identifiers",
        (
            "permno", "permco", "security_returns", "delisting_returns", "shares_outstanding",
            "volume", "corporate_actions", "historical_security_identity",
        ),
        (),
        "Commercial reference for stock-level OpenAP inputs and rank validation. WRDS states "
        "that CRSP requires a separate vendor license in addition to WRDS access.",
    ),
    SourceEvidence(
        "compustat_commercial", "S&P Compustat North America and historical segments",
        "https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/sp-global-market-intelligence/",
        "wrds_subscription_and_vendor_license", False, False,
        "North American fundamentals, point-in-time variants and historical segment data",
        (
            "compustat_fundamentals", "point_in_time_fundamentals", "unrestated_fundamentals",
            "historical_segments", "customer_segments", "gvkey", "cusip",
        ),
        (),
        "Exact commercial reference for Compustat-defined accounting and segment signals; "
        "the WRDS subscription does not include the required S&P license.",
    ),
    SourceEvidence(
        "lseg_ibes_commercial", "LSEG I/B/E/S",
        "https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/vendor-partner-ibes/",
        "wrds_subscription_and_vendor_license", False, False,
        "Detailed and summary analyst estimate, recommendation and actuals histories",
        (
            "analyst_estimate_vintages", "analyst_recommendations", "forecast_dispersion",
            "forecast_revisions", "ibes_ticker", "analyst_and_broker_identifiers",
        ),
        (),
        "Exact commercial benchmark for analyst signals. WRDS warns that analyst and broker "
        "identifiers can be reassigned, so each data vintage must be treated separately.",
    ),
    SourceEvidence(
        "nyse_taq_commercial", "NYSE TAQ",
        "https://www.nyse.com/market-data/historical/daily-taq", "commercial_subscription",
        False, False, "US consolidated intraday trades and quotes",
        (
            "intraday_trades", "intraday_quotes", "bid_ask", "trade_conditions",
            "exchange_timestamps",
        ),
        (),
        "Commercial benchmark for true intraday and microstructure signals; WRDS lists NYSE "
        "TAQ among datasets requiring a separate institutional license.",
    ),
    SourceEvidence(
        "wrds_linking_suite", "WRDS Linking Suite",
        "https://wrds-www.wharton.upenn.edu/pages/grid-items/linking-suite-wrds/",
        "wrds_and_vendor_subscriptions", False, False,
        "Historical links among CRSP, Compustat, I/B/E/S, OptionMetrics and TAQ",
        (
            "ibes_crsp_link", "optionmetrics_crsp_link", "taq_crsp_link",
            "crsp_compustat_link", "supply_chain_identifiers",
        ),
        (),
        "Commercial identity benchmark. Each linked vendor dataset needs its own license, so "
        "the links cannot solve the zero-cost objective.",
    ),
)


def _column(frame: pd.DataFrame, *candidates: str) -> str:
    lowered = {str(column).lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    raise CompletionError(f"Missing required column; expected one of {candidates}")


def _optional_value(row: Mapping[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None and not pd.isna(value):
            return value
    return ""


def _source_candidates(signal: str, category: str) -> tuple[str, ...]:
    if signal in OPTION_IV_SIGNALS:
        return (
            "marketdata_options_free", "massive_options_basic", "tradier_personal_api",
            "cboe_delayed_options", "alpha_vantage_options_premium",
            "optionmetrics_ivydb_us", "openap_official",
        )
    if signal in OPTION_VOLUME_SIGNALS:
        return (
            "marketdata_options_free", "massive_options_basic", "tradier_personal_api",
            "occ_option_volume", "cboe_delayed_options", "cboe_public_aggregate",
            "alpha_vantage_options_premium", "optionmetrics_ivydb_us", "openap_official",
        )
    if signal == "ShortInterest":
        return ("finra_equity_short_interest", "alpha_vantage_free")
    if signal == "IO_ShortInterest":
        return ("finra_equity_short_interest", "sec_13f", "alpha_vantage_free")
    if signal == "Recomm_ShortInterest":
        return ("finra_equity_short_interest", "alpha_vantage_free")
    if signal in PATENT_SIGNALS:
        return (
            "kpss_patent_crsp_extended", "google_patents_bigquery", "uspto_patentsview_bulk",
            "uspto_odp_patentsview", "sec_edgar",
        )
    if signal in ANALYST_SIGNALS:
        return (
            "openap_official", "alpha_vantage_free", "fmp_basic", "twelve_data_basic",
            "nasdaq_zacks_premium", "zacks_data_commercial",
            "intrinio_zacks_enterprise", "simfin_free", "sec_edgar",
            "sec_financial_statement_datasets", "openfigi", "lseg_ibes_commercial",
            "compustat_commercial", "crsp_stock_commercial", "wrds_linking_suite",
        )
    if signal in INSTITUTIONAL_SIGNALS:
        return ("sec_13f", "openap_official")
    text = category.lower()
    if any(token in text for token in ("account", "fundamental", "investment")):
        return ("sec_edgar", "openap_official")
    if any(token in text for token in ("price", "momentum", "trading", "market")):
        return ("yahoo_public", "openap_official")
    return ("openap_official", "sec_edgar", "yahoo_public")


def source_can_satisfy(signal: str, source_id: str) -> bool:
    """Hard semantic gates for commonly confused public datasets."""

    source = next((item for item in SOURCE_CATALOG if item.source_id == source_id), None)
    if source is None or not source.free or not source.authorized_automation:
        return False
    if signal in OPTION_SIGNALS:
        return False
    if signal in SHORT_INTEREST_SIGNALS and source_id == "finra_short_sale_volume":
        return False
    if signal in OPTION_IV_SIGNALS and source_id == "cboe_public_aggregate":
        return False
    if signal in PATENT_SIGNALS:
        return False
    return source_id in _source_candidates(signal, "")


def _specific_blocker(
    signal: str,
    *,
    baseline_group: str,
    category: str,
    spec: SignalSpec | None,
) -> str:
    """Return the most concrete known blocker instead of a generic label."""

    if signal in OPTION_IV_SIGNALS:
        return "authorized_current_option_surface_missing"
    if signal in OPTION_VOLUME_SIGNALS:
        return "issuer_option_volume_definition_and_validation_missing"
    if baseline_group == "statistically_excluded_or_not_selected":
        return "statistical_or_definition_review_required"
    if signal in SHORT_INTEREST_SIGNALS:
        return "listed_short_interest_history_and_stock_validation_required"
    if signal == "CitationsRD":
        return "patent_five_year_scaled_citations_and_exact_xrd_stock_validation_required"
    if signal == "PatentsRD":
        return "patent_counts_exact_xrd_and_stock_validation_required"
    if signal in ANALYST_SIGNALS:
        return "point_in_time_analyst_history_missing_or_unvalidated"
    if signal in INSTITUTIONAL_SIGNALS:
        return "institutional_mapping_and_stock_level_validation_required"
    if signal in ZERO_TRADE_SIGNALS:
        return "daily_zero_trade_days_shares_and_calendar_validation_required"
    family = (spec.data_family if spec is not None else category).lower()
    if family in {"microstructure", "intraday"}:
        return "classified_intraday_trade_data_missing"
    if family in {"supply_chain", "customer", "industry_network"}:
        return "firm_relationship_panel_missing_or_unvalidated"
    if family in {"accounting", "fundamental", "investment", "credit"}:
        return "sec_xbrl_formula_mapping_and_stock_validation_required"
    if family in {"market", "price", "momentum", "trading", "liquidity"}:
        return "market_formula_and_stock_level_validation_required"
    if family in {"event", "governance"}:
        return "causal_event_taxonomy_and_stock_validation_required"
    return "required_inputs_or_stock_level_validation_missing"


def build_source_catalog() -> pd.DataFrame:
    rows = []
    for source in SOURCE_CATALOG:
        record = asdict(source)
        record["satisfies"] = "|".join(source.satisfies)
        record["cannot_satisfy"] = "|".join(source.cannot_satisfy)
        rows.append(record)
    return pd.DataFrame(rows).sort_values("source_id").reset_index(drop=True)


def _normalise_current_coverage(coverage: pd.DataFrame) -> pd.DataFrame:
    """Translate the current-score coverage contract to the audit contract.

    The current-score pipeline deliberately reports 185 candidate predictors,
    while this audit owns the canonical unfinished 181.  Keep the two
    inventories separate and translate only the shared evidence columns.
    """

    if coverage.empty or "signalname" not in coverage.columns:
        return coverage
    result = coverage.copy()
    result["signal"] = result["signalname"].astype(str).str.strip()
    if "symbols_with_value" in result.columns and "non_null_count" not in result:
        result["non_null_count"] = result["symbols_with_value"]
    if "coverage_status" in result.columns:
        fidelity_map = {
            "exact": "exact_unvalidated",
            "proxy": "unvalidated_proxy",
            "mixed": "mixed_exact_proxy_unvalidated",
            "unavailable": "unavailable",
        }
        result["fidelity_class"] = result["coverage_status"].map(fidelity_map).fillna(
            "unclassified"
        )
        result["status"] = (
            "current_" + result["coverage_status"].astype(str) + "_unvalidated"
        )
    return result


def build_completion_manifest(
    signal_doc: pd.DataFrame,
    *,
    registry_93: Mapping[str, SignalSpec] | None = None,
) -> pd.DataFrame:
    """Build the canonical 181-row unfinished-signal manifest."""

    acronym = _column(signal_doc, "Acronym", "signalname", "signal")
    official = signal_doc.copy()
    official[acronym] = official[acronym].astype(str).str.strip()
    official = official.loc[official[acronym].ne("")].drop_duplicates(acronym)
    required_93 = set(REQUIRED_93)
    groups = [
        set(CURRENT_EXACT_31), set(CURRENT_PROXY_61), required_93,
        set(CURRENT_EXCLUDED_27),
    ]
    if any(left & right for index, left in enumerate(groups) for right in groups[index + 1 :]):
        raise CompletionError("The four canonical OpenAP groups must be disjoint")
    official_universe = set().union(*groups)
    if len(official_universe) != 212:
        raise CompletionError(
            f"Expected a 212-signal canonical universe, found {len(official_universe)}"
        )
    available_names = set(official[acronym])
    missing_known = official_universe - available_names
    if missing_known:
        raise CompletionError(f"Known signals absent from SignalDoc: {sorted(missing_known)}")
    official_names = official_universe
    official = official.loc[official[acronym].isin(official_universe)].copy()
    excluded = set(CURRENT_EXCLUDED_27)

    rows: list[dict[str, Any]] = []
    by_name = official.set_index(acronym).to_dict(orient="index")
    registry_93 = registry_93 or {}
    for signal in sorted(official_names - set(CURRENT_EXACT_31)):
        source_row = by_name[signal]
        category = str(
            _optional_value(source_row, "Cat.Data", "Category", "Cat.Form")
        )
        spec = registry_93.get(signal)
        if signal in CURRENT_PROXY_61:
            baseline_group = "current_proxy_unvalidated"
            readiness = "not_ready"
        elif signal in required_93:
            baseline_group = "strict_93_unfinished"
            readiness = "not_ready"
        else:
            baseline_group = "statistically_excluded_or_not_selected"
            readiness = "not_ready"
        blocker = _specific_blocker(
            signal,
            baseline_group=baseline_group,
            category=category,
            spec=spec,
        )
        candidates = (
            tuple(spec.candidate_sources)
            if spec is not None
            else _source_candidates(signal, category)
        )
        required_inputs = (
            tuple(spec.required_inputs)
            if spec is not None
            else (str(_optional_value(source_row, "Detailed Definition", "Definition")),)
        )
        rows.append(
            {
                "signal": signal,
                "baseline_group": baseline_group,
                "readiness": readiness,
                "current_usable": False,
                "official_formula_path": (
                    spec.openap_script
                    if spec is not None
                    else str(_optional_value(source_row, "Code", "Code Path"))
                ),
                "official_definition": str(
                    _optional_value(source_row, "Detailed Definition", "Definition")
                ),
                "category": category,
                "portfolio_period_months": _optional_value(
                    source_row, "Portfolio Period", "Portfolio.Period"
                ),
                "reproduction_tstat": "",
                "study_tstat": _optional_value(source_row, "T-Stat", "T.Stat"),
                "required_inputs": json.dumps(required_inputs, ensure_ascii=True),
                "candidate_sources": json.dumps(candidates, ensure_ascii=True),
                "blocker_code": blocker,
                "validation_required": (
                    "independent stock-level rank correlation, extreme-decile agreement, "
                    "coverage and causal available-at audit"
                ),
                "evidence_complete": False,
            }
        )
    manifest = pd.DataFrame(rows).sort_values("signal").reset_index(drop=True)
    if len(manifest) != 181 or manifest["signal"].nunique() != 181:
        raise CompletionError("The unfinished manifest must contain 181 unique signals")
    if manifest["current_usable"].any() or manifest["evidence_complete"].any():
        raise CompletionError("Unvalidated baseline signals cannot be marked ready")
    return manifest


def attach_runtime_evidence(
    manifest: pd.DataFrame,
    *,
    reproduction_summary: pd.DataFrame | None = None,
    current_features: pd.DataFrame | None = None,
    coverage_93: pd.DataFrame | None = None,
    current_coverage: pd.DataFrame | None = None,
    formula_inventory: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Attach measured current coverage without changing readiness.

    Raw availability and readiness are intentionally different columns.  This
    prevents a wide panel with non-null proxies from bypassing fidelity gates.
    """

    result = manifest.copy()
    result["raw_current_value_available"] = False
    result["raw_current_non_null_count"] = 0
    result["raw_current_coverage_pct"] = 0.0
    result["raw_fidelity"] = ""
    result["raw_status"] = ""
    result["validation_paired_observations"] = 0
    result["validation_spearman"] = pd.NA
    result["validation_extreme_decile_agreement"] = pd.NA
    result["formula_status"] = ""
    result["formula_commit"] = ""
    result["formula_source_url"] = ""
    result["formula_sha256"] = ""
    result["raw_unavailable_reasons"] = ""
    result["raw_value_sources"] = ""

    if reproduction_summary is not None and not reproduction_summary.empty:
        name_column = _column(reproduction_summary, "signalname", "Acronym", "signal")
        tstat_column = _column(reproduction_summary, "tstat")
        stats = (
            reproduction_summary[[name_column, tstat_column]]
            .drop_duplicates(name_column)
            .set_index(name_column)[tstat_column]
        )
        result["reproduction_tstat"] = result["signal"].map(stats)

    if current_features is not None and not current_features.empty:
        denominator = len(current_features)
        for signal in set(result["signal"]).intersection(current_features.columns):
            count = int(pd.to_numeric(current_features[signal], errors="coerce").notna().sum())
            mask = result["signal"].eq(signal)
            result.loc[mask, "raw_current_value_available"] = count > 0
            result.loc[mask, "raw_current_non_null_count"] = count
            result.loc[mask, "raw_current_coverage_pct"] = (
                100.0 * count / denominator if denominator else 0.0
            )
            result.loc[mask, "raw_fidelity"] = "unvalidated_proxy"
            result.loc[mask, "raw_status"] = "current_value_requires_validation"

    is_current_coverage = (
        current_coverage is not None
        and not current_coverage.empty
        and "signalname" in current_coverage.columns
    )
    runtime_coverage = current_coverage if current_coverage is not None else coverage_93
    runtime_coverage = (
        _normalise_current_coverage(runtime_coverage)
        if runtime_coverage is not None
        else None
    )
    if runtime_coverage is not None and not runtime_coverage.empty:
        name_column = _column(runtime_coverage, "signal")
        indexed = runtime_coverage.drop_duplicates(name_column).set_index(name_column)
        field_map = {
            "non_null_count": "raw_current_non_null_count",
            "coverage_pct": "raw_current_coverage_pct",
            "fidelity_class": "raw_fidelity",
            "status": "raw_status",
            "paired_observations": "validation_paired_observations",
            "spearman": "validation_spearman",
            "extreme_decile_agreement": "validation_extreme_decile_agreement",
        }
        for source_field, target_field in field_map.items():
            if source_field not in indexed.columns:
                continue
            mapped = result["signal"].map(indexed[source_field])
            result.loc[mapped.notna(), target_field] = mapped.loc[mapped.notna()]
        for source_field, target_field in {
            "unavailable_reasons": "raw_unavailable_reasons",
            "value_sources": "raw_value_sources",
        }.items():
            if source_field not in indexed.columns:
                continue
            mapped = result["signal"].map(indexed[source_field])
            result.loc[mapped.notna(), target_field] = mapped.loc[mapped.notna()]
        if "non_null_count" in indexed.columns:
            counts = pd.to_numeric(result["raw_current_non_null_count"], errors="coerce").fillna(0)
            result["raw_current_value_available"] = counts.gt(0)
        if is_current_coverage:
            missing = ~result["signal"].isin(indexed.index)
            result.loc[missing, "raw_fidelity"] = "not_applicable_current_score"
            result.loc[missing, "raw_status"] = "excluded_from_current_score_universe"
            result.loc[missing, "raw_unavailable_reasons"] = (
                "excluded_from_current_score_universe"
            )
            result.loc[missing, "raw_value_sources"] = "coverage_185_absent"

    if formula_inventory is not None and not formula_inventory.empty:
        name_column = _column(formula_inventory, "signal")
        indexed = formula_inventory.drop_duplicates(name_column).set_index(name_column)
        field_map = {
            "status": "formula_status",
            "commit": "formula_commit",
            "source_url": "formula_source_url",
            "sha256": "formula_sha256",
            "path": "official_formula_path",
        }
        for source_field, target_field in field_map.items():
            if source_field not in indexed.columns:
                continue
            mapped = result["signal"].map(indexed[source_field])
            result.loc[mapped.notna(), target_field] = mapped.loc[mapped.notna()]

    # Evidence attachment must never silently promote a baseline signal.
    result["current_usable"] = False
    result["evidence_complete"] = False
    result["readiness"] = "not_ready"
    return result


def write_completion_outputs(
    manifest: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    catalog = build_source_catalog()
    manifest.to_csv(output / "openap_181_completion_manifest.csv", index=False)
    catalog.to_csv(output / "openap_181_source_catalog.csv", index=False)
    blockers = (
        manifest.groupby(["baseline_group", "blocker_code"], dropna=False)
        .size()
        .rename("signal_count")
        .reset_index()
        .sort_values("signal_count", ascending=False)
    )
    blockers.to_csv(output / "openap_181_blockers.csv", index=False)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_predictors": 212,
        "already_ready_exact": len(CURRENT_EXACT_31),
        "unfinished_signals": int(len(manifest)),
        "ready_after_audit": int(manifest["current_usable"].sum()),
        "proxy_unvalidated": int(
            manifest["baseline_group"].eq("current_proxy_unvalidated").sum()
        ),
        "strict_93_unfinished": int(
            manifest["baseline_group"].eq("strict_93_unfinished").sum()
        ),
        "statistically_excluded_or_not_selected": int(
            manifest["baseline_group"].eq("statistically_excluded_or_not_selected").sum()
        ),
        "completion_claimed": False,
        "fail_closed": True,
        "cost_eur": 0,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (output / "openap_181_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary
