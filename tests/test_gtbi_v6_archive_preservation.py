from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import jsonschema
import pytest

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.preserve_gtbi_v6_artifact import (
    DOMAIN,
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
    with pytest.raises(PreservationError, match="GitHub Actions-only"):
        preserve(tmp_path / "output", "unused-token")
