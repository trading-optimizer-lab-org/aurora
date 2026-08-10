"""Current SEC reconstruction of OpenAP EarningsConsistency.

The pinned OpenAP data preparation makes annual Compustat observations
available six months after fiscal year-end and repeats each observation for
12 months.  This module reproduces that calendar and the pinned predictor
formula with SEC basic EPS, while retaining reconstructed (never strict)
fidelity because SEC EarningsPerShareBasic is not proven identical to
Compustat epspx.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .sec_companyfacts_149 import build_companyfacts_identity


EARNINGS_CONSISTENCY_FORMULA_SHA256 = (
    "f47fc929d4c0c52faccad8e04fb76bc628bbbf93a87988279edc5059def00914"
)
EARNINGS_CONSISTENCY_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/EarningsConsistency.py"
)
EARNINGS_CONSISTENCY_DATA_PREP_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "DataDownloads/CompustatAnnual.py"
)
EARNINGS_CONSISTENCY_COMPANYFACT_TAGS = frozenset({"EarningsPerShareBasic"})

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


def _month_start(value: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(
        year=value.year,
        month=value.month,
        day=1,
        tz="UTC",
    )


def _normalise_annual_eps(
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
    frame["unit"] = (
        frame["unit"]
        .fillna("")
        .astype(str)
        .str.replace(" ", "", regex=False)
        .str.lower()
    )
    duration = (frame["period_end"] - frame["period_start"]).dt.days + 1
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].eq("EarningsPerShareBasic")
        & frame["unit"].isin({"usd/share", "usd/shares"})
        & frame["period_start"].notna()
        & frame["period_end"].notna()
        & duration.between(300, 390)
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(cutoff)
        & frame["form"].isin({"10-K", "10-K/A"})
    ].copy()
    if frame.empty:
        return frame

    context = ["cik", "period_end"]
    latest = frame.groupby(context)["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest)].copy()
    conflicts = frame.groupby(context)["value"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].copy()
    return (
        frame.sort_values(context + ["filed_at", "accession_number"])
        .drop_duplicates(context, keep="last")
        .reset_index(drop=True)
    )


def _monthly_eps(annual: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for fact in annual.to_dict(orient="records"):
        official_month = _month_start(
            pd.Timestamp(fact["period_end"])
        ) + pd.DateOffset(months=6)
        for offset in range(12):
            month = official_month + pd.DateOffset(months=offset)
            rows.append(
                {
                    "month": month,
                    "period_end": pd.Timestamp(fact["period_end"]),
                    "filed_at": pd.Timestamp(fact["filed_at"]),
                    "available_at": pd.Timestamp(fact["available_at"]),
                    "value": float(fact["value"]),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=["month", "period_end", "filed_at", "available_at", "value"]
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["month", "period_end", "available_at"])
        .drop_duplicates("month", keep="last")
        .reset_index(drop=True)
    )


def _growth(
    current: float | None,
    lag12: float | None,
    lag24: float | None,
) -> float | None:
    if current is None or lag12 is None or lag24 is None:
        return None
    denominator = 0.5 * (abs(lag12) + abs(lag24))
    if not np.isfinite(denominator) or denominator == 0:
        return None
    value = (current - lag12) / denominator
    return float(value) if np.isfinite(value) else None


def _formula_value(
    monthly: pd.DataFrame,
    *,
    formation_month: pd.Timestamp,
) -> tuple[float | None, pd.DataFrame, str]:
    by_month = monthly.set_index("month", drop=False)
    selected: dict[int, pd.Series] = {}
    for lag in range(0, 73, 12):
        month = formation_month - pd.DateOffset(months=lag)
        if month in by_month.index:
            selected[lag] = by_month.loc[month]
    evidence = (
        pd.DataFrame(list(selected.values()))
        .drop_duplicates("period_end")
        .sort_values("period_end")
        .reset_index(drop=True)
        if selected
        else monthly.iloc[0:0].copy()
    )
    eps = {lag: float(row["value"]) for lag, row in selected.items()}
    current = eps.get(0)
    lag12 = eps.get(12)
    if current is None or lag12 is None:
        return None, evidence, "insufficient_annual_eps_history"

    growth = {
        lag: _growth(eps.get(lag), eps.get(lag + 12), eps.get(lag + 24))
        for lag in range(0, 49, 12)
    }
    current_growth = growth[0]
    prior_growth = growth[12]
    extreme = (abs(current / lag12) > 6) if lag12 != 0 else current != 0
    exception = (
        extreme
        or (
            current_growth is not None
            and prior_growth is not None
            and current_growth > 0
            and prior_growth < 0
        )
        or (
            current_growth is not None
            and current_growth < 0
            and (prior_growth is None or prior_growth > 0)
        )
    )
    if exception:
        return None, evidence, "official_exception_filter"
    finite_growth = [value for value in growth.values() if value is not None]
    if not finite_growth:
        return None, evidence, "insufficient_annual_eps_history"
    value = float(np.mean(finite_growth))
    if not np.isfinite(value):
        return None, evidence, "nonfinite_formula_result"
    return value, evidence, ""


def _output_row(
    *,
    identity: Any,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
    value: float | None,
    evidence: pd.DataFrame,
    reason: str,
) -> dict[str, Any]:
    finite = value is not None and np.isfinite(float(value))
    period_end = evidence["period_end"].max() if not evidence.empty else pd.NaT
    filed_at = evidence["filed_at"].max() if not evidence.empty else pd.NaT
    available_at = evidence["available_at"].max() if not evidence.empty else pd.NaT
    cik = int(identity.cik)
    return {
        "security_id": str(identity.security_id),
        "ticker": str(identity.symbol),
        "cik": f"{cik:010d}",
        "signal": "EarningsConsistency",
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
        "formula_id": "openap_earnings_consistency_sec_basic_eps_6m_lag",
        "formula_sha256": EARNINGS_CONSISTENCY_FORMULA_SHA256,
        "observation_count": int(len(evidence)),
        "reason_if_missing": "" if finite else reason,
        "caveat": (
            "SEC EarningsPerShareBasic reconstructs Compustat epspx; the six-month "
            "OpenAP availability convention is reproduced from the current SEC "
            "vintage, which can include later restatements; current CIK/ticker is "
            "not a historical GVKEY/PERMNO bridge"
        ),
    }


def calculate_sec_earnings_consistency_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate current reconstructed EarningsConsistency from SEC basic EPS."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("earnings consistency formation_at or retrieved_at is invalid")
    identity = build_companyfacts_identity(status)
    facts = _normalise_annual_eps(
        companyfacts,
        cutoff=min(formation, retrieved),
    )
    formation_month = _month_start(formation)
    rows: list[dict[str, Any]] = []
    for current in identity.itertuples(index=False):
        issuer = facts.loc[facts["cik"].eq(int(current.cik))].copy()
        value, evidence, reason = _formula_value(
            _monthly_eps(issuer),
            formation_month=formation_month,
        )
        rows.append(
            _output_row(
                identity=current,
                formation=formation,
                retrieved=retrieved,
                value=value,
                evidence=evidence,
                reason=reason,
            )
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


__all__ = [
    "EARNINGS_CONSISTENCY_COMPANYFACT_TAGS",
    "EARNINGS_CONSISTENCY_DATA_PREP_URL",
    "EARNINGS_CONSISTENCY_FORMULA_SHA256",
    "EARNINGS_CONSISTENCY_FORMULA_URL",
    "calculate_sec_earnings_consistency_current",
]
