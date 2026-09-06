from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.recovery import CheckpointSlotEvidence
from tests.test_catalog_recovery_blocks import _policy
from tests.test_sp500_catalog_optimized_reduction import _write_checkpoint


@pytest.mark.parametrize("mutation", ["valid", "bytes", "block", "assignment", "attempt"])
def test_real_recovery_action_checks_persisted_result_before_reuse(
    tmp_path: Path, mutation: str,
) -> None:
    """Execute the actual action's checkpoint loop, not a duplicate decision."""
    policy = _policy()
    (tmp_path / "checkpoint_policy.json").write_text(json.dumps(policy), "utf-8")
    target = tmp_path / "checkpoints" / "checkpoint-1"
    target.parent.mkdir()
    _write_checkpoint(target, worker_id=0, slot_index=1, slot_count=2,
        strategy_ids=["strategy-1" if mutation == "assignment" else "strategy-0"],
        previous_receipt_sha256="0" * 64,
        recovery_block_id=("f" * 64 if mutation == "block" else
                           policy["recovery_blocks_v1"]["blocks"][0]["block_id"]))
    if mutation == "bytes":
        (target / "results.parquet").write_bytes(b"damaged after publication")
    if mutation == "attempt":
        attempt_path = target / "shard_attempt_manifest.json"
        attempt = json.loads(attempt_path.read_text("utf-8"))
        attempt["attempt_id"] = "another-attempt"
        attempt_path.write_text(json.dumps(attempt), "utf-8")

    path = Path(__file__).resolve().parents[1] / ".github/actions/aurora-recovery-plan/action.yml"
    action = load_github_yaml(path)
    step = next(row for row in action["runs"]["steps"] if row.get("id") == "reconcile")
    source = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    tree = ast.parse(source)
    loop = next(node for node in tree.body if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name) and node.iter.id == "expected_checkpoints")
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    namespace = {"temp": tmp_path, "plan_root": tmp_path,
        "checkpoint_policy": policy, "checkpoint_slots": {},
        "expected_checkpoints": ["checkpoint-1"],
        "descriptor_by_worker": {0: {"checkpoint_slot_count": 2,
            "checkpoint_slot_artifacts": ["checkpoint-1", "checkpoint-2"]}},
        "canonical_sha256": canonical_sha256, "hashlib": hashlib, "json": json,
        "CheckpointSlotEvidence": CheckpointSlotEvidence}
    code = compile(ast.Module(body=[*imports, loop], type_ignores=[]), str(path), "exec")
    if mutation != "valid":
        with pytest.raises((ValueError, SystemExit), match="RECOVERY_BLOCK_"):
            exec(code, namespace)
        assert namespace["checkpoint_slots"] == {}
    else:
        exec(code, namespace)
        assert namespace["checkpoint_slots"][0][0].artifact_name == "checkpoint-1"
