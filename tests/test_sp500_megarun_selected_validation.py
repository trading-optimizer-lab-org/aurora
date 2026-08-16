import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from aurora.infra.sp500_megarun.dehb_lane_registry import (
    AuthorizedValidationLaneEvaluator,
    TrainLaneEvaluator,
)
from aurora.infra.sp500_megarun.selected_validation import (
    VALIDATION_ACK,
    SelectedValidationError,
    build_authorized_validation_snapshot,
    load_selection_manifest,
    score_validation_returns,
    validate_selection_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_snapshot(
    root: Path,
    *,
    partition: str,
    dates: list[str],
    validation_opened: bool = False,
    extra_dataset: bool = False,
) -> Path:
    root.mkdir()
    datasets = {}
    dataset_ids = ["D_SPY", *(("D_EXTRA",) if extra_dataset else ())]
    for dataset_id in dataset_ids:
        frame = pd.DataFrame({"date": pd.to_datetime(dates), "value": range(len(dates))})
        path = root / f"{dataset_id}.parquet"
        frame.to_parquet(path, index=False)
        datasets[dataset_id] = {"sha256": _sha256(path)}
    manifest = {
        "contract_sha256": "a" * 64,
        "partition": partition,
        "mountable_by_first_cycle": partition == "train",
        "validation_opened": validation_opened,
        "locked_opened": False,
        "datasets": datasets,
    }
    (root / "snapshot_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return root


def test_authorized_snapshot_combines_warmup_but_stops_before_locked(tmp_path):
    train = _write_snapshot(
        tmp_path / "train_snapshot_1993_2010",
        partition="train",
        dates=["2010-12-30", "2010-12-31"],
    )
    validation = _write_snapshot(
        tmp_path / "validation_snapshot_2011_2020",
        partition="validation",
        dates=["2011-01-03", "2020-12-31"],
    )

    receipt = build_authorized_validation_snapshot(
        train,
        validation,
        tmp_path / "authorized_validation_snapshot_1993_2020",
        authorization=VALIDATION_ACK,
    )

    manifest = json.loads((receipt.snapshot_dir / "snapshot_manifest.json").read_text("utf-8"))
    combined = pd.read_parquet(receipt.snapshot_dir / "D_SPY.parquet")
    assert manifest["partition"] == "authorized_validation"
    assert manifest["validation_opened"] is True
    assert manifest["locked_opened"] is False
    assert combined["date"].max() == pd.Timestamp("2020-12-31")
    assert combined["date"].tolist() == [
        pd.Timestamp("2010-12-30"),
        pd.Timestamp("2010-12-31"),
        pd.Timestamp("2011-01-03"),
        pd.Timestamp("2020-12-31"),
    ]


@pytest.mark.parametrize(
    ("authorization", "validation_opened", "validation_dates", "extra_dataset", "error"),
    [
        ("WRONG", False, ["2011-01-03"], False, "AUTHORIZATION"),
        (VALIDATION_ACK, True, ["2011-01-03"], False, "ALREADY_OPEN"),
        (VALIDATION_ACK, False, ["2021-01-04"], False, "LOCKED"),
        (VALIDATION_ACK, False, ["2011-01-03"], True, "DATASET_SET"),
    ],
)
def test_authorized_snapshot_fails_closed(
    tmp_path,
    authorization,
    validation_opened,
    validation_dates,
    extra_dataset,
    error,
):
    train = _write_snapshot(
        tmp_path / "train_snapshot_1993_2010",
        partition="train",
        dates=["2010-12-31"],
    )
    validation = _write_snapshot(
        tmp_path / "validation_snapshot_2011_2020",
        partition="validation",
        dates=validation_dates,
        validation_opened=validation_opened,
        extra_dataset=extra_dataset,
    )

    with pytest.raises(SelectedValidationError, match=error):
        build_authorized_validation_snapshot(
            train,
            validation,
            tmp_path / "authorized_validation_snapshot_1993_2020",
            authorization=authorization,
        )


def test_only_authorized_evaluator_can_mount_opened_validation(tmp_path):
    train = _write_snapshot(
        tmp_path / "train_snapshot_1993_2010",
        partition="train",
        dates=["2010-12-31"],
    )
    validation = _write_snapshot(
        tmp_path / "validation_snapshot_2011_2020",
        partition="validation",
        dates=["2011-01-03", "2020-12-31"],
    )
    receipt = build_authorized_validation_snapshot(
        train,
        validation,
        tmp_path / "authorized_validation_snapshot_1993_2020",
        authorization=VALIDATION_ACK,
    )
    defaults = {f"F{number:03d}": {} for number in range(1, 241)}

    with pytest.raises(ValueError, match="TRAIN_SNAPSHOT_PARTITION_REQUIRED"):
        TrainLaneEvaluator(
            receipt.snapshot_dir,
            expected_manifest_sha256=receipt.manifest_sha256,
            expected_spy_sha256=receipt.spy_sha256,
            default_configurations=defaults,
        )
    evaluator = AuthorizedValidationLaneEvaluator(
        receipt.snapshot_dir,
        expected_manifest_sha256=receipt.manifest_sha256,
        expected_spy_sha256=receipt.spy_sha256,
        default_configurations=defaults,
        authorization=VALIDATION_ACK,
    )
    assert evaluator.snapshot == receipt.snapshot_dir.resolve()
    with pytest.raises(ValueError, match="AUTHORIZATION"):
        AuthorizedValidationLaneEvaluator(
            receipt.snapshot_dir,
            expected_manifest_sha256=receipt.manifest_sha256,
            expected_spy_sha256=receipt.spy_sha256,
            default_configurations=defaults,
            authorization="WRONG",
        )


def _selection_payload(count: int = 12):
    return {
        "schema_version": 1,
        "selection_id": "sp500-selected-12-before-validation-v1",
        "source_train_run_id": 31932275712,
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "validation_opened": False,
        "locked_opened": False,
        "strategies": [
            {
                "selection_order": number,
                "name": f"strategy-{number}",
                "source_kind": "catalog",
                "source_id": f"source-{number}",
                "components": [
                    {
                        "lane_id": f"F{number:03d}",
                        "configuration": {"window": 20, "direction": "continuation"},
                    }
                ],
                "composition": {"kind": "identity"},
                "train_metrics": {
                    "annualized_strategy_return": 0.10,
                    "annualized_alpha": 0.05,
                    "weekly_winning_or_positive_rate": 0.60,
                },
            }
            for number in range(1, count + 1)
        ],
    }


def test_selection_manifest_requires_exactly_twelve_unique_frozen_recipes():
    first = validate_selection_manifest(_selection_payload())
    second = validate_selection_manifest(_selection_payload())

    assert len(first) == 12
    assert [row.recipe_sha256 for row in first] == [
        row.recipe_sha256 for row in second
    ]
    with pytest.raises(SelectedValidationError, match="STRATEGY_COUNT"):
        validate_selection_manifest(_selection_payload(11))
    duplicate = _selection_payload()
    duplicate["strategies"][1] = dict(duplicate["strategies"][0])
    duplicate["strategies"][1]["selection_order"] = 2
    duplicate["strategies"][1]["source_id"] = "source-duplicate"
    with pytest.raises(SelectedValidationError, match="STRATEGY_DUPLICATE"):
        validate_selection_manifest(duplicate)


def test_committed_selection_is_frozen_and_still_closed_before_validation():
    manifest = load_selection_manifest(
        Path("config/sp500_megarun_selected_validation_12.json")
    )

    assert len(manifest.strategies) == 12
    assert manifest.source_train_run_id == 31932275712
    assert manifest.validation_opened is False
    assert manifest.locked_opened is False
    assert len({row.recipe_sha256 for row in manifest.strategies}) == 12


def test_validation_metrics_count_weekly_union_and_yearly_objective():
    dates = pd.to_datetime([f"{year}-06-30" for year in range(2011, 2021)])
    strategy = pd.Series([0.10, -0.10, -0.10, *([0.10] * 7)], index=dates)
    spy = pd.Series([0.20, -0.20, 0.10, *([0.05] * 7)], index=dates)

    result = score_validation_returns(strategy, spy)

    assert result["week_count"] == 10
    assert result["positive_weeks"] == 8
    assert result["weeks_beating_spy"] == 8
    assert result["winning_or_positive_weeks"] == 9
    assert result["weekly_winning_or_positive_rate"] == pytest.approx(0.9)
    assert result["positive_years"] == 8
    assert result["years_beating_spy"] == 8
    assert result["years_passing_both"] == 7
    assert result["average_return_when_spy_falls"] == pytest.approx(-0.10)
    assert list(result["annual_returns"]) == [str(year) for year in range(2011, 2021)]
    assert result["validation_opened"] is True
    assert result["locked_opened"] is False


def test_validation_metrics_reject_any_locked_date():
    dates = pd.to_datetime([f"{year}-06-30" for year in range(2011, 2022)])
    returns = pd.Series([0.01] * len(dates), index=dates)

    with pytest.raises(SelectedValidationError, match="LOCKED"):
        score_validation_returns(returns, returns)
