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
    {"CPVolSpread", "RIVolSpread", "SmileSlope", "skew1", "dCPVolSpread", "dVolCall"}
)
OPTION_VOLUME_SIGNALS = frozenset({"OptionVolume1", "OptionVolume2"})
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
        "Can support a current reconstruction only after field and terms validation.",
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
        "finra_short_sale_volume", "FINRA daily short-sale volume",
        "https://www.finra.org/finra-data/browse-catalog/short-sale-volume",
        "official_api", True, True, "FINRA-reported short-sale transaction volume",
        ("short_sale_volume",), ("short_interest",),
        "FINRA explicitly states that short-sale volume is not short interest.",
    ),
    SourceEvidence(
        "finra_otc_short_interest", "FINRA OTC equity short interest",
        "https://www.finra.org/finra-data/browse-catalog/equity-short-interest/data",
        "official_api", True, True, "OTC securities only",
        ("otc_short_interest",), ("listed_equity_short_interest",),
        "Does not cover the full NYSE/Nasdaq listed-stock universe.",
    ),
    SourceEvidence(
        "exchange_short_interest", "NYSE and Nasdaq listed short interest products",
        "https://www.nyse.com/data-products/catalog/nyse-group-short-interest",
        "commercial_feed", False, False, "Listed exchange short interest",
        ("listed_equity_short_interest",), (),
        "The complete listed feed is commercial, so it cannot satisfy the free-only goal.",
    ),
    SourceEvidence(
        "uspto_patentsview_bulk", "USPTO PatentsView bulk datasets",
        "https://data.uspto.gov/bulkdata/datasets/pvannual", "official_bulk_download",
        True, True, "Disambiguated patent, assignee and citation data through 2025",
        ("patent_counts", "patent_citations", "assignee_identity"),
        ("assignee_to_public_issuer_crosswalk",),
        "Public bulk source; issuer linkage still needs a separately validated bridge.",
    ),
    SourceEvidence(
        "sec_13f", "SEC Form 13F structured datasets",
        "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets",
        "official_bulk_download", True, True, "Quarterly institutional holdings",
        ("institutional_holdings",), ("complete_beneficial_ownership",),
        "CUSIP mapping and quarter availability must be handled causally.",
    ),
    SourceEvidence(
        "bea_input_output", "BEA input-output accounts",
        "https://www.bea.gov/data/industries/input-output-accounts-data",
        "official_bulk_download", True, True, "US industry supplier-use relationships",
        ("industry_supplier_links",), ("firm_customer_links",),
        "Needs an audited SIC/NAICS-to-BEA bridge for firm-level use.",
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
        return ("cboe_delayed_options", "openap_official")
    if signal in OPTION_VOLUME_SIGNALS:
        return ("cboe_delayed_options", "cboe_public_aggregate")
    if signal in SHORT_INTEREST_SIGNALS:
        return ("exchange_short_interest", "finra_otc_short_interest")
    if signal in PATENT_SIGNALS:
        return ("uspto_patentsview_bulk", "sec_edgar")
    if signal in ANALYST_SIGNALS:
        return ("openap_official", "yahoo_public")
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

    if signal in SHORT_INTEREST_SIGNALS and source_id == "finra_short_sale_volume":
        return False
    if signal in OPTION_IV_SIGNALS and source_id == "cboe_public_aggregate":
        return False
    if signal in PATENT_SIGNALS and source_id == "uspto_patentsview_bulk":
        return True
    return source_id in _source_candidates(signal, "")


def build_source_catalog() -> pd.DataFrame:
    rows = []
    for source in SOURCE_CATALOG:
        record = asdict(source)
        record["satisfies"] = "|".join(source.satisfies)
        record["cannot_satisfy"] = "|".join(source.cannot_satisfy)
        rows.append(record)
    return pd.DataFrame(rows).sort_values("source_id").reset_index(drop=True)


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
            blocker = "independent_stock_level_validation_required"
            readiness = "not_ready"
        elif signal in required_93:
            baseline_group = "strict_93_unfinished"
            blocker = "required_inputs_or_validation_missing"
            readiness = "not_ready"
        else:
            baseline_group = "statistically_excluded_or_not_selected"
            blocker = "statistical_or_definition_review_required"
            readiness = "not_ready"
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

    if coverage_93 is not None and not coverage_93.empty:
        name_column = _column(coverage_93, "signal")
        indexed = coverage_93.drop_duplicates(name_column).set_index(name_column)
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
        if "non_null_count" in indexed.columns:
            counts = pd.to_numeric(result["raw_current_non_null_count"], errors="coerce").fillna(0)
            result["raw_current_value_available"] = counts.gt(0)

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
