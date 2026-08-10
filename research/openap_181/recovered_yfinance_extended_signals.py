"""Eight additional non-strict market signals from recovered price evidence.

The calculations follow the pinned OpenAP formulas where the recovered inputs
permit it.  Current Yahoo metadata and SEC identities replace historical CRSP
membership, shares and market value, so no row is eligible for the strict score.
"""

from __future__ import annotations

from io import StringIO
from typing import Any
import re

import numpy as np
import pandas as pd

from .twelve_data_factor_signals import KENNETH_FRENCH_MONTHLY_URL
from .twelve_data_market_signals import _OUTPUT_COLUMNS, _normalise_bars, _timestamp


PASTOR_STAMBAUGH_URL = (
    "https://faculty.chicagobooth.edu/-/media/faculty/lubos-pastor/data/"
    "liq_data_1962_2025.txt"
)
RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS = (
    "BetaLiquidityPS",
    "FirmAgeMom",
    "IndMom",
    "IndRetBig",
    "Size",
    "TrendFactor",
    "VolMkt",
    "std_turn",
)
RECOVERED_YFINANCE_EXTENDED_FORMULA_SHA256 = {
    "BetaLiquidityPS": "dfdae867eeab94286f89be9ee39d36ad9523cd992d2c755170430db2d29750f4",
    "FirmAgeMom": "6c031460e7c7d50643ef77123b248b6f1141bbab0d98e5e9c30fac48a344fff6",
    "IndMom": "d730976fcf666e3e19759be809ee29d5e01444e1e9fa7de576b1181b65ec55fd",
    "IndRetBig": "6205f427710b7141b4c2378c20c3cfe6a64decce5145d9d1f5f15b419ee019ce",
    "Size": "3741c5ca88b4869772195bb16b5094fd1fcd36bd48090c317b7fa5f1ed0be5be",
    "TrendFactor": "8280bce92bacaf1d9b848f38533fb7a2d4a3120e7598e55b990e9b09c48cddd8",
    "VolMkt": "83b50bcb6849e45c105ffd2beb7a6350892d9c9d46e50470b7b137077d7d356e",
    "std_turn": "bddf1463c30c774360247a9afc156546ce8ed7d8f6832c46ac07ce75c3d7da52",
}
_TREND_WINDOWS = (3, 5, 10, 20, 50, 100, 200, 400, 600, 800, 1000)
_CONTEXT_COLUMNS = frozenset({"security_id", "ticker", "cik"})


def parse_pastor_stambaugh_liquidity(
    payload: bytes,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Parse the authors' four-column text file without forward rows."""

    formation = _timestamp(formation_at)
    if pd.isna(formation):
        raise ValueError("Pastor-Stambaugh formation_at is invalid")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Pastor-Stambaugh source is not valid UTF-8") from exc
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(StringIO(text), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        fields = stripped.split()
        if len(fields) != 4 or re.fullmatch(r"\d{6}", fields[0]) is None:
            raise ValueError(
                f"Pastor-Stambaugh source has an invalid row at line {line_number}"
            )
        year = int(fields[0][:4])
        month = int(fields[0][4:])
        try:
            period = pd.Period(year=year, month=month, freq="M")
            values = [float(value) for value in fields[1:]]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Pastor-Stambaugh source has invalid values at line {line_number}"
            ) from exc
        if not np.isfinite(values).all():
            raise ValueError("Pastor-Stambaugh source contains non-finite values")
        records.append(
            {
                "month": period,
                "aggregate_liquidity": values[0],
                "ps_innov": values[1],
                "traded_liquidity": np.nan if values[2] == -99 else values[2],
            }
        )
    frame = pd.DataFrame(
        records,
        columns=(
            "month",
            "aggregate_liquidity",
            "ps_innov",
            "traded_liquidity",
        ),
    )
    if frame.empty or frame["month"].duplicated().any():
        raise ValueError("Pastor-Stambaugh source is empty or has duplicate months")
    formation_period = formation.tz_convert(None).to_period("M")
    frame = frame.loc[frame["month"].lt(formation_period)].sort_values("month")
    if frame.empty:
        raise ValueError("Pastor-Stambaugh source has no causal observations")
    return frame.reset_index(drop=True)


def _context_frame(context: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(_CONTEXT_COLUMNS.difference(context.columns))
    if missing:
        raise ValueError(f"recovered market context is missing columns: {missing}")
    frame = context.copy()
    frame["security_id"] = frame["security_id"].fillna("").astype(str).str.strip()
    frame["ticker"] = frame["ticker"].fillna("").astype(str).str.strip().str.upper()
    frame["cik"] = frame["cik"].fillna("").astype(str).str.strip().str.zfill(10)
    invalid = (
        frame["security_id"].eq("")
        | frame["ticker"].eq("")
        | ~frame["cik"].str.fullmatch(r"\d{10}")
        | frame["security_id"].duplicated(keep=False)
        | frame["ticker"].duplicated(keep=False)
    )
    if invalid.any():
        raise ValueError("recovered market context contains ambiguous identities")
    for target, candidates in {
        "market_cap": ("issuer_market_cap", "marketCap"),
        "shares": ("sharesOutstanding", "resolved_shares"),
        "industry_group": ("sic", "industry", "sector"),
        "first_observed": ("first_price_date", "firstTradeDateEpochUtc"),
        "exchange": ("exchange_sec", "exchange"),
    }.items():
        frame[target] = np.nan if target in {"market_cap", "shares"} else ""
        for candidate in candidates:
            if candidate not in frame:
                continue
            if target in {"market_cap", "shares"}:
                candidate_values = pd.to_numeric(frame[candidate], errors="coerce")
                frame[target] = pd.to_numeric(frame[target], errors="coerce").fillna(
                    candidate_values
                )
            elif target == "first_observed":
                candidate_values = frame[candidate]
                if candidate == "firstTradeDateEpochUtc":
                    candidate_values = pd.to_datetime(
                        pd.to_numeric(candidate_values, errors="coerce"),
                        unit="s",
                        errors="coerce",
                        utc=True,
                    )
                else:
                    candidate_values = pd.to_datetime(
                        candidate_values,
                        errors="coerce",
                        utc=True,
                    )
                current = pd.to_datetime(frame[target], errors="coerce", utc=True)
                frame[target] = current.fillna(candidate_values)
            else:
                current = frame[target].fillna("").astype(str).str.strip()
                candidate_values = frame[candidate].fillna("").astype(str).str.strip()
                frame[target] = current.where(current.ne(""), candidate_values)
    frame["market_cap"] = pd.to_numeric(frame["market_cap"], errors="coerce")
    frame["shares"] = pd.to_numeric(frame["shares"], errors="coerce")
    frame["first_observed"] = pd.to_datetime(
        frame["first_observed"], errors="coerce", utc=True
    )
    industry = frame["industry_group"].fillna("").astype(str).str.strip()
    sic2 = industry.str.extract(r"(\d{2})", expand=False)
    frame["industry_group"] = sic2.where(sic2.notna(), industry)
    return frame


def _monthly_panel(
    bars: pd.DataFrame,
    context: pd.DataFrame,
    *,
    current_period: pd.Period,
) -> pd.DataFrame:
    adjusted = bars.loc[bars["adjust"].eq("all")].copy()
    adjusted["month"] = adjusted["date"].dt.to_period("M")
    monthly = (
        adjusted.sort_values(["security_id", "date"])
        .groupby(["security_id", "month"], as_index=False)
        .agg(
            ticker=("ticker", "last"),
            cik=("cik", "last"),
            close=("close", "last"),
            period_end=("date", "max"),
            available_at=("available_at", "max"),
        )
        .sort_values(["security_id", "month"])
    )
    nominal = bars.loc[bars["adjust"].eq("none")].copy()
    nominal["month"] = nominal["date"].dt.to_period("M")
    nominal["dollar_volume"] = nominal["close"] * nominal["volume"]
    nominal_monthly = (
        nominal.sort_values(["security_id", "date"])
        .groupby(["security_id", "month"], as_index=False)
        .agg(
            nominal_close=("close", "last"),
            volume=("volume", "sum"),
            dollar_volume=("dollar_volume", "sum"),
        )
    )
    monthly = monthly.merge(
        nominal_monthly,
        on=["security_id", "month"],
        how="inner",
        validate="one_to_one",
    )
    monthly = monthly.loc[monthly["month"].le(current_period)].copy()
    monthly["return"] = monthly.groupby("security_id", sort=False)["close"].pct_change()
    monthly = monthly.merge(
        context[
            [
                "security_id",
                "market_cap",
                "shares",
                "industry_group",
                "first_observed",
                "exchange",
            ]
        ],
        on="security_id",
        how="inner",
        validate="many_to_one",
    )
    derived_market_cap = monthly["shares"] * monthly["nominal_close"]
    monthly["market_cap"] = derived_market_cap.where(
        np.isfinite(derived_market_cap) & derived_market_cap.gt(0),
        monthly["market_cap"],
    )
    for lag in range(1, 6):
        monthly[f"return_lag{lag}"] = monthly.groupby("security_id", sort=False)[
            "return"
        ].shift(lag)
    lag_columns = [f"return_lag{lag}" for lag in range(1, 6)]
    monthly["momentum_5_lags"] = (
        (1.0 + monthly[lag_columns]).prod(axis=1, min_count=5) - 1.0
    )
    monthly["monthly_turnover"] = monthly["volume"] / monthly["shares"]
    monthly["std_turn_value"] = monthly.groupby("security_id", sort=False)[
        "monthly_turnover"
    ].transform(lambda values: values.rolling(36, min_periods=24).std(ddof=1))
    monthly["volmkt_value"] = (
        monthly.groupby("security_id", sort=False)["dollar_volume"]
        .transform(lambda values: values.rolling(12, min_periods=10).mean())
        / monthly["market_cap"]
    )
    return monthly


def _ols_beta(y: np.ndarray, x: np.ndarray, minimum: int) -> tuple[np.ndarray, int] | None:
    y_values = np.asarray(y, dtype=float)
    x_values = np.asarray(x, dtype=float)
    if x_values.ndim == 1:
        x_values = x_values.reshape(-1, 1)
    valid = np.isfinite(y_values) & np.isfinite(x_values).all(axis=1)
    y_values = y_values[valid]
    x_values = x_values[valid]
    if len(y_values) < minimum:
        return None
    design = np.column_stack([np.ones(len(x_values)), x_values])
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return None
    coefficients = np.linalg.lstsq(design, y_values, rcond=None)[0]
    if not np.isfinite(coefficients).all():
        return None
    return coefficients, len(y_values)


def _beta_liquidity_values(
    monthly: pd.DataFrame,
    ff3_monthly: pd.DataFrame,
    liquidity: pd.DataFrame,
    *,
    current_period: pd.Period,
) -> dict[str, dict[str, Any]]:
    factors = ff3_monthly.copy()
    required = {"date", "mktrf", "smb", "hml", "rf"}
    missing = sorted(required.difference(factors.columns))
    if missing:
        raise ValueError(f"monthly French factors are missing columns: {missing}")
    factors["month"] = pd.to_datetime(factors["date"], errors="coerce").dt.to_period("M")
    for column in ("mktrf", "smb", "hml", "rf"):
        factors[column] = pd.to_numeric(factors[column], errors="coerce")
    factor_panel = factors[["month", "mktrf", "smb", "hml", "rf"]].merge(
        liquidity[["month", "ps_innov"]],
        on="month",
        how="inner",
        validate="one_to_one",
    )
    factor_panel = factor_panel.loc[factor_panel["month"].le(current_period)].dropna()
    latest_factor_month = factor_panel["month"].max() if not factor_panel.empty else None
    results: dict[str, dict[str, Any]] = {}
    for security_id, security in monthly.groupby("security_id", sort=True):
        aligned = security[["month", "return", "period_end", "available_at"]].merge(
            factor_panel,
            on="month",
            how="inner",
            validate="one_to_one",
        ).sort_values("month").tail(60)
        fit = _ols_beta(
            (aligned["return"] - aligned["rf"]).to_numpy(dtype=float),
            aligned[["ps_innov", "mktrf", "hml", "smb"]].to_numpy(dtype=float),
            minimum=36,
        )
        results[str(security_id)] = {
            "value": None if fit is None else float(fit[0][1]),
            "observation_count": 0 if fit is None else int(fit[1]),
            "period_end": (
                pd.NaT if latest_factor_month is None else latest_factor_month.to_timestamp("M")
            ),
            "available_at": (
                pd.NaT
                if aligned.empty
                else pd.to_datetime(aligned["available_at"], errors="coerce", utc=True).max()
            ),
            "current": latest_factor_month == current_period,
            "reason": (
                "insufficient_60_month_four_factor_history"
                if fit is None
                else (
                    ""
                    if latest_factor_month == current_period
                    else "pastor_stambaugh_factor_not_current_for_formation_month"
                )
            ),
        }
    return results


def _trend_factor_values(
    bars: pd.DataFrame,
    context: pd.DataFrame,
    *,
    current_period: pd.Period,
) -> dict[str, dict[str, Any]]:
    adjusted = bars.loc[bars["adjust"].eq("all")].copy()
    earliest = (current_period - 72).to_timestamp()
    adjusted = adjusted.loc[adjusted["date"].ge(earliest)].copy()
    feature_parts: list[pd.DataFrame] = []
    for security_id, security in adjusted.groupby("security_id", sort=True):
        security = security.sort_values("date").copy()
        security["month"] = security["date"].dt.to_period("M")
        for window in _TREND_WINDOWS:
            security[f"ma_{window}"] = (
                security["close"].rolling(window, min_periods=1).mean()
                / security["close"]
            )
        month_end = security.groupby("month", sort=True).tail(1).copy()
        month_end["return"] = month_end["close"].pct_change()
        month_end["future_return"] = month_end["return"].shift(-1)
        month_end["security_id"] = str(security_id)
        feature_parts.append(month_end)
    if not feature_parts:
        return {}
    features = pd.concat(feature_parts, ignore_index=True)
    features = features.merge(
        context[["security_id", "market_cap", "exchange"]],
        on="security_id",
        how="inner",
        validate="many_to_one",
    )
    ma_columns = [f"ma_{window}" for window in _TREND_WINDOWS]
    beta_rows: list[dict[str, Any]] = []
    first_beta_period = current_period - 12
    last_beta_period = current_period - 1
    beta_input = features.loc[
        features["month"].between(first_beta_period, last_beta_period)
    ].copy()
    for month, cross_section in beta_input.groupby("month", sort=True):
        nyse_caps = pd.to_numeric(
            cross_section.loc[
                cross_section["exchange"].astype(str).str.contains("NYSE", case=False),
                "market_cap",
            ],
            errors="coerce",
        ).dropna()
        all_caps = pd.to_numeric(cross_section["market_cap"], errors="coerce").dropna()
        reference_caps = nyse_caps if len(nyse_caps) >= 5 else all_caps
        size_floor = reference_caps.quantile(0.10) if not reference_caps.empty else np.nan
        eligible = cross_section.loc[
            cross_section["close"].ge(5.0)
            & pd.to_numeric(cross_section["market_cap"], errors="coerce").ge(size_floor)
        ]
        fit = _ols_beta(
            eligible["future_return"].to_numpy(dtype=float),
            eligible[ma_columns].to_numpy(dtype=float),
            minimum=len(ma_columns) + 2,
        )
        if fit is not None:
            beta_rows.append(
                {
                    "month": month,
                    "coefficients": fit[0][1:],
                    "observation_count": fit[1],
                }
            )
    average_beta: np.ndarray | None = None
    if len(beta_rows) >= 6:
        average_beta = np.mean(
            np.vstack([row["coefficients"] for row in beta_rows]),
            axis=0,
        )
    current = features.loc[features["month"].eq(current_period)]
    results: dict[str, dict[str, Any]] = {}
    for row in current.itertuples(index=False):
        values = np.asarray([getattr(row, column) for column in ma_columns], dtype=float)
        value = (
            float(values @ average_beta)
            if average_beta is not None
            and np.isfinite(values).all()
            and np.isfinite(average_beta).all()
            else None
        )
        results[str(row.security_id)] = {
            "value": value,
            "observation_count": sum(
                int(beta_row["observation_count"]) for beta_row in beta_rows
            ),
            "period_end": row.date,
            "available_at": row.available_at,
            "current": value is not None,
            "reason": (
                ""
                if value is not None
                else "insufficient_causal_cross_sectional_trend_regressions"
            ),
        }
    return results


def _row(
    identity: Any,
    *,
    signal: str,
    value: float | None,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
    period_end: object,
    available_at: object,
    observation_count: int,
    current: bool,
    reason: str,
    source_id: str,
    source_url: str,
    formula_id: str,
    caveat: str,
) -> dict[str, Any]:
    finite = value is not None and np.isfinite(float(value))
    period = pd.to_datetime(period_end, errors="coerce")
    available = pd.to_datetime(available_at, errors="coerce", utc=True)
    current_usable = bool(finite and current)
    return {
        "security_id": str(identity.security_id),
        "ticker": str(identity.ticker),
        "cik": str(identity.cik),
        "signal": signal,
        "formation_at": formation.isoformat(),
        "period_end": "" if pd.isna(period) else pd.Timestamp(period).date().isoformat(),
        "filed_at": "",
        "available_at": "" if pd.isna(available) else pd.Timestamp(available).isoformat(),
        "retrieved_at": retrieved.isoformat(),
        "value": float(value) if finite else float("nan"),
        "fidelity_class": (
            "reconstructed"
            if current_usable
            else ("historical_reconstructed" if finite else "unavailable")
        ),
        "current_usable": current_usable,
        "source_id": source_id,
        "source_url": source_url,
        "formula_id": formula_id,
        "formula_sha256": RECOVERED_YFINANCE_EXTENDED_FORMULA_SHA256[signal],
        "observation_count": int(observation_count),
        "strict_score_eligible": False,
        "reason_if_missing": "" if current_usable else reason,
        "caveat": caveat,
    }


def calculate_recovered_yfinance_extended_signals(
    bars: pd.DataFrame,
    security_context: pd.DataFrame,
    ff3_monthly: pd.DataFrame,
    pastor_stambaugh: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
    source_id: str,
    source_url: str,
) -> pd.DataFrame:
    """Calculate the remaining eight prepared market targets fail-closed."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("extended market timestamps are invalid")
    source_id = str(source_id).strip()
    source_url = str(source_url).strip()
    if not source_id or not source_url:
        raise ValueError("extended market provenance must be non-empty")
    context = _context_frame(security_context)
    normalised = _normalise_bars(
        bars,
        cutoff=min(formation, retrieved),
        expected_source_id=source_id,
        source_label="recovered yfinance artifact",
    )
    adjustment_modes = normalised.groupby("security_id")["adjust"].agg(
        lambda values: frozenset(values)
    )
    required_modes = frozenset({"all", "none"})
    if adjustment_modes.empty or not adjustment_modes.map(
        lambda modes: modes == required_modes
    ).all():
        raise ValueError(
            "extended recovered signals require adjusted and nominal bars per identity"
        )
    bar_identities = normalised[["security_id", "ticker", "cik"]].drop_duplicates()
    identities = context[["security_id", "ticker", "cik"]].merge(
        bar_identities,
        on=["security_id", "ticker", "cik"],
        how="inner",
        validate="one_to_one",
    )
    if len(identities) != len(context):
        raise ValueError("extended market context is not fully covered by recovered bars")
    current_period = formation.tz_convert(None).to_period("M") - 1
    monthly = _monthly_panel(normalised, context, current_period=current_period)
    current = monthly.loc[monthly["month"].eq(current_period)].copy()

    if not current.empty:
        current["size_rank"] = current["market_cap"].rank(pct=True, method="average")
        current["age_months"] = [
            (
                (current_period.year - first.year) * 12
                + current_period.month
                - first.month
                + 1
            )
            if not pd.isna(first)
            else np.nan
            for first in pd.to_datetime(current["first_observed"], errors="coerce", utc=True)
        ]
        current["age_rank"] = np.nan
        age_eligible = (
            current["age_months"].ge(12)
            & current["nominal_close"].ge(5.0)
        )
        current.loc[age_eligible, "age_rank"] = current.loc[
            age_eligible, "age_months"
        ].rank(pct=True, method="average")
        current["industry_size_rank"] = current.groupby("industry_group")[
            "market_cap"
        ].rank(pct=True, method="average")
        industry_momentum: dict[str, float] = {}
        industry_big_return: dict[str, float] = {}
        for industry, group in current.groupby("industry_group"):
            if not str(industry).strip():
                continue
            valid_momentum = group.loc[
                group["momentum_5_lags"].notna() & group["market_cap"].gt(0)
            ]
            if not valid_momentum.empty:
                industry_momentum[str(industry)] = float(
                    np.average(
                        valid_momentum["momentum_5_lags"],
                        weights=valid_momentum["market_cap"],
                    )
                )
            big = group.loc[
                group["industry_size_rank"].gt(0.70) & group["return"].notna()
            ]
            if not big.empty:
                industry_big_return[str(industry)] = float(big["return"].mean())
    else:
        industry_momentum = {}
        industry_big_return = {}
    current_by_id = current.set_index("security_id", drop=False)

    liquidity_values = _beta_liquidity_values(
        monthly,
        ff3_monthly,
        pastor_stambaugh,
        current_period=current_period,
    )
    trend_values = _trend_factor_values(
        normalised,
        context,
        current_period=current_period,
    )
    rows: list[dict[str, Any]] = []
    for identity in identities.itertuples(index=False):
        latest = (
            current_by_id.loc[identity.security_id]
            if identity.security_id in current_by_id.index
            else None
        )
        if isinstance(latest, pd.DataFrame):
            raise ValueError("extended market panel has duplicate current identities")
        available_at = None if latest is None else latest["available_at"]
        period_end = None if latest is None else latest["period_end"]
        observations = 0 if latest is None else int(
            monthly["security_id"].eq(identity.security_id).sum()
        )
        cap = None if latest is None else latest["market_cap"]
        size_value = (
            float(np.log(cap))
            if cap is not None and np.isfinite(cap) and float(cap) > 0
            else None
        )
        firm_age_value = None
        ind_mom_value = None
        ind_ret_big_value = None
        std_turn_value = None
        volmkt_value = None
        if latest is not None:
            industry = str(latest["industry_group"])
            if (
                pd.notna(latest["age_months"])
                and float(latest["age_months"]) >= 12
                and float(latest["nominal_close"]) >= 5.0
                and float(latest["age_rank"]) <= 0.20
                and pd.notna(latest["momentum_5_lags"])
            ):
                firm_age_value = float(latest["momentum_5_lags"])
            ind_mom_value = industry_momentum.get(industry)
            if float(latest["industry_size_rank"]) < 0.70:
                ind_ret_big_value = industry_big_return.get(industry)
            if float(latest["size_rank"]) <= 0.60 and pd.notna(latest["std_turn_value"]):
                std_turn_value = float(latest["std_turn_value"])
            if pd.notna(latest["volmkt_value"]):
                volmkt_value = float(latest["volmkt_value"])

        common_source_id = source_id
        common_source_url = source_url
        common_caveat = (
            "Official OpenAP formula reconstructed from existing private artifacts; "
            "current identities, SEC two-digit SIC, shares and market values are not "
            "a historical CRSP/FF48 point-in-time panel"
        )
        for signal, value, formula_id, reason in (
            (
                "FirmAgeMom",
                firm_age_value,
                "openap_youngest_quintile_five_lag_momentum",
                "not_youngest_quintile_or_insufficient_age_momentum",
            ),
            (
                "IndMom",
                ind_mom_value,
                "openap_current_industry_cap_weighted_five_lag_momentum",
                "current_industry_or_momentum_unavailable",
            ),
            (
                "IndRetBig",
                ind_ret_big_value,
                "openap_current_industry_top30pct_mean_return",
                "issuer_is_large_or_industry_big_return_unavailable",
            ),
            (
                "Size",
                size_value,
                "openap_log_current_issuer_market_cap",
                "current_issuer_market_cap_unavailable",
            ),
            (
                "VolMkt",
                volmkt_value,
                "openap_12m_mean_dollar_volume_over_current_market_cap",
                "insufficient_volume_or_market_cap_history",
            ),
            (
                "std_turn",
                std_turn_value,
                "openap_36m_turnover_std_min24_small60pct",
                "insufficient_turnover_history_or_large_size_quintile",
            ),
        ):
            rows.append(
                _row(
                    identity,
                    signal=signal,
                    value=value,
                    formation=formation,
                    retrieved=retrieved,
                    period_end=period_end,
                    available_at=available_at,
                    observation_count=observations,
                    current=True,
                    reason=reason,
                    source_id=common_source_id,
                    source_url=common_source_url,
                    formula_id=formula_id,
                    caveat=common_caveat,
                )
            )
        liquidity = liquidity_values.get(identity.security_id, {})
        rows.append(
            _row(
                identity,
                signal="BetaLiquidityPS",
                value=liquidity.get("value"),
                formation=formation,
                retrieved=retrieved,
                period_end=liquidity.get("period_end"),
                available_at=liquidity.get("available_at"),
                observation_count=int(liquidity.get("observation_count", 0)),
                current=bool(liquidity.get("current", False)),
                reason=str(liquidity.get("reason", "factor_inputs_unavailable")),
                source_id=f"{source_id}|kenneth_french|pastor_stambaugh",
                source_url=(
                    f"{source_url}|{KENNETH_FRENCH_MONTHLY_URL}|"
                    f"{PASTOR_STAMBAUGH_URL}"
                ),
                formula_id="openap_60m_four_factor_ps_innovation_beta_min36",
                caveat=(
                    "Official liquidity innovation series and formula; recovered "
                    "returns and current identities replace CRSP, and the published "
                    "factor is not current after December 2025"
                ),
            )
        )
        trend = trend_values.get(identity.security_id, {})
        rows.append(
            _row(
                identity,
                signal="TrendFactor",
                value=trend.get("value"),
                formation=formation,
                retrieved=retrieved,
                period_end=trend.get("period_end", period_end),
                available_at=trend.get("available_at", available_at),
                observation_count=int(trend.get("observation_count", 0)),
                current=bool(trend.get("current", False)),
                reason=str(trend.get("reason", "trend_inputs_unavailable")),
                source_id=common_source_id,
                source_url=common_source_url,
                formula_id="openap_11ma_cross_sectional_regression_12m_lagged_betas",
                caveat=common_caveat,
            )
        )
    result = pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)
    expected_rows = len(identities) * len(RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS)
    if (
        len(result) != expected_rows
        or set(result["signal"]) != set(RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS)
        or result["strict_score_eligible"].ne(False).any()  # noqa: E712
    ):
        raise RuntimeError("extended recovered signal output violates its frozen contract")
    return result


__all__ = [
    "PASTOR_STAMBAUGH_URL",
    "RECOVERED_YFINANCE_EXTENDED_FORMULA_SHA256",
    "RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS",
    "calculate_recovered_yfinance_extended_signals",
    "parse_pastor_stambaugh_liquidity",
]
