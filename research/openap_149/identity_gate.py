"""Historical, non-circular security-to-PERMNO identity gate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


class IdentityGateError(ValueError):
    """Raised when a bridge cannot support strict stock-level validation."""


REQUIRED_BRIDGE_COLUMNS = {
    "canonical_security_id",
    "permno",
    "valid_from",
    "valid_to",
    "share_class_id",
    "evidence_url",
    "evidence_kind",
    "source_id",
    "source_retrieved_at",
    "source_sha256",
    "zero_cost_authorized",
}

ALLOWED_EVIDENCE_KINDS = {
    "direct_identifier_history",
    "issuer_filing",
    "exchange_record",
    "independently_licensed_identifier_link",
}

BRIDGE_COLUMNS = tuple(sorted(REQUIRED_BRIDGE_COLUMNS))
REQUIRED_MONTHS = tuple(
    period.strftime("%Y%m")
    for period in pd.period_range("2023-01", "2024-12", freq="M")
)


@dataclass(frozen=True)
class BridgeManifest:
    rows: int
    min_valid_from: str
    max_valid_to: str
    bridge_sha256: str
    frozen_before_reference_read: bool


@dataclass(frozen=True)
class IdentityGateDecision:
    status: str
    minimum_monthly_coverage: float
    median_monthly_coverage: float
    maximum_monthly_coverage: float
    required_months: int
    retained_pairs: int
    reference_pairs: int
    ambiguous_links: int
    monthly_coverage: tuple[tuple[str, float, int, int], ...]


def _strict_true(series: pd.Series) -> bool:
    return bool(
        len(series)
        and pd.api.types.is_bool_dtype(series.dtype)
        and series.notna().all()
        and series.all()
    )


def _validate_non_overlapping(frame: pd.DataFrame, key: str) -> None:
    for identity, group in frame.groupby(key, sort=False):
        ordered = group.sort_values(["valid_from", "valid_to"])
        previous_end: pd.Timestamp | None = None
        for row in ordered.itertuples(index=False):
            if previous_end is not None and row.valid_from <= previous_end:
                raise IdentityGateError(
                    f"identity interval overlap for {key}={identity}"
                )
            previous_end = row.valid_to


def validate_bridge(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize a direct-evidence bridge and reject ambiguity or circularity."""

    missing = REQUIRED_BRIDGE_COLUMNS - set(frame.columns)
    if missing:
        raise IdentityGateError(f"Missing bridge columns: {sorted(missing)}")
    if frame.empty:
        raise IdentityGateError("Identity bridge is empty")

    result = frame.loc[:, BRIDGE_COLUMNS].copy()
    for column in (
        "canonical_security_id",
        "share_class_id",
        "evidence_url",
        "evidence_kind",
        "source_id",
        "source_sha256",
    ):
        result[column] = result[column].fillna("").astype(str).str.strip()
        if result[column].eq("").any():
            raise IdentityGateError(f"Bridge has empty {column}")

    permno = pd.to_numeric(result["permno"], errors="coerce")
    if permno.isna().any() or (permno <= 0).any() or (permno % 1 != 0).any():
        raise IdentityGateError("PERMNO must be a positive integer")
    result["permno"] = permno.astype("int64")

    for column in ("valid_from", "valid_to", "source_retrieved_at"):
        result[column] = pd.to_datetime(result[column], errors="coerce", utc=True)
        if result[column].isna().any():
            raise IdentityGateError(f"Bridge has invalid {column}")
    if (result["valid_to"] < result["valid_from"]).any():
        raise IdentityGateError("valid_to precedes valid_from")

    if not _strict_true(result["zero_cost_authorized"]):
        raise IdentityGateError("Every bridge row must be authorized zero-cost evidence")
    result["zero_cost_authorized"] = True

    invalid_urls = result["evidence_url"].map(
        lambda value: (
            urlparse(value).scheme != "https" or not urlparse(value).netloc
        )
    )
    if invalid_urls.any():
        raise IdentityGateError("Every evidence_url must be an absolute HTTPS URL")

    target_derived = ~result["evidence_kind"].isin(ALLOWED_EVIDENCE_KINDS)
    if target_derived.any():
        raise IdentityGateError("Bridge contains target-derived or unsupported evidence")
    if not result["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all():
        raise IdentityGateError("Bridge contains an invalid SHA-256")

    _validate_non_overlapping(result, "canonical_security_id")
    _validate_non_overlapping(result, "permno")
    return result.sort_values(
        ["canonical_security_id", "valid_from", "valid_to", "permno"]
    ).reset_index(drop=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_bridge(frame: pd.DataFrame, output: Path) -> BridgeManifest:
    """Write the canonical bridge before any official reference is read."""

    normalized = validate_bridge(frame)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_parquet(destination, engine="pyarrow", index=False, compression="zstd")
    return BridgeManifest(
        rows=int(len(normalized)),
        min_valid_from=normalized["valid_from"].min().isoformat(),
        max_valid_to=normalized["valid_to"].max().isoformat(),
        bridge_sha256=_sha256(destination),
        frozen_before_reference_read=True,
    )


def _canonical_reference_spine(frame: pd.DataFrame) -> pd.DataFrame:
    missing = {"permno", "yyyymm"} - set(frame.columns)
    if missing:
        raise IdentityGateError(f"Reference spine missing columns: {sorted(missing)}")
    result = frame.loc[:, ["permno", "yyyymm"]].copy()
    result["permno"] = pd.to_numeric(result["permno"], errors="coerce")
    result["yyyymm"] = result["yyyymm"].astype(str).str.replace(r"\.0$", "", regex=True)
    if result["permno"].isna().any() or not result["yyyymm"].str.fullmatch(r"\d{6}").all():
        raise IdentityGateError("Reference spine contains invalid PERMNO or yyyymm")
    result["permno"] = result["permno"].astype("int64")
    result = result.drop_duplicates().reset_index(drop=True)
    observed = set(result["yyyymm"])
    missing_months = sorted(set(REQUIRED_MONTHS) - observed)
    if missing_months:
        raise IdentityGateError(f"Reference spine missing required months: {missing_months}")
    return result.loc[result["yyyymm"].isin(REQUIRED_MONTHS)].copy()


def evaluate_bridge_coverage(
    bridge: pd.DataFrame,
    reference_spine: pd.DataFrame,
    *,
    manifest: BridgeManifest,
    minimum_required: float = 0.70,
) -> IdentityGateDecision:
    """Evaluate identifier-only monthly coverage after the bridge freeze."""

    if not manifest.frozen_before_reference_read:
        raise IdentityGateError("Identity bridge was not frozen before reference read")
    normalized = validate_bridge(bridge)
    if manifest.rows != len(normalized):
        raise IdentityGateError("Frozen bridge manifest row count does not match")
    reference = _canonical_reference_spine(reference_spine)

    monthly: list[tuple[str, float, int, int]] = []
    retained_pairs = 0
    reference_pairs = 0
    for month in REQUIRED_MONTHS:
        period = pd.Period(month, freq="M")
        month_start = period.start_time.tz_localize("UTC")
        month_end = period.end_time.tz_localize("UTC")
        active = normalized.loc[
            normalized["valid_from"].le(month_end)
            & normalized["valid_to"].ge(month_start),
            "permno",
        ]
        official = set(reference.loc[reference["yyyymm"].eq(month), "permno"])
        covered = len(official & set(active))
        total = len(official)
        if total == 0:
            raise IdentityGateError(f"Reference spine has no securities for {month}")
        coverage = covered / total
        retained_pairs += covered
        reference_pairs += total
        monthly.append((month, float(coverage), covered, total))

    coverages = pd.Series([row[1] for row in monthly], dtype=float)
    minimum = float(coverages.min())
    status = "pass" if minimum >= minimum_required else "blocked_identity"
    return IdentityGateDecision(
        status=status,
        minimum_monthly_coverage=minimum,
        median_monthly_coverage=float(coverages.median()),
        maximum_monthly_coverage=float(coverages.max()),
        required_months=len(REQUIRED_MONTHS),
        retained_pairs=retained_pairs,
        reference_pairs=reference_pairs,
        ambiguous_links=0,
        monthly_coverage=tuple(monthly),
    )


__all__ = [
    "BridgeManifest",
    "IdentityGateDecision",
    "IdentityGateError",
    "REQUIRED_BRIDGE_COLUMNS",
    "evaluate_bridge_coverage",
    "freeze_bridge",
    "validate_bridge",
]
