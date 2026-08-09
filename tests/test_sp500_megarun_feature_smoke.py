from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _smoke_api():
    try:
        return importlib.import_module("aurora.infra.sp500_megarun.feature_smoke")
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"feature smoke implementation is missing: {exc}")


def _full_train_spy() -> pd.DataFrame:
    dates = pd.bdate_range("1993-01-22", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    close = 100.0 + 0.02 * phase + 3.0 * np.sin(phase / 17.0)
    open_ = np.roll(close, 1) * (1.0 + 0.001 * np.cos(phase / 11.0))
    open_[0] = close[0]
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": np.maximum(open_, close) + 0.75,
            "low": np.minimum(open_, close) - 0.75,
            "close": close,
            "volume": 1_000_000.0 + 100_000.0 * (1.0 + np.sin(phase / 7.0)),
        }
    )


def test_price_smoke_builds_twenty_train_only_feature_artifacts(tmp_path: Path) -> None:
    api = _smoke_api()

    report = api.build_price_feature_smoke(_full_train_spy(), output_dir=tmp_path)

    assert report["ready"] is True
    assert report["executable_lane_count"] == 20
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert len(list((tmp_path / "features").glob("F*.parquet"))) == 20
    assert (tmp_path / "feature_smoke_report.json").exists()


def test_price_smoke_rejects_a_2011_row(tmp_path: Path) -> None:
    api = _smoke_api()
    spy = _full_train_spy()
    extra = spy.iloc[[-1]].copy()
    extra["date"] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.FeatureEngineError, match="NON_TRAIN_PRICE_ROW"):
        api.build_price_feature_smoke(
            pd.concat([spy, extra], ignore_index=True),
            output_dir=tmp_path,
        )
