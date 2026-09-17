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
    ticket = ticket_for(request)
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
