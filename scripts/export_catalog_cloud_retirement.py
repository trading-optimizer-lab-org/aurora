#!/usr/bin/env python3
"""Collect a public, read-only snapshot before the cloud cutover.

This collector is deliberately narrower than the later administrative
operation.  It does not stop the broker, create or move files in the broker
spool, read credentials, call a remote write endpoint, or generate a ticket.
It only proves that the already-disabled local sender is quiescent and exports
the exact ticket/status pairs which the protected cutover model can consume.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.sp500_megarun.catalog_cloud_cutover import (  # noqa: E402
    CloudImportedCampaignV1,
    CloudLocalRetirementV1,
)
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1  # noqa: E402
from aurora.infra.sp500_megarun.catalog_fast_authority_github import (  # noqa: E402
    load_current_fast_authority,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (  # noqa: E402
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (  # noqa: E402
    CatalogLaunchTicketV1,
    canonical_model_bytes,
    canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_requester import (  # noqa: E402
    CatalogRequesterCampaignStatusV1,
    CatalogRequesterConfigV1,
)
from aurora.infra.sp500_megarun.catalog_requester_broker import (  # noqa: E402
    CatalogBrokerInboxInventoryV1,
    CatalogBrokerTicketJournalV1,
    _broker_directory,
    _is_reparse_stat,
    _load_ticket_journal,
    _read_canonical_model,
    inventory_catalog_broker_inbox,
)
from scripts.admit_catalog_fast_request import (  # noqa: E402
    _download_owner_archive,
    _historical_owner_commit_approved,
    _strict_json,
)
from scripts.verify_catalog_fast_authority import read_live_edit  # noqa: E402


REPOSITORY = "trading-optimizer-lab-org/aurora"
_FIXED_BROKER_ROOT = Path("C:/ProgramData/AURORA/CatalogRequester")
# Kept as a named runtime constant so synthetic tests can bind an isolated
# spool without making an alternate root available to the CLI.
BROKER_ROOT = _FIXED_BROKER_ROOT
TASK_NAME = "AURORA Catalog Requester Broker"
# Microsoft.TaskScheduler TASK_STATE: DISABLED=1, RUNNING=4.  Keep these
# values separate so a contradictory COM Running state cannot be accepted just
# because Get-ScheduledTask reported the textual state "Disabled".
_COM_DISABLED_STATE = 1
_COM_RUNNING_STATE = 4
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_CAMPAIGN_KEY = r"[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+"
_CURRENT_STATUS_FILE = re.compile(
    rf"(?P<campaign>{_CAMPAIGN_KEY})\.(?P<kind>journal|status)\.json\Z"
)
_HISTORICAL_STATUS_FILE = re.compile(
    rf"(?P<campaign>{_CAMPAIGN_KEY})\.generation-[0-9]{{10}}\.terminal\.json\Z"
)
_PUBLIC_JSON_MAX_BYTES = 256 * 1024


# The task check is intentionally a fixed read-only PowerShell/COM probe.  A
# missing task is an error; it is never treated as an equivalent of Disabled.
TASK_PROBE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$taskName = 'AURORA Catalog Requester Broker'
try {
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
    if (@($task).Count -ne 1) { throw 'task lookup was not unique' }
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $comTask = $folder.GetTask($taskName)
    if ($null -eq $comTask) { throw 'COM task lookup returned no task' }
    $running = @($service.GetRunningTasks(0) | Where-Object {
        $_.Name -eq $taskName -and $_.Path -eq ('\' + $taskName)
    })
    [pscustomobject]@{
        task_name = $taskName
        task_found = $true
        com_task_found = $true
        com_checked = $true
        task_state = [string]$task.State
        com_task_state = [int]$comTask.State
        running_instance_count = [int]$running.Count
    } | ConvertTo-Json -Compress
    exit 0
} catch {
    $message = [string]$_.Exception.Message
    if ($message -match '(?i)access is denied|unauthorized') {
        [Console]::Error.WriteLine('CATALOG_CLOUD_RETIREMENT_TASK_PROBE_PERMISSION')
    } elseif ($message -match '(?i)cannot find|no msft_scheduledtask|does not exist|not found') {
        [Console]::Error.WriteLine('CATALOG_CLOUD_RETIREMENT_TASK_MISSING')
    } else {
        [Console]::Error.WriteLine('CATALOG_CLOUD_RETIREMENT_TASK_PROBE_FAILED')
    }
    exit 1
}
"""


def _error(code: str) -> ValueError:
    return ValueError(code)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_existing_directory(path: Path, *, missing_code: str, permission_code: str, invalid_code: str) -> Path:
    try:
        if path.is_symlink():
            raise _error(invalid_code)
        metadata = path.stat(follow_symlinks=False)
        if _is_reparse_stat(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise _error(invalid_code)
        return path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise _error(missing_code) from exc
    except PermissionError as exc:
        raise _error(permission_code) from exc
    except RuntimeError as exc:
        raise _error(invalid_code) from exc


def _repository_root(path: Path) -> Path:
    return _safe_existing_directory(
        path,
        missing_code="CATALOG_CLOUD_RETIREMENT_REPOSITORY_MISSING",
        permission_code="CATALOG_CLOUD_RETIREMENT_REPOSITORY_PERMISSION",
        invalid_code="CATALOG_CLOUD_RETIREMENT_REPOSITORY_INVALID",
    )


def _broker_root() -> Path:
    return _safe_existing_directory(
        BROKER_ROOT,
        missing_code="CATALOG_CLOUD_RETIREMENT_BROKER_ROOT_MISSING",
        permission_code="CATALOG_CLOUD_RETIREMENT_BROKER_ROOT_PERMISSION",
        invalid_code="CATALOG_CLOUD_RETIREMENT_BROKER_ROOT_INVALID",
    )


def _load_requester_config(repo_root: Path) -> CatalogRequesterConfigV1:
    path = repo_root / "config/catalog_requester_v1.json"
    try:
        metadata = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or _is_reparse_stat(metadata):
            raise _error("CATALOG_CLOUD_RETIREMENT_CONFIG_INVALID")
        payload = _strict_json(path)
        config = CatalogRequesterConfigV1.model_validate(payload)
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_CONFIG_MISSING") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_CONFIG_PERMISSION") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_CONFIG_INVALID") from exc
    if config.broker.root.replace("\\", "/") != _FIXED_BROKER_ROOT.as_posix():
        raise _error("CATALOG_CLOUD_RETIREMENT_BROKER_ROOT_CONFIG_INVALID")
    if config.broker.task_name != TASK_NAME:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_CONFIG_INVALID")
    return config


def _strict_probe_json(raw: str) -> Mapping[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_INVALID")
            result[key] = value
        return result

    try:
        payload = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_INVALID") from exc
    if not isinstance(payload, Mapping):
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_INVALID")
    expected = {
        "task_name",
        "task_found",
        "com_task_found",
        "com_checked",
        "task_state",
        "com_task_state",
        "running_instance_count",
    }
    if set(payload) != expected:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_INVALID")
    return payload


def _read_task_state() -> Mapping[str, Any]:
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                TASK_PROBE_SCRIPT,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_UNAVAILABLE") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_PERMISSION") from exc
    except subprocess.SubprocessError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_FAILED") from exc
    if result.returncode != 0:
        error_text = result.stderr or ""
        for code in (
            "CATALOG_CLOUD_RETIREMENT_TASK_PROBE_PERMISSION",
            "CATALOG_CLOUD_RETIREMENT_TASK_MISSING",
            "CATALOG_CLOUD_RETIREMENT_TASK_PROBE_FAILED",
        ):
            if code in error_text:
                raise _error(code)
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_FAILED")
    payload = _strict_probe_json(result.stdout.strip())
    if (
        payload["task_name"] != TASK_NAME
        or payload["task_found"] is not True
        or payload["com_task_found"] is not True
        or payload["com_checked"] is not True
    ):
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_INVALID")
    if type(payload["com_task_state"]) is not int:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_INVALID")
    if payload["com_task_state"] == _COM_RUNNING_STATE:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_COM_RUNNING")
    if payload["com_task_state"] != _COM_DISABLED_STATE:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_COM_STATE_INVALID")
    if payload["task_state"] != "Disabled":
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_NOT_DISABLED")
    if type(payload["running_instance_count"]) is not int:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_PROBE_INVALID")
    if payload["running_instance_count"] != 0:
        raise _error("CATALOG_CLOUD_RETIREMENT_TASK_INSTANCES_RUNNING")
    return payload


def _inbox_inventory(root: Path, config: CatalogRequesterConfigV1) -> CatalogBrokerInboxInventoryV1:
    try:
        inventory = inventory_catalog_broker_inbox(
            broker_root=root,
            config=config,
        )
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_INBOX_MISSING") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_INBOX_PERMISSION") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_INBOX_INVALID") from exc
    if (
        inventory.stable is not True
        or inventory.complete is not True
        or inventory.available is not True
        or inventory.reason_code != "REQUEST_BROKER_CAPACITY_AVAILABLE"
        or type(inventory.pending_entry_count) is not int
        or type(inventory.pending_bytes) is not int
        or inventory.pending_entry_count != 0
        or inventory.pending_bytes != 0
    ):
        raise _error("CATALOG_CLOUD_RETIREMENT_INBOX_NOT_QUIESCENT")
    return inventory


def _processing_snapshot(root: Path, config: CatalogRequesterConfigV1) -> tuple[tuple[str, int, int], ...]:
    try:
        directory = _broker_directory(root, config.broker.processing)
        records: list[tuple[str, int, int]] = []
        with os.scandir(directory) as iterator:
            for item in iterator:
                metadata = os.lstat(item.path)
                records.append((item.name, max(0, metadata.st_size), getattr(metadata, "st_mtime_ns", 0)))
        return tuple(sorted(records))
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_MISSING") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_PERMISSION") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_INVALID") from exc


def _processing_inventory(root: Path, config: CatalogRequesterConfigV1) -> tuple[str, ...]:
    first = _processing_snapshot(root, config)
    second = _processing_snapshot(root, config)
    if first != second:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_UNSTABLE")
    # No safe historical/active distinction is assumed here.  Any entry is
    # therefore evidence that processing is not quiescent.
    if second:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_NOT_QUIESCENT")
    return tuple(name for name, _, _ in second)


def _status_directory(root: Path, config: CatalogRequesterConfigV1) -> Path:
    try:
        return _broker_directory(root, config.broker.campaign_status)
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_DIRECTORY_MISSING") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_DIRECTORY_PERMISSION") from exc
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_DIRECTORY_INVALID") from exc


def _status_files(directory: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    journals: dict[str, Path] = {}
    statuses: dict[str, Path] = {}
    try:
        with os.scandir(directory) as iterator:
            for item in iterator:
                metadata = os.lstat(item.path)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or item.is_symlink()
                    or _is_reparse_stat(metadata)
                    or getattr(metadata, "st_nlink", 1) != 1
                    or metadata.st_size > 16_384
                ):
                    raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_FILE_UNSAFE")
                match = _CURRENT_STATUS_FILE.fullmatch(item.name)
                if match:
                    campaign = match["campaign"]
                    target = journals if match["kind"] == "journal" else statuses
                    target[campaign] = directory / item.name
                    continue
                if _HISTORICAL_STATUS_FILE.fullmatch(item.name):
                    # Historical terminal journals are bounded and their
                    # presence does not replace the current pointer pair.
                    continue
                raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_LAYOUT_INVALID")
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_DIRECTORY_MISSING") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_DIRECTORY_PERMISSION") from exc
    except (OSError, TypeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_DIRECTORY_INVALID") from exc
    return journals, statuses


@dataclass(frozen=True)
class _CampaignSnapshot:
    all_rows: tuple[tuple[str, CatalogBrokerTicketJournalV1, CatalogRequesterCampaignStatusV1], ...]
    available_rows: tuple[tuple[CatalogBrokerTicketJournalV1, CatalogRequesterCampaignStatusV1], ...]


def _campaign_snapshot(root: Path, config: CatalogRequesterConfigV1) -> _CampaignSnapshot:
    directory = _status_directory(root, config)
    journals, statuses = _status_files(directory)
    if set(journals) != set(statuses):
        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_OR_JOURNAL_MISSING")
    all_rows: list[tuple[str, CatalogBrokerTicketJournalV1, CatalogRequesterCampaignStatusV1]] = []
    available: list[tuple[CatalogBrokerTicketJournalV1, CatalogRequesterCampaignStatusV1]] = []
    for campaign in sorted(journals):
        try:
            journal = _load_ticket_journal(journals[campaign])
            status = _read_canonical_model(
                statuses[campaign],
                CatalogRequesterCampaignStatusV1,
                maximum_bytes=config.broker.maximum_request_bytes,
            )
        except FileNotFoundError as exc:
            raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_OR_JOURNAL_MISSING") from exc
        except PermissionError as exc:
            raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_PERMISSION") from exc
        except (OSError, ValueError, TypeError) as exc:
            raise _error("CATALOG_CLOUD_RETIREMENT_JOURNAL_OR_STATUS_INVALID") from exc
        if not isinstance(status, CatalogRequesterCampaignStatusV1):
            raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_INVALID")
        if status.campaign_key != campaign or journal.campaign_key != campaign:
            raise _error("CATALOG_CLOUD_RETIREMENT_CAMPAIGN_IDENTITY_INVALID")
        row = (campaign, journal, status)
        all_rows.append(row)
        if journal.state == "terminal" and status.state == "terminal":
            continue
        if journal.state == "available" and status.state == "ticket_available":
            available.append((journal, status))
            continue
        raise _error("CATALOG_CLOUD_RETIREMENT_CAMPAIGN_STATE_NOT_QUIESCENT")
    if not available:
        raise _error("CATALOG_CLOUD_RETIREMENT_NO_AVAILABLE_TICKETS")
    return _CampaignSnapshot(tuple(all_rows), tuple(available))


def _campaign_signature(snapshot: _CampaignSnapshot) -> tuple[tuple[str, bytes, bytes], ...]:
    return tuple(
        (
            campaign,
            canonical_model_bytes(journal),
            canonical_model_bytes(status),
        )
        for campaign, journal, status in snapshot.all_rows
    )


def _read_quiescence(root: Path, config: CatalogRequesterConfigV1) -> tuple[tuple[tuple[str, object], ...], CatalogBrokerInboxInventoryV1, tuple[str, ...]]:
    task = _read_task_state()
    task_signature = tuple(sorted((str(key), value) for key, value in task.items()))
    inventory = _inbox_inventory(root, config)
    processing = _processing_inventory(root, config)
    return task_signature, inventory, processing


def _read_git_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, PermissionError, subprocess.SubprocessError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_GIT_HEAD_UNAVAILABLE") from exc
    head = result.stdout.strip()
    if result.returncode != 0 or not _COMMIT.fullmatch(head):
        raise _error("CATALOG_CLOUD_RETIREMENT_GIT_HEAD_UNAVAILABLE")
    return head


def _load_remote_authority(repo_root: Path, source_commit: str) -> FastAuthorityStateV1:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if repository != REPOSITORY or not token:
        raise _error("CATALOG_CLOUD_RETIREMENT_GITHUB_ENVIRONMENT_INVALID")
    anchor_path = repo_root / "config/catalog_authority_anchor_v1.json"
    try:
        metadata = anchor_path.stat(follow_symlinks=False)
        if anchor_path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or _is_reparse_stat(metadata):
            raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_ANCHOR_INVALID")
        anchor = _strict_json(anchor_path)
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_ANCHOR_MISSING") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_ANCHOR_PERMISSION") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_ANCHOR_INVALID") from exc
    if not isinstance(anchor, Mapping):
        raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_ANCHOR_INVALID")
    try:
        client = CatalogGitHubReadOnlyClient(repository, token)
        authority = load_current_fast_authority(
            client=client,
            anchor=anchor,
            protected_commit=source_commit,
            read_edit=lambda: read_live_edit(dict(anchor)),
            download_archive=lambda artifact_id: _download_owner_archive(repository, token, artifact_id),
            approve_historical_commit=lambda candidate: _historical_owner_commit_approved(
                client, candidate, source_commit
            ),
        )
    except (CatalogGitHubSnapshotError, OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("CATALOG_CLOUD_RETIREMENT_"):
            raise
        raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_UNAVAILABLE") from exc
    if not isinstance(authority, FastAuthorityStateV1):
        raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_INVALID")
    return authority


def _authority_ticket(request: Any) -> CatalogLaunchTicketV1:
    try:
        ticket = CatalogLaunchTicketV1.model_validate(
            {name: getattr(request, name) for name in CatalogLaunchTicketV1.model_fields}
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_TICKET_INVALID") from exc
    if getattr(request, "launch_ticket_sha256", None) != ticket.launch_ticket_sha256:
        raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_TICKET_INVALID")
    return ticket


def _verify_ticket_authority(
    authority: FastAuthorityStateV1,
    available: tuple[tuple[CatalogBrokerTicketJournalV1, CatalogRequesterCampaignStatusV1], ...],
) -> tuple[CloudImportedCampaignV1, ...]:
    rows: list[CloudImportedCampaignV1] = []
    for journal, status in available:
        owners = [
            row for row in authority.campaigns if row.request.campaign_key == journal.campaign_key
        ]
        if len(owners) != 1:
            raise _error("CATALOG_CLOUD_RETIREMENT_TICKET_AUTHORITY_MISMATCH")
        owner = owners[0]
        if _authority_ticket(owner.request) != journal.ticket:
            raise _error("CATALOG_CLOUD_RETIREMENT_TICKET_AUTHORITY_MISMATCH")
        if any(row.request.campaign_key == journal.campaign_key for row in authority.emissions):
            raise _error("CATALOG_CLOUD_RETIREMENT_AUTHORITY_ALREADY_EMITTED")
        try:
            rows.append(CloudImportedCampaignV1(journal=journal, status=status))
        except ValueError as exc:
            raise _error("CATALOG_CLOUD_RETIREMENT_IMPORTED_TICKET_INVALID") from exc
    rows.sort(key=lambda row: row.journal.campaign_key)
    return tuple(rows)


def collect_retirement(repo_root: Path) -> CloudLocalRetirementV1:
    """Collect one validated receipt without writing the output file."""

    root = _repository_root(repo_root)
    config = _load_requester_config(root)
    broker_root = _broker_root()
    source_commit = _read_git_head(root)
    first_guard = _read_quiescence(broker_root, config)
    first_campaigns = _campaign_snapshot(broker_root, config)
    authority = _load_remote_authority(root, source_commit)
    second_guard = _read_quiescence(broker_root, config)
    second_campaigns = _campaign_snapshot(broker_root, config)
    if first_guard != second_guard or _campaign_signature(first_campaigns) != _campaign_signature(second_campaigns):
        raise _error("CATALOG_CLOUD_RETIREMENT_LOCAL_STATE_CHANGED")
    campaigns = _verify_ticket_authority(authority, second_campaigns.available_rows)
    observed_at = _utc_now()
    unsigned = CloudLocalRetirementV1.model_construct(
        schema_version="1",
        repository=REPOSITORY,
        source_commit=source_commit,
        observed_at=observed_at,
        task_name=TASK_NAME,
        task_state="Disabled",
        running_instances=0,
        inbox_pending_entries=0,
        processing_pending_entries=0,
        authority_state_sha256=authority.state_sha256,
        campaigns=campaigns,
        receipt_sha256="0" * 64,
    )
    receipt = unsigned.model_copy(update={"receipt_sha256": canonical_sha256(unsigned)})
    try:
        return CloudLocalRetirementV1.model_validate(receipt.model_dump(mode="json"))
    except ValueError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_RECEIPT_INVALID") from exc


def _validate_output_target(output: Path, repo_root: Path, broker_root: Path) -> Path:
    raw_output = output if output.is_absolute() else Path.cwd() / output
    if raw_output.exists() or raw_output.is_symlink():
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_EXISTS")
    raw_parent = raw_output.parent
    try:
        ancestor = raw_parent
        while True:
            if ancestor.is_symlink():
                raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_PATH_UNSAFE")
            metadata = ancestor.stat(follow_symlinks=False)
            if _is_reparse_stat(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_PATH_UNSAFE")
            if ancestor.parent == ancestor:
                break
            ancestor = ancestor.parent
        resolved_parent = raw_parent.resolve(strict=True)
        candidate = raw_output.resolve(strict=False)
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_PARENT_MISSING") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_PERMISSION") from exc
    except RuntimeError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_PATH_UNSAFE") from exc
    if resolved_parent.is_relative_to(broker_root.resolve(strict=True)):
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_PATH_UNSAFE")
    if any(part.casefold() == "secrets" for part in resolved_parent.parts):
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_PATH_UNSAFE")
    return resolved_parent / candidate.name


def _write_receipt_exclusive(receipt: CloudLocalRetirementV1, output: Path, repo_root: Path, broker_root: Path) -> Path:
    target = _validate_output_target(output, repo_root, broker_root)
    data = canonical_model_bytes(receipt) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(str(target), flags, 0o600)
    except FileExistsError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_EXISTS") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_PERMISSION") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise _error("CATALOG_CLOUD_RETIREMENT_OUTPUT_WRITE_FAILED") from exc
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repo_root = _repository_root(args.repo_root)
        broker_root = _broker_root()
        receipt = collect_retirement(repo_root)
        target = _write_receipt_exclusive(receipt, args.output, repo_root, broker_root)
        print(json.dumps({
            "status": "CATALOG_CLOUD_RETIREMENT_COLLECTED",
            "output": str(target),
            "receipt_sha256": receipt.receipt_sha256,
        }, sort_keys=True))
        return 0
    except (CatalogGitHubSnapshotError, OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        reason = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"(?:CATALOG|REQUESTER)_[A-Z0-9_]+", reason):
            reason = "CATALOG_CLOUD_RETIREMENT_UNAVAILABLE"
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
