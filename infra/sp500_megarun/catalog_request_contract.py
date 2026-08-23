"""Pure request contracts shared by the unprivileged client and verifier."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import RFC_4122, UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def canonical_model_bytes(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: BaseModel) -> str:
    return hashlib.sha256(canonical_model_bytes(value)).hexdigest()


REQUEST_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
CAMPAIGN_KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+$"
_TITLE = re.compile(r"^\[AURORA CATALOG RUN REQUEST\] (?P<request_id>[0-9a-f-]{36})$")
_BODY = re.compile(r"\A```json\n(?P<payload>\{[^\x00]*\})\n```\n\Z")
MAX_TITLE_CHARS = 128
MAX_BODY_BYTES = 4096


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


class CatalogLaunchTicketV1(FrozenModel):
    schema_version: Literal["1"]
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    launch_generation: int = Field(ge=1)
    campaign_definition_sha256: Sha256
    prompt_sha256: Sha256
    previous_terminal_request_sha256: Sha256 | None

    @field_validator("request_id")
    @classmethod
    def _require_uuid7(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or parsed.variant != RFC_4122:
            raise ValueError("request_id must be RFC 4122 UUIDv7")
        return value

    @model_validator(mode="after")
    def _require_predecessor_shape(self) -> "CatalogLaunchTicketV1":
        if (self.launch_generation == 1) != (
            self.previous_terminal_request_sha256 is None
        ):
            raise ValueError("only generation 1 may omit terminal predecessor")
        return self

    @property
    def launch_ticket_sha256(self) -> str:
        return canonical_sha256(self)


class CatalogRunIntentDraftV1(FrozenModel):
    schema_version: Literal["1"]
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    launch_generation: int = Field(ge=1)
    launch_ticket_sha256: Sha256
    previous_terminal_request_sha256: Sha256 | None
    campaign_definition_sha256: Sha256
    prompt_sha256: Sha256
    authorization: Literal["USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN"]
    free_resources_only: Literal[True]
    automatic_recovery: Literal[True]
    max_same_failure_count: Literal[3]

    @field_validator("request_id")
    @classmethod
    def _require_uuid7(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or parsed.variant != RFC_4122:
            raise ValueError("request_id must be RFC 4122 UUIDv7")
        return value

    @model_validator(mode="after")
    def _require_predecessor_shape(self) -> "CatalogRunIntentDraftV1":
        if (self.launch_generation == 1) != (
            self.previous_terminal_request_sha256 is None
        ):
            raise ValueError("only generation 1 may omit terminal predecessor")
        return self

    @property
    def submission_key_sha256(self) -> str:
        return canonical_sha256(self)


class CatalogRunIntentV1(CatalogRunIntentDraftV1):
    @property
    def intent_sha256(self) -> str:
        return canonical_sha256(self)


class CatalogRunRequestV1(CatalogRunIntentV1):
    requester_public_key_sha256: Sha256
    requester_attestation_algorithm: Literal["rsa-pss-sha256-v1"]
    requester_attestation_b64: str = Field(
        pattern=r"^[A-Za-z0-9+/]+={0,2}$",
        min_length=300,
        max_length=700,
    )

    @property
    def intent(self) -> CatalogRunIntentV1:
        return CatalogRunIntentV1.model_validate(
            self.model_dump(
                exclude={
                    "requester_public_key_sha256",
                    "requester_attestation_algorithm",
                    "requester_attestation_b64",
                }
            )
        )

    @property
    def intent_sha256(self) -> str:
        return self.intent.intent_sha256

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(self)


def _attestation_payload(title: str, intent: CatalogRunIntentV1) -> bytes:
    canonical_intent = canonical_model_bytes(intent)
    return (
        b"AURORA_CATALOG_REQUEST_ATTESTATION_V1\x00"
        + title.encode("utf-8")
        + b"\x00"
        + canonical_intent
    )
