"""Privileged, closed broker boundary for catalog-run issue creation.

This module is intentionally separate from the unprivileged client.  It signs
one already-validated draft, mints one short-lived GitHub App installation
token, permits only the request endpoints, and verifies the created issue.
"""

from __future__ import annotations

from base64 import b64encode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
from typing import Callable, Literal, Mapping, Protocol
from urllib.parse import urlsplit
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import Field, field_validator, model_validator
import requests

from .catalog_request_contract import (
    MAX_BODY_BYTES,
    MAX_TITLE_CHARS,
    FrozenModel,
    Sha256,
    CatalogLaunchTicketV1,
    CatalogRunIntentDraftV1,
    CatalogRunIntentV1,
    CatalogRunRequestV1,
    _attestation_payload,
    canonical_model_bytes,
    canonical_sha256,
)
from .catalog_requester import (
    CatalogBrokerCapacityReceiptV1,
    CatalogRequesterConfigV1,
    CatalogRequesterCampaignStatusV1,
    CatalogRequesterProductionSealV1,
    CatalogRequesterReconcileHintV1,
    CatalogRequesterReceiptV1,
    _build_registered_catalog_draft,
    build_registered_catalog_draft,
    verify_production_bootstrap_receipt,
)
from .catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from .catalog_campaign_registry import load_catalog_campaign_registry
from .catalog_run_request import parse_catalog_run_request


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("REQUESTER_TIME_NOT_UTC")
    return value.astimezone(UTC)


def _uuid7() -> uuid.UUID:
    native_uuid7 = getattr(uuid, "uuid7", None)
    if native_uuid7 is not None:
        return native_uuid7()

    timestamp_ms = time.time_ns() // 1_000_000
    if not 0 <= timestamp_ms < (1 << 48):
        raise ValueError("REQUESTER_UUID7_TIMESTAMP_OUT_OF_RANGE")
    random_bits = int.from_bytes(os.urandom(10), "big") & ((1 << 74) - 1)
    random_a = random_bits >> 62
    random_b = random_bits & ((1 << 62) - 1)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return uuid.UUID(int=value)


CatalogRequesterBrokerConfigV1 = CatalogRequesterConfigV1


class CatalogBrokerInboxEntryV1(FrozenModel):
    name: str = Field(pattern=r"^[A-Za-z0-9._-]{1,160}$")
    size_bytes: int = Field(ge=0)
    kind: Literal["request", "reconcile_hint", "unknown"]
    regular_file: bool
    single_link: bool
    reparse_point: bool


class CatalogBrokerInboxInventoryV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    stable: bool
    complete: bool
    available: bool
    reason_code: Literal[
        "REQUEST_BROKER_CAPACITY_AVAILABLE",
        "REQUEST_BROKER_CAPACITY_EXCEEDED",
        "REQUEST_BROKER_CAPACITY_UNPROVEN",
    ]
    pending_entry_count: int = Field(ge=0)
    pending_bytes: int = Field(ge=0)
    entries: tuple[CatalogBrokerInboxEntryV1, ...]


class CatalogBrokerTicketJournalV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    campaign_key: str
    launch_generation: int = Field(ge=1)
    ticket: CatalogLaunchTicketV1
    state: Literal["available", "claiming", "consumed", "active", "terminal"]
    submission_key_sha256: Sha256 | None
    request_sha256: Sha256 | None
    issue_number: int | None = Field(default=None, ge=1)
    created_at: datetime
    updated_at: datetime
    journal_sha256: Sha256

    @field_validator("created_at", "updated_at")
    @classmethod
    def _utc_times(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogBrokerTicketJournalV1":
        if (
            self.campaign_key != self.ticket.campaign_key
            or self.launch_generation != self.ticket.launch_generation
            or self.updated_at < self.created_at
        ):
            raise ValueError("REQUESTER_TICKET_JOURNAL_INVALID")
        claimed = self.state in {"claiming", "consumed", "active", "terminal"}
        if claimed != (self.submission_key_sha256 is not None):
            raise ValueError("REQUESTER_TICKET_JOURNAL_INVALID")
        active = self.state in {"active", "terminal"}
        if active and (
            self.request_sha256 is None or self.issue_number is None
        ):
            raise ValueError("REQUESTER_TICKET_JOURNAL_INVALID")
        if not active and (
            self.request_sha256 is not None or self.issue_number is not None
        ):
            raise ValueError("REQUESTER_TICKET_JOURNAL_INVALID")
        payload = self.model_copy(update={"journal_sha256": "0" * 64})
        if canonical_sha256(payload) != self.journal_sha256:
            raise ValueError("REQUESTER_TICKET_JOURNAL_HASH_INVALID")
        return self


class CatalogBrokerBootstrapSealV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    qualification_permanently_sealed: Literal[True]
    qualification_submission_key_sha256: Sha256
    qualification_request_sha256: Sha256
    qualification_issue_number: int = Field(ge=1)
    controller_receipt_sha256: Sha256
    sealed_at: datetime
    bootstrap_seal_sha256: Sha256

    @field_validator("sealed_at")
    @classmethod
    def _utc_sealed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _hash(self) -> "CatalogBrokerBootstrapSealV1":
        payload = self.model_copy(update={"bootstrap_seal_sha256": "0" * 64})
        if canonical_sha256(payload) != self.bootstrap_seal_sha256:
            raise ValueError("REQUESTER_BOOTSTRAP_SEAL_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        qualification_submission_key_sha256: str,
        qualification_request_sha256: str,
        qualification_issue_number: int,
        controller_receipt_sha256: str,
        sealed_at: datetime,
    ) -> "CatalogBrokerBootstrapSealV1":
        unsigned = cls.model_construct(
            schema_version="1",
            qualification_permanently_sealed=True,
            qualification_submission_key_sha256=(
                qualification_submission_key_sha256
            ),
            qualification_request_sha256=qualification_request_sha256,
            qualification_issue_number=qualification_issue_number,
            controller_receipt_sha256=controller_receipt_sha256,
            sealed_at=_utc(sealed_at),
            bootstrap_seal_sha256="0" * 64,
        )
        return cls.model_validate(
            unsigned.model_copy(
                update={"bootstrap_seal_sha256": canonical_sha256(unsigned)}
            ).model_dump(mode="json")
        )


class CatalogBrokerTerminalPollStateV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    campaign_key: str
    launch_generation: int = Field(ge=1)
    submission_key_sha256: Sha256
    request_sha256: Sha256
    issue_number: int = Field(ge=1)
    last_github_checked_at: datetime
    next_github_check_at: datetime
    backoff_seconds: int = Field(ge=1, le=900)
    etag: str | None = Field(default=None, min_length=1, max_length=256)
    last_hint_sha256: Sha256 | None = None
    poll_state_sha256: Sha256

    @field_validator("last_github_checked_at", "next_github_check_at")
    @classmethod
    def _utc_poll_times(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("etag")
    @classmethod
    def _safe_etag(cls, value: str | None) -> str | None:
        if value is not None and ("\r" in value or "\n" in value):
            raise ValueError("REQUESTER_TERMINAL_ETAG_INVALID")
        return value

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogBrokerTerminalPollStateV1":
        if self.next_github_check_at < self.last_github_checked_at:
            raise ValueError("REQUESTER_TERMINAL_POLL_STATE_INVALID")
        payload = self.model_copy(update={"poll_state_sha256": "0" * 64})
        if canonical_sha256(payload) != self.poll_state_sha256:
            raise ValueError("REQUESTER_TERMINAL_POLL_STATE_HASH_INVALID")
        return self


class CatalogBrokerTerminalRateWindowV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    reserved_at: tuple[datetime, ...]
    rate_window_sha256: Sha256

    @field_validator("reserved_at")
    @classmethod
    def _utc_rate_times(cls, value: tuple[datetime, ...]) -> tuple[datetime, ...]:
        checked = tuple(_utc(item) for item in value)
        if tuple(sorted(checked)) != checked or len(checked) > 30:
            raise ValueError("REQUESTER_TERMINAL_RATE_STATE_INVALID")
        return checked

    @model_validator(mode="after")
    def _hash(self) -> "CatalogBrokerTerminalRateWindowV1":
        payload = self.model_copy(update={"rate_window_sha256": "0" * 64})
        if canonical_sha256(payload) != self.rate_window_sha256:
            raise ValueError("REQUESTER_TERMINAL_RATE_STATE_HASH_INVALID")
        return self


class CatalogBrokerRejectedEntryV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    source_name_sha256: Sha256
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    observed_at: datetime
    rejection_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _utc_rejected_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _hash(self) -> "CatalogBrokerRejectedEntryV1":
        payload = self.model_copy(update={"rejection_sha256": "0" * 64})
        if canonical_sha256(payload) != self.rejection_sha256:
            raise ValueError("REQUESTER_REJECTION_HASH_INVALID")
        return self


class CatalogBrokerSelfAuditReceiptV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    status: Literal["qualification_only", "production_sealed"]
    repository: str
    service_identity: Literal["AURORARequester"]
    requester_actor: str
    app_id: int = Field(ge=1)
    installation_id: int = Field(ge=1)
    requester_public_key_sha256: Sha256
    broker_application_sha256: Sha256
    acl_baseline_sha256: Sha256
    production_seal_present: bool
    observed_at: datetime
    self_audit_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _utc_self_audit_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogBrokerSelfAuditReceiptV1":
        if (self.status == "production_sealed") != self.production_seal_present:
            raise ValueError("REQUESTER_BROKER_SELF_AUDIT_INVALID")
        payload = self.model_copy(update={"self_audit_sha256": "0" * 64})
        if canonical_sha256(payload) != self.self_audit_sha256:
            raise ValueError("REQUESTER_BROKER_SELF_AUDIT_HASH_INVALID")
        return self


def _ticket_journal(
    *,
    ticket: CatalogLaunchTicketV1,
    state: Literal["available", "claiming", "consumed", "active", "terminal"],
    submission_key_sha256: str | None,
    request_sha256: str | None,
    issue_number: int | None,
    created_at: datetime,
    updated_at: datetime,
) -> CatalogBrokerTicketJournalV1:
    unsigned = CatalogBrokerTicketJournalV1.model_construct(
        schema_version="1",
        campaign_key=ticket.campaign_key,
        launch_generation=ticket.launch_generation,
        ticket=ticket,
        state=state,
        submission_key_sha256=submission_key_sha256,
        request_sha256=request_sha256,
        issue_number=issue_number,
        created_at=_utc(created_at),
        updated_at=_utc(updated_at),
        journal_sha256="0" * 64,
    )
    return CatalogBrokerTicketJournalV1.model_validate(
        unsigned.model_copy(
            update={"journal_sha256": canonical_sha256(unsigned)}
        ).model_dump(mode="json")
    )


def _terminal_poll_state(
    *,
    campaign_key: str,
    launch_generation: int,
    submission_key_sha256: str,
    request_sha256: str,
    issue_number: int,
    last_github_checked_at: datetime,
    next_github_check_at: datetime,
    backoff_seconds: int,
    etag: str | None,
    last_hint_sha256: str | None,
) -> CatalogBrokerTerminalPollStateV1:
    unsigned = CatalogBrokerTerminalPollStateV1.model_construct(
        schema_version="1",
        campaign_key=campaign_key,
        launch_generation=launch_generation,
        submission_key_sha256=submission_key_sha256,
        request_sha256=request_sha256,
        issue_number=issue_number,
        last_github_checked_at=_utc(last_github_checked_at),
        next_github_check_at=_utc(next_github_check_at),
        backoff_seconds=backoff_seconds,
        etag=etag,
        last_hint_sha256=last_hint_sha256,
        poll_state_sha256="0" * 64,
    )
    return CatalogBrokerTerminalPollStateV1.model_validate(
        unsigned.model_copy(
            update={"poll_state_sha256": canonical_sha256(unsigned)}
        ).model_dump(mode="json")
    )


def _terminal_rate_window(
    reserved_at: tuple[datetime, ...],
) -> CatalogBrokerTerminalRateWindowV1:
    unsigned = CatalogBrokerTerminalRateWindowV1.model_construct(
        schema_version="1",
        reserved_at=tuple(_utc(item) for item in reserved_at),
        rate_window_sha256="0" * 64,
    )
    return CatalogBrokerTerminalRateWindowV1.model_validate(
        unsigned.model_copy(
            update={"rate_window_sha256": canonical_sha256(unsigned)}
        ).model_dump(mode="json")
    )


def _rejected_entry(
    *,
    source_name: str,
    reason_code: str,
    observed_at: datetime,
) -> CatalogBrokerRejectedEntryV1:
    unsigned = CatalogBrokerRejectedEntryV1.model_construct(
        schema_version="1",
        source_name_sha256=hashlib.sha256(
            source_name.encode("utf-8", errors="surrogatepass")
        ).hexdigest(),
        reason_code=reason_code,
        observed_at=_utc(observed_at),
        rejection_sha256="0" * 64,
    )
    return CatalogBrokerRejectedEntryV1.model_validate(
        unsigned.model_copy(
            update={"rejection_sha256": canonical_sha256(unsigned)}
        ).model_dump(mode="json")
    )


def _is_reparse_stat(value: os.stat_result) -> bool:
    attributes = getattr(value, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _broker_directory(root: Path, relative: str) -> Path:
    candidate = root / relative
    if candidate.is_symlink():
        raise ValueError("REQUESTER_BROKER_ACL_OR_PATH_INVALID")
    resolved = candidate.resolve(strict=True)
    root_resolved = root.resolve(strict=True)
    metadata = resolved.stat(follow_symlinks=False)
    if (
        not resolved.is_relative_to(root_resolved)
        or not stat.S_ISDIR(metadata.st_mode)
        or _is_reparse_stat(metadata)
    ):
        raise ValueError("REQUESTER_BROKER_ACL_OR_PATH_INVALID")
    return resolved


def _inventory_snapshot(
    directory: Path,
    *,
    maximum_entries: int,
    maximum_bytes: int,
    maximum_request_bytes: int,
    maximum_hint_bytes: int,
) -> tuple[tuple[CatalogBrokerInboxEntryV1, ...], int, bool, bool]:
    records: list[CatalogBrokerInboxEntryV1] = []
    pending_bytes = 0
    complete = True
    safe = True
    with os.scandir(directory) as iterator:
        for item in iterator:
            try:
                # Python 3.14 on Windows currently reports st_nlink=0 from
                # DirEntry.stat() even when os.lstat() reports the real count.
                metadata = os.lstat(item.path)
            except OSError:
                safe = False
                complete = False
                break
            name = item.name
            regular = stat.S_ISREG(metadata.st_mode)
            reparse = item.is_symlink() or _is_reparse_stat(metadata)
            single_link = getattr(metadata, "st_nlink", 1) == 1
            if name.endswith(".request.json"):
                kind: Literal["request", "reconcile_hint", "unknown"] = "request"
                size_safe = metadata.st_size <= maximum_request_bytes
            elif name.endswith(".reconcile-hint.json"):
                kind = "reconcile_hint"
                size_safe = metadata.st_size <= maximum_hint_bytes
            else:
                kind = "unknown"
                size_safe = False
            name_safe = (
                0 < len(name) <= 160
                and all(character.isalnum() or character in "._-" for character in name)
            )
            if not (regular and single_link and not reparse and size_safe and name_safe):
                safe = False
            records.append(
                CatalogBrokerInboxEntryV1(
                    name=name if name_safe else "unsafe-entry",
                    size_bytes=max(0, metadata.st_size),
                    kind=kind,
                    regular_file=regular,
                    single_link=single_link,
                    reparse_point=reparse,
                )
            )
            pending_bytes += max(0, metadata.st_size)
            if len(records) > maximum_entries or pending_bytes > maximum_bytes:
                complete = False
                break
    return tuple(sorted(records, key=lambda value: value.name)), pending_bytes, complete, safe


def inventory_catalog_broker_inbox(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
) -> CatalogBrokerInboxInventoryV1:
    """Take two bounded metadata-only snapshots before trusting capacity."""

    root = broker_root.resolve(strict=True)
    inbox = _broker_directory(root, config.broker.inbox)
    kwargs = {
        "maximum_entries": config.broker.maximum_pending_entries,
        "maximum_bytes": config.broker.maximum_inbox_bytes,
        "maximum_request_bytes": config.broker.maximum_request_bytes,
        "maximum_hint_bytes": config.broker.maximum_hint_bytes,
    }
    first = _inventory_snapshot(inbox, **kwargs)
    second = _inventory_snapshot(inbox, **kwargs)
    stable = first == second
    entries, pending_bytes, complete, safe = second
    count = len(entries)
    exceeded = (
        count > config.broker.maximum_pending_entries
        or pending_bytes > config.broker.maximum_inbox_bytes
    )
    within_capacity = (
        count < config.broker.maximum_pending_entries
        and pending_bytes < config.broker.maximum_inbox_bytes
    )
    if exceeded:
        reason = "REQUEST_BROKER_CAPACITY_EXCEEDED"
        available = False
    elif not stable or not complete or not safe:
        reason = "REQUEST_BROKER_CAPACITY_UNPROVEN"
        available = False
    elif not within_capacity:
        reason = "REQUEST_BROKER_CAPACITY_EXCEEDED"
        available = False
    else:
        reason = "REQUEST_BROKER_CAPACITY_AVAILABLE"
        available = True
    return CatalogBrokerInboxInventoryV1(
        stable=stable,
        complete=complete,
        available=available,
        reason_code=reason,
        pending_entry_count=count,
        pending_bytes=pending_bytes,
        entries=entries,
    )


def quarantine_one_invalid_catalog_broker_entry(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
) -> Path | None:
    """Move one unsafe/unknown bounded entry aside without reading or deleting it."""

    root = broker_root.resolve(strict=True)
    inbox = _broker_directory(root, config.broker.inbox)
    processing = _broker_directory(root, config.broker.processing)
    candidates: list[tuple[str, str]] = []
    inspected = 0
    with os.scandir(inbox) as iterator:
        for item in iterator:
            inspected += 1
            if inspected > config.broker.maximum_pending_entries:
                break
            try:
                metadata = os.lstat(item.path)
            except OSError:
                continue
            name = item.name
            name_safe = (
                0 < len(name) <= 160
                and all(character.isalnum() or character in "._-" for character in name)
            )
            regular = stat.S_ISREG(metadata.st_mode)
            reparse = item.is_symlink() or _is_reparse_stat(metadata)
            single_link = getattr(metadata, "st_nlink", 1) == 1
            if name.endswith(".request.json"):
                known_size = metadata.st_size <= config.broker.maximum_request_bytes
                known_kind = True
            elif name.endswith(".reconcile-hint.json"):
                known_size = metadata.st_size <= config.broker.maximum_hint_bytes
                known_kind = True
            else:
                known_size = False
                known_kind = False
            if not (
                name_safe
                and regular
                and not reparse
                and single_link
                and known_kind
                and known_size
            ):
                candidates.append((name, item.path))
    if not candidates:
        return None
    name, source_text = sorted(candidates, key=lambda value: value[0])[0]
    source = Path(source_text)
    quarantine_name = (
        "quarantine-"
        + hashlib.sha256(name.encode("utf-8", errors="surrogatepass")).hexdigest()
        + ".entry"
    )
    destination = processing / quarantine_name
    if destination.exists() or destination.is_symlink():
        destination = processing / (
            quarantine_name.removesuffix(".entry")
            + f"-{uuid.uuid4().hex}.entry"
        )
    os.rename(source, destination)
    return destination


def _exclusive_write(path: Path, data: bytes) -> bool:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError("short broker write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def _replace_service_state(source: Path, destination: Path) -> None:
    for attempt in range(40):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in {5, 32} or attempt == 39:
                raise
            time.sleep(0.05)


def _atomic_replace(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".service-tmp")
    if temporary.exists() or temporary.is_symlink():
        metadata = os.lstat(temporary)
        if (
            temporary.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or _is_reparse_stat(metadata)
            or getattr(metadata, "st_nlink", 1) != 1
        ):
            raise ValueError("REQUESTER_BROKER_TEMPORARY_EXISTS")
        if metadata.st_size == len(data) and temporary.read_bytes() == data:
            _replace_service_state(temporary, path)
            return
        abandoned = path.with_name(
            path.name + f".abandoned-{uuid.uuid4().hex}.service-state"
        )
        if abandoned.exists() or abandoned.is_symlink():
            raise ValueError("REQUESTER_BROKER_TEMPORARY_EXISTS")
        os.rename(temporary, abandoned)
    if not _exclusive_write(temporary, data):
        raise ValueError("REQUESTER_BROKER_TEMPORARY_EXISTS")
    _replace_service_state(temporary, path)


def publish_catalog_broker_capacity(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    observed_at: datetime,
) -> CatalogBrokerCapacityReceiptV1:
    inventory = inventory_catalog_broker_inbox(
        broker_root=broker_root,
        config=config,
    )
    receipt = CatalogBrokerCapacityReceiptV1.create(
        observed_at=observed_at,
        available=inventory.available,
        reason_code=inventory.reason_code,
        pending_entry_count=inventory.pending_entry_count,
        pending_bytes=inventory.pending_bytes,
        maximum_pending_entries=config.broker.maximum_pending_entries,
        maximum_inbox_bytes=config.broker.maximum_inbox_bytes,
    )
    receipts = _broker_directory(
        broker_root.resolve(strict=True), config.broker.receipts
    )
    _atomic_replace(
        receipts / "broker-capacity-v1.receipt.json",
        canonical_model_bytes(receipt) + b"\n",
    )
    return receipt


def publish_catalog_broker_self_audit(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    client: CatalogBrokerGithubClient,
    broker_application_sha256: str,
    acl_baseline_sha256: str,
    observed_at: datetime,
) -> CatalogBrokerSelfAuditReceiptV1:
    production_seal = broker_root.joinpath(
        *config.broker.production_seal.split("/")
    )
    present = production_seal.exists() or production_seal.is_symlink()
    if present:
        checked_production_seal = _read_canonical_model(
            production_seal,
            CatalogRequesterProductionSealV1,
            maximum_bytes=16_384,
        )
        bootstrap_seal = _read_canonical_model(
            broker_root / "config/bootstrap-qualified-v1.seal.json",
            CatalogBrokerBootstrapSealV1,
            maximum_bytes=16_384,
        )
        if (
            not isinstance(checked_production_seal, CatalogRequesterProductionSealV1)
            or not isinstance(bootstrap_seal, CatalogBrokerBootstrapSealV1)
            or checked_production_seal.requester_broker_application_sha256
            != broker_application_sha256
            or checked_production_seal.sealed_at < bootstrap_seal.sealed_at
        ):
            raise ValueError("REQUESTER_PRODUCTION_SEAL_UNPROVEN")
        _verify_bootstrap_seal_context(
            broker_root=broker_root,
            config=config,
            seal=bootstrap_seal,
        )
        verify_production_bootstrap_receipt(
            broker_root=broker_root,
            config=config,
            production_seal=checked_production_seal,
        )
    unsigned = CatalogBrokerSelfAuditReceiptV1.model_construct(
        schema_version="1",
        status="production_sealed" if present else "qualification_only",
        repository=config.repository,
        service_identity="AURORARequester",
        requester_actor=client.expected_actor,
        app_id=client.app_id,
        installation_id=client.installation_id,
        requester_public_key_sha256=client.requester_public_key_sha256,
        broker_application_sha256=broker_application_sha256,
        acl_baseline_sha256=acl_baseline_sha256,
        production_seal_present=present,
        observed_at=_utc(observed_at),
        self_audit_sha256="0" * 64,
    )
    receipt = CatalogBrokerSelfAuditReceiptV1.model_validate(
        unsigned.model_copy(
            update={"self_audit_sha256": canonical_sha256(unsigned)}
        ).model_dump(mode="json")
    )
    receipts = _broker_directory(
        broker_root.resolve(strict=True), config.broker.receipts
    )
    _atomic_replace(
        receipts / "broker-self-audit-v1.receipt.json",
        canonical_model_bytes(receipt) + b"\n",
    )
    return receipt


def _read_canonical_model(
    path: Path,
    model_type: type[FrozenModel],
    *,
    maximum_bytes: int,
) -> FrozenModel:
    if path.is_symlink():
        raise ValueError("REQUESTER_SERVICE_STATE_INVALID")
    metadata = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or _is_reparse_stat(metadata)
        or getattr(metadata, "st_nlink", 1) != 1
        or metadata.st_size > maximum_bytes
    ):
        raise ValueError("REQUESTER_SERVICE_STATE_INVALID")
    data = path.read_bytes()
    if not data.endswith(b"\n"):
        raise ValueError("REQUESTER_SERVICE_STATE_INVALID")
    try:
        model = model_type.model_validate_json(data[:-1])
    except Exception as exc:
        raise ValueError("REQUESTER_SERVICE_STATE_INVALID") from exc
    if data != canonical_model_bytes(model) + b"\n":
        raise ValueError("REQUESTER_SERVICE_STATE_INVALID")
    return model


def _load_ticket_journal(path: Path) -> CatalogBrokerTicketJournalV1:
    journal = _read_canonical_model(
        path,
        CatalogBrokerTicketJournalV1,
        maximum_bytes=16_384,
    )
    if not isinstance(journal, CatalogBrokerTicketJournalV1):
        raise ValueError("REQUESTER_TICKET_JOURNAL_INVALID")
    return journal


def _verify_bootstrap_seal_context_unchecked(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    seal: CatalogBrokerBootstrapSealV1,
) -> None:
    """Bind the administrator seal to the one real terminal qualification."""

    root = broker_root.resolve(strict=True)
    campaign_key = config.bootstrap_qualification.campaign_key
    statuses = _broker_directory(root, config.broker.campaign_status)
    processing = _broker_directory(root, config.broker.processing)
    receipts = _broker_directory(root, config.broker.receipts)
    journal = _load_ticket_journal(statuses / f"{campaign_key}.journal.json")
    archived = _load_ticket_journal(
        statuses / f"{campaign_key}.generation-0000000001.terminal.json"
    )
    receipt = _read_canonical_model(
        receipts / f"{seal.qualification_submission_key_sha256}.receipt.json",
        CatalogRequesterReceiptV1,
        maximum_bytes=config.broker.maximum_request_bytes,
    )
    signed = _read_canonical_model(
        processing / f"{seal.qualification_submission_key_sha256}.signed.json",
        CatalogBrokerProcessingRecordV1,
        maximum_bytes=64_000,
    )
    consumed_ticket = _read_canonical_model(
        processing / f"{seal.qualification_submission_key_sha256}.ticket.json",
        CatalogLaunchTicketV1,
        maximum_bytes=config.broker.maximum_request_bytes,
    )
    status = _read_canonical_model(
        statuses / f"{campaign_key}.status.json",
        CatalogRequesterCampaignStatusV1,
        maximum_bytes=config.broker.maximum_request_bytes,
    )
    if (
        not isinstance(receipt, CatalogRequesterReceiptV1)
        or not isinstance(signed, CatalogBrokerProcessingRecordV1)
        or not isinstance(consumed_ticket, CatalogLaunchTicketV1)
        or not isinstance(status, CatalogRequesterCampaignStatusV1)
        or journal != archived
        or journal.state != "terminal"
        or journal.campaign_key != campaign_key
        or journal.launch_generation != 1
        or journal.ticket.previous_terminal_request_sha256 is not None
        or journal.ticket != consumed_ticket
        or journal.submission_key_sha256
        != seal.qualification_submission_key_sha256
        or journal.request_sha256 != seal.qualification_request_sha256
        or journal.issue_number != seal.qualification_issue_number
        or receipt.status not in {"submitted", "existing"}
        or receipt.submission_key_sha256 != journal.submission_key_sha256
        or receipt.request_id != journal.ticket.request_id
        or receipt.campaign_key != campaign_key
        or receipt.launch_generation != 1
        or receipt.request_sha256 != journal.request_sha256
        or receipt.issue_number != journal.issue_number
        or signed.request.intent.submission_key_sha256
        != journal.submission_key_sha256
        or signed.request_sha256 != journal.request_sha256
        or signed.request.launch_ticket_sha256
        != journal.ticket.launch_ticket_sha256
        or status.state != "terminal"
        or status.campaign_key != campaign_key
        or status.launch_generation != 1
        or status.submission_key_sha256 != journal.submission_key_sha256
        or status.request_sha256 != journal.request_sha256
        or status.issue_number != journal.issue_number
        or seal.sealed_at < journal.updated_at
    ):
        raise ValueError("REQUESTER_BOOTSTRAP_SEAL_CONTEXT_INVALID")


def _verify_bootstrap_seal_context(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    seal: CatalogBrokerBootstrapSealV1,
) -> None:
    try:
        _verify_bootstrap_seal_context_unchecked(
            broker_root=broker_root,
            config=config,
            seal=seal,
        )
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) == (
            "REQUESTER_BOOTSTRAP_SEAL_CONTEXT_INVALID"
        ):
            raise
        raise ValueError("REQUESTER_BOOTSTRAP_SEAL_CONTEXT_INVALID") from exc


def _transition_ticket_journal(
    journal: CatalogBrokerTicketJournalV1,
    *,
    state: Literal["available", "claiming", "consumed", "active", "terminal"],
    updated_at: datetime,
    submission_key_sha256: str | None = None,
    request_sha256: str | None = None,
    issue_number: int | None = None,
) -> CatalogBrokerTicketJournalV1:
    return _ticket_journal(
        ticket=journal.ticket,
        state=state,
        submission_key_sha256=submission_key_sha256,
        request_sha256=request_sha256,
        issue_number=issue_number,
        created_at=journal.created_at,
        updated_at=updated_at,
    )


def _write_campaign_status(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    journal: CatalogBrokerTicketJournalV1,
    last_github_checked_at: datetime | None = None,
    status_updated_at: datetime | None = None,
) -> CatalogRequesterCampaignStatusV1:
    if journal.state == "available":
        public_state: Literal[
            "ticket_available", "request_pending", "active", "terminal"
        ] = "ticket_available"
    elif journal.state in {"claiming", "consumed"}:
        public_state = "request_pending"
    elif journal.state == "active":
        public_state = "active"
    else:
        public_state = "terminal"
    status = CatalogRequesterCampaignStatusV1.create(
        campaign_key=journal.campaign_key,
        state=public_state,
        launch_generation=journal.launch_generation,
        launch_ticket_sha256=journal.ticket.launch_ticket_sha256,
        submission_key_sha256=journal.submission_key_sha256,
        request_id=(
            journal.ticket.request_id
            if journal.submission_key_sha256 is not None
            else None
        ),
        request_sha256=journal.request_sha256,
        issue_number=journal.issue_number,
        last_github_checked_at=(
            (
                journal.updated_at
                if last_github_checked_at is None
                else _utc(last_github_checked_at)
            )
            if journal.state in {"active", "terminal"}
            else None
        ),
        updated_at=(
            journal.updated_at
            if status_updated_at is None
            else _utc(status_updated_at)
        ),
    )
    statuses = _broker_directory(
        broker_root.resolve(strict=True), config.broker.campaign_status
    )
    _atomic_replace(
        statuses / f"{journal.campaign_key}.status.json",
        canonical_model_bytes(status) + b"\n",
    )
    return status


def _ensure_one_launch_ticket(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    candidate: CatalogLaunchTicketV1,
    observed_at: datetime,
) -> CatalogLaunchTicketV1 | None:
    root = broker_root.resolve(strict=True)
    statuses = _broker_directory(root, config.broker.campaign_status)
    tickets = _broker_directory(root, config.broker.launch_tickets)
    processing = _broker_directory(root, config.broker.processing)
    journal_path = statuses / f"{candidate.campaign_key}.journal.json"
    ticket_path = tickets / f"{candidate.campaign_key}.ticket.json"
    if journal_path.exists():
        journal = _load_ticket_journal(journal_path)
        if (
            journal.campaign_key != candidate.campaign_key
            or journal.ticket.campaign_definition_sha256
            != candidate.campaign_definition_sha256
            or journal.ticket.prompt_sha256 != candidate.prompt_sha256
        ):
            raise ValueError("REQUESTER_TICKET_JOURNAL_CONTEXT_MISMATCH")
        if journal.state == "available":
            _retire_obsolete_terminal_poll_state(
                broker_root=root,
                config=config,
                successor_journal=journal,
            )
            if ticket_path.exists():
                ticket = _read_canonical_model(
                    ticket_path,
                    CatalogLaunchTicketV1,
                    maximum_bytes=config.broker.maximum_request_bytes,
                )
                if ticket != journal.ticket:
                    raise ValueError("REQUESTER_LAUNCH_TICKET_CONFLICT")
            elif ticket_path.is_symlink():
                raise ValueError("REQUESTER_LAUNCH_TICKET_CONFLICT")
            else:
                _atomic_replace(
                    ticket_path,
                    canonical_model_bytes(journal.ticket) + b"\n",
                )
            _write_campaign_status(
                broker_root=root,
                config=config,
                journal=journal,
            )
            return journal.ticket
        if journal.state == "claiming":
            if journal.submission_key_sha256 is None:
                raise ValueError("REQUESTER_TICKET_JOURNAL_INVALID")
            consumed = processing / f"{journal.submission_key_sha256}.ticket.json"
            source_exists = ticket_path.exists()
            consumed_exists = consumed.exists()
            if source_exists == consumed_exists:
                raise ValueError("REQUESTER_TICKET_CLAIM_UNCERTAIN")
            if source_exists:
                os.rename(ticket_path, consumed)
            consumed_journal = _transition_ticket_journal(
                journal,
                state="consumed",
                submission_key_sha256=journal.submission_key_sha256,
                updated_at=observed_at,
            )
            _atomic_replace(
                journal_path,
                canonical_model_bytes(consumed_journal) + b"\n",
            )
            _write_campaign_status(
                broker_root=root,
                config=config,
                journal=consumed_journal,
            )
            return None
        if ticket_path.exists() or ticket_path.is_symlink():
            raise ValueError("REQUESTER_LAUNCH_TICKET_REAPPEARED")
        _write_campaign_status(
            broker_root=root,
            config=config,
            journal=journal,
        )
        return None

    if ticket_path.exists() or ticket_path.is_symlink():
        raise ValueError("REQUESTER_TICKET_JOURNAL_MISSING")
    journal = _ticket_journal(
        ticket=candidate,
        state="available",
        submission_key_sha256=None,
        request_sha256=None,
        issue_number=None,
        created_at=observed_at,
        updated_at=observed_at,
    )
    if not _exclusive_write(
        journal_path,
        canonical_model_bytes(journal) + b"\n",
    ):
        return _ensure_one_launch_ticket(
            broker_root=root,
            config=config,
            candidate=candidate,
            observed_at=observed_at,
        )
    _atomic_replace(ticket_path, canonical_model_bytes(candidate) + b"\n")
    _write_campaign_status(
        broker_root=root,
        config=config,
        journal=journal,
    )
    return candidate


def _new_launch_ticket(
    *,
    campaign_key: str,
    campaign_definition_sha256: str,
    prompt_sha256: str,
) -> CatalogLaunchTicketV1:
    return CatalogLaunchTicketV1(
        schema_version="1",
        request_id=str(_uuid7()),
        campaign_key=campaign_key,
        launch_generation=1,
        campaign_definition_sha256=campaign_definition_sha256,
        prompt_sha256=prompt_sha256,
        previous_terminal_request_sha256=None,
    )


def _prepare_campaign_history_rebuild(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    campaign_key: str,
    journal: CatalogBrokerTicketJournalV1 | None = None,
) -> None:
    """Preserve uncertain local public state before authoritative reconstruction."""

    root = broker_root.resolve(strict=True)
    processing = _broker_directory(root, config.broker.processing)
    statuses = _broker_directory(root, config.broker.campaign_status)
    tickets = _broker_directory(root, config.broker.launch_tickets)
    public_candidates = (
        (statuses / f"{campaign_key}.journal.json", "journal"),
        (statuses / f"{campaign_key}.status.json", "status"),
        (statuses / f"{campaign_key}.terminal-poll.json", "poll"),
        (tickets / f"{campaign_key}.ticket.json", "ticket"),
    )
    private_candidates: tuple[tuple[Path, str], ...] = ()
    if journal is not None and journal.submission_key_sha256 is not None:
        submission_key = journal.submission_key_sha256
        receipts = _broker_directory(root, config.broker.receipts)
        private_candidates = (
            (processing / f"{submission_key}.signed.json", "signed"),
            (processing / f"{submission_key}.ticket.json", "consumed-ticket"),
            (processing / f"{submission_key}.post-attempt.json", "post-attempt"),
            (processing / f"{submission_key}.request.json", "request"),
            (receipts / f"{submission_key}.receipt.json", "receipt"),
        )
    candidates = (*public_candidates, *private_candidates)
    recovery_id = uuid.uuid4().hex
    for source, kind in candidates:
        if not source.exists() and not source.is_symlink():
            continue
        destination = processing / (
            f"history-rebuild-{campaign_key}-{kind}-{recovery_id}.entry"
        )
        if destination.exists() or destination.is_symlink():
            raise ValueError("REQUESTER_HISTORY_LOCAL_STATE_CONFLICT")
        os.rename(source, destination)


def ensure_catalog_launch_tickets(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    observed_at: datetime,
    client: CatalogBrokerGithubClient | None = None,
) -> tuple[CatalogLaunchTicketV1, ...]:
    """Publish qualification-only or sealed production generation-1 tickets."""

    root = broker_root.resolve(strict=True)
    prompt_path = root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"
    if prompt_path.is_symlink():
        raise ValueError("REQUESTER_PROMPT_INVALID")
    prompt_bytes = prompt_path.read_bytes()
    prompt_sha256 = hashlib.sha256(prompt_bytes).hexdigest()
    policy_path = root / "config/catalog_run_prompt_policy_v1.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or policy.get("active_prompt_sha256") != prompt_sha256:
        raise ValueError("CATALOG_PROMPT_HASH_MISMATCH")

    production_seal_path = root.joinpath(*config.broker.production_seal.split("/"))
    bootstrap_seal_path = root / "config/bootstrap-qualified-v1.seal.json"
    production_seal_present = (
        production_seal_path.exists() or production_seal_path.is_symlink()
    )
    bootstrap_seal_present = (
        bootstrap_seal_path.exists() or bootstrap_seal_path.is_symlink()
    )
    published: list[CatalogLaunchTicketV1] = []

    def ensure_with_history(candidate: CatalogLaunchTicketV1) -> CatalogLaunchTicketV1 | None:
        journal_path = (
            root
            / config.broker.campaign_status
            / f"{candidate.campaign_key}.journal.json"
        )
        if journal_path.exists() and not journal_path.is_symlink():
            try:
                journal = _load_ticket_journal(journal_path)
            except ValueError:
                if client is None:
                    raise ValueError("REQUESTER_TICKET_HISTORY_UNPROVEN") from None
                _prepare_campaign_history_rebuild(
                    broker_root=root,
                    config=config,
                    campaign_key=candidate.campaign_key,
                )
            else:
                if journal.state == "active":
                    try:
                        _repair_active_campaign_local_state(
                            broker_root=root,
                            config=config,
                            journal=journal,
                        )
                    except (OSError, ValueError):
                        if client is None:
                            raise ValueError(
                                "REQUESTER_TICKET_HISTORY_UNPROVEN"
                            ) from None
                        _prepare_campaign_history_rebuild(
                            broker_root=root,
                            config=config,
                            campaign_key=candidate.campaign_key,
                            journal=journal,
                        )
                        return reconstruct_catalog_campaign_journal_from_github(
                            broker_root=root,
                            config=config,
                            client=client,
                            campaign_key=candidate.campaign_key,
                            campaign_definition_sha256=(
                                candidate.campaign_definition_sha256
                            ),
                            prompt_sha256=candidate.prompt_sha256,
                            observed_at=observed_at,
                        )
                return _ensure_one_launch_ticket(
                    broker_root=root,
                    config=config,
                    candidate=candidate,
                    observed_at=observed_at,
                )
        else:
            if client is None:
                raise ValueError("REQUESTER_TICKET_HISTORY_UNPROVEN")
            _prepare_campaign_history_rebuild(
                broker_root=root,
                config=config,
                campaign_key=candidate.campaign_key,
            )
        return reconstruct_catalog_campaign_journal_from_github(
            broker_root=root,
            config=config,
            client=client,
            campaign_key=candidate.campaign_key,
            campaign_definition_sha256=candidate.campaign_definition_sha256,
            prompt_sha256=candidate.prompt_sha256,
            observed_at=observed_at,
        )

    def retire_sealed_qualification_poll() -> None:
        statuses = _broker_directory(root, config.broker.campaign_status)
        qualification_journal = _load_ticket_journal(
            statuses
            / f"{config.bootstrap_qualification.campaign_key}.journal.json"
        )
        if qualification_journal.state != "terminal":
            raise ValueError("REQUESTER_BOOTSTRAP_SEAL_CONTEXT_INVALID")
        _retire_obsolete_terminal_poll_state(
            broker_root=root,
            config=config,
            successor_journal=qualification_journal,
        )

    if not production_seal_present:
        if bootstrap_seal_present:
            try:
                seal = _read_canonical_model(
                    bootstrap_seal_path,
                    CatalogBrokerBootstrapSealV1,
                    maximum_bytes=16_384,
                )
            except (OSError, ValueError) as exc:
                raise ValueError("REQUESTER_BOOTSTRAP_SEAL_INVALID") from exc
            if not isinstance(seal, CatalogBrokerBootstrapSealV1):
                raise ValueError("REQUESTER_BOOTSTRAP_SEAL_INVALID")
            _verify_bootstrap_seal_context(
                broker_root=root,
                config=config,
                seal=seal,
            )
            retire_sealed_qualification_poll()
            qualification_path = (
                root
                / config.broker.launch_tickets
                / f"{config.bootstrap_qualification.campaign_key}.ticket.json"
            )
            if qualification_path.exists() or qualification_path.is_symlink():
                raise ValueError("REQUESTER_BOOTSTRAP_TICKET_REAPPEARED")
            return ()
        ticket = _new_launch_ticket(
            campaign_key=config.bootstrap_qualification.campaign_key,
            campaign_definition_sha256=canonical_sha256(
                config.bootstrap_qualification
            ),
            prompt_sha256=prompt_sha256,
        )
        ensured = ensure_with_history(ticket)
        return (ensured,) if ensured is not None else ()

    try:
        production_seal = _read_canonical_model(
            production_seal_path,
            CatalogRequesterProductionSealV1,
            maximum_bytes=16_384,
        )
    except (OSError, ValueError) as exc:
        raise ValueError("REQUESTER_PRODUCTION_SEAL_UNPROVEN") from exc
    if not isinstance(production_seal, CatalogRequesterProductionSealV1):
        raise ValueError("REQUESTER_PRODUCTION_SEAL_UNPROVEN")
    try:
        bootstrap_seal = _read_canonical_model(
            bootstrap_seal_path,
            CatalogBrokerBootstrapSealV1,
            maximum_bytes=16_384,
        )
    except (OSError, ValueError) as exc:
        raise ValueError("REQUESTER_BOOTSTRAP_SEAL_INVALID") from exc
    if not isinstance(bootstrap_seal, CatalogBrokerBootstrapSealV1):
        raise ValueError("REQUESTER_BOOTSTRAP_SEAL_INVALID")
    _verify_bootstrap_seal_context(
        broker_root=root,
        config=config,
        seal=bootstrap_seal,
    )
    retire_sealed_qualification_poll()
    if production_seal.sealed_at < bootstrap_seal.sealed_at:
        raise ValueError("REQUESTER_PRODUCTION_SEAL_UNPROVEN")
    verify_production_bootstrap_receipt(
        broker_root=root,
        config=config,
        production_seal=production_seal,
    )

    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    for entry in registry.campaigns:
        if not entry.active:
            continue
        manifest = parse_catalog_campaign_definition_bytes(
            root.joinpath(*entry.definition_manifest_path.split("/")).read_bytes()
        )
        candidate = _new_launch_ticket(
            campaign_key=entry.campaign_key,
            campaign_definition_sha256=manifest.campaign_definition_sha256,
            prompt_sha256=prompt_sha256,
        )
        expected_config, expected_draft = _build_registered_catalog_draft(
            broker_root=root,
            campaign_key=entry.campaign_key,
            ticket_override=candidate,
        )
        if expected_config != config or expected_draft.launch_ticket_sha256 != (
            candidate.launch_ticket_sha256
        ):
            raise ValueError("REQUESTER_PRODUCTION_TICKET_CONTEXT_INVALID")
        ensured = ensure_with_history(candidate)
        if ensured is not None:
            published.append(ensured)
    return tuple(published)


def claim_next_catalog_request(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    excluded_processing_names: frozenset[str] = frozenset(),
) -> Path | None:
    """Claim one safe request by a same-volume atomic rename."""

    root = broker_root.resolve(strict=True)
    processing = _broker_directory(root, config.broker.processing)
    recoverable: list[Path] = []
    with os.scandir(processing) as entries:
        for entry in entries:
            if entry.name.endswith(".request.json") and (
                entry.name not in excluded_processing_names
            ):
                recoverable.append(Path(entry.path))
                if len(recoverable) > config.broker.maximum_pending_entries:
                    raise ValueError("REQUESTER_PROCESSING_CAPACITY_EXCEEDED")
    if recoverable:
        return sorted(recoverable)[0]

    inventory = inventory_catalog_broker_inbox(
        broker_root=broker_root,
        config=config,
    )
    if not inventory.available and inventory.reason_code != (
        "REQUEST_BROKER_CAPACITY_EXCEEDED"
    ):
        return None
    candidates = tuple(
        entry
        for entry in inventory.entries
        if entry.kind == "request"
        and entry.regular_file
        and entry.single_link
        and not entry.reparse_point
        and entry.size_bytes <= config.broker.maximum_request_bytes
    )
    if not candidates:
        return None
    inbox = _broker_directory(root, config.broker.inbox)
    selected = next(
        (
            candidate
            for candidate in candidates
            if not (processing / candidate.name).exists()
            and not (processing / candidate.name).is_symlink()
        ),
        None,
    )
    if selected is None:
        return None
    source = inbox / selected.name
    destination = processing / selected.name
    before = source.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_nlink", 1) != 1
        or _is_reparse_stat(before)
        or before.st_size != selected.size_bytes
    ):
        return None
    try:
        os.rename(source, destination)
    except FileExistsError:
        return None
    after = destination.stat(follow_symlinks=False)
    if after.st_size != before.st_size or not stat.S_ISREG(after.st_mode):
        raise ValueError("REQUESTER_BROKER_CLAIM_INVALID")
    return destination


def claim_next_catalog_reconcile_hint(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    excluded_processing_names: frozenset[str] = frozenset(),
) -> Path | None:
    """Claim one bounded reconcile hint without inspecting request contents."""

    root = broker_root.resolve(strict=True)
    processing = _broker_directory(root, config.broker.processing)
    recoverable: list[Path] = []
    with os.scandir(processing) as entries:
        for entry in entries:
            if entry.name.endswith(".reconcile-hint.json") and (
                entry.name not in excluded_processing_names
            ):
                recoverable.append(Path(entry.path))
                if len(recoverable) > config.broker.maximum_pending_entries:
                    raise ValueError("REQUESTER_PROCESSING_CAPACITY_EXCEEDED")
    if recoverable:
        return sorted(recoverable)[0]

    inventory = inventory_catalog_broker_inbox(
        broker_root=broker_root,
        config=config,
    )
    if not inventory.available and inventory.reason_code != (
        "REQUEST_BROKER_CAPACITY_EXCEEDED"
    ):
        return None
    candidates = tuple(
        entry
        for entry in inventory.entries
        if entry.kind == "reconcile_hint"
        and entry.regular_file
        and entry.single_link
        and not entry.reparse_point
        and entry.size_bytes <= config.broker.maximum_hint_bytes
    )
    if not candidates:
        return None
    inbox = _broker_directory(root, config.broker.inbox)
    selected = next(
        (
            candidate
            for candidate in candidates
            if not (processing / candidate.name).exists()
            and not (processing / candidate.name).is_symlink()
        ),
        None,
    )
    if selected is None:
        return None
    source = inbox / selected.name
    destination = processing / selected.name
    before = os.lstat(source)
    if (
        not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_nlink", 1) != 1
        or _is_reparse_stat(before)
        or before.st_size != selected.size_bytes
    ):
        return None
    try:
        os.rename(source, destination)
    except FileExistsError:
        return None
    after = os.lstat(destination)
    if after.st_size != before.st_size or not stat.S_ISREG(after.st_mode):
        raise ValueError("REQUESTER_BROKER_CLAIM_INVALID")
    return destination


def load_claimed_catalog_draft(
    *,
    claimed_path: Path,
    config: CatalogRequesterBrokerConfigV1,
) -> CatalogRunIntentDraftV1:
    metadata = claimed_path.stat(follow_symlinks=False)
    if (
        claimed_path.is_symlink()
        or _is_reparse_stat(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or getattr(metadata, "st_nlink", 1) != 1
        or metadata.st_size > config.broker.maximum_request_bytes
    ):
        raise ValueError("REQUESTER_BROKER_REQUEST_INVALID")
    data = claimed_path.read_bytes()
    if not data.endswith(b"\n"):
        raise ValueError("REQUESTER_BROKER_REQUEST_INVALID")
    try:
        draft = CatalogRunIntentDraftV1.model_validate_json(data[:-1])
    except Exception as exc:
        raise ValueError("REQUESTER_BROKER_REQUEST_INVALID") from exc
    if canonical_model_bytes(draft) + b"\n" != data:
        raise ValueError("REQUESTER_BROKER_REQUEST_INVALID")
    expected_name = f"{draft.submission_key_sha256}.request.json"
    if claimed_path.name != expected_name:
        raise ValueError("REQUESTER_BROKER_REQUEST_INVALID")
    return draft


def _retire_claimed_catalog_request(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    claimed_path: Path,
    draft: CatalogRunIntentDraftV1,
) -> Path:
    """Move one completed claim out of the broker's recoverable queue."""

    root = broker_root.resolve(strict=True)
    processing = _broker_directory(root, config.broker.processing)
    expected_name = f"{draft.submission_key_sha256}.request.json"
    if (
        claimed_path.parent.resolve(strict=True) != processing
        or claimed_path.name != expected_name
        or claimed_path.is_symlink()
    ):
        raise ValueError("REQUESTER_BROKER_CLAIM_INVALID")
    expected_bytes = canonical_model_bytes(draft) + b"\n"
    metadata = claimed_path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or _is_reparse_stat(metadata)
        or getattr(metadata, "st_nlink", 1) != 1
        or metadata.st_size != len(expected_bytes)
        or claimed_path.read_bytes() != expected_bytes
    ):
        raise ValueError("REQUESTER_BROKER_CLAIM_INVALID")

    archived = processing / f"processed-{draft.submission_key_sha256}.request"
    if archived.exists() or archived.is_symlink():
        archived_metadata = archived.stat(follow_symlinks=False)
        if (
            archived.is_symlink()
            or not stat.S_ISREG(archived_metadata.st_mode)
            or _is_reparse_stat(archived_metadata)
            or getattr(archived_metadata, "st_nlink", 1) != 1
            or archived_metadata.st_size != len(expected_bytes)
            or archived.read_bytes() != expected_bytes
        ):
            raise ValueError("REQUESTER_BROKER_ARCHIVE_CONFLICT")
        os.replace(claimed_path, archived)
    else:
        os.rename(claimed_path, archived)

    archived_metadata = archived.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(archived_metadata.st_mode)
        or _is_reparse_stat(archived_metadata)
        or getattr(archived_metadata, "st_nlink", 1) != 1
        or archived_metadata.st_size != len(expected_bytes)
        or archived.read_bytes() != expected_bytes
    ):
        raise ValueError("REQUESTER_BROKER_ARCHIVE_INVALID")
    return archived


def load_claimed_catalog_reconcile_hint(
    *,
    claimed_path: Path,
    config: CatalogRequesterBrokerConfigV1,
) -> CatalogRequesterReconcileHintV1:
    metadata = os.lstat(claimed_path)
    if (
        claimed_path.is_symlink()
        or _is_reparse_stat(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or getattr(metadata, "st_nlink", 1) != 1
        or metadata.st_size > config.broker.maximum_hint_bytes
    ):
        raise ValueError("REQUESTER_BROKER_RECONCILE_HINT_INVALID")
    data = claimed_path.read_bytes()
    if not data.endswith(b"\n"):
        raise ValueError("REQUESTER_BROKER_RECONCILE_HINT_INVALID")
    try:
        hint = CatalogRequesterReconcileHintV1.model_validate_json(data[:-1])
    except Exception as exc:
        raise ValueError("REQUESTER_BROKER_RECONCILE_HINT_INVALID") from exc
    if canonical_model_bytes(hint) + b"\n" != data or claimed_path.name != (
        f"{hint.campaign_key}.reconcile-hint.json"
    ):
        raise ValueError("REQUESTER_BROKER_RECONCILE_HINT_INVALID")
    return hint


def quarantine_invalid_claimed_catalog_request(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    claimed_path: Path,
    reason_code: str,
    observed_at: datetime,
) -> Path:
    """Drain one invalid claimed entry into service-only, non-retry state."""

    processing = _broker_directory(
        broker_root.resolve(strict=True), config.broker.processing
    )
    if claimed_path.parent.resolve(strict=True) != processing:
        raise ValueError("REQUESTER_BROKER_CLAIM_INVALID")
    metadata = os.lstat(claimed_path)
    if stat.S_ISDIR(metadata.st_mode) and not _is_reparse_stat(metadata):
        raise ValueError("REQUESTER_BROKER_CLAIM_INVALID")
    rejection = _rejected_entry(
        source_name=claimed_path.name,
        reason_code=reason_code,
        observed_at=observed_at,
    )
    rejection_stem = f"rejected-{rejection.rejection_sha256}"
    destination = processing / f"{rejection_stem}.entry"
    receipt_path = processing / f"{rejection_stem}.json"
    if (
        destination.exists()
        or destination.is_symlink()
        or receipt_path.exists()
        or receipt_path.is_symlink()
    ):
        rejection_stem += f"-{uuid.uuid4().hex}"
        destination = processing / f"{rejection_stem}.entry"
        receipt_path = processing / f"{rejection_stem}.json"
    os.rename(claimed_path, destination)
    if not _exclusive_write(
        receipt_path,
        canonical_model_bytes(rejection) + b"\n",
    ):
        raise ValueError("REQUESTER_BROKER_QUARANTINE_CONFLICT")
    return destination


def verify_and_consume_catalog_launch_ticket(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    draft: CatalogRunIntentDraftV1,
    observed_at: datetime | None = None,
) -> Path:
    """Rebuild the draft from installed public inputs, then consume its ticket."""

    expected_config, expected_draft = build_registered_catalog_draft(
        broker_root=broker_root,
        campaign_key=draft.campaign_key,
    )
    if expected_config != config or expected_draft != draft:
        raise ValueError("REQUESTER_BROKER_TICKET_OR_CONTEXT_MISMATCH")
    root = broker_root.resolve(strict=True)
    tickets = _broker_directory(root, config.broker.launch_tickets)
    processing = _broker_directory(root, config.broker.processing)
    statuses = _broker_directory(root, config.broker.campaign_status)
    source = tickets / f"{draft.campaign_key}.ticket.json"
    destination = processing / f"{draft.submission_key_sha256}.ticket.json"
    journal_path = statuses / f"{draft.campaign_key}.journal.json"
    journal = _load_ticket_journal(journal_path)
    if journal.ticket.launch_ticket_sha256 != draft.launch_ticket_sha256:
        raise ValueError("REQUESTER_BROKER_TICKET_OR_CONTEXT_MISMATCH")
    now = _utc(observed_at or datetime.now(UTC))
    if journal.state == "available":
        claiming = _transition_ticket_journal(
            journal,
            state="claiming",
            submission_key_sha256=draft.submission_key_sha256,
            updated_at=now,
        )
        _atomic_replace(journal_path, canonical_model_bytes(claiming) + b"\n")
        _write_campaign_status(
            broker_root=root,
            config=config,
            journal=claiming,
        )
        journal = claiming
    if (
        journal.state != "claiming"
        or journal.submission_key_sha256 != draft.submission_key_sha256
    ):
        raise ValueError("REQUESTER_BROKER_TICKET_ALREADY_CONSUMED")
    source_exists = source.exists()
    destination_exists = destination.exists()
    if source_exists == destination_exists:
        raise ValueError("REQUESTER_TICKET_CLAIM_UNCERTAIN")
    if source_exists:
        os.rename(source, destination)
    consumed = _transition_ticket_journal(
        journal,
        state="consumed",
        submission_key_sha256=draft.submission_key_sha256,
        updated_at=now,
    )
    _atomic_replace(journal_path, canonical_model_bytes(consumed) + b"\n")
    _write_campaign_status(
        broker_root=root,
        config=config,
        journal=consumed,
    )
    return destination


def verify_consumed_catalog_launch_ticket(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    draft: CatalogRunIntentDraftV1,
    observed_at: datetime | None = None,
) -> Path:
    """Recover the crash boundary after consume and before signature persist."""

    processing = _broker_directory(
        broker_root.resolve(strict=True), config.broker.processing
    )
    path = processing / f"{draft.submission_key_sha256}.ticket.json"
    metadata = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or _is_reparse_stat(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or getattr(metadata, "st_nlink", 1) != 1
        or metadata.st_size > config.broker.maximum_request_bytes
    ):
        raise ValueError("REQUESTER_BROKER_CONSUMED_TICKET_INVALID")
    data = path.read_bytes()
    try:
        ticket = CatalogLaunchTicketV1.model_validate_json(data[:-1])
    except Exception as exc:
        raise ValueError("REQUESTER_BROKER_CONSUMED_TICKET_INVALID") from exc
    if not data.endswith(b"\n") or data != canonical_model_bytes(ticket) + b"\n":
        raise ValueError("REQUESTER_BROKER_CONSUMED_TICKET_INVALID")
    expected_config, expected_draft = _build_registered_catalog_draft(
        broker_root=broker_root,
        campaign_key=draft.campaign_key,
        ticket_override=ticket,
    )
    if expected_config != config or expected_draft != draft:
        raise ValueError("REQUESTER_BROKER_TICKET_OR_CONTEXT_MISMATCH")
    statuses = _broker_directory(
        broker_root.resolve(strict=True), config.broker.campaign_status
    )
    journal_path = statuses / f"{draft.campaign_key}.journal.json"
    journal = _load_ticket_journal(journal_path)
    if (
        journal.ticket != ticket
        or journal.submission_key_sha256 != draft.submission_key_sha256
        or journal.state not in {"claiming", "consumed"}
    ):
        raise ValueError("REQUESTER_TICKET_JOURNAL_INVALID")
    if journal.state == "claiming":
        consumed = _transition_ticket_journal(
            journal,
            state="consumed",
            submission_key_sha256=draft.submission_key_sha256,
            updated_at=_utc(observed_at or datetime.now(UTC)),
        )
        _atomic_replace(journal_path, canonical_model_bytes(consumed) + b"\n")
        _write_campaign_status(
            broker_root=broker_root,
            config=config,
            journal=consumed,
        )
    return path


def load_or_create_signed_processing_record(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    draft: CatalogRunIntentDraftV1,
    private_key_pem: bytes,
    signed_at: datetime,
) -> CatalogBrokerProcessingRecordV1:
    processing = _broker_directory(
        broker_root.resolve(strict=True), config.broker.processing
    )
    path = processing / f"{draft.submission_key_sha256}.signed.json"
    if path.exists() or path.is_symlink():
        try:
            record = _read_canonical_model(
                path,
                CatalogBrokerProcessingRecordV1,
                maximum_bytes=64_000,
            )
        except (OSError, ValueError) as exc:
            raise ValueError("CATALOG_PROCESSING_RECORD_INVALID") from exc
        if (
            not isinstance(record, CatalogBrokerProcessingRecordV1)
            or record.request.intent.model_dump(mode="json")
            != draft.model_dump(mode="json")
        ):
            raise ValueError("CATALOG_PROCESSING_RECORD_INVALID")
        return record
    record = sign_catalog_request(
        draft=draft,
        private_key_pem=private_key_pem,
        signed_at=signed_at,
    )
    _atomic_replace(path, record.processing_bytes)
    return record


class CatalogBrokerProcessingRecordV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    stage: Literal["signed_before_post"]
    title: str = Field(max_length=MAX_TITLE_CHARS)
    body: str
    intent_sha256: Sha256
    request_sha256: Sha256
    request: CatalogRunRequestV1
    signed_at: datetime
    processing_record_sha256: Sha256

    @field_validator("signed_at")
    @classmethod
    def _utc_signed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogBrokerProcessingRecordV1":
        if len(self.body.encode("utf-8")) > MAX_BODY_BYTES:
            raise ValueError("CATALOG_REQUEST_INVALID")
        expected_title = f"[AURORA CATALOG RUN REQUEST] {self.request.request_id}"
        expected_body = (
            "```json\n"
            + canonical_model_bytes(self.request).decode("utf-8")
            + "\n```\n"
        )
        if self.title != expected_title or self.body != expected_body:
            raise ValueError("CATALOG_REQUEST_NONCANONICAL")
        if self.intent_sha256 != self.request.intent_sha256:
            raise ValueError("CATALOG_REQUEST_INTENT_HASH_INVALID")
        if self.request_sha256 != self.request.request_sha256:
            raise ValueError("CATALOG_REQUEST_HASH_INVALID")
        payload = self.model_copy(update={"processing_record_sha256": "0" * 64})
        if canonical_sha256(payload) != self.processing_record_sha256:
            raise ValueError("CATALOG_PROCESSING_RECORD_HASH_INVALID")
        return self

    @property
    def processing_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    @property
    def processing_bytes(self) -> bytes:
        return canonical_model_bytes(self) + b"\n"


class CatalogBrokerPostAttemptV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    stage: Literal["post_may_have_been_attempted"]
    submission_key_sha256: Sha256
    processing_record_sha256: Sha256
    post_lower_bound: datetime
    post_attempt_sha256: Sha256

    @field_validator("post_lower_bound")
    @classmethod
    def _utc_lower_bound(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _hash(self) -> "CatalogBrokerPostAttemptV1":
        payload = self.model_copy(update={"post_attempt_sha256": "0" * 64})
        if canonical_sha256(payload) != self.post_attempt_sha256:
            raise ValueError("REQUESTER_POST_ATTEMPT_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        signed: CatalogBrokerProcessingRecordV1,
        post_lower_bound: datetime,
    ) -> "CatalogBrokerPostAttemptV1":
        unsigned = cls.model_construct(
            schema_version="1",
            stage="post_may_have_been_attempted",
            submission_key_sha256=signed.request.intent.submission_key_sha256,
            processing_record_sha256=signed.processing_record_sha256,
            post_lower_bound=_github_timestamp_floor(post_lower_bound),
            post_attempt_sha256="0" * 64,
        )
        return cls.model_validate(
            unsigned.model_copy(
                update={"post_attempt_sha256": canonical_sha256(unsigned)}
            ).model_dump(mode="json")
        )


def load_or_create_post_attempt(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    signed: CatalogBrokerProcessingRecordV1,
    post_lower_bound: datetime,
) -> tuple[CatalogBrokerPostAttemptV1, bool]:
    processing = _broker_directory(
        broker_root.resolve(strict=True), config.broker.processing
    )
    key = signed.request.intent.submission_key_sha256
    path = processing / f"{key}.post-attempt.json"
    if path.exists() or path.is_symlink():
        try:
            existing = _read_canonical_model(
                path,
                CatalogBrokerPostAttemptV1,
                maximum_bytes=16_384,
            )
        except (OSError, ValueError) as exc:
            raise ValueError("REQUESTER_POST_ATTEMPT_INVALID") from exc
        if (
            not isinstance(existing, CatalogBrokerPostAttemptV1)
            or existing.submission_key_sha256 != key
            or existing.processing_record_sha256 != signed.processing_record_sha256
        ):
            raise ValueError("REQUESTER_POST_ATTEMPT_INVALID")
        return existing, False
    attempt = CatalogBrokerPostAttemptV1.create(
        signed=signed,
        post_lower_bound=post_lower_bound,
    )
    _atomic_replace(path, canonical_model_bytes(attempt) + b"\n")
    return attempt, True


@dataclass(frozen=True)
class CatalogBrokerHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    json_body: object


class CatalogBrokerHttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> CatalogBrokerHttpResponse: ...


class CatalogBrokerTransientError(ValueError):
    """Retryable provider failure carrying the earliest safe retry delay."""

    def __init__(self, *, retry_after_seconds: int | None = None) -> None:
        super().__init__("REQUESTER_GITHUB_TRANSIENT_FAILURE")
        self.retry_after_seconds = retry_after_seconds


def _github_retry_delay_seconds(headers: Mapping[str, str]) -> int | None:
    normalized = {str(key).casefold(): str(value).strip() for key, value in headers.items()}
    now_epoch = time.time()
    candidates: list[int] = []
    retry_after = normalized.get("retry-after")
    if retry_after is not None:
        try:
            delay = int(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = math.ceil(retry_at.timestamp() - now_epoch)
            except (TypeError, ValueError, OverflowError):
                delay = 0
        if delay > 0:
            candidates.append(delay)
    if normalized.get("x-ratelimit-remaining") == "0":
        try:
            reset_epoch = int(normalized.get("x-ratelimit-reset", ""))
        except ValueError:
            reset_epoch = 0
        reset_delay = math.ceil(reset_epoch - now_epoch)
        if reset_delay > 0:
            candidates.append(reset_delay)
    return max(candidates) if candidates else None


class RequestsCatalogBrokerHttpTransport:
    """Hardened Requests adapter with no inherited proxy/netrc behavior."""

    def __init__(self, *, timeout_seconds: int) -> None:
        if timeout_seconds < 1 or timeout_seconds > 60:
            raise ValueError("REQUESTER_HTTP_TIMEOUT_INVALID")
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.verify = True
        self._timeout = (min(5, timeout_seconds), timeout_seconds)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> CatalogBrokerHttpResponse:
        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise CatalogBrokerTransientError() from exc
        response_headers = {
            str(key): str(value) for key, value in response.headers.items()
        }
        normalized_headers = {
            key.casefold(): value.strip() for key, value in response_headers.items()
        }
        explicitly_rate_limited = response.status_code == 403 and (
            "retry-after" in normalized_headers
            or normalized_headers.get("x-ratelimit-remaining") == "0"
        )
        if response.status_code in {408, 425, 429, 500, 502, 503, 504} or (
            explicitly_rate_limited
        ):
            raise CatalogBrokerTransientError(
                retry_after_seconds=_github_retry_delay_seconds(response_headers)
            )
        if 300 <= response.status_code < 400:
            raise ValueError("REQUESTER_GITHUB_REDIRECT_FORBIDDEN")
        if response.status_code == 304:
            payload = None
        else:
            try:
                payload = response.json()
            except requests.exceptions.JSONDecodeError as exc:
                raise ValueError("REQUESTER_GITHUB_RESPONSE_INVALID") from exc
        return CatalogBrokerHttpResponse(
            status_code=response.status_code,
            headers=response_headers,
            json_body=payload,
        )


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_private_key(private_key_pem: bytes) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("REQUESTER_PRIVATE_KEY_INVALID") from exc
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError("REQUESTER_PRIVATE_KEY_INVALID")
    return key


def _app_jwt(*, app_id: int, private_key: rsa.RSAPrivateKey, now: datetime) -> str:
    observed = _utc(now)
    header = _b64url(b'{"alg":"RS256","typ":"JWT"}')
    payload = _b64url(
        json.dumps(
            {
                "exp": int((observed + timedelta(minutes=9)).timestamp()),
                "iat": int((observed - timedelta(seconds=60)).timestamp()),
                "iss": str(app_id),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{header}.{payload}.{_b64url(signature)}"


def sign_catalog_request(
    *,
    draft: CatalogRunIntentDraftV1,
    private_key_pem: bytes,
    signed_at: datetime | None = None,
) -> CatalogBrokerProcessingRecordV1:
    """Sign exact canonical request bytes and return a persistable record."""

    checked_draft = CatalogRunIntentDraftV1.model_validate_json(
        canonical_model_bytes(draft)
    )
    intent = CatalogRunIntentV1.model_validate(checked_draft.model_dump(mode="json"))
    title = f"[AURORA CATALOG RUN REQUEST] {intent.request_id}"
    key = _load_private_key(private_key_pem)
    public_key = key.public_key()
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = key.sign(
        _attestation_payload(title, intent),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size,
        ),
        hashes.SHA256(),
    )
    request = CatalogRunRequestV1(
        **intent.model_dump(mode="json"),
        requester_public_key_sha256=hashlib.sha256(public_der).hexdigest(),
        requester_attestation_algorithm="rsa-pss-sha256-v1",
        requester_attestation_b64=b64encode(signature).decode("ascii"),
    )
    body = "```json\n" + canonical_model_bytes(request).decode("utf-8") + "\n```\n"
    unsigned = CatalogBrokerProcessingRecordV1.model_construct(
        schema_version="1",
        stage="signed_before_post",
        title=title,
        body=body,
        intent_sha256=request.intent_sha256,
        request_sha256=request.request_sha256,
        request=request,
        signed_at=_utc(signed_at or datetime.now(UTC)),
        processing_record_sha256="0" * 64,
    )
    return CatalogBrokerProcessingRecordV1.model_validate(
        unsigned.model_copy(
            update={"processing_record_sha256": canonical_sha256(unsigned)}
        ).model_dump(mode="json")
    )


class CatalogBrokerGithubClient:
    """GitHub App client with a closed method/path state machine."""

    def __init__(
        self,
        *,
        config: CatalogRequesterBrokerConfigV1,
        http: CatalogBrokerHttpTransport,
        app_id: int,
        installation_id: int,
        private_key_pem: bytes,
        expected_actor: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if app_id < 1 or installation_id < 1:
            raise ValueError("REQUESTER_APP_IDENTITY_INVALID")
        if not expected_actor.endswith("[bot]"):
            raise ValueError("REQUESTER_APP_ACTOR_INVALID")
        self.config = config
        self.http = http
        self.app_id = app_id
        self.installation_id = installation_id
        self._private_key = _load_private_key(private_key_pem)
        self.expected_actor = expected_actor
        self.now = now or (lambda: datetime.now(UTC))

    @property
    def _issues_path(self) -> str:
        return self.config.request_issue_endpoint.format(
            repository=self.config.repository
        )

    @property
    def requester_public_key_sha256(self) -> str:
        public_der = self._private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(public_der).hexdigest()

    def _path_allowed(self, method: str, path: str) -> bool:
        token_path = f"/app/installations/{self.installation_id}/access_tokens"
        exact_issue_prefix = self._issues_path + "/"
        if method == "POST" and path in {token_path, self._issues_path}:
            return True
        if method == "GET" and path.startswith(exact_issue_prefix):
            suffix = path[len(exact_issue_prefix) :]
            return suffix.isdigit() and int(suffix) >= 1
        if method == "GET" and path.startswith(self._issues_path + "?"):
            first = (
                self._issues_path
                + "?state=all&sort=created&direction=desc&per_page=100"
            )
            if path == first:
                return True
            prefix = first + "&page="
            page = path[len(prefix) :] if path.startswith(prefix) else ""
            return page.isdigit() and int(page) >= 2 and str(int(page)) == page
        return False

    def request_fixed(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json_body: dict[str, object] | None = None,
        if_none_match: str | None = None,
    ) -> CatalogBrokerHttpResponse:
        normalized_method = method.upper()
        if not self._path_allowed(normalized_method, path):
            raise ValueError("REQUESTER_GITHUB_ENDPOINT_FORBIDDEN")
        if not path.startswith("/") or "://" in path:
            raise ValueError("REQUESTER_GITHUB_ENDPOINT_FORBIDDEN")
        if if_none_match is not None and (
            normalized_method != "GET"
            or not path.startswith(self._issues_path + "/")
            or len(if_none_match) > 256
            or not if_none_match
            or "\r" in if_none_match
            or "\n" in if_none_match
        ):
            raise ValueError("REQUESTER_GITHUB_CONDITIONAL_GET_INVALID")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": self.config.api_version,
        }
        if if_none_match is not None:
            headers["If-None-Match"] = if_none_match
        return self.http.request(
            normalized_method,
            self.config.api_origin + path,
            headers=headers,
            json_body=json_body,
        )

    def installation_token(self) -> str:
        path = f"/app/installations/{self.installation_id}/access_tokens"
        repository_name = self.config.repository.rsplit("/", 1)[1]
        jwt = _app_jwt(
            app_id=self.app_id,
            private_key=self._private_key,
            now=self.now(),
        )
        response = self.request_fixed(
            "POST",
            path,
            token=jwt,
            json_body={"repositories": [repository_name]},
        )
        if response.status_code != 201 or not isinstance(response.json_body, Mapping):
            raise ValueError("REQUESTER_INSTALLATION_TOKEN_UNPROVEN")
        payload = response.json_body
        permissions = payload.get("permissions")
        if permissions != self.config.required_installation_permissions:
            raise ValueError("REQUESTER_APP_OVERPRIVILEGED")
        repositories = payload.get("repositories")
        if not isinstance(repositories, list) or [
            item.get("full_name") if isinstance(item, Mapping) else None
            for item in repositories
        ] != [self.config.repository]:
            raise ValueError("REQUESTER_APP_REPOSITORY_SCOPE_INVALID")
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("REQUESTER_INSTALLATION_TOKEN_UNPROVEN")
        return token


def _parse_github_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("REQUESTER_CREATED_ISSUE_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("REQUESTER_CREATED_ISSUE_INVALID") from exc
    return _utc(parsed)


def _github_timestamp_floor(value: datetime) -> datetime:
    """Conservatively align a lower bound to GitHub's whole-second timestamps."""

    return _utc(value).replace(microsecond=0)


def _github_timestamp_ceil(value: datetime) -> datetime:
    """Conservatively align an upper bound to GitHub's whole-second timestamps."""

    checked = _utc(value)
    if checked.microsecond == 0:
        return checked
    return checked.replace(microsecond=0) + timedelta(seconds=1)


def _github_response_time(response: CatalogBrokerHttpResponse) -> datetime | None:
    raw = next(
        (value for key, value in response.headers.items() if key.casefold() == "date"),
        None,
    )
    if raw is None:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        return _utc(parsed)
    except (TypeError, ValueError) as exc:
        raise ValueError("REQUESTER_GITHUB_RESPONSE_INVALID") from exc


def _verify_issue(
    payload: object,
    *,
    signed: CatalogBrokerProcessingRecordV1,
    expected_actor: str,
    post_lower_bound: datetime,
    post_upper_bound: datetime,
    repository: str | None = None,
) -> int:
    if not isinstance(payload, Mapping):
        raise ValueError("REQUESTER_CREATED_ISSUE_INVALID")
    number = payload.get("number")
    user = payload.get("user")
    actor = user.get("login") if isinstance(user, Mapping) else None
    created_at = _parse_github_time(payload.get("created_at"))
    updated_at = _parse_github_time(payload.get("updated_at"))
    lower_bound = _github_timestamp_floor(post_lower_bound)
    upper_bound = _github_timestamp_ceil(post_upper_bound)
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
        or actor != expected_actor
        or payload.get("title") != signed.title
        or payload.get("body") != signed.body
        or payload.get("state") not in {"open", "closed"}
        or not lower_bound <= created_at <= upper_bound
        or updated_at < created_at
    ):
        raise ValueError("REQUESTER_CREATED_ISSUE_INVALID")
    if repository is not None and payload.get("html_url") != (
        f"https://github.com/{repository}/issues/{number}"
    ):
        raise ValueError("REQUESTER_CREATED_ISSUE_INVALID")
    return number


def _next_listing_path(
    response: CatalogBrokerHttpResponse,
    *,
    client: CatalogBrokerGithubClient,
) -> str | None:
    link_value = next(
        (
            value
            for key, value in response.headers.items()
            if key.casefold() == "link"
        ),
        None,
    )
    if link_value is None:
        return None
    next_urls: list[str] = []
    for segment in link_value.split(","):
        pieces = tuple(piece.strip() for piece in segment.split(";"))
        if len(pieces) < 2 or not pieces[0].startswith("<") or not pieces[0].endswith(">"):
            raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
        relations = {
            piece.split("=", 1)[1].strip().strip('"')
            for piece in pieces[1:]
            if piece.startswith("rel=") and "=" in piece
        }
        if "next" in relations:
            next_urls.append(pieces[0][1:-1])
    if len(next_urls) > 1:
        raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
    if not next_urls:
        return None
    parsed = urlsplit(next_urls[0])
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if (
        origin != client.config.api_origin
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    if not client._path_allowed("GET", path):
        raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
    return path


def _reconcile_uncertain_post(
    *,
    signed: CatalogBrokerProcessingRecordV1,
    client: CatalogBrokerGithubClient,
    token: str,
    post_lower_bound: datetime,
    post_upper_bound: datetime,
) -> int:
    first_path = (
        client._issues_path
        + "?state=all&sort=created&direction=desc&per_page=100"
    )
    path: str | None = first_path
    lower_bound = _github_timestamp_floor(post_lower_bound)
    upper_bound = _github_timestamp_ceil(post_upper_bound)
    matches: list[int] = []
    seen: set[int] = set()
    seen_pages: set[str] = set()
    previous_created: datetime | None = None
    pages = 0
    while path is not None:
        if path in seen_pages or pages >= 1_000:
            raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
        expected_path = first_path if pages == 0 else f"{first_path}&page={pages + 1}"
        if path != expected_path:
            raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
        seen_pages.add(path)
        pages += 1
        response = client.request_fixed("GET", path, token=token)
        if response.status_code != 200 or not isinstance(response.json_body, list):
            raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
        response_time = _github_response_time(response)
        if response_time is not None:
            upper_bound = max(upper_bound, _github_timestamp_ceil(response_time))
        page_oldest: datetime | None = None
        for item in response.json_body:
            if not isinstance(item, Mapping):
                raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
            number = item.get("number")
            created = _parse_github_time(item.get("created_at"))
            if (
                isinstance(number, bool)
                or not isinstance(number, int)
                or number in seen
            ):
                raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
            if previous_created is not None and created > previous_created:
                raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
            seen.add(number)
            previous_created = created
            page_oldest = created
            if item.get("title") == signed.title and item.get("body") == signed.body:
                matches.append(
                    _verify_issue(
                        item,
                        signed=signed,
                        expected_actor=client.expected_actor,
                        post_lower_bound=lower_bound,
                        post_upper_bound=upper_bound,
                        repository=client.config.repository,
                    )
                )
        next_path = _next_listing_path(response, client=client)
        if page_oldest is not None and page_oldest < lower_bound:
            path = None
        else:
            path = next_path
        if path is None and next_path is not None and len(response.json_body) < 100:
            raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
    if not matches:
        raise ValueError("REQUESTER_POST_RECONCILIATION_RETRYABLE")
    if len(matches) != 1:
        raise ValueError("REQUESTER_POST_RECONCILIATION_PENDING")
    return matches[0]


@dataclass(frozen=True)
class _CatalogHistoryRecord:
    issue_number: int
    title: str
    body: str
    request: CatalogRunRequestV1
    ticket: CatalogLaunchTicketV1
    created_at: datetime
    updated_at: datetime
    terminal: bool


def _history_issue_terminal(
    issue: Mapping[str, object],
    *,
    config: CatalogRequesterBrokerConfigV1,
) -> bool:
    labels = issue.get("labels")
    label_names = {
        item.get("name")
        for item in labels
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    } if isinstance(labels, list) else set()
    closed_by = issue.get("closed_by")
    if issue.get("state") == "open":
        if (
            config.terminal_close_marker.label in label_names
            or closed_by is not None
            or issue.get("closed_at") is not None
        ):
            raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
        return False
    if issue.get("state") != "closed":
        raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
    if (
        issue.get("state_reason") != config.terminal_close_marker.state_reason
        or not isinstance(closed_by, Mapping)
        or closed_by.get("login") != config.terminal_close_marker.closed_by
        or config.terminal_close_marker.label not in label_names
    ):
        raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
    closed_at = _parse_github_time(issue.get("closed_at"))
    created_at = _parse_github_time(issue.get("created_at"))
    updated_at = _parse_github_time(issue.get("updated_at"))
    if not created_at <= closed_at <= updated_at:
        raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
    return True


def _complete_signed_catalog_history(
    *,
    config: CatalogRequesterBrokerConfigV1,
    client: CatalogBrokerGithubClient,
    campaign_key: str,
    campaign_definition_sha256: str,
    prompt_sha256: str,
    observed_at: datetime,
) -> tuple[_CatalogHistoryRecord, ...]:
    token = client.installation_token()
    public_key_pem = client._private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    first_path = (
        client._issues_path
        + "?state=all&sort=created&direction=desc&per_page=100"
    )
    path: str | None = first_path
    seen_pages: set[str] = set()
    seen_issues: set[int] = set()
    previous_created_at: datetime | None = None
    records: list[_CatalogHistoryRecord] = []
    pages = 0
    now = _utc(observed_at)
    while path is not None:
        if path in seen_pages or pages >= 1_000:
            raise ValueError("REQUESTER_HISTORY_INVENTORY_INCOMPLETE")
        expected_path = first_path if pages == 0 else f"{first_path}&page={pages + 1}"
        if path != expected_path:
            raise ValueError("REQUESTER_HISTORY_INVENTORY_INCOMPLETE")
        seen_pages.add(path)
        pages += 1
        response = client.request_fixed("GET", path, token=token)
        if response.status_code != 200 or not isinstance(response.json_body, list):
            raise ValueError("REQUESTER_HISTORY_INVENTORY_INCOMPLETE")
        for issue in response.json_body:
            if not isinstance(issue, Mapping):
                raise ValueError("REQUESTER_HISTORY_INVENTORY_INCOMPLETE")
            issue_number = issue.get("number")
            if (
                isinstance(issue_number, bool)
                or not isinstance(issue_number, int)
                or issue_number < 1
                or issue_number in seen_issues
            ):
                raise ValueError("REQUESTER_HISTORY_INVENTORY_INCOMPLETE")
            created_at = _parse_github_time(issue.get("created_at"))
            updated_at = _parse_github_time(issue.get("updated_at"))
            if (
                created_at > now
                or updated_at < created_at
                or updated_at > now
                or (
                    previous_created_at is not None
                    and created_at > previous_created_at
                )
            ):
                raise ValueError("REQUESTER_HISTORY_INVENTORY_INCOMPLETE")
            seen_issues.add(issue_number)
            previous_created_at = created_at
            user = issue.get("user")
            actor = user.get("login") if isinstance(user, Mapping) else None
            title = issue.get("title")
            body = issue.get("body")
            if actor != client.expected_actor or not (
                isinstance(title, str)
                and title.startswith("[AURORA CATALOG RUN REQUEST] ")
            ):
                continue
            if not isinstance(body, str):
                raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
            try:
                request = parse_catalog_run_request(
                    title,
                    body,
                    trusted_public_key=public_key_pem,
                )
            except ValueError as exc:
                raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID") from exc
            if request.campaign_key != campaign_key:
                continue
            if (
                request.campaign_definition_sha256
                != campaign_definition_sha256
                or request.prompt_sha256 != prompt_sha256
                or issue.get("html_url")
                != f"https://github.com/{config.repository}/issues/{issue_number}"
            ):
                raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
            ticket = CatalogLaunchTicketV1(
                schema_version="1",
                request_id=request.request_id,
                campaign_key=request.campaign_key,
                launch_generation=request.launch_generation,
                campaign_definition_sha256=request.campaign_definition_sha256,
                prompt_sha256=request.prompt_sha256,
                previous_terminal_request_sha256=(
                    request.previous_terminal_request_sha256
                ),
            )
            if ticket.launch_ticket_sha256 != request.launch_ticket_sha256:
                raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
            records.append(
                _CatalogHistoryRecord(
                    issue_number=issue_number,
                    title=title,
                    body=body,
                    request=request,
                    ticket=ticket,
                    created_at=created_at,
                    updated_at=updated_at,
                    terminal=_history_issue_terminal(issue, config=config),
                )
            )
        try:
            next_path = _next_listing_path(response, client=client)
        except ValueError as exc:
            raise ValueError("REQUESTER_HISTORY_INVENTORY_INCOMPLETE") from exc
        if next_path is not None and len(response.json_body) < 100:
            raise ValueError("REQUESTER_HISTORY_INVENTORY_INCOMPLETE")
        path = next_path

    ordered = tuple(sorted(records, key=lambda item: item.request.launch_generation))
    if not ordered:
        return ()
    generations = tuple(item.request.launch_generation for item in ordered)
    if generations != tuple(range(1, len(ordered) + 1)):
        raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
    if len({item.issue_number for item in ordered}) != len(ordered) or len(
        {item.request.request_sha256 for item in ordered}
    ) != len(ordered):
        raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
    for index, item in enumerate(ordered):
        predecessor = None if index == 0 else ordered[index - 1].request.request_sha256
        if item.request.previous_terminal_request_sha256 != predecessor:
            raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
        if index < len(ordered) - 1 and not item.terminal:
            raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
        if index > 0 and (
            item.created_at < ordered[index - 1].created_at
            or item.issue_number <= ordered[index - 1].issue_number
        ):
            raise ValueError("REQUESTER_HISTORY_CHAIN_INVALID")
    return ordered


def _history_processing_record(
    record: _CatalogHistoryRecord,
) -> CatalogBrokerProcessingRecordV1:
    unsigned = CatalogBrokerProcessingRecordV1.model_construct(
        schema_version="1",
        stage="signed_before_post",
        title=record.title,
        body=record.body,
        intent_sha256=record.request.intent_sha256,
        request_sha256=record.request.request_sha256,
        request=record.request,
        signed_at=record.created_at,
        processing_record_sha256="0" * 64,
    )
    return CatalogBrokerProcessingRecordV1.model_validate(
        unsigned.model_copy(
            update={"processing_record_sha256": canonical_sha256(unsigned)}
        ).model_dump(mode="json")
    )


def _exclusive_model_or_exact(path: Path, model: FrozenModel) -> None:
    data = canonical_model_bytes(model) + b"\n"
    if _exclusive_write(path, data):
        return
    if path.read_bytes() != data:
        raise ValueError("REQUESTER_HISTORY_LOCAL_STATE_CONFLICT")


def reconstruct_catalog_campaign_journal_from_github(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    client: CatalogBrokerGithubClient,
    campaign_key: str,
    campaign_definition_sha256: str,
    prompt_sha256: str,
    observed_at: datetime,
) -> CatalogLaunchTicketV1 | None:
    """Rebuild only one complete, cryptographically verified campaign chain."""

    root = broker_root.resolve(strict=True)
    statuses = _broker_directory(root, config.broker.campaign_status)
    tickets = _broker_directory(root, config.broker.launch_tickets)
    processing = _broker_directory(root, config.broker.processing)
    journal_path = statuses / f"{campaign_key}.journal.json"
    ticket_path = tickets / f"{campaign_key}.ticket.json"
    if journal_path.exists() or journal_path.is_symlink():
        raise ValueError("REQUESTER_HISTORY_LOCAL_STATE_CONFLICT")
    if ticket_path.exists() or ticket_path.is_symlink():
        raise ValueError("REQUESTER_HISTORY_LOCAL_STATE_CONFLICT")
    history = _complete_signed_catalog_history(
        config=config,
        client=client,
        campaign_key=campaign_key,
        campaign_definition_sha256=campaign_definition_sha256,
        prompt_sha256=prompt_sha256,
        observed_at=observed_at,
    )
    now = _utc(observed_at)
    if not history:
        candidate = _new_launch_ticket(
            campaign_key=campaign_key,
            campaign_definition_sha256=campaign_definition_sha256,
            prompt_sha256=prompt_sha256,
        )
        return _ensure_one_launch_ticket(
            broker_root=root,
            config=config,
            candidate=candidate,
            observed_at=now,
        )
    if (
        campaign_key == config.bootstrap_qualification.campaign_key
        and len(history) > config.bootstrap_qualification.maximum_posts
    ):
        raise ValueError("REQUESTER_QUALIFICATION_HISTORY_INVALID")

    for record in history:
        if not record.terminal:
            continue
        archived = _ticket_journal(
            ticket=record.ticket,
            state="terminal",
            submission_key_sha256=record.request.intent.submission_key_sha256,
            request_sha256=record.request.request_sha256,
            issue_number=record.issue_number,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        _exclusive_model_or_exact(
            statuses
            / (
                f"{campaign_key}.generation-"
                f"{record.request.launch_generation:010d}.terminal.json"
            ),
            archived,
        )

    latest = history[-1]
    if not latest.terminal:
        active = _ticket_journal(
            ticket=latest.ticket,
            state="active",
            submission_key_sha256=latest.request.intent.submission_key_sha256,
            request_sha256=latest.request.request_sha256,
            issue_number=latest.issue_number,
            created_at=latest.created_at,
            updated_at=now,
        )
        if not _exclusive_write(
            journal_path,
            canonical_model_bytes(active) + b"\n",
        ):
            raise ValueError("REQUESTER_HISTORY_LOCAL_STATE_CONFLICT")
        _exclusive_model_or_exact(
            processing
            / f"{latest.request.intent.submission_key_sha256}.ticket.json",
            latest.ticket,
        )
        _exclusive_model_or_exact(
            processing
            / f"{latest.request.intent.submission_key_sha256}.signed.json",
            _history_processing_record(latest),
        )
        receipt = _submitted_receipt(
            signed=_history_processing_record(latest),
            issue_number=latest.issue_number,
            observed_at=now,
        )
        persist_catalog_requester_receipt(
            broker_root=root,
            config=config,
            receipt=receipt,
        )
        _write_campaign_status(
            broker_root=root,
            config=config,
            journal=active,
            last_github_checked_at=now,
            status_updated_at=now,
        )
        _load_or_create_poll_state(
            broker_root=root,
            config=config,
            journal=active,
        )
        return None

    if campaign_key == config.bootstrap_qualification.campaign_key:
        terminal = _ticket_journal(
            ticket=latest.ticket,
            state="terminal",
            submission_key_sha256=latest.request.intent.submission_key_sha256,
            request_sha256=latest.request.request_sha256,
            issue_number=latest.issue_number,
            created_at=latest.created_at,
            updated_at=latest.updated_at,
        )
        if not _exclusive_write(
            journal_path,
            canonical_model_bytes(terminal) + b"\n",
        ):
            raise ValueError("REQUESTER_HISTORY_LOCAL_STATE_CONFLICT")
        _exclusive_model_or_exact(
            processing
            / f"{latest.request.intent.submission_key_sha256}.ticket.json",
            latest.ticket,
        )
        signed = _history_processing_record(latest)
        _exclusive_model_or_exact(
            processing
            / f"{latest.request.intent.submission_key_sha256}.signed.json",
            signed,
        )
        persist_catalog_requester_receipt(
            broker_root=root,
            config=config,
            receipt=_submitted_receipt(
                signed=signed,
                issue_number=latest.issue_number,
                observed_at=now,
            ),
        )
        _write_campaign_status(
            broker_root=root,
            config=config,
            journal=terminal,
            last_github_checked_at=now,
            status_updated_at=now,
        )
        return None

    next_ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=str(_uuid7()),
        campaign_key=campaign_key,
        launch_generation=latest.request.launch_generation + 1,
        campaign_definition_sha256=campaign_definition_sha256,
        prompt_sha256=prompt_sha256,
        previous_terminal_request_sha256=latest.request.request_sha256,
    )
    return _ensure_one_launch_ticket(
        broker_root=root,
        config=config,
        candidate=next_ticket,
        observed_at=now,
    )


def _submitted_receipt(
    *,
    signed: CatalogBrokerProcessingRecordV1,
    issue_number: int,
    observed_at: datetime,
) -> CatalogRequesterReceiptV1:
    return CatalogRequesterReceiptV1.create(
        status="submitted",
        reason_code="REQUEST_SUBMITTED",
        submission_key_sha256=signed.request.intent.submission_key_sha256,
        request_id=signed.request.request_id,
        campaign_key=signed.request.campaign_key,
        launch_generation=signed.request.launch_generation,
        issue_number=issue_number,
        request_sha256=signed.request_sha256,
        observed_at=_utc(observed_at),
    )


def reconcile_catalog_request_to_github(
    *,
    signed: CatalogBrokerProcessingRecordV1,
    client: CatalogBrokerGithubClient,
    post_lower_bound: datetime,
    post_upper_bound: datetime | None = None,
    installation_token: str | None = None,
) -> CatalogRequesterReceiptV1:
    """Search only; this recovery path is structurally unable to POST an issue."""

    checked = CatalogBrokerProcessingRecordV1.model_validate_json(
        canonical_model_bytes(signed)
    )
    token = installation_token or client.installation_token()
    upper_bound = _utc(post_upper_bound or client.now())
    issue_number = _reconcile_uncertain_post(
        signed=checked,
        client=client,
        token=token,
        post_lower_bound=post_lower_bound,
        post_upper_bound=upper_bound,
    )
    return _submitted_receipt(
        signed=checked,
        issue_number=issue_number,
        observed_at=upper_bound,
    )


def persist_catalog_requester_receipt(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    receipt: CatalogRequesterReceiptV1,
) -> CatalogRequesterReceiptV1:
    receipts = _broker_directory(
        broker_root.resolve(strict=True), config.broker.receipts
    )
    path = receipts / f"{receipt.submission_key_sha256}.receipt.json"
    data = canonical_model_bytes(receipt) + b"\n"
    if not path.exists() and not path.is_symlink():
        _atomic_replace(path, data)
        return receipt
    if path.is_symlink():
        raise ValueError("REQUESTER_RECEIPT_INVALID")
    existing_data = path.read_bytes()
    try:
        existing = CatalogRequesterReceiptV1.model_validate_json(existing_data[:-1])
    except Exception as exc:
        raise ValueError("REQUESTER_RECEIPT_INVALID") from exc
    if existing_data != canonical_model_bytes(existing) + b"\n" or existing != receipt:
        raise ValueError("REQUESTER_RECEIPT_CONFLICT")
    return existing


def _poll_state_path(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    campaign_key: str,
) -> Path:
    statuses = _broker_directory(
        broker_root.resolve(strict=True), config.broker.campaign_status
    )
    return statuses / f"{campaign_key}.terminal-poll.json"


def _repair_active_campaign_local_state(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    journal: CatalogBrokerTicketJournalV1,
) -> None:
    if (
        journal.state != "active"
        or journal.submission_key_sha256 is None
        or journal.request_sha256 is None
        or journal.issue_number is None
    ):
        raise ValueError("REQUESTER_TERMINAL_CONTEXT_INVALID")
    root = broker_root.resolve(strict=True)
    processing = _broker_directory(root, config.broker.processing)
    submission_key = journal.submission_key_sha256
    signed = _read_canonical_model(
        processing / f"{submission_key}.signed.json",
        CatalogBrokerProcessingRecordV1,
        maximum_bytes=64_000,
    )
    if not isinstance(signed, CatalogBrokerProcessingRecordV1) or (
        signed.request.intent.submission_key_sha256 != submission_key
        or signed.request_sha256 != journal.request_sha256
        or signed.request.launch_ticket_sha256
        != journal.ticket.launch_ticket_sha256
    ):
        raise ValueError("REQUESTER_TERMINAL_CONTEXT_INVALID")
    _exclusive_model_or_exact(
        processing / f"{submission_key}.ticket.json",
        journal.ticket,
    )
    receipt = _submitted_receipt(
        signed=signed,
        issue_number=journal.issue_number,
        observed_at=journal.updated_at,
    )
    persist_catalog_requester_receipt(
        broker_root=root,
        config=config,
        receipt=receipt,
    )
    poll = _load_or_create_poll_state(
        broker_root=root,
        config=config,
        journal=journal,
    )
    _write_campaign_status(
        broker_root=root,
        config=config,
        journal=journal,
        last_github_checked_at=poll.last_github_checked_at,
        status_updated_at=journal.updated_at,
    )


def _initial_poll_state(
    *,
    journal: CatalogBrokerTicketJournalV1,
    config: CatalogRequesterBrokerConfigV1,
    observed_at: datetime,
) -> CatalogBrokerTerminalPollStateV1:
    if (
        journal.state != "active"
        or journal.submission_key_sha256 is None
        or journal.request_sha256 is None
        or journal.issue_number is None
    ):
        raise ValueError("REQUESTER_TERMINAL_CONTEXT_INVALID")
    minimum = config.broker.terminal_reconcile_min_seconds
    stagger = int(
        hashlib.sha256(journal.campaign_key.encode("ascii")).hexdigest()[:8],
        16,
    ) % minimum
    checked = _utc(observed_at)
    return _terminal_poll_state(
        campaign_key=journal.campaign_key,
        launch_generation=journal.launch_generation,
        submission_key_sha256=journal.submission_key_sha256,
        request_sha256=journal.request_sha256,
        issue_number=journal.issue_number,
        last_github_checked_at=checked,
        next_github_check_at=checked + timedelta(seconds=minimum + stagger),
        backoff_seconds=minimum,
        etag=None,
        last_hint_sha256=None,
    )


def _load_or_create_poll_state(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    journal: CatalogBrokerTicketJournalV1,
) -> CatalogBrokerTerminalPollStateV1:
    path = _poll_state_path(
        broker_root=broker_root,
        config=config,
        campaign_key=journal.campaign_key,
    )
    if path.exists():
        state = _read_canonical_model(
            path,
            CatalogBrokerTerminalPollStateV1,
            maximum_bytes=16_384,
        )
        if not isinstance(state, CatalogBrokerTerminalPollStateV1):
            raise ValueError("REQUESTER_TERMINAL_POLL_STATE_INVALID")
    else:
        state = _initial_poll_state(
            journal=journal,
            config=config,
            observed_at=journal.updated_at,
        )
        if not _exclusive_write(path, canonical_model_bytes(state) + b"\n"):
            return _load_or_create_poll_state(
                broker_root=broker_root,
                config=config,
                journal=journal,
            )
    if (
        state.campaign_key != journal.campaign_key
        or state.launch_generation != journal.launch_generation
        or state.submission_key_sha256 != journal.submission_key_sha256
        or state.request_sha256 != journal.request_sha256
        or state.issue_number != journal.issue_number
    ):
        raise ValueError("REQUESTER_TERMINAL_POLL_STATE_INVALID")
    return state


def _persist_poll_state(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    state: CatalogBrokerTerminalPollStateV1,
) -> None:
    path = _poll_state_path(
        broker_root=broker_root,
        config=config,
        campaign_key=state.campaign_key,
    )
    _atomic_replace(path, canonical_model_bytes(state) + b"\n")


def _retire_obsolete_terminal_poll_state(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    successor_journal: CatalogBrokerTicketJournalV1,
) -> None:
    path = _poll_state_path(
        broker_root=broker_root,
        config=config,
        campaign_key=successor_journal.campaign_key,
    )
    if not path.exists() and not path.is_symlink():
        return
    state = _read_canonical_model(
        path,
        CatalogBrokerTerminalPollStateV1,
        maximum_bytes=16_384,
    )
    if not isinstance(state, CatalogBrokerTerminalPollStateV1):
        raise ValueError("REQUESTER_TERMINAL_POLL_STATE_INVALID")
    advances_generation = (
        successor_journal.state == "available"
        and state.launch_generation < successor_journal.launch_generation
        and state.request_sha256
        == successor_journal.ticket.previous_terminal_request_sha256
    )
    seals_qualification = (
        successor_journal.state == "terminal"
        and state.launch_generation == successor_journal.launch_generation
        and state.request_sha256 == successor_journal.request_sha256
    )
    if (
        state.campaign_key != successor_journal.campaign_key
        or not (advances_generation or seals_qualification)
    ):
        raise ValueError("REQUESTER_TERMINAL_POLL_STATE_INVALID")
    statuses = _broker_directory(
        broker_root.resolve(strict=True), config.broker.campaign_status
    )
    archive = statuses / (
        f"{state.campaign_key}.generation-{state.launch_generation:010d}."
        "terminal-poll.json"
    )
    if not archive.exists() and not archive.is_symlink():
        os.rename(path, archive)
        return
    archived = _read_canonical_model(
        archive,
        CatalogBrokerTerminalPollStateV1,
        maximum_bytes=16_384,
    )
    if not isinstance(archived, CatalogBrokerTerminalPollStateV1) or (
        archived.campaign_key != state.campaign_key
        or archived.launch_generation != state.launch_generation
        or archived.request_sha256 != state.request_sha256
        or archived.issue_number != state.issue_number
    ):
        raise ValueError("REQUESTER_TERMINAL_POLL_ARCHIVE_CONFLICT")
    processing = _broker_directory(
        broker_root.resolve(strict=True), config.broker.processing
    )
    redundant = processing / f"retired-{state.poll_state_sha256}.poll-state"
    if redundant.exists() or redundant.is_symlink():
        if redundant.read_bytes() != canonical_model_bytes(state) + b"\n":
            raise ValueError("REQUESTER_TERMINAL_POLL_ARCHIVE_CONFLICT")
        redundant = processing / (
            f"retired-{state.poll_state_sha256}-{uuid.uuid4().hex}.poll-state"
        )
    os.rename(path, redundant)


def _reserve_terminal_exact_get(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    observed_at: datetime,
) -> bool:
    processing = _broker_directory(
        broker_root.resolve(strict=True), config.broker.processing
    )
    path = processing / "terminal-reconcile-rate-v1.json"
    now = _utc(observed_at)
    retained: tuple[datetime, ...] = ()
    if path.exists():
        current = _read_canonical_model(
            path,
            CatalogBrokerTerminalRateWindowV1,
            maximum_bytes=16_384,
        )
        if not isinstance(current, CatalogBrokerTerminalRateWindowV1):
            raise ValueError("REQUESTER_TERMINAL_RATE_STATE_INVALID")
        if any(item > now for item in current.reserved_at):
            raise ValueError("REQUESTER_TERMINAL_RATE_STATE_INVALID")
        retained = tuple(
            item
            for item in current.reserved_at
            if item > now - timedelta(minutes=1)
        )
    if len(retained) >= config.broker.terminal_reconcile_max_gets_per_minute:
        return False
    updated = _terminal_rate_window((*retained, now))
    if path.exists():
        _atomic_replace(path, canonical_model_bytes(updated) + b"\n")
    elif not _exclusive_write(path, canonical_model_bytes(updated) + b"\n"):
        return _reserve_terminal_exact_get(
            broker_root=broker_root,
            config=config,
            observed_at=now,
        )
    return True


def _mark_ticket_journal_active(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    receipt: CatalogRequesterReceiptV1,
) -> None:
    statuses = _broker_directory(
        broker_root.resolve(strict=True), config.broker.campaign_status
    )
    path = statuses / f"{receipt.campaign_key}.journal.json"
    journal = _load_ticket_journal(path)
    if journal.state == "active":
        if (
            journal.submission_key_sha256 != receipt.submission_key_sha256
            or journal.request_sha256 != receipt.request_sha256
            or journal.issue_number != receipt.issue_number
        ):
            raise ValueError("REQUESTER_TICKET_JOURNAL_CONFLICT")
        _write_campaign_status(
            broker_root=broker_root,
            config=config,
            journal=journal,
        )
        _load_or_create_poll_state(
            broker_root=broker_root,
            config=config,
            journal=journal,
        )
        return
    if (
        journal.state != "consumed"
        or journal.submission_key_sha256 != receipt.submission_key_sha256
        or receipt.request_sha256 is None
        or receipt.issue_number is None
    ):
        raise ValueError("REQUESTER_TICKET_JOURNAL_CONFLICT")
    active = _transition_ticket_journal(
        journal,
        state="active",
        submission_key_sha256=receipt.submission_key_sha256,
        request_sha256=receipt.request_sha256,
        issue_number=receipt.issue_number,
        updated_at=receipt.observed_at,
    )
    _atomic_replace(path, canonical_model_bytes(active) + b"\n")
    _write_campaign_status(
        broker_root=broker_root,
        config=config,
        journal=active,
    )
    _load_or_create_poll_state(
        broker_root=broker_root,
        config=config,
        journal=active,
    )


def advance_catalog_ticket_after_verified_terminal(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    signed: CatalogBrokerProcessingRecordV1,
    issue: Mapping[str, object],
    expected_requester_actor: str,
    observed_at: datetime,
) -> CatalogLaunchTicketV1 | None:
    """Advance exactly one generation only from the configured terminal marker."""

    root = broker_root.resolve(strict=True)
    statuses = _broker_directory(root, config.broker.campaign_status)
    journal_path = statuses / f"{signed.request.campaign_key}.journal.json"
    journal = _load_ticket_journal(journal_path)
    if journal.launch_generation > signed.request.launch_generation:
        if (
            journal.state == "available"
            and journal.ticket.previous_terminal_request_sha256
            == signed.request_sha256
        ):
            ensured = _ensure_one_launch_ticket(
                broker_root=root,
                config=config,
                candidate=journal.ticket,
                observed_at=observed_at,
            )
            if ensured is None:
                raise ValueError("REQUESTER_NEXT_TICKET_UNPROVEN")
            return ensured
        raise ValueError("REQUESTER_TICKET_GENERATION_CONFLICT")
    if (
        journal.state != "active"
        or journal.launch_generation != signed.request.launch_generation
        or journal.submission_key_sha256
        != signed.request.intent.submission_key_sha256
        or journal.request_sha256 != signed.request_sha256
        or journal.issue_number is None
    ):
        raise ValueError("REQUESTER_TERMINAL_CONTEXT_INVALID")

    user = issue.get("user")
    closed_by = issue.get("closed_by")
    labels = issue.get("labels")
    label_names = {
        item.get("name")
        for item in labels
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    } if isinstance(labels, list) else set()
    created_at = _parse_github_time(issue.get("created_at"))
    updated_at = _parse_github_time(issue.get("updated_at"))
    closed_at = _parse_github_time(issue.get("closed_at"))
    expected_url = (
        f"https://github.com/{config.repository}/issues/{journal.issue_number}"
    )
    if (
        issue.get("number") != journal.issue_number
        or not isinstance(user, Mapping)
        or user.get("login") != expected_requester_actor
        or issue.get("title") != signed.title
        or issue.get("body") != signed.body
        or issue.get("html_url") != expected_url
        or issue.get("state") != config.terminal_close_marker.state
        or issue.get("state_reason") != config.terminal_close_marker.state_reason
        or not isinstance(closed_by, Mapping)
        or closed_by.get("login") != config.terminal_close_marker.closed_by
        or config.terminal_close_marker.label not in label_names
        or not created_at <= closed_at <= updated_at <= _utc(observed_at)
    ):
        raise ValueError("REQUESTER_TERMINAL_MARKER_INVALID")

    terminal_candidate = _transition_ticket_journal(
        journal,
        state="terminal",
        submission_key_sha256=journal.submission_key_sha256,
        request_sha256=journal.request_sha256,
        issue_number=journal.issue_number,
        updated_at=observed_at,
    )
    archive_path = statuses / (
        f"{journal.campaign_key}.generation-{journal.launch_generation:010d}."
        "terminal.json"
    )
    if archive_path.exists():
        archived = _load_ticket_journal(archive_path)
        if (
            archived.state != "terminal"
            or archived.ticket != journal.ticket
            or archived.request_sha256 != journal.request_sha256
            or archived.issue_number != journal.issue_number
        ):
            raise ValueError("REQUESTER_TERMINAL_ARCHIVE_CONFLICT")
    elif not _exclusive_write(
        archive_path,
        canonical_model_bytes(terminal_candidate) + b"\n",
    ):
        raise ValueError("REQUESTER_TERMINAL_ARCHIVE_CONFLICT")

    if journal.campaign_key == config.bootstrap_qualification.campaign_key:
        _atomic_replace(
            journal_path,
            canonical_model_bytes(terminal_candidate) + b"\n",
        )
        _write_campaign_status(
            broker_root=root,
            config=config,
            journal=terminal_candidate,
            last_github_checked_at=observed_at,
            status_updated_at=observed_at,
        )
        return None

    next_ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=str(_uuid7()),
        campaign_key=journal.campaign_key,
        launch_generation=journal.launch_generation + 1,
        campaign_definition_sha256=journal.ticket.campaign_definition_sha256,
        prompt_sha256=journal.ticket.prompt_sha256,
        previous_terminal_request_sha256=signed.request_sha256,
    )
    next_journal = _ticket_journal(
        ticket=next_ticket,
        state="available",
        submission_key_sha256=None,
        request_sha256=None,
        issue_number=None,
        created_at=observed_at,
        updated_at=observed_at,
    )
    _atomic_replace(
        journal_path,
        canonical_model_bytes(next_journal) + b"\n",
    )
    ensured = _ensure_one_launch_ticket(
        broker_root=root,
        config=config,
        candidate=next_ticket,
        observed_at=observed_at,
    )
    if ensured is None:
        raise ValueError("REQUESTER_NEXT_TICKET_UNPROVEN")
    return ensured


def _response_etag(response: CatalogBrokerHttpResponse) -> str | None:
    values = [
        value
        for key, value in response.headers.items()
        if key.casefold() == "etag"
    ]
    if len(values) > 1:
        raise ValueError("REQUESTER_TERMINAL_ETAG_INVALID")
    if not values:
        return None
    value = values[0]
    if not value or len(value) > 256 or "\r" in value or "\n" in value:
        raise ValueError("REQUESTER_TERMINAL_ETAG_INVALID")
    return value


def _updated_poll_state_after_get(
    *,
    state: CatalogBrokerTerminalPollStateV1,
    config: CatalogRequesterBrokerConfigV1,
    observed_at: datetime,
    etag: str | None,
    hint_sha256: str | None,
) -> CatalogBrokerTerminalPollStateV1:
    backoff = min(
        config.broker.terminal_reconcile_max_seconds,
        max(
            config.broker.terminal_reconcile_min_seconds,
            state.backoff_seconds * 2,
        ),
    )
    now = _utc(observed_at)
    return _terminal_poll_state(
        campaign_key=state.campaign_key,
        launch_generation=state.launch_generation,
        submission_key_sha256=state.submission_key_sha256,
        request_sha256=state.request_sha256,
        issue_number=state.issue_number,
        last_github_checked_at=now,
        next_github_check_at=now + timedelta(seconds=backoff),
        backoff_seconds=backoff,
        etag=state.etag if etag is None else etag,
        last_hint_sha256=(
            state.last_hint_sha256 if hint_sha256 is None else hint_sha256
        ),
    )


def reconcile_active_catalog_campaign(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    client: CatalogBrokerGithubClient,
    campaign_key: str,
    observed_at: datetime,
    hint: CatalogRequesterReconcileHintV1 | None = None,
) -> CatalogLaunchTicketV1 | None:
    """Perform at most one rate-limited exact-issue terminal check."""

    root = broker_root.resolve(strict=True)
    statuses = _broker_directory(root, config.broker.campaign_status)
    journal_path = statuses / f"{campaign_key}.journal.json"
    journal = _load_ticket_journal(journal_path)
    if journal.state != "active":
        return None
    if journal.submission_key_sha256 is None:
        raise ValueError("REQUESTER_TERMINAL_CONTEXT_INVALID")
    poll = _load_or_create_poll_state(
        broker_root=root,
        config=config,
        journal=journal,
    )
    now = _utc(observed_at)
    hint_eligible = False
    if hint is not None:
        status_path = statuses / f"{campaign_key}.status.json"
        status = _read_canonical_model(
            status_path,
            CatalogRequesterCampaignStatusV1,
            maximum_bytes=config.broker.maximum_request_bytes,
        )
        if not isinstance(status, CatalogRequesterCampaignStatusV1):
            raise ValueError("REQUESTER_BROKER_RECONCILE_HINT_INVALID")
        if (
            hint.campaign_key != journal.campaign_key
            or hint.launch_generation != journal.launch_generation
            or hint.launch_ticket_sha256 != journal.ticket.launch_ticket_sha256
            or hint.submission_key_sha256 != journal.submission_key_sha256
            or hint.request_id != journal.ticket.request_id
            or hint.request_sha256 != journal.request_sha256
            or hint.issue_number != journal.issue_number
            or hint.status_sha256 != status.status_sha256
            or hint.last_github_checked_at != status.last_github_checked_at
            or hint.hint_sha256 == poll.last_hint_sha256
        ):
            return None
        hint_eligible = (
            now - poll.last_github_checked_at
        ).total_seconds() >= config.broker.terminal_reconcile_min_seconds
    if now < poll.next_github_check_at and not hint_eligible:
        return None
    if not _reserve_terminal_exact_get(
        broker_root=root,
        config=config,
        observed_at=now,
    ):
        return None

    signed_path = (
        _broker_directory(root, config.broker.processing)
        / f"{journal.submission_key_sha256}.signed.json"
    )
    signed = _read_canonical_model(
        signed_path,
        CatalogBrokerProcessingRecordV1,
        maximum_bytes=64_000,
    )
    if not isinstance(signed, CatalogBrokerProcessingRecordV1) or (
        signed.request.campaign_key != journal.campaign_key
        or signed.request.launch_generation != journal.launch_generation
        or signed.request_sha256 != journal.request_sha256
        or signed.request.intent.submission_key_sha256
        != journal.submission_key_sha256
    ):
        raise ValueError("REQUESTER_TERMINAL_CONTEXT_INVALID")
    token = client.installation_token()
    response = client.request_fixed(
        "GET",
        f"{client._issues_path}/{journal.issue_number}",
        token=token,
        if_none_match=poll.etag,
    )
    if response.status_code in {404, 410}:
        unavailable_poll = _updated_poll_state_after_get(
            state=poll,
            config=config,
            observed_at=now,
            etag=poll.etag,
            hint_sha256=None if hint is None else hint.hint_sha256,
        )
        _persist_poll_state(
            broker_root=root,
            config=config,
            state=unavailable_poll,
        )
        _write_campaign_status(
            broker_root=root,
            config=config,
            journal=journal,
            last_github_checked_at=now,
            status_updated_at=now,
        )
        return None
    if response.status_code not in {200, 304}:
        raise ValueError("REQUESTER_TERMINAL_READBACK_UNPROVEN")
    etag = _response_etag(response)
    updated_poll = _updated_poll_state_after_get(
        state=poll,
        config=config,
        observed_at=now,
        etag=etag,
        hint_sha256=None if hint is None else hint.hint_sha256,
    )
    if response.status_code == 304:
        _persist_poll_state(
            broker_root=root,
            config=config,
            state=updated_poll,
        )
        _write_campaign_status(
            broker_root=root,
            config=config,
            journal=journal,
            last_github_checked_at=now,
            status_updated_at=now,
        )
        return None
    issue_number = _verify_issue(
        response.json_body,
        signed=signed,
        expected_actor=client.expected_actor,
        post_lower_bound=signed.signed_at,
        post_upper_bound=now,
        repository=config.repository,
    )
    if issue_number != journal.issue_number:
        raise ValueError("REQUESTER_TERMINAL_READBACK_UNPROVEN")
    if not isinstance(response.json_body, Mapping):
        raise ValueError("REQUESTER_TERMINAL_READBACK_UNPROVEN")
    if response.json_body.get("state") == "open":
        _persist_poll_state(
            broker_root=root,
            config=config,
            state=updated_poll,
        )
        _write_campaign_status(
            broker_root=root,
            config=config,
            journal=journal,
            last_github_checked_at=now,
            status_updated_at=now,
        )
        return None
    try:
        next_ticket = advance_catalog_ticket_after_verified_terminal(
            broker_root=root,
            config=config,
            signed=signed,
            issue=response.json_body,
            expected_requester_actor=client.expected_actor,
            observed_at=now,
        )
    except ValueError as exc:
        if str(exc) == "REQUESTER_TERMINAL_MARKER_INVALID":
            rejected_terminal_poll = _updated_poll_state_after_get(
                state=poll,
                config=config,
                observed_at=now,
                etag=poll.etag,
                hint_sha256=None if hint is None else hint.hint_sha256,
            )
            _persist_poll_state(
                broker_root=root,
                config=config,
                state=rejected_terminal_poll,
            )
            _write_campaign_status(
                broker_root=root,
                config=config,
                journal=journal,
                last_github_checked_at=now,
                status_updated_at=now,
            )
            return None
        raise
    successor = _load_ticket_journal(journal_path)
    _retire_obsolete_terminal_poll_state(
        broker_root=root,
        config=config,
        successor_journal=successor,
    )
    return next_ticket


def process_claimed_catalog_reconcile_hint(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    claimed_path: Path,
    client: CatalogBrokerGithubClient,
    observed_at: datetime,
) -> CatalogLaunchTicketV1 | None:
    """Validate, use at most once, and retire one claimed client hint."""

    try:
        hint = load_claimed_catalog_reconcile_hint(
            claimed_path=claimed_path,
            config=config,
        )
    except ValueError:
        quarantine_invalid_claimed_catalog_request(
            broker_root=broker_root,
            config=config,
            claimed_path=claimed_path,
            reason_code="REQUESTER_BROKER_RECONCILE_HINT_INVALID",
            observed_at=observed_at,
        )
        return None
    try:
        return reconcile_active_catalog_campaign(
            broker_root=broker_root,
            config=config,
            client=client,
            campaign_key=hint.campaign_key,
            observed_at=observed_at,
            hint=hint,
        )
    finally:
        if claimed_path.exists():
            processing = _broker_directory(
                broker_root.resolve(strict=True), config.broker.processing
            )
            retired = processing / f"processed-{hint.hint_sha256}.hint"
            if retired.exists() or retired.is_symlink():
                metadata = retired.stat(follow_symlinks=False)
                expected = canonical_model_bytes(hint) + b"\n"
                if (
                    retired.is_symlink()
                    or not stat.S_ISREG(metadata.st_mode)
                    or _is_reparse_stat(metadata)
                    or getattr(metadata, "st_nlink", 1) != 1
                    or metadata.st_size != len(expected)
                    or retired.read_bytes() != expected
                ):
                    raise ValueError("REQUESTER_BROKER_HINT_REPLAY")
                os.replace(claimed_path, retired)
            else:
                os.rename(claimed_path, retired)


def submit_catalog_request_to_github(
    *,
    signed: CatalogBrokerProcessingRecordV1,
    client: CatalogBrokerGithubClient,
    post_lower_bound: datetime,
    post_upper_bound: datetime | None = None,
    installation_token: str | None = None,
) -> CatalogRequesterReceiptV1:
    """POST once, then read back or safely reconcile the exact signed issue."""

    checked = CatalogBrokerProcessingRecordV1.model_validate_json(
        canonical_model_bytes(signed)
    )
    token = installation_token or client.installation_token()
    issue_path = client._issues_path
    try:
        response = client.request_fixed(
            "POST",
            issue_path,
            token=token,
            json_body={"title": checked.title, "body": checked.body},
        )
    except (
        TimeoutError,
        ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
    ):
        upper_bound = _utc(post_upper_bound or client.now())
        issue_number = _reconcile_uncertain_post(
            signed=checked,
            client=client,
            token=token,
            post_lower_bound=post_lower_bound,
            post_upper_bound=upper_bound,
        )
    else:
        if response.status_code != 201 or not isinstance(response.json_body, Mapping):
            raise ValueError("REQUESTER_ISSUE_POST_UNPROVEN")
        issue_number = response.json_body.get("number")
        if isinstance(issue_number, bool) or not isinstance(issue_number, int):
            raise ValueError("REQUESTER_ISSUE_POST_UNPROVEN")
        readback = client.request_fixed(
            "GET",
            f"{issue_path}/{issue_number}",
            token=token,
        )
        if readback.status_code != 200:
            raise ValueError("REQUESTER_CREATED_ISSUE_INVALID")
        upper_bound = _utc(post_upper_bound or client.now())
        response_time = _github_response_time(readback)
        if response_time is not None:
            upper_bound = max(upper_bound, response_time)
        verified_number = _verify_issue(
            readback.json_body,
            signed=checked,
            expected_actor=client.expected_actor,
            post_lower_bound=post_lower_bound,
            post_upper_bound=upper_bound,
            repository=client.config.repository,
        )
        if verified_number != issue_number:
            raise ValueError("REQUESTER_CREATED_ISSUE_INVALID")

    return _submitted_receipt(
        signed=checked,
        issue_number=issue_number,
        observed_at=upper_bound,
    )


def process_claimed_catalog_request(
    *,
    broker_root: Path,
    config: CatalogRequesterBrokerConfigV1,
    claimed_path: Path,
    private_key_pem: bytes,
    client: CatalogBrokerGithubClient,
    observed_at: datetime,
) -> CatalogRequesterReceiptV1:
    """Process or safely reconcile one claimed draft without duplicate POSTs."""

    draft = load_claimed_catalog_draft(claimed_path=claimed_path, config=config)
    root = broker_root.resolve(strict=True)
    receipts = _broker_directory(root, config.broker.receipts)
    receipt_path = receipts / f"{draft.submission_key_sha256}.receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        try:
            existing = _read_canonical_model(
                receipt_path,
                CatalogRequesterReceiptV1,
                maximum_bytes=config.broker.maximum_request_bytes,
            )
        except (OSError, ValueError) as exc:
            raise ValueError("REQUESTER_RECEIPT_INVALID") from exc
        if (
            not isinstance(existing, CatalogRequesterReceiptV1)
            or existing.status != "submitted"
            or existing.reason_code != "REQUEST_SUBMITTED"
            or existing.submission_key_sha256 != draft.submission_key_sha256
            or existing.request_id != draft.request_id
            or existing.campaign_key != draft.campaign_key
            or existing.launch_generation != draft.launch_generation
        ):
            raise ValueError("REQUESTER_RECEIPT_INVALID")
        _retire_claimed_catalog_request(
            broker_root=root,
            config=config,
            claimed_path=claimed_path,
            draft=draft,
        )
        return existing

    processing = _broker_directory(root, config.broker.processing)
    signed_path = processing / f"{draft.submission_key_sha256}.signed.json"
    if not signed_path.exists():
        consumed_ticket = processing / f"{draft.submission_key_sha256}.ticket.json"
        if consumed_ticket.exists():
            verify_consumed_catalog_launch_ticket(
                broker_root=root,
                config=config,
                draft=draft,
                observed_at=observed_at,
            )
        else:
            verify_and_consume_catalog_launch_ticket(
                broker_root=root,
                config=config,
                draft=draft,
                observed_at=observed_at,
            )
    signed = load_or_create_signed_processing_record(
        broker_root=root,
        config=config,
        draft=draft,
        private_key_pem=private_key_pem,
        signed_at=observed_at,
    )
    # Prove GitHub identity, permissions, and repository scope before persisting
    # the one-way marker that forbids every future issue POST for this request.
    installation_token = client.installation_token()
    attempt, newly_created = load_or_create_post_attempt(
        broker_root=root,
        config=config,
        signed=signed,
        post_lower_bound=_utc(client.now()),
    )
    if newly_created:
        receipt = submit_catalog_request_to_github(
            signed=signed,
            client=client,
            post_lower_bound=attempt.post_lower_bound,
            installation_token=installation_token,
        )
    else:
        receipt = reconcile_catalog_request_to_github(
            signed=signed,
            client=client,
            post_lower_bound=attempt.post_lower_bound,
            installation_token=installation_token,
        )
    _mark_ticket_journal_active(
        broker_root=root,
        config=config,
        receipt=receipt,
    )
    persisted = persist_catalog_requester_receipt(
        broker_root=root,
        config=config,
        receipt=receipt,
    )
    _retire_claimed_catalog_request(
        broker_root=root,
        config=config,
        claimed_path=claimed_path,
        draft=draft,
    )
    return persisted


__all__ = [
    "CatalogBrokerGithubClient",
    "CatalogBrokerBootstrapSealV1",
    "CatalogBrokerHttpResponse",
    "CatalogBrokerInboxInventoryV1",
    "CatalogBrokerPostAttemptV1",
    "CatalogBrokerProcessingRecordV1",
    "CatalogBrokerRejectedEntryV1",
    "CatalogBrokerSelfAuditReceiptV1",
    "CatalogBrokerTerminalPollStateV1",
    "CatalogBrokerTerminalRateWindowV1",
    "CatalogBrokerTicketJournalV1",
    "CatalogRequesterBrokerConfigV1",
    "RequestsCatalogBrokerHttpTransport",
    "advance_catalog_ticket_after_verified_terminal",
    "claim_next_catalog_reconcile_hint",
    "claim_next_catalog_request",
    "ensure_catalog_launch_tickets",
    "inventory_catalog_broker_inbox",
    "load_claimed_catalog_draft",
    "load_claimed_catalog_reconcile_hint",
    "load_or_create_signed_processing_record",
    "load_or_create_post_attempt",
    "persist_catalog_requester_receipt",
    "publish_catalog_broker_self_audit",
    "process_claimed_catalog_reconcile_hint",
    "quarantine_invalid_claimed_catalog_request",
    "reconcile_active_catalog_campaign",
    "reconstruct_catalog_campaign_journal_from_github",
    "process_claimed_catalog_request",
    "publish_catalog_broker_capacity",
    "quarantine_one_invalid_catalog_broker_entry",
    "reconcile_catalog_request_to_github",
    "sign_catalog_request",
    "submit_catalog_request_to_github",
    "verify_and_consume_catalog_launch_ticket",
    "verify_consumed_catalog_launch_ticket",
]
