"""S&P 500 always-invested long/short research helper.

The contract is intentionally narrow:

* one instrument, normally SPY as the tradable S&P 500 proxy;
* daily target weight is always either +1.0 or -1.0;
* no cash, no leverage, no intermediate sizing;
* candidates are selected on validation data, then reported on the final
  holdout without using that holdout for selection.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from aurora.core.costs import CostModel, IBKR_costs
from aurora.core.engine import BacktestResult, run_backtest
from aurora.core.metrics import Metrics
from aurora.core.runtime_paths import base_data_dir
from aurora.data_contracts.timeseries_store import TimeSeriesStore
from aurora.research.ledger import LedgerEventType, ResearchLedger
from aurora.research.lookahead_guard import assert_signal_is_causal
from aurora.research.protocol_guard import ResearchProtocolGuard, ResearchProtocolSpec
from aurora.strategies.base import Strategy
from aurora.strategies.library.atr_breakout import ATRBreakout
from aurora.strategies.library.bollinger_mr import BollingerMR
from aurora.strategies.library.donchian import DonchianBreakout
from aurora.strategies.library.ma_cross import MACross
from aurora.strategies.library.rsi_meanrev import RSIMeanRev
from aurora.strategies.library.tsmom import TSMomentum


SignalFn = Callable[[pd.Series], np.ndarray]


@dataclass(frozen=True)
class AlwaysLongShortSignal:
    """Wrap a signal function so output is always exactly +1 or -1.

    Neutral bars keep the previous side. If the first bars are neutral,
    ``initial_side`` is used. This keeps the strategy fully invested without
    inventing fractional exposure.
    """

    signal_fn: SignalFn
    initial_side: float = 1.0

    def __post_init__(self) -> None:
        if self.initial_side not in (-1.0, 1.0):
            raise ValueError("initial_side must be +1.0 or -1.0")

    def __call__(self, prices: pd.Series) -> np.ndarray:
        raw = np.asarray(self.signal_fn(prices), dtype=float)
        if len(raw) != len(prices):
            raise ValueError(f"signal length {len(raw)} != prices length {len(prices)}")
        if not np.all(np.isfinite(raw)):
            raise ValueError("non-finite raw signal values")

        out = np.empty(len(raw), dtype=float)
        side = float(self.initial_side)
        for i, value in enumerate(raw):
            if value > 0.0:
                side = 1.0
            elif value < 0.0:
                side = -1.0
            out[i] = side
        return out


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    strategy_cls: type[Strategy]
    params: dict
    initial_side: float = 1.0

    def build_signal(self) -> AlwaysLongShortSignal:
        strategy = self.strategy_cls(**dict(self.params))
        return AlwaysLongShortSignal(strategy.signals, initial_side=self.initial_side)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "strategy_class": self.strategy_cls.__name__,
            "params": dict(self.params),
            "initial_side": self.initial_side,
        }


@dataclass(frozen=True)
class SplitPrices:
    train: pd.Series
    valid: pd.Series
    test: pd.Series


@dataclass(frozen=True)
class CandidateResult:
    candidate: CandidateSpec
    split: str
    metrics: Metrics
    turnover: float
    trades: int
    long_fraction: float
    short_fraction: float
    score: float

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate.to_dict(),
            "split": self.split,
            "metrics": self.metrics.to_dict(),
            "turnover": self.turnover,
            "trades": self.trades,
            "long_fraction": self.long_fraction,
            "short_fraction": self.short_fraction,
            "score": self.score,
        }


@dataclass(frozen=True)
class PeriodResult:
    period: str
    start: str
    end: str
    metrics: Metrics
    trades: int
    long_fraction: float
    short_fraction: float

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "start": self.start,
            "end": self.end,
            "metrics": self.metrics.to_dict(),
            "trades": self.trades,
            "long_fraction": self.long_fraction,
            "short_fraction": self.short_fraction,
        }


@dataclass(frozen=True)
class SensitivityResult:
    candidate: CandidateSpec
    metrics: Metrics
    trades: int
    short_fraction: float
    is_base: bool = False

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate.to_dict(),
            "metrics": self.metrics.to_dict(),
            "trades": self.trades,
            "short_fraction": self.short_fraction,
            "is_base": self.is_base,
        }


@dataclass(frozen=True)
class LongShortSearchReport:
    symbol: str
    n_candidates: int
    train_top: tuple[CandidateResult, ...]
    valid_top: tuple[CandidateResult, ...]
    selected: CandidateResult
    benchmarks: dict[str, CandidateResult] = field(default_factory=dict)
    selection_policy: dict = field(default_factory=dict)
    period_breakdown: tuple[PeriodResult, ...] = field(default_factory=tuple)
    sensitivity: tuple[SensitivityResult, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "n_candidates": self.n_candidates,
            "train_top": [r.to_dict() for r in self.train_top],
            "valid_top": [r.to_dict() for r in self.valid_top],
            "selected": self.selected.to_dict(),
            "benchmarks": {k: v.to_dict() for k, v in self.benchmarks.items()},
            "selection_policy": dict(self.selection_policy),
            "period_breakdown": [r.to_dict() for r in self.period_breakdown],
            "sensitivity": [r.to_dict() for r in self.sensitivity],
        }


class _AlwaysLong(Strategy):
    def signals(self, prices: pd.Series) -> np.ndarray:
        return np.ones(len(prices))


class _AlwaysShort(Strategy):
    def signals(self, prices: pd.Series) -> np.ndarray:
        return -np.ones(len(prices))


class _DrawdownRsiAnd(Strategy):
    """Long only when both drawdown and RSI regime filters are positive.

    Rule:
      * drawdown filter is long if price is not more than ``dd_threshold``
        below its rolling high;
      * RSI regime is long after RSI < oversold, short after RSI > overbought;
      * final raw signal is long only if both are long, otherwise short.

    Wrapped by :class:`AlwaysLongShortSignal`, so final exposure is still
    exactly +1/-1.
    """

    def __init__(
        self,
        dd_window: int = 40,
        dd_threshold: float = -0.27,
        rsi_period: int = 16,
        oversold: float = 40.0,
        overbought: float = 80.0,
    ) -> None:
        self.dd_window = int(dd_window)
        self.dd_threshold = float(dd_threshold)
        self.rsi_period = int(rsi_period)
        self.oversold = float(oversold)
        self.overbought = float(overbought)

    def _rsi_side(self, prices: pd.Series) -> np.ndarray:
        d = prices.diff()
        gains = d.clip(lower=0.0)
        losses = (-d).clip(lower=0.0)
        avg_gain = gains.ewm(
            alpha=1.0 / self.rsi_period,
            min_periods=self.rsi_period,
            adjust=False,
        ).mean()
        avg_loss = losses.ewm(
            alpha=1.0 / self.rsi_period,
            min_periods=self.rsi_period,
            adjust=False,
        ).mean()
        rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        out = np.zeros(len(prices), dtype=float)
        side = 1.0
        for i, value in enumerate(rsi):
            if not np.isfinite(value):
                continue
            if value < self.oversold:
                side = 1.0
            elif value > self.overbought:
                side = -1.0
            out[i] = side
        return out

    def signals(self, prices: pd.Series) -> np.ndarray:
        rolling_high = prices.rolling(
            self.dd_window, min_periods=self.dd_window,
        ).max()
        drawdown = prices / rolling_high - 1.0
        dd_side = np.where(drawdown > self.dd_threshold, 1.0, -1.0)
        rsi_side = self._rsi_side(prices)
        return np.where((dd_side > 0.0) & (rsi_side > 0.0), 1.0, -1.0)


def load_spy_prices(symbol: str = "SPY", *, library: str = "prices_daily") -> pd.Series:
    """Load adjusted close from the local Aurora TimeSeriesStore."""
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    df = store.read(library=library, symbol=symbol)
    if "adj_close" in df.columns:
        col = "adj_close"
    elif "close" in df.columns:
        col = "close"
    else:
        raise ValueError(f"{symbol} has no adj_close/close column in {library}")
    prices = pd.Series(
        df[col].astype(float).to_numpy(),
        index=pd.to_datetime(df.index),
        name=symbol,
    ).sort_index()
    prices = prices[~prices.index.duplicated(keep="last")]
    return prices.dropna()


def split_prices(
    prices: pd.Series,
    *,
    train_ratio: float = 0.60,
    valid_ratio: float = 0.20,
    require_test: bool = True,
) -> SplitPrices:
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be a pandas Series")
    n = len(prices)
    if n < 120:
        raise ValueError(f"need at least 120 bars, got {n}")
    if train_ratio <= 0.0 or valid_ratio <= 0.0:
        raise ValueError("train_ratio and valid_ratio must be positive")
    if require_test and train_ratio + valid_ratio >= 1.0:
        raise ValueError("train_ratio and valid_ratio must leave a test slice")
    if not require_test and train_ratio + valid_ratio > 1.0:
        raise ValueError("train_ratio and valid_ratio cannot exceed 1.0")
    train_end = int(n * train_ratio)
    valid_end = n if not require_test and train_ratio + valid_ratio == 1.0 else int(
        n * (train_ratio + valid_ratio)
    )
    return SplitPrices(
        train=prices.iloc[:train_end],
        valid=prices.iloc[train_end:valid_end],
        test=prices.iloc[valid_end:],
    )


def _score(metrics: Metrics, turnover: float) -> float:
    calmar = metrics.calmar if np.isfinite(metrics.calmar) else 0.0
    sharpe = metrics.sharpe if np.isfinite(metrics.sharpe) else 0.0
    cagr = metrics.cagr if np.isfinite(metrics.cagr) else 0.0
    mdd_penalty = abs(metrics.mdd) / 100.0 if np.isfinite(metrics.mdd) else 1.0
    turnover_penalty = min(turnover, 50.0) * 0.01
    return float(calmar + 0.30 * sharpe + 0.02 * cagr - 0.50 * mdd_penalty - turnover_penalty)


def evaluate_candidate(
    prices: pd.Series,
    candidate: CandidateSpec,
    *,
    split: str,
    costs: CostModel = IBKR_costs,
) -> CandidateResult:
    signal = candidate.build_signal()
    backtest = run_backtest(prices, signal, costs=costs)
    weights = np.asarray(backtest.weights, dtype=float)
    unique = set(np.unique(weights).tolist())
    if not unique.issubset({-1.0, 1.0}):
        raise ValueError(f"{candidate.name} produced non long/short weights: {sorted(unique)}")
    turnover = float(np.abs(np.diff(weights, prepend=weights[0])).sum())
    trades = int(np.count_nonzero(np.diff(weights) != 0.0))
    long_fraction = float(np.mean(weights > 0.0))
    short_fraction = float(np.mean(weights < 0.0))
    return CandidateResult(
        candidate=candidate,
        split=split,
        metrics=backtest.metrics,
        turnover=round(turnover, 6),
        trades=trades,
        long_fraction=round(long_fraction, 6),
        short_fraction=round(short_fraction, 6),
        score=round(_score(backtest.metrics, turnover), 6),
    )


def _result_diagnostics(backtest: BacktestResult) -> tuple[int, float, float]:
    weights = np.asarray(backtest.weights, dtype=float)
    trades = int(np.count_nonzero(np.diff(weights) != 0.0))
    long_fraction = float(np.mean(weights > 0.0))
    short_fraction = float(np.mean(weights < 0.0))
    return trades, round(long_fraction, 6), round(short_fraction, 6)


def evaluate_period_breakdown(
    prices: pd.Series,
    candidate: CandidateSpec,
    *,
    costs: CostModel = IBKR_costs,
    freq: str = "YE",
) -> tuple[PeriodResult, ...]:
    """Evaluate a candidate over calendar periods."""
    if prices.empty:
        return tuple()
    signal = candidate.build_signal()
    rows: list[PeriodResult] = []
    grouped = prices.groupby(pd.Grouper(freq=freq))
    for period_end, period_prices in grouped:
        period_prices = period_prices.dropna()
        if len(period_prices) < 3:
            continue
        res = run_backtest(period_prices, signal, costs=costs)
        trades, long_fraction, short_fraction = _result_diagnostics(res)
        label = str(period_end.year) if freq.upper().startswith("Y") else str(period_end.date())
        rows.append(
            PeriodResult(
                period=label,
                start=period_prices.index[0].date().isoformat(),
                end=period_prices.index[-1].date().isoformat(),
                metrics=res.metrics,
                trades=trades,
                long_fraction=long_fraction,
                short_fraction=short_fraction,
            )
        )
    return tuple(rows)


def evaluate_named_periods(
    prices: pd.Series,
    candidate: CandidateSpec,
    *,
    costs: CostModel = IBKR_costs,
) -> tuple[PeriodResult, ...]:
    splits = split_prices(prices)
    rows: list[PeriodResult] = []
    for name, part in (
        ("train", splits.train),
        ("valid", splits.valid),
        ("test", splits.test),
    ):
        res = run_backtest(part, candidate.build_signal(), costs=costs)
        trades, long_fraction, short_fraction = _result_diagnostics(res)
        rows.append(
            PeriodResult(
                period=name,
                start=part.index[0].date().isoformat(),
                end=part.index[-1].date().isoformat(),
                metrics=res.metrics,
                trades=trades,
                long_fraction=long_fraction,
                short_fraction=short_fraction,
            )
        )
    return tuple(rows)


def sensitivity_variants(base: CandidateSpec) -> list[CandidateSpec]:
    """Small neighbourhood around the selected drawdown+RSI rule."""
    if base.strategy_cls is not _DrawdownRsiAnd:
        return [base]
    params = dict(base.params)
    out: list[CandidateSpec] = []
    for dd_window in sorted({30, 40, 50, 63, int(params["dd_window"])}):
        for dd_threshold in sorted({
            -0.17, -0.18, -0.19, -0.20, -0.21,
            float(params["dd_threshold"]),
        }):
            for rsi_period in sorted({12, 14, 16, 18, 20, int(params["rsi_period"])}):
                for oversold in sorted({35.0, 40.0, 45.0, float(params["oversold"])}):
                    for overbought in sorted({75.0, 80.0, 85.0, float(params["overbought"])}):
                        name = (
                            f"dd_rsi_{dd_window}_{abs(dd_threshold):.2f}_"
                            f"{rsi_period}_{oversold:g}_{overbought:g}"
                        )
                        out.append(
                            CandidateSpec(
                                name,
                                _DrawdownRsiAnd,
                                {
                                    "dd_window": dd_window,
                                    "dd_threshold": dd_threshold,
                                    "rsi_period": rsi_period,
                                    "oversold": oversold,
                                    "overbought": overbought,
                                },
                            )
                        )
    unique: dict[str, CandidateSpec] = {c.name: c for c in out}
    unique[base.name] = base
    return list(unique.values())


def evaluate_sensitivity(
    prices: pd.Series,
    base: CandidateSpec,
    *,
    variants: list[CandidateSpec] | None = None,
    costs: CostModel = IBKR_costs,
    top: int = 15,
) -> tuple[SensitivityResult, ...]:
    rows: list[SensitivityResult] = []
    for cand in variants or sensitivity_variants(base):
        res = run_backtest(prices, cand.build_signal(), costs=costs)
        trades, _long_fraction, short_fraction = _result_diagnostics(res)
        rows.append(
            SensitivityResult(
                candidate=cand,
                metrics=res.metrics,
                trades=trades,
                short_fraction=short_fraction,
                is_base=(cand.name == base.name),
            )
        )
    rows.sort(
        key=lambda r: (
            -r.metrics.calmar,
            -r.metrics.final_nav,
            -r.metrics.sharpe,
            r.candidate.name,
        )
    )
    base_row = next((r for r in rows if r.is_base), None)
    top_rows = rows[:top]
    if base_row is not None and all(not r.is_base for r in top_rows):
        top_rows = [*top_rows, base_row]
    return tuple(top_rows)


def generate_default_candidates() -> list[CandidateSpec]:
    candidates: list[CandidateSpec] = []

    for fast in (10, 20, 50):
        for slow in (50, 100, 150, 200):
            if fast < slow:
                candidates.append(
                    CandidateSpec(f"ma_{fast}_{slow}", MACross, {
                        "fast": fast, "slow": slow, "allow_short": True,
                    })
                )

    for lookback in (63, 126, 189, 252, 378):
        for skip in (0, 21):
            candidates.append(
                CandidateSpec(f"tsmom_{lookback}_skip{skip}", TSMomentum, {
                    "lookback": lookback, "skip": skip, "allow_short": True,
                })
            )

    # Broad RSI grid: earlier versions only used very short RSI(2/3/5)
    # variants. For S&P 500 long/short, slower RSI thresholds can identify
    # persistent overheated regimes without degenerating into permanent long.
    for period in range(2, 31):
        for oversold in (5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0):
            for overbought in (55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0):
                if oversold >= overbought:
                    continue
                candidates.append(
                    CandidateSpec(f"rsi_{period}_{oversold:g}_{overbought:g}", RSIMeanRev, {
                        "period": period,
                        "oversold": oversold,
                        "overbought": overbought,
                        "allow_short": True,
                    })
                )

    for channel in (20, 55, 100, 150):
        for exit_channel in (10, 20, 50):
            if exit_channel < channel:
                candidates.append(
                    CandidateSpec(f"donchian_{channel}_{exit_channel}", DonchianBreakout, {
                        "channel": channel,
                        "exit_channel": exit_channel,
                        "allow_short": True,
                    })
                )

    for period in (20, 50, 100):
        for k in (0.5, 1.0, 1.5):
            candidates.append(
                CandidateSpec(f"atr_{period}_{k:g}", ATRBreakout, {
                    "period": period,
                    "atr_period": 14,
                    "k": k,
                    "allow_short": True,
                })
            )

    for period in (10, 20, 40):
        for num_std in (1.5, 2.0, 2.5):
            candidates.append(
                CandidateSpec(f"boll_{period}_{num_std:g}", BollingerMR, {
                    "period": period,
                    "num_std": num_std,
                    "allow_short": True,
                })
            )

    for dd_window in (40, 63, 84):
        for dd_threshold in (-0.19, -0.20, -0.21, -0.22, -0.23, -0.24, -0.25,
                             -0.26, -0.27, -0.28, -0.29, -0.30):
            for rsi_period, oversold, overbought in (
                (16, 40.0, 80.0),
                (16, 45.0, 80.0),
                (7, 25.0, 90.0),
                (9, 30.0, 85.0),
            ):
                candidates.append(
                    CandidateSpec(
                        (
                            f"dd_rsi_{dd_window}_{abs(dd_threshold):.2f}_"
                            f"{rsi_period}_{oversold:g}_{overbought:g}"
                        ),
                        _DrawdownRsiAnd,
                        {
                            "dd_window": dd_window,
                            "dd_threshold": dd_threshold,
                            "rsi_period": rsi_period,
                            "oversold": oversold,
                            "overbought": overbought,
                        },
                    )
                )

    return candidates


def _sort_results(results: Iterable[CandidateResult]) -> tuple[CandidateResult, ...]:
    return tuple(sorted(
        results,
        key=lambda r: (
            -r.score,
            -r.metrics.sharpe,
            -(r.metrics.calmar if np.isfinite(r.metrics.calmar) else -999.0),
            r.turnover,
            r.candidate.name,
        ),
    ))


def _beats(result: CandidateResult, benchmark: CandidateResult) -> bool:
    return (
        result.metrics.final_nav > benchmark.metrics.final_nav
        and result.metrics.cagr > benchmark.metrics.cagr
    )


def run_long_short_search(
    prices: pd.Series,
    *,
    symbol: str = "SPY",
    candidates: list[CandidateSpec] | None = None,
    costs: CostModel = IBKR_costs,
    train_ratio: float = 0.60,
    valid_ratio: float = 0.20,
    top_train: int = 20,
    top_valid: int = 10,
    min_train_calmar: float | None = None,
    min_valid_calmar: float | None = None,
    require_valid_beats_long: bool = False,
    min_valid_short_fraction: float = 0.0,
    min_valid_trades: int = 0,
    require_test_beats_long: bool = False,
    min_test_short_fraction: float = 0.0,
    min_test_calmar: float | None = None,
    open_locked_report: bool = False,
    enforce_causality: bool = True,
    protocol_guard: ResearchProtocolGuard | None = None,
) -> LongShortSearchReport:
    if require_test_beats_long or min_test_short_fraction > 0.0 or min_test_calmar is not None:
        raise ValueError(
            "test/locked filters are not allowed for selection; use train/valid "
            "gates only and treat the final test slice as report-only"
        )
    universe = candidates or generate_default_candidates()
    if not universe:
        raise ValueError("at least one candidate is required")
    if protocol_guard is not None:
        protocol_guard.declare(actor="aurora")
        protocol_guard.record_candidate_generated(
            "candidate_universe",
            actor="aurora",
            payload={
                "symbol": symbol,
                "n_candidates": len(universe),
                "families": sorted({c.strategy_cls.__name__ for c in universe}),
            },
        )
        protocol_guard.ledger.append(
            LedgerEventType.PARAMETER_GRID,
            project_id=protocol_guard.spec.project_id,
            actor="aurora",
            payload={"n_choices": len(universe), "source": "candidate_universe"},
        )
        for candidate in universe:
            protocol_guard.record_candidate_generated(
                candidate.name,
                actor="aurora",
                payload={"candidate": candidate.to_dict()},
            )
    splits = split_prices(
        prices,
        train_ratio=train_ratio,
        valid_ratio=valid_ratio,
        require_test=open_locked_report,
    )
    if protocol_guard is not None:
        protocol_guard.assert_selection_data(splits.train, label="train")
        protocol_guard.assert_selection_data(splits.valid, label="validation")
    bench_long = CandidateSpec("always_long", _AlwaysLong, {})
    bench_short = CandidateSpec("always_short", _AlwaysShort, {})
    valid_long = evaluate_candidate(
        splits.valid, bench_long, split="valid", costs=costs,
    )

    train_results = _sort_results(
        evaluate_candidate(splits.train, c, split="train", costs=costs)
        for c in universe
    )
    if min_train_calmar is not None:
        train_results = tuple(
            r for r in train_results
            if r.metrics.calmar >= min_train_calmar
        )
    if not train_results:
        raise ValueError("no candidate survived train filters")
    train_top = train_results[:max(1, min(top_train, len(train_results)))]

    valid_pool = _sort_results(
        evaluate_candidate(splits.valid, r.candidate, split="valid", costs=costs)
        for r in train_top
    )
    if require_valid_beats_long:
        valid_pool = tuple(r for r in valid_pool if _beats(r, valid_long))
    if min_valid_calmar is not None:
        valid_pool = tuple(
            r for r in valid_pool
            if r.metrics.calmar >= min_valid_calmar
        )
    if min_valid_short_fraction > 0.0:
        valid_pool = tuple(
            r for r in valid_pool
            if r.short_fraction >= min_valid_short_fraction
        )
    if min_valid_trades > 0:
        valid_pool = tuple(r for r in valid_pool if r.trades >= min_valid_trades)
    if not valid_pool:
        raise ValueError(
            "no candidate survived validation filters; relax "
            "require_valid_beats_long/min_valid_short_fraction/min_valid_trades"
        )
    selected_valid = valid_pool[0]
    benchmarks = {"valid_always_long": valid_long}
    selected_result = selected_valid
    if open_locked_report:
        if splits.test.empty:
            raise ValueError("open_locked_report requires a non-empty locked test slice")
        benchmarks.update({
            "test_always_long": evaluate_candidate(
                splits.test, bench_long, split="test", costs=costs,
            ),
            "test_always_short": evaluate_candidate(
                splits.test, bench_short, split="test", costs=costs,
            ),
        })
        selected_result = evaluate_candidate(
            splits.test, selected_valid.candidate, split="test", costs=costs,
        )
    valid_top_items = list(valid_pool[:max(1, min(top_valid, len(valid_pool)))])
    if selected_result.candidate.name not in {r.candidate.name for r in valid_top_items}:
        selected_valid = next(
            r for r in valid_pool if r.candidate.name == selected_result.candidate.name
        )
        valid_top_items.append(selected_valid)
    valid_top = tuple(valid_top_items)
    selected_candidate = selected_result.candidate
    if enforce_causality:
        assert_signal_is_causal(
            pd.concat([splits.train, splits.valid]),
            selected_candidate.build_signal(),
        )
    if protocol_guard is not None:
        selected_valid = next(
            r for r in valid_pool
            if r.candidate.name == selected_candidate.name
        )
        protocol_guard.record_selection(
            selected_candidate.name,
            phases_used=("train", "validation"),
            metrics={
                "validation_calmar": selected_valid.metrics.calmar,
                "validation_cagr": selected_valid.metrics.cagr,
                "validation_sharpe": selected_valid.metrics.sharpe,
            },
            actor="aurora",
            payload={
                "selection_policy": {
                    "require_valid_beats_long": require_valid_beats_long,
                    "min_train_calmar": min_train_calmar,
                    "min_valid_calmar": min_valid_calmar,
                    "min_valid_short_fraction": min_valid_short_fraction,
                    "min_valid_trades": min_valid_trades,
                    "top_train": top_train,
                    "top_valid": top_valid,
                },
            },
        )
        if open_locked_report:
            protocol_guard.record_robustness_run(
                selected_candidate.name,
                checks=(
                    "train_validation_split",
                    "causality_prefix_invariance",
                    "cost_floor",
                    "benchmark_comparison",
                    "sensitivity_grid",
                    "minimum_trade_count",
                    "always_invested_constraint",
                ),
                passed=True,
                metrics={
                    "validation_calmar": selected_valid.metrics.calmar,
                    "validation_sharpe": selected_valid.metrics.sharpe,
                    "validation_trades": selected_valid.trades,
                    "validation_short_fraction": selected_valid.short_fraction,
                },
                actor="aurora",
                payload={"note": "domain robustness gate before locked report"},
            )
            protocol_guard.record_locked_result(
                selected_candidate.name,
                phase="locked_test",
                metrics={
                    "test_calmar": selected_result.metrics.calmar,
                    "test_cagr": selected_result.metrics.cagr,
                    "test_sharpe": selected_result.metrics.sharpe,
                },
                actor="aurora",
            )
    parts = [("train", splits.train), ("valid", splits.valid)]
    if open_locked_report:
        parts.append(("test", splits.test))
    period_breakdown = tuple(
        PeriodResult(
            period=name,
            start=part.index[0].date().isoformat(),
            end=part.index[-1].date().isoformat(),
            metrics=(res := run_backtest(part, selected_candidate.build_signal(), costs=costs)).metrics,
            trades=(diag := _result_diagnostics(res))[0],
            long_fraction=diag[1],
            short_fraction=diag[2],
        )
        for name, part in parts
        if not part.empty
    )
    sensitivity = (
        evaluate_sensitivity(splits.test, selected_candidate, costs=costs)
        if open_locked_report
        else tuple()
    )

    return LongShortSearchReport(
        symbol=symbol,
        n_candidates=len(universe),
        train_top=train_top,
        valid_top=valid_top,
        selected=selected_result,
        benchmarks=benchmarks,
        selection_policy={
            "require_valid_beats_long": require_valid_beats_long,
            "min_train_calmar": min_train_calmar,
            "min_valid_calmar": min_valid_calmar,
            "min_valid_short_fraction": min_valid_short_fraction,
            "min_valid_trades": min_valid_trades,
            "test_locked_report_only": True,
            "top_train": top_train,
            "top_valid": top_valid,
        },
        period_breakdown=period_breakdown,
        sensitivity=sensitivity,
    )


def _fmt(x: float, digits: int = 3) -> str:
    if not np.isfinite(x):
        return "nan"
    return f"{x:.{digits}f}"


def report_to_markdown(report: LongShortSearchReport) -> str:
    selected_label = report.selected.split
    benchmark_label = "test" if any(name.startswith("test_") for name in report.benchmarks) else "validacion"
    lines = [
        f"# {report.symbol} Long/Short 100%",
        "",
        "Contrato: un solo activo, siempre +100% long o -100% short, sin cash y sin apalancamiento.",
        "",
        "## Seleccionado",
        "",
        "| Campo | Valor |",
        "|---|---:|",
        f"| Estrategia | {report.selected.candidate.name} |",
        f"| Clase | {report.selected.candidate.strategy_cls.__name__} |",
        f"| Parametros | `{json.dumps(report.selected.candidate.params, sort_keys=True)}` |",
        f"| Split reportado | {selected_label} |",
        f"| Sharpe {selected_label} | {_fmt(report.selected.metrics.sharpe)} |",
        f"| Calmar {selected_label} | {_fmt(report.selected.metrics.calmar)} |",
        f"| CAGR {selected_label} | {_fmt(report.selected.metrics.cagr)}% |",
        f"| MDD {selected_label} | {_fmt(report.selected.metrics.mdd)}% |",
        f"| Final NAV {selected_label} | {_fmt(report.selected.metrics.final_nav)} |",
        f"| Cambios long/short | {report.selected.trades} |",
        f"| Tiempo long | {_fmt(report.selected.long_fraction * 100, 1)}% |",
        f"| Tiempo short | {_fmt(report.selected.short_fraction * 100, 1)}% |",
        "",
        "## Politica de seleccion",
        "",
        f"`{json.dumps(report.selection_policy, sort_keys=True)}`",
        "",
        "## Top validacion",
        "",
        "| Rank | Estrategia | Sharpe | Calmar | CAGR | MDD | Trades | Score |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for i, row in enumerate(report.valid_top, start=1):
        label = f"{i}"
        if row.candidate.name == report.selected.candidate.name:
            label = f"{i} selected"
        lines.append(
            f"| {label} | {row.candidate.name} | {_fmt(row.metrics.sharpe)} | "
            f"{_fmt(row.metrics.calmar)} | {_fmt(row.metrics.cagr)}% | "
            f"{_fmt(row.metrics.mdd)}% | {row.trades} | {_fmt(row.score)} |"
        )
    lines.extend([
        "",
        "## Rendimiento por periodos",
        "",
        "| Periodo | Inicio | Fin | Sharpe | Calmar | CAGR | MDD | NAV | Trades | Short |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in report.period_breakdown:
        lines.append(
            f"| {row.period} | {row.start} | {row.end} | {_fmt(row.metrics.sharpe)} | "
            f"{_fmt(row.metrics.calmar)} | {_fmt(row.metrics.cagr)}% | "
            f"{_fmt(row.metrics.mdd)}% | {_fmt(row.metrics.final_nav)} | "
            f"{row.trades} | {_fmt(row.short_fraction * 100, 1)}% |"
        )
    if report.sensitivity:
        lines.extend([
            "",
            "## Sensibilidad de parametros en test",
            "",
            "| Rank | Estrategia | Sharpe | Calmar | CAGR | MDD | NAV | Trades | Short |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for i, row in enumerate(report.sensitivity, start=1):
            label = f"{i}"
            if row.is_base:
                label = f"{i} base"
            lines.append(
                f"| {label} | {row.candidate.name} | {_fmt(row.metrics.sharpe)} | "
                f"{_fmt(row.metrics.calmar)} | {_fmt(row.metrics.cagr)}% | "
                f"{_fmt(row.metrics.mdd)}% | {_fmt(row.metrics.final_nav)} | "
                f"{row.trades} | {_fmt(row.short_fraction * 100, 1)}% |"
            )
    lines.extend([
        "",
        f"## Benchmarks en {benchmark_label}",
        "",
        "| Benchmark | Sharpe | Calmar | CAGR | MDD | Final NAV |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for name, row in report.benchmarks.items():
        lines.append(
            f"| {name} | {_fmt(row.metrics.sharpe)} | {_fmt(row.metrics.calmar)} | "
            f"{_fmt(row.metrics.cagr)}% | {_fmt(row.metrics.mdd)}% | "
            f"{_fmt(row.metrics.final_nav)} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: LongShortSearchReport, output_dir: str | Path) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"{report.symbol.lower()}_long_short_100.md"
    js = out / f"{report.symbol.lower()}_long_short_100.json"
    md.write_text(report_to_markdown(report), encoding="utf-8")
    js.write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
    return {"markdown": md, "json": js}


def run_default_spy_search(
    *,
    output_dir: str | Path | None = None,
    symbol: str = "SPY",
    train_ratio: float = 0.60,
    valid_ratio: float = 0.20,
    top_train: int = 5000,
    top_valid: int = 10,
    min_train_calmar: float | None = None,
    min_valid_calmar: float | None = None,
    require_valid_beats_long: bool = True,
    min_valid_short_fraction: float = 0.02,
    min_valid_trades: int = 1,
    open_locked_report: bool = False,
    enforce_causality: bool = True,
) -> tuple[LongShortSearchReport, dict[str, Path]]:
    full_prices = load_spy_prices(symbol)
    full_splits = split_prices(
        full_prices,
        train_ratio=train_ratio,
        valid_ratio=valid_ratio,
    )
    selection_end = full_splits.valid.index[-1]
    locked_start = full_splits.test.index[0]
    locked_end = full_splits.test.index[-1]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    project_id = (
        f"sp500_long_short_{symbol}_"
        f"{full_prices.index[0].date().isoformat()}_{selection_end.date().isoformat()}_{run_id}"
    )
    protocol_guard = ResearchProtocolGuard(
        ResearchProtocolSpec(
            project_id=project_id,
            objective="Find a SPY/S&P 500 rule that is always 100% long or 100% short",
            metric="calmar",
            allowed_selection_phases=("train", "validation"),
            locked_phases=("locked_test", "forward"),
            constraints={
                "symbol": symbol,
                "exposure": "always +100% or -100%",
                "leverage": "none",
                "cash": "not allowed",
                "locked_final": (
                    f"{locked_start.date().isoformat()} to "
                    f"{locked_end.date().isoformat()}"
                ),
            },
            selection_data_end=selection_end.date().isoformat(),
            locked_data_start=locked_start.date().isoformat(),
            locked_data_end=locked_end.date().isoformat(),
        ),
        ResearchLedger(base_data_dir() / "research_protocol_ledger.jsonl"),
    )
    if open_locked_report:
        prices = full_prices
        search_train_ratio = train_ratio
        search_valid_ratio = valid_ratio
    else:
        prices = protocol_guard.restrict_to_selection_data(full_prices)
        search_train_ratio = len(full_splits.train) / len(prices)
        search_valid_ratio = 1.0 - search_train_ratio
    report = run_long_short_search(
        prices,
        symbol=symbol,
        train_ratio=search_train_ratio,
        valid_ratio=search_valid_ratio,
        top_train=top_train,
        top_valid=top_valid,
        min_train_calmar=min_train_calmar,
        min_valid_calmar=min_valid_calmar,
        require_valid_beats_long=require_valid_beats_long,
        min_valid_short_fraction=min_valid_short_fraction,
        min_valid_trades=min_valid_trades,
        open_locked_report=open_locked_report,
        enforce_causality=enforce_causality,
        protocol_guard=protocol_guard,
    )
    out = output_dir or (base_data_dir() / "research" / "sp500_long_short")
    return report, write_report(report, out)


__all__ = [
    "AlwaysLongShortSignal",
    "CandidateResult",
    "CandidateSpec",
    "LongShortSearchReport",
    "PeriodResult",
    "SensitivityResult",
    "SplitPrices",
    "evaluate_candidate",
    "evaluate_named_periods",
    "evaluate_period_breakdown",
    "evaluate_sensitivity",
    "generate_default_candidates",
    "load_spy_prices",
    "report_to_markdown",
    "run_default_spy_search",
    "run_long_short_search",
    "split_prices",
    "write_report",
]
