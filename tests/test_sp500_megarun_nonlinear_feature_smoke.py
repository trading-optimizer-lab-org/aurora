from __future__ import annotations

import importlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


def _api():
    return importlib.import_module(
        "aurora.infra.sp500_megarun.nonlinear_feature_smoke"
    )


def test_nonlinear_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    api = _api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.NonlinearFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_nonlinear_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_nonlinear_smoke_rejects_missing_inputs(tmp_path: Path) -> None:
    api = _api()
    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()

    with pytest.raises(api.NonlinearFeatureSmokeError, match="TRAIN_DATASET_MISSING:D_SPY"):
        api.build_nonlinear_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_nonlinear_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_nonlinear_feature_smoke_f131"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_nonlinear_feature_smoke",
        lambda *_args, **_kwargs: {"ready": True, "executable_lane_count": 10},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke",
            "--train-snapshot",
            str(tmp_path / "train_snapshot_1993_2010"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert cli.main() == 0


@pytest.mark.parametrize(
    ("lane_id", "parameter", "configuration", "expected"),
    [
        ("F131", "statistic", {"scales": 2}, {"scales": 4}),
        ("F132", "ensembles", {"kind": "emd"}, {"kind": "eemd"}),
        ("F132", "noise_scale", {"kind": "emd"}, {"kind": "eemd"}),
        ("F132", "components", {"statistic": "imf1"}, {"statistic": "residual", "kind": "eemd", "noise_scale": 0.1}),
        ("F133", "embedding", {"window": 63}, {"window": 126}),
        ("F133", "components", {"statistic": "trend_component"}, {"statistic": "residual"}),
        ("F133", "statistic", {"components": 1}, {"components": 3}),
        ("F134", "min_occurrences", {"statistic": "trend"}, {"statistic": "combined"}),
        ("F135", "neighbors", {"statistic": "discord_score"}, {"statistic": "motif_follow_through"}),
        ("F135", "radius", {"statistic": "discord_score"}, {"statistic": "motif_density"}),
        ("F135", "statistic", {"neighbors": 1}, {"neighbors": 3}),
        ("F136", "minimum_line", {"statistic": "recurrence_rate"}, {"statistic": "determinism"}),
        ("F137", "q_low", {"statistic": "hurst"}, {"statistic": "multifractal_width"}),
        ("F137", "q_high", {"statistic": "hurst"}, {"statistic": "multifractal_width"}),
        ("F139", "asymmetry", {"kind": "ewma", "statistic": "filtered_volatility"}, {"kind": "asymmetric_ewma", "statistic": "variance_gap"}),
        ("F139", "kind", {"kind": "asymmetric_ewma", "asymmetry": 0.0}, {"asymmetry": 1.0}),
        ("F139", "window", {"statistic": "filtered_volatility"}, {"statistic": "variance_gap"}),
        ("F140", "transition_speed", {"kind": "setar", "statistic": "regime_state"}, {"kind": "star", "statistic": "forecast"}),
    ],
)
def test_nonlinear_parameter_witnesses_activate_conditional_choices(
    lane_id: str,
    parameter: str,
    configuration: dict[str, object],
    expected: dict[str, object],
) -> None:
    repaired = _api()._repair_nonlinear_configuration(
        lane_id,
        parameter,
        configuration.copy(),
    )

    for name, value in expected.items():
        assert repaired[name] == value


def test_nonlinear_parameter_audit_uses_lane_specific_causal_train_tails() -> None:
    dates = pd.bdate_range("2003-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    base = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates,
            "available_at": dates,
            "value": phase,
        }
    )
    earlier = base.iloc[[0]].copy()
    earlier_date = earlier["date"].iloc[0] - pd.offsets.BDay(1)
    for column in ("date", "observed_at", "available_at"):
        earlier[column] = earlier_date
    calendar = pd.concat((earlier, base), ignore_index=True)
    panels = {"spy": base.copy(), "calendar": calendar}

    short = _api()._parameter_audit_panels(panels, "F132")
    long = _api()._parameter_audit_panels(panels, "F134")

    assert len(short["spy"]) < len(long["spy"]) < len(base)
    assert short["spy"]["date"].max() == pd.Timestamp("2010-12-31")
    assert long["spy"]["date"].max() == pd.Timestamp("2010-12-31")
    assert short["spy"]["date"].isin(short["calendar"]["date"]).all()
    assert long["spy"]["date"].isin(long["calendar"]["date"]).all()
    assert short["spy"]["date"].ge(pd.Timestamp("2003-01-02")).all()
    assert long["spy"]["date"].ge(pd.Timestamp("2003-01-02")).all()
