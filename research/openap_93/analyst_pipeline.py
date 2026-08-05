"""Current analyst-signal reconstructions from causal Yahoo snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json

import numpy as np
import pandas as pd

from .registry import FidelityClass


ANALYST_IMPLEMENTED_SIGNALS = frozenset(
    {
        "ChangeInRecommendation",
        "EarningsForecastDisparity",
        "EarningsStreak",
        "ExclExp",
        "FEPS",
        "ForecastDispersion",
    }
)

EPS_FACT_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")


@dataclass(frozen=True)
class AnalystValue:
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
        finite_value = _number(self.value)
        finite = finite_value is not None
        fidelity = self.fidelity if finite else FidelityClass.UNAVAILABLE
        available = pd.to_datetime(self.available_at, errors="coerce", utc=True)
        if pd.notna(available):
            available = available.tz_convert(None)
        period_end = pd.to_datetime(self.period_end, errors="coerce")
        return {
            "symbol": self.symbol,
            "signal": self.signal,
            "value": finite_value,
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
            "available_at": available,
            "period_end": period_end,
            "observation_count": int(self.observation_count),
            "reason_if_missing": "" if finite else (self.reason or "analyst_input_missing"),
            "caveat": self.caveat,
            "formation_at": formation_at,
            "staleness_days": (
                int((formation_at.normalize() - available.normalize()).days)
                if pd.notna(available)
                else np.nan
            ),
        }


def _decode_payload(value: Any) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [dict(item) for item in decoded if isinstance(item, dict)]


def _latest_payloads(
    analyst_rows: pd.DataFrame,
    formation_at: pd.Timestamp,
) -> dict[tuple[str, str], tuple[list[dict[str, Any]], pd.Timestamp]]:
    if analyst_rows.empty:
        return {}
    frame = analyst_rows.copy()
    frame["retrieved_at"] = pd.to_datetime(
        frame["retrieved_at"], errors="coerce", utc=True
    )
    formation_utc = formation_at.tz_localize("UTC")
    frame = frame.loc[
        frame["retrieved_at"].notna() & frame["retrieved_at"].le(formation_utc)
    ].copy()
    frame = frame.sort_values("retrieved_at").drop_duplicates(
        ["symbol", "dataset"], keep="last"
    )
    result: dict[tuple[str, str], tuple[list[dict[str, Any]], pd.Timestamp]] = {}
    for row in frame.itertuples(index=False):
        result[(str(row.symbol), str(row.dataset))] = (
            _decode_payload(row.payload_json),
            pd.Timestamp(row.retrieved_at).tz_convert(None),
        )
    return result


def _period(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((row for row in rows if str(row.get("period", "")) == name), None)


def _number(value: Any) -> float | None:
    result = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(result) if pd.notna(result) and np.isfinite(float(result)) else None


def _weighted_opscore(row: dict[str, Any] | None) -> tuple[float | None, int]:
    if row is None:
        return None, 0
    categories = (("strongBuy", 1), ("buy", 2), ("hold", 3), ("sell", 4), ("strongSell", 5))
    counts = [max(0.0, _number(row.get(name)) or 0.0) for name, _ in categories]
    total = int(sum(counts))
    if total <= 0:
        return None, 0
    mean_rating = sum(
        count * rating
        for count, (_, rating) in zip(counts, categories, strict=True)
    ) / total
    return float(6.0 - mean_rating), total


def _latest_eps_fact(
    facts: pd.DataFrame,
    symbol: str,
    quarter: pd.Timestamp | None,
) -> tuple[float | None, pd.Timestamp | None, pd.Timestamp | None]:
    if facts.empty or quarter is None or pd.isna(quarter):
        return None, None, None
    frame = facts.loc[
        facts["symbol"].eq(symbol) & facts["tag"].isin(EPS_FACT_TAGS)
    ].copy()
    if frame.empty:
        return None, None, None
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame["period_start"] = pd.to_datetime(frame["period_start"], errors="coerce")
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce", utc=True)
    frame["_duration"] = (frame["period_end"] - frame["period_start"]).dt.days
    frame = frame.loc[
        frame["period_end"].eq(pd.Timestamp(quarter))
        & frame["_duration"].between(60, 120)
    ].copy()
    if frame.empty:
        return None, None, None
    order = {tag: index for index, tag in enumerate(EPS_FACT_TAGS)}
    frame["_tag_order"] = frame["tag"].map(order).fillna(len(order))
    row = frame.sort_values(
        ["_tag_order", "available_at"], ascending=[True, False]
    ).iloc[0]
    value = _number(row["value"])
    available = pd.Timestamp(row["available_at"]).tz_convert(None)
    return value, available, pd.Timestamp(row["period_end"])


def calculate_analyst_signals(
    security_master: pd.DataFrame,
    analyst_rows: pd.DataFrame,
    companyfacts: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate current signals without treating approximate IBES fields as exact."""

    formation = pd.Timestamp(formation_at).tz_localize(None)
    payloads = _latest_payloads(analyst_rows, formation)
    master = security_master.drop_duplicates("symbol")
    values: list[AnalystValue] = []

    for item in master.itertuples(index=False):
        symbol = str(item.symbol)
        recommendations, recommendations_at = payloads.get(
            (symbol, "recommendations"), ([], pd.NaT)
        )
        estimates, estimates_at = payloads.get(
            (symbol, "earnings_estimate"), ([], pd.NaT)
        )
        growth, growth_at = payloads.get(
            (symbol, "growth_estimates"), ([], pd.NaT)
        )
        history, history_at = payloads.get(
            (symbol, "earnings_history"), ([], pd.NaT)
        )

        current_score, current_analysts = _weighted_opscore(
            _period(recommendations, "0m")
        )
        prior_score, prior_analysts = _weighted_opscore(
            _period(recommendations, "-1m")
        )
        change = (
            current_score - prior_score
            if current_score is not None and prior_score is not None
            else None
        )
        values.append(
            AnalystValue(
                symbol,
                "ChangeInRecommendation",
                change,
                FidelityClass.RECONSTRUCTED,
                "openap_change_in_recommendation_weighted_consensus_current_minus_1m",
                ("yahoo_public",),
                recommendations_at,
                None,
                min(current_analysts, prior_analysts),
                "current_and_prior_recommendation_consensus_required",
                "Yahoo consensus buckets replace individual IBES recommendations; "
                "the weighted mean and monthly difference follow the official formula",
            )
        )

        annual = _period(estimates, "0y")
        forecast = _number(annual.get("avg")) if annual else None
        analyst_count = int(_number(annual.get("numberOfAnalysts")) or 0) if annual else 0
        values.append(
            AnalystValue(
                symbol,
                "FEPS",
                forecast,
                FidelityClass.RECONSTRUCTED,
                "openap_feps_yahoo_current_fiscal_year_mean_estimate",
                ("yahoo_public",),
                estimates_at,
                None,
                analyst_count,
                "current_fiscal_year_consensus_missing",
                "Yahoo period 0y is mapped to the IBES primary fiscal-year forecast fpi=1",
            )
        )

        high = _number(annual.get("high")) if annual else None
        low = _number(annual.get("low")) if annual else None
        dispersion = (
            0.5 * (high - low) / abs(forecast)
            if high is not None
            and low is not None
            and forecast is not None
            and abs(forecast) > 1e-12
            and analyst_count >= 2
            else None
        )
        values.append(
            AnalystValue(
                symbol,
                "ForecastDispersion",
                dispersion,
                FidelityClass.UNVALIDATED_PROXY,
                "yahoo_half_forecast_range_over_abs_mean_proxy",
                ("yahoo_public",),
                estimates_at,
                None,
                analyst_count,
                "forecast_range_or_analyst_count_missing",
                "Yahoo exposes forecast high and low but not the IBES "
                "cross-analyst standard deviation",
            )
        )

        long_term = _period(growth, "LTG") or _period(growth, "+5y")
        ltg = _number(long_term.get("stockTrend")) if long_term else None
        prior_eps = _number(annual.get("yearAgoEps")) if annual else None
        if ltg is not None and abs(ltg) <= 2.0:
            ltg *= 100.0
        disparity = (
            ltg - 100.0 * (forecast - prior_eps) / abs(prior_eps)
            if ltg is not None
            and forecast is not None
            and prior_eps is not None
            and abs(prior_eps) > 1e-12
            else None
        )
        disparity_at = max(
            (value for value in (estimates_at, growth_at) if pd.notna(value)),
            default=pd.NaT,
        )
        values.append(
            AnalystValue(
                symbol,
                "EarningsForecastDisparity",
                disparity,
                FidelityClass.UNVALIDATED_PROXY,
                "openap_disparity_yahoo_ltg_minus_scaled_current_year_change_proxy",
                ("yahoo_public",),
                disparity_at,
                None,
                analyst_count,
                "long_term_growth_or_fiscal_year_inputs_missing",
                "Yahoo yearAgoEps substitutes for IBES FY0 actual and Yahoo LTG "
                "replaces IBES fpi=0",
            )
        )

        ordered_history = sorted(
            history,
            key=lambda row: pd.to_datetime(row.get("quarter"), errors="coerce"),
        )
        latest_two = ordered_history[-2:]
        surprises = [_number(row.get("surprisePercent")) for row in latest_two]
        finite_surprises = [value for value in surprises if value is not None]
        same_sign = (
            len(finite_surprises) == 2
            and all(value != 0 for value in finite_surprises)
            and np.sign(finite_surprises[0]) == np.sign(finite_surprises[1])
        )
        streak = finite_surprises[-1] if same_sign else None
        latest_quarter = (
            pd.to_datetime(ordered_history[-1].get("quarter"), errors="coerce")
            if ordered_history
            else None
        )
        values.append(
            AnalystValue(
                symbol,
                "EarningsStreak",
                streak,
                FidelityClass.UNVALIDATED_PROXY,
                "openap_earnings_streak_yahoo_two_same_sign_surprises_proxy",
                ("yahoo_public",),
                history_at,
                latest_quarter,
                len(ordered_history),
                "two_consecutive_same_sign_surprises_required",
                "Yahoo quarterly surprisePercent replaces the IBES six-month "
                "price-scaled surprise",
            )
        )

        actual_eps = (
            _number(ordered_history[-1].get("epsActual")) if ordered_history else None
        )
        reported_eps, reported_at, reported_period = _latest_eps_fact(
            companyfacts, symbol, latest_quarter
        )
        exclusions = (
            actual_eps - reported_eps
            if actual_eps is not None and reported_eps is not None
            else None
        )
        exclusions_at = max(
            (
                value
                for value in (history_at, reported_at)
                if value is not None and pd.notna(value)
            ),
            default=pd.NaT,
        )
        values.append(
            AnalystValue(
                symbol,
                "ExclExp",
                exclusions,
                FidelityClass.UNVALIDATED_PROXY,
                "openap_excluded_expenses_yahoo_actual_minus_sec_gaap_eps_proxy",
                ("yahoo_public", "sec_edgar"),
                exclusions_at,
                reported_period,
                int(actual_eps is not None) + int(reported_eps is not None),
                "matching_yahoo_and_sec_quarterly_eps_required",
                "Yahoo adjusted actual EPS substitutes for IBES int0a; SEC GAAP "
                "EPS substitutes for Compustat epspiq",
            )
        )

    return pd.DataFrame(value.record(formation) for value in values)


def implemented_source_pairs() -> frozenset[tuple[str, str]]:
    pairs = {
        (signal, "yahoo_public") for signal in ANALYST_IMPLEMENTED_SIGNALS
    }
    pairs.add(("ExclExp", "sec_edgar"))
    return frozenset(pairs)


__all__ = [
    "ANALYST_IMPLEMENTED_SIGNALS",
    "EPS_FACT_TAGS",
    "calculate_analyst_signals",
    "implemented_source_pairs",
]
