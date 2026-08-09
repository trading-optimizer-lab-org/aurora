"""Causal train-only input panels for executable SP500 feature families."""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.feature_contract import apply_available_at_policy


class FeatureInputNormalizerError(ValueError):
    """Raised when an input panel is ambiguous, non-train or non-causal."""


_TRAIN_END = pd.Timestamp("2010-12-31")
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
    elif policy == "friday_after_tuesday":
        eligible = eligible.loc[
            eligible["date"].add(pd.Timedelta(days=3)).le(normalized_sessions.max())
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
            "vix_close": pd.to_numeric(vix["CLOSE"], errors="coerce"),
        }
    ).dropna(subset=["vix_close"])

    old_close = pd.to_numeric(vxo.get("4"), errors="coerce")
    new_close = pd.to_numeric(vxo.get("Unnamed: 4"), errors="coerce")
    vxo_values = pd.DataFrame(
        {
            "date": vxo["date"],
            "vxo_close": old_close.combine_first(new_close),
        }
    ).dropna(subset=["vxo_close"])
    panel = vix_values.merge(vxo_values, on="date", how="outer", validate="one_to_one")
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


def _aggregate_cftc_mode(frame: pd.DataFrame, *, suffix: str) -> pd.DataFrame:
    numeric = pd.DataFrame(
        {
            "date": frame["date"],
            "open_interest": _numeric(frame, "Open Interest (All)"),
            "noncommercial_long": _numeric(
                frame, "Noncommercial Positions-Long (All)"
            ),
            "noncommercial_short": _numeric(
                frame, "Noncommercial Positions-Short (All)"
            ),
            "commercial_long": _numeric(frame, "Commercial Positions-Long (All)"),
            "commercial_short": _numeric(frame, "Commercial Positions-Short (All)"),
            "concentration_long": _numeric(
                frame, "Concentration-Net LT =4 TDR-Long (All)"
            ),
            "concentration_short": _numeric(
                frame, "Concentration-Net LT =4 TDR-Short (All)"
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
            f"top4_net_concentration{suffix}": (
                grouped["concentration_long_weighted"]
                - grouped["concentration_short_weighted"]
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
    market_names = (
        cftc["Market and Exchange Names"].astype(str).str.strip().str.upper()
    )
    selected = cftc.loc[
        market_names.isin(_SP500_CFTC_MARKETS)
    ].copy()
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
    selected["value"] = pd.to_numeric(selected["value"], errors="coerce")
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
    selected["value"] = pd.to_numeric(selected["value"], errors="coerce")
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
                "realtime_output_growth": (
                    (latest_value / previous_value) ** 4 - 1.0
                )
                * 100.0,
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
) -> pd.Series:
    normalized_sessions = (
        pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().unique().sort_values()
    )
    positions = normalized_sessions.searchsorted(
        pd.to_datetime(targets).to_numpy(), side="left"
    )
    result = pd.Series(pd.NaT, index=targets.index, dtype="datetime64[ns]")
    valid = positions < len(normalized_sessions)
    if valid.any():
        result.loc[valid] = normalized_sessions.take(positions[valid]).to_numpy()
    return result


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
                    event[f"{name}_revision"] = float(
                        values.loc[index] - first_values.loc[index]
                    )
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


__all__ = [
    "FeatureInputNormalizerError",
    "normalize_cboe_vol_panel",
    "normalize_credit_spread_panel",
    "normalize_cftc_sp500_panel",
    "normalize_financial_conditions_panel",
    "normalize_fomc_event_panel",
    "normalize_macro_release_panel",
    "normalize_philadelphia_realtime_growth_panel",
    "normalize_spy_decision_panel",
    "normalize_treasury_curve_panel",
]
