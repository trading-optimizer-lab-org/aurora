"""Layered, deterministic campaign primitives for the 36-test stock protocol."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

import pandas as pd

from .dataset import ResearchPanel
from .entries import apply_entry_rule
from .execution import execute_next_open
from .learning import learn_nonnegative_weights
from .manifest import ProtocolManifest
from .metrics import compute_portfolio_metrics, yearly_returns
from .portfolio import build_portfolio, simulate_daily_portfolio
from .signals import compute_features, compute_signal, select_cross_section
from .variants import map_entry_rule, map_exit_rule


DEVELOPMENT_END = pd.Timestamp("2015-12-31")
HOLDOUT_START = pd.Timestamp("2016-01-01")
HOLDOUT_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")


@dataclass(frozen=True)
class EvaluationResult:
    candidate_id: str
    spec: dict[str, Any]
    status: str
    metrics: dict[str, float]
    equity_curve: pd.DataFrame
    trade_ledger: pd.DataFrame
    position_ledger: pd.DataFrame
    yearly: pd.DataFrame
    locked_opened: bool
    data_end: str

    def result_row(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "spec_json": json.dumps(self.spec, sort_keys=True, separators=(",", ":")),
            "status": self.status,
            **self.metrics,
            "locked_opened": self.locked_opened,
            "data_end": self.data_end,
        }


def canonical_candidate_id(spec: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(spec), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")
    return "stock_" + hashlib.sha256(raw).hexdigest()[:20]


def initial_signal_specs(manifest: ProtocolManifest) -> list[dict[str, Any]]:
    """Create a broad but explicit cross-sectional selection funnel."""

    selection_rules = [
        *({"kind": "top_percent", "value": value} for value in (5.0, 10.0, 20.0, 30.0)),
        {"kind": "quintile", "value": 1},
        {"kind": "decile", "value": 1},
        {"kind": "top_n", "value": 20},
    ]
    tests = {test.test_id: test for test in manifest.tests}
    specs: list[dict[str, Any]] = []
    for test_id in (1, 2, 3, 8, 9):
        test = tests[test_id]
        for variant_index, variant in enumerate(test.variants):
            for selection in selection_rules:
                specs.append(
                    {
                        "signal_test_id": test_id,
                        "signal_variant_index": variant_index,
                        "signal_variant": dict(variant),
                        "selection": dict(selection),
                        "entry": {"kind": "immediate_next_open", "max_wait_sessions": 0},
                        "exit": {"kind": "none", "holding_sessions": 63},
                        "portfolio": {"sizing": "equal"},
                        "cost_bps": 0,
                        "horizon_sessions": 63,
                    }
                )
    return specs


def _tests(manifest: ProtocolManifest, ids: Sequence[int]):
    indexed = {test.test_id: test for test in manifest.tests}
    return [indexed[test_id] for test_id in ids]


def expand_layer_specs(
    upstream_specs: Sequence[Mapping[str, Any]],
    layer: str,
    manifest: ProtocolManifest,
) -> list[dict[str, Any]]:
    """Expand exactly one axis while binding every child to its frozen parent."""

    if layer == "weight":
        tests = _tests(manifest, (13,))
    elif layer == "entry":
        tests = _tests(manifest, (15, 16, 17, 18, 19, 20))
    elif layer == "exit":
        tests = _tests(manifest, (21, 22, 23, 24, 25, 26))
    elif layer == "portfolio":
        tests = _tests(manifest, (27, 28, 29))
    elif layer == "cost":
        tests = _tests(manifest, (32,))
    else:
        raise ValueError(f"unknown layer: {layer}")
    children: list[dict[str, Any]] = []
    if layer == "weight":
        component_signals = [dict(spec) for spec in upstream_specs]
        upstream_ids = [canonical_candidate_id(spec) for spec in component_signals]
        if not component_signals:
            raise ValueError("weight layer requires frozen signal components")
        for test in tests:
            for variant_index, variant in enumerate(test.variants):
                child = dict(component_signals[0])
                child["component_signals"] = component_signals
                child["upstream_candidate_ids"] = upstream_ids
                child["weight_test_id"] = test.test_id
                child["weight_variant_index"] = variant_index
                child["signal_weights"] = dict(variant)
                child["selection"] = {"kind": "top_percent", "value": 20.0}
                children.append(child)
        return children
    for upstream in upstream_specs:
        upstream_id = canonical_candidate_id(upstream)
        for test in tests:
            for variant_index, variant in enumerate(test.variants):
                child = dict(upstream)
                child["upstream_candidate_id"] = upstream_id
                child[f"{layer}_test_id"] = test.test_id
                child[f"{layer}_variant_index"] = variant_index
                if layer == "entry":
                    child["entry"] = map_entry_rule(test.test_id, variant)
                elif layer == "exit":
                    child["exit"] = map_exit_rule(test.test_id, variant)
                    child["horizon_sessions"] = int(child["exit"]["holding_sessions"])
                elif layer == "portfolio":
                    portfolio = dict(child.get("portfolio", {"sizing": "equal"}))
                    portfolio.update(dict(variant))
                    child["portfolio"] = portfolio
                elif layer == "cost":
                    child["cost_bps"] = int(variant["cost_bps"])
                children.append(child)
    return children


def _forward_component_returns(
    panel: ResearchPanel,
    candidates: pd.DataFrame,
    component_id: str,
    horizon_sessions: int = 21,
) -> pd.DataFrame:
    prices = panel.frame[["date", "symbol", "adj_close"]].copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    prices = prices.sort_values(["symbol", "date"])
    prices["future_close"] = prices.groupby("symbol", sort=False)["adj_close"].shift(
        -horizon_sessions
    )
    prices["available_date"] = prices.groupby("symbol", sort=False)["date"].shift(
        -horizon_sessions
    )
    prices["forward_return"] = prices["future_close"].div(prices["adj_close"]).sub(1.0)
    joined = candidates[["signal_date", "symbol"]].merge(
        prices[["date", "symbol", "available_date", "forward_return"]],
        left_on=["signal_date", "symbol"],
        right_on=["date", "symbol"],
        how="left",
    )
    joined = joined.dropna(subset=["available_date", "forward_return"])
    if joined.empty:
        return pd.DataFrame(
            columns=["signal_date", "available_date", "component_id", "component_return"]
        )
    grouped = joined.groupby("signal_date", as_index=False).agg(
        available_date=("available_date", "max"),
        component_return=("forward_return", "mean"),
    )
    grouped["component_id"] = component_id
    return grouped


def _causal_component_weights(
    component_returns: pd.DataFrame,
    component_ids: Sequence[str],
    target_date: pd.Timestamp,
) -> dict[str, float]:
    equal = {component: 1.0 / len(component_ids) for component in component_ids}
    available = component_returns.loc[
        pd.to_datetime(component_returns["available_date"]).lt(target_date)
    ]
    if available.empty:
        return equal
    pivot = available.pivot_table(
        index="signal_date",
        columns="component_id",
        values="component_return",
        aggfunc="mean",
    ).reindex(columns=component_ids).dropna()
    if len(pivot) < 12:
        return equal
    train = pivot.reset_index().rename(columns={"signal_date": "date"})
    return learn_nonnegative_weights(train, train_end=target_date - pd.Timedelta(days=1))


def _ensemble_candidates(
    panel: ResearchPanel,
    spec: Mapping[str, Any],
) -> pd.DataFrame:
    components = [dict(item) for item in spec.get("component_signals", [])]
    if not components:
        raise ValueError("ensemble spec contains no component signals")
    frames: list[pd.DataFrame] = []
    returns: list[pd.DataFrame] = []
    component_ids: list[str] = []
    for component in components:
        component_id = canonical_candidate_id(component)
        component_ids.append(component_id)
        variant = dict(component["signal_variant"])
        variant["selection"] = dict(component["selection"])
        variant.setdefault("rebalance", "monthly")
        candidates = compute_signal(panel, int(component["signal_test_id"]), variant)
        candidates["component_id"] = component_id
        frames.append(candidates)
        returns.append(_forward_component_returns(panel, candidates, component_id))
    union = pd.concat(frames, ignore_index=True)
    component_returns = pd.concat(returns, ignore_index=True)
    mode = str(dict(spec.get("signal_weights", {})).get("weights", "equal"))
    weighted_rows: list[pd.DataFrame] = []
    for signal_date, group in union.groupby("signal_date", sort=True):
        if mode == "equal":
            weights = {component: 1.0 / len(component_ids) for component in component_ids}
        elif mode == "ridge_nonnegative":
            weights = _causal_component_weights(
                component_returns, component_ids, pd.Timestamp(signal_date)
            )
        else:
            raise NotImplementedError(f"signal weighting mode {mode} is not implemented")
        part = group.copy()
        part["component_weight"] = part["component_id"].map(weights).astype(float)
        part["weighted_vote"] = part["component_weight"].mul(
            pd.to_numeric(part["cross_section_percentile"], errors="raise")
        )
        weighted_rows.append(part)
    weighted = pd.concat(weighted_rows, ignore_index=True)
    metadata_columns = [
        column
        for column in ("available_at", "adj_close", "adj_high", "adj_low", "atr20", "vol_12_1")
        if column in weighted
    ]
    aggregations: dict[str, object] = {"weighted_vote": "sum"}
    aggregations.update({column: "first" for column in metadata_columns})
    combined = weighted.groupby(["signal_date", "symbol"], as_index=False).agg(aggregations)
    combined = combined.rename(columns={"weighted_vote": "score"})
    combined["available_at"] = combined["signal_date"]
    selected = select_cross_section(combined, dict(spec["selection"]))
    selected["signal"] = True
    selected["signal_weight_mode"] = mode
    return selected


def _candidates_for_spec(panel: ResearchPanel, spec: Mapping[str, Any]) -> pd.DataFrame:
    if spec.get("component_signals"):
        return _ensemble_candidates(panel, spec)
    signal_variant = dict(spec.get("signal_variant", {}))
    signal_variant["selection"] = dict(spec["selection"])
    signal_variant.setdefault("rebalance", "monthly")
    return compute_signal(panel, int(spec["signal_test_id"]), signal_variant)


def _bounded_panel(
    panel: ResearchPanel,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> ResearchPanel:
    if end >= LOCKED_START:
        raise ValueError("campaign evaluation crosses locked boundary")
    if start > end:
        raise ValueError("campaign start must not exceed end")
    frame = panel.frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    if frame["date"].max() >= LOCKED_START:
        raise ValueError("campaign panel contains locked data")
    bounded = frame.loc[frame["date"].le(end)].copy()
    if bounded.empty:
        raise ValueError("campaign panel has no bounded observations")
    return ResearchPanel(bounded, panel.audit)


def evaluate_spec(
    panel: ResearchPanel,
    spec: Mapping[str, Any],
    *,
    start: str,
    end: str,
    initial_capital: float = 100_000.0,
) -> EvaluationResult:
    """Evaluate one fully specified configuration into daily accounting ledgers."""

    start_date = pd.Timestamp(start).normalize()
    end_date = pd.Timestamp(end).normalize()
    bounded = _bounded_panel(panel, start_date, end_date)
    materialized = json.loads(json.dumps(dict(spec), sort_keys=True, default=str))
    candidates = _candidates_for_spec(bounded, materialized)
    candidates = candidates.loc[
        pd.to_datetime(candidates["signal_date"]).between(start_date, end_date)
    ].copy()
    features = compute_features(bounded)
    entry_rule = dict(
        materialized.get(
            "entry", {"kind": "immediate_next_open", "max_wait_sessions": 0}
        )
    )
    events = apply_entry_rule(candidates, features, entry_rule)
    exit_rule = dict(materialized.get("exit", {"kind": "none", "holding_sessions": 63}))
    ranking_keep = None
    if exit_rule.get("kind") == "ranking_hysteresis":
        keep_spec = dict(materialized)
        keep_spec["selection"] = {
            "kind": "top_percent",
            "value": float(exit_rule["keep_percentile"]),
        }
        ranking_keep = _candidates_for_spec(bounded, keep_spec)
    trades = execute_next_open(events, bounded, exit_rule, ranking_keep=ranking_keep)
    candidate_id = canonical_candidate_id(materialized)
    if trades.empty:
        return EvaluationResult(
            candidate_id=candidate_id,
            spec=materialized,
            status="no_observations",
            metrics={},
            equity_curve=pd.DataFrame(),
            trade_ledger=trades,
            position_ledger=pd.DataFrame(),
            yearly=pd.DataFrame(),
            locked_opened=False,
            data_end=end_date.date().isoformat(),
        )
    weighted = build_portfolio(
        trades,
        dict(materialized.get("portfolio", {"sizing": "equal"})),
        panel=bounded,
    )
    curve, positions, ledger = simulate_daily_portfolio(
        weighted,
        bounded,
        initial_capital=initial_capital,
        cost_bps_per_side=float(materialized.get("cost_bps", 0.0)),
    )
    metrics = compute_portfolio_metrics(curve, ledger)
    annual = yearly_returns(curve)
    annual.insert(0, "candidate_id", candidate_id)
    return EvaluationResult(
        candidate_id=candidate_id,
        spec=materialized,
        status="evaluated",
        metrics=metrics,
        equity_curve=curve,
        trade_ledger=ledger,
        position_ledger=positions,
        yearly=annual,
        locked_opened=False,
        data_end=end_date.date().isoformat(),
    )
