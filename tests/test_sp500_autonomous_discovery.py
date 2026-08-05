from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

from aurora.infra.sp500_autonomous_discovery import registry
from aurora.infra.sp500_autonomous_discovery.contracts import canonical_rule_hash
from aurora.infra.sp500_autonomous_discovery.dedupe import build_dedupe_map
from aurora.infra.sp500_autonomous_discovery.feature_store import FeatureStore
from aurora.infra.sp500_autonomous_discovery.scheduling import assign_by_cost
from aurora.infra.sp500_autonomous_discovery.statistics import evaluate_batch
from aurora.infra.sp500_autonomous_discovery.validation import (
    ValidationGateError,
    _verify_freeze,
)
from aurora.infra.sp500_long_short_daily.data import PreparedMarketData
from aurora.infra.sp500_long_short_daily.signals import candidate_decisions


def _template() -> dict[str, object]:
    candidate = {
        "strategy_id": "template",
        "instrument": "SPY",
        "family": "price_trend_sma",
        "variant_label": "template",
        "evidence_track": "pre_2011_evidence",
        "position_values": [-1, 1],
        "absolute_exposure": 1.0,
        "cash_allowed": False,
        "partial_exposure_allowed": False,
        "leverage_allowed": False,
        "volatility_scaling_allowed": False,
        "pyramiding_allowed": False,
        "multiple_assets_in_portfolio": False,
        "locked_boundary": ">=2021-01-01 unopened",
        "commission_bps": 0.0,
        "slippage_bps": 0.0,
        "borrow_cost_bps": 0.0,
        "financing_bps": 0.0,
        "switching_cost_bps": 0.0,
        "market_impact_bps": 0.0,
        "required_datasets": ["DS001"],
        "parameters": {"window": 20, "threshold": 0.1},
        "rules": {"entry": "close > sma(window)", "exit": "reverse"},
        "complexity_score": 1,
        "priority_score": 10,
    }
    candidate["canonical_hash"] = canonical_rule_hash(candidate)
    return candidate


def test_canonical_hash_ignores_identity_but_changes_effective_rule() -> None:
    first = _template()
    second = dict(first, strategy_id="other", notes="new note", research_source_ids=["new"])
    assert canonical_rule_hash(first) == canonical_rule_hash(second)
    changed = dict(first, parameters={"window": 21, "threshold": 0.1})
    assert canonical_rule_hash(first) != canonical_rule_hash(changed)


def test_candidate_generation_is_reproducible_and_contract_bound(monkeypatch) -> None:
    fake_package = SimpleNamespace(
        candidates=(_template(),),
        research=(),
        features=(),
        datasets=(),
    )
    monkeypatch.setattr(registry, "base_package", lambda: fake_package)
    first = registry.generate_candidates(2, count=8)
    second = registry.generate_candidates(2, count=8)
    assert [row["strategy_id"] for row in first] == [row["strategy_id"] for row in second]
    assert [row["canonical_hash"] for row in first] == [row["canonical_hash"] for row in second]
    assert {row["position_values"][0] for row in first} == {-1}
    assert all(row["position_values"] == [-1, 1] for row in first)
    assert all(row["locked_boundary"] == ">=2021-01-01 unopened" for row in first)


def test_trial_ledger_is_cumulative_and_pre_registered(tmp_path, monkeypatch) -> None:
    candidates = tuple(_template() | {"strategy_id": f"candidate-{index}", "canonical_hash": canonical_rule_hash(_template() | {"strategy_id": f"candidate-{index}"})} for index in range(3))
    monkeypatch.setattr(registry, "base_package", lambda: SimpleNamespace(candidates=(), research=(), features=(), datasets=()))
    registry.write_batch_registry(
        tmp_path,
        batch_id=4,
        candidates=candidates,
        previous_trial_count=312,
    )
    rows = registry.read_jsonl(tmp_path / "trial_ledger.jsonl")
    assert [row["global_trial_index"] for row in rows] == [313, 314, 315]
    assert all(row["pre_registered_before_performance"] is True for row in rows)
    manifest = json.loads((tmp_path / "candidate_registry_manifest.json").read_text(encoding="utf-8"))
    assert manifest["global_trial_count_after_batch"] == 315
    assert manifest["trial_ledger_rows"] == 3


def test_trial_ledger_appends_to_prior_batch(tmp_path, monkeypatch) -> None:
    prior = [
        {
            "batch_id": 0,
            "canonical_hash": f"hash-{index}",
            "global_trial_index": index,
            "pre_registered_before_performance": True,
            "status": "registered",
            "strategy_id": f"prior-{index}",
        }
        for index in range(1, 4)
    ]
    prior_path = tmp_path / "prior" / "trial_ledger.jsonl"
    registry.write_jsonl(prior_path, prior)
    monkeypatch.setenv("AURORA_PRIOR_TRIAL_LEDGER_PATH", str(prior_path))
    candidate = _template() | {
        "strategy_id": "candidate-4",
        "canonical_hash": canonical_rule_hash(_template() | {"strategy_id": "candidate-4"}),
    }
    monkeypatch.setattr(
        registry,
        "base_package",
        lambda: SimpleNamespace(candidates=(), research=(), features=(), datasets=()),
    )
    registry.write_batch_registry(
        tmp_path / "current",
        batch_id=1,
        candidates=(candidate,),
        previous_trial_count=3,
    )
    rows = registry.read_jsonl(tmp_path / "current" / "trial_ledger.jsonl")
    assert [row["global_trial_index"] for row in rows] == [1, 2, 3, 4]
    assert (tmp_path / "current" / "autonomous_trial_ledger.parquet").is_file()


def test_trial_ledger_requires_prior_source_after_first_batch(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AURORA_PRIOR_TRIAL_LEDGER_PATH", raising=False)
    monkeypatch.setattr(
        registry,
        "base_package",
        lambda: SimpleNamespace(candidates=(), research=(), features=(), datasets=()),
    )
    with pytest.raises(ValueError, match="PRIOR_TRIAL_LEDGER_REQUIRED"):
        registry.write_batch_registry(
            tmp_path,
            batch_id=2,
            candidates=(_template(),),
            previous_trial_count=313,
        )


def _metric_row(strategy_id: str, values: np.ndarray, *, family: str = "price_trend_sma") -> dict[str, object]:
    dates = pd.date_range("2000-01-03", periods=len(values), freq="B")
    return {
        "unit_key": strategy_id,
        "unit_type": "candidate",
        "strategy_id": strategy_id,
        "family": family,
        "canonical_hash": strategy_id,
        "status": "evaluated",
        "train_dates": [item.isoformat() for item in dates],
        "train_returns": values.tolist(),
        "train_positions": [1 if index % 2 else -1 for index in range(len(values))],
        "annual_metrics_json": json.dumps([
            {"year": 2000, "sessions": len(values), "return_pct": 5.0, "cagr_pct": 5.0, "sharpe": 1.0, "positive": True}
        ]),
    }


def test_evaluate_batch_writes_auditable_rows(tmp_path) -> None:
    candidate = _metric_row("AUTO-1", np.full(30, 0.001))
    benchmark = dict(_metric_row("buy_and_hold_spy_total_return", np.full(30, 0.0005)))
    benchmark["unit_type"] = "benchmark"
    result = evaluate_batch([candidate, benchmark], tmp_path, batch_id=0)
    assert result["total_strategies_evaluated"] == 1
    leaderboard = pd.read_csv(tmp_path / "leaderboard.csv")
    assert set(leaderboard["strategy_id"]) == {"AUTO-1", "buy_and_hold_spy_total_return"}
    summary = json.loads((tmp_path / "autonomous_batch_summary.json").read_text(encoding="utf-8"))
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    freeze = _verify_freeze(tmp_path / "train_selection_freeze.json")
    assert freeze["locked_opened"] is False
    assert json.loads((tmp_path / "train_freeze_candidate.json").read_text(encoding="utf-8")) == freeze
    with pytest.raises(ValidationGateError, match="TRAIN_FREEZE_NOT_ELIGIBLE"):
        _verify_freeze(tmp_path / "train_selection_freeze.json", require_finalized=True)


def test_dedupe_and_cost_assignment_are_traceable() -> None:
    first = _template()
    second = dict(first, strategy_id="same-effective-rule", notes="different identity")
    dedupe = build_dedupe_map([first, second])
    assert len(dedupe) == 2
    assert sum(bool(row["deduped"]) for row in dedupe) == 1
    assignments = assign_by_cost(
        [
            {"strategy_id": "slow", "canonical_hash": "s", "cost_score": 5.0},
            {"strategy_id": "fast", "canonical_hash": "f", "cost_score": 0.5},
        ],
        2,
    )
    assert {row["strategy_id"] for row in assignments} == {"slow", "fast"}
    assert {row["estimated_cost_bucket"] for row in assignments} == {"slow", "fast"}


def test_feature_store_is_causal_and_keyed() -> None:
    index = pd.date_range("2020-01-01", periods=260, freq="B")
    frame = pd.DataFrame(
        {
            "tr_close": np.linspace(100, 130, len(index)),
            "high": np.linspace(101, 131, len(index)),
            "low": np.linspace(99, 129, len(index)),
            "volume": np.full(len(index), 1000.0),
        },
        index=index,
    )
    store = FeatureStore(dataset_sha256="data", code_sha="code", start="2020-01-01", end="2020-12-31")
    features = store.get_or_build("SPY", frame)
    assert features.index.equals(index)
    assert features.loc[index[0], "return_20d"] != features.loc[index[-1], "return_20d"]
    assert store.key("SPY").value == store.key("SPY").value
    assert store.key("SPY").value != store.key("OTHER").value
    assert "SPY" in store.manifest()["symbols"]


def test_cached_price_signal_matches_uncached_signal() -> None:
    index = pd.date_range("2000-01-01", periods=260, freq="B")
    close = pd.Series(np.linspace(100.0, 130.0, len(index)), index=index)
    ledger = pd.DataFrame(
        {
            "tr_close": close,
            "tr_open": close,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "volume": 1000.0,
            "long_return": close.pct_change().fillna(0.0),
            "short_return": -close.pct_change().fillna(0.0),
        },
        index=index,
    )
    data = PreparedMarketData(
        ledger=ledger,
        series={},
        available_dataset_ids=frozenset({"DS001"}),
        rejected_datasets={},
        receipts=(),
        split="train",
    )
    store = FeatureStore(
        dataset_sha256="data",
        code_sha="code",
        start="2000-01-01",
        end="2000-12-31",
    )
    features = store.get_or_build("SPY", ledger)
    cases = (
        ("price_trend_sma", {"lookback": 20}),
        ("time_series_momentum", {"lookback": 20}),
        ("short_horizon_reversal", {"lookback": 20}),
        ("trend_ensemble", {"horizons": [20, 63]}),
        ("dual_ma_cross", {"fast": 10, "slow": 20}),
    )
    for family, parameters in cases:
        candidate = _template() | {
            "family": family,
            "required_datasets": ["DS001"],
            "parameters": parameters,
        }
        uncached = candidate_decisions(candidate, data).decisions
        cached = candidate_decisions(candidate, data, feature_frame=features).decisions
        pd.testing.assert_series_equal(uncached, cached)


def test_workflow_is_github_only_and_bounded() -> None:
    path = ".github/workflows/sp500-autonomous-discovery.yml"
    text = open(path, encoding="utf-8").read()
    yaml.safe_load(text)
    assert "C:\\" not in text
    assert "self-hosted" not in text
    assert "ubuntu-24.04" in text
    assert "2010-12-31" in text
    assert "2020-12-31" in text
    assert "2021-01-01" in text
    assert "OPEN_VALIDATION_2011_2020_ONCE_AUTONOMOUS" in text
    assert "sp500-autonomous-validation-once" in text
    assert "cancel-in-progress: false" in text
    assert "autonomous_prior_ledger_artifact_name" in open(
        ".github/workflows/_aurora-future-run-v3.yml", encoding="utf-8"
    ).read()
    for phase in ("preflight", "research", "data_build", "pilot", "search_batch", "merge_batch", "statistical_gate", "freeze", "validation_once", "verify"):
        assert f"- {phase}" in text
