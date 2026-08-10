"""Causal selection and evidence assembly for rendered SEC real-estate pilots."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .sec_companyfacts_149 import build_companyfacts_identity
from .sec_rendered_reports import select_current_realestate_pilot_filings


_ASSET_COLUMNS = {
    "cik",
    "taxonomy",
    "tag",
    "unit",
    "value",
    "period_end",
    "form",
    "accession_number",
    "available_at",
    "source",
    "source_mode",
}
_STATUS_EVIDENCE_COLUMNS = {
    "cik",
    "surface",
    "status",
    "canonical_json_sha256",
    "source_mode",
    "source_url",
}


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{label} missing required columns: {missing}")


def _utc(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _causal_assets_for_filings(
    companyfacts: pd.DataFrame,
    filings: list[dict[str, Any]],
    *,
    formation_at: object,
) -> pd.DataFrame:
    _require_columns(companyfacts, _ASSET_COLUMNS, "SEC CompanyFacts")
    formation = _utc(formation_at)
    selected = pd.DataFrame(filings)[
        ["cik", "accession_number", "report_date"]
    ].copy()
    selected["cik"] = pd.to_numeric(selected["cik"], errors="coerce")
    selected["report_date"] = pd.to_datetime(
        selected["report_date"], errors="coerce", utc=True
    )

    facts = companyfacts.copy()
    facts["cik"] = pd.to_numeric(facts["cik"], errors="coerce")
    facts["value"] = pd.to_numeric(facts["value"], errors="coerce")
    facts["period_end"] = pd.to_datetime(
        facts["period_end"], errors="coerce", utc=True
    )
    facts["available_at"] = pd.to_datetime(
        facts["available_at"], errors="coerce", utc=True
    )
    facts = facts.loc[
        facts["cik"].notna()
        & facts["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & facts["tag"].fillna("").astype(str).eq("Assets")
        & facts["unit"].fillna("").astype(str).eq("USD")
        & facts["form"].fillna("").astype(str).isin({"10-K", "10-K/A"})
        & facts["value"].notna()
        & np.isfinite(facts["value"])
        & facts["period_end"].notna()
        & facts["available_at"].notna()
        & facts["available_at"].le(formation)
    ].copy()
    matched = facts.merge(
        selected,
        on=["cik", "accession_number"],
        how="inner",
        validate="many_to_one",
    )
    matched = matched.loc[matched["period_end"].eq(matched["report_date"])].copy()
    if matched.empty:
        return matched

    conflicts = matched.groupby("cik")["value"].transform("nunique").gt(1)
    matched = matched.loc[~conflicts].copy()
    return (
        matched.sort_values(["cik", "available_at"])
        .drop_duplicates("cik", keep="last")
        .reset_index(drop=True)
    )


def _companyfacts_source_evidence(status: pd.DataFrame) -> pd.DataFrame:
    _require_columns(status, _STATUS_EVIDENCE_COLUMNS, "SEC status")
    evidence = status.copy()
    evidence["cik"] = pd.to_numeric(evidence["cik"], errors="coerce")
    evidence = evidence.loc[
        evidence["cik"].notna()
        & evidence["surface"].eq("companyfacts")
        & evidence["status"].eq("ok")
        & evidence["canonical_json_sha256"].fillna("").astype(str).str.fullmatch(
            r"[0-9a-fA-F]{64}"
        )
    ].copy()
    conflicts = evidence.groupby("cik")["canonical_json_sha256"].transform(
        "nunique"
    ).gt(1)
    evidence = evidence.loc[~conflicts].copy()
    return evidence.sort_values("cik").drop_duplicates("cik", keep="last")


def select_realestate_sector_pilot_candidates(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: object,
    target_sic2: str,
    anchor_cik: object,
    minimum_issuers: int = 5,
    maximum_issuers: int = 12,
) -> list[dict[str, Any]]:
    """Choose asset-backed current filings for one bounded SEC SIC2 pilot."""

    if minimum_issuers < 5 or maximum_issuers < minimum_issuers:
        raise ValueError("realestate sector pilot requires at least five issuers")
    candidate_limit = max(int(submissions["cik"].nunique()), maximum_issuers)
    filings = select_current_realestate_pilot_filings(
        submissions.to_dict(orient="records"),
        formation_at=formation_at,
        target_sic2=target_sic2,
        anchor_cik=anchor_cik,
        minimum_issuers=minimum_issuers,
        maximum_issuers=candidate_limit,
    )
    assets = _causal_assets_for_filings(
        companyfacts,
        filings,
        formation_at=formation_at,
    )
    identity = build_companyfacts_identity(status).copy()
    identity["cik"] = pd.to_numeric(identity["cik"], errors="coerce")
    source = _companyfacts_source_evidence(status)
    frame = pd.DataFrame(filings)
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame = frame.merge(
        assets[
            [
                "cik",
                "value",
                "tag",
                "unit",
                "available_at",
                "source",
                "source_mode",
            ]
        ],
        on="cik",
        how="inner",
        validate="one_to_one",
    )
    frame = frame.merge(
        identity[["cik", "security_id", "symbol", "mapping_source"]],
        on="cik",
        how="inner",
        validate="one_to_one",
    )
    frame = frame.merge(
        source[
            [
                "cik",
                "canonical_json_sha256",
                "source_url",
            ]
        ],
        on="cik",
        how="inner",
        validate="one_to_one",
        suffixes=("", "_status"),
    )
    anchor = int(str(anchor_cik).strip())
    if anchor not in set(frame["cik"].astype(int)):
        raise ValueError("anchor CIK lacks causal assets or complete SEC identity")
    frame["anchor_priority"] = frame["cik"].astype(int).ne(anchor).astype(int)
    frame = frame.sort_values(
        ["anchor_priority", "value", "cik"],
        ascending=[True, False, True],
    ).head(maximum_issuers)
    if len(frame) < minimum_issuers:
        raise ValueError("fewer than five asset-backed causal issuers in target SIC2")

    selected: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        selected.append(
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key
                    not in {
                        "anchor_priority",
                        "value",
                        "tag",
                        "unit",
                        "available_at",
                        "canonical_json_sha256",
                        "source_url_status",
                    }
                },
                "cik": str(int(row["cik"])),
                "assets": float(row["value"]),
                "assets_tag": str(row["tag"]),
                "assets_unit": str(row["unit"]),
                "assets_available_at": pd.Timestamp(
                    row["available_at"]
                ).isoformat(),
                "assets_source_url": str(row["source"]),
                "assets_source_mode": str(row["source_mode"]),
                "assets_source_sha256": str(row["canonical_json_sha256"]).lower(),
                "formation_at": str(formation_at),
                "fidelity": "reconstructed_not_strict",
                "strict_score_eligible": False,
            }
        )
    return selected


__all__ = ["select_realestate_sector_pilot_candidates"]
