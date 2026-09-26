import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_objective import FastTrainObjective
from aurora.infra.sp500_megarun.dehb_lane_registry import AuthorizedValidationLaneEvaluator
from aurora.infra.sp500_megarun.selected_validation import (
    VALIDATION_ACK,
    SelectedValidationError,
    build_authorized_validation_snapshot,
)
from aurora.infra.sp500_megarun.strategy_catalog import CatalogComponentV1
from scripts import run_sp500_atlas_validation_14 as atlas_validation


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(path: Path, partition: str, dates: list[str]) -> Path:
    path.mkdir()
    target = path / "D_SPY.parquet"
    pd.DataFrame({"date": pd.to_datetime(dates), "value": range(len(dates))}).to_parquet(target)
    (path / "snapshot_manifest.json").write_text(
        json.dumps({
            "contract_sha256": "a" * 64,
            "partition": partition,
            "validation_opened": False,
            "locked_opened": False,
            "datasets": {"D_SPY": {"sha256": _sha256(target)}},
        }),
        encoding="utf-8",
    )
    return path


def test_atlas_gate_reuses_existing_snapshot_verifier_without_weakening_it(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    args = SimpleNamespace(
        preflight_only=False,
        authorization="WRONG",
        output_dir=tmp_path / "result",
        working_dir=tmp_path / "work",
        final_results=tmp_path / "final",
        plan=tmp_path / "plan.json",
    )
    with pytest.raises(ValueError, match="ATLAS_VALIDATION_AUTHORIZATION_REQUIRED"):
        atlas_validation.run_validation(args)
    args.authorization = atlas_validation.ATLAS_VALIDATION_ACK
    def after_gate(*_args):
        raise RuntimeError("PAST_ATLAS_GATE")

    monkeypatch.setattr(atlas_validation, "load_frozen_frontier", after_gate)
    with pytest.raises(RuntimeError, match="PAST_ATLAS_GATE"):
        atlas_validation.run_validation(args)

    train = _snapshot(tmp_path / "train_snapshot_1993_2010", "train", ["2010-12-31"])
    validation = _snapshot(tmp_path / "validation_snapshot_2011_2020", "validation", ["2011-01-03", "2020-12-31"])
    output = tmp_path / "authorized_validation_snapshot_1993_2020"
    with pytest.raises(SelectedValidationError, match="AUTHORIZATION"):
        build_authorized_validation_snapshot(
            train, validation, output,
            authorization=atlas_validation.ATLAS_VALIDATION_ACK,
        )
    receipt = build_authorized_validation_snapshot(
        train, validation, output,
        authorization=VALIDATION_ACK,
    )
    assert receipt.validation_opened is True
    assert receipt.locked_opened is False
    assert receipt.maximum_date == "2020-12-31"
    defaults = {f"F{number:03d}": {} for number in range(1, 241)}
    with pytest.raises(ValueError, match="AUTHORIZATION"):
        AuthorizedValidationLaneEvaluator(
            receipt.snapshot_dir,
            expected_manifest_sha256=receipt.manifest_sha256,
            expected_spy_sha256=receipt.spy_sha256,
            default_configurations=defaults,
            authorization=atlas_validation.ATLAS_VALIDATION_ACK,
        )
    evaluator = AuthorizedValidationLaneEvaluator(
        receipt.snapshot_dir,
        expected_manifest_sha256=receipt.manifest_sha256,
        expected_spy_sha256=receipt.spy_sha256,
        default_configurations=defaults,
        authorization=VALIDATION_ACK,
    )
    assert evaluator.snapshot == receipt.snapshot_dir.resolve()


def test_frozen_frontier_requires_exact_hash_and_fourteen_unique_ids(tmp_path, monkeypatch):
    final = tmp_path / "final"
    final.mkdir()
    rows = []
    for ordinal in range(14):
        recipe = f"{ordinal:064x}"
        row = {
            "ordinal": ordinal,
            "raw_ordinal": ordinal,
            "strategy_id": "ATLAS1-" + recipe,
            "scientific_recipe_sha256": recipe,
            "plan_sha256": "p" * 64,
            "validation_opened": False,
            "locked_opened": False,
        }
        rows.append({**row, "result_sha256": canonical_sha256(row)})
    frontier = final / "pareto_frontier.jsonl"
    frontier.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    digest = _sha256(frontier)
    monkeypatch.setattr(atlas_validation, "FRONTIER_SHA256", digest)
    monkeypatch.setattr(atlas_validation, "PLAN_SHA256", "p" * 64)
    monkeypatch.setattr(atlas_validation, "CATALOG_MANIFEST_SHA256", "c" * 64)
    monkeypatch.setattr(atlas_validation, "load_plan", lambda _: SimpleNamespace(
        plan_sha256="p" * 64,
        catalog_manifest_sha256="c" * 64,
        selected_raw_ordinal=lambda value: value,
    ))
    (final / "reduction_receipt.json").write_text(json.dumps({
        "accepted": True,
        "requested_recipe_count": 209906,
        "verified_recipe_count": 209906,
        "pareto_recipe_count": 14,
        "frontier_sha256": digest,
        "plan_sha256": "p" * 64,
        "catalog_manifest_sha256": "c" * 64,
        "validation_opened": False,
        "locked_opened": False,
    }), encoding="utf-8")
    assert len(atlas_validation.load_frozen_frontier(final, tmp_path / "plan.json")) == 14
    frontier.write_text(frontier.read_text("utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="FRONTIER_HASH_MISMATCH"):
        atlas_validation.load_frozen_frontier(final, tmp_path / "plan.json")


def test_train_parity_is_required_before_validation_data(tmp_path):
    dates = pd.to_datetime([f"{year}-01-02" for year in range(1997, 2012)])
    ledger = pd.DataFrame({"long_return": [0.01] * len(dates)}, index=dates)
    objective = FastTrainObjective(ledger, target_years=tuple(range(1998, 2011)), allowed_end="2011-01-02")
    component = CatalogComponentV1.create("F001", {"window": 2})

    def evaluator(_lane, _configuration):
        return pd.DataFrame({"date": dates, "available_at": dates, "value": [1.0] * len(dates)})

    row = {
        "components": [component.configuration_sha256],
        "composition": {"kind": "identity", "direction": 1},
        "position_sha256": "0" * 64,
        "annualized_strategy_return": 0.0,
    }
    with pytest.raises(ValueError, match="TRAIN_POSITION_MISMATCH"):
        atlas_validation._score_rows(
            [row], {component.configuration_sha256: component}, evaluator, objective,
            pd.DatetimeIndex(ledger.index), allowed_end="2011-01-02", validation=False,
        )
