"""Exercise the installer's real subprocess verifier against actual built apps."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import shutil
import subprocess
import venv

import pytest

from scripts.prepare_catalog_chat_maintenance import prepare_package
from tests.test_catalog_chat_maintenance_package import ROOT, _baseline, _source


def _quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def test_installer_subprocess_verifies_both_real_packaged_apps(tmp_path: Path) -> None:
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required")
    # The developer interpreter may resolve dependencies from user-site, which
    # the real installer's mandatory -I correctly excludes. Give this local
    # test its own isolated runtime; never alter the installed protected one.
    runtime_root = tmp_path / "verifier-runtime"
    venv.EnvBuilder(with_pip=False).create(runtime_root)
    site_packages = runtime_root / "Lib/site-packages"
    for name in ("pydantic", "pydantic_core", "typing_extensions", "annotated_types", "typing_inspection"):
        spec = importlib.util.find_spec(name)
        assert spec is not None and spec.origin is not None, name
        origin = Path(spec.origin)
        if spec.submodule_search_locations is not None:
            shutil.copytree(origin.parent, site_packages / name)
        else:
            shutil.copy2(origin, site_packages / origin.name)
    runtime = runtime_root / "Scripts/python.exe"
    source, commit = _source(tmp_path)
    baseline, ready_hash, seal_hash = _baseline(tmp_path)
    output = tmp_path / "candidate"
    prepare_package(
        source_root=source, output_dir=output, expected_commit_sha=commit,
        baseline_root=baseline, expected_ready_file_sha256=ready_hash,
        expected_seal_file_sha256=seal_hash,
    )
    root = output / "verification/CatalogRequester"
    script = tmp_path / "real-verifier.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f". {_quote(ROOT / 'scripts/install_catalog_chat_entry.ps1')}\n"
        f"$runtime = {_quote(runtime)}\n"
        f"$root = {_quote(root)}\n"
        f"$commit = {_quote(commit)}\n"
        "$client = Invoke-CatalogChatEntryVerifierProcess -RuntimePython $runtime -ApplicationKind client -VerificationRoot $root -ExpectedCommitSha $commit\n"
        "$broker = Invoke-CatalogChatEntryVerifierProcess -RuntimePython $runtime -ApplicationKind broker -VerificationRoot $root -ExpectedCommitSha $commit\n"
        "$rejected = $false\n"
        "try { $null = Invoke-CatalogChatEntryVerifierProcess -RuntimePython $runtime -ApplicationKind client -VerificationRoot $root -ExpectedCommitSha ('0' * 40) }\n"
        "catch { $rejected = $_.Exception.Message -eq 'OFFICIAL_VERIFIER_BINDING_INVALID:client' }\n"
        "[pscustomobject]@{ client = $client; broker = $broker; wrong_commit_rejected = $rejected } | ConvertTo-Json -Depth 5 -Compress\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(script)],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    for kind in ("client", "broker"):
        assert result[kind]["application_kind"] == kind
        assert result[kind]["protected_commit_sha"] == commit
    assert result["wrong_commit_rejected"] is True
