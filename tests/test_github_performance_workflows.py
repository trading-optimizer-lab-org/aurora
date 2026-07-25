from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).parents[1]
ACTION_PATH = (
    ROOT / ".github" / "actions" / "aurora-runtime-setup" / "action.yml"
)


def _load_action() -> dict[str, Any]:
    return yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))


def _locked_action(name: str) -> str:
    lock = json.loads(
        (ROOT / "config" / "official_actions_lock.json").read_text(
            encoding="utf-8"
        )
    )
    return f"{name}@{lock[name]}"


def test_runtime_setup_is_composite_and_pinned() -> None:
    action = _load_action()
    assert action["runs"]["using"] == "composite"
    uses = [
        step["uses"]
        for step in action["runs"]["steps"]
        if "uses" in step
    ]
    assert _locked_action("actions/setup-python") in uses
    assert _locked_action("actions/cache") in uses
    assert (
        "actions/cache/restore@"
        + _locked_action("actions/cache").split("@", 1)[1]
    ) in uses
    assert all(
        value.rsplit("@", 1)[-1].isalnum() and
        len(value.rsplit("@", 1)[-1]) == 40
        for value in uses
    )


def test_runtime_setup_defaults_to_restore_only() -> None:
    action = _load_action()
    assert action["inputs"]["cache-mode"]["default"] == "restore-only"
    steps = action["runs"]["steps"]
    restore = next(step for step in steps if step.get("id") == "cache-restore")
    writer = next(step for step in steps if step.get("id") == "cache-writer")
    assert restore["if"] == "inputs.cache-mode == 'restore-only'"
    assert writer["if"] == "inputs.cache-mode == 'writer'"


def test_runtime_setup_pins_numeric_threads_to_detected_cpus() -> None:
    action_text = ACTION_PATH.read_text(encoding="utf-8")
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        assert f'echo "{variable}=$cpu_count"' in action_text
    assert "getconf _NPROCESSORS_ONLN" in action_text


def test_runtime_setup_has_no_credential_or_larger_runner_escape() -> None:
    action_text = ACTION_PATH.read_text(encoding="utf-8").lower()
    assert "persist-credentials" not in action_text
    assert "larger" not in action_text
    assert "gpu" not in action_text
    assert "self-hosted" not in action_text
