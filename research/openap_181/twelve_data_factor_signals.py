"""OpenAP market signals using Twelve Data bars and free French factors.

The calculations in this module are intentionally non-strict.  Twelve Data
does not provide CRSP identifiers or CRSP return semantics, and the current
SEC security universe is not a point-in-time CRSP universe.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .twelve_data_market_batch import TIME_SERIES_ENDPOINT
from .twelve_data_market_signals import (
    _OUTPUT_COLUMNS,
    _daily_return_panel,
    _monthly_return_panel,
    _normalise_bars,
    _timestamp,
)


KENNETH_FRENCH_DAILY_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_Factors_daily_CSV.zip"
)
KENNETH_FRENCH_MONTHLY_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_Factors_CSV.zip"
)

TWELVE_DATA_FACTOR_SIGNAL_TARGETS = (
    "Beta",
    "BetaFP",
    "CoskewACX",
    "Coskewness",
    "IdioVol3F",
    "IdioVolAHT",
    "PriceDelayRsq",
    "PriceDelaySlope",
    "PriceDelayTstat",
    "ResidualMomentum",
    "ReturnSkew3F",
)
TWELVE_DATA_FACTOR_FORMULA_SHA256 = {
    "Beta": "6929bf9f18bf8b0a36a6b79bca80cdb1b485c461ad574ef103eda4736c8a1be3",
    "BetaFP": "8aa7d340f706d19a73331b1fddbf5e06e59e141e85bf89056e049870421e2241",
    "CoskewACX": (
        "81cff4979e62361a896a5b61b61a9778b7abf67c14a51bb2ef3bfebc7b273998"
    ),
    "Coskewness": (
        "1deefcb70f9a3fbb9fec2816de5035f159e57790c0f23354e1047465f1082979"
    ),
    "IdioVol3F": (
        "6705b51935883db5726d363ad8692067b3ee9c37637b3e0b54f4fcd7890e059c"
    ),
    "IdioVolAHT": (
        "c57894a41caa3389eb83db8053445b03cfa70a75422a7ea189ad10fc2bae5994"
    ),
    "PriceDelayRsq": (
        "a003da84b08f46f78598f076c50959128016cb402a9235b4dabeb0341ac08fef"
    ),
    "PriceDelaySlope": (
        "a003da84b08f46f78598f076c50959128016cb402a9235b4dabeb0341ac08fef"
    ),
    "PriceDelayTstat": (
        "a003da84b08f46f78598f076c50959128016cb402a9235b4dabeb0341ac08fef"
    ),
    "ResidualMomentum": (
        "1f1c9a114c36ee325bc2f679933ad5b1760ccac0816ec437246eb986c31f3143"
    ),
    "ReturnSkew3F": (
        "6705b51935883db5726d363ad8692067b3ee9c37637b3e0b54f4fcd7890e059c"
    ),
}
_FACTOR_COLUMNS = frozenset({"date", "mktrf", "smb", "hml", "rf"})
_SOURCE_ID = "twelve_data_basic|kenneth_french"
_SOURCE_URL = (
    f"{TIME_SERIES_ENDPOINT}|{KENNETH_FRENCH_DAILY_URL}|"
    f"{KENNETH_FRENCH_MONTHLY_URL}"
)


def _require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    label: str,
) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def _normalise_factors(
    factors: pd.DataFrame,
    *,
    cutoff: pd.Timestamp,
    label: str,
) -> pd.DataFrame:
    _require_columns(factors, _FACTOR_COLUMNS, label)
    frame = factors.loc[:, sorted(_FACTOR_COLUMNS)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].dt.tz is not None:
        frame["date"] = frame["date"].dt.tz_convert(None)
    for column in ("mktrf", "smb", "hml", "rf"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    cutoff_naive = cutoff.tz_convert(None)
    invalid = (
        frame["date"].isna()
        | frame["date"].gt(cutoff_naive)
        | ~np.isfinite(frame[["mktrf", "smb", "hml", "rf"]]).all(axis=1)
    )
    frame = frame.loc[~invalid].sort_values("date").reset_index(drop=True)
    if frame.empty:
        raise ValueError(f"{label} has no finite causal rows")
    if frame["date"].duplicated().any():
        raise ValueError(f"{label} contains duplicate dates")
    return frame


def _ols(
    y: np.ndarray,
    x: np.ndarray,
    *,
    minimum: int,
) -> tuple[np.ndarray, float, np.ndarray, int] | None:
    y_array = np.asarray(y, dtype=float)
    x_array = np.asarray(x, dtype=float)
    if x_array.ndim == 1:
        x_array = x_array.reshape(-1, 1)
    valid = np.isfinite(y_array) & np.isfinite(x_array).all(axis=1)
    y_valid = y_array[valid]
    x_valid = x_array[valid]
    if len(y_valid) < minimum or len(y_valid) <= x_valid.shape[1] + 1:
        return None
    design = np.column_stack([np.ones(len(y_valid), dtype=float), x_valid])
    if np.linalg.matrix_rank(design) != design.shape[1]:
        return None
    coefficients, *_ = np.linalg.lstsq(design, y_valid, rcond=None)
    residuals = y_valid - design @ coefficients
    total = float(np.square(y_valid - y_valid.mean()).sum())
    r_squared = (
        float(1.0 - np.square(residuals).sum() / total)
        if total > 0.0
        else float("nan")
    )
    return coefficients, r_squared, residuals, len(y_valid)


def _t_values(
    coefficients: np.ndarray,
    residuals: np.ndarray,
    x: np.ndarray,
) -> np.ndarray | None:
    design = np.column_stack(
        [np.ones(len(x), dtype=float), np.asarray(x, dtype=float)]
    )
    degrees = len(design) - design.shape[1]
    if degrees <= 0:
        return None
    try:
        covariance = (
            float(np.square(residuals).sum())
            / float(degrees)
            * np.linalg.inv(design.T @ design)
        )
    except np.linalg.LinAlgError:
        return None
    standard_errors = np.sqrt(np.diag(covariance))
    if (
        len(standard_errors) != len(coefficients)
        or not np.isfinite(standard_errors).all()
        or np.any(standard_errors <= 0.0)
    ):
        return None
    return coefficients / standard_errors


def _identity_rows(normalised: pd.DataFrame) -> pd.DataFrame:
    return normalised.sort_values("date").drop_duplicates(
        "security_id", keep="last"
    )[["security_id", "ticker", "cik"]]


def _record(
    identity: Any,
    *,
    signal: str,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
    value: float | None,
    period_end: object,
    available_at: object,
    observation_count: int,
    formula_id: str,
    missing_reason: str,
    caveat: str,
) -> dict[str, Any]:
    finite = value is not None and np.isfinite(float(value))
    period = pd.to_datetime(period_end, errors="coerce")
    available = pd.to_datetime(available_at, errors="coerce", utc=True)
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
        "fidelity_class": "reconstructed" if finite else "unavailable",
        "current_usable": bool(finite),
        "source_id": _SOURCE_ID,
        "source_url": _SOURCE_URL,
        "formula_id": formula_id,
        "formula_sha256": TWELVE_DATA_FACTOR_FORMULA_SHA256[signal],
        "observation_count": int(observation_count),
        "strict_score_eligible": False,
        "reason_if_missing": "" if finite else missing_reason,
        "caveat": caveat,
    }


def _monthly_inputs(
    normalised: pd.DataFrame,
    *,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    parts = [
        _monthly_return_panel(security, formation=formation)
        for _, security in normalised.groupby("security_id", sort=True)
    ]
    parts = [part for part in parts if not part.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _beta_rows(
    normalised: pd.DataFrame,
    ff3_monthly: pd.DataFrame,
    *,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
) -> list[dict[str, Any]]:
    identities = _identity_rows(normalised)
    monthly = _monthly_inputs(normalised, formation=formation)
    if monthly.empty:
        factor = pd.DataFrame(columns=["month", "rf", "ewretd"])
    else:
        market = monthly.groupby("month", as_index=False)["return"].mean().rename(
            columns={"return": "ewretd"}
        )
        factor = ff3_monthly.copy()
        factor["month"] = factor["date"].dt.to_period("M")
        factor = factor[["month", "rf"]].merge(
            market,
            on="month",
            how="inner",
            validate="one_to_one",
        )
    rows: list[dict[str, Any]] = []
    for identity in identities.itertuples(index=False):
        security = monthly.loc[
            monthly.get("security_id", pd.Series(dtype=str)).eq(identity.security_id)
        ]
        aligned = (
            security.merge(factor, on="month", how="inner", validate="many_to_one")
            .sort_values("month")
            .dropna(subset=["return", "rf", "ewretd"])
            .tail(60)
        )
        fitted = _ols(
            (aligned["return"] - aligned["rf"]).to_numpy(dtype=float),
            (aligned["ewretd"] - aligned["rf"]).to_numpy(dtype=float),
            minimum=20,
        )
        beta = float(fitted[0][1]) if fitted is not None else None
        latest = aligned.iloc[-1] if not aligned.empty else None
        rows.append(
            _record(
                identity,
                signal="Beta",
                formation=formation,
                retrieved=retrieved,
                value=beta,
                period_end=None if latest is None else latest["period_end"],
                available_at=None if latest is None else latest["available_at"],
                observation_count=0 if fitted is None else fitted[3],
                formula_id="openap_capm_beta_60m_min20_equal_weight_market",
                missing_reason="insufficient_monthly_equal_weight_market_history",
                caveat=(
                    "Pinned OpenAP rolling formula reconstructed with the equal-"
                    "weighted return of the current Twelve Data universe; CRSP "
                    "membership, identifiers and return semantics remain unmatched"
                ),
            )
        )
    return rows


def _coskew_moment(
    stock: np.ndarray,
    market: np.ndarray,
    *,
    minimum: int,
) -> tuple[float | None, int]:
    stock_values = np.asarray(stock, dtype=float)
    market_values = np.asarray(market, dtype=float)
    valid = np.isfinite(stock_values) & np.isfinite(market_values)
    stock_values = stock_values[valid]
    market_values = market_values[valid]
    if len(stock_values) < minimum:
        return None, len(stock_values)
    stock_demeaned = stock_values - stock_values.mean()
    market_demeaned = market_values - market_values.mean()
    market_second = float(np.mean(np.square(market_demeaned)))
    denominator = float(
        np.sqrt(np.mean(np.square(stock_demeaned))) * market_second
    )
    if denominator <= 0.0 or not np.isfinite(denominator):
        return None, len(stock_values)
    value = float(
        np.mean(stock_demeaned * np.square(market_demeaned)) / denominator
    )
    return (value, len(stock_values)) if np.isfinite(value) else (None, len(stock_values))


def _adjusted_sample_skew(values: np.ndarray) -> float | None:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if len(array) < 3:
        return None
    standard_deviation = float(np.std(array, ddof=1))
    if standard_deviation <= 0.0:
        return None
    n = float(len(array))
    value = float(
        n
        / ((n - 1.0) * (n - 2.0))
        * np.sum(np.power((array - array.mean()) / standard_deviation, 3.0))
    )
    return value if np.isfinite(value) else None


def _residual_momentum_value(aligned: pd.DataFrame) -> tuple[float | None, int]:
    if len(aligned) < 47:
        return None, 0
    y = (aligned["return"] - aligned["rf"]).to_numpy(dtype=float)
    x = aligned[["mktrf", "hml", "smb"]].to_numpy(dtype=float)
    rolling_residuals: list[float] = []
    for end in range(36, len(aligned) + 1):
        fitted = _ols(y[end - 36 : end], x[end - 36 : end], minimum=36)
        rolling_residuals.append(
            float(fitted[2][-1]) if fitted is not None else float("nan")
        )
    prior = np.asarray(rolling_residuals[:-1], dtype=float)[-11:]
    prior = prior[np.isfinite(prior)]
    if len(prior) < 11:
        return None, len(prior)
    standard_deviation = float(np.std(prior, ddof=1))
    if standard_deviation <= 0.0:
        return None, len(prior)
    value = float(np.mean(prior) / standard_deviation)
    return (value, len(prior)) if np.isfinite(value) else (None, len(prior))


def _monthly_factor_rows(
    normalised: pd.DataFrame,
    ff3_monthly: pd.DataFrame,
    *,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
) -> list[dict[str, Any]]:
    identities = _identity_rows(normalised)
    monthly = _monthly_inputs(normalised, formation=formation)
    factors = ff3_monthly.copy()
    factors["month"] = factors["date"].dt.to_period("M")
    factors = factors[["month", "mktrf", "smb", "hml", "rf"]]
    formation_period = formation.tz_convert(None).to_period("M")
    first_coskew_month = formation_period - 60
    last_month = formation_period - 1
    rows: list[dict[str, Any]] = []
    for identity in identities.itertuples(index=False):
        security = monthly.loc[
            monthly.get("security_id", pd.Series(dtype=str)).eq(identity.security_id)
        ]
        aligned = (
            security.merge(factors, on="month", how="inner", validate="many_to_one")
            .sort_values("month")
            .dropna(subset=["return", "mktrf", "smb", "hml", "rf"])
        )
        coskew_window = aligned.loc[
            aligned["month"].between(first_coskew_month, last_month)
        ]
        coskewness, coskew_n = _coskew_moment(
            (coskew_window["return"] - coskew_window["rf"]).to_numpy(dtype=float),
            coskew_window["mktrf"].to_numpy(dtype=float),
            minimum=12,
        )
        residual_momentum, residual_n = _residual_momentum_value(aligned)
        latest = aligned.iloc[-1] if not aligned.empty else None
        for signal, value, observations, formula_id, missing_reason in (
            (
                "Coskewness",
                coskewness,
                coskew_n,
                "openap_monthly_coskewness_60_calendar_months_min12",
                "insufficient_monthly_coskewness_history",
            ),
            (
                "ResidualMomentum",
                residual_momentum,
                residual_n,
                "openap_ff3_36m_rolling_residual_prior11_mean_sd",
                "insufficient_monthly_ff3_residual_history",
            ),
        ):
            rows.append(
                _record(
                    identity,
                    signal=signal,
                    formation=formation,
                    retrieved=retrieved,
                    value=value,
                    period_end=None if latest is None else latest["period_end"],
                    available_at=None if latest is None else latest["available_at"],
                    observation_count=observations,
                    formula_id=formula_id,
                    missing_reason=missing_reason,
                    caveat=(
                        "Pinned OpenAP factor formula reconstructed from Twelve "
                        "Data returns and free French factors; CRSP identity and "
                        "return semantics remain unmatched"
                    ),
                )
            )
    return rows


def _beta_fp_value(aligned: pd.DataFrame) -> tuple[float | None, int]:
    if aligned.empty:
        return None, 0
    # The pinned Polars expressions run in parallel, so LogRet reads the
    # pre-alias raw stock return even though the same with_columns call also
    # aliases ret-rf as ret.  Preserve the executable source, not its comment.
    stock_log = np.log1p(aligned["return"].to_numpy(dtype=float))
    market_log = np.log1p(aligned["mktrf"].to_numpy(dtype=float))
    if len(stock_log) < 500:
        return None, len(stock_log)
    stock_vol = stock_log[-252:]
    market_vol = market_log[-252:]
    stock_vol = stock_vol[np.isfinite(stock_vol)]
    market_vol = market_vol[np.isfinite(market_vol)]
    if len(stock_vol) < 120 or len(market_vol) < 120:
        return None, min(len(stock_vol), len(market_vol))
    sd_stock = float(np.std(stock_vol, ddof=1))
    sd_market = float(np.std(market_vol, ddof=1))
    stock_three = stock_log[2:] + stock_log[1:-1] + stock_log[:-2]
    market_three = market_log[2:] + market_log[1:-1] + market_log[:-2]
    stock_three = stock_three[-1260:]
    market_three = market_three[-1260:]
    valid = np.isfinite(stock_three) & np.isfinite(market_three)
    stock_three = stock_three[valid]
    market_three = market_three[valid]
    if len(stock_three) < 500 or sd_market <= 0.0:
        return None, len(stock_three)
    std_stock_three = float(np.std(stock_three, ddof=1))
    std_market_three = float(np.std(market_three, ddof=1))
    if std_stock_three <= 0.0 or std_market_three <= 0.0:
        return None, len(stock_three)
    covariance = float(
        np.mean(stock_three * market_three)
        - np.mean(stock_three) * np.mean(market_three)
    )
    correlation = covariance / (std_stock_three * std_market_three)
    value = abs(correlation) * sd_stock / sd_market
    return (float(value), len(stock_three)) if np.isfinite(value) else (None, len(stock_three))


def _annual_delay_window(
    formation: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    formation_naive = formation.tz_convert(None)
    refresh_year = (
        formation_naive.year
        if formation_naive.month >= 7
        else formation_naive.year - 1
    )
    return (
        pd.Timestamp(refresh_year - 1, 7, 1),
        pd.Timestamp(refresh_year, 6, 30),
        pd.Timestamp(refresh_year, 7, 1, tz="UTC"),
    )


def _price_delay_values(
    aligned: pd.DataFrame,
    *,
    formation: pd.Timestamp,
) -> tuple[dict[str, float | None], int, object, object]:
    start, end, release = _annual_delay_window(formation)
    annual = aligned.loc[aligned["date"].between(start, end)].copy()
    required = ["return", "rf", "mktrf", "mkt_lag1", "mkt_lag2", "mkt_lag3", "mkt_lag4"]
    annual = annual.dropna(subset=required)
    empty = {
        "PriceDelayRsq": None,
        "PriceDelaySlope": None,
        "PriceDelayTstat": None,
    }
    if len(annual) < 26 or annual["date"].max().month != 6:
        return empty, len(annual), end, pd.NaT
    y = (annual["return"] - annual["rf"]).to_numpy(dtype=float)
    current_market = annual["mktrf"].to_numpy(dtype=float)
    unrestricted_x = annual[
        ["mktrf", "mkt_lag1", "mkt_lag2", "mkt_lag3", "mkt_lag4"]
    ].to_numpy(dtype=float)
    restricted = _ols(y, current_market, minimum=26)
    unrestricted = _ols(y, unrestricted_x, minimum=26)
    if restricted is None or unrestricted is None:
        return empty, len(annual), end, pd.NaT
    coefficients, unrestricted_r2, residuals, observations = unrestricted
    restricted_r2 = restricted[1]
    t_values = _t_values(coefficients, residuals, unrestricted_x)
    if (
        not np.isfinite(unrestricted_r2)
        or abs(unrestricted_r2) < 1e-12
        or t_values is None
    ):
        return empty, observations, end, pd.NaT
    lag_weights = np.arange(1.0, 5.0)
    slope_denominator = float(coefficients[1] + coefficients[2:6].sum())
    tstat_denominator = float(t_values[1] + t_values[2:6].sum())
    values = {
        "PriceDelayRsq": float(1.0 - restricted_r2 / unrestricted_r2),
        "PriceDelaySlope": (
            float(lag_weights @ coefficients[2:6] / slope_denominator)
            if abs(slope_denominator) >= 1e-12
            else None
        ),
        "PriceDelayTstat": (
            float(lag_weights @ t_values[2:6] / tstat_denominator)
            if abs(tstat_denominator) >= 1e-12
            else None
        ),
    }
    available = pd.to_datetime(annual["available_at"], errors="coerce", utc=True).max()
    if pd.isna(available) or available < release:
        available = release
    return values, observations, end, available


def _coskew_acx_rows(
    normalised: pd.DataFrame,
    ff3_daily: pd.DataFrame,
    *,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
) -> list[dict[str, Any]]:
    identities = _identity_rows(normalised)
    formation_period = formation.tz_convert(None).to_period("M")
    first_month = formation_period - 12
    last_month = formation_period - 1
    states: list[dict[str, Any]] = []
    for identity in identities.itertuples(index=False):
        security = normalised.loc[normalised["security_id"].eq(identity.security_id)]
        daily = _daily_return_panel(security, formation=formation)
        aligned = daily.merge(
            ff3_daily[["date", "mktrf", "rf"]],
            on="date",
            how="inner",
            validate="one_to_one",
        ).sort_values("date")
        window = aligned.loc[
            aligned["date"].dt.to_period("M").between(first_month, last_month)
        ].copy()
        stock_log_excess = (
            np.log1p(window["return"].to_numpy(dtype=float))
            - np.log1p(window["rf"].to_numpy(dtype=float))
        )
        market_log_excess = (
            np.log1p(
                (
                    window["mktrf"] + window["rf"]
                ).to_numpy(dtype=float)
            )
            - np.log1p(window["rf"].to_numpy(dtype=float))
        )
        value, observations = _coskew_moment(
            stock_log_excess,
            market_log_excess,
            minimum=1,
        )
        states.append(
            {
                "identity": identity,
                "value": value,
                "observation_count": observations,
                "period_end": (
                    window["date"].max() if not window.empty else pd.NaT
                ),
                "available_at": (
                    pd.to_datetime(
                        window["available_at"], errors="coerce", utc=True
                    ).max()
                    if not window.empty
                    else pd.NaT
                ),
            }
        )
    maximum_observations = max(
        (int(state["observation_count"]) for state in states),
        default=0,
    )
    rows: list[dict[str, Any]] = []
    for state in states:
        value = state["value"]
        if maximum_observations - int(state["observation_count"]) > 5:
            value = None
        rows.append(
            _record(
                state["identity"],
                signal="CoskewACX",
                formation=formation,
                retrieved=retrieved,
                value=value,
                period_end=state["period_end"],
                available_at=state["available_at"],
                observation_count=int(state["observation_count"]),
                formula_id="openap_acx_log_excess_coskew_12m_max_minus5",
                missing_reason="more_than_five_sessions_below_cross_section_max",
                caveat=(
                    "Pinned OpenAP 12-calendar-month ACX formula reconstructed "
                    "with Twelve Data returns and free French factors; the current "
                    "universe replaces the historical CRSP cross-section"
                ),
            )
        )
    return rows


def _daily_factor_rows(
    normalised: pd.DataFrame,
    ff3_daily: pd.DataFrame,
    *,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
) -> list[dict[str, Any]]:
    factors = ff3_daily.copy().sort_values("date")
    for lag in range(1, 5):
        factors[f"mkt_lag{lag}"] = factors["mktrf"].shift(lag)
    identities = _identity_rows(normalised)
    rows: list[dict[str, Any]] = []
    for identity in identities.itertuples(index=False):
        security = normalised.loc[normalised["security_id"].eq(identity.security_id)]
        daily = _daily_return_panel(security, formation=formation)
        aligned = daily.merge(factors, on="date", how="inner", validate="one_to_one").sort_values("date")
        completed_month = formation.tz_convert(None).to_period("M") - 1
        month_daily = aligned.loc[
            aligned["date"].dt.to_period("M").eq(completed_month)
        ].copy()
        ff3_fit = _ols(
            (month_daily["return"] - month_daily["rf"]).to_numpy(dtype=float),
            month_daily[["mktrf", "smb", "hml"]].to_numpy(dtype=float),
            minimum=15,
        )
        residuals = ff3_fit[2] if ff3_fit is not None else np.asarray([])
        idio_vol = (
            float(np.std(residuals, ddof=1))
            if len(residuals) >= 2
            else None
        )
        return_skew = _adjusted_sample_skew(residuals)
        month_end = month_daily["date"].max() if not month_daily.empty else pd.NaT
        month_available = (
            pd.to_datetime(
                month_daily["available_at"], errors="coerce", utc=True
            ).max()
            if not month_daily.empty
            else pd.NaT
        )
        for signal, value, formula_id in (
            (
                "IdioVol3F",
                idio_vol,
                "openap_ff3_daily_month_residual_std_min15",
            ),
            (
                "ReturnSkew3F",
                return_skew,
                "openap_ff3_daily_month_adjusted_residual_skew_min15",
            ),
        ):
            rows.append(
                _record(
                    identity,
                    signal=signal,
                    formation=formation,
                    retrieved=retrieved,
                    value=value,
                    period_end=month_end,
                    available_at=month_available,
                    observation_count=0 if ff3_fit is None else ff3_fit[3],
                    formula_id=formula_id,
                    missing_reason="insufficient_daily_ff3_month_observations",
                    caveat=(
                        "Pinned OpenAP monthly FF3 residual formula reconstructed "
                        "with Twelve Data returns; CRSP identity and return "
                        "semantics remain unmatched"
                    ),
                )
            )
        capm_window = aligned.dropna(
            subset=["return", "rf", "mktrf"]
        ).tail(252)
        capm_fit = _ols(
            (capm_window["return"] - capm_window["rf"]).to_numpy(dtype=float),
            capm_window["mktrf"].to_numpy(dtype=float),
            minimum=100,
        )
        capm_rmse: float | None = None
        if capm_fit is not None and capm_fit[3] > 2:
            capm_rmse = float(
                np.sqrt(
                    np.square(capm_fit[2]).sum()
                    / float(capm_fit[3] - 2)
                )
            )
        capm_latest = capm_window.iloc[-1] if not capm_window.empty else None
        rows.append(
            _record(
                identity,
                signal="IdioVolAHT",
                formation=formation,
                retrieved=retrieved,
                value=capm_rmse,
                period_end=None if capm_latest is None else capm_latest["date"],
                available_at=(
                    None if capm_latest is None else capm_latest["available_at"]
                ),
                observation_count=0 if capm_fit is None else capm_fit[3],
                formula_id="openap_capm_252_observation_rmse_min100",
                missing_reason="insufficient_daily_capm_history",
                caveat=(
                    "Pinned OpenAP 252-observation CAPM RMSE reconstructed with "
                    "Twelve Data returns; CRSP identity and return semantics "
                    "remain unmatched"
                ),
            )
        )
        beta_fp, beta_fp_n = _beta_fp_value(aligned)
        latest = aligned.iloc[-1] if not aligned.empty else None
        rows.append(
            _record(
                identity,
                signal="BetaFP",
                formation=formation,
                retrieved=retrieved,
                value=beta_fp,
                period_end=None if latest is None else latest["date"],
                available_at=None if latest is None else latest["available_at"],
                observation_count=beta_fp_n,
                formula_id="openap_beta_fp_252d_vol_1260d_three_day_corr",
                missing_reason="insufficient_daily_factor_history_for_beta_fp",
                caveat=(
                    "Pinned OpenAP position-based formula reconstructed with Twelve "
                    "Data returns; historical CRSP identity and return semantics "
                    "remain unmatched"
                ),
            )
        )
        delay_values, delay_n, delay_end, delay_available = _price_delay_values(
            aligned,
            formation=formation,
        )
        for signal in ("PriceDelayRsq", "PriceDelaySlope", "PriceDelayTstat"):
            rows.append(
                _record(
                    identity,
                    signal=signal,
                    formation=formation,
                    retrieved=retrieved,
                    value=delay_values[signal],
                    period_end=delay_end,
                    available_at=delay_available,
                    observation_count=delay_n,
                    formula_id={
                        "PriceDelayRsq": "openap_price_delay_d1_annual_four_market_lags",
                        "PriceDelaySlope": "openap_price_delay_d2_weighted_slope_ratio",
                        "PriceDelayTstat": "openap_price_delay_d3_weighted_tstat_ratio",
                    }[signal],
                    missing_reason="insufficient_complete_july_to_june_delay_window",
                    caveat=(
                        "Pinned OpenAP annual July-to-June regression reconstructed "
                        "with Twelve Data returns and free French market factors; "
                        "CRSP identity and return semantics remain unmatched"
                    ),
                )
            )
    return rows


def calculate_twelve_data_factor_signals(
    bars: pd.DataFrame,
    ff3_daily: pd.DataFrame,
    ff3_monthly: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate the prepared free-factor signals without strict promotion."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("market formation_at or retrieved_at is invalid")
    cutoff = min(formation, retrieved)
    normalised = _normalise_bars(bars, cutoff=cutoff)
    daily = _normalise_factors(
        ff3_daily,
        cutoff=cutoff,
        label="Kenneth French daily factors",
    )
    monthly = _normalise_factors(
        ff3_monthly,
        cutoff=cutoff,
        label="Kenneth French monthly factors",
    )
    rows = _beta_rows(
        normalised,
        monthly,
        formation=formation,
        retrieved=retrieved,
    )
    rows.extend(
        _daily_factor_rows(
            normalised,
            daily,
            formation=formation,
            retrieved=retrieved,
        )
    )
    rows.extend(
        _monthly_factor_rows(
            normalised,
            monthly,
            formation=formation,
            retrieved=retrieved,
        )
    )
    rows.extend(
        _coskew_acx_rows(
            normalised,
            daily,
            formation=formation,
            retrieved=retrieved,
        )
    )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


__all__ = [
    "KENNETH_FRENCH_DAILY_URL",
    "KENNETH_FRENCH_MONTHLY_URL",
    "TWELVE_DATA_FACTOR_FORMULA_SHA256",
    "TWELVE_DATA_FACTOR_SIGNAL_TARGETS",
    "calculate_twelve_data_factor_signals",
]
