"""Purged development-fold evaluation for immutable stock-protocol specs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from .campaign import (
    DEVELOPMENT_END,
    EvaluationResult,
    canonical_candidate_id,
    evaluate_spec,
)
from .dataset import ResearchPanel, read_pack_range
from .metrics import compute_portfolio_metrics, yearly_returns
from .portfolio import simulate_daily_portfolio
from .signals import compute_features
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


def evaluate_development_walk_forward_from_pack(
    pack_root: Path,
    spec: dict[str, object],
    *,
    start: str,
    end: str = "2015-12-31",
    initial_capital: float = 100_000.0,
    mode: str = "expanding",
) -> CrossValidatedEvaluation:
    """Evaluate purged folds without materialising the complete price pack."""

    end_date = pd.Timestamp(end).normalize()
    if end_date != DEVELOPMENT_END:
        raise ValueError("development evaluation must end at 2015-12-31")
    calendar_path = pack_root / "trading_calendar.parquet"
    if not calendar_path.is_file():
        raise FileNotFoundError(f"pack trading calendar is missing: {calendar_path}")
    calendar = pd.read_parquet(calendar_path, columns=["date"])
    dates = pd.DatetimeIndex(
        pd.to_datetime(calendar["date"], errors="raise").dt.normalize().unique()
    ).sort_values()
    dates = dates[(dates >= pd.Timestamp(start).normalize()) & (dates <= end_date)]
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
    fold_rows: list[dict[str, object]] = []
    curves: list[pd.DataFrame] = []
    positions: list[pd.DataFrame] = []
    ledgers: list[pd.DataFrame] = []
    candidate_id = ""
    for fold in folds:
        warmup_start = fold.test_start - pd.DateOffset(years=2)
        panel = read_pack_range(
            pack_root,
            start_date=warmup_start.date().isoformat(),
            end_date=fold.test_end.date().isoformat(),
        )
        result = evaluate_spec(
            panel,
            spec,
            start=fold.test_start.date().isoformat(),
            end=fold.test_end.date().isoformat(),
            initial_capital=initial_capital,
        )
        candidate_id = result.candidate_id
        row = {
            **fold.to_dict(),
            "candidate_id": result.candidate_id,
            "selection_used_holdout": False,
            "locked_opened": False,
        }
        if result.status != "evaluated" or result.equity_curve.empty:
            fold_rows.append({**row, "status": result.status})
            continue
        fold_rows.append({**row, "status": "evaluated", **result.metrics})
        curves.append(result.equity_curve.assign(fold_id=fold.fold_id, walk_forward_mode=mode))
        positions.append(result.position_ledger.assign(fold_id=fold.fold_id))
        ledgers.append(result.trade_ledger.assign(fold_id=fold.fold_id))
    fold_frame = pd.DataFrame(fold_rows)
    if not curves:
        empty = EvaluationResult(
            candidate_id=candidate_id,
            spec=dict(spec),
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
    annual.insert(0, "candidate_id", candidate_id)
    result = EvaluationResult(
        candidate_id=candidate_id,
        spec=dict(spec),
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


def evaluate_development_walk_forward_many_from_pack(
    pack_root: Path,
    specs: Sequence[dict[str, object]],
    *,
    start: str,
    end: str = "2015-12-31",
    initial_capital: float = 100_000.0,
    mode: str = "expanding",
) -> tuple[CrossValidatedEvaluation, ...]:
    """Evaluate fixed specs while sharing each bounded fold panel and feature frame."""

    materialized_specs = tuple(dict(spec) for spec in specs)
    if not materialized_specs:
        raise ValueError("at least one spec is required")
    end_date = pd.Timestamp(end).normalize()
    if end_date != DEVELOPMENT_END:
        raise ValueError("development evaluation must end at 2015-12-31")
    calendar_path = pack_root / "trading_calendar.parquet"
    if not calendar_path.is_file():
        raise FileNotFoundError(f"pack trading calendar is missing: {calendar_path}")
    calendar = pd.read_parquet(calendar_path, columns=["date"])
    dates = pd.DatetimeIndex(
        pd.to_datetime(calendar["date"], errors="raise").dt.normalize().unique()
    ).sort_values()
    dates = dates[(dates >= pd.Timestamp(start).normalize()) & (dates <= end_date)]

    states: list[dict[str, object]] = []
    work_by_window: dict[
        tuple[pd.Timestamp, pd.Timestamp], list[tuple[int, PurgedFold]]
    ] = {}
    for index, spec in enumerate(materialized_specs):
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
        states.append(
            {
                "candidate_id": canonical_candidate_id(spec),
                "spec": spec,
                "folds": folds,
                "fold_rows": [],
                "curves": [],
                "positions": [],
                "ledgers": [],
            }
        )
        for fold in folds:
            warmup_start = fold.test_start - pd.DateOffset(years=2)
            work_by_window.setdefault((warmup_start, fold.test_end), []).append(
                (index, fold)
            )

    for (warmup_start, test_end), assignments in sorted(work_by_window.items()):
        panel = read_pack_range(
            pack_root,
            start_date=warmup_start.date().isoformat(),
            end_date=test_end.date().isoformat(),
        )
        feature_frame = compute_features(panel)
        for state_index, fold in assignments:
            state = states[state_index]
            spec = state["spec"]
            if not isinstance(spec, dict):
                raise TypeError("walk-forward state spec must be a dictionary")
            result = evaluate_spec(
                panel,
                spec,
                start=fold.test_start.date().isoformat(),
                end=fold.test_end.date().isoformat(),
                initial_capital=initial_capital,
                features=feature_frame,
            )
            state["candidate_id"] = result.candidate_id
            row = {
                **fold.to_dict(),
                "candidate_id": result.candidate_id,
                "selection_used_holdout": False,
                "locked_opened": False,
            }
            fold_rows = state["fold_rows"]
            if not isinstance(fold_rows, list):
                raise TypeError("walk-forward fold rows must be a list")
            if result.status != "evaluated" or result.equity_curve.empty:
                fold_rows.append({**row, "status": result.status})
                continue
            fold_rows.append({**row, "status": "evaluated", **result.metrics})
            curves = state["curves"]
            positions = state["positions"]
            ledgers = state["ledgers"]
            if not all(isinstance(parts, list) for parts in (curves, positions, ledgers)):
                raise TypeError("walk-forward result accumulators must be lists")
            curves.append(
                result.equity_curve.assign(fold_id=fold.fold_id, walk_forward_mode=mode)
            )
            positions.append(result.position_ledger.assign(fold_id=fold.fold_id))
            ledgers.append(result.trade_ledger.assign(fold_id=fold.fold_id))

    evaluations: list[CrossValidatedEvaluation] = []
    for state in states:
        candidate_id = str(state["candidate_id"])
        spec = dict(state["spec"])
        folds = tuple(state["folds"])
        fold_rows = list(state["fold_rows"])
        curves = list(state["curves"])
        positions = list(state["positions"])
        ledgers = list(state["ledgers"])
        fold_frame = pd.DataFrame(fold_rows)
        if not curves:
            empty = EvaluationResult(
                candidate_id=candidate_id,
                spec=spec,
                status="no_observations",
                metrics={},
                equity_curve=pd.DataFrame(),
                trade_ledger=pd.DataFrame(),
                position_ledger=pd.DataFrame(),
                yearly=pd.DataFrame(),
                locked_opened=False,
                data_end=end_date.date().isoformat(),
            )
            evaluations.append(CrossValidatedEvaluation(empty, fold_frame, folds))
            continue
        stitched = stitch_fold_curves(curves, initial_capital=initial_capital)
        combined_ledger = pd.concat(ledgers, ignore_index=True)
        combined_positions = pd.concat(positions, ignore_index=True)
        metrics = compute_portfolio_metrics(stitched, combined_ledger)
        annual = yearly_returns(stitched)
        annual.insert(0, "candidate_id", candidate_id)
        result = EvaluationResult(
            candidate_id=candidate_id,
            spec=spec,
            status="evaluated",
            metrics=metrics,
            equity_curve=stitched,
            trade_ledger=combined_ledger,
            position_ledger=combined_positions,
            yearly=annual,
            locked_opened=False,
            data_end=end_date.date().isoformat(),
        )
        evaluations.append(CrossValidatedEvaluation(result, fold_frame, folds))
    return tuple(evaluations)
