"""Compact state transitions, not a replacement for writer authentication.

The GitHub adapter must verify anchor, latest edit and artifact producer before
using this state. Bootstrap is a maintenance operation, never a missing-state
fallback. This module performs no remote writes or automatic initialization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from datetime import datetime
import json

from pydantic import Field, field_validator, model_serializer, model_validator

from ..github_performance.contracts import canonical_sha256
from .catalog_request_contract import CatalogLaunchTicketV1, CatalogRunRequestV1, FrozenModel, Sha256
from .catalog_cloud_emission import CatalogCloudEmissionV1, CatalogCloudCompletedIntentV1
from .catalog_lineage_transition import CatalogLineageTransitionV1, load_lineage_transition as load_lineage_transition
from .catalog_unreserved_checkpoint_recovery import UnreservedCheckpointRecoveryProofV1

if TYPE_CHECKING:
    from .catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1


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


class CheckpointRecoverySupersededIntentV1(FrozenModel):
    """Retain the failed emission without inventing a scientific terminal."""

    emission: CatalogCloudEmissionV1
    source_owner_issue_number: int = Field(strict=True, ge=1)
    source_owner_run_id: int = Field(strict=True, ge=1)
    recovery_profile_sha256: Sha256
    recovery_evidence_sha256: Sha256
    successor_request_sha256: Sha256

    @model_validator(mode="after")
    def _binding(self) -> "CheckpointRecoverySupersededIntentV1":
        if (self.emission.state != "PUBLICADO"
            or self.emission.issue_number != self.source_owner_issue_number
            or self.emission.request.request_sha256 == self.successor_request_sha256):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_INVALID")
        return self


class UnreservedCheckpointSupersededIntentV1(FrozenModel):
    """Published transport failure, never an owner or scientific terminal."""

    emission: CatalogCloudEmissionV1
    authority_state_sha256: Sha256
    proof: UnreservedCheckpointRecoveryProofV1
    recovery_profile_sha256: Sha256
    recovery_evidence_sha256: Sha256
    successor_request_sha256: Sha256

    @field_validator("proof", mode="before")
    @classmethod
    def _proof_bytes(cls, value):
        # Authority _create round-trips canonical JSON through a Python mapping.
        # Decode only the serialized proof via its strict JSON model, preserving
        # strict integers, closed fields and UTC/expiry validation.
        if isinstance(value, dict) and all(isinstance(value.get(key), str) for key in
                                          ("observed_at", "expires_at", "request_expired_at")):
            return UnreservedCheckpointRecoveryProofV1.model_validate_json(json.dumps(value))
        if isinstance(value, UnreservedCheckpointRecoveryProofV1):
            return UnreservedCheckpointRecoveryProofV1.model_validate(value.model_dump())
        return value

    @property
    def unreserved_evidence_sha256(self) -> str:
        return self.proof.evidence_sha256

    @model_validator(mode="after")
    def _binding(self) -> "UnreservedCheckpointSupersededIntentV1":
        if (self.emission.state != "PUBLICADO"
                or self.emission.request.request_sha256 == self.successor_request_sha256
                or self.proof.authority_state_sha256 != self.authority_state_sha256
                or self.proof.emission_sha256 != canonical_sha256(self.emission.model_dump(mode="json"))
                or self.proof.failed_request_sha256 != self.emission.request.request_sha256
                or self.proof.failed_issue_number != self.emission.issue_number
                or self.proof.campaign_key != self.emission.request.campaign_key
                or self.proof.target_generation != self.emission.request.launch_generation
                or self.proof.source_request_sha256 != self.emission.request.previous_terminal_request_sha256
                or self.proof.profile_sha256 != self.recovery_profile_sha256):
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_ARCHIVE_INVALID")
        return self


class _AuthorityContent(FrozenModel):
    schema_version: Literal["1"] = "1"
    document_type: Literal["catalog_fast_authority_state_v1"] = "catalog_fast_authority_state_v1"
    revision: int = Field(strict=True, ge=1)
    previous_state_sha256: Sha256 | None
    campaigns: tuple[FastAuthorityCampaignV1, ...] = Field(max_length=128)
    emissions: tuple[CatalogCloudEmissionV1, ...] = Field(default=(), max_length=128)
    completed_intents: tuple[CatalogCloudCompletedIntentV1, ...] = Field(default=(), max_length=128)
    recovery_superseded_intents: tuple[CheckpointRecoverySupersededIntentV1, ...] = Field(default=(), max_length=128)
    unreserved_superseded_intents: tuple[UnreservedCheckpointSupersededIntentV1, ...] = Field(default=(), max_length=128)

    @model_serializer(mode="wrap")
    def _legacy_wire_shape(self, handler):
        payload = handler(self)
        if not self.emissions:
            payload.pop("emissions", None)
        if not self.completed_intents:
            payload.pop("completed_intents", None)
        if not self.recovery_superseded_intents:
            payload.pop("recovery_superseded_intents", None)
        if not self.unreserved_superseded_intents:
            payload.pop("unreserved_superseded_intents", None)
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
        superseded_ids = tuple(row.emission.intent_id for row in self.recovery_superseded_intents)
        if (superseded_ids != tuple(sorted(set(superseded_ids)))
            or set(superseded_ids) & (set(archived_ids) | set(intent_ids))
            or len(superseded_ids) + len(archived_ids) > 128):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_INVALID")
        unreserved_ids = tuple(row.emission.intent_id for row in self.unreserved_superseded_intents)
        if (unreserved_ids != tuple(sorted(set(unreserved_ids)))
                or set(unreserved_ids) & (set(intent_ids) | set(archived_ids) | set(superseded_ids))
                or len(unreserved_ids) + len(superseded_ids) + len(archived_ids) > 128):
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_ARCHIVE_INVALID")
        old_hashes = [row.emission.request.request_sha256 for row in self.unreserved_superseded_intents]
        new_hashes = [row.successor_request_sha256 for row in self.unreserved_superseded_intents]
        if len(set(old_hashes)) != len(old_hashes) or len(set(new_hashes)) != len(new_hashes):
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_ARCHIVE_INVALID")
        edges = dict(zip(old_hashes, new_hashes))
        for start in edges:
            seen = set()
            while start in edges:
                if start in seen:
                    raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_ARCHIVE_INVALID")
                seen.add(start)
                start = edges[start]
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
                            completed_intents=self.completed_intents,
                              recovery_superseded_intents=self.recovery_superseded_intents,
                              unreserved_superseded_intents=self.unreserved_superseded_intents)

    def _checkpoint_predecessor(self, request: CatalogRunRequestV1 | CatalogLaunchTicketV1,
                               recovery_proof: "CheckpointRecoveryOwnerProofV1",
                               lineage_transition: CatalogLineageTransitionV1 | None) -> FastAuthorityCampaignV1:
        from .catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1

        old = next((row for row in self.campaigns if row.request.campaign_key == request.campaign_key), None)
        if (
            not isinstance(recovery_proof, CheckpointRecoveryOwnerProofV1)
            or recovery_proof.evidence_kind not in {"failed_owner_without_terminal", "failed_owner_with_terminal"}
            or old is None
            or (recovery_proof.evidence_kind == "failed_owner_without_terminal" and old.is_terminal)
            or (recovery_proof.evidence_kind == "failed_owner_with_terminal" and (
                not old.is_terminal or recovery_proof.source_terminal_receipt_sha256 is None
                or old.terminal_receipt_sha256 != recovery_proof.source_terminal_receipt_sha256))
            or old.owner_issue_number != recovery_proof.source_issue_number
            or old.owner_run_id != recovery_proof.source_run_id
            or old.request.request_sha256 != recovery_proof.source_request_sha256
            or request.campaign_key != recovery_proof.campaign_key
            or request.launch_generation != recovery_proof.target_generation
            or request.launch_generation != old.generation + 1
            or request.previous_terminal_request_sha256 != old.request.request_sha256
            or request.request_id == old.request.request_id
            or lineage_transition is None
            or not lineage_transition.authorizes(old.request, request)
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_INVALID")
        return old

    def _checkpoint_archive(self, request: CatalogRunRequestV1,
                            recovery_proof: "CheckpointRecoveryOwnerProofV1") -> CheckpointRecoverySupersededIntentV1:
        from .catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1

        if not isinstance(recovery_proof, CheckpointRecoveryOwnerProofV1):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_INVALID")
        if any(row.emission.request.request_sha256 == request.request_sha256
               for row in self.unreserved_superseded_intents):
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_SOURCE_SUPERSEDED")
        target = request.request_sha256
        visited = set()
        while True:
            links = [row for row in self.unreserved_superseded_intents
                     if row.successor_request_sha256 == target]
            if not links:
                break
            if (len(links) != 1 or target in visited
                    or links[0].recovery_profile_sha256 != recovery_proof.profile_sha256
                    or links[0].recovery_evidence_sha256 != recovery_proof.evidence_sha256
                    or links[0].emission.request.launch_generation != request.launch_generation
                    or links[0].emission.request.campaign_key != request.campaign_key
                    or links[0].emission.request.previous_terminal_request_sha256 != request.previous_terminal_request_sha256):
                raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_ARCHIVE_INVALID")
            visited.add(target)
            target = links[0].emission.request.request_sha256
        rows = [row for row in self.recovery_superseded_intents
                if row.successor_request_sha256 == target]
        if len(rows) != 1:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_INVALID")
        row = rows[0]
        if (row.recovery_profile_sha256 != recovery_proof.profile_sha256
            or row.recovery_evidence_sha256 != recovery_proof.evidence_sha256
            or row.source_owner_issue_number != recovery_proof.source_issue_number
            or row.source_owner_run_id != recovery_proof.source_run_id
            or row.emission.request.request_sha256 != recovery_proof.source_request_sha256
            or request.previous_terminal_request_sha256 != recovery_proof.source_request_sha256):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_INVALID")
        return row

    def _require_unreserved_checkpoint(self, request, *, recovery_proof, unreserved_proof, now):
        """Caller supplies freshly authenticated evidence, never issue labels alone."""
        from .catalog_unreserved_checkpoint_recovery import UnreservedCheckpointRecoveryProofV1
        from .catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1

        if (not isinstance(unreserved_proof, UnreservedCheckpointRecoveryProofV1)
                or not isinstance(recovery_proof, CheckpointRecoveryOwnerProofV1)):
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_PROOF_INVALID")
        proof = UnreservedCheckpointRecoveryProofV1.model_validate(unreserved_proof.model_dump())
        if (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
                or not proof.observed_at <= now < proof.expires_at
                or now < proof.request_expired_at):
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_PROOF_EXPIRED")
        old = next(
            (row for row in self.campaigns if row.request.campaign_key == request.campaign_key), None)
        prior = next((row for row in self.emissions if row.request.campaign_key == request.campaign_key), None)
        if (old is None or old.is_terminal or prior is None or prior.state != "PUBLICADO"
                or old.request == prior.request or prior.request.launch_generation != old.generation + 1
                or proof.repository != "trading-optimizer-lab-org/aurora"
                or proof.authority_state_sha256 != self.state_sha256
                or proof.emission_sha256 != canonical_sha256(prior.model_dump(mode="json"))
                or proof.failed_request_sha256 != prior.request.request_sha256
                or proof.failed_issue_number != prior.issue_number
                or proof.campaign_key != request.campaign_key or proof.target_generation != request.launch_generation
                or request.launch_generation != prior.request.launch_generation
                or request.previous_terminal_request_sha256 != prior.request.previous_terminal_request_sha256
                or request.request_id in {prior.request.request_id, old.request.request_id}
                or proof.source_owner_issue_number != old.owner_issue_number
                or proof.source_owner_run_id != old.owner_run_id
                or proof.source_request_sha256 != old.request.request_sha256
                or proof.profile_sha256 != recovery_proof.profile_sha256):
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_PROOF_INVALID")
        self._checkpoint_archive(prior.request, recovery_proof)
        return prior

    def replace_unreserved_checkpoint_emission(self, emission: CatalogCloudEmissionV1, *,
                                              recovery_proof, unreserved_proof,
                                              lineage_transition=None, now):
        """Archive failed transport and stage a fresh same-generation request atomically."""
        from .catalog_unreserved_checkpoint_recovery import UnreservedCheckpointRecoveryProofV1

        if (not isinstance(unreserved_proof, UnreservedCheckpointRecoveryProofV1)
                or emission.state != "SIGNED" or not isinstance(now, datetime)
                or now.tzinfo is None or now.utcoffset() is None):
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_PROOF_INVALID")
        proof = UnreservedCheckpointRecoveryProofV1.model_validate(unreserved_proof.model_dump())
        if not proof.observed_at <= now < proof.expires_at or now < proof.request_expired_at:
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_PROOF_EXPIRED")
        matching = next((row for row in self.emissions if row.intent_id == emission.intent_id), None)
        if matching is not None:
            mutable = {"state", "issue_number", "post_run_id", "post_run_attempt"}
            links = [row for row in self.unreserved_superseded_intents
                     if row.successor_request_sha256 == emission.request.request_sha256]
            if (matching.model_dump(exclude=mutable) != emission.model_dump(exclude=mutable)
                    or len(links) != 1 or links[0].unreserved_evidence_sha256 != proof.evidence_sha256
                    or links[0].authority_state_sha256 != proof.authority_state_sha256):
                raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_REPLAY_CONFLICT")
            self._checkpoint_archive(emission.request, recovery_proof)
            return self
        archived_ids = {row.intent_id for row in self.completed_intents} | {
            row.intent_id for row in (
                *(item.emission for item in self.recovery_superseded_intents),
                *(item.emission for item in self.unreserved_superseded_intents))}
        if emission.intent_id in archived_ids:
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_INTENT_SUPERSEDED")
        prior = self._require_unreserved_checkpoint(emission.request, recovery_proof=recovery_proof,
                                                    unreserved_proof=proof, now=now)
        if emission.intent_issue_number == prior.intent_issue_number:
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_INTENT_CONFLICT")
        self._checkpoint_predecessor(emission.request, recovery_proof, lineage_transition)
        if len(self.completed_intents) + len(self.recovery_superseded_intents) + len(self.unreserved_superseded_intents) >= 128:
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_HISTORY_CAPACITY_EXCEEDED")
        archive = UnreservedCheckpointSupersededIntentV1(
            emission=prior, authority_state_sha256=self.state_sha256,
            proof=proof,
            recovery_profile_sha256=recovery_proof.profile_sha256,
            recovery_evidence_sha256=recovery_proof.evidence_sha256,
            successor_request_sha256=emission.request.request_sha256,
        )
        return self._create(revision=self.revision + 1, previous_state_sha256=self.state_sha256,
            campaigns=self.campaigns,
            emissions=tuple(emission if row == prior else row for row in self.emissions),
            completed_intents=self.completed_intents, recovery_superseded_intents=self.recovery_superseded_intents,
            unreserved_superseded_intents=tuple(sorted((*self.unreserved_superseded_intents, archive),
                                                       key=lambda row: row.emission.intent_id)))

    def stage_checkpoint_emission(self, emission: CatalogCloudEmissionV1, *,
                                 recovery_proof: "CheckpointRecoveryOwnerProofV1",
                                 lineage_transition: CatalogLineageTransitionV1 | None = None) -> "FastAuthorityStateV1":
        """Stage a protected successor, preserving its failed source as nonterminal.

        The caller must authenticate this proof afresh and load the profile from
        protected code. The serialized writer independently repeats this transition.
        """
        if recovery_proof.evidence_kind == "failed_owner_with_terminal":
            self._checkpoint_predecessor(emission.request, recovery_proof, lineage_transition)
            return self.stage_emission(emission, lineage_transition=lineage_transition)
        if emission.state != "SIGNED":
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_EMISSION_INVALID")
        matching = next((row for row in self.emissions if row.intent_id == emission.intent_id), None)
        if matching is not None:
            mutable = {"state", "issue_number", "post_run_id", "post_run_attempt"}
            if matching.model_dump(exclude=mutable) != emission.model_dump(exclude=mutable):
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_EMISSION_INVALID")
            self._checkpoint_archive(emission.request, recovery_proof)
            return self
        if (any(row.intent_id == emission.intent_id for row in self.completed_intents)
              or any(row.intent_id == emission.intent_id for row in (
                  *(item.emission for item in self.recovery_superseded_intents),
                  *(item.emission for item in self.unreserved_superseded_intents)))):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_INTENT_REPLAY")
        old = self._checkpoint_predecessor(emission.request, recovery_proof, lineage_transition)
        prior = next((row for row in self.emissions if row.request.campaign_key == emission.request.campaign_key), None)
        if (prior is None or prior.state != "PUBLICADO" or prior.request != old.request
            or prior.issue_number != old.owner_issue_number):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_EMISSION_INVALID")
        if len(self.completed_intents) + len(self.recovery_superseded_intents) + len(self.unreserved_superseded_intents) >= 128:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_HISTORY_CAPACITY_EXCEEDED")
        archive = CheckpointRecoverySupersededIntentV1(
            emission=prior, source_owner_issue_number=old.owner_issue_number,
            source_owner_run_id=old.owner_run_id,
            recovery_profile_sha256=recovery_proof.profile_sha256,
            recovery_evidence_sha256=recovery_proof.evidence_sha256,
            successor_request_sha256=emission.request.request_sha256,
        )
        rows = {row.request.campaign_key: row for row in self.emissions}
        rows[emission.request.campaign_key] = emission
        return self._create(
            revision=self.revision + 1, previous_state_sha256=self.state_sha256,
            campaigns=self.campaigns, emissions=tuple(rows[key] for key in sorted(rows)),
            completed_intents=self.completed_intents,
            unreserved_superseded_intents=self.unreserved_superseded_intents,
            recovery_superseded_intents=tuple(sorted((*self.recovery_superseded_intents, archive),
                                                   key=lambda row: row.emission.intent_id)),
        )

    def reserve_checkpoint_successor(self, *, request: CatalogRunRequestV1, issue_number: int, run_id: int,
                                    recovery_proof: "CheckpointRecoveryOwnerProofV1",
                                    lineage_transition: CatalogLineageTransitionV1 | None = None) -> "FastAuthorityStateV1":
        """Reserve only the published successor already bound to the source proof."""
        if recovery_proof.evidence_kind == "failed_owner_with_terminal":
            old = next((row for row in self.campaigns if row.request.campaign_key == request.campaign_key), None)
            if old is None or old.request != request:
                self._checkpoint_predecessor(request, recovery_proof, lineage_transition)
            return self.reserve(request=request, issue_number=issue_number, run_id=run_id,
                                lineage_transition=lineage_transition)
        self._checkpoint_archive(request, recovery_proof)
        emission = next((row for row in self.emissions if row.request.campaign_key == request.campaign_key), None)
        if (emission is None or emission.request != request or emission.state != "PUBLICADO"
            or emission.issue_number != issue_number):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_EMISSION_INVALID")
        old = next((row for row in self.campaigns if row.request.campaign_key == request.campaign_key), None)
        if old is not None and old.request == request:
            return self
        self._checkpoint_predecessor(request, recovery_proof, lineage_transition)
        return self._replace(FastAuthorityCampaignV1(request=request, owner_issue_number=issue_number, owner_run_id=run_id))

    def stage_emission(self, emission: CatalogCloudEmissionV1, *,
                       lineage_transition: CatalogLineageTransitionV1 | None = None) -> "FastAuthorityStateV1":
        """Persist one signed request before posting; caller verifies its signature.

        Completed intent bindings remain in this same authenticated state; full
        signed bytes remain in the verified scientific issue and its artifacts.
        """
        if emission.state != "SIGNED":
            raise ValueError("CATALOG_CLOUD_EMISSION_TRANSITION_INVALID")
        if any(row.intent_id == emission.intent_id for row in (
                *(item.emission for item in self.recovery_superseded_intents),
                *(item.emission for item in self.unreserved_superseded_intents))):
            raise ValueError("CATALOG_CLOUD_INTENT_ALREADY_SUPERSEDED")
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
            if len(completed) + len(self.recovery_superseded_intents) + len(self.unreserved_superseded_intents) >= 128:
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
                            completed_intents=tuple(completed[key] for key in sorted(completed)),
                              recovery_superseded_intents=self.recovery_superseded_intents,
                              unreserved_superseded_intents=self.unreserved_superseded_intents)

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
                            completed_intents=self.completed_intents,
                              recovery_superseded_intents=self.recovery_superseded_intents,
                              unreserved_superseded_intents=self.unreserved_superseded_intents)

    def reserve(self, *, request: CatalogRunRequestV1, issue_number: int, run_id: int,
                lineage_transition: CatalogLineageTransitionV1 | None = None) -> "FastAuthorityStateV1":
        if any(row.request.request_sha256 == request.request_sha256 for row in (
                *(item.emission for item in self.recovery_superseded_intents),
                *(item.emission for item in self.unreserved_superseded_intents))):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_SUPERSEDED")
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

    def close_unlaunched(
        self, *, request: CatalogRunRequestV1, issue_number: int, run_id: int,
        terminal_receipt_sha256: str,
        lineage_transition: CatalogLineageTransitionV1 | None = None,
    ) -> "FastAuthorityStateV1":
        """Close one exact published cloud request without launching science.

        ``reserve`` is used only as an in-memory validation of generation,
        predecessor, owner-terminal and lineage rules.  Its intermediate
        reservation is deliberately discarded; the returned state contains
        one terminal campaign row and advances the authority exactly once.
        """
        emission = next(
            (row for row in self.emissions if row.request.campaign_key == request.campaign_key),
            None,
        )
        if (
            emission is None
            or emission.state != "PUBLICADO"
            or emission.request != request
            or emission.issue_number != issue_number
        ):
            raise ValueError("CATALOG_FAST_UNLAUNCHED_EMISSION_INVALID")

        existing = next(
            (row for row in self.campaigns if row.request.campaign_key == request.campaign_key),
            None,
        )
        if existing is not None and (
            existing.request.request_id == request.request_id
            or existing.request.request_sha256 == request.request_sha256
        ):
            raise ValueError("CATALOG_FAST_UNLAUNCHED_OWNER_EXISTS")

        validated = self.reserve(
            request=request,
            issue_number=issue_number,
            run_id=run_id,
            lineage_transition=lineage_transition,
        )
        row = next(
            (item for item in validated.campaigns if item.request.campaign_key == request.campaign_key),
            None,
        )
        if (
            row is None
            or row.request != request
            or row.owner_issue_number != issue_number
            or row.owner_run_id != run_id
            or row.legacy_closure_evidence_sha256 is not None
        ):
            raise ValueError("CATALOG_FAST_UNLAUNCHED_TRANSITION_INVALID")

        terminal_row = FastAuthorityCampaignV1.model_validate({
            **row.model_dump(mode="json"),
            "terminal_receipt_sha256": terminal_receipt_sha256,
            "legacy_closure_evidence_sha256": None,
        })
        return self._replace(terminal_row)

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
        if any(row.request.request_sha256 == request.request_sha256 for row in (
                *(item.emission for item in self.recovery_superseded_intents),
                *(item.emission for item in self.unreserved_superseded_intents))):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_SUPERSEDED")
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
