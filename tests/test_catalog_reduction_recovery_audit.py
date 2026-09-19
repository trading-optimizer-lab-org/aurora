from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

import pytest

from aurora.infra.sp500_megarun.catalog_runtime_audit import (
    allowed_skips_from_verified_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
BINDING = {
    "request_sha256": "1" * 64,
    "authority_id": "018f47a2-6e91-7c34-8000-000000000001",
    "campaign_id": "2" * 64,
    "science_sha256": "3" * 64,
    "execution_plan_sha256": "4" * 64,
    "execution_protocol_sha256": "5" * 64,
    "protected_commit_sha": "6" * 40,
}


def _local_script_command(script: Path, *arguments: str) -> list[str]:
    bootstrap = """
import importlib.util
import runpy
import sys
from pathlib import Path

script = Path(sys.argv[1]).resolve()
root = script.parents[1]
try:
    import __editable___aurora_1_5_0_finder as editable_finder
    editable_finder.MAPPING["aurora"] = str(root)
except ImportError:
    pass
spec = importlib.util.spec_from_file_location(
    "aurora", root / "__init__.py", submodule_search_locations=[str(root)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["aurora"] = module
assert spec.loader is not None
spec.loader.exec_module(module)
sys.meta_path[:] = [
    finder for finder in sys.meta_path
    if not finder.__class__.__module__.startswith("__editable___")
]
sys.argv = [str(script), *sys.argv[2:]]
runpy.run_path(str(script), run_name="__main__")
"""
    return [sys.executable, "-c", bootstrap, str(script), *arguments]


def _evidence(*, recovery_verified: bool = True) -> dict[str, object]:
    return {
        "binding": BINDING,
        "matrix_counts": {
            "component_matrix_a_count": 4,
            "component_matrix_b_count": 4,
            "cached_component_matrix_a_count": 4,
            "cached_component_matrix_b_count": 4,
            "recipe_matrix_a_count": 4,
            "recipe_matrix_b_count": 4,
            "recipe_matrix_c_count": 4,
            "payload_artifact_count": 4,
            "reduction_matrix_count": 4,
        },
        "reconcile_status": "",
        "recovery": [
            {"status": "", "has_matrix_a": "", "has_matrix_b": ""},
            {"status": "", "has_matrix_a": "", "has_matrix_b": ""},
            {"status": "", "has_matrix_a": "", "has_matrix_b": ""},
        ],
        "recovery_verified": recovery_verified,
    }


def test_verified_recovery_allows_contractual_producer_omission_without_zeroing_plan_counts() -> None:
    allowed = allowed_skips_from_verified_outputs(
        _evidence(), binding=BINDING,
    )
    assert allowed == frozenset({
        "engine / publish_sealed_payload_artifacts",
        "engine / build_components_a",
        "engine / build_components_b",
        "engine / materialize_cached_components_a",
        "engine / materialize_cached_components_b",
        "engine / verify_component_store",
        "engine / evaluate_a",
        "engine / evaluate_b",
        "engine / evaluate_c",
        "engine / reconcile_wave_0",
        "engine / recovery_wave_1",
        "engine / recovery_wave_2",
        "engine / recovery_wave_3",
        "engine / ready_to_merge",
        "engine / reduce_groups",
    })


def test_unverified_recovery_cannot_authorize_the_same_omission() -> None:
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_SKIP_POLICY_INVALID"):
        allowed_skips_from_verified_outputs(
            _evidence(recovery_verified=False), binding=BINDING,
        )


def test_real_runtime_audit_cli_accepts_only_current_bound_recovery_evidence(tmp_path: Path) -> None:
    jobs = [
        {
            "id": 10,
            "name": "engine / engine_verify_sealed_plan",
            "conclusion": "success",
            "labels": ["ubuntu-24.04"],
            "runner_group_name": "GitHub Actions",
        },
        {
            "id": 11,
            "name": "engine / prepare_runtime_and_inputs",
            "conclusion": "success",
            "labels": ["ubuntu-24.04"],
            "runner_group_name": "GitHub Actions",
        },
        {
            "id": 12,
            "name": "engine / reduce",
            "conclusion": "success",
            "labels": ["ubuntu-24.04"],
            "runner_group_name": "GitHub Actions",
        },
        {
            "id": 13,
            "name": "engine / verify_terminal_science",
            "conclusion": "success",
            "labels": ["ubuntu-24.04"],
            "runner_group_name": "GitHub Actions",
        },
        {
            "id": 14,
            "name": "engine / audit_runtime",
            "conclusion": "success",
            "labels": ["ubuntu-24.04"],
            "runner_group_name": "GitHub Actions",
        },
    ]
    skipped = [
        {
            "id": 100 + index,
            "name": name,
            "conclusion": "skipped",
            "labels": [],
        }
        for index, name in enumerate(sorted(allowed_skips_from_verified_outputs(_evidence(), binding=BINDING)), 1)
    ]
    pages = [{"jobs": [*jobs, *skipped]}]
    artifacts = {"artifacts": [{"id": 20, "name": "final", "expired": False, "size_in_bytes": 12}]}
    documents = {
        "binding": BINDING,
        "verified-skip-evidence": _evidence(),
        "run": {
            "id": 1000,
            "run_attempt": 1,
            "head_sha": BINDING["protected_commit_sha"],
            "path": ".github/workflows/catalog-optimized-run.yml",
            "repository": {"full_name": "trading-optimizer-lab-org/aurora"},
        },
        "repository": {
            "full_name": "trading-optimizer-lab-org/aurora",
            "visibility": "public",
            "private": False,
        },
        "jobs": pages,
        "jobs-confirmation": pages,
        "artifacts": artifacts,
        "artifacts-confirmation": artifacts,
    }
    arguments: list[str] = []
    for name, payload in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        arguments.extend((f"--{name}", str(path)))
    output = tmp_path / "runtime-audit.json"
    arguments.extend(
        (
            "--run-id", "1000",
            "--run-attempt", "1",
            "--audited-at", datetime(2026, 9, 19, 12, 0, tzinfo=UTC).isoformat(),
            "--output", str(output),
        )
    )
    result = subprocess.run(
        _local_script_command(ROOT / "scripts/audit_catalog_runtime.py", *arguments),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["execution_plan_sha256"] == BINDING["execution_plan_sha256"]
    assert receipt["job_ids"][-1] == 115
