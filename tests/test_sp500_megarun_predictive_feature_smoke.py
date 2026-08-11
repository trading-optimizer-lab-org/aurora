from __future__ import annotations

import importlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


def _api():
    return importlib.import_module(
        "aurora.infra.sp500_megarun.predictive_feature_smoke"
    )


def _write_inputs(root: Path) -> tuple[Path, dict[str, Path]]:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2005-01-03", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    returns = 0.0003 + 0.004 * np.sin(phase / 13.0) + 0.002 * np.cos(phase / 31.0)
    close = 100.0 * np.exp(np.cumsum(returns))
    pd.DataFrame({"date": dates}).to_parquet(snapshot / "D_CALENDAR.parquet", index=False)
    pd.DataFrame(
        {
            "date": dates,
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1_000_000.0 * (1.2 + 0.1 * np.sin(phase / 17.0)),
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)
    pd.DataFrame(
        {
            "date": dates,
            "resource_id": "vix_from_2003",
            "CLOSE": 20.0 + 3.0 * np.sin(phase / 23.0),
        }
    ).to_parquet(snapshot / "D_VIX.parquet", index=False)
    pd.DataFrame(
        {
            "date": dates,
            "4": 19.0 + 2.0 * np.cos(phase / 29.0),
            "Unnamed: 4": np.nan,
        }
    ).to_parquet(snapshot / "D_VXO.parquet", index=False)

    roots = {
        "F003": root / "price",
        "F015": root / "price",
        "F021": root / "market",
        "F032": root / "macro",
        "F039": root / "macro",
    }
    for target in set(roots.values()):
        (target / "features").mkdir(parents=True)
    decision_dates = dates[1:]
    for offset, (lane, target) in enumerate(roots.items(), start=1):
        pd.DataFrame(
            {
                "date": decision_dates,
                "observed_at": dates[:-1],
                "available_at": decision_dates,
                "value": np.sin(phase[1:] / (6.0 + offset))
                + 0.2 * np.cos(phase[1:] / (11.0 + offset)),
            }
        ).to_parquet(target / "features" / f"{lane}.parquet", index=False)
    return snapshot, roots


def test_predictive_smoke_builds_f141_f150_train_only_artifacts(tmp_path: Path) -> None:
    api = _api()
    snapshot, roots = _write_inputs(tmp_path)

    report = api.build_predictive_feature_smoke(
        snapshot,
        price_feature_dir=roots["F003"],
        market_feature_dir=roots["F021"],
        macro_feature_dir=roots["F032"],
        output_dir=tmp_path / "out",
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(141, 151)]
    assert report["executable_lane_count"] == 10
    assert report["approved_causal_inputs"] == ["F003", "F015", "F021", "F032", "F039"]
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    parameter_audit = report["parameter_choice_audit"]
    assert parameter_audit["ready"] is True
    assert parameter_audit["expected_choice_probe_count"] == 310
    assert parameter_audit["choice_probe_count"] == 310
    assert parameter_audit["failed_probes"] == []
    assert parameter_audit["inactive_choice_groups"] == []
    assert (tmp_path / "out" / "features" / "F141.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F150.parquet").is_file()


def test_predictive_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    api = _api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.PredictiveFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_predictive_feature_smoke(
            wrong,
            price_feature_dir=tmp_path / "price",
            market_feature_dir=tmp_path / "market",
            macro_feature_dir=tmp_path / "macro",
            output_dir=tmp_path / "out",
        )


def test_predictive_smoke_rejects_missing_approved_feature(tmp_path: Path) -> None:
    api = _api()
    snapshot, roots = _write_inputs(tmp_path)
    (roots["F039"] / "features" / "F039.parquet").unlink()

    with pytest.raises(api.PredictiveFeatureSmokeError, match="CAUSAL_FEATURE_MISSING:F039"):
        api.build_predictive_feature_smoke(
            snapshot,
            price_feature_dir=roots["F003"],
            market_feature_dir=roots["F021"],
            macro_feature_dir=roots["F032"],
            output_dir=tmp_path / "out",
        )


def test_predictive_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_predictive_feature_smoke_f141"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_predictive_feature_smoke",
        lambda *_args, **_kwargs: {"ready": True, "executable_lane_count": 10},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke",
            "--train-snapshot",
            str(tmp_path / "train_snapshot_1993_2010"),
            "--price-feature-dir",
            str(tmp_path / "price"),
            "--market-feature-dir",
            str(tmp_path / "market"),
            "--macro-feature-dir",
            str(tmp_path / "macro"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert cli.main() == 0


@pytest.mark.parametrize(
    ("lane_id", "parameter", "configuration", "expected"),
    [
        ("F141", "statistic", {"statistic": "innovation", "kind": "ar"}, {"kind": "arma", "ma_order": 1}),
        ("F141", "ma_order", {"ma_order": 2, "kind": "ar"}, {"kind": "arma"}),
        ("F141", "ma_order", {"ma_order": 0, "kind": "arma"}, {"kind": "ar"}),
        ("F141", "volume_lags", {"kind": "ar"}, {"kind": "distributed_regression"}),
        ("F141", "kind", {"kind": "arma", "ma_order": 0}, {"ma_order": 1}),
        ("F142", "statistic", {"statistic": "error_correction", "kind": "var"}, {"kind": "vecm"}),
        ("F143", "sign_rule", {"statistic": "explained_share"}, {"statistic": "factor_score", "components": 3}),
        ("F144", "forecast_quantile", {"statistic": "median_skew"}, {"statistic": "quantile_forecast"}),
        ("F144", "tail_quantile", {"statistic": "quantile_forecast"}, {"statistic": "median_skew"}),
        ("F145", "gamma", {"kind": "linear"}, {"kind": "rbf"}),
        ("F145", "degree", {"kind": "linear"}, {"kind": "polynomial"}),
        ("F145", "support_vectors", {"window": 126}, {"window": 252}),
        ("F150", "temperature", {"kind": "moe", "statistic": "forecast_z"}, {"kind": "attention", "statistic": "attention_entropy"}),
        ("F150", "experts", {"kind": "attention", "statistic": "forecast_z"}, {"kind": "moe", "statistic": "expert_disagreement"}),
        ("F150", "gate", {"kind": "attention", "statistic": "forecast_z"}, {"kind": "moe", "statistic": "expert_disagreement", "lookback": 10}),
        ("F150", "statistic", {"kind": "attention", "statistic": "expert_disagreement"}, {"kind": "moe"}),
    ],
)
def test_predictive_parameter_witnesses_activate_conditional_choices(
    lane_id: str,
    parameter: str,
    configuration: dict[str, object],
    expected: dict[str, object],
) -> None:
    repaired = _api()._repair_predictive_configuration(
        lane_id,
        parameter,
        configuration.copy(),
    )

    assert repaired["refit"] == "annual"
    for name, value in expected.items():
        assert repaired[name] == value


def test_predictive_parameter_audit_uses_date_aligned_causal_train_tails() -> None:
    dates = pd.bdate_range("2003-01-02", "2010-12-31")
    base = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates,
            "available_at": dates,
            "value": np.arange(len(dates), dtype=float),
        }
    )
    market = base.assign(
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0 + np.arange(len(dates), dtype=float),
        volume=1_000_000.0,
    )
    earlier = base.iloc[[0]].copy()
    earlier_date = earlier["date"].iloc[0] - pd.offsets.BDay(1)
    for column in ("date", "observed_at", "available_at"):
        earlier[column] = earlier_date
    cboe = pd.concat((earlier.assign(vix_close=20.0), base.assign(vix_close=20.0)), ignore_index=True)
    features = {
        lane: pd.concat((earlier, base), ignore_index=True)
        for lane in ("F003", "F015", "F021", "F032", "F039")
    }

    short_panels, short_features = _api()._parameter_audit_inputs(
        {"spy": market, "cboe": cboe}, features, "F143"
    )
    long_panels, long_features = _api()._parameter_audit_inputs(
        {"spy": market, "cboe": cboe}, features, "F149"
    )

    assert len(short_panels["spy"]) < len(long_panels["spy"]) < len(market)
    assert short_panels["spy"]["date"].max() == pd.Timestamp("2010-12-31")
    assert long_panels["spy"]["date"].max() == pd.Timestamp("2010-12-31")
    assert short_panels["spy"]["date"].isin(short_panels["cboe"]["date"]).all()
    assert long_panels["spy"]["date"].isin(long_panels["cboe"]["date"]).all()
    assert all(panel["date"].max() == pd.Timestamp("2010-12-31") for panel in short_features.values())
    assert all(panel["date"].max() == pd.Timestamp("2010-12-31") for panel in long_features.values())


def test_predictive_physical_smoke_has_an_isolated_dispatch_scope() -> None:
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "sp500-megarun-macro-feature-smoke-f032.yml"
    ).read_text(encoding="utf-8")

    assert "- f141_f150" in workflow
    assert "smoke_f141_f150:" in workflow
    assert "inputs.scope == 'f141_f150'" in workflow
    assert "timeout-minutes: 20" in workflow
