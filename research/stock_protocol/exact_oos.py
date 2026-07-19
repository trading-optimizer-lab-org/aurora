"""Frozen identity and manifest verification for one exact OOS evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .campaign import EvaluationResult, canonical_candidate_id
from .locked_access import LockedDataAuthorization, issue_locked_data_authorization


EXACT_CANDIDATE_ID = "stock_3b897081e03c8d934f1d"
EXACT_SOURCE_RUN_ID = "29658603488"
EXACT_SOURCE_ARTIFACT_NAME = (
    "stock-protocol-scientific-full-universe-360jobs-corrected-results"
)
EXACT_SOURCE_ARTIFACT_DIGEST = (
    "sha256:3936159b63e4dab5e7299fafb6996c6eb963cb4d88aea388fe6e62444a059116"
)
EXACT_SOURCE_TASK_RUN_ID = "29558183535"
EXACT_SOURCE_TASK_ARTIFACT_NAME = "stock-protocol-exits-task-144"
EXACT_SOURCE_TASK_ARTIFACT_DIGEST = (
    "sha256:e324fcf5fe6bc1148ae95e6f08922683ceeb290a97f8c6e415d6f297535d5e20"
)
EXACT_DATASET_HASH = "cc90a87a7bece9411508aefd3c4f8e26bd156b001e8e03dec33545927509e964"
EXACT_POLICY_HASH = "0ac27343d4a435edb19ce48887a8723e47a569b4f4942bfaa258d1cf82fce5cc"


class ExactReproductionError(ValueError):
    """The implementation does not reproduce the frozen source result."""


def _component(
    signal_test_id: int,
    signal_variant: dict[str, object],
    selection: dict[str, object],
    signal_variant_index: int,
) -> dict[str, object]:
    return {
        "cost_bps": 0,
        "entry": {"kind": "immediate_next_open", "max_wait_sessions": 0},
        "exit": {"holding_sessions": 63, "kind": "none"},
        "horizon_sessions": 63,
        "portfolio": {"sizing": "equal"},
        "selection": selection,
        "signal_test_id": signal_test_id,
        "signal_variant": signal_variant,
        "signal_variant_index": signal_variant_index,
    }


def exact_strategy_spec() -> dict[str, Any]:
    """Return the complete immutable source spec from exits task 144."""

    momentum = {"lookback": 126, "skip": 21}
    components = [
        _component(2, momentum, {"kind": "top_percent", "value": 5.0}, 0),
        _component(2, momentum, {"kind": "top_percent", "value": 10.0}, 0),
        _component(2, momentum, {"kind": "decile", "value": 1}, 0),
        _component(8, {"lookback": 252, "portfolio": "top_10"}, {"kind": "top_n", "value": 20}, 0),
        _component(8, {"lookback": 252, "portfolio": "top_20"}, {"kind": "top_n", "value": 20}, 1),
        _component(8, {"lookback": 252, "portfolio": "top_20"}, {"kind": "top_percent", "value": 5.0}, 1),
        _component(8, {"lookback": 252, "portfolio": "top_10"}, {"kind": "top_percent", "value": 5.0}, 0),
        _component(3, {"lookback": 252, "sizing": "inverse_vol", "skip": 21}, {"kind": "top_percent", "value": 30.0}, 1),
        _component(3, {"lookback": 252, "sizing": "raw", "skip": 21}, {"kind": "top_percent", "value": 30.0}, 0),
        _component(2, momentum, {"kind": "quintile", "value": 1}, 0),
    ]
    return {
        "component_signals": components,
        "cost_bps": 0,
        "entry": {
            "kind": "breakout_rvol",
            "max_wait_sessions": 21,
            "threshold": 2.5,
            "window": 20,
        },
        "entry_test_id": 18,
        "entry_variant_index": 3,
        "exit": {
            "holding_sessions": 252,
            "kind": "take_profit",
            "target_pct": 50.0,
        },
        "exit_test_id": 26,
        "exit_variant_index": 5,
        "horizon_sessions": 252,
        "portfolio": {"sizing": "equal"},
        "selection": {"kind": "top_percent", "value": 20.0},
        "signal_test_id": 2,
        "signal_variant": momentum,
        "signal_variant_index": 0,
        "signal_weights": {"weights": "equal"},
        "upstream_candidate_id": "stock_1bd7e9b629da67074fea",
        "upstream_candidate_ids": [
            "stock_caf4098a86b69c4f11da",
            "stock_bd1c8222441c7f12dfa5",
            "stock_f02ef45ca858fa84d6b5",
            "stock_d236469e524c2d34e70f",
            "stock_f973dae27c67dd57beea",
            "stock_a876ce65a3070313c249",
            "stock_e95149f21d98197dd139",
            "stock_4a3f198ba057ab2e08d3",
            "stock_d55d4d78efad32a17cf7",
            "stock_894e846146ccf8588b9b",
        ],
        "weight_test_id": 13,
        "weight_variant_index": 0,
    }


def _ordered_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "symbol",
        "signal_date",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "exit_reason",
        "status",
        "fold_id",
        "trade_id",
        "net_return",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ExactReproductionError(
            f"trade ledger missing frozen columns: {sorted(missing)}"
        )
    result = frame[list(required)].copy()
    for column in ("signal_date", "entry_date", "exit_date"):
        result[column] = pd.to_datetime(result[column], errors="raise").dt.strftime(
            "%Y-%m-%d"
        )
    return result.sort_values(
        ["fold_id", "signal_date", "symbol", "trade_id"],
        kind="stable",
    ).reset_index(drop=True)


def assert_exact_is_reproduction(
    actual: EvaluationResult,
    *,
    source_result: dict[str, object],
    source_trade_ledger: pd.DataFrame,
) -> dict[str, object]:
    """Require frozen metrics and every source trade identity to reproduce."""

    if actual.status != "evaluated":
        raise ExactReproductionError(f"IS status is {actual.status!r}")
    if actual.locked_opened:
        raise ExactReproductionError("IS reproduction opened locked")
    if actual.candidate_id != EXACT_CANDIDATE_ID:
        raise ExactReproductionError("IS candidate identity mismatch")
    if source_result.get("candidate_id") != EXACT_CANDIDATE_ID:
        raise ExactReproductionError("source candidate identity mismatch")
    tolerances = {
        "cagr": 0.0002,
        "sharpe": 0.005,
        "max_drawdown": 0.0002,
    }
    metric_rows: dict[str, dict[str, float | bool]] = {}
    for name, tolerance in tolerances.items():
        expected = float(source_result[name])
        observed = float(actual.metrics[name])
        difference = observed - expected
        passed = bool(abs(difference) <= tolerance)
        metric_rows[name] = {
            "expected": expected,
            "observed": observed,
            "difference": difference,
            "tolerance": tolerance,
            "passed": passed,
        }
        if not passed:
            raise ExactReproductionError(
                f"IS metric {name} differs by {difference}, tolerance {tolerance}"
            )
    expected_trades = int(float(source_result["trades"]))
    observed_trades = int(float(actual.metrics["trades"]))
    if observed_trades != expected_trades:
        raise ExactReproductionError(
            f"closed operation count differs: {observed_trades} != {expected_trades}"
        )
    expected_ledger = _ordered_ledger(source_trade_ledger)
    observed_ledger = _ordered_ledger(actual.trade_ledger)
    if len(observed_ledger) != len(expected_ledger):
        raise ExactReproductionError(
            f"trade ledger row count differs: {len(observed_ledger)} != {len(expected_ledger)}"
        )
    text_columns = (
        "symbol",
        "signal_date",
        "entry_date",
        "exit_date",
        "exit_reason",
        "status",
    )
    for column in text_columns:
        if not observed_ledger[column].astype(str).equals(
            expected_ledger[column].astype(str)
        ):
            raise ExactReproductionError(f"trade ledger {column} differs")
    integer_columns = ("fold_id", "trade_id")
    for column in integer_columns:
        if not np.array_equal(
            pd.to_numeric(observed_ledger[column], errors="raise").to_numpy(),
            pd.to_numeric(expected_ledger[column], errors="raise").to_numpy(),
        ):
            raise ExactReproductionError(f"trade ledger {column} differs")
    numeric_columns = ("entry_price", "exit_price", "net_return")
    for column in numeric_columns:
        if not np.allclose(
            pd.to_numeric(observed_ledger[column], errors="coerce").to_numpy(),
            pd.to_numeric(expected_ledger[column], errors="coerce").to_numpy(),
            rtol=0.0,
            atol=1e-12,
            equal_nan=True,
        ):
            raise ExactReproductionError(f"trade ledger {column} differs")
    return {
        "exact_reproduction": True,
        "candidate_id": actual.candidate_id,
        "ledger_rows": int(len(observed_ledger)),
        "closed_operations": observed_trades,
        "metric_comparison": metric_rows,
        "locked_opened": False,
    }


def load_frozen_manifest_authorization(
    path: Path,
    *,
    expected_manifest_sha256: str,
    expected_implementation_commit: str,
) -> LockedDataAuthorization:
    """Verify every frozen identity field before issuing the one-use capability."""

    raw = Path(path).read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256.lower() != str(expected_manifest_sha256).lower():
        raise ValueError("frozen manifest hash mismatch")
    payload = json.loads(raw)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported frozen manifest schema")
    if payload.get("purpose") != "single_irreversible_exact_oos_validation":
        raise ValueError("frozen manifest purpose mismatch")
    if payload.get("candidate_id") != EXACT_CANDIDATE_ID:
        raise ValueError("frozen manifest candidate mismatch")
    if payload.get("implementation_commit") != expected_implementation_commit:
        raise ValueError("frozen manifest implementation commit mismatch")
    source = payload.get("source", {})
    if source.get("run_id") != EXACT_SOURCE_RUN_ID:
        raise ValueError("frozen manifest source run mismatch")
    if source.get("artifact_digest") != EXACT_SOURCE_ARTIFACT_DIGEST:
        raise ValueError("frozen manifest source artifact mismatch")
    spec = payload.get("strategy_spec")
    if spec != exact_strategy_spec() or canonical_candidate_id(spec) != EXACT_CANDIDATE_ID:
        raise ValueError("frozen manifest candidate strategy mismatch")
    periods = payload.get("periods", {})
    expected_periods = {
        "development_start": "1995-01-01",
        "development_end": "2015-12-31",
        "diagnostic_start": "2016-01-01",
        "diagnostic_end": "2020-12-31",
        "locked_start": "2021-01-01",
    }
    for key, value in expected_periods.items():
        if periods.get(key) != value:
            raise ValueError(f"frozen manifest period mismatch: {key}")
    governance = payload.get("governance", {})
    if governance.get("strategy_count") != 1:
        raise ValueError("frozen manifest must contain exactly one strategy")
    if governance.get("optimization_allowed") is not False:
        raise ValueError("frozen manifest cannot allow optimization")
    if governance.get("parameter_search_allowed") is not False:
        raise ValueError("frozen manifest cannot allow parameter search")
    for key in (
        "locked_opened",
        "validation_used_for_selection",
        "locked_used_for_selection",
        "financial_logic_changes_after_freeze",
    ):
        if governance.get(key) is not False:
            raise ValueError(f"frozen manifest governance violation: {key}")
    data = payload.get("data", {})
    if data.get("dataset_hash") != EXACT_DATASET_HASH:
        raise ValueError("frozen manifest dataset hash mismatch")
    if data.get("policy_hash") != EXACT_POLICY_HASH:
        raise ValueError("frozen manifest policy hash mismatch")
    if data.get("survivorship_limited") is not True:
        raise ValueError("frozen manifest must preserve survivorship limitation")
    costs = payload.get("costs", {})
    if costs.get("primary_bps_per_side") != 0:
        raise ValueError("frozen manifest primary costs mismatch")
    if costs.get("sensitivity_bps_per_side") != [5, 10, 25, 50]:
        raise ValueError("frozen manifest cost sensitivity mismatch")
    return issue_locked_data_authorization(
        candidate_id=EXACT_CANDIDATE_ID,
        manifest_sha256=actual_sha256,
        implementation_commit=expected_implementation_commit,
        locked_end=str(periods["locked_end"]),
    )
