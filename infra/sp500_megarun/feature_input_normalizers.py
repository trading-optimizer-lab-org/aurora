"""Causal train-only input panels for executable SP500 feature families."""

from __future__ import annotations

import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.feature_contract import apply_available_at_policy


class FeatureInputNormalizerError(ValueError):
    """Raised when an input panel is ambiguous, non-train or non-causal."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_VIX_PUBLIC_METHODOLOGY_START = pd.Timestamp("2003-09-22")
_SP500_CFTC_MARKETS = {
    "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
    "E-MINI S&P 500 STOCK INDEX - INTERNATIONAL MONETARY MARKET",
    "S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
    "S&P 500 STOCK INDEX - INTERNATIONAL MONETARY MARKET",
}
_TREASURY_SERIES: Mapping[str, str] = {
    "RIFLGFCM01_N.B": "yield_1m",
    "RIFLGFCM03_N.B": "yield_3m",
    "RIFLGFCM06_N.B": "yield_6m",
    "RIFLGFCY01_N.B": "yield_1y",
    "RIFLGFCY02_N.B": "yield_2y",
    "RIFLGFCY03_N.B": "yield_3y",
    "RIFLGFCY05_N.B": "yield_5y",
    "RIFLGFCY07_N.B": "yield_7y",
    "RIFLGFCY10_N.B": "yield_10y",
    "RIFLGFCY20_N.B": "yield_20y",
    "RIFLGFCY30_N.B": "yield_30y",
}
_CREDIT_SERIES: Mapping[str, str] = {
    "RIMLPAAAR_N.B": "aaa_yield",
    "RIMLPBAAR_N.B": "baa_yield",
}
_POLICY_RATE_SERIES = "RIFSPFF_N.B"
_MONETARY_LIQUIDITY_SERIES: Mapping[str, tuple[str, str]] = {
    "RESMO14A_N.WW": ("monetary_base", "h3_weekly"),
    "RESTR14A_N.WW": ("total_reserves", "h3_weekly"),
    "M2.WM": ("m2", "h6_weekly"),
}
_CREDIT_MONEY_SERIES: Mapping[str, tuple[str, str]] = {
    "B1001NCBA": ("bank_credit", "h8_weekly"),
    "B1020NCBA": ("loans_and_leases", "h8_weekly"),
    "M2.WM": ("m2", "h6_weekly"),
    "H1.DTBSPCK.M": ("commercial_paper", "cp_monthly_old"),
    "DTBSPCK_N.WW": ("commercial_paper", "cp_weekly_new"),
}
_COMMERCIAL_PAPER_RATE_SERIES: Mapping[str, str] = {
    "RIFSPPNAAD90_N.B": "aa_nonfinancial_90d",
    "RIFSPPNA2P2D90_N.B": "a2p2_nonfinancial_90d",
    "RIFSPPFAAD90_N.B": "aa_financial_90d",
}
_COMMERCIAL_PAPER_ISSUANCE_SERIES: Mapping[str, str] = {
    "MKT.1_4.MKT.AMT": "issuance_1_4_days",
    "MKT.5_9.MKT.AMT": "issuance_5_9_days",
}
_BANK_CREDIT_SERIES: Mapping[str, str] = {
    "B1001NCBA": "bank_credit",
    "B1002NCBA": "securities",
    "B1020NCBA": "loans",
    "B1023NCBA": "ci_loans",
    "B1026NCBA": "real_estate_loans",
    "B1029NCBA": "consumer_loans",
}
_MONEY_RESERVES_SERIES: Mapping[str, tuple[str, str]] = {
    "M1.WM": ("m1", "h6_weekly"),
    "M2.WM": ("m2", "h6_weekly"),
    "RESMO14A_N.WW": ("monetary_base", "h3_weekly"),
    "RESTR14A_N.WW": ("total_reserves", "h3_weekly"),
    "RESBR14A_N.WW": ("fed_borrowings", "h3_weekly"),
    "B1001NCBA": ("bank_credit", "h8_weekly"),
}
_CONSUMER_CREDIT_SERIES: Mapping[str, str] = {
    "DTCTL.M": "consumer_total",
    "DTCTLR.M": "consumer_revolving",
    "DTCTLN.M": "consumer_nonrevolving",
}
_SPF_REAL_RATE_SHEETS: Mapping[str, str] = {
    "RR1_TBILL_CPI": "real_rate_cpi",
    "RR1_TBILL_PCE": "real_rate_pce",
    "RR1_TBILL_PGDP": "real_rate_pgdp",
}
_MACRO_RELEASE_SERIES: Mapping[str, tuple[str, str]] = {
    "philly_cpi_first_releases": ("cpi", "monthly"),
    "philly_core_cpi_first_releases": ("core_cpi", "monthly"),
    "philly_core_pce_first_releases": ("core_pce", "quarterly"),
    "philly_payroll_first_releases": ("payroll", "monthly"),
    "philly_industrial_production_first_releases": (
        "industrial_production",
        "monthly",
    ),
    "philly_housing_starts_first_releases": ("housing_starts", "monthly"),
    "philly_real_output_first_releases": ("output", "quarterly"),
    "philly_real_consumption_first_releases": ("consumption", "quarterly"),
    "philly_nonresidential_investment_first_releases": (
        "nonresidential_investment",
        "quarterly",
    ),
    "philly_residential_investment_first_releases": (
        "residential_investment",
        "quarterly",
    ),
    "philly_manufacturing_production_first_releases": (
        "manufacturing_production",
        "monthly",
    ),
    "philly_capacity_utilization_first_releases": (
        "capacity_utilization",
        "monthly",
    ),
    "philly_manufacturing_capacity_first_releases": (
        "manufacturing_capacity",
        "monthly",
    ),
}
_REALTIME_MACRO_RESOURCES: Mapping[str, tuple[str, str, str | None]] = {
    "real_output_quarterly_vintages": ("output_growth", "growth", "output_revision"),
    "real_gdi_quarterly_vintages": ("gdi_growth", "growth", "gdi_revision"),
    "nominal_consumption_quarterly_vintages": (
        "nominal_consumption_growth",
        "growth",
        None,
    ),
    "nominal_disposable_income_quarterly_vintages": (
        "nominal_disposable_income_growth",
        "growth",
        None,
    ),
    "saving_rate_quarterly_vintages": ("saving_rate", "level", "saving_rate_revision"),
}
_SLOOS_SERIES: Mapping[str, str] = {
    "SUBLPDCILS_N.Q": "standards_large_mid",
    "SUBLPDCILD_N.Q": "demand_large_mid",
    "SUBLPDCISS_N.Q": "standards_small",
    "SUBLPDCISD_N.Q": "demand_small",
    "SUBLPDCILTC_N.Q": "term_credit_line_cost",
    "SUBLPDCILTL_N.Q": "term_covenants",
    "SUBLPDCILTM_N.Q": "term_maximum_size",
    "SUBLPDCILTQ_N.Q": "term_collateral",
    "SUBLPDCILTS_N.Q": "term_spreads",
}
_FX_SERIES: Mapping[str, str] = {
    "V0.JRXWTFB_N.B": "broad_dollar",
    "RXI_N.B.CA": "fx_cad",
    "RXI_N.B.JA": "fx_jpy",
    "RXI_N.B.SZ": "fx_chf",
    "RXI$US_N.B.UK": "fx_gbp",
    "RXI$US_N.B.AL": "fx_aud",
    "RXI$US_N.B.NZ": "fx_nzd",
    "RXI_N.B.DN": "fx_dkk",
    "RXI_N.B.NO": "fx_nok",
    "RXI_N.B.SD": "fx_sek",
}
_FX_RECIPROCAL_SERIES = frozenset({"RXI$US_N.B.UK", "RXI$US_N.B.AL", "RXI$US_N.B.NZ"})
_FX_REQUIRED_ASSETS = frozenset({"broad_dollar", "fx_cad", "fx_jpy", "fx_chf", "fx_gbp"})
_USD_FUNDING_SERIES: Mapping[str, str] = {
    "RIFLGFCM03_N.B": "treasury_3m",
    "RILSPDEPM03_N.B": "eurodollar_3m",
}
_WORLD_BANK_COMMODITY_COLUMNS: Mapping[str, str] = {
    "Crude oil, average": "crude_oil",
    "Coal, Australian": "coal",
    "Natural gas, US": "natural_gas",
    "Aluminum": "aluminum",
    "Iron ore, cfr spot": "iron_ore",
    "Copper": "copper",
    "Lead": "lead",
    "Tin": "tin",
    "Nickel": "nickel",
    "Zinc": "zinc",
    "Gold": "gold",
    "Platinum": "platinum",
    "Silver": "silver",
    "Cocoa": "cocoa",
    "Coffee, Arabica": "coffee_arabica",
    "Coffee, Robusta": "coffee_robusta",
    "Palm oil": "palm_oil",
    "Soybeans": "soybeans",
    "Maize": "maize",
    "Rice, Thai 5%": "rice",
    "Wheat, US SRW": "wheat",
    "Beef **": "beef",
    "Sugar, world": "sugar",
    "Cotton, A Index": "cotton",
    "Phosphate rock": "phosphate_rock",
    "DAP": "dap",
    "Urea": "urea",
    "Potassium chloride **": "potash",
}
_Z1_EQUITY_SERIES: Mapping[str, str] = {
    "FL153064105.Q": "household_corporate_equity",
    "FL154090005.Q": "household_financial_assets",
    "FL653064100.Q": "mutual_fund_corporate_equity",
    "FL654090000.Q": "mutual_fund_financial_assets",
}
_Z1_FINANCIAL_ACCOUNT_SERIES: Mapping[str, tuple[str, ...]] = {
    "household_equity": ("LM153064105.Q", "FL153064105.Q"),
    "household_financial_assets": ("FL154090005.Q",),
    "household_liabilities": ("FL154190005.Q",),
    "household_checkable": ("FL153020005.Q",),
    "household_time_deposits": ("FL153030005.Q",),
    "household_mmf": ("FL153034005.Q",),
    "corporate_financial_assets": ("FL104090005.Q",),
    "corporate_liabilities": ("FL104190005.Q",),
    "corporate_checkable": ("FL103020000.Q",),
    "corporate_time_deposits": ("FL103030003.Q",),
    "corporate_mmf": ("FL103034000.Q",),
    "corporate_debt": ("FL104122005.Q",),
    "corporate_net_issuance": ("FA103164105.Q",),
    "mutual_fund_total_assets": ("LM654090000.Q", "FL654090000.Q"),
    "mutual_fund_equity": ("LM653064100.Q", "FL653064100.Q"),
    "mutual_fund_flow": ("FA654090000.Q", "FU654090000.Q"),
    "etf_total_assets": ("LM564090005.Q", "FL564090005.Q"),
    "etf_equity": ("LM563064100.Q", "FL563064100.Q"),
    "etf_flow": ("FA564090005.Q", "FU564090005.Q"),
    "mmf_total_assets": ("FL634090005.Q",),
    "mmf_flow": ("FA634090005.Q", "FU634090005.Q"),
    "mmf_treasury": ("FL633061105.Q",),
    "mmf_commercial_paper": ("FL633069175.Q",),
    "broker_total_assets": ("FL664090005.Q",),
    "broker_liabilities": ("FL664190005.Q",),
    "broker_repo_assets": ("FL662051003.Q",),
    "broker_repo_liabilities": ("FL662151003.Q",),
    "foreign_treasury_purchases": ("FA263061105.Q",),
    "foreign_bond_purchases": ("FA263063005.Q",),
    "foreign_equity_purchases": ("FA263064105.Q",),
    "foreign_mutual_fund_purchases": ("FA263064203.Q",),
}


def _validated_dates(frame: pd.DataFrame, *, dataset_id: str) -> pd.DataFrame:
    if "date" not in frame:
        raise FeatureInputNormalizerError(f"DATE_COLUMN_MISSING:{dataset_id}")
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    if result["date"].isna().any():
        raise FeatureInputNormalizerError(f"INVALID_DATE:{dataset_id}")
    if result["date"].gt(_TRAIN_END).any():
        raise FeatureInputNormalizerError(f"NON_TRAIN_ROW:{dataset_id}")
    return result


def _fed_ddp_numeric(values: pd.Series) -> pd.Series:
    """Convert Federal Reserve DDP values while removing its -9999 sentinel."""

    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.mask(numeric.eq(-9999.0))


def _project_to_decision_session(
    frame: pd.DataFrame,
    *,
    policy: str,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    normalized_sessions = (
        pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().unique().sort_values()
    )
    if len(normalized_sessions) < 2:
        raise FeatureInputNormalizerError("INSUFFICIENT_TRAIN_SESSIONS")
    eligible = frame.copy()
    if policy == "next_session":
        eligible = eligible.loc[eligible["date"].lt(normalized_sessions.max())]
    elif policy == "two_calendar_days":
        eligible = eligible.loc[
            eligible["date"].add(pd.Timedelta(days=2)).le(normalized_sessions.max())
        ]
    elif policy == "friday_after_tuesday":
        eligible = eligible.loc[
            eligible["date"].add(pd.Timedelta(days=3)).le(normalized_sessions.max())
        ]
    elif policy == "h10_following_week_release_plus_session":
        following_monday = eligible["date"] + pd.to_timedelta(
            7 - eligible["date"].dt.weekday, unit="D"
        )
        eligible = eligible.loc[following_monday.lt(normalized_sessions.max())]
    elif policy == "next_month_third_session":
        target_month = eligible["date"] + pd.offsets.MonthBegin(1)
        eligible = eligible.loc[
            target_month.ge(normalized_sessions.min().to_period("M").to_timestamp())
            & target_month.le(normalized_sessions.max())
        ]
    elif policy == "second_month_tenth_session":
        target_month = eligible["date"] + pd.offsets.MonthBegin(2)
        eligible = eligible.loc[
            target_month.ge(normalized_sessions.min().to_period("M").to_timestamp())
            & target_month.le(normalized_sessions.max())
        ]
    if eligible.empty:
        raise FeatureInputNormalizerError(f"NO_PROJECTABLE_ROWS:{policy}")
    projected = apply_available_at_policy(
        eligible,
        policy=policy,
        sessions=normalized_sessions,
    )
    projected = (
        projected.sort_values(
            ["available_at", "observed_at"],
            kind="mergesort",
        )
        .drop_duplicates("available_at", keep="last")
        .reset_index(drop=True)
    )
    projected["date"] = projected["available_at"]
    return projected.sort_values("date", kind="mergesort").reset_index(drop=True)


def normalize_cboe_vol_panel(
    vix_frame: pd.DataFrame,
    vxo_frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Join official VIX and VXO closes and make them usable next session."""

    vix = _validated_dates(vix_frame, dataset_id="D_VIX")
    vxo = _validated_dates(vxo_frame, dataset_id="D_VXO")
    if "resource_id" in vix:
        vix = vix.loc[vix["resource_id"].astype(str).eq("vix_from_2003")]
    if "CLOSE" not in vix:
        raise FeatureInputNormalizerError("VIX_CLOSE_COLUMN_MISSING")
    vix_values = pd.DataFrame(
        {
            "date": vix["date"],
            "modern_vix_close": pd.to_numeric(vix["CLOSE"], errors="coerce"),
        }
    ).dropna(subset=["modern_vix_close"])
    vix_values = vix_values.loc[vix_values["date"].ge(_VIX_PUBLIC_METHODOLOGY_START)]

    old_close = (
        pd.to_numeric(vxo["4"], errors="coerce")
        if "4" in vxo
        else pd.Series(np.nan, index=vxo.index, dtype=float)
    )
    new_close = (
        pd.to_numeric(vxo["Unnamed: 4"], errors="coerce")
        if "Unnamed: 4" in vxo
        else pd.Series(np.nan, index=vxo.index, dtype=float)
    )
    vxo_values = pd.DataFrame(
        {
            "date": vxo["date"],
            "vxo_close": old_close.combine_first(new_close),
        }
    ).dropna(subset=["vxo_close"])
    panel = (
        vix_values.merge(vxo_values, on="date", how="outer", validate="one_to_one")
        .sort_values("date", kind="mergesort")
        .reset_index(drop=True)
    )
    # The official histories contain a handful of isolated blank observations.
    # Carry only already-published closes and cap the carry so a stale series
    # cannot silently bridge a prolonged source outage.
    panel[["modern_vix_close", "vxo_close"]] = panel[["modern_vix_close", "vxo_close"]].ffill(
        limit=5
    )
    panel["vix_close"] = panel["modern_vix_close"].where(
        panel["date"].ge(_VIX_PUBLIC_METHODOLOGY_START),
        panel["vxo_close"],
    )
    panel = panel.drop(columns="modern_vix_close")
    if panel[["vix_close", "vxo_close"]].dropna(how="all").empty:
        raise FeatureInputNormalizerError("EMPTY_CBOE_VOL_PANEL")
    return _project_to_decision_session(panel, policy="next_session", sessions=sessions)


def normalize_spy_decision_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Move each observed SPY close to the next available decision session."""

    spy = _validated_dates(frame, dataset_id="D_SPY")
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required - set(spy.columns))
    if missing:
        raise FeatureInputNormalizerError(f"SPY_COLUMNS_MISSING:{','.join(missing)}")
    return _project_to_decision_session(spy, policy="next_session", sessions=sessions)


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        raise FeatureInputNormalizerError(f"CFTC_COLUMN_MISSING:{column}")
    return pd.to_numeric(frame[column], errors="coerce")


def _optional_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _aggregate_cftc_mode(frame: pd.DataFrame, *, suffix: str) -> pd.DataFrame:
    numeric = pd.DataFrame(
        {
            "date": frame["date"],
            "open_interest": _numeric(frame, "Open Interest (All)"),
            "noncommercial_long": _numeric(frame, "Noncommercial Positions-Long (All)"),
            "noncommercial_short": _numeric(frame, "Noncommercial Positions-Short (All)"),
            "noncommercial_spreading": _optional_numeric(
                frame, "Noncommercial Positions-Spreading (All)"
            ),
            "reportable_short": _optional_numeric(frame, "Total Reportable Positions-Short (All)"),
            "commercial_long": _numeric(frame, "Commercial Positions-Long (All)"),
            "commercial_short": _numeric(frame, "Commercial Positions-Short (All)"),
            "trader_count": _optional_numeric(frame, "Traders-Total (All)"),
            "concentration_long": _numeric(frame, "Concentration-Net LT =4 TDR-Long (All)"),
            "concentration_short": _numeric(frame, "Concentration-Net LT =4 TDR-Short (All)"),
            "concentration8_long": _optional_numeric(
                frame, "Concentration-Net LT =8 TDR-Long (All)"
            ),
            "concentration8_short": _optional_numeric(
                frame, "Concentration-Net LT =8 TDR-Short (All)"
            ),
        }
    ).dropna(subset=["open_interest"])
    if numeric.empty:
        return pd.DataFrame()
    numeric["concentration_long_weighted"] = (
        numeric["concentration_long"] * numeric["open_interest"]
    )
    numeric["concentration_short_weighted"] = (
        numeric["concentration_short"] * numeric["open_interest"]
    )
    numeric["concentration8_long_weighted"] = (
        numeric["concentration8_long"] * numeric["open_interest"]
    )
    numeric["concentration8_short_weighted"] = (
        numeric["concentration8_short"] * numeric["open_interest"]
    )
    grouped = numeric.groupby("date", as_index=False, sort=True).sum(min_count=1)
    denominator = grouped["open_interest"].replace(0.0, np.nan)
    result = pd.DataFrame(
        {
            "date": grouped["date"],
            f"open_interest{suffix}": grouped["open_interest"],
            f"noncommercial_net_pct_oi{suffix}": (
                grouped["noncommercial_long"] - grouped["noncommercial_short"]
            )
            / denominator,
            f"commercial_net_pct_oi{suffix}": (
                grouped["commercial_long"] - grouped["commercial_short"]
            )
            / denominator,
            f"noncommercial_short_pct_oi{suffix}": grouped["noncommercial_short"] / denominator,
            f"noncommercial_spreading_pct_oi{suffix}": (
                grouped["noncommercial_spreading"] / denominator
            ),
            f"reportable_short_pct_oi{suffix}": grouped["reportable_short"] / denominator,
            f"trader_count{suffix}": grouped["trader_count"],
            f"top4_net_concentration{suffix}": (
                grouped["concentration_long_weighted"] - grouped["concentration_short_weighted"]
            )
            / denominator
            / 100.0,
            f"top8_net_concentration{suffix}": (
                grouped["concentration8_long_weighted"] - grouped["concentration8_short_weighted"]
            )
            / denominator
            / 100.0,
        }
    )
    return result


def normalize_cftc_sp500_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Aggregate only preregistered S&P 500 legacy contracts after Friday release."""

    cftc = _validated_dates(frame, dataset_id="D_CFTC")
    cftc.columns = [str(column).strip() for column in cftc.columns]
    if "Market and Exchange Names" not in cftc:
        raise FeatureInputNormalizerError("CFTC_MARKET_COLUMN_MISSING")
    market_names = cftc["Market and Exchange Names"].astype(str).str.strip().str.upper()
    selected = cftc.loc[market_names.isin(_SP500_CFTC_MARKETS)].copy()
    if selected.empty:
        raise FeatureInputNormalizerError("CFTC_SP500_CONTRACTS_MISSING")
    resource = selected.get("resource_id", pd.Series("", index=selected.index)).astype(str)
    futures = _aggregate_cftc_mode(
        selected.loc[resource.str.contains("futures_only", case=False)],
        suffix="",
    )
    combined = _aggregate_cftc_mode(
        selected.loc[~resource.str.contains("futures_only", case=False)],
        suffix="_combined",
    )
    if futures.empty and combined.empty:
        raise FeatureInputNormalizerError("EMPTY_CFTC_SP500_PANEL")
    if futures.empty:
        generic = combined.rename(
            columns={
                column: column.removesuffix("_combined")
                for column in combined.columns
                if column != "date"
            }
        )
        panel = generic.merge(combined, on="date", how="left")
    elif combined.empty:
        panel = futures
    else:
        panel = futures.merge(combined, on="date", how="outer", validate="one_to_one")
    return _project_to_decision_session(
        panel,
        policy="friday_after_tuesday",
        sessions=sessions,
    )


def normalize_cftc_cross_market_fallback_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build the frozen cross-market COT fallback after Friday publication."""

    cftc = _validated_dates(frame, dataset_id="D_CBOE_PCR")
    cftc.columns = [str(column).strip() for column in cftc.columns]
    required = {
        "Market and Exchange Names",
        "Open Interest (All)",
        "Commercial Positions-Long (All)",
        "Commercial Positions-Short (All)",
        "Noncommercial Positions-Long (All)",
        "Noncommercial Positions-Short (All)",
    }
    missing = sorted(required - set(cftc.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"CFTC_FALLBACK_COLUMNS_MISSING:{','.join(missing)}"
        )
    if "resource_id" in cftc:
        cftc = cftc.loc[
            cftc["resource_id"].astype(str).str.contains("futures_only", case=False)
        ].copy()
    if cftc.empty:
        raise FeatureInputNormalizerError("CFTC_FALLBACK_FUTURES_ONLY_MISSING")
    open_interest = _numeric(cftc, "Open Interest (All)").replace(0.0, np.nan)
    commercial = (
        _numeric(cftc, "Commercial Positions-Long (All)")
        - _numeric(cftc, "Commercial Positions-Short (All)")
    ) / open_interest
    noncommercial = (
        _numeric(cftc, "Noncommercial Positions-Long (All)")
        - _numeric(cftc, "Noncommercial Positions-Short (All)")
    ) / open_interest
    numeric = pd.DataFrame(
        {
            "date": cftc["date"],
            "market": cftc["Market and Exchange Names"].astype(str).str.strip(),
            "commercial": commercial,
            "noncommercial": noncommercial,
        }
    ).dropna()
    numeric = numeric.drop_duplicates(["date", "market"], keep="last")
    numeric["commercial_positive"] = numeric["commercial"].gt(0.0).astype(float)
    numeric["noncommercial_positive"] = numeric["noncommercial"].gt(0.0).astype(float)
    numeric["disagreement"] = (numeric["commercial"] - numeric["noncommercial"]).abs()
    grouped = numeric.groupby("date", as_index=False, sort=True).agg(
        commercial_breadth=("commercial_positive", "mean"),
        noncommercial_breadth=("noncommercial_positive", "mean"),
        positioning_disagreement=("disagreement", "mean"),
        commercial_dispersion=("commercial", lambda value: value.std(ddof=0)),
        market_count=("market", "nunique"),
    )
    grouped["commercial_breadth"] -= 0.5
    grouped["noncommercial_breadth"] -= 0.5
    grouped["breadth_gap"] = (
        grouped["commercial_breadth"] - grouped["noncommercial_breadth"]
    )
    if grouped.empty:
        raise FeatureInputNormalizerError("EMPTY_CFTC_CROSS_MARKET_FALLBACK")
    return _project_to_decision_session(
        grouped,
        policy="friday_after_tuesday",
        sessions=sessions,
    )


def normalize_treasury_curve_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Pivot official business-frequency Treasury constant-maturity yields."""

    rates = _validated_dates(frame, dataset_id="D_RATES")
    required = {"series_id", "value"}
    if not required <= set(rates.columns):
        raise FeatureInputNormalizerError("RATE_CURVE_COLUMNS_MISSING")
    selected = rates.loc[rates["series_id"].isin(_TREASURY_SERIES)].copy()
    selected["maturity"] = selected["series_id"].map(_TREASURY_SERIES)
    selected["value"] = _fed_ddp_numeric(selected["value"])
    selected = selected.dropna(subset=["maturity", "value"])
    if selected.empty:
        raise FeatureInputNormalizerError("TREASURY_CURVE_SERIES_MISSING")
    panel = selected.pivot_table(
        index="date",
        columns="maturity",
        values="value",
        aggfunc="last",
    ).reset_index()
    panel.columns.name = None
    value_columns = [column for column in panel if column != "date"]
    panel[value_columns] = panel[value_columns].ffill()
    return _project_to_decision_session(panel, policy="next_session", sessions=sessions)


def normalize_credit_spread_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Pivot official daily Moody's Aaa and Baa corporate yields."""

    rates = _validated_dates(frame, dataset_id="D_RATES")
    required = {"series_id", "value"}
    if not required <= set(rates.columns):
        raise FeatureInputNormalizerError("CREDIT_RATE_COLUMNS_MISSING")
    selected = rates.loc[rates["series_id"].isin(_CREDIT_SERIES)].copy()
    selected["credit_series"] = selected["series_id"].map(_CREDIT_SERIES)
    selected["value"] = _fed_ddp_numeric(selected["value"])
    selected = selected.dropna(subset=["credit_series", "value"])
    if selected.empty:
        raise FeatureInputNormalizerError("CREDIT_RATE_SERIES_MISSING")
    panel = selected.pivot_table(
        index="date",
        columns="credit_series",
        values="value",
        aggfunc="last",
    ).reset_index()
    panel.columns.name = None
    if not {"aaa_yield", "baa_yield"} <= set(panel.columns):
        raise FeatureInputNormalizerError("CREDIT_RATE_PAIR_INCOMPLETE")
    panel[["aaa_yield", "baa_yield"]] = panel[["aaa_yield", "baa_yield"]].ffill()
    panel = panel.dropna(subset=["aaa_yield", "baa_yield"])
    panel["baa_aaa_spread"] = panel["baa_yield"] - panel["aaa_yield"]
    return _project_to_decision_session(panel, policy="next_session", sessions=sessions)


def normalize_financial_conditions_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Make the derived daily conditions composite usable only next session."""

    conditions = _validated_dates(frame, dataset_id="D_FIN_COND")
    required = {
        "financial_conditions_score",
        "rate_level",
        "volatility_level",
    }
    missing = sorted(required - set(conditions.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"FINANCIAL_CONDITION_COLUMNS_MISSING:{','.join(missing)}"
        )
    for column in required:
        conditions[column] = pd.to_numeric(conditions[column], errors="coerce")
    conditions = conditions.dropna(subset=list(required))
    if conditions.empty:
        raise FeatureInputNormalizerError("EMPTY_FINANCIAL_CONDITIONS_PANEL")
    return _project_to_decision_session(
        conditions,
        policy="next_session",
        sessions=sessions,
    )


def normalize_uncertainty_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose the causal uncertainty composite only on the next session."""

    uncertainty = _validated_dates(frame, dataset_id="D_EPU")
    required = {
        "uncertainty_score",
        "volatility_level",
        "absolute_rate_change",
    }
    missing = sorted(required - set(uncertainty.columns))
    if missing:
        raise FeatureInputNormalizerError(f"UNCERTAINTY_COLUMNS_MISSING:{','.join(missing)}")
    for column in required:
        uncertainty[column] = pd.to_numeric(uncertainty[column], errors="coerce")
    uncertainty = uncertainty.dropna(subset=list(required))
    if uncertainty.empty:
        raise FeatureInputNormalizerError("EMPTY_UNCERTAINTY_PANEL")
    return _project_to_decision_session(
        uncertainty,
        policy="next_session",
        sessions=sessions,
    )


def normalize_philadelphia_realtime_growth_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Calculate the latest real-output growth known at each official vintage."""

    realtime = _validated_dates(frame, dataset_id="D_PHILLY_RT")
    required = {"observation_date", "value", "resource_id"}
    missing = sorted(required - set(realtime.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"PHILADELPHIA_REALTIME_COLUMNS_MISSING:{','.join(missing)}"
        )
    realtime = realtime.loc[
        realtime["resource_id"].astype(str).eq("real_output_monthly_vintages")
    ].copy()
    realtime["observation_date"] = pd.to_datetime(
        realtime["observation_date"], errors="coerce"
    ).dt.normalize()
    realtime["value"] = pd.to_numeric(realtime["value"], errors="coerce")
    realtime = realtime.dropna(subset=["observation_date", "value"])
    rows: list[dict[str, object]] = []
    for vintage_at, vintage in realtime.groupby("date", sort=True):
        history = (
            vintage.loc[vintage["observation_date"].le(vintage_at)]
            .sort_values("observation_date", kind="mergesort")
            .drop_duplicates("observation_date", keep="last")
        )
        if len(history) < 2:
            continue
        previous, latest = history.iloc[-2], history.iloc[-1]
        previous_value = float(previous["value"])
        latest_value = float(latest["value"])
        if previous_value <= 0.0:
            continue
        rows.append(
            {
                "date": vintage_at,
                "period_observed_at": latest["observation_date"],
                "realtime_output_growth": ((latest_value / previous_value) ** 4 - 1.0) * 100.0,
            }
        )
    if not rows:
        raise FeatureInputNormalizerError("EMPTY_PHILADELPHIA_REALTIME_GROWTH")
    projected = _project_to_decision_session(
        pd.DataFrame(rows),
        policy="next_session",
        sessions=sessions,
    )
    projected["observed_at"] = pd.to_datetime(
        projected.pop("period_observed_at"), errors="raise"
    ).dt.normalize()
    return projected


def _normalize_realtime_vintage_state(
    frame: pd.DataFrame,
    *,
    resource_id: str,
    value_names: tuple[str, ...],
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    selected = frame.loc[frame["resource_id"].astype(str).eq(resource_id)].copy()
    rows: list[dict[str, object]] = []
    for vintage_at, vintage in selected.groupby("date", sort=True):
        history = (
            vintage.loc[vintage["observation_date"].le(vintage_at)]
            .sort_values("observation_date", kind="mergesort")
            .drop_duplicates("observation_date", keep="last")
        )
        if len(history) < 2:
            continue
        previous, latest = history.iloc[-2], history.iloc[-1]
        previous_value = float(previous["value"])
        latest_value = float(latest["value"])
        row: dict[str, object] = {
            "date": vintage_at,
            "period_observed_at": latest["observation_date"],
        }
        if "realtime_output_growth" in value_names:
            if previous_value <= 0.0:
                continue
            row["realtime_output_growth"] = ((latest_value / previous_value) ** 4 - 1.0) * 100.0
        if "realtime_unemployment" in value_names:
            row["realtime_unemployment"] = latest_value
        if "unemployment_change" in value_names:
            row["unemployment_change"] = latest_value - previous_value
        rows.append(row)
    if not rows:
        raise FeatureInputNormalizerError(f"EMPTY_PHILADELPHIA_REALTIME_STATE:{resource_id}")
    projected = _project_to_decision_session(
        pd.DataFrame(rows),
        policy="next_session",
        sessions=sessions,
    )
    projected["observed_at"] = pd.to_datetime(
        projected.pop("period_observed_at"), errors="raise"
    ).dt.normalize()
    return projected


def normalize_philadelphia_realtime_cycle_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Combine vintage-known output growth and unemployment state."""

    realtime = _validated_dates(frame, dataset_id="D_PHILLY_RT")
    required = {"observation_date", "value", "resource_id"}
    missing = sorted(required - set(realtime.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"PHILADELPHIA_REALTIME_COLUMNS_MISSING:{','.join(missing)}"
        )
    realtime["observation_date"] = pd.to_datetime(
        realtime["observation_date"], errors="coerce"
    ).dt.normalize()
    realtime["value"] = pd.to_numeric(realtime["value"], errors="coerce")
    realtime = realtime.dropna(subset=["observation_date", "value"])

    output = _normalize_realtime_vintage_state(
        realtime,
        resource_id="real_output_monthly_vintages",
        value_names=("realtime_output_growth",),
        sessions=sessions,
    ).rename(columns={"observed_at": "output_observed_at"})
    unemployment = _normalize_realtime_vintage_state(
        realtime,
        resource_id="unemployment_quarterly_vintages",
        value_names=("realtime_unemployment", "unemployment_change"),
        sessions=sessions,
    ).rename(columns={"observed_at": "unemployment_observed_at"})

    dates = pd.DataFrame(
        {
            "date": pd.DatetimeIndex(output["date"].tolist() + unemployment["date"].tolist())
            .unique()
            .sort_values()
        }
    )
    result = pd.merge_asof(
        dates,
        output.drop(columns="available_at").sort_values("date"),
        on="date",
        direction="backward",
    )
    result = pd.merge_asof(
        result.sort_values("date"),
        unemployment.drop(columns="available_at").sort_values("date"),
        on="date",
        direction="backward",
    )
    required_values = {
        "realtime_output_growth",
        "realtime_unemployment",
        "unemployment_change",
    }
    result = result.dropna(subset=sorted(required_values))
    if result.empty:
        raise FeatureInputNormalizerError("EMPTY_PHILADELPHIA_REALTIME_CYCLE")
    result["observed_at"] = result[["output_observed_at", "unemployment_observed_at"]].max(axis=1)
    result["available_at"] = result["date"]
    return result.drop(columns=["output_observed_at", "unemployment_observed_at"]).reset_index(
        drop=True
    )


def _realtime_macro_resource_state(
    frame: pd.DataFrame,
    *,
    resource_id: str,
    value_name: str,
    transformation: str,
    revision_name: str | None,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    selected = frame.loc[frame["resource_id"].astype(str).eq(resource_id)].copy()
    if selected.empty:
        raise FeatureInputNormalizerError(f"REALTIME_MACRO_RESOURCE_MISSING:{resource_id}")
    rows: list[dict[str, object]] = []
    previous_history: pd.Series | None = None
    for vintage_at, vintage in selected.groupby("date", sort=True):
        history = (
            vintage.loc[vintage["observation_date"].le(vintage_at)]
            .sort_values("observation_date", kind="mergesort")
            .drop_duplicates("observation_date", keep="last")
            .set_index("observation_date")["value"]
        )
        if history.empty or (transformation == "growth" and len(history) < 2):
            previous_history = history
            continue
        latest_at = pd.Timestamp(history.index[-1]).normalize()
        latest = float(history.iloc[-1])
        if transformation == "growth":
            previous = float(history.iloc[-2])
            if previous <= 0.0 or latest <= 0.0:
                previous_history = history
                continue
            value = ((latest / previous) ** 4 - 1.0) * 100.0
        elif transformation == "level":
            value = latest
        else:  # pragma: no cover - closed mapping above
            raise FeatureInputNormalizerError(
                f"UNKNOWN_REALTIME_TRANSFORMATION:{resource_id}:{transformation}"
            )
        row: dict[str, object] = {
            "date": vintage_at,
            "period_observed_at": latest_at,
            value_name: value,
        }
        if value_name == "saving_rate":
            row["saving_rate_change"] = (
                latest - float(history.iloc[-2]) if len(history) >= 2 else np.nan
            )
        if revision_name is not None:
            revision = np.nan
            if previous_history is not None:
                common = history.index.intersection(previous_history.index)
                if len(common):
                    common_at = common.max()
                    revision = float(history.loc[common_at] - previous_history.loc[common_at])
            row[revision_name] = revision
        rows.append(row)
        previous_history = history
    if not rows:
        raise FeatureInputNormalizerError(f"EMPTY_REALTIME_MACRO_RESOURCE:{resource_id}")
    projected = _project_to_decision_session(
        pd.DataFrame(rows),
        policy="next_session",
        sessions=sessions,
    )
    projected["observed_at"] = pd.to_datetime(
        projected.pop("period_observed_at"), errors="raise"
    ).dt.normalize()
    return projected


def normalize_realtime_macro_vintage_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose output, GDI and household states only after each official vintage."""

    realtime = _validated_dates(frame, dataset_id="D_PHILLY_RT")
    required = {"observation_date", "value", "resource_id"}
    missing = sorted(required - set(realtime.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"REALTIME_MACRO_COLUMNS_MISSING:{','.join(missing)}"
        )
    realtime["observation_date"] = pd.to_datetime(
        realtime["observation_date"], errors="coerce"
    ).dt.normalize()
    realtime["value"] = pd.to_numeric(realtime["value"], errors="coerce")
    realtime = realtime.dropna(subset=["observation_date", "value"])
    states = {
        resource_id: _realtime_macro_resource_state(
            realtime,
            resource_id=resource_id,
            value_name=value_name,
            transformation=transformation,
            revision_name=revision_name,
            sessions=sessions,
        )
        for resource_id, (value_name, transformation, revision_name) in (
            _REALTIME_MACRO_RESOURCES.items()
        )
    }
    dates = pd.DataFrame(
        {
            "date": pd.DatetimeIndex(
                sorted({date for state in states.values() for date in state["date"]})
            )
        }
    )
    result = dates
    observed_columns: list[str] = []
    for resource_id, state in states.items():
        value_columns = [
            column
            for column in state
            if column not in {"date", "observed_at", "available_at"}
        ]
        observed_name = f"_{resource_id}_observed_at"
        observed_columns.append(observed_name)
        result = pd.merge_asof(
            result.sort_values("date"),
            state.drop(columns="available_at")
            .rename(columns={"observed_at": observed_name})
            .sort_values("date"),
            on="date",
            direction="backward",
        )
        if not value_columns:  # pragma: no cover - construction invariant
            raise FeatureInputNormalizerError(f"REALTIME_MACRO_VALUE_MISSING:{resource_id}")
    # Real GDI vintages begin only in 2005.  Do not truncate the otherwise
    # complete output and household histories merely because that optional
    # component was disseminated later.
    required_values = [
        "output_growth",
        "nominal_consumption_growth",
        "nominal_disposable_income_growth",
        "saving_rate",
    ]
    result = result.dropna(subset=required_values).reset_index(drop=True)
    if result.empty:
        raise FeatureInputNormalizerError("EMPTY_REALTIME_MACRO_PANEL")
    result["observed_at"] = result[observed_columns].max(axis=1)
    result["available_at"] = result["date"]
    return result.drop(columns=observed_columns)


def _spf_survey_periods(frame: pd.DataFrame) -> pd.Series:
    year = pd.to_numeric(frame["0"], errors="coerce")
    quarter = pd.to_numeric(frame["1"], errors="coerce")
    result = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    valid = year.notna() & quarter.between(1, 4)
    if valid.any():
        result.loc[valid] = pd.PeriodIndex(
            [
                f"{int(y)}Q{int(q)}"
                for y, q in zip(year.loc[valid], quarter.loc[valid], strict=True)
            ],
            freq="Q",
        ).to_timestamp()
    return result


def normalize_philadelphia_publication_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Count official real-time vintages and their breadth on each publication date."""

    realtime = _validated_dates(frame, dataset_id="D_PHILLY_RT")
    required = {"observation_date", "vintage_label", "resource_id"}
    missing = sorted(required - set(realtime.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"PHILADELPHIA_PUBLICATION_COLUMNS_MISSING:{','.join(missing)}"
        )
    realtime["observation_date"] = pd.to_datetime(
        realtime["observation_date"], errors="coerce"
    ).dt.normalize()
    realtime = realtime.dropna(
        subset=["observation_date", "vintage_label", "resource_id"]
    )
    rows: list[dict[str, object]] = []
    for publication_at, publication in realtime.groupby("date", sort=True):
        resources = publication["resource_id"].astype(str)
        latest_by_resource = publication.groupby("resource_id")[
            "observation_date"
        ].max()
        ages = (pd.Timestamp(publication_at) - latest_by_resource).dt.days
        rows.append(
            {
                "date": publication_at,
                "vintage_count": int(publication["vintage_label"].nunique()),
                "resource_breadth": int(resources.nunique()),
                "monthly_breadth": int(
                    resources.loc[resources.str.contains("monthly", case=False)].nunique()
                ),
                "quarterly_breadth": int(
                    resources.loc[resources.str.contains("quarterly", case=False)].nunique()
                ),
                "publication_point_count": int(len(publication)),
                "latest_observation_age_days": float(ages.mean()),
                "oldest_latest_observation_age_days": float(ages.max()),
            }
        )
    if not rows:
        raise FeatureInputNormalizerError("EMPTY_PHILADELPHIA_PUBLICATION_PANEL")
    return _project_to_decision_session(
        pd.DataFrame(rows),
        policy="next_session",
        sessions=sessions,
    )


def _annualized_quarter_growth(current: Any, previous: Any) -> float:
    current_value = float(current)
    previous_value = float(previous)
    if current_value <= 0.0 or previous_value <= 0.0:
        return np.nan
    return ((current_value / previous_value) ** 4 - 1.0) * 100.0


def normalize_spf_central_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose frozen SPF median nowcasts after a conservative quarter-end guard."""

    spf = _validated_dates(frame, dataset_id="D_SPF")
    required = {"source_sheet", "resource_id", "0", "1", "2", "3", "4"}
    missing = sorted(required - set(spf.columns))
    if missing:
        raise FeatureInputNormalizerError(f"SPF_CENTRAL_COLUMNS_MISSING:{','.join(missing)}")
    selected = spf.loc[spf["resource_id"].astype(str).eq("spf_median_level")].copy()
    selected["target_period"] = _spf_survey_periods(selected)
    for column in ("2", "3", "4"):
        selected[column] = pd.to_numeric(selected[column], errors="coerce")
    rows: list[dict[str, object]] = []
    forecasts_by_target: dict[pd.Timestamp, float] = {}
    for target_period, survey in selected.dropna(subset=["target_period"]).groupby(
        "target_period", sort=True
    ):
        by_sheet = survey.drop_duplicates("source_sheet", keep="last").set_index("source_sheet")
        if not {"RGDP", "UNEMP", "CPI", "HOUSING", "TBILL"} <= set(by_sheet.index):
            continue
        rgdp = by_sheet.loc["RGDP"]
        housing = by_sheet.loc["HOUSING"]
        output_nowcast = _annualized_quarter_growth(rgdp["3"], rgdp["2"])
        output_next = _annualized_quarter_growth(rgdp["4"], rgdp["3"])
        prior_forecast = forecasts_by_target.get(pd.Timestamp(target_period))
        forecasts_by_target[pd.Timestamp(target_period) + pd.DateOffset(months=3)] = output_next
        rows.append(
            {
                "observed_at": pd.Timestamp(target_period),
                "target_period": pd.Timestamp(target_period),
                "output_nowcast": output_nowcast,
                "output_next_forecast": output_next,
                "output_prior_forecast": prior_forecast,
                "output_forecast_revision": (
                    output_nowcast - prior_forecast if prior_forecast is not None else np.nan
                ),
                "unemployment_nowcast": float(by_sheet.loc["UNEMP", "3"]),
                "cpi_nowcast": float(by_sheet.loc["CPI", "3"]),
                "housing_nowcast": _annualized_quarter_growth(housing["3"], housing["2"]),
                "tbill_nowcast": float(by_sheet.loc["TBILL", "3"]),
            }
        )
    if not rows:
        raise FeatureInputNormalizerError("EMPTY_SPF_CENTRAL_PANEL")
    result = pd.DataFrame(rows)
    quarter_end = pd.to_datetime(result["target_period"]) + pd.offsets.QuarterEnd()
    result["date"] = _release_session(
        quarter_end,
        sessions=sessions,
        strictly_after=True,
    )
    result = result.dropna(subset=["date"]).sort_values("date", kind="mergesort")
    result["available_at"] = result["date"]
    return result.reset_index(drop=True)


def normalize_spf_disagreement_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose current-quarter SPF interquartile ranges after quarter end."""

    spf = _validated_dates(frame, dataset_id="D_SPF")
    required = {"source_sheet", "resource_id", "0", "3"}
    missing = sorted(required - set(spf.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"SPF_DISAGREEMENT_COLUMNS_MISSING:{','.join(missing)}"
        )
    selected = spf.loc[spf["resource_id"].astype(str).eq("spf_dispersion")].copy()
    labels = selected["0"].astype(str).str.strip().str.upper()
    valid = labels.str.fullmatch(r"\d{4}Q[1-4]")
    selected = selected.loc[valid].copy()
    selected["target_period"] = pd.PeriodIndex(labels.loc[valid], freq="Q").to_timestamp()
    selected["iqr"] = pd.to_numeric(selected["3"], errors="coerce")
    sheet_names = {
        "NGDP": "ngdp_iqr",
        "UNEMP": "unemployment_iqr",
        "CPI": "cpi_iqr",
        "HOUSING": "housing_iqr",
        "TBILL": "tbill_iqr",
    }
    selected = selected.loc[selected["source_sheet"].astype(str).isin(sheet_names)].copy()
    selected["value_name"] = selected["source_sheet"].astype(str).map(sheet_names)
    pivot = selected.pivot_table(
        index="target_period",
        columns="value_name",
        values="iqr",
        aggfunc="last",
    ).reset_index()
    required_values = list(sheet_names.values())
    pivot = pivot.dropna(subset=required_values)
    if pivot.empty:
        raise FeatureInputNormalizerError("EMPTY_SPF_DISAGREEMENT_PANEL")
    pivot["observed_at"] = pivot["target_period"]
    quarter_end = pd.to_datetime(pivot["target_period"]) + pd.offsets.QuarterEnd()
    pivot["date"] = _release_session(quarter_end, sessions=sessions, strictly_after=True)
    pivot = pivot.dropna(subset=["date"])
    pivot["available_at"] = pivot["date"]
    return pivot.loc[
        :, ["date", "observed_at", "available_at", "target_period", *required_values]
    ].reset_index(drop=True)


def normalize_spf_output_error_panel(
    spf_frame: pd.DataFrame,
    macro_frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Join an SPF output forecast to the later first release for the same quarter."""

    central = normalize_spf_central_panel(spf_frame, sessions=sessions)
    releases = normalize_macro_release_panel(macro_frame, sessions=sessions)
    releases = releases.loc[releases.get("output_first", pd.Series(dtype=float)).notna()].copy()
    if releases.empty:
        raise FeatureInputNormalizerError("SPF_OUTPUT_FIRST_RELEASE_MISSING")
    forecasts = central.loc[
        :,
        [
            "target_period",
            "output_nowcast",
            "output_prior_forecast",
            "output_forecast_revision",
        ],
    ]
    result = releases.merge(
        forecasts,
        left_on="observed_at",
        right_on="target_period",
        how="inner",
        validate="one_to_one",
    )
    if result.empty:
        raise FeatureInputNormalizerError("SPF_OUTPUT_TARGET_MATCH_MISSING")
    result["nowcast_signed_error"] = result["output_first"] - result["output_nowcast"]
    result["nowcast_absolute_error"] = result["nowcast_signed_error"].abs()
    result["prior_signed_error"] = result["output_first"] - result["output_prior_forecast"]
    result["prior_absolute_error"] = result["prior_signed_error"].abs()
    return result.loc[
        :,
        [
            "date",
            "observed_at",
            "available_at",
            "target_period",
            "output_first",
            "output_nowcast",
            "output_prior_forecast",
            "output_forecast_revision",
            "nowcast_signed_error",
            "nowcast_absolute_error",
            "prior_signed_error",
            "prior_absolute_error",
        ],
    ].reset_index(drop=True)


def normalize_sloos_credit_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose revised SLOOS history only after a conservative sixty-day guard."""

    sloos = _validated_dates(frame, dataset_id="D_SLOOS")
    if not {"series_id", "value"} <= set(sloos.columns):
        raise FeatureInputNormalizerError("SLOOS_COLUMNS_MISSING")
    selected = sloos.loc[sloos["series_id"].astype(str).isin(_SLOOS_SERIES)].copy()
    selected["value"] = _fed_ddp_numeric(selected["value"])
    selected["value_name"] = selected["series_id"].astype(str).map(_SLOOS_SERIES)
    pivot = selected.pivot_table(
        index="date",
        columns="value_name",
        values="value",
        aggfunc="last",
    ).reset_index()
    required_values = list(_SLOOS_SERIES.values())
    pivot = pivot.dropna(subset=required_values)
    if pivot.empty:
        raise FeatureInputNormalizerError("EMPTY_SLOOS_CREDIT_PANEL")
    pivot["observed_at"] = pivot["date"]
    pivot["date"] = _release_session(
        pivot["observed_at"] + pd.Timedelta(days=60),
        sessions=sessions,
    )
    pivot = pivot.dropna(subset=["date"]).sort_values("date", kind="mergesort")
    pivot["available_at"] = pivot["date"]
    return pivot.loc[
        :, ["date", "observed_at", "available_at", *required_values]
    ].reset_index(drop=True)


def _release_target(period: pd.Series, *, frequency: str, release_number: int) -> pd.Series:
    if frequency == "monthly":
        month_offset = release_number
    elif frequency == "quarterly":
        month_offset = release_number + 3
    else:  # pragma: no cover - closed mapping above
        raise FeatureInputNormalizerError(f"UNKNOWN_MACRO_FREQUENCY:{frequency}")
    return period + pd.offsets.MonthBegin(month_offset) + pd.Timedelta(days=14)


def _release_session(
    targets: pd.Series,
    *,
    sessions: pd.DatetimeIndex,
    strictly_after: bool = False,
) -> pd.Series:
    normalized_sessions = (
        pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().unique().sort_values()
    )
    positions = normalized_sessions.searchsorted(
        pd.to_datetime(targets).to_numpy(), side="right" if strictly_after else "left"
    )
    result = pd.Series(pd.NaT, index=targets.index, dtype="datetime64[ns]")
    normalized_targets = pd.to_datetime(targets)
    valid = (positions < len(normalized_sessions)) & normalized_targets.ge(
        normalized_sessions.min()
    ).to_numpy()
    if valid.any():
        result.loc[valid] = normalized_sessions.take(positions[valid]).to_numpy()
    return result


def _release_targets(observed: pd.Series, *, schedule: str) -> pd.Series:
    if schedule == "h3_weekly":
        return observed + pd.Timedelta(days=8)
    if schedule == "h6_weekly":
        return observed + pd.Timedelta(days=10)
    if schedule == "h8_weekly":
        return observed + pd.Timedelta(days=9)
    if schedule == "cp_weekly_new":
        return observed + pd.Timedelta(days=7)
    if schedule == "cp_monthly_old":
        return observed + pd.offsets.MonthBegin(2)
    if schedule == "cp_daily":
        return observed + pd.Timedelta(days=1)
    if schedule == "g19_monthly":
        return observed + pd.offsets.MonthBegin(2) + pd.Timedelta(days=7)
    raise FeatureInputNormalizerError(f"UNKNOWN_RELEASE_SCHEDULE:{schedule}")


def _project_release_series(
    frame: pd.DataFrame,
    *,
    series_id: str,
    value_name: str,
    schedule: str,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    selected = frame.loc[frame["series_id"].astype(str).eq(series_id)].copy()
    if selected.empty:
        return pd.DataFrame(columns=["date", "observed_at", "available_at", value_name])
    selected[value_name] = _fed_ddp_numeric(selected["value"])
    selected = selected.dropna(subset=[value_name])
    released = pd.DataFrame(
        {
            "observed_at": selected["date"],
            "date": _release_session(
                _release_targets(selected["date"], schedule=schedule),
                sessions=sessions,
                strictly_after=True,
            ),
            value_name: selected[value_name],
        }
    ).dropna(subset=["date", value_name])
    released = (
        released.sort_values(["date", "observed_at"], kind="mergesort")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    released["available_at"] = released["date"]
    return released


def _merge_release_states(
    states: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    missing = [name for name, state in states.items() if state.empty]
    if missing:
        raise FeatureInputNormalizerError(f"RELEASE_SERIES_MISSING:{','.join(sorted(missing))}")
    dates = pd.DatetimeIndex(sorted({date for state in states.values() for date in state["date"]}))
    result = pd.DataFrame({"date": dates})
    observed_columns: list[str] = []
    for value_name, state in states.items():
        observed_name = f"_{value_name}_observed_at"
        aligned = pd.merge_asof(
            result.loc[:, ["date"]],
            state.loc[:, ["date", "observed_at", value_name]].rename(
                columns={"observed_at": observed_name}
            ),
            on="date",
            direction="backward",
        )
        result[value_name] = aligned[value_name]
        result[observed_name] = aligned[observed_name]
        observed_columns.append(observed_name)
    result = result.dropna(subset=list(states)).reset_index(drop=True)
    result["observed_at"] = result[observed_columns].max(axis=1)
    result["available_at"] = result["date"]
    return result.drop(columns=observed_columns)


def _merge_release_states_allow_missing(
    states: Mapping[str, pd.DataFrame],
    *,
    required: tuple[str, ...],
) -> pd.DataFrame:
    """Merge released histories while requiring only the structural base series."""

    missing = [name for name in required if name not in states or states[name].empty]
    if missing:
        raise FeatureInputNormalizerError(f"RELEASE_SERIES_MISSING:{','.join(sorted(missing))}")
    dates = pd.DatetimeIndex(
        sorted({date for state in states.values() if not state.empty for date in state["date"]})
    )
    result = pd.DataFrame({"date": dates})
    observed_columns: list[str] = []
    for value_name, state in states.items():
        observed_name = f"_{value_name}_observed_at"
        observed_columns.append(observed_name)
        if state.empty:
            result[value_name] = np.nan
            result[observed_name] = pd.NaT
            continue
        aligned = pd.merge_asof(
            result.loc[:, ["date"]],
            state.loc[:, ["date", "observed_at", value_name]].rename(
                columns={"observed_at": observed_name}
            ),
            on="date",
            direction="backward",
        )
        result[value_name] = aligned[value_name]
        result[observed_name] = aligned[observed_name]
    result = result.dropna(subset=list(required)).reset_index(drop=True)
    result["observed_at"] = result[observed_columns].max(axis=1)
    result["available_at"] = result["date"]
    return result.drop(columns=observed_columns)


def normalize_policy_rate_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Project the official effective federal-funds rate to the next session."""

    rates = _validated_dates(frame, dataset_id="D_RATES")
    if not {"series_id", "value"} <= set(rates.columns):
        raise FeatureInputNormalizerError("POLICY_RATE_COLUMNS_MISSING")
    selected = rates.loc[
        rates["series_id"].astype(str).eq(_POLICY_RATE_SERIES),
        ["date", "value"],
    ].copy()
    selected["effective_fed_funds"] = _fed_ddp_numeric(selected.pop("value"))
    selected = selected.dropna(subset=["effective_fed_funds"])
    if selected.empty:
        raise FeatureInputNormalizerError("POLICY_RATE_SERIES_MISSING")
    return _project_to_decision_session(selected, policy="next_session", sessions=sessions)


def normalize_monetary_liquidity_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build H.3/H.6 liquidity states only after their conservative releases."""

    macro = _validated_dates(frame, dataset_id="D_MACRO_PIT")
    if not {"series_id", "value"} <= set(macro.columns):
        raise FeatureInputNormalizerError("MONETARY_LIQUIDITY_COLUMNS_MISSING")
    states = {
        value_name: _project_release_series(
            macro,
            series_id=series_id,
            value_name=value_name,
            schedule=schedule,
            sessions=sessions,
        )
        for series_id, (value_name, schedule) in _MONETARY_LIQUIDITY_SERIES.items()
    }
    return _merge_release_states(states)


def normalize_credit_money_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build causal H.8, H.6 and bridged commercial-paper balance sheets."""

    macro = _validated_dates(frame, dataset_id="D_MACRO_PIT")
    if not {"series_id", "value"} <= set(macro.columns):
        raise FeatureInputNormalizerError("CREDIT_MONEY_COLUMNS_MISSING")
    projected = {
        series_id: _project_release_series(
            macro,
            series_id=series_id,
            value_name=value_name,
            schedule=schedule,
            sessions=sessions,
        )
        for series_id, (value_name, schedule) in _CREDIT_MONEY_SERIES.items()
    }
    old_cp = projected["H1.DTBSPCK.M"]
    new_cp = projected["DTBSPCK_N.WW"]
    if not new_cp.empty:
        old_cp = old_cp.loc[old_cp["date"].lt(new_cp["date"].min())]
    cp_parts = [state for state in (old_cp, new_cp) if not state.empty]
    if cp_parts:
        commercial_paper = (
            pd.concat(cp_parts, ignore_index=True)
            .sort_values(["date", "observed_at"], kind="mergesort")
            .drop_duplicates("date", keep="last")
            .reset_index(drop=True)
        )
    else:
        commercial_paper = old_cp
    states = {
        "bank_credit": projected["B1001NCBA"],
        "loans_and_leases": projected["B1020NCBA"],
        "m2": projected["M2.WM"],
        "commercial_paper": commercial_paper,
    }
    return _merge_release_states(states)


def _append_optional_release_state(
    base: pd.DataFrame,
    optional: pd.DataFrame,
    *,
    value_name: str,
) -> pd.DataFrame:
    """Attach a shorter released history without truncating the base panel."""

    result = base.copy()
    if optional.empty:
        result[value_name] = np.nan
        return result
    aligned = pd.merge_asof(
        result.loc[:, ["date"]],
        optional.loc[:, ["date", "observed_at", value_name]].rename(
            columns={"observed_at": "_optional_observed_at"}
        ),
        on="date",
        direction="backward",
    )
    result[value_name] = aligned[value_name]
    result["observed_at"] = pd.concat(
        [result["observed_at"], aligned["_optional_observed_at"]], axis=1
    ).max(axis=1)
    return result


def normalize_commercial_paper_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build released CP rate, outstanding and optional issuance states."""

    macro = _validated_dates(frame, dataset_id="D_FED_CP")
    if not {"series_id", "value"} <= set(macro.columns):
        raise FeatureInputNormalizerError("COMMERCIAL_PAPER_COLUMNS_MISSING")
    projected_rates = {
        value_name: _project_release_series(
            macro,
            series_id=series_id,
            value_name=value_name,
            schedule="cp_daily",
            sessions=sessions,
        )
        for series_id, value_name in _COMMERCIAL_PAPER_RATE_SERIES.items()
    }
    old_outstanding = _project_release_series(
        macro,
        series_id="H1.DTBSPCK.M",
        value_name="cp_outstanding",
        schedule="cp_monthly_old",
        sessions=sessions,
    )
    new_outstanding = _project_release_series(
        macro,
        series_id="DTBSPCK_N.WW",
        value_name="cp_outstanding",
        schedule="cp_weekly_new",
        sessions=sessions,
    )
    if not new_outstanding.empty:
        old_outstanding = old_outstanding.loc[
            old_outstanding["date"].lt(new_outstanding["date"].min())
        ]
    outstanding_parts = [state for state in (old_outstanding, new_outstanding) if not state.empty]
    if not outstanding_parts:
        raise FeatureInputNormalizerError("COMMERCIAL_PAPER_OUTSTANDING_MISSING")
    outstanding = (
        pd.concat(outstanding_parts, ignore_index=True)
        .sort_values(["date", "observed_at"], kind="mergesort")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    issuance_parts = {
        value_name: _project_release_series(
            macro,
            series_id=series_id,
            value_name=value_name,
            schedule="cp_daily",
            sessions=sessions,
        )
        for series_id, value_name in _COMMERCIAL_PAPER_ISSUANCE_SERIES.items()
    }
    panel = _merge_release_states_allow_missing(
        {
            **projected_rates,
            "cp_outstanding": outstanding,
            **issuance_parts,
        },
        required=("cp_outstanding",),
    )
    issuance_columns = list(_COMMERCIAL_PAPER_ISSUANCE_SERIES.values())
    panel["issuance_amount"] = panel[issuance_columns].sum(axis=1, min_count=2)
    return panel.drop(columns=issuance_columns)


def normalize_bank_credit_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build the six frozen H.8 balance-sheet components after release."""

    macro = _validated_dates(frame, dataset_id="D_FED_H8")
    if not {"series_id", "value"} <= set(macro.columns):
        raise FeatureInputNormalizerError("BANK_CREDIT_COLUMNS_MISSING")
    return _merge_release_states(
        {
            value_name: _project_release_series(
                macro,
                series_id=series_id,
                value_name=value_name,
                schedule="h8_weekly",
                sessions=sessions,
            )
            for series_id, value_name in _BANK_CREDIT_SERIES.items()
        }
    )


def normalize_money_reserves_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Join H.3, H.6 and H.8 quantities after conservative release dates."""

    macro = _validated_dates(frame, dataset_id="D_FED_MONEY_RESERVES")
    if not {"series_id", "value"} <= set(macro.columns):
        raise FeatureInputNormalizerError("MONEY_RESERVES_COLUMNS_MISSING")
    return _merge_release_states(
        {
            value_name: _project_release_series(
                macro,
                series_id=series_id,
                value_name=value_name,
                schedule=schedule,
                sessions=sessions,
            )
            for series_id, (value_name, schedule) in _MONEY_RESERVES_SERIES.items()
        }
    )


def normalize_consumer_credit_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build G.19 total, revolving and nonrevolving credit after release."""

    macro = _validated_dates(frame, dataset_id="D_FED_G19")
    if not {"series_id", "value"} <= set(macro.columns):
        raise FeatureInputNormalizerError("CONSUMER_CREDIT_COLUMNS_MISSING")
    return _merge_release_states(
        {
            value_name: _project_release_series(
                macro,
                series_id=series_id,
                value_name=value_name,
                schedule="g19_monthly",
                sessions=sessions,
            )
            for series_id, value_name in _CONSUMER_CREDIT_SERIES.items()
        }
    )


def _spf_real_rate_state(
    frame: pd.DataFrame,
    *,
    sheet: str,
    value_name: str,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    selected = frame.loc[
        frame["source_sheet"].astype(str).eq(sheet)
        & frame["resource_id"].astype(str).eq("spf_median_level")
    ].copy()
    if selected.empty:
        return pd.DataFrame(columns=["date", "observed_at", "available_at", value_name])
    year = pd.to_numeric(selected["0"], errors="coerce")
    quarter = pd.to_numeric(selected["1"], errors="coerce")
    selected[value_name] = pd.to_numeric(selected["6"], errors="coerce")
    valid = year.notna() & quarter.between(1, 4) & selected[value_name].notna()
    selected = selected.loc[valid].copy()
    if selected.empty:
        return pd.DataFrame(columns=["date", "observed_at", "available_at", value_name])
    period = pd.PeriodIndex(
        [f"{int(y)}Q{int(q)}" for y, q in zip(year.loc[valid], quarter.loc[valid], strict=True)],
        freq="Q",
    )
    selected["observed_at"] = period.to_timestamp(how="end").normalize()
    selected["date"] = _release_session(
        selected["observed_at"], sessions=sessions, strictly_after=True
    )
    selected = selected.dropna(subset=["date", value_name])
    selected = (
        selected.sort_values(["date", "observed_at"], kind="mergesort")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    selected["available_at"] = selected["date"]
    return selected.loc[:, ["date", "observed_at", "available_at", value_name]]


def normalize_spf_real_rate_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose one-year-ahead SPF real T-bill medians after quarter end."""

    spf = _validated_dates(frame, dataset_id="D_SPF")
    required = {"source_sheet", "resource_id", "0", "1", "6"}
    missing = sorted(required - set(spf.columns))
    if missing:
        raise FeatureInputNormalizerError(f"SPF_REAL_RATE_COLUMNS_MISSING:{','.join(missing)}")
    states = {
        value_name: _spf_real_rate_state(
            spf,
            sheet=sheet,
            value_name=value_name,
            sessions=sessions,
        )
        for sheet, value_name in _SPF_REAL_RATE_SHEETS.items()
    }
    base = _merge_release_states(
        {
            "real_rate_cpi": states["real_rate_cpi"],
            "real_rate_pgdp": states["real_rate_pgdp"],
        }
    )
    return _append_optional_release_state(base, states["real_rate_pce"], value_name="real_rate_pce")


def normalize_macro_release_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Place each first and second release on its conservative official vintage date."""

    macro = _validated_dates(frame, dataset_id="D_MACRO_PIT")
    if "resource_id" not in macro or "1" not in macro:
        raise FeatureInputNormalizerError("MACRO_RELEASE_COLUMNS_MISSING")
    events: list[dict[str, object]] = []
    for resource_id, (name, frequency) in _MACRO_RELEASE_SERIES.items():
        selected = macro.loc[macro["resource_id"].astype(str).eq(resource_id)].copy()
        if selected.empty:
            continue
        for release_number, value_column in ((1, "1"), (2, "2")):
            if value_column not in selected:
                continue
            values = pd.to_numeric(selected[value_column], errors="coerce")
            first_values = pd.to_numeric(selected["1"], errors="coerce")
            targets = _release_target(
                selected["date"],
                frequency=frequency,
                release_number=release_number,
            )
            release_sessions = _release_session(targets, sessions=sessions)
            for index in selected.index[values.notna() & release_sessions.notna()]:
                event: dict[str, object] = {
                    "date": release_sessions.loc[index],
                    "observed_at": selected.loc[index, "date"],
                }
                if release_number == 1:
                    event[f"{name}_first"] = float(values.loc[index])
                elif first_values.notna().loc[index]:
                    event[f"{name}_revision"] = float(values.loc[index] - first_values.loc[index])
                events.append(event)
    if not events:
        raise FeatureInputNormalizerError("EMPTY_MACRO_RELEASE_PANEL")
    event_frame = pd.DataFrame(events).sort_values("date", kind="mergesort")
    value_columns = [
        column for column in event_frame.columns if column not in {"date", "observed_at"}
    ]
    grouped = event_frame.groupby("date", as_index=False, sort=True).agg(
        {
            "observed_at": "max",
            **{column: "last" for column in value_columns},
        }
    )
    grouped["available_at"] = grouped["date"]
    return grouped


def normalize_fomc_event_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Count public FOMC documents and make each event usable next session."""

    fomc = _validated_dates(frame, dataset_id="D_FOMC_PUBLIC")
    if "document_kind" not in fomc:
        raise FeatureInputNormalizerError("FOMC_DOCUMENT_KIND_MISSING")
    events = (
        fomc.groupby("date", as_index=False, sort=True)
        .size()
        .rename(columns={"size": "fomc_event_count"})
    )
    return _project_to_decision_session(
        events,
        policy="next_session",
        sessions=sessions,
    )


def _fomc_decision_date(date: pd.Timestamp, reference: object) -> pd.Timestamp:
    text = str(reference)
    match = re.search(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2}\s*[-\u2013]\s*"
        r"(\d{1,2})\s+Meeting\s*[-\u2013]\s*((?:19|20)\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return pd.Timestamp(date).normalize()
    return pd.Timestamp(f"{match.group(1)} {match.group(2)}, {match.group(3)}")


def normalize_fomc_decision_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Keep policy-decision events and expose them only on the next session."""

    fomc = _validated_dates(frame, dataset_id="D_FOMC_PUBLIC")
    required = {"document_kind", "document_reference"}
    missing = sorted(required - set(fomc.columns))
    if missing:
        raise FeatureInputNormalizerError(f"FOMC_DECISION_COLUMNS_MISSING:{','.join(missing)}")
    selected = fomc.loc[fomc["document_kind"].astype(str).isin(["meeting", "statement"])].copy()
    if selected.empty:
        raise FeatureInputNormalizerError("FOMC_DECISIONS_MISSING")
    selected["date"] = [
        _fomc_decision_date(date, reference)
        if kind == "meeting"
        else pd.Timestamp(date).normalize()
        for date, reference, kind in zip(
            selected["date"],
            selected["document_reference"],
            selected["document_kind"].astype(str),
            strict=True,
        )
    ]
    selected["meeting_count"] = selected["document_kind"].eq("meeting").astype(int)
    selected["statement_count"] = selected["document_kind"].eq("statement").astype(int)
    selected["conference_call"] = (
        selected["document_reference"]
        .astype(str)
        .str.contains("Conference Call", case=False, regex=False)
        .astype(int)
    )
    events = selected.groupby("date", as_index=False, sort=True).agg(
        meeting_count=("meeting_count", "sum"),
        statement_count=("statement_count", "sum"),
        conference_call=("conference_call", "max"),
    )
    return _project_to_decision_session(events, policy="next_session", sessions=sessions)


def normalize_fomc_publication_panels(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> Mapping[str, pd.DataFrame]:
    """Expose statement and minutes-release timing without pretending text exists."""

    fomc = _validated_dates(frame, dataset_id="D_FOMC_PUBLIC")
    required = {"document_kind", "document_reference"}
    missing = sorted(required - set(fomc.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"FOMC_PUBLICATION_COLUMNS_MISSING:{','.join(missing)}"
        )

    meetings = fomc.loc[fomc["document_kind"].astype(str).eq("meeting")].copy()
    meetings["date"] = [
        _fomc_decision_date(date, reference)
        for date, reference in zip(
            meetings["date"], meetings["document_reference"], strict=True
        )
    ]
    meeting_dates = (
        meetings.loc[:, ["date"]]
        .drop_duplicates()
        .sort_values("date", kind="mergesort")
        .rename(columns={"date": "decision_date"})
    )

    panels: dict[str, pd.DataFrame] = {}
    for output_name, kind in (
        ("statements", "statement"),
        ("minutes", "minutes_release"),
    ):
        selected = fomc.loc[
            fomc["document_kind"].astype(str).eq(kind), ["date"]
        ].copy()
        if selected.empty:
            raise FeatureInputNormalizerError(
                f"FOMC_PUBLICATION_KIND_MISSING:{kind}"
            )
        events = (
            selected.groupby("date", as_index=False, sort=True)
            .size()
            .rename(columns={"size": "event_count"})
        )
        events["gap_days"] = events["date"].diff().dt.days.astype(float)
        events["frequency_per_year"] = 365.25 / events["gap_days"].replace(0.0, np.nan)
        if output_name == "minutes":
            if meeting_dates.empty:
                raise FeatureInputNormalizerError("FOMC_MEETINGS_MISSING_FOR_MINUTES")
            events = pd.merge_asof(
                events.sort_values("date", kind="mergesort"),
                meeting_dates,
                left_on="date",
                right_on="decision_date",
                direction="backward",
            )
            events["decision_lag_days"] = (
                events["date"] - events["decision_date"]
            ).dt.days.astype(float)
            events = events.drop(columns="decision_date")
        panels[output_name] = _project_to_decision_session(
            events,
            policy="next_session",
            sessions=sessions,
        )
    return panels


def normalize_fomc_document_mix_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build the public FOMC event mix while excluding noncausal minutes dates."""

    fomc = _validated_dates(frame, dataset_id="D_FOMC_PUBLIC")
    required = {"document_kind", "document_reference"}
    missing = sorted(required - set(fomc.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"FOMC_DOCUMENT_MIX_COLUMNS_MISSING:{','.join(missing)}"
        )
    selected = fomc.loc[
        fomc["document_kind"].astype(str).isin(
            ["meeting", "statement", "minutes_release"]
        )
    ].copy()
    if selected.empty:
        raise FeatureInputNormalizerError("FOMC_DOCUMENT_MIX_MISSING")
    selected["date"] = [
        _fomc_decision_date(date, reference)
        if kind == "meeting"
        else pd.Timestamp(date).normalize()
        for date, reference, kind in zip(
            selected["date"],
            selected["document_reference"],
            selected["document_kind"].astype(str),
            strict=True,
        )
    ]
    for kind, column in (
        ("meeting", "meeting_count"),
        ("statement", "statement_count"),
        ("minutes_release", "minutes_release_count"),
    ):
        selected[column] = selected["document_kind"].eq(kind).astype(int)
    events = selected.groupby("date", as_index=False, sort=True).agg(
        meeting_count=("meeting_count", "sum"),
        statement_count=("statement_count", "sum"),
        minutes_release_count=("minutes_release_count", "sum"),
    )
    events["document_count"] = events[
        ["meeting_count", "statement_count", "minutes_release_count"]
    ].sum(axis=1)
    denominator = events["document_count"].replace(0, np.nan)
    shares: list[pd.Series] = []
    for column, share_name in (
        ("meeting_count", "meeting_share"),
        ("statement_count", "statement_share"),
        ("minutes_release_count", "minutes_release_share"),
    ):
        events[share_name] = events[column] / denominator
        shares.append(events[share_name])
    entropy_parts = [-(share.where(share.gt(0.0)) * np.log(share.where(share.gt(0.0)))) for share in shares]
    events["document_mix_entropy"] = pd.concat(entropy_parts, axis=1).sum(axis=1)
    events["publication_gap_days"] = events["date"].diff().dt.days.astype(float)
    return _project_to_decision_session(
        events,
        policy="next_session",
        sessions=sessions,
    )


def normalize_treasury_auction_results_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Aggregate common auction-result fields after the conservative record date."""

    auctions = _validated_dates(frame, dataset_id="D_TREASURY_AUCTIONS")
    required = {
        "offering_amt",
        "total_accepted",
        "total_tendered",
        "high_yield",
        "high_investment_rate",
        "high_discnt_rate",
        "issue_date",
        "maturity_date",
        "security_type",
        "reopening",
    }
    missing = sorted(required - set(auctions.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"TREASURY_AUCTION_COLUMNS_MISSING:{','.join(missing)}"
        )

    numeric_names = {
        "offering_amt": "offering_amount",
        "total_accepted": "accepted_amount",
        "total_tendered": "tendered_amount",
        "high_yield": "high_yield",
        "high_investment_rate": "high_investment_rate",
        "high_discnt_rate": "high_discount_rate",
    }
    for source, target in numeric_names.items():
        auctions[target] = pd.to_numeric(
            auctions[source].replace({"null": np.nan, "": np.nan}),
            errors="coerce",
        )
    auctions["issue_date"] = pd.to_datetime(auctions["issue_date"], errors="coerce")
    auctions["maturity_date"] = pd.to_datetime(
        auctions["maturity_date"], errors="coerce"
    )
    auctions["maturity_years"] = (
        (auctions["maturity_date"] - auctions["issue_date"]).dt.days / 365.25
    )
    auctions["clearing_rate"] = (
        auctions["high_yield"]
        .combine_first(auctions["high_investment_rate"])
        .combine_first(auctions["high_discount_rate"])
    )
    auctions = auctions.dropna(
        subset=[
            "offering_amount",
            "accepted_amount",
            "tendered_amount",
            "maturity_years",
        ]
    )
    auctions = auctions.loc[
        auctions["offering_amount"].gt(0.0)
        & auctions["accepted_amount"].gt(0.0)
        & auctions["tendered_amount"].ge(0.0)
        & auctions["maturity_years"].gt(0.0)
    ].copy()
    if auctions.empty:
        raise FeatureInputNormalizerError("EMPTY_TREASURY_AUCTION_PANEL")

    security = auctions["security_type"].astype(str).str.lower()
    offering = auctions["offering_amount"]
    accepted = auctions["accepted_amount"]
    auctions["clearing_rate_weighted"] = auctions["clearing_rate"] * accepted
    auctions["clearing_rate_weight"] = accepted.where(
        auctions["clearing_rate"].notna(), 0.0
    )
    auctions["maturity_weighted"] = auctions["maturity_years"] * offering
    auctions["bill_offering"] = offering.where(security.eq("bill"), 0.0)
    auctions["note_bond_offering"] = offering.where(
        security.isin(["note", "bond"]), 0.0
    )
    auctions["long_term_offering"] = offering.where(
        auctions["maturity_years"].ge(10.0), 0.0
    )
    auctions["reopening_offering"] = offering.where(
        auctions["reopening"].astype(str).str.lower().eq("yes"), 0.0
    )
    for kind in ("bill", "note", "bond"):
        auctions[f"{kind}_offering"] = offering.where(security.eq(kind), 0.0)

    grouped = auctions.groupby("date", as_index=False, sort=True).agg(
        auction_count=("offering_amount", "size"),
        offering_amount=("offering_amount", "sum"),
        accepted_amount=("accepted_amount", "sum"),
        tendered_amount=("tendered_amount", "sum"),
        clearing_rate_weighted=("clearing_rate_weighted", "sum"),
        clearing_rate_weight=("clearing_rate_weight", "sum"),
        maturity_weighted=("maturity_weighted", "sum"),
        bill_offering=("bill_offering", "sum"),
        note_bond_offering=("note_bond_offering", "sum"),
        long_term_offering=("long_term_offering", "sum"),
        reopening_offering=("reopening_offering", "sum"),
        note_offering=("note_offering", "sum"),
        bond_offering=("bond_offering", "sum"),
    )
    denominator = grouped["offering_amount"].replace(0.0, np.nan)
    grouped["acceptance_to_offer"] = grouped["accepted_amount"] / denominator
    grouped["bid_to_cover"] = grouped["tendered_amount"] / grouped[
        "accepted_amount"
    ].replace(0.0, np.nan)
    grouped["clearing_rate"] = grouped["clearing_rate_weighted"] / grouped[
        "clearing_rate_weight"
    ].replace(0.0, np.nan)
    grouped["weighted_maturity_years"] = grouped["maturity_weighted"] / denominator
    grouped["bill_share"] = grouped["bill_offering"] / denominator
    grouped["note_bond_share"] = grouped["note_bond_offering"] / denominator
    grouped["long_term_share"] = grouped["long_term_offering"] / denominator
    grouped["reopening_share"] = grouped["reopening_offering"] / denominator
    grouped["maturity_hhi"] = sum(
        (grouped[f"{kind}_offering"] / denominator).pow(2)
        for kind in ("bill", "note", "bond")
    )
    grouped = grouped.drop(
        columns=[
            "clearing_rate_weighted",
            "clearing_rate_weight",
            "maturity_weighted",
            "bill_offering",
            "note_bond_offering",
            "long_term_offering",
            "reopening_offering",
            "note_offering",
            "bond_offering",
        ]
    )
    return _project_to_decision_session(
        grouped,
        policy="next_session",
        sessions=sessions,
    )


def normalize_treasury_auction_announcement_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Aggregate only fields known by each official Treasury announcement date."""

    auctions = _validated_dates(frame, dataset_id="D_TREASURY_AUCTIONS")
    required = {
        "announcemt_date",
        "auction_date",
        "issue_date",
        "maturity_date",
        "security_type",
        "offering_amt",
    }
    missing = sorted(required - set(auctions.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"TREASURY_ANNOUNCEMENT_COLUMNS_MISSING:{','.join(missing)}"
        )
    for column in ("announcemt_date", "auction_date", "issue_date", "maturity_date"):
        auctions[column] = pd.to_datetime(auctions[column], errors="coerce").dt.normalize()
    auctions["offering_amount"] = pd.to_numeric(
        auctions["offering_amt"].replace({"null": np.nan, "": np.nan}),
        errors="coerce",
    )
    auctions["maturity_years"] = (
        (auctions["maturity_date"] - auctions["issue_date"]).dt.days / 365.25
    )
    auctions["announcement_to_auction_days"] = (
        auctions["auction_date"] - auctions["announcemt_date"]
    ).dt.days.astype(float)
    auctions = auctions.dropna(
        subset=[
            "announcemt_date",
            "auction_date",
            "offering_amount",
            "maturity_years",
            "announcement_to_auction_days",
        ]
    )
    auctions = auctions.loc[
        auctions["offering_amount"].gt(0.0)
        & auctions["maturity_years"].gt(0.0)
        & auctions["announcement_to_auction_days"].ge(0.0)
    ].copy()
    if auctions.empty:
        raise FeatureInputNormalizerError("EMPTY_TREASURY_ANNOUNCEMENT_PANEL")
    auctions["date"] = auctions["announcemt_date"]
    offering = auctions["offering_amount"]
    security = auctions["security_type"].astype(str).str.lower()
    auctions["maturity_weighted"] = auctions["maturity_years"] * offering
    auctions["lead_weighted"] = auctions["announcement_to_auction_days"] * offering
    for kind in ("bill", "note", "bond"):
        auctions[f"{kind}_offering"] = offering.where(security.eq(kind), 0.0)
    grouped = auctions.groupby("date", as_index=False, sort=True).agg(
        announcement_count=("offering_amount", "size"),
        announced_offering=("offering_amount", "sum"),
        maturity_weighted=("maturity_weighted", "sum"),
        lead_weighted=("lead_weighted", "sum"),
        bill_offering=("bill_offering", "sum"),
        note_offering=("note_offering", "sum"),
        bond_offering=("bond_offering", "sum"),
    )
    denominator = grouped["announced_offering"].replace(0.0, np.nan)
    grouped["weighted_maturity_years"] = grouped["maturity_weighted"] / denominator
    grouped["announcement_to_auction_days"] = grouped["lead_weighted"] / denominator
    grouped["maturity_hhi"] = sum(
        (grouped[f"{kind}_offering"] / denominator).pow(2)
        for kind in ("bill", "note", "bond")
    )
    grouped["bill_share"] = grouped["bill_offering"] / denominator
    grouped["note_bond_share"] = (
        grouped["note_offering"] + grouped["bond_offering"]
    ) / denominator
    grouped = grouped.drop(
        columns=[
            "maturity_weighted",
            "lead_weighted",
            "bill_offering",
            "note_offering",
            "bond_offering",
        ]
    )
    return _project_to_decision_session(
        grouped,
        policy="next_session",
        sessions=sessions,
    )


def normalize_federal_debt_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose daily federal debt totals and optional composition next session."""

    debt = _validated_dates(frame, dataset_id="D_TREASURY_FISCAL")
    required = {
        "tot_pub_debt_out_amt",
        "debt_held_public_amt",
        "intragov_hold_amt",
    }
    missing = sorted(required - set(debt.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"FEDERAL_DEBT_COLUMNS_MISSING:{','.join(missing)}"
        )
    result = pd.DataFrame(
        {
            "date": debt["date"],
            "total_debt": pd.to_numeric(
                debt["tot_pub_debt_out_amt"].replace({"null": np.nan, "": np.nan}),
                errors="coerce",
            ),
            "public_debt": pd.to_numeric(
                debt["debt_held_public_amt"].replace({"null": np.nan, "": np.nan}),
                errors="coerce",
            ),
            "intragov_debt": pd.to_numeric(
                debt["intragov_hold_amt"].replace({"null": np.nan, "": np.nan}),
                errors="coerce",
            ),
        }
    ).dropna(subset=["total_debt"])
    result = (
        result.sort_values("date", kind="mergesort")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    if result.empty:
        raise FeatureInputNormalizerError("EMPTY_FEDERAL_DEBT_PANEL")
    return _project_to_decision_session(
        result,
        policy="next_session",
        sessions=sessions,
    )


def normalize_lagged_valuation_panel(
    goyal_frame: pd.DataFrame,
    shiller_frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build a labelled proxy only after a full-year revision safety lag."""

    goyal = _validated_dates(goyal_frame, dataset_id="D_GOYAL")
    shiller = _validated_dates(shiller_frame, dataset_id="D_SHILLER")
    goyal_required = {"Index", "D12", "E12", "b/m", "ntis"}
    missing_goyal = sorted(goyal_required - set(goyal.columns))
    if missing_goyal:
        raise FeatureInputNormalizerError(f"GOYAL_COLUMNS_MISSING:{','.join(missing_goyal)}")
    if "12" not in shiller:
        raise FeatureInputNormalizerError("SHILLER_CAPE_COLUMN_MISSING")
    if "resource_id" in goyal:
        updated = goyal.loc[goyal["resource_id"].astype(str).eq("predictor_data_updated")].copy()
        if not updated.empty:
            goyal = updated
    goyal = goyal.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
    shiller = shiller.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
    selected = goyal.loc[:, ["date", *sorted(goyal_required)]].merge(
        shiller.loc[:, ["date", "12"]],
        on="date",
        how="inner",
        validate="one_to_one",
    )
    for column in (*goyal_required, "12"):
        selected[column] = pd.to_numeric(selected[column], errors="coerce")
    selected = selected.dropna(subset=[*goyal_required, "12"])
    index_level = selected["Index"].replace(0.0, np.nan)
    earnings = selected["E12"].replace(0.0, np.nan)
    cape = selected["12"].replace(0.0, np.nan)
    panel = pd.DataFrame(
        {
            "observed_at": selected["date"],
            "dividend_yield": selected["D12"] / index_level,
            "earnings_yield": selected["E12"] / index_level,
            "book_to_market": selected["b/m"],
            "inverse_cape": 1.0 / cape,
            "net_equity_issuance": selected["ntis"],
            "payout_ratio": selected["D12"] / earnings,
            "aggregate_earnings": selected["E12"],
            "aggregate_dividends": selected["D12"],
            "market_index": selected["Index"],
        }
    ).dropna()
    targets = panel["observed_at"] + pd.offsets.MonthBegin(13) + pd.Timedelta(days=14)
    panel["date"] = _release_session(targets, sessions=sessions)
    panel = panel.dropna(subset=["date"]).sort_values("date", kind="mergesort")
    if panel.empty:
        raise FeatureInputNormalizerError("EMPTY_LAGGED_VALUATION_PANEL")
    panel["available_at"] = panel["date"]
    return panel.reset_index(drop=True)


def normalize_lagged_goyal_issuance_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose Goyal aggregate net issuance after the full revision guard."""

    goyal = _validated_dates(frame, dataset_id="D_GOYAL")
    if "ntis" not in goyal:
        raise FeatureInputNormalizerError("GOYAL_NTIS_COLUMN_MISSING")
    if "resource_id" in goyal:
        updated = goyal.loc[goyal["resource_id"].astype(str).eq("predictor_data_updated")].copy()
        if not updated.empty:
            goyal = updated
    result = pd.DataFrame(
        {
            "observed_at": goyal["date"],
            "net_equity_issuance": pd.to_numeric(goyal["ntis"], errors="coerce"),
        }
    ).dropna(subset=["net_equity_issuance"])
    result = result.sort_values("observed_at", kind="mergesort").drop_duplicates(
        "observed_at", keep="last"
    )
    targets = result["observed_at"] + pd.offsets.MonthBegin(13) + pd.Timedelta(days=14)
    result["date"] = _release_session(targets, sessions=sessions)
    result = result.dropna(subset=["date"]).sort_values("date", kind="mergesort")
    if result.empty:
        raise FeatureInputNormalizerError("EMPTY_LAGGED_GOYAL_ISSUANCE_PANEL")
    result["available_at"] = result["date"]
    return result.reset_index(drop=True)


def normalize_fx_cross_asset_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose H.10 rows only after the following weekly release and next session."""

    fx = _validated_dates(frame, dataset_id="D_FX")
    required = {"series_id", "value"}
    missing = sorted(required - set(fx.columns))
    if missing:
        raise FeatureInputNormalizerError(f"FX_COLUMNS_MISSING:{','.join(missing)}")
    selected = fx.loc[fx["series_id"].isin(_FX_SERIES)].copy()
    selected["asset"] = selected["series_id"].map(_FX_SERIES)
    selected["value"] = _fed_ddp_numeric(selected["value"])
    selected["value"] = selected["value"].where(selected["value"].gt(0.0))
    reciprocal = selected["series_id"].isin(_FX_RECIPROCAL_SERIES)
    selected.loc[reciprocal, "value"] = 1.0 / selected.loc[reciprocal, "value"]
    selected = selected.dropna(subset=["asset", "value"])
    panel = (
        selected.pivot_table(index="date", columns="asset", values="value", aggfunc="last")
        .sort_index()
        .reset_index()
    )
    panel.columns.name = None
    missing_assets = sorted(_FX_REQUIRED_ASSETS - set(panel.columns))
    if missing_assets:
        raise FeatureInputNormalizerError(f"FX_FROZEN_SERIES_MISSING:{','.join(missing_assets)}")
    asset_columns = [asset for asset in _FX_SERIES.values() if asset in panel.columns]
    panel[asset_columns] = panel[asset_columns].ffill()
    panel = panel.dropna(subset=list(_FX_REQUIRED_ASSETS))
    return _project_to_decision_session(
        panel,
        policy="h10_following_week_release_plus_session",
        sessions=sessions,
    )


def normalize_usd_funding_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Prepare U.S. Treasury and offshore U.S.-dollar three-month rates."""

    rates = _validated_dates(frame, dataset_id="D_FED_H15_H10")
    required = {"series_id", "value"}
    missing = sorted(required - set(rates.columns))
    if missing:
        raise FeatureInputNormalizerError(f"USD_FUNDING_COLUMNS_MISSING:{','.join(missing)}")
    selected = rates.loc[rates["series_id"].isin(_USD_FUNDING_SERIES)].copy()
    selected["funding_series"] = selected["series_id"].map(_USD_FUNDING_SERIES)
    selected["value"] = _fed_ddp_numeric(selected["value"])
    selected = selected.dropna(subset=["funding_series", "value"])
    panel = selected.pivot_table(
        index="date",
        columns="funding_series",
        values="value",
        aggfunc="last",
    ).reset_index()
    panel.columns.name = None
    required_series = set(_USD_FUNDING_SERIES.values())
    missing_series = sorted(required_series - set(panel.columns))
    if missing_series:
        raise FeatureInputNormalizerError(f"USD_FUNDING_SERIES_MISSING:{','.join(missing_series)}")
    panel[list(required_series)] = panel[list(required_series)].ffill()
    panel = panel.dropna(subset=list(required_series))
    panel["offshore_basis"] = panel["eurodollar_3m"] - panel["treasury_3m"]
    return _project_to_decision_session(panel, policy="next_session", sessions=sessions)


def normalize_world_bank_commodity_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Parse the frozen monthly Pink Sheet panel and apply its release lag."""

    commodities = _validated_dates(frame, dataset_id="D_WORLD_BANK_COMMODITIES")
    available_raw = [column for column in _WORLD_BANK_COMMODITY_COLUMNS if column in commodities]
    if not available_raw:
        raise FeatureInputNormalizerError("WORLD_BANK_COMMODITY_COLUMNS_MISSING")
    numeric = commodities.loc[:, available_raw].apply(pd.to_numeric, errors="coerce")
    numeric = numeric.where(numeric.gt(0.0))
    available_raw = [column for column in available_raw if numeric[column].notna().any()]
    if len(available_raw) < 2:
        raise FeatureInputNormalizerError("INSUFFICIENT_WORLD_BANK_COMMODITIES")
    panel = pd.concat([commodities.loc[:, ["date"]], numeric.loc[:, available_raw]], axis=1).rename(
        columns=_WORLD_BANK_COMMODITY_COLUMNS
    )
    panel = panel.dropna(
        how="all",
        subset=[_WORLD_BANK_COMMODITY_COLUMNS[column] for column in available_raw],
    )
    return _project_to_decision_session(
        panel,
        policy="next_month_third_session",
        sessions=sessions,
    )


def normalize_cboe_vol_bundle_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Split the frozen Cboe bundle before applying the causal VIX bridge."""

    bundle = _validated_dates(frame, dataset_id="D_CBOE_VOL")
    if "source_dataset" not in bundle:
        raise FeatureInputNormalizerError("CBOE_VOL_SOURCE_DATASET_MISSING")
    source = bundle["source_dataset"].astype(str)
    vix = bundle.loc[source.eq("D_VIX")].copy()
    vxo = bundle.loc[source.eq("D_VXO")].copy()
    if vix.empty or vxo.empty:
        raise FeatureInputNormalizerError("CBOE_VOL_NATIVE_SOURCE_MISSING")
    return normalize_cboe_vol_panel(vix, vxo, sessions=sessions)


def normalize_world_bank_cross_asset_panel(
    gold_frame: pd.DataFrame,
    oil_frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Release monthly gold and oil only on the third train session next month."""

    gold = _validated_dates(gold_frame, dataset_id="D_GOLD")
    oil = _validated_dates(oil_frame, dataset_id="D_WTI")
    if "value" not in gold or "value" not in oil:
        raise FeatureInputNormalizerError("WORLD_BANK_VALUE_COLUMN_MISSING")
    gold_values = pd.DataFrame(
        {"date": gold["date"], "gold": pd.to_numeric(gold["value"], errors="coerce")}
    ).dropna(subset=["gold"])
    oil_values = pd.DataFrame(
        {"date": oil["date"], "oil": pd.to_numeric(oil["value"], errors="coerce")}
    ).dropna(subset=["oil"])
    panel = gold_values.merge(oil_values, on="date", how="inner", validate="one_to_one")
    if panel.empty:
        raise FeatureInputNormalizerError("EMPTY_WORLD_BANK_CROSS_ASSET_PANEL")
    return _project_to_decision_session(panel, policy="next_month_third_session", sessions=sessions)


def normalize_french_industry_panel(
    industry_frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Prepare only the 48-industry returns required by realized-correlation lanes."""

    industries = _validated_dates(industry_frame, dataset_id="D_FRENCH_INDUSTRIES")
    if "resource_id" in industries:
        industries = industries.loc[industries["resource_id"].astype(str).eq("industry_48_daily")]
    excluded = {"date", "resource_id", "source_dataset"}
    industry_columns = [column for column in industries.columns if column not in excluded]
    numeric = industries.loc[:, industry_columns].apply(pd.to_numeric, errors="coerce")
    numeric = numeric.mask(numeric.isin((-99.99, -999.0)))
    industry_columns = [column for column in industry_columns if numeric[column].notna().any()]
    if len(industry_columns) < 2:
        raise FeatureInputNormalizerError("FRENCH_INDUSTRY_COLUMNS_MISSING")
    industry_panel = pd.concat(
        (
            industries.loc[:, ["date"]].reset_index(drop=True),
            numeric.loc[:, industry_columns].reset_index(drop=True) / 100.0,
        ),
        axis=1,
    )
    industry_panel = industry_panel.dropna(how="all", subset=industry_columns)
    return _project_to_decision_session(industry_panel, policy="next_session", sessions=sessions)


def normalize_french_us_panels(
    factor_frame: pd.DataFrame,
    industry_frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Prepare broad-US factor and 48-industry returns for the next session."""

    factor_panel = normalize_french_factor_panel(factor_frame, sessions=sessions)
    industry_panel = normalize_french_industry_panel(industry_frame, sessions=sessions)
    return factor_panel, industry_panel


def normalize_french_factor_panel(
    factor_frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Prepare the broad-US daily FF3 factors without an industry dependency."""

    factors = _validated_dates(factor_frame, dataset_id="D_FRENCH_FACTORS")
    if "resource_id" in factors:
        factors = factors.loc[factors["resource_id"].astype(str).eq("ff3_daily")]
    factor_columns = {"Mkt-RF": "market_excess", "SMB": "smb", "HML": "hml"}
    missing_factors = sorted(set(factor_columns) - set(factors.columns))
    if missing_factors:
        raise FeatureInputNormalizerError(
            f"FRENCH_FACTOR_COLUMNS_MISSING:{','.join(missing_factors)}"
        )
    factor_panel = factors.loc[:, ["date", *factor_columns]].rename(columns=factor_columns)
    for column in factor_columns.values():
        factor_panel[column] = pd.to_numeric(factor_panel[column], errors="coerce") / 100.0
    factor_panel = factor_panel.dropna(subset=list(factor_columns.values()))
    return _project_to_decision_session(factor_panel, policy="next_session", sessions=sessions)


_FRENCH_CHARACTERISTIC_FREQUENCIES: Mapping[str, str] = {
    "size_daily": "daily",
    "book_to_market_daily": "daily",
    "profitability_daily": "daily",
    "investment_daily": "daily",
    "momentum_10_daily": "daily",
    "short_reversal_10_daily": "daily",
    "long_reversal_10_daily": "daily",
    "accruals_monthly": "monthly",
    "beta_monthly": "monthly",
    "net_share_issues_monthly": "monthly",
    "variance_monthly": "monthly",
    "residual_variance_monthly": "monthly",
}
_KNOWN_NON_CHARACTERISTIC_FRENCH_RESOURCES = {
    "ff3_daily",
    "industry_48_daily",
}
_FRENCH_GLOBAL_FACTOR_RESOURCES = (
    "developed_five_factors",
    "developed_ex_us",
    "europe",
    "japan",
    "asia_pacific_ex_japan",
)
_FRENCH_GLOBAL_MOMENTUM_RESOURCES = (
    "developed_momentum",
    "developed_ex_us_momentum",
    "europe_momentum",
    "japan_momentum",
    "asia_pacific_ex_japan_momentum",
)
_FRENCH_GLOBAL_RESOURCE_ORDER = (
    "developed_five_factors",
    "developed_momentum",
    "developed_ex_us",
    "europe",
    "japan",
    "asia_pacific_ex_japan",
    "developed_ex_us_momentum",
    "europe_momentum",
    "japan_momentum",
    "asia_pacific_ex_japan_momentum",
)


def normalize_french_characteristic_panels(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> Mapping[str, pd.DataFrame]:
    """Prepare every frozen U.S. characteristic portfolio at a causal session."""

    french = _validated_dates(frame, dataset_id="D_FRENCH_US")
    if "resource_id" not in french:
        raise FeatureInputNormalizerError("FRENCH_RESOURCE_ID_MISSING")
    resource_ids = set(french["resource_id"].dropna().astype(str))
    known = set(_FRENCH_CHARACTERISTIC_FREQUENCIES) | (_KNOWN_NON_CHARACTERISTIC_FRENCH_RESOURCES)
    unknown = sorted(resource_ids - known)
    if unknown:
        raise FeatureInputNormalizerError(
            f"UNKNOWN_FRENCH_CHARACTERISTIC_RESOURCE:{','.join(unknown)}"
        )

    metadata = {
        "date",
        "resource_id",
        "source_dataset",
        "source_file",
    }
    panels: dict[str, pd.DataFrame] = {}
    for resource_id, frequency in _FRENCH_CHARACTERISTIC_FREQUENCIES.items():
        selected = french.loc[french["resource_id"].astype(str).eq(resource_id)].copy()
        if selected.empty:
            continue
        numeric: dict[str, pd.Series] = {}
        for column in selected.columns:
            if str(column) in metadata:
                continue
            values = pd.to_numeric(selected[column], errors="coerce")
            values = values.mask(values.isin((-99.99, -999.0)))
            if values.notna().any():
                numeric[str(column)] = values / 100.0
        if len(numeric) < 2:
            raise FeatureInputNormalizerError(
                f"FRENCH_CHARACTERISTIC_COLUMNS_MISSING:{resource_id}"
            )
        panel = pd.DataFrame({"date": selected["date"], **numeric})
        panel = panel.dropna(how="all", subset=list(numeric))
        if frequency == "daily":
            policy = "next_session"
        else:
            panel["date"] = panel["date"] + pd.offsets.MonthEnd(0)
            policy = "second_month_tenth_session"
        panels[resource_id] = _project_to_decision_session(
            panel,
            policy=policy,
            sessions=sessions,
        )
    if not panels:
        raise FeatureInputNormalizerError("EMPTY_FRENCH_CHARACTERISTIC_PANELS")
    return panels


def normalize_french_global_factor_panels(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> Mapping[str, pd.DataFrame]:
    """Prepare frozen global and regional factor returns for the next session."""

    french = _validated_dates(frame, dataset_id="D_FRENCH_GLOBAL")
    if "resource_id" not in french:
        raise FeatureInputNormalizerError("FRENCH_GLOBAL_RESOURCE_ID_MISSING")
    resource_ids = set(french["resource_id"].dropna().astype(str))
    known = set(_FRENCH_GLOBAL_RESOURCE_ORDER)
    unknown = sorted(resource_ids - known)
    if unknown:
        raise FeatureInputNormalizerError(f"UNKNOWN_FRENCH_GLOBAL_RESOURCE:{','.join(unknown)}")

    factor_columns = {
        "Mkt-RF": "market_excess",
        "SMB": "size",
        "HML": "value",
        "RMW": "profitability",
        "CMA": "investment",
    }
    panels: dict[str, pd.DataFrame] = {}
    for resource_id in _FRENCH_GLOBAL_RESOURCE_ORDER:
        selected = french.loc[french["resource_id"].astype(str).eq(resource_id)].copy()
        if selected.empty:
            continue
        if resource_id in _FRENCH_GLOBAL_MOMENTUM_RESOURCES:
            required = {"WML": "momentum"}
        else:
            required = factor_columns
        missing = sorted(set(required) - set(selected.columns))
        if missing:
            raise FeatureInputNormalizerError(
                f"FRENCH_GLOBAL_COLUMNS_MISSING:{resource_id}:{','.join(missing)}"
            )
        panel = selected.loc[:, ["date", *required]].rename(columns=required)
        value_columns = list(required.values())
        for column in value_columns:
            values = pd.to_numeric(panel[column], errors="coerce")
            panel[column] = values.mask(values.isin((-99.99, -999.0))) / 100.0
        panel = panel.dropna(subset=value_columns)
        panels[resource_id] = _project_to_decision_session(
            panel,
            policy="next_session",
            sessions=sessions,
        )
    if not panels:
        raise FeatureInputNormalizerError("EMPTY_FRENCH_GLOBAL_PANELS")
    return panels


def normalize_revised_z1_equity_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build a Z.1 equity-allocation proxy after a 13-month revision guard."""

    z1 = _validated_dates(frame, dataset_id="D_Z1")
    required = {"series_id", "value"}
    missing = sorted(required - set(z1.columns))
    if missing:
        raise FeatureInputNormalizerError(f"Z1_COLUMNS_MISSING:{','.join(missing)}")
    selected = z1.loc[z1["series_id"].isin(_Z1_EQUITY_SERIES)].copy()
    selected["item"] = selected["series_id"].map(_Z1_EQUITY_SERIES)
    selected["value"] = pd.to_numeric(selected["value"], errors="coerce")
    panel = selected.pivot_table(
        index="date", columns="item", values="value", aggfunc="last"
    ).reset_index()
    panel.columns.name = None
    missing_items = sorted(set(_Z1_EQUITY_SERIES.values()) - set(panel.columns))
    if missing_items:
        raise FeatureInputNormalizerError(f"Z1_EQUITY_SERIES_MISSING:{','.join(missing_items)}")
    household_assets = panel["household_financial_assets"].replace(0.0, np.nan)
    mutual_assets = panel["mutual_fund_financial_assets"].replace(0.0, np.nan)
    result = pd.DataFrame(
        {
            "observed_at": panel["date"],
            "household_equity_share": panel["household_corporate_equity"] / household_assets,
            "mutual_fund_equity_share": panel["mutual_fund_corporate_equity"] / mutual_assets,
        }
    ).dropna()
    targets = result["observed_at"] + pd.offsets.MonthBegin(13) + pd.Timedelta(days=14)
    result["date"] = _release_session(targets, sessions=sessions)
    result = result.dropna(subset=["date"]).sort_values("date", kind="mergesort")
    if result.empty:
        raise FeatureInputNormalizerError("EMPTY_REVISED_Z1_EQUITY_PANEL")
    result["available_at"] = result["date"]
    return result.reset_index(drop=True)


def normalize_z1_corporate_issuance_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose official corporate-equity net issuance after a revision guard."""

    z1 = _validated_dates(frame, dataset_id="D_Z1")
    required = {"series_id", "value"}
    missing = sorted(required - set(z1.columns))
    if missing:
        raise FeatureInputNormalizerError(f"Z1_COLUMNS_MISSING:{','.join(missing)}")
    selected = z1.loc[z1["series_id"].astype(str).eq("FA103164105.Q")].copy()
    selected["corporate_equity_net_issuance"] = pd.to_numeric(selected["value"], errors="coerce")
    result = selected.loc[:, ["date", "corporate_equity_net_issuance"]].dropna(
        subset=["corporate_equity_net_issuance"]
    )
    if result.empty:
        raise FeatureInputNormalizerError("Z1_CORPORATE_ISSUANCE_SERIES_MISSING")
    result = result.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
    result = result.rename(columns={"date": "observed_at"})
    targets = result["observed_at"] + pd.offsets.MonthBegin(13) + pd.Timedelta(days=14)
    result["date"] = _release_session(targets, sessions=sessions)
    result = result.dropna(subset=["date"]).sort_values("date", kind="mergesort")
    if result.empty:
        raise FeatureInputNormalizerError("EMPTY_Z1_CORPORATE_ISSUANCE_PANEL")
    result["available_at"] = result["date"]
    return result.reset_index(drop=True)


def normalize_revised_z1_financial_accounts_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose frozen Z.1 sector balances only after the 13-month revision guard."""

    z1 = _validated_dates(frame, dataset_id="D_Z1")
    required = {"series_id", "value"}
    missing = sorted(required - set(z1.columns))
    if missing:
        raise FeatureInputNormalizerError(f"Z1_COLUMNS_MISSING:{','.join(missing)}")
    z1["series_id"] = z1["series_id"].astype(str)
    present = set(z1["series_id"])
    pieces: list[pd.DataFrame] = []
    missing_items: list[str] = []
    for item, candidates in _Z1_FINANCIAL_ACCOUNT_SERIES.items():
        selected_id = next((candidate for candidate in candidates if candidate in present), None)
        if selected_id is None:
            missing_items.append(item)
            continue
        selected = z1.loc[
            z1["series_id"].eq(selected_id), ["date", "value"]
        ].copy()
        selected["item"] = item
        selected["value"] = _fed_ddp_numeric(selected["value"])
        pieces.append(selected)
    if missing_items:
        raise FeatureInputNormalizerError(
            f"Z1_FINANCIAL_ACCOUNT_SERIES_MISSING:{','.join(sorted(missing_items))}"
        )
    combined = pd.concat(pieces, ignore_index=True)
    panel = combined.pivot_table(
        index="date", columns="item", values="value", aggfunc="last"
    ).reset_index()
    panel.columns.name = None
    value_columns = list(_Z1_FINANCIAL_ACCOUNT_SERIES)
    panel = panel.dropna(subset=value_columns, how="all")
    panel = panel.sort_values("date", kind="mergesort").rename(
        columns={"date": "observed_at"}
    )
    targets = panel["observed_at"] + pd.offsets.MonthBegin(13) + pd.Timedelta(days=14)
    panel["date"] = _release_session(targets, sessions=sessions)
    panel = panel.dropna(subset=["date"]).sort_values("date", kind="mergesort")
    if panel.empty:
        raise FeatureInputNormalizerError("EMPTY_REVISED_Z1_FINANCIAL_ACCOUNTS_PANEL")
    panel["available_at"] = panel["date"]
    return panel.loc[
        :, ["date", "observed_at", "available_at", *value_columns]
    ].reset_index(drop=True)


def normalize_tic_foreign_flow_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Expose Treasury and equity TIC purchases after a conservative release lag."""

    tic = _validated_dates(frame, dataset_id="D_TIC")
    required = {"resource_id", "total_net_purchases", "foreign_official"}
    missing = sorted(required - set(tic.columns))
    if missing:
        raise FeatureInputNormalizerError(f"TIC_COLUMNS_MISSING:{','.join(missing)}")
    resources = {
        "tic_treasury_sector": ("tic_treasury_net_purchases", "tic_treasury_official"),
        "tic_equity_sector": ("tic_equity_net_purchases", "tic_equity_official"),
    }
    pieces: list[pd.DataFrame] = []
    for resource_id, (total_name, official_name) in resources.items():
        selected = tic.loc[tic["resource_id"].astype(str).eq(resource_id)].copy()
        if selected.empty:
            raise FeatureInputNormalizerError(f"TIC_RESOURCE_MISSING:{resource_id}")
        selected[total_name] = pd.to_numeric(
            selected["total_net_purchases"], errors="coerce"
        )
        selected[official_name] = pd.to_numeric(
            selected["foreign_official"], errors="coerce"
        )
        pieces.append(selected.loc[:, ["date", total_name, official_name]])
    panel = pieces[0].merge(pieces[1], on="date", how="inner", validate="one_to_one")
    panel = panel.dropna().sort_values("date", kind="mergesort")
    if panel.empty:
        raise FeatureInputNormalizerError("EMPTY_TIC_FOREIGN_FLOW_PANEL")
    return _project_to_decision_session(
        panel,
        policy="second_month_tenth_session",
        sessions=sessions,
    )


def normalize_finra_margin_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Publish FINRA monthly debit and credit balances with the frozen safety lag."""

    margin = _validated_dates(frame, dataset_id="D_FINRA_MARGIN")
    debit_column = "Debit Balances in Customers' Securities Margin Accounts"
    cash_column = "Free Credit Balances in Customers' Cash Accounts"
    securities_column = "Free Credit Balances in Customers' Securities Margin Accounts"
    missing = sorted({debit_column, cash_column} - set(margin.columns))
    if missing:
        raise FeatureInputNormalizerError(f"FINRA_MARGIN_COLUMNS_MISSING:{','.join(missing)}")
    debit = pd.to_numeric(margin[debit_column], errors="coerce")
    cash = pd.to_numeric(margin[cash_column], errors="coerce")
    if securities_column in margin:
        securities = pd.to_numeric(margin[securities_column], errors="coerce").fillna(0.0)
    else:
        securities = pd.Series(0.0, index=margin.index)
    credit = (cash + securities).replace(0.0, np.nan)
    panel = pd.DataFrame(
        {
            "date": margin["date"],
            "margin_debit": debit,
            "margin_credit": credit,
            "margin_debit_to_credit": debit / credit,
        }
    ).dropna()
    return _project_to_decision_session(
        panel, policy="second_month_tenth_session", sessions=sessions
    )


def normalize_noaa_ny_weather_panel(
    frame: pd.DataFrame,
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Clean LaGuardia GSOD fields and enforce the frozen two-day delay."""

    weather = _validated_dates(frame, dataset_id="D_NOAA_NY")
    required = {
        "TEMP",
        "DEWP",
        "SLP",
        "VISIB",
        "WDSP",
        "MXSPD",
        "GUST",
        "MAX",
        "MIN",
        "PRCP",
        "SNDP",
        "FRSHTT",
    }
    missing = sorted(required - set(weather.columns))
    if missing:
        raise FeatureInputNormalizerError(
            f"NOAA_WEATHER_COLUMNS_MISSING:{','.join(missing)}"
        )
    numeric_specs = {
        "TEMP": ("temperature", 999.0),
        "DEWP": ("dewpoint", 999.0),
        "SLP": ("sea_level_pressure", 9999.0),
        "VISIB": ("visibility", 999.0),
        "WDSP": ("wind_speed", 999.0),
        "MXSPD": ("maximum_wind_speed", 999.0),
        "GUST": ("gust", 999.0),
        "MAX": ("maximum_temperature", 999.0),
        "MIN": ("minimum_temperature", 999.0),
        "PRCP": ("precipitation", 99.0),
        "SNDP": ("snow_depth", 999.0),
    }
    panel = pd.DataFrame({"date": weather["date"]})
    for source, (target, sentinel_floor) in numeric_specs.items():
        values = pd.to_numeric(weather[source], errors="coerce")
        panel[target] = values.mask(values.ge(sentinel_floor))
    flags = (
        weather["FRSHTT"]
        .fillna(0)
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
        .str[-6:]
    )
    for position, name in enumerate(("fog", "rain", "snow_ice", "hail", "thunder", "tornado")):
        panel[name] = pd.to_numeric(flags.str[position], errors="coerce").fillna(0).astype(int)
    panel = panel.sort_values("date", kind="mergesort").drop_duplicates(
        "date", keep="last"
    )
    return _project_to_decision_session(
        panel,
        policy="two_calendar_days",
        sessions=sessions,
    )


def normalize_calendar_state_panel(
    *,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Describe each bounded train session using only deterministic calendar facts."""

    dates = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().unique().sort_values()
    dates = dates[dates <= _TRAIN_END]
    if dates.empty:
        raise FeatureInputNormalizerError("EMPTY_TRAIN_CALENDAR")
    frame = pd.DataFrame({"date": dates})
    groups = frame.groupby([frame["date"].dt.year, frame["date"].dt.month], sort=False)
    frame["weekday"] = frame["date"].dt.weekday
    frame["month"] = frame["date"].dt.month
    frame["quarter"] = frame["date"].dt.quarter
    frame["session_of_month"] = groups.cumcount() + 1
    frame["sessions_remaining_month"] = groups.cumcount(ascending=False)
    expiry_dates: list[pd.Timestamp] = []
    for period in pd.PeriodIndex(dates, freq="M").unique():
        month_start = period.start_time.normalize()
        first_friday = month_start + pd.Timedelta(days=(4 - month_start.weekday()) % 7)
        third_friday = first_friday + pd.Timedelta(days=14)
        month_sessions = dates[(dates.year == period.year) & (dates.month == period.month)]
        eligible = month_sessions[month_sessions <= third_friday]
        if len(eligible):
            expiry_dates.append(pd.Timestamp(eligible[-1]))
    expiries = pd.DatetimeIndex(expiry_dates)
    frame["is_standard_expiry"] = frame["date"].isin(expiries).astype(int)
    frame["is_quarterly_expiry"] = (
        frame["is_standard_expiry"].eq(1) & frame["month"].isin([3, 6, 9, 12])
    ).astype(int)
    session_positions = {date: index for index, date in enumerate(dates)}
    sessions_until: list[int] = []
    for index, date in enumerate(dates):
        position = expiries.searchsorted(date, side="left")
        if position < len(expiries):
            sessions_until.append(session_positions[expiries[position]] - index)
            continue
        next_month = (date + pd.offsets.MonthBegin(1)).normalize()
        first_friday = next_month + pd.Timedelta(days=(4 - next_month.weekday()) % 7)
        next_expiry = first_friday + pd.Timedelta(days=14)
        sessions_until.append(len(pd.bdate_range(date, next_expiry)) - 1)
    frame["sessions_until_standard_expiry"] = sessions_until
    frame["observed_at"] = frame["date"]
    frame["available_at"] = frame["date"]
    return frame


__all__ = [
    "FeatureInputNormalizerError",
    "normalize_cboe_vol_panel",
    "normalize_cboe_vol_bundle_panel",
    "normalize_bank_credit_panel",
    "normalize_commercial_paper_panel",
    "normalize_consumer_credit_panel",
    "normalize_credit_spread_panel",
    "normalize_credit_money_panel",
    "normalize_cftc_cross_market_fallback_panel",
    "normalize_cftc_sp500_panel",
    "normalize_financial_conditions_panel",
    "normalize_uncertainty_panel",
    "normalize_finra_margin_panel",
    "normalize_federal_debt_panel",
    "normalize_fomc_decision_panel",
    "normalize_fomc_event_panel",
    "normalize_fomc_document_mix_panel",
    "normalize_fomc_publication_panels",
    "normalize_french_industry_panel",
    "normalize_french_factor_panel",
    "normalize_french_characteristic_panels",
    "normalize_french_global_factor_panels",
    "normalize_french_us_panels",
    "normalize_fx_cross_asset_panel",
    "normalize_usd_funding_panel",
    "normalize_lagged_valuation_panel",
    "normalize_lagged_goyal_issuance_panel",
    "normalize_macro_release_panel",
    "normalize_monetary_liquidity_panel",
    "normalize_noaa_ny_weather_panel",
    "normalize_money_reserves_panel",
    "normalize_philadelphia_realtime_growth_panel",
    "normalize_philadelphia_realtime_cycle_panel",
    "normalize_philadelphia_publication_panel",
    "normalize_policy_rate_panel",
    "normalize_spf_real_rate_panel",
    "normalize_revised_z1_equity_panel",
    "normalize_revised_z1_financial_accounts_panel",
    "normalize_tic_foreign_flow_panel",
    "normalize_z1_corporate_issuance_panel",
    "normalize_spy_decision_panel",
    "normalize_treasury_auction_results_panel",
    "normalize_treasury_auction_announcement_panel",
    "normalize_treasury_curve_panel",
    "normalize_world_bank_cross_asset_panel",
    "normalize_world_bank_commodity_panel",
    "normalize_calendar_state_panel",
]
