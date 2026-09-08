"""Exercise maintenance subprocesses from built applications, without live writes."""

import base64
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import venv

import pytest

from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import parse_catalog_campaign_definition_bytes
from tests.test_catalog_lineage_migration import _disk_state
from tests.test_catalog_requester_packaging import _isolated_source_tree, _git, _build_apps, _install_built_apps


def test_installer_maintenance_subprocesses_use_real_isolated_packages(tmp_path: Path) -> None:
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required")
    runtime_root = tmp_path / "isolated-runtime"
    venv.EnvBuilder(with_pip=False).create(runtime_root)
    runtime_python = runtime_root / "Scripts/python.exe"
    site = runtime_root / "Lib/site-packages"
    dependency_lock = Path(__file__).resolve().parents[1] / "requirements/catalog-requester-broker-win-py314.lock"
    dependencies = {name.replace("-", "_") for name in re.findall(r"^([a-zA-Z0-9_-]+)==", dependency_lock.read_text(), re.MULTILINE)}
    for name in sorted(dependencies):
        distribution = importlib.metadata.distribution(name)
        for relative in distribution.files or ():
            if ".." in relative.parts or relative.is_absolute() or relative.suffix == ".pyc":
                continue
            assert relative.suffix != ".pth", "isolated runtime must not import external paths"
            destination = site.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(distribution.locate_file(relative)), destination)
    source, _ = _isolated_source_tree(tmp_path)
    live = tmp_path / "live"
    live.mkdir()
    config, public, approval, _ = _disk_state(live)
    registry = json.loads((source / "config/catalog_campaign_registry_v1.json").read_bytes())
    entry = next(row for row in registry["campaigns"] if row["campaign_key"] == approval.campaign_key)
    manifest = parse_catalog_campaign_definition_bytes((source / entry["definition_manifest_path"]).read_bytes())
    approval = approval.model_copy(update={"target_definition_sha256": manifest.campaign_definition_sha256,
        "target_prompt_sha256": hashlib.sha256((source / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()).hexdigest()})
    (source / "config/catalog_requester_public_key_v1.pem").write_bytes(public)
    (source / "config/catalog_lineage_transitions_v1.json").write_text(json.dumps({
        "schema_version": "1", "transitions": [approval.model_dump(mode="json")]}), encoding="utf-8")
    _git(source, "add", "config")
    _git(source, "commit", "-m", "synthetic approved boundary")
    output = tmp_path / "apps"
    built = _build_apps(source, output, _git(source, "rev-parse", "HEAD"))
    assert built.returncode == 0, built.stderr
    _install_built_apps(source, output)
    payload = tmp_path / "payload"
    payload.mkdir()
    candidate = source.rename(payload / "CatalogRequester")
    (live / "config").mkdir()
    (live / "config/catalog_requester_v1.json").write_text(config.model_dump_json(), encoding="utf-8")
    (live / "config/catalog_requester_public_key_v1.pem").write_bytes(public)
    (live / "chat-intents").mkdir()
    (live / "chat-replies").mkdir()
    (live / "chat-intents/.service.lock").touch()
    before = {p.relative_to(live): p.read_bytes() for p in live.rglob("*") if p.is_file()}
    installer = Path(__file__).resolve().parents[1] / "scripts/install_catalog_chat_entry.ps1"
    def quoted(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / "maintenance-processes.ps1"
    script.write_text(f"""
$ErrorActionPreference = 'Stop'
. {quoted(installer)}
$script:CatalogChatEntryRequesterRoot = {quoted(live)}
$records = Invoke-CatalogChatEntryLineageProcess -RuntimePython {quoted(runtime_python)} -VerificationRoot {quoted(candidate)} -BrokerRoot {quoted(live)}
$runtime = [pscustomobject]@{{ client_python = {quoted(runtime_python)} }}
$lock = [IO.File]::Open({quoted(live / 'chat-intents/.service.lock')}, 'Open', 'ReadWrite', 'None')
try {{ Invoke-CatalogChatEntryIdleProcess -VerificationRoot {quoted(candidate)} -Runtime $runtime }}
finally {{ $lock.Dispose() }}
$records | ConvertTo-Json -Depth 10 -Compress
""", encoding="utf-8")
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(script)],
        cwd=tmp_path, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)["records"]
    assert len(rows) == 3
    for row in rows:
        assert hashlib.sha256(base64.b64decode(row["content_base64"])).hexdigest() == row["sha256"]
    assert {p.relative_to(live): p.read_bytes() for p in live.rglob("*") if p.is_file()} == before
