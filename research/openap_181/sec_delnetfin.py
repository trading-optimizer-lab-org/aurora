"""Fail-closed current SEC reconstruction of OpenAP DelNetFin."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .sec_companyfacts_149 import build_companyfacts_identity


DELNETFIN_FORMULA_SHA256 = (
    "1830473d43cb94fcca0bf59d9c8f0403fc77a3617a96f517402fbe73e47344fa"
)
DELNETFIN_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/DelNetFin.py"
)

_CONCEPT_TAGS = {
    "assets": ("Assets",),
    "short_investments": ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
    "long_investments": ("LongTermInvestments", "OtherInvestments"),
    "debt_long": ("LongTermDebtNoncurrent",),
    "debt_current": ("LongTermDebtCurrent",),
    "preferred_stock": ("PreferredStockValue", "PreferredStockCarryingValue"),
}
_REQUIRED_CONCEPTS = (
    "assets",
    "short_investments",
    "long_investments",
    "debt_long",
    "debt_current",
)
DELNETFIN_COMPANYFACT_TAGS = frozenset(
    tag for tags in _CONCEPT_TAGS.values() for tag in tags
)
_FACT_COLUMNS = frozenset(
    {
        "cik",
        "taxonomy",
        "tag",
        "unit",
        "value",
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


def _normalise_annual_facts(
    companyfacts: pd.DataFrame,
    *,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    _require_columns(companyfacts, _FACT_COLUMNS, "SEC CompanyFacts")
    frame = companyfacts.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["period_end"] = pd.to_datetime(
        frame["period_end"], errors="coerce", utc=True
    )
    frame["filed_at"] = pd.to_datetime(frame["filed"], errors="coerce", utc=True)
    frame["available_at"] = pd.to_datetime(
        frame["available_at"], errors="coerce", utc=True
    )
    frame["form"] = frame["form"].fillna("").astype(str).str.upper()
    frame["unit"] = frame["unit"].fillna("").astype(str).str.upper()
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(DELNETFIN_COMPANYFACT_TAGS)
        & frame["unit"].eq("USD")
        & frame["period_end"].notna()
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(cutoff)
        & frame["form"].isin({"10-K", "10-K/A"})
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


def _monthly_tag_panel(tag_facts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for fact in tag_facts.to_dict(orient="records"):
        first_month = _month_start(pd.Timestamp(fact["period_end"])) + pd.DateOffset(
            months=6
        )
        for offset in range(12):
            rows.append(
                {
                    "month": first_month + pd.DateOffset(months=offset),
                    "tag": str(fact["tag"]),
                    "period_end": pd.Timestamp(fact["period_end"]),
                    "filed_at": pd.Timestamp(fact["filed_at"]),
                    "available_at": pd.Timestamp(fact["available_at"]),
                    "value": float(fact["value"]),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "month",
                "tag",
                "period_end",
                "filed_at",
                "available_at",
                "value",
            ]
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["month", "period_end", "available_at"])
        .drop_duplicates("month", keep="last")
        .reset_index(drop=True)
    )


def _best_concept_panel(
    issuer: pd.DataFrame,
    tags: tuple[str, ...],
    *,
    target_months: tuple[pd.Timestamp, pd.Timestamp],
) -> pd.DataFrame:
    best = pd.DataFrame()
    best_key = (-1, -1, 0)
    for priority, tag in enumerate(tags):
        candidate = _monthly_tag_panel(issuer.loc[issuer["tag"].eq(tag)])
        months = set(candidate["month"].tolist()) if not candidate.empty else set()
        coverage = sum(month in months for month in target_months)
        key = (coverage, len(candidate), -priority)
        if key > best_key:
            best = candidate
            best_key = key
    return best


def _select_formula_inputs(
    issuer: pd.DataFrame,
    *,
    formation_month: pd.Timestamp,
) -> tuple[dict[str, tuple[float, float]] | None, pd.DataFrame, str]:
    lag_month = formation_month - pd.DateOffset(months=12)
    target_months = (formation_month, lag_month)
    values: dict[str, tuple[float, float]] = {}
    evidence_rows: list[pd.Series] = []
    period_pairs: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for concept, tags in _CONCEPT_TAGS.items():
        panel = _best_concept_panel(
            issuer,
            tags,
            target_months=target_months,
        )
        indexed = panel.set_index("month", drop=False)
        selected = [
            indexed.loc[month] if month in indexed.index else None
            for month in target_months
        ]
        if concept == "preferred_stock":
            values[concept] = (
                0.0 if selected[0] is None else float(selected[0]["value"]),
                0.0 if selected[1] is None else float(selected[1]["value"]),
            )
            evidence_rows.extend(row for row in selected if row is not None)
            continue
        if any(row is None for row in selected):
            evidence = (
                pd.DataFrame(evidence_rows)
                if evidence_rows
                else panel.iloc[0:0].copy()
            )
            return None, evidence, "missing_required_annual_component"
        current_row, lag_row = selected
        assert current_row is not None and lag_row is not None
        values[concept] = (
            float(current_row["value"]),
            float(lag_row["value"]),
        )
        period_pairs[concept] = (
            pd.Timestamp(current_row["period_end"]),
            pd.Timestamp(lag_row["period_end"]),
        )
        evidence_rows.extend([current_row, lag_row])

    current_periods = {pair[0] for pair in period_pairs.values()}
    lag_periods = {pair[1] for pair in period_pairs.values()}
    evidence = pd.DataFrame(evidence_rows).drop_duplicates(
        ["tag", "period_end"]
    )
    if len(current_periods) != 1 or len(lag_periods) != 1:
        return None, evidence, "misaligned_annual_periods"
    current_period = next(iter(current_periods))
    lag_period = next(iter(lag_periods))
    gap_days = int((current_period - lag_period).days)
    if not 300 <= gap_days <= 430:
        return None, evidence, "misaligned_annual_periods"
    return values, evidence, ""


def _formula_value(values: dict[str, tuple[float, float]]) -> float | None:
    assets, assets_lag = values["assets"]
    denominator = 0.5 * (assets + assets_lag)
    if not np.isfinite(denominator) or denominator <= 0:
        return None
    current = (
        values["short_investments"][0]
        + values["long_investments"][0]
        - values["debt_long"][0]
        - values["debt_current"][0]
        - values["preferred_stock"][0]
    )
    lagged = (
        values["short_investments"][1]
        + values["long_investments"][1]
        - values["debt_long"][1]
        - values["debt_current"][1]
        - values["preferred_stock"][1]
    )
    result = (current - lagged) / denominator
    return float(result) if np.isfinite(result) else None


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
        "signal": "DelNetFin",
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
        "formula_id": "openap_delnetfin_sec_aggregate_components_6m_lag",
        "formula_sha256": DELNETFIN_FORMULA_SHA256,
        "observation_count": int(len(evidence)),
        "reason_if_missing": "" if finite else reason,
        "caveat": (
            "SEC aggregate tags reconstruct Compustat at/ivst/ivao/dltt/dlc/pstk; "
            "missing preferred stock follows the official zero rule, current SEC "
            "vintages can contain later restatements, and CIK/ticker is not a "
            "historical GVKEY/PERMNO bridge"
        ),
    }


def calculate_sec_delnetfin_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate current reconstructed DelNetFin from aligned annual SEC facts."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("DelNetFin formation_at or retrieved_at is invalid")
    identity = build_companyfacts_identity(status)
    facts = _normalise_annual_facts(
        companyfacts,
        cutoff=min(formation, retrieved),
    )
    formation_month = _month_start(formation)
    rows: list[dict[str, Any]] = []
    for current in identity.itertuples(index=False):
        issuer = facts.loc[facts["cik"].eq(int(current.cik))].copy()
        selected, evidence, reason = _select_formula_inputs(
            issuer,
            formation_month=formation_month,
        )
        value = _formula_value(selected) if selected is not None else None
        if selected is not None and value is None:
            reason = "invalid_average_assets_or_nonfinite_result"
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
    "DELNETFIN_COMPANYFACT_TAGS",
    "DELNETFIN_FORMULA_SHA256",
    "DELNETFIN_FORMULA_URL",
    "calculate_sec_delnetfin_current",
]
