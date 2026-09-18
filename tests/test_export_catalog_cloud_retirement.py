"""Bounded, synthetic checks for the public cloud-retirement collector."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import (
    FastAuthorityCampaignV1,
    FastAuthorityStateV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_requester import (
    CatalogRequesterCampaignStatusV1,
    CatalogRequesterConfigV1,
)
from aurora.infra.sp500_megarun.catalog_requester_broker import _ticket_journal
from scripts import export_catalog_cloud_retirement as command
from tests.test_catalog_cloud_authority import emission
from tests.test_catalog_cloud_ticket import ticket_for
from tests.test_catalog_fast_authority_github import publication_transport


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 17, 13, 0, tzinfo=timezone.utc)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "config/catalog_requester_v1.json",
        repo / "config/catalog_requester_v1.json",
    )
    return repo


def _broker(tmp_path: Path) -> Path:
    broker = tmp_path / "CatalogRequester"
    for name in (
        "inbox",
        "processing",
        "receipts",
        "launch-tickets",
        "campaign-status",
        "secrets",
        "config",
    ):
        (broker / name).mkdir(parents=True)
    return broker


def _config() -> CatalogRequesterConfigV1:
    return CatalogRequesterConfigV1.model_validate_json(
        (ROOT / "config/catalog_requester_v1.json").read_bytes()
    )


def _install_available_campaign(broker: Path, *, updated_at: datetime = NOW):
    request = emission().request
    ticket = ticket_for(request).model_copy(update={
        "request_id": "00000000-0000-7000-8000-000000000123",
        "launch_generation": request.launch_generation + 1,
        "previous_terminal_request_sha256": request.request_sha256,
    })
    journal = _ticket_journal(
        ticket=ticket,
        state="available",
        submission_key_sha256=None,
        request_sha256=None,
        issue_number=None,
        created_at=NOW,
        updated_at=updated_at,
    )
    status = CatalogRequesterCampaignStatusV1.create(
        campaign_key=ticket.campaign_key,
        state="ticket_available",
        launch_generation=ticket.launch_generation,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        updated_at=updated_at,
    )
    status_dir = broker / "campaign-status"
    (status_dir / f"{ticket.campaign_key}.journal.json").write_bytes(
        canonical_model_bytes(journal) + b"\n"
    )
    (status_dir / f"{ticket.campaign_key}.status.json").write_bytes(
        canonical_model_bytes(status) + b"\n"
    )
    authority = FastAuthorityStateV1.bootstrap(
        campaigns=(
            FastAuthorityCampaignV1(
                request=request,
                owner_issue_number=276,
                owner_run_id=33910681070,
                terminal_receipt_sha256="9" * 64,
            ),
        )
    )
    return ticket, journal, status, authority


def _task_payload(**updates):
    payload = {
        "task_name": command.TASK_NAME,
        "task_found": True,
        "com_task_found": True,
        "com_checked": True,
        "task_state": "Disabled",
        "com_task_state": 1,
        "running_instance_count": 0,
    }
    payload.update(updates)
    return payload


def _bind_ready(monkeypatch, broker: Path, authority: FastAuthorityStateV1) -> None:
    monkeypatch.setattr(command, "BROKER_ROOT", broker)
    monkeypatch.setattr(command, "_read_git_head", lambda _: "a" * 40)
    monkeypatch.setattr(command, "_read_task_state", lambda: _task_payload())
    monkeypatch.setattr(command, "_load_remote_authority", lambda *_: authority)
    monkeypatch.setattr(command, "_utc_now", lambda: NOW + timedelta(minutes=1))


def test_collects_canonical_public_receipt_from_real_local_consumers(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    broker = _broker(tmp_path)
    ticket, journal, status, authority = _install_available_campaign(broker)
    _bind_ready(monkeypatch, broker, authority)

    receipt = command.collect_retirement(repo)

    assert receipt.source_commit == "a" * 40
    assert receipt.authority_state_sha256 == authority.state_sha256
    assert receipt.campaigns[0].journal.ticket == ticket
    assert receipt.campaigns[0].journal.journal_sha256 == journal.journal_sha256
    assert receipt.campaigns[0].status.status_sha256 == status.status_sha256
    reopened = receipt.__class__.model_validate_json(canonical_model_bytes(receipt))
    assert reopened == receipt
    assert canonical_model_bytes(receipt).endswith(b"}")


def test_output_is_public_canonical_and_exclusive(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    broker = _broker(tmp_path)
    _, _, _, authority = _install_available_campaign(broker)
    _bind_ready(monkeypatch, broker, authority)
    receipt = command.collect_retirement(repo)
    public = repo / "public"
    public.mkdir()
    output = public / "catalog-cloud-retirement.json"

    target = command._write_receipt_exclusive(receipt, output, repo, broker)

    assert target == output
    assert output.read_bytes() == canonical_model_bytes(receipt) + b"\n"
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_OUTPUT_EXISTS"):
        command._write_receipt_exclusive(receipt, output, repo, broker)


def test_cli_accepts_only_repo_root_and_output_and_writes_verified_receipt(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    broker = _broker(tmp_path)
    _, _, _, authority = _install_available_campaign(broker)
    _bind_ready(monkeypatch, broker, authority)
    output = repo / "public/catalog-cloud-retirement.json"
    output.parent.mkdir()

    assert command.main(["--repo-root", str(repo), "--output", str(output)]) == 0
    receipt = command.CloudLocalRetirementV1.model_validate_json(output.read_bytes())
    assert receipt.authority_state_sha256 == authority.state_sha256


def test_task_probe_requires_exact_disabled_task_and_com_zero_instances(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_task_payload()),
            stderr="",
        )

    monkeypatch.setattr(command.subprocess, "run", fake_run)
    observed = command._read_task_state()

    assert observed["task_state"] == "Disabled"
    assert observed["com_task_state"] == 1
    assert observed["running_instance_count"] == 0
    assert calls[0][0][0] == "powershell.exe"
    assert calls[0][1]["capture_output"] is True
    assert "Get-ScheduledTask" in command.TASK_PROBE_SCRIPT
    assert "New-Object -ComObject 'Schedule.Service'" in command.TASK_PROBE_SCRIPT
    for forbidden in ("Stop-ScheduledTask", "Register-ScheduledTask", "Unregister-ScheduledTask", "Set-ScheduledTask"):
        assert forbidden not in command.TASK_PROBE_SCRIPT


def test_task_probe_rejects_com_running_even_when_powershell_says_disabled(monkeypatch):
    """Regression for the previous incorrect COM Disabled=4 assumption."""
    monkeypatch.setattr(
        command.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_task_payload(com_task_state=4)),
            stderr="",
        ),
    )

    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_TASK_COM_RUNNING"):
        command._read_task_state()


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "CATALOG_CLOUD_RETIREMENT_TASK_MISSING",
            "CATALOG_CLOUD_RETIREMENT_TASK_MISSING",
        ),
        (
            "CATALOG_CLOUD_RETIREMENT_TASK_PROBE_PERMISSION",
            "CATALOG_CLOUD_RETIREMENT_TASK_PROBE_PERMISSION",
        ),
    ],
)
def test_task_absence_or_permission_is_not_inferred_as_disabled(monkeypatch, stderr, expected):
    monkeypatch.setattr(
        command.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=stderr),
    )

    with pytest.raises(ValueError, match=expected):
        command._read_task_state()


def test_inbox_and_processing_require_empty_stable_boundaries(tmp_path):
    broker = _broker(tmp_path)
    config = _config()
    (broker / "inbox" / "request.request.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_INBOX_NOT_QUIESCENT"):
        command._inbox_inventory(broker, config)

    (broker / "inbox" / "request.request.json").unlink()
    (broker / "processing" / "historical-or-pending").write_bytes(b"record")
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_PROCESSING_NOT_QUIESCENT"):
        command._processing_inventory(broker, config)


def _install_processing_history(broker):
    from aurora.infra.sp500_megarun.catalog_cloud_transport import _processing_record
    from aurora.infra.sp500_megarun.catalog_requester_broker import CatalogBrokerPostAttemptV1
    signed = _processing_record(emission(), NOW)
    request = signed.request
    key = request.intent.submission_key_sha256
    terminal = _ticket_journal(ticket=ticket_for(request), state="terminal",
        submission_key_sha256=key, request_sha256=request.request_sha256,
        issue_number=276, created_at=NOW, updated_at=NOW)
    models = {
        f"processing/{key}.signed.json": signed,
        f"processing/{key}.ticket.json": terminal.ticket,
        f"processing/{key}.post-attempt.json": CatalogBrokerPostAttemptV1.create(signed=signed, post_lower_bound=NOW),
        f"processing/processed-{key}.request": request.intent,
        f"campaign-status/{request.campaign_key}.generation-{request.launch_generation:010d}.terminal.json": terminal,
    }
    for name, model in models.items():
        (broker / name).write_bytes(canonical_model_bytes(model) + b"\n")
    (broker / "processing/catalog-requester-broker.lock").write_bytes(b"1")
    return key


def test_processing_preserves_verified_terminal_history(tmp_path):
    broker = _broker(tmp_path)
    _install_processing_history(broker)
    before = {p.name: p.read_bytes() for p in (broker / "processing").iterdir()}
    assert command._processing_inventory(broker, _config())
    assert {p.name: p.read_bytes() for p in (broker / "processing").iterdir()} == before


@pytest.mark.parametrize("fault", ["pending", "missing_terminal", "wrong_terminal", "unknown", "unsafe_directory"])
def test_processing_history_never_hides_pending_or_unproven_state(tmp_path, fault):
    broker = _broker(tmp_path)
    key = _install_processing_history(broker)
    if fault == "pending":
        (broker / "processing" / f"{key}.request.json").write_bytes(b"{}")
    elif fault == "missing_terminal":
        next((broker / "campaign-status").glob("*.terminal.json")).unlink()
    elif fault == "wrong_terminal":
        terminal = next((broker / "campaign-status").glob("*.terminal.json"))
        terminal.write_bytes(b"{}")
    elif fault == "unsafe_directory":
        (broker / "processing" / "processed-dead.request").mkdir()
    else:
        (broker / "processing" / "unknown.entry").write_bytes(b"{}")
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_PROCESSING_"):
        command._processing_inventory(broker, _config())


def test_history_rebuild_archive_is_inert_but_does_not_hide_recoverable_claim(tmp_path):
    broker = _broker(tmp_path)
    ticket, _, _, _ = _install_available_campaign(broker)
    path = broker / "processing" / f"history-rebuild-{ticket.campaign_key}-request-{'a' * 32}.entry"
    # The existing broker intentionally archives uncertain/malformed originals.
    path.write_bytes(b"uncertain archived original, not an executable claim")
    assert command._processing_inventory(broker, _config())
    (broker / "processing" / f"{'b' * 64}.reconcile-hint.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_PROCESSING_"):
        command._processing_inventory(broker, _config())


def test_history_rebuild_archive_cannot_name_an_unknown_campaign(tmp_path):
    broker = _broker(tmp_path)
    path = broker / "processing" / f"history-rebuild-unknown-v1-request-{'a' * 32}.entry"
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_PROCESSING_"):
        command._processing_inventory(broker, _config())


def test_bounded_history_read_rejects_replacement_before_read(tmp_path, monkeypatch):
    path = tmp_path / "history"
    path.write_bytes(b"original")
    real_open = command.os.open
    def replace_before_open(target, flags):
        path.rename(tmp_path / "preserved-original")
        path.write_bytes(b"replacement outside original identity")
        return real_open(target, flags)
    monkeypatch.setattr(command.os, "open", replace_before_open)
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_PROCESSING_UNSTABLE"):
        command._bounded_history_bytes(path)


def test_canonical_journal_or_status_tampering_fails_closed(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    broker = _broker(tmp_path)
    _, _, _, authority = _install_available_campaign(broker)
    _bind_ready(monkeypatch, broker, authority)
    status_path = next((broker / "campaign-status").glob("*.status.json"))
    status_path.write_bytes(status_path.read_bytes().rstrip(b"\n") + b" \n")

    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_JOURNAL_OR_STATUS_INVALID"):
        command.collect_retirement(repo)


def test_re_read_detects_valid_local_status_change_during_remote_read(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    broker = _broker(tmp_path)
    ticket, _, _, authority = _install_available_campaign(broker)
    _bind_ready(monkeypatch, broker, authority)
    status_path = broker / "campaign-status" / f"{ticket.campaign_key}.status.json"
    changed = CatalogRequesterCampaignStatusV1.create(
        campaign_key=ticket.campaign_key,
        state="ticket_available",
        launch_generation=ticket.launch_generation,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        updated_at=NOW + timedelta(seconds=1),
    )

    def remote_read(*args):
        status_path.write_bytes(canonical_model_bytes(changed) + b"\n")
        return authority

    monkeypatch.setattr(command, "_load_remote_authority", remote_read)
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_LOCAL_STATE_CHANGED"):
        command.collect_retirement(repo)


def test_ticket_must_match_current_remote_authority_and_no_output_is_created(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    broker = _broker(tmp_path)
    _install_available_campaign(broker)
    empty_authority = FastAuthorityStateV1.bootstrap(campaigns=())
    _bind_ready(monkeypatch, broker, empty_authority)

    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_TICKET_AUTHORITY_MISMATCH"):
        command.collect_retirement(repo)
    assert not (repo / "catalog-cloud-retirement.json").exists()


def test_real_authority_reader_accepts_only_synthetic_get_transport(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _, _, _, authority = _install_available_campaign(_broker(tmp_path))
    fixture = publication_transport(state=authority)
    (repo / "config/catalog_authority_anchor_v1.json").write_text(
        json.dumps(fixture.anchor), encoding="utf-8"
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", command.REPOSITORY)
    monkeypatch.setenv("GH_TOKEN", "synthetic-read-token")
    monkeypatch.setattr(command, "CatalogGitHubReadOnlyClient", lambda repository, token: fixture.client)
    monkeypatch.setattr(command, "read_live_edit", lambda anchor: fixture.edit)
    monkeypatch.setattr(command, "_download_owner_archive", lambda repository, token, artifact_id: fixture.raw)
    monkeypatch.setattr(command, "_historical_owner_commit_approved", lambda client, candidate, protected: True)

    observed = command._load_remote_authority(repo, "a" * 40)

    assert observed == authority
    assert fixture.calls
    assert all(path.startswith("/repos/trading-optimizer-lab-org/aurora/") for path in fixture.calls)


@pytest.mark.parametrize("fault", ["active_owner", "same_generation", "generation_jump", "wrong_predecessor", "reused_request_id"])
def test_available_ticket_requires_exact_terminal_successor(tmp_path, fault):
    broker = _broker(tmp_path)
    ticket, journal, status, authority = _install_available_campaign(broker)
    owner = authority.campaigns[0]
    if fault == "active_owner":
        authority = authority.model_copy(update={"campaigns": (owner.model_copy(update={"terminal_receipt_sha256": None}),)})
    else:
        change = {
            "same_generation": {"launch_generation": owner.generation},
            "generation_jump": {"launch_generation": owner.generation + 2},
            "wrong_predecessor": {"previous_terminal_request_sha256": "f" * 64},
            "reused_request_id": {"request_id": owner.request.request_id},
        }[fault]
        ticket = ticket.model_copy(update=change)
        journal = journal.model_copy(update={"ticket": ticket})
    with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_TICKET_AUTHORITY_MISMATCH"):
        command._verify_ticket_authority(authority, ((journal, status),))


@pytest.mark.parametrize("wrong_generation", [False, True])
def test_historical_terminal_poll_is_bounded_typed_and_not_a_current_pointer(tmp_path, wrong_generation):
    from aurora.infra.sp500_megarun.catalog_requester_broker import CatalogBrokerTerminalPollStateV1
    from aurora.infra.sp500_megarun.catalog_request_contract import canonical_sha256
    broker = _broker(tmp_path)
    ticket, _, _, authority = _install_available_campaign(broker)
    request = authority.campaigns[0].request
    unsigned = CatalogBrokerTerminalPollStateV1.model_construct(
        schema_version="1", campaign_key=request.campaign_key, launch_generation=request.launch_generation,
        submission_key_sha256=request.intent.submission_key_sha256, request_sha256=request.request_sha256,
        issue_number=276, last_github_checked_at=NOW, next_github_check_at=NOW + timedelta(minutes=1),
        backoff_seconds=60, etag=None, last_hint_sha256=None, poll_state_sha256="0" * 64)
    poll = unsigned.model_copy(update={"poll_state_sha256": canonical_sha256(unsigned)})
    generation = request.launch_generation + int(wrong_generation)
    path = broker / "campaign-status" / f"{request.campaign_key}.generation-{generation:010d}.terminal-poll.json"
    path.write_bytes(canonical_model_bytes(poll) + b"\n")
    if wrong_generation:
        with pytest.raises(ValueError, match="CATALOG_CLOUD_RETIREMENT_STATUS_LAYOUT_INVALID"):
            command._campaign_snapshot(broker, _config())
    else:
        snapshot = command._campaign_snapshot(broker, _config())
        assert len(snapshot.all_rows) == len(snapshot.available_rows) == 1
        assert snapshot.available_rows[0][0].ticket == ticket
