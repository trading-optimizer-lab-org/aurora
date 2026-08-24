"""Development adapter for the unprivileged catalog requester client."""

from __future__ import annotations

import argparse


_BROKER_ROOT = "C:/ProgramData/AURORA/CatalogRequester"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit one registered catalog campaign through the locked broker."
    )
    parser.add_argument("--campaign-key", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    import ctypes
    from datetime import UTC, datetime
    import os
    from pathlib import Path
    import sys

    from .catalog_request_contract import canonical_model_bytes
    from .catalog_requester import (
        submit_registered_catalog_campaign,
        verify_installed_requester_application,
    )

    size = ctypes.c_ulong(256)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)):
        raise RuntimeError("REQUESTER_CLIENT_OS_IDENTITY_INVALID")
    ctypes.windll.shell32.IsUserAnAdmin.argtypes = ()
    ctypes.windll.shell32.IsUserAnAdmin.restype = ctypes.c_int
    if buffer.value.casefold() != "auroraagent" or (
        ctypes.windll.shell32.IsUserAnAdmin()
    ):
        raise RuntimeError("REQUESTER_CLIENT_OS_IDENTITY_INVALID")
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
            "AURORA_CATALOG_REQUESTER_APP_ID",
            "AURORA_CATALOG_REQUESTER_INSTALLATION_ID",
            "AURORA_CATALOG_REQUESTER_PRIVATE_KEY",
            "AURORA_CATALOG_REQUESTER_PRIVATE_KEY_PATH",
            "AURORA_CATALOG_REQUESTER_JWT",
            "AURORA_CATALOG_REQUESTER_TOKEN",
        )
    ):
        raise RuntimeError("AGENT_REQUESTER_CREDENTIAL_EXPOSED")
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
    service_home = Path.home()
    if any(
        path.exists() or path.is_symlink()
        for path in (
            service_home / ".config/gh/hosts.yml",
            service_home / "AppData/Roaming/GitHub CLI/hosts.yml",
        )
    ):
        raise RuntimeError("AGENT_ADMIN_CREDENTIAL_EXPOSED")

    root = Path(_BROKER_ROOT)
    try:
        expected_prefix = (root / "client-venv").resolve(strict=True)
        expected_executable = (
            expected_prefix / "Scripts/python.exe"
        ).resolve(strict=True)
        expected_application = (
            root / "bin/catalog-requester-client.pyz"
        ).resolve(strict=True)
        observed_executable = Path(sys.executable).resolve(strict=True)
        observed_prefix = Path(sys.prefix).resolve(strict=True)
        observed_base_prefix = Path(sys.base_prefix).resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("REQUESTER_CLIENT_RUNTIME_INVALID") from exc
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
        raise RuntimeError("REQUESTER_CLIENT_RUNTIME_INVALID")
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
            raise RuntimeError("REQUESTER_CLIENT_RUNTIME_INVALID")
        observed_path = Path(entry).resolve(strict=False)
        if observed_path not in allowed_runtime_paths:
            raise RuntimeError("REQUESTER_CLIENT_RUNTIME_INVALID")
    verify_installed_requester_application(
        broker_root=root,
        application_kind="client",
        application_path=Path(sys.argv[0]),
    )

    receipt = submit_registered_catalog_campaign(
        broker_root=root,
        campaign_key=args.campaign_key,
        observed_at=datetime.now(UTC),
    )
    print(canonical_model_bytes(receipt).decode("utf-8"))
    return 0


__all__ = ["main"]
