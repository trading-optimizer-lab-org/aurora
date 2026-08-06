"""Current dividend-event signals from causal daily distributions."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .registry import FidelityClass


EVENT_IMPLEMENTED_SIGNALS = frozenset({"AgeIPO", "DivInit", "DivOmit", "DivSeason"})

DIVSEASON_VARIANT_ID = "openap_dividend_seasonality_frequency_inferred"


def _dividend_periods(dividend_months: Any) -> list[pd.Period]:
    periods: list[pd.Period] = []
    for value in dividend_months:
        if value is None or pd.isna(value):
            continue
        periods.append(pd.Period(value, freq="M"))
    return sorted(set(periods))


def infer_dividend_frequency(dividend_months: Any) -> str:
    """Infer payment frequency using completed dividend months only."""

    periods = _dividend_periods(dividend_months)
    if len(periods) < 2:
        return "unknown"
    gaps = np.diff([period.ordinal for period in periods]).astype(float)
    recent_gaps = gaps[-12:]
    median_gap = float(np.median(recent_gaps))
    classifications = (
        ("monthly", 1.0, 1.0),
        ("quarterly", 3.0, 1.0),
        ("semiannual", 6.0, 1.0),
        ("annual", 12.0, 2.0),
    )
    for label, expected_gap, tolerance in classifications:
        close = np.abs(recent_gaps - expected_gap) <= tolerance
        if abs(median_gap - expected_gap) <= tolerance and float(close.mean()) >= 0.60:
            return label
    return "unknown"


def dividend_season_value(
    dividend_months: Any,
    completed_month: str | pd.Period | pd.Timestamp,
) -> float | None:
    """Return the OpenAP-style expected-payment indicator for next month."""

    through = pd.Period(completed_month, freq="M")
    periods = [period for period in _dividend_periods(dividend_months) if period <= through]
    if not periods:
        return None
    lags = {through.ordinal - period.ordinal for period in periods}
    if not any(0 <= lag <= 11 for lag in lags):
        return None
    frequency = infer_dividend_frequency(periods)
    if frequency == "monthly":
        return None
    eligible_lags = {
        "quarterly": {2, 5, 8, 11},
        "semiannual": {5, 11},
        "annual": {11},
        "unknown": {2, 5, 8, 11},
    }[frequency]
    return float(bool(lags.intersection(eligible_lags)))


def _monthly_dividends(prices: pd.DataFrame, formation: pd.Timestamp) -> pd.DataFrame:
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.loc[frame["date"].le(formation)].dropna(subset=["symbol", "date"])
    frame["month"] = frame["date"].dt.to_period("M")
    frame["dividends"] = pd.to_numeric(frame.get("dividends"), errors="coerce").fillna(0.0)
    return frame.groupby(["symbol", "month"], as_index=False).agg(
        dividend=("dividends", "sum"),
        last_market_date=("date", "max"),
    )


def _complete_months(frame: pd.DataFrame, through: pd.Period) -> pd.DataFrame:
    if frame.empty:
        return frame
    start = min(frame["month"].min(), through - 36)
    months = pd.period_range(start, through, freq="M")
    result = frame.set_index("month").reindex(months)
    result.index.name = "month"
    result["dividend"] = result["dividend"].fillna(0.0)
    return result.reset_index()


def _omission(
    paid: pd.Series,
    completed_month: pd.Period,
    window: int,
    payer_window: int,
) -> bool:
    recent = paid.loc[
        (paid.index > completed_month - window) & (paid.index <= completed_month)
    ]
    previous = paid.loc[
        (paid.index > completed_month - 2 * window)
        & (paid.index <= completed_month - window)
    ]
    payer_history = paid.loc[
        (paid.index > completed_month - payer_window - window)
        & (paid.index <= completed_month - window)
    ]
    return (
        len(recent) >= window
        and recent.sum() == 0
        and previous.sum() > 0
        and payer_history.sum() >= max(1, payer_window // window)
    )


def calculate_event_signals(
    security_master: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    formation = pd.Timestamp(formation_at).tz_localize(None)
    completed_month = formation.to_period("M") - 1
    monthly = _monthly_dividends(prices, formation)
    master = security_master.copy().drop_duplicates("symbol")
    rows: list[dict[str, Any]] = []

    for item in master.itertuples(index=False):
        symbol = str(item.symbol)
        history = _complete_months(monthly.loc[monthly["symbol"].eq(symbol)], completed_month)
        if history.empty:
            dividend = pd.Series(dtype=float)
        else:
            dividend = history.set_index("month")["dividend"].astype(float)
        paid = dividend.gt(0).astype(int)
        initiation_events: list[bool] = []
        for event_month in pd.period_range(completed_month - 5, completed_month, freq="M"):
            prior_24_event = dividend.loc[
                (dividend.index >= event_month - 24) & (dividend.index < event_month)
            ]
            initiation_events.append(
                bool(
                    dividend.get(event_month, 0.0) > 0
                    and len(prior_24_event) >= 24
                    and prior_24_event.sum() == 0
                )
            )
        prior_24 = dividend.loc[
            (dividend.index >= completed_month - 24) & (dividend.index < completed_month)
        ]
        initiation = float(any(initiation_events))

        omitted = float(
            _omission(paid, completed_month, 3, 18)
            or _omission(paid, completed_month, 6, 18)
            or _omission(paid, completed_month, 12, 24)
        )
        pay_months = [period for period, value in paid.items() if value > 0]
        dividend_frequency = infer_dividend_frequency(pay_months)
        season = dividend_season_value(pay_months, completed_month)

        first = pd.to_datetime(
            getattr(item, "first_clean_price_date", None), errors="coerce"
        )
        if pd.isna(first):
            first = pd.to_datetime(
                getattr(item, "first_price_date", None), errors="coerce"
            )
        months_since_listing = (
            (completed_month.ordinal - first.to_period("M").ordinal)
            if pd.notna(first)
            else None
        )
        age_ipo = (
            float(months_since_listing)
            if months_since_listing is not None and 3 <= months_since_listing <= 36
            else None
        )
        common = {
            "symbol": symbol,
            "formation_at": formation,
            "period_end": completed_month.to_timestamp("M"),
            "available_at": completed_month.to_timestamp("M"),
            "staleness_days": int((formation.normalize() - completed_month.to_timestamp("M")).days),
        }
        for signal, value, fidelity, formula, caveat in (
            (
                "DivInit", initiation if len(prior_24) >= 24 else None,
                FidelityClass.RECONSTRUCTED,
                "openap_dividend_initiation_after_24m_none_hold6_current_month",
                "Yahoo cash distributions do not expose CRSP distribution codes",
            ),
            (
                "DivOmit", omitted if len(paid) >= 24 else None,
                FidelityClass.RECONSTRUCTED,
                "openap_dividend_omission_3m_6m_12m_windows",
                "Regular cash distributions inferred from Yahoo dividend history",
            ),
            (
                "DivSeason", season,
                FidelityClass.UNVALIDATED_PROXY,
                "openap_dividend_seasonality_frequency_inferred",
                "Payment frequency is inferred because CRSP cd3 is unavailable",
            ),
            (
                "AgeIPO", age_ipo,
                FidelityClass.UNVALIDATED_PROXY,
                "openap_recent_ipo_listing_age_proxy",
                "Listing age substitutes for founding age; values outside 3-36 months are not applicable",
            ),
        ):
            finite_value = (
                float(value)
                if value is not None and np.isfinite(float(value))
                else None
            )
            finite = finite_value is not None
            actual_fidelity = fidelity if finite else FidelityClass.UNAVAILABLE
            if finite:
                missing_reason = ""
            elif (
                signal == "AgeIPO"
                and months_since_listing is not None
                and not 3 <= months_since_listing <= 36
            ):
                missing_reason = "not_applicable:listing_age_outside_3_36_months"
            elif signal == "DivSeason" and dividend_frequency == "monthly":
                missing_reason = "not_applicable:monthly_dividend_payer"
            else:
                missing_reason = "insufficient_event_history"
            rows.append(
                {
                    **common,
                    "signal": signal,
                    "value": finite_value,
                    "fidelity_class": actual_fidelity.value,
                    "current_usable": bool(
                        finite
                        and actual_fidelity
                        in {
                            FidelityClass.EXACT,
                            FidelityClass.RECONSTRUCTED,
                            FidelityClass.VALIDATED_PROXY,
                        }
                    ),
                    "variant_id": (
                        DIVSEASON_VARIANT_ID if signal == "DivSeason" else formula
                    ),
                    "formula_id": formula,
                    "source_ids": "yahoo_public",
                    "observation_count": int(len(paid)),
                    "reason_if_missing": missing_reason,
                    "caveat": caveat,
                    "dividend_frequency": (
                        dividend_frequency if signal == "DivSeason" else None
                    ),
                }
            )
    return pd.DataFrame(rows)


def implemented_source_pairs() -> frozenset[tuple[str, str]]:
    return frozenset((signal, "yahoo_public") for signal in EVENT_IMPLEMENTED_SIGNALS)
