"""Focused fixtures for the in-run Atlas terminal contract."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun import catalog_atlas_terminal_adapter as adapter
from scripts.finalize_catalog_atlas_fast_run import _parser


def _plan() -> SimpleNamespace:
    return SimpleNamespace(
        plan_sha256="a" * 64,
        catalog_manifest_sha256="b" * 64,
        selection_sha256="c" * 64,
        shards=(SimpleNamespace(shard_index=0, start_ordinal=0, stop_ordinal=2, expected_recipe_count=2),),
    )


def _write_final(root: Path, *, source_index: bool = False) -> None:
    plan = _plan()
    rows = []
    for ordinal in range(2):
        row = {
            "ordinal": ordinal,
            "plan_sha256": plan.plan_sha256,
            "validation_opened": False,
            "locked_opened": False,
            "value": ordinal,
        }
        row["result_sha256"] = adapter._canonical(row)
        rows.append(row)
    result_bytes = b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n" for row in rows
    )
    (root / "results.jsonl").write_bytes(result_bytes)
    result_sha = hashlib.sha256(result_bytes).hexdigest()
    common = {
        "plan_sha256": plan.plan_sha256,
        "requested_recipe_count": 2,
        "verified_recipe_count": 2,
        "verified_shard_count": 1,
    }
    (root / "reduction_receipt.json").write_text(json.dumps({
        **common,
        "accepted": True,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "selection_sha256": plan.selection_sha256,
        "missing_ordinals": 0,
        "duplicate_ordinals": 0,
        "conflicts": 0,
        "results_sha256": result_sha,
        "storage_mode": "combined_results_file",
        "row_hash_verification_mode": "canonical_row_hash",
        "row_hashes_recomputed": True,
        "result_file_hashes_verified": True,
        "validation_opened": False,
        "locked_opened": False,
    }))
    (root / "coverage_report.json").write_text(json.dumps({
        "requested_recipe_count": 2,
        "verified_recipe_count": 2,
        "verified_shard_count": 1,
        "missing_ordinals": 0,
        "duplicate_ordinals": 0,
        "conflicts": 0,
        "validation_opened": False,
        "locked_opened": False,
    }))
    (root / "all_results_manifest.json").write_text(json.dumps({
        "storage_mode": "combined_results_file",
        "results_path": "../results.jsonl",
        "results_sha256": result_sha,
        "row_count": 2,
        "row_hash_verification_mode": "canonical_row_hash",
        "row_hashes_recomputed": True,
        "result_file_hashes_verified": True,
        "validation_opened": False,
        "locked_opened": False,
    }))
    if source_index:
        source = {
            "schema_version": 1,
            "storage_mode": "combined_results_file",
            "plan_sha256": plan.plan_sha256,
            "catalog_manifest_sha256": plan.catalog_manifest_sha256,
            "row_count": 2,
            "shard_count": 1,
            "validation_opened": False,
            "locked_opened": False,
            "shards": [{
                "shard_index": 0,
                "start_ordinal": 0,
                "stop_ordinal": 2,
                "expected_recipe_count": 2,
                "result_sha256": "d" * 64,
            }],
        }
        source["source_index_sha256"] = adapter._canonical(source)
        (root / "source_results_index.json").write_text(json.dumps(source))


def test_reducer_fixture_is_verified_without_shard_downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "EXPECTED_RECIPE_COUNT", 2)
    monkeypatch.setattr(adapter, "EXPECTED_SHARD_COUNT", 1)
    root = tmp_path / "final"
    root.mkdir()
    _write_final(root)

    count, digest = adapter._verify_final(root, _plan())

    assert count == 2
    assert digest == hashlib.sha256((root / "results.jsonl").read_bytes()).hexdigest()


def test_normal_full_result_does_not_require_source_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "EXPECTED_RECIPE_COUNT", 2)
    monkeypatch.setattr(adapter, "EXPECTED_SHARD_COUNT", 1)
    root = tmp_path / "final"
    root.mkdir()
    _write_final(root, source_index=False)

    count, _ = adapter._verify_final(root, _plan())

    assert count == 2


def test_optional_source_index_is_still_fail_closed_when_present_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "EXPECTED_RECIPE_COUNT", 2)
    monkeypatch.setattr(adapter, "EXPECTED_SHARD_COUNT", 1)
    root = tmp_path / "final"
    root.mkdir()
    _write_final(root, source_index=True)
    source = json.loads((root / "source_results_index.json").read_text())
    source["shard_count"] = 2
    source["source_index_sha256"] = adapter._canonical({key: value for key, value in source.items() if key != "source_index_sha256"})
    (root / "source_results_index.json").write_text(json.dumps(source))

    with pytest.raises(adapter.AtlasTerminalEvidenceError) as caught:
        adapter._verify_final(root, _plan())

    assert caught.value.code == "ATLAS_TERMINAL_SOURCE_INDEX_BINDING_INVALID"


def test_parent_run_in_progress_and_required_matrix_jobs_are_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps({
        "id": 209906,
        "html_url": "https://github.com/example/repo/actions/runs/209906",
        "head_sha": "e" * 40,
        "path": adapter.CONTROLLER_WORKFLOW_PATH,
        "status": "in_progress",
        "conclusion": None,
    }))
    run, run_id, _, _ = adapter._parse_run(run_path)
    assert run["status"] == "in_progress"
    assert run["conclusion"] is None
    assert run_id == 209906

    monkeypatch.setattr(adapter, "EXPECTED_SHARD_COUNT", 360)
    rows = [
        {"name": "gate", "conclusion": "success"},
        {"name": "engine", "conclusion": "skipped"},
        {"name": "engine / engine_verify_sealed_plan", "conclusion": "skipped"},
        {"name": "engine_atlas", "conclusion": "success"},
        {"name": "engine_atlas / preflight", "conclusion": "success"},
        {"name": "engine_atlas / reduce", "conclusion": "success"},
        {"name": "finalize", "conclusion": None},
    ]
    rows.extend({"name": f"engine_atlas / evaluate_{name} ({index})", "conclusion": "success"}
                for index, name in enumerate(("a", "b", "c") * 120))
    assert len(adapter._validate_jobs({"jobs": rows})) == 367
    assert len(adapter._validate_jobs({"jobs": [row for row in rows if row["name"] != "engine"]})) == 366


def test_cli_requires_only_parent_snapshots_and_two_artifact_roots() -> None:
    args = _parser().parse_args([
        "--request-context", "context.json", "--decision", "decision.json",
        "--run", "run.json", "--jobs", "jobs.json",
        "--preflight-root", "preflight", "--final-root", "final",
        "--output", "receipt.json", "--comment-output", "comment.json",
        "--github-output", "github-output",
    ])

    assert args.final_results_artifact == "sp500-atlas-final-results"
    assert adapter.CAMPAIGN_KEY == "sp500-atlas-v1"
    assert adapter.CATALOG_ID == "sp500-atlas-1"
    assert not hasattr(args, "invocation")
    assert not hasattr(args, "artifacts")
    assert not hasattr(args, "shards_root")


def test_adapter_imports_without_pyarrow() -> None:
    class NoPyarrow:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "pyarrow" or fullname.startswith("pyarrow."):
                raise ModuleNotFoundError("pyarrow intentionally unavailable", name=fullname)
            return None

    module_name = adapter.__name__
    original = sys.modules.pop(module_name)
    blocker = NoPyarrow()
    sys.meta_path.insert(0, blocker)
    try:
        reloaded = importlib.import_module(module_name)
        assert reloaded.EXPECTED_RECIPE_COUNT == 209_906
    finally:
        sys.meta_path.remove(blocker)
        sys.modules[module_name] = original
