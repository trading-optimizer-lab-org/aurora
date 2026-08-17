from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_revision_guard_accepts_only_explicit_operational_paths():
    from aurora.infra.sp500_megarun.dehb_continuous_revision import (
        unexpected_scientific_changes,
    )

    assert unexpected_scientific_changes(
        [
            ".github/workflows/sp500-dehb-continuous-worker-pool-v2.yml",
            "infra/sp500_megarun/dehb_continuous_worker.py",
            "infra/sp500_megarun/dehb_continuous_store.py",
            "infra/sp500_megarun/dehb_continuous_archive.py",
            "scripts/build_sp500_dehb_historical_archive.py",
            "scripts/reduce_sp500_dehb_continuous_snapshot.py",
            "scripts/run_sp500_dehb_continuous_worker.py",
            "scripts/segment_sp500_dehb_continuous_state.py",
            "tests/test_sp500_megarun_dehb_continuous_worker.py",
        ]
    ) == ()


def test_revision_guard_rejects_evaluator_or_contract_changes():
    from aurora.infra.sp500_megarun.dehb_continuous_revision import (
        unexpected_scientific_changes,
    )

    assert unexpected_scientific_changes(
        [
            "infra/sp500_megarun/dehb_worker.py",
            "config/sp500_megarun_dehb_campaign_v1.json",
        ]
    ) == (
        "config/sp500_megarun_dehb_campaign_v1.json",
        "infra/sp500_megarun/dehb_worker.py",
    )


def test_revision_guard_accepts_isolated_unintegrated_strategy_catalog():
    from aurora.infra.sp500_megarun.dehb_continuous_revision import (
        unexpected_scientific_changes,
    )

    assert unexpected_scientific_changes(
        [
            "config/sp500_megarun_strategy_catalog_v1/catalog.jsonl",
            "docs/superpowers/specs/2026-08-15-sp500-strategy-catalog-design.md",
            "infra/sp500_megarun/strategy_catalog.py",
            "scripts/build_sp500_megarun_strategy_catalog.py",
        ]
    ) == ()


def test_revision_script_runs_before_package_installation():
    root = Path(__file__).resolve().parents[1]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "scripts/verify_sp500_dehb_scientific_revision.py",
            "--scientific-commit",
            head,
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
