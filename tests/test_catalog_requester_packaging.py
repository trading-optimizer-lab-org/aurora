from __future__ import annotations

import ast
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

import jsonschema
import pytest

from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_requester import (
    CatalogRequesterProductionSealV1,
    verify_installed_requester_application,
)


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/build_catalog_requester_apps.py"
SCHEMA = ROOT / "schemas/catalog_requester_app_manifest_v1.schema.json"
BROKER_INSTALLER = ROOT / "scripts/install_catalog_requester_broker.ps1"
AGENT_INSTALLER = ROOT / "scripts/install_catalog_agent_sandbox.ps1"
BROKER_CLI = ROOT / "infra/sp500_megarun/catalog_requester_broker_cli.py"
CLIENT_CLI = ROOT / "infra/sp500_megarun/catalog_requester_cli.py"

CLIENT_SOURCES = {
    "infra/sp500_megarun/catalog_request_contract.py",
    "infra/sp500_megarun/catalog_campaign_registry.py",
    "infra/sp500_megarun/catalog_campaign_definition_contract.py",
    "infra/sp500_megarun/catalog_requester.py",
    "infra/sp500_megarun/catalog_requester_cli.py",
}
BROKER_SOURCES = {
    "infra/sp500_megarun/catalog_request_contract.py",
    "infra/sp500_megarun/catalog_campaign_registry.py",
    "infra/sp500_megarun/catalog_campaign_definition_contract.py",
    "infra/sp500_megarun/catalog_requester.py",
    "infra/sp500_megarun/catalog_run_request.py",
    "infra/sp500_megarun/catalog_requester_broker.py",
    "infra/sp500_megarun/catalog_requester_broker_cli.py",
}


def test_builder_is_standard_library_only_and_has_closed_source_allowlists() -> None:
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    assert roots <= {
        "__future__",
        "argparse",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "stat",
        "subprocess",
        "sys",
        "typing",
        "zipfile",
    }
    source = BUILDER.read_text(encoding="utf-8")
    for path in CLIENT_SOURCES | BROKER_SOURCES:
        assert path in source
    assert "glob(" not in source
    assert "rglob(" not in source


def test_builder_completes_a_partial_manifest_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import build_catalog_requester_apps as builder_module

    original_write = builder_module.os.write

    def partial_write(descriptor: int, payload: bytes) -> int:
        return original_write(descriptor, payload[:11])

    monkeypatch.setattr(builder_module.os, "write", partial_write)
    embedded_path = "aurora_catalog_requester_client/manifest.json"
    builder_module._write_application(
        tmp_path,
        application_kind="client",
        core={"schema_version": "test"},
        members={"__main__.py": b"", embedded_path: b"{}"},
        embedded_path=embedded_path,
    )
    manifest = tmp_path / "catalog-requester-client.manifest.json"
    assert manifest.read_bytes().endswith(b"\n")
    assert json.loads(manifest.read_text(encoding="utf-8"))["application_kind"] == (
        "client"
    )


def test_builder_git_verification_uses_an_exact_command_local_safe_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import build_catalog_requester_apps as builder_module

    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(builder_module.subprocess, "run", fake_run)
    root = tmp_path.resolve(strict=True)

    builder_module._run_git(root, "rev-parse", "HEAD")

    assert calls == [
        [
            "git",
            "-c",
            f"safe.directory={root}",
            "-C",
            str(root),
            "rev-parse",
            "HEAD",
        ]
    ]


def test_broker_runtime_rejects_an_administrative_service_token() -> None:
    source = BROKER_CLI.read_text(encoding="utf-8")
    assert "GetUserNameW" in source
    assert "IsUserAnAdmin" in source
    assert "REQUESTER_BROKER_OS_IDENTITY_INVALID" in source
    assert "REQUESTER_PUBLIC_IDENTITY_BINDING_INVALID" in source
    assert "client.requester_public_key_sha256" in source


def test_broker_startup_rehashes_both_installed_applications() -> None:
    source = BROKER_CLI.read_text(encoding="utf-8")
    assert 'application_kind="client"' in source
    assert 'application_path=root / "bin/catalog-requester-client.pyz"' in source
    assert 'application_kind="broker"' in source
    assert "Path(sys.argv[0])" in source


def test_requester_apps_reject_the_wrong_or_nonisolated_python_runtime() -> None:
    client = CLIENT_CLI.read_text(encoding="utf-8")
    broker = BROKER_CLI.read_text(encoding="utf-8")
    for source, venv, reason in (
        (client, "client-venv", "REQUESTER_CLIENT_RUNTIME_INVALID"),
        (broker, "broker-venv", "REQUESTER_BROKER_RUNTIME_INVALID"),
    ):
        assert venv in source
        assert reason in source
        assert "sys.executable" in source
        assert "sys.prefix" in source
        assert "sys.base_prefix" in source
        assert "sys.flags.isolated" in source
        assert "sys.flags.ignore_environment" in source
        assert "sys.flags.no_user_site" in source
        assert "sys.flags.safe_path" in source
        assert '"python314.zip"' in source
        assert '"Lib/site-packages"' in source


def test_client_runtime_requires_the_dedicated_non_admin_agent_identity() -> None:
    source = CLIENT_CLI.read_text(encoding="utf-8")
    assert "GetUserNameW" in source
    assert 'buffer.value.casefold() != "auroraagent"' in source
    assert "IsUserAnAdmin" in source
    assert "REQUESTER_CLIENT_OS_IDENTITY_INVALID" in source


def test_spool_creator_cannot_retain_owner_control_after_broker_claim() -> None:
    installer = BROKER_INSTALLER.read_text(encoding="utf-8")
    broker_cli = BROKER_CLI.read_text(encoding="utf-8")
    assert "*S-1-3-4:(OI)(IO)(RC)" in installer
    assert '${AgentIdentity}:(WD,REA,RA,X,S)' in installer
    inbox_acl = installer[installer.index('& icacls.exe (Join-Path $BrokerRoot "inbox")') :]
    inbox_acl = inbox_acl[: inbox_acl.index("if ($LASTEXITCODE -ne 0)")]
    assert '${AgentIdentity}:(F)' not in inbox_acl
    assert '${AgentIdentity}:(M)' not in inbox_acl
    assert '${AgentIdentity}:(RX)' not in inbox_acl
    assert '${AgentIdentity}:(RD)' not in inbox_acl
    assert '${AgentIdentity}:(D)' not in inbox_acl
    assert "seal_claimed_spool_file" in broker_cli
    assert "ConvertStringSecurityDescriptorToSecurityDescriptorW" in broker_cli
    assert "SetKernelObjectSecurity" in broker_cli
    assert "CreateFileW" in broker_cli
    assert "REQUESTER_BROKER_CLAIM_BUSY" in broker_cli
    assert "excluded_processing_names" in broker_cli
    assert "REQUESTER_BROKER_CLAIM_ACL_INVALID" in broker_cli
    assert broker_cli.index("seal_claimed_spool_file(claimed)") < broker_cli.rindex(
        "load_claimed_catalog_draft("
    )


def test_requester_dependency_inputs_are_exact_and_separate() -> None:
    assert (ROOT / "requirements/catalog-requester-client.in").read_text(
        encoding="utf-8"
    ) == "pydantic==2.13.4\n"
    assert (ROOT / "requirements/catalog-requester-broker.in").read_text(
        encoding="utf-8"
    ) == "cryptography==50.0.0\npydantic==2.13.4\nrequests==2.34.2\n"
    client_lock = (
        ROOT / "requirements/catalog-requester-client-win-py314.lock"
    ).read_text(encoding="utf-8")
    broker_lock = (
        ROOT / "requirements/catalog-requester-broker-win-py314.lock"
    ).read_text(encoding="utf-8")
    assert "pydantic==2.13.4" in client_lock
    assert "cryptography" not in client_lock.casefold()
    assert "requests" not in client_lock.casefold()
    for package in ("cryptography==50.0.0", "pydantic==2.13.4", "requests==2.34.2"):
        assert package in broker_lock
    assert "--hash=sha256:" in client_lock
    assert "--hash=sha256:" in broker_lock


def test_builder_cli_has_only_three_bootstrap_arguments() -> None:
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--source-root" in result.stdout
    assert "--output-dir" in result.stdout
    assert "--expected-commit-sha" in result.stdout
    assert "--extra-source" not in result.stdout
    assert "--entry-point" not in result.stdout


def test_schema_has_closed_client_and_broker_branches() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]["application_kind"]["enum"]) == {
        "client",
        "broker",
    }


def _archive_members(path: Path) -> tuple[str, ...]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos)
        assert all(info.create_system == 3 for info in infos)
        assert all((info.external_attr >> 16) & 0o777 == 0o644 for info in infos)
        return tuple(info.filename for info in infos)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _isolated_source_tree(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    registry = json.loads(
        (ROOT / "config/catalog_campaign_registry_v1.json").read_text(
            encoding="utf-8"
        )
    )
    definition_paths = {
        item["definition_manifest_path"]
        for item in registry["campaigns"]
        if item["active"] is True
    }
    paths = (
        CLIENT_SOURCES
        | BROKER_SOURCES
        | {
            "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md",
            "config/catalog_run_prompt_policy_v1.json",
            "config/catalog_campaign_registry_v1.json",
            "config/catalog_requester_v1.json",
            "config/catalog_controller_actors_v1.json",
            "config/catalog_github_controls_v1.json",
            "schemas/catalog_requester_app_manifest_v1.schema.json",
            "schemas/catalog_campaign_definition_manifest_v1.schema.json",
            "schemas/catalog_run_prompt_policy_v1.schema.json",
            "requirements/catalog-requester-client.in",
            "requirements/catalog-requester-client-win-py314.lock",
            "requirements/catalog-requester-broker.in",
            "requirements/catalog-requester-broker-win-py314.lock",
        }
        | definition_paths
    )
    for relative in sorted(paths):
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    public_key = source / "config/catalog_requester_public_key_v1.pem"
    shutil.copyfile(
        ROOT / "tests/fixtures/catalog_request_cross_runtime_public_key_v1.pem",
        public_key,
    )
    _git(source, "init", "--initial-branch=main")
    _git(source, "config", "user.name", "Requester Builder Test")
    _git(source, "config", "user.email", "requester-builder@example.invalid")
    _git(source, "add", "--all")
    _git(source, "commit", "-m", "synthetic requester source")
    return source, _git(source, "rev-parse", "HEAD")


def _build_apps(source: Path, output: Path, commit: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--source-root",
            str(source),
            "--output-dir",
            str(output),
            "--expected-commit-sha",
            commit,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _install_built_apps(source: Path, output: Path) -> Path:
    installed_bin = source / "bin"
    installed_bin.mkdir()
    for name in (
        "catalog-requester-client.pyz",
        "catalog-requester-client.manifest.json",
        "catalog-requester-broker.pyz",
        "catalog-requester-broker.manifest.json",
    ):
        shutil.copyfile(output / name, installed_bin / name)
    return installed_bin


def _rewrite_installed_manifest_core(
    *,
    installed_bin: Path,
    application_kind: str,
    mutation: str,
) -> None:
    application = installed_bin / f"catalog-requester-{application_kind}.pyz"
    manifest = (
        installed_bin / f"catalog-requester-{application_kind}.manifest.json"
    )
    wrapper = json.loads(manifest.read_text(encoding="utf-8"))
    core = wrapper["manifest_core"]
    if mutation == "extra_field":
        core["ignored_security_field"] = True
    elif mutation == "entry_point":
        core["entry_point"] = "unexpected.module:main"
    elif mutation == "source_files":
        core["source_files"] = []
    elif mutation == "generated_members":
        core["generated_members"] = []
    elif mutation == "dependency_input":
        core["dependency_input"]["path"] = "requirements/untrusted.in"
    elif mutation == "public_inputs":
        core["public_inputs"] = core["public_inputs"][1:]
    else:  # pragma: no cover - test helper contract
        raise AssertionError(mutation)
    core_bytes = json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    embedded_path = core["embedded_manifest_member"]["path"]
    rewritten = application.with_suffix(".rewritten")
    with zipfile.ZipFile(application, mode="r") as source_archive:
        members = tuple(
            (info, source_archive.read(info.filename))
            for info in source_archive.infolist()
        )
    with zipfile.ZipFile(rewritten, mode="x") as target_archive:
        for old_info, data in members:
            info = zipfile.ZipInfo(old_info.filename, date_time=old_info.date_time)
            info.compress_type = old_info.compress_type
            info.create_system = old_info.create_system
            info.external_attr = old_info.external_attr
            info.flag_bits = old_info.flag_bits
            target_archive.writestr(
                info,
                core_bytes if old_info.filename == embedded_path else data,
            )
    os.replace(rewritten, application)
    wrapper["manifest_core"] = core
    wrapper["embedded_manifest_sha256"] = hashlib.sha256(core_bytes).hexdigest()
    wrapper["application_sha256"] = hashlib.sha256(
        application.read_bytes()
    ).hexdigest()
    manifest.write_bytes(
        json.dumps(
            wrapper,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def test_builder_rejects_a_link_used_as_the_source_root(tmp_path: Path) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    linked_source = tmp_path / "linked-source"
    try:
        linked_source.symlink_to(source, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory links unavailable: {exc}")

    result = _build_apps(linked_source, tmp_path / "linked-output", commit)

    assert result.returncode != 0
    assert "REQUESTER_BUILD_ROOT_INVALID" in result.stderr


def test_tracked_builder_rejects_dirty_or_wrong_commit_without_output(tmp_path: Path) -> None:
    output = tmp_path / "apps"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--source-root",
            str(ROOT),
            "--output-dir",
            str(output),
            "--expected-commit-sha",
            "0" * 40,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not output.exists()


def test_no_requester_private_key_is_tracked() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    for relative in listed.decode("utf-8").split("\0"):
        if not relative:
            continue
        path = ROOT / relative
        if path.suffix.casefold() not in {".py", ".json", ".md", ".pem", ".ps1", ".in"}:
            continue
        data = path.read_bytes()
        assert b"-----BEGIN " + b"PRIVATE KEY-----" not in data
        assert b"-----BEGIN RSA " + b"PRIVATE KEY-----" not in data


def test_built_application_names_and_member_boundaries_are_fixed(tmp_path: Path) -> None:
    # A production build is intentionally impossible before the real public key
    # is bound. The source itself must nevertheless name only these outputs and
    # fixed archive package roots.
    source = BUILDER.read_text(encoding="utf-8")
    assert "catalog-requester-client.pyz" in source
    assert "catalog-requester-client.manifest.json" in source
    assert "catalog-requester-broker.pyz" in source
    assert "catalog-requester-broker.manifest.json" in source
    assert "aurora_catalog_requester_client" in source
    assert "aurora_catalog_requester_broker" in source
    assert "application_sha256_location" in source
    assert "embedded_manifest_sha256_location" in source
    assert hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_two_clean_builds_are_identical_closed_and_schema_valid(tmp_path: Path) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    for output in (first, second):
        result = _build_apps(source, output, commit)
        assert result.returncode == 0, result.stderr

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for kind, package, source_paths in (
        ("client", "aurora_catalog_requester_client", CLIENT_SOURCES),
        ("broker", "aurora_catalog_requester_broker", BROKER_SOURCES),
    ):
        app_name = f"catalog-requester-{kind}.pyz"
        manifest_name = f"catalog-requester-{kind}.manifest.json"
        assert (first / app_name).read_bytes() == (second / app_name).read_bytes()
        assert (first / manifest_name).read_bytes() == (
            second / manifest_name
        ).read_bytes()
        wrapper = json.loads((first / manifest_name).read_text(encoding="utf-8"))
        jsonschema.validate(wrapper, schema)
        core = wrapper["manifest_core"]
        jsonschema.validate(core, schema)
        assert wrapper["application_kind"] == core["application_kind"] == kind
        assert wrapper["application_sha256"] == hashlib.sha256(
            (first / app_name).read_bytes()
        ).hexdigest()
        with zipfile.ZipFile(first / app_name) as archive:
            members = tuple(info.filename for info in archive.infolist())
            embedded_path = core["embedded_manifest_member"]["path"]
            embedded = archive.read(embedded_path)
        assert members == tuple(sorted(members))
        assert wrapper["embedded_manifest_sha256"] == hashlib.sha256(
            embedded
        ).hexdigest()
        assert embedded == json.dumps(
            core,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        expected_members = {
            "__main__.py",
            f"{package}/__init__.py",
            f"{package}/catalog_requester_app_manifest_v1.json",
            *(f"{package}/{Path(path).name}" for path in source_paths),
        }
        assert set(members) == expected_members
        assert tuple(item["order"] for item in core["archive_members"]) == tuple(
            sorted(item["order"] for item in core["archive_members"])
        )
        assert core["embedded_manifest_member"]["order"] == members.index(
            embedded_path
        )
        help_result = subprocess.run(
            [sys.executable, "-I", "-s", "-E", str(first / app_name), "--help"],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stderr


def test_external_manifest_schema_recursively_closes_the_embedded_core(
    tmp_path: Path,
) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    output = tmp_path / "apps"
    result = _build_apps(source, output, commit)
    assert result.returncode == 0, result.stderr
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    wrapper = json.loads(
        (output / "catalog-requester-client.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    wrapper["manifest_core"]["ignored_security_field"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(wrapper, schema)

    wrapper = json.loads(
        (output / "catalog-requester-client.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    wrapper["entry_point"] = wrapper["manifest_core"]["entry_point"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(wrapper, schema)


def test_builder_rejects_dirty_source_before_creating_output(tmp_path: Path) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    prompt = source / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"
    prompt.write_bytes(prompt.read_bytes() + b"tamper\n")
    output = tmp_path / "tampered"
    result = _build_apps(source, output, commit)
    assert result.returncode != 0
    assert "REQUESTER_BUILD_DIRTY_SOURCE" in result.stderr
    assert not output.exists()


def test_builder_accepts_clean_windows_checkout_and_uses_committed_bytes(
    tmp_path: Path,
) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    subprocess.run(
        ["git", "-C", str(source), "config", "core.autocrlf", "false"],
        check=True,
        capture_output=True,
    )
    for path in source.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    relative = "requirements/catalog-requester-client.in"
    target = source / relative
    _git(source, "add", "--all")
    _git(source, "commit", "--amend", "--no-edit")
    commit = _git(source, "rev-parse", "HEAD")
    baseline = tmp_path / "baseline"
    baseline_result = _build_apps(source, baseline, commit)
    assert baseline_result.returncode == 0, baseline_result.stderr

    subprocess.run(
        ["git", "-C", str(source), "config", "core.autocrlf", "true"],
        check=True,
        capture_output=True,
    )
    target.unlink()
    subprocess.run(
        ["git", "-C", str(source), "checkout", "HEAD", "--", relative],
        check=True,
        capture_output=True,
    )
    assert b"\r\n" in target.read_bytes()
    status = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    )
    assert status.stdout == b""

    windows_output = tmp_path / "windows-output"
    result = _build_apps(source, windows_output, commit)

    assert result.returncode == 0, result.stderr
    for name in (
        "catalog-requester-client.pyz",
        "catalog-requester-client.manifest.json",
        "catalog-requester-broker.pyz",
        "catalog-requester-broker.manifest.json",
    ):
        assert (windows_output / name).read_bytes() == (baseline / name).read_bytes()


def test_repository_forces_pem_files_to_lf() -> None:
    attributes = (Path(__file__).parents[1] / ".gitattributes").read_text("utf-8")
    assert "*.pem text eol=lf" in attributes.splitlines()


def test_builder_ignores_unrelated_untracked_user_files(tmp_path: Path) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    (source / "unrelated-user-note.md").write_text(
        "preserve this file\n",
        encoding="utf-8",
    )
    output = tmp_path / "apps-with-user-note"

    result = _build_apps(source, output, commit)

    assert result.returncode == 0, result.stderr
    assert (source / "unrelated-user-note.md").read_text(encoding="utf-8") == (
        "preserve this file\n"
    )


def test_installed_apps_verify_own_bytes_embedded_core_and_public_inputs(
    tmp_path: Path,
) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    output = tmp_path / "apps"
    result = _build_apps(source, output, commit)
    assert result.returncode == 0, result.stderr
    installed_bin = source / "bin"
    installed_bin.mkdir()
    for name in (
        "catalog-requester-client.pyz",
        "catalog-requester-client.manifest.json",
        "catalog-requester-broker.pyz",
        "catalog-requester-broker.manifest.json",
    ):
        shutil.copyfile(output / name, installed_bin / name)
    for kind in ("client", "broker"):
        wrapper = verify_installed_requester_application(
            broker_root=source,
            application_kind=kind,
            application_path=installed_bin / f"catalog-requester-{kind}.pyz",
        )
        assert wrapper["application_kind"] == kind
    client = installed_bin / "catalog-requester-client.pyz"
    client.write_bytes(client.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="REQUESTER_APPLICATION_HASH_MISMATCH"):
        verify_installed_requester_application(
            broker_root=source,
            application_kind="client",
            application_path=client,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_field",
        "entry_point",
        "source_files",
        "generated_members",
        "dependency_input",
        "public_inputs",
    ),
)
def test_runtime_manifest_mirror_rejects_every_coherent_core_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    output = tmp_path / "apps"
    result = _build_apps(source, output, commit)
    assert result.returncode == 0, result.stderr
    installed_bin = _install_built_apps(source, output)
    _rewrite_installed_manifest_core(
        installed_bin=installed_bin,
        application_kind="client",
        mutation=mutation,
    )

    with pytest.raises(ValueError, match="REQUESTER_APPLICATION_MANIFEST_INVALID"):
        verify_installed_requester_application(
            broker_root=source,
            application_kind="client",
            application_path=installed_bin / "catalog-requester-client.pyz",
        )


def test_production_seal_must_bind_the_installed_apps_to_the_same_commit(
    tmp_path: Path,
) -> None:
    source, commit = _isolated_source_tree(tmp_path)
    output = tmp_path / "apps"
    result = _build_apps(source, output, commit)
    assert result.returncode == 0, result.stderr
    installed_bin = source / "bin"
    installed_bin.mkdir()
    for name in (
        "catalog-requester-client.pyz",
        "catalog-requester-client.manifest.json",
        "catalog-requester-broker.pyz",
        "catalog-requester-broker.manifest.json",
    ):
        shutil.copyfile(output / name, installed_bin / name)
    manifests = {
        kind: json.loads(
            (installed_bin / f"catalog-requester-{kind}.manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for kind in ("client", "broker")
    }
    seal = CatalogRequesterProductionSealV1.create(
        protected_commit_sha="f" * 40,
        bootstrap_receipt_sha256="1" * 64,
        requester_client_application_sha256=manifests["client"][
            "application_sha256"
        ],
        requester_broker_application_sha256=manifests["broker"][
            "application_sha256"
        ],
        sealed_at=datetime(2026, 8, 22, 12, 0, tzinfo=UTC),
    )
    (source / "config/production-enabled-v1.seal.json").write_bytes(
        canonical_model_bytes(seal) + b"\n"
    )

    with pytest.raises(ValueError, match="REQUESTER_PRODUCTION_COMMIT_MISMATCH"):
        verify_installed_requester_application(
            broker_root=source,
            application_kind="client",
            application_path=installed_bin / "catalog-requester-client.pyz",
        )


def _run_powershell_script(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path),
            *arguments,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_installers_are_non_mutating_dry_runs_by_default() -> None:
    for path, identity in (
        (AGENT_INSTALLER, "AURORAAgent"),
        (BROKER_INSTALLER, "AURORARequester"),
    ):
        result = _run_powershell_script(path)
        assert result.returncode == 0, result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["schema_version"] == "1"
        assert receipt["mode"] == "dry_run"
        assert receipt["mutation_performed"] is False
        assert receipt["target_identity"] == identity
        assert receipt["production_enabled"] is False
        if identity == "AURORAAgent":
            assert receipt["repository_access"] == "unproven_until_codex_host_audit"
            assert (
                receipt["browser_profile_or_connector"]
                == "unproven_until_codex_host_audit"
            )
            assert (
                receipt["inherited_user_credentials"]
                == "unproven_until_codex_host_audit"
            )


def test_installers_reject_apply_without_exact_confirmation() -> None:
    for path in (AGENT_INSTALLER, BROKER_INSTALLER):
        result = _run_powershell_script(path, "-Apply")
        assert result.returncode != 0
        assert "CONFIRMATION_REQUIRED" in result.stderr


def test_installers_generate_passwords_with_windows_powershell_51_api() -> None:
    for path in (AGENT_INSTALLER, BROKER_INSTALLER):
        source = path.read_text(encoding="utf-8")
        assert "[Security.Cryptography.RandomNumberGenerator]::Fill" not in source
        assert "[Security.Cryptography.RandomNumberGenerator]::Create()" in source
        assert "$Generator.GetBytes($bytes)" in source
        assert "$Generator.Dispose()" in source


def test_broker_retry_uses_boolean_set_local_user_parameters() -> None:
    source = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "-PasswordNeverExpires $true" in source
    assert "-UserMayChangePassword $false" in source
    assert (
        "Set-LocalUser -Name $TargetIdentity -Password $TaskPassword `\n"
        "        -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword"
        not in source
    )


def test_broker_runs_inline_python_verifiers_from_protected_files() -> None:
    source = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "-c $DependencyInventoryVerifier" not in source
    assert "-c $FingerprintVerifier" not in source
    assert "$DependencyVerifierPath" in source
    assert "$FingerprintVerifierPath" in source
    assert "BLOCKED_REQUESTER_VERIFIER_ACL_APPLY_FAILED" in source
    assert source.count(
        "Remove-Item -LiteralPath $DependencyVerifierPath"
    ) == 1


def test_broker_read_only_acl_check_rejects_only_mutating_rights() -> None:
    source = BROKER_INSTALLER.read_text(encoding="utf-8")
    block = source.split("$ForbiddenReadOnlyRights = (", 1)[1].split(")", 1)[0]
    for right in (
        "WriteData",
        "AppendData",
        "WriteExtendedAttributes",
        "WriteAttributes",
        "Delete",
        "DeleteSubdirectoriesAndFiles",
        "ChangePermissions",
        "TakeOwnership",
    ):
        assert f"FileSystemRights]::{right}" in block
    assert "FileSystemRights]::FullControl" not in block
    assert "FileSystemRights]::Modify" not in block
    assert "FileSystemRights]::Write -bor" not in block
    assert source.count(
        "Remove-Item -LiteralPath $FingerprintVerifierPath"
    ) == 1


def test_broker_registers_task_with_windows_resolved_account_name() -> None:
    source = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "$InstalledUser.SID.Translate(" in source
    assert "[Security.Principal.NTAccount]" in source
    assert "BLOCKED_REQUESTER_ACCOUNT_NAME_INVALID" in source
    assert "New-ScheduledTaskPrincipal -UserId $TargetAccountName" in source
    assert "[PSCredential]::new($TargetAccountName, $TaskPassword)" in source
    assert '[PSCredential]::new(".\\$TargetIdentity", $TaskPassword)' not in source


def test_broker_installer_finishes_read_only_preflight_before_stopping_service() -> None:
    source = BROKER_INSTALLER.read_text(encoding="utf-8")
    stop = source.index("Stop-ScheduledTask -TaskName $TaskName")
    assert source.index("BLOCKED_REQUESTER_STAGED_APPLICATION_MISMATCH") < stop
    assert source.index("BLOCKED_REQUESTER_BROKER_APP_BINDING_MISSING") < stop
    assert "status --porcelain=v1 --untracked-files=no" in source
    assert "$ExistingProductionSealItem = Get-Item" in source
    assert source.index("$ExistingProductionSealItem = Get-Item") < stop


def test_installers_have_closed_accounts_paths_and_hidden_task() -> None:
    agent = AGENT_INSTALLER.read_text(encoding="utf-8")
    broker = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "AURORAAgent" in agent
    assert "AURORARequester" not in agent
    assert "AURORARequester" in broker
    assert "C:\\ProgramData\\AURORA\\CatalogRequester" in broker
    assert "AURORA Catalog Requester Broker" in broker
    assert "-WindowStyle Hidden" in broker
    assert "catalog-requester-broker.pyz" in broker
    assert "catalog-requester-client.pyz" in broker
    for source in (agent, broker):
        assert "Invoke-Expression" not in source
        assert "iex " not in source.casefold()


def test_broker_installer_rebuilds_twice_and_enforces_batch_only_logon() -> None:
    broker = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "Invoke-VerifiedRequesterBuild" in broker
    assert "BLOCKED_REQUESTER_BUILD_NONDETERMINISTIC" in broker
    assert "BLOCKED_REQUESTER_STAGED_APPLICATION_MISMATCH" in broker
    assert "build_catalog_requester_apps.py" in broker
    assert "SeBatchLogonRight" in broker
    assert "SeDenyBatchLogonRight" in broker
    assert "SeDenyInteractiveLogonRight" in broker
    assert "SeDenyRemoteInteractiveLogonRight" in broker
    assert "SeDebugPrivilege" in broker
    assert "SeTakeOwnershipPrivilege" in broker
    assert '$Right -notin $RequiredRights' in broker
    assert "BLOCKED_REQUESTER_BROKER_LOGON_RIGHTS_INVALID" in broker


def test_broker_retries_only_explicit_transient_failures_without_exiting() -> None:
    source = BROKER_CLI.read_text(encoding="utf-8")
    assert "def _broker_main() -> int:" in source
    assert "REQUESTER_POST_RECONCILIATION_RETRYABLE" in source
    assert "REQUESTER_GITHUB_TRANSIENT_FAILURE" in source
    assert "retry_delay_seconds = min(" in source
    assert "60 * (2 ** min(consecutive_failures - 1, 4))" in source
    assert "os.close(_broker_lock_descriptor)" in source


def test_broker_rejects_every_github_cli_admin_credential_environment() -> None:
    source = BROKER_CLI.read_text(encoding="utf-8")
    for variable in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "GH_CONFIG_DIR",
        "XDG_CONFIG_HOME",
    ):
        assert f'"{variable}"' in source


def test_broker_rejects_requester_and_auditor_credential_environments() -> None:
    source = BROKER_CLI.read_text(encoding="utf-8")
    for variable in (
        "AURORA_CATALOG_REQUESTER_PRIVATE_KEY",
        "AURORA_CATALOG_REQUESTER_PRIVATE_KEY_PATH",
        "AURORA_CATALOG_REQUESTER_JWT",
        "AURORA_CATALOG_REQUESTER_TOKEN",
    ):
        assert f'"{variable}"' in source
    for variable in (
        "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
        "AURORA_CATALOG_AUDITOR_PRIVATE_KEY_PATH",
        "AURORA_CATALOG_AUDITOR_JWT",
        "AURORA_CATALOG_AUDITOR_TOKEN",
        "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
    ):
        assert f'"{variable}"' in source


def test_client_rejects_every_github_cli_admin_credential_environment() -> None:
    source = CLIENT_CLI.read_text(encoding="utf-8")
    for variable in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "GH_CONFIG_DIR",
        "XDG_CONFIG_HOME",
    ):
        assert f'"{variable}"' in source
    assert "AGENT_ADMIN_CREDENTIAL_EXPOSED" in source
    assert ".config/gh/hosts.yml" in source
    assert "AppData/Roaming/GitHub CLI/hosts.yml" in source


def test_client_rejects_requester_and_auditor_credential_environments() -> None:
    source = CLIENT_CLI.read_text(encoding="utf-8")
    for variable in (
        "AURORA_CATALOG_REQUESTER_APP_ID",
        "AURORA_CATALOG_REQUESTER_INSTALLATION_ID",
        "AURORA_CATALOG_REQUESTER_PRIVATE_KEY",
        "AURORA_CATALOG_REQUESTER_PRIVATE_KEY_PATH",
        "AURORA_CATALOG_REQUESTER_JWT",
        "AURORA_CATALOG_REQUESTER_TOKEN",
    ):
        assert f'"{variable}"' in source
    assert "AGENT_REQUESTER_CREDENTIAL_EXPOSED" in source
    for variable in (
        "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
        "AURORA_CATALOG_AUDITOR_PRIVATE_KEY_PATH",
        "AURORA_CATALOG_AUDITOR_JWT",
        "AURORA_CATALOG_AUDITOR_TOKEN",
        "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
    ):
        assert f'"{variable}"' in source
    assert "AGENT_AUDITOR_CREDENTIAL_EXPOSED" in source


def test_requester_app_binding_is_service_only_not_machinewide() -> None:
    installer = BROKER_INSTALLER.read_text(encoding="utf-8")
    broker_cli = BROKER_CLI.read_text(encoding="utf-8")
    assert "requester-app-binding-v1.json" in installer
    assert "requester-app-binding-v1.json" in broker_cli
    assert 'SetEnvironmentVariable($VariableName, $null, "Machine")' in installer
    assert "REQUESTER_APP_BINDING_INVALID" in broker_cli
    assert "REQUESTER_BROKER_ENVIRONMENT_EXPOSED" in broker_cli
    for variable in (
        "AURORA_CATALOG_REQUESTER_APP_ID",
        "AURORA_CATALOG_REQUESTER_INSTALLATION_ID",
        "AURORA_CATALOG_REQUESTER_PRIVATE_KEY_PATH",
    ):
        assert f'"{variable}"' in broker_cli
    assert 'os.environ.get("AURORA_CATALOG_REQUESTER_APP_ID"' not in broker_cli
    assert (
        'os.environ.get("AURORA_CATALOG_REQUESTER_INSTALLATION_ID"'
        not in broker_cli
    )
    assert 'os.environ.get("AURORA_CATALOG_REQUESTER_PRIVATE_KEY_PATH"' not in (
        broker_cli
    )


def test_broker_installer_verifies_existing_app_binding_before_trusting_it() -> None:
    installer = BROKER_INSTALLER.read_text(encoding="utf-8")
    acl_check = "Assert-ClosedAcl -Path $AppBindingPath"
    binding_read = "$ExistingBindingBytes = [IO.File]::ReadAllBytes($AppBindingPath)"
    assert acl_check in installer
    assert binding_read in installer
    assert installer.index(acl_check) < installer.index(binding_read)
    assert "BLOCKED_REQUESTER_APP_BINDING_EXISTING_ACL_INVALID" in installer
    assert "BLOCKED_REQUESTER_APP_BINDING_NONCANONICAL" in installer


def test_broker_retry_wrapper_releases_lock_and_restarts_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurora.infra.sp500_megarun import catalog_requester_broker_cli as cli

    attempts = 0
    sleeps: list[float] = []

    def fake_broker_main() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("REQUESTER_GITHUB_TRANSIENT_FAILURE")
        return 23

    descriptor = os.open(tmp_path / "broker.lock", os.O_WRONLY | os.O_CREAT)
    cli._broker_lock_descriptor = descriptor
    monkeypatch.setattr(cli, "_broker_main", fake_broker_main)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    try:
        assert cli.main() == 23
        with pytest.raises(OSError):
            os.fstat(descriptor)
    finally:
        cli._broker_lock_descriptor = None
        try:
            os.close(descriptor)
        except OSError:
            pass

    assert attempts == 2
    assert sleeps == [60]


def test_broker_retry_wrapper_honors_provider_retry_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurora.infra.sp500_megarun import catalog_requester_broker_cli as cli

    class ProviderDelay(ValueError):
        retry_after_seconds = 600

    attempts = 0
    sleeps: list[float] = []

    def fake_broker_main() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ProviderDelay("REQUESTER_GITHUB_TRANSIENT_FAILURE")
        return 29

    monkeypatch.setattr(cli, "_broker_main", fake_broker_main)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    assert cli.main() == 29
    assert attempts == 2
    assert sleeps == [600]


def test_broker_installer_rejects_any_unexpected_ntfs_acl_identity() -> None:
    broker = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "Assert-ClosedAcl" in broker
    assert "ReadOnlySids" in broker
    assert "FileSystemRights" in broker
    assert "ChangePermissions" in broker
    assert "TakeOwnership" in broker
    assert "GetAccessRules" in broker
    assert "AreAccessRulesProtected" in broker
    assert "$StagingAclPaths" in broker
    assert "BLOCKED_REQUESTER_BROKER_STAGED_ITEM_ACL_NOT_CLOSED" in broker
    assert "BLOCKED_REQUESTER_BROKER_ACL_NOT_CLOSED" in broker
    assert "BLOCKED_REQUESTER_BROKER_STAGING_ACL_NOT_CLOSED" in broker


def test_broker_installer_cannot_upgrade_live_production_and_reads_back_task() -> None:
    broker = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "BLOCKED_REQUESTER_BROKER_PRODUCTION_ALREADY_SEALED" in broker
    assert "Get-ScheduledTask" in broker
    assert "Stop-ScheduledTask" in broker
    assert "BLOCKED_REQUESTER_BROKER_TASK_STILL_RUNNING" in broker
    assert "BLOCKED_REQUESTER_BROKER_TASK_READBACK_INVALID" in broker


def test_broker_task_runs_continuously_on_a_laptop_and_catches_missed_start() -> None:
    broker = BROKER_INSTALLER.read_text(encoding="utf-8")
    for setting in (
        "-AllowStartIfOnBatteries",
        "-DontStopIfGoingOnBatteries",
        "-StartWhenAvailable",
        "DisallowStartIfOnBatteries",
        "StopIfGoingOnBatteries",
        "StartWhenAvailable",
    ):
        assert setting in broker


def test_agent_installer_reports_only_prepared_before_real_host_restart() -> None:
    agent = AGENT_INSTALLER.read_text(encoding="utf-8")
    assert (
        '$Plan.final_capability_result = '
        '"PREPARED_RESTART_AND_PROCESS_AUDIT_REQUIRED"'
        in agent
    )
    assert "AGENT_ISOLATION_VERIFIED" not in agent


def test_broker_installer_reuses_only_the_same_installed_private_key() -> None:
    broker = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "BLOCKED_REQUESTER_KEY_ROTATION_UNSAFE" in broker
    assert "isinstance(private_key, rsa.RSAPrivateKey)" in broker
    assert "private_key.key_size < 2048" in broker
    assert "public_key.verify(" in broker
    assert "$InstalledPrivateKeyExists" in broker
    assert "$KeyToVerify" in broker
    assert "Remove-Item -LiteralPath $StagedPrivateKey" in broker
    assert "BLOCKED_REQUESTER_PRIVATE_KEY_EXISTING_ACL_INVALID" in broker
    assert broker.index("BLOCKED_REQUESTER_PRIVATE_KEY_EXISTING_ACL_INVALID") < (
        broker.index("$KeyToVerify")
    )


def test_broker_installer_recreates_and_audits_exact_venv_inventories() -> None:
    broker = BROKER_INSTALLER.read_text(encoding="utf-8")
    assert "-m venv --clear $ClientVenv" in broker
    assert "-m venv --clear $BrokerVenv" in broker
    assert "$DependencyInventoryVerifier" in broker
    assert "from importlib import metadata" in broker
    assert 'distribution.read_text("direct_url.json")' in broker
    assert 'site_root.glob("*.pth")' in broker
    assert "BLOCKED_REQUESTER_CLIENT_DEPENDENCY_INVENTORY_INVALID" in broker
    assert "BLOCKED_REQUESTER_BROKER_DEPENDENCY_INVENTORY_INVALID" in broker
    assert "client_dependency_inventory_sha256" in broker
    assert "broker_dependency_inventory_sha256" in broker
