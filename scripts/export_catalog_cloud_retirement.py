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
import hashlib
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
    CatalogRunIntentDraftV1,
    canonical_model_bytes,
    canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_requester import (  # noqa: E402
    CatalogRequesterCampaignStatusV1,
    CatalogRequesterConfigV1,
    CatalogRequesterReconcileHintV1,
)
from aurora.infra.sp500_megarun.catalog_requester_broker import (  # noqa: E402
    CatalogBrokerInboxInventoryV1,
    CatalogBrokerPostAttemptV1,
    CatalogBrokerProcessingRecordV1,
    CatalogBrokerTerminalPollStateV1,
    CatalogBrokerTerminalRateWindowV1,
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
_HISTORICAL_POLL_FILE = re.compile(
    rf"(?P<campaign>{_CAMPAIGN_KEY})\.generation-(?P<generation>[0-9]{{10}})\.terminal-poll\.json\Z"
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


def _bounded_history_bytes(path: Path, maximum: int = 64_000) -> bytes:
    before = path.lstat()
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    def safe(value):
        return stat.S_ISREG(value.st_mode) and not _is_reparse_stat(value) and value.st_nlink == 1 and value.st_size <= maximum
    if not safe(before):
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_FILE_UNSAFE")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not safe(opened) or identity(opened) != identity(before):
            raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_UNSTABLE")
        data = stream.read(maximum + 1)
        if (len(data) != opened.st_size or identity(os.fstat(stream.fileno())) != identity(opened)
                or identity(path.lstat()) != identity(opened)):
            raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_UNSTABLE")
    return data


def _processing_snapshot(root: Path, config: CatalogRequesterConfigV1) -> tuple[tuple[str, int, int, str], ...]:
    try:
        directory = _broker_directory(root, config.broker.processing)
        records: list[tuple[str, int, int, str]] = []
        with os.scandir(directory) as iterator:
            for item in iterator:
                metadata = os.lstat(item.path)
                if (not stat.S_ISREG(metadata.st_mode) or _is_reparse_stat(metadata)
                        or metadata.st_nlink != 1 or metadata.st_size > 64_000 or len(records) >= 4096):
                    raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_FILE_UNSAFE")
                # Windows holds this byte locked while the broker is alive.
                # Task/process checks, not the file's presence, prove retirement.
                digest = "lock" if item.name == "catalog-requester-broker.lock" else hashlib.sha256(_bounded_history_bytes(Path(item.path))).hexdigest()
                records.append((item.name, metadata.st_size, getattr(metadata, "st_mtime_ns", 0), digest))
        return tuple(sorted(records))
    except FileNotFoundError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_MISSING") from exc
    except PermissionError as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_PERMISSION") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_INVALID") from exc


def _verify_processing_history(root: Path, config: CatalogRequesterConfigV1, fingerprints: Mapping[str, str]) -> None:
    directory = _broker_directory(root, config.broker.processing)
    statuses = _broker_directory(root, config.broker.campaign_status)
    signed_records: dict[str, CatalogBrokerProcessingRecordV1] = {}
    def read_model(path: Path, model_type: Any, maximum_bytes: int = 16_384) -> Any:
        data = _bounded_history_bytes(path, maximum_bytes)
        if path.parent == directory and hashlib.sha256(data).hexdigest() != fingerprints[path.name]:
            raise ValueError("processing content changed")
        model = model_type.model_validate_json(data)
        if data != canonical_model_bytes(model) + b"\n":
            raise ValueError("noncanonical history")
        return model
    try:
        for name in fingerprints:
            match = re.fullmatch(r"([0-9a-f]{64})\.signed\.json", name)
            if match is None:
                continue
            signed = read_model(directory / name, CatalogBrokerProcessingRecordV1, maximum_bytes=64_000)
            if not isinstance(signed, CatalogBrokerProcessingRecordV1):
                raise ValueError("signed type")
            request = signed.request
            if match[1] != request.intent.submission_key_sha256:
                raise ValueError("signed name")
            terminal = read_model(statuses / f"{request.campaign_key}.generation-{request.launch_generation:010d}.terminal.json", CatalogBrokerTicketJournalV1)
            if (terminal.state != "terminal" or terminal.ticket != _authority_ticket(request)
                    or terminal.submission_key_sha256 != match[1] or terminal.request_sha256 != request.request_sha256):
                raise ValueError("terminal binding")
            signed_records[match[1]] = signed
        for name in fingerprints:
            path = directory / name
            if name == "catalog-requester-broker.lock":
                if path.stat().st_size != 1:
                    raise ValueError("lock size")
                continue
            if name == "terminal-reconcile-rate-v1.json":
                read_model(path, CatalogBrokerTerminalRateWindowV1)
                continue
            archived = re.fullmatch(r"processed-([0-9a-f]{64})\.(request|hint)", name)
            if archived:
                model_type = CatalogRunIntentDraftV1 if archived[2] == "request" else CatalogRequesterReconcileHintV1
                model = read_model(path, model_type)
                if isinstance(model, CatalogRunIntentDraftV1):
                    digest = model.submission_key_sha256
                elif isinstance(model, CatalogRequesterReconcileHintV1):
                    digest = model.hint_sha256
                else:
                    raise ValueError("archive type")
                if digest != archived[1]:
                    raise ValueError("archive binding")
                continue
            # These exact inert names are produced by _prepare_campaign_history_rebuild;
            # their bytes are preserved, fingerprinted, and never interpreted as work.
            history = re.fullmatch(rf"history-rebuild-({_CAMPAIGN_KEY})-(journal|status|poll|ticket|signed|consumed-ticket|post-attempt|request|receipt)-[0-9a-f]{{32}}\.entry", name)
            if history:
                current = read_model(statuses / f"{history[1]}.journal.json", CatalogBrokerTicketJournalV1)
                if current.campaign_key != history[1] or current.state not in {"available", "terminal"}:
                    raise ValueError("archived campaign is not quiescent")
                continue
            evidence = re.fullmatch(r"([0-9a-f]{64})\.(signed|ticket|post-attempt)\.json", name)
            if evidence and evidence[1] in signed_records:
                signed = signed_records[evidence[1]]
                if evidence[2] == "ticket":
                    ticket = read_model(path, CatalogLaunchTicketV1)
                    if ticket != _authority_ticket(signed.request):
                        raise ValueError("ticket binding")
                elif evidence[2] == "post-attempt":
                    attempt = read_model(path, CatalogBrokerPostAttemptV1)
                    if (not isinstance(attempt, CatalogBrokerPostAttemptV1)
                            or attempt.submission_key_sha256 != evidence[1]
                            or attempt.processing_record_sha256 != signed.processing_record_sha256):
                        raise ValueError("post binding")
                continue
            raise ValueError("pending or unknown entry")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_NOT_QUIESCENT") from exc


def _processing_inventory(root: Path, config: CatalogRequesterConfigV1) -> tuple[str, ...]:
    first = _processing_snapshot(root, config)
    _verify_processing_history(root, config, {row[0]: row[3] for row in first})
    second = _processing_snapshot(root, config)
    if first != second:
        raise _error("CATALOG_CLOUD_RETIREMENT_PROCESSING_UNSTABLE")
    # Return history fingerprints for the surrounding before/after comparison,
    # not a pending-work count. No spool file is moved, removed or rewritten.
    return tuple(f"{name}:{size}:{mtime}:{digest}" for name, size, mtime, digest in second)


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
                historical_poll = _HISTORICAL_POLL_FILE.fullmatch(item.name)
                if historical_poll:
                    try:
                        poll = _read_canonical_model(directory / item.name, CatalogBrokerTerminalPollStateV1, maximum_bytes=16_384)
                    except (OSError, ValueError, TypeError) as exc:
                        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_LAYOUT_INVALID") from exc
                    if (not isinstance(poll, CatalogBrokerTerminalPollStateV1)
                            or poll.campaign_key != historical_poll["campaign"]
                            or poll.launch_generation != int(historical_poll["generation"])):
                        raise _error("CATALOG_CLOUD_RETIREMENT_STATUS_LAYOUT_INVALID")
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
        ticket = journal.ticket
        if (not owner.is_terminal or ticket.launch_generation != owner.generation + 1
                or ticket.previous_terminal_request_sha256 != owner.request.request_sha256
                or ticket.request_id == owner.request.request_id):
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
