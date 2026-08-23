from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID
import zipfile

import pytest

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    append_authority_record,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_routing_snapshot import (
    build_catalog_routing_bundle,
)
from scripts.capture_catalog_routing_snapshot import (
    _record_from_mirror_zip,
    _request_receipt_orphan_from_slot,
    _request_receipt_bundle_from_mirror_zip,
    _request_receipt_from_mirror_zip,
    _write_bundle,
)
from test_catalog_routing_snapshot import (
    ACTOR,
    AUTHORITY_NUMBER,
    HEAD,
    NOW,
    REPOSITORY,
    _authority_issue,
    _repository,
    _request_issue,
    _request_receipt,
    _timeline,
)


ROOT = Path(__file__).resolve().parents[1]


def _record():
    return append_authority_record(
        previous=None,
        authority_id=UUID("018f47a2-6e91-7c34-8000-000000000101"),
        request_issue_number=101,
        campaign_id="c" * 64,
        request_sha256="1" * 64,
        science_sha256="2" * 64,
        execution_plan_sha256="3" * 64,
        execution_protocol_sha256="4" * 64,
        state=AuthorityState.RESERVED,
        run_id=123,
        run_attempt=1,
        writer_job_id="reserve",
        writer_job_database_id=456,
        protected_commit_sha="5" * 40,
        created_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
    )


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return target.getvalue()


def _bundle(tmp_path: Path):
    root, request, title, _ = _repository(tmp_path)
    request_issue = _request_issue(request, title)
    authority_issue = _authority_issue()
    return build_catalog_routing_bundle(
        repo_root=root,
        repository_snapshot={"full_name": REPOSITORY, "node_id": "R_repo"},
        repository_variable_number=str(AUTHORITY_NUMBER),
        protected_head_sha=HEAD,
        expected_protected_commit_sha=HEAD,
        request_issue=request_issue,
        open_issues=(request_issue,),
        request_comments=(),
        request_timeline=_timeline(request_issue),
        authority_issue=authority_issue,
        authority_comments=(),
        authority_timeline=_timeline(authority_issue),
        writer_run_snapshots=(),
        artifact_records=(),
        checkpoints=(),
        tamper_incidents=(),
        active_owner_authority_ids=(),
        observed_at=NOW,
        snapshot_source_sha256="7" * 64,
    )


def test_capture_cli_has_no_arbitrary_network_or_command_surface() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/capture_catalog_routing_snapshot.py"),
            "--help",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--issue-number" in result.stdout
    for forbidden in ("--repository", "--url", "--token", "--command", "--workflow"):
        assert forbidden not in result.stdout


def test_mirror_zip_accepts_only_one_exact_canonical_record() -> None:
    record = _record()
    archive = _zip_bytes({"record.json": canonical_model_bytes(record) + b"\n"})

    assert _record_from_mirror_zip(archive) == record


@pytest.mark.parametrize(
    "files",
    (
        {"../record.json": b"{}"},
        {"record.json": b"{}", "extra.json": b"{}"},
        {"nested/record.json": b"{}"},
        {"record.json": b"x" * (128 * 1024 + 1)},
    ),
)
def test_mirror_zip_rejects_traversal_extras_and_oversize(
    files: dict[str, bytes],
) -> None:
    with pytest.raises(ValueError, match="CATALOG_LEDGER_MIRROR_ARTIFACT_INVALID"):
        _record_from_mirror_zip(_zip_bytes(files))


def test_mirror_zip_rejects_noncanonical_or_duplicate_json() -> None:
    record = _record()
    payload = record.model_dump(mode="json")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    duplicated = raw[:-1] + ',"schema_version":"1"}'

    with pytest.raises(ValueError, match="CATALOG_LEDGER_MIRROR_ARTIFACT_INVALID"):
        _record_from_mirror_zip(_zip_bytes({"record.json": duplicated.encode()}))


def test_request_receipt_mirror_zip_accepts_the_exact_recoverable_bundle() -> None:
    receipt = _request_receipt("1" * 64)
    summary = "Solicitud aplazada por capacidad ocupada."
    comment = receipt.comment_body(summary)
    archive = _zip_bytes(
        {
            "request-receipt.json": canonical_model_bytes(receipt) + b"\n",
            "comment.md": comment.encode("utf-8"),
        }
    )
    assert _request_receipt_from_mirror_zip(archive) == receipt
    assert _request_receipt_bundle_from_mirror_zip(archive) == (receipt, comment)
    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_MIRROR_INVALID"):
        _request_receipt_from_mirror_zip(
            _zip_bytes({"receipt.json": canonical_model_bytes(receipt)})
        )
    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_MIRROR_INVALID"):
        _request_receipt_bundle_from_mirror_zip(
            _zip_bytes(
                {
                    "request-receipt.json": canonical_model_bytes(receipt) + b"\n",
                    "comment.md": b"not the sealed comment\n",
                }
            )
        )


def test_write_bundle_is_canonical_complete_and_emits_only_bounded_outputs(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    output_dir = tmp_path / "routing"
    github_output = tmp_path / "github-output.txt"
    _write_bundle(
        output_dir=output_dir,
        bundle=bundle,
        github_output=github_output,
    )

    assert sorted(path.name for path in output_dir.iterdir()) == [
        "authority-comments.json",
        "authority-issue.json",
        "event.json",
        "protected-head.json",
        "request-queue.json",
        "request-receipts.json",
        "request-timeline.json",
        "routing-command.json",
        "routing-snapshot.json",
    ]
    for path in output_dir.iterdir():
        raw = path.read_bytes()
        assert raw.endswith(b"\n")
        assert json.loads(raw) is not None
        assert raw == json.dumps(
            json.loads(raw),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"
    lines = github_output.read_text(encoding="utf-8").splitlines()
    assert [line.split("=", 1)[0] for line in lines] == [
        "snapshot_sha256",
        "request_sha256",
        "campaign_id",
        "applicable_commit_sha",
        "request_receipt_orphan",
    ]
    assert all("token" not in line.lower() and "url" not in line.lower() for line in lines)


def test_write_bundle_preserves_one_exact_recoverable_orphan(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    receipt = _request_receipt(bundle.command.request_sha256)
    comment = receipt.comment_body("Solicitud aplazada por capacidad ocupada.")
    metadata = {
        "artifact_id": 123,
        "artifact_name": receipt.artifact_name,
        "receipt_sha256": receipt.receipt_sha256,
        "comment_sha256": hashlib.sha256(comment.encode("utf-8")).hexdigest(),
        "delivery_sequence": receipt.delivery_sequence,
    }
    output_dir = tmp_path / "routing-orphan"
    github_output = tmp_path / "github-output-orphan.txt"

    _write_bundle(
        output_dir=output_dir,
        bundle=bundle,
        github_output=github_output,
        orphan_request_receipt=receipt,
        orphan_request_comment=comment,
        orphan_artifact_metadata=metadata,
    )

    assert (output_dir / "request-receipt-orphan.json").read_bytes() == (
        canonical_model_bytes(receipt) + b"\n"
    )
    assert (output_dir / "request-receipt-orphan-comment.md").read_text(
        "utf-8"
    ) == comment
    assert json.loads(
        (output_dir / "request-receipt-orphan-artifact.json").read_text("utf-8")
    ) == metadata
    assert github_output.read_text("utf-8").splitlines()[-1] == (
        "request_receipt_orphan=true"
    )


def test_write_bundle_rejects_mismatched_orphan_metadata(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    receipt = _request_receipt(bundle.command.request_sha256)
    comment = receipt.comment_body("Solicitud aplazada por capacidad ocupada.")
    metadata = {
        "artifact_id": 123,
        "artifact_name": receipt.artifact_name,
        "receipt_sha256": "f" * 64,
        "comment_sha256": hashlib.sha256(comment.encode("utf-8")).hexdigest(),
        "delivery_sequence": receipt.delivery_sequence,
    }
    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_ORPHAN_INVALID"):
        _write_bundle(
            output_dir=tmp_path / "routing-invalid-orphan",
            bundle=bundle,
            github_output=None,
            orphan_request_receipt=receipt,
            orphan_request_comment=comment,
            orphan_artifact_metadata=metadata,
        )


def test_next_receipt_slot_detects_one_orphan_and_rejects_duplicates(
    monkeypatch,
) -> None:
    receipt = _request_receipt("1" * 64)
    comment = receipt.comment_body("Solicitud aplazada por capacidad ocupada.")
    archive = _zip_bytes(
        {
            "request-receipt.json": canonical_model_bytes(receipt) + b"\n",
            "comment.md": comment.encode("utf-8"),
        }
    )
    monkeypatch.setattr(
        "scripts.capture_catalog_routing_snapshot._download_artifact_zip",
        lambda repository, artifact_id: archive,
    )
    row = {"id": 345, "name": receipt.artifact_name, "expired": False}
    selected = _request_receipt_orphan_from_slot(
        repository=REPOSITORY,
        artifact_name=receipt.artifact_name,
        artifacts=(row,),
        issue_number=receipt.issue_number,
        request_sha256=receipt.request_sha256,
        delivery_sequence=receipt.delivery_sequence,
    )
    assert selected[0] == receipt
    assert selected[1] == comment
    assert selected[2]["artifact_id"] == 345

    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_MIRROR_CONFLICT"):
        _request_receipt_orphan_from_slot(
            repository=REPOSITORY,
            artifact_name=receipt.artifact_name,
            artifacts=(row, {**row, "id": 346}),
            issue_number=receipt.issue_number,
            request_sha256=receipt.request_sha256,
            delivery_sequence=receipt.delivery_sequence,
        )
