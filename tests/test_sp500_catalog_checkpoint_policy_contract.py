from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from typing import Any

import pytest

from scripts.reduce_sp500_optimized_catalog_group import (
    _checkpoint_rows,
    _verify_plan_document,
)
from tests.test_catalog_prepared_materialization import prepared_transport_fixture


def _producer_policy(tmp_path: Path) -> dict[str, Any]:
    _bundle, template, _plan, _identity, _prepared = prepared_transport_fixture(
        tmp_path
    )
    return _verify_plan_document(
        template / "checkpoint_policy.json", "checkpoint_policy"
    )


def test_current_producer_policy_is_accepted_by_reducer(tmp_path: Path) -> None:
    """The real producer's current policy must cross the reducer boundary."""
    policy = _producer_policy(tmp_path)

    rows = _checkpoint_rows(policy, worker_ids=list(range(7)))

    assert sorted(rows) == list(range(7))


def test_legacy_four_field_policy_remains_accepted(tmp_path: Path) -> None:
    policy = _producer_policy(tmp_path)
    legacy = deepcopy(policy)
    for row in legacy["workers"]:
        row.pop("projected_checkpoint_overhead_fraction")

    rows = _checkpoint_rows(legacy, worker_ids=list(range(7)))

    assert sorted(rows) == list(range(7))


@pytest.mark.parametrize("value", [0.0, 0.305467, 1.25])
def test_checkpoint_projection_accepts_finite_nonnegative_numbers(
    tmp_path: Path, value: float,
) -> None:
    policy = _producer_policy(tmp_path)
    candidate = deepcopy(policy)
    for row in candidate["workers"]:
        row["projected_checkpoint_overhead_fraction"] = value

    rows = _checkpoint_rows(candidate, worker_ids=list(range(7)))

    assert rows[0]["projected_checkpoint_overhead_fraction"] == value


@pytest.mark.parametrize(
    "value",
    [-0.01, "0.3", True, None, math.nan, math.inf, -math.inf],
)
def test_checkpoint_projection_rejects_invalid_values(
    tmp_path: Path, value: object,
) -> None:
    policy = _producer_policy(tmp_path)
    candidate = deepcopy(policy)
    candidate["workers"][0]["projected_checkpoint_overhead_fraction"] = value

    with pytest.raises(SystemExit, match="REDUCTION_CHECKPOINT_POLICY_INVALID"):
        _checkpoint_rows(candidate, worker_ids=list(range(7)))


@pytest.mark.parametrize(
    "mutation",
    ["missing_required", "unknown_key", "duplicate_worker", "missing_worker"],
)
def test_checkpoint_policy_rejects_structural_contract_breaks(
    tmp_path: Path, mutation: str,
) -> None:
    policy = _producer_policy(tmp_path)
    candidate = deepcopy(policy)
    if mutation == "missing_required":
        candidate["workers"][0].pop("checkpoint_slot_artifacts")
    elif mutation == "unknown_key":
        candidate["workers"][0]["projected_checkpoint_overhead_fraction_typo"] = 0.3
    elif mutation == "duplicate_worker":
        candidate["workers"].append(deepcopy(candidate["workers"][0]))
    else:
        candidate["workers"].pop()

    with pytest.raises(SystemExit, match="REDUCTION_CHECKPOINT_POLICY_INVALID"):
        _checkpoint_rows(candidate, worker_ids=list(range(7)))
