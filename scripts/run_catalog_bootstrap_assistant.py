"""Closed one-shot coordinator for AURORA catalog bootstrap."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Callable, Literal, Protocol, cast


UTC = timezone.utc


class _Fcntl(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, descriptor: int, operation: int) -> None: ...


class _Msvcrt(Protocol):
    LK_NBLCK: int
    LK_NBRLCK: int
    LK_UNLCK: int

    def locking(self, descriptor: int, mode: int, nbytes: int) -> None: ...


_fcntl: _Fcntl | None
_msvcrt: _Msvcrt | None


def _as_int(value: object) -> int:
    return int(cast(int | str | float | bytes | bytearray, value))

try:
        import fcntl as _fcntl_module
        _fcntl = cast(_Fcntl, _fcntl_module)
except ImportError:  # pragma: no cover - Windows uses msvcrt instead.
    _fcntl = None

try:
        import msvcrt as _msvcrt_module
        _msvcrt = cast(_Msvcrt, _msvcrt_module)
except ImportError:  # pragma: no cover - POSIX uses fcntl instead.
    _msvcrt = None


if TYPE_CHECKING:
    from infra.sp500_megarun.catalog_bootstrap_contract import (
        CatalogBootstrapAppManifestV1,
        CatalogBootstrapManifestSetV1,
    )
    from infra.sp500_megarun.catalog_bootstrap_github import CatalogAppPublicBinding
    from infra.sp500_megarun.catalog_bootstrap_github import VerifiedCatalogAppAccess
    from infra.sp500_megarun.catalog_bootstrap_finalizer import (
        CatalogBootstrapObservedProductionSealV1,
    )
    from infra.sp500_megarun.catalog_bootstrap_state import (
        CatalogBootstrapEventV1,
        CatalogBootstrapStateV1,
        EventName,
    )


def load_bootstrap_state(path: Path) -> CatalogBootstrapStateV1:
    from infra.sp500_megarun.catalog_bootstrap_state import load_bootstrap_state as load

    return load(path)


def persist_bootstrap_state(path: Path, state: CatalogBootstrapStateV1) -> None:
    from infra.sp500_megarun.catalog_bootstrap_state import (
        persist_bootstrap_state as persist,
    )

    persist(path, state)


def advance_bootstrap_state(
    state: CatalogBootstrapStateV1, event: CatalogBootstrapEventV1
) -> CatalogBootstrapStateV1:
    from infra.sp500_megarun.catalog_bootstrap_state import (
        advance_bootstrap_state as advance,
    )

    return advance(state, event)


def initial_bootstrap_state(
    bootstrap_id: str, protected_commit_sha: str
) -> CatalogBootstrapStateV1:
    from infra.sp500_megarun.catalog_bootstrap_state import (
        initial_bootstrap_state as initial,
    )

    return initial(bootstrap_id, protected_commit_sha)


class _CatalogBootstrapGitHubClient(Protocol):
    def find_exact_installation(
        self, expected: CatalogBootstrapAppManifestV1
    ) -> VerifiedCatalogAppAccess: ...

    def close(self) -> None: ...


def CatalogBootstrapGitHubClient(
    *, app_id: int, private_key_pem: bytearray
) -> _CatalogBootstrapGitHubClient:
    """Construct the GitHub client lazily while preserving the patchable API."""

    from infra.sp500_megarun.catalog_bootstrap_github import (
        CatalogBootstrapGitHubClient as client_type,
    )

    return client_type(app_id=app_id, private_key_pem=private_key_pem)


EXPECTED_ROOT = Path("C:/ProgramData/AURORA/CatalogBootstrap")
REPOSITORY: Literal["trading-optimizer-lab-org/aurora"] = (
    "trading-optimizer-lab-org/aurora"
)
BROKER_ROOT = Path("C:/ProgramData/AURORA/CatalogRequester")
AGENT_ROOT = Path("C:/ProgramData/AURORA/CatalogAgent")
BOOTSTRAP_STAGING_ROOT = Path("C:/ProgramData/AURORA/BootstrapStaging")
CONTROLLER_VARIABLE = "CATALOG_CONTROLLER_ENABLED"
ARMED_VARIABLE = "CATALOG_CONTROLLER_PRODUCTION_ARMED"
ENVIRONMENT = "catalog-production"
AUDITOR_SECRET = "AURORA_CATALOG_AUDITOR_PRIVATE_KEY"
ENTERPRISE_BILLING_SECRET = "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN"
ENTERPRISE_CACHE_VERIFIER_SECRET = (
    "AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN"
)
PACKAGE_INVENTORY_SECRET = "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN"
PROTECTED_ENVIRONMENT_REQUIRED_SECRETS = frozenset(
    {
        AUDITOR_SECRET,
        ENTERPRISE_BILLING_SECRET,
        ENTERPRISE_CACHE_VERIFIER_SECRET,
        PACKAGE_INVENTORY_SECRET,
    }
)
PROTECTED_ENVIRONMENT_EXTERNAL_SECRETS = (
    PROTECTED_ENVIRONMENT_REQUIRED_SECRETS - {AUDITOR_SECRET}
)
QUALIFICATION_CHECKPOINT_FILENAME = "qualification-substeps-v1.checkpoint.json"


class CatalogControllerShutdownError(RuntimeError):
    """Ordered controller-shutdown failures, compatible with Python 3.10."""

    def __init__(self, errors: list[Exception]) -> None:
        self.exceptions = tuple(errors)
        detail = "|".join(str(error) for error in errors)
        super().__init__(f"CATALOG_BOOTSTRAP_CONTROLLER_SHUTDOWN_FAILED:{detail}")
REQUESTER_TERMINAL_CHECKPOINT_FILENAME = "requester-qualification-terminal-v1.json"
REQUESTER_COMPLETE_CHECKPOINT_FILENAME = "requester-qualification-complete-v1.json"
_BOOTSTRAP_QUALIFICATION_CAMPAIGN = "controller-bootstrap-qualification-v1"
_QUALIFICATION_STEP_ORDER = (
    "live_2",
    "live_3",
    "policy_1",
    "policy_2",
    "policy_3",
    "controller_qualification_1",
    "controller_qualification_2",
    "controller_qualification_3",
    "capacity",
    "keeper",
    "requester",
)
_QUALIFICATION_STEP_WORKFLOWS = {
    "live_2": "catalog-live-controls-qualification.yml",
    "live_3": "catalog-live-controls-qualification.yml",
    "policy_1": "catalog-controller-policy-check.yml",
    "policy_2": "catalog-controller-policy-check.yml",
    "policy_3": "catalog-controller-policy-check.yml",
    "controller_qualification_1": "catalog-controller-qualification.yml",
    "controller_qualification_2": "catalog-controller-qualification.yml",
    "controller_qualification_3": "catalog-controller-qualification.yml",
    "capacity": "catalog-capacity-calibration.yml",
    "keeper": "catalog-artifact-keeper.yml",
}
_DISPATCH_INTENT_STEP_WORKFLOWS = {
    **_QUALIFICATION_STEP_WORKFLOWS,
    "github_controls_live_1": "catalog-live-controls-qualification.yml",
    "github_controls_runtime_upgrade_live_1": (
        "catalog-live-controls-qualification.yml"
    ),
    "final_pre_enable_live": "catalog-live-controls-qualification.yml",
    "final_post_enable_live": "catalog-live-controls-qualification.yml",
}
_QUALIFICATION_WORKFLOW_DISPLAY_NAMES = {
    "catalog-live-controls-qualification.yml": "Catalog live controls qualification",
    "catalog-controller-policy-check.yml": "Catalog controller policy",
    "catalog-controller-qualification.yml": (
        "AURORA catalog controller synthetic qualification"
    ),
    "catalog-capacity-calibration.yml": "Catalog capacity calibration",
    "catalog-artifact-keeper.yml": "Catalog artifact keeper",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_BOOTSTRAP_WORKFLOWS = frozenset(
    {
        "catalog-live-controls-qualification.yml",
        "catalog-controller-policy-check.yml",
        "catalog-controller-qualification.yml",
        "catalog-capacity-calibration.yml",
        "catalog-artifact-keeper.yml",
    }
)
_HEAVY_WORKFLOW_PATHS = frozenset(
    {
        ".github/workflows/catalog-component-worker.yml",
        ".github/workflows/catalog-optimized-run.yml",
        ".github/workflows/catalog-optimized-worker.yml",
        ".github/workflows/catalog-recovery-wave.yml",
    }
)
_PUBLIC_BINDING_PATHS = (
    "config/catalog_authority_anchor_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_auditor_v1.json",
    "config/catalog_requester_app_permissions_v1.json",
    "config/catalog_requester_public_key_v1.pem",
)
_LOCAL_INSTALL_REPAIR_PATHS = (
    "infra/sp500_megarun/catalog_bootstrap_state.py",
    "scripts/build_catalog_requester_apps.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/fixtures/catalog_controller_qualification/simulator.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS = (
    ".gitattributes",
    "scripts/build_catalog_requester_apps.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_COMPAT_REPAIR_PATHS = (
    "scripts/install_catalog_agent_sandbox.ps1",
    "scripts/install_catalog_requester_broker.ps1",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS = (
    "scripts/install_catalog_requester_broker.ps1",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_VERIFIER_REPAIR_PATHS = (
    "scripts/install_catalog_requester_broker.ps1",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_ACL_REPAIR_PATHS = _LOCAL_INSTALL_VERIFIER_REPAIR_PATHS
_LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS = _LOCAL_INSTALL_ACL_REPAIR_PATHS
_LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS = (
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
)
_GITHUB_CONTROLS_REPAIR_PATHS = (
    "infra/sp500_megarun/catalog_bootstrap_state.py",
    "scripts/apply_catalog_github_controls.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_github_controls.py",
)
_GITHUB_CONTROLS_FOLLOWUP_REPAIR_PATHS = (
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
)
_GITHUB_CONTROLS_ENTERPRISE_REPAIR_PATHS = (
    "config/catalog_github_auditor_v1.json",
    "config/catalog_github_controls_v1.json",
    "infra/sp500_megarun/catalog_github_controls.py",
    "schemas/catalog_github_auditor_v1.schema.json",
    "schemas/catalog_github_controls_v1.schema.json",
    "scripts/audit_catalog_github_controls.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_github_controls.py",
)
# Immutable changed-path evidence for the historical PR 176 repair. Later
# topology migrations must not rewrite the receipt contract retroactively.
_GITHUB_CONTROLS_BILLING_TOKEN_REPAIR_PATHS = (
    ".github/workflows/catalog-live-controls-audit.yml",
    "config/catalog_github_auditor_v1.json",
    "config/catalog_github_controls_v1.json",
    "infra/sp500_megarun/catalog_github_controls.py",
    "infra/sp500_megarun/catalog_requester_broker_cli.py",
    "infra/sp500_megarun/catalog_requester_cli.py",
    "schemas/catalog_github_auditor_v1.schema.json",
    "schemas/catalog_github_controls_v1.schema.json",
    "scripts/audit_catalog_agent_capabilities.ps1",
    "scripts/audit_catalog_github_controls.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_controller_workflows.py",
    "tests/test_catalog_github_controls.py",
    "tests/test_catalog_requester_packaging.py",
)
_GITHUB_CONTROLS_STABLE_PRECONDITION_REPAIR_PATHS = (
    "infra/sp500_megarun/catalog_github_controls.py",
    "scripts/apply_catalog_github_controls.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_github_controls.py",
)
_GITHUB_CONTROLS_CACHE_RETENTION_REPAIR_PATHS = (
    "config/catalog_github_controls_v1.json",
    "schemas/catalog_github_controls_v1.schema.json",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_github_controls.py",
)
_GITHUB_CONTROLS_STORAGE_AUDIT_REPAIR_PATHS = (
    ".github/actions/catalog-live-controls-audit/action.yml",
    "config/catalog_campaign_definitions/sp500-optimized-catalog-v1.manifest.json",
    "scripts/audit_catalog_github_controls.py",
    "scripts/run_catalog_artifact_keeper.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_controller_workflows.py",
    "tests/test_catalog_github_controls.py",
    "tests/test_sp500_catalog_optimized_engine.py",
)
_GITHUB_CONTROLS_AUDIT_THROUGHPUT_REPAIR_PATHS = (
    "scripts/apply_catalog_github_controls.py",
    "scripts/audit_catalog_github_controls.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_github_controls.py",
)
_GITHUB_CONTROLS_PACKAGE_TOKEN_REPAIR_PATHS = (
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
)
_IDEMPOTENT_RESUME_BRANCH = "codex/catalog-bootstrap-idempotent-resume"
_IDEMPOTENT_RESUME_PR_NUMBER = 194
_IDEMPOTENT_RESUME_REQUIRED_CHECK = "catalog-controller-policy"
_IDEMPOTENT_RESUME_FOLLOWUP_BRANCH = "codex/catalog-bootstrap-runtime-followup"
_IDEMPOTENT_RESUME_FOLLOWUP_PR_NUMBER = 196
_IDEMPOTENT_RESUME_FOLLOWUP_REQUIRED_CHECK = "catalog-controller-policy"
_IDEMPOTENT_RESUME_CATCHUP_BRANCH = "codex/catalog-bootstrap-runtime-catchup"
_IDEMPOTENT_RESUME_CATCHUP_PR_NUMBER = 197
_MAX_IDEMPOTENT_RESUME_UPGRADE_INDEX = 128
_IDEMPOTENT_RESUME_CATCHUP_REQUIRED_CHECK = "catalog-controller-policy"
_IDEMPOTENT_RESUME_ALLOWED_ROOTS = frozenset(
    {".github", "config", "docs", "infra", "schemas", "scripts", "tests"}
)
_BOOTSTRAP_REQUIRED_CHECK_NAMES = frozenset({"GTBI V7 stage-two required"})
_EXACT_REPOSITORY_REMOTES = frozenset(
    {
        "https://github.com/trading-optimizer-lab-org/aurora.git",
        "git@github.com:trading-optimizer-lab-org/aurora.git",
        "ssh://git@github.com/trading-optimizer-lab-org/aurora.git",
    }
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _safe_blocked_reason(exc: Exception, fallback: str) -> str:
    reason = str(exc)
    missing_prefix = "CATALOG_BOOTSTRAP_AUDITOR_ENVIRONMENT_SECRETS_MISSING:"
    if reason.startswith(missing_prefix):
        missing = reason.removeprefix(missing_prefix).split(",")
        if (
            missing
            and missing == sorted(set(missing))
            and set(missing) <= PROTECTED_ENVIRONMENT_REQUIRED_SECRETS
        ):
            return reason
    if not reason or len(reason) > 160 or any(
        marker in reason.casefold()
        for marker in ("private", "secret", "token", "password", "jwt")
    ):
        return fallback
    return reason


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_BOOTSTRAP_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> object:
    raise ValueError(f"CATALOG_BOOTSTRAP_JSON_NONFINITE:{value}")


def _is_reparse_path(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        info = path.lstat()
    except OSError:
        return False
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & reparse_attribute)


def _validate_exact_file_path(path: Path, error_code: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(error_code) from exc
    if (
        _is_reparse_path(path)
        or not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_nlink", 1) != 1
    ):
        raise ValueError(error_code)


def _read_canonical_document(path: Path, error_code: str) -> dict[str, object]:
    _validate_exact_file_path(path, error_code)
    try:
        data = path.read_bytes()
        if not data.endswith(b"\n") or data[:-1].endswith(b"\r"):
            raise ValueError
        value = json.loads(
            data[:-1].decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(value, dict) or _canonical(value) + b"\n" != data:
        raise ValueError(error_code)
    return value


def _checkpoint_lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _safe_unlink_checkpoint_temp(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        return
    if (
        _is_reparse_path(path)
        or not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_nlink", 1) != 1
    ):
        return
    try:
        path.unlink()
    except OSError:
        return


def _cleanup_checkpoint_temps(path: Path) -> None:
    try:
        candidates = tuple(path.parent.glob(f".{path.name}.*.tmp"))
    except OSError:
        return
    for candidate in candidates:
        _safe_unlink_checkpoint_temp(candidate)


def _validate_lock_descriptor(path: Path, descriptor: int) -> None:
    _validate_exact_file_path(path, "CATALOG_BOOTSTRAP_CHECKPOINT_LOCK_INVALID")
    try:
        observed = path.lstat()
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_LOCK_INVALID") from exc
    if (
        getattr(observed, "st_nlink", 1) != 1
        or not stat.S_ISREG(opened.st_mode)
        or getattr(opened, "st_nlink", 1) != 1
        or (
            getattr(observed, "st_ino", 0)
            and getattr(opened, "st_ino", 0)
            and (
                observed.st_ino != opened.st_ino
                or observed.st_dev != opened.st_dev
            )
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_LOCK_INVALID")


def _try_lock_descriptor(descriptor: int) -> bool:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if _msvcrt is not None:
        try:
            nonblocking = getattr(_msvcrt, "LK_NBRLCK", _msvcrt.LK_NBLCK)
            _msvcrt.locking(descriptor, nonblocking, 1)
        except OSError:
            return False
        return True
    if _fcntl is not None:
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_LOCK_UNSUPPORTED")


def _unlock_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if _msvcrt is not None:
        _msvcrt.locking(descriptor, _msvcrt.LK_UNLCK, 1)
    elif _fcntl is not None:
        _fcntl.flock(descriptor, _fcntl.LOCK_UN)


@contextmanager
def _exclusive_checkpoint_lock(
    path: Path, *, timeout_seconds: float = 30.0
) -> Iterator[None]:
    """Hold a validated cross-process lock for a checkpoint read/validate/write."""

    if timeout_seconds < 0:
        raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_LOCKED")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _checkpoint_lock_path(path)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    deadline: float | None = None
    descriptor: int | None = None
    acquired = False
    try:
        while not acquired:
            try:
                if lock_path.exists() or lock_path.is_symlink():
                    _validate_exact_file_path(
                        lock_path, "CATALOG_BOOTSTRAP_CHECKPOINT_LOCK_INVALID"
                    )
                    descriptor = os.open(str(lock_path), os.O_RDWR)
                else:
                    descriptor = os.open(str(lock_path), flags, 0o600)
                    if os.fstat(descriptor).st_size == 0:
                        os.write(descriptor, b"0")
                    os.fsync(descriptor)
                _validate_lock_descriptor(lock_path, descriptor)
                acquired = _try_lock_descriptor(descriptor)
            except FileExistsError:
                acquired = False
            except ValueError:
                raise
            except OSError:
                acquired = False
            if acquired:
                break
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                descriptor = None
            if deadline is None:
                deadline = time.monotonic() + timeout_seconds
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_LOCKED")
            time.sleep(min(0.05, remaining))

        locked_descriptor = cast(int, descriptor)
        if os.fstat(locked_descriptor).st_size == 0:
            os.write(locked_descriptor, b"0")
            os.fsync(locked_descriptor)
        yield
    finally:
        if descriptor is not None:
            if acquired:
                try:
                    _unlock_descriptor(descriptor)
                except OSError:
                    pass
            try:
                os.close(descriptor)
            except OSError:
                pass


def _write_checkpoint_bytes_locked(
    path: Path, data: bytes, *, replace_existing: bool
) -> str:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor: int | None = None
    published = False
    try:
        descriptor = os.open(str(temporary), flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _validate_exact_file_path(
            temporary, "CATALOG_BOOTSTRAP_CHECKPOINT_PATH_INVALID"
        )
        if not replace_existing:
            if path.exists() or path.is_symlink():
                _validate_exact_file_path(
                    path, "CATALOG_BOOTSTRAP_CHECKPOINT_PATH_INVALID"
                )
                if path.read_bytes() != data:
                    raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_CONFLICT")
                _safe_unlink_checkpoint_temp(temporary)
                return hashlib.sha256(data).hexdigest()
        _publish_checkpoint_temp(
            temporary, path, replace_existing=replace_existing
        )
        published = True
    except Exception as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _safe_unlink_checkpoint_temp(temporary)
        if isinstance(exc, ValueError):
            raise
        raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_WRITE_FAILED") from exc

    _validate_exact_file_path(path, "CATALOG_BOOTSTRAP_CHECKPOINT_PATH_INVALID")
    try:
        observed = path.read_bytes()
    except OSError as exc:
        raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_READBACK_INVALID") from exc
    if observed != data:
        raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_READBACK_INVALID")
    if not published:
        raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_WRITE_FAILED")
    _cleanup_checkpoint_temps(path)
    return hashlib.sha256(observed).hexdigest()


def _publish_checkpoint_temp(
    temporary: Path, path: Path, *, replace_existing: bool
) -> None:
    """Publish durable checkpoint bytes, including rename metadata."""

    if sys.platform == "win32":
        from ctypes import WinDLL, get_last_error

        move_file_ex = WinDLL("kernel32", use_last_error=True).MoveFileExW
        move_file_ex.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        move_file_ex.restype = ctypes.c_int
        flags = 0x8 | (0x1 if replace_existing else 0)  # WRITE_THROUGH | REPLACE
        if not move_file_ex(str(temporary), str(path), flags):
            error = get_last_error()
            raise OSError(error, "MoveFileExW checkpoint publication failed")
        return
    if replace_existing:
        os.replace(temporary, path)
    else:
        os.rename(temporary, path)
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    directory = os.open(str(path.parent), directory_flags)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_exact_canonical_checkpoint(path: Path, value: object) -> str:
    """Create one immutable canonical evidence file, or accept identical bytes."""

    data = _canonical(value) + b"\n"
    with _exclusive_checkpoint_lock(path):
        _cleanup_checkpoint_temps(path)
        if path.exists() or path.is_symlink():
            _validate_exact_file_path(path, "CATALOG_BOOTSTRAP_CHECKPOINT_PATH_INVALID")
            try:
                observed = path.read_bytes()
            except OSError as exc:
                raise ValueError(
                    "CATALOG_BOOTSTRAP_CHECKPOINT_READBACK_INVALID"
                ) from exc
            if observed != data:
                raise ValueError("CATALOG_BOOTSTRAP_CHECKPOINT_CONFLICT")
            return hashlib.sha256(observed).hexdigest()
        return _write_checkpoint_bytes_locked(path, data, replace_existing=False)


def _repository_remote_is_exact(remote: str) -> bool:
    return remote in _EXACT_REPOSITORY_REMOTES


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("CATALOG_BOOTSTRAP_CONTEXT_INVALID")
    return value


def _manifests() -> CatalogBootstrapManifestSetV1:
    from infra.sp500_megarun.catalog_bootstrap_contract import (
        CatalogBootstrapManifestSetV1,
    )

    with zipfile.ZipFile(Path(sys.argv[0])) as archive:
        data = archive.read("config/catalog_bootstrap_app_manifests_v1.json")
    return CatalogBootstrapManifestSetV1.model_validate_json(data)


def _state_path(root: Path) -> Path:
    return root / "state/catalog-bootstrap-state-v1.json"


def _context(root: Path) -> dict[str, object]:
    value = _read_json(root / "install-context-v1.json")
    if set(value) != {"repository", "source_commit_sha", "source_root"}:
        raise ValueError("CATALOG_BOOTSTRAP_CONTEXT_INVALID")
    if value["repository"] != REPOSITORY:
        raise ValueError("CATALOG_BOOTSTRAP_CONTEXT_INVALID")
    return value


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED")
    return result.stdout.strip()


def _run_with_input(
    args: list[str],
    body: object,
    *,
    cwd: Path | None = None,
    timeout_seconds: int = 120,
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        input=_canonical(body),
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED")
    return result.stdout.decode("utf-8").strip()


def _review_import_environment(root: Path, source: Path) -> dict[str, str]:
    source = source.resolve(strict=True)
    source_init = source / "__init__.py"
    if not source_init.is_file() or source_init.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    import_root = root / "review-import-v1"
    package_root = import_root / "aurora"
    package_root.mkdir(parents=True, exist_ok=True)
    shim = (
        "from pathlib import Path as _Path\n"
        f"_AURORA_SOURCE = _Path({json.dumps(str(source))})\n"
        "__path__ = [str(_AURORA_SOURCE)]\n"
        "__file__ = str(_AURORA_SOURCE / '__init__.py')\n"
        "exec(compile((_AURORA_SOURCE / '__init__.py').read_bytes(), "
        "__file__, 'exec'), globals(), globals())\n"
    ).encode("utf-8")
    shim_path = package_root / "__init__.py"
    if package_root.is_symlink() or shim_path.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    shim_path.write_bytes(shim)
    if shim_path.read_bytes() != shim:
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    sitecustomize = (
        "import importlib.util as _importlib_util\n"
        "import sys as _sys\n"
        "_sys.meta_path[:] = [\n"
        "    _finder for _finder in _sys.meta_path\n"
        "    if not getattr(_finder, '__module__', '').startswith("
        "'__editable___aurora_')\n"
        "]\n"
        f"_source = {json.dumps(str(source))}\n"
        "_spec = _importlib_util.spec_from_file_location("
        "'aurora', _source + '/__init__.py', "
        "submodule_search_locations=[_source])\n"
        "if _spec is None or _spec.loader is None:\n"
        "    raise RuntimeError('AURORA_SOURCE_IMPORT_FAILED')\n"
        "_module = _importlib_util.module_from_spec(_spec)\n"
        "_sys.modules['aurora'] = _module\n"
        "_spec.loader.exec_module(_module)\n"
    ).encode("utf-8")
    sitecustomize_path = import_root / "sitecustomize.py"
    if sitecustomize_path.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    sitecustomize_path.write_bytes(sitecustomize)
    if sitecustomize_path.read_bytes() != sitecustomize:
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() != "pythonpath"
    }
    environment["PYTHONPATH"] = str(import_root)
    return environment


def _write_canonical(path: Path, value: object) -> str:
    data = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def _read_repository_variable(name: str) -> str:
    if name not in {
        CONTROLLER_VARIABLE,
        ARMED_VARIABLE,
        "CATALOG_AUTHORITY_ISSUE_NUMBER",
        "AURORA_CATALOG_AUDITOR_APP_ID",
    }:
        raise ValueError("CATALOG_BOOTSTRAP_VARIABLE_FORBIDDEN")
    return _run(["gh", "variable", "get", name, "--repo", REPOSITORY])


def _set_repository_variable(name: str, value: str) -> str:
    if name not in {
        CONTROLLER_VARIABLE,
        ARMED_VARIABLE,
        "CATALOG_AUTHORITY_ISSUE_NUMBER",
        "AURORA_CATALOG_AUDITOR_APP_ID",
    }:
        raise ValueError("CATALOG_BOOTSTRAP_VARIABLE_FORBIDDEN")
    _run(["gh", "variable", "set", name, "--body", value, "--repo", REPOSITORY])
    observed = _read_repository_variable(name)
    if observed != value:
        raise ValueError("CATALOG_BOOTSTRAP_VARIABLE_READBACK_INVALID")
    return observed


def _disable_controller() -> None:
    errors: list[Exception] = []
    for name in (ARMED_VARIABLE, CONTROLLER_VARIABLE):
        try:
            _set_repository_variable(name, "false")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            errors.append(exc)
    if errors:
        raise CatalogControllerShutdownError(errors)


def _disable_controller_for_failure_receipt(
    root: Path,
    *,
    phase: str,
) -> bool:
    try:
        _disable_controller()
    except Exception:
        _write_canonical(
            root / "receipts/controller-bootstrap-shutdown-failed-v1.json",
            {
                "controller_enabled_readback": True,
                "phase": phase,
                "reason_code": "CATALOG_BOOTSTRAP_CONTROLLER_SHUTDOWN_FAILED",
                "result": "FAILED",
                "schema_version": "1",
            },
        )
        return False
    return True


def _controller_is_ready() -> bool:
    return (
        _read_repository_variable(CONTROLLER_VARIABLE) == "true"
        and _read_repository_variable(ARMED_VARIABLE) == "true"
    )


def _list_workflow_runs(workflow: str) -> list[dict[str, object]]:
    if workflow not in _ALLOWED_BOOTSTRAP_WORKFLOWS:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_FORBIDDEN")
    raw = _run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"/repos/{REPOSITORY}/actions/workflows/{workflow}/runs"
            "?branch=main&per_page=100",
        ]
    )
    try:
        pages = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_LIST_INVALID") from exc
    if not isinstance(pages, list):
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_LIST_INVALID")
    normalized: list[dict[str, object]] = []
    for page in pages:
        rows = page.get("workflow_runs") if isinstance(page, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_LIST_INVALID")
        for row in rows:
            normalized.append(
                {
                    "databaseId": row.get("id"),
                    "headSha": row.get("head_sha"),
                    "event": row.get("event"),
                    "status": row.get("status"),
                    "conclusion": row.get("conclusion"),
                    "createdAt": row.get("created_at"),
                    "url": row.get("html_url"),
                    "path": row.get("path"),
                }
            )
    return normalized


def _read_workflow_run_by_id(
    workflow: str,
    run_id: int,
    *,
    protected_commit_sha: str,
) -> dict[str, object]:
    if (
        workflow not in _ALLOWED_BOOTSTRAP_WORKFLOWS
        or isinstance(run_id, bool)
        or run_id < 1
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RUN_INVALID")
    raw = _run(
        [
            "gh",
            "api",
            f"/repos/{REPOSITORY}/actions/runs/{run_id}",
        ]
    )
    try:
        observed = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RUN_INVALID") from exc
    expected_path = f".github/workflows/{workflow}"
    if (
        not isinstance(observed, dict)
        or observed.get("path") != expected_path
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RUN_INVALID")
    normalized = {
        "databaseId": observed.get("id"),
        "headSha": observed.get("head_sha"),
        "event": observed.get("event"),
        "status": observed.get("status"),
        "conclusion": observed.get("conclusion"),
        "url": observed.get("html_url"),
    }
    _validate_workflow_run_result(normalized, protected_commit_sha=protected_commit_sha)
    if normalized["databaseId"] != run_id:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RUN_INVALID")
    return normalized


def _watch_workflow_run(run_id: int) -> None:
    watched = subprocess.run(
        ["gh", "run", "watch", str(run_id), "--repo", REPOSITORY, "--exit-status"],
        check=False,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if watched.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_FAILED")


def _new_workflow_run_candidates(
    rows: list[dict[str, object]],
    *,
    baseline_run_ids: set[int],
) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if isinstance(row.get("databaseId"), int)
        and not isinstance(row.get("databaseId"), bool)
        and _as_int(row["databaseId"]) not in baseline_run_ids
    ]


def _workflow_run_matches_dispatch(
    row: dict[str, object],
    *,
    workflow: str,
    protected_commit_sha: str,
) -> bool:
    return (
        row.get("event") == "workflow_dispatch"
        and row.get("headSha") == protected_commit_sha
        and row.get("path") == f".github/workflows/{workflow}"
    )


def _list_recent_heavy_workflow_runs(
    workflow_path: str,
) -> list[dict[str, object]]:
    if workflow_path not in _HEAVY_WORKFLOW_PATHS:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_FORBIDDEN")
    workflow_name = Path(workflow_path).name
    raw = _run(
        [
            "gh",
            "api",
            f"/repos/{REPOSITORY}/actions/workflows/{workflow_name}/runs"
            "?branch=main&per_page=100",
        ]
    )
    value = json.loads(raw)
    rows = value.get("workflow_runs") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_LIST_INVALID")
    return rows


def _dispatch_workflow(
    workflow: str,
    protected_commit_sha: str,
    *,
    baseline_run_ids: set[int] | None = None,
) -> dict[str, object]:
    if workflow not in _ALLOWED_BOOTSTRAP_WORKFLOWS or not _COMMIT.fullmatch(
        protected_commit_sha
    ):
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_FORBIDDEN")
    before = (
        set(baseline_run_ids)
        if baseline_run_ids is not None
        else {
            _as_int(row["databaseId"])
            for row in _list_workflow_runs(workflow)
            if isinstance(row.get("databaseId"), int)
        }
    )
    _run(
        [
            "gh",
            "workflow",
            "run",
            workflow,
            "--repo",
            REPOSITORY,
            "--ref",
            "main",
        ]
    )
    deadline = time.monotonic() + 300
    selected: dict[str, object] | None = None
    while time.monotonic() < deadline:
        new_runs = _new_workflow_run_candidates(
            _list_workflow_runs(workflow), baseline_run_ids=before
        )
        candidates = [
            row
            for row in new_runs
            if _workflow_run_matches_dispatch(
                row,
                workflow=workflow,
                protected_commit_sha=protected_commit_sha,
            )
        ]
        if len(new_runs) > 1 or len(candidates) > 1:
            raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_RUN_AMBIGUOUS")
        if new_runs and not candidates:
            raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_RUN_IDENTITY_AMBIGUOUS")
        if candidates:
            selected = candidates[0]
            break
        time.sleep(3)
    if selected is None:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_RUN_NOT_FOUND")
    run_id = _as_int(selected["databaseId"])
    _watch_workflow_run(run_id)
    return _read_workflow_run_by_id(
        workflow,
        run_id,
        protected_commit_sha=protected_commit_sha,
    )


def _qualification_dispatch_intent_path(root: Path, step_name: str) -> Path:
    if step_name not in _DISPATCH_INTENT_STEP_WORKFLOWS:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_DISPATCH_INTENT_INVALID")
    return root / f"qualification-dispatch-{step_name}-v1.intent.json"


def _new_qualification_dispatch_intent(
    *,
    step_name: str,
    workflow: str,
    protected_commit_sha: str,
    baseline_run_ids: set[int],
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1",
        "campaign_key": _BOOTSTRAP_QUALIFICATION_CAMPAIGN,
        "step_name": step_name,
        "workflow": workflow,
        "protected_commit_sha": protected_commit_sha,
        "baseline_run_ids": sorted(baseline_run_ids),
        "correlation_key_sha256": "0" * 64,
    }
    value["correlation_key_sha256"] = _seal_hash(
        value, "correlation_key_sha256"
    )
    return value


def _validate_qualification_dispatch_intent(
    value: dict[str, object],
    *,
    step_name: str,
    protected_commit_sha: str,
) -> None:
    workflow = _DISPATCH_INTENT_STEP_WORKFLOWS.get(step_name)
    baseline = value.get("baseline_run_ids")
    if (
        set(value)
        != {
            "schema_version",
            "campaign_key",
            "step_name",
            "workflow",
            "protected_commit_sha",
            "baseline_run_ids",
            "correlation_key_sha256",
        }
        or value.get("schema_version") != "1"
        or value.get("campaign_key") != _BOOTSTRAP_QUALIFICATION_CAMPAIGN
        or value.get("step_name") != step_name
        or value.get("workflow") != workflow
        or value.get("protected_commit_sha") != protected_commit_sha
        or not isinstance(baseline, list)
        or any(
            isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1
            for run_id in baseline
        )
        or baseline != sorted(set(baseline))
        or not _SHA256.fullmatch(str(value.get("correlation_key_sha256", "")))
        or _seal_hash(value, "correlation_key_sha256")
        != value.get("correlation_key_sha256")
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_DISPATCH_INTENT_INVALID")


def _reconcile_qualification_dispatch_intent(
    intent: dict[str, object],
) -> dict[str, object]:
    workflow = str(intent["workflow"])
    protected_commit_sha = str(intent["protected_commit_sha"])
    baseline_run_ids = {
        _as_int(run_id)
        for run_id in cast(list[object], intent["baseline_run_ids"])
    }
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        new_runs = _new_workflow_run_candidates(
            _list_workflow_runs(workflow), baseline_run_ids=baseline_run_ids
        )
        candidates = [
            row
            for row in new_runs
            if _workflow_run_matches_dispatch(
                row,
                workflow=workflow,
                protected_commit_sha=protected_commit_sha,
            )
        ]
        if len(new_runs) > 1 or len(candidates) > 1:
            raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RUN_AMBIGUOUS")
        if new_runs and not candidates:
            raise ValueError(
                "CATALOG_BOOTSTRAP_QUALIFICATION_RUN_IDENTITY_AMBIGUOUS"
            )
        if candidates:
            run_id = _as_int(candidates[0]["databaseId"])
            _watch_workflow_run(run_id)
            return _read_workflow_run_by_id(
                workflow,
                run_id,
                protected_commit_sha=protected_commit_sha,
            )
        time.sleep(3)
    raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RUN_NOT_FOUND")


def _run_qualification_workflow_step(
    root: Path,
    step_name: str,
    protected_commit_sha: str,
) -> dict[str, object]:
    workflow = _DISPATCH_INTENT_STEP_WORKFLOWS.get(step_name)
    if workflow is None or not _COMMIT.fullmatch(protected_commit_sha):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_DISPATCH_INTENT_INVALID")
    intent_path = _qualification_dispatch_intent_path(root, step_name)
    dispatch_guard = intent_path.with_name(f".{intent_path.name}.dispatch-guard")
    with _exclusive_checkpoint_lock(dispatch_guard, timeout_seconds=4000):
        if intent_path.exists() or intent_path.is_symlink():
            intent = _read_canonical_document(
                intent_path,
                "CATALOG_BOOTSTRAP_QUALIFICATION_DISPATCH_INTENT_INVALID",
            )
            _validate_qualification_dispatch_intent(
                intent,
                step_name=step_name,
                protected_commit_sha=protected_commit_sha,
            )
            return _reconcile_qualification_dispatch_intent(intent)

        baseline_run_ids = {
            _as_int(row["databaseId"])
            for row in _list_workflow_runs(workflow)
            if isinstance(row.get("databaseId"), int)
            and not isinstance(row.get("databaseId"), bool)
        }
        intent = _new_qualification_dispatch_intent(
            step_name=step_name,
            workflow=workflow,
            protected_commit_sha=protected_commit_sha,
            baseline_run_ids=baseline_run_ids,
        )
        _write_exact_canonical_checkpoint(intent_path, intent)
        return _dispatch_workflow(
            workflow,
            protected_commit_sha,
            baseline_run_ids=baseline_run_ids,
        )


def _download_live_qualification(
    root: Path,
    run: dict[str, object],
    protected_commit_sha: str,
) -> dict[str, object]:
    run_id = _as_int(run["databaseId"])
    destination = root / f"receipts/live-controls-{run_id}"
    if not destination.exists():
        destination.mkdir(parents=True)
        _run(
            [
                "gh",
                "run",
                "download",
                str(run_id),
                "--repo",
                REPOSITORY,
                "--name",
                f"catalog-live-controls-qualification-{run_id}",
                "--dir",
                str(destination),
            ],
            timeout_seconds=600,
        )
    receipt_path = destination / "catalog_live_controls_qualification_receipt_v1.json"
    data = receipt_path.read_bytes()
    receipt = _read_json(receipt_path)
    if (
        data != _canonical(receipt) + b"\n"
        or set(receipt)
        != {
            "schema_version",
            "observer_context",
            "protected_commit_sha",
            "admission_receipt_sha256",
            "terminal_receipt_sha256",
            "receipt_sha256",
        }
        or receipt.get("schema_version") != "1"
        or receipt.get("observer_context") != "live_qualification"
        or receipt.get("protected_commit_sha") != protected_commit_sha
        or any(
            not _SHA256.fullmatch(str(receipt.get(name, "")))
            for name in (
                "admission_receipt_sha256",
                "terminal_receipt_sha256",
                "receipt_sha256",
            )
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LIVE_RECEIPT_INVALID")
    identity = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if hashlib.sha256(_canonical(identity)).hexdigest() != receipt["receipt_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_LIVE_RECEIPT_INVALID")
    return {
        "run_id": run_id,
        "run_url": run.get("url"),
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "receipt": receipt,
    }


def _run_live_qualification(
    root: Path,
    protected_commit_sha: str,
    *,
    step_name: str | None = None,
) -> dict[str, object]:
    if step_name not in _DISPATCH_INTENT_STEP_WORKFLOWS:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_DISPATCH_INTENT_INVALID")
    run = _run_qualification_workflow_step(root, step_name, protected_commit_sha)
    return _download_live_qualification(root, run, protected_commit_sha)


def _github_activity_snapshot() -> dict[str, object]:
    issue_pages = json.loads(
        _run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"/repos/{REPOSITORY}/issues?state=all&per_page=100",
            ]
        )
    )
    issues = [row for page in issue_pages for row in page]
    requests = [
        _as_int(row["number"])
        for row in issues
        if isinstance(row, dict)
        and "pull_request" not in row
        and isinstance(row.get("number"), int)
        and str(row.get("title", "")).startswith("[AURORA CATALOG RUN REQUEST] ")
    ]
    heavy = {
        _as_int(row["id"])
        for workflow_path in _HEAVY_WORKFLOW_PATHS
        for row in _list_recent_heavy_workflow_runs(workflow_path)
        if isinstance(row.get("id"), int) and row.get("path") == workflow_path
    }
    return {
        "request_issue_numbers": sorted(requests),
        "heavy_run_ids": sorted(heavy),
    }


def _run_binding_review_rounds(root: Path, source: Path) -> dict[str, object]:
    staged_tree = _run(["git", "write-tree"], cwd=source)
    if not _COMMIT.fullmatch(staged_tree):
        raise ValueError("CATALOG_BOOTSTRAP_BINDING_TREE_INVALID")
    review_environment = _review_import_environment(root, source)
    rounds: list[dict[str, object]] = []
    test_paths = (
        "tests/test_catalog_bootstrap_binding.py",
        "tests/test_catalog_authority_ledger.py",
        "tests/test_catalog_github_controls.py",
        "tests/test_catalog_controller_workflows.py",
        "tests/test_catalog_run_request.py",
        "tests/test_submit_catalog_run_request.py",
        "tests/test_catalog_requester_broker.py",
    )
    for number in range(1, 4):
        _run(
            ["C:/Python314/python.exe", "-m", "pytest", "-q", *test_paths],
            cwd=source,
            env=review_environment,
            timeout_seconds=3600,
        )
        _run(
            [
                "C:/Python314/python.exe",
                "-m",
                "ruff",
                "check",
                "infra/sp500_megarun/catalog_bootstrap_binding.py",
                *test_paths,
            ],
            cwd=source,
            env=review_environment,
            timeout_seconds=600,
        )
        _run(["git", "diff", "--cached", "--check"], cwd=source)
        observed_tree = _run(["git", "write-tree"], cwd=source)
        staged_diff = _run(["git", "diff", "--cached", "--binary"], cwd=source)
        if observed_tree != staged_tree or any(
            marker in staged_diff
            for marker in (
                "BEGIN PRIVATE KEY",
                "BEGIN RSA PRIVATE KEY",
                "github_pat_",
                "ghp_",
            )
        ):
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_REVIEW_FAILED")
        round_receipt = {
            "round": number,
            "staged_tree_sha": staged_tree,
            "changed_paths": list(
                sorted(
                    path
                    for path in _run(
                        ["git", "diff", "--cached", "--name-only"], cwd=source
                    ).splitlines()
                    if path
                )
            ),
            "material_problems_found": [],
        }
        round_receipt["round_sha256"] = hashlib.sha256(
            _canonical(round_receipt)
        ).hexdigest()
        rounds.append(round_receipt)
    result: dict[str, object] = {"staged_tree_sha": staged_tree, "rounds": rounds}
    _write_canonical(root / "binding-review-rounds-v1.json", result)
    return result


def _event(
    state: CatalogBootstrapStateV1,
    name: EventName,
    evidence: object,
) -> CatalogBootstrapEventV1:
    from infra.sp500_megarun.catalog_bootstrap_state import CatalogBootstrapEventV1

    return CatalogBootstrapEventV1(
        schema_version="1",
        bootstrap_id=state.bootstrap_id,
        sequence=state.sequence + 1,
        name=name,
        protected_commit_sha=state.protected_commit_sha,
        observed_at=datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        evidence_sha256=hashlib.sha256(_canonical(evidence)).hexdigest(),
    )


def _advance(
    root: Path,
    state: CatalogBootstrapStateV1,
    name: EventName,
    evidence: object,
) -> None:
    persist_bootstrap_state(
        _state_path(root),
        advance_bootstrap_state(state, _event(state, name, evidence)),
    )


def perform_precheck(root: Path) -> None:
    if root.resolve() != EXPECTED_ROOT.resolve():
        raise ValueError("CATALOG_BOOTSTRAP_ROOT_INVALID")
    _disable_controller()
    context = _context(root)
    source = Path(str(context["source_root"]))
    head = _run(["git", "rev-parse", "HEAD"], cwd=source)
    if head != context["source_commit_sha"]:
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_COMMIT_CHANGED")
    if _run(["git", "status", "--porcelain=v1", "--untracked-files=no"], cwd=source):
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_DIRTY")
    enabled = "false"
    armed = "false"
    baseline = _github_activity_snapshot()
    _write_canonical(root / "github-activity-baseline-v1.json", baseline)
    state = initial_bootstrap_state(
        f"bootstrap-{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}",
        head,
    )
    persist_bootstrap_state(_state_path(root), state)
    _advance(
        root,
        state,
        "precheck_passed",
        {"head": head, "enabled": enabled, "armed": armed, "activity": baseline},
    )


def _stop_hp_codex_processes() -> None:
    command = (
        "$rows=Get-CimInstance Win32_Process | Where-Object {$_.Name -in "
        "@('ChatGPT.exe','codex.exe')}; foreach($p in $rows){"
        "$o=Invoke-CimMethod -InputObject $p -MethodName GetOwner;"
        "if($o.User -eq 'HP'){Stop-Process -Id $p.ProcessId -Force}};"
        "Start-Sleep -Milliseconds 500; $left=Get-CimInstance Win32_Process | "
        "Where-Object {$_.Name -in @('ChatGPT.exe','codex.exe')};"
        "foreach($p in $left){$o=Invoke-CimMethod -InputObject $p -MethodName GetOwner;"
        "if($o.User -eq 'HP'){exit 17}}"
    )
    _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]
    )


def _create_app(root: Path, kind: Literal["requester", "auditor"]) -> None:
    from infra.sp500_megarun.catalog_bootstrap_github import derive_public_binding
    from infra.sp500_megarun.catalog_bootstrap_manifest import (
        ManifestLoopbackServer,
        exchange_manifest_code,
        start_manifest_session,
    )
    from infra.sp500_megarun.catalog_bootstrap_secrets import store_requester_key_once

    state = load_bootstrap_state(_state_path(root))
    app: CatalogBootstrapAppManifestV1 = getattr(_manifests(), kind)
    session = start_manifest_session(
        kind,
        now=datetime.now(tz=UTC),
    )
    with ManifestLoopbackServer(session, app) as server:
        _write_canonical(
            root / "browser-action-v1.json",
            {
                "schema_version": "1",
                "action": f"create_{kind}_app",
                "url": server.start_url,
                "expires_at": session.expires_at.isoformat().replace("+00:00", "Z"),
            },
        )
        accepted = server.wait(timeout_seconds=3600)
    conversion = exchange_manifest_code(accepted.query["code"])
    try:
        binding = derive_public_binding(
            kind=kind,
            app_id=conversion.app_id,
            slug=conversion.slug,
            private_key_pem=conversion.private_key_pem,
        )
        secret_root = root / "secrets"
        secret_root.mkdir(parents=True, exist_ok=True)
        store_requester_key_once(
            secret_root / f"{kind}-pending.pem",
            conversion.private_key_pem,
        )
        public = {
            "app_id": binding.app_id,
            "app_slug": binding.app_slug,
            "kind": kind,
            "public_key_pem": binding.public_key_pem.decode("ascii"),
            "public_key_sha256": binding.public_key_sha256,
        }
        (root / f"{kind}-public-v1.json").write_bytes(_canonical(public) + b"\n")
    finally:
        conversion.clear()
        (root / "browser-action-v1.json").unlink(missing_ok=True)
    name: EventName = (
        "requester_created" if kind == "requester" else "auditor_created"
    )
    _advance(root, state, name, public)


def create_requester(root: Path) -> None:
    _create_app(root, "requester")


def create_auditor(root: Path) -> None:
    _create_app(root, "auditor")


def _verify_installation(
    root: Path, kind: Literal["requester", "auditor"]
) -> None:
    state = load_bootstrap_state(_state_path(root))
    app = getattr(_manifests(), kind)
    public_path = root / f"{kind}-public-v1.json"
    public = _read_json(public_path)
    key_buffer = bytearray((root / f"secrets/{kind}-pending.pem").read_bytes())
    client = CatalogBootstrapGitHubClient(
        app_id=_as_int(public["app_id"]),
        private_key_pem=key_buffer,
    )
    install_url = f"https://github.com/apps/{public['app_slug']}/installations/new"
    _write_canonical(
        root / "browser-action-v1.json",
        {
            "schema_version": "1",
            "action": f"install_{kind}_app",
            "url": install_url,
        },
    )
    deadline = time.monotonic() + 3600
    while True:
        try:
            access = client.find_exact_installation(app)
            break
        except ValueError as exc:
            if str(exc) != "APP_INSTALLATION_NOT_EXACT" or time.monotonic() >= deadline:
                client.close()
                raise
            time.sleep(5)
    client.close()
    (root / "browser-action-v1.json").unlink(missing_ok=True)
    public["installation_id"] = access.installation_id
    public_path.write_bytes(_canonical(public) + b"\n")
    name: EventName = (
        "requester_installed" if kind == "requester" else "auditor_installed"
    )
    _advance(root, state, name, public)


def verify_requester_installation(root: Path) -> None:
    _verify_installation(root, "requester")


def verify_auditor_installation(root: Path) -> None:
    _verify_installation(root, "auditor")


def _public_binding(root: Path, kind: str) -> CatalogAppPublicBinding:
    from infra.sp500_megarun.catalog_bootstrap_github import CatalogAppPublicBinding

    value = _read_json(root / f"{kind}-public-v1.json")
    return CatalogAppPublicBinding(
        kind=kind,
        app_id=_as_int(value["app_id"]),
        app_slug=str(value["app_slug"]),
        public_key_pem=str(value["public_key_pem"]).encode("ascii"),
        public_key_sha256=str(value["public_key_sha256"]),
    )


def _authority_issue() -> dict[str, object]:
    from infra.sp500_megarun.catalog_bootstrap_binding import (
        create_or_verify_authority_anchor,
    )

    raw = _run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"/repos/{REPOSITORY}/issues?state=all&per_page=100",
        ]
    )
    pages = json.loads(raw)
    rows = [item for page in pages for item in page]
    exact_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("title") == "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT"
        and "pull_request" not in row
    ]
    if not exact_rows:
        created = json.loads(
            _run_with_input(
                [
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    f"/repos/{REPOSITORY}/issues",
                    "--input",
                    "-",
                ],
                {
                    "body": "AURORA CATALOG AUTHORITY LEDGER V1\n",
                    "title": "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT",
                },
            )
        )
        exact_rows = [created]
    if len(exact_rows) != 1 or not isinstance(exact_rows[0].get("number"), int):
        raise ValueError("MULTIPLE_ANCHORS")
    comment_pages = json.loads(
        _run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"/repos/{REPOSITORY}/issues/{exact_rows[0]['number']}/comments?per_page=100",
            ]
        )
    )
    comments = [row for page in comment_pages for row in page]
    if comments:
        raise ValueError("AUTHORITY_ANCHOR_NOT_EMPTY")
    candidates = [
        {
            "repository": REPOSITORY,
            "repository_node_id": json.loads(
                _run(["gh", "api", f"/repos/{REPOSITORY}"])
            )["node_id"],
            "number": row.get("number"),
            "node_id": row.get("node_id"),
            "title": row.get("title"),
            "creator_login": row.get("user", {}).get("login"),
            "created_at": row.get("created_at"),
        }
        for row in exact_rows
    ]
    return dict(create_or_verify_authority_anchor(candidates))


def apply_public_binding(root: Path) -> None:
    from infra.sp500_megarun.catalog_bootstrap_binding import build_public_binding_patch

    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    requester = _public_binding(root, "requester")
    auditor = _public_binding(root, "auditor")
    authority = _authority_issue()
    tree = {
        path: (source / path).read_bytes()
        for path in (
            "config/catalog_controller_actors_v1.json",
            "config/catalog_github_auditor_v1.json",
        )
    }
    patch = build_public_binding_patch(requester, auditor, authority, tree)
    branch_hash = hashlib.sha256(
        f"{requester.app_id}:{auditor.app_id}".encode()
    ).hexdigest()[:12]
    branch = f"catalog/bootstrap-binding-{branch_hash}"
    _run(["git", "fetch", "origin", "main"], cwd=source)
    existing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=source,
        check=False,
    ).returncode == 0
    if existing:
        _run(["git", "switch", branch], cwd=source)
    else:
        _run(["git", "switch", "--create", branch, "origin/main"], cwd=source)
    for relative, data in patch.documents.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _run(["git", "add", "--", *patch.changed_paths], cwd=source)
    changed = tuple(
        sorted(
            line
            for line in _run(
                ["git", "diff", "--cached", "--name-only"], cwd=source
            ).splitlines()
            if line
        )
    )
    if not changed and existing:
        committed = tuple(
            sorted(
                line
                for line in _run(
                    ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                    cwd=source,
                ).splitlines()
                if line
            )
        )
        ahead = _run(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=source)
        if committed != patch.changed_paths or ahead != "1":
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_REPLAY_INVALID")
        review = _read_json(root / "binding-review-rounds-v1.json")
    else:
        if changed != patch.changed_paths:
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_DIFF_INVALID")
        if _run(["git", "diff", "--cached", "--check"], cwd=source):
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_DIFF_INVALID")
        review = _run_binding_review_rounds(root, source)
        commit_result = subprocess.run(
            ["git", "commit", "-m", "chore: bind catalog controller identities"],
            cwd=source,
            check=False,
            capture_output=True,
            text=True,
        )
        if commit_result.returncode != 0:
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_COMMIT_FAILED")
    head = _run(["git", "rev-parse", "HEAD"], cwd=source)
    _run(["git", "push", "--set-upstream", "origin", branch], cwd=source)
    listed = json.loads(
        _run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                REPOSITORY,
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number,headRefOid",
            ]
        )
    )
    if len(listed) > 1:
        raise ValueError("MULTIPLE_BOOTSTRAP_PRS")
    if listed:
        pr_number = int(listed[0]["number"])
    else:
        url = _run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                REPOSITORY,
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                "chore: bind catalog controller identities",
                "--body",
                "Automated public-only catalog bootstrap binding.",
            ],
            cwd=source,
        )
        pr_number = int(url.rstrip("/").split("/")[-1])
    receipt = {
        "binding_commit_sha": head,
        "branch": branch,
        "pr_number": pr_number,
        "review_rounds_sha256": hashlib.sha256(_canonical(review)).hexdigest(),
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        _canonical(receipt) + b"\n"
    )
    _advance(root, state, "public_binding_committed", receipt)


def _wait_for_required_checks(
    pr_number: str,
    source: Path,
    *,
    timeout_seconds: int = 1800,
    poll_seconds: int = 5,
) -> tuple[dict[str, str], ...]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "checks",
                pr_number,
                "--repo",
                REPOSITORY,
                "--required",
                "--json",
                "name,state,bucket",
            ],
            cwd=source,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        rows: object = None
        if result.stdout.strip():
            try:
                rows = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID") from exc
        if isinstance(rows, list) and rows:
            normalized: list[dict[str, str]] = []
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("name"), str)
                    or not isinstance(row.get("state"), str)
                    or row.get("bucket") not in {"pass", "pending", "fail", "cancel"}
                ):
                    raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
                normalized.append(
                    {
                        "bucket": str(row["bucket"]),
                        "name": str(row["name"]),
                        "state": str(row["state"]),
                    }
                )
            if len({row["name"] for row in normalized}) != len(normalized):
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
            if not _BOOTSTRAP_REQUIRED_CHECK_NAMES.issubset(
                {row["name"] for row in normalized}
            ):
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
            if any(row["bucket"] in {"fail", "cancel"} for row in normalized):
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECK_FAILED")
            if all(row["bucket"] == "pass" for row in normalized):
                return tuple(sorted(normalized, key=lambda row: row["name"]))
        elif rows is not None and rows != []:
            raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
        elif result.returncode != 0:
            message = f"{result.stdout}\n{result.stderr}".casefold()
            if "no required checks reported" not in message:
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
        time.sleep(poll_seconds)
    raise ValueError("BOOTSTRAP_PR_NOT_READY")


def _verify_existing_installations(root: Path) -> dict[str, int]:
    from infra.sp500_megarun.catalog_bootstrap_secrets import clear_private_material

    observed: dict[str, int] = {}
    manifests = _manifests()
    for kind in ("requester", "auditor"):
        public = _read_json(root / f"{kind}-public-v1.json")
        installation_id = public.get("installation_id")
        app_id = public.get("app_id")
        key_path = root / f"secrets/{kind}-pending.pem"
        if (
            not isinstance(installation_id, int)
            or not isinstance(app_id, int)
            or not key_path.is_file()
            or key_path.is_symlink()
        ):
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_INSTALLATION_INVALID")
        key_buffer = bytearray(key_path.read_bytes())
        client: _CatalogBootstrapGitHubClient | None = None
        try:
            client = CatalogBootstrapGitHubClient(
                app_id=app_id,
                private_key_pem=key_buffer,
            )
            access = client.find_exact_installation(getattr(manifests, kind))
        finally:
            if client is None:
                clear_private_material(key_buffer)
            else:
                client.close()
        if access.installation_id != installation_id:
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_INSTALLATION_INVALID")
        observed[kind] = installation_id
    return dict(sorted(observed.items()))


def _protected_environment_secret_names() -> frozenset[str]:
    raw = _run(
        [
            "gh", "secret", "list", "--env", ENVIRONMENT, "--repo",
            REPOSITORY, "--json", "name",
        ]
    )
    try:
        rows = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "CATALOG_BOOTSTRAP_ENVIRONMENT_SECRET_LIST_INVALID"
        ) from exc
    if not isinstance(rows, list):
        raise ValueError("CATALOG_BOOTSTRAP_ENVIRONMENT_SECRET_LIST_INVALID")
    names: list[str] = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"name"}
            or not isinstance(row.get("name"), str)
            or not row["name"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_ENVIRONMENT_SECRET_LIST_INVALID")
        names.append(row["name"])
    if len(names) != len(set(names)):
        raise ValueError("CATALOG_BOOTSTRAP_ENVIRONMENT_SECRET_LIST_INVALID")
    return frozenset(names)


def _require_protected_environment_secrets(
    required: frozenset[str],
) -> None:
    names = _protected_environment_secret_names()
    missing = sorted(required - names)
    if missing:
        raise ValueError(
            "CATALOG_BOOTSTRAP_AUDITOR_ENVIRONMENT_SECRETS_MISSING:"
            + ",".join(missing)
        )


def _protected_environment_secret_exists() -> bool:
    return AUDITOR_SECRET in _protected_environment_secret_names()


def _verify_post_install_installations(
    root: Path,
    *,
    allow_uploaded_auditor: bool = False,
) -> dict[str, int]:
    from infra.sp500_megarun.catalog_bootstrap_secrets import clear_private_material

    observed: dict[str, int] = {}
    manifests = _manifests()
    key_paths = {
        "requester": BROKER_ROOT / "secrets/requester-private-key.pem",
        "auditor": root / "secrets/auditor-pending.pem",
    }
    for kind in ("requester", "auditor"):
        public = _read_json(root / f"{kind}-public-v1.json")
        installation_id = public.get("installation_id")
        app_id = public.get("app_id")
        key_path = key_paths[kind]
        if (
            kind == "auditor"
            and allow_uploaded_auditor
            and isinstance(installation_id, int)
            and isinstance(app_id, int)
            and not key_path.exists()
            and _protected_environment_secret_exists()
        ):
            observed[kind] = installation_id
            continue
        if (
            not isinstance(installation_id, int)
            or not isinstance(app_id, int)
            or not key_path.is_file()
            or key_path.is_symlink()
        ):
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_INSTALLATION_INVALID")
        key_buffer = bytearray(key_path.read_bytes())
        client: _CatalogBootstrapGitHubClient | None = None
        try:
            client = CatalogBootstrapGitHubClient(
                app_id=app_id,
                private_key_pem=key_buffer,
            )
            access = client.find_exact_installation(getattr(manifests, kind))
        finally:
            if client is None:
                clear_private_material(key_buffer)
            else:
                client.close()
        if access.installation_id != installation_id:
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_INSTALLATION_INVALID")
        observed[kind] = installation_id
    return dict(sorted(observed.items()))


def _validated_binding_review(
    root: Path,
    operation: dict[str, object],
) -> dict[str, object]:
    review_path = root / "binding-review-rounds-v1.json"
    review = _read_json(review_path)
    if (
        review_path.read_bytes() != _canonical(review) + b"\n"
        or
        hashlib.sha256(_canonical(review)).hexdigest()
        != operation.get("review_rounds_sha256")
        or not _COMMIT.fullmatch(str(review.get("staged_tree_sha", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_REVIEW_INVALID")
    rounds = review.get("rounds")
    if not isinstance(rounds, list) or len(rounds) != 3:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_REVIEW_INVALID")
    for expected_number, row in enumerate(rounds, 1):
        if not isinstance(row, dict):
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_REVIEW_INVALID")
        unsigned = {key: value for key, value in row.items() if key != "round_sha256"}
        if (
            row.get("round") != expected_number
            or row.get("staged_tree_sha") != review["staged_tree_sha"]
            or tuple(row.get("changed_paths", ())) != _PUBLIC_BINDING_PATHS
            or row.get("material_problems_found") != []
            or row.get("round_sha256")
            != hashlib.sha256(_canonical(unsigned)).hexdigest()
        ):
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_REVIEW_INVALID")
    return review


def _resume_transient_merge_block(root: Path) -> bool:
    state = load_bootstrap_state(_state_path(root))
    if state.phase != "BLOCKED" or state.sequence != 7:
        return False
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked = _read_json(blocked_path)
    expected_block = {
        "controller_enabled_readback": False,
        "phase": "MERGE_PENDING",
        "reason_code": "BOOTSTRAP_PR_NOT_READY",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    if blocked != expected_block:
        return False
    if blocked_path.read_bytes() != _canonical(blocked) + b"\n":
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_BLOCK_RECEIPT_INVALID")
    if root.resolve() != EXPECTED_ROOT.resolve():
        raise ValueError("CATALOG_BOOTSTRAP_ROOT_INVALID")
    _disable_controller()
    context = _context(root)
    source = Path(str(context["source_root"]))
    if source.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_SOURCE_INVALID")
    source = source.resolve(strict=True)
    _run(["git", "fetch", "origin", "main"], cwd=source)
    current_commit = _run(["git", "rev-parse", "HEAD"], cwd=source)
    remote = _run(["git", "remote", "get-url", "origin"], cwd=source)
    if (
        current_commit != context["source_commit_sha"]
        or current_commit != _run(["git", "rev-parse", "origin/main"], cwd=source)
        or not _repository_remote_is_exact(remote)
        or _run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=source,
        )
        or _run(["git", "branch", "--show-current"], cwd=source) != "main"
    ):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_SOURCE_INVALID")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", state.protected_commit_sha, current_commit],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if ancestry.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_SOURCE_INVALID")
    if _run(
        ["gh", "variable", "get", CONTROLLER_VARIABLE, "--repo", REPOSITORY]
    ) != "false":
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_NOT_DISABLED")

    operation_path = root / "public-binding-operation-v1.json"
    operation = _read_json(operation_path)
    branch = operation.get("branch")
    pr_number = operation.get("pr_number")
    binding_commit = operation.get("binding_commit_sha")
    if (
        set(operation)
        != {"binding_commit_sha", "branch", "pr_number", "review_rounds_sha256"}
        or not isinstance(branch, str)
        or not re.fullmatch(r"catalog/bootstrap-binding-[0-9a-f]{12}", branch)
        or not isinstance(pr_number, int)
        or not isinstance(binding_commit, str)
        or not _COMMIT.fullmatch(binding_commit)
        or not _SHA256.fullmatch(str(operation.get("review_rounds_sha256", "")))
        or operation_path.read_bytes() != _canonical(operation) + b"\n"
    ):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_OPERATION_INVALID")
    review = _validated_binding_review(root, operation)
    observed_pr = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                REPOSITORY,
                "--json",
                "state,baseRefName,headRefName,headRefOid",
            ],
            cwd=source,
        )
    )
    if not isinstance(observed_pr, dict):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_PR_INVALID")
    head_commit = observed_pr.get("headRefOid")
    if (
        observed_pr.get("state") != "OPEN"
        or observed_pr.get("baseRefName") != "main"
        or observed_pr.get("headRefName") != branch
        or not isinstance(head_commit, str)
        or not _COMMIT.fullmatch(head_commit)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_PR_INVALID")
    _run(["git", "fetch", "origin", branch], cwd=source)
    binding_ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", binding_commit, head_commit],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if binding_ancestry.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_PR_INVALID")
    changed_paths = tuple(
        sorted(
            path
            for path in _run(
                ["gh", "pr", "diff", str(pr_number), "--repo", REPOSITORY, "--name-only"],
                cwd=source,
            ).splitlines()
            if path
        )
    )
    if changed_paths != _PUBLIC_BINDING_PATHS:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_PR_INVALID")
    required_checks = _wait_for_required_checks(str(pr_number), source)
    installations = _verify_existing_installations(root)
    baseline = _read_json(root / "github-activity-baseline-v1.json")
    current_activity = _github_activity_snapshot()
    if current_activity != baseline:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_ACTIVITY_INVALID")
    recovery = {
        "binding_commit_sha": binding_commit,
        "blocked_state_sha256": hashlib.sha256(
            (root / "state/catalog-bootstrap-state-v1.json").read_bytes()
        ).hexdigest(),
        "head_commit_sha": head_commit,
        "installations": installations,
        "pr_number": pr_number,
        "required_checks": list(required_checks),
        "review_rounds_sha256": hashlib.sha256(_canonical(review)).hexdigest(),
        "source_commit_sha": current_commit,
    }
    _write_canonical(root / "receipts/controller-bootstrap-merge-retry-v1.json", recovery)
    _advance(root, state, "merge_retry_authorized", recovery)
    return True


def _local_install_repair_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_followup_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_compat_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_COMPAT_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_account_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_verifier_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_VERIFIER_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_acl_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_ACL_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_task_identity_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_task_identity_followup_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git", "diff", "--binary", "--full-index",
            f"{base_commit}..{head_commit}", "--",
            *_LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError(
            "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_PATCH_INVALID"
        )
    return hashlib.sha256(result.stdout).hexdigest()


def _github_controls_repair_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
    changed_paths: tuple[str, ...] = _GITHUB_CONTROLS_REPAIR_PATHS,
) -> str:
    result = subprocess.run(
        [
            "git", "diff", "--binary", "--full-index",
            f"{base_commit}..{head_commit}", "--", *changed_paths,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _verify_github_controls_repair_graph(
    source: Path,
    operation: dict[str, object],
    *,
    patch_base_commit: str | None = None,
) -> None:
    merge_commit = str(operation["merge_commit_sha"])
    base_commit = str(operation["base_commit_sha"])
    head_commit = str(operation["head_commit_sha"])
    patch_base = patch_base_commit or base_commit
    if not _COMMIT.fullmatch(patch_base):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_GRAPH_INVALID")
    if patch_base != base_commit:
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", patch_base, base_commit],
            cwd=source,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if ancestry.returncode != 0:
            raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_GRAPH_INVALID")
    parents = _run(
        ["git", "rev-list", "--parents", "-n", "1", merge_commit],
        cwd=source,
    ).split()
    merge_graph_valid = (
        parents == [merge_commit, base_commit, head_commit]
        or parents == [merge_commit, base_commit]
    )
    if not merge_graph_valid:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_GRAPH_INVALID")
    changed_paths = tuple(
        str(path) for path in cast(list[object], operation["changed_paths"])
    )
    expected_patch = operation["patch_sha256"]
    if _github_controls_repair_patch_sha256(
        source, patch_base, head_commit, changed_paths
    ) != expected_patch:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_PATCH_INVALID")
    if len(parents) == 2 and _github_controls_repair_patch_sha256(
        source, patch_base, merge_commit, changed_paths
    ) != expected_patch:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_PATCH_INVALID")


def _git_changed_paths(source: Path, base_commit: str, head_commit: str) -> tuple[str, ...]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            f"{base_commit}..{head_commit}",
            "--",
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_GIT_DIFF_INVALID")
    raw_paths = result.stdout.split(b"\0")
    if raw_paths[-1:] == [b""]:
        raw_paths.pop()
    try:
        paths = tuple(path.decode("utf-8") for path in raw_paths)
    except UnicodeDecodeError as exc:
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_GIT_DIFF_INVALID") from exc
    if not _valid_idempotent_resume_paths(list(paths)):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_PATHS_INVALID")
    return paths


def _verify_idempotent_resume_github_authorization(
    source: Path,
    operation: dict[str, object],
    *,
    protected_main_commit_sha: str | None = None,
) -> None:
    operation_pr_number = operation.get("pr_number")
    if operation_pr_number == _IDEMPOTENT_RESUME_PR_NUMBER:
        expected_branch = _IDEMPOTENT_RESUME_BRANCH
        required_check = _IDEMPOTENT_RESUME_REQUIRED_CHECK
        patch_base_commit = str(operation.get("base_commit_sha", ""))
        graph_patch_base: str | None = None
    elif operation_pr_number == _IDEMPOTENT_RESUME_FOLLOWUP_PR_NUMBER:
        expected_branch = _IDEMPOTENT_RESUME_FOLLOWUP_BRANCH
        required_check = _IDEMPOTENT_RESUME_FOLLOWUP_REQUIRED_CHECK
        patch_base_commit = str(operation.get("prior_runtime_commit_sha", ""))
        graph_patch_base = patch_base_commit
    elif operation_pr_number == _IDEMPOTENT_RESUME_CATCHUP_PR_NUMBER:
        expected_branch = _IDEMPOTENT_RESUME_CATCHUP_BRANCH
        required_check = _IDEMPOTENT_RESUME_CATCHUP_REQUIRED_CHECK
        patch_base_commit = str(operation.get("prior_runtime_commit_sha", ""))
        graph_patch_base = patch_base_commit
    elif (
        isinstance(operation_pr_number, int)
        and not isinstance(operation_pr_number, bool)
        and operation_pr_number > _IDEMPOTENT_RESUME_CATCHUP_PR_NUMBER
        and isinstance(operation.get("branch"), str)
        and re.fullmatch(r"codex/catalog-[a-z0-9][a-z0-9-]{0,79}", str(operation["branch"]))
        and operation.get("required_check") == "catalog-controller-policy"
    ):
        expected_branch = str(operation["branch"])
        required_check = "catalog-controller-policy"
        patch_base_commit = str(operation.get("prior_runtime_commit_sha", ""))
        graph_patch_base = patch_base_commit
    else:
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_GITHUB_INVALID")
    if not _COMMIT.fullmatch(patch_base_commit):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_GITHUB_INVALID")
    try:
        pull_request = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(operation_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    (
                        "number,state,isDraft,baseRefName,baseRefOid,headRefName,"
                        "headRefOid,mergeCommit"
                    ),
                ],
                cwd=source,
            )
        )
        checks = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "checks",
                    str(operation_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "name,state,bucket",
                ],
                cwd=source,
            )
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_GITHUB_INVALID") from exc

    merge_commit = pull_request.get("mergeCommit") if isinstance(pull_request, dict) else None
    merge_oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    if (
        not isinstance(pull_request, dict)
        or pull_request.get("number") != operation_pr_number
        or pull_request.get("state") != "MERGED"
        or pull_request.get("isDraft") is not False
        or pull_request.get("baseRefName") != "main"
        or pull_request.get("baseRefOid") != operation.get("base_commit_sha")
        or pull_request.get("headRefName") != expected_branch
        or pull_request.get("headRefOid") != operation.get("head_commit_sha")
        or merge_oid != operation.get("merge_commit_sha")
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_GITHUB_INVALID")

    if not isinstance(checks, list):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CHECK_INVALID")
    required_checks = [
        check
        for check in checks
        if isinstance(check, dict) and check.get("name") == required_check
    ]
    if (
        len(required_checks) != 1
        or required_checks[0].get("bucket") != "pass"
        or not isinstance(required_checks[0].get("state"), str)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CHECK_INVALID")

    head_commit = str(operation["head_commit_sha"])
    merge_commit_sha = str(operation["merge_commit_sha"])
    expected_main = protected_main_commit_sha or merge_commit_sha
    if (
        not _COMMIT.fullmatch(expected_main)
        or _run(["git", "rev-parse", "origin/main"], cwd=source) != expected_main
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_MAIN_INVALID")
    if merge_commit_sha != expected_main:
        _run(
            ["git", "merge-base", "--is-ancestor", merge_commit_sha, expected_main],
            cwd=source,
        )
    changed_paths = tuple(cast(list[str], operation["changed_paths"]))
    if _git_changed_paths(source, patch_base_commit, head_commit) != changed_paths:
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_PATHS_INVALID")
    if graph_patch_base is None:
        _verify_github_controls_repair_graph(source, operation)
    else:
        _verify_github_controls_repair_graph(
            source,
            operation,
            patch_base_commit=graph_patch_base,
        )


def _validated_local_install_repair(
    root: Path,
    binding: dict[str, object],
) -> dict[str, object]:
    repair_path = root / "local-install-repair-operation-v1.json"
    repair = _read_json(repair_path)
    changed_paths = repair.get("changed_paths")
    if (
        set(repair)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or repair_path.read_bytes() != _canonical(repair) + b"\n"
        or repair.get("schema_version") != "1"
        or repair.get("repository") != REPOSITORY
        or repair.get("base_commit_sha") != binding.get("merge_commit_sha")
        or not isinstance(repair.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-recovery-[0-9a-f]{12}",
            str(repair.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_REPAIR_PATHS
        or not isinstance(repair.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(repair.get("head_commit_sha")))
        or not isinstance(repair.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(repair.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(repair.get("patch_sha256", "")))
        or not isinstance(repair.get("pr_number"), int)
        or _as_int(repair["pr_number"]) < 1
        or repair.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_INVALID")
    return repair


def _validated_local_install_followup_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-followup-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-followup-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_REPAIR_INVALID")
    return operation


def _validated_local_install_compat_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-compat-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-compat-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_COMPAT_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_REPAIR_INVALID")
    return operation


def _validated_local_install_account_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-account-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-account-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_REPAIR_INVALID")
    return operation


def _validated_local_install_verifier_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-verifier-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-verifier-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_VERIFIER_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_REPAIR_INVALID")
    return operation


def _validated_local_install_acl_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-acl-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-acl-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_ACL_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_REPAIR_INVALID")
    return operation


def _validated_local_install_task_identity_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-task-identity-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-task-identity-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_REPAIR_INVALID")
    return operation


def _validated_local_install_task_identity_followup_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-task-identity-followup-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-task-identity-followup-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths)
        != _LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_REPAIR_INVALID"
        )
    return operation


def _validated_github_controls_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-github-controls-recovery-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_INVALID")
    return operation


def _validated_github_controls_followup_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-followup-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-github-controls-followup-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_FOLLOWUP_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_FOLLOWUP_INVALID")
    return operation


def _validated_github_controls_enterprise_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-enterprise-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or operation.get("branch") != "codex/catalog-enterprise-billing-recovery"
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_ENTERPRISE_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_ENTERPRISE_INVALID")
    return operation


def _validated_github_controls_billing_token_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-billing-token-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or operation.get("branch")
        != "codex/catalog-billing-audit-token-recovery"
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_BILLING_TOKEN_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or operation.get("pr_number") != 176
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BILLING_TOKEN_INVALID")
    return operation


def _validated_github_controls_stable_precondition_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-stable-precondition-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or operation.get("branch")
        != "codex/catalog-controls-stable-state-precondition"
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_STABLE_PRECONDITION_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STABLE_PRECONDITION_INVALID"
        )
    return operation


def _validated_github_controls_cache_retention_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-cache-retention-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or operation.get("branch")
        != "codex/catalog-cache-retention-limit-recovery"
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_CACHE_RETENTION_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_CACHE_RETENTION_INVALID"
        )
    return operation


def _validated_github_controls_storage_audit_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-storage-audit-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or operation.get("branch") != "codex/catalog-storage-audit-recovery"
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_STORAGE_AUDIT_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STORAGE_AUDIT_INVALID"
        )
    return operation


def _validated_github_controls_audit_throughput_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-audit-throughput-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or operation.get("branch") != "codex/catalog-controls-audit-throughput"
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_AUDIT_THROUGHPUT_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_AUDIT_THROUGHPUT_INVALID"
        )
    return operation


def _validated_github_controls_package_token_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-package-token-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number",
            "prior_runtime_commit_sha", "repository", "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("prior_runtime_commit_sha")
        != prior_repair.get("merge_commit_sha")
        or operation.get("branch")
        != "codex/catalog-windows-receipt-recovery"
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_PACKAGE_TOKEN_REPAIR_PATHS
        or not isinstance(operation.get("base_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("base_commit_sha")))
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or _as_int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_PACKAGE_TOKEN_INVALID"
        )
    return operation


def _valid_idempotent_resume_paths(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    if any(not isinstance(item, str) for item in value):
        return False
    paths = cast(list[str], value)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        return False
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        if (
            not raw_path
            or "\\" in raw_path
            or ":" in raw_path
            or path.is_absolute()
            or raw_path != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            return False
        if raw_path == "pyproject.toml":
            continue
        if not path.parts or path.parts[0] not in _IDEMPOTENT_RESUME_ALLOWED_ROOTS:
            return False
    return True


def _validated_idempotent_resume_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-idempotent-resume-repair-operation-v1.json"
    operation = _read_json(path)
    prior_merge = prior_repair.get("merge_commit_sha")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "prior_runtime_commit_sha",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_merge
        or operation.get("prior_runtime_commit_sha") != prior_merge
        or operation.get("branch") != _IDEMPOTENT_RESUME_BRANCH
        or operation.get("pr_number") != _IDEMPOTENT_RESUME_PR_NUMBER
        or operation.get("required_check") != _IDEMPOTENT_RESUME_REQUIRED_CHECK
        or not _valid_idempotent_resume_paths(operation.get("changed_paths"))
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha", "")))
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha", "")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_REPAIR_INVALID")
    return operation


def _validated_idempotent_resume_followup_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-idempotent-resume-followup-repair-operation-v1.json"
    operation = _read_json(path)
    prior_merge = prior_repair.get("merge_commit_sha")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "prior_runtime_commit_sha",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("prior_runtime_commit_sha") != prior_merge
        or operation.get("branch") != _IDEMPOTENT_RESUME_FOLLOWUP_BRANCH
        or operation.get("pr_number") != _IDEMPOTENT_RESUME_FOLLOWUP_PR_NUMBER
        or operation.get("required_check")
        != _IDEMPOTENT_RESUME_FOLLOWUP_REQUIRED_CHECK
        or not _valid_idempotent_resume_paths(operation.get("changed_paths"))
        or not _COMMIT.fullmatch(str(operation.get("base_commit_sha", "")))
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha", "")))
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha", "")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_FOLLOWUP_REPAIR_INVALID")
    return operation


def _validated_idempotent_resume_catchup_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-idempotent-resume-catchup-repair-operation-v1.json"
    operation = _read_json(path)
    prior_merge = prior_repair.get("merge_commit_sha")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "prior_runtime_commit_sha",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_merge
        or operation.get("prior_runtime_commit_sha") != prior_merge
        or operation.get("branch") != _IDEMPOTENT_RESUME_CATCHUP_BRANCH
        or operation.get("pr_number") != _IDEMPOTENT_RESUME_CATCHUP_PR_NUMBER
        or operation.get("required_check")
        != _IDEMPOTENT_RESUME_CATCHUP_REQUIRED_CHECK
        or not _valid_idempotent_resume_paths(operation.get("changed_paths"))
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha", "")))
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha", "")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CATCHUP_REPAIR_INVALID")
    return operation


def _validated_idempotent_resume_upgrade_repair(
    root: Path,
    upgrade_index: int,
    prior_repair: dict[str, object],
) -> tuple[Path, dict[str, object]]:
    path = (
        root
        / f"github-controls-idempotent-resume-upgrade-{upgrade_index}-operation-v1.json"
    )
    operation = _read_json(path)
    prior_merge = prior_repair.get("merge_commit_sha")
    branch = operation.get("branch")
    pr_number = operation.get("pr_number")
    base_commit = operation.get("base_commit_sha")
    prior_runtime = operation.get("prior_runtime_commit_sha")
    head_commit = operation.get("head_commit_sha")
    merge_commit = operation.get("merge_commit_sha")
    patch_hash = operation.get("patch_sha256")
    if (
        upgrade_index < 13
        or set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "prior_runtime_commit_sha",
            "repository",
            "required_check",
            "schema_version",
            "upgrade_index",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("upgrade_index") != upgrade_index
        or operation.get("repository") != REPOSITORY
        or not isinstance(prior_merge, str)
        or not _COMMIT.fullmatch(prior_merge)
        or not isinstance(base_commit, str)
        or not _COMMIT.fullmatch(base_commit)
        or not isinstance(prior_runtime, str)
        or not _COMMIT.fullmatch(prior_runtime)
        or operation.get("base_commit_sha") != prior_merge
        or operation.get("prior_runtime_commit_sha") != prior_merge
        or not isinstance(branch, str)
        or not re.fullmatch(r"codex/catalog-[a-z0-9][a-z0-9-]{0,79}", branch)
        or not isinstance(pr_number, int)
        or isinstance(pr_number, bool)
        or pr_number <= _IDEMPOTENT_RESUME_CATCHUP_PR_NUMBER
        or operation.get("required_check") != "catalog-controller-policy"
        or not _valid_idempotent_resume_paths(operation.get("changed_paths"))
        or not isinstance(head_commit, str)
        or not _COMMIT.fullmatch(head_commit)
        or not isinstance(merge_commit, str)
        or not _COMMIT.fullmatch(merge_commit)
        or not isinstance(patch_hash, str)
        or not _SHA256.fullmatch(patch_hash)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REPAIR_INVALID")
    return path, operation


def _idempotent_resume_upgrade_indexes(root: Path) -> tuple[int, ...]:
    operation_pattern = re.compile(
        r"github-controls-idempotent-resume-upgrade-(\d+)-operation-v1\.json"
    )
    retry_pattern = re.compile(
        r"controller-bootstrap-github-controls-retry-(\d+)-v1\.json"
    )
    operation_indexes = {
        int(match.group(1))
        for path in root.iterdir()
        if (match := operation_pattern.fullmatch(path.name)) is not None
        and int(match.group(1)) >= 13
    }
    retry_indexes = {
        int(match.group(1))
        for path in (root / "receipts").iterdir()
        if (match := retry_pattern.fullmatch(path.name)) is not None
        and int(match.group(1)) >= 13
    }
    if operation_indexes != retry_indexes:
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_RETRY_INVALID")
    if not operation_indexes:
        return ()
    highest = max(operation_indexes)
    if (
        min(operation_indexes) != 13
        or highest > _MAX_IDEMPOTENT_RESUME_UPGRADE_INDEX
        or len(operation_indexes) != highest - 12
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_RETRY_INVALID")
    return tuple(sorted(operation_indexes))


def _validated_runtime_upgrade_refresh(
    root: Path,
    operation: dict[str, object],
    retry: dict[str, object],
    prior_runtime_commits: tuple[object, ...],
    *,
    operation_path: Path | None = None,
    error_code: str = "CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_REFRESH_INVALID",
) -> dict[str, object]:
    refresh_path = root / "runtime-upgrade-controls-refresh-v1.json"
    controls_path = root / "github-controls-operation-v1.json"
    backup_path = root / "github-controls-operation-before-runtime-upgrade-v1.json"
    if operation_path is None:
        operation_path = root / "github-controls-idempotent-resume-repair-operation-v1.json"
    refresh = _read_canonical_document(refresh_path, error_code)
    controls = _read_canonical_document(controls_path, error_code)
    backup = _read_canonical_document(backup_path, error_code)
    if not prior_runtime_commits or any(
        not isinstance(commit, str) or not _COMMIT.fullmatch(commit)
        for commit in prior_runtime_commits
    ):
        raise ValueError(error_code)
    if (
        set(refresh)
        != {
            "bootstrap_id",
            "prior_controls_operation_sha256",
            "protected_commit_sha",
            "refreshed_controls_operation_sha256",
            "runtime_upgrade_operation_sha256",
            "schema_version",
        }
        or refresh.get("schema_version") != "1"
        or refresh.get("bootstrap_id") != retry.get("bootstrap_id")
        or refresh.get("protected_commit_sha") != operation.get("merge_commit_sha")
        or refresh.get("runtime_upgrade_operation_sha256")
        != hashlib.sha256(operation_path.read_bytes()).hexdigest()
        or refresh.get("prior_controls_operation_sha256")
        != hashlib.sha256(backup_path.read_bytes()).hexdigest()
        or refresh.get("refreshed_controls_operation_sha256")
        != hashlib.sha256(controls_path.read_bytes()).hexdigest()
        or backup.get("protected_commit_sha") not in prior_runtime_commits
        or controls.get("protected_commit_sha") != operation.get("merge_commit_sha")
    ):
        raise ValueError(error_code)
    return refresh


def _runtime_commit(
    root: Path,
    *,
    allow_pending_idempotent_resume: bool = False,
) -> str:
    binding_path = root / "public-binding-operation-v1.json"
    binding = _read_json(binding_path)
    binding_merge = binding.get("merge_commit_sha")
    if (
        binding_path.read_bytes() != _canonical(binding) + b"\n"
        or not isinstance(binding_merge, str)
        or not _COMMIT.fullmatch(binding_merge)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_PUBLIC_BINDING_INVALID")
    retry_path = root / "receipts/controller-bootstrap-local-install-retry-v1.json"
    if not retry_path.exists():
        return binding_merge
    if _is_reparse_path(retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_RECEIPT_INVALID")
    retry = _read_json(retry_path)
    repair = _validated_local_install_repair(root, binding)
    repair_merge = repair["merge_commit_sha"]
    if (
        set(retry)
        != {
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "installations",
            "public_binding_merge_commit_sha",
            "repair_merge_commit_sha",
            "repair_operation_sha256",
            "repair_pr_number",
            "schema_version",
        }
        or retry_path.read_bytes() != _canonical(retry) + b"\n"
        or retry.get("schema_version") != "1"
        or retry.get("public_binding_merge_commit_sha") != binding_merge
        or retry.get("repair_merge_commit_sha") != repair_merge
        or retry.get("repair_pr_number") != repair.get("pr_number")
        or retry.get("repair_operation_sha256")
        != hashlib.sha256(_canonical(repair)).hexdigest()
        or not _SHA256.fullmatch(str(retry.get("activity_baseline_sha256", "")))
        or not _SHA256.fullmatch(str(retry.get("blocked_state_sha256", "")))
        or not _COMMIT.fullmatch(str(retry.get("bootstrap_source_commit_sha", "")))
        or not isinstance(retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_RECEIPT_INVALID")
    followup_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-2-v1.json"
    )
    if not followup_retry_path.exists():
        return str(repair_merge)
    if _is_reparse_path(followup_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_RETRY_RECEIPT_INVALID")
    followup = _validated_local_install_followup_repair(root, repair)
    followup_retry = _read_json(followup_retry_path)
    followup_merge = followup["merge_commit_sha"]
    if (
        set(followup_retry)
        != {
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "followup_merge_commit_sha",
            "followup_operation_sha256",
            "followup_pr_number",
            "installations",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or followup_retry_path.read_bytes() != _canonical(followup_retry) + b"\n"
        or followup_retry.get("schema_version") != "1"
        or followup_retry.get("prior_runtime_commit_sha") != repair_merge
        or followup_retry.get("followup_merge_commit_sha") != followup_merge
        or followup_retry.get("followup_pr_number") != followup.get("pr_number")
        or followup_retry.get("followup_operation_sha256")
        != hashlib.sha256(_canonical(followup)).hexdigest()
        or followup_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(followup_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(followup_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(followup_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(followup_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_RETRY_RECEIPT_INVALID")
    compat_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-3-v1.json"
    )
    if not compat_retry_path.exists():
        return str(followup_merge)
    if _is_reparse_path(compat_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_RETRY_RECEIPT_INVALID")
    compat = _validated_local_install_compat_repair(root, followup)
    compat_retry = _read_json(compat_retry_path)
    compat_merge = compat["merge_commit_sha"]
    if (
        set(compat_retry)
        != {
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "compat_merge_commit_sha",
            "compat_operation_sha256",
            "compat_pr_number",
            "installations",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or compat_retry_path.read_bytes() != _canonical(compat_retry) + b"\n"
        or compat_retry.get("schema_version") != "1"
        or compat_retry.get("prior_runtime_commit_sha") != followup_merge
        or compat_retry.get("compat_merge_commit_sha") != compat_merge
        or compat_retry.get("compat_pr_number") != compat.get("pr_number")
        or compat_retry.get("compat_operation_sha256")
        != hashlib.sha256(_canonical(compat)).hexdigest()
        or compat_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(followup_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(compat_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(compat_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(compat_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(compat_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_RETRY_RECEIPT_INVALID")
    account_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-4-v1.json"
    )
    if not account_retry_path.exists():
        return str(compat_merge)
    if _is_reparse_path(account_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_RETRY_RECEIPT_INVALID")
    account = _validated_local_install_account_repair(root, compat)
    account_retry = _read_json(account_retry_path)
    account_merge = account["merge_commit_sha"]
    if (
        set(account_retry)
        != {
            "account_merge_commit_sha",
            "account_operation_sha256",
            "account_pr_number",
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "installations",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or account_retry_path.read_bytes() != _canonical(account_retry) + b"\n"
        or account_retry.get("schema_version") != "1"
        or account_retry.get("prior_runtime_commit_sha") != compat_merge
        or account_retry.get("account_merge_commit_sha") != account_merge
        or account_retry.get("account_pr_number") != account.get("pr_number")
        or account_retry.get("account_operation_sha256")
        != hashlib.sha256(_canonical(account)).hexdigest()
        or account_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(compat_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(account_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(account_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(account_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(account_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_RETRY_RECEIPT_INVALID")
    verifier_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-5-v1.json"
    )
    if not verifier_retry_path.exists():
        return str(account_merge)
    if _is_reparse_path(verifier_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_RETRY_RECEIPT_INVALID")
    verifier = _validated_local_install_verifier_repair(root, account)
    verifier_retry = _read_json(verifier_retry_path)
    verifier_merge = verifier["merge_commit_sha"]
    if (
        set(verifier_retry)
        != {
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "installations",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
            "verifier_merge_commit_sha",
            "verifier_operation_sha256",
            "verifier_pr_number",
        }
        or verifier_retry_path.read_bytes() != _canonical(verifier_retry) + b"\n"
        or verifier_retry.get("schema_version") != "1"
        or verifier_retry.get("prior_runtime_commit_sha") != account_merge
        or verifier_retry.get("verifier_merge_commit_sha") != verifier_merge
        or verifier_retry.get("verifier_pr_number") != verifier.get("pr_number")
        or verifier_retry.get("verifier_operation_sha256")
        != hashlib.sha256(_canonical(verifier)).hexdigest()
        or verifier_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(account_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(verifier_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(verifier_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(verifier_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(verifier_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_RETRY_RECEIPT_INVALID")
    acl_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-6-v1.json"
    )
    if not acl_retry_path.exists():
        return str(verifier_merge)
    if _is_reparse_path(acl_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_RETRY_RECEIPT_INVALID")
    acl = _validated_local_install_acl_repair(root, verifier)
    acl_retry = _read_json(acl_retry_path)
    acl_merge = acl["merge_commit_sha"]
    if (
        set(acl_retry)
        != {
            "acl_merge_commit_sha", "acl_operation_sha256", "acl_pr_number",
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "installations",
            "prior_retry_receipt_sha256", "prior_runtime_commit_sha",
            "schema_version",
        }
        or acl_retry_path.read_bytes() != _canonical(acl_retry) + b"\n"
        or acl_retry.get("schema_version") != "1"
        or acl_retry.get("prior_runtime_commit_sha") != verifier_merge
        or acl_retry.get("acl_merge_commit_sha") != acl_merge
        or acl_retry.get("acl_pr_number") != acl.get("pr_number")
        or acl_retry.get("acl_operation_sha256")
        != hashlib.sha256(_canonical(acl)).hexdigest()
        or acl_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(verifier_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(str(acl_retry.get("activity_baseline_sha256", "")))
        or not _SHA256.fullmatch(str(acl_retry.get("blocked_state_sha256", "")))
        or not _COMMIT.fullmatch(str(acl_retry.get("bootstrap_source_commit_sha", "")))
        or not isinstance(acl_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_RETRY_RECEIPT_INVALID")
    task_identity_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-7-v1.json"
    )
    task_identity_operation_path = (
        root / "local-install-task-identity-repair-operation-v1.json"
    )
    if not task_identity_operation_path.exists():
        return str(acl_merge)
    if _is_reparse_path(task_identity_operation_path):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_REPAIR_INVALID")
    task_identity = _validated_local_install_task_identity_repair(root, acl)
    task_identity_merge = task_identity["merge_commit_sha"]
    if not task_identity_retry_path.exists():
        return str(task_identity_merge)
    if _is_reparse_path(task_identity_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_RETRY_RECEIPT_INVALID")
    task_identity_followup = (
        _validated_local_install_task_identity_followup_repair(root, task_identity)
    )
    task_identity_retry = _read_json(task_identity_retry_path)
    task_identity_followup_merge = task_identity_followup["merge_commit_sha"]
    if (
        set(task_identity_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "installations",
            "prior_retry_receipt_sha256", "prior_runtime_commit_sha",
            "schema_version", "task_identity_followup_merge_commit_sha",
            "task_identity_followup_operation_sha256",
            "task_identity_followup_pr_number",
        }
        or task_identity_retry_path.read_bytes()
        != _canonical(task_identity_retry) + b"\n"
        or task_identity_retry.get("schema_version") != "1"
        or task_identity_retry.get("prior_runtime_commit_sha")
        != task_identity_merge
        or task_identity_retry.get("task_identity_followup_merge_commit_sha")
        != task_identity_followup_merge
        or task_identity_retry.get("task_identity_followup_pr_number")
        != task_identity_followup.get("pr_number")
        or task_identity_retry.get("task_identity_followup_operation_sha256")
        != hashlib.sha256(_canonical(task_identity_followup)).hexdigest()
        or task_identity_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(acl_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(task_identity_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(task_identity_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(task_identity_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(task_identity_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_RETRY_RECEIPT_INVALID")
    github_controls_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-v1.json"
    )
    if not github_controls_retry_path.exists():
        return str(task_identity_followup_merge)
    if _is_reparse_path(github_controls_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RETRY_RECEIPT_INVALID")
    github_controls = _validated_github_controls_repair(
        root, task_identity_followup
    )
    github_controls_retry = _read_json(github_controls_retry_path)
    github_controls_merge = github_controls["merge_commit_sha"]
    if (
        set(github_controls_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "github_controls_merge_commit_sha",
            "github_controls_operation_sha256", "github_controls_pr_number",
            "installations", "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha", "schema_version",
        }
        or github_controls_retry_path.read_bytes()
        != _canonical(github_controls_retry) + b"\n"
        or github_controls_retry.get("schema_version") != "1"
        or github_controls_retry.get("prior_runtime_commit_sha")
        != task_identity_followup_merge
        or github_controls_retry.get("github_controls_merge_commit_sha")
        != github_controls_merge
        or github_controls_retry.get("github_controls_pr_number")
        != github_controls.get("pr_number")
        or github_controls_retry.get("github_controls_operation_sha256")
        != hashlib.sha256(_canonical(github_controls)).hexdigest()
        or github_controls_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(task_identity_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(github_controls_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(github_controls_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(github_controls_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(github_controls_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RETRY_RECEIPT_INVALID")
    followup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-2-v1.json"
    )
    if not followup_retry_path.exists():
        return str(github_controls_merge)
    if _is_reparse_path(followup_retry_path):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_FOLLOWUP_RETRY_INVALID"
        )
    followup = _validated_github_controls_followup_repair(
        root, github_controls
    )
    followup_retry = _read_json(followup_retry_path)
    followup_merge = followup["merge_commit_sha"]
    if (
        set(followup_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "followup_merge_commit_sha",
            "followup_operation_sha256", "followup_pr_number",
            "installations", "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha", "schema_version",
        }
        or followup_retry_path.read_bytes()
        != _canonical(followup_retry) + b"\n"
        or followup_retry.get("schema_version") != "1"
        or followup_retry.get("prior_runtime_commit_sha")
        != github_controls_merge
        or followup_retry.get("followup_merge_commit_sha") != followup_merge
        or followup_retry.get("followup_pr_number") != followup.get("pr_number")
        or followup_retry.get("followup_operation_sha256")
        != hashlib.sha256(_canonical(followup)).hexdigest()
        or followup_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(github_controls_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(followup_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(followup_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(followup_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(followup_retry.get("installations"), dict)
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_FOLLOWUP_RETRY_INVALID"
        )
    enterprise_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-3-v1.json"
    )
    if not enterprise_retry_path.exists():
        return str(followup_merge)
    if _is_reparse_path(enterprise_retry_path):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_ENTERPRISE_RETRY_INVALID"
        )
    enterprise = _validated_github_controls_enterprise_repair(root, followup)
    enterprise_retry = _read_json(enterprise_retry_path)
    enterprise_merge = enterprise["merge_commit_sha"]
    if (
        set(enterprise_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "enterprise_merge_commit_sha",
            "enterprise_operation_sha256", "enterprise_pr_number",
            "installations", "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha", "schema_version",
        }
        or enterprise_retry_path.read_bytes()
        != _canonical(enterprise_retry) + b"\n"
        or enterprise_retry.get("schema_version") != "1"
        or enterprise_retry.get("prior_runtime_commit_sha") != followup_merge
        or enterprise_retry.get("enterprise_merge_commit_sha")
        != enterprise_merge
        or enterprise_retry.get("enterprise_pr_number")
        != enterprise.get("pr_number")
        or enterprise_retry.get("enterprise_operation_sha256")
        != hashlib.sha256(_canonical(enterprise)).hexdigest()
        or enterprise_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(followup_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(enterprise_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(enterprise_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(enterprise_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(enterprise_retry.get("installations"), dict)
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_ENTERPRISE_RETRY_INVALID"
        )
    billing_token_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-4-v1.json"
    )
    if not billing_token_retry_path.exists():
        return str(enterprise_merge)
    if _is_reparse_path(billing_token_retry_path):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BILLING_TOKEN_RETRY_INVALID"
        )
    billing_token = _validated_github_controls_billing_token_repair(
        root, enterprise
    )
    billing_token_retry = _read_json(billing_token_retry_path)
    billing_token_merge = billing_token["merge_commit_sha"]
    if (
        set(billing_token_retry)
        != {
            "activity_baseline_sha256", "billing_token_merge_commit_sha",
            "billing_token_operation_sha256", "billing_token_pr_number",
            "blocked_state_sha256", "bootstrap_source_commit_sha",
            "installations", "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha", "schema_version",
        }
        or billing_token_retry_path.read_bytes()
        != _canonical(billing_token_retry) + b"\n"
        or billing_token_retry.get("schema_version") != "1"
        or billing_token_retry.get("prior_runtime_commit_sha")
        != enterprise_merge
        or billing_token_retry.get("billing_token_merge_commit_sha")
        != billing_token_merge
        or billing_token_retry.get("billing_token_pr_number")
        != billing_token.get("pr_number")
        or billing_token_retry.get("billing_token_operation_sha256")
        != hashlib.sha256(_canonical(billing_token)).hexdigest()
        or billing_token_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(enterprise_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(billing_token_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(billing_token_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(billing_token_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(billing_token_retry.get("installations"), dict)
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BILLING_TOKEN_RETRY_INVALID"
        )
    stable_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-5-v1.json"
    )
    if not stable_retry_path.exists():
        return str(billing_token_merge)
    if _is_reparse_path(stable_retry_path):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STABLE_PRECONDITION_RETRY_INVALID"
        )
    stable = _validated_github_controls_stable_precondition_repair(
        root, billing_token
    )
    stable_retry = _read_json(stable_retry_path)
    stable_merge = stable["merge_commit_sha"]
    if (
        set(stable_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "installations",
            "prior_retry_receipt_sha256", "prior_runtime_commit_sha",
            "schema_version", "stable_precondition_merge_commit_sha",
            "stable_precondition_operation_sha256",
            "stable_precondition_pr_number",
        }
        or stable_retry_path.read_bytes() != _canonical(stable_retry) + b"\n"
        or stable_retry.get("schema_version") != "1"
        or stable_retry.get("prior_runtime_commit_sha") != billing_token_merge
        or stable_retry.get("stable_precondition_merge_commit_sha")
        != stable_merge
        or stable_retry.get("stable_precondition_pr_number")
        != stable.get("pr_number")
        or stable_retry.get("stable_precondition_operation_sha256")
        != hashlib.sha256(_canonical(stable)).hexdigest()
        or stable_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(billing_token_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(stable_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(stable_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(stable_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(stable_retry.get("installations"), dict)
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STABLE_PRECONDITION_RETRY_INVALID"
        )
    cache_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-6-v1.json"
    )
    if not cache_retry_path.exists():
        return str(stable_merge)
    if _is_reparse_path(cache_retry_path):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_CACHE_RETENTION_RETRY_INVALID"
        )
    cache = _validated_github_controls_cache_retention_repair(root, stable)
    cache_retry = _read_json(cache_retry_path)
    cache_merge = cache["merge_commit_sha"]
    if (
        set(cache_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "cache_retention_merge_commit_sha",
            "cache_retention_operation_sha256", "cache_retention_pr_number",
            "installations", "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha", "schema_version",
        }
        or cache_retry_path.read_bytes() != _canonical(cache_retry) + b"\n"
        or cache_retry.get("schema_version") != "1"
        or cache_retry.get("prior_runtime_commit_sha") != stable_merge
        or cache_retry.get("cache_retention_merge_commit_sha") != cache_merge
        or cache_retry.get("cache_retention_pr_number") != cache.get("pr_number")
        or cache_retry.get("cache_retention_operation_sha256")
        != hashlib.sha256(_canonical(cache)).hexdigest()
        or cache_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(stable_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(cache_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(cache_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(cache_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(cache_retry.get("installations"), dict)
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_CACHE_RETENTION_RETRY_INVALID"
        )
    storage_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-7-v1.json"
    )
    if not storage_retry_path.exists():
        return str(cache_merge)
    if _is_reparse_path(storage_retry_path):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STORAGE_AUDIT_RETRY_INVALID"
        )
    storage = _validated_github_controls_storage_audit_repair(root, cache)
    storage_retry = _read_json(storage_retry_path)
    storage_merge = storage["merge_commit_sha"]
    if (
        set(storage_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "installations",
            "prior_retry_receipt_sha256", "prior_runtime_commit_sha",
            "schema_version", "storage_audit_merge_commit_sha",
            "storage_audit_operation_sha256", "storage_audit_pr_number",
        }
        or storage_retry_path.read_bytes() != _canonical(storage_retry) + b"\n"
        or storage_retry.get("schema_version") != "1"
        or storage_retry.get("prior_runtime_commit_sha") != cache_merge
        or storage_retry.get("storage_audit_merge_commit_sha") != storage_merge
        or storage_retry.get("storage_audit_pr_number") != storage.get("pr_number")
        or storage_retry.get("storage_audit_operation_sha256")
        != hashlib.sha256(_canonical(storage)).hexdigest()
        or storage_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(cache_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(storage_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(storage_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(storage_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(storage_retry.get("installations"), dict)
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STORAGE_AUDIT_RETRY_INVALID"
        )
    throughput_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-8-v1.json"
    )
    if not throughput_retry_path.exists():
        return str(storage_merge)
    if _is_reparse_path(throughput_retry_path):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_AUDIT_THROUGHPUT_RETRY_INVALID"
        )
    throughput = _validated_github_controls_audit_throughput_repair(root, storage)
    throughput_retry = _read_json(throughput_retry_path)
    throughput_merge = throughput["merge_commit_sha"]
    if (
        set(throughput_retry)
        != {
            "activity_baseline_sha256", "audit_throughput_merge_commit_sha",
            "audit_throughput_operation_sha256", "audit_throughput_pr_number",
            "blocked_state_sha256", "bootstrap_source_commit_sha", "installations",
            "prior_retry_receipt_sha256", "prior_runtime_commit_sha", "schema_version",
        }
        or throughput_retry_path.read_bytes()
        != _canonical(throughput_retry) + b"\n"
        or throughput_retry.get("schema_version") != "1"
        or throughput_retry.get("prior_runtime_commit_sha") != storage_merge
        or throughput_retry.get("audit_throughput_merge_commit_sha")
        != throughput_merge
        or throughput_retry.get("audit_throughput_pr_number")
        != throughput.get("pr_number")
        or throughput_retry.get("audit_throughput_operation_sha256")
        != hashlib.sha256(_canonical(throughput)).hexdigest()
        or throughput_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(storage_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(throughput_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(throughput_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(throughput_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(throughput_retry.get("installations"), dict)
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_AUDIT_THROUGHPUT_RETRY_INVALID"
        )
    package_token_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-9-v1.json"
    )
    if not package_token_retry_path.exists():
        return str(throughput_merge)
    if _is_reparse_path(package_token_retry_path):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_PACKAGE_TOKEN_RETRY_INVALID"
        )
    package_token = _validated_github_controls_package_token_repair(
        root, throughput
    )
    package_token_retry = _read_json(package_token_retry_path)
    package_token_merge = package_token["merge_commit_sha"]
    if (
        set(package_token_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "installations",
            "package_token_merge_commit_sha",
            "package_token_operation_sha256", "package_token_pr_number",
            "prior_retry_receipt_sha256", "prior_runtime_commit_sha",
            "schema_version",
        }
        or package_token_retry_path.read_bytes()
        != _canonical(package_token_retry) + b"\n"
        or package_token_retry.get("schema_version") != "1"
        or package_token_retry.get("prior_runtime_commit_sha")
        != throughput_merge
        or package_token_retry.get("package_token_merge_commit_sha")
        != package_token_merge
        or package_token_retry.get("package_token_pr_number")
        != package_token.get("pr_number")
        or package_token_retry.get("package_token_operation_sha256")
        != hashlib.sha256(_canonical(package_token)).hexdigest()
        or package_token_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(throughput_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(package_token_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(package_token_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(package_token_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(package_token_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_PACKAGE_TOKEN_RETRY_INVALID")
    resume_retry_path = root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json"
    if not resume_retry_path.exists():
        return str(package_token_merge)
    if _is_reparse_path(resume_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_RETRY_INVALID")
    resume_operation = _validated_idempotent_resume_repair(root, package_token)
    resume_retry = _read_json(resume_retry_path)
    resume_merge = resume_operation["merge_commit_sha"]
    if (
        set(resume_retry)
        != {
            "activity_baseline_sha256",
            "bootstrap_id",
            "bootstrap_source_commit_sha",
            "idempotent_resume_merge_commit_sha",
            "idempotent_resume_operation_sha256",
            "idempotent_resume_pr_number",
            "installations",
            "interrupted_phase",
            "interrupted_sequence",
            "interrupted_state_sha256",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or resume_retry_path.read_bytes() != _canonical(resume_retry) + b"\n"
        or resume_retry.get("schema_version") != "1"
        or not isinstance(resume_retry.get("bootstrap_id"), str)
        or not str(resume_retry.get("bootstrap_id")).startswith("bootstrap-")
        or resume_retry.get("interrupted_phase") != "QUALIFICATION_PENDING"
        or resume_retry.get("interrupted_sequence") != 43
        or resume_retry.get("prior_runtime_commit_sha") != package_token_merge
        or resume_retry.get("idempotent_resume_merge_commit_sha") != resume_merge
        or resume_retry.get("idempotent_resume_pr_number") != _IDEMPOTENT_RESUME_PR_NUMBER
        or resume_retry.get("idempotent_resume_operation_sha256")
        != hashlib.sha256(_canonical(resume_operation)).hexdigest()
        or resume_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(package_token_retry_path.read_bytes()).hexdigest()
        or resume_retry.get("bootstrap_source_commit_sha")
        != package_token_retry.get("bootstrap_source_commit_sha")
        or resume_retry.get("installations") != package_token_retry.get("installations")
        or not _SHA256.fullmatch(str(resume_retry.get("activity_baseline_sha256", "")))
        or not _SHA256.fullmatch(str(resume_retry.get("interrupted_state_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_RETRY_INVALID")
    followup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-11-v1.json"
    )
    if not followup_retry_path.exists():
        if not allow_pending_idempotent_resume:
            _validated_runtime_upgrade_refresh(
                root,
                resume_operation,
                resume_retry,
                (package_token_merge,),
            )
        return str(resume_merge)
    if _is_reparse_path(followup_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_FOLLOWUP_RETRY_INVALID")
    followup_operation = _validated_idempotent_resume_followup_repair(
        root,
        resume_operation,
    )
    followup_retry = _read_json(followup_retry_path)
    followup_merge = followup_operation["merge_commit_sha"]
    followup_operation_path = (
        root / "github-controls-idempotent-resume-followup-repair-operation-v1.json"
    )
    if (
        set(followup_retry)
        != {
            "activity_baseline_sha256",
            "bootstrap_id",
            "bootstrap_source_commit_sha",
            "idempotent_resume_followup_merge_commit_sha",
            "idempotent_resume_followup_operation_sha256",
            "idempotent_resume_followup_pr_number",
            "installations",
            "interrupted_phase",
            "interrupted_sequence",
            "interrupted_state_sha256",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or followup_retry_path.read_bytes() != _canonical(followup_retry) + b"\n"
        or followup_retry.get("schema_version") != "1"
        or followup_retry.get("bootstrap_id") != resume_retry.get("bootstrap_id")
        or followup_retry.get("interrupted_phase") != "QUALIFICATION_PENDING"
        or followup_retry.get("interrupted_sequence") != 43
        or followup_retry.get("prior_runtime_commit_sha") != resume_merge
        or followup_retry.get("idempotent_resume_followup_merge_commit_sha")
        != followup_merge
        or followup_retry.get("idempotent_resume_followup_pr_number")
        != _IDEMPOTENT_RESUME_FOLLOWUP_PR_NUMBER
        or followup_retry.get("idempotent_resume_followup_operation_sha256")
        != hashlib.sha256(_canonical(followup_operation)).hexdigest()
        or followup_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(resume_retry_path.read_bytes()).hexdigest()
        or followup_retry.get("bootstrap_source_commit_sha")
        != resume_retry.get("bootstrap_source_commit_sha")
        or followup_retry.get("installations") != resume_retry.get("installations")
        or not _SHA256.fullmatch(
            str(followup_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(followup_retry.get("interrupted_state_sha256", ""))
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_FOLLOWUP_RETRY_INVALID")
    catchup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-12-v1.json"
    )
    if not catchup_retry_path.exists():
        if not allow_pending_idempotent_resume:
            _validated_runtime_upgrade_refresh(
                root,
                followup_operation,
                followup_retry,
                (resume_merge, resume_operation.get("prior_runtime_commit_sha")),
                operation_path=followup_operation_path,
                error_code="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_FOLLOWUP_REFRESH_INVALID",
            )
        return str(followup_merge)
    if _is_reparse_path(catchup_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CATCHUP_RETRY_INVALID")
    catchup_operation = _validated_idempotent_resume_catchup_repair(
        root,
        followup_operation,
    )
    catchup_retry = _read_json(catchup_retry_path)
    catchup_merge = catchup_operation["merge_commit_sha"]
    catchup_operation_path = (
        root / "github-controls-idempotent-resume-catchup-repair-operation-v1.json"
    )
    if (
        set(catchup_retry)
        != {
            "activity_baseline_sha256",
            "bootstrap_id",
            "bootstrap_source_commit_sha",
            "idempotent_resume_catchup_merge_commit_sha",
            "idempotent_resume_catchup_operation_sha256",
            "idempotent_resume_catchup_pr_number",
            "installations",
            "interrupted_phase",
            "interrupted_sequence",
            "interrupted_state_sha256",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or catchup_retry_path.read_bytes() != _canonical(catchup_retry) + b"\n"
        or catchup_retry.get("schema_version") != "1"
        or catchup_retry.get("bootstrap_id") != followup_retry.get("bootstrap_id")
        or catchup_retry.get("interrupted_phase") != "QUALIFICATION_PENDING"
        or catchup_retry.get("interrupted_sequence") != 43
        or catchup_retry.get("prior_runtime_commit_sha") != followup_merge
        or catchup_retry.get("idempotent_resume_catchup_merge_commit_sha")
        != catchup_merge
        or catchup_retry.get("idempotent_resume_catchup_pr_number")
        != _IDEMPOTENT_RESUME_CATCHUP_PR_NUMBER
        or catchup_retry.get("idempotent_resume_catchup_operation_sha256")
        != hashlib.sha256(_canonical(catchup_operation)).hexdigest()
        or catchup_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(followup_retry_path.read_bytes()).hexdigest()
        or catchup_retry.get("bootstrap_source_commit_sha")
        != followup_retry.get("bootstrap_source_commit_sha")
        or catchup_retry.get("installations") != followup_retry.get("installations")
        or not _SHA256.fullmatch(
            str(catchup_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(catchup_retry.get("interrupted_state_sha256", ""))
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CATCHUP_RETRY_INVALID")
    accepted_prior_runtimes: list[object] = [
        followup_merge,
        followup_operation.get("prior_runtime_commit_sha"),
        resume_operation.get("prior_runtime_commit_sha"),
    ]
    latest_operation = catchup_operation
    latest_retry = catchup_retry
    latest_operation_path = catchup_operation_path
    latest_retry_path = catchup_retry_path
    latest_merge = catchup_merge
    upgrade_indexes = _idempotent_resume_upgrade_indexes(root)
    for upgrade_index in upgrade_indexes:
        operation_path = (
            root
            / f"github-controls-idempotent-resume-upgrade-{upgrade_index}-operation-v1.json"
        )
        retry_path = (
            root
            / f"receipts/controller-bootstrap-github-controls-retry-{upgrade_index}-v1.json"
        )
        if (
            not operation_path.exists()
            or not retry_path.exists()
            or _is_reparse_path(operation_path)
            or _is_reparse_path(retry_path)
        ):
            raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_RETRY_INVALID")
        validated_path, operation = _validated_idempotent_resume_upgrade_repair(
            root,
            upgrade_index,
            latest_operation,
        )
        retry = _read_json(retry_path)
        merge_commit = operation["merge_commit_sha"]
        if (
            set(retry)
            != {
                "activity_baseline_sha256",
                "bootstrap_id",
                "bootstrap_source_commit_sha",
                "idempotent_resume_upgrade_index",
                "idempotent_resume_upgrade_merge_commit_sha",
                "idempotent_resume_upgrade_operation_sha256",
                "idempotent_resume_upgrade_pr_number",
                "installations",
                "interrupted_phase",
                "interrupted_sequence",
                "interrupted_state_sha256",
                "prior_retry_receipt_sha256",
                "prior_runtime_commit_sha",
                "schema_version",
            }
            or retry_path.read_bytes() != _canonical(retry) + b"\n"
            or retry.get("schema_version") != "1"
            or retry.get("bootstrap_id") != latest_retry.get("bootstrap_id")
            or retry.get("interrupted_phase") != "QUALIFICATION_PENDING"
            or retry.get("interrupted_sequence") != 43
            or retry.get("idempotent_resume_upgrade_index") != upgrade_index
            or retry.get("prior_runtime_commit_sha") != latest_merge
            or retry.get("idempotent_resume_upgrade_merge_commit_sha")
            != merge_commit
            or retry.get("idempotent_resume_upgrade_pr_number")
            != operation.get("pr_number")
            or retry.get("idempotent_resume_upgrade_operation_sha256")
            != hashlib.sha256(_canonical(operation)).hexdigest()
            or retry.get("prior_retry_receipt_sha256")
            != hashlib.sha256(latest_retry_path.read_bytes()).hexdigest()
            or retry.get("bootstrap_source_commit_sha")
            != latest_retry.get("bootstrap_source_commit_sha")
            or retry.get("installations") != latest_retry.get("installations")
            or not _SHA256.fullmatch(
                str(retry.get("activity_baseline_sha256", ""))
            )
            or not _SHA256.fullmatch(
                str(retry.get("interrupted_state_sha256", ""))
            )
        ):
            raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_RETRY_INVALID")
        accepted_prior_runtimes.append(operation.get("prior_runtime_commit_sha"))
        latest_operation = operation
        latest_retry = retry
        latest_operation_path = validated_path
        latest_retry_path = retry_path
        latest_merge = merge_commit
    if not allow_pending_idempotent_resume:
        _validated_runtime_upgrade_refresh(
            root,
            latest_operation,
            latest_retry,
            tuple(accepted_prior_runtimes),
            operation_path=latest_operation_path,
            error_code=(
                "CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CATCHUP_REFRESH_INVALID"
                if not upgrade_indexes
                else "CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REFRESH_INVALID"
            ),
        )
    return str(latest_merge)


def _resume_transient_local_install_block(root: Path) -> bool:
    state = load_bootstrap_state(_state_path(root))
    if state.phase != "BLOCKED" or state.sequence not in {10, 12, 14, 16, 18, 20, 22}:
        return False
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked = _read_json(blocked_path)
    expected_block = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    if blocked != expected_block:
        return False
    if blocked_path.read_bytes() != _canonical(blocked) + b"\n":
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_BLOCK_RECEIPT_INVALID")
    if root.resolve() != EXPECTED_ROOT.resolve():
        raise ValueError("CATALOG_BOOTSTRAP_ROOT_INVALID")
    _disable_controller()
    followup_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-2-v1.json"
    )
    if state.sequence == 12 and followup_retry_path.exists():
        evidence = _read_json(followup_retry_path)
        if _runtime_commit(root) != evidence.get("followup_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    compat_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-3-v1.json"
    )
    if state.sequence == 14 and compat_retry_path.exists():
        evidence = _read_json(compat_retry_path)
        if _runtime_commit(root) != evidence.get("compat_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    account_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-4-v1.json"
    )
    if state.sequence == 16 and account_retry_path.exists():
        evidence = _read_json(account_retry_path)
        if _runtime_commit(root) != evidence.get("account_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    verifier_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-5-v1.json"
    )
    if state.sequence == 18 and verifier_retry_path.exists():
        evidence = _read_json(verifier_retry_path)
        if _runtime_commit(root) != evidence.get("verifier_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    acl_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-6-v1.json"
    )
    if state.sequence == 20 and acl_retry_path.exists():
        evidence = _read_json(acl_retry_path)
        if _runtime_commit(root) != evidence.get("acl_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    task_identity_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-7-v1.json"
    )
    if state.sequence == 22 and task_identity_retry_path.exists():
        evidence = _read_json(task_identity_retry_path)
        if _runtime_commit(root) != evidence.get(
            "task_identity_followup_merge_commit_sha"
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_RETRY_RECEIPT_INVALID"
            )
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True

    context_path = root / "install-context-v1.json"
    context = _context(root)
    source_commit = context.get("source_commit_sha")
    if (
        context_path.read_bytes() != _canonical(context) + b"\n"
        or not isinstance(source_commit, str)
        or not _COMMIT.fullmatch(source_commit)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_CONTEXT_INVALID")
    source = Path(str(context["source_root"]))
    if _is_reparse_path(source):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_SOURCE_INVALID")
    source = source.resolve(strict=True)

    operation_path = root / "public-binding-operation-v1.json"
    operation = _read_json(operation_path)
    binding_branch = operation.get("branch")
    binding_pr_number = operation.get("pr_number")
    binding_commit = operation.get("binding_commit_sha")
    binding_merge = operation.get("merge_commit_sha")
    if (
        set(operation)
        != {
            "binding_commit_sha",
            "branch",
            "merge_commit_sha",
            "pr_number",
            "review_rounds_sha256",
        }
        or operation_path.read_bytes() != _canonical(operation) + b"\n"
        or not isinstance(binding_branch, str)
        or not re.fullmatch(
            r"catalog/bootstrap-binding-[0-9a-f]{12}",
            binding_branch,
        )
        or not isinstance(binding_pr_number, int)
        or binding_pr_number < 1
        or not isinstance(binding_commit, str)
        or not _COMMIT.fullmatch(binding_commit)
        or not isinstance(binding_merge, str)
        or not _COMMIT.fullmatch(binding_merge)
        or not _SHA256.fullmatch(str(operation.get("review_rounds_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_OPERATION_INVALID")

    repair = _validated_local_install_repair(root, operation)
    repair_branch = str(repair["branch"])
    repair_head = str(repair["head_commit_sha"])
    repair_merge = str(repair["merge_commit_sha"])
    repair_pr_number = _as_int(repair["pr_number"])
    followup: dict[str, object] | None = None
    compat: dict[str, object] | None = None
    account: dict[str, object] | None = None
    verifier: dict[str, object] | None = None
    acl: dict[str, object] | None = None
    task_identity: dict[str, object] | None = None
    task_identity_followup: dict[str, object] | None = None
    runtime_paths: tuple[str, ...]
    if state.sequence == 22:
        followup = _validated_local_install_followup_repair(root, repair)
        compat = _validated_local_install_compat_repair(root, followup)
        account = _validated_local_install_account_repair(root, compat)
        verifier = _validated_local_install_verifier_repair(root, account)
        acl = _validated_local_install_acl_repair(root, verifier)
        task_identity = _validated_local_install_task_identity_repair(root, acl)
        task_identity_merge = str(task_identity["merge_commit_sha"])
        if _runtime_commit(root) != task_identity_merge:
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_RETRY_RECEIPT_INVALID"
            )
        task_identity_followup = (
            _validated_local_install_task_identity_followup_repair(
                root, task_identity
            )
        )
        runtime_base = task_identity_merge
        runtime_head = str(task_identity_followup["head_commit_sha"])
        runtime_merge = str(task_identity_followup["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_task_identity_followup_patch_sha256
    elif state.sequence == 20:
        followup = _validated_local_install_followup_repair(root, repair)
        compat = _validated_local_install_compat_repair(root, followup)
        account = _validated_local_install_account_repair(root, compat)
        verifier = _validated_local_install_verifier_repair(root, account)
        verifier_merge = str(verifier["merge_commit_sha"])
        if _runtime_commit(root) != verifier_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_RETRY_RECEIPT_INVALID")
        acl = _validated_local_install_acl_repair(root, verifier)
        runtime_base = verifier_merge
        runtime_head = str(acl["head_commit_sha"])
        runtime_merge = str(acl["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_ACL_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_acl_patch_sha256
    elif state.sequence == 18:
        followup = _validated_local_install_followup_repair(root, repair)
        compat = _validated_local_install_compat_repair(root, followup)
        account = _validated_local_install_account_repair(root, compat)
        account_merge = str(account["merge_commit_sha"])
        if _runtime_commit(root) != account_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_RETRY_RECEIPT_INVALID")
        verifier = _validated_local_install_verifier_repair(root, account)
        runtime_base = account_merge
        runtime_head = str(verifier["head_commit_sha"])
        runtime_merge = str(verifier["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_VERIFIER_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_verifier_patch_sha256
    elif state.sequence == 16:
        followup = _validated_local_install_followup_repair(root, repair)
        compat = _validated_local_install_compat_repair(root, followup)
        compat_merge = str(compat["merge_commit_sha"])
        if _runtime_commit(root) != compat_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_RETRY_RECEIPT_INVALID")
        account = _validated_local_install_account_repair(root, compat)
        runtime_base = compat_merge
        runtime_head = str(account["head_commit_sha"])
        runtime_merge = str(account["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_account_patch_sha256
    elif state.sequence == 14:
        followup = _validated_local_install_followup_repair(root, repair)
        followup_merge = str(followup["merge_commit_sha"])
        if _runtime_commit(root) != followup_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_RETRY_RECEIPT_INVALID")
        compat = _validated_local_install_compat_repair(root, followup)
        runtime_base = followup_merge
        runtime_head = str(compat["head_commit_sha"])
        runtime_merge = str(compat["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_COMPAT_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_compat_patch_sha256
    elif state.sequence == 12:
        if _runtime_commit(root) != repair_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_RETRY_RECEIPT_INVALID")
        followup = _validated_local_install_followup_repair(root, repair)
        runtime_base = repair_merge
        runtime_head = str(followup["head_commit_sha"])
        runtime_merge = str(followup["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_followup_patch_sha256
    else:
        runtime_base = binding_merge
        runtime_head = repair_head
        runtime_merge = repair_merge
        runtime_paths = _LOCAL_INSTALL_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_repair_patch_sha256
    if source_commit != runtime_merge:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_CONTEXT_INVALID")

    for installed_root in (AGENT_ROOT, BROKER_ROOT):
        if (
            installed_root.exists()
            or _is_reparse_path(installed_root)
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_PARTIAL_INSTALL")
    staging = BOOTSTRAP_STAGING_ROOT
    if _is_reparse_path(staging):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_PARTIAL_INSTALL")
    if staging.exists() and (not staging.is_dir() or any(staging.iterdir())):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_PARTIAL_INSTALL")
    pending_key = root / "secrets/requester-pending.pem"
    if (
        not pending_key.is_file()
        or _is_reparse_path(pending_key)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_KEY_INVALID")

    _run(["git", "fetch", "origin", "main"], cwd=source)
    current_commit = _run(["git", "rev-parse", "HEAD"], cwd=source)
    remote = _run(["git", "remote", "get-url", "origin"], cwd=source)
    if (
        current_commit != runtime_merge
        or current_commit != _run(["git", "rev-parse", "origin/main"], cwd=source)
        or not _repository_remote_is_exact(remote)
        or _run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=source,
        )
        or _run(["git", "branch", "--show-current"], cwd=source) != "main"
        or _run(["git", "rev-parse", f"{runtime_merge}^1"], cwd=source)
        != runtime_base
        or _run(["git", "rev-parse", f"{runtime_merge}^2"], cwd=source)
        != runtime_head
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_SOURCE_INVALID")

    for revision in (
        f"{runtime_base}..{runtime_head}",
        f"{runtime_base}..{runtime_merge}",
    ):
        changed = tuple(
            line
            for line in _run(
                ["git", "diff", "--name-only", revision, "--"],
                cwd=source,
            ).splitlines()
            if line
        )
        if changed != runtime_paths:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PATHS_INVALID")
    if (
        runtime_patch_sha256(
            source,
            runtime_base,
            runtime_head,
        )
        != (
            task_identity_followup
            or task_identity
            or acl
            or verifier
            or account
            or compat
            or followup
            or repair
        )["patch_sha256"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PATCH_INVALID")

    ancestry = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            state.protected_commit_sha,
            binding_merge,
        ],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if ancestry.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_SOURCE_INVALID")
    if _run(
        ["gh", "variable", "get", CONTROLLER_VARIABLE, "--repo", REPOSITORY]
    ) != "false":
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_NOT_DISABLED")

    observed_binding = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                str(binding_pr_number),
                "--repo",
                REPOSITORY,
                "--json",
                "state,baseRefName,headRefName,mergeCommit",
            ],
            cwd=source,
        )
    )
    observed_binding_merge = (
        observed_binding.get("mergeCommit")
        if isinstance(observed_binding, dict)
        else None
    )
    if (
        not isinstance(observed_binding, dict)
        or set(observed_binding)
        != {"baseRefName", "headRefName", "mergeCommit", "state"}
        or observed_binding.get("state") != "MERGED"
        or observed_binding.get("baseRefName") != "main"
        or observed_binding.get("headRefName") != binding_branch
        or not isinstance(observed_binding_merge, dict)
        or set(observed_binding_merge) != {"oid"}
        or observed_binding_merge.get("oid") != binding_merge
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_PR_INVALID")

    observed_repair = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                str(repair_pr_number),
                "--repo",
                REPOSITORY,
                "--json",
                "state,baseRefName,headRefName,headRefOid,mergeCommit",
            ],
            cwd=source,
        )
    )
    observed_repair_merge = (
        observed_repair.get("mergeCommit")
        if isinstance(observed_repair, dict)
        else None
    )
    if (
        not isinstance(observed_repair, dict)
        or set(observed_repair)
        != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
        or observed_repair.get("state") != "MERGED"
        or observed_repair.get("baseRefName") != "main"
        or observed_repair.get("headRefName") != repair_branch
        or observed_repair.get("headRefOid") != repair_head
        or not isinstance(observed_repair_merge, dict)
        or set(observed_repair_merge) != {"oid"}
        or observed_repair_merge.get("oid") != repair_merge
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PR_INVALID")
    observed_paths = tuple(
        line
        for line in _run(
            [
                "gh",
                "pr",
                "diff",
                str(repair_pr_number),
                "--repo",
                REPOSITORY,
                "--name-only",
            ],
            cwd=source,
        ).splitlines()
        if line
    )
    if observed_paths != _LOCAL_INSTALL_REPAIR_PATHS:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PATHS_INVALID")
    _wait_for_required_checks(str(repair_pr_number), source)
    if followup is not None:
        followup_pr_number = _as_int(followup["pr_number"])
        observed_followup = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(followup_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_followup_merge = (
            observed_followup.get("mergeCommit")
            if isinstance(observed_followup, dict)
            else None
        )
        if (
            not isinstance(observed_followup, dict)
            or set(observed_followup)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_followup.get("state") != "MERGED"
            or observed_followup.get("baseRefName") != "main"
            or observed_followup.get("headRefName") != followup["branch"]
            or observed_followup.get("headRefOid") != followup["head_commit_sha"]
            or not isinstance(observed_followup_merge, dict)
            or set(observed_followup_merge) != {"oid"}
            or observed_followup_merge.get("oid") != followup["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_REPAIR_PR_INVALID")
        observed_followup_paths = tuple(
            line
            for line in _run(
                [
                    "gh",
                    "pr",
                    "diff",
                    str(followup_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_followup_paths != _LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(followup_pr_number), source)
    if compat is not None:
        compat_pr_number = _as_int(compat["pr_number"])
        observed_compat = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(compat_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_compat_merge = (
            observed_compat.get("mergeCommit")
            if isinstance(observed_compat, dict)
            else None
        )
        if (
            not isinstance(observed_compat, dict)
            or set(observed_compat)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_compat.get("state") != "MERGED"
            or observed_compat.get("baseRefName") != "main"
            or observed_compat.get("headRefName") != compat["branch"]
            or observed_compat.get("headRefOid") != compat["head_commit_sha"]
            or not isinstance(observed_compat_merge, dict)
            or set(observed_compat_merge) != {"oid"}
            or observed_compat_merge.get("oid") != compat["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_REPAIR_PR_INVALID")
        observed_compat_paths = tuple(
            line
            for line in _run(
                [
                    "gh",
                    "pr",
                    "diff",
                    str(compat_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_compat_paths != _LOCAL_INSTALL_COMPAT_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(compat_pr_number), source)
    if account is not None:
        account_pr_number = _as_int(account["pr_number"])
        observed_account = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(account_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_account_merge = (
            observed_account.get("mergeCommit")
            if isinstance(observed_account, dict)
            else None
        )
        if (
            not isinstance(observed_account, dict)
            or set(observed_account)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_account.get("state") != "MERGED"
            or observed_account.get("baseRefName") != "main"
            or observed_account.get("headRefName") != account["branch"]
            or observed_account.get("headRefOid") != account["head_commit_sha"]
            or not isinstance(observed_account_merge, dict)
            or set(observed_account_merge) != {"oid"}
            or observed_account_merge.get("oid") != account["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_REPAIR_PR_INVALID")
        observed_account_paths = tuple(
            line
            for line in _run(
                [
                    "gh",
                    "pr",
                    "diff",
                    str(account_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_account_paths != _LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(account_pr_number), source)
    if verifier is not None:
        verifier_pr_number = _as_int(verifier["pr_number"])
        observed_verifier = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(verifier_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_verifier_merge = (
            observed_verifier.get("mergeCommit")
            if isinstance(observed_verifier, dict)
            else None
        )
        if (
            not isinstance(observed_verifier, dict)
            or set(observed_verifier)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_verifier.get("state") != "MERGED"
            or observed_verifier.get("baseRefName") != "main"
            or observed_verifier.get("headRefName") != verifier["branch"]
            or observed_verifier.get("headRefOid") != verifier["head_commit_sha"]
            or not isinstance(observed_verifier_merge, dict)
            or set(observed_verifier_merge) != {"oid"}
            or observed_verifier_merge.get("oid") != verifier["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_REPAIR_PR_INVALID")
        observed_verifier_paths = tuple(
            line
            for line in _run(
                [
                    "gh",
                    "pr",
                    "diff",
                    str(verifier_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_verifier_paths != _LOCAL_INSTALL_VERIFIER_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(verifier_pr_number), source)
    if acl is not None:
        acl_pr_number = _as_int(acl["pr_number"])
        observed_acl = json.loads(
            _run(
                [
                    "gh", "pr", "view", str(acl_pr_number), "--repo", REPOSITORY,
                    "--json", "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_acl_merge = (
            observed_acl.get("mergeCommit") if isinstance(observed_acl, dict) else None
        )
        if (
            not isinstance(observed_acl, dict)
            or set(observed_acl)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_acl.get("state") != "MERGED"
            or observed_acl.get("baseRefName") != "main"
            or observed_acl.get("headRefName") != acl["branch"]
            or observed_acl.get("headRefOid") != acl["head_commit_sha"]
            or not isinstance(observed_acl_merge, dict)
            or set(observed_acl_merge) != {"oid"}
            or observed_acl_merge.get("oid") != acl["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_REPAIR_PR_INVALID")
        observed_acl_paths = tuple(
            line
            for line in _run(
                [
                    "gh", "pr", "diff", str(acl_pr_number), "--repo", REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_acl_paths != _LOCAL_INSTALL_ACL_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(acl_pr_number), source)
    if task_identity is not None:
        task_identity_pr_number = _as_int(task_identity["pr_number"])
        observed_task_identity = json.loads(
            _run(
                [
                    "gh", "pr", "view", str(task_identity_pr_number),
                    "--repo", REPOSITORY, "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_task_identity_merge = (
            observed_task_identity.get("mergeCommit")
            if isinstance(observed_task_identity, dict)
            else None
        )
        if (
            not isinstance(observed_task_identity, dict)
            or set(observed_task_identity)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_task_identity.get("state") != "MERGED"
            or observed_task_identity.get("baseRefName") != "main"
            or observed_task_identity.get("headRefName") != task_identity["branch"]
            or observed_task_identity.get("headRefOid")
            != task_identity["head_commit_sha"]
            or not isinstance(observed_task_identity_merge, dict)
            or set(observed_task_identity_merge) != {"oid"}
            or observed_task_identity_merge.get("oid")
            != task_identity["merge_commit_sha"]
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_REPAIR_PR_INVALID"
            )
        observed_task_identity_paths = tuple(
            line
            for line in _run(
                [
                    "gh", "pr", "diff", str(task_identity_pr_number),
                    "--repo", REPOSITORY, "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if (
            observed_task_identity_paths
            != _LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_REPAIR_PATHS_INVALID"
            )
        _wait_for_required_checks(str(task_identity_pr_number), source)
    if task_identity_followup is not None:
        task_identity_followup_pr_number = _as_int(task_identity_followup["pr_number"])
        observed_task_identity_followup = json.loads(
            _run(
                [
                    "gh", "pr", "view", str(task_identity_followup_pr_number),
                    "--repo", REPOSITORY, "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_task_identity_followup_merge = (
            observed_task_identity_followup.get("mergeCommit")
            if isinstance(observed_task_identity_followup, dict)
            else None
        )
        if (
            not isinstance(observed_task_identity_followup, dict)
            or set(observed_task_identity_followup)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_task_identity_followup.get("state") != "MERGED"
            or observed_task_identity_followup.get("baseRefName") != "main"
            or observed_task_identity_followup.get("headRefName")
            != task_identity_followup["branch"]
            or observed_task_identity_followup.get("headRefOid")
            != task_identity_followup["head_commit_sha"]
            or not isinstance(observed_task_identity_followup_merge, dict)
            or set(observed_task_identity_followup_merge) != {"oid"}
            or observed_task_identity_followup_merge.get("oid")
            != task_identity_followup["merge_commit_sha"]
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_REPAIR_PR_INVALID"
            )
        observed_task_identity_followup_paths = tuple(
            line
            for line in _run(
                [
                    "gh", "pr", "diff", str(task_identity_followup_pr_number),
                    "--repo", REPOSITORY, "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if (
            observed_task_identity_followup_paths
            != _LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS_INVALID"
            )
        _wait_for_required_checks(str(task_identity_followup_pr_number), source)

    installations = _verify_existing_installations(root)
    baseline_path = root / "github-activity-baseline-v1.json"
    baseline = _read_json(baseline_path)
    if (
        baseline_path.read_bytes() != _canonical(baseline) + b"\n"
        or set(baseline) != {"heavy_run_ids", "request_issue_numbers"}
        or not isinstance(baseline["heavy_run_ids"], list)
        or not isinstance(baseline["request_issue_numbers"], list)
        or _github_activity_snapshot() != baseline
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_ACTIVITY_INVALID")

    common_recovery = {
        "activity_baseline_sha256": hashlib.sha256(_canonical(baseline)).hexdigest(),
        "blocked_state_sha256": hashlib.sha256(
            (root / "state/catalog-bootstrap-state-v1.json").read_bytes()
        ).hexdigest(),
        "bootstrap_source_commit_sha": state.protected_commit_sha,
        "installations": installations,
        "schema_version": "1",
    }
    if task_identity_followup is not None:
        assert task_identity is not None
        prior_retry_path = acl_retry_path
        recovery = {
            **common_recovery,
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": task_identity["merge_commit_sha"],
            "task_identity_followup_merge_commit_sha": task_identity_followup[
                "merge_commit_sha"
            ],
            "task_identity_followup_operation_sha256": hashlib.sha256(
                _canonical(task_identity_followup)
            ).hexdigest(),
            "task_identity_followup_pr_number": task_identity_followup["pr_number"],
        }
        recovery_path = task_identity_retry_path
    elif acl is not None:
        assert verifier is not None
        prior_retry_path = verifier_retry_path
        recovery = {
            **common_recovery,
            "acl_merge_commit_sha": acl["merge_commit_sha"],
            "acl_operation_sha256": hashlib.sha256(_canonical(acl)).hexdigest(),
            "acl_pr_number": acl["pr_number"],
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": verifier["merge_commit_sha"],
        }
        recovery_path = acl_retry_path
    elif verifier is not None:
        assert account is not None
        prior_retry_path = account_retry_path
        recovery = {
            **common_recovery,
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": account["merge_commit_sha"],
            "verifier_merge_commit_sha": verifier["merge_commit_sha"],
            "verifier_operation_sha256": hashlib.sha256(
                _canonical(verifier)
            ).hexdigest(),
            "verifier_pr_number": verifier["pr_number"],
        }
        recovery_path = verifier_retry_path
    elif account is not None:
        assert compat is not None
        prior_retry_path = compat_retry_path
        recovery = {
            **common_recovery,
            "account_merge_commit_sha": account["merge_commit_sha"],
            "account_operation_sha256": hashlib.sha256(
                _canonical(account)
            ).hexdigest(),
            "account_pr_number": account["pr_number"],
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": compat["merge_commit_sha"],
        }
        recovery_path = account_retry_path
    elif compat is not None:
        assert followup is not None
        prior_retry_path = followup_retry_path
        recovery = {
            **common_recovery,
            "compat_merge_commit_sha": compat["merge_commit_sha"],
            "compat_operation_sha256": hashlib.sha256(
                _canonical(compat)
            ).hexdigest(),
            "compat_pr_number": compat["pr_number"],
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": followup["merge_commit_sha"],
        }
        recovery_path = compat_retry_path
    elif followup is None:
        recovery = {
            **common_recovery,
            "public_binding_merge_commit_sha": binding_merge,
            "repair_merge_commit_sha": repair_merge,
            "repair_operation_sha256": hashlib.sha256(_canonical(repair)).hexdigest(),
            "repair_pr_number": repair_pr_number,
        }
        recovery_path = (
            root / "receipts/controller-bootstrap-local-install-retry-v1.json"
        )
    else:
        prior_retry_path = (
            root / "receipts/controller-bootstrap-local-install-retry-v1.json"
        )
        recovery = {
            **common_recovery,
            "followup_merge_commit_sha": followup["merge_commit_sha"],
            "followup_operation_sha256": hashlib.sha256(
                _canonical(followup)
            ).hexdigest(),
            "followup_pr_number": followup["pr_number"],
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": repair_merge,
        }
        recovery_path = followup_retry_path
    _write_canonical(recovery_path, recovery)
    _advance(root, state, "local_install_retry_authorized", recovery)
    return True


def _resume_transient_github_controls_block(root: Path) -> bool:
    state = load_bootstrap_state(_state_path(root))
    if state.phase != "BLOCKED" or state.sequence not in {
        25, 27, 29, 31, 33, 35, 37, 39, 41,
    }:
        return False
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked = _read_json(blocked_path)
    expected_block = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": (
            "CATALOG_BOOTSTRAP_WORKFLOW_FAILED"
            if state.sequence == 37
            else (
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RECEIPTS_INVALID"
                if state.sequence == 41
                else (
                    "CATALOG_BOOTSTRAP_PHASE_FAILED"
                    if state.sequence == 35
                    else "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED"
                )
            )
        ),
        "result": "BLOCKED",
        "schema_version": "1",
    }
    if blocked != expected_block:
        return False
    if blocked_path.read_bytes() != _canonical(blocked) + b"\n":
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BLOCK_INVALID")
    if root.resolve() != EXPECTED_ROOT.resolve():
        raise ValueError("CATALOG_BOOTSTRAP_ROOT_INVALID")
    _disable_controller()
    first_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-v1.json"
    )
    if not first_retry_path.exists():
        return False
    if _is_reparse_path(first_retry_path):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RETRY_RECEIPT_INVALID")
    runtime_commit = _runtime_commit(root)
    enterprise_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-3-v1.json"
    )
    billing_token_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-4-v1.json"
    )
    stable_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-5-v1.json"
    )
    cache_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-6-v1.json"
    )
    storage_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-7-v1.json"
    )
    throughput_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-8-v1.json"
    )
    package_token_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-9-v1.json"
    )
    followup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-2-v1.json"
    )
    retry_path: Path
    evidence: dict[str, object]
    operation_path: Path
    merge_field: str
    expected_paths: tuple[str, ...]
    if state.sequence in {37, 39, 41}:
        if not package_token_retry_path.exists():
            return False
        if _is_reparse_path(package_token_retry_path):
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_PACKAGE_TOKEN_RETRY_INVALID"
            )
        retry_path = package_token_retry_path
        evidence = _read_json(retry_path)
        operation_path = (
            root / "github-controls-package-token-repair-operation-v1.json"
        )
        merge_field = "package_token_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_PACKAGE_TOKEN_REPAIR_PATHS
    elif state.sequence == 35:
        if not throughput_retry_path.exists():
            return False
        if _is_reparse_path(throughput_retry_path):
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_AUDIT_THROUGHPUT_RETRY_INVALID"
            )
        retry_path = throughput_retry_path
        evidence = _read_json(retry_path)
        operation_path = (
            root / "github-controls-audit-throughput-repair-operation-v1.json"
        )
        merge_field = "audit_throughput_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_AUDIT_THROUGHPUT_REPAIR_PATHS
    elif state.sequence == 33:
        if not storage_retry_path.exists():
            return False
        if _is_reparse_path(storage_retry_path):
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STORAGE_AUDIT_RETRY_INVALID"
            )
        retry_path = storage_retry_path
        evidence = _read_json(retry_path)
        operation_path = (
            root / "github-controls-storage-audit-repair-operation-v1.json"
        )
        merge_field = "storage_audit_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_STORAGE_AUDIT_REPAIR_PATHS
    elif state.sequence == 31:
        if not cache_retry_path.exists():
            return False
        if _is_reparse_path(cache_retry_path):
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_CACHE_RETENTION_RETRY_INVALID"
            )
        retry_path = cache_retry_path
        evidence = _read_json(retry_path)
        operation_path = (
            root / "github-controls-cache-retention-repair-operation-v1.json"
        )
        merge_field = "cache_retention_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_CACHE_RETENTION_REPAIR_PATHS
    elif state.sequence == 29:
        if not stable_retry_path.exists():
            return False
        if _is_reparse_path(stable_retry_path):
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STABLE_PRECONDITION_RETRY_INVALID"
            )
        retry_path = stable_retry_path
        evidence = _read_json(retry_path)
        operation_path = (
            root / "github-controls-stable-precondition-repair-operation-v1.json"
        )
        merge_field = "stable_precondition_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_STABLE_PRECONDITION_REPAIR_PATHS
    elif state.sequence == 27:
        if billing_token_retry_path.exists():
            if _is_reparse_path(billing_token_retry_path):
                raise ValueError(
                    "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BILLING_TOKEN_RETRY_INVALID"
                )
            retry_path = billing_token_retry_path
            evidence = _read_json(retry_path)
            operation_path = (
                root / "github-controls-billing-token-repair-operation-v1.json"
            )
            merge_field = "billing_token_merge_commit_sha"
            expected_paths = _GITHUB_CONTROLS_BILLING_TOKEN_REPAIR_PATHS
        elif not enterprise_retry_path.exists():
            return False
        elif _is_reparse_path(enterprise_retry_path):
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_ENTERPRISE_RETRY_INVALID"
            )
        else:
            retry_path = enterprise_retry_path
            evidence = _read_json(retry_path)
            operation_path = (
                root / "github-controls-enterprise-repair-operation-v1.json"
            )
            merge_field = "enterprise_merge_commit_sha"
            expected_paths = _GITHUB_CONTROLS_ENTERPRISE_REPAIR_PATHS
    elif followup_retry_path.exists():
        if _is_reparse_path(followup_retry_path):
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_FOLLOWUP_RETRY_INVALID"
        )
        retry_path = followup_retry_path
        evidence = _read_json(retry_path)
        operation_path = root / "github-controls-followup-repair-operation-v1.json"
        merge_field = "followup_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_FOLLOWUP_REPAIR_PATHS
    else:
        retry_path = first_retry_path
        evidence = _read_json(retry_path)
        operation_path = root / "github-controls-repair-operation-v1.json"
        merge_field = "github_controls_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_REPAIR_PATHS
    if runtime_commit != evidence.get(merge_field):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RETRY_RECEIPT_INVALID")
    if evidence.get("blocked_state_sha256") != hashlib.sha256(
        _state_path(root).read_bytes()
    ).hexdigest():
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BLOCK_STATE_INVALID")
    operation = _read_json(operation_path)
    context = _context(root)
    source = Path(str(context["source_root"])).resolve(strict=True)
    if context.get("source_commit_sha") != runtime_commit:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_CONTEXT_INVALID")
    if (
        _run(["git", "rev-parse", "HEAD"], cwd=source) != runtime_commit
        or _run(["git", "rev-parse", "origin/main"], cwd=source)
        != runtime_commit
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_SOURCE_INVALID")
    observed = json.loads(
        _run(
            [
                "gh", "pr", "view", str(operation["pr_number"]), "--repo",
                REPOSITORY, "--json",
                "state,baseRefName,headRefName,headRefOid,mergeCommit",
            ],
            cwd=source,
        )
    )
    observed_merge = observed.get("mergeCommit") if isinstance(observed, dict) else None
    if (
        not isinstance(observed, dict)
        or observed.get("state") != "MERGED"
        or observed.get("baseRefName") != "main"
        or observed.get("headRefName") != operation["branch"]
        or observed.get("headRefOid") != operation["head_commit_sha"]
        or not isinstance(observed_merge, dict)
        or observed_merge.get("oid") != runtime_commit
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_PR_INVALID")
    _verify_github_controls_repair_graph(source, operation)
    prior_runtime = operation.get("prior_runtime_commit_sha")
    if prior_runtime is not None:
        if prior_runtime != evidence.get("prior_runtime_commit_sha"):
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_PACKAGE_TOKEN_ANCESTRY_INVALID"
            )
        ancestry = subprocess.run(
            [
                "git", "merge-base", "--is-ancestor", str(prior_runtime),
                str(operation["base_commit_sha"]),
            ],
            cwd=source,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        if ancestry.returncode != 0:
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_PACKAGE_TOKEN_ANCESTRY_INVALID"
            )
    observed_paths = tuple(
        line
        for line in _run(
            [
                "gh", "pr", "diff", str(operation["pr_number"]), "--repo",
                REPOSITORY, "--name-only",
            ],
            cwd=source,
        ).splitlines()
        if line
    )
    if observed_paths != expected_paths:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_PATHS_INVALID")
    _wait_for_required_checks(str(operation["pr_number"]), source)
    if _verify_post_install_installations(
        root,
        allow_uploaded_auditor=state.sequence in {37, 39, 41},
    ) != evidence.get("installations"):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_INSTALLATIONS_INVALID")
    baseline_path = root / "github-activity-baseline-v1.json"
    baseline = _read_json(baseline_path)
    if (
        hashlib.sha256(_canonical(baseline)).hexdigest()
        != evidence.get("activity_baseline_sha256")
        or _github_activity_snapshot() != baseline
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_ACTIVITY_INVALID")
    _advance(root, state, "github_controls_retry_authorized", evidence)
    return True


def merge_public_binding(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    receipt = _read_json(root / "public-binding-operation-v1.json")
    pr_number = str(receipt["pr_number"])
    binding_commit = receipt.get("binding_commit_sha")
    if not isinstance(binding_commit, str) or not _COMMIT.fullmatch(binding_commit):
        raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
    expected_head: str
    if state.sequence == 6:
        expected_head = binding_commit
    elif state.sequence == 8:
        retry_path = root / "receipts/controller-bootstrap-merge-retry-v1.json"
        retry = _read_json(retry_path)
        expected_retry_keys = {
            "binding_commit_sha",
            "blocked_state_sha256",
            "head_commit_sha",
            "installations",
            "pr_number",
            "required_checks",
            "review_rounds_sha256",
            "source_commit_sha",
        }
        retry_head = retry.get("head_commit_sha")
        if (
            set(retry) != expected_retry_keys
            or retry_path.read_bytes() != _canonical(retry) + b"\n"
            or retry.get("binding_commit_sha") != binding_commit
            or retry.get("pr_number") != receipt.get("pr_number")
            or retry.get("review_rounds_sha256")
            != receipt.get("review_rounds_sha256")
            or not isinstance(retry_head, str)
            or not _COMMIT.fullmatch(retry_head)
        ):
            raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
        expected_head = retry_head
    else:
        raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
    _wait_for_required_checks(pr_number, source)
    pull_request = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--repo",
                REPOSITORY,
                "--json",
                "state,baseRefName,headRefOid",
            ],
            cwd=source,
        )
    )
    if (
        not isinstance(pull_request, dict)
        or pull_request.get("state") != "OPEN"
        or pull_request.get("baseRefName") != "main"
        or pull_request.get("headRefOid") != expected_head
    ):
        raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
    _run(
        [
            "gh",
            "pr",
            "merge",
            pr_number,
            "--repo",
            REPOSITORY,
            "--merge",
            "--match-head-commit",
            expected_head,
        ],
        cwd=source,
    )
    observed = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--repo",
                REPOSITORY,
                "--json",
                "state,mergeCommit",
            ]
        )
    )
    merge_sha = observed.get("mergeCommit", {}).get("oid")
    if observed.get("state") != "MERGED" or not isinstance(merge_sha, str):
        raise ValueError("BOOTSTRAP_PR_MERGE_UNVERIFIED")
    _run(["git", "fetch", "origin", "main"], cwd=source)
    ancestry = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            str(receipt["binding_commit_sha"]),
            merge_sha,
        ],
        cwd=source,
        timeout=1800,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ValueError("BOOTSTRAP_PR_MERGE_UNVERIFIED")
    receipt["merge_commit_sha"] = merge_sha
    (root / "public-binding-operation-v1.json").write_bytes(
        _canonical(receipt) + b"\n"
    )
    _advance(root, state, "protected_merge_observed", receipt)


def install_local_components(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    merge_sha = _runtime_commit(root)
    _run(["git", "switch", "--detach", merge_sha], cwd=source)
    staging = BOOTSTRAP_STAGING_ROOT
    apps = staging / "requester-apps"
    staging.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "icacls.exe",
            str(staging),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)(F)",
            "*S-1-5-32-544:(OI)(CI)(F)",
        ]
    )
    _run(
        [
            "C:/Python314/python.exe",
            str(source / "scripts/build_catalog_requester_apps.py"),
            "--source-root",
            str(source),
            "--output-dir",
            str(apps),
            "--expected-commit-sha",
            merge_sha,
        ],
        cwd=source,
        timeout_seconds=1800,
    )
    requester_key = root / "secrets/requester-pending.pem"
    staged_key = staging / "requester-private-key.pem"
    if not staged_key.exists():
        staged_key.write_bytes(requester_key.read_bytes())
    _run(
        [
            "icacls.exe",
            str(staged_key),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(F)",
            "*S-1-5-32-544:(F)",
        ]
    )
    requester = _read_json(root / "requester-public-v1.json")
    app_id = str(requester["app_id"])
    installation_id = str(requester["installation_id"])
    setup_environment = (
        f"[Environment]::SetEnvironmentVariable('AURORA_CATALOG_REQUESTER_APP_ID','{app_id}','Machine');"
        f"[Environment]::SetEnvironmentVariable('AURORA_CATALOG_REQUESTER_INSTALLATION_ID','{installation_id}','Machine')"
    )
    _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", setup_environment])
    agent_receipt = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/install_catalog_agent_sandbox.ps1"),
            "-Apply",
            "-Confirm",
            "AURORA_CATALOG_AGENT_SANDBOX_V1",
        ],
        cwd=source,
        timeout_seconds=1800,
    )
    broker_receipt = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/install_catalog_requester_broker.ps1"),
            "-Apply",
            "-Confirm",
            "AURORA_CATALOG_REQUESTER_BROKER_V1",
        ],
        cwd=source,
        timeout_seconds=1800,
    )
    _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Start-ScheduledTask -TaskName 'AURORA Catalog Requester Broker'; Start-Sleep -Seconds 2; if((Get-ScheduledTask -TaskName 'AURORA Catalog Requester Broker').State -ne 'Running'){exit 19}",
        ]
    )
    if staged_key.exists():
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STAGING_NOT_CLEARED")
    installed_key = BROKER_ROOT / "secrets/requester-private-key.pem"
    if not installed_key.is_file():
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_KEY_NOT_INSTALLED")
    requester_key.unlink()
    if requester_key.exists():
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STAGING_NOT_CLEARED")
    receipt = {
        "agent": json.loads(agent_receipt.splitlines()[-1]),
        "broker": json.loads(broker_receipt.splitlines()[-1]),
        "merge_commit_sha": merge_sha,
    }
    (root / "local-install-receipt-v1.json").write_bytes(_canonical(receipt) + b"\n")
    _advance(root, state, "local_install_verified", receipt)


def _prepare_auditor_secret(root: Path) -> dict[str, object]:
    from infra.sp500_megarun.catalog_bootstrap_secrets import upload_auditor_key_once

    pending = root / "secrets/auditor-pending.pem"
    staging = root / "secrets/auditor-upload-once.pem"
    if pending.is_file() and not pending.is_symlink():
        proof = upload_auditor_key_once(staging, bytearray(pending.read_bytes()))
        pending.unlink()
        if pending.exists() or staging.exists():
            raise ValueError("CATALOG_BOOTSTRAP_AUDITOR_STAGING_NOT_CLEARED")
        return proof
    retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-9-v1.json"
    )
    if (
        pending.exists()
        or staging.exists()
        or not retry_path.is_file()
        or _is_reparse_path(retry_path)
        or not _protected_environment_secret_exists()
    ):
        raise ValueError("CATALOG_BOOTSTRAP_AUDITOR_SECRET_NOT_PROVEN")
    return {"name": AUDITOR_SECRET, "status": "preserved"}


def _validated_existing_github_control_receipts(
    root: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    dry_path = root / "receipts/github-controls-dry-run-v1.json"
    apply_path = root / "receipts/github-controls-apply-v1.json"
    if (
        not dry_path.is_file()
        or _is_reparse_path(dry_path)
        or not apply_path.is_file()
        or _is_reparse_path(apply_path)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RECEIPTS_INVALID")
    dry = _read_json(dry_path)
    applied = _read_json(apply_path)
    after_receipt = applied.get("after_receipt")
    prepared = applied.get("bootstrap_controls_prepared") is True or (
        isinstance(after_receipt, dict) and after_receipt.get("status") == "ready"
    )
    if (
        dry_path.read_bytes() not in {
            _canonical(dry) + b"\n",
            _canonical(dry) + b"\r\n",
        }
        or apply_path.read_bytes() not in {
            _canonical(applied) + b"\n",
            _canonical(applied) + b"\r\n",
        }
        or dry.get("mode") != "dry_run"
        or not _SHA256.fullmatch(str(dry.get("current_state_sha256", "")))
        or applied.get("mode") != "apply"
        or not prepared
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RECEIPTS_INVALID")
    return dry, applied


def _prepare_github_controls_operation(
    root: Path,
    protected_commit_sha: str,
    *,
    live_step_name: str,
) -> dict[str, object]:
    context = _context(root)
    source = Path(str(context["source_root"]))
    authority = _read_json(source / "config/catalog_authority_anchor_v1.json")
    auditor = _read_json(root / "auditor-public-v1.json")
    if (
        not _COMMIT.fullmatch(protected_commit_sha)
        or authority.get("production_enabled") is not True
        or not isinstance(authority.get("issue_number"), int)
        or not isinstance(auditor.get("app_id"), int)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_PUBLIC_BINDING_INVALID")
    _require_protected_environment_secrets(PROTECTED_ENVIRONMENT_EXTERNAL_SECRETS)
    _disable_controller()
    _set_repository_variable(
        "CATALOG_AUTHORITY_ISSUE_NUMBER", str(authority["issue_number"])
    )
    dry_path = root / "receipts/github-controls-dry-run-v1.json"
    apply_path = root / "receipts/github-controls-apply-v1.json"
    if dry_path.exists() or apply_path.exists():
        _, applied = _validated_existing_github_control_receipts(root)
    else:
        _run(
            [
                "C:/Python314/python.exe",
                str(source / "scripts/apply_catalog_github_controls.py"),
                "--repo-root",
                str(source),
                "--output",
                str(dry_path),
            ],
            cwd=source,
            timeout_seconds=1800,
        )
        dry = _read_json(dry_path)
        current_sha = str(dry.get("current_state_sha256", ""))
        if not _SHA256.fullmatch(current_sha):
            raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_DRY_RUN_INVALID")
        _run(
            [
                "C:/Python314/python.exe",
                str(source / "scripts/apply_catalog_github_controls.py"),
                "--repo-root",
                str(source),
                "--output",
                str(apply_path),
                "--apply",
                "--bootstrap-controls-only",
                "--verified-dry-run",
                str(dry_path),
                "--expected-current-state-sha",
                current_sha,
                "--confirm",
                "CATALOG_GITHUB_CONTROLS_V1",
            ],
            cwd=source,
            timeout_seconds=1800,
        )
        applied = _read_json(apply_path)
    after_receipt = applied.get("after_receipt")
    if applied.get("bootstrap_controls_prepared") is not True and (
        not isinstance(after_receipt, dict)
        or after_receipt.get("status") != "ready"
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_NOT_PREPARED")
    _set_repository_variable("AURORA_CATALOG_AUDITOR_APP_ID", str(auditor["app_id"]))
    _prepare_auditor_secret(root)
    _require_protected_environment_secrets(PROTECTED_ENVIRONMENT_REQUIRED_SECRETS)
    live = _run_live_qualification(root, protected_commit_sha, step_name=live_step_name)
    receipt = {
        "protected_commit_sha": protected_commit_sha,
        "apply_receipt_sha256": hashlib.sha256(apply_path.read_bytes()).hexdigest(),
        "external_credentials_verified": True,
        "qualified_credentials_verified": True,
        "first_live_qualification": live,
    }
    _write_canonical(root / "github-controls-operation-v1.json", receipt)
    return receipt


def apply_github_controls(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    receipt = _prepare_github_controls_operation(
        root,
        _runtime_commit(root),
        live_step_name="github_controls_live_1",
    )
    _advance(root, state, "github_controls_verified", receipt)


def _refresh_interrupted_runtime_controls(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    if state.phase != "QUALIFICATION_PENDING" or state.sequence != 43:
        return
    resume_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json"
    )
    if not resume_retry_path.exists():
        return
    followup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-11-v1.json"
    )
    catchup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-12-v1.json"
    )
    generic_upgrade_indexes = _idempotent_resume_upgrade_indexes(root)
    prior_upgrade_operation_paths: tuple[Path, ...]
    authorization_operation_paths: tuple[Path, ...]
    if generic_upgrade_indexes:
        if not catchup_retry_path.exists():
            raise ValueError(
                "CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_RETRY_INVALID"
            )
        latest_upgrade_index = generic_upgrade_indexes[-1]
        retry_path = (
            root
            / f"receipts/controller-bootstrap-github-controls-retry-{latest_upgrade_index}-v1.json"
        )
        upgrade_operation_path = (
            root
            / f"github-controls-idempotent-resume-upgrade-{latest_upgrade_index}-operation-v1.json"
        )
        prior_upgrade_operation_paths = (
            *(
                root
                / f"github-controls-idempotent-resume-upgrade-{index}-operation-v1.json"
                for index in generic_upgrade_indexes[:-1]
            ),
            root / "github-controls-idempotent-resume-catchup-repair-operation-v1.json",
            root / "github-controls-idempotent-resume-followup-repair-operation-v1.json",
            root / "github-controls-idempotent-resume-repair-operation-v1.json",
        )
        authorization_operation_paths = tuple(
            root
            / f"github-controls-idempotent-resume-upgrade-{index}-operation-v1.json"
            for index in generic_upgrade_indexes
        )
    elif catchup_retry_path.exists():
        retry_path = catchup_retry_path
        upgrade_operation_path = (
            root
            / "github-controls-idempotent-resume-catchup-repair-operation-v1.json"
        )
        prior_upgrade_operation_paths = (
            root / "github-controls-idempotent-resume-followup-repair-operation-v1.json",
            root / "github-controls-idempotent-resume-repair-operation-v1.json",
        )
        authorization_operation_paths = (upgrade_operation_path,)
    elif followup_retry_path.exists():
        retry_path = followup_retry_path
        upgrade_operation_path = (
            root
            / "github-controls-idempotent-resume-followup-repair-operation-v1.json"
        )
        prior_upgrade_operation_paths = (
            root / "github-controls-idempotent-resume-repair-operation-v1.json",
        )
        authorization_operation_paths = (upgrade_operation_path,)
    else:
        retry_path = resume_retry_path
        upgrade_operation_path = (
            root / "github-controls-idempotent-resume-repair-operation-v1.json"
        )
        prior_upgrade_operation_paths = ()
        authorization_operation_paths = (upgrade_operation_path,)
    state_path = _state_path(root)
    state_document = _read_json(state_path)
    retry = _read_json(retry_path)
    baseline_path = root / "github-activity-baseline-v1.json"
    baseline = _read_json(baseline_path)
    if (
        retry.get("bootstrap_id") != state_document.get("bootstrap_id")
        or retry.get("interrupted_state_sha256")
        != hashlib.sha256(state_path.read_bytes()).hexdigest()
        or retry.get("activity_baseline_sha256") != hashlib.sha256(_canonical(baseline)).hexdigest()
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_STATE_INVALID")

    upgrade_operation = _read_json(upgrade_operation_path)
    acceptable_prior_runtimes = {upgrade_operation.get("prior_runtime_commit_sha")}
    for prior_upgrade_operation_path in prior_upgrade_operation_paths:
        prior_upgrade_operation = _read_json(prior_upgrade_operation_path)
        acceptable_prior_runtimes.add(
            prior_upgrade_operation.get("prior_runtime_commit_sha")
        )
    if any(
        not isinstance(commit, str) or not _COMMIT.fullmatch(commit)
        for commit in acceptable_prior_runtimes
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CONTROLS_INVALID")
    context = _context(root)
    source = Path(str(context["source_root"]))
    _run(["git", "fetch", "origin", "main"], cwd=source, timeout_seconds=1800)
    protected_commit_sha = _runtime_commit(root, allow_pending_idempotent_resume=True)
    if (
        context.get("source_commit_sha") != protected_commit_sha
        or _run(["git", "rev-parse", "HEAD"], cwd=source) != protected_commit_sha
        or _run(["git", "rev-parse", "origin/main"], cwd=source) != protected_commit_sha
        or _run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=source,
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_SOURCE_INVALID")
    for authorization_operation_path in authorization_operation_paths:
        _verify_idempotent_resume_github_authorization(
            source,
            _read_json(authorization_operation_path),
            protected_main_commit_sha=protected_commit_sha,
        )

    controls_path = root / "github-controls-operation-v1.json"
    controls = _read_canonical_document(
        controls_path, "CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CONTROLS_INVALID"
    )
    backup_path = root / "github-controls-operation-before-runtime-upgrade-v1.json"
    refresh_path = root / "runtime-upgrade-controls-refresh-v1.json"
    if controls.get("protected_commit_sha") in acceptable_prior_runtimes:
        _write_exact_canonical_checkpoint(backup_path, controls)
        _prepare_github_controls_operation(
            root,
            protected_commit_sha,
            live_step_name="github_controls_runtime_upgrade_live_1",
        )
        controls = _read_canonical_document(
            controls_path,
            "CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CONTROLS_INVALID",
        )
    elif controls.get("protected_commit_sha") != protected_commit_sha:
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CONTROLS_INVALID")

    if not backup_path.exists():
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_BACKUP_MISSING")
    prior_controls = _read_canonical_document(
        backup_path, "CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_BACKUP_INVALID"
    )
    if (
        prior_controls.get("protected_commit_sha") not in acceptable_prior_runtimes
        or controls.get("protected_commit_sha") != protected_commit_sha
    ):
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CONTROLS_INVALID")
    refresh = {
        "bootstrap_id": state_document["bootstrap_id"],
        "prior_controls_operation_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
        "protected_commit_sha": protected_commit_sha,
        "refreshed_controls_operation_sha256": hashlib.sha256(
            controls_path.read_bytes()
        ).hexdigest(),
        "runtime_upgrade_operation_sha256": hashlib.sha256(
            upgrade_operation_path.read_bytes()
        ).hexdigest(),
        "schema_version": "1",
    }
    _write_exact_canonical_checkpoint(refresh_path, refresh)
    if _runtime_commit(root) != protected_commit_sha:
        raise ValueError("CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_REFRESH_INVALID")


def _parse_terminal_controller_receipt(issue_number: int) -> dict[str, object]:
    pages = json.loads(
        _run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"/repos/{REPOSITORY}/issues/{issue_number}/comments?per_page=100",
            ]
        )
    )
    rows = [row for page in pages for row in page]
    marker = "<!-- AURORA_CATALOG_REQUEST_RECEIPT_V1 -->\n```json\n"
    receipts: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("body"), str):
            continue
        body = str(row["body"])
        user = row.get("user")
        if marker not in body:
            continue
        if (
            not isinstance(user, dict)
            or user.get("login") != "github-actions[bot]"
            or row.get("created_at") != row.get("updated_at")
            or body.count(marker) != 1
            or not body.endswith("\n```\n")
        ):
            raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
        encoded = body.split(marker, 1)[1][:-5]
        value = json.loads(
            encoded,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
        if not isinstance(value, dict) or encoded.encode() != _canonical(value):
            raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
        receipts.append(value)
    exact = [
        row
        for row in receipts
        if row.get("issue_number") == issue_number
        and row.get("state") == "BLOCKED"
        and row.get("reason_code") == "CATALOG_CONTROLLER_DISABLED"
        and row.get("writer_job_id") == "report_nonexecuting_decision"
        and _SHA256.fullmatch(str(row.get("receipt_sha256", "")))
    ]
    if len(exact) != 1:
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
    identity = {key: value for key, value in exact[0].items() if key != "receipt_sha256"}
    if hashlib.sha256(_canonical(identity)).hexdigest() != exact[0]["receipt_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
    return exact[0]


def _invoke_bootstrap_request(source: Path) -> dict[str, object]:
    raw = _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/run_catalog_bootstrap_qualification_client.ps1"),
        ],
        cwd=source,
        timeout_seconds=300,
    )
    value = json.loads(raw.splitlines()[-1])
    if (
        not isinstance(value, dict)
        or value.get("campaign_key") != _BOOTSTRAP_QUALIFICATION_CAMPAIGN
        or value.get("status") not in {"pending", "submitted", "existing", "blocked"}
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_INVALID")
    _validate_requester_receipt(value)
    if value.get("status") == "blocked":
        reason = str(value.get("reason_code", "UNKNOWN"))
        raise ValueError(f"CATALOG_BOOTSTRAP_REQUESTER_BLOCKED:{reason}")
    return value


def _seal_hash(payload: dict[str, object], field: str) -> str:
    unsigned = {**payload, field: "0" * 64}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _validate_requester_receipt(value: dict[str, object]) -> None:
    expected_keys = {
        "schema_version",
        "status",
        "reason_code",
        "submission_key_sha256",
        "request_id",
        "campaign_key",
        "launch_generation",
        "issue_number",
        "request_sha256",
        "observed_at",
        "receipt_sha256",
    }
    if set(value) != expected_keys:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_INVALID")
    status = value.get("status")
    submitted = status in {"submitted", "existing"}
    if (
        value.get("schema_version") != "1"
        or status not in {"pending", "submitted", "existing", "blocked"}
        or not isinstance(value.get("reason_code"), str)
        or not _SHA256.fullmatch(str(value.get("submission_key_sha256", "")))
        or not isinstance(value.get("request_id"), str)
        or re.fullmatch(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            str(value.get("request_id")),
        ) is None
        or value.get("campaign_key") != _BOOTSTRAP_QUALIFICATION_CAMPAIGN
        or isinstance(value.get("launch_generation"), bool)
        or not isinstance(value.get("launch_generation"), int)
        or value.get("launch_generation") != 1
        or not isinstance(value.get("observed_at"), str)
        or not _SHA256.fullmatch(str(value.get("receipt_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_INVALID")
    has_issue = (
        isinstance(value.get("issue_number"), int)
        and not isinstance(value.get("issue_number"), bool)
        and _as_int(value["issue_number"]) > 0
    )
    has_request = _SHA256.fullmatch(str(value.get("request_sha256", ""))) is not None
    if submitted != has_issue or submitted != has_request:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_INVALID")
    unsigned = {**value, "receipt_sha256": "0" * 64}
    if hashlib.sha256(_canonical(unsigned)).hexdigest() != value["receipt_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_INVALID")


def _validate_requester_status(value: dict[str, object]) -> None:
    expected_keys = {
        "schema_version",
        "campaign_key",
        "state",
        "launch_generation",
        "launch_ticket_sha256",
        "submission_key_sha256",
        "request_id",
        "request_sha256",
        "issue_number",
        "last_github_checked_at",
        "updated_at",
        "status_sha256",
    }
    if set(value) != expected_keys:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STATUS_INVALID")
    state = value.get("state")
    requested = state in {"request_pending", "active", "terminal"}
    github_known = state in {"active", "terminal"}
    if (
        value.get("schema_version") != "1"
        or value.get("campaign_key") != _BOOTSTRAP_QUALIFICATION_CAMPAIGN
        or state not in {"ticket_available", "request_pending", "active", "terminal"}
        or isinstance(value.get("launch_generation"), bool)
        or not isinstance(value.get("launch_generation"), int)
        or value.get("launch_generation") != 1
        or not _SHA256.fullmatch(str(value.get("launch_ticket_sha256", "")))
        or (requested != (_SHA256.fullmatch(str(value.get("submission_key_sha256", ""))) is not None))
        or (
            requested
            != (
                isinstance(value.get("request_id"), str)
                and re.fullmatch(
                    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    str(value.get("request_id")),
                )
                is not None
            )
        )
        or (github_known != (_SHA256.fullmatch(str(value.get("request_sha256", ""))) is not None))
        or (github_known != (isinstance(value.get("issue_number"), int) and not isinstance(value.get("issue_number"), bool) and _as_int(value["issue_number"]) > 0))
        or not isinstance(value.get("updated_at"), str)
        or not _SHA256.fullmatch(str(value.get("status_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STATUS_INVALID")
    if github_known != isinstance(value.get("last_github_checked_at"), str):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STATUS_INVALID")
    unsigned = {**value, "status_sha256": "0" * 64}
    if hashlib.sha256(_canonical(unsigned)).hexdigest() != value["status_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STATUS_INVALID")


def _requester_status_path() -> Path:
    return (
        BROKER_ROOT
        / "campaign-status"
        / f"{_BOOTSTRAP_QUALIFICATION_CAMPAIGN}.status.json"
    )


def _load_requester_status() -> dict[str, object] | None:
    path = _requester_status_path()
    if not path.exists() and not path.is_symlink():
        return None
    status = _read_canonical_document(
        path, "CATALOG_BOOTSTRAP_REQUESTER_STATUS_INVALID"
    )
    _validate_requester_status(status)
    return status


def _wait_for_requester_ticket() -> None:
    ticket = (
        BROKER_ROOT
        / "launch-tickets"
        / f"{_BOOTSTRAP_QUALIFICATION_CAMPAIGN}.ticket.json"
    )
    deadline = time.monotonic() + 300
    while not ticket.exists() and not ticket.is_symlink() and time.monotonic() < deadline:
        time.sleep(2)
    if not ticket.exists() and not ticket.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_TICKET_MISSING")
    value = _read_canonical_document(
        ticket, "CATALOG_BOOTSTRAP_QUALIFICATION_TICKET_INVALID"
    )
    expected = {
        "schema_version",
        "request_id",
        "campaign_key",
        "launch_generation",
        "campaign_definition_sha256",
        "prompt_sha256",
        "previous_terminal_request_sha256",
    }
    if (
        set(value) != expected
        or value.get("schema_version") != "1"
        or value.get("campaign_key") != _BOOTSTRAP_QUALIFICATION_CAMPAIGN
        or value.get("launch_generation") != 1
        or not _SHA256.fullmatch(str(value.get("campaign_definition_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("prompt_sha256", "")))
        or value.get("previous_terminal_request_sha256") is not None
        or re.fullmatch(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            str(value.get("request_id")),
        ) is None
        or hashlib.sha256(_canonical(value)).hexdigest()
        != str((_load_requester_status() or {}).get("launch_ticket_sha256", ""))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_TICKET_INVALID")


def _wait_for_terminal_requester_status(
    status: dict[str, object] | None,
) -> dict[str, object]:
    if status is not None and status.get("state") == "terminal":
        return status
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        observed = _load_requester_status()
        if observed is not None and observed.get("state") == "terminal":
            return observed
        time.sleep(5)
    raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_NOT_TERMINAL")


def _load_requester_public_binding(root: Path) -> dict[str, object]:
    path = root / "requester-public-v1.json"
    value = _read_canonical_document(
        path, "CATALOG_BOOTSTRAP_REQUESTER_IDENTITY_INVALID"
    )
    if (
        not isinstance(value.get("app_slug"), str)
        or not value["app_slug"]
        or (
            value.get("public_key_sha256") is not None
            and not _SHA256.fullmatch(str(value["public_key_sha256"]))
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_IDENTITY_INVALID")
    return value


def _request_payload_from_issue(
    issue: dict[str, object],
    *,
    status: dict[str, object],
    requester: dict[str, object],
) -> dict[str, object]:
    title = f"[AURORA CATALOG RUN REQUEST] {status['request_id']}"
    body = issue.get("body")
    if issue.get("title") != title or not isinstance(body, str):
        raise ValueError("CATALOG_BOOTSTRAP_REQUEST_SIGNING_INVALID")
    prefix = "```json\n"
    suffix = "\n```\n"
    if not body.startswith(prefix) or not body.endswith(suffix):
        raise ValueError("CATALOG_BOOTSTRAP_REQUEST_SIGNING_INVALID")
    encoded = body[len(prefix) : -len(suffix)]
    try:
        payload = json.loads(
            encoded,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("CATALOG_BOOTSTRAP_REQUEST_SIGNING_INVALID") from exc
    if not isinstance(payload, dict) or encoded.encode() != _canonical(payload):
        raise ValueError("CATALOG_BOOTSTRAP_REQUEST_SIGNING_INVALID")
    required = {
        "schema_version",
        "request_id",
        "campaign_key",
        "launch_generation",
        "launch_ticket_sha256",
        "previous_terminal_request_sha256",
        "campaign_definition_sha256",
        "prompt_sha256",
        "authorization",
        "free_resources_only",
        "automatic_recovery",
        "max_same_failure_count",
        "requester_public_key_sha256",
        "requester_attestation_algorithm",
        "requester_attestation_b64",
    }
    if (
        set(payload) != required
        or payload.get("schema_version") != "1"
        or payload.get("request_id") != status["request_id"]
        or payload.get("campaign_key") != _BOOTSTRAP_QUALIFICATION_CAMPAIGN
        or payload.get("launch_generation") != 1
        or payload.get("launch_ticket_sha256") != status["launch_ticket_sha256"]
        or payload.get("previous_terminal_request_sha256") is not None
        or not _SHA256.fullmatch(str(payload.get("campaign_definition_sha256", "")))
        or not _SHA256.fullmatch(str(payload.get("prompt_sha256", "")))
        or payload.get("authorization") != "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN"
        or payload.get("free_resources_only") is not True
        or payload.get("automatic_recovery") is not True
        or payload.get("max_same_failure_count") != 3
        or (
            requester.get("public_key_sha256") is not None
            and payload.get("requester_public_key_sha256")
            != requester.get("public_key_sha256")
        )
        or payload.get("requester_attestation_algorithm")
        != "rsa-pss-sha256-v1"
        or not isinstance(payload.get("requester_attestation_b64"), str)
        or len(str(payload.get("requester_attestation_b64"))) < 300
        or not _SHA256.fullmatch(str(status.get("request_sha256", "")))
        or hashlib.sha256(_canonical(payload)).hexdigest() != status["request_sha256"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUEST_SIGNING_INVALID")
    return payload


def _load_remote_requester_issue(
    issue_number: int,
    *,
    status: dict[str, object],
    requester: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], str]:
    raw = _run(["gh", "api", f"/repos/{REPOSITORY}/issues/{issue_number}"])
    try:
        issue = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_ISSUE_INVALID") from exc
    if not isinstance(issue, dict):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_ISSUE_INVALID")
    actor = f"{requester['app_slug']}[bot]"
    closed_by = issue.get("closed_by")
    user = issue.get("user")
    if (
        issue.get("number") != issue_number
        or issue.get("state") != "closed"
        or issue.get("state_reason") != "completed"
        or not isinstance(user, Mapping)
        or user.get("login") != actor
        or not isinstance(closed_by, Mapping)
        or closed_by.get("login") != "github-actions[bot]"
        or issue.get("html_url")
        != f"https://github.com/{REPOSITORY}/issues/{issue_number}"
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_ISSUE_INVALID")
    payload = _request_payload_from_issue(issue, status=status, requester=requester)
    identity = {
        "number": issue_number,
        "html_url": issue["html_url"],
        "user_login": actor,
        "closed_by_login": "github-actions[bot]",
    }
    return issue, identity, hashlib.sha256(_canonical(issue)).hexdigest()


def _validate_controller_receipt(
    receipt: dict[str, object],
    *,
    issue_number: int,
    request_sha256: str,
) -> None:
    if (
        receipt.get("issue_number") != issue_number
        or receipt.get("state") != "BLOCKED"
        or receipt.get("reason_code") != "CATALOG_CONTROLLER_DISABLED"
        or receipt.get("writer_job_id") != "report_nonexecuting_decision"
        or receipt.get("request_sha256") != request_sha256
        or not _SHA256.fullmatch(str(receipt.get("receipt_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
    identity = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if hashlib.sha256(_canonical(identity)).hexdigest() != receipt["receipt_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")


def _load_local_requester_receipt(
    status: dict[str, object],
) -> tuple[dict[str, object], str] | None:
    submission = str(status["submission_key_sha256"])
    path = BROKER_ROOT / "receipts" / f"{submission}.receipt.json"
    if not path.exists() and not path.is_symlink():
        return None
    receipt = _read_canonical_document(
        path, "CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_INVALID"
    )
    _validate_requester_receipt(receipt)
    if (
        receipt.get("status") not in {"submitted", "existing"}
        or receipt.get("submission_key_sha256") != status["submission_key_sha256"]
        or receipt.get("request_id") != status["request_id"]
        or receipt.get("request_sha256") != status["request_sha256"]
        or receipt.get("issue_number") != status["issue_number"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_INVALID")
    return receipt, hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_requester_identity(
    status: Mapping[str, object],
    receipt: Mapping[str, object],
    *,
    error_code: str,
) -> None:
    if any(
        status.get(field) != receipt.get(field)
        for field in (
            "request_id",
            "request_sha256",
            "submission_key_sha256",
            "issue_number",
        )
    ):
        raise ValueError(error_code)


def _ensure_local_requester_receipt(
    status: dict[str, object], receipt: dict[str, object]
) -> tuple[dict[str, object], str]:
    _validate_requester_status(status)
    _validate_requester_receipt(receipt)
    _validate_requester_identity(
        status,
        receipt,
        error_code="CATALOG_BOOTSTRAP_REQUESTER_EVIDENCE_IDENTITY_MISMATCH",
    )
    local = _load_local_requester_receipt(status)
    if local is None:
        submission = str(status["submission_key_sha256"])
        path = BROKER_ROOT / "receipts" / f"{submission}.receipt.json"
        _write_exact_canonical_checkpoint(path, receipt)
        local = _load_local_requester_receipt(status)
    if local is None:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_MISSING")
    observed, file_sha256 = local
    if observed != receipt:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_CHANGED")
    return observed, file_sha256


def _validate_bootstrap_seal(
    seal: dict[str, object],
    *,
    status: dict[str, object],
    controller: dict[str, object],
    protected_commit_sha: str,
) -> None:
    expected = {
        "schema_version",
        "qualification_permanently_sealed",
        "qualification_submission_key_sha256",
        "qualification_request_sha256",
        "qualification_issue_number",
        "controller_receipt_sha256",
        "sealed_at",
        "bootstrap_seal_sha256",
    }
    if (
        set(seal) != expected
        or seal.get("schema_version") != "1"
        or seal.get("qualification_permanently_sealed") is not True
        or seal.get("qualification_submission_key_sha256")
        != status["submission_key_sha256"]
        or seal.get("qualification_request_sha256") != status["request_sha256"]
        or seal.get("qualification_issue_number") != status["issue_number"]
        or seal.get("controller_receipt_sha256") != controller["receipt_sha256"]
        or not isinstance(seal.get("sealed_at"), str)
        or not _SHA256.fullmatch(str(seal.get("bootstrap_seal_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_SEAL_INVALID")
    if protected_commit_sha and not _COMMIT.fullmatch(protected_commit_sha):
        raise ValueError("CATALOG_BOOTSTRAP_SEAL_INVALID")
    if _seal_hash(seal, "bootstrap_seal_sha256") != seal["bootstrap_seal_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_SEAL_INVALID")


def _load_or_create_bootstrap_seal(
    *,
    status: dict[str, object],
    controller: dict[str, object],
    protected_commit_sha: str,
) -> dict[str, object]:
    path = BROKER_ROOT / "config/bootstrap-qualified-v1.seal.json"
    if path.exists() or path.is_symlink():
        seal = _read_canonical_document(path, "CATALOG_BOOTSTRAP_SEAL_INVALID")
        _validate_bootstrap_seal(
            seal,
            status=status,
            controller=controller,
            protected_commit_sha=protected_commit_sha,
        )
        return seal
    seal = {
        "schema_version": "1",
        "qualification_permanently_sealed": True,
        "qualification_submission_key_sha256": status["submission_key_sha256"],
        "qualification_request_sha256": status["request_sha256"],
        "qualification_issue_number": status["issue_number"],
        "controller_receipt_sha256": controller["receipt_sha256"],
        "sealed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "bootstrap_seal_sha256": "0" * 64,
    }
    seal["bootstrap_seal_sha256"] = _seal_hash(seal, "bootstrap_seal_sha256")
    _write_exact_canonical_checkpoint(path, seal)
    observed = _read_canonical_document(path, "CATALOG_BOOTSTRAP_SEAL_INVALID")
    _validate_bootstrap_seal(
        observed,
        status=status,
        controller=controller,
        protected_commit_sha=protected_commit_sha,
    )
    return observed


def _requester_qualification_from_evidence(
    *,
    status: dict[str, object],
    receipt: dict[str, object],
    receipt_file_sha256: str,
    identity: dict[str, object],
    issue_sha256: str,
    controller: dict[str, object],
    seal: dict[str, object],
    duplicate_call_proof_sha256: str,
) -> dict[str, object]:
    return {
        "issue_number": status["issue_number"],
        "submission_key_sha256": status["submission_key_sha256"],
        "request_sha256": status["request_sha256"],
        "request_id": status["request_id"],
        "launch_ticket_sha256": status["launch_ticket_sha256"],
        "status_sha256": status["status_sha256"],
        "requester_receipt_sha256": receipt["receipt_sha256"],
        "requester_receipt_file_sha256": receipt_file_sha256,
        "issue_identity_sha256": hashlib.sha256(_canonical(identity)).hexdigest(),
        "issue_sha256": issue_sha256,
        "controller_receipt_sha256": controller["receipt_sha256"],
        "bootstrap_seal_sha256": seal["bootstrap_seal_sha256"],
        "duplicate_call_proof_sha256": duplicate_call_proof_sha256,
    }


def _requester_checkpoint_hash(value: dict[str, object], field: str) -> str:
    return _seal_hash(value, field)


def _terminal_checkpoint_payload(
    *,
    protected_commit_sha: str,
    status: dict[str, object],
    receipt: dict[str, object],
    receipt_file_sha256: str,
    identity: dict[str, object],
    issue_sha256: str,
    controller: dict[str, object],
    seal: dict[str, object],
    duplicate_call_proof_sha256: str,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1",
        "campaign_key": _BOOTSTRAP_QUALIFICATION_CAMPAIGN,
        "protected_commit_sha": protected_commit_sha,
        "status": status,
        "status_sha256": status["status_sha256"],
        "requester_receipt": receipt,
        "requester_receipt_sha256": receipt["receipt_sha256"],
        "requester_receipt_file_sha256": receipt_file_sha256,
        "request_id": status["request_id"],
        "request_sha256": status["request_sha256"],
        "submission_key_sha256": status["submission_key_sha256"],
        "launch_ticket_sha256": status["launch_ticket_sha256"],
        "issue_number": status["issue_number"],
        "issue_identity": identity,
        "issue_identity_sha256": hashlib.sha256(_canonical(identity)).hexdigest(),
        "issue_sha256": issue_sha256,
        "controller_receipt": controller,
        "controller_receipt_sha256": controller["receipt_sha256"],
        "bootstrap_seal_sha256": seal["bootstrap_seal_sha256"],
        "duplicate_call_proof_sha256": duplicate_call_proof_sha256,
        "requester_qualification": _requester_qualification_from_evidence(
            status=status,
            receipt=receipt,
            receipt_file_sha256=receipt_file_sha256,
            identity=identity,
            issue_sha256=issue_sha256,
            controller=controller,
            seal=seal,
            duplicate_call_proof_sha256=duplicate_call_proof_sha256,
        ),
        "terminal_checkpoint_sha256": "0" * 64,
    }
    value["terminal_checkpoint_sha256"] = _requester_checkpoint_hash(
        value, "terminal_checkpoint_sha256"
    )
    return value


def _validate_terminal_checkpoint(value: dict[str, object]) -> None:
    expected = {
        "schema_version",
        "campaign_key",
        "protected_commit_sha",
        "status",
        "status_sha256",
        "requester_receipt",
        "requester_receipt_sha256",
        "requester_receipt_file_sha256",
        "request_id",
        "request_sha256",
        "submission_key_sha256",
        "launch_ticket_sha256",
        "issue_number",
        "issue_identity",
        "issue_identity_sha256",
        "issue_sha256",
        "controller_receipt",
        "controller_receipt_sha256",
        "bootstrap_seal_sha256",
        "duplicate_call_proof_sha256",
        "requester_qualification",
        "terminal_checkpoint_sha256",
    }
    status = value.get("status")
    receipt = value.get("requester_receipt")
    controller = value.get("controller_receipt")
    identity = value.get("issue_identity")
    if (
        set(value) != expected
        or value.get("schema_version") != "1"
        or value.get("campaign_key") != _BOOTSTRAP_QUALIFICATION_CAMPAIGN
        or not _COMMIT.fullmatch(str(value.get("protected_commit_sha", "")))
        or not isinstance(status, dict)
        or not isinstance(receipt, dict)
        or not isinstance(controller, dict)
        or not isinstance(identity, dict)
        or not _SHA256.fullmatch(str(value.get("status_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("requester_receipt_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("requester_receipt_file_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("launch_ticket_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("issue_identity_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("issue_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("controller_receipt_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("bootstrap_seal_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("duplicate_call_proof_sha256", "")))
        or not _SHA256.fullmatch(str(value.get("terminal_checkpoint_sha256", "")))
        or value.get("request_id") != status.get("request_id")
        or value.get("request_sha256") != status.get("request_sha256")
        or value.get("submission_key_sha256")
        != status.get("submission_key_sha256")
        or value.get("launch_ticket_sha256") != status.get("launch_ticket_sha256")
        or value.get("issue_number") != status.get("issue_number")
        or value.get("status_sha256") != status.get("status_sha256")
        or value.get("requester_receipt_sha256") != receipt.get("receipt_sha256")
        or value.get("controller_receipt_sha256") != controller.get("receipt_sha256")
        or value.get("issue_identity_sha256")
        != hashlib.sha256(_canonical(identity)).hexdigest()
        or value.get("requester_qualification")
        != _requester_qualification_from_evidence(
            status=status,
            receipt=receipt,
            receipt_file_sha256=str(value["requester_receipt_file_sha256"]),
            identity=identity,
            issue_sha256=str(value["issue_sha256"]),
            controller=controller,
            seal={"bootstrap_seal_sha256": value["bootstrap_seal_sha256"]},
            duplicate_call_proof_sha256=str(value["duplicate_call_proof_sha256"]),
        )
        or _requester_checkpoint_hash(value, "terminal_checkpoint_sha256")
        != value["terminal_checkpoint_sha256"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_TERMINAL_CHECKPOINT_INVALID")
    _validate_requester_status(status)
    _validate_requester_receipt(receipt)
    _validate_controller_receipt(
        controller,
        issue_number=_as_int(value["issue_number"]),
        request_sha256=str(status["request_sha256"]),
    )


def _complete_checkpoint_payload(
    terminal: dict[str, object],
) -> dict[str, object]:
    value = {**terminal, "complete_checkpoint_sha256": "0" * 64}
    value["complete_checkpoint_sha256"] = _requester_checkpoint_hash(
        value, "complete_checkpoint_sha256"
    )
    return value


def _validate_complete_checkpoint(value: dict[str, object]) -> None:
    expected = {
        "schema_version",
        "campaign_key",
        "protected_commit_sha",
        "status",
        "status_sha256",
        "requester_receipt",
        "requester_receipt_sha256",
        "requester_receipt_file_sha256",
        "request_id",
        "request_sha256",
        "submission_key_sha256",
        "launch_ticket_sha256",
        "issue_number",
        "issue_identity",
        "issue_identity_sha256",
        "issue_sha256",
        "controller_receipt",
        "controller_receipt_sha256",
        "bootstrap_seal_sha256",
        "duplicate_call_proof_sha256",
        "requester_qualification",
        "terminal_checkpoint_sha256",
        "complete_checkpoint_sha256",
    }
    if set(value) != expected or _requester_checkpoint_hash(
        value, "complete_checkpoint_sha256"
    ) != value.get("complete_checkpoint_sha256"):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_COMPLETE_CHECKPOINT_INVALID")
    _validate_terminal_checkpoint(
        {key: value[key] for key in expected if key != "complete_checkpoint_sha256"}
    )


def _revalidate_requester_evidence(
    root: Path,
    source: Path,
    evidence: dict[str, object],
    *,
    protected_commit_sha: str,
) -> None:
    if evidence.get("protected_commit_sha") != protected_commit_sha:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_PROTECTED_COMMIT_MISMATCH")
    checkpoint_receipt = evidence.get("requester_receipt")
    checkpoint_status = evidence.get("status")
    if not isinstance(checkpoint_receipt, dict) or not isinstance(
        checkpoint_status, dict
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_EVIDENCE_IDENTITY_MISMATCH")
    identity_fields = (
        "request_id",
        "request_sha256",
        "submission_key_sha256",
        "issue_number",
    )
    if any(
        evidence.get(field) != checkpoint_status.get(field)
        or evidence.get(field) != checkpoint_receipt.get(field)
        for field in identity_fields
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_EVIDENCE_IDENTITY_MISMATCH")
    status = _load_requester_status()
    if status is None or status != evidence.get("status"):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STATUS_CHANGED")
    if status["status_sha256"] != evidence["status_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STATUS_CHANGED")
    requester = _load_requester_public_binding(root)
    issue, identity, issue_sha256 = _load_remote_requester_issue(
        _as_int(status["issue_number"]), status=status, requester=requester
    )
    if (
        identity != evidence.get("issue_identity")
        or hashlib.sha256(_canonical(identity)).hexdigest()
        != evidence.get("issue_identity_sha256")
        or issue_sha256 != evidence.get("issue_sha256")
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_ISSUE_CHANGED")
    del issue
    controller = _parse_terminal_controller_receipt(_as_int(status["issue_number"]))
    _validate_controller_receipt(
        controller,
        issue_number=_as_int(status["issue_number"]),
        request_sha256=str(status["request_sha256"]),
    )
    if controller != evidence.get("controller_receipt"):
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_CHANGED")
    if controller["receipt_sha256"] != evidence.get("controller_receipt_sha256"):
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_CHANGED")
    seal_path = BROKER_ROOT / "config/bootstrap-qualified-v1.seal.json"
    seal = _read_canonical_document(seal_path, "CATALOG_BOOTSTRAP_SEAL_INVALID")
    _validate_bootstrap_seal(
        seal,
        status=status,
        controller=controller,
        protected_commit_sha=protected_commit_sha,
    )
    if seal["bootstrap_seal_sha256"] != evidence.get("bootstrap_seal_sha256"):
        raise ValueError("CATALOG_BOOTSTRAP_SEAL_CHANGED")
    local = _load_local_requester_receipt(status)
    if local is None:
        recovered = _invoke_bootstrap_request(source)
        if recovered != checkpoint_receipt:
            raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_CHANGED")
        local = _ensure_local_requester_receipt(status, recovered)
    receipt, file_sha256 = local
    if (
        receipt != checkpoint_receipt
        or file_sha256 != evidence.get("requester_receipt_file_sha256")
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_CHANGED")


def _run_requester_qualification(
    root: Path,
    source: Path,
    protected_commit_sha: str | None = None,
) -> dict[str, object]:
    if protected_commit_sha is None:
        context = _context(root)
        protected_commit_sha = str(context.get("source_commit_sha", ""))
    if not _COMMIT.fullmatch(protected_commit_sha):
        raise ValueError("CATALOG_BOOTSTRAP_PROTECTED_COMMIT_INVALID")

    terminal_path = root / REQUESTER_TERMINAL_CHECKPOINT_FILENAME
    complete_path = root / REQUESTER_COMPLETE_CHECKPOINT_FILENAME
    if complete_path.exists() or complete_path.is_symlink():
        complete = _read_canonical_document(
            complete_path, "CATALOG_BOOTSTRAP_REQUESTER_COMPLETE_CHECKPOINT_INVALID"
        )
        _validate_complete_checkpoint(complete)
        _revalidate_requester_evidence(
            root, source, complete, protected_commit_sha=protected_commit_sha
        )
        return cast(dict[str, object], complete["requester_qualification"])

    if terminal_path.exists() or terminal_path.is_symlink():
        terminal = _read_canonical_document(
            terminal_path, "CATALOG_BOOTSTRAP_REQUESTER_TERMINAL_CHECKPOINT_INVALID"
        )
        _validate_terminal_checkpoint(terminal)
        _revalidate_requester_evidence(
            root, source, terminal, protected_commit_sha=protected_commit_sha
        )
        complete = _complete_checkpoint_payload(terminal)
        _write_exact_canonical_checkpoint(complete_path, complete)
        observed = _read_canonical_document(
            complete_path, "CATALOG_BOOTSTRAP_REQUESTER_COMPLETE_CHECKPOINT_INVALID"
        )
        _validate_complete_checkpoint(observed)
        return cast(dict[str, object], observed["requester_qualification"])

    status_before = _load_requester_status()
    seal_path = BROKER_ROOT / "config/bootstrap-qualified-v1.seal.json"
    seal_exists = seal_path.exists() or seal_path.is_symlink()
    if status_before is None or status_before.get("state") == "ticket_available":
        _wait_for_requester_ticket()
    first: dict[str, object]
    if seal_exists:
        if status_before is None:
            raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STATUS_INVALID")
        status = _wait_for_terminal_requester_status(status_before)
        local = _load_local_requester_receipt(status)
        if local is None:
            recovered = _invoke_bootstrap_request(source)
            local = _ensure_local_requester_receipt(status, recovered)
        first, first_file_sha256 = local
    else:
        first = _invoke_bootstrap_request(source)
        status = _wait_for_terminal_requester_status(_load_requester_status())
        if first.get("status") not in {"submitted", "existing"}:
            local = _load_local_requester_receipt(status)
            if local is None:
                raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_MISSING")
            first, first_file_sha256 = local
        else:
            _validate_requester_receipt(first)
            first_file_sha256 = hashlib.sha256(
                (_canonical(first) + b"\n")
            ).hexdigest()

    _validate_requester_receipt(first)
    if (
        status.get("state") != "terminal"
        or first.get("request_id") != status.get("request_id")
        or first.get("issue_number") != status.get("issue_number")
        or first.get("request_sha256") != status.get("request_sha256")
        or first.get("submission_key_sha256") != status.get("submission_key_sha256")
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_NOT_TERMINAL")
    first, first_file_sha256 = _ensure_local_requester_receipt(status, first)
    requester = _load_requester_public_binding(root)
    _, identity, issue_sha256 = _load_remote_requester_issue(
        _as_int(status["issue_number"]), status=status, requester=requester
    )
    controller = _parse_terminal_controller_receipt(_as_int(status["issue_number"]))
    _validate_controller_receipt(
        controller,
        issue_number=_as_int(status["issue_number"]),
        request_sha256=str(status["request_sha256"]),
    )
    seal = _load_or_create_bootstrap_seal(
        status=status,
        controller=controller,
        protected_commit_sha=protected_commit_sha,
    )

    second = _invoke_bootstrap_request(source)
    _validate_requester_receipt(second)
    _validate_requester_identity(
        status,
        second,
        error_code="CATALOG_BOOTSTRAP_REQUESTER_EVIDENCE_IDENTITY_MISMATCH",
    )
    if _canonical(second) != _canonical(first):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_REPLAY_INVALID")
    duplicate_call_proof_sha256 = hashlib.sha256(
        _canonical({"first": first, "second": second})
    ).hexdigest()
    if not _SHA256.fullmatch(duplicate_call_proof_sha256):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_REPLAY_INVALID")
    terminal = _terminal_checkpoint_payload(
        protected_commit_sha=protected_commit_sha,
        status=status,
        receipt=first,
        receipt_file_sha256=first_file_sha256,
        identity=identity,
        issue_sha256=issue_sha256,
        controller=controller,
        seal=seal,
        duplicate_call_proof_sha256=duplicate_call_proof_sha256,
    )
    _write_exact_canonical_checkpoint(terminal_path, terminal)
    observed_terminal = _read_canonical_document(
        terminal_path, "CATALOG_BOOTSTRAP_REQUESTER_TERMINAL_CHECKPOINT_INVALID"
    )
    _validate_terminal_checkpoint(observed_terminal)
    complete = _complete_checkpoint_payload(observed_terminal)
    _write_exact_canonical_checkpoint(complete_path, complete)
    observed_complete = _read_canonical_document(
        complete_path, "CATALOG_BOOTSTRAP_REQUESTER_COMPLETE_CHECKPOINT_INVALID"
    )
    _validate_complete_checkpoint(observed_complete)
    return cast(dict[str, object], observed_complete["requester_qualification"])


def _qualification_checkpoint_path(root: Path) -> Path:
    return root / QUALIFICATION_CHECKPOINT_FILENAME


def _qualification_file_sha256(path: Path, error_code: str) -> str:
    _read_canonical_document(path, error_code)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_live_qualification_result(
    value: dict[str, object],
    *,
    protected_commit_sha: str,
) -> None:
    receipt = value.get("receipt")
    run_id = value.get("run_id")
    if (
        set(value) != {"run_id", "run_url", "file_sha256", "receipt"}
        or isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id < 1
        or not _SHA256.fullmatch(str(value.get("file_sha256", "")))
        or not isinstance(receipt, dict)
        or set(receipt)
        != {
            "schema_version",
            "observer_context",
            "protected_commit_sha",
            "admission_receipt_sha256",
            "terminal_receipt_sha256",
            "receipt_sha256",
        }
        or receipt.get("schema_version") != "1"
        or receipt.get("observer_context") != "live_qualification"
        or receipt.get("protected_commit_sha") != protected_commit_sha
        or any(
            not _SHA256.fullmatch(str(receipt.get(name, "")))
            for name in (
                "admission_receipt_sha256",
                "terminal_receipt_sha256",
                "receipt_sha256",
            )
        )
        or hashlib.sha256(
            _canonical(
                {
                    key: item
                    for key, item in receipt.items()
                    if key != "receipt_sha256"
                }
            )
        ).hexdigest()
        != receipt["receipt_sha256"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LIVE_RECEIPT_INVALID")
    if hashlib.sha256(_canonical(receipt) + b"\n").hexdigest() != value["file_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_LIVE_RECEIPT_INVALID")


def _validate_workflow_run_result(
    value: dict[str, object],
    *,
    protected_commit_sha: str,
) -> None:
    expected = {"databaseId", "headSha", "event", "status", "conclusion", "url"}
    database_id = value.get("databaseId")
    if (
        set(value) != expected
        or isinstance(database_id, bool)
        or not isinstance(database_id, int)
        or database_id < 1
        or value.get("headSha") != protected_commit_sha
        or value.get("event") != "workflow_dispatch"
        or value.get("status") != "completed"
        or value.get("conclusion") != "success"
        or not isinstance(value.get("url"), str)
        or not value["url"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RUN_INVALID")


def _validate_requester_qualification_result(value: dict[str, object]) -> None:
    expected = {
        "issue_number",
        "submission_key_sha256",
        "request_sha256",
        "request_id",
        "launch_ticket_sha256",
        "status_sha256",
        "requester_receipt_sha256",
        "requester_receipt_file_sha256",
        "issue_identity_sha256",
        "issue_sha256",
        "controller_receipt_sha256",
        "bootstrap_seal_sha256",
        "duplicate_call_proof_sha256",
    }
    issue_number = value.get("issue_number")
    if (
        set(value) != expected
        or isinstance(issue_number, bool)
        or not isinstance(issue_number, int)
        or issue_number < 1
        or not isinstance(value.get("request_id"), str)
        or any(
            not _SHA256.fullmatch(str(value.get(name, "")))
            for name in expected
            if name != "issue_number" and name != "request_id"
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_QUALIFICATION_INVALID")


def _validate_qualification_step_entry(
    entry: dict[str, object],
    *,
    protected_commit_sha: str,
) -> None:
    if set(entry) != {"name", "receipt", "receipt_sha256"}:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")
    name = entry.get("name")
    receipt = entry.get("receipt")
    if (
        not isinstance(name, str)
        or name not in _QUALIFICATION_STEP_ORDER
        or not isinstance(receipt, dict)
        or not _SHA256.fullmatch(str(entry.get("receipt_sha256", "")))
        or hashlib.sha256(_canonical(receipt)).hexdigest()
        != entry["receipt_sha256"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")
    if name == "requester":
        _validate_requester_qualification_result(receipt)
    elif name in {"live_2", "live_3"}:
        _validate_live_qualification_result(
            receipt, protected_commit_sha=protected_commit_sha
        )
    else:
        _validate_workflow_run_result(receipt, protected_commit_sha=protected_commit_sha)


def _qualification_checkpoint_hash(value: dict[str, object]) -> str:
    return _seal_hash(value, "checkpoint_sha256")


def _validate_qualification_checkpoint(
    value: dict[str, object],
    *,
    protected_commit_sha: str,
    github_controls_operation_sha256: str,
    activity_baseline_sha256: str,
) -> None:
    expected = {
        "schema_version",
        "protected_commit_sha",
        "github_controls_operation_sha256",
        "activity_baseline_sha256",
        "step_order",
        "steps",
        "checkpoint_sha256",
    }
    steps = value.get("steps")
    if (
        set(value) != expected
        or value.get("schema_version") != "1"
        or value.get("protected_commit_sha") != protected_commit_sha
        or value.get("github_controls_operation_sha256")
        != github_controls_operation_sha256
        or value.get("activity_baseline_sha256") != activity_baseline_sha256
        or value.get("step_order") != list(_QUALIFICATION_STEP_ORDER)
        or not isinstance(steps, list)
        or len(steps) > len(_QUALIFICATION_STEP_ORDER)
        or not _SHA256.fullmatch(str(value.get("checkpoint_sha256", "")))
        or _qualification_checkpoint_hash(value) != value["checkpoint_sha256"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")
    names: list[str] = []
    for entry in steps:
        if not isinstance(entry, dict):
            raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")
        _validate_qualification_step_entry(
            entry, protected_commit_sha=protected_commit_sha
        )
        names.append(str(entry["name"]))
    if names != list(_QUALIFICATION_STEP_ORDER[: len(names)]):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")


def _load_qualification_checkpoint(
    root: Path,
    *,
    protected_commit_sha: str,
    github_controls_operation_sha256: str,
    activity_baseline_sha256: str,
) -> dict[str, object] | None:
    path = _qualification_checkpoint_path(root)
    if not path.exists() and not path.is_symlink():
        return None
    value = _read_canonical_document(
        path, "CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID"
    )
    _validate_qualification_checkpoint(
        value,
        protected_commit_sha=protected_commit_sha,
        github_controls_operation_sha256=github_controls_operation_sha256,
        activity_baseline_sha256=activity_baseline_sha256,
    )
    return value


def _new_qualification_checkpoint(
    *,
    protected_commit_sha: str,
    github_controls_operation_sha256: str,
    activity_baseline_sha256: str,
    steps: list[dict[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1",
        "protected_commit_sha": protected_commit_sha,
        "github_controls_operation_sha256": github_controls_operation_sha256,
        "activity_baseline_sha256": activity_baseline_sha256,
        "step_order": list(_QUALIFICATION_STEP_ORDER),
        "steps": steps,
        "checkpoint_sha256": "0" * 64,
    }
    value["checkpoint_sha256"] = _qualification_checkpoint_hash(value)
    return value


def _write_qualification_checkpoint_revision(
    path: Path,
    value: dict[str, object],
    previous: dict[str, object] | None,
) -> str:
    data = _canonical(value) + b"\n"
    if previous is None:
        return _write_exact_canonical_checkpoint(path, value)
    previous_data = _canonical(previous) + b"\n"
    with _exclusive_checkpoint_lock(path):
        _cleanup_checkpoint_temps(path)
        _validate_exact_file_path(path, "CATALOG_BOOTSTRAP_CHECKPOINT_PATH_INVALID")
        try:
            if path.read_bytes() != previous_data:
                raise ValueError(
                    "CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_CONFLICT"
                )
        except OSError as exc:
            raise ValueError(
                "CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID"
            ) from exc
        return _write_checkpoint_bytes_locked(path, data, replace_existing=True)


def _append_qualification_checkpoint_step(
    root: Path,
    checkpoint: dict[str, object] | None,
    *,
    step_name: str,
    receipt: dict[str, object],
    protected_commit_sha: str,
    github_controls_operation_sha256: str,
    activity_baseline_sha256: str,
) -> dict[str, object]:
    current_steps: list[dict[str, object]] = (
        []
        if checkpoint is None
        else list(cast(list[dict[str, object]], checkpoint["steps"]))
    )
    if current_steps and current_steps[-1]["name"] == step_name:
        if current_steps[-1]["receipt"] != receipt:
            raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_CONFLICT")
        return checkpoint if checkpoint is not None else {}
    if len(current_steps) != _QUALIFICATION_STEP_ORDER.index(step_name):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_ORDER_INVALID")
    entry: dict[str, object] = {
        "name": step_name,
        "receipt": receipt,
        "receipt_sha256": hashlib.sha256(_canonical(receipt)).hexdigest(),
    }
    updated = _new_qualification_checkpoint(
        protected_commit_sha=protected_commit_sha,
        github_controls_operation_sha256=github_controls_operation_sha256,
        activity_baseline_sha256=activity_baseline_sha256,
        steps=[*current_steps, entry],
    )
    _write_qualification_checkpoint_revision(
        _qualification_checkpoint_path(root), updated, checkpoint
    )
    observed = _read_canonical_document(
        _qualification_checkpoint_path(root),
        "CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID",
    )
    _validate_qualification_checkpoint(
        observed,
        protected_commit_sha=protected_commit_sha,
        github_controls_operation_sha256=github_controls_operation_sha256,
        activity_baseline_sha256=activity_baseline_sha256,
    )
    return observed


def _read_stored_workflow_run(
    workflow: str,
    stored: dict[str, object],
    *,
    protected_commit_sha: str,
) -> dict[str, object]:
    _validate_workflow_run_result(stored, protected_commit_sha=protected_commit_sha)
    run_id = _as_int(stored["databaseId"])
    observed = _read_workflow_run_by_id(
        workflow,
        run_id,
        protected_commit_sha=protected_commit_sha,
    )
    if observed != stored:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RUN_CHANGED")
    return observed


def _revalidate_qualification_step(
    root: Path,
    entry: dict[str, object],
    *,
    protected_commit_sha: str,
) -> dict[str, object]:
    name = str(entry["name"])
    receipt = entry["receipt"]
    if name == "requester":
        context = _context(root)
        result = _run_requester_qualification(
            root,
            Path(str(context["source_root"])),
            protected_commit_sha,
        )
        if result != receipt:
            raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_QUALIFICATION_CHANGED")
        return result
    if name in {"live_2", "live_3"}:
        if not isinstance(receipt, dict):
            raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")
        stored_run = {
            "databaseId": receipt["run_id"],
            "headSha": protected_commit_sha,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "url": receipt.get("run_url"),
        }
        observed_run = _read_stored_workflow_run(
            _QUALIFICATION_STEP_WORKFLOWS[name],
            stored_run,
            protected_commit_sha=protected_commit_sha,
        )
        downloaded = _download_live_qualification(
            root,
            observed_run,
            protected_commit_sha,
        )
        if downloaded != receipt:
            raise ValueError("CATALOG_BOOTSTRAP_LIVE_RECEIPT_CHANGED")
        return downloaded
    if not isinstance(receipt, dict):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")
    return _read_stored_workflow_run(
        _QUALIFICATION_STEP_WORKFLOWS[name],
        receipt,
        protected_commit_sha=protected_commit_sha,
    )


def run_qualifications(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    protected_commit_sha = _runtime_commit(root)
    if not _COMMIT.fullmatch(protected_commit_sha):
        raise ValueError("CATALOG_BOOTSTRAP_PROTECTED_COMMIT_INVALID")
    controls_path = root / "github-controls-operation-v1.json"
    baseline_path = root / "github-activity-baseline-v1.json"
    controls = _read_canonical_document(
        controls_path, "CATALOG_BOOTSTRAP_QUALIFICATION_CONTEXT_INVALID"
    )
    baseline = _read_canonical_document(
        baseline_path, "CATALOG_BOOTSTRAP_QUALIFICATION_CONTEXT_INVALID"
    )
    first_live_qualification = controls.get("first_live_qualification")
    if (
        controls.get("protected_commit_sha") != protected_commit_sha
        or not isinstance(first_live_qualification, dict)
        or not isinstance(baseline.get("request_issue_numbers"), list)
        or not isinstance(baseline.get("heavy_run_ids"), list)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CONTEXT_INVALID")
    _validate_live_qualification_result(
        first_live_qualification,
        protected_commit_sha=protected_commit_sha,
    )
    controls_hash = hashlib.sha256(controls_path.read_bytes()).hexdigest()
    baseline_hash = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    checkpoint = _load_qualification_checkpoint(
        root,
        protected_commit_sha=protected_commit_sha,
        github_controls_operation_sha256=controls_hash,
        activity_baseline_sha256=baseline_hash,
    )
    checkpoint_steps: list[object] = []
    if checkpoint is not None:
        checkpoint_steps = cast(list[object], checkpoint["steps"])
        for entry in checkpoint_steps:
            if not isinstance(entry, dict):
                raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")
            _revalidate_qualification_step(
                root,
                entry,
                protected_commit_sha=protected_commit_sha,
            )

    steps_by_name: dict[str, dict[str, object]] = {
        str(entry["name"]): entry
        for entry in checkpoint_steps
        if isinstance(entry, dict)
    }
    for step_name in _QUALIFICATION_STEP_ORDER:
        if step_name in steps_by_name:
            continue
        if step_name in {"live_2", "live_3"}:
            receipt = _run_live_qualification(
                root,
                protected_commit_sha,
                step_name=step_name,
            )
        elif step_name == "requester":
            receipt = _run_requester_qualification(
                root, source, protected_commit_sha
            )
        else:
            receipt = _run_qualification_workflow_step(
                root,
                step_name,
                protected_commit_sha,
            )
        if not isinstance(receipt, dict):
            raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RECEIPT_INVALID")
        if step_name in {"live_2", "live_3"}:
            _validate_live_qualification_result(
                receipt, protected_commit_sha=protected_commit_sha
            )
        elif step_name != "requester":
            _validate_workflow_run_result(
                receipt, protected_commit_sha=protected_commit_sha
            )
        checkpoint = _append_qualification_checkpoint_step(
            root,
            checkpoint,
            step_name=step_name,
            receipt=receipt,
            protected_commit_sha=protected_commit_sha,
            github_controls_operation_sha256=controls_hash,
            activity_baseline_sha256=baseline_hash,
        )
        steps_by_name[step_name] = cast(
            dict[str, object],
            cast(list[object], checkpoint["steps"])[-1],
        )

    if checkpoint is None:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID")
    _validate_qualification_checkpoint(
        checkpoint,
        protected_commit_sha=protected_commit_sha,
        github_controls_operation_sha256=controls_hash,
        activity_baseline_sha256=baseline_hash,
    )
    live_receipts: list[dict[str, object]] = [
        cast(dict[str, object], first_live_qualification),
        cast(dict[str, object], steps_by_name["live_2"]["receipt"]),
        cast(dict[str, object], steps_by_name["live_3"]["receipt"]),
    ]
    file_hashes = [str(item["file_sha256"]) for item in live_receipts]
    if len(set(file_hashes)) != 3 or any(
        not _SHA256.fullmatch(value) for value in file_hashes
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATIONS_NOT_INDEPENDENT")
    requester_value = steps_by_name["requester"]["receipt"]
    capacity_value = steps_by_name["capacity"]["receipt"]
    keeper_value = steps_by_name["keeper"]["receipt"]
    requester = cast(dict[str, object], requester_value)
    capacity = cast(dict[str, object], capacity_value)
    keeper = cast(dict[str, object], keeper_value)
    if (
        not isinstance(requester_value, dict)
        or not isinstance(capacity_value, dict)
        or not isinstance(keeper_value, dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_RECEIPT_INVALID")
    current = _github_activity_snapshot()
    baseline_requests = set(cast(list[int], baseline["request_issue_numbers"]))
    current_requests = set(cast(list[int], current["request_issue_numbers"]))
    baseline_heavy = set(cast(list[int], baseline["heavy_run_ids"]))
    current_heavy = set(cast(list[int], current["heavy_run_ids"]))
    if current_requests - baseline_requests != {requester["issue_number"]}:
        raise ValueError("CATALOG_BOOTSTRAP_PRODUCTION_REQUEST_OBSERVED")
    if current_heavy - baseline_heavy:
        raise ValueError("CATALOG_BOOTSTRAP_PRODUCTION_RUN_OBSERVED")
    receipt = {
        "protected_commit_sha": protected_commit_sha,
        "live_qualifications": live_receipts,
        "qualification_receipt_sha256s": file_hashes,
        "capacity_run_id": capacity["databaseId"],
        "keeper_run_id": keeper["databaseId"],
        "requester_qualification": requester,
        "qualification_checkpoint_sha256": hashlib.sha256(
            _qualification_checkpoint_path(root).read_bytes()
        ).hexdigest(),
        "qualification_step_receipt_sha256s": {
            name: steps_by_name[name]["receipt_sha256"]
            for name in _QUALIFICATION_STEP_ORDER
        },
        "production_request_count": 0,
        "production_run_count": 0,
    }
    _write_exact_canonical_checkpoint(root / "qualification-operation-v1.json", receipt)
    _advance(root, state, "qualification_passed", receipt)


def _codex_process_owners() -> list[dict[str, object]]:
    command = (
        "$r=@(); Get-CimInstance Win32_Process | Where-Object {$_.Name -in "
        "@('ChatGPT.exe','codex.exe')} | ForEach-Object {$o=Invoke-CimMethod "
        "-InputObject $_ -MethodName GetOwner; $r += [ordered]@{pid=$_.ProcessId;"
        "name=$_.Name;user=$o.User}}; $r | ConvertTo-Json -Compress"
    )
    raw = _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]
    )
    if not raw:
        return []
    value = json.loads(raw)
    rows = value if isinstance(value, list) else [value]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("CATALOG_BOOTSTRAP_PROCESS_AUDIT_INVALID")
    return rows


def launch_isolated_codex(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    source = Path(str(_context(root)["source_root"]))
    _stop_hp_codex_processes()
    _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/launch_catalog_codex_secure.ps1"),
        ],
        cwd=source,
        timeout_seconds=180,
    )
    deadline = time.monotonic() + 120
    owners: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        owners = _codex_process_owners()
        if owners and all(row.get("user") == "AURORAAgent" for row in owners):
            break
        time.sleep(3)
    if not owners or any(row.get("user") != "AURORAAgent" for row in owners):
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_RESTART_INVALID")
    capability_raw = _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/audit_catalog_agent_capabilities.ps1"),
        ],
        cwd=source,
        timeout_seconds=180,
    )
    capability = json.loads(capability_raw.splitlines()[-1])
    if not isinstance(capability, dict) or capability.get("identity") != "AURORAAgent":
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_CAPABILITY_INVALID")
    installed_profile = AGENT_ROOT / "profile/config.toml"
    source_profile = source / "config/catalog_agent_codex_profile_v1.toml"
    profile_bytes = installed_profile.read_bytes()
    normalized_profile = profile_bytes.replace(b"\r\n", b"\n")
    if profile_bytes != source_profile.read_bytes() or any(
        marker not in normalized_profile
        for marker in (
            b'[plugins."browser@openai-bundled"]\nenabled = false',
            b'[plugins."chrome@openai-bundled"]\nenabled = false',
            b'[plugins."computer-use@openai-bundled"]\nenabled = false',
            b'[plugins."codex-app-tools@openai-bundled"]\nenabled = false',
            b'sandbox = "unelevated"',
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_PROFILE_INVALID")
    receipt = {
        "processes": owners,
        "agent_process_owner": "AURORAAgent",
        "capability_audit": capability,
        "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "browser_connectors_disabled": True,
    }
    _write_canonical(root / "agent-restart-operation-v1.json", receipt)
    _advance(root, state, "agent_restart_verified", receipt)


def _application_sha256(kind: str) -> str:
    manifest = _read_json(BROKER_ROOT / f"bin/catalog-requester-{kind}.manifest.json")
    value = str(manifest.get("application_sha256", ""))
    if not _SHA256.fullmatch(value):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_MANIFEST_INVALID")
    return value


def _production_seal(
    protected_commit_sha: str,
    ready_receipt_bytes: bytes,
) -> CatalogBootstrapObservedProductionSealV1:
    from infra.sp500_megarun.catalog_bootstrap_finalizer import (
        CatalogBootstrapObservedProductionSealV1,
    )

    payload: dict[str, object] = {
        "schema_version": "1",
        "production_enabled": True,
        "protected_commit_sha": protected_commit_sha,
        "bootstrap_receipt_sha256": hashlib.sha256(ready_receipt_bytes).hexdigest(),
        "requester_client_application_sha256": _application_sha256("client"),
        "requester_broker_application_sha256": _application_sha256("broker"),
        "sealed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "production_seal_sha256": "0" * 64,
    }
    payload["production_seal_sha256"] = _seal_hash(
        payload, "production_seal_sha256"
    )
    return CatalogBootstrapObservedProductionSealV1.model_validate(payload)


def perform_final_audit(root: Path) -> None:
    from infra.sp500_megarun.catalog_bootstrap_finalizer import (
        CatalogBootstrapFinalEvidenceV1,
        canonical_ready_receipt_bytes,
        complete_sealed_bootstrap,
        finalize_bootstrap,
    )

    state = load_bootstrap_state(_state_path(root))
    protected_commit_sha = _runtime_commit(root)
    qualification = _read_json(root / "qualification-operation-v1.json")
    applied_controls = _read_json(root / "receipts/github-controls-apply-v1.json")
    after_controls = applied_controls.get("after_receipt")
    if not isinstance(after_controls, dict):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RECEIPT_INVALID")
    zero_budgets = after_controls.get("actions_zero_spend_budgets")
    if not isinstance(zero_budgets, list) or len(zero_budgets) != 3:
        raise ValueError("CATALOG_BOOTSTRAP_ZERO_BUDGETS_INVALID")
    hashes: tuple[str, ...] = tuple(
        cast(list[str], qualification["qualification_receipt_sha256s"])
    )
    owners = _codex_process_owners()
    agent_operation = _read_json(root / "agent-restart-operation-v1.json")
    capability = agent_operation.get("capability_audit")
    if not isinstance(capability, dict) or any(
        capability.get(name) is not True
        for name in (
            "medium_or_lower_integrity",
            "requester_key_read_denied",
            "broker_code_read_denied",
            "processing_list_denied",
            "agent_credential_read_denied",
            "broker_write_denied",
            "elevated_helper_write_denied",
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_CAPABILITY_INVALID")
    if not owners or any(row.get("user") != "AURORAAgent" for row in owners):
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_PROCESS_OWNER_INVALID")
    try:
        _set_repository_variable(ARMED_VARIABLE, "false")
        pre_enable = _run_live_qualification(
            root, protected_commit_sha, step_name="final_pre_enable_live"
        )
        _set_repository_variable(CONTROLLER_VARIABLE, "true")
        post_enable = _run_live_qualification(
            root, protected_commit_sha, step_name="final_post_enable_live"
        )
        baseline = _read_json(root / "github-activity-baseline-v1.json")
        current = _github_activity_snapshot()
        requester = cast(
            dict[str, object], qualification["requester_qualification"]
        )
        production_requests = set(
            cast(list[int], current["request_issue_numbers"])
        ) - set(cast(list[int], baseline["request_issue_numbers"])) - {
            _as_int(requester["issue_number"])
        }
        production_runs = set(cast(list[int], current["heavy_run_ids"])) - set(
            cast(list[int], baseline["heavy_run_ids"])
        )
        post_enable_receipt = cast(dict[str, object], post_enable["receipt"])
        evidence = CatalogBootstrapFinalEvidenceV1(
            schema_version="1",
            repository=REPOSITORY,
            protected_commit_sha=protected_commit_sha,
            public_binding_sha256=hashlib.sha256(
                (root / "public-binding-operation-v1.json").read_bytes()
            ).hexdigest(),
            merged_binding_verified=True,
            requester_installation_verified=True,
            auditor_installation_verified=True,
            requester_key_isolated=not (root / "secrets/requester-pending.pem").exists(),
            auditor_key_github_only=not (root / "secrets/auditor-pending.pem").exists(),
            local_identities_and_acls_verified=(
                (BROKER_ROOT / "config/acl-baseline-v1.json").is_file()
                and (BROKER_ROOT / "receipts/broker-self-audit-v1.receipt.json").is_file()
                and capability.get("is_admin") is False
                and capability.get("enabled_dangerous_privileges") == 0
                and capability.get("forbidden_environment_count") == 0
            ),
            agent_process_owner="AURORAAgent",
            hp_codex_process_count=sum(row.get("user") == "HP" for row in owners),
            github_controls_status="ready",
            zero_budget_count=len(zero_budgets),
            qualification_receipt_sha256s=hashes,
            qualification_equivalent=True,
            disabled_bootstrap_request_count=1,
            production_request_count=len(production_requests),
            production_run_count=len(production_runs),
            controller_enabled_readback=(
                _run(
                    [
                        "gh",
                        "variable",
                        "get",
                        CONTROLLER_VARIABLE,
                        "--repo",
                        REPOSITORY,
                    ]
                )
                == "true"
            ),
            post_enable_controls_status=(
                "ready"
                if post_enable_receipt["protected_commit_sha"]
                == protected_commit_sha
                else "blocked"
            ),
        )
        ready = finalize_bootstrap(evidence)
        ready_bytes = canonical_ready_receipt_bytes(ready)
        ready_path = BROKER_ROOT / "receipts/controller-bootstrap-v1.receipt.json"
        _write_canonical(ready_path, ready.model_dump(mode="json"))
        if ready_path.read_bytes() != ready_bytes:
            raise ValueError("CATALOG_BOOTSTRAP_READY_RECEIPT_READBACK_INVALID")
        seal = _production_seal(protected_commit_sha, ready_bytes)
        seal_path = BROKER_ROOT / "config/production-enabled-v1.seal.json"
        _write_canonical(seal_path, seal.model_dump(mode="json"))
        completion = complete_sealed_bootstrap(ready, seal)
        _write_canonical(
            root / "receipts/controller-bootstrap-completion-v1.receipt.json",
            completion.model_dump(mode="json"),
        )
        deadline = time.monotonic() + 300
        registry = _read_json(BROKER_ROOT / "config/catalog_campaign_registry_v1.json")
        campaigns = cast(list[object], registry.get("campaigns", []))
        active = {
            row["campaign_key"]
            for row in campaigns
            if isinstance(row, dict) and row.get("active") is True
        }
        while time.monotonic() < deadline:
            tickets = {
                path.name.removesuffix(".ticket.json")
                for path in (BROKER_ROOT / "launch-tickets").glob("*.ticket.json")
            }
            if tickets == active:
                break
            time.sleep(2)
        if tickets != active:
            raise ValueError("CATALOG_BOOTSTRAP_PRODUCTION_TICKETS_INVALID")
        self_audit_path = BROKER_ROOT / "receipts/broker-self-audit-v1.receipt.json"
        deadline = time.monotonic() + 120
        self_audit: dict[str, object] = {}
        while time.monotonic() < deadline:
            self_audit = _read_json(self_audit_path)
            if self_audit.get("status") == "production_sealed":
                break
            time.sleep(2)
        if (
            self_audit.get("status") != "production_sealed"
            or self_audit.get("production_seal_present") is not True
            or self_audit.get("broker_application_sha256")
            != seal.requester_broker_application_sha256
        ):
            raise ValueError("CATALOG_BOOTSTRAP_BROKER_FINAL_AUDIT_INVALID")
        _set_repository_variable(ARMED_VARIABLE, "true")
        if not _controller_is_ready():
            raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_NOT_READY")
        final_activity = _github_activity_snapshot()
        final_production_requests = set(
            cast(list[int], final_activity["request_issue_numbers"])
        ) - set(cast(list[int], baseline["request_issue_numbers"])) - {
            _as_int(requester["issue_number"])
        }
        final_production_runs = set(
            cast(list[int], final_activity["heavy_run_ids"])
        ) - set(cast(list[int], baseline["heavy_run_ids"]))
        final_owners = _codex_process_owners()
        if (
            final_production_requests
            or final_production_runs
            or not final_owners
            or any(row.get("user") != "AURORAAgent" for row in final_owners)
            or not _controller_is_ready()
        ):
            raise ValueError("CATALOG_BOOTSTRAP_POST_ENABLE_DRIFT")
        final = {
            "ready_receipt_sha256": hashlib.sha256(ready_bytes).hexdigest(),
            "completion_receipt_sha256": completion.completion_receipt_sha256,
            "production_seal_sha256": seal.production_seal_sha256,
            "pre_enable_live_run_id": pre_enable["run_id"],
            "post_enable_live_run_id": post_enable["run_id"],
            "production_ticket_campaign_keys": sorted(tickets),
            "broker_self_audit_sha256": self_audit.get("self_audit_sha256"),
            "controller_enabled_readback": True,
            "controller_armed_readback": True,
        }
        _write_canonical(root / "final-audit-operation-v1.json", final)
        _advance(root, state, "final_audit_passed", final)
    except Exception:
        _disable_controller()
        raise


PHASE_HANDLERS: dict[str, Callable[[Path], None]] = {
    "PRECHECK": perform_precheck,
    "REQUESTER_CREATE_PENDING": create_requester,
    "REQUESTER_INSTALL_PENDING": verify_requester_installation,
    "AUDITOR_CREATE_PENDING": create_auditor,
    "AUDITOR_INSTALL_PENDING": verify_auditor_installation,
    "PUBLIC_BINDING_PENDING": apply_public_binding,
    "MERGE_PENDING": merge_public_binding,
    "LOCAL_INSTALL_PENDING": install_local_components,
    "GITHUB_CONTROLS_PENDING": apply_github_controls,
    "QUALIFICATION_PENDING": run_qualifications,
    "AGENT_RESTART_PENDING": launch_isolated_codex,
    "FINAL_AUDIT_PENDING": perform_final_audit,
}


def run_phase(phase: str, installed_root: Path) -> None:
    try:
        handler = PHASE_HANDLERS[phase]
    except KeyError as exc:
        raise ValueError("CATALOG_BOOTSTRAP_PHASE_INVALID") from exc
    handler(installed_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed-root", type=Path, required=True)
    args = parser.parse_args()
    state_file = _state_path(args.installed_root)
    if not state_file.exists():
        perform_precheck(args.installed_root)
    state = load_bootstrap_state(state_file)
    while True:
        state = load_bootstrap_state(state_file)
        if state.phase == "READY":
            return 0
        if state.phase == "BLOCKED":
            try:
                recovered = _resume_transient_merge_block(args.installed_root)
                if not recovered:
                    recovered = _resume_transient_local_install_block(
                        args.installed_root
                    )
                if not recovered:
                    recovered = _resume_transient_github_controls_block(
                        args.installed_root
                    )
                if not recovered:
                    return 2
            except Exception as exc:
                if not _disable_controller_for_failure_receipt(
                    args.installed_root,
                    phase="BLOCKED",
                ):
                    return 3
                reason = _safe_blocked_reason(
                    exc, "CATALOG_BOOTSTRAP_RECOVERY_FAILED"
                )
                recovery_phase = "BLOCKED"
                blocked_path = (
                    args.installed_root
                    / "receipts/controller-bootstrap-blocked-v1.json"
                )
                try:
                    blocked_receipt = _read_json(blocked_path)
                    if blocked_path.read_bytes() != _canonical(blocked_receipt) + b"\n":
                        raise ValueError("CATALOG_BOOTSTRAP_RECOVERY_RECEIPT_INVALID")
                    observed_phase = blocked_receipt.get("phase")
                    if observed_phase in {"MERGE_PENDING", "LOCAL_INSTALL_PENDING"}:
                        recovery_phase = observed_phase
                except (OSError, TypeError, ValueError):
                    pass
                _write_canonical(
                    args.installed_root
                    / "receipts/controller-bootstrap-recovery-blocked-v1.json",
                    {
                        "controller_enabled_readback": False,
                        "phase": recovery_phase,
                        "reason_code": reason,
                        "result": "BLOCKED",
                        "schema_version": "1",
                    },
                )
                return 2
            continue
        if state.phase == "QUALIFICATION_PENDING":
            try:
                _refresh_interrupted_runtime_controls(args.installed_root)
            except Exception as exc:
                if not _disable_controller_for_failure_receipt(
                    args.installed_root,
                    phase=state.phase,
                ):
                    return 3
                _write_canonical(
                    args.installed_root
                    / "receipts/controller-bootstrap-runtime-upgrade-refresh-blocked-v1.json",
                    {
                        "controller_enabled_readback": False,
                        "phase": state.phase,
                        "reason_code": _safe_blocked_reason(
                            exc,
                            "CATALOG_BOOTSTRAP_RUNTIME_UPGRADE_REFRESH_FAILED",
                        ),
                        "result": "BLOCKED",
                        "schema_version": "1",
                        "state_preserved_for_retry": True,
                    },
                )
                return 2
        try:
            run_phase(state.phase, args.installed_root)
        except Exception as exc:
            if not _disable_controller_for_failure_receipt(
                args.installed_root,
                phase=state.phase,
            ):
                return 3
            reason = _safe_blocked_reason(exc, "CATALOG_BOOTSTRAP_PHASE_FAILED")
            blocked = {
                "schema_version": "1",
                "result": "BLOCKED",
                "phase": state.phase,
                "reason_code": reason,
                "controller_enabled_readback": False,
            }
            _write_canonical(
                args.installed_root / "receipts/controller-bootstrap-blocked-v1.json",
                blocked,
            )
            _advance(args.installed_root, state, "blocked", blocked)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
