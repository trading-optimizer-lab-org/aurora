"""Irreversible exact-OOS validation contracts for the frozen stock strategy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research.stock_protocol.campaign import evaluate_spec
from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel
from aurora.research.stock_protocol.exact_oos import (
    EXACT_CANDIDATE_ID,
    EXACT_SOURCE_ARTIFACT_DIGEST,
    EXACT_SOURCE_RUN_ID,
    ExactReproductionError,
    assert_exact_is_reproduction,
    exact_strategy_spec,
    load_frozen_manifest_authorization,
)
from aurora.research.stock_protocol.exact_oos_reporting import classify_verdict
from aurora.research.stock_protocol.campaign import EvaluationResult


def _locked_panel() -> ResearchPanel:
    dates = pd.bdate_range("2019-01-02", "2022-12-30")
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(("AAA", "BBB", "CCC")):
        close = 50.0 * np.cumprod(
            np.full(len(dates), 1.0003 + symbol_index * 0.0001)
        )
        for index, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close[index] * 0.999,
                    "high": close[index] * 1.01,
                    "low": close[index] * 0.99,
                    "close": close[index],
                    "adj_close": close[index],
                    "volume": 1_000_000.0,
                    "dividends": 0.0,
                    "stock_splits": 0.0,
                }
            )
    frame = pd.DataFrame(rows)
    audit = PackAudit(
        source_root="synthetic",
        output_root="synthetic",
        data_start="2019-01-02",
        data_end="2022-12-30",
        rows=len(frame),
        symbols=3,
        locked_rows=int(frame["date"].ge("2021-01-01").sum()),
        survivorship_free=False,
        metadata_is_bitemporal=False,
        dataset_hash="synthetic-locked",
        locked_opened=True,
    )
    return ResearchPanel(frame, audit)


def _manifest_payload(implementation_commit: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "purpose": "single_irreversible_exact_oos_validation",
        "candidate_id": EXACT_CANDIDATE_ID,
        "implementation_commit": implementation_commit,
        "source": {
            "run_id": EXACT_SOURCE_RUN_ID,
            "artifact_digest": EXACT_SOURCE_ARTIFACT_DIGEST,
        },
        "strategy_spec": exact_strategy_spec(),
        "periods": {
            "development_start": "1995-01-01",
            "development_end": "2015-12-31",
            "diagnostic_start": "2016-01-01",
            "diagnostic_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "locked_end": "2022-12-30",
        },
        "governance": {
            "strategy_count": 1,
            "optimization_allowed": False,
            "parameter_search_allowed": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
            "locked_used_for_selection": False,
            "financial_logic_changes_after_freeze": False,
        },
        "data": {
            "dataset_hash": "cc90a87a7bece9411508aefd3c4f8e26bd156b001e8e03dec33545927509e964",
            "policy_hash": "0ac27343d4a435edb19ce48887a8723e47a569b4f4942bfaa258d1cf82fce5cc",
            "survivorship_limited": True,
        },
        "costs": {
            "primary_bps_per_side": 0,
            "sensitivity_bps_per_side": [5, 10, 25, 50],
        },
    }


def _write_manifest(tmp_path, implementation_commit: str = "a" * 40):
    path = tmp_path / "frozen_manifest.json"
    path.write_text(
        json.dumps(_manifest_payload(implementation_commit), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def test_exact_strategy_identity_and_frozen_source_are_immutable():
    spec = exact_strategy_spec()

    assert EXACT_CANDIDATE_ID == "stock_3b897081e03c8d934f1d"
    assert EXACT_SOURCE_RUN_ID == "29658603488"
    assert EXACT_SOURCE_ARTIFACT_DIGEST == (
        "sha256:3936159b63e4dab5e7299fafb6996c6eb963cb4d88aea388fe6e62444a059116"
    )
    assert spec["signal_test_id"] == 2
    assert spec["signal_variant"] == {"lookback": 126, "skip": 21}
    assert spec["selection"] == {"kind": "top_percent", "value": 20.0}
    assert spec["signal_weights"] == {"weights": "equal"}
    assert len(spec["component_signals"]) == 10
    assert spec["entry"] == {
        "kind": "breakout_rvol",
        "max_wait_sessions": 21,
        "threshold": 2.5,
        "window": 20,
    }
    assert spec["exit"] == {
        "holding_sessions": 252,
        "kind": "take_profit",
        "target_pct": 50.0,
    }
    assert spec["portfolio"] == {"sizing": "equal"}
    assert spec["cost_bps"] == 0


def test_locked_data_remains_blocked_without_frozen_authorization():
    with pytest.raises(ValueError, match="locked"):
        evaluate_spec(
            _locked_panel(),
            exact_strategy_spec(),
            start="2021-01-01",
            end="2022-12-30",
        )


def test_manifest_hash_and_implementation_commit_must_match(tmp_path):
    path, digest = _write_manifest(tmp_path)

    with pytest.raises(ValueError, match="manifest hash"):
        load_frozen_manifest_authorization(
            path,
            expected_manifest_sha256="0" * 64,
            expected_implementation_commit="a" * 40,
        )
    with pytest.raises(ValueError, match="implementation commit"):
        load_frozen_manifest_authorization(
            path,
            expected_manifest_sha256=digest,
            expected_implementation_commit="b" * 40,
        )


def test_exact_manifest_authorizes_exactly_one_locked_evaluation(tmp_path):
    path, digest = _write_manifest(tmp_path)
    authorization = load_frozen_manifest_authorization(
        path,
        expected_manifest_sha256=digest,
        expected_implementation_commit="a" * 40,
    )

    result = evaluate_spec(
        _locked_panel(),
        exact_strategy_spec(),
        start="2021-01-01",
        end="2022-12-30",
        locked_authorization=authorization,
    )

    assert result.locked_opened is True
    assert result.data_end == "2022-12-30"
    with pytest.raises(ValueError, match="already consumed"):
        evaluate_spec(
            _locked_panel(),
            exact_strategy_spec(),
            start="2021-01-01",
            end="2022-12-30",
            locked_authorization=authorization,
        )


def test_authorization_cannot_be_reused_for_a_different_strategy(tmp_path):
    path, digest = _write_manifest(tmp_path)
    authorization = load_frozen_manifest_authorization(
        path,
        expected_manifest_sha256=digest,
        expected_implementation_commit="a" * 40,
    )
    changed = exact_strategy_spec()
    changed["exit"] = {**changed["exit"], "target_pct": 49.0}

    with pytest.raises(ValueError, match="candidate"):
        evaluate_spec(
            _locked_panel(),
            changed,
            start="2021-01-01",
            end="2022-12-30",
            locked_authorization=authorization,
        )


def test_manifest_cannot_enable_optimization_or_parameter_search(tmp_path):
    payload = _manifest_payload("a" * 40)
    payload["governance"]["optimization_allowed"] = True
    path = tmp_path / "frozen_manifest.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="optimization"):
        load_frozen_manifest_authorization(
            path,
            expected_manifest_sha256=digest,
            expected_implementation_commit="a" * 40,
        )


def test_strict_verdict_is_fixed_before_locked_results():
    statistics = pd.DataFrame(
        [
            {"test": "block_bootstrap_sharpe", "lower_95": 0.2, "p_value": 0.01, "estimate": 1.0},
            {"test": "paired_daily_return_ttest", "lower_95": np.nan, "p_value": 0.01, "estimate": 0.0002},
        ]
    )
    strategy = {"total_return": 1.0, "cagr": 0.20, "sharpe": 1.5}
    spy = {"total_return": 0.5, "cagr": 0.10, "sharpe": 0.8}

    assert classify_verdict(strategy, spy, statistics) == "validated_out_of_sample"
    statistics.loc[statistics["test"].eq("paired_daily_return_ttest"), "p_value"] = 0.20
    assert classify_verdict(strategy, spy, statistics) == "promising_but_inconclusive"


def test_exact_oos_workflow_is_manifest_gated_and_single_strategy():
    workflow = Path(".github/workflows/stock-protocol-scientific-tests.yml").read_text(
        encoding="utf-8"
    )

    assert "frozen_oos_strategy_manifest.json" in workflow
    assert "shard_index: [0, 1, 2, 3" in workflow
    assert "--shard-count 32" in workflow
    assert "max-parallel: 16" in workflow
    assert "evaluate-frozen-oos" in workflow
    assert "stock-protocol-exact-irrevocable-oos-results" in workflow
    assert "locked_strategy_count\"] == 1" in workflow


def _reproduction_result(ledger: pd.DataFrame) -> EvaluationResult:
    return EvaluationResult(
        candidate_id=EXACT_CANDIDATE_ID,
        spec=exact_strategy_spec(),
        status="evaluated",
        metrics={
            "cagr": 0.37236,
            "sharpe": 1.41689,
            "max_drawdown": -0.38238,
            "trades": 1.0,
        },
        equity_curve=pd.DataFrame(),
        trade_ledger=ledger,
        position_ledger=pd.DataFrame(),
        yearly=pd.DataFrame(),
        locked_opened=False,
        data_end="2015-12-31",
    )


def test_is_reproduction_requires_exact_trade_dates_symbols_and_prices():
    reference = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "signal_date": ["2008-01-31"],
            "entry_date": ["2008-02-01"],
            "entry_price": [10.0],
            "exit_date": ["2008-05-01"],
            "exit_price": [15.0],
            "exit_reason": ["take_profit"],
            "status": ["closed"],
            "fold_id": [0],
            "trade_id": [0],
            "net_return": [0.5],
        }
    )
    source_result = {
        "candidate_id": EXACT_CANDIDATE_ID,
        "cagr": 0.3723646104412519,
        "sharpe": 1.4168958719655276,
        "max_drawdown": -0.38238563062182696,
        "trades": 1,
    }

    report = assert_exact_is_reproduction(
        _reproduction_result(reference.copy()),
        source_result=source_result,
        source_trade_ledger=reference,
    )
    assert report["exact_reproduction"] is True

    changed = reference.copy()
    changed.loc[0, "entry_price"] = 10.01
    with pytest.raises(ExactReproductionError, match="trade ledger"):
        assert_exact_is_reproduction(
            _reproduction_result(changed),
            source_result=source_result,
            source_trade_ledger=reference,
        )
