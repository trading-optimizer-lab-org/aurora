from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_synthetic_objective_is_deterministic_and_pandas_serializable() -> None:
    from aurora.infra.sp500_megarun.dehb_official_smoke import synthetic_objective

    config = {"window": 63, "mode": "level", "threshold": 0.25}

    first = synthetic_objective(config, 9)
    second = synthetic_objective(dict(reversed(list(config.items()))), 9)

    assert first == second
    assert set(first) == {"fitness", "cost", "info"}
    assert isinstance(first["fitness"], float)
    assert first["cost"] == 9.0
    assert first["info"]["synthetic_only"] is True
    assert first["info"]["fidelity"] == 9
    json.dumps(first, sort_keys=True)


def test_github_only_guard_rejects_local_execution(monkeypatch) -> None:
    from aurora.infra.sp500_megarun.dehb_official_smoke import (
        OfficialDehbSmokeError,
        require_github_actions,
    )

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)

    with pytest.raises(OfficialDehbSmokeError, match="GITHUB_ACTIONS_REQUIRED"):
        require_github_actions()


def test_github_only_guard_accepts_actions(monkeypatch) -> None:
    from aurora.infra.sp500_megarun.dehb_official_smoke import require_github_actions

    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    require_github_actions()


def test_report_gate_requires_every_official_dehb_guarantee() -> None:
    from aurora.infra.sp500_megarun.dehb_official_smoke import (
        OfficialDehbSmokeError,
        validate_official_smoke_report,
    )

    report = {
        "ready": True,
        "official_dehb_version": "0.1.2",
        "configspace_version": "1.2.2",
        "lane_count": 240,
        "all_configspaces_exact": True,
        "fidelities": [1, 3, 9, 27],
        "eta": 3,
        "actual_four_worker_run": True,
        "worker_equivalence_1_2_4": True,
        "checkpoint_resume_exact": True,
        "search_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "snapshot_mounted": False,
    }
    validate_official_smoke_report(report)

    broken = {**report, "checkpoint_resume_exact": False}
    with pytest.raises(OfficialDehbSmokeError, match="SMOKE_GATE_FAILED"):
        validate_official_smoke_report(broken)


def test_cli_refuses_to_overwrite_a_nonempty_output_directory(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.dehb_official_smoke import (
        OfficialDehbSmokeError,
        require_empty_output_directory,
    )

    target = tmp_path / "existing"
    target.mkdir()
    (target / "receipt.json").write_text("{}", encoding="utf-8")

    with pytest.raises(OfficialDehbSmokeError, match="OUTPUT_DIRECTORY_NOT_EMPTY"):
        require_empty_output_directory(target)
