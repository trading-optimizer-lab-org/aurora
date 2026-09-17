"""Persistable transport transaction; scientific authority remains unchanged."""

from typing import Literal
from uuid import RFC_4122, UUID

from pydantic import Field, field_validator, model_validator

from .catalog_cloud_intake import CloudIntentV1

from .catalog_request_contract import (
    CatalogLaunchTicketV1, CatalogRunRequestV1, FrozenModel, Sha256,
    canonical_model_bytes,
)


class CloudOriginEvidenceV1(FrozenModel):
    """Public evidence bound by the authenticated producer's authority artifact."""

    app_id: int = Field(strict=True, ge=1)
    installation_id: int = Field(strict=True, ge=1)
    requester_actor: str = Field(pattern=r"^[a-zA-Z0-9-]+\[bot\]$")
    requester_public_key_sha256: Sha256
    environment: Literal["catalog-cloud-intake"]
    permissions: tuple[tuple[str, str], ...]
    retirement_receipt_sha256: Sha256
    launch_ticket_sha256: Sha256

    @model_validator(mode="after")
    def _scope(self):
        if self.permissions != (("issues", "write"), ("metadata", "read")):
            raise ValueError("CATALOG_CLOUD_ORIGIN_PERMISSIONS_INVALID")
        return self


class CatalogCloudEmissionV1(FrozenModel):
    intent_id: str
    intent_issue_number: int = Field(strict=True, ge=1)
    repository_id: int = Field(strict=True, ge=1)
    actor_id: int = Field(strict=True, ge=1)
    intent_sha256: Sha256
    request: CatalogRunRequestV1
    origin: CloudOriginEvidenceV1
    producer_run_id: int = Field(strict=True, ge=1)
    producer_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    state: Literal["SIGNED", "PUBLICACION_INCIERTA", "PUBLICADO"]
    issue_number: int | None = Field(default=None, strict=True, ge=1)
    post_run_id: int | None = Field(default=None, strict=True, ge=1)
    post_run_attempt: int | None = Field(default=None, strict=True, ge=1)

    @field_validator("intent_id")
    @classmethod
    def _uuid4(cls, value: str) -> str:
        identifier = UUID(value)
        if identifier.version != 4 or identifier.variant != RFC_4122 or str(identifier) != value:
            raise ValueError("CATALOG_CLOUD_INTENT_ID_INVALID")
        return value

    @model_validator(mode="after")
    def _binding(self) -> "CatalogCloudEmissionV1":
        intent = CloudIntentV1(intent_id=self.intent_id, campaign_key=self.request.campaign_key)
        if intent.intent_sha256 != self.intent_sha256:
            raise ValueError("CATALOG_CLOUD_INTENT_CONFLICT")
        if (self.origin.launch_ticket_sha256 != self.request.launch_ticket_sha256
                or self.origin.requester_public_key_sha256 != self.request.requester_public_key_sha256):
            raise ValueError("CATALOG_CLOUD_ORIGIN_BINDING_INVALID")
        if (self.state == "PUBLICADO") != (self.issue_number is not None):
            raise ValueError("CATALOG_CLOUD_EMISSION_TRANSITION_INVALID")
        if self.state == "SIGNED":
            if self.post_run_id is not None or self.post_run_attempt is not None:
                raise ValueError("CATALOG_CLOUD_EMISSION_TRANSITION_INVALID")
        elif self.post_run_id is None or self.post_run_attempt is None:
            raise ValueError("CATALOG_CLOUD_EMISSION_TRANSITION_INVALID")
        ticket = CatalogLaunchTicketV1(
            schema_version="1", request_id=self.request.request_id,
            campaign_key=self.request.campaign_key,
            launch_generation=self.request.launch_generation,
            campaign_definition_sha256=self.request.campaign_definition_sha256,
            prompt_sha256=self.request.prompt_sha256,
            previous_terminal_request_sha256=self.request.previous_terminal_request_sha256,
        )
        if ticket.launch_ticket_sha256 != self.request.launch_ticket_sha256:
            raise ValueError("CATALOG_CLOUD_TICKET_MISMATCH")
        return self

    @property
    def title(self) -> str:
        return f"[AURORA CATALOG RUN REQUEST] {self.request.request_id}"

    @property
    def body(self) -> str:
        return "```json\n" + canonical_model_bytes(self.request).decode("utf-8") + "\n```\n"

    def advance(self, state: str, issue_number: int | None = None, *,
                post_run_id: int | None = None, post_run_attempt: int | None = None) -> "CatalogCloudEmissionV1":
        post_id = self.post_run_id if post_run_id is None else post_run_id
        post_attempt = self.post_run_attempt if post_run_attempt is None else post_run_attempt
        if state == self.state and issue_number == self.issue_number and (post_id, post_attempt) == (self.post_run_id, self.post_run_attempt):
            return self
        if (self.state, state) not in {
            ("SIGNED", "PUBLICACION_INCIERTA"),
            ("PUBLICACION_INCIERTA", "PUBLICADO"),
        }:
            raise ValueError("CATALOG_CLOUD_EMISSION_TRANSITION_INVALID")
        if self.state != "SIGNED" and (post_id, post_attempt) != (self.post_run_id, self.post_run_attempt):
            raise ValueError("CATALOG_CLOUD_EMISSION_TRANSITION_INVALID")
        return self.__class__.model_validate({
            **self.model_dump(mode="json"), "state": state, "issue_number": issue_number,
            "post_run_id": post_id, "post_run_attempt": post_attempt,
        })


class CatalogCloudCompletedIntentV1(FrozenModel):
    """Compact replay binding inside the same authenticated authority."""

    intent_id: str
    intent_issue_number: int = Field(strict=True, ge=1)
    repository_id: int = Field(strict=True, ge=1)
    actor_id: int = Field(strict=True, ge=1)
    intent_sha256: Sha256
    campaign_key: str
    request_id: str
    request_sha256: Sha256
    issue_number: int = Field(strict=True, ge=1)
    terminal_receipt_sha256: Sha256

    @model_validator(mode="after")
    def _binding(self) -> "CatalogCloudCompletedIntentV1":
        intent = CloudIntentV1(intent_id=self.intent_id, campaign_key=self.campaign_key)
        identifier = UUID(self.request_id)
        if (intent.intent_sha256 != self.intent_sha256 or identifier.version != 7
                or identifier.variant != RFC_4122 or str(identifier) != self.request_id):
            raise ValueError("CATALOG_CLOUD_COMPLETED_INTENT_INVALID")
        return self

    @classmethod
    def from_emission(cls, emission: CatalogCloudEmissionV1, terminal_hash: str):
        if emission.issue_number is None:
            raise ValueError("CATALOG_CLOUD_EMISSION_UNPUBLISHED")
        return cls(
            intent_id=emission.intent_id, intent_issue_number=emission.intent_issue_number,
            repository_id=emission.repository_id, actor_id=emission.actor_id,
            intent_sha256=emission.intent_sha256, campaign_key=emission.request.campaign_key,
            request_id=emission.request.request_id, request_sha256=emission.request.request_sha256,
            issue_number=emission.issue_number, terminal_receipt_sha256=terminal_hash,
        )
