"""Compact state transitions, not a replacement for writer authentication.

The GitHub adapter must verify anchor, latest edit and artifact producer before
using this state. Bootstrap is a maintenance operation, never a missing-state
fallback. This module performs no remote writes or automatic initialization.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..github_performance.contracts import canonical_sha256
from .catalog_request_contract import CatalogRunRequestV1, FrozenModel, Sha256


_PREFIX = "AURORA CATALOG FAST AUTHORITY V1\n"


class FastAuthorityCampaignV1(FrozenModel):
    request: CatalogRunRequestV1
    owner_issue_number: int = Field(strict=True, ge=1)
    owner_run_id: int = Field(strict=True, ge=1)
    terminal_receipt_sha256: Sha256 | None = None
    # Imported protected closure evidence is NOT a scientific terminal receipt.
    # Only the maintenance importer may supply it after verifying its sources.
    legacy_closure_evidence_sha256: Sha256 | None = None

    @property
    def is_terminal(self) -> bool:
        return self.terminal_receipt_sha256 is not None or self.legacy_closure_evidence_sha256 is not None

    @property
    def generation(self) -> int:
        return self.request.launch_generation


class _AuthorityContent(FrozenModel):
    schema_version: Literal["1"] = "1"
    document_type: Literal["catalog_fast_authority_state_v1"] = "catalog_fast_authority_state_v1"
    revision: int = Field(strict=True, ge=1)
    previous_state_sha256: Sha256 | None
    campaigns: tuple[FastAuthorityCampaignV1, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def _shape(self) -> "_AuthorityContent":
        keys = tuple(row.request.campaign_key for row in self.campaigns)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("CATALOG_FAST_AUTHORITY_CAMPAIGNS_INVALID")
        if (self.revision == 1) != (self.previous_state_sha256 is None):
            raise ValueError("CATALOG_FAST_AUTHORITY_REVISION_INVALID")
        return self


class FastAuthorityStateV1(_AuthorityContent):
    state_sha256: Sha256

    @model_validator(mode="after")
    def _hash(self) -> "FastAuthorityStateV1":
        if canonical_sha256(self.model_dump(mode="json", exclude={"state_sha256"})) != self.state_sha256:
            raise ValueError("CATALOG_FAST_AUTHORITY_HASH_INVALID")
        return self

    @classmethod
    def _create(cls, **values: object) -> "FastAuthorityStateV1":
        content = _AuthorityContent.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**content, "state_sha256": canonical_sha256(content)})

    @classmethod
    def bootstrap(cls, *, campaigns: tuple[FastAuthorityCampaignV1, ...]) -> "FastAuthorityStateV1":
        """Encode an independently authorized maintenance baseline only."""
        return cls._create(revision=1, previous_state_sha256=None, campaigns=campaigns)

    def _replace(self, row: FastAuthorityCampaignV1) -> "FastAuthorityStateV1":
        campaigns = {item.request.campaign_key: item for item in self.campaigns}
        campaigns[row.request.campaign_key] = row
        return self._create(revision=self.revision + 1, previous_state_sha256=self.state_sha256,
                            campaigns=tuple(campaigns[key] for key in sorted(campaigns)))

    def reserve(self, *, request: CatalogRunRequestV1, issue_number: int, run_id: int) -> "FastAuthorityStateV1":
        old = next((row for row in self.campaigns if row.request.campaign_key == request.campaign_key), None)
        if old is not None:
            if old.request.request_id == request.request_id:
                if old.request.intent_sha256 != request.intent_sha256:
                    raise ValueError("CATALOG_FAST_INTENT_CONFLICT")
                return self
            if not old.is_terminal:
                raise ValueError("CATALOG_CAMPAIGN_BUSY")
            if old.request.campaign_definition_sha256 != request.campaign_definition_sha256:
                raise ValueError("CATALOG_FAST_AUTHORITY_LINEAGE_CHANGE_REQUIRES_MAINTENANCE")
        if request.launch_generation != (old.generation + 1 if old else 1):
            raise ValueError("CATALOG_FAST_GENERATION_CONFLICT")
        if request.previous_terminal_request_sha256 != (old.request.request_sha256 if old else None):
            raise ValueError("CATALOG_FAST_PREDECESSOR_CONFLICT")
        return self._replace(FastAuthorityCampaignV1(request=request, owner_issue_number=issue_number, owner_run_id=run_id))

    def terminalize(self, *, request: CatalogRunRequestV1, run_id: int,
                    terminal_receipt_sha256: str) -> "FastAuthorityStateV1":
        old = next((row for row in self.campaigns if row.request.campaign_key == request.campaign_key), None)
        if old is None or old.owner_run_id != run_id or old.request.request_sha256 != request.request_sha256:
            raise ValueError("CATALOG_FAST_AUTHORITY_OWNER_MISMATCH")
        if old.terminal_receipt_sha256 is not None:
            if old.terminal_receipt_sha256 != terminal_receipt_sha256:
                raise ValueError("CATALOG_FAST_AUTHORITY_TERMINAL_CONFLICT")
            return self
        return self._replace(FastAuthorityCampaignV1.model_validate({
            **old.model_dump(mode="json"), "terminal_receipt_sha256": terminal_receipt_sha256,
        }))

    def to_body(self) -> str:
        return _PREFIX + self.model_dump_json()


class FastAuthorityEditBindingV1(FrozenModel):
    """Artifact content binding; caller still authenticates its writer."""

    schema_version: Literal["1"] = "1"
    issue_node_id: str = Field(min_length=1, max_length=256)
    edit_node_id: str = Field(min_length=1, max_length=256)
    state: FastAuthorityStateV1


def bind_authority_edit(*, state: FastAuthorityStateV1, issue_node_id: str,
                        edit_node_id: str) -> FastAuthorityEditBindingV1:
    return FastAuthorityEditBindingV1(issue_node_id=issue_node_id, edit_node_id=edit_node_id, state=state)


def verify_authority_edit(*, body: str, publication_json: str, issue_node_id: str,
                          latest_edit_node_id: str) -> FastAuthorityStateV1:
    """Bind live content to one exact edit, after upstream provenance checks."""
    if len(body.encode("utf-8")) > 256 * 1024 or len(publication_json.encode("utf-8")) > 512 * 1024:
        raise ValueError("CATALOG_FAST_AUTHORITY_SIZE_INVALID")
    publication = FastAuthorityEditBindingV1.model_validate_json(publication_json)
    if (publication.issue_node_id != issue_node_id or publication.edit_node_id != latest_edit_node_id
            or body != publication.state.to_body()):
        raise ValueError("CATALOG_FAST_AUTHORITY_EDIT_MISMATCH")
    return publication.state
