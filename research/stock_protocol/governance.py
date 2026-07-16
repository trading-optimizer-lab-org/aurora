"""Derived implementation matrix and missing-data contracts for all 36 tests."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .manifest import ProtocolManifest


ALLOWED_IMPLEMENTATION_STATES = {
    "fully_implemented",
    "implemented_with_documented_limitation",
    "unsupported_missing_data",
    "unsupported_not_implemented",
    "no_observations",
    "failed",
}


_LIMITED = {
    13: "Non-negative learned weights are trained only on prior folds; current universe remains survivorship-limited.",
    17: "Consolidation is an objective adjusted-range contraction; no intraday structure is inferred.",
    21: "Ranking hysteresis is available only for price-signal ranks with observed daily closes.",
    28: "Asset and correlation caps are available; historical sector caps require PIT classifications.",
    29: "Regime exposure uses observable SPY price/volatility only; macro point-in-time regimes are excluded.",
}


_CODE_PATHS = {
    range(1, 14): "aurora.research.stock_protocol.signals",
    range(15, 27): "aurora.research.stock_protocol.execution",
    range(27, 30): "aurora.research.stock_protocol.portfolio",
    range(32, 33): "aurora.research.stock_protocol.portfolio",
    range(34, 35): "aurora.research.stock_protocol.validation",
    range(35, 36): "aurora.research.stock_protocol.robustness",
    range(36, 37): "aurora.research.stock_protocol.pareto",
}


def _code_path(test_id: int) -> str:
    for ids, path in _CODE_PATHS.items():
        if test_id in ids:
            return path
    return "aurora.research.stock_protocol.governance"


def implementation_matrix(manifest: ProtocolManifest) -> pd.DataFrame:
    """Build one honest, non-generic implementation record per protocol test."""

    rows: list[dict[str, Any]] = []
    for test in manifest.tests:
        if test.status == "unsupported_missing_data":
            status = "unsupported_missing_data"
            limitation = test.reason
        elif test.test_id in _LIMITED:
            status = "implemented_with_documented_limitation"
            limitation = _LIMITED[test.test_id]
        else:
            status = "fully_implemented"
            limitation = (
                "Implementation is causal for available fields; all results remain "
                "preliminary because the active universe is a current-universe backfill."
            )
        if status not in ALLOWED_IMPLEMENTATION_STATES:
            raise ValueError(f"invalid implementation status for test {test.test_id}")
        rows.append(
            {
                "test_id": test.test_id,
                "name": test.name,
                "implementation_status": status,
                "code_path": _code_path(test.test_id),
                "required_datasets": ",".join(test.requires),
                "variant_count": len(test.variants),
                "limitation": limitation,
                "survivorship_limited": True,
                "locked_opened": False,
            }
        )
    return pd.DataFrame(rows).sort_values("test_id").reset_index(drop=True)


_MISSING_CONTRACTS: dict[int, dict[str, str]] = {
    4: {"dataset": "pit_eps_events", "required_columns": "permanent_id,event_time,fiscal_period,reported_eps,consensus_eps,available_at", "frequency": "event", "available_at_field": "available_at", "provider_examples": "Compustat Point-in-Time, FactSet Estimates, Intrinio Zacks"},
    5: {"dataset": "pit_analyst_estimate_history", "required_columns": "permanent_id,estimate_period,estimate_value,revision_time,available_at", "frequency": "event", "available_at_field": "available_at", "provider_examples": "IBES, FactSet Estimates, LSEG Estimates"},
    6: {"dataset": "pit_sales_guidance", "required_columns": "permanent_id,period,sales_estimate,guidance_low,guidance_high,event_time,available_at", "frequency": "event", "available_at_field": "available_at", "provider_examples": "FactSet Estimates, LSEG Estimates"},
    7: {"dataset": "pit_price_earnings_inputs", "required_columns": "permanent_id,event_time,reported_eps,consensus_eps,revision_value,available_at", "frequency": "event", "available_at_field": "available_at", "provider_examples": "Compustat Point-in-Time plus IBES"},
    10: {"dataset": "pit_accounting_cash_profitability", "required_columns": "permanent_id,fiscal_period,cash_flow_operations,total_assets,filing_time,available_at", "frequency": "quarterly", "available_at_field": "available_at", "provider_examples": "Compustat Point-in-Time, FactSet Fundamentals"},
    11: {"dataset": "pit_accounting_growth_dilution", "required_columns": "permanent_id,fiscal_period,total_assets,shares_outstanding,inventory,receivables,filing_time,available_at", "frequency": "quarterly", "available_at_field": "available_at", "provider_examples": "Compustat Point-in-Time, FactSet Fundamentals"},
    12: {"dataset": "complete_tests_1_to_11_feature_matrix", "required_columns": "permanent_id,signal_date,test_1_score_to_test_11_score,available_at", "frequency": "monthly", "available_at_field": "available_at", "provider_examples": "Derived after contracts 4-11 are populated"},
    14: {"dataset": "pit_global_classification_membership", "required_columns": "permanent_id,country,sector,industry,listed_from,listed_to,available_at", "frequency": "event", "available_at_field": "available_at", "provider_examples": "Compustat Security Daily, CRSP plus GICS history, FactSet RBICS"},
    30: {"dataset": "pit_global_equity_universe", "required_columns": "permanent_id,country,exchange,currency,listed_from,listed_to,delisting_return,available_at", "frequency": "daily", "available_at_field": "available_at", "provider_examples": "Compustat Global, FactSet Prices"},
    31: {"dataset": "pit_size_liquidity_sector_metadata", "required_columns": "permanent_id,market_cap,adv20,spread,sector,regime_date,available_at", "frequency": "daily", "available_at_field": "available_at", "provider_examples": "CRSP plus Compustat, FactSet"},
    33: {"dataset": "pit_universe_and_delistings", "required_columns": "permanent_id,ticker,listed_from,listed_to,delisting_date,delisting_return,available_at", "frequency": "daily_event", "available_at_field": "available_at", "provider_examples": "CRSP Stock Database, Compustat Security Daily"},
}


def unsupported_data_requirements(manifest: ProtocolManifest) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for test in manifest.unsupported_tests():
        contract = _MISSING_CONTRACTS.get(test.test_id)
        if contract is None:
            raise ValueError(f"missing data contract for unsupported test {test.test_id}")
        rows.append(
            {
                "test_id": test.test_id,
                "name": test.name,
                "reason": test.reason,
                **contract,
                "loader_interface": "PointInTimeResearchDataProvider",
                "expected_format": "partitioned_parquet_with_bitemporal_catalog",
                "locked_opened": False,
            }
        )
    return pd.DataFrame(rows).sort_values("test_id").reset_index(drop=True)
