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
    compose_selected_signals,
    load_selection_manifest,
    score_validation_returns,
    validate_selection_manifest,
    write_validation_baselines,
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
    combined = pd.read_parquet(receipt.snapshot_dir / ("D_SPY" + ".parquet"))
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


def test_authorized_evaluator_accepts_only_validation_bound_baselines(tmp_path):
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
    roots = {}
    report_names = {
        "price": "feature_smoke_report.json",
        "market": "market_feature_smoke_report.json",
        "macro": "macro_feature_smoke_report.json",
    }
    for family, report_name in report_names.items():
        root = tmp_path / f"baseline_{family}"
        (root / "features").mkdir(parents=True)
        artifacts = {}
        if family == "price":
            feature = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2011-01-03"]),
                    "available_at": pd.to_datetime(["2011-01-03"]),
                    "value": [1.0],
                }
            )
            target = root / "features" / "F001.parquet"
            feature.to_parquet(target, index=False)
            artifacts["F001"] = {
                "path": "features/F001.parquet",
                "sha256": _sha256(target),
            }
        (root / report_name).write_text(
            json.dumps(
                {
                    "ready": True,
                    "validation_opened": True,
                    "locked_opened": False,
                    "artifacts": artifacts,
                }
            ),
            encoding="utf-8",
        )
        roots[family] = root
    evaluator = AuthorizedValidationLaneEvaluator(
        receipt.snapshot_dir,
        expected_manifest_sha256=receipt.manifest_sha256,
        expected_spy_sha256=receipt.spy_sha256,
        default_configurations={f"F{number:03d}": {} for number in range(1, 241)},
        authorization=VALIDATION_ACK,
        baseline_feature_dirs=roots,
    )

    loaded = evaluator._baseline_features(["F001"])

    assert loaded["F001"]["date"].max() == pd.Timestamp("2011-01-03")


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


def test_selected_compositions_keep_exact_catalog_semantics():
    index = pd.to_datetime(["2011-01-03", "2011-01-04", "2011-01-05"])
    first = pd.Series([1.0, -1.0, pd.NA], index=index, dtype="Float64")
    second = pd.Series([1.0, 1.0, -1.0], index=index)

    pd.testing.assert_series_equal(
        compose_selected_signals([first], {"kind": "identity"}),
        pd.Series([1.0, -1.0, float("nan")], index=index, name="decision"),
    )
    pd.testing.assert_series_equal(
        compose_selected_signals([first, second], {"kind": "and"}),
        pd.Series([1.0, float("nan"), float("nan")], index=index, name="decision"),
    )
    assert compose_selected_signals(
        [first, second],
        {"kind": "weighted_score", "weights": [1.0, -0.5]},
    ).tolist() == [1.0, -1.0, 1.0]
    assert compose_selected_signals(
        [first, second],
        {"kind": "override", "base_component_index": 0, "priority_component_index": 1},
    ).tolist() == [1.0, 1.0, -1.0]


def test_validation_baselines_cover_f001_f050_and_record_open_boundary(tmp_path):
    calls = []

    def evaluator(lane_id, configuration):
        calls.append((lane_id, configuration))
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2010-12-31", "2020-12-31"]),
                "available_at": pd.to_datetime(["2010-12-31", "2020-12-31"]),
                "value": [0.0, 1.0],
            }
        )

    roots = write_validation_baselines(
        evaluator,
        {f"F{number:03d}": {"window": number} for number in range(1, 241)},
        tmp_path / "validation_baselines",
    )

    assert [lane for lane, _ in calls] == [f"F{number:03d}" for number in range(1, 51)]
    for family, expected_count in {"price": 20, "market": 11, "macro": 19}.items():
        report_name = {
            "price": "feature_smoke_report.json",
            "market": "market_feature_smoke_report.json",
            "macro": "macro_feature_smoke_report.json",
        }[family]
        report = json.loads((roots[family] / report_name).read_text("utf-8"))
        assert report["ready"] is True
        assert report["validation_opened"] is True
        assert report["locked_opened"] is False
        assert len(report["artifacts"]) == expected_count
