from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.execution_policy import LocalRunBlocked
from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts import restore_gtbi_v6_artifact as restore_module
from scripts.generate_gtbi_v7_g3b_preservation_owner_receipt import (
    MANIFEST,
    RECEIPT,
    build_receipt,
)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _live_snapshot(receipt: dict) -> dict:
    artifact = receipt["lease_artifact"]
    run = receipt["preservation_run"]
    return {
        "artifact": {
            "id": artifact["id"],
            "name": artifact["name"],
            "size_in_bytes": artifact["size_in_bytes"],
            "digest": artifact["digest"],
            "created_at": artifact["created_at_utc"],
            "expires_at": artifact["expires_at_utc"],
            "expired": artifact["expired"],
        },
        "run": {
            "id": run["id"],
            "html_url": run["url"],
            "head_sha": run["head_sha"],
            "status": run["status"],
            "conclusion": run["conclusion"],
            "path": run["workflow_path"],
        },
    }


def test_owner_preservation_receipt_is_canonical_and_reproducible() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_G3B_OWNER_PRESERVATION_LIVE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert (
        build_receipt(
            _live_snapshot(receipt),
            observed_at_utc=receipt["observed_at_utc"],
        )
        == receipt
    )
    assert receipt["evaluation"] == {"ready": True, "blockers": []}
    assert receipt["lease_artifact"]["expired"] is False
    assert receipt["external_copy_required"] is False
    assert receipt["github_only"] is True
    assert receipt["requires_local_machine"] is False
    assert receipt["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "local_research_run_performed": False,
    }


def test_owner_preservation_transition_closes_only_prev7_0208() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert manifest["manifest_digest"] == domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    assert manifest["task_actions"] == [
        {
            **manifest["task_actions"][0],
            "task_id": "PREV7-0208",
            "target_status": "done",
        }
    ]
    assert manifest["branch_actions"] == []
    assert manifest["gate_actions"] == []


def _synthetic_restore_fixture(tmp_path: Path) -> tuple[Path, Path, dict, list[dict]]:
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    payloads = [b"verified-", b"archive"]
    parts = []
    for index, payload in enumerate(payloads):
        filename = f"part-{index:02d}.bin"
        (parts_dir / filename).write_bytes(payload)
        parts.append(
            {
                "part_index": index,
                "filename": filename,
                "size_bytes": len(payload),
                "sha256": _sha256(payload),
            }
        )
    archive = b"".join(payloads)
    manifest = {
        "preservation_manifest_digest": "sha256:" + "1" * 64,
        "source_size_bytes": len(archive),
        "source_archive_digest": _sha256(archive),
    }
    members = [{"path": "fixture.txt", "size_bytes": len(archive)}]
    receipt = {
        "preservation_manifest_digest": manifest["preservation_manifest_digest"],
        "parts": parts,
        "members": members,
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return parts_dir, receipt_path, manifest, members


def test_restore_procedure_reconstructs_and_verifies_synthetic_parts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts_dir, receipt_path, manifest, members = _synthetic_restore_fixture(tmp_path)
    monkeypatch.setattr(restore_module, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(restore_module, "load_and_verify_manifest", lambda: manifest)
    monkeypatch.setattr(
        restore_module,
        "inspect_archive",
        lambda _path, _manifest: {"member_count": 1, "members": members},
    )

    result = restore_module.restore(parts_dir, receipt_path, tmp_path / "restored")
    assert result["source_archive_digest"] == manifest["source_archive_digest"]
    assert result["member_manifest_match"] is True
    assert (tmp_path / "restored/restore_receipt.json").exists()


def test_restore_procedure_rejects_tampered_part(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts_dir, receipt_path, manifest, _members = _synthetic_restore_fixture(tmp_path)
    (parts_dir / "part-01.bin").write_bytes(b"tampered")
    monkeypatch.setattr(restore_module, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(restore_module, "load_and_verify_manifest", lambda: manifest)
    with pytest.raises(restore_module.PreservationError, match="part mismatch"):
        restore_module.restore(parts_dir, receipt_path, tmp_path / "restored")


def test_restore_procedure_is_blocked_outside_github_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(LocalRunBlocked, match="GitHub-only"):
        restore_module.restore(
            tmp_path / "parts",
            tmp_path / "receipt.json",
            tmp_path / "restored",
        )
