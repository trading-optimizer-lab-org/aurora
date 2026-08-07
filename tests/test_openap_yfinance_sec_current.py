from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from aurora.research.openap_current_score import (
    EXPECTED_PREDICTORS,
    FeatureValue,
    OpenAPDataError,
    assemble_feature_table,
    build_redundancy_groups,
    build_horizon_evidence_weights,
    calculate_accounting_features,
    calculate_price_features,
    calculate_scores,
    calculate_six_coverage_scores,
    coverage_report,
    latest_sec_concepts,
    select_strict_predictors,
)


def _metadata(rows: int = EXPECTED_PREDICTORS) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signalname": [f"signal_{index:03d}" for index in range(rows)],
            "Cat.Signal": "Predictor",
            "tstat": 2.5,
            "T.Stat": 2.2,
            "Sign": 1.0,
            "portperiod": 1.0,
            "Cat.Data": "Price",
            "Cat.Economic": "Test",
            "Signal.Rep.Quality": "1_good",
        }
    )


def test_strict_selection_requires_exactly_185() -> None:
    selected = select_strict_predictors(_metadata())
    assert len(selected) == 185
    with pytest.raises(OpenAPDataError):
        select_strict_predictors(_metadata(184))


def test_redundancy_groups_catch_positive_and_mirror_signals() -> None:
    metadata = _metadata(3)
    metadata.loc[:, "signalname"] = ["a", "b", "c"]
    metadata.loc[:, "Sign"] = [1.0, 1.0, -1.0]
    returns = pd.DataFrame(
        {
            "a": np.arange(100, dtype=float),
            "b": np.arange(100, dtype=float) * 2,
            "c": np.arange(100, dtype=float) * -3,
        }
    )
    groups = build_redundancy_groups(metadata, returns, threshold=0.8, minimum_overlap=60)
    assert groups["redundancy_group"].nunique() == 1
    assert set(groups["signalname"]) == {"a", "b", "c"}


def test_sec_concepts_ignore_facts_not_yet_available() -> None:
    facts = pd.DataFrame(
        {
            "tag": ["Assets", "Assets"],
            "value": [100.0, 999.0],
            "period_end": ["2024-12-31", "2025-12-31"],
            "available_at": ["2025-02-01T12:00:00Z", "2026-02-01T12:00:00Z"],
        }
    )
    concepts = latest_sec_concepts(facts, pd.Timestamp("2025-06-01"))
    assert concepts["assets"][0] == 100.0
    assert 999.0 not in concepts["assets"]


def test_price_features_are_real_and_trendfactor_is_disclosed_proxy() -> None:
    dates = pd.bdate_range("2021-01-01", periods=1100)
    frame = pd.DataFrame(
        {
            "date": dates,
            "adj_close": np.linspace(10, 100, len(dates)),
            "close": np.linspace(10, 100, len(dates)),
            "high": np.linspace(10.1, 100.1, len(dates)),
            "low": np.linspace(9.9, 99.9, len(dates)),
            "volume": 1_000_000,
        }
    )
    result = calculate_price_features(frame)
    assert result["Mom12m"].status == "exact"
    assert result["TrendFactor"].status == "proxy"
    assert result["TrendFactor"].raw_value is not None


def test_accounting_features_do_not_fill_missing_with_zero() -> None:
    concepts = {
        "assets": [100.0, 80.0],
        "equity": [60.0, 50.0],
        "net_income": [10.0, 9.0],
        "operating_cash_flow": [8.0, 7.0],
        "revenue": [150.0, 130.0],
    }
    result = calculate_accounting_features(concepts, market_cap=200.0)
    assert result["BM"].raw_value == pytest.approx(0.3)
    assert result["AssetGrowth"].raw_value == pytest.approx(0.25)
    assert result["ChInv"].raw_value is None


def test_score_gives_one_vote_to_redundancy_group() -> None:
    metadata = _metadata()
    metadata.loc[0, "signalname"] = "a"
    metadata.loc[1, "signalname"] = "b"
    groups = pd.DataFrame(
        {
            "signalname": metadata["signalname"],
            "redundancy_group": ["same", "same"] + [f"g{i}" for i in range(183)],
        }
    )
    values = {
        "AAA": {
            "a": FeatureValue("a", 1.0, "exact", "test", "a"),
            "b": FeatureValue("b", 1.0, "exact", "test", "b"),
            **{
                f"signal_{index:03d}": FeatureValue(f"signal_{index:03d}", float(index), "exact", "test", "x")
                for index in range(2, 185)
            },
        },
        "BBB": {
            "a": FeatureValue("a", 0.0, "exact", "test", "a"),
            "b": FeatureValue("b", 0.0, "exact", "test", "b"),
            **{
                f"signal_{index:03d}": FeatureValue(f"signal_{index:03d}", float(index - 1), "exact", "test", "x")
                for index in range(2, 185)
            },
        },
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01", redundancy_groups=groups)
    scores = calculate_scores(features)
    assert not scores.empty
    assert scores.loc[scores["symbol"].eq("AAA"), "groups_used"].iloc[0] == 184


def test_horizon_weights_use_tstats_and_full_correlation_matrix() -> None:
    metadata = pd.DataFrame(
        {
            "signalname": ["a", "b", "c"],
            "portperiod": [1, 1, 1],
            "tstat": [3.0, 3.0, 3.0],
        }
    )
    correlation = pd.DataFrame(
        [[1.0, 0.99, 0.0], [0.99, 1.0, 0.0], [0.0, 0.0, 1.0]],
        index=["a", "b", "c"],
        columns=["a", "b", "c"],
    )
    weights = build_horizon_evidence_weights(metadata, correlation, horizons=(1,))
    by_signal = weights.set_index("signalname")["score_weight"]
    assert weights["score_weight"].sum() == pytest.approx(1.0)
    assert by_signal["c"] > by_signal["a"]
    assert by_signal["c"] > by_signal["b"]
    assert by_signal["a"] == pytest.approx(by_signal["b"], rel=1e-4)


def test_six_scores_apply_total_92_metric_coverage_tiers() -> None:
    signals = [f"signal_{index:03d}" for index in range(92)]
    metadata = pd.DataFrame(
        {
            "signalname": signals,
            "portperiod": [1] * 44 + [12] * 48,
            "tstat": 3.0,
        }
    )
    correlation = pd.DataFrame(np.eye(92), index=signals, columns=signals)
    weights = build_horizon_evidence_weights(metadata, correlation, horizons=(1, 12))
    rows = []
    available_by_symbol = {"C92": 92, "C75": 75, "C65": 65, "C55": 55}
    for symbol, available in available_by_symbol.items():
        for index, signal in enumerate(signals):
            rows.append(
                {
                    "as_of": "2026-08-07",
                    "symbol": symbol,
                    "signalname": signal,
                    "raw_value": float(index + len(symbol)) if index < available else np.nan,
                    "status": "exact",
                    "horizon_months": int(metadata.loc[index, "portperiod"]),
                }
            )
    features = pd.DataFrame(rows)
    scores = calculate_six_coverage_scores(
        features,
        weights,
        eligible_signals=signals,
        coverage_thresholds=(80, 70, 60),
        horizons=(1, 12),
    )
    assert set(scores["score_id"]) == {
        "openap_1m_c80",
        "openap_12m_c80",
        "openap_1m_c70",
        "openap_12m_c70",
        "openap_1m_c60",
        "openap_12m_c60",
    }
    universe_sizes = scores.groupby("minimum_total_metrics")["universe_size"].first().to_dict()
    assert universe_sizes == {60: 3, 70: 2, 80: 1}
    symbols_by_tier = {
        threshold: set(group["symbol"])
        for threshold, group in scores.groupby("minimum_total_metrics")
    }
    assert symbols_by_tier[80] == {"C92"}
    assert symbols_by_tier[70] == {"C92", "C75"}
    assert symbols_by_tier[60] == {"C92", "C75", "C65"}
    assert scores["score"].between(0.0, 100.0).all()


def test_coverage_has_one_row_for_every_strict_predictor() -> None:
    metadata = _metadata()
    values = {
        "AAA": {
            "signal_000": FeatureValue("signal_000", 1.0, "exact", "test", "formula")
        }
    }
    features = assemble_feature_table(metadata, values, as_of="2026-08-01")
    report = coverage_report(features, metadata)
    assert len(report) == 185
    assert report.loc[report["signalname"].eq("signal_000"), "coverage_status"].iloc[0] == "exact"


def test_workflow_contract_is_github_only_and_complete() -> None:
    text = Path(".github/workflows/openap-yfinance-sec-current-score.yml").read_text(encoding="utf-8")
    config = Path("config/openap_yfinance_sec_current.yaml").read_text(encoding="utf-8")
    registry = [
        line.strip()
        for line in Path("config/openap_current_score_92_signals.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "OpenAP Current Score YFinance SEC EDGAR" in text
    assert "YFINANCE_CHUNKS: \"48\"" in text
    assert "max-parallel: 16" in text
    assert "sec-bulk" in text
    assert "openap-sec-raw-archives" in text
    assert "openap-yfinance-sec-current-score-results" in text
    assert "locked_opened" in text
    assert "backtest_enabled" in text
    assert "openap_six_scores_current.csv" in text
    assert "openap_six_scores_current_wide.csv" in text
    assert "horizons_months: [1, 12]" in config
    assert "coverage_universe_minimum_metrics: [80, 70, 60]" in config
    assert len(registry) == 92
    assert len(set(registry)) == 92


def test_existing_snapshot_workflow_downloads_and_checks_all_six_universes() -> None:
    text = Path(".github/workflows/openap-six-scores-existing-snapshot.yml").read_text(encoding="utf-8")
    assert "OpenAP Six Scores From Existing Snapshot" in text
    assert "gh run download" in text
    assert "openap_features_current.parquet" in text
    assert "score-snapshot" in text
    assert '"openap_1m_c80": 366' in text
    assert '"openap_12m_c70": 1250' in text
    assert '"openap_1m_c60": 2031' in text
    assert "locked_opened" in text
