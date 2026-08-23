from __future__ import annotations

from datetime import UTC, datetime
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from aurora.infra.sp500_megarun.catalog_mirror_delivery import (
    CatalogMirrorRepairClaimV1,
    CatalogMirrorRepairWriterContextV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from scripts import reconcile_catalog_mirror_delivery as delivery


PAYLOAD_SHA256 = "a" * 64
COMMIT_SHA = "b" * 40


def _claim(sequence: int = 0) -> CatalogMirrorRepairClaimV1:
    writer = CatalogMirrorRepairWriterContextV1(
        run_id=1000 + sequence,
        run_attempt=1,
        writer_job_id="reserve",
        writer_job_database_id=2000 + sequence,
        workflow_path=".github/workflows/catalog-run-controller.yml",
        repository="trading-optimizer-lab-org/aurora",
        protected_commit_sha=COMMIT_SHA,
        observed_at=datetime(2026, 8, 22, 10, sequence, tzinfo=UTC),
    )
    return CatalogMirrorRepairClaimV1.create(
        target_kind="authority",
        target_artifact_name="catalog-authority-test-0000000001",
        target_artifact_id=55,
        target_payload_sha256=PAYLOAD_SHA256,
        repair_sequence=sequence,
        previous_claim_sha256=None if sequence == 0 else "c" * 64,
        writer=writer,
    )


def _zip(payload: bytes, *, filename: str = "repair-claim.json") -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(filename, payload)
    return buffer.getvalue()


def test_repair_claim_artifact_requires_one_exact_canonical_file(monkeypatch) -> None:
    claim = _claim()
    monkeypatch.setattr(
        delivery,
        "_gh",
        lambda endpoint, binary=False: _zip(canonical_model_bytes(claim) + b"\n"),
    )

    parsed = delivery._repair_claim_payload(
        artifact_id=77,
        artifact_name=claim.artifact_name,
    )
    assert parsed == claim

    monkeypatch.setattr(
        delivery,
        "_gh",
        lambda endpoint, binary=False: _zip(
            canonical_model_bytes(claim) + b"\n",
            filename="wrong.json",
        ),
    )
    with pytest.raises(ValueError, match="CATALOG_MIRROR_REPAIR_CLAIM_INVALID"):
        delivery._repair_claim_payload(
            artifact_id=77,
            artifact_name=claim.artifact_name,
        )


def test_repair_claim_discovery_blocks_a_gap(monkeypatch) -> None:
    second = _claim(1)

    def rows(name: str):
        if name.endswith("-001"):
            return ({"id": 81, "expired": False},)
        return ()

    monkeypatch.setattr(delivery, "_artifact_rows", rows)
    monkeypatch.setattr(delivery, "_repair_claim_payload", lambda **kwargs: second)

    with pytest.raises(
        ValueError,
        match="CATALOG_MIRROR_REPAIR_CLAIM_CHAIN_INVALID",
    ):
        delivery._prior_repair_claims(PAYLOAD_SHA256)


def test_repair_claim_discovery_blocks_duplicate_or_expired_slots(monkeypatch) -> None:
    for rows in (
        ({"id": 91, "expired": False}, {"id": 92, "expired": False}),
        ({"id": 93, "expired": True},),
    ):
        monkeypatch.setattr(
            delivery,
            "_artifact_rows",
            lambda name, rows=rows: rows if name.endswith("-000") else (),
        )
        with pytest.raises(
            ValueError,
            match="CATALOG_MIRROR_REPAIR_CLAIM_CHAIN_INVALID",
        ):
            delivery._prior_repair_claims(PAYLOAD_SHA256)


def test_reconciler_inputs_must_be_canonical_files_inside_runner_temp(
    tmp_path: Path,
) -> None:
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    duplicate = runner_temp / "duplicate.json"
    duplicate.write_text('{"value":1,"value":2}', encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="CATALOG_MIRROR_JSON_DUPLICATE"):
        delivery._read_json(duplicate, runner_temp=runner_temp)
    with pytest.raises(ValueError, match="CATALOG_MIRROR_INPUT_INVALID"):
        delivery._read_json(outside, runner_temp=runner_temp)
