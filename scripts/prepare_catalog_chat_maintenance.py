"""Stage a reproducible public maintenance payload; never install or arm production."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Literal

from aurora.infra.sp500_megarun.catalog_requester import verify_installed_requester_application
from aurora.infra.sp500_megarun.catalog_bootstrap_finalizer import (
    CatalogBootstrapFinalReceiptV1, CatalogBootstrapObservedProductionSealV1,
    CatalogRequesterMaintenanceReceiptV1, canonical_ready_receipt_bytes,
    complete_requester_maintenance,
)
from scripts import build_catalog_requester_apps as builder

_SENDER_SOURCE = "scripts/submit_catalog_chat_intent.py"
_KINDS: tuple[Literal["client", "broker"], ...] = ("client", "broker")
_READY = "receipts/controller-bootstrap-v1.receipt.json"
_SEAL = "config/production-enabled-v1.seal.json"
_MAINTENANCE = "receipts/requester-maintenance-v1.receipt.json"


@dataclass(frozen=True)
class _Baseline:
    ready: CatalogBootstrapFinalReceiptV1
    seal: CatalogBootstrapObservedProductionSealV1
    previous: CatalogRequesterMaintenanceReceiptV1 | None
    ready_bytes: bytes
    file_hashes: dict[str, str]


def _baseline_bytes(root: Path, relative: str, expected: str) -> bytes:
    path = root.absolute() / relative
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("CHAT_MAINTENANCE_BASELINE_UNSAFE")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("CHAT_MAINTENANCE_BASELINE_UNSAFE")
    with path.open("rb") as stream:
        data = stream.read(1048577)
    if len(data) > 1048576 or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("CHAT_MAINTENANCE_BASELINE_HASH_MISMATCH")
    return data


def _read_baseline(root: Path, ready_hash: str, seal_hash: str, previous_hash: str | None) -> _Baseline:
    # Pins must come from authenticated maintenance observations, not from these
    # files themselves. This staging command still grants NO installation authority.
    ready_bytes = _baseline_bytes(root, _READY, ready_hash)
    ready = CatalogBootstrapFinalReceiptV1.model_validate_json(ready_bytes)
    seal_bytes = _baseline_bytes(root, _SEAL, seal_hash)
    seal = CatalogBootstrapObservedProductionSealV1.model_validate_json(seal_bytes)
    if ready_bytes != canonical_ready_receipt_bytes(ready) or seal_bytes != builder._canonical(seal.model_dump(mode="json")) + b"\n":
        raise ValueError("CHAT_MAINTENANCE_BASELINE_NONCANONICAL")
    previous = None
    hashes = {_READY: ready_hash, _SEAL: seal_hash}
    if previous_hash is not None:
        previous = CatalogRequesterMaintenanceReceiptV1.model_validate_json(_baseline_bytes(root, _MAINTENANCE, previous_hash))
        hashes[_MAINTENANCE] = previous_hash
    elif (root / _MAINTENANCE).exists():
        raise ValueError("CHAT_MAINTENANCE_PREDECESSOR_PIN_REQUIRED")
    # Validate the actual predecessor before paying for either build.
    complete_requester_maintenance(
        ready, seal, seal, expected_commit_sha=seal.protected_commit_sha,
        client_application_sha256=seal.requester_client_application_sha256,
        broker_application_sha256=seal.requester_broker_application_sha256,
        previous_maintenance=previous,
    )
    return _Baseline(ready, seal, previous, ready_bytes, hashes)


def _bind_and_verify(output: Path, baseline: _Baseline, commit: str) -> None:
    requester = output / "payload/CatalogRequester"
    hashes = {kind: hashlib.sha256((requester / f"bin/catalog-requester-{kind}.pyz").read_bytes()).hexdigest() for kind in _KINDS}
    unsigned = baseline.seal.model_copy(update={
        "protected_commit_sha": commit, "sealed_at": datetime.now(timezone.utc),
        "requester_client_application_sha256": hashes["client"],
        "requester_broker_application_sha256": hashes["broker"],
        "production_seal_sha256": "0" * 64,
    })
    seal = unsigned.model_copy(update={"production_seal_sha256": hashlib.sha256(builder._canonical(unsigned.model_dump(mode="json"))).hexdigest()})
    receipt = complete_requester_maintenance(
        baseline.ready, baseline.seal, seal, expected_commit_sha=commit,
        client_application_sha256=hashes["client"], broker_application_sha256=hashes["broker"],
        previous_maintenance=baseline.previous,
    )
    _exclusive_write(requester / _SEAL, builder._canonical(seal.model_dump(mode="json")) + b"\n")
    _exclusive_write(requester / _MAINTENANCE, builder._canonical(receipt.model_dump(mode="json")) + b"\n")
    # The historical READY is copied only to a separate verification tree. It
    # never enters the replacement inventory and is never rewritten in place.
    verification = output / "verification/CatalogRequester"
    for path in sorted(requester.rglob("*")):
        if path.is_file():
            _exclusive_write(verification / path.relative_to(requester), path.read_bytes())
    _exclusive_write(verification / _READY, baseline.ready_bytes)
    for kind in _KINDS:
        verify_installed_requester_application(
            broker_root=verification, application_kind=kind,
            application_path=verification / f"bin/catalog-requester-{kind}.pyz",
        )


def _exclusive_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ValueError("CHAT_MAINTENANCE_OUTPUT_EXISTS")
    # Only stage under an existing, ordinary parent; never follow a junction.
    absolute = path.absolute()
    for parent in absolute.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or parent.is_symlink():
            raise ValueError("CHAT_MAINTENANCE_OUTPUT_UNSAFE")
    absolute.mkdir(exist_ok=False)
    return absolute


def prepare_package(*, source_root: Path, output_dir: Path, expected_commit_sha: str,
                    baseline_root: Path | None = None, expected_ready_file_sha256: str | None = None,
                    expected_seal_file_sha256: str | None = None,
                    expected_previous_maintenance_file_sha256: str | None = None) -> dict[str, object]:
    """Verify committed builds and stage exact public bytes in a fresh local tree.

    A candidate is NOT installation approval. Protected maintenance must still
    authenticate the approved commit, audit existing ACLs/runtime, capture backup,
    preserve credentials, bind real receipts/seal and test rollback before use.
    Partial output is kept for diagnosis; no retry or deletion is automatic.
    """
    baseline = None
    if baseline_root is not None:
        if expected_ready_file_sha256 is None or expected_seal_file_sha256 is None:
            raise ValueError("CHAT_MAINTENANCE_BASELINE_PINS_REQUIRED")
        baseline = _read_baseline(baseline_root, expected_ready_file_sha256, expected_seal_file_sha256,
                                  expected_previous_maintenance_file_sha256)
    elif any(value is not None for value in (expected_ready_file_sha256, expected_seal_file_sha256, expected_previous_maintenance_file_sha256)):
        raise ValueError("CHAT_MAINTENANCE_BASELINE_ROOT_REQUIRED")
    output = _new_output(output_dir)
    first, second = output / "build-a", output / "build-b"
    builder.build(source_root=source_root, output_dir=first, expected_commit_sha=expected_commit_sha)
    builder.build(source_root=source_root, output_dir=second, expected_commit_sha=expected_commit_sha)
    root = source_root.resolve(strict=True)
    expected_names = {
        f"catalog-requester-{kind}.{suffix}"
        for kind in _KINDS for suffix in ("pyz", "manifest.json")
    }
    for directory in (first, second):
        if {path.name for path in directory.iterdir()} != expected_names:
            raise ValueError("CHAT_MAINTENANCE_BUILD_SET_MISMATCH")
    for name in sorted(expected_names):
        if (first / name).read_bytes() != (second / name).read_bytes():
            raise ValueError("CHAT_MAINTENANCE_NONDETERMINISTIC_BUILD")

    registry_path = "config/catalog_campaign_registry_v1.json"
    registry = builder._read_verified_file(root, registry_path, expected_commit_sha)
    public_paths = builder.PUBLIC_INPUTS + builder._active_definition_paths(registry)
    public_bytes = {
        relative: builder._read_verified_file(root, relative, expected_commit_sha)
        for relative in public_paths
    }
    sender = builder._read_verified_file(root, _SENDER_SOURCE, expected_commit_sha)
    payload = output / "payload"
    requester = payload / "CatalogRequester"
    for name in sorted(expected_names):
        _exclusive_write(requester / "bin" / name, (first / name).read_bytes())
    for relative, data in public_bytes.items():
        _exclusive_write(requester / relative, data)
    public_sender = payload / "CatalogChatSender"
    _exclusive_write(public_sender / "submit_catalog_chat_intent.py", sender)
    _exclusive_write(public_sender / "catalog_campaign_registry_v1.json", registry)

    dependencies: list[dict[str, object]] = []
    for kind in _KINDS:
        wrapper = verify_installed_requester_application(
            broker_root=requester, application_kind=kind,
            application_path=requester / f"bin/catalog-requester-{kind}.pyz",
        )
        core = wrapper["manifest_core"]
        if not isinstance(core, dict) or core["protected_commit_sha"] != expected_commit_sha:
            raise ValueError("CHAT_MAINTENANCE_COMMIT_MISMATCH")
        for field in ("dependency_input", "dependency_lock"):
            record = core[field]
            if not isinstance(record, dict):
                raise ValueError("CHAT_MAINTENANCE_DEPENDENCY_INVALID")
            relative = builder._safe_relative_path(str(record["path"]))
            data = builder._read_verified_file(root, relative, expected_commit_sha)
            if hashlib.sha256(data).hexdigest() != record["sha256"] or len(data) != record["size_bytes"]:
                raise ValueError("CHAT_MAINTENANCE_DEPENDENCY_MISMATCH")
            _exclusive_write(output / "evidence" / relative, data)
            dependencies.append(dict(record))

    if baseline is not None:
        _bind_and_verify(output, baseline, expected_commit_sha)
    files: list[dict[str, object]] = []
    for path in sorted(payload.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            files.append({"path": path.relative_to(payload).as_posix(),
                          "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
    result: dict[str, object] = {
        "schema_version": "1", "status": "CANDIDATE",
        "protected_commit_sha": expected_commit_sha,
        "two_builds_identical": True, "applications_verified_unsealed": True,
        "production_verified": False, "installation_authorized_by_this_file": False,
        "applications_verified_sealed_against_baseline": baseline is not None,
        "baseline_file_sha256": baseline.file_hashes if baseline is not None else {},
        "files": files, "dependencies": dependencies,
        "pending": ["approved_commit_provenance", "protected_inventory_and_backup",
                    "runtime_and_acl_validation", "real_seal_and_receipt_binding",
                    "rollback_validation", "protected_installation", "live_acceptance"],
    }
    _exclusive_write(output / "candidate.json", builder._canonical(result) + b"\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-commit-sha", required=True)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--expected-ready-file-sha256")
    parser.add_argument("--expected-seal-file-sha256")
    parser.add_argument("--expected-previous-maintenance-file-sha256")
    args = parser.parse_args()
    result = prepare_package(source_root=args.source_root, output_dir=args.output_dir,
                             expected_commit_sha=args.expected_commit_sha, baseline_root=args.baseline_root,
                             expected_ready_file_sha256=args.expected_ready_file_sha256,
                             expected_seal_file_sha256=args.expected_seal_file_sha256,
                             expected_previous_maintenance_file_sha256=args.expected_previous_maintenance_file_sha256)
    print(json.dumps({key: result[key] for key in ("status", "protected_commit_sha", "production_verified")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
