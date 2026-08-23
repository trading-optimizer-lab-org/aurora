"""Create-new custody for bootstrap private material on Windows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Protocol


REPOSITORY = "trading-optimizer-lab-org/aurora"
ENVIRONMENT = "catalog-production"
AUDITOR_SECRET = "AURORA_CATALOG_AUDITOR_PRIVATE_KEY"


class _RunResult(Protocol):
    returncode: int
    stdout: bytes
    stderr: bytes


class _Runner(Protocol):
    def __call__(self, args: list[str], **kwargs: object) -> _RunResult: ...


def clear_private_material(*values: bytearray) -> None:
    for value in values:
        for index in range(len(value)):
            value[index] = 0


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = os.lstat(path).st_file_attributes
    except AttributeError:
        return path.is_symlink()
    return bool(attributes & 0x400)


def _default_acl_checker(parent: Path) -> bool:
    if os.name != "nt" or not parent.is_dir() or _is_reparse_point(parent):
        return False
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$p=$args[0]; (Get-Acl -LiteralPath $p).Sddl",
            "--",
            str(parent),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return False
    sddl = result.stdout.strip()
    if not sddl.startswith("O:") or "D:" not in sddl:
        return False
    return not any(
        re.search(rf"\(A;[^)]*;;;{sid}\)", sddl)
        for sid in ("WD", "AU", "BU", "BG", "AN")
    )


def store_requester_key_once(
    path: Path,
    private_key_pem: bytearray,
    *,
    acl_checker: Callable[[Path], bool] = _default_acl_checker,
) -> str:
    path = Path(path)
    try:
        if not path.parent.is_dir() or not acl_checker(path.parent):
            raise ValueError("SECRET_ACL_OPEN")
        if _is_reparse_point(path.parent) or path.is_symlink():
            raise ValueError("SECRET_REPARSE_POINT")
        expected = hashlib.sha256(private_key_pem).hexdigest()
        try:
            with path.open("xb") as handle:
                handle.write(private_key_pem)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ValueError("SECRET_ALREADY_EXISTS") from exc
        if _is_reparse_point(path):
            raise ValueError("SECRET_REPARSE_POINT")
        with path.open("rb") as handle:
            observed = hashlib.sha256(handle.read()).hexdigest()
        if observed != expected:
            raise ValueError("SECRET_READBACK_MISMATCH")
        return observed
    finally:
        clear_private_material(private_key_pem)


def _checked_run(run: _Runner, args: list[str], *, input_data: bytes | None) -> bytes:
    result = run(
        args,
        input=input_data,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError("SECRET_DESTINATION_COMMAND_FAILED")
    return result.stdout


def upload_auditor_key_once(
    staging_path: Path,
    private_key_pem: bytearray,
    *,
    acl_checker: Callable[[Path], bool] = _default_acl_checker,
    run: _Runner = subprocess.run,
) -> dict[str, object]:
    store_requester_key_once(
        staging_path,
        private_key_pem,
        acl_checker=acl_checker,
    )
    upload_buffer = bytearray(staging_path.read_bytes())
    try:
        _checked_run(
            run,
            [
                "gh",
                "secret",
                "set",
                AUDITOR_SECRET,
                "--env",
                ENVIRONMENT,
                "--repo",
                REPOSITORY,
            ],
            input_data=bytes(upload_buffer),
        )
        raw = _checked_run(
            run,
            [
                "gh",
                "api",
                f"/repos/{REPOSITORY}/environments/{ENVIRONMENT}/secrets/{AUDITOR_SECRET}",
            ],
            input_data=None,
        )
        try:
            proof = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("SECRET_DESTINATION_PROOF_INVALID") from exc
        if not isinstance(proof, dict) or proof.get("name") != AUDITOR_SECRET:
            raise ValueError("SECRET_DESTINATION_PROOF_INVALID")
        staging_path.unlink()
        if staging_path.exists():
            raise ValueError("SECRET_STAGING_DELETE_FAILED")
        return proof
    finally:
        clear_private_material(upload_buffer)
