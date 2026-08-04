"""Point-in-time quarterly SEC reconstructions for the OpenAP 93 extension."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .registry import FidelityClass


QUARTERLY_IMPLEMENTED_SIGNALS = frozenset(
    {
        "AnnouncementReturn",
        "EarnSupBig",
        "EarningsSurprise",
        "NumEarnIncrease",
        "RevenueSurprise",
        "roaq",
    }
)

NET_INCOME_TAGS = ("NetIncomeLoss", "ProfitLoss")
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
SHARE_TAGS = (
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
)
ASSET_TAGS = ("Assets",)


@dataclass(frozen=True)
class QuarterlyValue:
    symbol: str
    signal: str
    value: float | None
    fidelity: FidelityClass
    formula_id: str
    sources: tuple[str, ...]
    available_at: pd.Timestamp | None
    period_end: pd.Timestamp | None
    observation_count: int
    reason: str = ""
    caveat: str = ""

    def record(self, formation_at: pd.Timestamp) -> dict[str, Any]:
        finite = self.value is not None and np.isfinite(float(self.value))
        fidelity = self.fidelity if finite else FidelityClass.UNAVAILABLE
        available_at = pd.to_datetime(self.available_at, errors="coerce", utc=True)
        if pd.notna(available_at):
            available_at = available_at.tz_convert(None)
        period_end = pd.to_datetime(self.period_end, errors="coerce")
        return {
            "symbol": self.symbol,
            "signal": self.signal,
            "value": float(self.value) if finite else None,
            "fidelity_class": fidelity.value,
            "current_usable": bool(
                finite
                and fidelity
                in {
                    FidelityClass.EXACT,
                    FidelityClass.RECONSTRUCTED,
                    FidelityClass.VALIDATED_PROXY,
                }
            ),
            "formula_id": self.formula_id,
            "source_ids": "|".join(self.sources),
            "available_at": available_at,
            "period_end": period_end,
            "observation_count": int(self.observation_count),
            "reason_if_missing": "" if finite else (self.reason or "insufficient_quarterly_history"),
            "caveat": self.caveat,
            "formation_at": formation_at,
            "staleness_days": (
                int((formation_at.normalize() - available_at.normalize()).days)
                if pd.notna(available_at)
                else np.nan
            ),
        }


def _duration_days(frame: pd.DataFrame) -> pd.Series:
    start = pd.to_datetime(frame["period_start"], errors="coerce")
    end = pd.to_datetime(frame["period_end"], errors="coerce")
    return (end - start).dt.days


def _select_tag(frame: pd.DataFrame, tags: Iterable[str]) -> pd.DataFrame:
    """Select one causal standalone-quarter observation per period end."""

    wanted = frame.loc[frame["tag"].isin(tuple(tags))].copy()
    if wanted.empty:
        return wanted
    tag_order = {tag: index for index, tag in enumerate(tags)}
    wanted["_tag_order"] = wanted["tag"].map(tag_order).fillna(len(tag_order))
    wanted["_duration_days"] = _duration_days(wanted)
    duration = wanted["_duration_days"]
    instantaneous = wanted["period_start"].isna()
    wanted = wanted.loc[instantaneous | duration.between(60, 120)].copy()
    wanted = wanted.sort_values(
        ["period_end", "_tag_order", "available_at", "filed"],
        ascending=[True, True, False, False],
    ).drop_duplicates("period_end", keep="first")
    return wanted.sort_values("period_end")


def _series(frame: pd.DataFrame, tags: Iterable[str]) -> pd.Series:
    selected = _select_tag(frame, tags)
    if selected.empty:
        return pd.Series(dtype=float)
    result = pd.to_numeric(selected.set_index("period_end")["value"], errors="coerce")
    result.index = pd.to_datetime(result.index)
    return result.sort_index()


def _standardized_surprise(values: pd.Series) -> tuple[float | None, int]:
    values = pd.to_numeric(values, errors="coerce").dropna().sort_index()
    if len(values) < 13:
        return None, len(values)
    yoy = values - values.shift(4)
    drift = pd.concat([yoy.shift(lag) for lag in range(1, 9)], axis=1).mean(axis=1)
    surprise = yoy - drift
    historical = pd.concat([surprise.shift(lag) for lag in range(1, 9)], axis=1)
    scale = historical.std(axis=1, ddof=1)
    latest = surprise.iloc[-1]
    latest_scale = scale.iloc[-1]
    if pd.isna(latest) or pd.isna(latest_scale) or abs(float(latest_scale)) < 1e-10:
        return None, len(values)
    return float(latest / latest_scale), len(values)


def _earnings_streak(values: pd.Series) -> tuple[float | None, int]:
    values = pd.to_numeric(values, errors="coerce").dropna().sort_index()
    yoy = values - values.shift(4)
    comparable = yoy.dropna()
    if comparable.empty:
        return None, len(values)
    count = 0
    for value in reversed(comparable.tail(8).tolist()):
        if value > 0:
            count += 1
        else:
            break
    return float(count), len(values)


def _latest_dates(frame: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if frame.empty:
        return None, None
    available = pd.to_datetime(frame["available_at"], errors="coerce", utc=True).max()
    if pd.notna(available):
        available = available.tz_convert(None)
    return available, pd.to_datetime(frame["period_end"], errors="coerce").max()


def _announcement_return(
    facts: pd.DataFrame,
    prices: pd.DataFrame,
    ff3_daily: pd.DataFrame,
) -> tuple[float | None, int, pd.Timestamp | None, pd.Timestamp | None]:
    earnings = facts.loc[
        facts["tag"].isin(NET_INCOME_TAGS) & facts["form"].isin(["10-Q", "10-K"])
    ].copy()
    if earnings.empty or prices.empty:
        return None, 0, None, None
    event = pd.to_datetime(earnings["filed"], errors="coerce").max()
    if pd.isna(event):
        return None, 0, None, None
    px = prices.copy()
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px["ret"] = pd.to_numeric(px["adj_close"], errors="coerce").pct_change()
    market = ff3_daily.copy()
    market["date"] = pd.to_datetime(market["date"], errors="coerce")
    merged = px.merge(market[["date", "mktrf", "rf"]], on="date", how="inner")
    window = merged.loc[merged["date"].between(event - pd.Timedelta(days=4), event + pd.Timedelta(days=4))]
    if window.empty:
        return None, 0, None, event
    nearest = int((window["date"] - event).abs().argmin())
    start = max(0, nearest - 2)
    stop = min(len(window), nearest + 2)
    selected = window.iloc[start:stop]
    value = (selected["ret"] - selected["mktrf"] - selected["rf"]).sum(min_count=3)
    return (
        float(value) if pd.notna(value) else None,
        len(selected),
        selected["date"].max(),
        event,
    )


def calculate_quarterly_signals(
    security_master: pd.DataFrame,
    companyfacts: pd.DataFrame,
    prices: pd.DataFrame,
    ff3_daily: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate current quarterly signals using only filings available at formation."""

    formation = pd.Timestamp(formation_at).tz_localize(None)
    master = security_master.copy().drop_duplicates("symbol")
    master["cik"] = pd.to_numeric(master["cik"], errors="coerce")
    facts = companyfacts.copy()
    facts["cik"] = pd.to_numeric(facts["cik"], errors="coerce")
    facts["available_at"] = pd.to_datetime(facts["available_at"], errors="coerce", utc=True)
    facts["_available_naive"] = facts["available_at"].dt.tz_convert(None)
    facts["period_end"] = pd.to_datetime(facts["period_end"], errors="coerce")
    facts = facts.loc[facts["_available_naive"].le(formation)].drop(
        columns=["symbol"], errors="ignore"
    ).merge(
        master[["symbol", "cik"]], on="cik", how="inner"
    )
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    rows: list[QuarterlyValue] = []
    surprise_rows: list[dict[str, Any]] = []

    for item in master.itertuples(index=False):
        symbol = str(item.symbol)
        firm = facts.loc[facts["symbol"].eq(symbol)].copy()
        available_at, period_end = _latest_dates(firm)
        net_income = _series(firm, NET_INCOME_TAGS)
        revenue = _series(firm, REVENUE_TAGS)
        shares = _series(firm, SHARE_TAGS)
        assets = _series(firm, ASSET_TAGS)
        eps = net_income.reindex(shares.index).div(shares).replace([np.inf, -np.inf], np.nan).dropna()
        revenue_ps = revenue.reindex(shares.index).div(shares).replace([np.inf, -np.inf], np.nan).dropna()

        earnings_surprise, earnings_n = _standardized_surprise(eps)
        revenue_surprise, revenue_n = _standardized_surprise(revenue_ps)
        streak, streak_n = _earnings_streak(net_income)
        common = dict(
            symbol=symbol,
            sources=("sec_edgar",),
            available_at=available_at,
            period_end=period_end,
        )
        rows.extend(
            [
                QuarterlyValue(
                    signal="EarningsSurprise", value=earnings_surprise,
                    fidelity=FidelityClass.RECONSTRUCTED,
                    formula_id="openap_eps_yoy_drift_standardized_8q_sec",
                    observation_count=earnings_n, **common,
                ),
                QuarterlyValue(
                    signal="RevenueSurprise", value=revenue_surprise,
                    fidelity=FidelityClass.RECONSTRUCTED,
                    formula_id="openap_revenue_per_share_yoy_drift_standardized_8q_sec",
                    observation_count=revenue_n, **common,
                ),
                QuarterlyValue(
                    signal="NumEarnIncrease", value=streak,
                    fidelity=FidelityClass.RECONSTRUCTED,
                    formula_id="openap_consecutive_positive_yoy_quarterly_income_max8_sec",
                    observation_count=streak_n, **common,
                ),
            ]
        )
        asset_lag = assets.shift(1)
        common_index = net_income.index.intersection(asset_lag.index)
        roaq_value = None
        if len(common_index):
            latest = common_index.max()
            denominator = asset_lag.loc[latest]
            if pd.notna(denominator) and abs(float(denominator)) > 1e-12:
                roaq_value = float(net_income.loc[latest] / denominator)
        rows.append(
            QuarterlyValue(
                signal="roaq", value=roaq_value,
                fidelity=FidelityClass.RECONSTRUCTED,
                formula_id="openap_quarterly_income_over_lagged_quarterly_assets_sec",
                observation_count=min(len(net_income), len(assets)), **common,
            )
        )

        ann_value, ann_n, ann_available, ann_period = _announcement_return(
            firm, prices.loc[prices["symbol"].eq(symbol)], ff3_daily
        )
        rows.append(
            QuarterlyValue(
                signal="AnnouncementReturn", value=ann_value,
                fidelity=FidelityClass.UNVALIDATED_PROXY,
                formula_id="openap_announcement_abnormal_return_sec_filing_date_proxy",
                sources=("sec_edgar", "yahoo_public", "kenneth_french"),
                available_at=ann_available,
                period_end=ann_period,
                observation_count=ann_n,
                caveat="SEC filing date substitutes for the Compustat earnings announcement date",
                symbol=symbol,
            )
        )
        issuer_market_cap = pd.to_numeric(
            pd.Series([getattr(item, "issuer_market_cap", None)]), errors="coerce"
        ).iloc[0]
        market_cap = pd.to_numeric(
            pd.Series([getattr(item, "marketCap", None)]), errors="coerce"
        ).iloc[0]
        surprise_rows.append(
            {
                "symbol": symbol,
                "earnings_surprise": earnings_surprise,
                "industry": getattr(item, "industry", None),
                "market_cap": issuer_market_cap if pd.notna(issuer_market_cap) else market_cap,
                "available_at": available_at,
                "period_end": period_end,
            }
        )

    surprise = pd.DataFrame(surprise_rows)
    if not surprise.empty:
        surprise["market_cap"] = pd.to_numeric(surprise["market_cap"], errors="coerce")
        surprise["size_rank"] = surprise.groupby("industry")["market_cap"].rank(pct=True)
        big = surprise.loc[surprise["size_rank"].ge(0.70)]
        industry_mean = big.groupby("industry")["earnings_surprise"].mean()
        for item in surprise.itertuples(index=False):
            value = industry_mean.get(item.industry, np.nan)
            if item.size_rank >= 0.70:
                value = np.nan
            rows.append(
                QuarterlyValue(
                    symbol=str(item.symbol), signal="EarnSupBig",
                    value=float(value) if pd.notna(value) else None,
                    fidelity=FidelityClass.UNVALIDATED_PROXY,
                    formula_id="openap_big_firm_industry_earnings_surprise_yahoo_industry_proxy",
                    sources=("sec_edgar", "yahoo_public"),
                    available_at=item.available_at, period_end=item.period_end,
                    observation_count=int(big["industry"].eq(item.industry).sum()),
                    caveat="Yahoo industry substitutes for historical FF48 SIC classification",
                )
            )

    return pd.DataFrame([row.record(formation) for row in rows])


def implemented_source_pairs() -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for signal in QUARTERLY_IMPLEMENTED_SIGNALS:
        pairs.add((signal, "sec_edgar"))
    pairs.update(
        {
            ("AnnouncementReturn", "yahoo_public"),
            ("AnnouncementReturn", "kenneth_french"),
            ("EarnSupBig", "yahoo_public"),
        }
    )
    return frozenset(pairs)
