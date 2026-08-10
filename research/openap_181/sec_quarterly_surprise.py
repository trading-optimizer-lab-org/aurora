"""Causal SEC reconstructions of two quarterly OpenAP surprise signals.

SEC CompanyFacts provides cumulative and standalone-quarter facts.  This
module converts additive flows and weighted-average shares into comparable
discrete fiscal quarters, requires the complete 21-quarter window needed by
the pinned formulas, and fails closed on gaps or ambiguous contexts.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .sec_companyfacts_149 import build_companyfacts_identity


EARNINGS_SURPRISE_FORMULA_SHA256 = (
    "bc5ddeb08dbff2036e5443f06b895c113a8d556ed577c9a8a8d7e23b7e52c279"
)
REVENUE_SURPRISE_FORMULA_SHA256 = (
    "00b8b548e0e913bdb5d9ff9f41da8766d7494286f5de2dbacf3aaa4410dc0cbc"
)
EARNINGS_SURPRISE_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/EarningsSurprise.py"
)
REVENUE_SURPRISE_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/RevenueSurprise.py"
)

_INCOME_TAGS = (
    "IncomeLossFromContinuingOperations",
    "NetIncomeLoss",
    "ProfitLoss",
)
_REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
_SHARE_TAGS = ("WeightedAverageNumberOfSharesOutstandingBasic",)
QUARTERLY_SURPRISE_COMPANYFACT_TAGS = frozenset(
    _INCOME_TAGS + _REVENUE_TAGS + _SHARE_TAGS
)

_FACT_COLUMNS = frozenset(
    {
        "cik",
        "taxonomy",
        "tag",
        "unit",
        "value",
        "period_start",
        "period_end",
        "fy",
        "fp",
        "form",
        "filed",
        "accession_number",
        "available_at",
    }
)
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
    "reason_if_missing",
    "caveat",
)
_SIGNAL_SPECS = {
    "EarningsSurprise": {
        "formula_id": "openap_eps_yoy_drift_standardized_8q_sec_21q",
        "formula_sha256": EARNINGS_SURPRISE_FORMULA_SHA256,
        "scale_floor": 1e-10,
        "caveat": (
            "SEC continuing/net income divided by weighted basic shares "
            "reconstructs Compustat epspxq; current CIK/ticker is not a "
            "historical GVKEY/PERMNO bridge"
        ),
    },
    "RevenueSurprise": {
        "formula_id": "openap_revenue_per_share_yoy_standardized_8q_sec_21q",
        "formula_sha256": REVENUE_SURPRISE_FORMULA_SHA256,
        "scale_floor": 1e-8,
        "caveat": (
            "SEC revenue and weighted basic shares reconstruct Compustat "
            "revtq/cshprq; current CIK/ticker is not a historical "
            "GVKEY/PERMNO bridge"
        ),
    },
}


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


def _normalise_facts(
    companyfacts: pd.DataFrame,
    *,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    _require_columns(companyfacts, _FACT_COLUMNS, "SEC CompanyFacts")
    frame = companyfacts.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["period_start"] = pd.to_datetime(
        frame["period_start"], errors="coerce", utc=True
    )
    frame["period_end"] = pd.to_datetime(
        frame["period_end"], errors="coerce", utc=True
    )
    frame["filed_at"] = pd.to_datetime(frame["filed"], errors="coerce", utc=True)
    frame["available_at"] = pd.to_datetime(
        frame["available_at"], errors="coerce", utc=True
    )
    frame["fy"] = pd.to_numeric(frame["fy"], errors="coerce")
    frame["form"] = frame["form"].fillna("").astype(str).str.upper()
    frame["tag"] = frame["tag"].fillna("").astype(str)
    frame["unit"] = frame["unit"].fillna("").astype(str)
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(QUARTERLY_SURPRISE_COMPANYFACT_TAGS)
        & frame["period_start"].notna()
        & frame["period_end"].notna()
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(cutoff)
        & frame["form"].isin({"10-Q", "10-Q/A", "10-K", "10-K/A"})
    ].copy()
    if frame.empty:
        return frame
    is_shares = frame["tag"].isin(_SHARE_TAGS)
    frame = frame.loc[
        (is_shares & frame["unit"].str.lower().eq("shares"))
        | (~is_shares & frame["unit"].eq("USD"))
    ].copy()
    if frame.empty:
        return frame

    context = ["cik", "tag", "period_start", "period_end"]
    latest = frame.groupby(context)["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest)].copy()
    conflicts = frame.groupby(context)["value"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].copy()
    return (
        frame.sort_values(context + ["filed_at", "accession_number"])
        .drop_duplicates(context, keep="last")
        .reset_index(drop=True)
    )


def _quarter_candidates(
    tag_facts: pd.DataFrame,
    *,
    weighted_average: bool,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    contexts = tag_facts.sort_values(["period_end", "period_start", "available_at"])
    for current in contexts.to_dict(orient="records"):
        start = pd.Timestamp(current["period_start"])
        end = pd.Timestamp(current["period_end"])
        duration = int((end - start).days) + 1
        if 70 <= duration <= 115:
            rows.append(
                {
                    "period_end": end,
                    "value": float(current["value"]),
                    "available_at": pd.Timestamp(current["available_at"]),
                    "filed_at": pd.Timestamp(current["filed_at"]),
                    "evidence_count": 1,
                    "priority": 0,
                }
            )
            continue
        if not 130 <= duration <= 390:
            continue
        prior = contexts.loc[
            contexts["period_start"].eq(start)
            & contexts["period_end"].lt(end)
            & (end - contexts["period_end"]).dt.days.between(70, 115)
        ].sort_values("period_end")
        if prior.empty:
            continue
        previous = prior.iloc[-1]
        prior_duration = int(
            (pd.Timestamp(previous["period_end"]) - start).days
        ) + 1
        quarter_days = duration - prior_duration
        if not 70 <= quarter_days <= 115:
            continue
        current_value = float(current["value"])
        prior_value = float(previous["value"])
        if weighted_average:
            value = (
                current_value * duration - prior_value * prior_duration
            ) / quarter_days
        else:
            value = current_value - prior_value
        if not np.isfinite(value) or (weighted_average and value <= 0):
            continue
        rows.append(
            {
                "period_end": end,
                "value": float(value),
                "available_at": max(
                    pd.Timestamp(current["available_at"]),
                    pd.Timestamp(previous["available_at"]),
                ),
                "filed_at": max(
                    pd.Timestamp(current["filed_at"]),
                    pd.Timestamp(previous["filed_at"]),
                ),
                "evidence_count": 2,
                "priority": 1,
            }
        )
    candidates = pd.DataFrame(rows)
    if candidates.empty:
        return candidates
    selected: list[pd.Series] = []
    for _, period in candidates.groupby("period_end", sort=True):
        period = period.loc[period["priority"].eq(period["priority"].min())]
        values = period["value"].to_numpy(dtype=float)
        if not np.isclose(values, values[0], rtol=1e-9, atol=1e-12).all():
            continue
        selected.append(period.sort_values("available_at").iloc[-1])
    if not selected:
        return pd.DataFrame(columns=candidates.columns)
    return pd.DataFrame(selected).sort_values("period_end").reset_index(drop=True)


def _contiguous_tail(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    ordered = frame.sort_values("period_end").drop_duplicates("period_end", keep="last")
    gaps = ordered["period_end"].diff().dt.days
    breaks = np.flatnonzero(~gaps.fillna(90).between(70, 115).to_numpy())
    start = int(breaks[-1]) if len(breaks) else 0
    return ordered.iloc[start:].reset_index(drop=True)


def _best_quarter_series(
    issuer_facts: pd.DataFrame,
    tags: tuple[str, ...],
    *,
    weighted_average: bool = False,
) -> pd.DataFrame:
    best = pd.DataFrame()
    best_key = (-1, -1, 0)
    for priority, tag in enumerate(tags):
        candidate = _quarter_candidates(
            issuer_facts.loc[issuer_facts["tag"].eq(tag)],
            weighted_average=weighted_average,
        )
        tail = _contiguous_tail(candidate)
        key = (len(tail), len(candidate), -priority)
        if key > best_key:
            best = candidate
            best_key = key
    return best


def _ratio_series(
    numerator: pd.DataFrame,
    shares: pd.DataFrame,
) -> pd.DataFrame:
    if numerator.empty or shares.empty:
        return pd.DataFrame()
    merged = numerator.merge(
        shares,
        on="period_end",
        how="inner",
        suffixes=("_numerator", "_shares"),
        validate="one_to_one",
    )
    if merged.empty:
        return merged
    merged = merged.loc[merged["value_shares"].gt(0)].copy()
    merged["value"] = merged["value_numerator"] / merged["value_shares"]
    merged["available_at"] = merged[
        ["available_at_numerator", "available_at_shares"]
    ].max(axis=1)
    merged["filed_at"] = merged[["filed_at_numerator", "filed_at_shares"]].max(
        axis=1
    )
    merged["evidence_count"] = (
        merged["evidence_count_numerator"] + merged["evidence_count_shares"]
    )
    return _contiguous_tail(
        merged[
            [
                "period_end",
                "value",
                "available_at",
                "filed_at",
                "evidence_count",
            ]
        ]
    )


def _standardized_surprise(
    ratio: pd.DataFrame,
    *,
    scale_floor: float,
) -> tuple[float | None, pd.DataFrame]:
    tail = _contiguous_tail(ratio)
    if len(tail) < 21:
        return None, tail
    window = tail.tail(21).reset_index(drop=True)
    values = pd.to_numeric(window["value"], errors="coerce")
    if values.isna().any() or not np.isfinite(values).all():
        return None, window
    yoy = values - values.shift(4)
    drift = pd.concat([yoy.shift(lag) for lag in range(1, 9)], axis=1).mean(
        axis=1
    )
    surprise = yoy - drift
    history = pd.concat(
        [surprise.shift(lag) for lag in range(1, 9)], axis=1
    )
    latest_history = history.iloc[-1]
    latest = surprise.iloc[-1]
    if pd.isna(latest) or latest_history.isna().any():
        return None, window
    scale = float(latest_history.std(ddof=1))
    if not np.isfinite(scale) or abs(scale) <= scale_floor:
        return None, window
    value = float(latest) / scale
    return (value if np.isfinite(value) else None), window


def _output_row(
    *,
    identity: Any,
    signal: str,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
    value: float | None,
    evidence: pd.DataFrame,
) -> dict[str, Any]:
    spec = _SIGNAL_SPECS[signal]
    finite = value is not None and np.isfinite(float(value))
    period_end = evidence["period_end"].max() if not evidence.empty else pd.NaT
    filed_at = evidence["filed_at"].max() if not evidence.empty else pd.NaT
    available_at = evidence["available_at"].max() if not evidence.empty else pd.NaT
    cik = int(identity.cik)
    return {
        "security_id": str(identity.security_id),
        "ticker": str(identity.symbol),
        "cik": f"{cik:010d}",
        "signal": signal,
        "formation_at": formation.isoformat(),
        "period_end": (
            "" if pd.isna(period_end) else pd.Timestamp(period_end).date().isoformat()
        ),
        "filed_at": "" if pd.isna(filed_at) else pd.Timestamp(filed_at).isoformat(),
        "available_at": (
            "" if pd.isna(available_at) else pd.Timestamp(available_at).isoformat()
        ),
        "retrieved_at": retrieved.isoformat(),
        "value": float(value) if finite else float("nan"),
        "fidelity_class": "reconstructed" if finite else "unavailable",
        "current_usable": bool(finite),
        "source_id": "sec_edgar",
        "source_url": (
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        ),
        "formula_id": str(spec["formula_id"]),
        "formula_sha256": str(spec["formula_sha256"]),
        "observation_count": 21 if finite else int(len(evidence)),
        "reason_if_missing": (
            "" if finite else "insufficient_21_contiguous_quarters"
        ),
        "caveat": str(spec["caveat"]),
    }


def calculate_sec_quarterly_surprises_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate current reconstructed EarningsSurprise and RevenueSurprise."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("quarterly surprise formation_at or retrieved_at is invalid")
    identity = build_companyfacts_identity(status)
    facts = _normalise_facts(companyfacts, cutoff=min(formation, retrieved))
    rows: list[dict[str, Any]] = []
    for current in identity.itertuples(index=False):
        issuer = facts.loc[facts["cik"].eq(int(current.cik))].copy()
        income = _best_quarter_series(issuer, _INCOME_TAGS)
        revenue = _best_quarter_series(issuer, _REVENUE_TAGS)
        shares = _best_quarter_series(
            issuer,
            _SHARE_TAGS,
            weighted_average=True,
        )
        for signal, numerator in (
            ("EarningsSurprise", income),
            ("RevenueSurprise", revenue),
        ):
            ratio = _ratio_series(numerator, shares)
            value, evidence = _standardized_surprise(
                ratio,
                scale_floor=float(_SIGNAL_SPECS[signal]["scale_floor"]),
            )
            rows.append(
                _output_row(
                    identity=current,
                    signal=signal,
                    formation=formation,
                    retrieved=retrieved,
                    value=value,
                    evidence=evidence,
                )
            )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


__all__ = [
    "EARNINGS_SURPRISE_FORMULA_SHA256",
    "EARNINGS_SURPRISE_FORMULA_URL",
    "QUARTERLY_SURPRISE_COMPANYFACT_TAGS",
    "REVENUE_SURPRISE_FORMULA_SHA256",
    "REVENUE_SURPRISE_FORMULA_URL",
    "calculate_sec_quarterly_surprises_current",
]
