"""Expensive train-only robustness checks reserved for global finalists."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_long_short_daily.statistics import (
    _stationary_bootstrap_indices,
)
from aurora.infra.sp500_megarun.dehb_technical_evidence import (
    validate_technical_evidence,
)
from aurora.infra.sp500_megarun.feature_contract import (
    dataset_available_at_policies,
)


class FinalistRobustnessError(ValueError):
    """Raised when a finalist cannot be reconciled to exact train evidence."""


def _annualized(values: np.ndarray) -> float:
    if not len(values) or np.any(values <= -1.0):
        raise FinalistRobustnessError("INVALID_RETURN_VECTOR")
    return math.expm1(float(np.log1p(values).sum()) * 252.0 / len(values))


def _annual_gate(
    strategy: np.ndarray,
    spy: np.ndarray,
    years: np.ndarray,
) -> bool:
    for year in np.unique(years):
        mask = years == year
        strategy_return = math.expm1(float(np.log1p(strategy[mask]).sum()))
        spy_return = math.expm1(float(np.log1p(spy[mask]).sum()))
        if not (strategy_return > 0.0 and strategy_return > spy_return):
            return False
    return True


def blocked_signal_placebo_test(
    strategy_returns: pd.Series,
    spy_returns: pd.Series,
    *,
    seed: int,
    paths: int = 2048,
    block_lengths: Sequence[int] = (5, 10, 20, 40, 63),
    alpha: float = 0.05,
) -> Mapping[str, Any]:
    """Block-resample positions and count placebo rules as good as the finalist."""

    if paths <= 0 or not block_lengths or any(length <= 0 for length in block_lengths):
        raise FinalistRobustnessError("PLACEBO_PARAMETERS_INVALID")
    if not 0.0 < alpha < 1.0:
        raise FinalistRobustnessError("PLACEBO_ALPHA_INVALID")
    frame = pd.concat(
        [strategy_returns.rename("strategy"), spy_returns.rename("spy")], axis=1
    ).dropna()
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        raise FinalistRobustnessError("PLACEBO_RETURN_FRAME_INVALID")
    strategy = frame["strategy"].to_numpy(dtype=float)
    spy = frame["spy"].to_numpy(dtype=float)
    if (
        not np.isfinite(strategy).all()
        or not np.isfinite(spy).all()
        or np.any(strategy <= -1.0)
        or np.any(spy <= -1.0)
    ):
        raise FinalistRobustnessError("PLACEBO_RETURN_FRAME_INVALID")
    nonzero = np.abs(spy) > 1e-15
    ratio = np.full(len(frame), np.nan, dtype=float)
    ratio[nonzero] = strategy[nonzero] / spy[nonzero]
    if (
        not np.allclose(np.abs(ratio[nonzero]), 1.0, rtol=1e-10, atol=1e-10)
        or not np.allclose(strategy[~nonzero], 0.0, rtol=0.0, atol=1e-15)
    ):
        raise FinalistRobustnessError("CANDIDATE_RETURN_NOT_SPY_LONG_SHORT")
    positions = pd.Series(np.sign(ratio), index=frame.index).ffill().bfill().fillna(1.0)
    position_values = positions.to_numpy(dtype=float)
    if not np.isin(position_values, (-1.0, 1.0)).all():
        raise FinalistRobustnessError("CANDIDATE_POSITION_INVALID")
    years = frame.index.year.to_numpy(dtype=int)
    base_annualized = _annualized(strategy)
    if not _annual_gate(strategy, spy, years):
        raise FinalistRobustnessError("FINALIST_ANNUAL_GATE_NOT_MET")

    rng = np.random.default_rng(seed)
    as_good = 0
    gate_survivors = 0
    by_block = {int(length): [0, 0] for length in block_lengths}
    for path_index in range(paths):
        block_length = int(block_lengths[path_index % len(block_lengths)])
        indices = _stationary_bootstrap_indices(rng, len(frame), block_length)
        placebo = position_values[indices] * spy
        survives = _annual_gate(placebo, spy, years)
        gate_survivors += int(survives)
        competitive = survives and _annualized(placebo) >= base_annualized
        as_good += int(competitive)
        by_block[block_length][0] += int(competitive)
        by_block[block_length][1] += 1
    pvalue = float((1 + as_good) / (paths + 1))
    return {
        "schema_version": 1,
        "paths": int(paths),
        "block_lengths": [int(value) for value in block_lengths],
        "alpha": float(alpha),
        "pvalue": pvalue,
        "placebos_as_good_as_finalist": int(as_good),
        "annual_gate_placebo_survival_rate": float(gate_survivors / paths),
        "as_good_rate_by_block_length": {
            str(length): passed / total
            for length, (passed, total) in by_block.items()
        },
        "selection_metric": "annual_gate_then_annualized_strategy_return",
        "uses_sharpe": False,
        "passed": pvalue <= alpha,
        "validation_opened": False,
        "locked_opened": False,
    }


def _regime_active_summary(
    strategy: pd.Series,
    spy: pd.Series,
) -> Mapping[str, Any]:
    strategy_return = math.expm1(float(np.log1p(strategy).sum()))
    spy_return = math.expm1(float(np.log1p(spy).sum()))
    return {
        "session_count": int(len(strategy)),
        "strategy_return": strategy_return,
        "spy_return": spy_return,
        "active_return": strategy_return - spy_return,
    }


def conditional_regime_review(
    strategy_returns: pd.Series,
    spy_returns: pd.Series,
    regimes: Mapping[str, pd.Series],
) -> Mapping[str, Any]:
    """Measure finalist behavior in low, middle, and high public-data regimes."""

    common = pd.concat(
        [strategy_returns.rename("strategy"), spy_returns.rename("spy")], axis=1
    ).dropna()
    rows: dict[str, Any] = {}
    for name, raw in regimes.items():
        values = pd.to_numeric(raw, errors="coerce").reindex(common.index).ffill()
        aligned = pd.concat([common, values.rename("regime")], axis=1).dropna()
        if len(aligned) < 30 or aligned["regime"].nunique() < 3:
            rows[str(name)] = {
                "status": "INSUFFICIENT_VARIATION",
                "session_count": int(len(aligned)),
            }
            continue
        lower = float(aligned["regime"].quantile(1.0 / 3.0))
        upper = float(aligned["regime"].quantile(2.0 / 3.0))
        masks = {
            "low": aligned["regime"].le(lower),
            "middle": aligned["regime"].gt(lower)
            & aligned["regime"].le(upper),
            "high": aligned["regime"].gt(upper),
        }
        rows[str(name)] = {
            "status": "MEASURED",
            "lower_threshold": lower,
            "upper_threshold": upper,
            "slices": {
                label: _regime_active_summary(
                    aligned.loc[mask, "strategy"], aligned.loc[mask, "spy"]
                )
                for label, mask in masks.items()
            },
        }
    return {
        "schema_version": 1,
        "regimes": rows,
        "uses_sharpe": False,
        "validation_opened": False,
        "locked_opened": False,
    }


def load_runtime_regime_review(
    runtime_input_pack: Path,
    strategy_returns: pd.Series,
    spy_returns: pd.Series,
) -> Mapping[str, Any]:
    """Build VIX, credit, and yield-curve regimes from the verified train pack."""

    from aurora.infra.sp500_megarun.feature_input_normalizers import (
        normalize_cboe_vol_panel,
        normalize_credit_spread_panel,
        normalize_treasury_curve_panel,
    )

    train = Path(runtime_input_pack).resolve() / "train_snapshot_1993_2010"
    sessions = pd.DatetimeIndex(spy_returns.index).normalize().unique().sort_values()
    vix = normalize_cboe_vol_panel(
        pd.read_parquet(train / "D_VIX.parquet"),
        pd.read_parquet(train / "D_VXO.parquet"),
        sessions=sessions,
    ).set_index("date")
    rates_raw = pd.read_parquet(train / "D_RATES.parquet")
    credit = normalize_credit_spread_panel(
        rates_raw,
        sessions=sessions,
    ).set_index("date")
    curve = normalize_treasury_curve_panel(
        rates_raw,
        sessions=sessions,
    ).set_index("date")
    return conditional_regime_review(
        strategy_returns,
        spy_returns,
        {
            "vix_close": vix["vix_close"],
            "baa_aaa_spread": credit["baa_aaa_spread"],
            "ten_year_minus_three_month": (
                curve["yield_10y"] - curve["yield_3m"]
            ),
        },
    )


def _corporate_action_gate(train_manifest: Mapping[str, Any]) -> bool:
    execution = train_manifest.get("spy_total_return_execution")
    if not isinstance(execution, Mapping):
        return False
    audit = execution.get("official_distribution_audit")
    return bool(
        execution.get("method") == "adjusted_open_from_adj_close_divided_by_close"
        and isinstance(audit, Mapping)
        and int(audit.get("operational_event_count", 0)) > 0
        and int(audit.get("uncovered_event_count", -1)) == 0
        and audit.get("validation_opened") is False
        and audit.get("locked_opened") is False
    )


def apply_finalist_train_gate_evidence(
    gate_matrix: Sequence[Mapping[str, Any]],
    *,
    campaign_sha256: str,
    lane_id: str,
    required_datasets: Sequence[str],
    seed_consensus: int,
    prefix_review: Mapping[str, Any],
    placebo_review: Mapping[str, Any],
    regime_review: Mapping[str, Any],
    train_manifest: Mapping[str, Any],
    technical_evidence: Mapping[str, Any],
    reconstruction_verified: bool,
) -> list[Mapping[str, Any]]:
    """Close every non-global train gate with explicit evidence and rationale."""

    validate_technical_evidence(
        technical_evidence,
        campaign_sha256=campaign_sha256,
    )
    by_gate = {
        int(row["gate_id"]): dict(row)
        for row in gate_matrix
        if "gate_id" in row
    }
    if set(by_gate) != set(range(1, 61)):
        raise FinalistRobustnessError("FINALIST_GATE_MATRIX_INCOMPLETE")

    def close(
        gate_id: int,
        status: str,
        *,
        evidence: str,
        details: object | None = None,
        rationale: str | None = None,
    ) -> None:
        row = by_gate[gate_id]
        row["status"] = status
        row["evidence_key"] = evidence
        if details is not None:
            row["evidence"] = details
        if rationale is not None:
            row["rationale"] = rationale
        by_gate[gate_id] = row

    close(
        15,
        "PASS" if seed_consensus >= 2 else "FAIL",
        evidence="seed_consensus",
        details={"observed": seed_consensus, "required": 2},
    )
    close(
        16,
        "NOT_APPLICABLE",
        evidence="frozen_runtime_pack",
        rationale=(
            "No second free SPY total-return provider is frozen; independent "
            "corporate-action reconstruction is enforced by gate 23."
        ),
    )
    policies = dataset_available_at_policies()
    dataset_policies = {
        dataset_id: policies.get(dataset_id, "unknown")
        for dataset_id in required_datasets
    }
    close(
        21,
        "MEASURED",
        evidence="dataset_available_at_policies",
        details=dataset_policies,
        rationale=(
            "Current-vintage proxies remain labelled as proxies and use their "
            "frozen conservative publication guard."
        ),
    )
    close(
        22,
        "NOT_APPLICABLE",
        evidence="execution_universe",
        details={"lane_id": lane_id, "traded_asset": "SPY"},
        rationale=(
            "The candidate trades SPY itself and never rebuilds historical SP500 "
            "returns from today's constituents."
        ),
    )
    corporate_action_passed = _corporate_action_gate(train_manifest)
    close(
        23,
        "PASS" if corporate_action_passed else "FAIL",
        evidence="train_manifest.spy_total_return_execution",
        details=train_manifest.get("spy_total_return_execution"),
    )
    close(
        24,
        "PASS" if prefix_review.get("passed") is True else "FAIL",
        evidence="candidate_prefix_invariance",
        details=prefix_review,
    )
    close(
        26,
        "NOT_APPLICABLE",
        evidence="frozen_execution_contract",
        rationale=(
            "The free physical ledger supports audited adjusted open-to-open total "
            "return; unverified intraday alternatives cannot select a finalist."
        ),
    )
    close(
        28,
        "PASS",
        evidence="technical_evidence.gates.60",
        details=technical_evidence["gates"]["60"],
    )
    close(
        31,
        "MEASURED",
        evidence="runtime_regime_review",
        details=regime_review,
    )
    close(
        40,
        "PASS" if placebo_review.get("passed") is True else "FAIL",
        evidence="blocked_signal_placebos",
        details=placebo_review,
    )
    for gate_id in (55, 56, 60):
        source = technical_evidence["gates"][str(gate_id)]
        close(
            gate_id,
            str(source["status"]),
            evidence=f"technical_evidence.gates.{gate_id}",
            details=source,
        )
    close(
        57,
        "PASS" if reconstruction_verified else "FAIL",
        evidence="global_clean_runner_reconstruction",
    )
    close(
        58,
        "PASS" if reconstruction_verified else "FAIL",
        evidence="strategy_and_position_fingerprint_reconstruction",
    )
    cache_passed = prefix_review.get("cache_reproduction_passed") is True
    close(
        59,
        "PASS" if cache_passed else "FAIL",
        evidence="candidate_prefix_invariance.cache_reproduction",
        details={
            "hot": prefix_review.get("hot_cache_reproduction"),
            "cold": prefix_review.get("cold_cache_reproduction"),
        },
    )
    return [by_gate[gate_id] for gate_id in range(1, 61)]


__all__ = [
    "FinalistRobustnessError",
    "apply_finalist_train_gate_evidence",
    "blocked_signal_placebo_test",
    "conditional_regime_review",
    "load_runtime_regime_review",
]
