"""Fail-closed recovery audit for public historical PERMNO bridge sources."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import yaml

from aurora.research.openap_149.identity_gate import BRIDGE_COLUMNS


class IdentityRecoveryError(ValueError):
    """Raised when recovery evidence violates the frozen v2 contract."""


@dataclass(frozen=True)
class RecoverySource:
    source_id: str
    evidence_url: str
    retrieval_url: str
    checked_at: str
    probe_policy: str
    expected_media_type: str
    parser: str
    public_access_without_login: bool
    public_zero_cost: bool
    authorized_for_internal_research: bool
    upstream_license_required: bool
    provides_permno: bool
    provides_public_security_id: bool
    historical_intervals: bool
    share_class_specific: bool
    covers_2023_2024: bool
    broad_universe: bool
    target_derived: bool
    upstream_provenance: str
    universe_limit: str
    documentary_blocker: str


@dataclass(frozen=True)
class ProbeReceipt:
    source_id: str
    attempted: bool
    status_code: int | None
    final_url: str
    content_type: str
    bytes_observed: int
    sha256: str
    observed_columns: tuple[str, ...]
    retrieved_at: str
    error: str


_BOOL_FIELDS = (
    "public_access_without_login",
    "public_zero_cost",
    "authorized_for_internal_research",
    "upstream_license_required",
    "provides_permno",
    "provides_public_security_id",
    "historical_intervals",
    "share_class_specific",
    "covers_2023_2024",
    "broad_universe",
    "target_derived",
)
_TEXT_FIELDS = (
    "source_id",
    "evidence_url",
    "retrieval_url",
    "probe_policy",
    "expected_media_type",
    "parser",
    "upstream_provenance",
    "universe_limit",
    "documentary_blocker",
)
_ROW_FIELDS = frozenset((*_BOOL_FIELDS, *_TEXT_FIELDS))
_PROBE_POLICIES = frozenset({"documentary_only", "bounded_get", "download_small"})
_MEDIA_TYPES = frozenset({"csv", "html", "json", "parquet", "pdf", "text", "xlsx"})
_PARSERS = frozenset(
    {"canonical_bridge_csv", "csv_header", "document", "json_keys", "parquet_schema"}
)
_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_LOGIN_PAYMENT_TERMS = (
    "/login",
    "/signin",
    "/sign-in",
    "/subscribe",
    "/checkout",
    "/payment",
)
_BOUNDED_LIMIT = 1024 * 1024
_SMALL_LIMIT = 256 * 1024
_USER_AGENT = "Aurora-OpenAP-Identity-Audit/2.0 research-contact=repository-owner"


def _strict_text(row: Mapping[str, object], field: str, source_id: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise IdentityRecoveryError(f"{source_id}: {field} must be non-blank text")
    return value.strip()


def _strict_bool(row: Mapping[str, object], field: str, source_id: str) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise IdentityRecoveryError(f"{source_id}: {field} must be an explicit boolean")
    return value


def _validate_https(value: str, *, field: str, source_id: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise IdentityRecoveryError(f"{source_id}: {field} must be an absolute HTTPS URL")


def load_recovery_catalog(path: Path) -> list[RecoverySource]:
    """Load the frozen v2 source catalogue without truthy coercions."""

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise IdentityRecoveryError("Recovery catalogue must be a mapping")
    if payload.get("dataset_id") != "openap_149_identity_sources_v2":
        raise IdentityRecoveryError("Unexpected recovery catalogue dataset_id")
    checked_at = payload.get("checked_at")
    if not isinstance(checked_at, str):
        raise IdentityRecoveryError("checked_at must be an ISO date string")
    try:
        date.fromisoformat(checked_at)
    except ValueError as exc:
        raise IdentityRecoveryError("checked_at must be a valid ISO date") from exc
    rows = payload.get("sources")
    if not isinstance(rows, list) or not rows:
        raise IdentityRecoveryError("Recovery catalogue must contain source rows")

    result: list[RecoverySource] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise IdentityRecoveryError("Every recovery source must be a mapping")
        source_id = _strict_text(raw, "source_id", "<unknown>")
        if not _SOURCE_ID_RE.fullmatch(source_id):
            raise IdentityRecoveryError(f"{source_id}: invalid source_id")
        if source_id in seen:
            raise IdentityRecoveryError(f"duplicate recovery source_id: {source_id}")
        seen.add(source_id)
        missing = sorted(_ROW_FIELDS.difference(raw))
        unknown = sorted(set(raw).difference(_ROW_FIELDS))
        if missing:
            raise IdentityRecoveryError(f"{source_id}: missing fields {missing}")
        if unknown:
            raise IdentityRecoveryError(f"{source_id}: unknown fields {unknown}")

        text_values = {
            field: _strict_text(raw, field, source_id) for field in _TEXT_FIELDS
        }
        bool_values = {
            field: _strict_bool(raw, field, source_id) for field in _BOOL_FIELDS
        }
        _validate_https(
            text_values["evidence_url"], field="evidence_url", source_id=source_id
        )
        _validate_https(
            text_values["retrieval_url"], field="retrieval_url", source_id=source_id
        )
        if text_values["probe_policy"] not in _PROBE_POLICIES:
            raise IdentityRecoveryError(
                f"{source_id}: unsupported probe_policy {text_values['probe_policy']!r}"
            )
        if text_values["expected_media_type"] not in _MEDIA_TYPES:
            raise IdentityRecoveryError(
                f"{source_id}: unsupported expected_media_type"
            )
        if text_values["parser"] not in _PARSERS:
            raise IdentityRecoveryError(
                f"{source_id}: unsupported parser {text_values['parser']!r}"
            )
        result.append(
            RecoverySource(checked_at=checked_at, **text_values, **bool_values)
        )
    return result


def classify_source(
    source: RecoverySource, receipt: ProbeReceipt | None
) -> str:
    """Return exactly one terminal class using the frozen priority order."""

    if source.target_derived:
        return "blocked_target_derived"
    if not source.public_zero_cost or not source.public_access_without_login:
        return "blocked_access"
    if (
        not source.authorized_for_internal_research
        or source.upstream_license_required
    ):
        return "blocked_rights"
    if not source.provides_permno or not source.provides_public_security_id:
        return "blocked_schema"
    if not source.historical_intervals or not source.share_class_specific:
        return "blocked_semantics"
    if not source.covers_2023_2024 or not source.broad_universe:
        return "blocked_coverage_claim"
    if receipt is None or not receipt.attempted or receipt.error:
        return "probe_error"
    if source.parser == "canonical_bridge_csv" and not set(BRIDGE_COLUMNS).issubset(
        receipt.observed_columns
    ):
        return "blocked_schema"
    return "pass_candidate"


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _redirect_is_blocked(value: str) -> bool:
    parsed = urlsplit(value)
    searchable = f"{parsed.netloc}{parsed.path}".lower()
    return any(term in searchable for term in _LOGIN_PAYMENT_TERMS)


def _media_type_matches(expected: str, content_type: str) -> bool:
    content_type = content_type.lower()
    accepted = {
        "csv": ("text/csv", "application/csv", "application/octet-stream"),
        "html": ("text/html", "application/xhtml+xml"),
        "json": ("application/json", "text/json", "text/plain"),
        "parquet": ("application/vnd.apache.parquet", "application/octet-stream"),
        "pdf": ("application/pdf", "application/octet-stream"),
        "text": ("text/plain", "text/markdown", "application/octet-stream"),
        "xlsx": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        ),
    }
    return any(token in content_type for token in accepted[expected])


def _observed_columns(source: RecoverySource, payload: bytes) -> tuple[str, ...]:
    if not payload:
        return ()
    try:
        if source.parser in {"csv_header", "canonical_bridge_csv"}:
            text = payload.decode("utf-8-sig", errors="strict")
            return tuple(next(csv.reader(StringIO(text))))
        if source.parser == "json_keys":
            parsed = json.loads(payload.decode("utf-8-sig"))
            if isinstance(parsed, dict):
                return tuple(sorted(str(key) for key in parsed))
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return tuple(sorted(str(key) for key in parsed[0]))
        if source.parser == "parquet_schema":
            frame = pd.read_parquet(BytesIO(payload))
            return tuple(str(column) for column in frame.columns)
    except (csv.Error, UnicodeDecodeError, json.JSONDecodeError, StopIteration, ValueError):
        return ()
    return ()


def _probe_source_payload(
    source: RecoverySource,
    *,
    getter: Callable[..., Any] | None,
    now: Callable[[], datetime],
) -> tuple[ProbeReceipt, bytes]:
    retrieved_at = _utc_text(now())
    if source.probe_policy == "documentary_only":
        return (
            ProbeReceipt(
                source_id=source.source_id,
                attempted=False,
                status_code=None,
                final_url=_safe_url(source.evidence_url),
                content_type="",
                bytes_observed=0,
                sha256="",
                observed_columns=(),
                retrieved_at=retrieved_at,
                error="documentary_only",
            ),
            b"",
        )

    if getter is None:
        import requests

        getter = requests.get
    try:
        response = getter(
            source.retrieval_url,
            headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
            timeout=(15, 45),
            allow_redirects=True,
            stream=True,
        )
    except Exception as exc:  # Network failures are evidence, not crashes.
        return (
            ProbeReceipt(
                source_id=source.source_id,
                attempted=True,
                status_code=None,
                final_url=_safe_url(source.retrieval_url),
                content_type="",
                bytes_observed=0,
                sha256="",
                observed_columns=(),
                retrieved_at=retrieved_at,
                error=f"request_error:{type(exc).__name__}",
            ),
            b"",
        )

    final_url = _safe_url(str(getattr(response, "url", source.retrieval_url)))
    status_code = int(getattr(response, "status_code", 0))
    headers = getattr(response, "headers", {})
    content_type = str(headers.get("content-type", headers.get("Content-Type", "")))
    error = ""
    if _redirect_is_blocked(final_url):
        error = "redirected_to_login_or_payment"
    elif status_code < 200 or status_code >= 300:
        error = f"http_status_{status_code}"

    limit = _SMALL_LIMIT if source.probe_policy == "download_small" else _BOUNDED_LIMIT
    observed = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            remaining = limit - len(observed)
            if remaining <= 0:
                break
            observed.extend(chunk[:remaining])
            if len(observed) >= limit:
                break
    except Exception as exc:
        error = error or f"stream_error:{type(exc).__name__}"
    payload = bytes(observed)
    if not error and not _media_type_matches(source.expected_media_type, content_type):
        error = "content_type_mismatch"
    columns = _observed_columns(source, payload)
    receipt = ProbeReceipt(
        source_id=source.source_id,
        attempted=True,
        status_code=status_code,
        final_url=final_url,
        content_type=content_type.split(";", 1)[0].strip().lower(),
        bytes_observed=len(payload),
        sha256=hashlib.sha256(payload).hexdigest() if payload else "",
        observed_columns=columns,
        retrieved_at=retrieved_at,
        error=error,
    )
    return receipt, payload


def probe_source(
    source: RecoverySource,
    *,
    getter: Callable[..., Any] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> ProbeReceipt:
    """Run one bounded source probe and return its sanitised receipt."""

    receipt, _ = _probe_source_payload(source, getter=getter, now=now)
    return receipt


def _failed_dimensions(source: RecoverySource) -> str:
    failures: list[str] = []
    positive = {
        "public_access_without_login": source.public_access_without_login,
        "public_zero_cost": source.public_zero_cost,
        "authorized_for_internal_research": source.authorized_for_internal_research,
        "provides_permno": source.provides_permno,
        "provides_public_security_id": source.provides_public_security_id,
        "historical_intervals": source.historical_intervals,
        "share_class_specific": source.share_class_specific,
        "covers_2023_2024": source.covers_2023_2024,
        "broad_universe": source.broad_universe,
    }
    failures.extend(key for key, value in positive.items() if not value)
    if source.upstream_license_required:
        failures.append("upstream_license_required")
    if source.target_derived:
        failures.append("target_derived")
    return "|".join(failures)


def audit_sources(
    sources: Sequence[RecoverySource],
    *,
    getter: Callable[..., Any] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[pd.DataFrame, list[ProbeReceipt], dict[str, bytes]]:
    """Probe, classify and reconcile all routes without reading target values."""

    rows: list[dict[str, object]] = []
    receipts: list[ProbeReceipt] = []
    payloads: dict[str, bytes] = {}
    for source in sources:
        receipt, payload = _probe_source_payload(source, getter=getter, now=now)
        receipts.append(receipt)
        if payload:
            payloads[source.source_id] = payload
        row = asdict(source)
        row.update(
            {
                "terminal_class": classify_source(source, receipt),
                "failed_dimensions": _failed_dimensions(source),
                "probe_attempted": receipt.attempted,
                "probe_status_code": receipt.status_code,
                "probe_final_url": receipt.final_url,
                "probe_content_type": receipt.content_type,
                "probe_bytes_observed": receipt.bytes_observed,
                "probe_sha256": receipt.sha256,
                "probe_observed_columns": "|".join(receipt.observed_columns),
                "probe_retrieved_at": receipt.retrieved_at,
                "probe_error": receipt.error,
            }
        )
        rows.append(row)
    audit = pd.DataFrame(rows).sort_values("source_id").reset_index(drop=True)
    if len(audit) != len(sources) or audit["source_id"].duplicated().any():
        raise IdentityRecoveryError("Source audit does not reconcile to catalogue")
    return audit, receipts, payloads


def build_candidate_bridge(
    audit: pd.DataFrame, payloads: Mapping[str, bytes]
) -> pd.DataFrame:
    """Build rows only from preflight-passing canonical bridge CSV routes."""

    required = {"source_id", "terminal_class", "parser"}
    if audit.empty:
        return pd.DataFrame(columns=BRIDGE_COLUMNS)
    missing_audit = required.difference(audit.columns)
    if missing_audit:
        if not audit["terminal_class"].eq("pass_candidate").any():
            return pd.DataFrame(columns=BRIDGE_COLUMNS)
        raise IdentityRecoveryError(
            f"Passing source audit is missing columns: {sorted(missing_audit)}"
        )
    frames: list[pd.DataFrame] = []
    passing = audit.loc[audit["terminal_class"].eq("pass_candidate")]
    for row in passing.to_dict(orient="records"):
        source_id = str(row["source_id"])
        if row["parser"] != "canonical_bridge_csv":
            raise IdentityRecoveryError(
                f"{source_id}: passing route lacks canonical bridge parser"
            )
        payload = payloads.get(source_id)
        if not payload:
            raise IdentityRecoveryError(f"{source_id}: passing route has no payload")
        frame = pd.read_csv(BytesIO(payload), low_memory=False)
        missing = [column for column in BRIDGE_COLUMNS if column not in frame]
        if missing:
            raise IdentityRecoveryError(
                f"{source_id}: canonical bridge payload is missing {missing}"
            )
        frames.append(frame[BRIDGE_COLUMNS].copy())
    if not frames:
        return pd.DataFrame(columns=BRIDGE_COLUMNS)
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates()
        .sort_values(["canonical_security_id", "valid_from", "permno"])
        .reset_index(drop=True)
    )


__all__ = [
    "BRIDGE_COLUMNS",
    "IdentityRecoveryError",
    "ProbeReceipt",
    "RecoverySource",
    "audit_sources",
    "build_candidate_bridge",
    "classify_source",
    "load_recovery_catalog",
    "probe_source",
]
