"""Purged development-fold evaluation for immutable stock-protocol specs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from .campaign import DEVELOPMENT_END, EvaluationResult, evaluate_spec
from .dataset import ResearchPanel
from .metrics import compute_portfolio_metrics, yearly_returns
from .portfolio import simulate_daily_portfolio
from .validation import PurgedFold, generate_purged_walk_forward


LOCKED_START = pd.Timestamp("2021-01-01")


@dataclass(frozen=True)
class CrossValidatedEvaluation:
    result: EvaluationResult
    fold_results: pd.DataFrame
    folds: tuple[PurgedFold, ...]


def stitch_fold_curves(
    curves: Sequence[pd.DataFrame],
    *,
    initial_capital: float = 100_000.0,
) -> pd.DataFrame:
    """Chain disjoint fold curves while preserving each fold's first-day PnL."""

    if not curves:
        raise ValueError("cannot stitch an empty collection of fold curves")
    if not np.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial_capital must be positive and finite")
    parts: list[pd.DataFrame] = []
    current_equity = float(initial_capital)
    previous_end: pd.Timestamp | None = None
    for source in curves:
        if source.empty or not {"date", "equity"} <= set(source.columns):
            raise ValueError("each fold curve requires date and equity")
        part = source.copy().sort_values("date").reset_index(drop=True)
        part["date"] = pd.to_datetime(part["date"], errors="raise").dt.normalize()
        if not part["date"].is_unique:
            raise ValueError("fold curve has duplicate dates")
        if part["date"].max() >= LOCKED_START:
            raise ValueError("fold curve crosses locked boundary")
        if previous_end is not None and part["date"].min() <= previous_end:
            raise ValueError("fold curves overlap or are out of order")
        equity = pd.to_numeric(part["equity"], errors="raise").astype(float)
        if not np.isfinite(equity).all() or equity.le(0).any():
            raise ValueError("fold equity must be finite and positive")
        returns = equity.pct_change(fill_method=None)
        returns.iloc[0] = equity.iloc[0] / float(initial_capital) - 1.0
        chained = current_equity * (1.0 + returns).cumprod()
        scale = chained.div(equity)
        for column in ("cash", "market_value", "costs"):
            if column in part:
                part[column] = pd.to_numeric(part[column], errors="raise").mul(scale)
        part["equity"] = chained
        current_equity = float(chained.iloc[-1])
        previous_end = pd.Timestamp(part["date"].max())
        parts.append(part)
    result = pd.concat(parts, ignore_index=True)
    if not result["date"].is_monotonic_increasing or not result["date"].is_unique:
        raise ValueError("stitched fold dates are invalid")
    return result


def _fold_trade_subset(ledger: pd.DataFrame, fold: PurgedFold) -> pd.DataFrame:
    if ledger.empty:
        return ledger.copy()
    frame = ledger.copy()
    entry = pd.to_datetime(frame["entry_date"], errors="raise").dt.normalize()
    exit_date = pd.to_datetime(frame["exit_date"], errors="raise").dt.normalize()
    return frame.loc[
        entry.between(fold.test_start, fold.test_end)
        & exit_date.between(fold.test_start, fold.test_end)
    ].copy()


def evaluate_development_walk_forward(
    panel: ResearchPanel,
    spec: dict[str, object],
    *,
    start: str,
    end: str = "2015-12-31",
    initial_capital: float = 100_000.0,
    mode: str = "expanding",
) -> CrossValidatedEvaluation:
    """Score a fixed spec only on purged pre-holdout test folds."""

    end_date = pd.Timestamp(end).normalize()
    if end_date != DEVELOPMENT_END:
        raise ValueError("development evaluation must end at 2015-12-31")
    raw_dates = pd.to_datetime(panel.frame["date"], errors="raise")
    bounded_dates = pd.to_datetime(
        panel.frame.loc[raw_dates.le(end_date), "date"], errors="raise"
    ).dt.normalize()
    dates = pd.DatetimeIndex(bounded_dates.unique()).sort_values()
    horizon = int(spec.get("horizon_sessions", 63))
    folds = tuple(
        generate_purged_walk_forward(
            dates,
            train_years=10 if mode == "expanding" else 15,
            validation_years=3,
            test_years=1,
            horizon_sessions=horizon,
            mode=mode,
        )
    )
    full = evaluate_spec(
        panel,
        spec,
        start=start,
        end=end_date.date().isoformat(),
        initial_capital=initial_capital,
    )
    if full.status != "evaluated":
        return CrossValidatedEvaluation(full, pd.DataFrame(), folds)
    fold_rows: list[dict[str, object]] = []
    curves: list[pd.DataFrame] = []
    positions: list[pd.DataFrame] = []
    ledgers: list[pd.DataFrame] = []
    cost_bps = float(spec.get("cost_bps", 0.0))
    for fold in folds:
        trades = _fold_trade_subset(full.trade_ledger, fold)
        row = {
            **fold.to_dict(),
            "candidate_id": full.candidate_id,
            "selection_used_holdout": False,
            "locked_opened": False,
        }
        if trades.empty or not pd.to_numeric(trades.get("weight"), errors="coerce").gt(0).any():
            fold_rows.append({**row, "status": "no_observations"})
            continue
        curve, fold_positions, ledger = simulate_daily_portfolio(
            trades,
            panel,
            initial_capital=initial_capital,
            cost_bps_per_side=cost_bps,
        )
        metrics = compute_portfolio_metrics(curve, ledger)
        fold_rows.append({**row, "status": "evaluated", **metrics})
        curve = curve.assign(fold_id=fold.fold_id, walk_forward_mode=mode)
        fold_positions = fold_positions.assign(fold_id=fold.fold_id)
        ledger = ledger.assign(fold_id=fold.fold_id)
        curves.append(curve)
        positions.append(fold_positions)
        ledgers.append(ledger)
    fold_frame = pd.DataFrame(fold_rows)
    if not curves:
        empty = EvaluationResult(
            candidate_id=full.candidate_id,
            spec=full.spec,
            status="no_observations",
            metrics={},
            equity_curve=pd.DataFrame(),
            trade_ledger=pd.DataFrame(),
            position_ledger=pd.DataFrame(),
            yearly=pd.DataFrame(),
            locked_opened=False,
            data_end=end_date.date().isoformat(),
        )
        return CrossValidatedEvaluation(empty, fold_frame, folds)
    stitched = stitch_fold_curves(curves, initial_capital=initial_capital)
    combined_ledger = pd.concat(ledgers, ignore_index=True)
    combined_positions = pd.concat(positions, ignore_index=True)
    metrics = compute_portfolio_metrics(stitched, combined_ledger)
    annual = yearly_returns(stitched)
    annual.insert(0, "candidate_id", full.candidate_id)
    result = EvaluationResult(
        candidate_id=full.candidate_id,
        spec=full.spec,
        status="evaluated",
        metrics=metrics,
        equity_curve=stitched,
        trade_ledger=combined_ledger,
        position_ledger=combined_positions,
        yearly=annual,
        locked_opened=False,
        data_end=end_date.date().isoformat(),
    )
    return CrossValidatedEvaluation(result, fold_frame, folds)
