"""Compact state transitions, not a replacement for writer authentication.

The GitHub adapter must verify anchor, latest edit and artifact producer before
using this state. Bootstrap is a maintenance operation, never a missing-state
fallback. This module performs no remote writes or automatic initialization.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_serializer, model_validator

from ..github_performance.contracts import canonical_sha256
from .catalog_request_contract import CatalogRunRequestV1, FrozenModel, Sha256
from .catalog_cloud_emission import CatalogCloudEmissionV1, CatalogCloudCompletedIntentV1
from .catalog_lineage_transition import CatalogLineageTransitionV1, load_lineage_transition as load_lineage_transition


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
    emissions: tuple[CatalogCloudEmissionV1, ...] = Field(default=(), max_length=128)
    completed_intents: tuple[CatalogCloudCompletedIntentV1, ...] = Field(default=(), max_length=128)

    @model_serializer(mode="wrap")
    def _legacy_wire_shape(self, handler):
        payload = handler(self)
        if not self.emissions:
            payload.pop("emissions", None)
        if not self.completed_intents:
            payload.pop("completed_intents", None)
        return payload

    @model_validator(mode="after")
    def _shape(self) -> "_AuthorityContent":
        keys = tuple(row.request.campaign_key for row in self.campaigns)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("CATALOG_FAST_AUTHORITY_CAMPAIGNS_INVALID")
        emission_keys = tuple(row.request.campaign_key for row in self.emissions)
        intent_ids = tuple(row.intent_id for row in self.emissions)
        if emission_keys != tuple(sorted(set(emission_keys))) or len(intent_ids) != len(set(intent_ids)):
            raise ValueError("CATALOG_CLOUD_EMISSIONS_INVALID")
        archived_ids = tuple(row.intent_id for row in self.completed_intents)
        if archived_ids != tuple(sorted(set(archived_ids))) or set(archived_ids) & set(intent_ids):
            raise ValueError("CATALOG_CLOUD_EMISSIONS_INVALID")
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
                            campaigns=tuple(campaigns[key] for key in sorted(campaigns)), emissions=self.emissions,
                            completed_intents=self.completed_intents)

    def stage_emission(self, emission: CatalogCloudEmissionV1, *,
                       lineage_transition: CatalogLineageTransitionV1 | None = None) -> "FastAuthorityStateV1":
        """Persist one signed request before posting; caller verifies its signature.

        Completed intent bindings remain in this same authenticated state; full
        signed bytes remain in the verified scientific issue and its artifacts.
        """
        if emission.state != "SIGNED":
            raise ValueError("CATALOG_CLOUD_EMISSION_TRANSITION_INVALID")
        archived = next((row for row in self.completed_intents if row.intent_id == emission.intent_id), None)
        if archived is not None:
            raise ValueError("CATALOG_CLOUD_INTENT_ALREADY_COMPLETED")
        matching = next((row for row in self.emissions if row.intent_id == emission.intent_id), None)
        if matching is not None:
            mutable = {"state", "issue_number", "post_run_id", "post_run_attempt"}
            if matching.model_dump(exclude=mutable) != emission.model_dump(exclude=mutable):
                raise ValueError("CATALOG_CLOUD_INTENT_CONFLICT")
            return self
        prior = next((row for row in self.emissions if row.request.campaign_key == emission.request.campaign_key), None)
        owner = next((row for row in self.campaigns if row.request.campaign_key == emission.request.campaign_key), None)
        if prior is not None and (owner is None or not owner.is_terminal
                                  or owner.request.request_sha256 != prior.request.request_sha256):
            raise ValueError("CATALOG_CAMPAIGN_BUSY")
        if owner is not None and owner.request.request_id == emission.request.request_id:
            raise ValueError("CATALOG_CLOUD_INTENT_CONFLICT")
        completed = {row.intent_id: row for row in self.completed_intents}
        if prior is not None:
            if owner is None or owner.terminal_receipt_sha256 is None:
                raise ValueError("CATALOG_CLOUD_TERMINAL_REQUIRED")
            if len(completed) >= 128:
                raise ValueError("CATALOG_CLOUD_HISTORY_CAPACITY_EXCEEDED")
            completed[prior.intent_id] = CatalogCloudCompletedIntentV1.from_emission(prior, owner.terminal_receipt_sha256)
        # Reuse the scientific generation/lineage transition solely for validation.
        # Its returned reservation is discarded: transport is never a run owner.
        without_emissions = self._create(
            revision=self.revision, previous_state_sha256=self.previous_state_sha256,
            campaigns=self.campaigns,
        )
        without_emissions.reserve(request=emission.request, issue_number=emission.intent_issue_number,
                                  run_id=emission.producer_run_id, lineage_transition=lineage_transition)
        rows = {row.request.campaign_key: row for row in self.emissions}
        rows[emission.request.campaign_key] = emission
        return self._create(revision=self.revision + 1, previous_state_sha256=self.state_sha256,
                            campaigns=self.campaigns, emissions=tuple(rows[key] for key in sorted(rows)),
                            completed_intents=tuple(completed[key] for key in sorted(completed)))

    def advance_emission(self, *, intent_id: str, state: str,
                         issue_number: int | None = None, post_run_id: int | None = None,
                         post_run_attempt: int | None = None) -> "FastAuthorityStateV1":
        item = next((row for row in self.emissions if row.intent_id == intent_id), None)
        if item is None:
            raise ValueError("CATALOG_CLOUD_EMISSION_UNKNOWN")
        updated = item.advance(state, issue_number, post_run_id=post_run_id, post_run_attempt=post_run_attempt)
        if updated == item:
            return self
        return self._create(revision=self.revision + 1, previous_state_sha256=self.state_sha256,
                            campaigns=self.campaigns,
                            emissions=tuple(updated if row.intent_id == intent_id else row for row in self.emissions),
                            completed_intents=self.completed_intents)

    def reserve(self, *, request: CatalogRunRequestV1, issue_number: int, run_id: int,
                lineage_transition: CatalogLineageTransitionV1 | None = None) -> "FastAuthorityStateV1":
        emission = next((row for row in self.emissions if row.request.campaign_key == request.campaign_key), None)
        if emission is not None and request.launch_generation >= emission.request.launch_generation:
            if request != emission.request or emission.state not in {"PUBLICACION_INCIERTA", "PUBLICADO"}:
                raise ValueError("CATALOG_CLOUD_EMISSION_REQUEST_MISMATCH")
            if emission.issue_number is not None and emission.issue_number != issue_number:
                raise ValueError("CATALOG_CLOUD_EMISSION_REQUEST_MISMATCH")
        old = next((row for row in self.campaigns if row.request.campaign_key == request.campaign_key), None)
        if old is not None:
            if old.request.request_id == request.request_id:
                if old.request.intent_sha256 != request.intent_sha256:
                    raise ValueError("CATALOG_FAST_INTENT_CONFLICT")
                return self
            if not old.is_terminal:
                raise ValueError("CATALOG_CAMPAIGN_BUSY")
            if (old.request.campaign_definition_sha256, old.request.prompt_sha256) != (
                request.campaign_definition_sha256, request.prompt_sha256
            ):
                if lineage_transition is None or not lineage_transition.authorizes(old.request, request):
                    raise ValueError("CATALOG_FAST_AUTHORITY_LINEAGE_CHANGE_REQUIRES_MAINTENANCE")
        if request.launch_generation != (old.generation + 1 if old else 1):
            raise ValueError("CATALOG_FAST_GENERATION_CONFLICT")
        if request.previous_terminal_request_sha256 != (old.request.request_sha256 if old else None):
            raise ValueError("CATALOG_FAST_PREDECESSOR_CONFLICT")
        return self._replace(FastAuthorityCampaignV1(request=request, owner_issue_number=issue_number, owner_run_id=run_id))

    def reconcile_legacy_closure(
        self, *, request: CatalogRunRequestV1, issue_number: int, historical_run_id: int,
        legacy_closure_evidence_sha256: str,
    ) -> "FastAuthorityStateV1":
        """Add one independently verified historical closure to the high-water state.

        This transition is deliberately separate from ``bootstrap`` and
        ``reserve``.  It can only import a first-generation request that has no
        predecessor and carries operational closure evidence, never a
        scientific terminal receipt.  Repeating the exact candidate is a
        no-op; any disagreement is a fail-closed conflict.
        """
        if (
            type(issue_number) is not int or issue_number < 1
            or type(historical_run_id) is not int or historical_run_id < 1
            or not isinstance(legacy_closure_evidence_sha256, str)
            or len(legacy_closure_evidence_sha256) != 64
            or any(character not in "0123456789abcdef" for character in legacy_closure_evidence_sha256)
        ):
            raise ValueError("CATALOG_FAST_AUTHORITY_RECONCILIATION_INPUT_INVALID")
        old = next((row for row in self.campaigns if row.request.campaign_key == request.campaign_key), None)
        if old is not None:
            if (
                old.request == request
                and old.owner_issue_number == issue_number
                and old.owner_run_id == historical_run_id
                and old.terminal_receipt_sha256 is None
                and old.legacy_closure_evidence_sha256 == legacy_closure_evidence_sha256
            ):
                return self
            raise ValueError("CATALOG_FAST_AUTHORITY_RECONCILIATION_CONFLICT")
        if request.launch_generation != 1:
            raise ValueError("CATALOG_FAST_GENERATION_CONFLICT")
        if request.previous_terminal_request_sha256 is not None:
            raise ValueError("CATALOG_FAST_PREDECESSOR_CONFLICT")
        return self._replace(FastAuthorityCampaignV1(
            request=request,
            owner_issue_number=issue_number,
            owner_run_id=historical_run_id,
            legacy_closure_evidence_sha256=legacy_closure_evidence_sha256,
        ))

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
