"""Pinned formula contracts and fail-closed source evidence for analyst signals."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
import json
import re

import pandas as pd


OPENAP_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"

_AOP_PATH = (
    "Signals/pyCode/Predictors/"
    "ZZ1_AnalystValue_AOP_PredictedFE_IntrinsicValue.py"
)
OPENAP_FORMULA_SOURCES: dict[str, dict[str, str]] = {
    "AOP": {
        "path": _AOP_PATH,
        "sha256": "86f76a954ceab140620827c77bf1b20bf6a4b524d0359a6894bd0a80e210b55a",
    },
    "AnalystRevision": {
        "path": "Signals/pyCode/Predictors/AnalystRevision.py",
        "sha256": "d4b6abd868bb612d3aedd45dbe64dedcd039b8da54d8151c4fbadf5caa4a3ab4",
    },
    "ChangeInRecommendation": {
        "path": "Signals/pyCode/Predictors/ChangeInRecommendation.py",
        "sha256": "5dd4b65c176e942e9d1c34f4f7d873253e2e8be9230160239ce5a2763f09f0a1",
    },
    "ChForecastAccrual": {
        "path": "Signals/pyCode/Predictors/ChForecastAccrual.py",
        "sha256": "350fad647ccb82592711d818b383dd113b9e1e853cc778c1163fc67f1f048384",
    },
    "DownRecomm": {
        "path": "Signals/pyCode/Predictors/DownRecomm.py",
        "sha256": "24ae1bd0616cb01a9c3b350565feeaed9f7068d7450e7f67185d0132ab69bd76",
    },
    "EarningsForecastDisparity": {
        "path": "Signals/pyCode/Predictors/EarningsForecastDisparity.py",
        "sha256": "5129d3753b1a5f6e528b29f6696478eda41d6fdabcab99395d55bf5f896b0c28",
    },
    "EarningsStreak": {
        "path": "Signals/pyCode/Predictors/EarningsStreak.py",
        "sha256": "b0f180cfd9d68a0dea17700c067f1bda47cf758249f55fa7c35516815bc1386d",
    },
    "EarningsSurprise": {
        "path": "Signals/pyCode/Predictors/EarningsSurprise.py",
        "sha256": "bc5ddeb08dbff2036e5443f06b895c113a8d556ed577c9a8a8d7e23b7e52c279",
    },
    "EarnSupBig": {
        "path": "Signals/pyCode/Predictors/EarnSupBig.py",
        "sha256": "3ea24680269cbe3aded1b060728bae655676e8448a51c6fcef5aeac0e23cf20b",
    },
    "ExclExp": {
        "path": "Signals/pyCode/Predictors/ExclExp.py",
        "sha256": "33913b9d3d259bae1fdca33e75e690bb1c27f8af2fa518f74fd7453e1955628e",
    },
    "FEPS": {
        "path": "Signals/pyCode/Predictors/FEPS.py",
        "sha256": "d9c8228ba8f1a87a4beb74e99f9784ad41af1cecb2e32c77250275522a57552b",
    },
    "ForecastDispersion": {
        "path": "Signals/pyCode/Predictors/ForecastDispersion.py",
        "sha256": "8021434c5790e0b321960972693389b723e256f5442edcf3438ce3d0f3ccace4",
    },
    "NumEarnIncrease": {
        "path": "Signals/pyCode/Predictors/NumEarnIncrease.py",
        "sha256": "575b3ed1cdb97df48e03ad6d00d883b8d476b169178979579c59a5b312ddadf3",
    },
    "PredictedFE": {
        "path": _AOP_PATH,
        "sha256": "86f76a954ceab140620827c77bf1b20bf6a4b524d0359a6894bd0a80e210b55a",
    },
    "RevenueSurprise": {
        "path": "Signals/pyCode/Predictors/RevenueSurprise.py",
        "sha256": "00b8b548e0e913bdb5d9ff9f41da8766d7494286f5de2dbacf3aaa4410dc0cbc",
    },
    "UpRecomm": {
        "path": "Signals/pyCode/Predictors/UpRecomm.py",
        "sha256": "763f4442926c88791fc442355c9cdd2ffc5eb5d16091ff09a14705a481aa0650",
    },
    "fgr5yrLag": {
        "path": "Signals/pyCode/Predictors/fgr5yrLag.py",
        "sha256": "e78d8372ce4c037e4e68aaff419c7dc5f138d7816f8ebeb0097873d654e30556",
    },
    "sfe": {
        "path": "Signals/pyCode/Predictors/sfe.py",
        "sha256": "254a0a886c43c6e7949441fb2d78cebc8ff2b65bab31c94a454f4afc1c28ec0c",
    },
}
ANALYST_SIGNALS = frozenset(OPENAP_FORMULA_SOURCES)

ANALYST_SIGNAL_FAMILIES = {
    "AOP": "ibes_mixed",
    "AnalystRevision": "ibes_forecast_vintages",
    "ChangeInRecommendation": "ibes_recommendations",
    "ChForecastAccrual": "ibes_mixed",
    "DownRecomm": "ibes_recommendations",
    "EarningsForecastDisparity": "ibes_forecast_vintages",
    "EarningsStreak": "ibes_forecast_vintages",
    "EarningsSurprise": "accounting_compustat",
    "EarnSupBig": "accounting_compustat",
    "ExclExp": "ibes_mixed",
    "FEPS": "ibes_forecast_vintages",
    "ForecastDispersion": "ibes_forecast_vintages",
    "NumEarnIncrease": "accounting_compustat",
    "PredictedFE": "ibes_compustat_crsp_cross_section",
    "RevenueSurprise": "accounting_compustat",
    "UpRecomm": "ibes_recommendations",
    "fgr5yrLag": "ibes_mixed",
    "sfe": "ibes_mixed",
}


def _requirement(
    formula: str,
    exact_inputs: str,
    timing: str,
    sample_start: int,
    sample_end: int,
    identity: str,
) -> dict[str, Any]:
    return {
        "formula": formula,
        "exact_inputs": exact_inputs,
        "timing": timing,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "identity": identity,
    }


ANALYST_FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "AOP": _requirement(
        "(AnalystValue-IntrinsicValue)/abs(IntrinsicValue)",
        "ibes_unadjusted_fpi_1_2;ibes_ltg_fpi_0;crsp_price_shares;"
        "compustat_ceq_ibcom_dvc_at_sale;ibes_permno_link",
        "May estimate vintage; June formation; one-month causal lag; twelve-month hold",
        1975,
        1993,
        "historical IBES ticker to CRSP PERMNO and Compustat GVKEY bridge",
    ),
    "AnalystRevision": _requirement(
        "meanest divided by exact one-month lag of meanest",
        "ibes_unadjusted_eps_fpi_1;statpers;meanest",
        "monthly; last eligible forecast aggregate; exact one-month calendar lag",
        1975,
        1980,
        "historical IBES ticker to security bridge",
    ),
    "ChangeInRecommendation": _requirement(
        "(6-mean(ireccd)) minus its exact one-month lag",
        "individual_analyst_id;broker_id;ireccd;anndats;recommendation_vintage",
        "last recommendation per analyst-firm-month; then monthly firm mean",
        1985,
        1998,
        "vintage-specific IBES analyst, broker and firm identifiers",
    ),
    "ChForecastAccrual": _requirement(
        "within upper accrual half: 1 for meanest increase, 0 for decrease",
        "ibes_meanest_fpi_1;compustat_act_che_lct_dlc_txp_at;exact_12m_lags",
        "monthly median accrual split; forecast compared with exact prior month",
        1981,
        1996,
        "historical IBES ticker, GVKEY and PERMNO bridge",
    ),
    "DownRecomm": _requirement(
        "1 when mean ireccd worsens versus exact prior month, otherwise 0",
        "individual_analyst_id;broker_id;ireccd;anndats;recommendation_vintage",
        "last recommendation per analyst-firm-month; exact one-month lag",
        1985,
        1997,
        "vintage-specific IBES analyst, broker and firm identifiers",
    ),
    "EarningsForecastDisparity": _requirement(
        "IBES LTG - 100*(FY1 meanest-FY0 actual)/abs(FY0 actual)",
        "ibes_unadjusted_fpi_1;ibes_ltg_fpi_0;ibes_unadjusted_actual;fpedats;statpers",
        "monthly; FY1 period end more than thirty days after statpers",
        1983,
        2006,
        "historical IBES ticker to security bridge",
    ),
    "EarningsStreak": _requirement(
        "price-scaled IBES surprise retained only for consecutive same-sign surprises",
        "ibes_adjusted_fpi_6;actual;meanest;price;statpers;anndats_act",
        "available at actual announcement; forward-fill retained streak at most six months",
        1987,
        2009,
        "historical IBES ticker and adjustment identity",
    ),
    "EarningsSurprise": _requirement(
        "standardized current YoY epspxq change minus mean of lags 3..24 months",
        "compustat_epspxq;calendar_quarter_lags;sample_standard_deviation;price_filter",
        "quarterly fact available after filing; monthly signal without retrospective restatement",
        1974,
        1981,
        "historical GVKEY to security and share-class bridge",
    ),
    "EarnSupBig": _requirement(
        "same-industry mean EarningsSurprise of top 30 percent by market equity",
        "exact_EarningsSurprise;crsp_sic;ff48;mve_c;monthly_cross_section",
        "monthly contemporaneous industry-size cross section; large firms excluded",
        1972,
        2001,
        "historical GVKEY, PERMNO, SIC and share-class bridge",
    ),
    "ExclExp": _requirement(
        "IBES unadjusted actual int0a minus Compustat epspiq, clipped at 1/99 percentiles",
        "ibes_unadjusted_actual_int0a;compustat_epspiq;matched_fiscal_quarter",
        "annual June formation; twelve-month hold; causal matched announcements",
        1988,
        1999,
        "historical IBES ticker, GVKEY and PERMNO bridge",
    ),
    "FEPS": _requirement(
        "IBES unadjusted FY1 meanest",
        "ibes_unadjusted_eps_fpi_1;meanest;statpers;fpedats",
        "monthly latest eligible aggregate as of formation",
        1983,
        2002,
        "historical IBES ticker to security bridge",
    ),
    "ForecastDispersion": _requirement(
        "IBES cross-analyst stdev_est divided by abs(meanest)",
        "ibes_unadjusted_eps_fpi_1;stdev_est;meanest;statpers;fpedats",
        "monthly latest eligible aggregate; pinned Python code governs period filter",
        1976,
        2000,
        "historical IBES ticker to security bridge",
    ),
    "NumEarnIncrease": _requirement(
        "count consecutive positive four-quarter ibq changes, capped at eight",
        "compustat_ibq;exact_12m_change;calendar_3m_lags_through_24m",
        "quarterly fact available after filing; monthly signal",
        1987,
        2009,
        "historical GVKEY to security and share-class bridge",
    ),
    "PredictedFE": _requirement(
        "fitted forecast error from monthly cross-sectional OLS on lagged SG, BM, AOP and LTG ranks",
        "ibes_fy1_fy2_ltg;crsp_price_shares;compustat_fundamentals;"
        "full_cross_sectional_regression_inputs;historical_links",
        "June formation; twelve-month hold; regressors lagged twelve months",
        1979,
        1993,
        "historical IBES ticker, GVKEY and PERMNO bridge across the full cross section",
    ),
    "RevenueSurprise": _requirement(
        "standardized YoY change in revtq/cshprq net of mean lags 3..24 months",
        "compustat_revtq;compustat_cshprq;calendar_quarter_lags;sample_standard_deviation",
        "quarterly fact available after filing; monthly signal without later backfill",
        1987,
        2003,
        "historical GVKEY to security, share class and corporate-action bridge",
    ),
    "UpRecomm": _requirement(
        "1 when mean ireccd improves versus exact prior month, otherwise 0",
        "individual_analyst_id;broker_id;ireccd;anndats;recommendation_vintage",
        "last recommendation per analyst-firm-month; exact one-month lag",
        1985,
        1997,
        "vintage-specific IBES analyst, broker and firm identifiers",
    ),
    "fgr5yrLag": _requirement(
        "IBES LTG fpi=0 lagged exactly six calendar months",
        "ibes_ltg_fpi_0;compustat_ceq_ib_txdi_dv_sale_ni_dp;exact_6m_lag",
        "June observations expanded for twelve months after accounting nonmissing screen",
        1983,
        1990,
        "historical IBES ticker, GVKEY and PERMNO bridge",
    ),
    "sfe": _requirement(
        "March FY1 medest divided by prior December price for lower-half analyst coverage",
        "ibes_unadjusted_fpi_1;medest;numest;fpedats;statpers;crsp_dec_price;compustat_fye",
        "March formation; forecast horizon over ninety days; twelve-month hold",
        1982,
        1998,
        "historical IBES ticker, GVKEY and PERMNO bridge",
    ),
}


SOURCE_ASSESSMENTS = (
    {
        "source_id": "lseg_ibes_commercial",
        "access": "institutional_vendor_license",
        "history": "detailed and summary estimate, actual and recommendation vintages",
        "fields": "exact IBES estimates, dispersion, analysts, brokers and recommendations",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_and_vintage_specific_identity_required",
    },
    {
        "source_id": "alpha_vantage_free",
        "access": "free_key_25_calls_per_day",
        "history": "aggregate estimate and revision response; no individual IBES detail",
        "fields": "EPS and revenue aggregates, counts and revision summary",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "free_terms_classify_research_and_testing_as_commercial_use",
    },
    {
        "source_id": "fmp_basic",
        "access": "free_individual_account",
        "history": "five-year individual plan; endpoint entitlement varies",
        "fields": "financial estimates, grades and aggregate recommendations",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "derivative_works_require_prior_written_approval_and_history_is_short",
    },
    {
        "source_id": "twelve_data_basic",
        "access": "free_account_8_credits_per_minute_800_per_day",
        "history": "basic trial symbols; analysis and fundamentals require Grow or above",
        "fields": "free reference and market data; no free full analyst entitlement",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "analyst_analysis_not_entitled_on_free_basic_and_not_ibes_detail",
    },
    {
        "source_id": "nasdaq_zacks_premium",
        "access": "paid_subscription",
        "history": "Zacks point-in-time estimate and rating products",
        "fields": "earnings estimates and analyst ratings",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "nasdaq_data_link_classifies_zee_and_zar_as_premium",
    },
    {
        "source_id": "zacks_data_commercial",
        "access": "direct_or_wrds_license",
        "history": "annual EPS since 1979, quarterly since 1982, ratings since 1985",
        "fields": "point-in-time estimates, recommendations and individual contributors",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "pricing_and_license_require_direct_contact_or_wrds",
    },
    {
        "source_id": "intrinio_zacks_enterprise",
        "access": "enterprise_or_temporary_trial",
        "history": "20+ years for selected Zacks estimate products",
        "fields": "EPS, LTG, surprises and analyst ratings",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "enterprise_product_and_free_trial_is_not_permanent_free_access",
    },
    {
        "source_id": "sec_edgar_xbrl",
        "access": "public_api_and_bulk_download",
        "history": "XBRL generally since 2009-04-15; as-filed amendments preserved",
        "fields": "registrant-tagged financial statement facts and filing metadata",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "compustat_field_equivalence_and_historical_security_identity_unproven",
    },
    {
        "source_id": "simfin_free",
        "access": "free_account",
        "history": "five years delayed fundamentals on free tier",
        "fields": "standardized and as-reported fundamentals; no analyst vintages",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "history_too_short_and_no_ibes_estimate_or_recommendation_detail",
    },
    {
        "source_id": "compustat_commercial",
        "access": "institutional_vendor_license",
        "history": "long North American accounting history",
        "fields": "epspxq,epspiq,ibq,revtq,cshprq and other exact OpenAP fields",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_required",
    },
    {
        "source_id": "crsp_commercial",
        "access": "institutional_vendor_license",
        "history": "security master, returns, shares, SIC and delistings",
        "fields": "PERMNO, prices, shares, market equity and historical identity",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_required",
    },
)

_REQUIRED_DOCUMENTS = (
    "ibes",
    "alpha_vantage_docs",
    "alpha_vantage_terms",
    "fmp_docs",
    "fmp_pricing",
    "fmp_terms",
    "twelve_data_pricing",
    "twelve_data_analysis",
    "nasdaq_data_link",
    "zacks",
    "intrinio",
    "sec_api",
    "sec_fsd",
    "sec_reuse",
)
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def _visible_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(str(value))
    text = " ".join(parser.parts).lower()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    return " ".join(text.replace("\xa0", " ").split())


def _has_all(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def evaluate_analyst_source_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate primary-source contracts without treating access failure as approval."""

    errors = dict(access_errors or {})
    text = {name: _visible_text(documents.get(name, "")) for name in _REQUIRED_DOCUMENTS}
    blocked = sorted(name for name in _REQUIRED_DOCUMENTS if not text[name] and name in errors)
    unresolved = sorted(
        name for name in _REQUIRED_DOCUMENTS if not text[name] and name not in errors
    )

    ibes_benchmark = _has_all(text["ibes"], "ibes", "subscription")
    ibes_vintage_risk = _has_all(text["ibes"], "reassigned", "vintage")
    alpha_aggregate = _has_all(
        text["alpha_vantage_docs"], "earnings estimates", "revision history"
    )
    alpha_authorized = not _has_all(
        text["alpha_vantage_terms"], "research", "commercial use"
    )
    fmp_authorized = not (
        _has_all(text["fmp_terms"], "derivative works", "written approval")
        or _has_all(text["fmp_terms"], "personal use", "non-commercial")
    )
    twelve_free_analysis = not (
        "grow" in text["twelve_data_analysis"]
        and "basic" in text["twelve_data_pricing"]
    )
    nasdaq_premium = _has_all(
        text["nasdaq_data_link"], "zacks earnings estimates", "premium"
    ) and _has_all(text["nasdaq_data_link"], "zacks analyst ratings", "premium")
    sec_reuse = _has_all(text["sec_reuse"], "free", "reuse")
    sec_as_filed = _has_all(text["sec_fsd"], "4/15/2009", "as filed")

    checks = (
        ibes_benchmark,
        ibes_vintage_risk,
        alpha_aggregate,
        not alpha_authorized,
        _has_all(text["fmp_docs"], "financial estimates", "historical grades"),
        _has_all(text["fmp_pricing"], "basic", "free"),
        not fmp_authorized,
        not twelve_free_analysis,
        nasdaq_premium,
        bool(text["zacks"]),
        bool(text["intrinio"]),
        _has_all(text["sec_api"], "no authentication", "2009"),
        sec_reuse,
        sec_as_filed,
    )
    return {
        "official_documents_verified": not blocked and not unresolved and all(checks),
        "source_access_decision_complete": not unresolved,
        "access_blocked_documents": blocked,
        "access_errors": {name: errors[name] for name in blocked},
        "unresolved_documents": unresolved,
        "ibes_commercial_benchmark_verified": ibes_benchmark,
        "ibes_vintage_identity_risk_verified": ibes_vintage_risk,
        "alpha_vantage_aggregate_only": alpha_aggregate,
        "alpha_vantage_project_use_authorized": alpha_authorized,
        "fmp_project_use_authorized": fmp_authorized,
        "twelve_data_free_analysis_entitled": twelve_free_analysis,
        "nasdaq_zacks_premium_verified": nasdaq_premium,
        "sec_free_reuse_authorized": sec_reuse,
        "sec_as_filed_start": "2009-04-15" if sec_as_filed else "unverified",
        "sec_compustat_equivalence_proven": False,
        "exact_free_authorized_source_found": False,
        "strict_approved": 0,
    }


ANALYST_BLOCKERS = {
    "AOP": "analyst_source_blocked:ibes_fy1_fy2_ltg_vintages+crsp_compustat_fields+historical_links_unavailable_free",
    "AnalystRevision": "analyst_source_blocked:ibes_fy1_meanest_monthly_vintages_and_historical_link_unavailable_free",
    "ChangeInRecommendation": "analyst_source_blocked:individual_analyst_recommendation_vintages+analyst_broker_identity_unavailable_free",
    "ChForecastAccrual": "analyst_source_blocked:ibes_fy1_vintages+compustat_accrual_fields+historical_links_unavailable_free",
    "DownRecomm": "analyst_source_blocked:individual_analyst_recommendation_vintages+analyst_broker_identity_for_downgrades_unavailable_free",
    "EarningsForecastDisparity": "analyst_source_blocked:ibes_fy1_ltg_actual_vintages+fpedats_statpers_history_unavailable_free",
    "EarningsStreak": "analyst_source_blocked:ibes_adjusted_fpi6_forecast_actual_price_vintages_unavailable_free",
    "EarningsSurprise": "analyst_source_blocked:sec_xbrl_to_compustat_epspxq_equivalence+pre_2009_history+identity+coverage+fidelity_unverified",
    "EarnSupBig": "analyst_source_blocked:exact_earningssurprise+historical_sic_ff48_market_equity_cross_section_unavailable_free",
    "ExclExp": "analyst_source_blocked:ibes_unadjusted_actual_int0a+compustat_epspiq+historical_link_unavailable_free",
    "FEPS": "analyst_source_blocked:ibes_unadjusted_fy1_meanest_vintages_unavailable_free",
    "ForecastDispersion": "analyst_source_blocked:ibes_cross_analyst_stdev_meanest_vintages_unavailable_free",
    "NumEarnIncrease": "analyst_source_blocked:sec_xbrl_to_compustat_ibq_equivalence+calendar_lags+identity+coverage+fidelity_unverified",
    "PredictedFE": "analyst_source_blocked:ibes_crsp_compustat_full_cross_sectional_regression_inputs+historical_links_unavailable_free",
    "RevenueSurprise": "analyst_source_blocked:sec_xbrl_to_compustat_revtq_cshprq_equivalence+corporate_actions+identity+coverage+fidelity_unverified",
    "UpRecomm": "analyst_source_blocked:individual_analyst_recommendation_vintages+analyst_broker_identity_for_upgrades_unavailable_free",
    "fgr5yrLag": "analyst_source_blocked:ibes_ltg_vintages+compustat_nonmissing_screen+historical_links_unavailable_free",
    "sfe": "analyst_source_blocked:ibes_medest_numest_vintages+crsp_dec_price+compustat_fye_links_unavailable_free",
}


def build_analyst_batch_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build documentary evidence that can block, but never promote, this batch."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("exact_free_authorized_source_found") is False
        and probe.get("raw_source_data_downloaded") is False
        and probe.get("raw_files_in_artifact") is False
        and probe.get("locked_opened") is False
        and probe.get("validation_used_for_selection") is False
        and probe.get("strict_approved") == 0
        and str(evidence_run_url).startswith("https://")
        and bool(str(evidence_artifact).strip())
        and bool(_COMMIT_RE.fullmatch(str(implementation_commit)))
    )
    if not valid:
        raise ValueError("Invalid or incomplete analyst probe evidence")
    return pd.DataFrame(
        [
            {
                "signal": signal,
                "formula_implemented": True,
                "data_pipeline_implemented": False,
                "point_in_time_verified": False,
                "identity_verified": False,
                "coverage_measured": False,
                "fidelity_measured": False,
                "coverage_result": "not_measured",
                "fidelity_result": "not_measured",
                "strict_gate_result": "blocked",
                "blocking_reason": ANALYST_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(ANALYST_SIGNALS)
        ]
    )


def write_analyst_source_probe_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write documentary metadata only; never persist analyst or filing records."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_analyst_batch_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "analyst_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "analyst_source_assessment.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "signal": signal,
                "family": ANALYST_SIGNAL_FAMILIES[signal],
                **requirement,
                "formula_path": OPENAP_FORMULA_SOURCES[signal]["path"],
                "formula_sha256": OPENAP_FORMULA_SOURCES[signal]["sha256"],
                "formula_commit": OPENAP_COMMIT,
            }
            for signal, requirement in sorted(ANALYST_FORMULA_REQUIREMENTS.items())
        ]
    ).to_csv(output_dir / "analyst_formula_requirements.csv", index=False)
    evidence.to_csv(output_dir / "analyst_batch_evidence.csv", index=False)
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP analyst source probe",
            "",
            "- Eighteen pinned OpenAP formula contracts were verified by source hash.",
            "- I/B/E/S, CRSP and Compustat remain commercial exact benchmarks only.",
            "- Free analyst APIs expose aggregates, short histories, paid-only analysis, or incompatible licenses.",
            "- SEC is an authorized as-filed route from 2009 for four accounting formulas, but Compustat equivalence, identity, coverage and fidelity remain unproved.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No raw analyst, recommendation, market or filing records were downloaded or retained.",
            "- Strict approvals: 0. All eighteen signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "ANALYST_SOURCE_PROBE_REPORT.md").write_text(
        report, encoding="utf-8"
    )


__all__ = [
    "ANALYST_FORMULA_REQUIREMENTS",
    "ANALYST_SIGNAL_FAMILIES",
    "ANALYST_SIGNALS",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_SOURCES",
    "SOURCE_ASSESSMENTS",
    "build_analyst_batch_evidence",
    "evaluate_analyst_source_documents",
    "write_analyst_source_probe_outputs",
]
