from __future__ import annotations

from pathlib import Path


from aurora.infra.github_performance.contracts import (
    RunSpec,
)
from aurora.infra.github_performance.preflight import (
    load_github_yaml,
)
from aurora.infra.github_performance.reference_workload import (
    REFERENCE_SEED,
    TRAIN_OBSERVATIONS,
    VALIDATION_OBSERVATIONS,
    _generate_prices,
)


ROOT = Path(__file__).parents[1]
SPEC_PATH = ROOT / "config" / "github_performance_reference.yaml"
WORKFLOW_PATH = (
    ROOT / ".github/workflows/github-performance-reference.yml"
)


def _resolved_spec(snapshot_hash: str, manifest_hash: str) -> RunSpec:
    payload = load_github_yaml(SPEC_PATH)
    payload["identity"]["code_sha"] = "a" * 40
    payload["identity"]["workflow_sha256"] = "b" * 64
    payload["policy"]["policy_hash"] = "c" * 64
    payload["data"]["manifest_sha256"] = manifest_hash
    payload["data"]["snapshot_hash"] = snapshot_hash
    payload["execution"]["dependency_lock_sha256"] = "d" * 64
    payload["execution"]["environment_sha256"] = "e" * 64
    payload["performance"]["capacity_profile_sha256"] = "f" * 64
    payload["metrics"]["contract_sha256"] = "1" * 64
    return RunSpec.model_validate(payload)


def test_reference_fixture_is_deterministic_and_never_crosses_locked() -> None:
    frame_a = _generate_prices()
    frame_b = _generate_prices()
    assert REFERENCE_SEED == 20_260_725
    assert frame_a.equals(frame_b)
    assert len(frame_a.loc[frame_a["period"] == "train"]) == (
        TRAIN_OBSERVATIONS
    )
    assert len(frame_a.loc[frame_a["period"] == "validation"]) == (
        VALIDATION_OBSERVATIONS
    )
    assert str(frame_a["date"].max().date()) == "2020-12-31"
