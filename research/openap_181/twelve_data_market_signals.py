"""Derived current OpenAP signals from validated Twelve Data daily bars."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..openap_current_score import (
    calculate_price_features,
    exclude_incomplete_us_session,
)
from .twelve_data_market_batch import TIME_SERIES_ENDPOINT


TWELVE_DATA_TIME_SERIES_SIGNAL_TARGETS = (
    "BidAskSpread",
    "High52",
    "MomOffSeason11YrPlus",
    "RealizedVol",
    "VolSD",
    "VolumeTrend",
    "zerotrade1M",
    "zerotrade6M",
    "zerotrade12M",
)
TWELVE_DATA_CROSS_SECTIONAL_SIGNAL_TARGETS = (
    "BetaTailRisk",
    "MomRev",
    "MomVol",
)
TWELVE_DATA_DIRECT_SIGNAL_TARGETS = (
    *TWELVE_DATA_TIME_SERIES_SIGNAL_TARGETS,
    *TWELVE_DATA_CROSS_SECTIONAL_SIGNAL_TARGETS,
)
TWELVE_DATA_DIRECT_FORMULA_SHA256 = {
    "BetaTailRisk": (
        "05a6814113c1e2d7e7513c5831fe73fa9e891c441ab549cbbbd61e418b6c959b"
    ),
    "BidAskSpread": (
        "ec53918eccd8117256dfc55acdaac97b784a9b47a396809a7db04def88490039"
    ),
    "High52": "259505288768464e56184f6dfe7d09f8bffe675bfe67e951bc9870b076e7238b",
    "MomOffSeason11YrPlus": (
        "e185e4a4f26a2e228572e31e8a9feda6184272f0c3b017889f18f7e28399d11a"
    ),
    "MomRev": "c161588a8b984f4832a43c66cb32af555743b5dc068227239123f706be43df60",
    "MomVol": "b80ab3e5495590470e7c865bc55b3dee06d009d4bf1ea2e3b23dfa3073967b27",
    "RealizedVol": (
        "6705b51935883db5726d363ad8692067b3ee9c37637b3e0b54f4fcd7890e059c"
    ),
    "VolSD": "38e54240acc94432becf5734a49acd2cac2e5bacc3504b9ee64cfe110109a6f6",
    "VolumeTrend": (
        "cf3013a4c9360874a0b6f76072a5bfe741b1710f0868a6d1a3517950e10ad8d7"
    ),
    "zerotrade1M": (
        "2d2ee47c3c695f21b114a7a13548d07eb517a08a6e0539dc2282743edf95498b"
    ),
    "zerotrade6M": (
        "2d2ee47c3c695f21b114a7a13548d07eb517a08a6e0539dc2282743edf95498b"
    ),
    "zerotrade12M": (
        "2d2ee47c3c695f21b114a7a13548d07eb517a08a6e0539dc2282743edf95498b"
    ),
}
_BAR_COLUMNS = frozenset(
    {
        "security_id",
        "ticker",
        "cik",
        "adjust",
        "date",
        "close",
        "high",
        "low",
        "volume",
        "available_at",
        "retrieved_at",
        "source_id",
        "historical_ticker_interval_verified",
        "strict_score_eligible",
    }
)
TWELVE_DATA_SIGNAL_BAR_COLUMNS = tuple(sorted(_BAR_COLUMNS))
_OUTPUT_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "signal",
    "formation_at",
    "period_end",
    "filed_at",
    "available_at",
    "retrieved_at",
    "value",
    "fidelity_class",
    "current_usable",
    "source_id",
    "source_url",
    "formula_id",
    "formula_sha256",
    "observation_count",
    "strict_score_eligible",
    "reason_if_missing",
    "caveat",
)


def _require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    label: str,
) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def _timestamp(value: object) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return pd.NaT if pd.isna(parsed) else pd.Timestamp(parsed)


def _normalise_bars(
    bars: pd.DataFrame,
    *,
    cutoff: pd.Timestamp,
    expected_source_id: str = "twelve_data_basic",
    source_label: str = "Twelve Data",
) -> pd.DataFrame:
    _require_columns(bars, _BAR_COLUMNS, f"{source_label} bars")
    frame = bars.copy()
    frame["security_id"] = frame["security_id"].fillna("").astype(str).str.strip()
    frame["ticker"] = frame["ticker"].fillna("").astype(str).str.strip().str.upper()
    frame["cik"] = frame["cik"].fillna("").astype(str).str.strip().str.zfill(10)
    frame["adjust"] = frame["adjust"].fillna("").astype(str).str.lower()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["high"] = pd.to_numeric(frame["high"], errors="coerce")
    frame["low"] = pd.to_numeric(frame["low"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame["available_at"] = pd.to_datetime(
        frame["available_at"], errors="coerce", utc=True
    )
    frame["retrieved_at"] = pd.to_datetime(
        frame["retrieved_at"], errors="coerce", utc=True
    )
    declared_identity = frame.loc[frame["security_id"].ne("")]
    identity_conflicts = declared_identity.groupby("security_id").agg(
        ticker_count=("ticker", lambda values: values.nunique(dropna=False)),
        cik_count=("cik", lambda values: values.nunique(dropna=False)),
    )
    if (
        identity_conflicts["ticker_count"].gt(1)
        | identity_conflicts["cik_count"].gt(1)
    ).any():
        raise ValueError(f"{source_label} bars contain conflicting current identities")
    invalid_provenance = (
        ~frame["source_id"].fillna("").astype(str).eq(expected_source_id)
        | frame["historical_ticker_interval_verified"].ne(False)  # noqa: E712
        | frame["strict_score_eligible"].ne(False)  # noqa: E712
    )
    if invalid_provenance.any():
        raise ValueError(f"{source_label} bars violate the non-strict source contract")
    frame = frame.loc[
        frame["security_id"].ne("")
        & frame["ticker"].ne("")
        & frame["cik"].str.fullmatch(r"\d{10}")
        & frame["adjust"].isin({"all", "none"})
        & frame["date"].notna()
        & frame["close"].notna()
        & np.isfinite(frame["close"])
        & frame["close"].gt(0)
        & frame["high"].notna()
        & np.isfinite(frame["high"])
        & frame["high"].gt(0)
        & frame["low"].notna()
        & np.isfinite(frame["low"])
        & frame["low"].gt(0)
        & frame["high"].ge(frame["low"])
        & frame["volume"].notna()
        & np.isfinite(frame["volume"])
        & frame["volume"].ge(0)
        & frame["available_at"].notna()
        & frame["available_at"].le(cutoff)
        & frame["retrieved_at"].notna()
    ].copy()
    if frame.duplicated(["security_id", "adjust", "date"]).any():
        raise ValueError(
            f"{source_label} bars contain duplicate security/adjust/date rows"
        )
    return frame.sort_values(["security_id", "adjust", "date"]).reset_index(
        drop=True
    )


def _feature_panel(security: pd.DataFrame) -> pd.DataFrame:
    adjusted = security.loc[
        security["adjust"].eq("all"),
        ["date", "close", "available_at"],
    ].rename(
        columns={"close": "adj_close", "available_at": "available_at_adjusted"}
    )
    nominal = security.loc[
        security["adjust"].eq("none"),
        ["date", "high", "low", "volume", "available_at"],
    ].rename(columns={"available_at": "available_at_nominal"})
    panel = adjusted.merge(nominal, on="date", how="inner", validate="one_to_one")
    if panel.empty:
        return panel
    panel["available_at"] = panel[
        ["available_at_adjusted", "available_at_nominal"]
    ].max(axis=1)
    return panel.sort_values("date").reset_index(drop=True)


def _corwin_schultz_monthly_proxy(
    panel: pd.DataFrame,
    *,
    formation: pd.Timestamp,
) -> tuple[float | None, int, object, object]:
    if panel.empty:
        return None, 0, pd.NaT, pd.NaT
    completed_month = formation.tz_convert(None).to_period("M") - 1
    dates = pd.to_datetime(panel["date"], errors="coerce")
    month = panel.loc[dates.dt.to_period("M").eq(completed_month)].copy()
    month["date"] = pd.to_datetime(month["date"], errors="coerce")
    month = month.sort_values("date").dropna(subset=["high", "low"])
    if len(month) < 2:
        return None, 0, month["date"].max(), month["available_at"].max()
    log_range_squared = np.square(
        np.log(month["high"].to_numpy(dtype=float) / month["low"].to_numpy(dtype=float))
    )
    beta = log_range_squared[1:] + log_range_squared[:-1]
    high_two = np.maximum(
        month["high"].to_numpy(dtype=float)[1:],
        month["high"].to_numpy(dtype=float)[:-1],
    )
    low_two = np.minimum(
        month["low"].to_numpy(dtype=float)[1:],
        month["low"].to_numpy(dtype=float)[:-1],
    )
    gamma = np.square(np.log(high_two / low_two))
    denominator = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (
        (np.sqrt(2.0 * beta) - np.sqrt(beta)) / denominator
        - np.sqrt(gamma / denominator)
    )
    alpha = np.maximum(alpha, 0.0)
    spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    spread = spread[np.isfinite(spread)]
    value = float(np.mean(spread)) if len(spread) else None
    return (
        value,
        len(spread),
        month["date"].max(),
        pd.to_datetime(month["available_at"], errors="coerce", utc=True).max(),
    )


def _rows_for_security(
    security: pd.DataFrame,
    *,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
) -> list[dict[str, Any]]:
    identity = security.iloc[-1]
    panel = _feature_panel(security)
    if not panel.empty:
        panel, _, _ = exclude_incomplete_us_session(panel, as_of=formation)
    features = (
        calculate_price_features(
            panel[["date", "adj_close", "volume"]],
            as_of=formation,
            source_id="twelve_data_basic",
            source_label="Twelve Data",
        )
        if not panel.empty
        else {}
    )
    period_end = panel["date"].max() if not panel.empty else pd.NaT
    available_at = panel["available_at"].max() if not panel.empty else pd.NaT
    spread_value, spread_n, spread_end, spread_available = (
        _corwin_schultz_monthly_proxy(panel, formation=formation)
    )
    rows: list[dict[str, Any]] = []
    for signal in TWELVE_DATA_TIME_SERIES_SIGNAL_TARGETS:
        feature = features.get(signal)
        is_spread = signal == "BidAskSpread"
        value = spread_value if is_spread else (
            feature.raw_value if feature is not None else None
        )
        signal_period_end = spread_end if is_spread else period_end
        signal_available_at = spread_available if is_spread else available_at
        observation_count = spread_n if is_spread else len(panel)
        finite = value is not None and np.isfinite(float(value))
        rows.append(
            {
                "security_id": str(identity["security_id"]),
                "ticker": str(identity["ticker"]),
                "cik": str(identity["cik"]),
                "signal": signal,
                "formation_at": formation.isoformat(),
                "period_end": (
                    ""
                    if pd.isna(signal_period_end)
                    else pd.Timestamp(signal_period_end).date().isoformat()
                ),
                "filed_at": "",
                "available_at": (
                    ""
                    if pd.isna(signal_available_at)
                    else pd.Timestamp(signal_available_at).isoformat()
                ),
                "retrieved_at": retrieved.isoformat(),
                "value": float(value) if finite else float("nan"),
                "fidelity_class": "reconstructed" if finite else "unavailable",
                "current_usable": bool(finite),
                "source_id": "twelve_data_basic",
                "source_url": TIME_SERIES_ENDPOINT,
                "formula_id": (
                    "corwin_schultz_standard_two_day_monthly_mean_proxy"
                    if is_spread
                    else (feature.formula_id if feature is not None else "")
                ),
                "formula_sha256": TWELVE_DATA_DIRECT_FORMULA_SHA256[signal],
                "observation_count": int(observation_count),
                "strict_score_eligible": False,
                "reason_if_missing": (
                    ""
                    if finite
                    else (
                        "insufficient_completed_month_high_low_pairs"
                        if is_spread
                        else feature.note
                        if feature is not None and feature.note
                        else "insufficient_bounded_market_history"
                    )
                ),
                "caveat": (
                    (
                        "Standard Corwin-Schultz high-low estimator reconstructed "
                        "from Twelve Data nominal highs and lows; OpenAP's unpublished "
                        "SAS preprocessing, CRSP identity and exact monthly treatment "
                        "remain unmatched"
                        if is_spread
                        else "Twelve Data Basic adjusted prices and consolidated "
                        "volume reconstruct the pinned time-series formula; "
                        "historical ticker intervals are not verified, CRSP-specific "
                        "semantics remain unmatched, and the result is never strict-"
                        "score eligible"
                    )
                ),
            }
        )
    return rows


def _compound_lags(
    monthly: pd.DataFrame,
    *,
    formation_period: pd.Period,
    lags: Iterable[int],
) -> float | None:
    values: list[float] = []
    for lag in lags:
        period = formation_period - int(lag)
        if period not in monthly.index:
            return None
        value = monthly.at[period, "return"]
        if pd.isna(value) or not np.isfinite(float(value)):
            return None
        values.append(float(value))
    compounded = float(np.prod(1.0 + np.asarray(values, dtype=float)) - 1.0)
    return compounded if np.isfinite(compounded) else None


def _monthly_return_panel(
    security: pd.DataFrame,
    *,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    identity = security.iloc[-1]
    panel = _feature_panel(security)
    if not panel.empty:
        panel, _, _ = exclude_incomplete_us_session(panel, as_of=formation)
    formation_period = formation.tz_localize(None).to_period("M")
    completed = panel.loc[
        pd.to_datetime(panel.get("date"), errors="coerce").dt.to_period("M")
        < formation_period
    ].copy()
    if completed.empty:
        return pd.DataFrame()
    completed["date"] = pd.to_datetime(completed["date"], errors="coerce")
    completed["month"] = completed["date"].dt.to_period("M")
    monthly = completed.groupby("month", sort=True).agg(
        close=("adj_close", "last"),
        period_end=("date", "max"),
        available_at=("available_at", "max"),
    )
    if monthly.empty:
        return pd.DataFrame()
    monthly = monthly.reindex(
        pd.period_range(monthly.index.min(), formation_period - 1, freq="M")
    )
    monthly["return"] = monthly["close"].pct_change(fill_method=None)
    monthly["security_id"] = str(identity["security_id"])
    monthly["ticker"] = str(identity["ticker"])
    monthly["cik"] = str(identity["cik"])
    return monthly.reset_index(names="month")


def _daily_return_panel(
    security: pd.DataFrame,
    *,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    identity = security.iloc[-1]
    adjusted = security.loc[
        security["adjust"].eq("all"),
        ["date", "close", "available_at"],
    ].rename(columns={"close": "adj_close"})
    adjusted, _, _ = exclude_incomplete_us_session(adjusted, as_of=formation)
    formation_period = formation.tz_localize(None).to_period("M")
    adjusted["date"] = pd.to_datetime(adjusted["date"], errors="coerce")
    adjusted = adjusted.loc[
        adjusted["date"].dt.to_period("M") < formation_period
    ].sort_values("date")
    if adjusted.empty:
        return pd.DataFrame()
    adjusted["return"] = adjusted["adj_close"].pct_change(fill_method=None)
    adjusted["month"] = adjusted["date"].dt.to_period("M")
    adjusted["security_id"] = str(identity["security_id"])
    return adjusted.dropna(subset=["return"])


def _beta_tail_rows(
    normalised: pd.DataFrame,
    *,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
) -> list[dict[str, Any]]:
    identities = normalised.sort_values("date").drop_duplicates(
        "security_id", keep="last"
    )[["security_id", "ticker", "cik"]]
    panels = [
        _monthly_return_panel(security, formation=formation)
        for _, security in normalised.groupby("security_id", sort=True)
    ]
    panels = [panel for panel in panels if not panel.empty]
    monthly = (
        pd.concat(panels, ignore_index=True)
        if panels
        else pd.DataFrame(
            columns=[
                "month",
                "return",
                "period_end",
                "available_at",
                "security_id",
                "ticker",
                "cik",
            ]
        )
    )
    daily_panels = [
        _daily_return_panel(security, formation=formation)
        for _, security in normalised.groupby("security_id", sort=True)
    ]
    daily_panels = [panel for panel in daily_panels if not panel.empty]
    daily = pd.concat(daily_panels, ignore_index=True) if daily_panels else pd.DataFrame()
    if not daily.empty:
        percentile5 = daily.groupby("date")["return"].quantile(
            0.05,
            interpolation="lower",
        )
        daily["return_p5"] = daily["date"].map(percentile5)
        tail = daily.loc[daily["return"].le(daily["return_p5"])].copy()
        ratio = tail["return"] / tail["return_p5"]
        tail["tail_excess"] = np.log(ratio.where(ratio.gt(0.0)))
        factor = tail.groupby("month", as_index=False)["tail_excess"].mean()
    else:
        factor = pd.DataFrame(columns=["month", "tail_excess"])
    rows: list[dict[str, Any]] = []
    for identity in identities.itertuples(index=False):
        security_monthly = monthly.loc[
            monthly.get("security_id", pd.Series(dtype=str)).eq(identity.security_id)
        ].copy()
        aligned = (
            security_monthly.merge(factor, on="month", how="inner")
            .sort_values("month")
            .tail(120)
            .dropna(subset=["return", "tail_excess"])
        )
        beta: float | None = None
        if len(aligned) >= 72 and aligned["tail_excess"].nunique() >= 2:
            design = np.column_stack(
                [np.ones(len(aligned), dtype=float), aligned["tail_excess"]]
            )
            if np.linalg.matrix_rank(design) == 2:
                coefficients, *_ = np.linalg.lstsq(
                    design,
                    aligned["return"].to_numpy(dtype=float),
                    rcond=None,
                )
                if len(coefficients) == 2 and np.isfinite(coefficients[1]):
                    beta = float(coefficients[1])
        latest = aligned.iloc[-1] if not aligned.empty else None
        finite = beta is not None and np.isfinite(beta)
        rows.append(
            {
                "security_id": str(identity.security_id),
                "ticker": str(identity.ticker),
                "cik": str(identity.cik),
                "signal": "BetaTailRisk",
                "formation_at": formation.isoformat(),
                "period_end": (
                    ""
                    if latest is None or pd.isna(latest["period_end"])
                    else pd.Timestamp(latest["period_end"]).date().isoformat()
                ),
                "filed_at": "",
                "available_at": (
                    ""
                    if latest is None or pd.isna(latest["available_at"])
                    else pd.Timestamp(latest["available_at"]).isoformat()
                ),
                "retrieved_at": retrieved.isoformat(),
                "value": beta if finite else float("nan"),
                "fidelity_class": "reconstructed" if finite else "unavailable",
                "current_usable": bool(finite),
                "source_id": "twelve_data_basic",
                "source_url": TIME_SERIES_ENDPOINT,
                "formula_id": "openap_cross_section_p5_tail_beta_120m_min72",
                "formula_sha256": TWELVE_DATA_DIRECT_FORMULA_SHA256[
                    "BetaTailRisk"
                ],
                "observation_count": int(len(aligned)),
                "strict_score_eligible": False,
                "reason_if_missing": (
                    "" if finite else "insufficient_cross_sectional_tail_history"
                ),
                "caveat": (
                    "Pinned OpenAP cross-sectional fifth-percentile tail factor "
                    "reconstructed from Twelve Data adjusted returns; current "
                    "security identity and non-CRSP returns remain non-strict"
                ),
            }
        )
    return rows


def _cross_sectional_inputs(
    security: pd.DataFrame,
    *,
    formation: pd.Timestamp,
) -> dict[str, Any]:
    identity = security.iloc[-1]
    panel = _feature_panel(security)
    if not panel.empty:
        panel, _, _ = exclude_incomplete_us_session(panel, as_of=formation)
    formation_period = formation.tz_localize(None).to_period("M")
    completed = panel.loc[
        pd.to_datetime(panel.get("date"), errors="coerce").dt.to_period("M")
        < formation_period
    ].copy()
    base = {
        "security_id": str(identity["security_id"]),
        "ticker": str(identity["ticker"]),
        "cik": str(identity["cik"]),
        "period_end": pd.NaT,
        "available_at": pd.NaT,
        "history_months": 0,
        "mom6": np.nan,
        "mom36": np.nan,
        "mean_volume6": np.nan,
    }
    if completed.empty:
        return base
    completed["date"] = pd.to_datetime(completed["date"], errors="coerce")
    completed["month"] = completed["date"].dt.to_period("M")
    monthly = completed.groupby("month", sort=True).agg(
        close=("adj_close", "last"),
        volume=("volume", lambda values: values.sum(min_count=1)),
        period_end=("date", "max"),
        available_at=("available_at", "max"),
    )
    if monthly.empty:
        return base
    full_index = pd.period_range(
        monthly.index.min(),
        formation_period - 1,
        freq="M",
    )
    monthly = monthly.reindex(full_index)
    monthly["return"] = monthly["close"].pct_change(fill_method=None)
    mom6 = _compound_lags(
        monthly,
        formation_period=formation_period,
        lags=range(1, 6),
    )
    mom36 = _compound_lags(
        monthly,
        formation_period=formation_period,
        lags=range(13, 37),
    )
    recent_volume = [
        monthly.at[formation_period - lag, "volume"]
        for lag in range(1, 7)
        if formation_period - lag in monthly.index
    ]
    finite_volume = [
        float(value)
        for value in recent_volume
        if pd.notna(value) and np.isfinite(float(value)) and float(value) >= 0.0
    ]
    mean_volume6 = (
        float(np.mean(finite_volume)) if len(finite_volume) >= 5 else np.nan
    )
    latest_period = formation_period - 1
    latest = monthly.loc[latest_period] if latest_period in monthly.index else None
    return {
        **base,
        "period_end": latest["period_end"] if latest is not None else pd.NaT,
        "available_at": latest["available_at"] if latest is not None else pd.NaT,
        "history_months": int(monthly["close"].notna().sum()),
        "mom6": float(mom6) if mom6 is not None else np.nan,
        "mom36": float(mom36) if mom36 is not None else np.nan,
        "mean_volume6": mean_volume6,
    }


def _qcut_one_based(values: pd.Series, bins: int) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    finite = values.notna() & np.isfinite(values)
    if int(finite.sum()) < int(bins):
        return result
    try:
        result.loc[finite] = (
            pd.qcut(values.loc[finite], q=bins, labels=False, duplicates="drop")
            .astype(float)
            .add(1.0)
        )
    except ValueError:
        return pd.Series(np.nan, index=values.index, dtype=float)
    return result


def _cross_sectional_rows(
    normalised: pd.DataFrame,
    *,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
) -> list[dict[str, Any]]:
    input_rows = [
        _cross_sectional_inputs(security, formation=formation)
        for _, security in normalised.groupby("security_id", sort=True)
    ]
    if not input_rows:
        return []
    inputs = pd.DataFrame(input_rows).set_index("security_id")
    inputs["mom6_quintile"] = _qcut_one_based(inputs["mom6"], 5)
    inputs["mom36_quintile"] = _qcut_one_based(inputs["mom36"], 5)
    inputs["mom6_decile"] = _qcut_one_based(inputs["mom6"], 10)
    inputs["volume_tercile"] = _qcut_one_based(inputs["mean_volume6"], 3)
    rows: list[dict[str, Any]] = []
    for security_id, row in inputs.sort_index().iterrows():
        momrev: float | None = None
        if row["mom6_quintile"] == 5.0 and row["mom36_quintile"] == 1.0:
            momrev = 1.0
        elif row["mom6_quintile"] == 1.0 and row["mom36_quintile"] == 5.0:
            momrev = 0.0
        momvol = (
            float(row["mom6_decile"])
            if row["volume_tercile"] == 3.0
            and float(row["history_months"]) >= 24.0
            and pd.notna(row["mom6_decile"])
            else None
        )
        for signal, value, formula_id, missing_reason in (
            (
                "MomRev",
                momrev,
                "openap_momrev_mom6_mom36_cross_sectional_extremes",
                (
                    "not_an_official_extreme_double_sort_portfolio"
                    if pd.notna(row["mom6"]) and pd.notna(row["mom36"])
                    else "insufficient_contiguous_monthly_return_history"
                ),
            ),
            (
                "MomVol",
                momvol,
                "openap_momvol_mom6_decile_high_volume_tercile",
                (
                    "not_in_official_high_volume_tercile"
                    if pd.notna(row["mom6"]) and pd.notna(row["mean_volume6"])
                    else "insufficient_monthly_return_or_volume_history"
                ),
            ),
        ):
            finite = value is not None and np.isfinite(float(value))
            rows.append(
                {
                    "security_id": str(security_id),
                    "ticker": str(row["ticker"]),
                    "cik": str(row["cik"]),
                    "signal": signal,
                    "formation_at": formation.isoformat(),
                    "period_end": (
                        ""
                        if pd.isna(row["period_end"])
                        else pd.Timestamp(row["period_end"]).date().isoformat()
                    ),
                    "filed_at": "",
                    "available_at": (
                        ""
                        if pd.isna(row["available_at"])
                        else pd.Timestamp(row["available_at"]).isoformat()
                    ),
                    "retrieved_at": retrieved.isoformat(),
                    "value": float(value) if finite else float("nan"),
                    "fidelity_class": "reconstructed" if finite else "unavailable",
                    "current_usable": bool(finite),
                    "source_id": "twelve_data_basic",
                    "source_url": TIME_SERIES_ENDPOINT,
                    "formula_id": formula_id,
                    "formula_sha256": TWELVE_DATA_DIRECT_FORMULA_SHA256[signal],
                    "observation_count": int(row["history_months"]),
                    "strict_score_eligible": False,
                    "reason_if_missing": "" if finite else missing_reason,
                    "caveat": (
                        "Pinned OpenAP cross-sectional sort reconstructed from "
                        "Twelve Data adjusted returns and consolidated volume; "
                        "missing calendar months fail closed, historical ticker "
                        "intervals and CRSP volume semantics remain unmatched"
                    ),
                }
            )
    return rows


def calculate_twelve_data_direct_signals(
    bars: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
    source_id: str = "twelve_data_basic",
    source_url: str = TIME_SERIES_ENDPOINT,
    source_label: str = "Twelve Data",
) -> pd.DataFrame:
    """Calculate direct market signals without external factor inputs."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("market formation_at or retrieved_at is invalid")
    source_id = str(source_id).strip()
    source_url = str(source_url).strip()
    source_label = str(source_label).strip()
    if not source_id or not source_url or not source_label:
        raise ValueError("market source provenance must be non-empty")
    normalised = _normalise_bars(
        bars,
        cutoff=min(formation, retrieved),
        expected_source_id=source_id,
        source_label=source_label,
    )
    rows: list[dict[str, Any]] = []
    for _, security in normalised.groupby("security_id", sort=True):
        rows.extend(
            _rows_for_security(
                security,
                formation=formation,
                retrieved=retrieved,
            )
        )
    rows.extend(
        _cross_sectional_rows(
            normalised,
            formation=formation,
            retrieved=retrieved,
        )
    )
    rows.extend(
        _beta_tail_rows(
            normalised,
            formation=formation,
            retrieved=retrieved,
        )
    )
    result = pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)
    result["source_id"] = source_id
    result["source_url"] = source_url
    result["caveat"] = result["caveat"].str.replace(
        "Twelve Data",
        source_label,
        regex=False,
    )
    return result


__all__ = [
    "TWELVE_DATA_CROSS_SECTIONAL_SIGNAL_TARGETS",
    "TWELVE_DATA_DIRECT_FORMULA_SHA256",
    "TWELVE_DATA_DIRECT_SIGNAL_TARGETS",
    "TWELVE_DATA_SIGNAL_BAR_COLUMNS",
    "TWELVE_DATA_TIME_SERIES_SIGNAL_TARGETS",
    "calculate_twelve_data_direct_signals",
]
