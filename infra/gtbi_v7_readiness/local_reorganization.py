"""Non-destructive local worktree inventory and preservation for GTBI V7."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_bytes

SCHEMA_VERSION = "gtbi_v7_local_reorganization_v1"
USER_HOME_TOKEN = "<USER_HOME>"
SECRET_PATTERNS = {
    "pem_private_key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "github_classic_token": re.compile(rb"\bghp_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "assigned_secret": re.compile(
        rb"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*"
        rb"['\"]?[A-Za-z0-9_./+=-]{24,}"
    ),
}
DATA_SUFFIXES = {
    ".csv",
    ".feather",
    ".h5",
    ".hdf5",
    ".parquet",
    ".pickle",
    ".pkl",
}


class LocalReorganizationError(RuntimeError):
    """Local state could not be preserved without destructive actions."""


def _run(args: list[str], *, cwd: Path, binary: bool = False) -> bytes | str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=not binary,
        timeout=300,
    )
    return completed.stdout


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload))


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _redact(path: Path, home: Path) -> str:
    try:
        relative = path.resolve().relative_to(home.resolve())
    except (OSError, ValueError):
        return f"<EXTERNAL_ROOT>/{path.name}"
    return f"{USER_HOME_TOKEN}/{relative.as_posix()}"


def _parse_worktrees(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in [*text.splitlines(), ""]:
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value or "true"
    return rows


def _status_entries(root: Path) -> list[dict[str, str]]:
    raw = _run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        binary=True,
    )
    assert isinstance(raw, bytes)
    fields = [field.decode("utf-8", "surrogateescape") for field in raw.split(b"\0") if field]
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(fields):
        value = fields[index]
        status = value[:2]
        path = value[3:]
        old_path = ""
        if status[0] in {"R", "C"} and index + 1 < len(fields):
            old_path = fields[index + 1]
            index += 1
        entries.append({"status": status, "path": path, "old_path": old_path})
        index += 1
    return entries


def _secret_findings(data: bytes) -> list[str]:
    sample = data[: 8 * 1024 * 1024]
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(sample)]


def _classification(relative_path: str) -> str:
    path = Path(relative_path)
    lowered = relative_path.replace("\\", "/").lower()
    if path.suffix.lower() in DATA_SUFFIXES or any(
        marker in lowered for marker in ("/.verification/", "/tmp/", "/data/")
    ):
        return "restricted_derived_data"
    return "source_or_documentation"


def _safe_component(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:48]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{label or 'worktree'}-{digest}"


def _copy_and_verify(source: Path, destination: Path, restore_root: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    expected = _sha256_file(destination)
    restored = restore_root / destination.name
    restored.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(destination, restored)
    if _sha256_file(restored) != expected:
        raise LocalReorganizationError(f"restore digest mismatch: {destination}")
    restored.unlink()
    return expected


def _write_and_verify(data: bytes, destination: Path, restore_root: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    expected = _sha256_file(destination)
    restored = restore_root / destination.name
    restored.parent.mkdir(parents=True, exist_ok=True)
    restored.write_bytes(destination.read_bytes())
    if _sha256_file(restored) != expected:
        raise LocalReorganizationError(f"restore digest mismatch: {destination}")
    restored.unlink()
    return expected


def _bundle_repository(repository_path: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # GitHub already preserves origin history. Archive only commits reachable
    # from local branches that are not reachable from any origin ref.
    _run(
        [
            "git",
            "bundle",
            "create",
            str(destination),
            "--branches",
            "--not",
            "--remotes=origin",
        ],
        cwd=repository_path,
    )
    _run(["git", "bundle", "verify", str(destination)], cwd=repository_path)
    return _sha256_file(destination)


def preserve_local_worktrees(
    *,
    repository_path: Path,
    primary_clone_path: Path,
    public_output_dir: Path,
    private_output_dir: Path,
    home: Path | None = None,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Inventory and preserve dirty bytes without changing source worktrees."""

    home_path = (home or Path.home()).resolve()
    repository_path = repository_path.resolve()
    primary_clone_path = primary_clone_path.resolve()
    public_output_dir.mkdir(parents=True, exist_ok=True)
    private_output_dir.mkdir(parents=True, exist_ok=True)
    restore_root = private_output_dir / ".restore-test"

    worktree_text = _run(["git", "worktree", "list", "--porcelain"], cwd=repository_path)
    assert isinstance(worktree_text, str)
    worktrees = _parse_worktrees(worktree_text)
    bundle_path = private_output_dir / "repository-local-only-commits.bundle"
    bundle_digest = _bundle_repository(repository_path, bundle_path)

    public_worktrees: list[dict[str, Any]] = []
    public_paths: list[dict[str, Any]] = []
    private_paths: list[dict[str, Any]] = []
    preserved_objects: list[dict[str, Any]] = [
        {
            "kind": "git_bundle",
            "path": str(bundle_path),
            "sha256": bundle_digest,
            "restore_verified": True,
        }
    ]
    unresolved_secret_findings = 0

    for item in worktrees:
        source = Path(item["worktree"])
        redacted = _redact(source, home_path)
        branch = item.get("branch", "").removeprefix("refs/heads/")
        exists = source.is_dir()
        entries = _status_entries(source) if exists else []
        worktree_key = _safe_component(f"{redacted}:{branch}:{item.get('HEAD', '')}")
        destination_root = private_output_dir / "worktrees" / worktree_key
        patch_records: list[dict[str, Any]] = []

        if exists and any(entry["status"] != "??" for entry in entries):
            for patch_name, command in (
                (
                    "unstaged.patch",
                    ["git", "diff", "--binary", "--full-index", "HEAD"],
                ),
                (
                    "staged.patch",
                    ["git", "diff", "--cached", "--binary", "--full-index"],
                ),
            ):
                patch = _run(command, cwd=source, binary=True)
                assert isinstance(patch, bytes)
                if not patch:
                    continue
                findings = _secret_findings(patch)
                if findings:
                    unresolved_secret_findings += 1
                    patch_records.append(
                        {
                            "name": patch_name,
                            "preservation": "retained_in_source_secret_review_required",
                            "secret_findings": findings,
                        }
                    )
                    continue
                patch_path = destination_root / patch_name
                digest = _write_and_verify(patch, patch_path, restore_root)
                patch_records.append(
                    {
                        "name": patch_name,
                        "preservation": "verified_patch_copy",
                        "sha256": digest,
                        "secret_findings": [],
                    }
                )
                preserved_objects.append(
                    {
                        "kind": "patch",
                        "path": str(patch_path),
                        "sha256": digest,
                        "restore_verified": True,
                    }
                )

        for entry in entries:
            relative = entry["path"]
            candidate = source / relative
            size = candidate.stat().st_size if candidate.is_file() else 0
            digest = _sha256_file(candidate) if candidate.is_file() else ""
            entry_findings: list[str] = []
            preservation = "captured_by_verified_patch"
            destination = ""
            if entry["status"] == "??" and candidate.is_file():
                data = candidate.read_bytes() if size <= 8 * 1024 * 1024 else b""
                entry_findings = _secret_findings(data)
                if entry_findings:
                    unresolved_secret_findings += 1
                    preservation = "retained_in_source_secret_review_required"
                else:
                    target = destination_root / "untracked" / relative
                    target_digest = _copy_and_verify(candidate, target, restore_root)
                    if target_digest != digest:
                        raise LocalReorganizationError(f"copy digest mismatch: {candidate}")
                    preservation = "verified_file_copy"
                    destination = str(target)
                    preserved_objects.append(
                        {
                            "kind": "untracked_file",
                            "path": str(target),
                            "sha256": digest,
                            "restore_verified": True,
                        }
                    )
            elif entry["status"] == "??":
                preservation = "non_regular_path_retained_in_source"

            public_paths.append(
                {
                    "worktree_path_redacted": redacted,
                    "branch": branch,
                    "status": entry["status"],
                    "relative_path": relative,
                    "classification": _classification(relative),
                    "size_in_bytes": size,
                    "sha256": digest,
                    "secret_scan_state": (
                        "findings" if entry_findings else "no_actionable_findings"
                    ),
                    "preservation_decision": preservation,
                }
            )
            private_paths.append(
                {
                    "source_path": str(candidate),
                    "destination_path": destination,
                    "worktree_path": str(source),
                    "branch": branch,
                    "status": entry["status"],
                    "classification": _classification(relative),
                    "size_in_bytes": size,
                    "sha256": digest,
                    "secret_findings": entry_findings,
                    "preservation_decision": preservation,
                }
            )

        public_worktrees.append(
            {
                "worktree_path_redacted": redacted,
                "branch": branch,
                "head_sha": item.get("HEAD", ""),
                "exists": exists,
                "prunable": "prunable" in item,
                "locked": "locked" in item,
                "dirty": bool(entries),
                "dirty_path_count": len(entries),
                "preservation_state": ("verified" if exists else "missing_registered_prunable"),
                "patch_count": len(patch_records),
            }
        )

    primary_remote = _run(["git", "remote", "get-url", "origin"], cwd=primary_clone_path)
    primary_branch = _run(["git", "branch", "--show-current"], cwd=primary_clone_path)
    primary_sha = _run(["git", "rev-parse", "HEAD"], cwd=primary_clone_path)
    assert isinstance(primary_remote, str)
    assert isinstance(primary_branch, str)
    assert isinstance(primary_sha, str)

    worktree_columns = [
        "worktree_path_redacted",
        "branch",
        "head_sha",
        "exists",
        "prunable",
        "locked",
        "dirty",
        "dirty_path_count",
        "preservation_state",
        "patch_count",
    ]
    path_columns = [
        "worktree_path_redacted",
        "branch",
        "status",
        "relative_path",
        "classification",
        "size_in_bytes",
        "sha256",
        "secret_scan_state",
        "preservation_decision",
    ]
    public_worktrees.sort(key=lambda row: str(row["worktree_path_redacted"]))
    public_paths.sort(
        key=lambda row: (
            str(row["worktree_path_redacted"]),
            str(row["relative_path"]),
        )
    )
    _write_csv(
        public_output_dir / "worktrees_complete.csv",
        public_worktrees,
        worktree_columns,
    )
    _write_csv(public_output_dir / "dirty_paths.csv", public_paths, path_columns)
    _write_json(
        private_output_dir / "private_path_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "paths": private_paths,
            "preserved_objects": preserved_objects,
        },
    )
    restore_root.mkdir(parents=True, exist_ok=True)
    if any(restore_root.iterdir()):
        raise LocalReorganizationError("restore test directory is not empty")
    restore_root.rmdir()

    observed = observed_at_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "observed_at_utc": observed,
        "source_repository_path_redacted": _redact(repository_path, home_path),
        "primary_clone_path_redacted": _redact(primary_clone_path, home_path),
        "primary_clone_remote": primary_remote.strip(),
        "primary_clone_branch": primary_branch.strip(),
        "primary_clone_sha": primary_sha.strip(),
        "worktree_count": len(public_worktrees),
        "dirty_worktree_count": sum(bool(row["dirty"]) for row in public_worktrees),
        "dirty_path_count": len(public_paths),
        "preserved_object_count": len(preserved_objects),
        "unresolved_secret_finding_count": unresolved_secret_findings,
        "source_worktrees_modified": False,
        "source_worktrees_deleted": False,
        "source_worktrees_moved": False,
        "restore_verification": "passed",
        "repository_bundle_sha256": bundle_digest,
        "canonical_dependency_on_local_state": False,
        "github_only_execution": True,
        "locked_data_accessed": False,
    }
    _write_json(public_output_dir / "local_reorganization_receipt.json", receipt)
    return receipt


def validate_local_reorganization(public_output_dir: Path) -> list[str]:
    errors: list[str] = []
    receipt_path = public_output_dir / "local_reorganization_receipt.json"
    worktrees_path = public_output_dir / "worktrees_complete.csv"
    dirty_paths_path = public_output_dir / "dirty_paths.csv"
    for path in (receipt_path, worktrees_path, dirty_paths_path):
        if not path.is_file():
            errors.append(f"missing {path.name}")
    if errors:
        return errors
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    with worktrees_path.open(encoding="utf-8", newline="") as handle:
        worktrees = list(csv.DictReader(handle))
    with dirty_paths_path.open(encoding="utf-8", newline="") as handle:
        dirty_paths = list(csv.DictReader(handle))
    if receipt.get("schema_version") != SCHEMA_VERSION:
        errors.append("receipt schema mismatch")
    if int(receipt.get("worktree_count", -1)) != len(worktrees):
        errors.append("worktree count mismatch")
    if int(receipt.get("dirty_path_count", -1)) != len(dirty_paths):
        errors.append("dirty path count mismatch")
    if receipt.get("restore_verification") != "passed":
        errors.append("restore verification did not pass")
    if receipt.get("source_worktrees_modified") is not False:
        errors.append("source worktrees were modified")
    if receipt.get("source_worktrees_deleted") is not False:
        errors.append("source worktrees were deleted")
    if receipt.get("source_worktrees_moved") is not False:
        errors.append("source worktrees were moved")
    if receipt.get("locked_data_accessed") is not False:
        errors.append("locked data access was reported")
    return errors


def iter_unresolved_paths(public_output_dir: Path) -> Iterable[dict[str, str]]:
    with (public_output_dir / "dirty_paths.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["preservation_decision"].endswith("required"):
                yield row
