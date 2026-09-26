"""A correction retry must reproduce the exact terminal hash."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from aurora.infra.sp500_megarun.catalog_atlas_terminal_adapter import AtlasTerminalVerification
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastLaunchDecisionV1, CatalogTerminalReceiptV2,
)
from scripts import prepare_atlas_terminal_correction as correction
from tests.test_catalog_fast_path import _request


def test_prepare_uses_immutable_source_time_for_idempotent_receipt(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    now = datetime(2026, 9, 24, 23, 12, 53, tzinfo=timezone.utc)
    source_run_id = 100
    old = CatalogTerminalReceiptV2.create(
        state="BLOCKED", reason_code="ATLAS_TERMINAL_CATALOG_HASH_INVALID",
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256="a" * 64,
        engine_run_id=source_run_id,
        run_url=f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{source_run_id}",
        expected_recipe_count=209906, observed_recipe_count=0, timing={},
        recovered_block_ids=None, failure_class="infrastructure",
        result_science_sha256=None, created_at=now,
    )
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED", reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256="a" * 64, selected_workers=20,
        launch_required=True, existing_run_id=None,
        decided_at=now - timedelta(hours=1), expires_at=now + timedelta(hours=1),
    )
    verification = AtlasTerminalVerification(
        "SUCCESS", "CATALOG_RUN_SUCCESS", 209906, 209906, source_run_id,
        f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{source_run_id}",
        "bd79d52474fbffba864915f004d9a63114b9d48d235d7502c328c423ad7ddd82",
        "18e614ffd8ef079fe7f6488db922d8bee33f539d07f37dc2de4bc1309c12df42",
        2, {},
    )
    old_path = tmp_path / "old.json"
    old_path.write_text(old.model_dump_json(), encoding="utf-8")
    gate = tmp_path / "gate"
    gate.mkdir()
    (gate / "catalog-fast-request-context.json").write_text(json.dumps({
        "issue_number": 378, "protected_commit_sha": correction.SOURCE_COMMIT,
    }), encoding="utf-8")
    monkeypatch.setattr(correction, "SOURCE_RUN_ID", source_run_id)
    monkeypatch.setattr(correction, "REQUEST_SHA", request.request_sha256)
    monkeypatch.setattr(correction, "OLD_RECEIPT_SHA", old.receipt_sha256)
    monkeypatch.setattr(correction, "_verify_source_metadata", lambda *_: ({}, ()))
    monkeypatch.setattr(correction, "verify_atlas_terminal_evidence",
                        lambda **_: ({}, request, decision, verification))
    receipts = [correction.prepare(
        root=tmp_path, gate=gate, preflight=tmp_path, final=tmp_path,
        old_terminal=old_path, output=tmp_path / f"receipt-{index}.json",
        proof_output=tmp_path / f"proof-{index}.json", client=None,
        protected_commit="f" * 40,
    ) for index in range(2)]
    assert receipts[0].receipt_sha256 == receipts[1].receipt_sha256
    assert receipts[0].created_at == now
