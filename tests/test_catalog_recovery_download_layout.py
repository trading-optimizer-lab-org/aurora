from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.github_performance.recovery import (
    RecoveryEvidenceError,
    reconcile_expected_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]
ACTION_PATH = ROOT / ".github/actions/aurora-recovery-plan/action.yml"
DOWNLOAD_ACTION = (
    "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
)

INVENTORIES = {
    "attempts": {
        "expected": "EXPECTED_ATTEMPTS",
        "count": "expected_attempt_count",
        "path": "expected_attempt_path",
        "step": "download_attempts",
        "prefix": "catalog-terminal-attempt-",
        "pattern": "catalog-terminal-attempt-*",
    },
    "checkpoints": {
        "expected": "EXPECTED_CHECKPOINTS",
        "count": "expected_checkpoint_count",
        "path": "expected_checkpoint_path",
        "step": "download_checkpoints",
        "prefix": "catalog-checkpoint-",
        "pattern": "catalog-checkpoint-*",
    },
    "failures": {
        "expected": "EXPECTED_FAILURES",
        "count": "expected_failure_count",
        "path": "expected_failure_path",
        "step": "download_failures",
        "prefix": "catalog-failure-attempt-",
        "pattern": "catalog-failure-attempt-*",
    },
}


def _action() -> dict[str, Any]:
    return dict(load_github_yaml(ACTION_PATH))


def _expected_script() -> str:
    step = next(
        row
        for row in _action()["runs"]["steps"]
        if row.get("id") == "expected"
    )
    marker = "python - <<'PY'\n"
    assert marker in step["run"]
    return textwrap.dedent(step["run"].split(marker, 1)[1].split("\nPY", 1)[0])


def _download_steps() -> dict[str, dict[str, Any]]:
    return {
        row["id"]: row
        for row in _action()["runs"]["steps"]
        if row.get("id") in {item["step"] for item in INVENTORIES.values()}
    }


def _run_expected(
    tmp_path: Path,
    inventories: dict[str, Any],
) -> tuple[subprocess.CompletedProcess[str], Path, dict[str, str]]:
    runner_temp = tmp_path / "runner-temp"
    output_path = tmp_path / "github-output"
    output_path.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "EXPECTED_ATTEMPTS": json.dumps(inventories["attempts"]),
            "EXPECTED_FAILURES": json.dumps(inventories["failures"]),
            "EXPECTED_CHECKPOINTS": json.dumps(inventories["checkpoints"]),
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(output_path),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", _expected_script()],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    outputs = {}
    if output_path.is_file():
        outputs = dict(
            line.split("=", 1)
            for line in output_path.read_text(encoding="utf-8").splitlines()
            if line
        )
    return result, runner_temp, outputs


def _names(kind: str, count: int) -> tuple[str, ...]:
    prefix = INVENTORIES[kind]["prefix"]
    return tuple(f"{prefix}{index:03d}" for index in range(1, count + 1))


def _materialize_pinned_download(
    destination: Path, artifact_names: tuple[str, ...]
) -> None:
    """Model the pinned action's merge-multiple:false extraction rule."""
    for artifact_name in artifact_names:
        target = (
            destination
            if len(artifact_names) == 1
            else destination / artifact_name
        )
        target.mkdir(parents=True, exist_ok=True)
        (target / "payload").write_text(artifact_name, encoding="utf-8")


def _observed_names(root: Path) -> tuple[str, ...]:
    if not root.is_dir():
        return ()
    return tuple(sorted(path.name for path in root.iterdir() if path.is_dir()))


def test_recovery_download_steps_are_pinned_and_use_expected_layout_outputs() -> None:
    steps = _download_steps()
    assert set(steps) == {
        "download_attempts",
        "download_checkpoints",
        "download_failures",
    }
    for kind, metadata in INVENTORIES.items():
        step = steps[metadata["step"]]
        assert step["uses"] == DOWNLOAD_ACTION
        assert step["with"]["pattern"] == metadata["pattern"]
        assert step["with"]["merge-multiple"] is False
        assert step["with"]["path"] == (
            f"${{{{ steps.expected.outputs.{metadata['path']} }}}}"
        )
        assert metadata["count"] in str(step["if"])


@pytest.mark.parametrize("count", [0, 1, 2], ids=["zero-skip", "singleton", "multiple"])
def test_actual_expected_python_selects_pinned_download_layout(
    tmp_path: Path, count: int
) -> None:
    inventories = {
        kind: list(_names(kind, count)) for kind in INVENTORIES
    }
    result, runner_temp, outputs = _run_expected(tmp_path, inventories)
    assert result.returncode == 0, result.stderr

    for kind, metadata in INVENTORIES.items():
        names = tuple(inventories[kind])
        assert outputs[metadata["count"]] == str(count)
        root = runner_temp / "catalog-recovery" / kind
        destination = Path(outputs[metadata["path"]])
        expected_destination = root / names[0] if count == 1 else root
        assert destination == expected_destination

        if count == 0:
            assert "!= '0'" in str(_download_steps()[metadata["step"]]["if"])
            assert not root.exists()
            continue

        _materialize_pinned_download(destination, names)
        observed = _observed_names(root)
        assert observed == names
        receipt = reconcile_expected_artifacts(
            expected=names,
            observed=observed,
            download_outcome="success",
        )
        assert receipt.observed == names


@pytest.mark.parametrize(
    ("actual_names", "case"),
    [
        (
            (
                "catalog-terminal-attempt-001",
                "catalog-terminal-attempt-002",
                "catalog-terminal-attempt-extra",
            ),
            "extra",
        ),
        (
            (
                "catalog-terminal-attempt-001",
                "catalog-terminal-attempt-unexpected",
            ),
            "unexpected",
        ),
    ],
)
def test_pinned_download_layout_keeps_extra_or_unexpected_names_rejectable(
    tmp_path: Path, actual_names: tuple[str, ...], case: str
) -> None:
    expected = _names("attempts", 2)
    inventories: dict[str, list[str]] = {kind: [] for kind in INVENTORIES}
    inventories["attempts"] = list(expected)
    result, runner_temp, outputs = _run_expected(tmp_path, inventories)
    assert result.returncode == 0, result.stderr

    destination = Path(outputs[INVENTORIES["attempts"]["path"]])
    root = runner_temp / "catalog-recovery" / "attempts"
    assert destination == root
    _materialize_pinned_download(destination, actual_names)
    observed = _observed_names(root)
    assert observed != expected, case
    with pytest.raises(RecoveryEvidenceError, match="RECOVERY_ARTIFACT_SET_MISMATCH"):
        reconcile_expected_artifacts(
            expected=expected,
            observed=observed,
            download_outcome="success",
        )


@pytest.mark.parametrize(
    ("environment_name", "value"),
    [
        ("EXPECTED_ATTEMPTS", "not-a-list"),
        ("EXPECTED_ATTEMPTS", ["catalog-terminal-attempt-001"] * 2),
        ("EXPECTED_FAILURES", ["catalog-failure-attempt-002", "catalog-failure-attempt-001"]),
        ("EXPECTED_CHECKPOINTS", ["."]),
        ("EXPECTED_ATTEMPTS", [".."]),
        ("EXPECTED_FAILURES", ["../escape"]),
        ("EXPECTED_CHECKPOINTS", [r"..\escape"]),
        ("EXPECTED_ATTEMPTS", ["bad\x00name"]),
        ("EXPECTED_FAILURES", ["bad\nname"]),
        ("EXPECTED_CHECKPOINTS", ["valid", None]),
    ],
)
def test_expected_python_rejects_malformed_or_unsafe_closed_inventory(
    tmp_path: Path, environment_name: str, value: Any
) -> None:
    inventories: dict[str, Any] = {
        "attempts": [],
        "failures": [],
        "checkpoints": [],
    }
    inventory_by_environment = {
        metadata["expected"]: kind for kind, metadata in INVENTORIES.items()
    }
    inventories[inventory_by_environment[environment_name]] = value

    result, _, _ = _run_expected(tmp_path, inventories)
    assert result.returncode != 0
    assert f"RECOVERY_{environment_name}_INVALID" in (
        result.stdout + result.stderr
    )
