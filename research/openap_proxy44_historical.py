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


def _rolling_volume_slope(volume: pd.Series, window: int = 252) -> pd.Series:
    y = np.log1p(pd.to_numeric(volume, errors="coerce"))
    index = pd.Series(np.arange(len(y), dtype=float), index=y.index)
    sum_y = y.rolling(window, min_periods=window).sum()
    sum_xy = (y * index).rolling(window, min_periods=window).sum()
    end = index
    start = index - window + 1.0
    mean_x = (start + end) / 2.0
    denominator = window * (window**2 - 1.0) / 12.0
    return (sum_xy - mean_x * sum_y) / denominator


def _price_signal_monthly(group: pd.DataFrame) -> pd.DataFrame:
    daily = group.sort_values("date").copy()
    close = pd.to_numeric(daily["adj_close"], errors="coerce")
    volume = pd.to_numeric(daily["volume"], errors="coerce")
    lengths = (3, 5, 10, 20, 50, 100, 200, 400, 600, 800, 1000)
    moving = [close.rolling(length, min_periods=length).mean() / close for length in lengths]
    daily["TrendFactor"] = -pd.concat(moving, axis=1).mean(axis=1, skipna=False)
    daily["VolSD"] = volume.rolling(252, min_periods=252).std(ddof=1)
    daily["VolumeTrend"] = _rolling_volume_slope(volume)
    daily["completed_month"] = daily["date"].dt.to_period("M").dt.to_timestamp()
    return daily.groupby("completed_month", as_index=False).tail(1)[
        ["completed_month", "TrendFactor", "VolSD", "VolumeTrend"]
    ]


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
    parts: list[pd.DataFrame] = []
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
        wide["signal_cutoff"] = wide["completed_month"] + pd.offsets.MonthEnd(0)
        wide["available_at"] = wide["signal_cutoff"]
        wide["formation_month"] = wide["completed_month"] + pd.offsets.MonthBegin(1)
        wide["realized_month_return"] = wide["formation_month"].map(realized)
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
    if not parts:
        return pd.DataFrame(
            columns=[
                "symbol", "completed_month", "signal_cutoff", "available_at",
                "formation_month", "realized_month_return", "signal", "proxy_value",
            ]
        )
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
