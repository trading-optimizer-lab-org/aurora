"""Current SEC reconstruction of the OpenAP ``ChInvIA`` signal."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..openap_current_score import SEC_CONCEPT_ALIASES
from .sec_companyfacts_149 import build_companyfacts_identity


CHINVIA_FORMULA_SHA256 = (
    "09d5b9ae1836066d80de96b77352632246eafe30bbefb59fdf2c635291d90388"
)
CHINVIA_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/ChInvIA.py"
)

_CAPEX_TAGS = SEC_CONCEPT_ALIASES["capex"]
_PPE_TAGS = SEC_CONCEPT_ALIASES["ppe"]
_FACT_TAGS = frozenset(_CAPEX_TAGS + _PPE_TAGS)
_FACT_COLUMNS = frozenset(
    {
        "cik",
        "taxonomy",
        "tag",
        "unit",
        "value",
        "period_start",
        "period_end",
        "form",
        "filed",
        "accession_number",
        "available_at",
    }
)
_SUBMISSION_COLUMNS = frozenset(
    {"cik", "accession_number", "accepted_at", "sic"}
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
    frame["form"] = frame["form"].fillna("").astype(str).str.upper()
    frame["unit"] = frame["unit"].fillna("").astype(str).str.upper()
    duration = (frame["period_end"] - frame["period_start"]).dt.days
    annual_capex = frame["tag"].isin(_CAPEX_TAGS) & duration.between(300, 430)
    annual_ppe = frame["tag"].isin(_PPE_TAGS)
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(_FACT_TAGS)
        & frame["unit"].eq("USD")
        & frame["period_end"].notna()
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(cutoff)
        & frame["form"].isin({"10-K", "10-K/A"})
        & (annual_capex | annual_ppe)
    ].copy()
    if frame.empty:
        return frame
    context = ["cik", "tag", "period_end"]
    latest = frame.groupby(context)["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest)].copy()
    conflicts = frame.groupby(context)["value"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].copy()
    return (
        frame.sort_values(context + ["filed_at", "accession_number"])
        .drop_duplicates(context, keep="last")
        .reset_index(drop=True)
    )


def _normalise_sic(
    submissions: pd.DataFrame,
    *,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    _require_columns(submissions, _SUBMISSION_COLUMNS, "SEC submissions")
    frame = submissions.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["sic"] = pd.to_numeric(frame["sic"], errors="coerce")
    frame["accepted_at"] = pd.to_datetime(
        frame["accepted_at"], errors="coerce", utc=True
    )
    frame = frame.loc[
        frame["cik"].notna()
        & frame["sic"].between(1, 9999)
        & frame["accepted_at"].notna()
        & frame["accepted_at"].le(cutoff)
    ].copy()
    if frame.empty:
        return frame
    latest_at = frame.groupby("cik")["accepted_at"].transform("max")
    frame = frame.loc[frame["accepted_at"].eq(latest_at)].copy()
    conflicts = frame.groupby("cik")["sic"].transform("nunique").gt(1)
    return (
        frame.loc[~conflicts]
        .sort_values(["cik", "accepted_at", "accession_number"])
        .drop_duplicates("cik", keep="last")
        .assign(sic=lambda current: current["sic"].astype(int))
        .reset_index(drop=True)
    )


def _best_fact(
    issuer: pd.DataFrame,
    *,
    period_end: pd.Timestamp,
    tags: tuple[str, ...],
) -> pd.Series | None:
    subset = issuer.loc[issuer["period_end"].eq(period_end)].copy()
    for tag in tags:
        match = subset.loc[subset["tag"].eq(tag)]
        if not match.empty:
            return match.iloc[-1]
    return None


def _issuer_inputs(issuer: pd.DataFrame) -> tuple[dict[str, Any] | None, str]:
    periods = sorted(issuer["period_end"].dropna().unique(), reverse=True)[:4]
    if len(periods) < 2:
        return None, "fewer_than_two_annual_periods"
    period_ends = [pd.Timestamp(value) for value in periods]
    if any(
        not 300 <= int((newer - older).days) <= 430
        for newer, older in zip(period_ends, period_ends[1:])
    ):
        return None, "noncontiguous_annual_periods"

    evidence: list[pd.Series] = []

    def capex_at(index: int) -> float | None:
        if index >= len(period_ends):
            return None
        direct = _best_fact(
            issuer,
            period_end=period_ends[index],
            tags=_CAPEX_TAGS,
        )
        if direct is not None:
            evidence.append(direct)
            return float(direct["value"])
        if index + 1 >= len(period_ends):
            return None
        current_ppe = _best_fact(
            issuer,
            period_end=period_ends[index],
            tags=_PPE_TAGS,
        )
        lag_ppe = _best_fact(
            issuer,
            period_end=period_ends[index + 1],
            tags=_PPE_TAGS,
        )
        if current_ppe is None or lag_ppe is None:
            return None
        evidence.extend([current_ppe, lag_ppe])
        return float(current_ppe["value"]) - float(lag_ppe["value"])

    current = capex_at(0)
    lag_12 = capex_at(1)
    lag_24 = capex_at(2)
    if current is None or lag_12 is None:
        return None, "missing_current_or_lagged_capex"
    average_lags = (
        0.5 * (lag_12 + lag_24) if lag_24 is not None else None
    )
    if average_lags is not None and average_lags != 0:
        change = (current - average_lags) / average_lags
        denominator_mode = "average_lag_12_24"
    elif lag_12 != 0:
        change = (current - lag_12) / lag_12
        denominator_mode = "lag_12_fallback"
    else:
        return None, "zero_capex_denominator"
    if not np.isfinite(change):
        return None, "nonfinite_capex_change"
    selected = pd.DataFrame(evidence).drop_duplicates(
        ["tag", "period_end", "available_at"]
    )
    return {
        "raw_change": float(change),
        "period_end": period_ends[0],
        "filed_at": selected["filed_at"].max(),
        "available_at": selected["available_at"].max(),
        "observation_count": int(len(selected)),
        "denominator_mode": denominator_mode,
    }, ""


def calculate_sec_chinvia_current(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate current industry-adjusted CAPEX growth from causal SEC data."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("ChInvIA formation_at or retrieved_at is invalid")
    cutoff = min(formation, retrieved)
    identity = build_companyfacts_identity(status)
    facts = _normalise_facts(companyfacts, cutoff=cutoff)
    sic = _normalise_sic(submissions, cutoff=cutoff)
    facts_by_cik = {
        int(cik): issuer.copy() for cik, issuer in facts.groupby("cik", sort=False)
    }
    sic_by_cik = {
        int(row.cik): row for row in sic.itertuples(index=False)
    }
    candidates: list[dict[str, Any]] = []
    for current in identity.itertuples(index=False):
        cik = int(current.cik)
        issuer = facts_by_cik.get(cik)
        inputs, reason = (
            _issuer_inputs(issuer)
            if issuer is not None
            else (None, "no_causal_annual_capex_facts")
        )
        sic_row = sic_by_cik.get(cik)
        if sic_row is None:
            reason = "missing_unambiguous_current_sec_sic"
        candidates.append(
            {
                "identity": current,
                "inputs": inputs,
                "sic_row": sic_row,
                "sic2d": (
                    str(int(sic_row.sic))[:2]
                    if sic_row is not None
                    else ""
                ),
                "reason": reason,
            }
        )

    finite = pd.DataFrame(
        [
            {
                "cik": int(candidate["identity"].cik),
                "sic2d": candidate["sic2d"],
                "raw_change": float(candidate["inputs"]["raw_change"]),
            }
            for candidate in candidates
            if candidate["inputs"] is not None and candidate["sic_row"] is not None
        ]
    )
    industry_means = (
        finite.groupby("sic2d")["raw_change"].mean().to_dict()
        if not finite.empty
        else {}
    )

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        current = candidate["identity"]
        inputs = candidate["inputs"]
        sic_row = candidate["sic_row"]
        industry_mean = industry_means.get(candidate["sic2d"])
        usable = (
            inputs is not None
            and sic_row is not None
            and industry_mean is not None
        )
        value = (
            float(inputs["raw_change"] - industry_mean)
            if usable
            else float("nan")
        )
        evidence_available = (
            max(pd.Timestamp(inputs["available_at"]), pd.Timestamp(sic_row.accepted_at))
            if usable
            else pd.NaT
        )
        reason = "" if usable else str(candidate["reason"])
        if not usable and not reason:
            reason = "missing_two_digit_sic_industry_mean"
        cik = int(current.cik)
        rows.append(
            {
                "security_id": str(current.security_id),
                "ticker": str(current.symbol),
                "cik": f"{cik:010d}",
                "signal": "ChInvIA",
                "formation_at": formation.isoformat(),
                "period_end": (
                    pd.Timestamp(inputs["period_end"]).date().isoformat()
                    if usable
                    else ""
                ),
                "filed_at": (
                    pd.Timestamp(inputs["filed_at"]).isoformat() if usable else ""
                ),
                "available_at": (
                    evidence_available.isoformat() if usable else ""
                ),
                "retrieved_at": retrieved.isoformat(),
                "value": value,
                "fidelity_class": "reconstructed" if usable else "unavailable",
                "current_usable": bool(usable),
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{cik:010d}.json|"
                    f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
                ),
                "formula_id": "openap_chinvia_capex_growth_sic2d_mean_sec",
                "formula_sha256": CHINVIA_FORMULA_SHA256,
                "observation_count": (
                    int(inputs["observation_count"]) + 1 if usable else 0
                ),
                "reason_if_missing": reason,
                "caveat": (
                    "OpenAP ChInvIA formula reconstructed with as-filed SEC annual "
                    "CAPEX (PP&E-change fallback) and current SEC two-digit SIC; SEC "
                    "SIC is not historical CRSP SIC, current CIK/ticker is not "
                    "PERMNO, and the output is never strict-score eligible"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


__all__ = [
    "CHINVIA_FORMULA_SHA256",
    "CHINVIA_FORMULA_URL",
    "calculate_sec_chinvia_current",
]
