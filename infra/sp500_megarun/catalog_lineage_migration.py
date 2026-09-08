"""Installation-only preparation; no service starts, protected writes or requests."""

from datetime import datetime
import hashlib
from pathlib import Path

from .catalog_lineage_transition import CatalogLineageTransitionV1, load_lineage_transition
from .catalog_campaign_definition_contract import parse_catalog_campaign_definition_bytes
from .catalog_campaign_registry import load_catalog_campaign_registry
from .catalog_request_contract import CatalogLaunchTicketV1, CatalogRunRequestV1, canonical_model_bytes
from .catalog_requester import CatalogRequesterCampaignStatusV1, CatalogRequesterConfigV1
from .catalog_requester_broker import (
    CatalogBrokerProcessingRecordV1, CatalogBrokerTicketJournalV1, _broker_directory,
    _read_canonical_model, _ticket_journal, _utc, inventory_catalog_broker_inbox,
)
from .catalog_run_request import parse_catalog_run_request


def prepare_candidate_lineage_files(
    *, broker_root: Path, candidate_root: Path, observed_at: datetime,
) -> tuple[dict[str, object], ...]:
    """Bind migration proposals to an already verified installation candidate.

    The installer must hold consumers stopped, protect the candidate tree and
    apply all returned records in the same CAS transaction as application files.
    This function neither consumes inputs nor changes the installed state.
    """
    try:
        config = CatalogRequesterConfigV1.model_validate_json(
            (candidate_root / "config/catalog_requester_v1.json").read_bytes())
        installed_config = CatalogRequesterConfigV1.model_validate_json(
            (broker_root / "config/catalog_requester_v1.json").read_bytes())
        public = (candidate_root / "config/catalog_requester_public_key_v1.pem").read_bytes()
        if config != installed_config or public != (broker_root / "config/catalog_requester_public_key_v1.pem").read_bytes():
            raise ValueError("installed trust context changed")
        prompt_hash = hashlib.sha256(
            (candidate_root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()).hexdigest()
        registry = load_catalog_campaign_registry(candidate_root / "config/catalog_campaign_registry_v1.json")
        tickets = _broker_directory(broker_root, config.broker.launch_tickets)
        statuses = _broker_directory(broker_root, config.broker.campaign_status)
        records = []
        for entry in registry.campaigns:
            if not entry.active:
                continue
            ticket_path = tickets / f"{entry.campaign_key}.ticket.json"
            if not ticket_path.exists() and not ticket_path.is_symlink():
                if any((statuses / f"{entry.campaign_key}.{suffix}.json").exists() for suffix in ("journal", "status")):
                    raise ValueError("partial installed lineage")
                continue
            ticket = _read_canonical_model(ticket_path, CatalogLaunchTicketV1, maximum_bytes=16_384)
            if ticket.campaign_key != entry.campaign_key:
                raise ValueError("campaign mismatch")
            manifest = parse_catalog_campaign_definition_bytes(
                (candidate_root / entry.definition_manifest_path).read_bytes())
            if manifest.campaign_key != entry.campaign_key:
                raise ValueError("candidate manifest campaign mismatch")
            target = (manifest.campaign_definition_sha256, prompt_hash)
            if (ticket.campaign_definition_sha256, ticket.prompt_sha256) == target:
                continue
            approval = load_lineage_transition(candidate_root, ticket)
            if approval is None or (approval.target_definition_sha256, approval.target_prompt_sha256) != target:
                raise ValueError("candidate transition not approved")
            records.extend(prepare_available_lineage_files(broker_root=broker_root, config=config,
                transition=approval, public_key=public, observed_at=observed_at))
        return tuple(records)
    except (ValueError, TypeError, OSError) as exc:
        raise ValueError("REQUESTER_LINEAGE_CANDIDATE_INVALID") from exc


def prepare_available_lineage_models(
    *, previous_request: CatalogRunRequestV1, transition: CatalogLineageTransitionV1,
    ticket: CatalogLaunchTicketV1, journal: CatalogBrokerTicketJournalV1,
    status: CatalogRequesterCampaignStatusV1, observed_at: datetime,
) -> tuple[CatalogLaunchTicketV1, CatalogBrokerTicketJournalV1, CatalogRequesterCampaignStatusV1]:
    """Transform consistent unused state after the installer proves quiescence.

    The caller authenticates the predecessor's terminal archive and the protected
    approval before applying these bytes with the existing backup/CAS transaction.
    """
    now = _utc(observed_at)
    old_context = (previous_request.campaign_definition_sha256, previous_request.prompt_sha256)
    target_context = (transition.target_definition_sha256, transition.target_prompt_sha256)
    if (
        journal.state != "available" or journal.ticket != ticket
        or status.state != "ticket_available" or status.campaign_key != ticket.campaign_key
        or status.launch_generation != ticket.launch_generation
        or status.launch_ticket_sha256 != ticket.launch_ticket_sha256
        or now < journal.updated_at or now < status.updated_at
        or (ticket.campaign_definition_sha256, ticket.prompt_sha256) not in {old_context, target_context}
    ):
        raise ValueError("REQUESTER_LINEAGE_MIGRATION_INVALID")
    next_ticket = CatalogLaunchTicketV1.model_validate({
        **ticket.model_dump(mode="json"),
        "campaign_definition_sha256": transition.target_definition_sha256,
        "prompt_sha256": transition.target_prompt_sha256,
    })
    if not transition.authorizes(previous_request, next_ticket):
        raise ValueError("REQUESTER_LINEAGE_MIGRATION_INVALID")
    if next_ticket == ticket:
        return ticket, journal, status
    next_journal = _ticket_journal(
        ticket=next_ticket, state="available", submission_key_sha256=None,
        request_sha256=None, issue_number=None, created_at=journal.created_at, updated_at=now,
    )
    next_status = CatalogRequesterCampaignStatusV1.create(
        campaign_key=next_ticket.campaign_key, state="ticket_available",
        launch_generation=next_ticket.launch_generation,
        launch_ticket_sha256=next_ticket.launch_ticket_sha256, updated_at=now,
    )
    return next_ticket, next_journal, next_status


def prepare_available_lineage_files(
    *, broker_root: Path, config: CatalogRequesterConfigV1,
    transition: CatalogLineageTransitionV1, public_key: bytes, observed_at: datetime,
) -> tuple[dict[str, object], ...]:
    """Return three content/CAS records without mutating any protected file.

    Installation owns service quiescence, target-version verification and applying
    these records through its existing ACL-preserving rollback transaction.
    """
    try:
        if broker_root.is_symlink():
            raise ValueError("unsafe root")
        root = broker_root.resolve(strict=True)
        inventory = inventory_catalog_broker_inbox(broker_root=root, config=config)
        if not inventory.stable or not inventory.complete or not inventory.available or inventory.pending_entry_count:
            raise ValueError("pending or unproven input")
        statuses = _broker_directory(root, config.broker.campaign_status)
        tickets = _broker_directory(root, config.broker.launch_tickets)
        processing = _broker_directory(root, config.broker.processing)
        key = transition.campaign_key
        # The typed ticket below must agree, but reject path metacharacters before opening it.
        if not key or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in key):
            raise ValueError("invalid campaign")
        paths = (tickets / f"{key}.ticket.json", statuses / f"{key}.journal.json", statuses / f"{key}.status.json")
        ticket = _read_canonical_model(paths[0], CatalogLaunchTicketV1, maximum_bytes=16_384)
        journal = _read_canonical_model(paths[1], CatalogBrokerTicketJournalV1, maximum_bytes=16_384)
        status = _read_canonical_model(paths[2], CatalogRequesterCampaignStatusV1, maximum_bytes=16_384)
        terminal = _read_canonical_model(
            statuses / f"{key}.generation-{transition.next_generation - 1:010d}.terminal.json",
            CatalogBrokerTicketJournalV1, maximum_bytes=16_384,
        )
        if (terminal.state != "terminal" or terminal.request_sha256 != transition.previous_request_sha256
            or terminal.launch_generation != transition.next_generation - 1
            or terminal.campaign_key != key or terminal.updated_at > journal.created_at):
            raise ValueError("terminal predecessor unavailable")
        signed = _read_canonical_model(
            processing / f"{terminal.submission_key_sha256}.signed.json",
            CatalogBrokerProcessingRecordV1, maximum_bytes=64_000,
        )
        previous = parse_catalog_run_request(signed.title, signed.body, public_key)
        if (previous != signed.request or previous.request_sha256 != terminal.request_sha256
            or previous.submission_key_sha256 != terminal.submission_key_sha256
            or previous.launch_ticket_sha256 != terminal.ticket.launch_ticket_sha256
            or signed.signed_at > terminal.updated_at):
            raise ValueError("signed predecessor mismatch")
        updated = prepare_available_lineage_models(previous_request=previous, transition=transition,
            ticket=ticket, journal=journal, status=status, observed_at=observed_at)
        records = []
        for path, old, new in zip(paths, (ticket, journal, status), updated, strict=True):
            before = canonical_model_bytes(old) + b"\n"
            after = canonical_model_bytes(new) + b"\n"
            records.append({
                "path": "CatalogRequester/" + path.relative_to(root).as_posix(),
                "expected_old_sha256": hashlib.sha256(before).hexdigest(),
                "sha256": hashlib.sha256(after).hexdigest(), "content": after,
            })
        return tuple(records)
    except (ValueError, TypeError, OSError) as exc:
        raise ValueError("REQUESTER_LINEAGE_MIGRATION_INVALID") from exc
