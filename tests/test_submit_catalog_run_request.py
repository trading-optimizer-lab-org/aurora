from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys

import pytest

from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    CatalogCampaignDefinitionEntryV1,
    CatalogCampaignDefinitionManifestV1,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignEntryV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogLaunchTicketV1,
    CatalogRunIntentDraftV1,
    canonical_model_bytes,
    canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_requester import (
    CatalogBrokerCapacityReceiptV1,
    CatalogRequesterCampaignStatusV1,
    CatalogRequesterReconcileHintV1,
    CatalogRequesterReceiptV1,
    CatalogRequesterConfigV1,
    CatalogRequesterProductionSealV1,
    build_registered_catalog_draft,
    build_catalog_intent_draft,
    submit_registered_catalog_campaign,
    submit_catalog_intent_to_spool,
)


ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000001"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _entry() -> CatalogCampaignEntryV1:
    return CatalogCampaignEntryV1(
        campaign_key="sp500-optimized-catalog-v1",
        engine_id="optimized_catalog_v1",
        definition_manifest_path=(
            "config/catalog_campaign_definitions/"
            "sp500-optimized-catalog-v1.manifest.json"
        ),
        optimization_policy_path="config/policy.json",
        campaign_contract_path="config/campaign.json",
        catalog_dir="config/catalog",
        selected_config_path="config/selected.json",
        admission_evidence_path="config/admission.json",
        data_contract_path="config/data.json",
        feature_contract_path="config/features.json",
        runtime_input_run_id=1,
        reference_run_id=2,
        scientific_contract_sha256="1" * 64,
        max_free_workers=360,
        allowed_protected_branch="main",
        source_artifact_contracts=(
            "runtime_input_pack_v1",
            "reference_oracle_v1",
        ),
        component_store_family="sp500_component_store_v1",
        reducer_family="catalog_hierarchical_reducer_v1",
        active=True,
    )


def _manifest() -> CatalogCampaignDefinitionManifestV1:
    return CatalogCampaignDefinitionManifestV1(
        schema_version="1",
        closure_algorithm="aurora-catalog-transitive-closure-v1",
        campaign_key="sp500-optimized-catalog-v1",
        registry_entry_sha256="2" * 64,
        entries=(
            CatalogCampaignDefinitionEntryV1(
                path="config/science.json",
                role="configuration",
                sha256="3" * 64,
                size_bytes=7,
            ),
        ),
    )


def _ticket(manifest: CatalogCampaignDefinitionManifestV1) -> CatalogLaunchTicketV1:
    return CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=hashlib.sha256(b"active prompt\n").hexdigest(),
        previous_terminal_request_sha256=None,
    )


def _draft() -> CatalogRunIntentDraftV1:
    manifest = _manifest()
    return build_catalog_intent_draft(
        ticket=_ticket(manifest),
        registry_entry=_entry(),
        campaign_manifest=manifest,
        prompt_bytes=b"active prompt\n",
    )


def _capacity(*, available: bool = True) -> CatalogBrokerCapacityReceiptV1:
    return CatalogBrokerCapacityReceiptV1.create(
        observed_at=NOW,
        available=available,
        pending_entry_count=0 if available else 32,
        pending_bytes=0 if available else 131_072,
        maximum_pending_entries=32,
        maximum_inbox_bytes=131_072,
    )


def test_client_builds_only_the_ticket_bound_canonical_draft() -> None:
    draft = _draft()
    assert draft.request_id == REQUEST_ID
    assert draft.launch_ticket_sha256 == _ticket(_manifest()).launch_ticket_sha256
    assert draft.campaign_definition_sha256 == _manifest().campaign_definition_sha256
    assert draft.prompt_sha256 == hashlib.sha256(b"active prompt\n").hexdigest()
    assert CatalogRunIntentDraftV1.model_validate_json(
        canonical_model_bytes(draft)
    ) == draft
    assert not {
        "repository",
        "commit",
        "ref",
        "path",
        "workflow",
        "workers",
        "parameters",
        "command",
    } & set(draft.model_fields)


def test_unprivileged_client_exclusive_creates_one_canonical_spool_file(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    receipts = tmp_path / "receipts"
    inbox.mkdir()
    receipts.mkdir()
    draft = _draft()

    first = submit_catalog_intent_to_spool(
        draft=draft,
        inbox=inbox,
        receipts=receipts,
        capacity=_capacity(),
        observed_at=NOW,
    )
    second = submit_catalog_intent_to_spool(
        draft=draft,
        inbox=inbox,
        receipts=receipts,
        capacity=_capacity(),
        observed_at=NOW,
    )

    assert first.status == "pending"
    assert second.status == "pending"
    assert first.submission_key_sha256 == draft.submission_key_sha256
    assert tuple(inbox.iterdir()) == (
        inbox / f"{draft.submission_key_sha256}.request.json",
    )
    payload = (inbox / f"{draft.submission_key_sha256}.request.json").read_bytes()
    assert payload == canonical_model_bytes(draft) + b"\n"
    assert len(payload) <= 4_096


@pytest.mark.parametrize(
    ("issue_number", "request_sha256"),
    (
        (77, None),
        (None, "4" * 64),
    ),
)
def test_non_submitted_receipt_rejects_partial_github_identity(
    issue_number: int | None,
    request_sha256: str | None,
) -> None:
    draft = _draft()

    with pytest.raises(ValueError, match="REQUESTER_RECEIPT_SHAPE_INVALID"):
        CatalogRequesterReceiptV1.create(
            status="pending",
            reason_code="REQUEST_BROKER_PENDING",
            submission_key_sha256=draft.submission_key_sha256,
            request_id=draft.request_id,
            campaign_key=draft.campaign_key,
            launch_generation=draft.launch_generation,
            issue_number=issue_number,
            request_sha256=request_sha256,
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    ("submission_key_sha256", "request_id"),
    (
        ("5" * 64, None),
        (None, REQUEST_ID),
    ),
)
def test_available_campaign_status_rejects_partial_request_identity(
    submission_key_sha256: str | None,
    request_id: str | None,
) -> None:
    draft = _draft()

    with pytest.raises(ValueError, match="REQUESTER_CAMPAIGN_STATUS_INVALID"):
        CatalogRequesterCampaignStatusV1.create(
            campaign_key=draft.campaign_key,
            state="ticket_available",
            launch_generation=draft.launch_generation,
            launch_ticket_sha256=draft.launch_ticket_sha256,
            submission_key_sha256=submission_key_sha256,
            request_id=request_id,
            updated_at=NOW,
        )


@pytest.mark.parametrize(
    ("request_sha256", "issue_number", "last_github_checked_at"),
    (
        ("6" * 64, None, None),
        (None, 77, None),
        (None, None, NOW),
        ("6" * 64, 77, None),
    ),
)
def test_pending_campaign_status_rejects_partial_github_identity(
    request_sha256: str | None,
    issue_number: int | None,
    last_github_checked_at: datetime | None,
) -> None:
    draft = _draft()

    with pytest.raises(ValueError, match="REQUESTER_CAMPAIGN_STATUS_INVALID"):
        CatalogRequesterCampaignStatusV1.create(
            campaign_key=draft.campaign_key,
            state="request_pending",
            launch_generation=draft.launch_generation,
            launch_ticket_sha256=draft.launch_ticket_sha256,
            submission_key_sha256=draft.submission_key_sha256,
            request_id=draft.request_id,
            request_sha256=request_sha256,
            issue_number=issue_number,
            last_github_checked_at=last_github_checked_at,
            updated_at=NOW,
        )


def test_unprivileged_client_completes_a_partial_os_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox = tmp_path / "inbox"
    receipts = tmp_path / "receipts"
    inbox.mkdir()
    receipts.mkdir()
    draft = _draft()

    from aurora.infra.sp500_megarun import catalog_requester as requester_module

    original_write = requester_module.os.write

    def partial_write(descriptor: int, payload: bytes) -> int:
        return original_write(descriptor, payload[:7])

    monkeypatch.setattr(requester_module.os, "write", partial_write)
    result = submit_catalog_intent_to_spool(
        draft=draft,
        inbox=inbox,
        receipts=receipts,
        capacity=_capacity(),
        observed_at=NOW,
    )

    assert result.status == "pending"
    assert (
        inbox / f"{draft.submission_key_sha256}.request.json"
    ).read_bytes() == canonical_model_bytes(draft) + b"\n"


def test_valid_service_receipt_wins_before_capacity_or_inbox(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    receipts = tmp_path / "receipts"
    inbox.mkdir()
    receipts.mkdir()
    draft = _draft()
    existing = CatalogRequesterReceiptV1.create(
        status="submitted",
        reason_code="REQUEST_SUBMITTED",
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        campaign_key=draft.campaign_key,
        launch_generation=draft.launch_generation,
        issue_number=123,
        request_sha256="4" * 64,
        observed_at=NOW,
    )
    receipt_path = receipts / f"{draft.submission_key_sha256}.receipt.json"
    receipt_path.write_bytes(canonical_model_bytes(existing) + b"\n")

    result = submit_catalog_intent_to_spool(
        draft=draft,
        inbox=inbox,
        receipts=receipts,
        capacity=_capacity(available=False),
        observed_at=NOW,
    )

    assert result == existing
    assert list(inbox.iterdir()) == []


def test_dangling_service_receipt_blocks_client_before_spool_write(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    receipts = tmp_path / "receipts"
    inbox.mkdir()
    receipts.mkdir()
    draft = _draft()
    receipt_path = receipts / f"{draft.submission_key_sha256}.receipt.json"
    try:
        receipt_path.symlink_to(receipts / "missing-receipt.json")
    except OSError as exc:
        pytest.skip(f"file links unavailable: {exc}")

    with pytest.raises(ValueError, match="REQUESTER_RECEIPT_UNSAFE"):
        submit_catalog_intent_to_spool(
            draft=draft,
            inbox=inbox,
            receipts=receipts,
            capacity=_capacity(),
            observed_at=NOW,
        )

    assert list(inbox.iterdir()) == []


def test_unproven_or_full_capacity_blocks_without_writing(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    receipts = tmp_path / "receipts"
    inbox.mkdir()
    receipts.mkdir()
    for capacity in (None, _capacity(available=False)):
        with pytest.raises(ValueError, match="REQUEST_BROKER_CAPACITY_UNPROVEN"):
            submit_catalog_intent_to_spool(
                draft=_draft(),
                inbox=inbox,
                receipts=receipts,
                capacity=capacity,
                observed_at=NOW,
            )
    assert list(inbox.iterdir()) == []


def test_capacity_receipt_must_have_room_for_the_complete_new_request(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    receipts = tmp_path / "receipts"
    inbox.mkdir()
    receipts.mkdir()
    draft = _draft()
    payload_size = len(canonical_model_bytes(draft) + b"\n")
    capacity = CatalogBrokerCapacityReceiptV1.create(
        observed_at=NOW,
        available=True,
        pending_entry_count=0,
        pending_bytes=131_072 - payload_size + 1,
        maximum_pending_entries=32,
        maximum_inbox_bytes=131_072,
    )

    with pytest.raises(ValueError, match="REQUEST_BROKER_CAPACITY_EXCEEDED"):
        submit_catalog_intent_to_spool(
            draft=draft,
            inbox=inbox,
            receipts=receipts,
            capacity=capacity,
            observed_at=NOW,
        )

    assert list(inbox.iterdir()) == []


def test_client_module_has_no_network_crypto_credential_or_broker_import() -> None:
    path = ROOT / "infra/sp500_megarun/catalog_requester.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    forbidden = {
        "cryptography",
        "requests",
        "socket",
        "urllib",
        "http",
        "subprocess",
        "keyring",
        "catalog_requester_broker",
    }
    assert not roots & forbidden
    source = path.read_text(encoding="utf-8")
    assert "GH_TOKEN" not in source
    assert "GITHUB_TOKEN" not in source
    assert "PRIVATE_KEY" not in source


def test_development_client_help_exposes_only_campaign_key() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/submit_catalog_run_request.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--campaign-key" in result.stdout
    for forbidden in (
        "--repository",
        "--url",
        "--token",
        "--private-key",
        "--request-id",
        "--launch-ticket",
        "--inbox",
        "--workflow",
    ):
        assert forbidden not in result.stdout


def test_requester_config_is_closed_and_repository_bound() -> None:
    config = json.loads(
        (ROOT / "config/catalog_requester_v1.json").read_text(encoding="utf-8")
    )
    assert config["repository"] == "trading-optimizer-lab-org/aurora"
    assert config["api_origin"] == "https://api.github.com"
    assert config["required_installation_permissions"] == {
        "issues": "write",
        "metadata": "read",
    }
    assert config["broker"]["maximum_request_bytes"] == 4_096
    assert config["broker"]["maximum_pending_entries"] == 32
    assert config["broker"]["maximum_inbox_bytes"] == 131_072


def test_client_rejects_path_like_campaign_key_before_file_resolution(
    tmp_path: Path,
) -> None:
    root = _installed_public_tree(tmp_path)
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_UNRESOLVED"):
        submit_registered_catalog_campaign(
            broker_root=root,
            campaign_key="../secrets/requester-private-key",
            observed_at=NOW,
        )


def _installed_public_tree(tmp_path: Path) -> Path:
    root = tmp_path / "CatalogRequester"
    for directory in (
        "config/catalog_campaign_definitions",
        "docs/runbooks",
        "inbox",
        "receipts",
        "launch-tickets",
        "campaign-status",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for relative in (
        "config/catalog_requester_v1.json",
        "config/catalog_campaign_registry_v1.json",
        "config/catalog_run_prompt_policy_v1.json",
        "config/catalog_campaign_definitions/sp500-optimized-catalog-v1.manifest.json",
        "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md",
    ):
        shutil.copyfile(ROOT / relative, root / relative)
    final_bootstrap_receipt = b'{"result":"READY","schema_version":"1"}\n'
    (root / "receipts/controller-bootstrap-v1.receipt.json").write_bytes(
        final_bootstrap_receipt
    )
    seal = CatalogRequesterProductionSealV1.create(
        protected_commit_sha="1" * 40,
        bootstrap_receipt_sha256=hashlib.sha256(
            final_bootstrap_receipt
        ).hexdigest(),
        requester_client_application_sha256="3" * 64,
        requester_broker_application_sha256="4" * 64,
        sealed_at=NOW,
    )
    (root / "config/production-enabled-v1.seal.json").write_bytes(
        canonical_model_bytes(seal) + b"\n"
    )
    return root


def test_installed_client_resolves_only_fixed_public_inputs_and_ticket(
    tmp_path: Path,
) -> None:
    root = _installed_public_tree(tmp_path)
    manifest = CatalogCampaignDefinitionManifestV1.model_validate_json(
        (
            root
            / "config/catalog_campaign_definitions/"
            "sp500-optimized-catalog-v1.manifest.json"
        ).read_bytes()
    )
    prompt = (root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        previous_terminal_request_sha256=None,
    )
    ticket_path = (
        root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json"
    )
    ticket_path.write_bytes(canonical_model_bytes(ticket) + b"\n")
    capacity = _capacity()
    (root / "receipts/broker-capacity-v1.receipt.json").write_bytes(
        canonical_model_bytes(capacity) + b"\n"
    )

    first = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key="sp500-optimized-catalog-v1",
        observed_at=NOW,
        _wait_for_refresh=False,
    )
    second = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key="sp500-optimized-catalog-v1",
        observed_at=NOW,
        _wait_for_refresh=False,
    )
    assert first.status == second.status == "pending"
    assert len(tuple((root / "inbox").iterdir())) == 1


def test_installed_client_waits_for_the_matching_service_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _installed_public_tree(tmp_path)
    manifest = CatalogCampaignDefinitionManifestV1.model_validate_json(
        (
            root
            / "config/catalog_campaign_definitions/"
            "sp500-optimized-catalog-v1.manifest.json"
        ).read_bytes()
    )
    prompt = (root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        previous_terminal_request_sha256=None,
    )
    (root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json").write_bytes(
        canonical_model_bytes(ticket) + b"\n"
    )
    (root / "receipts/broker-capacity-v1.receipt.json").write_bytes(
        canonical_model_bytes(_capacity()) + b"\n"
    )
    _, draft = build_registered_catalog_draft(
        broker_root=root,
        campaign_key=ticket.campaign_key,
    )
    expected = CatalogRequesterReceiptV1.create(
        status="submitted",
        reason_code="REQUEST_SUBMITTED",
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        campaign_key=draft.campaign_key,
        launch_generation=draft.launch_generation,
        issue_number=77,
        request_sha256="9" * 64,
        observed_at=NOW,
    )

    from aurora.infra.sp500_megarun import catalog_requester as requester_module

    sleeps = 0

    def service_tick(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        (root / "receipts" / f"{draft.submission_key_sha256}.receipt.json").write_bytes(
            canonical_model_bytes(expected) + b"\n"
        )

    monkeypatch.setattr(requester_module.time, "sleep", service_tick)
    result = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key=ticket.campaign_key,
        observed_at=NOW,
    )
    assert result == expected
    assert sleeps == 1


def test_stale_active_status_creates_one_exact_bounded_reconcile_hint(
    tmp_path: Path,
) -> None:
    root = _installed_public_tree(tmp_path)
    manifest = CatalogCampaignDefinitionManifestV1.model_validate_json(
        (
            root
            / "config/catalog_campaign_definitions/"
            "sp500-optimized-catalog-v1.manifest.json"
        ).read_bytes()
    )
    prompt = (root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        previous_terminal_request_sha256=None,
    )
    draft = build_catalog_intent_draft(
        ticket=ticket,
        registry_entry=_entry(),
        campaign_manifest=manifest,
        prompt_bytes=prompt,
    )
    receipt = CatalogRequesterReceiptV1.create(
        status="submitted",
        reason_code="REQUEST_SUBMITTED",
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        campaign_key=draft.campaign_key,
        launch_generation=draft.launch_generation,
        issue_number=77,
        request_sha256="9" * 64,
        observed_at=NOW,
    )
    (root / "receipts" / f"{draft.submission_key_sha256}.receipt.json").write_bytes(
        canonical_model_bytes(receipt) + b"\n"
    )
    status = CatalogRequesterCampaignStatusV1.create(
        campaign_key=draft.campaign_key,
        state="active",
        launch_generation=1,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        request_sha256="9" * 64,
        issue_number=77,
        last_github_checked_at=NOW,
        updated_at=NOW,
    )
    (root / "campaign-status/sp500-optimized-catalog-v1.status.json").write_bytes(
        canonical_model_bytes(status) + b"\n"
    )
    observed = NOW + timedelta(seconds=61)
    fresh_capacity = CatalogBrokerCapacityReceiptV1.create(
        observed_at=observed,
        available=True,
        pending_entry_count=0,
        pending_bytes=0,
        maximum_pending_entries=32,
        maximum_inbox_bytes=131_072,
    )
    (root / "receipts/broker-capacity-v1.receipt.json").write_bytes(
        canonical_model_bytes(fresh_capacity) + b"\n"
    )

    first = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key=draft.campaign_key,
        observed_at=observed,
        _wait_for_refresh=False,
    )
    second = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key=draft.campaign_key,
        observed_at=observed,
        _wait_for_refresh=False,
    )
    hint_path = root / "inbox/sp500-optimized-catalog-v1.reconcile-hint.json"
    hint_bytes = hint_path.read_bytes()
    hint = CatalogRequesterReconcileHintV1.model_validate_json(hint_bytes[:-1])
    assert first == second == receipt
    assert hint_bytes == canonical_model_bytes(hint) + b"\n"
    assert len(hint_bytes) <= 1_024
    assert hint.status_sha256 == status.status_sha256
    assert hint.request_sha256 == status.request_sha256
    assert tuple((root / "inbox").iterdir()) == (hint_path,)


def test_client_returns_existing_receipt_when_refresh_observes_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _installed_public_tree(tmp_path)
    manifest = CatalogCampaignDefinitionManifestV1.model_validate_json(
        (
            root
            / "config/catalog_campaign_definitions/"
            "sp500-optimized-catalog-v1.manifest.json"
        ).read_bytes()
    )
    prompt = (root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        previous_terminal_request_sha256=None,
    )
    draft = build_catalog_intent_draft(
        ticket=ticket,
        registry_entry=_entry(),
        campaign_manifest=manifest,
        prompt_bytes=prompt,
    )
    receipt = CatalogRequesterReceiptV1.create(
        status="submitted",
        reason_code="REQUEST_SUBMITTED",
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        campaign_key=draft.campaign_key,
        launch_generation=1,
        issue_number=77,
        request_sha256="9" * 64,
        observed_at=NOW,
    )
    (root / "receipts" / f"{draft.submission_key_sha256}.receipt.json").write_bytes(
        canonical_model_bytes(receipt) + b"\n"
    )
    active = CatalogRequesterCampaignStatusV1.create(
        campaign_key=draft.campaign_key,
        state="active",
        launch_generation=1,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        request_sha256="9" * 64,
        issue_number=77,
        last_github_checked_at=NOW,
        updated_at=NOW,
    )
    terminal = CatalogRequesterCampaignStatusV1.create(
        campaign_key=draft.campaign_key,
        state="terminal",
        launch_generation=1,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        submission_key_sha256=draft.submission_key_sha256,
        request_id=draft.request_id,
        request_sha256="9" * 64,
        issue_number=77,
        last_github_checked_at=NOW + timedelta(seconds=61),
        updated_at=NOW + timedelta(seconds=61),
    )
    (root / "campaign-status/sp500-optimized-catalog-v1.status.json").write_bytes(
        canonical_model_bytes(active) + b"\n"
    )
    observed = NOW + timedelta(seconds=61)
    (root / "receipts/broker-capacity-v1.receipt.json").write_bytes(
        canonical_model_bytes(
            CatalogBrokerCapacityReceiptV1.create(
                observed_at=observed,
                available=True,
                pending_entry_count=0,
                pending_bytes=0,
                maximum_pending_entries=32,
                maximum_inbox_bytes=131_072,
            )
        )
        + b"\n"
    )
    from aurora.infra.sp500_megarun import catalog_requester as requester_module

    monkeypatch.setattr(
        requester_module,
        "_wait_for_campaign_status_refresh",
        lambda **_kwargs: terminal,
    )

    result = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key=draft.campaign_key,
        observed_at=observed,
    )

    assert result == receipt


def test_installed_client_fails_closed_on_stale_capacity_or_prompt_tamper(
    tmp_path: Path,
) -> None:
    root = _installed_public_tree(tmp_path)
    manifest = CatalogCampaignDefinitionManifestV1.model_validate_json(
        (
            root
            / "config/catalog_campaign_definitions/"
            "sp500-optimized-catalog-v1.manifest.json"
        ).read_bytes()
    )
    prompt_path = root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        previous_terminal_request_sha256=None,
    )
    (root / "launch-tickets/sp500-optimized-catalog-v1.ticket.json").write_bytes(
        canonical_model_bytes(ticket) + b"\n"
    )
    stale = CatalogBrokerCapacityReceiptV1.create(
        observed_at=datetime(2026, 8, 22, 11, 59, tzinfo=UTC),
        available=True,
        pending_entry_count=0,
        pending_bytes=0,
        maximum_pending_entries=32,
        maximum_inbox_bytes=131_072,
    )
    capacity_path = root / "receipts/broker-capacity-v1.receipt.json"
    capacity_path.write_bytes(canonical_model_bytes(stale) + b"\n")
    with pytest.raises(ValueError, match="REQUEST_BROKER_CAPACITY_UNPROVEN"):
        submit_registered_catalog_campaign(
            broker_root=root,
            campaign_key="sp500-optimized-catalog-v1",
            observed_at=NOW,
        )
    assert list((root / "inbox").iterdir()) == []

    capacity_path.write_bytes(canonical_model_bytes(_capacity()) + b"\n")
    prompt_path.write_bytes(prompt_path.read_bytes() + b"tamper\n")
    with pytest.raises(ValueError, match="CATALOG_PROMPT_HASH_MISMATCH"):
        submit_registered_catalog_campaign(
            broker_root=root,
            campaign_key="sp500-optimized-catalog-v1",
            observed_at=NOW,
        )
    assert list((root / "inbox").iterdir()) == []


def test_installed_client_rejects_production_without_final_seal(
    tmp_path: Path,
) -> None:
    root = _installed_public_tree(tmp_path)
    (root / "config/production-enabled-v1.seal.json").unlink()
    with pytest.raises(ValueError, match="REQUESTER_PRODUCTION_SEAL_UNPROVEN"):
        build_registered_catalog_draft(
            broker_root=root,
            campaign_key="sp500-optimized-catalog-v1",
        )


def test_bootstrap_qualification_is_one_separate_unsealed_nonproduction_key(
    tmp_path: Path,
) -> None:
    root = _installed_public_tree(tmp_path)
    (root / "config/production-enabled-v1.seal.json").unlink()
    (root / "config/catalog_campaign_registry_v1.json").unlink()
    (
        root
        / "config/catalog_campaign_definitions/"
        "sp500-optimized-catalog-v1.manifest.json"
    ).unlink()
    config = CatalogRequesterConfigV1.model_validate_json(
        (root / "config/catalog_requester_v1.json").read_bytes()
    )
    prompt = (root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key=config.bootstrap_qualification.campaign_key,
        launch_generation=1,
        campaign_definition_sha256=canonical_sha256(
            config.bootstrap_qualification
        ),
        prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        previous_terminal_request_sha256=None,
    )
    ticket_path = (
        root
        / "launch-tickets/controller-bootstrap-qualification-v1.ticket.json"
    )
    ticket_path.write_bytes(canonical_model_bytes(ticket) + b"\n")
    (root / "receipts/broker-capacity-v1.receipt.json").write_bytes(
        canonical_model_bytes(_capacity()) + b"\n"
    )
    receipt = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key="controller-bootstrap-qualification-v1",
        observed_at=NOW,
        _wait_for_refresh=False,
    )
    assert receipt.status == "pending"
    (root / "config/bootstrap-qualified-v1.seal.json").write_bytes(b"sealed\n")
    with pytest.raises(ValueError, match="REQUESTER_BOOTSTRAP_QUALIFICATION_SEALED"):
        build_registered_catalog_draft(
            broker_root=root,
            campaign_key="controller-bootstrap-qualification-v1",
        )
