"""Causal selection and evidence assembly for rendered SEC real-estate pilots."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from .sec_companyfacts_149 import build_companyfacts_identity
from .sec_rendered_reports import (
    build_rendered_realestate_evidence,
    compute_current_realestate_cross_section,
    locate_rendered_ppe_report,
    select_current_realestate_pilot_filings,
)


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
_SEC_ARCHIVE_ROOT = "https://www.sec.gov/Archives/edgar/data"
_READTHROUGH_METHOD = "sec_via_jina_readthrough"


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


def _date(value: object) -> str:
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return ""


def assemble_realestate_sector_pilot(
    selected_candidates: Iterable[Mapping[str, Any]],
    issuer_evidence: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Assemble one current SIC2 cross-section from exact annual report periods."""

    candidates = [dict(row) for row in selected_candidates]
    evidence_rows = [dict(row) for row in issuer_evidence]
    evidence_by_cik: dict[str, dict[str, Any]] = {}
    for evidence in evidence_rows:
        records = [dict(row) for row in evidence.get("records") or []]
        ciks = {
            str(int(str(row.get("cik")))) for row in records if row.get("cik")
        }
        if len(ciks) != 1:
            continue
        cik = next(iter(ciks))
        if cik in evidence_by_cik:
            raise ValueError(f"duplicate rendered evidence for CIK {cik}")
        evidence_by_cik[cik] = {**evidence, "records": records}

    current_inputs: list[dict[str, Any]] = []
    failed_issuers: list[dict[str, str]] = []
    seen_candidates: set[str] = set()
    for candidate in candidates:
        try:
            cik = str(int(str(candidate.get("cik"))))
        except (TypeError, ValueError):
            failed_issuers.append(
                {"cik": str(candidate.get("cik") or ""), "reason": "invalid_cik"}
            )
            continue
        if cik in seen_candidates:
            raise ValueError(f"duplicate selected candidate CIK {cik}")
        seen_candidates.add(cik)
        evidence = evidence_by_cik.get(cik)
        report_date = _date(candidate.get("report_date"))
        matches = (
            [
                row
                for row in evidence.get("records", [])
                if _date(row.get("period_end")) == report_date
            ]
            if evidence is not None and evidence.get("raw_data_acquired") is True
            else []
        )
        if len(matches) != 1:
            failed_issuers.append(
                {
                    "cik": cik,
                    "reason": (
                        "matching_annual_period_missing"
                        if not matches
                        else "ambiguous_matching_annual_period"
                    ),
                }
            )
            continue
        rendered = dict(matches[0])
        try:
            rendered_available = _utc(rendered.get("available_at"))
            assets_available = _utc(candidate.get("assets_available_at"))
        except (TypeError, ValueError):
            failed_issuers.append(
                {"cik": cik, "reason": "invalid_available_at"}
            )
            continue
        current_inputs.append(
            {
                **rendered,
                **candidate,
                "cik": cik,
                "period_end": report_date,
                "rendered_available_at": rendered_available.isoformat(),
                "available_at": max(rendered_available, assets_available).isoformat(),
                "fidelity": "reconstructed_not_strict",
                "strict_score_eligible": False,
            }
        )

    adjusted = compute_current_realestate_cross_section(
        current_inputs,
        minimum_observations=5,
    )
    computed = sum(row["current_signal_computed"] is True for row in adjusted)
    acquired = len(current_inputs)
    if computed:
        status = "current_signal_computed"
        blocker = "strict_crsp_sic_and_compustat_equivalence_unvalidated"
    elif acquired:
        status = "blocked_coverage"
        blocker = "fewer_than_5_same_sic2_observations"
    else:
        status = "blocked_source_failure"
        blocker = "rendered_ppe_inputs_missing"
    return {
        "signal": "realestate",
        "status": status,
        "candidates_selected": len(candidates),
        "raw_issuers_acquired": acquired,
        "current_values_computed": computed,
        "strict_score_eligible": False,
        "fidelity": "reconstructed_not_strict",
        "proxy_used": True,
        "minimum_industry_observations": 5,
        "remaining_blocker": blocker,
        "failed_issuers": failed_issuers,
        "records": adjusted,
    }


def _retrieved_at(value: object | None) -> str:
    if value is not None:
        return str(value)
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _readthrough_access_url(source_url: str) -> str:
    return f"https://r.jina.ai/http://{source_url.removeprefix('https://')}"


def _markdown_content(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    if "Markdown Content:" in text:
        return text.split("Markdown Content:", 1)[1].strip()
    return text.strip()


def _acquire_readthrough_file(
    *,
    filename: str,
    source_url: str,
    destination: Path,
    client: Any,
    retry_delays: tuple[float, ...],
    retrieved_at: str,
) -> tuple[dict[str, Any], str]:
    access_url = _readthrough_access_url(source_url)
    last_error: Exception | None = None
    status_code = 0
    attempts = len(retry_delays) + 1
    for attempt in range(attempts):
        try:
            response = client.get(
                access_url,
                headers={
                    "User-Agent": "Aurora Research rendered SEC readthrough",
                    "X-No-Cache": "true",
                },
                timeout=(30, 300),
            )
            status_code = int(response.status_code)
            response.raise_for_status()
            content = bytes(response.content)
            markdown = _markdown_content(content)
            if len(markdown.encode("utf-8")) < 100:
                raise ValueError("rendered SEC readthrough returned empty content")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            return (
                {
                    "filename": filename,
                    "source_url": source_url,
                    "access_url": access_url,
                    "access_method": _READTHROUGH_METHOD,
                    "status": "downloaded",
                    "http_status": status_code,
                    "failure_reason": "",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "retrieved_at": retrieved_at,
                },
                markdown,
            )
        except Exception as exc:
            last_error = exc
            response = getattr(exc, "response", None)
            if response is not None and getattr(response, "status_code", None):
                status_code = int(response.status_code)
            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
    return (
        {
            "filename": filename,
            "source_url": source_url,
            "access_url": access_url,
            "access_method": _READTHROUGH_METHOD,
            "status": "failed",
            "http_status": status_code,
            "failure_reason": (
                f"{type(last_error).__name__}_after_{attempts}_attempts"
            ),
            "sha256": "",
            "size_bytes": 0,
            "retrieved_at": retrieved_at,
        },
        "",
    )


def acquire_rendered_realestate_filing(
    selected_filing: Mapping[str, Any],
    *,
    output_dir: Path | str,
    session: Any | None = None,
    retry_delays: tuple[float, ...] = (1.0, 2.0),
    retrieved_at: object | None = None,
) -> dict[str, Any]:
    """Acquire one rendered PP&E report with SEC origin and proxy provenance."""

    filing = dict(selected_filing)
    try:
        cik = str(int(str(filing["cik"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("rendered filing requires a numeric SEC CIK") from exc
    accession = str(filing.get("accession_number") or "").strip()
    if re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) is None:
        raise ValueError("rendered filing requires a canonical SEC accession")
    accession_compact = accession.replace("-", "")
    origin_root = f"{_SEC_ARCHIVE_ROOT}/{cik}/{accession_compact}"
    issuer_dir = Path(output_dir) / f"CIK{int(cik):010d}"
    timestamp = _retrieved_at(retrieved_at)
    client = session if session is not None else requests.Session()
    owns_session = session is None
    source_files: list[dict[str, Any]] = []
    try:
        summary_filename = "FilingSummary.xml"
        summary_row, summary_text = _acquire_readthrough_file(
            filename=summary_filename,
            source_url=f"{origin_root}/{summary_filename}",
            destination=issuer_dir / f"{summary_filename}.txt",
            client=client,
            retry_delays=retry_delays,
            retrieved_at=timestamp,
        )
        source_files.append(summary_row)
        report_filename = locate_rendered_ppe_report(summary_text)
        if not report_filename:
            evidence = build_rendered_realestate_evidence(
                selected_filing=filing,
                report_metadata={
                    "report_filename": "",
                    "source_url": "",
                    "access_url": "",
                    "access_method": _READTHROUGH_METHOD,
                    "sha256": "",
                    "size_bytes": 0,
                },
                report_text="",
            )
            evidence["remaining_blocker"] = "rendered_ppe_report_not_located"
            evidence["source_files"] = source_files
            return evidence
        report_row, report_text = _acquire_readthrough_file(
            filename=report_filename,
            source_url=f"{origin_root}/{report_filename}",
            destination=issuer_dir / f"{report_filename}.txt",
            client=client,
            retry_delays=retry_delays,
            retrieved_at=timestamp,
        )
        source_files.append(report_row)
        evidence = build_rendered_realestate_evidence(
            selected_filing=filing,
            report_metadata={
                "report_filename": report_filename,
                "source_url": report_row["source_url"],
                "access_url": report_row["access_url"],
                "access_method": report_row["access_method"],
                "sha256": report_row["sha256"],
                "size_bytes": report_row["size_bytes"],
            },
            report_text=report_text,
        )
        evidence["source_files"] = source_files
        return evidence
    finally:
        if owns_session:
            client.close()


def run_rendered_realestate_sector_batch(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: object,
    target_sic2: str,
    anchor_cik: object,
    source_run_id: object,
    output_dir: Path | str,
    minimum_issuers: int = 5,
    maximum_issuers: int = 12,
    retrieved_at: object | None = None,
) -> dict[str, Any]:
    """Acquire and persist one bounded rendered real-estate sector batch."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    timestamp = _retrieved_at(retrieved_at)
    candidates = select_realestate_sector_pilot_candidates(
        companyfacts,
        submissions,
        status,
        formation_at=formation_at,
        target_sic2=target_sic2,
        anchor_cik=anchor_cik,
        minimum_issuers=minimum_issuers,
        maximum_issuers=maximum_issuers,
    )
    (output / "openap_149_realestate_candidates.json").write_text(
        json.dumps(candidates, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    issuer_evidence: list[dict[str, Any]] = []
    acquisition_failures: list[dict[str, str]] = []
    manifest_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        cik = str(int(str(candidate["cik"])))
        try:
            evidence = acquire_rendered_realestate_filing(
                candidate,
                output_dir=output / "rendered_sources",
                retrieved_at=timestamp,
            )
        except Exception as exc:
            reason = f"acquisition_error:{type(exc).__name__}"
            acquisition_failures.append({"cik": cik, "reason": reason})
            evidence = {
                "signal": "realestate",
                "status": "acquisition_error",
                "raw_data_acquired": False,
                "current_signal_computed": False,
                "strict_score_eligible": False,
                "fidelity": "reconstructed_not_strict",
                "remaining_blocker": reason,
                "source_files": [],
                "records": [],
            }
        evidence = {**evidence, "selected_cik": cik}
        issuer_evidence.append(evidence)
        source_files = [dict(row) for row in evidence.get("source_files") or []]
        acquired = evidence.get("raw_data_acquired") is True
        manifest_rows.append(
            {
                "cik": cik,
                "security_id": str(candidate.get("security_id") or ""),
                "symbol": str(candidate.get("symbol") or ""),
                "accession_number": str(
                    candidate.get("accession_number") or ""
                ),
                "report_date": _date(candidate.get("report_date")),
                "status": (
                    "raw_data_acquired"
                    if acquired
                    else str(evidence.get("status") or "blocked_source_failure")
                ),
                "raw_data_acquired": acquired,
                "source_file_count": len(source_files),
                "downloaded_source_files": sum(
                    row.get("status") == "downloaded" for row in source_files
                ),
                "remaining_blocker": str(
                    evidence.get("remaining_blocker") or ""
                ),
                "formation_at": str(formation_at),
                "retrieved_at": timestamp,
                "fidelity": "reconstructed_not_strict",
                "strict_score_eligible": False,
            }
        )

    result = assemble_realestate_sector_pilot(candidates, issuer_evidence)
    failed_ciks = {row["cik"] for row in acquisition_failures}
    result["failed_issuers"] = acquisition_failures + [
        row for row in result["failed_issuers"] if row["cik"] not in failed_ciks
    ]
    result.update(
        {
            "source_run_id": str(source_run_id),
            "formation_at": str(formation_at),
            "target_sic2": str(target_sic2),
            "anchor_cik": str(int(str(anchor_cik))),
            "retrieved_at": timestamp,
            "locked_opened": False,
            "forward_opened": False,
            "validation_used_for_selection": False,
            "cost_eur": 0,
        }
    )

    raw_records = [
        {**dict(record), "selected_cik": evidence["selected_cik"]}
        for evidence in issuer_evidence
        for record in evidence.get("records") or []
    ]
    current_records = [
        dict(record)
        for record in result["records"]
        if record.get("current_signal_computed") is True
    ]
    pd.DataFrame(manifest_rows).to_csv(
        output / "openap_149_realestate_acquisition_manifest.csv",
        index=False,
    )
    pd.DataFrame(raw_records).to_csv(
        output / "openap_149_realestate_raw_records.csv",
        index=False,
    )
    current = pd.DataFrame(current_records)
    current.to_csv(output / "openap_149_realestate_current.csv", index=False)
    current.to_parquet(
        output / "openap_149_realestate_current.parquet",
        index=False,
        compression="zstd",
    )
    (output / "openap_149_realestate_issuer_evidence.json").write_text(
        json.dumps(issuer_evidence, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output / "openap_149_realestate_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return result


__all__ = [
    "acquire_rendered_realestate_filing",
    "assemble_realestate_sector_pilot",
    "run_rendered_realestate_sector_batch",
    "select_realestate_sector_pilot_candidates",
]
