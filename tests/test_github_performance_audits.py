from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from aurora.infra.github_performance.audits import (
    DataAccessRecord,
    RuntimeAccessLedger,
    RuntimePolicyViolation,
    build_required_audits,
    write_required_audits,
)
from aurora.infra.github_performance.contracts import RunSpec
from github_performance_helpers import minimal_valid_spec


def _spec() -> RunSpec:
    return RunSpec.model_validate(minimal_valid_spec())


def _record(
    *,
    partition: str = "train",
    minimum_date: date = date(2003, 1, 2),
    maximum_date: date = date(2010, 12, 31),
    row_count: int = 2_016,
    split: str = "train",
    purpose: str = "selection",
    locked: bool = False,
) -> DataAccessRecord:
    return DataAccessRecord(
        source="snapshot:reference",
        partition=partition,
        minimum_date=minimum_date,
        maximum_date=maximum_date,
        row_count=row_count,
        split=split,
        purpose=purpose,
        locked=locked,
        shard_id="s000",
        attempt_id="a000",
    )


def test_runtime_access_ledger_derives_safe_policy_evidence() -> None:
    ledger = RuntimeAccessLedger(
        records=(
            _record(),
            _record(
                partition="validation",
                minimum_date=date(2011, 1, 3),
                maximum_date=date(2020, 12, 31),
                row_count=2_520,
                split="validation",
                purpose="report",
            ),
        )
    )

    audits = build_required_audits(
        _spec(),
        ledger,
        environment={
            "github_actions": True,
            "runner_label": "ubuntu-24.04",
            "larger_runner_used": False,
        },
    )

    assert audits.data.locked_rows_accessed == 0
    assert audits.data.maximum_accessed_date == date(2020, 12, 31)
    assert audits.policy.locked_opened is False
    assert audits.policy.validation_used_for_selection is False
    assert audits.runtime.github_only_run is True
    assert audits.runtime.standard_runner_only is True


def test_locked_rows_fail_closed_even_when_spec_declares_locked_closed() -> None:
    ledger = RuntimeAccessLedger(
        records=(
            _record(
                partition="locked",
                minimum_date=date(2021, 1, 4),
                maximum_date=date(2021, 1, 4),
                row_count=1,
                split="locked",
                purpose="report",
                locked=True,
            ),
        )
    )

    with pytest.raises(
        RuntimePolicyViolation,
        match="LOCKED_ROWS_ACCESSED",
    ):
        build_required_audits(
            _spec(),
            ledger,
            environment={"github_actions": True},
        )


def test_validation_selection_fails_closed() -> None:
    ledger = RuntimeAccessLedger(
        records=(
            _record(
                partition="validation",
                minimum_date=date(2011, 1, 3),
                maximum_date=date(2020, 12, 31),
                row_count=2_520,
                split="validation",
                purpose="selection",
            ),
        )
    )

    with pytest.raises(
        RuntimePolicyViolation,
        match="VALIDATION_USED_FOR_SELECTION",
    ):
        build_required_audits(
            _spec(),
            ledger,
            environment={"github_actions": True},
        )


def test_access_after_validation_end_fails_even_when_not_marked_locked() -> None:
    ledger = RuntimeAccessLedger(
        records=(
            _record(
                partition="validation",
                minimum_date=date(2020, 12, 31),
                maximum_date=date(2021, 1, 4),
                row_count=2,
                split="validation",
                purpose="report",
                locked=False,
            ),
        )
    )

    with pytest.raises(
        RuntimePolicyViolation,
        match="DATA_AFTER_VALIDATION_END",
    ):
        build_required_audits(
            _spec(),
            ledger,
            environment={"github_actions": True},
        )


def test_required_audit_files_are_complete_and_derived(
    tmp_path: Path,
) -> None:
    ledger = RuntimeAccessLedger(
        records=(
            _record(),
            _record(
                partition="validation",
                minimum_date=date(2011, 1, 3),
                maximum_date=date(2020, 12, 31),
                row_count=2_520,
                split="validation",
                purpose="report",
            ),
        )
    )
    audits = build_required_audits(
        _spec(),
        ledger,
        environment={
            "github_actions": True,
            "runner_label": "ubuntu-24.04",
            "larger_runner_used": False,
            "code_sha": "a" * 40,
            "workflow_sha256": "b" * 64,
            "environment_sha256": "c" * 64,
        },
    )

    paths = write_required_audits(tmp_path, audits)

    assert {path.name for path in paths} == {
        "data_audit.json",
        "policy_audit.json",
        "runtime_audit.json",
        "provenance.json",
        "runtime_access_ledger.parquet",
    }
    data = json.loads((tmp_path / "data_audit.json").read_text())
    policy = json.loads((tmp_path / "policy_audit.json").read_text())
    assert data["locked_rows_accessed"] == 0
    assert data["maximum_accessed_date"] == "2020-12-31"
    assert policy["validation_used_for_selection"] is False

