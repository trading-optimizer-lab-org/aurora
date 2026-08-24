"""Build the two deterministic, closed catalog requester applications."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile


CLIENT_SOURCES = (
    "infra/sp500_megarun/catalog_request_contract.py",
    "infra/sp500_megarun/catalog_campaign_registry.py",
    "infra/sp500_megarun/catalog_campaign_definition_contract.py",
    "infra/sp500_megarun/catalog_requester.py",
    "infra/sp500_megarun/catalog_requester_cli.py",
)
BROKER_SOURCES = (
    "infra/sp500_megarun/catalog_request_contract.py",
    "infra/sp500_megarun/catalog_campaign_registry.py",
    "infra/sp500_megarun/catalog_campaign_definition_contract.py",
    "infra/sp500_megarun/catalog_requester.py",
    "infra/sp500_megarun/catalog_run_request.py",
    "infra/sp500_megarun/catalog_requester_broker.py",
    "infra/sp500_megarun/catalog_requester_broker_cli.py",
)
PUBLIC_INPUTS = (
    "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md",
    "config/catalog_run_prompt_policy_v1.json",
    "config/catalog_campaign_registry_v1.json",
    "config/catalog_requester_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_controls_v1.json",
    "config/catalog_requester_public_key_v1.pem",
    "schemas/catalog_requester_app_manifest_v1.schema.json",
    "schemas/catalog_campaign_definition_manifest_v1.schema.json",
    "schemas/catalog_run_prompt_policy_v1.schema.json",
)
APPLICATIONS = {
    "client": {
        "sources": CLIENT_SOURCES,
        "package": "aurora_catalog_requester_client",
        "cli_module": "catalog_requester_cli",
        "dependency_input": "requirements/catalog-requester-client.in",
        "dependency_lock": "requirements/catalog-requester-client-win-py314.lock",
        "application": "catalog-requester-client.pyz",
        "manifest": "catalog-requester-client.manifest.json",
    },
    "broker": {
        "sources": BROKER_SOURCES,
        "package": "aurora_catalog_requester_broker",
        "cli_module": "catalog_requester_broker_cli",
        "dependency_input": "requirements/catalog-requester-broker.in",
        "dependency_lock": "requirements/catalog-requester-broker-win-py314.lock",
        "application": "catalog-requester-broker.pyz",
        "manifest": "catalog-requester-broker.manifest.json",
    },
}
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_MODE = 0o644
_EMBEDDED_MANIFEST_NAME = "catalog_requester_app_manifest_v1.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build deterministic isolated catalog requester applications."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-commit-sha", required=True)
    return parser


def _run_git(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={os.fspath(root)}",
            "-C",
            os.fspath(root),
            *arguments,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("REQUESTER_BUILD_GIT_VERIFICATION_FAILED")
    return result.stdout


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative_path(value: str) -> str:
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("REQUESTER_BUILD_PATH_INVALID")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise ValueError("REQUESTER_BUILD_PATH_INVALID")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError("REQUESTER_BUILD_PATH_INVALID")
    return value


def _is_reparse(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _read_verified_file(root: Path, relative: str, commit: str) -> bytes:
    checked = _safe_relative_path(relative)
    candidate = root.joinpath(*checked.split("/"))
    if candidate.is_symlink() or _is_reparse(candidate):
        raise ValueError("REQUESTER_BUILD_LINK_FORBIDDEN")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("REQUESTER_BUILD_PATH_INVALID")
    tracked = _run_git(root, "ls-files", "--error-unmatch", "--", checked).strip()
    if tracked.decode("utf-8") != checked:
        raise ValueError("REQUESTER_BUILD_UNTRACKED_INPUT")
    data = resolved.read_bytes()
    committed = _run_git(root, "show", f"{commit}:{checked}")
    if data != committed and data.replace(b"\r\n", b"\n") != committed.replace(
        b"\r\n", b"\n"
    ):
        raise ValueError("REQUESTER_BUILD_SOURCE_MISMATCH")
    return committed


def _file_digest(path: str, data: bytes) -> dict[str, object]:
    return {"path": path, "sha256": _sha256(data), "size_bytes": len(data)}


def _active_definition_paths(registry_bytes: bytes) -> tuple[str, ...]:
    try:
        registry = json.loads(registry_bytes)
        campaigns = registry["campaigns"]
        paths = tuple(
            item["definition_manifest_path"]
            for item in campaigns
            if item["active"] is True
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("REQUESTER_BUILD_REGISTRY_INVALID") from exc
    checked = tuple(_safe_relative_path(str(path)) for path in paths)
    if checked != tuple(sorted(checked)) or len(checked) != len(set(checked)):
        raise ValueError("REQUESTER_BUILD_REGISTRY_INVALID")
    return checked


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | _MODE) << 16
    info.flag_bits = 0
    return info


def _archive_member(path: str, order: int, data: bytes) -> dict[str, object]:
    return {
        "path": path,
        "order": order,
        "mode": "0644",
        "sha256": _sha256(data),
        "size_bytes": len(data),
    }


def _application_inputs(
    root: Path,
    *,
    commit: str,
    application_kind: str,
    public_inputs: tuple[tuple[str, bytes], ...],
) -> tuple[dict[str, object], dict[str, bytes], str]:
    definition = APPLICATIONS[application_kind]
    package = str(definition["package"])
    source_records: list[dict[str, object]] = []
    members: dict[str, bytes] = {}
    for relative in definition["sources"]:
        data = _read_verified_file(root, str(relative), commit)
        archive_member = f"{package}/{PurePosixPath(str(relative)).name}"
        members[archive_member] = data
        source_records.append(
            {
                "path": relative,
                "archive_member": archive_member,
                "sha256": _sha256(data),
                "size_bytes": len(data),
            }
        )
    package_init = f"{package}/__init__.py"
    root_main = "__main__.py"
    members[package_init] = b""
    members[root_main] = (
        f"from {package}.{definition['cli_module']} import main\n"
        "raise SystemExit(main())\n"
    ).encode("ascii")

    dependency_input_path = str(definition["dependency_input"])
    dependency_lock_path = str(definition["dependency_lock"])
    dependency_input = _read_verified_file(root, dependency_input_path, commit)
    dependency_lock = _read_verified_file(root, dependency_lock_path, commit)
    embedded_path = f"{package}/{_EMBEDDED_MANIFEST_NAME}"
    all_member_names = tuple(sorted((*members, embedded_path)))
    embedded_order = all_member_names.index(embedded_path)
    archive_records = tuple(
        _archive_member(path, all_member_names.index(path), members[path])
        for path in all_member_names
        if path != embedded_path
    )
    generated = tuple(
        record
        for record in archive_records
        if record["path"] in {package_init, root_main}
    )
    core: dict[str, object] = {
        "schema_version": "1",
        "manifest_format": "embedded",
        "application_kind": application_kind,
        "application_version": "1",
        "protected_commit_sha": commit,
        "python_requirement": "CPython 3.14",
        "entry_point": f"{package}.{definition['cli_module']}:main",
        "archive_package": package,
        "source_files": source_records,
        "generated_members": generated,
        "archive_members": archive_records,
        "embedded_manifest_member": {
            "path": embedded_path,
            "order": embedded_order,
            "mode": "0644",
        },
        "dependency_input": _file_digest(dependency_input_path, dependency_input),
        "dependency_lock": _file_digest(dependency_lock_path, dependency_lock),
        "public_inputs": tuple(
            _file_digest(path, data) for path, data in public_inputs
        ),
        "embedded_manifest_sha256_location": "external_manifest",
        "application_sha256_location": "external_manifest",
    }
    members[embedded_path] = _canonical(core)
    return core, members, embedded_path


def _write_application(
    output_dir: Path,
    *,
    application_kind: str,
    core: dict[str, object],
    members: dict[str, bytes],
    embedded_path: str,
) -> None:
    definition = APPLICATIONS[application_kind]
    application_path = output_dir / str(definition["application"])
    manifest_path = output_dir / str(definition["manifest"])
    if application_path.exists() or manifest_path.exists():
        raise ValueError("REQUESTER_BUILD_OUTPUT_EXISTS")
    with zipfile.ZipFile(application_path, mode="x") as archive:
        for name in sorted(members):
            archive.writestr(_zip_info(name), members[name])
    application_bytes = application_path.read_bytes()
    wrapper = {
        "schema_version": "1",
        "manifest_format": "external",
        "application_kind": application_kind,
        "manifest_core": core,
        "embedded_manifest_sha256": _sha256(members[embedded_path]),
        "application_sha256": _sha256(application_bytes),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(manifest_path, flags, 0o600)
    try:
        payload = _canonical(wrapper) + b"\n"
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short manifest write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def build(*, source_root: Path, output_dir: Path, expected_commit_sha: str) -> None:
    if (
        len(expected_commit_sha) != 40
        or expected_commit_sha.casefold() != expected_commit_sha
        or any(character not in "0123456789abcdef" for character in expected_commit_sha)
    ):
        raise ValueError("REQUESTER_BUILD_COMMIT_INVALID")
    if source_root.is_symlink() or _is_reparse(source_root):
        raise ValueError("REQUESTER_BUILD_ROOT_INVALID")
    root = source_root.resolve(strict=True)
    if not root.is_dir() or _is_reparse(root):
        raise ValueError("REQUESTER_BUILD_ROOT_INVALID")
    actual_commit = _run_git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if actual_commit != expected_commit_sha:
        raise ValueError("REQUESTER_BUILD_COMMIT_MISMATCH")
    if _run_git(root, "status", "--porcelain=v1", "--untracked-files=no"):
        raise ValueError("REQUESTER_BUILD_DIRTY_SOURCE")

    registry_path = "config/catalog_campaign_registry_v1.json"
    registry_bytes = _read_verified_file(root, registry_path, actual_commit)
    public_paths = PUBLIC_INPUTS + _active_definition_paths(registry_bytes)
    if len(public_paths) != len(set(public_paths)):
        raise ValueError("REQUESTER_BUILD_PUBLIC_INPUT_DUPLICATE")
    public_inputs = tuple(
        (path, _read_verified_file(root, path, actual_commit)) for path in public_paths
    )
    prepared: dict[str, tuple[dict[str, object], dict[str, bytes], str]] = {}
    for application_kind in ("client", "broker"):
        prepared[application_kind] = _application_inputs(
            root,
            commit=actual_commit,
            application_kind=application_kind,
            public_inputs=public_inputs,
        )

    output = output_dir.resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise ValueError("REQUESTER_BUILD_OUTPUT_EXISTS")
    output.mkdir(parents=False, exist_ok=False)
    for application_kind in ("client", "broker"):
        core, members, embedded_path = prepared[application_kind]
        _write_application(
            output,
            application_kind=application_kind,
            core=core,
            members=members,
            embedded_path=embedded_path,
        )


def main() -> int:
    args = _parser().parse_args()
    build(
        source_root=args.source_root,
        output_dir=args.output_dir,
        expected_commit_sha=args.expected_commit_sha,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
