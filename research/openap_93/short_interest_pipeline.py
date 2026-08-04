"""Current short-interest signals from causal Yahoo public snapshots."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .analyst_pipeline import _latest_payloads, _period, _weighted_opscore
from .registry import FidelityClass


SHORT_INTEREST_IMPLEMENTED_SIGNALS = frozenset(
    {"IO_ShortInterest", "Recomm_ShortInterest", "ShortInterest"}
)


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) and np.isfinite(float(parsed)) else None


def _timestamp(value: Any, *, epoch: bool = False) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if epoch:
        numeric = _number(value)
        if numeric is not None:
            unit = "ms" if abs(numeric) >= 1_000_000_000_000 else "s"
            parsed = pd.to_datetime(numeric, unit=unit, errors="coerce", utc=True)
        else:
            parsed = pd.to_datetime(value, errors="coerce", utc=True)
    else:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_convert(None)


def _percentile_bucket(values: pd.Series, buckets: int) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    numeric = pd.to_numeric(values, errors="coerce")
    available = numeric.dropna()
    if len(available) < buckets:
        return result
    ranks = available.rank(method="average", pct=True)
    result.loc[available.index] = np.ceil(ranks * buckets).clip(1, buckets)
    return result


def calculate_short_interest_signals(
    security_master: pd.DataFrame,
    analyst_rows: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Reconstruct current short interest and keep IBES/13F substitutes closed."""

    formation = pd.Timestamp(formation_at).tz_localize(None)
    frame = security_master.copy().drop_duplicates("symbol")
    for column in (
        "sharesShort",
        "sharesOutstanding",
        "heldPercentInstitutions",
    ):
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    frame["retrieved_at_parsed"] = frame.get(
        "retrieved_at", pd.Series(index=frame.index, dtype=object)
    ).map(_timestamp)
    frame["period_end"] = frame.get(
        "dateShortInterest", pd.Series(index=frame.index, dtype=object)
    ).map(lambda value: _timestamp(value, epoch=True))
    causal = frame["retrieved_at_parsed"].notna() & frame[
        "retrieved_at_parsed"
    ].le(formation)
    valid_ratio = (
        causal
        & frame["sharesShort"].ge(0)
        & frame["sharesOutstanding"].gt(0)
        & frame["period_end"].notna()
        & frame["period_end"].le(formation)
    )
    frame["short_interest"] = np.where(
        valid_ratio,
        frame["sharesShort"] / frame["sharesOutstanding"],
        np.nan,
    )

    payloads = _latest_payloads(analyst_rows, formation)
    recommendation_values: list[float | None] = []
    recommendation_counts: list[int] = []
    recommendation_available: list[pd.Timestamp | None] = []
    for symbol in frame["symbol"].astype(str):
        payload, available = payloads.get(
            (symbol, "recommendations"), ([], None)
        )
        value, count = _weighted_opscore(_period(payload, "0m"))
        recommendation_values.append(value)
        recommendation_counts.append(count)
        recommendation_available.append(available)
    frame["consensus_recommendation"] = recommendation_values
    frame["recommendation_count"] = recommendation_counts
    frame["recommendation_available"] = recommendation_available
    frame["short_quintile"] = _percentile_bucket(frame["short_interest"], 5)
    frame["recommendation_quintile"] = _percentile_bucket(
        frame["consensus_recommendation"], 5
    )
    frame["recomm_short_value"] = np.select(
        [
            frame["short_quintile"].eq(1)
            & frame["recommendation_quintile"].eq(1),
            frame["short_quintile"].eq(5)
            & frame["recommendation_quintile"].eq(5),
        ],
        [1.0, 0.0],
        default=np.nan,
    )

    institutional = frame["heldPercentInstitutions"].copy()
    institutional = institutional.where(institutional.ge(0))
    institutional = institutional.where(institutional.gt(1.5), institutional * 100.0)
    short_threshold = frame["short_interest"].quantile(0.99)
    frame["io_short_value"] = np.where(
        frame["short_interest"].ge(short_threshold) & institutional.notna(),
        institutional,
        np.nan,
    )

    rows: list[dict[str, Any]] = []
    for item in frame.itertuples(index=False):
        available = item.retrieved_at_parsed
        recommendation_available_at = item.recommendation_available
        combined_available = max(
            [value for value in (available, recommendation_available_at) if value is not None],
            default=None,
        )
        common = {
            "symbol": str(item.symbol),
            "formation_at": formation,
            "period_end": item.period_end,
            "staleness_days": (
                int((formation.normalize() - available.normalize()).days)
                if available is not None
                else np.nan
            ),
        }
        specifications = (
            (
                "ShortInterest",
                item.short_interest,
                FidelityClass.RECONSTRUCTED,
                "openap_shortint_divided_by_shares_outstanding",
                available,
                1,
                "Yahoo sharesShort and sharesOutstanding reconstruct the official ratio; "
                "vendor field definitions are less controlled than Compustat/CRSP",
            ),
            (
                "Recomm_ShortInterest",
                item.recomm_short_value,
                FidelityClass.UNVALIDATED_PROXY,
                "openap_extreme_short_interest_and_consensus_recommendation_quintiles_proxy",
                combined_available,
                int(item.recommendation_count),
                "Yahoo aggregate recommendation buckets replace IBES individual analyst "
                "recommendations and their six-month extension",
            ),
            (
                "IO_ShortInterest",
                item.io_short_value,
                FidelityClass.UNVALIDATED_PROXY,
                "openap_institutional_ownership_among_top_one_pct_short_interest_proxy",
                available,
                1,
                "Yahoo heldPercentInstitutions replaces the complete Thomson Reuters 13F panel",
            ),
        )
        for signal, value, fidelity, formula, available_at, count, caveat in specifications:
            finite = value is not None and np.isfinite(float(value))
            actual_fidelity = fidelity if finite else FidelityClass.UNAVAILABLE
            rows.append(
                {
                    **common,
                    "signal": signal,
                    "value": float(value) if finite else None,
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
                    "formula_id": formula,
                    "source_ids": "yahoo_public",
                    "available_at": available_at,
                    "observation_count": int(count),
                    "reason_if_missing": "" if finite else "short_interest_inputs_missing_or_not_applicable",
                    "caveat": caveat,
                }
            )
    return pd.DataFrame(rows)


def implemented_source_pairs() -> frozenset[tuple[str, str]]:
    return frozenset(
        (signal, "yahoo_public") for signal in SHORT_INTEREST_IMPLEMENTED_SIGNALS
    )


__all__ = [
    "SHORT_INTEREST_IMPLEMENTED_SIGNALS",
    "calculate_short_interest_signals",
    "implemented_source_pairs",
]
