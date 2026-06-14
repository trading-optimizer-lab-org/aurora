from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.run_sr_15m_equity_universe import (
    FINAL_ARTIFACT_NAME,
    build_equity_feature_panel,
    equal_thirds_split_masks,
    run_features,
    run_locked_retest,
    run_merge,
    run_screen,
    sr_feature_columns,
    find_raw_data_dir,
)

pytestmark = pytest.mark.filterwarnings("ignore::pandas.errors.PerformanceWarning")


def make_symbol_bars(days: int = 60, *, offset: float = 0.0, reversal: bool = False) -> pd.DataFrame:
    stamps = []
    for day in pd.bdate_range("2026-01-02", periods=days):
        start = day + pd.Timedelta(hours=9, minutes=30)
        stamps.extend(start + pd.Timedelta(minutes=15 * i) for i in range(26))
    idx = pd.DatetimeIndex(stamps)
    x = np.arange(len(idx), dtype=float)
    trend = x * (0.02 if not reversal else -0.02)
    wave = np.sin(x / 13.0) * 0.8
    close = pd.Series(100.0 + offset + trend + wave, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([open_, close], axis=1).max(axis=1) + 0.20
    low = pd.concat([open_, close], axis=1).min(axis=1) - 0.20
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": 1_000_000},
        index=idx,
    )


def write_raw_universe(root: Path, symbols: list[str], *, days: int = 60) -> Path:
    data_dir = root / "source" / "data"
    data_dir.mkdir(parents=True)
    common_index: list[str] | None = None
    for i, symbol in enumerate(symbols):
        bars = make_symbol_bars(days=days, offset=float(i), reversal=(i % 2 == 1))
        bars.to_csv(data_dir / f"{symbol}_15m.csv", index_label="timestamp")
        stamps = [str(v) for v in bars.index]
        common_index = stamps if common_index is None else common_index
    manifest = {
        "source": "test",
        "interval": "15m",
        "downloaded_symbols": symbols,
        "symbol_count": len(symbols),
        "common_rows_per_symbol": days * 26,
        "common_start": common_index[0],
        "common_end": common_index[-1],
    }
    (root / "source" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root / "source"


def test_equal_thirds_split_masks_are_exact_for_1560_rows() -> None:
    train, validation, locked = equal_thirds_split_masks(1560)

    assert int(train.sum()) == 520
    assert int(validation.sum()) == 520
    assert int(locked.sum()) == 520
    assert train[:520].all()
    assert validation[520:1040].all()
    assert locked[1040:].all()
    assert not train[520:].any()
    assert not validation[:520].any()
    assert not validation[1040:].any()
    assert not locked[:1040].any()


def test_build_equity_feature_panel_adds_sr_only_features_and_equal_split() -> None:
    panel, audit = build_equity_feature_panel(make_symbol_bars(), symbol="AAA", target_bars=4)
    feature_cols = sr_feature_columns(panel)

    assert feature_cols
    assert all(c.startswith("sr_") for c in feature_cols)
    assert {"train", "validation", "locked"} == set(panel["split"].dropna().unique())
    split_counts = panel["split"].value_counts().to_dict()
    assert split_counts["train"] == split_counts["validation"] == split_counts["locked"]
    assert audit["symbol"] == "AAA"
    assert audit["split_policy"] == "equal_temporal_thirds_train_validation_locked"
    assert audit["feature_count"] == len(feature_cols)
    assert any("retest" in c or "fakeout" in c or "reclaim" in c for c in feature_cols)


def test_features_mode_rejects_missing_minimum_symbols(tmp_path: Path) -> None:
    input_dir = write_raw_universe(tmp_path, ["AAA", "BBB", "CCC"])

    with pytest.raises(RuntimeError, match="minimo requerido"):
        run_features(tmp_path / "out", input_dir=input_dir, min_symbols=20, target_bars=4)


def test_find_raw_data_dir_handles_nested_github_artifact_download(tmp_path: Path) -> None:
    input_dir = write_raw_universe(tmp_path / "artifact_root", ["AAA", "BBB", "CCC"])
    nested = tmp_path / "downloaded" / "free-15m-equity-universe-yfinance-data"
    nested.mkdir(parents=True)
    (nested / "data").mkdir()
    for path in (input_dir / "data").glob("*_15m.csv"):
        (nested / "data" / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    assert find_raw_data_dir(tmp_path / "downloaded") == nested / "data"


def test_pipeline_keeps_locked_out_of_screen_and_retests_at_end(tmp_path: Path) -> None:
    symbols = [f"S{i:02d}" for i in range(3)]
    input_dir = write_raw_universe(tmp_path, symbols)
    output_dir = tmp_path / "out"

    run_features(output_dir, input_dir=input_dir, min_symbols=3, target_bars=4)
    run_screen(
        output_dir,
        stage=0,
        total_stages=100,
        top_n=20,
        cost_bps=1.0,
        target_bars=4,
    )
    run_merge(output_dir, target_sharpe=0.0, top_n=20, min_validation_symbols=1)
    run_locked_retest(
        output_dir,
        source_candidates=output_dir / "final" / "accepted.csv",
        stage=0,
        candidates_per_stage=100,
        top_n=20,
        cost_bps=1.0,
        target_bars=4,
    )

    shard = pd.read_csv(output_dir / "screen" / "stage_000" / "top_candidates.csv")
    assert not shard.empty
    assert "locked_sharpe" not in shard.columns
    assert set(shard["selection_split"].unique()) == {"train_validation_only"}

    locked = pd.read_csv(output_dir / "locked" / "stage_000" / "locked_results.csv")
    assert not locked.empty
    assert "locked_sharpe_pooled" in locked.columns
    assert "locked_positive_symbols" in locked.columns


def test_workflow_is_manual_and_has_expected_artifact() -> None:
    path = Path(".github/workflows/sr-15m-equity-universe-feature-search.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "Free 15m S/R Equity Universe Feature Search"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    assert data[True]["workflow_dispatch"]["inputs"]["source_run_id"]["default"] == "27498064404"
    assert data[True]["workflow_dispatch"]["inputs"]["source_artifact"]["default"] == "free-15m-equity-universe-yfinance-data"
    assert "locked_retest" in data["jobs"]
    assert FINAL_ARTIFACT_NAME in text
