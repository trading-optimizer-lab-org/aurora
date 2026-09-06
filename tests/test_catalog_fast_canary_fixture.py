"""Portable, production-format catalog fixture; not a PREPARED receipt."""
import hashlib
import json
from pathlib import Path

from aurora.infra.sp500_megarun.strategy_catalog import verify_strategy_catalog_directory


def test_production_format_fixture_preserves_approved_selection() -> None:
    fixture = Path(__file__).parent / "fixtures/catalog_fast_canary_v1"
    root = fixture / "production-catalog"
    verify_strategy_catalog_directory(root)
    selection = json.loads((fixture / "selection.json").read_bytes())
    manifest = json.loads((root / "manifest.json").read_bytes())
    coverage = json.loads((root / "coverage.json").read_bytes())
    assert (root / "catalog.jsonl").read_bytes() == (fixture / "catalog.jsonl").read_bytes()
    assert hashlib.sha256((root / "catalog.jsonl").read_bytes()).hexdigest() == selection["files_sha256"]["catalog.jsonl"]
    assert coverage["expected_strategy_ids"] == selection["strategy_ids"]
    assert coverage["source_catalog_sha256"] == selection["source_catalog_sha256"]
    assert coverage["scope"] == "selected_canary_only"
    assert manifest["strategy_count"] == 8
    assert manifest["individual_strategy_count"] == manifest["cross_strategy_count"] == 4
    assert manifest["validation_opened"] is False
    assert manifest["locked_opened"] is False
    assert manifest["search_end"] == "2010-12-31"
    assert selection["state"] == "SELECTED_NOT_PREPARED"
