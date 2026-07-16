"""Complete scientific artifact and derived-count contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.finalize_stock_protocol_scientific import finalize_scientific_artifact


MANIFEST = Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"


REQUIRED_OUTPUTS = {
    "protocol_manifest.json",
    "data_audit.json",
    "final_summary.json",
    "implementation_matrix.csv",
    "unsupported_missing_data.csv",
    "signal_layer_results.csv",
    "weight_layer_results.csv",
    "entry_layer_results.csv",
    "exit_layer_results.csv",
    "portfolio_layer_results.csv",
    "cost_scenarios.csv",
    "walk_forward_results.csv",
    "robustness_results.csv",
    "daily_equity_curves",
    "trade_ledgers",
    "position_ledgers",
    "yearly_results.csv",
    "pareto_frontier.csv",
    "pareto_by_cost.csv",
    "pareto_by_horizon.csv",
    "parameter_stability.csv",
    "statistical_tests.csv",
    "holdout_2016_2020.csv",
    "run_audit.md",
    "final_recommendation.md",
}


def _result_rows(phase: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "candidate_id": ["balanced", "dominated"],
            "phase": [phase, phase],
            "cagr": [0.15, 0.10],
            "sortino": [1.5, 0.8],
            "calmar": [1.0, 0.5],
            "return_per_capital_day": [0.001, 0.0005],
            "max_drawdown": [-0.15, -0.25],
            "expected_shortfall_5": [-0.03, -0.05],
            "turnover": [2.0, 7.0],
            "average_days_invested": [80.0, 100.0],
            "total_costs": [100.0, 400.0],
            "horizon_sessions": [252, 252],
            "cost_bps": [10, 10],
            "locked_opened": [False, False],
            "data_end": ["2020-12-31", "2020-12-31"],
        }
    )


def _complete_input(root: Path) -> None:
    phases = (
        "signal",
        "weight",
        "entry",
        "exit",
        "portfolio",
        "cost",
        "walk_forward",
        "robustness",
    )
    for phase in phases:
        _result_rows(phase).to_csv(root / f"{phase}_results.csv", index=False)
    (root / "data_audit.json").write_text(
        json.dumps(
            {
                "data_start": "1995-01-01",
                "data_end": "2020-12-31",
                "locked_opened": False,
                "locked_rows": 0,
                "universe_mode": "current_universe_backfill",
                "survivorship_limited": True,
                "dataset_hash": "dataset-hash",
            }
        ),
        encoding="utf-8",
    )
    for directory in ("daily_equity_curves", "trade_ledgers", "position_ledgers"):
        path = root / directory
        path.mkdir(exist_ok=True)
        pd.DataFrame({"candidate_id": ["balanced"], "value": [1.0]}).to_csv(
            path / "balanced.csv", index=False
        )
    pd.DataFrame({"candidate_id": ["balanced"], "year": [2020], "return": [0.1]}).to_csv(
        root / "yearly_results.csv", index=False
    )
    pd.DataFrame({"candidate_id": ["balanced"], "parameter": ["window"], "stable": [True]}).to_csv(
        root / "parameter_stability.csv", index=False
    )
    pd.DataFrame({"candidate_id": ["balanced"], "method": ["bootstrap"], "pvalue": [0.02]}).to_csv(
        root / "statistical_tests.csv", index=False
    )
    pd.DataFrame(
        {
            "candidate_id": ["balanced"],
            "period_start": ["2016-01-01"],
            "period_end": ["2020-12-31"],
            "evaluation_count": [1],
            "selection_used": [False],
            "locked_opened": [False],
        }
    ).to_csv(root / "holdout_2016_2020.csv", index=False)


def test_final_artifact_is_complete_and_counts_are_derived(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "final"
    source.mkdir()
    _complete_input(source)

    finalize_scientific_artifact(source, output, MANIFEST)

    assert REQUIRED_OUTPUTS <= {path.name for path in output.iterdir()}
    summary = json.loads((output / "final_summary.json").read_text(encoding="utf-8"))
    matrix = pd.read_csv(output / "implementation_matrix.csv")
    unsupported = pd.read_csv(output / "unsupported_missing_data.csv")
    assert summary["tests_total"] == len(matrix) == 36
    assert summary["tests_unsupported_missing_data"] == len(unsupported) == 11
    assert summary["partial"] is False
    assert summary["locked_opened"] is False
    assert summary["survivorship_limited"] is True
    assert summary["counts_derived_from_files"] is True
    assert set(pd.read_csv(output / "pareto_frontier.csv")["candidate_id"]) == {"balanced"}
    recommendation = (output / "final_recommendation.md").read_text(encoding="utf-8")
    assert "survivorship" in recommendation.lower()
    assert "2021" in recommendation
    assert "balanced" in recommendation


def test_finalizer_refuses_partial_inputs_instead_of_claiming_complete(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _complete_input(source)
    (source / "robustness_results.csv").unlink()
    with pytest.raises(ValueError, match="missing required input"):
        finalize_scientific_artifact(source, tmp_path / "final", MANIFEST)


def test_finalizer_rejects_locked_or_non_finite_results(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _complete_input(source)
    locked = _result_rows("portfolio")
    locked.loc[0, "locked_opened"] = True
    locked.to_csv(source / "portfolio_results.csv", index=False)
    with pytest.raises(ValueError, match="locked"):
        finalize_scientific_artifact(source, tmp_path / "locked-final", MANIFEST)
    _complete_input(source)
    invalid = _result_rows("portfolio")
    invalid.loc[0, "cagr"] = float("inf")
    invalid.to_csv(source / "portfolio_results.csv", index=False)
    with pytest.raises(ValueError, match="non-finite"):
        finalize_scientific_artifact(source, tmp_path / "invalid-final", MANIFEST)


def test_finalizer_builds_pareto_from_net_cost_results(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _complete_input(source)
    portfolio = _result_rows("portfolio")
    portfolio.loc[0, "candidate_id"] = "gross_only_winner"
    portfolio.loc[1, "candidate_id"] = "net_winner"
    portfolio.to_csv(source / "portfolio_results.csv", index=False)
    costs = _result_rows("cost")
    costs.loc[0, "candidate_id"] = "net_winner"
    costs.loc[1, "candidate_id"] = "gross_only_winner"
    costs.to_csv(source / "cost_results.csv", index=False)

    finalize_scientific_artifact(source, tmp_path / "final", MANIFEST)

    assert set(pd.read_csv(tmp_path / "final" / "pareto_frontier.csv")["candidate_id"]) == {
        "net_winner"
    }


def test_finalizer_accepts_preholdout_phase_with_earlier_actual_data_end(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _complete_input(source)
    robustness = _result_rows("robustness")
    robustness["data_end"] = "2015-12-31"
    robustness["evaluation_end"] = "2015-12-31"
    robustness.to_csv(source / "robustness_results.csv", index=False)

    finalize_scientific_artifact(source, tmp_path / "final", MANIFEST)

    assert (tmp_path / "final" / "final_summary.json").is_file()


def test_final_recommendation_covers_required_scientific_conclusions(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _complete_input(source)
    finalize_scientific_artifact(source, tmp_path / "final", MANIFEST)

    recommendation = (tmp_path / "final" / "final_recommendation.md").read_text(
        encoding="utf-8"
    ).lower()
    for required in (
        "errores del run anterior",
        "correcciones aplicadas",
        "valor marginal",
        "entradas",
        "salidas",
        "sizing",
        "costes",
        "walk-forward",
        "holdout",
        "pareto",
        "survivorship",
        "datos pendientes",
    ):
        assert required in recommendation
