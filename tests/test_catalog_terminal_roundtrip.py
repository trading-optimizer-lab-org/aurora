"""Producer normalization must survive the independent receipt reader."""

from datetime import datetime, timezone
import json

import pytest

from aurora.infra.sp500_megarun.catalog_fast_path import CatalogTerminalReceiptV1


def terminal_values(duration: object) -> dict[str, object]:
    return dict(
        state="BLOCKED", reason_code="CATALOG_PREPARATION_REQUIRED",
        request_sha256="a" * 64, submission_key_sha256="b" * 64,
        campaign_key="sp500-optimized-catalog-v1", prepared_receipt_sha256=None,
        engine_run_id=None, run_url=None, expected_recipe_count=8,
        observed_recipe_count=0, queue_seconds=duration,
        preparation_seconds=0.0, computation_seconds=0.0,
        recovery_seconds=0.0, reduction_seconds=0.0,
        recovered_block_count=0, failure_class="request",
        result_science_sha256=None,
        created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("duration", [0, 0.0, 1, 1.0, 1.25])
def test_created_terminal_reopens_without_hash_change(duration: float) -> None:
    receipt = CatalogTerminalReceiptV1.create(**terminal_values(duration))
    reopened = CatalogTerminalReceiptV1.model_validate_json(receipt.model_dump_json())
    assert reopened.queue_seconds == duration
    assert reopened.receipt_sha256 == receipt.receipt_sha256


def test_equivalent_numeric_inputs_have_one_identity() -> None:
    integer = CatalogTerminalReceiptV1.create(**terminal_values(0))
    decimal = CatalogTerminalReceiptV1.create(**terminal_values(0.0))
    assert integer.receipt_sha256 == decimal.receipt_sha256


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf"), "invalid"])
def test_invalid_duration_is_never_published(duration: object) -> None:
    with pytest.raises(ValueError):
        CatalogTerminalReceiptV1.create(**terminal_values(duration))


def test_received_receipt_hash_is_not_repaired() -> None:
    receipt = CatalogTerminalReceiptV1.create(**terminal_values(0.0))
    received = json.loads(receipt.model_dump_json())
    received["queue_seconds"] = 12.0
    with pytest.raises(ValueError, match="CATALOG_TERMINAL_RECEIPT_HASH_INVALID"):
        CatalogTerminalReceiptV1.model_validate(received)


def test_optional_defaults_are_included_before_hashing() -> None:
    values = terminal_values(0.0)
    del values["engine_run_id"]
    del values["run_url"]
    receipt = CatalogTerminalReceiptV1.create(**values)
    assert CatalogTerminalReceiptV1.model_validate_json(receipt.model_dump_json()) == receipt


def test_v2_unknown_metrics_remain_unknown_and_legacy_hash_stays_valid() -> None:
    from aurora.infra.sp500_megarun.catalog_fast_path import CatalogTerminalReceiptV2, parse_catalog_terminal_receipt
    values = terminal_values(0)
    for key in ("queue_seconds", "preparation_seconds", "computation_seconds", "recovery_seconds", "reduction_seconds", "recovered_block_count"):
        values.pop(key)
    receipt = CatalogTerminalReceiptV2.create(**values, timing={}, recovered_block_ids=None)
    reopened = parse_catalog_terminal_receipt(json.loads(receipt.model_dump_json()))
    assert reopened.schema_version == "2"
    assert reopened.timing.worker_evaluation_seconds is None
    assert reopened.recovered_block_count is None
    old = CatalogTerminalReceiptV1.create(**terminal_values(0))
    assert parse_catalog_terminal_receipt(json.loads(old.model_dump_json())).receipt_sha256 == old.receipt_sha256
    changed = json.loads(receipt.model_dump_json())
    changed["timing"]["worker_evaluation_seconds"] = 0
    with pytest.raises(ValueError, match="HASH_INVALID"):
        parse_catalog_terminal_receipt(changed)
