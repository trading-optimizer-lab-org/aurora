"""Current cross-sectional market predictors for the OpenAP 93 extension.

The module is deliberately pure: callers provide the security master, daily
prices and normalized public factors.  This keeps source I/O and formula
verification independently testable and lets GitHub reuse immutable inputs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .market import (
    beta_liquidity_ps,
    beta_vix,
    coskew_acx,
    coskewness_60m,
    ff3_month_residual_moments,
    ols_fit,
    price_delay_rsq,
    residual_momentum,
    zero_trade_measure,
)
from .registry import FidelityClass


MARKET_IMPLEMENTED_SIGNALS = frozenset(
    {
        "BetaLiquidityPS",
        "BetaTailRisk",
        "CoskewACX",
        "Coskewness",
        "FirmAgeMom",
        "IdioVol3F",
        "IndIPO",
        "IndRetBig",
        "MomRev",
        "MomVol",
        "PriceDelayRsq",
        "ResidualMomentum",
        "ReturnSkew3F",
        "betaVIX",
        "zerotrade12M",
        "zerotrade1M",
        "zerotrade6M",
    }
)


@dataclass(frozen=True)
class MarketSignalValue:
    symbol: str
    signal: str
    value: float | None
    fidelity: FidelityClass
    formula_id: str
    source_ids: tuple[str, ...]
    available_at: pd.Timestamp
    period_end: pd.Timestamp
    observation_count: int
    missing_reason: str = ""
    caveat: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "signal": self.signal,
            "value": self.value,
            "fidelity_class": self.fidelity.value,
            "current_usable": bool(
                self.value is not None
                and self.fidelity
                in {
                    FidelityClass.EXACT,
                    FidelityClass.RECONSTRUCTED,
                    FidelityClass.VALIDATED_PROXY,
                }
            ),
            "formula_id": self.formula_id,
            "source_ids": "|".join(self.source_ids),
            "available_at": self.available_at,
            "period_end": self.period_end,
            "observation_count": self.observation_count,
            "reason_if_missing": self.missing_reason,
            "caveat": self.caveat,
        }


def _safe_value(value: float | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if np.isfinite(result) else None


def _period_frame(frame: pd.DataFrame, date_column: str = "date") -> pd.DataFrame:
    result = frame.copy()
    result[date_column] = pd.to_datetime(result[date_column], errors="coerce").dt.tz_localize(None)
    return result.dropna(subset=[date_column]).sort_values(date_column)


def _monthly_stock(prices: pd.DataFrame, formation_at: pd.Timestamp) -> pd.DataFrame:
    frame = _period_frame(prices)
    completed_month = formation_at.to_period("M") - 1
    frame = frame.loc[frame["date"].dt.to_period("M") <= completed_month].copy()
    if frame.empty:
        return pd.DataFrame(columns=["date", "ret", "volume"])
    monthly = (
        frame.set_index("date")
        .resample("ME")
        .agg(adj_close=("adj_close", "last"), volume=("volume", "sum"))
    )
    monthly["ret"] = monthly["adj_close"].pct_change(fill_method=None)
    return monthly.reset_index()


def _aligned_monthly(
    monthly: pd.DataFrame,
    factors: pd.DataFrame,
    liquidity: pd.DataFrame,
) -> pd.DataFrame:
    stock = monthly.copy()
    stock["month"] = stock["date"].dt.to_period("M")
    ff = _period_frame(factors)
    ff["month"] = ff["date"].dt.to_period("M")
    liq = _period_frame(liquidity)
    liq["month"] = liq["date"].dt.to_period("M")
    return (
        stock.merge(ff.drop(columns="date"), on="month", how="inner")
        .merge(liq[["month", "ps_innovation"]], on="month", how="left")
        .sort_values("month")
    )


def _aligned_daily(prices: pd.DataFrame, ff3_daily: pd.DataFrame) -> pd.DataFrame:
    stock = _period_frame(prices)
    stock["ret"] = pd.to_numeric(stock["adj_close"], errors="coerce").pct_change(fill_method=None)
    factors = _period_frame(ff3_daily)
    return stock.merge(factors, on="date", how="inner").sort_values("date")


def _tail_factor(all_prices: pd.DataFrame, formation_at: pd.Timestamp) -> pd.DataFrame:
    data = _period_frame(all_prices)
    completed_month = formation_at.to_period("M") - 1
    data = data.loc[data["date"].dt.to_period("M") <= completed_month].copy()
    data["ret"] = data.groupby("symbol", sort=False)["adj_close"].pct_change(fill_method=None)
    data["month"] = data["date"].dt.to_period("M")
    data = data.dropna(subset=["ret"])
    percentile = data.groupby("month")["ret"].quantile(0.05, interpolation="lower")
    data["retp5"] = data["month"].map(percentile)
    tail = data.loc[data["ret"].le(data["retp5"]) & data["retp5"].lt(0)].copy()
    ratio = tail["ret"] / tail["retp5"]
    tail["tailex"] = np.log(ratio.where(ratio.gt(0)))
    return tail.groupby("month", as_index=False)["tailex"].mean().dropna()


def _beta_tail(monthly: pd.DataFrame, tail_factor: pd.DataFrame) -> tuple[float | None, int]:
    frame = monthly.copy()
    frame["month"] = frame["date"].dt.to_period("M")
    aligned = frame.merge(tail_factor, on="month", how="inner").tail(120)
    valid = aligned[["ret", "tailex"]].dropna()
    if len(valid) < 72:
        return None, len(valid)
    try:
        coefficients, _, _ = ols_fit(valid["ret"], valid["tailex"].to_numpy())
    except ValueError:
        return None, len(valid)
    return float(coefficients[1]), len(valid)


def _annual_delay_window(formation_at: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    refresh_year = formation_at.year if formation_at.month >= 7 else formation_at.year - 1
    end = pd.Timestamp(refresh_year, 6, 30)
    start = pd.Timestamp(refresh_year - 1, 7, 1)
    return start, end


def _quantile_codes(values: pd.Series, bins: int) -> pd.Series:
    valid = pd.to_numeric(values, errors="coerce")
    ranked = valid.rank(method="first")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    if ranked.notna().sum() >= bins:
        result.loc[ranked.notna()] = pd.qcut(
            ranked.loc[ranked.notna()], q=bins, labels=False, duplicates="drop"
        ).astype(float) + 1.0
    return result


def _append(
    rows: list[MarketSignalValue],
    *,
    symbol: str,
    signal: str,
    value: float | None,
    fidelity: FidelityClass,
    formula_id: str,
    source_ids: tuple[str, ...],
    available_at: pd.Timestamp,
    period_end: pd.Timestamp,
    observation_count: int,
    missing_reason: str = "insufficient_history_or_inputs",
    caveat: str = "",
) -> None:
    finite = _safe_value(value)
    rows.append(
        MarketSignalValue(
            symbol=symbol,
            signal=signal,
            value=finite,
            fidelity=fidelity if finite is not None else FidelityClass.UNAVAILABLE,
            formula_id=formula_id,
            source_ids=source_ids,
            available_at=available_at,
            period_end=period_end,
            observation_count=int(observation_count),
            missing_reason="" if finite is not None else missing_reason,
            caveat=caveat,
        )
    )


def calculate_market_signals(
    security_master: pd.DataFrame,
    prices_daily: pd.DataFrame,
    ff3_daily: pd.DataFrame,
    ff3_monthly: pd.DataFrame,
    liquidity_monthly: pd.DataFrame,
    vix_daily: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate all supported market-family members of the required 93."""

    formation = pd.Timestamp(formation_at).tz_localize(None)
    master = security_master.copy().drop_duplicates("symbol").set_index("symbol")
    prices = _period_frame(prices_daily)
    prices = prices.loc[prices["date"].le(formation)].copy()
    tail_factor = _tail_factor(prices, formation)
    vix = _period_frame(vix_daily)[["date", "vix_change"]]
    rows: list[MarketSignalValue] = []
    cross: list[dict[str, Any]] = []

    for symbol, group in prices.groupby("symbol", sort=True):
        if symbol not in master.index:
            continue
        daily = group.sort_values("date")
        monthly = _monthly_stock(daily, formation)
        aligned_m = _aligned_monthly(monthly, ff3_monthly, liquidity_monthly)
        aligned_d = _aligned_daily(daily, ff3_daily)
        aligned_daily_end = (
            aligned_d["date"].max() if not aligned_d.empty else pd.NaT
        )
        period_end = daily["date"].max()
        available_at = period_end
        monthly_end = monthly["date"].max() if not monthly.empty else period_end

        monthly_excess = aligned_m["ret"] - aligned_m["rf"]
        aligned_month_end = (
            aligned_m["date"].max() if not aligned_m.empty else pd.NaT
        )
        beta_ps_input = aligned_m.dropna(
            subset=["ret", "ps_innovation", "mktrf", "smb", "hml"]
        )
        beta_ps_end = (
            beta_ps_input["date"].max() if not beta_ps_input.empty else pd.NaT
        )
        beta_ps = beta_liquidity_ps(
            monthly_excess,
            aligned_m["ps_innovation"],
            aligned_m["mktrf"],
            aligned_m["smb"],
            aligned_m["hml"],
        )
        _append(
            rows,
            symbol=symbol,
            signal="BetaLiquidityPS",
            value=beta_ps,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_beta_liquidity_ps_60m_min36",
            source_ids=("yahoo_public", "kenneth_french", "pastor_stambaugh"),
            available_at=beta_ps_end,
            period_end=beta_ps_end,
            observation_count=int(
                aligned_m[["ret", "ps_innovation", "mktrf", "smb", "hml"]]
                .dropna()
                .tail(60)
                .shape[0]
            ),
        )

        beta_tail, beta_tail_n = _beta_tail(monthly, tail_factor)
        _append(
            rows,
            symbol=symbol,
            signal="BetaTailRisk",
            value=beta_tail,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_cross_section_p5_tail_beta_120m_min72",
            source_ids=("yahoo_public",),
            available_at=monthly_end,
            period_end=monthly_end,
            observation_count=beta_tail_n,
        )

        market_total = aligned_d["mktrf"] + aligned_d["rf"]
        coskew_daily = coskew_acx(
            aligned_d["ret"].tail(252), market_total.tail(252)
        )
        _append(
            rows,
            symbol=symbol,
            signal="CoskewACX",
            value=coskew_daily,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_acx_daily_coskew_trailing_year",
            source_ids=("yahoo_public", "kenneth_french"),
            available_at=aligned_daily_end,
            period_end=aligned_daily_end,
            observation_count=int(aligned_d[["ret", "mktrf", "rf"]].dropna().tail(252).shape[0]),
        )

        coskew_monthly = coskewness_60m(monthly_excess, aligned_m["mktrf"])
        _append(
            rows,
            symbol=symbol,
            signal="Coskewness",
            value=coskew_monthly,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_systematic_coskewness_60m_min12",
            source_ids=("yahoo_public", "kenneth_french"),
            available_at=aligned_month_end,
            period_end=aligned_month_end,
            observation_count=int(aligned_m[["ret", "mktrf", "rf"]].dropna().tail(60).shape[0]),
        )

        completed_month = formation.to_period("M") - 1
        last_month_daily = aligned_d.loc[
            aligned_d["date"].dt.to_period("M").eq(completed_month)
        ]
        last_month_end = (
            last_month_daily["date"].max() if not last_month_daily.empty else pd.NaT
        )
        idio, skew = ff3_month_residual_moments(
            last_month_daily["ret"] - last_month_daily["rf"],
            last_month_daily["mktrf"],
            last_month_daily["smb"],
            last_month_daily["hml"],
        )
        for signal, value in (("IdioVol3F", idio), ("ReturnSkew3F", skew)):
            _append(
                rows,
                symbol=symbol,
                signal=signal,
                value=value,
                fidelity=FidelityClass.RECONSTRUCTED,
                formula_id=f"openap_ff3_daily_residual_{signal.lower()}_min15",
                source_ids=("yahoo_public", "kenneth_french"),
                available_at=last_month_end,
                period_end=last_month_end,
                observation_count=len(last_month_daily),
            )

        start_delay, end_delay = _annual_delay_window(formation)
        delay = aligned_d.loc[aligned_d["date"].between(start_delay, end_delay)]
        delay_value = price_delay_rsq(
            delay["ret"] - delay["rf"], delay["mktrf"], lags=4
        )
        _append(
            rows,
            symbol=symbol,
            signal="PriceDelayRsq",
            value=delay_value,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_hou_moskowitz_d1_july_refresh_four_lags",
            source_ids=("yahoo_public", "kenneth_french"),
            available_at=min(available_at, end_delay),
            period_end=end_delay,
            observation_count=len(delay.dropna(subset=["ret", "mktrf", "rf"])),
        )

        residual = residual_momentum(
            monthly_excess,
            aligned_m["mktrf"],
            aligned_m["smb"],
            aligned_m["hml"],
        )
        _append(
            rows,
            symbol=symbol,
            signal="ResidualMomentum",
            value=residual,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_residual_momentum_ff3_36m_prior11",
            source_ids=("yahoo_public", "kenneth_french"),
            available_at=aligned_month_end,
            period_end=aligned_month_end,
            observation_count=len(aligned_m),
        )

        vix_aligned = aligned_d.merge(vix, on="date", how="inner", suffixes=("", "_vix"))
        vix_end = vix_aligned["date"].max() if not vix_aligned.empty else pd.NaT
        vix_beta = beta_vix(
            vix_aligned["ret"] - vix_aligned["rf"],
            vix_aligned["mktrf"],
            vix_aligned["vix_change"],
        )
        _append(
            rows,
            symbol=symbol,
            signal="betaVIX",
            value=vix_beta,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_beta_vix_20d_min15_market_control",
            source_ids=("yahoo_public", "kenneth_french", "cboe_public"),
            available_at=vix_end,
            period_end=vix_end,
            observation_count=int(
                vix_aligned[["ret", "rf", "mktrf", "vix_change"]]
                .dropna()
                .tail(20)
                .shape[0]
            ),
        )

        shares = pd.to_numeric(
            pd.Series([master.loc[symbol].get("sharesOutstanding")]), errors="coerce"
        ).iloc[0]
        turnover = (
            pd.to_numeric(daily["volume"], errors="coerce") / shares
            if pd.notna(shares) and shares > 0
            else pd.Series(np.nan, index=daily.index)
        )
        for signal, sessions, deflator in (
            ("zerotrade1M", 21, 480_000.0),
            ("zerotrade6M", 126, 11_000.0),
            ("zerotrade12M", 252, 11_000.0),
        ):
            value = zero_trade_measure(
                daily["volume"].tail(sessions),
                turnover.tail(sessions),
                expected_days=sessions,
                deflator=deflator,
            )
            _append(
                rows,
                symbol=symbol,
                signal=signal,
                value=value,
                fidelity=FidelityClass.UNVALIDATED_PROXY,
                formula_id=f"openap_zero_trade_{sessions}d_current_shares_proxy",
                source_ids=("yahoo_public", "sec_edgar"),
                available_at=available_at,
                period_end=period_end,
                observation_count=min(len(daily), sessions),
                caveat=(
                    "Yahoo consolidated volume and current shares replace "
                    "CRSP daily volume/shrout"
                ),
            )

        returns = monthly.set_index("date")["ret"]
        momentum6_window = returns.iloc[-6:-1].dropna() if len(returns) >= 6 else pd.Series(dtype=float)
        momentum36_window = returns.iloc[-37:-13].dropna() if len(returns) >= 37 else pd.Series(dtype=float)
        momentum6 = (
            float(np.prod(1.0 + momentum6_window) - 1.0)
            if len(momentum6_window) == 5
            else np.nan
        )
        momentum36 = (
            float(np.prod(1.0 + momentum36_window) - 1.0)
            if len(momentum36_window) == 24
            else np.nan
        )
        mean_volume6 = float(monthly["volume"].tail(6).mean()) if len(monthly) >= 6 else np.nan
        first_date = pd.to_datetime(
            master.loc[symbol].get("first_clean_price_date"), errors="coerce"
        )
        if pd.isna(first_date):
            first_date = daily["date"].min()
        age_months = (formation.year - first_date.year) * 12 + formation.month - first_date.month
        cross.append(
            {
                "symbol": symbol,
                "momentum6": momentum6,
                "momentum36": momentum36,
                "mean_volume6": mean_volume6,
                "age_months": age_months,
                "first_date": first_date,
                "price": float(daily["adj_close"].iloc[-1]),
                "industry": str(master.loc[symbol].get("industry") or ""),
                "market_cap": pd.to_numeric(
                    pd.Series([master.loc[symbol].get("marketCap")]), errors="coerce"
                ).iloc[0],
                "last_month_return": returns.iloc[-1] if len(returns) else np.nan,
                "period_end": period_end,
                "monthly_end": monthly_end,
                "monthly_count": len(monthly),
            }
        )

    cross_frame = pd.DataFrame(cross).set_index("symbol") if cross else pd.DataFrame()
    if not cross_frame.empty:
        mom6_q = _quantile_codes(cross_frame["momentum6"], 5)
        mom36_q = _quantile_codes(cross_frame["momentum36"], 5)
        momrev = pd.Series(np.nan, index=cross_frame.index)
        momrev.loc[mom6_q.eq(5) & mom36_q.eq(1)] = 1.0
        momrev.loc[mom6_q.eq(1) & mom36_q.eq(5)] = 0.0
        mom_decile = _quantile_codes(cross_frame["momentum6"], 10)
        volume_tercile = _quantile_codes(cross_frame["mean_volume6"], 3)
        momvol = mom_decile.where(volume_tercile.eq(3))
        age_quintile = _quantile_codes(cross_frame["age_months"], 5)
        firm_age_mom = cross_frame["momentum6"].where(
            age_quintile.eq(1) & cross_frame["price"].ge(5) & cross_frame["age_months"].ge(12)
        )
        ipo = cross_frame["age_months"].between(3, 36).astype(float)

        industry_rank = cross_frame.groupby("industry")["market_cap"].rank(pct=True)
        big_returns = (
            cross_frame.loc[industry_rank.gt(0.70)]
            .groupby("industry")["last_month_return"]
            .mean()
        )
        ind_ret_big = cross_frame["industry"].map(big_returns).where(industry_rank.lt(0.70))

        for symbol, state in cross_frame.iterrows():
            common = {
                "symbol": symbol,
                "available_at": state["period_end"],
                "period_end": state["monthly_end"],
                "observation_count": int(state["monthly_count"]),
            }
            _append(
                rows,
                signal="MomRev",
                value=momrev.loc[symbol],
                fidelity=FidelityClass.RECONSTRUCTED,
                formula_id="openap_mom6_q5_and_mom36_q1_binary",
                source_ids=("yahoo_public",),
                **common,
            )
            _append(
                rows,
                signal="MomVol",
                value=momvol.loc[symbol],
                fidelity=FidelityClass.RECONSTRUCTED,
                formula_id="openap_mom6_decile_within_high_volume_tercile",
                source_ids=("yahoo_public",),
                **common,
            )
            _append(
                rows,
                signal="FirmAgeMom",
                value=firm_age_mom.loc[symbol],
                fidelity=FidelityClass.UNVALIDATED_PROXY,
                formula_id="openap_youngest_quintile_mom6_first_price_proxy",
                source_ids=("yahoo_public",),
                caveat="First clean Yahoo price date may post-date the actual first listing",
                **common,
            )
            _append(
                rows,
                signal="IndIPO",
                value=ipo.loc[symbol],
                fidelity=FidelityClass.UNVALIDATED_PROXY,
                formula_id="openap_ipo_age_3_to_36m_first_price_proxy",
                source_ids=("yahoo_public",),
                caveat="First clean Yahoo price date replaces a verified IPO date",
                **common,
            )
            _append(
                rows,
                signal="IndRetBig",
                value=ind_ret_big.loc[symbol],
                fidelity=FidelityClass.UNVALIDATED_PROXY,
                formula_id="openap_big_industry_return_industry_label_proxy",
                source_ids=("yahoo_public", "sec_edgar"),
                caveat="Current Yahoo industry replaces historical FF48 classification",
                **common,
            )

    return pd.DataFrame([row.to_record() for row in rows])


def implemented_source_pairs() -> frozenset[tuple[str, str]]:
    """Return only source/signal pairs exercised by this implementation."""

    source_map: dict[str, tuple[str, ...]] = {
        "BetaLiquidityPS": ("yahoo_public", "kenneth_french", "pastor_stambaugh"),
        "BetaTailRisk": ("yahoo_public",),
        "CoskewACX": ("yahoo_public", "kenneth_french"),
        "Coskewness": ("yahoo_public", "kenneth_french"),
        "FirmAgeMom": ("yahoo_public",),
        "IdioVol3F": ("yahoo_public", "kenneth_french"),
        "IndIPO": ("yahoo_public",),
        "IndRetBig": ("yahoo_public", "sec_edgar"),
        "MomRev": ("yahoo_public",),
        "MomVol": ("yahoo_public",),
        "PriceDelayRsq": ("yahoo_public", "kenneth_french"),
        "ResidualMomentum": ("yahoo_public", "kenneth_french"),
        "ReturnSkew3F": ("yahoo_public", "kenneth_french"),
        "betaVIX": ("yahoo_public", "kenneth_french", "cboe_public"),
        "zerotrade1M": ("yahoo_public", "sec_edgar"),
        "zerotrade6M": ("yahoo_public", "sec_edgar"),
        "zerotrade12M": ("yahoo_public", "sec_edgar"),
    }
    return frozenset(
        (signal, source) for signal, sources in source_map.items() for source in sources
    )
