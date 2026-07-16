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
from .manifest import ProtocolManifest
from .metrics import compute_portfolio_metrics, yearly_returns
from .portfolio import build_portfolio, simulate_daily_portfolio
from .signals import compute_features, compute_signal
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
    for upstream in upstream_specs:
        upstream_id = canonical_candidate_id(upstream)
        for test in tests:
            for variant_index, variant in enumerate(test.variants):
                child = dict(upstream)
                child["upstream_candidate_id"] = upstream_id
                child[f"{layer}_test_id"] = test.test_id
                child[f"{layer}_variant_index"] = variant_index
                if layer == "weight":
                    child["signal_weights"] = dict(variant)
                elif layer == "entry":
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
    signal_variant = dict(materialized.get("signal_variant", {}))
    signal_variant["selection"] = dict(materialized["selection"])
    signal_variant.setdefault("rebalance", "monthly")
    candidates = compute_signal(
        bounded,
        int(materialized["signal_test_id"]),
        signal_variant,
    )
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
    trades = execute_next_open(events, bounded, exit_rule)
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
    weighted = build_portfolio(trades, dict(materialized.get("portfolio", {"sizing": "equal"})))
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
