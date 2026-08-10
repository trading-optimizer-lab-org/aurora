"""Verified, bounded loading of SEC Notes listing-identity facts.

This module performs no network access and writes no artifacts.  It accepts one
previously downloaded official SEC Notes archive only when the accompanying
transport manifest proves its URL, HTTP result, byte size, and SHA-256 digest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import zipfile
from typing import Iterable

import pandas as pd

from .sec_fsd_access import (
    OFFICIAL_NOTES_URL_TEMPLATE,
    SEC_FSD_MANIFEST_COLUMNS,
    SEC_NOTES_ACCESS_METHOD,
)
from .sec_listing_identity import (
    LISTING_CONCEPTS,
    PERIODIC_FORMS,
    normalize_sec_notes_listing_facts,
)


_PERIOD_RE = re.compile(r"^(?:20[0-9]{2}q[1-4]|20[0-9]{2}_(?:0[1-9]|1[0-2]))$")
_ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUB_COLUMNS = ["adsh", "cik", "form", "accepted", "instance"]
_TXT_COLUMNS = ["adsh", "tag", "version", "context", "iprx", "value"]
_TXT_CHUNK_ROWS = 250_000

# Current official Notes archives are hundreds of MiB compressed and can be
# several GiB uncompressed.  These bounds admit that documented scale while
# refusing an unrelated or malicious archive before pandas reads it.
_MAX_ARCHIVE_SIZE_BYTES = 2 * 1024**3
_MAX_SUB_UNCOMPRESSED_BYTES = 1024**3
_MAX_TXT_UNCOMPRESSED_BYTES = 16 * 1024**3


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _normalize_cik(value: object) -> str:
    text = _clean_text(value)
    if re.fullmatch(r"[0-9]{1,10}", text):
        return f"{int(text):010d}"
    if re.fullmatch(r"[0-9]{1,10}\.0", text):
        return f"{int(float(text)):010d}"
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_allowed_ciks(values: Iterable[object]) -> frozenset[str]:
    raw = tuple(values)
    normalized = frozenset(_normalize_cik(value) for value in raw)
    if not raw or "" in normalized or len(normalized) != len(raw):
        raise ValueError(
            "allowed_ciks must contain unique, valid SEC CIK identifiers"
        )
    return normalized


def _validated_source_manifest(
    source_manifest: pd.DataFrame,
    archive_path: Path,
) -> pd.Series:
    missing = sorted(
        set(SEC_FSD_MANIFEST_COLUMNS).difference(source_manifest.columns)
    )
    if missing:
        raise ValueError(f"SEC Notes source manifest is missing columns: {missing}")
    if len(source_manifest) != 1:
        raise ValueError("SEC Notes source manifest must contain exactly one row")

    row = source_manifest.iloc[0]
    period = _clean_text(row["period"]).lower()
    if _PERIOD_RE.fullmatch(period) is None:
        raise ValueError("SEC Notes source manifest has an invalid period")
    expected_url = OFFICIAL_NOTES_URL_TEMPLATE.format(period=period)
    if (
        _clean_text(row["source_id"]) != f"sec_notes_{period}"
        or _clean_text(row["source_url"]) != expected_url
        or _clean_text(row["access_url"]) != expected_url
        or _clean_text(row["access_method"]) != SEC_NOTES_ACCESS_METHOD
    ):
        raise ValueError(
            "SEC Notes source manifest is not exact official SEC evidence"
        )
    status = _clean_text(row["status"])
    http_status = pd.to_numeric(row["http_status"], errors="coerce")
    if (
        status != "downloaded"
        or pd.isna(http_status)
        or float(http_status) != 200.0
    ):
        raise ValueError("SEC Notes archive requires downloaded HTTP 200 evidence")
    if _clean_text(row["failure_reason"]):
        raise ValueError(
            "Downloaded SEC Notes evidence must not contain a failure reason"
        )

    retrieved_at = pd.to_datetime(row["retrieved_at"], errors="coerce", utc=True)
    if pd.isna(retrieved_at):
        raise ValueError("SEC Notes source manifest has an invalid retrieved_at")
    if archive_path.name.lower() != f"{period}_notes.zip":
        raise ValueError("SEC Notes archive filename does not match its period")
    if not archive_path.is_file():
        raise ValueError(f"Missing SEC Notes archive: {archive_path.name}")

    archive_size = archive_path.stat().st_size
    expected_size = pd.to_numeric(row["size_bytes"], errors="coerce")
    if (
        archive_size <= 0
        or archive_size > _MAX_ARCHIVE_SIZE_BYTES
        or pd.isna(expected_size)
        or float(expected_size) != float(archive_size)
    ):
        raise ValueError("SEC Notes archive size does not match its manifest")
    expected_hash = _clean_text(row["sha256"]).lower()
    if _SHA256_RE.fullmatch(expected_hash) is None:
        raise ValueError("SEC Notes source manifest has an invalid SHA-256")
    if _sha256(archive_path) != expected_hash:
        raise ValueError("SEC Notes archive SHA-256 does not match its manifest")
    return row


def _member(
    archive: zipfile.ZipFile,
    expected_basename: str,
    *,
    maximum_uncompressed_bytes: int,
) -> zipfile.ZipInfo:
    matches = [
        info
        for info in archive.infolist()
        if Path(info.filename).name.lower() == expected_basename
    ]
    if len(matches) != 1:
        raise ValueError(
            f"SEC Notes archive requires exactly one {expected_basename}"
        )
    info = matches[0]
    if info.is_dir() or info.flag_bits & 0x1:
        raise ValueError(f"SEC Notes {expected_basename} is not a plain file")
    if info.file_size <= 0 or info.file_size > maximum_uncompressed_bytes:
        raise ValueError(
            f"SEC Notes {expected_basename} has an unsafe uncompressed size"
        )
    return info


def _read_submissions(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    allowed_ciks: frozenset[str],
) -> pd.DataFrame:
    with archive.open(member) as handle:
        submissions = pd.read_csv(
            handle,
            sep="\t",
            usecols=_SUB_COLUMNS,
            dtype="string",
            low_memory=False,
        )
    submissions["_cik"] = submissions["cik"].map(_normalize_cik)
    submissions["_adsh"] = submissions["adsh"].map(_clean_text)
    submissions["_form"] = (
        submissions["form"].fillna("").astype(str).str.strip().str.upper()
    )
    submissions = submissions.loc[
        submissions["_cik"].isin(allowed_ciks)
        & submissions["_form"].isin(PERIODIC_FORMS)
    ].copy()
    if not submissions["_adsh"].str.fullmatch(_ACCESSION_RE).all():
        raise ValueError(
            "SEC Notes SUB contains an invalid target listing accession"
        )
    submissions["cik"] = submissions["_cik"]
    submissions["adsh"] = submissions["_adsh"]
    submissions["form"] = submissions["_form"]
    return submissions[_SUB_COLUMNS].reset_index(drop=True)


def _read_listing_text_facts(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    allowed_accessions: frozenset[str],
) -> tuple[pd.DataFrame, int]:
    frames: list[pd.DataFrame] = []
    rows_scanned = 0
    with archive.open(member) as handle:
        chunks = pd.read_csv(
            handle,
            sep="\t",
            usecols=_TXT_COLUMNS,
            dtype="string",
            chunksize=_TXT_CHUNK_ROWS,
            low_memory=False,
        )
        for chunk in chunks:
            rows_scanned += len(chunk)
            if not allowed_accessions:
                continue
            reduced = chunk.loc[
                chunk["adsh"].fillna("").astype(str).isin(allowed_accessions)
                & chunk["tag"].fillna("").astype(str).isin(LISTING_CONCEPTS)
            ].copy()
            if not reduced.empty:
                frames.append(reduced)
    if not frames:
        return pd.DataFrame(columns=_TXT_COLUMNS), rows_scanned
    return pd.concat(frames, ignore_index=True)[_TXT_COLUMNS], rows_scanned


def load_sec_notes_listing_facts(
    archive_path: Path | str,
    source_manifest: pd.DataFrame,
    *,
    allowed_ciks: Iterable[object],
) -> tuple[pd.DataFrame, dict[str, int | str]]:
    """Load exact listing facts from one verified official SEC Notes ZIP."""

    archive_file = Path(archive_path)
    manifest = _validated_source_manifest(source_manifest, archive_file)
    cik_filter = _validated_allowed_ciks(allowed_ciks)
    try:
        with zipfile.ZipFile(archive_file) as archive:
            sub_member = _member(
                archive,
                "sub.txt",
                maximum_uncompressed_bytes=_MAX_SUB_UNCOMPRESSED_BYTES,
            )
            txt_member = _member(
                archive,
                "txt.txt",
                maximum_uncompressed_bytes=_MAX_TXT_UNCOMPRESSED_BYTES,
            )
            submissions = _read_submissions(archive, sub_member, cik_filter)
            accessions = frozenset(submissions["adsh"].astype(str))
            text_facts, rows_scanned = _read_listing_text_facts(
                archive,
                txt_member,
                accessions,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError("SEC Notes archive is not a valid ZIP file") from exc

    facts = normalize_sec_notes_listing_facts(
        submissions,
        text_facts,
        dataset_source_url=_clean_text(manifest["source_url"]),
        dataset_sha256=_clean_text(manifest["sha256"]),
    )
    summary: dict[str, int | str] = {
        "archive_size_bytes": archive_file.stat().st_size,
        "eligible_submission_rows": len(submissions),
        "listing_fact_rows": len(facts),
        "source_period": _clean_text(manifest["period"]).lower(),
        "txt_rows_scanned": rows_scanned,
    }
    return facts, summary


def load_sec_notes_listing_history(
    archive_dir: Path | str,
    source_manifest: pd.DataFrame,
    *,
    allowed_ciks: Iterable[object],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load a non-overlapping set of verified SEC Notes archive periods."""

    missing = sorted(
        set(SEC_FSD_MANIFEST_COLUMNS).difference(source_manifest.columns)
    )
    if missing:
        raise ValueError(f"SEC Notes source manifest is missing columns: {missing}")
    if source_manifest.empty:
        raise ValueError("SEC Notes history requires at least one archive period")
    periods = source_manifest["period"].map(_clean_text).str.lower()
    if periods.eq("").any() or periods.duplicated(keep=False).any():
        raise ValueError("SEC Notes history periods must be unique and non-empty")

    root = Path(archive_dir)
    cik_filter = _validated_allowed_ciks(allowed_ciks)
    fact_frames: list[pd.DataFrame] = []
    summaries: list[dict[str, int | str]] = []
    ordered = source_manifest.assign(_period=periods).sort_values(
        "_period",
        kind="stable",
    )
    for _, row in ordered.iterrows():
        period = str(row["_period"])
        facts, summary = load_sec_notes_listing_facts(
            root / f"{period}_notes.zip",
            pd.DataFrame([row.drop(labels="_period")]),
            allowed_ciks=cik_filter,
        )
        fact_frames.append(facts)
        summaries.append(summary)

    facts = pd.concat(fact_frames, ignore_index=True)
    fact_key = ["cik", "accession", "context_id", "concept", "iprx"]
    if not facts.empty and facts.duplicated(fact_key, keep=False).any():
        raise ValueError(
            "SEC Notes history contains overlapping or duplicate filing facts"
        )
    if not facts.empty:
        facts = facts.sort_values(
            ["cik", "accepted_at", "accession", "context_id", "concept", "iprx"]
        ).reset_index(drop=True)
    return facts, pd.DataFrame(summaries)


__all__ = [
    "load_sec_notes_listing_facts",
    "load_sec_notes_listing_history",
]
