"""Canonical mirror-first incidents for immutable catalog comment tampering."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from .catalog_request_contract import FrozenModel, Sha256, canonical_model_bytes


AUTHORITY_TAMPER_MARKER = "AURORA_CATALOG_LEDGER_TAMPER_V1"
REQUEST_TAMPER_MARKER = "AURORA_CATALOG_REQUEST_COMMENT_TAMPER_V1"


class CatalogCommentTamperIncidentV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    marker: Literal[
        "AURORA_CATALOG_LEDGER_TAMPER_V1",
        "AURORA_CATALOG_REQUEST_COMMENT_TAMPER_V1",
    ]
    relevant: Literal[True]
    target_kind: Literal["authority", "request_receipt"]
    issue_number: int = Field(ge=1)
    original_comment_id: int = Field(ge=1)
    event_action: Literal["edited", "deleted"]
    actor: str = Field(min_length=1, max_length=100)
    writer_run_id: int = Field(ge=1)
    writer_run_attempt: int = Field(ge=1)
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    event_sha256: Sha256
    original_body_sha256: Sha256
    observed_body_sha256: Sha256
    artifact_name: str = Field(
        pattern=r"^catalog-comment-tamper-[1-9][0-9]*-[1-9][0-9]*$"
    )
    incident_sha256: Sha256

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogCommentTamperIncidentV1":
        expected_marker = (
            AUTHORITY_TAMPER_MARKER
            if self.target_kind == "authority"
            else REQUEST_TAMPER_MARKER
        )
        if (
            self.marker != expected_marker
            or self.artifact_name
            != f"catalog-comment-tamper-{self.writer_run_id}-{self.writer_run_attempt}"
        ):
            raise ValueError("CATALOG_COMMENT_TAMPER_SHAPE_INVALID")
        identity = self.model_dump(mode="json", exclude={"incident_sha256"})
        digest = hashlib.sha256(
            json.dumps(
                identity,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if digest != self.incident_sha256:
            raise ValueError("CATALOG_COMMENT_TAMPER_HASH_INVALID")
        return self


def parse_catalog_comment_tamper_incident(
    comment: Mapping[str, object],
    *,
    expected_issue_number: int,
    expected_marker: str | None = None,
) -> CatalogCommentTamperIncidentV1 | None:
    """Parse one exact immutable bot incident; ignore untrusted marker text."""

    body = comment.get("body")
    if not isinstance(body, str) or (
        AUTHORITY_TAMPER_MARKER not in body and REQUEST_TAMPER_MARKER not in body
    ):
        return None
    user = comment.get("user")
    author = user.get("login") if isinstance(user, Mapping) else None
    if author != "github-actions[bot]":
        return None
    if comment.get("created_at") != comment.get("updated_at"):
        raise ValueError("CATALOG_COMMENT_TAMPER_COMMENT_INVALID")
    markers = [
        marker
        for marker in (AUTHORITY_TAMPER_MARKER, REQUEST_TAMPER_MARKER)
        if f"<!-- {marker} -->" in body
    ]
    if len(markers) != 1:
        raise ValueError("CATALOG_COMMENT_TAMPER_COMMENT_INVALID")
    marker = markers[0]
    prefix = f"<!-- {marker} -->\n```json\n"
    suffix = "\n```\n"
    if not body.startswith(prefix) or not body.endswith(suffix):
        raise ValueError("CATALOG_COMMENT_TAMPER_COMMENT_INVALID")
    encoded = body[len(prefix) : -len(suffix)]
    try:
        payload = json.loads(encoded)
        incident = CatalogCommentTamperIncidentV1.model_validate(payload)
    except Exception:
        raise ValueError("CATALOG_COMMENT_TAMPER_COMMENT_INVALID") from None
    if (
        incident.issue_number != expected_issue_number
        or (expected_marker is not None and incident.marker != expected_marker)
        or canonical_model_bytes(incident) != encoded.encode("utf-8")
    ):
        raise ValueError("CATALOG_COMMENT_TAMPER_COMMENT_INVALID")
    return incident


__all__ = [
    "AUTHORITY_TAMPER_MARKER",
    "REQUEST_TAMPER_MARKER",
    "CatalogCommentTamperIncidentV1",
    "parse_catalog_comment_tamper_incident",
]
