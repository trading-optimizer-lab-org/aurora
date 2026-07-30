from __future__ import annotations

import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import jsonschema
import pytest
import yaml

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.preserve_gtbi_v6_artifact import (
    DOMAIN,
    LocalRunBlocked,
    MANIFEST_PATH,
    PreservationError,
    inspect_archive,
    load_and_verify_manifest,
    preserve,
    split_archive,
    verify_remote_metadata,
)

ROOT = Path(__file__).resolve().parents[1]


def _limits() -> dict:
    return {
        "maximum_member_count": 10,
        "maximum_total_uncompressed_bytes": 10000,
        "maximum_compression_ratio": 100,
    }


def test_fixed_manifest_and_schema_are_canonical_and_valid() -> None:
    manifest = load_and_verify_manifest()
    expected = domain_digest(
        DOMAIN,
        manifest,
        omit_top_level_fields=("preservation_manifest_digest",),
    )
    assert manifest["preservation_manifest_digest"] == expected
    assert manifest["source_artifact_id"] == 8251391531
    assert manifest["source_run_id"] == 29162930823
    assert MANIFEST_PATH.read_bytes() == canonical_bytes(manifest) + b"\n"
    schema_path = (
        ROOT
        / "config/gtbi/schemas/v7/operational/"
        "v6_preservation_manifest_v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(manifest, schema)


def test_remote_metadata_must_match_every_frozen_identity_field() -> None:
    manifest = load_and_verify_manifest()
    metadata = {
        "id": manifest["source_artifact_id"],
        "name": manifest["source_artifact_name"],
        "size_in_bytes": manifest["source_size_bytes"],
        "digest": manifest["source_archive_digest"],
        "expires_at": manifest["source_expires_at_utc"],
        "expired": False,
        "workflow_run": {"id": manifest["source_run_id"]},
    }
    verify_remote_metadata(metadata, manifest)
    metadata["name"] = "substituted"
    with pytest.raises(PreservationError, match="metadata mismatch"):
        verify_remote_metadata(metadata, manifest)


def test_zip_is_stream_inspected_and_split_without_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr("a.txt", b"alpha")
        out.writestr("nested/b.txt", b"bravo")
    inspection = inspect_archive(archive, _limits())
    assert inspection["member_count"] == 2
    assert {row["path"] for row in inspection["members"]} == {
        "a.txt",
        "nested/b.txt",
    }
    parts = split_archive(archive, tmp_path / "parts", 10)
    assert len(parts) > 1
    reconstructed = b"".join(
        (tmp_path / "parts" / part["filename"]).read_bytes() for part in parts
    )
    assert reconstructed == archive.read_bytes()


def test_zip_rejects_path_traversal_and_symlink(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as out:
        out.writestr("../escape.txt", b"no")
    with pytest.raises(PreservationError, match="unsafe ZIP"):
        inspect_archive(traversal, _limits())

    symlink = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink, "w") as out:
        out.writestr(info, "target")
    with pytest.raises(PreservationError, match="symlink"):
        inspect_archive(symlink, _limits())


def test_heavy_preservation_is_rejected_outside_github_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(LocalRunBlocked, match="GitHub-only"):
        preserve(tmp_path / "output", "unused-token")


def test_registered_workflow_has_isolated_fixed_preservation_mode() -> None:
    workflow_path = (
        ROOT
        / ".github/workflows/"
        "global-technical-buy-indicator-external-pack-360jobs.yml"
    )
    text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    jobs = workflow["jobs"]
    preservation = jobs["preserve_v6_artifact"]

    assert preservation["runs-on"] == "ubuntu-24.04"
    assert preservation["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert "__preserve_v6_artifact__" in preservation["if"]
    assert any(
        step.get("run", "").startswith(
            "python scripts/preserve_gtbi_v6_artifact.py"
        )
        for step in preservation["steps"]
    )
    dependency_step = next(
        step
        for step in preservation["steps"]
        if step.get("name") == "Install preservation validator dependencies"
    )
    assert '"cryptography==48.0.0"' in dependency_step["run"]
    assert '"jsonschema==4.26.0"' in dependency_step["run"]
    upload = next(
        step
        for step in preservation["steps"]
        if step.get("name") == "Upload verified preservation lease"
    )
    assert upload["with"]["retention-days"] == 90
    assert upload["with"]["compression-level"] == 0
    assert upload["with"]["path"] == "preserved-v6"

    for job_id in ("plan", "build_external_pack", "run_shard", "merge"):
        condition = jobs[job_id]["if"]
        assert "__preserve_v6_artifact__" in condition
        assert "!=" in condition

    assert "self-hosted" not in text
    assert "C:\\" not in text


def test_preservation_entrypoint_loads_without_quant_engine_dependencies() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/preserve_gtbi_v6_artifact.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--output-dir" in result.stdout


def test_registered_workflow_has_isolated_strict_inventory_mode() -> None:
    workflow_path = (
        ROOT
        / ".github/workflows/"
        "global-technical-buy-indicator-external-pack-360jobs.yml"
    )
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    inventory = jobs["inventory_gtbi_v7"]

    assert inventory["runs-on"] == "ubuntu-24.04"
    assert inventory["permissions"] == {
        "actions": "read",
        "contents": "read",
        "deployments": "read",
        "packages": "read",
        "security-events": "read",
    }
    assert "__gtbi_v7_inventory__" in inventory["if"]
    command = next(
        step["run"]
        for step in inventory["steps"]
        if step.get("name") == "Generate strict bounded remote inventory"
    )
    assert "--mode remote" in command
    assert "--strict" in command
    upload = next(
        step
        for step in inventory["steps"]
        if step.get("name") == "Upload inventory evidence"
    )
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["retention-days"] == 30

    for job_id in ("plan", "build_external_pack", "run_shard", "merge"):
        condition = jobs[job_id]["if"]
        assert "__gtbi_v7_inventory__" in condition
        assert "!=" in condition
