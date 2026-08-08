"""Causal historical reconstruction and behavior audit for the canonical 44 proxies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from aurora.core.execution_policy import require_github_execution
from aurora.research.openap_93.official_portfolio_similarity import (
    build_official_long_short_spreads,
    build_proxy_spreads,
    compare_official_and_proxy,
    normalise_official_long_short,
)
from aurora.research.openap_proxy_real_correlation import CANONICAL_PROXY_SIGNALS


HISTORICALLY_RECONSTRUCTED_PROXY_SIGNALS = (
    "AgeIPO",
    "DivInit",
    "DivOmit",
    "DivSeason",
    "IndIPO",
    "TrendFactor",
    "VolSD",
    "VolumeTrend",
)

TREND_WINDOWS = (3, 5, 10, 20, 50, 100, 200, 400, 600, 800, 1000)

NOT_RECONSTRUCTIBLE_REASONS = {
    "AOP": "historical point-in-time analyst forecasts and long-term growth are unavailable",
    "AnalystRevision": "historical point-in-time analyst revision panel is unavailable",
    "CPVolSpread": "historical option chain by strike and maturity is unavailable",
    "ChForecastAccrual": "historical point-in-time analyst forecast panel is unavailable",
    "ChangeInRecommendation": "historical point-in-time recommendation history is unavailable",
    "CredRatDG": "historical issuer credit-rating changes are unavailable",
    "DelBreadth": "complete point-in-time institutional holdings and identifier history are unavailable",
    "DownRecomm": "historical point-in-time downgrade recommendations are unavailable",
    "EarningsForecastDisparity": "historical analyst forecast distribution is unavailable",
    "ExclExp": "historical forecast EPS excluding extraordinary items is unavailable",
    "FEPS": "historical point-in-time forecast EPS is unavailable",
    "ForecastDispersion": "historical analyst dispersion and analyst counts are unavailable",
    "IO_ShortInterest": "joint historical institutional ownership and short-interest panel is unavailable",
    "NOA": "historical canonical financing components have not been reconstructed from SEC taxonomy",
    "OptionVolume1": "historical option volume by contract is unavailable",
    "OptionVolume2": "historical option volume by contract is unavailable",
    "RDIPO": "historical IPO cohort and causal R&D panel is incomplete",
    "RDcap": "official recursively capitalized historical R&D stock is unavailable",
    "REV6": "historical point-in-time analyst revision history is unavailable",
    "RIO_Disp": "complete point-in-time institutional holdings history is unavailable",
    "RIO_MB": "complete point-in-time institutional holdings history is unavailable",
    "RIO_Turnover": "complete point-in-time institutional holdings history is unavailable",
    "RIO_Volatility": "complete point-in-time institutional holdings history is unavailable",
    "RIVolSpread": "historical option-implied volatility and institutional holdings are unavailable",
    "Recomm_ShortInterest": "joint recommendation and short-interest history is unavailable",
    "ShareVol": "historical point-in-time shares outstanding needed for turnover are unavailable",
    "SmileSlope": "historical option smile by strike and maturity is unavailable",
    "Spinoff": "complete point-in-time spinoff event history is unavailable",
    "UpRecomm": "historical point-in-time upgrade recommendations are unavailable",
    "dCPVolSpread": "historical option chain by strike and maturity is unavailable",
    "dNoa": "lagged canonical net operating assets have not been reconstructed",
    "dVolCall": "historical call-option volume by contract is unavailable",
    "fgr5yrLag": "historical point-in-time five-year analyst growth forecasts are unavailable",
    "sfe": "historical point-in-time forecast errors are unavailable",
    "skew1": "historical option-implied skew by strike and maturity is unavailable",
    "std_turn": "historical point-in-time shares outstanding needed for turnover are unavailable",
}


def _rolling_ols_slope(values: pd.Series, months: pd.Series) -> float:
    y = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    x = pd.to_numeric(months, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 30:
        return np.nan
    x = x[valid]
    y = y[valid]
    centered = x - x.mean()
    denominator = float(np.dot(centered, centered))
    if denominator <= 0:
        return np.nan
    return float(np.dot(centered, y - y.mean()) / denominator)


def _price_signal_monthly(group: pd.DataFrame) -> pd.DataFrame:
    """Build the official monthly inputs, not the final cross-sectional signal."""

    daily = group.sort_values("date").copy()
    close = pd.to_numeric(daily["adj_close"], errors="coerce")
    volume = pd.to_numeric(daily["volume"], errors="coerce")
    for length in TREND_WINDOWS:
        # OpenAP uses partial moving-average windows and requires all 11 ratios
        # only when producing the final TrendFactor value.
        daily[f"A_{length}"] = close.rolling(length, min_periods=1).mean() / close
    daily["completed_month"] = daily["date"].dt.to_period("M").dt.to_timestamp()
    month_end = daily.groupby("completed_month", as_index=False).tail(1)[
        ["completed_month", *[f"A_{length}" for length in TREND_WINDOWS]]
    ].copy()
    monthly_volume = (
        pd.DataFrame({"completed_month": daily["completed_month"], "volume": volume})
        .groupby("completed_month", as_index=False)["volume"]
        .sum(min_count=1)
    )
    result = month_end.merge(monthly_volume, on="completed_month", how="left")
    result["VolSD"] = result["volume"].rolling(36, min_periods=24).std(ddof=1)
    month_number = result["completed_month"].dt.year * 12 + result["completed_month"].dt.month - 1
    result["VolumeTrend"] = [
        (
            _rolling_ols_slope(
                result["volume"].iloc[max(0, index - 59): index + 1],
                month_number.iloc[max(0, index - 59): index + 1],
            )
            / result["volume"].iloc[max(0, index - 59): index + 1].mean()
        )
        if result["volume"].iloc[max(0, index - 59): index + 1].notna().sum() >= 30
        and result["volume"].iloc[max(0, index - 59): index + 1].mean() != 0
        else np.nan
        for index in range(len(result))
    ]
    return result


def _apply_volume_trend_trim(monthly: pd.DataFrame) -> pd.DataFrame:
    """Apply OpenAP's cross-sectional 1/99 trim month by month."""

    result = monthly.copy()
    for _, index in result.groupby("completed_month").groups.items():
        values = pd.to_numeric(result.loc[index, "VolumeTrend"], errors="coerce")
        finite = values.dropna()
        if len(finite) < 2:
            continue
        low = finite.quantile(0.01, interpolation="nearest")
        high = finite.quantile(0.99, interpolation="nearest")
        outside = values.lt(low) | values.gt(high)
        result.loc[values.index[outside], "VolumeTrend"] = np.nan
    return result


def _build_trend_factor(monthly: pd.DataFrame) -> pd.Series:
    """Reproduce OpenAP's lagged cross-sectional moving-average model."""

    feature_columns = [f"A_{length}" for length in TREND_WINDOWS]
    frame = monthly.sort_values(["completed_month", "symbol"]).copy()
    next_return = frame[["symbol", "completed_month", "month_return"]].copy()
    next_return["completed_month"] = next_return["completed_month"] - pd.offsets.MonthBegin(1)
    next_return = next_return.rename(columns={"month_return": "future_return"})
    frame = frame.merge(next_return, on=["symbol", "completed_month"], how="left")
    beta_rows: list[dict[str, object]] = []
    for month, group in frame.groupby("completed_month", sort=True):
        sample = group.dropna(subset=["future_return", *feature_columns])
        if len(sample) <= len(feature_columns) + 1:
            continue
        x = sample[feature_columns].to_numpy(dtype=float)
        x = np.column_stack([x, np.ones(len(x), dtype=float)])
        y = sample["future_return"].to_numpy(dtype=float)
        beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
        if rank < x.shape[1]:
            continue
        row: dict[str, object] = {"completed_month": month}
        row.update({column: float(beta[i]) for i, column in enumerate(feature_columns)})
        beta_rows.append(row)
    if not beta_rows:
        return pd.Series(np.nan, index=monthly.index, dtype=float)
    betas = pd.DataFrame(beta_rows).sort_values("completed_month").set_index("completed_month")
    expected = betas[feature_columns].shift(1).rolling(12, min_periods=1).mean()
    expected = expected.add_prefix("beta_").reset_index()
    scored = frame.merge(expected, on="completed_month", how="left", sort=False)
    products = [
        pd.to_numeric(scored[column], errors="coerce")
        * pd.to_numeric(scored[f"beta_{column}"], errors="coerce")
        for column in feature_columns
    ]
    product_frame = pd.concat(products, axis=1)
    value = product_frame.sum(axis=1, min_count=len(feature_columns))
    keyed = pd.DataFrame(
        {
            "symbol": scored["symbol"],
            "completed_month": scored["completed_month"],
            "TrendFactor": value,
        }
    )
    original = monthly[["symbol", "completed_month"]].reset_index().merge(
        keyed, on=["symbol", "completed_month"], how="left"
    )
    return original.set_index("index")["TrendFactor"].reindex(monthly.index)


def _omission(paid: pd.Series, completed: pd.Period, window: int, payer_window: int) -> bool:
    recent = paid.loc[(paid.index > completed - window) & (paid.index <= completed)]
    previous = paid.loc[(paid.index > completed - 2 * window) & (paid.index <= completed - window)]
    payer = paid.loc[
        (paid.index > completed - payer_window - window)
        & (paid.index <= completed - window)
    ]
    return (
        len(recent) >= window
        and recent.sum() == 0
        and previous.sum() > 0
        and payer.sum() >= max(1, payer_window // window)
    )


def _event_signal_monthly(group: pd.DataFrame) -> pd.DataFrame:
    daily = group.sort_values("date").copy()
    daily["month"] = daily["date"].dt.to_period("M")
    observed = daily.groupby("month")["dividends"].sum(min_count=1)
    months = pd.period_range(observed.index.min(), observed.index.max(), freq="M")
    dividend = observed.reindex(months).fillna(0.0)
    paid = dividend.gt(0).astype(int)
    initiation_event = pd.Series(False, index=months)
    for month in months:
        prior = dividend.loc[(dividend.index >= month - 24) & (dividend.index < month)]
        initiation_event.loc[month] = bool(
            dividend.loc[month] > 0 and len(prior) >= 24 and prior.sum() == 0
        )
    initiated_last_six = initiation_event.astype(int).rolling(6, min_periods=1).max().astype(float)
    first_month = daily["date"].min().to_period("M")
    rows: list[dict[str, object]] = []
    for month in months:
        trailing = paid.loc[(paid.index >= month - 11) & (paid.index <= month)]
        pay_months = paid.loc[paid.gt(0)].index
        offsets = [month.ordinal - period.ordinal for period in pay_months]
        age = month.ordinal - first_month.ordinal
        rows.append(
            {
                "completed_month": month.to_timestamp(),
                "AgeIPO": float(age) if 3 <= age <= 36 else np.nan,
                "IndIPO": float(3 <= age <= 36),
                "DivInit": initiated_last_six.loc[month] if age >= 24 else np.nan,
                "DivOmit": float(
                    _omission(paid, month, 3, 18)
                    or _omission(paid, month, 6, 18)
                    or _omission(paid, month, 12, 24)
                ) if age >= 24 else np.nan,
                "DivSeason": float(any(offset in {2, 5, 8, 11} for offset in offsets))
                if trailing.sum() > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_price_event_proxy_panel(prices_daily: pd.DataFrame) -> pd.DataFrame:
    """Build eight causal proxy series and attach only the following month's return."""

    required = {"symbol", "date", "adj_close", "volume", "dividends"}
    missing = required.difference(prices_daily.columns)
    if missing:
        raise ValueError(f"prices_daily is missing columns: {sorted(missing)}")
    prices = prices_daily.copy()
    prices["symbol"] = prices["symbol"].astype("string").str.upper().str.strip()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["adj_close"] = pd.to_numeric(prices["adj_close"], errors="coerce")
    prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce")
    prices["dividends"] = pd.to_numeric(prices["dividends"], errors="coerce").fillna(0.0)
    prices = prices.dropna(subset=["symbol", "date", "adj_close", "volume"])
    monthly_parts: list[pd.DataFrame] = []
    for symbol, group in prices.groupby("symbol", sort=False):
        price_monthly = _price_signal_monthly(group)
        event_monthly = _event_signal_monthly(group)
        monthly_close = (
            group.set_index("date")["adj_close"].resample("ME").last().dropna()
        )
        realized = monthly_close.pct_change(fill_method=None)
        realized.index = realized.index.to_period("M").to_timestamp()
        wide = price_monthly.merge(event_monthly, on="completed_month", how="outer")
        wide["symbol"] = symbol
        wide["month_return"] = wide["completed_month"].map(realized)
        monthly_parts.append(wide)
    if not monthly_parts:
        return pd.DataFrame(
            columns=[
                "symbol", "completed_month", "signal_cutoff", "available_at",
                "formation_month", "realized_month_return", "signal", "proxy_value",
            ]
        )
    monthly = pd.concat(monthly_parts, ignore_index=True)
    monthly = _apply_volume_trend_trim(monthly)
    monthly["TrendFactor"] = _build_trend_factor(monthly)
    parts: list[pd.DataFrame] = []
    for symbol, wide in monthly.groupby("symbol", sort=False):
        wide = wide.copy()
        wide["signal_cutoff"] = wide["completed_month"] + pd.offsets.MonthEnd(0)
        wide["available_at"] = wide["signal_cutoff"]
        wide["formation_month"] = wide["completed_month"] + pd.offsets.MonthBegin(1)
        next_return = monthly.loc[monthly["symbol"].eq(symbol)].set_index("completed_month")["month_return"]
        wide["realized_month_return"] = wide["formation_month"].map(next_return)
        long = wide.melt(
            id_vars=[
                "symbol", "completed_month", "signal_cutoff", "available_at",
                "formation_month", "realized_month_return",
            ],
            value_vars=list(HISTORICALLY_RECONSTRUCTED_PROXY_SIGNALS),
            var_name="signal",
            value_name="proxy_value",
        )
        parts.append(long)
    result = pd.concat(parts, ignore_index=True)
    result["proxy_value"] = pd.to_numeric(result["proxy_value"], errors="coerce")
    return result.sort_values(["signal", "formation_month", "symbol"]).reset_index(drop=True)


def build_reconstruction_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal in CANONICAL_PROXY_SIGNALS:
        part = panel.loc[panel["signal"].eq(signal)] if not panel.empty else pd.DataFrame()
        finite = pd.to_numeric(part.get("proxy_value"), errors="coerce").notna() if not part.empty else pd.Series(dtype=bool)
        reconstructed = signal in HISTORICALLY_RECONSTRUCTED_PROXY_SIGNALS
        rows.append(
            {
                "signal": signal,
                "status": "reconstructed" if reconstructed and finite.any() else "not_reconstructible",
                "observations": int(finite.sum()),
                "months": int(part.loc[finite, "formation_month"].nunique()) if finite.any() else 0,
                "symbols": int(part.loc[finite, "symbol"].nunique()) if finite.any() else 0,
                "reason": "" if reconstructed and finite.any() else NOT_RECONSTRUCTIBLE_REASONS.get(
                    signal, "no historical causal implementation with the available free inputs"
                ),
            }
        )
    return pd.DataFrame(rows)


def _load_prices(database: str | Path) -> pd.DataFrame:
    con = duckdb.connect(str(database), read_only=True)
    try:
        return con.execute(
            """
            SELECT p.symbol, p.date, p.adj_close, p.volume, coalesce(p.dividends, 0.0) AS dividends
            FROM prices_daily_clean p
            JOIN security_master s USING(symbol)
            WHERE coalesce(s.ranking_eligible, false)
            ORDER BY p.symbol, p.date
            """
        ).df()
    finally:
        con.close()


def run_proxy44_historical(
    *,
    base_database: str | Path,
    official_long_short: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    require_github_execution("OpenAP canonical 44 proxy historical audit")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    panel = build_price_event_proxy_panel(_load_prices(base_database))
    coverage = build_reconstruction_coverage(panel)
    official = normalise_official_long_short(
        pd.read_csv(official_long_short), signal_names=CANONICAL_PROXY_SIGNALS
    )
    official_spreads = build_official_long_short_spreads(official)
    proxy_spreads = build_proxy_spreads(
        panel, pd.DataFrame(), signal_names=CANONICAL_PROXY_SIGNALS
    )
    joined, similarity = compare_official_and_proxy(
        official_spreads, proxy_spreads, signal_names=CANONICAL_PROXY_SIGNALS
    )
    all_period = similarity.loc[similarity["period"].eq("all")].copy()
    final = coverage.merge(all_period, on="signal", how="left", suffixes=("_reconstruction", "_comparison"))
    final["measurement_type"] = np.where(
        pd.to_numeric(final["months_comparison"], errors="coerce").fillna(0).ge(12),
        "portfolio_behavior_correlation",
        "not_measured",
    )
    panel.to_parquet(output / "openap_proxy44_historical_panel.parquet", index=False, compression="zstd")
    coverage.to_csv(output / "openap_proxy44_reconstruction_coverage.csv", index=False)
    proxy_spreads.to_csv(output / "openap_proxy44_proxy_spreads.csv", index=False)
    joined.to_csv(output / "openap_proxy44_joined_monthly.csv", index=False)
    similarity.to_csv(output / "openap_proxy44_similarity_all_periods.csv", index=False)
    final.to_csv(output / "openap_proxy44_correlation.csv", index=False)
    payload = {
        "canonical_proxy_count": len(CANONICAL_PROXY_SIGNALS),
        "reconstructed_count": int(coverage["status"].eq("reconstructed").sum()),
        "not_reconstructible_count": int(coverage["status"].eq("not_reconstructible").sum()),
        "measured_count": int(final["measurement_type"].eq("portfolio_behavior_correlation").sum()),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "backtest_enabled": False,
        "identity_claimed": False,
        "survivorship_caveat": "Aurora free price universe is current-security based",
        "correlation_level": "monthly long-short portfolio behavior, not stock-level identity",
    }
    (output / "openap_proxy44_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload
