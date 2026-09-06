"""Pure, unprivileged client boundary for catalog-run requests.

This module deliberately has no network, credential, subprocess, or broker
dependency.  It validates one service-owned launch ticket, produces one closed
intent draft, and can only exclusive-create that draft in a fixed spool.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Literal
import zipfile

from pydantic import Field, field_validator, model_validator

from .catalog_campaign_definition_contract import (
    CatalogCampaignDefinitionManifestV1,
    parse_catalog_campaign_definition_bytes,
    registry_entry_sha256,
)
from .catalog_campaign_registry import (
    CatalogCampaignEntryV1,
    load_catalog_campaign_registry,
)
from .catalog_request_contract import (
    CAMPAIGN_KEY_PATTERN,
    FrozenModel,
    Sha256,
    CatalogLaunchTicketV1,
    CatalogRunIntentDraftV1,
    canonical_model_bytes,
    canonical_sha256,
)


_REQUEST_SUFFIX = ".request.json"
_RECEIPT_SUFFIX = ".receipt.json"
_MAX_REQUEST_BYTES = 4_096
_CAPACITY_RECEIPT_NAME = "broker-capacity-v1.receipt.json"
_FINAL_BOOTSTRAP_RECEIPT_NAME = "controller-bootstrap-v1.receipt.json"
_APPLICATION_CORE_KEYS = frozenset(
    {
        "schema_version",
        "manifest_format",
        "application_kind",
        "application_version",
        "protected_commit_sha",
        "python_requirement",
        "entry_point",
        "archive_package",
        "source_files",
        "generated_members",
        "archive_members",
        "embedded_manifest_member",
        "dependency_input",
        "dependency_lock",
        "public_inputs",
        "embedded_manifest_sha256_location",
        "application_sha256_location",
    }
)
_APPLICATION_SOURCES = {
    "client": (
        "infra/sp500_megarun/catalog_request_contract.py",
        "infra/sp500_megarun/catalog_chat_intent.py",
        "infra/sp500_megarun/catalog_chat_submission.py",
        "infra/sp500_megarun/catalog_chat_windows_input.py",
        "infra/sp500_megarun/catalog_chat_consumer.py",
        "infra/sp500_megarun/catalog_chat_delivery.py",
        "infra/sp500_megarun/catalog_chat_service.py",
        "infra/sp500_megarun/catalog_campaign_registry.py",
        "infra/sp500_megarun/catalog_campaign_definition_contract.py",
        "infra/sp500_megarun/catalog_requester.py",
        "infra/sp500_megarun/catalog_requester_cli.py",
    ),
    "broker": (
        "infra/sp500_megarun/catalog_request_contract.py",
        "infra/sp500_megarun/catalog_campaign_registry.py",
        "infra/sp500_megarun/catalog_campaign_definition_contract.py",
        "infra/sp500_megarun/catalog_requester.py",
        "infra/sp500_megarun/catalog_run_request.py",
        "infra/sp500_megarun/catalog_requester_broker.py",
        "infra/sp500_megarun/catalog_requester_broker_cli.py",
    ),
}
_APPLICATION_DEPENDENCIES = {
    "client": (
        "requirements/catalog-requester-client.in",
        "requirements/catalog-requester-client-win-py314.lock",
    ),
    "broker": (
        "requirements/catalog-requester-broker.in",
        "requirements/catalog-requester-broker-win-py314.lock",
    ),
}
_APPLICATION_PUBLIC_INPUTS = (
    "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md",
    "config/catalog_run_prompt_policy_v1.json",
    "config/catalog_campaign_registry_v1.json",
    "config/catalog_requester_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_controls_v1.json",
    "config/catalog_requester_public_key_v1.pem",
    "schemas/catalog_requester_app_manifest_v1.schema.json",
    "schemas/catalog_campaign_definition_manifest_v1.schema.json",
    "schemas/catalog_run_prompt_policy_v1.schema.json",
)


class CatalogRequesterBrokerSpoolConfigV1(FrozenModel):
    transport: Literal["windows_locked_spool_v1"]
    root: Literal["C:/ProgramData/AURORA/CatalogRequester"]
    inbox: Literal["inbox"]
    processing: Literal["processing"]
    receipts: Literal["receipts"]
    launch_tickets: Literal["launch-tickets"]
    campaign_status: Literal["campaign-status"]
    secrets: Literal["secrets"]
    production_seal: Literal["config/production-enabled-v1.seal.json"]
    task_name: Literal["AURORA Catalog Requester Broker"]
    service_identity: Literal["AURORARequester"]
    maximum_request_bytes: Literal[4096]
    maximum_hint_bytes: Literal[1024]
    maximum_pending_entries: Literal[32]
    maximum_inbox_bytes: Literal[131072]
    poll_seconds: Literal[2]
    client_receipt_timeout_seconds: Literal[90]
    terminal_reconcile_min_seconds: Literal[60]
    terminal_reconcile_max_seconds: Literal[900]
    terminal_reconcile_max_gets_per_minute: Literal[30]


class CatalogRequesterTerminalMarkerV1(FrozenModel):
    label: Literal["catalog-run-terminal-v1"]
    state: Literal["closed"]
    state_reason: Literal["completed"]
    closed_by: Literal["github-actions[bot]"]


class CatalogRequesterBootstrapQualificationV1(FrozenModel):
    campaign_key: Literal["controller-bootstrap-qualification-v1"]
    maximum_posts: Literal[1]
    allowed_only_before_broker_seal: Literal[True]
    must_end_without_authority_or_compute: Literal[True]


class CatalogRequesterConfigV1(FrozenModel):
    schema_version: Literal["1"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    api_origin: Literal["https://api.github.com"]
    api_version: Literal["2026-03-10"]
    request_issue_endpoint: Literal["/repos/{repository}/issues"]
    broker: CatalogRequesterBrokerSpoolConfigV1
    terminal_close_marker: CatalogRequesterTerminalMarkerV1
    bootstrap_qualification: CatalogRequesterBootstrapQualificationV1
    required_installation_permissions: dict[str, Literal["read", "write"]]
    forbidden_write_permissions: tuple[str, ...]
    timeout_seconds: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def _closed_permission_contract(self) -> "CatalogRequesterConfigV1":
        if self.required_installation_permissions != {
            "issues": "write",
            "metadata": "read",
        }:
            raise ValueError("REQUESTER_PERMISSION_CONFIG_INVALID")
        if len(self.forbidden_write_permissions) != len(
            set(self.forbidden_write_permissions)
        ):
            raise ValueError("REQUESTER_PERMISSION_CONFIG_INVALID")
        return self


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("REQUESTER_TIME_NOT_UTC")
    return value.astimezone(UTC)


def _validated_campaign_key(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(CAMPAIGN_KEY_PATTERN, value) is None:
        raise ValueError("CATALOG_CAMPAIGN_UNRESOLVED")
    return value


class CatalogBrokerCapacityReceiptV1(FrozenModel):
    """Secret-free, service-authored proof that the bounded inbox has room."""

    schema_version: Literal["1"] = "1"
    observed_at: datetime
    available: bool
    reason_code: Literal[
        "REQUEST_BROKER_CAPACITY_AVAILABLE",
        "REQUEST_BROKER_CAPACITY_EXCEEDED",
        "REQUEST_BROKER_CAPACITY_UNPROVEN",
    ]
    pending_entry_count: int = Field(ge=0)
    pending_bytes: int = Field(ge=0)
    maximum_pending_entries: int = Field(ge=1)
    maximum_inbox_bytes: int = Field(ge=1)
    capacity_receipt_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _validate_shape_and_hash(self) -> "CatalogBrokerCapacityReceiptV1":
        calculated_available = (
            self.pending_entry_count < self.maximum_pending_entries
            and self.pending_bytes < self.maximum_inbox_bytes
        )
        if self.available and (
            not calculated_available
            or self.reason_code != "REQUEST_BROKER_CAPACITY_AVAILABLE"
        ):
            raise ValueError("REQUEST_BROKER_CAPACITY_RECEIPT_INVALID")
        if not self.available and self.reason_code == "REQUEST_BROKER_CAPACITY_AVAILABLE":
            raise ValueError("REQUEST_BROKER_CAPACITY_RECEIPT_INVALID")
        if (
            self.reason_code == "REQUEST_BROKER_CAPACITY_EXCEEDED"
            and calculated_available
        ):
            raise ValueError("REQUEST_BROKER_CAPACITY_RECEIPT_INVALID")
        payload = self.model_copy(update={"capacity_receipt_sha256": "0" * 64})
        if canonical_sha256(payload) != self.capacity_receipt_sha256:
            raise ValueError("REQUEST_BROKER_CAPACITY_RECEIPT_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        observed_at: datetime,
        available: bool,
        pending_entry_count: int,
        pending_bytes: int,
        maximum_pending_entries: int,
        maximum_inbox_bytes: int,
        reason_code: Literal[
            "REQUEST_BROKER_CAPACITY_AVAILABLE",
            "REQUEST_BROKER_CAPACITY_EXCEEDED",
            "REQUEST_BROKER_CAPACITY_UNPROVEN",
        ]
        | None = None,
    ) -> "CatalogBrokerCapacityReceiptV1":
        calculated_available = (
            pending_entry_count < maximum_pending_entries
            and pending_bytes < maximum_inbox_bytes
        )
        if reason_code is None:
            reason_code = (
                "REQUEST_BROKER_CAPACITY_AVAILABLE"
                if available
                else (
                    "REQUEST_BROKER_CAPACITY_EXCEEDED"
                    if not calculated_available
                    else "REQUEST_BROKER_CAPACITY_UNPROVEN"
                )
            )
        unsigned = cls.model_construct(
            schema_version="1",
            observed_at=_require_utc(observed_at),
            available=available,
            reason_code=reason_code,
            pending_entry_count=pending_entry_count,
            pending_bytes=pending_bytes,
            maximum_pending_entries=maximum_pending_entries,
            maximum_inbox_bytes=maximum_inbox_bytes,
            capacity_receipt_sha256="0" * 64,
        )
        return cls.model_validate(
            unsigned.model_copy(
                update={"capacity_receipt_sha256": canonical_sha256(unsigned)}
            ).model_dump(mode="json")
        )


class CatalogRequesterReceiptV1(FrozenModel):
    """Deterministic, secret-free client result for one submission key."""

    schema_version: Literal["1"] = "1"
    status: Literal["pending", "submitted", "existing", "blocked"]
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    submission_key_sha256: Sha256
    request_id: str
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    launch_generation: int = Field(ge=1)
    issue_number: int | None = Field(default=None, ge=1)
    request_sha256: Sha256 | None = None
    observed_at: datetime
    receipt_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _validate_shape_and_hash(self) -> "CatalogRequesterReceiptV1":
        submitted = self.status in {"submitted", "existing"}
        if submitted and (
            self.issue_number is None or self.request_sha256 is None
        ):
            raise ValueError("REQUESTER_RECEIPT_SHAPE_INVALID")
        if not submitted and (
            self.issue_number is not None or self.request_sha256 is not None
        ):
            raise ValueError("REQUESTER_RECEIPT_SHAPE_INVALID")
        payload = self.model_copy(update={"receipt_sha256": "0" * 64})
        if canonical_sha256(payload) != self.receipt_sha256:
            raise ValueError("REQUESTER_RECEIPT_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        status: Literal["pending", "submitted", "existing", "blocked"],
        reason_code: str,
        submission_key_sha256: str,
        request_id: str,
        campaign_key: str,
        launch_generation: int,
        observed_at: datetime,
        issue_number: int | None = None,
        request_sha256: str | None = None,
    ) -> "CatalogRequesterReceiptV1":
        unsigned = cls.model_construct(
            schema_version="1",
            status=status,
            reason_code=reason_code,
            submission_key_sha256=submission_key_sha256,
            request_id=request_id,
            campaign_key=campaign_key,
            launch_generation=launch_generation,
            issue_number=issue_number,
            request_sha256=request_sha256,
            observed_at=_require_utc(observed_at),
            receipt_sha256="0" * 64,
        )
        return cls.model_validate(
            unsigned.model_copy(
                update={"receipt_sha256": canonical_sha256(unsigned)}
            ).model_dump(mode="json")
        )


class CatalogRequesterProductionSealV1(FrozenModel):
    """Final administrator-authored local proof that production may be requested."""

    schema_version: Literal["1"] = "1"
    production_enabled: Literal[True]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    bootstrap_receipt_sha256: Sha256
    requester_client_application_sha256: Sha256
    requester_broker_application_sha256: Sha256
    sealed_at: datetime
    production_seal_sha256: Sha256

    @field_validator("sealed_at")
    @classmethod
    def _utc_sealed_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _hash(self) -> "CatalogRequesterProductionSealV1":
        payload = self.model_copy(update={"production_seal_sha256": "0" * 64})
        if canonical_sha256(payload) != self.production_seal_sha256:
            raise ValueError("REQUESTER_PRODUCTION_SEAL_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        protected_commit_sha: str,
        bootstrap_receipt_sha256: str,
        requester_client_application_sha256: str,
        requester_broker_application_sha256: str,
        sealed_at: datetime,
    ) -> "CatalogRequesterProductionSealV1":
        unsigned = cls.model_construct(
            schema_version="1",
            production_enabled=True,
            protected_commit_sha=protected_commit_sha,
            bootstrap_receipt_sha256=bootstrap_receipt_sha256,
            requester_client_application_sha256=(
                requester_client_application_sha256
            ),
            requester_broker_application_sha256=(
                requester_broker_application_sha256
            ),
            sealed_at=_require_utc(sealed_at),
            production_seal_sha256="0" * 64,
        )
        return cls.model_validate(
            unsigned.model_copy(
                update={"production_seal_sha256": canonical_sha256(unsigned)}
            ).model_dump(mode="json")
        )


class CatalogRequesterCampaignStatusV1(FrozenModel):
    """Secret-free service-owned pointer used before looking for a new ticket."""

    schema_version: Literal["1"] = "1"
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    state: Literal["ticket_available", "request_pending", "active", "terminal"]
    launch_generation: int = Field(ge=1)
    launch_ticket_sha256: Sha256
    submission_key_sha256: Sha256 | None
    request_id: str | None
    request_sha256: Sha256 | None
    issue_number: int | None = Field(default=None, ge=1)
    last_github_checked_at: datetime | None
    updated_at: datetime
    status_sha256: Sha256

    @field_validator("last_github_checked_at", "updated_at")
    @classmethod
    def _utc_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogRequesterCampaignStatusV1":
        requested = self.state in {"request_pending", "active", "terminal"}
        if requested and (
            self.submission_key_sha256 is None or self.request_id is None
        ):
            raise ValueError("REQUESTER_CAMPAIGN_STATUS_INVALID")
        if not requested and (
            self.submission_key_sha256 is not None or self.request_id is not None
        ):
            raise ValueError("REQUESTER_CAMPAIGN_STATUS_INVALID")
        github_known = self.state in {"active", "terminal"}
        if github_known and (
            self.request_sha256 is None
            or self.issue_number is None
            or self.last_github_checked_at is None
        ):
            raise ValueError("REQUESTER_CAMPAIGN_STATUS_INVALID")
        if not github_known and (
            self.request_sha256 is not None
            or self.issue_number is not None
            or self.last_github_checked_at is not None
        ):
            raise ValueError("REQUESTER_CAMPAIGN_STATUS_INVALID")
        payload = self.model_copy(update={"status_sha256": "0" * 64})
        if canonical_sha256(payload) != self.status_sha256:
            raise ValueError("REQUESTER_CAMPAIGN_STATUS_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        campaign_key: str,
        state: Literal["ticket_available", "request_pending", "active", "terminal"],
        launch_generation: int,
        launch_ticket_sha256: str,
        updated_at: datetime,
        submission_key_sha256: str | None = None,
        request_id: str | None = None,
        request_sha256: str | None = None,
        issue_number: int | None = None,
        last_github_checked_at: datetime | None = None,
    ) -> "CatalogRequesterCampaignStatusV1":
        unsigned = cls.model_construct(
            schema_version="1",
            campaign_key=campaign_key,
            state=state,
            launch_generation=launch_generation,
            launch_ticket_sha256=launch_ticket_sha256,
            submission_key_sha256=submission_key_sha256,
            request_id=request_id,
            request_sha256=request_sha256,
            issue_number=issue_number,
            last_github_checked_at=(
                None
                if last_github_checked_at is None
                else _require_utc(last_github_checked_at)
            ),
            updated_at=_require_utc(updated_at),
            status_sha256="0" * 64,
        )
        return cls.model_validate(
            unsigned.model_copy(
                update={"status_sha256": canonical_sha256(unsigned)}
            ).model_dump(mode="json")
        )


class CatalogRequesterReconcileHintV1(FrozenModel):
    """Closed, secret-free request to refresh one exact active issue."""

    schema_version: Literal["1"] = "1"
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    launch_generation: int = Field(ge=1)
    launch_ticket_sha256: Sha256
    submission_key_sha256: Sha256
    request_id: str
    request_sha256: Sha256
    issue_number: int = Field(ge=1)
    status_sha256: Sha256
    last_github_checked_at: datetime
    hinted_at: datetime
    hint_sha256: Sha256

    @field_validator("last_github_checked_at", "hinted_at")
    @classmethod
    def _utc_hint_times(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogRequesterReconcileHintV1":
        if self.hinted_at < self.last_github_checked_at:
            raise ValueError("REQUESTER_RECONCILE_HINT_INVALID")
        payload = self.model_copy(update={"hint_sha256": "0" * 64})
        if canonical_sha256(payload) != self.hint_sha256:
            raise ValueError("REQUESTER_RECONCILE_HINT_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        status: CatalogRequesterCampaignStatusV1,
        hinted_at: datetime,
    ) -> "CatalogRequesterReconcileHintV1":
        if (
            status.state != "active"
            or status.submission_key_sha256 is None
            or status.request_id is None
            or status.request_sha256 is None
            or status.issue_number is None
            or status.last_github_checked_at is None
        ):
            raise ValueError("REQUESTER_RECONCILE_HINT_INVALID")
        unsigned = cls.model_construct(
            schema_version="1",
            campaign_key=status.campaign_key,
            launch_generation=status.launch_generation,
            launch_ticket_sha256=status.launch_ticket_sha256,
            submission_key_sha256=status.submission_key_sha256,
            request_id=status.request_id,
            request_sha256=status.request_sha256,
            issue_number=status.issue_number,
            status_sha256=status.status_sha256,
            last_github_checked_at=status.last_github_checked_at,
            hinted_at=_require_utc(hinted_at),
            hint_sha256="0" * 64,
        )
        return cls.model_validate(
            unsigned.model_copy(
                update={"hint_sha256": canonical_sha256(unsigned)}
            ).model_dump(mode="json")
        )


def build_catalog_intent_draft(
    *,
    ticket: CatalogLaunchTicketV1,
    registry_entry: CatalogCampaignEntryV1,
    campaign_manifest: CatalogCampaignDefinitionManifestV1,
    prompt_bytes: bytes,
) -> CatalogRunIntentDraftV1:
    """Build the only request shape accepted by the privileged broker."""

    if not isinstance(prompt_bytes, bytes):
        raise ValueError("CATALOG_REQUEST_PROMPT_INVALID")
    if ticket.campaign_key != registry_entry.campaign_key:
        raise ValueError("CATALOG_LAUNCH_TICKET_CAMPAIGN_MISMATCH")
    if campaign_manifest.campaign_key != registry_entry.campaign_key:
        raise ValueError("CATALOG_CAMPAIGN_DEFINITION_CAMPAIGN_MISMATCH")
    if ticket.campaign_definition_sha256 != campaign_manifest.campaign_definition_sha256:
        raise ValueError("CATALOG_LAUNCH_TICKET_DEFINITION_MISMATCH")
    if ticket.prompt_sha256 != hashlib.sha256(prompt_bytes).hexdigest():
        raise ValueError("CATALOG_LAUNCH_TICKET_PROMPT_MISMATCH")

    draft = CatalogRunIntentDraftV1(
        schema_version="1",
        request_id=ticket.request_id,
        campaign_key=ticket.campaign_key,
        launch_generation=ticket.launch_generation,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        previous_terminal_request_sha256=ticket.previous_terminal_request_sha256,
        campaign_definition_sha256=ticket.campaign_definition_sha256,
        prompt_sha256=ticket.prompt_sha256,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    return CatalogRunIntentDraftV1.model_validate_json(canonical_model_bytes(draft))


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _fixed_directory(path: Path) -> Path:
    if path.is_symlink() or _is_reparse_point(path):
        raise ValueError("REQUEST_BROKER_PATH_UNSAFE")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("REQUEST_BROKER_PATH_UNSAFE")
    return resolved


def _fixed_file(path: Path, *, maximum_bytes: int | None = None) -> Path:
    if path.is_symlink() or _is_reparse_point(path):
        raise ValueError("REQUESTER_INPUT_UNSAFE")
    resolved = path.resolve(strict=True)
    metadata = resolved.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or getattr(metadata, "st_nlink", 1) != 1:
        raise ValueError("REQUESTER_INPUT_UNSAFE")
    if maximum_bytes is not None and metadata.st_size > maximum_bytes:
        raise ValueError("REQUESTER_INPUT_TOO_LARGE")
    return resolved


def verify_production_bootstrap_receipt(
    *,
    broker_root: Path,
    config: CatalogRequesterConfigV1,
    production_seal: CatalogRequesterProductionSealV1,
) -> None:
    """Bind production use to the exact final global bootstrap receipt bytes."""

    try:
        root = _fixed_directory(broker_root)
        receipt_path = _fixed_file(
            root / config.broker.receipts / _FINAL_BOOTSTRAP_RECEIPT_NAME,
            maximum_bytes=1_048_576,
        )
        data = receipt_path.read_bytes()
        if len(data) < 2 or not data.endswith(b"\n"):
            raise ValueError("bootstrap receipt framing invalid")

        def reject_duplicate_keys(
            pairs: list[tuple[str, object]],
        ) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate bootstrap receipt key")
                result[key] = value
            return result

        def reject_nonfinite(value: str) -> object:
            raise ValueError(f"non-finite bootstrap receipt value: {value}")

        payload = json.loads(
            data[:-1].decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii") + b"\n"
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "1"
            or payload.get("result") != "READY"
            or (
                "final_result" in payload
                and payload.get("final_result") != "READY"
            )
            or data != canonical
            or hashlib.sha256(data).hexdigest()
            != production_seal.bootstrap_receipt_sha256
        ):
            raise ValueError("bootstrap receipt hash mismatch")
    except (OSError, ValueError) as exc:
        raise ValueError("REQUESTER_PRODUCTION_BOOTSTRAP_RECEIPT_INVALID") from exc


def _load_verified_production_seal(
    *,
    broker_root: Path,
    config: CatalogRequesterConfigV1,
) -> CatalogRequesterProductionSealV1:
    production_seal_path = broker_root.joinpath(
        *config.broker.production_seal.split("/")
    )
    try:
        seal = _canonical_model_file(
            production_seal_path,
            CatalogRequesterProductionSealV1,
        )
    except Exception:
        raise ValueError("REQUESTER_PRODUCTION_SEAL_UNPROVEN") from None
    if not isinstance(seal, CatalogRequesterProductionSealV1):
        raise ValueError("REQUESTER_PRODUCTION_SEAL_UNPROVEN")
    verify_production_bootstrap_receipt(
        broker_root=broker_root,
        config=config,
        production_seal=seal,
    )
    return seal


def _canonical_model_file(path: Path, model_type: type[FrozenModel]) -> FrozenModel:
    data = _fixed_file(path, maximum_bytes=_MAX_REQUEST_BYTES).read_bytes()
    if not data.endswith(b"\n"):
        raise ValueError("REQUESTER_SERVICE_FILE_NONCANONICAL")
    try:
        model = model_type.model_validate_json(data[:-1])
    except Exception as exc:
        raise ValueError("REQUESTER_SERVICE_FILE_INVALID") from exc
    if canonical_model_bytes(model) + b"\n" != data:
        raise ValueError("REQUESTER_SERVICE_FILE_NONCANONICAL")
    return model


def _select_registered_campaign(
    *,
    registry_path: Path,
    campaign_key: str,
) -> CatalogCampaignEntryV1:
    campaign_key = _validated_campaign_key(campaign_key)
    registry = load_catalog_campaign_registry(_fixed_file(registry_path))
    matches = tuple(
        entry
        for entry in registry.campaigns
        if entry.active and entry.campaign_key == campaign_key
    )
    if len(matches) != 1:
        raise ValueError("CATALOG_CAMPAIGN_UNRESOLVED")
    return matches[0]


def _strict_json_object(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    data = _fixed_file(path, maximum_bytes=maximum_bytes).read_bytes()

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        payload = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except Exception as exc:
        raise ValueError("REQUESTER_PUBLIC_INPUT_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("REQUESTER_PUBLIC_INPUT_INVALID")
    return payload


def _manifest_wrapper(
    path: Path,
    *,
    application_kind: Literal["client", "broker"],
) -> dict[str, object]:
    payload = _strict_json_object(path, maximum_bytes=16_777_216)
    data = path.read_bytes()
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    if data != canonical or set(payload) != {
        "schema_version",
        "manifest_format",
        "application_kind",
        "manifest_core",
        "embedded_manifest_sha256",
        "application_sha256",
    }:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    if (
        payload.get("schema_version") != "1"
        or payload.get("manifest_format") != "external"
        or payload.get("application_kind") != application_kind
    ):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    for field in ("embedded_manifest_sha256", "application_sha256"):
        value = payload.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    if not isinstance(payload.get("manifest_core"), dict):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    return payload


def _safe_manifest_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    pieces = value.split("/")
    if any(piece in {"", ".", ".."} for piece in pieces):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    if not all(
        all(character.isalnum() or character in "._-" for character in piece)
        for piece in pieces
    ):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    return value


def _validate_manifest_digest_fields(record: dict[str, object]) -> None:
    digest = record.get("sha256")
    size = record.get("size_bytes")
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or type(size) is not int
        or size < 0
    ):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")


def _validate_application_manifest_core(
    *,
    core: dict[str, object],
    application_kind: Literal["client", "broker"],
) -> tuple[tuple[str, str, str, int], ...]:
    if set(core) != _APPLICATION_CORE_KEYS:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    package = f"aurora_catalog_requester_{application_kind}"
    cli_module = (
        "catalog_requester_cli"
        if application_kind == "client"
        else "catalog_requester_broker_cli"
    )
    if core.get("entry_point") != f"{package}.{cli_module}:main":
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")

    source_files = core.get("source_files")
    expected_sources = _APPLICATION_SOURCES[application_kind]
    if not isinstance(source_files, list) or len(source_files) != len(
        expected_sources
    ):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    checked_sources: list[tuple[str, str, str, int]] = []
    for record, expected_path in zip(source_files, expected_sources, strict=True):
        if not isinstance(record, dict) or set(record) != {
            "path",
            "archive_member",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        archive_member = f"{package}/{Path(expected_path).name}"
        if (
            _safe_manifest_relative_path(record.get("path")) != expected_path
            or _safe_manifest_relative_path(record.get("archive_member"))
            != archive_member
        ):
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        _validate_manifest_digest_fields(record)
        checked_sources.append(
            (
                expected_path,
                archive_member,
                str(record["sha256"]),
                int(record["size_bytes"]),
            )
        )

    for field, expected_path in zip(
        ("dependency_input", "dependency_lock"),
        _APPLICATION_DEPENDENCIES[application_kind],
        strict=True,
    ):
        record = core.get(field)
        if not isinstance(record, dict) or set(record) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        if _safe_manifest_relative_path(record.get("path")) != expected_path:
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        _validate_manifest_digest_fields(record)
    return tuple(checked_sources)


def _verify_digest_record(
    *,
    record: object,
    data: bytes,
    require_path: bool = True,
) -> str:
    if not isinstance(record, dict):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    expected_keys = {"sha256", "size_bytes"} | ({"path"} if require_path else set())
    if frozenset(record) not in {
        frozenset(expected_keys),
        frozenset((*expected_keys, "order", "mode")),
    }:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    _validate_manifest_digest_fields(record)
    if "order" in record and (
        type(record.get("order")) is not int
        or int(record["order"]) < 0
        or record.get("mode") != "0644"
    ):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    path = _safe_manifest_relative_path(record.get("path")) if require_path else ""
    if (
        record.get("size_bytes") != len(data)
        or record.get("sha256") != hashlib.sha256(data).hexdigest()
    ):
        raise ValueError("REQUESTER_APPLICATION_HASH_MISMATCH")
    return path


def verify_installed_requester_application(
    *,
    broker_root: Path,
    application_kind: Literal["client", "broker"],
    application_path: Path,
) -> dict[str, object]:
    """Verify one immutable pyz, its embedded core, and every public input."""

    root = _fixed_directory(broker_root)
    expected_name = f"catalog-requester-{application_kind}.pyz"
    expected_application = root / "bin" / expected_name
    checked_application = _fixed_file(application_path, maximum_bytes=67_108_864)
    if checked_application != expected_application.resolve(strict=True):
        raise ValueError("REQUESTER_APPLICATION_PATH_INVALID")
    application_bytes = checked_application.read_bytes()
    manifest_path = root / "bin" / f"catalog-requester-{application_kind}.manifest.json"
    wrapper = _manifest_wrapper(manifest_path, application_kind=application_kind)
    if wrapper["application_sha256"] != hashlib.sha256(application_bytes).hexdigest():
        raise ValueError("REQUESTER_APPLICATION_HASH_MISMATCH")
    core = wrapper["manifest_core"]
    if not isinstance(core, dict):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    checked_sources = _validate_application_manifest_core(
        core=core,
        application_kind=application_kind,
    )
    expected_package = f"aurora_catalog_requester_{application_kind}"
    if (
        core.get("schema_version") != "1"
        or core.get("manifest_format") != "embedded"
        or core.get("application_kind") != application_kind
        or core.get("application_version") != "1"
        or core.get("python_requirement") != "CPython 3.14"
        or core.get("archive_package") != expected_package
        or core.get("embedded_manifest_sha256_location") != "external_manifest"
        or core.get("application_sha256_location") != "external_manifest"
        or not isinstance(core.get("protected_commit_sha"), str)
        or re.fullmatch(r"[0-9a-f]{40}", str(core.get("protected_commit_sha")))
        is None
    ):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    embedded_record = core.get("embedded_manifest_member")
    if not isinstance(embedded_record, dict) or set(embedded_record) != {
        "path",
        "order",
        "mode",
    }:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    embedded_path = _safe_manifest_relative_path(embedded_record.get("path"))
    if (
        embedded_path
        != f"{expected_package}/catalog_requester_app_manifest_v1.json"
        or embedded_record.get("mode") != "0644"
        or type(embedded_record.get("order")) is not int
        or int(embedded_record["order"]) < 0
    ):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    core_bytes = json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if wrapper["embedded_manifest_sha256"] != hashlib.sha256(core_bytes).hexdigest():
        raise ValueError("REQUESTER_APPLICATION_HASH_MISMATCH")

    archive_records = core.get("archive_members")
    if not isinstance(archive_records, list):
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    record_by_path: dict[str, dict[str, object]] = {}
    for record in archive_records:
        if not isinstance(record, dict) or set(record) != {
            "path",
            "order",
            "mode",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        path = _safe_manifest_relative_path(record.get("path"))
        if path in record_by_path or record.get("mode") != "0644":
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        _validate_manifest_digest_fields(record)
        if type(record.get("order")) is not int or int(record["order"]) < 0:
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        record_by_path[path] = record
    expected_source_members = tuple(item[1] for item in checked_sources)
    expected_generated_members = (
        "__main__.py",
        f"{expected_package}/__init__.py",
    )
    expected_archive_members = tuple(
        sorted((*expected_source_members, *expected_generated_members))
    )
    if tuple(record_by_path) != expected_archive_members:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    for _, archive_member, digest, size in checked_sources:
        archive_record = record_by_path[archive_member]
        if (
            archive_record.get("sha256") != digest
            or archive_record.get("size_bytes") != size
        ):
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    generated_members = core.get("generated_members")
    if generated_members != [
        record_by_path[path]
        for path in expected_archive_members
        if path in expected_generated_members
    ]:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    try:
        with zipfile.ZipFile(checked_application, mode="r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                names != sorted(names)
                or len(names) != len(set(names))
                or set(names) != {*record_by_path, embedded_path}
                or archive.comment
            ):
                raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
            for index, info in enumerate(infos):
                if (
                    info.is_dir()
                    or info.create_system != 3
                    or info.date_time != (1980, 1, 1, 0, 0, 0)
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.external_attr >> 16 != stat.S_IFREG | 0o644
                    or info.flag_bits != 0
                    or info.extra
                    or info.comment
                ):
                    raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
                data = archive.read(info)
                if info.filename == embedded_path:
                    if data != core_bytes or embedded_record.get("order") != index:
                        raise ValueError("REQUESTER_APPLICATION_HASH_MISMATCH")
                    continue
                record = record_by_path[info.filename]
                if record.get("order") != index:
                    raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
                _verify_digest_record(record=record, data=data)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("REQUESTER_APPLICATION_INVALID") from exc

    public_inputs = core.get("public_inputs")
    if not isinstance(public_inputs, list) or not public_inputs:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    registry = load_catalog_campaign_registry(
        _fixed_file(root / "config/catalog_campaign_registry_v1.json")
    )
    expected_public_paths = _APPLICATION_PUBLIC_INPUTS + tuple(
        sorted(
            entry.definition_manifest_path
            for entry in registry.campaigns
            if entry.active
        )
    )
    observed_public_paths = tuple(
        record.get("path") if isinstance(record, dict) else None
        for record in public_inputs
    )
    if observed_public_paths != expected_public_paths:
        raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
    seen_public: set[str] = set()
    for record in public_inputs:
        if not isinstance(record, dict) or set(record) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        relative = _safe_manifest_relative_path(record.get("path"))
        if relative in seen_public:
            raise ValueError("REQUESTER_APPLICATION_MANIFEST_INVALID")
        seen_public.add(relative)
        data = _fixed_file(root.joinpath(*relative.split("/")), maximum_bytes=16_777_216).read_bytes()
        _verify_digest_record(record=record, data=data)
    production_seal_path = root / "config/production-enabled-v1.seal.json"
    if production_seal_path.exists() or production_seal_path.is_symlink():
        seal = _canonical_model_file(
            production_seal_path,
            CatalogRequesterProductionSealV1,
        )
        if not isinstance(seal, CatalogRequesterProductionSealV1):
            raise ValueError("REQUESTER_PRODUCTION_SEAL_UNPROVEN")
        client_manifest = _manifest_wrapper(
            root / "bin/catalog-requester-client.manifest.json",
            application_kind="client",
        )
        broker_manifest = _manifest_wrapper(
            root / "bin/catalog-requester-broker.manifest.json",
            application_kind="broker",
        )
        if (
            client_manifest["application_sha256"]
            != seal.requester_client_application_sha256
            or broker_manifest["application_sha256"]
            != seal.requester_broker_application_sha256
        ):
            raise ValueError("REQUESTER_PRODUCTION_APPLICATION_MISMATCH")
        if core["protected_commit_sha"] != seal.protected_commit_sha:
            raise ValueError("REQUESTER_PRODUCTION_COMMIT_MISMATCH")
    return wrapper


def _read_existing_receipt(
    *,
    path: Path,
    draft: CatalogRunIntentDraftV1,
) -> CatalogRequesterReceiptV1 | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        data = _fixed_file(path, maximum_bytes=_MAX_REQUEST_BYTES).read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError("REQUESTER_RECEIPT_UNSAFE") from exc
    if not data.endswith(b"\n"):
        raise ValueError("REQUESTER_RECEIPT_INVALID")
    try:
        receipt = CatalogRequesterReceiptV1.model_validate_json(data[:-1])
    except Exception as exc:
        raise ValueError("REQUESTER_RECEIPT_INVALID") from exc
    if canonical_model_bytes(receipt) + b"\n" != data:
        raise ValueError("REQUESTER_RECEIPT_NONCANONICAL")
    if (
        receipt.submission_key_sha256 != draft.submission_key_sha256
        or receipt.request_id != draft.request_id
        or receipt.campaign_key != draft.campaign_key
        or receipt.launch_generation != draft.launch_generation
    ):
        raise ValueError("REQUESTER_RECEIPT_MISMATCH")
    return receipt


def submit_catalog_intent_to_spool(
    *,
    draft: CatalogRunIntentDraftV1,
    inbox: Path,
    receipts: Path,
    capacity: CatalogBrokerCapacityReceiptV1 | None,
    observed_at: datetime,
) -> CatalogRequesterReceiptV1:
    """Exclusive-create one canonical request without inspecting the inbox."""

    checked_draft = CatalogRunIntentDraftV1.model_validate_json(
        canonical_model_bytes(draft)
    )
    inbox_root = _fixed_directory(inbox)
    receipt_root = _fixed_directory(receipts)
    key = checked_draft.submission_key_sha256
    existing = _read_existing_receipt(
        path=receipt_root / f"{key}{_RECEIPT_SUFFIX}",
        draft=checked_draft,
    )
    if existing is not None:
        return existing
    if capacity is None or not capacity.available:
        raise ValueError("REQUEST_BROKER_CAPACITY_UNPROVEN")

    payload = canonical_model_bytes(checked_draft) + b"\n"
    if len(payload) > _MAX_REQUEST_BYTES:
        raise ValueError("REQUEST_BROKER_CAPACITY_EXCEEDED")
    if (
        capacity.pending_entry_count + 1 > capacity.maximum_pending_entries
        or capacity.pending_bytes + len(payload) > capacity.maximum_inbox_bytes
    ):
        raise ValueError("REQUEST_BROKER_CAPACITY_EXCEEDED")
    target = inbox_root / f"{key}{_REQUEST_SUFFIX}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError:
        pass
    else:
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("short spool write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    return CatalogRequesterReceiptV1.create(
        status="pending",
        reason_code="REQUEST_BROKER_PENDING",
        submission_key_sha256=key,
        request_id=checked_draft.request_id,
        campaign_key=checked_draft.campaign_key,
        launch_generation=checked_draft.launch_generation,
        observed_at=observed_at,
    )


def _load_fresh_broker_capacity(
    *,
    root: Path,
    config: CatalogRequesterConfigV1,
    observed_at: datetime,
) -> CatalogBrokerCapacityReceiptV1:
    capacity_path = root / config.broker.receipts / _CAPACITY_RECEIPT_NAME
    capacity = _canonical_model_file(
        capacity_path,
        CatalogBrokerCapacityReceiptV1,
    )
    if not isinstance(capacity, CatalogBrokerCapacityReceiptV1):
        raise ValueError("REQUEST_BROKER_CAPACITY_UNPROVEN")
    maximum_age_seconds = max(10, config.broker.poll_seconds * 5)
    age_seconds = (_require_utc(observed_at) - capacity.observed_at).total_seconds()
    if age_seconds < 0 or age_seconds > maximum_age_seconds:
        raise ValueError("REQUEST_BROKER_CAPACITY_UNPROVEN")
    if (
        capacity.maximum_pending_entries != config.broker.maximum_pending_entries
        or capacity.maximum_inbox_bytes != config.broker.maximum_inbox_bytes
    ):
        raise ValueError("REQUEST_BROKER_CAPACITY_UNPROVEN")
    return capacity


def create_catalog_reconcile_hint(
    *,
    broker_root: Path,
    config: CatalogRequesterConfigV1,
    status: CatalogRequesterCampaignStatusV1,
    observed_at: datetime,
) -> CatalogRequesterReconcileHintV1 | None:
    """Create at most one closed hint without listing or reading the inbox."""

    now = _require_utc(observed_at)
    if status.state != "active" or status.last_github_checked_at is None:
        return None
    age_seconds = (now - status.last_github_checked_at).total_seconds()
    if age_seconds < config.broker.terminal_reconcile_min_seconds:
        return None
    try:
        capacity = _load_fresh_broker_capacity(
            root=broker_root,
            config=config,
            observed_at=now,
        )
    except (OSError, ValueError):
        return None
    if not capacity.available:
        return None
    hint = CatalogRequesterReconcileHintV1.create(status=status, hinted_at=now)
    payload = canonical_model_bytes(hint) + b"\n"
    if (
        len(payload) > config.broker.maximum_hint_bytes
        or capacity.pending_entry_count + 1 > capacity.maximum_pending_entries
        or capacity.pending_bytes + len(payload) > capacity.maximum_inbox_bytes
    ):
        raise ValueError("REQUEST_BROKER_CAPACITY_EXCEEDED")
    inbox = _fixed_directory(broker_root / config.broker.inbox)
    target = inbox / f"{status.campaign_key}.reconcile-hint.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError:
        return hint
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short reconcile-hint write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return hint


def _read_campaign_status(
    *,
    path: Path,
    campaign_key: str,
) -> CatalogRequesterCampaignStatusV1:
    campaign_key = _validated_campaign_key(campaign_key)
    status = _canonical_model_file(path, CatalogRequesterCampaignStatusV1)
    if not isinstance(status, CatalogRequesterCampaignStatusV1) or (
        status.campaign_key != campaign_key
    ):
        raise ValueError("REQUESTER_CAMPAIGN_STATUS_INVALID")
    return status


def _wait_for_campaign_status_refresh(
    *,
    path: Path,
    campaign_key: str,
    prior_status_sha256: str,
    timeout_seconds: int,
    poll_seconds: int,
) -> CatalogRequesterCampaignStatusV1 | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_seconds)
        refreshed = _read_campaign_status(path=path, campaign_key=campaign_key)
        if refreshed.status_sha256 != prior_status_sha256:
            return refreshed
    return None


def _wait_for_request_receipt(
    *,
    path: Path,
    draft: CatalogRunIntentDraftV1,
    timeout_seconds: int,
    poll_seconds: int,
) -> CatalogRequesterReceiptV1 | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_seconds)
        receipt = _read_existing_receipt(path=path, draft=draft)
        if receipt is not None:
            return receipt
    return None


def _build_registered_catalog_draft(
    *,
    broker_root: Path,
    campaign_key: str,
    ticket_override: CatalogLaunchTicketV1 | None,
) -> tuple[CatalogRequesterConfigV1, CatalogRunIntentDraftV1]:
    """Resolve fixed public inputs into the one service-ticket-bound draft."""

    campaign_key = _validated_campaign_key(campaign_key)
    root = _fixed_directory(broker_root)
    config_path = root / "config/catalog_requester_v1.json"
    config = CatalogRequesterConfigV1.model_validate(
        _strict_json_object(config_path, maximum_bytes=32_768)
    )
    prompt_path = root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"
    prompt_bytes = _fixed_file(prompt_path, maximum_bytes=1_048_576).read_bytes()
    prompt_policy = _strict_json_object(
        root / "config/catalog_run_prompt_policy_v1.json",
        maximum_bytes=1_048_576,
    )
    prompt_sha256 = hashlib.sha256(prompt_bytes).hexdigest()
    if prompt_policy.get("active_prompt_sha256") != prompt_sha256:
        raise ValueError("CATALOG_PROMPT_HASH_MISMATCH")

    if campaign_key == config.bootstrap_qualification.campaign_key:
        production_seal = root.joinpath(*config.broker.production_seal.split("/"))
        bootstrap_seal = root / "config/bootstrap-qualified-v1.seal.json"
        if (
            production_seal.exists()
            or production_seal.is_symlink()
            or bootstrap_seal.exists()
            or bootstrap_seal.is_symlink()
        ):
            raise ValueError("REQUESTER_BOOTSTRAP_QUALIFICATION_SEALED")
        ticket_path = root / config.broker.launch_tickets / f"{campaign_key}.ticket.json"
        if ticket_override is None:
            ticket = _canonical_model_file(ticket_path, CatalogLaunchTicketV1)
            if not isinstance(ticket, CatalogLaunchTicketV1):
                raise ValueError("CATALOG_LAUNCH_TICKET_INVALID")
        else:
            ticket = CatalogLaunchTicketV1.model_validate_json(
                canonical_model_bytes(ticket_override)
            )
        expected_definition = canonical_sha256(config.bootstrap_qualification)
        if (
            ticket.campaign_key != campaign_key
            or ticket.prompt_sha256 != prompt_sha256
            or ticket.campaign_definition_sha256 != expected_definition
            or ticket.launch_generation != 1
            or ticket.previous_terminal_request_sha256 is not None
        ):
            raise ValueError("REQUESTER_BOOTSTRAP_TICKET_INVALID")
        draft = CatalogRunIntentDraftV1(
            schema_version="1",
            request_id=ticket.request_id,
            campaign_key=ticket.campaign_key,
            launch_generation=ticket.launch_generation,
            launch_ticket_sha256=ticket.launch_ticket_sha256,
            previous_terminal_request_sha256=None,
            campaign_definition_sha256=ticket.campaign_definition_sha256,
            prompt_sha256=ticket.prompt_sha256,
            authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
            free_resources_only=True,
            automatic_recovery=True,
            max_same_failure_count=3,
        )
        return config, CatalogRunIntentDraftV1.model_validate_json(
            canonical_model_bytes(draft)
        )

    _load_verified_production_seal(
        broker_root=root,
        config=config,
    )

    ticket_path = root / config.broker.launch_tickets / f"{campaign_key}.ticket.json"
    if ticket_override is None:
        ticket = _canonical_model_file(ticket_path, CatalogLaunchTicketV1)
        if not isinstance(ticket, CatalogLaunchTicketV1):
            raise ValueError("CATALOG_LAUNCH_TICKET_INVALID")
    else:
        ticket = CatalogLaunchTicketV1.model_validate_json(
            canonical_model_bytes(ticket_override)
        )

    registry_path = root / "config/catalog_campaign_registry_v1.json"
    entry = _select_registered_campaign(
        registry_path=registry_path,
        campaign_key=campaign_key,
    )
    manifest_path = root.joinpath(*entry.definition_manifest_path.split("/"))
    manifest = parse_catalog_campaign_definition_bytes(
        _fixed_file(manifest_path, maximum_bytes=8_388_608).read_bytes()
    )
    if manifest.campaign_key != entry.campaign_key:
        raise ValueError("CATALOG_CAMPAIGN_DEFINITION_CAMPAIGN_MISMATCH")
    if manifest.registry_entry_sha256 != registry_entry_sha256(entry):
        raise ValueError("CATALOG_CAMPAIGN_DEFINITION_REGISTRY_MISMATCH")
    draft = build_catalog_intent_draft(
        ticket=ticket,
        registry_entry=entry,
        campaign_manifest=manifest,
        prompt_bytes=prompt_bytes,
    )
    return config, draft


def build_registered_catalog_draft(
    *,
    broker_root: Path,
    campaign_key: str,
) -> tuple[CatalogRequesterConfigV1, CatalogRunIntentDraftV1]:
    """Client-safe wrapper that always reads the fixed service-owned ticket."""

    return _build_registered_catalog_draft(
        broker_root=broker_root,
        campaign_key=campaign_key,
        ticket_override=None,
    )


def submit_registered_catalog_campaign(
    *,
    broker_root: Path,
    campaign_key: str,
    observed_at: datetime,
    _wait_for_refresh: bool = True,
) -> CatalogRequesterReceiptV1:
    """Resolve fixed installed inputs and submit one ticket-bound campaign."""

    now = _require_utc(observed_at)
    campaign_key = _validated_campaign_key(campaign_key)
    root = _fixed_directory(broker_root)
    installed_config = CatalogRequesterConfigV1.model_validate(
        _strict_json_object(
            root / "config/catalog_requester_v1.json",
            maximum_bytes=32_768,
        )
    )
    if campaign_key != installed_config.bootstrap_qualification.campaign_key:
        _load_verified_production_seal(
            broker_root=root,
            config=installed_config,
        )
    status_path = (
        root
        / installed_config.broker.campaign_status
        / f"{campaign_key}.status.json"
    )
    if status_path.exists() or status_path.is_symlink():
        status = _read_campaign_status(
            path=status_path,
            campaign_key=campaign_key,
        )
        if status.state in {"request_pending", "active", "terminal"}:
            if status.submission_key_sha256 is None or status.request_id is None:
                raise ValueError("REQUESTER_CAMPAIGN_STATUS_INVALID")
            receipt_path = (
                root
                / installed_config.broker.receipts
                / f"{status.submission_key_sha256}.receipt.json"
            )
            if receipt_path.exists() or receipt_path.is_symlink():
                data = _fixed_file(
                    receipt_path,
                    maximum_bytes=_MAX_REQUEST_BYTES,
                ).read_bytes()
                if not data.endswith(b"\n"):
                    raise ValueError("REQUESTER_RECEIPT_INVALID")
                try:
                    receipt = CatalogRequesterReceiptV1.model_validate_json(data[:-1])
                except Exception as exc:
                    raise ValueError("REQUESTER_RECEIPT_INVALID") from exc
                if (
                    data != canonical_model_bytes(receipt) + b"\n"
                    or receipt.submission_key_sha256
                    != status.submission_key_sha256
                    or receipt.request_id != status.request_id
                    or receipt.campaign_key != status.campaign_key
                    or receipt.launch_generation != status.launch_generation
                ):
                    raise ValueError("REQUESTER_RECEIPT_MISMATCH")
                active_result = receipt
            else:
                active_result = CatalogRequesterReceiptV1.create(
                    status="pending",
                    reason_code="REQUEST_BROKER_PENDING",
                    submission_key_sha256=status.submission_key_sha256,
                    request_id=status.request_id,
                    campaign_key=status.campaign_key,
                    launch_generation=status.launch_generation,
                    observed_at=now,
                )
            if status.state != "active":
                return active_result
            hint = create_catalog_reconcile_hint(
                broker_root=root,
                config=installed_config,
                status=status,
                observed_at=now,
            )
            if hint is None or not _wait_for_refresh:
                return active_result
            refreshed = _wait_for_campaign_status_refresh(
                path=status_path,
                campaign_key=campaign_key,
                prior_status_sha256=status.status_sha256,
                timeout_seconds=installed_config.broker.client_receipt_timeout_seconds,
                poll_seconds=installed_config.broker.poll_seconds,
            )
            if refreshed is None or refreshed.state in {"request_pending", "active"}:
                return active_result
            if refreshed.state == "terminal":
                if (
                    refreshed.launch_generation != status.launch_generation
                    or refreshed.launch_ticket_sha256
                    != status.launch_ticket_sha256
                    or refreshed.submission_key_sha256
                    != status.submission_key_sha256
                    or refreshed.request_id != status.request_id
                    or refreshed.request_sha256 != status.request_sha256
                    or refreshed.issue_number != status.issue_number
                ):
                    raise ValueError("REQUESTER_CAMPAIGN_STATUS_INVALID")
                return active_result
            if refreshed.state != "ticket_available":
                raise ValueError("REQUESTER_CAMPAIGN_STATUS_INVALID")
    config, draft = build_registered_catalog_draft(
        broker_root=root,
        campaign_key=campaign_key,
    )
    if config != installed_config:
        raise ValueError("REQUESTER_CONFIG_CHANGED_DURING_READ")

    capacity = _load_fresh_broker_capacity(
        root=root,
        config=config,
        observed_at=now,
    )
    pending = submit_catalog_intent_to_spool(
        draft=draft,
        inbox=root / config.broker.inbox,
        receipts=root / config.broker.receipts,
        capacity=capacity,
        observed_at=now,
    )
    if pending.status != "pending" or not _wait_for_refresh:
        return pending
    receipt = _wait_for_request_receipt(
        path=(
            root
            / config.broker.receipts
            / f"{draft.submission_key_sha256}.receipt.json"
        ),
        draft=draft,
        timeout_seconds=config.broker.client_receipt_timeout_seconds,
        poll_seconds=config.broker.poll_seconds,
    )
    return pending if receipt is None else receipt


__all__ = [
    "CatalogBrokerCapacityReceiptV1",
    "CatalogRequesterConfigV1",
    "CatalogRequesterCampaignStatusV1",
    "CatalogRequesterReconcileHintV1",
    "CatalogRequesterProductionSealV1",
    "CatalogRequesterReceiptV1",
    "build_registered_catalog_draft",
    "build_catalog_intent_draft",
    "create_catalog_reconcile_hint",
    "submit_registered_catalog_campaign",
    "submit_catalog_intent_to_spool",
    "verify_installed_requester_application",
]
