from __future__ import annotations

from pathlib import Path
import hashlib

import numpy as np
import pandas as pd
import pytest


def _ledger() -> pd.DataFrame:
    index = pd.bdate_range("2000-01-03", "2001-12-31")
    return pd.DataFrame(
        {"long_return": np.where(index.year == 2000, 0.0002, 0.0001)},
        index=index,
    )


def _feature(values: np.ndarray | list[float]) -> pd.DataFrame:
    dates = _ledger().index
    return pd.DataFrame(
        {
            "date": dates,
            "available_at": dates,
            "value": values,
        }
    )


def test_feature_values_become_exact_long_short_decisions_with_carry_on_zero() -> None:
    from aurora.infra.sp500_megarun.dehb_worker import feature_frame_to_decisions

    frame = pd.DataFrame(
        {
            "date": pd.bdate_range("2000-01-03", periods=6),
            "available_at": pd.bdate_range("2000-01-03", periods=6),
            "value": [1.0, 0.0, np.nan, -0.1, 0.0, 2.0],
        }
    )

    decisions = feature_frame_to_decisions(frame, allowed_end="2010-12-31")

    assert decisions.iloc[[0, 3, 5]].tolist() == [1.0, -1.0, 1.0]
    assert decisions.iloc[[1, 2, 4]].isna().all()
    assert decisions.index.equals(pd.DatetimeIndex(frame["date"]))


def test_candidate_objective_uses_only_fidelity_years_and_returns_exact_archive_key() -> None:
    from aurora.infra.sp500_megarun.dehb_worker import evaluate_lane_candidate

    ledger = _ledger()
    ledger["long_return"] = -0.0002
    values = -np.ones(len(ledger))
    result = evaluate_lane_candidate(
        config={"window": 20},
        fidelity=1,
        lane_id="F001",
        ledger=ledger,
        feature_evaluator=lambda _lane, _config: _feature(values),
        fidelity_years={1: (2000,), 3: (2000, 2001)},
        allowed_end="2010-12-31",
    )

    assert result["fitness"] < 0.0
    assert result["cost"] == 1.0
    assert result["info"]["lane_id"] == "F001"
    assert result["info"]["target_years"] == [2000]
    assert result["info"]["train_feasible"] is True
    assert result["info"]["archive_key"][0] == 0.0
    assert result["info"]["validation_opened"] is False
    assert result["info"]["locked_opened"] is False


def test_candidate_objective_rejects_future_availability_and_unknown_fidelity() -> None:
    from aurora.infra.sp500_megarun.dehb_worker import (
        DehbWorkerError,
        evaluate_lane_candidate,
        feature_frame_to_decisions,
    )

    frame = _feature(np.ones(len(_ledger())))
    frame.loc[0, "available_at"] = frame.loc[0, "date"] + pd.Timedelta(days=1)
    with pytest.raises(DehbWorkerError, match="FEATURE_AVAILABLE_AFTER_DECISION"):
        feature_frame_to_decisions(frame, allowed_end="2010-12-31")

    with pytest.raises(DehbWorkerError, match="UNKNOWN_FIDELITY:9"):
        evaluate_lane_candidate(
            config={},
            fidelity=9,
            lane_id="F001",
            ledger=_ledger(),
            feature_evaluator=lambda _lane, _config: _feature(
                np.ones(len(_ledger()))
            ),
            fidelity_years={1: (2000,)},
            allowed_end="2010-12-31",
        )


def test_train_snapshot_loader_requires_exact_partition_manifest_and_adjusted_close(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_worker import (
        DehbWorkerError,
        load_train_total_return_ledger,
    )

    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()
    prices = pd.DataFrame(
        {
            "date": pd.bdate_range("2000-01-03", periods=4),
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "adj_close": [100.5, 101.5, 102.5, 103.5],
            "volume": [1, 1, 1, 1],
        }
    )
    prices.to_parquet(snapshot / "D_SPY.parquet", index=False)
    (snapshot / "snapshot_manifest.json").write_text(
        '{"partition":"train","validation_opened":false,"locked_opened":false}',
        encoding="utf-8",
    )

    manifest_sha256 = hashlib.sha256(
        (snapshot / "snapshot_manifest.json").read_bytes()
    ).hexdigest()
    spy_sha256 = hashlib.sha256((snapshot / "D_SPY.parquet").read_bytes()).hexdigest()
    ledger = load_train_total_return_ledger(
        snapshot,
        allowed_end="2010-12-31",
        expected_manifest_sha256=manifest_sha256,
        expected_spy_sha256=spy_sha256,
    )
    assert len(ledger) == 4

    (snapshot / "snapshot_manifest.json").write_text(
        '{"partition":"validation","validation_opened":true,"locked_opened":false}',
        encoding="utf-8",
    )
    with pytest.raises(DehbWorkerError, match="TRAIN_SNAPSHOT_BOUNDARY_OPEN"):
        load_train_total_return_ledger(
            snapshot,
            allowed_end="2010-12-31",
            expected_manifest_sha256=hashlib.sha256(
                (snapshot / "snapshot_manifest.json").read_bytes()
            ).hexdigest(),
            expected_spy_sha256=spy_sha256,
        )


def test_train_snapshot_loader_rejects_unbound_manifest_or_spy_hash(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_worker import (
        DehbWorkerError,
        load_train_total_return_ledger,
    )

    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()
    pd.DataFrame(
        {
            "date": pd.bdate_range("2000-01-03", periods=2),
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "adj_close": [100.5, 101.5],
            "volume": [1, 1],
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)
    (snapshot / "snapshot_manifest.json").write_text(
        '{"partition":"train","validation_opened":false,"locked_opened":false}',
        encoding="utf-8",
    )

    with pytest.raises(DehbWorkerError, match="TRAIN_MANIFEST_SHA256_MISMATCH"):
        load_train_total_return_ledger(
            snapshot,
            allowed_end="2010-12-31",
            expected_manifest_sha256="a" * 64,
            expected_spy_sha256=hashlib.sha256(
                (snapshot / "D_SPY.parquet").read_bytes()
            ).hexdigest(),
        )


def test_train_lane_registry_covers_all_240_and_builds_one_lazy_context(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_lane_registry import (
        FamilyAdapter,
        TrainLaneEvaluator,
        supported_lane_ids,
    )

    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()
    manifest_path = snapshot / "snapshot_manifest.json"
    manifest_path.write_text(
        '{"partition":"train","validation_opened":false,"locked_opened":false,'
        '"mountable_by_first_cycle":true,"datasets":{"D_SPY":{"sha256":"'
        + "b" * 64
        + '"}}}',
        encoding="utf-8",
    )
    built: list[str] = []

    def builder(_owner):
        built.append("built")
        return lambda lane, config: pd.DataFrame(
            {
                "date": [pd.Timestamp("2000-01-03")],
                "available_at": [pd.Timestamp("2000-01-03")],
                "value": [float(config["value"])],
                "lane": [lane],
            }
        )

    registry = TrainLaneEvaluator(
        snapshot,
        expected_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        expected_spy_sha256="b" * 64,
        default_configurations={lane: {} for lane in supported_lane_ids()},
        adapters=(FamilyAdapter(1, 240, builder),),
    )

    assert supported_lane_ids() == tuple(f"F{i:03d}" for i in range(1, 241))
    assert registry("F001", {"value": 1})["lane"].iloc[0] == "F001"
    assert registry("F240", {"value": -1})["value"].iloc[0] == -1.0
    assert built == ["built"]


def test_train_lane_registry_rejects_unknown_lane_and_incomplete_adapter_coverage(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_lane_registry import (
        FamilyAdapter,
        LaneRegistryError,
        TrainLaneEvaluator,
        supported_lane_ids,
    )

    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()
    manifest_path = snapshot / "snapshot_manifest.json"
    manifest_path.write_text(
        '{"partition":"train","validation_opened":false,"locked_opened":false,'
        '"mountable_by_first_cycle":true,"datasets":{"D_SPY":{"sha256":"'
        + "c" * 64
        + '"}}}',
        encoding="utf-8",
    )
    common = {
        "train_snapshot": snapshot,
        "expected_manifest_sha256": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "expected_spy_sha256": "c" * 64,
        "default_configurations": {lane: {} for lane in supported_lane_ids()},
    }
    with pytest.raises(LaneRegistryError, match="LANE_ADAPTER_COVERAGE_MISMATCH"):
        TrainLaneEvaluator(
            **common,
            adapters=(FamilyAdapter(1, 239, lambda _owner: lambda *_args: pd.DataFrame()),),
        )

    registry = TrainLaneEvaluator(
        **common,
        adapters=(FamilyAdapter(1, 240, lambda _owner: lambda *_args: pd.DataFrame()),),
    )
    with pytest.raises(LaneRegistryError, match="UNKNOWN_LANE:F241"):
        registry("F241", {})
