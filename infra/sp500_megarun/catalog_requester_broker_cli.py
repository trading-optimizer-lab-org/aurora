"""Production entry point for the isolated catalog requester broker."""

from __future__ import annotations

import argparse


_BROKER_ROOT = "C:/ProgramData/AURORA/CatalogRequester"
_broker_lock_descriptor: int | None = None
_RETRYABLE_REASON_CODES = frozenset(
    {
        "REQUESTER_GITHUB_TRANSIENT_FAILURE",
        "REQUESTER_POST_RECONCILIATION_RETRYABLE",
    }
)


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Run the locked AURORA catalog requester broker."
    )


def _broker_main() -> int:
    global _broker_lock_descriptor

    _parser().parse_args()
    import ctypes
    from datetime import UTC, datetime
    import hashlib
    import json
    import msvcrt
    import os
    from pathlib import Path
    import stat
    import sys
    import time

    from .catalog_requester import (
        CatalogRequesterConfigV1,
        verify_installed_requester_application,
    )
    from .catalog_requester_broker import (
        CatalogBrokerGithubClient,
        RequestsCatalogBrokerHttpTransport,
        claim_next_catalog_reconcile_hint,
        claim_next_catalog_request,
        ensure_catalog_launch_tickets,
        load_claimed_catalog_draft,
        process_claimed_catalog_request,
        process_claimed_catalog_reconcile_hint,
        publish_catalog_broker_self_audit,
        publish_catalog_broker_capacity,
        quarantine_one_invalid_catalog_broker_entry,
        quarantine_invalid_claimed_catalog_request,
        reconcile_active_catalog_campaign,
    )
    from .catalog_campaign_registry import load_catalog_campaign_registry

    def windows_path_sddl(path: Path, *, security_information: int = 0x00000007) -> str:
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        advapi32.GetNamedSecurityInfoW.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        )
        advapi32.GetNamedSecurityInfoW.restype = ctypes.c_ulong
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_ulong),
        )
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = (
            ctypes.c_int
        )
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        owner = ctypes.c_void_p()
        group = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        result = advapi32.GetNamedSecurityInfoW(
            str(path),
            1,
            security_information,
            ctypes.byref(owner),
            ctypes.byref(group),
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result != 0 or not descriptor.value:
            raise RuntimeError("REQUESTER_BROKER_ACL_READBACK_FAILED")
        text_pointer = ctypes.c_void_p()
        text_length = ctypes.c_ulong()
        try:
            converted = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor,
                1,
                security_information,
                ctypes.byref(text_pointer),
                ctypes.byref(text_length),
            )
            if not converted or not text_pointer.value:
                raise RuntimeError("REQUESTER_BROKER_ACL_READBACK_FAILED")
            return ctypes.wstring_at(text_pointer.value)
        finally:
            if text_pointer.value:
                kernel32.LocalFree(text_pointer)
            kernel32.LocalFree(descriptor)

    def windows_account_sid(account_name: str) -> str:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32.LookupAccountNameW.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_uint),
        )
        advapi32.LookupAccountNameW.restype = ctypes.c_int
        advapi32.ConvertSidToStringSidW.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        sid_size = ctypes.c_ulong()
        domain_size = ctypes.c_ulong()
        sid_use = ctypes.c_uint()
        advapi32.LookupAccountNameW(
            None,
            account_name,
            None,
            ctypes.byref(sid_size),
            None,
            ctypes.byref(domain_size),
            ctypes.byref(sid_use),
        )
        if ctypes.get_last_error() != 122 or sid_size.value == 0:
            raise RuntimeError("REQUESTER_BROKER_OS_IDENTITY_UNPROVEN")
        sid_buffer = ctypes.create_string_buffer(sid_size.value)
        domain_buffer = ctypes.create_unicode_buffer(max(1, domain_size.value))
        if not advapi32.LookupAccountNameW(
            None,
            account_name,
            sid_buffer,
            ctypes.byref(sid_size),
            domain_buffer,
            ctypes.byref(domain_size),
            ctypes.byref(sid_use),
        ):
            raise RuntimeError("REQUESTER_BROKER_OS_IDENTITY_UNPROVEN")
        text_pointer = ctypes.c_void_p()
        try:
            if not advapi32.ConvertSidToStringSidW(
                sid_buffer,
                ctypes.byref(text_pointer),
            ) or not text_pointer.value:
                raise RuntimeError("REQUESTER_BROKER_OS_IDENTITY_UNPROVEN")
            return ctypes.wstring_at(text_pointer.value)
        finally:
            if text_pointer.value:
                kernel32.LocalFree(text_pointer)

    def seal_claimed_spool_file(path: Path) -> None:
        if path.parent.resolve(strict=True) != processing or path.is_symlink():
            raise ValueError("REQUESTER_BROKER_CLAIM_ACL_INVALID")
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
        )
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_int
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_ulong),
        )
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            ctypes.c_int
        )
        advapi32.SetKernelObjectSecurity.argtypes = (
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        )
        advapi32.SetKernelObjectSecurity.restype = ctypes.c_int
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        read_and_set_security = 0x80000000 | 0x00020000 | 0x00040000 | 0x00080000
        exclusive = kernel32.CreateFileW(
            str(path),
            read_and_set_security,
            0,
            None,
            3,
            0x00200000,
            None,
        )
        if exclusive == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in {32, 33}:
                raise ValueError("REQUESTER_BROKER_CLAIM_BUSY")
            raise ValueError("REQUESTER_BROKER_CLAIM_ACL_INVALID")
        sddl = (
            f"O:{service_sid}D:P"
            f"(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{service_sid})"
        )
        descriptor = ctypes.c_void_p()
        descriptor_size = ctypes.c_ulong()
        try:
            metadata = path.stat(follow_symlinks=False)
            reparse_marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & reparse_marker
                or getattr(metadata, "st_nlink", 1) != 1
                or metadata.st_size
                > max(
                    config.broker.maximum_request_bytes,
                    config.broker.maximum_hint_bytes,
                )
            ):
                raise ValueError("REQUESTER_BROKER_CLAIM_ACL_INVALID")
            if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl,
                1,
                ctypes.byref(descriptor),
                ctypes.byref(descriptor_size),
            ) or not descriptor.value:
                raise ValueError("REQUESTER_BROKER_CLAIM_ACL_INVALID")
            owner_dacl_protected = 0x00000001 | 0x00000004 | 0x80000000
            if not advapi32.SetKernelObjectSecurity(
                exclusive,
                owner_dacl_protected,
                descriptor,
            ):
                raise ValueError("REQUESTER_BROKER_CLAIM_ACL_INVALID")
        finally:
            if descriptor.value:
                kernel32.LocalFree(descriptor)
            if not kernel32.CloseHandle(exclusive):
                raise ValueError("REQUESTER_BROKER_CLAIM_ACL_INVALID")
        if windows_path_sddl(path, security_information=0x00000005) != sddl:
            raise ValueError("REQUESTER_BROKER_CLAIM_ACL_INVALID")

    def verify_acl_baseline(root_path: Path) -> None:
        expected_paths = (
            ".",
            "bin",
            "config",
            "docs",
            "schemas",
            "secrets",
            "inbox",
            "processing",
            "receipts",
            "launch-tickets",
            "campaign-status",
            "client-venv",
            "broker-venv",
            "bin/catalog-requester-client.pyz",
            "bin/catalog-requester-client.manifest.json",
            "bin/catalog-requester-broker.pyz",
            "bin/catalog-requester-broker.manifest.json",
            "secrets/requester-private-key.pem",
            "secrets/requester-app-binding-v1.json",
        )
        baseline_path = root_path / "config/acl-baseline-v1.json"
        if baseline_path.is_symlink() or baseline_path.stat().st_size > 65_536:
            raise RuntimeError("REQUESTER_BROKER_ACL_BASELINE_INVALID")
        try:
            data = baseline_path.read_bytes()
            payload = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("REQUESTER_BROKER_ACL_BASELINE_INVALID") from exc
        if (
            not data.endswith(b"\n")
            or not isinstance(payload, dict)
            or set(payload) != {"schema_version", "records"}
            or payload.get("schema_version") != "1"
            or not isinstance(payload.get("records"), list)
        ):
            raise RuntimeError("REQUESTER_BROKER_ACL_BASELINE_INVALID")
        records = payload["records"]
        observed_paths = tuple(
            record.get("path") if isinstance(record, dict) else None
            for record in records
        )
        if observed_paths != expected_paths:
            raise RuntimeError("REQUESTER_BROKER_ACL_BASELINE_INVALID")
        for record in records:
            if not isinstance(record, dict) or set(record) != {"path", "sddl"}:
                raise RuntimeError("REQUESTER_BROKER_ACL_BASELINE_INVALID")
            relative = record["path"]
            expected_sddl = record["sddl"]
            if not isinstance(relative, str) or not isinstance(expected_sddl, str):
                raise RuntimeError("REQUESTER_BROKER_ACL_BASELINE_INVALID")
            target = (
                root_path
                if relative == "."
                else root_path.joinpath(*relative.split("/"))
            )
            if target.is_symlink() or not target.resolve(strict=True).is_relative_to(
                root_path
            ):
                raise RuntimeError("REQUESTER_BROKER_ACL_OR_PATH_INVALID")
            if windows_path_sddl(target) != expected_sddl:
                raise RuntimeError("REQUESTER_BROKER_ACL_DRIFT")

    size = ctypes.c_ulong(256)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)):
        raise RuntimeError("REQUESTER_BROKER_OS_IDENTITY_UNPROVEN")
    if buffer.value.casefold() != "aurorarequester":
        raise RuntimeError("REQUESTER_BROKER_OS_IDENTITY_INVALID")
    ctypes.windll.shell32.IsUserAnAdmin.argtypes = ()
    ctypes.windll.shell32.IsUserAnAdmin.restype = ctypes.c_int
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("REQUESTER_BROKER_OS_IDENTITY_INVALID")
    service_sid = windows_account_sid(f".\\{buffer.value}")

    if any(
        os.environ.get(name)
        for name in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN",
            "GITHUB_ENTERPRISE_TOKEN",
            "GH_CONFIG_DIR",
            "XDG_CONFIG_HOME",
        )
    ):
        raise RuntimeError("AGENT_ADMIN_CREDENTIAL_EXPOSED")
    if any(
        os.environ.get(name)
        for name in (
            "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
            "AURORA_CATALOG_AUDITOR_PRIVATE_KEY_PATH",
            "AURORA_CATALOG_AUDITOR_JWT",
            "AURORA_CATALOG_AUDITOR_TOKEN",
            "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
            "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN",
        )
    ):
        raise RuntimeError("AGENT_AUDITOR_CREDENTIAL_EXPOSED")
    if any(
        os.environ.get(name)
        for name in (
            "AURORA_CATALOG_REQUESTER_APP_ID",
            "AURORA_CATALOG_REQUESTER_INSTALLATION_ID",
            "AURORA_CATALOG_REQUESTER_PRIVATE_KEY",
            "AURORA_CATALOG_REQUESTER_PRIVATE_KEY_PATH",
            "AURORA_CATALOG_REQUESTER_JWT",
            "AURORA_CATALOG_REQUESTER_TOKEN",
        )
    ):
        raise RuntimeError("REQUESTER_BROKER_ENVIRONMENT_EXPOSED")
    service_home = Path.home()
    if any(
        path.exists() or path.is_symlink()
        for path in (
            service_home / ".config/gh/hosts.yml",
            service_home / "AppData/Roaming/GitHub CLI/hosts.yml",
        )
    ):
        raise RuntimeError("AGENT_ADMIN_CREDENTIAL_EXPOSED")

    root = Path(_BROKER_ROOT).resolve(strict=True)
    try:
        expected_prefix = (root / "broker-venv").resolve(strict=True)
        expected_executable = (
            expected_prefix / "Scripts/pythonw.exe"
        ).resolve(strict=True)
        expected_application = (
            root / "bin/catalog-requester-broker.pyz"
        ).resolve(strict=True)
        observed_executable = Path(sys.executable).resolve(strict=True)
        observed_prefix = Path(sys.prefix).resolve(strict=True)
        observed_base_prefix = Path(sys.base_prefix).resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("REQUESTER_BROKER_RUNTIME_INVALID") from exc
    if (
        sys.version_info[:2] != (3, 14)
        or observed_executable != expected_executable
        or observed_prefix != expected_prefix
        or observed_base_prefix == observed_prefix
        or not sys.flags.isolated
        or not sys.flags.ignore_environment
        or not sys.flags.no_user_site
        or not sys.flags.safe_path
    ):
        raise RuntimeError("REQUESTER_BROKER_RUNTIME_INVALID")
    allowed_runtime_paths = {
        expected_application,
        expected_prefix / "Lib/site-packages",
        observed_base_prefix,
        observed_base_prefix / "python314.zip",
        observed_base_prefix / "DLLs",
        observed_base_prefix / "Lib",
    }
    for entry in sys.path:
        if not entry:
            raise RuntimeError("REQUESTER_BROKER_RUNTIME_INVALID")
        observed_path = Path(entry).resolve(strict=False)
        if observed_path not in allowed_runtime_paths:
            raise RuntimeError("REQUESTER_BROKER_RUNTIME_INVALID")
    lock_path = root / "processing/catalog-requester-broker.lock"
    lock_flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        lock_flags |= os.O_BINARY
    broker_lock = os.open(lock_path, lock_flags, 0o600)
    _broker_lock_descriptor = broker_lock
    try:
        lock_metadata = os.fstat(broker_lock)
        if not stat.S_ISREG(lock_metadata.st_mode) or lock_metadata.st_nlink != 1:
            raise RuntimeError("REQUESTER_BROKER_LOCK_INVALID")
        if lock_metadata.st_size == 0:
            os.write(broker_lock, b"1")
            os.fsync(broker_lock)
        os.lseek(broker_lock, 0, os.SEEK_SET)
        msvcrt.locking(broker_lock, msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        os.close(broker_lock)
        _broker_lock_descriptor = None
        raise RuntimeError("REQUESTER_BROKER_ALREADY_RUNNING") from exc
    verify_installed_requester_application(
        broker_root=root,
        application_kind="client",
        application_path=root / "bin/catalog-requester-client.pyz",
    )
    application_wrapper = verify_installed_requester_application(
        broker_root=root,
        application_kind="broker",
        application_path=Path(sys.argv[0]),
    )
    verify_acl_baseline(root)
    config = CatalogRequesterConfigV1.model_validate_json(
        (root / "config/catalog_requester_v1.json").read_bytes()
    )
    actors = json.loads(
        (root / "config/catalog_controller_actors_v1.json").read_text(
            encoding="utf-8"
        )
    )
    controls = json.loads(
        (root / "config/catalog_github_controls_v1.json").read_text(
            encoding="utf-8"
        )
    )
    request_actors = actors.get("request_actors") if isinstance(actors, dict) else None
    if (
        not isinstance(request_actors, list)
        or len(request_actors) != 1
        or not isinstance(request_actors[0], str)
        or not request_actors[0].endswith("[bot]")
    ):
        raise RuntimeError("REQUESTER_APP_ACTOR_UNBOUND")
    terminal_control = (
        controls.get("issue_labels", {}).get("terminal", {})
        if isinstance(controls, dict)
        and isinstance(controls.get("issue_labels"), dict)
        else {}
    )
    if (
        not isinstance(terminal_control, dict)
        or terminal_control.get("name") != config.terminal_close_marker.label
        or actors.get("ledger_actor") != config.terminal_close_marker.closed_by
    ):
        raise RuntimeError("REQUESTER_TERMINAL_MARKER_CONFIG_DRIFT")

    reparse_marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    app_binding_path = root / config.broker.secrets / "requester-app-binding-v1.json"
    try:
        binding_metadata = app_binding_path.stat(follow_symlinks=False)
        binding_data = app_binding_path.read_bytes()
        app_binding = json.loads(binding_data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("REQUESTER_APP_BINDING_INVALID") from exc
    if (
        app_binding_path.is_symlink()
        or not stat.S_ISREG(binding_metadata.st_mode)
        or getattr(binding_metadata, "st_file_attributes", 0) & reparse_marker
        or getattr(binding_metadata, "st_nlink", 1) != 1
        or binding_metadata.st_size > 4_096
        or not isinstance(app_binding, dict)
        or set(app_binding) != {"schema_version", "app_id", "installation_id"}
        or app_binding.get("schema_version") != "1"
        or type(app_binding.get("app_id")) is not int
        or type(app_binding.get("installation_id")) is not int
        or int(app_binding["app_id"]) < 1
        or int(app_binding["installation_id"]) < 1
        or binding_data
        != json.dumps(
            app_binding,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        + b"\n"
    ):
        raise RuntimeError("REQUESTER_APP_BINDING_INVALID")
    key_path = root / config.broker.secrets / "requester-private-key.pem"
    expected_key_path = root / config.broker.secrets / "requester-private-key.pem"
    if key_path.is_symlink() or key_path.resolve(strict=True) != expected_key_path:
        raise RuntimeError("REQUESTER_PRIVATE_KEY_PATH_INVALID")
    key_metadata = key_path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(key_metadata.st_mode)
        or getattr(key_metadata, "st_file_attributes", 0) & reparse_marker
        or getattr(key_metadata, "st_nlink", 1) != 1
        or key_metadata.st_size > 32_768
    ):
        raise RuntimeError("REQUESTER_PRIVATE_KEY_PATH_INVALID")
    private_key_pem = key_path.read_bytes()
    transport = RequestsCatalogBrokerHttpTransport(
        timeout_seconds=config.timeout_seconds
    )
    client = CatalogBrokerGithubClient(
        config=config,
        http=transport,
        app_id=int(app_binding["app_id"]),
        installation_id=int(app_binding["installation_id"]),
        private_key_pem=private_key_pem,
        expected_actor=request_actors[0],
    )
    if actors.get("requester_public_key_sha256") != (
        client.requester_public_key_sha256
    ):
        raise RuntimeError("REQUESTER_PUBLIC_IDENTITY_BINDING_INVALID")
    publish_catalog_broker_self_audit(
        broker_root=root,
        config=config,
        client=client,
        broker_application_sha256=str(application_wrapper["application_sha256"]),
        acl_baseline_sha256=hashlib.sha256(
            (root / "config/acl-baseline-v1.json").read_bytes()
        ).hexdigest(),
        observed_at=datetime.now(UTC),
    )

    processing = root / config.broker.processing
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    campaign_keys = tuple(
        sorted(
            {
                config.bootstrap_qualification.campaign_key,
                *(entry.campaign_key for entry in registry.campaigns if entry.active),
            }
        )
    )
    while True:
        observed_at = datetime.now(UTC)
        verify_acl_baseline(root)
        ensure_catalog_launch_tickets(
            broker_root=root,
            config=config,
            observed_at=observed_at,
            client=client,
        )
        capacity = publish_catalog_broker_capacity(
            broker_root=root,
            config=config,
            observed_at=observed_at,
        )
        if not capacity.available:
            quarantined = quarantine_one_invalid_catalog_broker_entry(
                broker_root=root,
                config=config,
            )
            if quarantined is not None:
                publish_catalog_broker_capacity(
                    broker_root=root,
                    config=config,
                    observed_at=datetime.now(UTC),
                )
                time.sleep(config.broker.poll_seconds)
                continue
            if capacity.reason_code == "REQUEST_BROKER_CAPACITY_UNPROVEN":
                time.sleep(config.broker.poll_seconds)
                continue
        busy_hint_names: set[str] = set()
        hint_claim_observed = False
        while len(busy_hint_names) < config.broker.maximum_pending_entries:
            claimed_hint = claim_next_catalog_reconcile_hint(
                broker_root=root,
                config=config,
                excluded_processing_names=frozenset(busy_hint_names),
            )
            if claimed_hint is None:
                break
            hint_claim_observed = True
            try:
                seal_claimed_spool_file(claimed_hint)
            except ValueError as exc:
                if str(exc) == "REQUESTER_BROKER_CLAIM_BUSY":
                    busy_hint_names.add(claimed_hint.name)
                    continue
                quarantine_invalid_claimed_catalog_request(
                    broker_root=root,
                    config=config,
                    claimed_path=claimed_hint,
                    reason_code="REQUESTER_BROKER_CLAIM_ACL_INVALID",
                    observed_at=observed_at,
                )
            else:
                process_claimed_catalog_reconcile_hint(
                    broker_root=root,
                    config=config,
                    claimed_path=claimed_hint,
                    client=client,
                    observed_at=observed_at,
                )
            break
        if hint_claim_observed:
            publish_catalog_broker_capacity(
                broker_root=root,
                config=config,
                observed_at=datetime.now(UTC),
            )
        for campaign_key in campaign_keys:
            journal_path = (
                root
                / config.broker.campaign_status
                / f"{campaign_key}.journal.json"
            )
            if not journal_path.exists():
                continue
            reconcile_active_catalog_campaign(
                broker_root=root,
                config=config,
                client=client,
                campaign_key=campaign_key,
                observed_at=observed_at,
            )
        busy_request_names: set[str] = set()
        request_claim_observed = False
        while len(busy_request_names) < config.broker.maximum_pending_entries:
            claimed = claim_next_catalog_request(
                broker_root=root,
                config=config,
                excluded_processing_names=frozenset(busy_request_names),
            )
            if claimed is None:
                break
            request_claim_observed = True
            try:
                seal_claimed_spool_file(claimed)
                load_claimed_catalog_draft(
                    claimed_path=claimed,
                    config=config,
                )
            except ValueError as exc:
                if str(exc) == "REQUESTER_BROKER_CLAIM_BUSY":
                    busy_request_names.add(claimed.name)
                    continue
                quarantine_invalid_claimed_catalog_request(
                    broker_root=root,
                    config=config,
                    claimed_path=claimed,
                    reason_code="REQUESTER_BROKER_REQUEST_INVALID",
                    observed_at=observed_at,
                )
            else:
                process_claimed_catalog_request(
                    broker_root=root,
                    config=config,
                    claimed_path=claimed,
                    private_key_pem=private_key_pem,
                    client=client,
                    observed_at=observed_at,
                )
            break
        if request_claim_observed:
            publish_catalog_broker_capacity(
                broker_root=root,
                config=config,
                observed_at=datetime.now(UTC),
            )
        time.sleep(config.broker.poll_seconds)


def main() -> int:
    """Keep retryable GitHub uncertainty alive without weakening fail-closed errors."""

    global _broker_lock_descriptor

    consecutive_failures = 0
    last_failure_at: float | None = None
    while True:
        try:
            return _broker_main()
        except (OSError, RuntimeError, ValueError) as exc:
            if str(exc) not in _RETRYABLE_REASON_CODES:
                raise
            import os
            import time

            if _broker_lock_descriptor is not None:
                os.close(_broker_lock_descriptor)
                _broker_lock_descriptor = None
            observed_at = time.monotonic()
            if last_failure_at is None or observed_at - last_failure_at >= 900:
                consecutive_failures = 1
            else:
                consecutive_failures += 1
            last_failure_at = observed_at
            retry_delay_seconds = min(
                900, 60 * (2 ** min(consecutive_failures - 1, 4))
            )
            provider_retry_after = getattr(exc, "retry_after_seconds", None)
            if type(provider_retry_after) is int and provider_retry_after > 0:
                retry_delay_seconds = max(
                    retry_delay_seconds,
                    provider_retry_after,
                )
            time.sleep(retry_delay_seconds)


__all__ = ["main"]
