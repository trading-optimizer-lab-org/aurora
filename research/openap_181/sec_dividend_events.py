"""Fail-closed SEC reconstructions of positive OpenAP dividend events.

CompanyFacts does not provide CRSP ex-dates or distribution codes.  This
module emits only positive ``DivInit`` or ``DivOmit`` evidence from explicit
contiguous quarterly facts.  It never turns missing SEC facts into zero and
never emits a negative classification.  ``DivInit`` uses a guaranteed
six-month event window; ``DivOmit`` is explicitly a filing-delayed proxy.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .sec_companyfacts_149 import build_companyfacts_identity


DIVINIT_FORMULA_SHA256 = (
    "e0c4f285ef43006b43d86a25c16ef06d6ae9546ad1355bcdfad8f57dbdc02540"
)
DIVINIT_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/DivInit.py"
)
DIVOMIT_FORMULA_SHA256 = (
    "58c9383e66f2ba59f46921486ee3874d8a61c809a32b6228bc13db89e5a0395f"
)
DIVOMIT_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/DivOmit.py"
)
DIVSEASON_FORMULA_SHA256 = (
    "4442c8175d61e0237371bb7524a6c610332d9cd437be597390b0f518c9d5b2b9"
)
DIVSEASON_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/DivSeason.py"
)

_DIVIDEND_TAGS = (
    "CommonStockDividendsPerShareCashPaid",
    "CommonStockDividendsPerShareDeclared",
)
DIVIDEND_EVENT_COMPANYFACT_TAGS = frozenset(_DIVIDEND_TAGS)
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
    return pd.Timestamp(value.year, value.month, 1, tz="UTC")


def _normalise_dividend_facts(
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
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["value"].ge(-1e-9)
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(DIVIDEND_EVENT_COMPANYFACT_TAGS)
        & frame["unit"].isin({"usd/share", "usd/shares"})
        & frame["period_start"].notna()
        & frame["period_end"].notna()
        # A fact can be published before its labelled period in malformed,
        # projected, or otherwise non-historical SEC contexts.  It must not
        # enter a point-in-time event window merely because its filing is old
        # enough; the observed period itself must also be at or before cutoff.
        & frame["period_end"].le(cutoff)
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(cutoff)
        & frame["form"].isin({"10-Q", "10-Q/A", "10-K", "10-K/A"})
    ].copy()
    if frame.empty:
        return frame
    frame.loc[frame["value"].abs().le(1e-9), "value"] = 0.0
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


def _quarter_candidates(tag_facts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    contexts = tag_facts.sort_values(["period_end", "period_start", "available_at"])
    for current in contexts.to_dict(orient="records"):
        start = pd.Timestamp(current["period_start"])
        end = pd.Timestamp(current["period_end"])
        duration = int((end - start).days) + 1
        if 70 <= duration <= 115:
            rows.append(
                {
                    "period_start": start,
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
        value = float(current["value"]) - float(previous["value"])
        if not np.isfinite(value) or value < -1e-9:
            continue
        if abs(value) <= 1e-9:
            value = 0.0
        rows.append(
            {
                "period_start": pd.Timestamp(previous["period_end"])
                + pd.Timedelta(days=1),
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


def _latest_proven_initiation(
    issuer_facts: pd.DataFrame,
    *,
    formation_month: pd.Timestamp,
) -> tuple[pd.DataFrame, str]:
    for tag in _DIVIDEND_TAGS:
        quarters = _quarter_candidates(
            issuer_facts.loc[issuer_facts["tag"].eq(tag)]
        )
        if len(quarters) < 9:
            continue
        ordered = quarters.sort_values("period_end").reset_index(drop=True)
        candidates: list[pd.DataFrame] = []
        for end in range(8, len(ordered)):
            window = ordered.iloc[end - 8 : end + 1].copy()
            gaps = window["period_end"].diff().dt.days.iloc[1:]
            if not gaps.between(70, 115).all():
                continue
            if not window.iloc[:8]["value"].abs().le(1e-9).all():
                continue
            if float(window.iloc[-1]["value"]) <= 1e-9:
                continue
            event = window.iloc[-1]
            guaranteed_hold_end = _month_start(
                pd.Timestamp(event["period_start"])
            ) + pd.DateOffset(months=6)
            available_month = _month_start(pd.Timestamp(window["available_at"].max()))
            if available_month <= formation_month < guaranteed_hold_end:
                candidates.append(window)
        if candidates:
            return candidates[-1], ""
    return issuer_facts.iloc[0:0].copy(), (
        "no_complete_zero_to_positive_9q_sequence_in_guaranteed_hold_window"
    )


def _latest_proven_omission(
    issuer_facts: pd.DataFrame,
    *,
    formation_month: pd.Timestamp,
) -> tuple[pd.DataFrame, str]:
    for tag in _DIVIDEND_TAGS:
        quarters = _quarter_candidates(
            issuer_facts.loc[issuer_facts["tag"].eq(tag)]
        )
        if len(quarters) < 7:
            continue
        ordered = quarters.sort_values("period_end").reset_index(drop=True)
        candidates: list[pd.DataFrame] = []
        for end in range(6, len(ordered)):
            window = ordered.iloc[end - 6 : end + 1].copy()
            gaps = window["period_end"].diff().dt.days.iloc[1:]
            if not gaps.between(70, 115).all():
                continue
            if not window.iloc[:6]["value"].gt(1e-9).all():
                continue
            if abs(float(window.iloc[-1]["value"])) > 1e-9:
                continue
            detection_month = _month_start(
                pd.Timestamp(window["available_at"].max())
            )
            if detection_month <= formation_month < (
                detection_month + pd.DateOffset(months=2)
            ):
                candidates.append(window)
        if candidates:
            return candidates[-1], ""
    return issuer_facts.iloc[0:0].copy(), (
        "no_complete_6q_regular_to_zero_sequence_in_2m_detection_window"
    )


def _month_gap(later: pd.Timestamp, earlier: pd.Timestamp) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def _latest_proven_season(
    issuer_facts: pd.DataFrame,
    *,
    formation_month: pd.Timestamp,
) -> tuple[pd.DataFrame, str]:
    frequency_specs = (
        ("quarterly", 4, range(2, 5), (2, 5, 8, 11)),
        ("semiannual", 3, range(5, 8), (5, 11)),
        ("annual", 3, range(11, 14), (11,)),
    )
    for tag in _DIVIDEND_TAGS:
        direct = issuer_facts.loc[issuer_facts["tag"].eq(tag)].copy()
        duration = (direct["period_end"] - direct["period_start"]).dt.days + 1
        direct = direct.loc[
            duration.between(1, 45)
            & direct["value"].gt(1e-9)
            & direct["period_end"].lt(formation_month + pd.DateOffset(months=1))
        ].copy()
        if direct.empty:
            continue
        direct["event_month"] = direct["period_end"].map(_month_start)
        direct = (
            direct.sort_values(["event_month", "available_at"])
            .drop_duplicates("event_month", keep="last")
            .reset_index(drop=True)
        )
        for _name, required_events, allowed_gaps, signal_lags in frequency_specs:
            if len(direct) < required_events:
                continue
            history = direct.tail(required_events).copy()
            months = history["event_month"].tolist()
            gaps = [
                _month_gap(pd.Timestamp(months[index]), pd.Timestamp(months[index - 1]))
                for index in range(1, len(months))
            ]
            if not all(gap in allowed_gaps for gap in gaps):
                continue
            target_months = {
                formation_month - pd.DateOffset(months=lag) for lag in signal_lags
            }
            if set(months).intersection(target_months):
                history["evidence_count"] = 1
                return history, ""
    return issuer_facts.iloc[0:0].copy(), (
        "no_direct_monthly_regular_dividend_history_for_predicted_month"
    )


def _output_row(
    *,
    identity: Any,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
    evidence: pd.DataFrame,
    reason: str,
) -> dict[str, Any]:
    usable = not evidence.empty
    cik = int(identity.cik)
    period_end = evidence["period_end"].max() if usable else pd.NaT
    filed_at = evidence["filed_at"].max() if usable else pd.NaT
    available_at = evidence["available_at"].max() if usable else pd.NaT
    observation_count = (
        int(evidence["evidence_count"].sum()) if usable else 0
    )
    return {
        "security_id": str(identity.security_id),
        "ticker": str(identity.symbol),
        "cik": f"{cik:010d}",
        "signal": "DivInit",
        "formation_at": formation.isoformat(),
        "period_end": (
            ""
            if pd.isna(period_end)
            else pd.Timestamp(period_end).date().isoformat()
        ),
        "filed_at": (
            "" if pd.isna(filed_at) else pd.Timestamp(filed_at).isoformat()
        ),
        "available_at": (
            "" if pd.isna(available_at) else pd.Timestamp(available_at).isoformat()
        ),
        "retrieved_at": retrieved.isoformat(),
        "value": 1.0 if usable else float("nan"),
        "fidelity_class": "reconstructed" if usable else "unavailable",
        "current_usable": usable,
        "source_id": "sec_edgar",
        "source_url": (
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        ),
        "formula_id": "openap_divinit_positive_sec_9q_guaranteed_6m_window",
        "formula_sha256": DIVINIT_FORMULA_SHA256,
        "observation_count": observation_count,
        "reason_if_missing": "" if usable else reason,
        "caveat": (
            "SEC common dividends per share prove a delayed positive initiation "
            "only; quarter boundaries replace CRSP ex-dates, distribution codes "
            "are unavailable, no negative classifications are emitted, and current "
            "CIK/ticker is not a historical PERMNO bridge"
        ),
    }


def _output_omission_row(
    *,
    identity: Any,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
    evidence: pd.DataFrame,
    reason: str,
) -> dict[str, Any]:
    usable = not evidence.empty
    cik = int(identity.cik)
    period_end = evidence["period_end"].max() if usable else pd.NaT
    filed_at = evidence["filed_at"].max() if usable else pd.NaT
    available_at = evidence["available_at"].max() if usable else pd.NaT
    observation_count = (
        int(evidence["evidence_count"].sum()) if usable else 0
    )
    return {
        "security_id": str(identity.security_id),
        "ticker": str(identity.symbol),
        "cik": f"{cik:010d}",
        "signal": "DivOmit",
        "formation_at": formation.isoformat(),
        "period_end": (
            ""
            if pd.isna(period_end)
            else pd.Timestamp(period_end).date().isoformat()
        ),
        "filed_at": (
            "" if pd.isna(filed_at) else pd.Timestamp(filed_at).isoformat()
        ),
        "available_at": (
            "" if pd.isna(available_at) else pd.Timestamp(available_at).isoformat()
        ),
        "retrieved_at": retrieved.isoformat(),
        "value": 1.0 if usable else float("nan"),
        "fidelity_class": "reconstructed" if usable else "unavailable",
        "current_usable": usable,
        "source_id": "sec_edgar",
        "source_url": (
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        ),
        "formula_id": "openap_divomit_positive_sec_6q_regular_then_zero_2m",
        "formula_sha256": DIVOMIT_FORMULA_SHA256,
        "observation_count": observation_count,
        "reason_if_missing": "" if usable else reason,
        "caveat": (
            "SEC quarterly common dividends per share prove a delayed omission "
            "proxy only; the two-month window starts at filing availability, not "
            "the unavailable CRSP ex-date, distribution frequency codes are not "
            "reproduced, no negative classifications are emitted, and current "
            "CIK/ticker is not a historical PERMNO bridge"
        ),
    }


def _output_season_row(
    *,
    identity: Any,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
    evidence: pd.DataFrame,
    reason: str,
) -> dict[str, Any]:
    usable = not evidence.empty
    cik = int(identity.cik)
    period_end = evidence["period_end"].max() if usable else pd.NaT
    filed_at = evidence["filed_at"].max() if usable else pd.NaT
    available_at = evidence["available_at"].max() if usable else pd.NaT
    return {
        "security_id": str(identity.security_id),
        "ticker": str(identity.symbol),
        "cik": f"{cik:010d}",
        "signal": "DivSeason",
        "formation_at": formation.isoformat(),
        "period_end": (
            ""
            if pd.isna(period_end)
            else pd.Timestamp(period_end).date().isoformat()
        ),
        "filed_at": (
            "" if pd.isna(filed_at) else pd.Timestamp(filed_at).isoformat()
        ),
        "available_at": (
            "" if pd.isna(available_at) else pd.Timestamp(available_at).isoformat()
        ),
        "retrieved_at": retrieved.isoformat(),
        "value": 1.0 if usable else float("nan"),
        "fidelity_class": "reconstructed" if usable else "unavailable",
        "current_usable": usable,
        "source_id": "sec_edgar",
        "source_url": (
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        ),
        "formula_id": "openap_divseason_positive_sec_direct_month_frequency",
        "formula_sha256": DIVSEASON_FORMULA_SHA256,
        "observation_count": int(len(evidence)) if usable else 0,
        "reason_if_missing": "" if usable else reason,
        "caveat": (
            "SEC direct one-month common-dividend contexts infer payment frequency "
            "and a positive seasonal month only; period end replaces CRSP ex-date, "
            "CRSP distribution codes are unavailable, no zero classifications are "
            "emitted, and current CIK/ticker is not a historical PERMNO bridge"
        ),
    }


def calculate_sec_divinit_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate conservative positive current DivInit evidence from SEC facts."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("DivInit formation_at or retrieved_at is invalid")
    identity = build_companyfacts_identity(status)
    facts = _normalise_dividend_facts(
        companyfacts,
        cutoff=min(formation, retrieved),
    )
    formation_month = _month_start(formation)
    rows: list[dict[str, Any]] = []
    for current in identity.itertuples(index=False):
        issuer = facts.loc[facts["cik"].eq(int(current.cik))].copy()
        evidence, reason = _latest_proven_initiation(
            issuer,
            formation_month=formation_month,
        )
        rows.append(
            _output_row(
                identity=current,
                formation=formation,
                retrieved=retrieved,
                evidence=evidence,
                reason=reason,
            )
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


def calculate_sec_divomit_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate delayed positive DivOmit evidence from explicit SEC quarters."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("DivOmit formation_at or retrieved_at is invalid")
    identity = build_companyfacts_identity(status)
    facts = _normalise_dividend_facts(
        companyfacts,
        cutoff=min(formation, retrieved),
    )
    formation_month = _month_start(formation)
    rows: list[dict[str, Any]] = []
    for current in identity.itertuples(index=False):
        issuer = facts.loc[facts["cik"].eq(int(current.cik))].copy()
        evidence, reason = _latest_proven_omission(
            issuer,
            formation_month=formation_month,
        )
        rows.append(
            _output_omission_row(
                identity=current,
                formation=formation,
                retrieved=retrieved,
                evidence=evidence,
                reason=reason,
            )
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


def calculate_sec_divseason_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate positive DivSeason evidence from direct monthly SEC facts."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("DivSeason formation_at or retrieved_at is invalid")
    identity = build_companyfacts_identity(status)
    facts = _normalise_dividend_facts(
        companyfacts,
        cutoff=min(formation, retrieved),
    )
    formation_month = _month_start(formation)
    rows: list[dict[str, Any]] = []
    for current in identity.itertuples(index=False):
        issuer = facts.loc[facts["cik"].eq(int(current.cik))].copy()
        evidence, reason = _latest_proven_season(
            issuer,
            formation_month=formation_month,
        )
        rows.append(
            _output_season_row(
                identity=current,
                formation=formation,
                retrieved=retrieved,
                evidence=evidence,
                reason=reason,
            )
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


__all__ = [
    "DIVIDEND_EVENT_COMPANYFACT_TAGS",
    "DIVINIT_FORMULA_SHA256",
    "DIVINIT_FORMULA_URL",
    "DIVOMIT_FORMULA_SHA256",
    "DIVOMIT_FORMULA_URL",
    "DIVSEASON_FORMULA_SHA256",
    "DIVSEASON_FORMULA_URL",
    "calculate_sec_divinit_current",
    "calculate_sec_divomit_current",
    "calculate_sec_divseason_current",
]
