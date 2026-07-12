"""Contract tests for the PIT-limited stock protocol manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aurora.research.stock_protocol.manifest import (
    EXECUTABLE_TEST_IDS,
    UNSUPPORTED_TEST_IDS,
    ProtocolManifest,
    load_protocol_manifest,
)


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"
)


def test_manifest_has_36_tests_and_25_executable_11_unsupported():
    manifest = load_protocol_manifest(MANIFEST_PATH)

    assert len(manifest.tests) == 36
    assert manifest.executable_test_ids() == EXECUTABLE_TEST_IDS
    assert len(manifest.executable_test_ids()) == 25
    assert len(manifest.unsupported_tests()) == 11
    assert tuple(item.test_id for item in manifest.unsupported_tests()) == (
        *UNSUPPORTED_TEST_IDS,
    )
    assert manifest.locked_opened is False
    assert manifest.data_end == "2020-12-31"


def test_manifest_enforces_date_and_limitation_contract():
    manifest = load_protocol_manifest(MANIFEST_PATH)

    assert manifest.research_start == "1995-01-01"
    assert manifest.research_end == "2015-12-31"
    assert manifest.final_holdout_start == "2016-01-01"
    assert manifest.final_holdout_end == "2020-12-31"
    assert manifest.locked_start == "2021-01-01"
    assert manifest.max_parallel_requested == 360
    assert manifest.survivorship_free is False
    assert manifest.full_protocol_compliance is False


def test_every_record_has_explicit_contract_fields():
    manifest = load_protocol_manifest(MANIFEST_PATH)

    assert {item.test_id for item in manifest.tests} == set(range(1, 37))
    for item in manifest.tests:
        assert item.status in {"executable", "unsupported_missing_data"}
        assert item.reason
        assert item.requires
        assert item.variants
        assert all(isinstance(requirement, str) for requirement in item.requires)
        assert all(isinstance(variant, dict) for variant in item.variants)


def test_unsupported_records_are_explicit_and_excluded_from_executable_ids():
    manifest = load_protocol_manifest(MANIFEST_PATH)

    unsupported = manifest.unsupported_tests()
    assert all(item.reason for item in unsupported)
    assert all(
        item.test_id not in manifest.executable_test_ids() for item in unsupported
    )
    assert all(
        item.status == "unsupported_missing_data"
        for item in manifest.tests
        if item.test_id in UNSUPPORTED_TEST_IDS
    )


def test_policy_hash_is_deterministic_and_excludes_no_contract_fields():
    manifest = load_protocol_manifest(MANIFEST_PATH)
    payload = manifest.policy_payload()

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    expected_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    assert manifest.policy_hash == expected_hash
    assert manifest.policy_hash == load_protocol_manifest(MANIFEST_PATH).policy_hash
    assert payload["data_end"] == "2020-12-31"
    assert payload["locked_opened"] is False
    assert payload["max_parallel_requested"] == 360
    assert payload["survivorship_free"] is False
    assert payload["full_protocol_compliance"] is False


def test_loader_rejects_missing_or_duplicate_ids(tmp_path: Path):
    source = MANIFEST_PATH.read_text(encoding="utf-8")
    source = source.replace("- {id: 36", "- {id: 35", 1)
    path = tmp_path / "invalid.yaml"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="exactly the IDs 1 through 36"):
        load_protocol_manifest(path)


def test_manifest_is_frozen():
    manifest = load_protocol_manifest(MANIFEST_PATH)

    with pytest.raises(Exception):
        manifest.data_end = "2021-01-01"  # type: ignore[misc]


def test_from_dict_recomputes_hash_and_validates_declared_hash():
    manifest = load_protocol_manifest(MANIFEST_PATH)
    payload = manifest.to_dict()
    payload["policy_hash"] = "deadbeef" * 8

    rebuilt = ProtocolManifest.from_dict(payload)

    assert rebuilt.policy_hash == manifest.policy_hash
    assert rebuilt.verify_hash()
    assert not rebuilt.verify_hash("deadbeef" * 8)
