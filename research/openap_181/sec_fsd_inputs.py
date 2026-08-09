"""Bounded preparation of official SEC FSD archives for the accounting batch."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable

import pandas as pd

from .sec_accounting_batch import CONCEPT_SPECS


_QUARTER_RE = re.compile(r"^(20\d{2})q([1-4])$")
_ALLOWED_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})
_SUB_COLUMNS = ["adsh", "cik", "sic", "form", "period", "filed", "accepted"]
_TAG_COLUMNS = ["tag", "version", "custom", "abstract"]
_NUM_COLUMNS = ["adsh", "tag", "version", "coreg", "ddate", "qtrs", "uom", "value"]
_PRE_COLUMNS = ["adsh", "line", "stmt", "tag", "version"]
_MANIFEST_COLUMNS = [
    "source_id",
    "source_url",
    "period",
    "sha256",
    "size_bytes",
    "retrieved_at",
    "status",
    "failure_reason",
]
_RELEVANT_TAGS = frozenset(
    alias for spec in CONCEPT_SPECS.values() for alias in spec.aliases
)


def _quarter_index(value: str) -> int:
    match = _QUARTER_RE.fullmatch(str(value).strip().lower())
    if match is None:
        raise ValueError(f"Invalid SEC quarter: {value}")
    year, quarter = (int(part) for part in match.groups())
    return year * 4 + quarter - 1


def bounded_quarters(start_quarter: str, end_quarter: str) -> tuple[str, ...]:
    """Return a chronological SEC quarter range capped before any download."""

    start = _quarter_index(start_quarter)
    end = _quarter_index(end_quarter)
    if start > end:
        raise ValueError("SEC start quarter must not follow end quarter")
    count = end - start + 1
    if count > 16:
        raise ValueError("SEC accounting batch accepts at most 16 quarters")
    return tuple(f"{index // 4}q{index % 4 + 1}" for index in range(start, end + 1))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _member_name(archive: zipfile.ZipFile, expected: str) -> str:
    matches = [name for name in archive.namelist() if Path(name).name.lower() == expected]
    if len(matches) != 1:
        raise ValueError(f"SEC FSD archive requires exactly one {expected}")
    return matches[0]


def _read_table(
    archive: zipfile.ZipFile,
    member: str,
    columns: list[str],
) -> pd.DataFrame:
    with archive.open(member) as handle:
        return pd.read_csv(
            handle,
            sep="\t",
            usecols=columns,
            low_memory=False,
        )


def _read_reduced_num(
    archive: zipfile.ZipFile,
    member: str,
    allowed_accessions: set[str],
) -> pd.DataFrame:
    frames = []
    with archive.open(member) as handle:
        chunks = pd.read_csv(
            handle,
            sep="\t",
            usecols=_NUM_COLUMNS,
            chunksize=250_000,
            low_memory=False,
        )
        for chunk in chunks:
            reduced = chunk.loc[
                chunk["tag"].isin(_RELEVANT_TAGS)
                & chunk["adsh"].astype(str).isin(allowed_accessions)
            ]
            if not reduced.empty:
                frames.append(reduced)
    if not frames:
        return pd.DataFrame(columns=_NUM_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def _concat(frames: Iterable[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    materialized = [frame for frame in frames if not frame.empty]
    if not materialized:
        return pd.DataFrame(columns=columns)
    return pd.concat(materialized, ignore_index=True)[columns]


def _validated_manifest(
    source_manifest: pd.DataFrame,
    zip_dir: Path,
    quarters: tuple[str, ...],
) -> pd.DataFrame:
    missing = sorted(set(_MANIFEST_COLUMNS) - set(source_manifest.columns))
    if missing:
        raise ValueError(f"SEC source manifest is missing columns: {missing}")
    clean = source_manifest[_MANIFEST_COLUMNS].copy()
    clean["period"] = clean["period"].astype(str).str.strip().str.lower()
    if clean["period"].duplicated().any() or set(clean["period"]) != set(quarters):
        raise ValueError("SEC source manifest must match the bounded quarter range exactly")
    clean["status"] = clean["status"].astype(str).str.strip()
    if not clean["status"].eq("downloaded").all():
        raise ValueError("Every SEC FSD quarter must be downloaded before preparation")
    for row in clean.itertuples(index=False):
        archive = zip_dir / f"{row.period}.zip"
        if not archive.is_file():
            raise ValueError(f"Missing SEC FSD archive: {archive.name}")
        if archive.stat().st_size != int(row.size_bytes):
            raise ValueError(f"SEC FSD size mismatch: {archive.name}")
        if _sha256(archive).lower() != str(row.sha256).strip().lower():
            raise ValueError(f"SEC FSD SHA-256 mismatch: {archive.name}")
    return clean.sort_values("period", kind="stable").reset_index(drop=True)


def _sec_timestamp(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(14)
    return pd.to_datetime(text, format="%Y%m%d%H%M%S", errors="coerce")


def _identity_and_expected(
    submissions: pd.DataFrame,
    formation_months: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cohort = submissions[["cik", "accepted"]].copy()
    cohort["cik"] = pd.to_numeric(cohort["cik"], errors="coerce")
    cohort["accepted_at"] = _sec_timestamp(cohort["accepted"])
    cohort = cohort.dropna(subset=["cik", "accepted_at"])
    cohort["cik"] = cohort["cik"].astype("int64")
    first_seen = cohort.groupby("cik", as_index=False)["accepted_at"].min()
    identity_rows = []
    expected_rows = []
    for row in first_seen.itertuples(index=False):
        security_id = f"CIK-{int(row.cik):010d}"
        identity_rows.append(
            {
                "security_id": security_id,
                "cik": int(row.cik),
                "valid_from": row.accepted_at,
                "valid_to": pd.NaT,
                "is_primary": True,
                "security_type": "unknown_not_available_in_sec_fsd",
                "mapping_source": "sec_cik_internal_not_openap_identity_bridge",
            }
        )
        for month in formation_months:
            if month >= row.accepted_at + pd.offsets.MonthEnd(0):
                expected_rows.append(
                    {
                        "security_id": security_id,
                        "formation_at": month,
                        "exchange": "unknown_not_available_in_sec_fsd",
                        "security_type": "unknown_not_available_in_sec_fsd",
                    }
                )
    return pd.DataFrame(identity_rows), pd.DataFrame(expected_rows)


def prepare_sec_fsd_batch_inputs(
    zip_dir: Path | str,
    source_manifest: pd.DataFrame,
    output_dir: Path | str,
    *,
    start_quarter: str,
    end_quarter: str,
    formation_start: str,
    formation_end: str,
) -> dict[str, int]:
    """Verify and reduce bounded official archives into deterministic CSV inputs."""

    quarters = bounded_quarters(start_quarter, end_quarter)
    archives = Path(zip_dir)
    clean_manifest = _validated_manifest(source_manifest, archives, quarters)
    formation_months = pd.date_range(formation_start, formation_end, freq="ME")
    if formation_months.empty:
        raise ValueError("Formation range must contain at least one month end")
    sub_frames = []
    tag_frames = []
    num_frames = []
    pre_frames = []
    for period in clean_manifest["period"]:
        with zipfile.ZipFile(archives / f"{period}.zip") as archive:
            sub = _read_table(archive, _member_name(archive, "sub.txt"), _SUB_COLUMNS)
            sub = sub.loc[sub["form"].isin(_ALLOWED_FORMS)].copy()
            allowed_accessions = set(sub["adsh"].dropna().astype(str))
            tag = _read_table(archive, _member_name(archive, "tag.txt"), _TAG_COLUMNS)
            tag = tag.loc[tag["tag"].isin(_RELEVANT_TAGS)].copy()
            pre = _read_table(archive, _member_name(archive, "pre.txt"), _PRE_COLUMNS)
            pre = pre.loc[
                pre["tag"].isin(_RELEVANT_TAGS)
                & pre["adsh"].astype(str).isin(allowed_accessions)
            ].copy()
            num = _read_reduced_num(
                archive,
                _member_name(archive, "num.txt"),
                allowed_accessions,
            )
            sub_frames.append(sub)
            tag_frames.append(tag)
            pre_frames.append(pre)
            num_frames.append(num)
    sub = _concat(sub_frames, _SUB_COLUMNS).drop_duplicates("adsh", keep="last")
    tag = _concat(tag_frames, _TAG_COLUMNS).drop_duplicates(["tag", "version"])
    pre = _concat(pre_frames, _PRE_COLUMNS).drop_duplicates(
        ["adsh", "tag", "version", "line"]
    )
    num = _concat(num_frames, _NUM_COLUMNS).drop_duplicates()
    identity, expected = _identity_and_expected(sub, formation_months)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    sub.to_csv(output / "sub.csv", index=False)
    tag.to_csv(output / "tag.csv", index=False)
    num.to_csv(output / "num.csv", index=False)
    pre.to_csv(output / "pre.csv", index=False)
    identity.to_csv(output / "identity.csv", index=False)
    pd.DataFrame({"formation_at": formation_months}).to_csv(
        output / "formation_months.csv",
        index=False,
    )
    expected.to_csv(output / "expected_universe.csv", index=False)
    clean_manifest.to_csv(output / "source_manifest.csv", index=False)
    summary = {
        "expected_rows": int(len(expected)),
        "formation_months": int(len(formation_months)),
        "identity_rows": int(len(identity)),
        "num_rows": int(len(num)),
        "pre_rows": int(len(pre)),
        "quarters": len(quarters),
        "sub_rows": int(len(sub)),
        "tag_rows": int(len(tag)),
    }
    (output / "preparation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


__all__ = ["bounded_quarters", "prepare_sec_fsd_batch_inputs"]
