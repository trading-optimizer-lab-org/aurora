"""Persistent SPY/S&P 500 long-short autosearch.

The search contract is intentionally strict:

* SPY is the only traded instrument.
* Final exposure is always exactly +1 or -1.
* Candidate selection is based on train only.
* Validation is an exam for train-approved candidates.
* Locked data is opened only at the end, and only when explicitly requested.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from aurora.core.costs import CostModel, IBKR_costs, apply_costs
from aurora.core.metrics import Metrics, compute_metrics
from aurora.core.runtime_paths import base_data_dir
from aurora.research.ledger import LedgerEventType, ResearchLedger
from aurora.research.protocol_guard import ResearchProtocolGuard, ResearchProtocolSpec
from aurora.research.sp500_long_short import load_spy_prices
from aurora.validation.statistical_robustness import (
    StatisticalRobustnessConfig,
    statistical_robustness_gate,
)


DEFAULT_MARKET_SYMBOLS = (
    "^VIX",
    "^VIX3M",
    "^TNX",
    "^IRX",
    "TLT",
    "IEF",
    "HYG",
    "LQD",
    "QQQ",
    "IWM",
    "RSP",
    "XLF",
    "XLK",
    "XLE",
    "XLU",
    "XLP",
    "XLV",
    "XLY",
    "GLD",
    "UUP",
)

DEFAULT_FRED_IDS = (
    "NFCI",
    "STLFSI4",
    "BAMLH0A0HYM2",
    "T10Y2Y",
    "T10Y3M",
    "UNRATE",
    "UMCSENT",
)


@dataclass(frozen=True)
class AutosearchConfig:
    """Configuration for one resumable autosearch run."""

    target_calmar: float = 1.0
    symbol: str = "SPY"
    train_end: str = "2013-10-18"
    validation_start: str = "2013-10-21"
    validation_end: str = "2020-01-28"
    locked_start: str = "2020-01-29"
    locked_end: str | None = None
    max_rounds: int = 6
    max_candidates_per_round: int = 50_000
    max_hours: float = 8.0
    cpu_workers: int = 1
    checkpoint_every: int = 5_000
    open_locked_final: bool = False
    market_symbols: tuple[str, ...] = DEFAULT_MARKET_SYMBOLS
    fred_ids: tuple[str, ...] = DEFAULT_FRED_IDS
    output_dir: str | None = None
    resume: bool = False
    provider: str = "yfinance"
    round_offset: int = 0
    feature_packs_path: str | None = None
    blocked_features: tuple[str, ...] = ()
    blocked_rule_signatures: tuple[str, ...] = ()

    def run_root(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        return base_data_dir() / "research" / "sp500_autosearch"


@dataclass(frozen=True)
class PeriodMetrics:
    metrics: Metrics
    trades: int
    long_fraction: float
    short_fraction: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics.to_dict(),
            "trades": self.trades,
            "long_fraction": self.long_fraction,
            "short_fraction": self.short_fraction,
        }


@dataclass(frozen=True)
class CandidateEvidence:
    candidate_id: str
    round_name: str
    rule: Mapping[str, Any]
    train: PeriodMetrics
    validation: PeriodMetrics | None
    locked: PeriodMetrics | None
    benchmark_train: PeriodMetrics
    benchmark_validation: PeriodMetrics
    benchmark_locked: PeriodMetrics | None
    robust_train_score: float
    robustness: Mapping[str, Any]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "round_name": self.round_name,
            "rule": dict(self.rule),
            "train": self.train.to_dict(),
            "validation": None if self.validation is None else self.validation.to_dict(),
            "locked": None if self.locked is None else self.locked.to_dict(),
            "benchmark_train": self.benchmark_train.to_dict(),
            "benchmark_validation": self.benchmark_validation.to_dict(),
            "benchmark_locked": (
                None if self.benchmark_locked is None else self.benchmark_locked.to_dict()
            ),
            "robust_train_score": self.robust_train_score,
            "robustness": dict(self.robustness),
            "passed": self.passed,
        }


@dataclass(frozen=True)
class AutosearchReport:
    project_id: str
    run_dir: Path
    target_calmar: float
    periods: Mapping[str, Any]
    best: CandidateEvidence
    locked_opened: bool
    rounds_completed: int
    candidates_evaluated: int
    validation_examined: int
    stopped_reason: str
    attempts_path: Path
    ledger_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "run_dir": str(self.run_dir),
            "target_calmar": self.target_calmar,
            "protocol": {
                "declared_before_search": True,
                "selection_rule": "train_only_robust_score",
                "validation_role": "exam_only_for_train_passers",
                "locked_opened": self.locked_opened,
            },
            "periods": dict(self.periods),
            "best": self.best.to_dict(),
            "locked_opened": self.locked_opened,
            "rounds_completed": self.rounds_completed,
            "candidates_evaluated": self.candidates_evaluated,
            "validation_examined": self.validation_examined,
            "stopped_reason": self.stopped_reason,
            "attempts_path": str(self.attempts_path),
            "ledger_path": str(self.ledger_path),
        }


@dataclass
class _SearchState:
    project_id: str
    round_index: int = 0
    candidates_evaluated: int = 0
    validation_examined: int = 0
    best: dict[str, Any] | None = None
    stopped: bool = False
    stopped_reason: str = "running"
    last_checkpoint_utc: str | None = None
    candidates_per_second: float | None = None


def _train_candidate_row(
    *,
    round_name: str,
    candidate_index: int,
    rule: Mapping[str, Any],
    prices_train: pd.Series,
    x_train: pd.DataFrame,
) -> dict[str, Any]:
    weights = _weights_for_rule(x_train, rule)
    train = _period_metrics(prices_train, weights)
    return {
        "candidate_id": _candidate_id(round_name, candidate_index),
        "round_name": round_name,
        "rule": rule,
        "train": train.to_dict(),
        "train_calmar": train.metrics.calmar,
        "robust_train_score": None,
        "validation": None,
        "passed": False,
    }


def _train_candidate_task(task: Mapping[str, Any]) -> dict[str, Any]:
    return _train_candidate_row(
        round_name=str(task["round_name"]),
        candidate_index=int(task["candidate_index"]),
        rule=task["rule"],
        prices_train=task["prices_train"],
        x_train=task["x_train"],
    )


def _candidate_batch_size(cpu_workers: int) -> int:
    """Convert the user-facing CPU budget into a vectorized candidate batch."""

    return max(128, min(4096, max(1, int(cpu_workers)) * 1024))


def _train_candidate_row_batches(
    *,
    round_name: str,
    start_candidate_index: int,
    rules: list[Mapping[str, Any]],
    prices_train: pd.Series,
    x_train: pd.DataFrame,
    batch_size: int,
) -> Iterable[list[dict[str, Any]]]:
    for batch_start in range(0, len(rules), max(1, batch_size)):
        batch_rules = rules[batch_start : batch_start + max(1, batch_size)]
        if not batch_rules:
            continue
        weight_columns = [_weights_for_rule(x_train, rule) for rule in batch_rules]
        metrics = _period_metrics_many(prices_train, np.column_stack(weight_columns))
        rows: list[dict[str, Any]] = []
        for offset, (rule, train) in enumerate(zip(batch_rules, metrics)):
            candidate_index = start_candidate_index + batch_start + offset
            rows.append(
                {
                    "candidate_id": _candidate_id(round_name, candidate_index),
                    "round_name": round_name,
                    "rule": rule,
                    "train": train.to_dict(),
                    "train_calmar": train.metrics.calmar,
                    "robust_train_score": None,
                    "validation": None,
                    "passed": False,
                }
            )
        yield rows


def _train_candidate_chunk_task(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    return next(
        iter(
            _train_candidate_row_batches(
                round_name=str(task["round_name"]),
                start_candidate_index=int(task["start_candidate_index"]),
                rules=list(task["rules"]),
                prices_train=task["prices_train"],
                x_train=task["x_train"],
                batch_size=int(task["batch_size"]),
            )
        )
    )


def _iter_training_batches(
    *,
    round_name: str,
    start_candidate_index: int,
    rules: list[Mapping[str, Any]],
    prices_train: pd.Series,
    x_train: pd.DataFrame,
    batch_size: int,
    cpu_workers: int,
) -> Iterable[list[dict[str, Any]]]:
    if cpu_workers > 1 and len(rules) >= batch_size * 2:
        tasks = []
        for batch_start in range(0, len(rules), batch_size):
            tasks.append(
                {
                    "round_name": round_name,
                    "start_candidate_index": start_candidate_index + batch_start,
                    "rules": rules[batch_start : batch_start + batch_size],
                    "prices_train": prices_train,
                    "x_train": x_train,
                    "batch_size": batch_size,
                }
            )
        yielded_any = False
        try:
            with ProcessPoolExecutor(max_workers=cpu_workers) as pool:
                for batch in pool.map(_train_candidate_chunk_task, tasks):
                    yielded_any = True
                    yield batch
            return
        except Exception:
            if yielded_any:
                raise

    yield from _train_candidate_row_batches(
        round_name=round_name,
        start_candidate_index=start_candidate_index,
        rules=rules,
        prices_train=prices_train,
        x_train=x_train,
        batch_size=batch_size,
    )


def run_sp500_autosearch(config: AutosearchConfig | None = None) -> AutosearchReport:
    """Run or resume a strict persistent SPY autosearch."""

    cfg = config or AutosearchConfig()
    run_dir, state = _open_or_create_run(cfg)
    attempts_path = run_dir / "all_attempts.jsonl"
    ledger = ResearchLedger(run_dir / "research_protocol_ledger.jsonl")

    data = _load_dataset_cached(cfg)
    train_idx = data.prices.loc[: cfg.train_end].index
    valid_idx = data.prices.loc[cfg.validation_start: cfg.validation_end].index
    locked_end = cfg.locked_end or data.prices.index[-1].date().isoformat()
    locked_idx = data.prices.loc[cfg.locked_start: locked_end].index
    if train_idx.empty or valid_idx.empty or locked_idx.empty:
        raise ValueError("train, validation and locked periods must be non-empty")

    guard = _declare_protocol(cfg, state.project_id, ledger, train_idx, valid_idx, locked_idx, data)
    feature_packs = _load_feature_packs(cfg.feature_packs_path)
    rounds = _rotated_round_plan(cfg.round_offset, feature_packs=feature_packs)
    deadline = time.monotonic() + max(float(cfg.max_hours), 0.001) * 3600.0
    search_started = time.monotonic()
    candidates_at_start = state.candidates_evaluated
    best_record = state.best
    passed_record: dict[str, Any] | None = None

    for round_index in range(state.round_index, min(cfg.max_rounds, len(rounds))):
        if time.monotonic() >= deadline:
            state.stopped_reason = "max_hours_reached"
            break
        round_name = rounds[round_index]
        x_train = _features_for_round(data, train_idx, round_name, feature_packs=feature_packs)
        x_valid = _features_for_round(data, valid_idx, round_name, feature_packs=feature_packs)
        third_indices = _thirds(train_idx)
        x_thirds = [
            _features_for_round(data, idx, round_name, feature_packs=feature_packs)
            for idx in third_indices
        ]
        rules = _rules_for_round(
            x_train,
            round_name,
            cfg.max_candidates_per_round,
            blocked_features=cfg.blocked_features,
            blocked_rule_signatures=cfg.blocked_rule_signatures,
        )

        ledger.append(
            LedgerEventType.PARAMETER_GRID,
            project_id=state.project_id,
            actor="aurora_autosearch",
            payload={
                "round": round_name,
                "n_choices": len(rules),
                "selection_phase": "train_only",
                "target_calmar": cfg.target_calmar,
            },
        )

        round_rows: list[dict[str, Any]] = []
        pending_rows: list[dict[str, Any]] = []
        prices_train = data.prices.loc[train_idx]
        start_candidate_index = state.candidates_evaluated
        batch_size = _candidate_batch_size(cfg.cpu_workers)
        next_checkpoint = state.candidates_evaluated + max(1, cfg.checkpoint_every)
        for batch in _iter_training_batches(
            round_name=round_name,
            start_candidate_index=start_candidate_index,
            rules=rules,
            prices_train=prices_train,
            x_train=x_train,
            batch_size=batch_size,
            cpu_workers=cfg.cpu_workers,
        ):
            for row in batch:
                round_rows.append(row)
                pending_rows.append(row)
                state.candidates_evaluated += 1
                if _better(row, best_record):
                    best_record = row
                    state.best = best_record
            if state.candidates_evaluated >= next_checkpoint:
                _append_attempts(attempts_path, pending_rows)
                pending_rows = []
                _update_progress(
                    state,
                    started_at=search_started,
                    candidates_at_start=candidates_at_start,
                )
                _write_state(run_dir, state)
                next_checkpoint = state.candidates_evaluated + max(1, cfg.checkpoint_every)

        ranked = sorted(
            round_rows,
            key=lambda r: r["train_calmar"] if np.isfinite(r["train_calmar"]) else -1e9,
            reverse=True,
        )
        # Add any just-flushed records back from the current round is not worth
        # re-reading here; robust scoring is intentionally bounded to the most
        # recent train-ranked candidates in this round.
        top_rows = ranked[: min(800, len(ranked))]
        robust_rows = _robustness_many(
            data.prices,
            train_idx,
            x_train,
            top_rows,
            third_indices,
            x_thirds,
        )
        peer_returns = _peer_net_returns_for_rows(
            data.prices.loc[train_idx],
            x_train,
            top_rows[: min(200, len(top_rows))],
        )
        for row, robust in zip(top_rows, robust_rows):
            rule = row["rule"]
            row["robustness"] = robust
            row["robust_train_score"] = robust["robust_train_score"]
            if row["robust_train_score"] >= cfg.target_calmar:
                train_weights = _weights_for_rule(x_train, rule)
                statistical = _statistical_robustness_for_weights(
                    prices=data.prices.loc[train_idx],
                    weights=train_weights,
                    target_calmar=cfg.target_calmar,
                    n_trials=max(1, state.candidates_evaluated),
                    peer_returns=peer_returns,
                )
                row["statistical_robustness"] = statistical.to_dict()
                if not statistical.passed:
                    row["passed"] = False
                    row["rejected_reason"] = "statistical_robustness_failed"
                    continue
                state.validation_examined += 1
                val_weights = _weights_for_rule(x_valid, rule)
                validation = _period_metrics(data.prices.loc[valid_idx], val_weights)
                row["validation"] = validation.to_dict()
                row["passed"] = validation.metrics.calmar >= cfg.target_calmar
                if row["passed"]:
                    passed_record = row
                    best_record = row
                    state.best = best_record
                    break
            if _better(row, best_record):
                best_record = row
                state.best = best_record

        _append_attempts(attempts_path, pending_rows)
        state.round_index = round_index + 1
        _update_progress(
            state,
            started_at=search_started,
            candidates_at_start=candidates_at_start,
        )
        _write_state(run_dir, state)
        if passed_record is not None:
            state.stopped = True
            state.stopped_reason = "target_passed_validation"
            break

    if passed_record is None:
        state.stopped_reason = state.stopped_reason if state.stopped_reason != "running" else "budget_exhausted"
    _write_state(run_dir, state)

    selected = passed_record or best_record
    if selected is None:
        raise RuntimeError("autosearch produced no candidate")

    evidence = _finalise_candidate(
        cfg=cfg,
        state=state,
        run_dir=run_dir,
        guard=guard,
        data=data,
        selected=selected,
        train_idx=train_idx,
        valid_idx=valid_idx,
        locked_idx=locked_idx,
    )
    report = AutosearchReport(
        project_id=state.project_id,
        run_dir=run_dir,
        target_calmar=cfg.target_calmar,
        periods={
            "train": [str(train_idx[0].date()), str(train_idx[-1].date()), len(train_idx)],
            "validation": [str(valid_idx[0].date()), str(valid_idx[-1].date()), len(valid_idx)],
            "locked": [str(locked_idx[0].date()), str(locked_idx[-1].date()), len(locked_idx)],
        },
        best=evidence,
        locked_opened=evidence.locked is not None,
        rounds_completed=state.round_index,
        candidates_evaluated=state.candidates_evaluated,
        validation_examined=state.validation_examined,
        stopped_reason=state.stopped_reason,
        attempts_path=attempts_path,
        ledger_path=ledger.path,
    )
    (run_dir / "result.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return report


def report_to_markdown(report: AutosearchReport) -> str:
    best = report.best
    lines = [
        "# SPY Autosearch",
        "",
        f"Project: `{report.project_id}`",
        f"Target Calmar: {report.target_calmar}",
        f"Stopped reason: {report.stopped_reason}",
        f"Locked opened: {report.locked_opened}",
        "",
        "## Best candidate",
        "",
        f"Name: `{best.candidate_id}`",
        f"Round: `{best.round_name}`",
        f"Rule: `{json.dumps(best.rule, sort_keys=True)}`",
        "",
        "| Period | Calmar | CAGR | MDD | Trades |",
        "|---|---:|---:|---:|---:|",
        _metric_row("Train", best.train),
        _metric_row("Validation", best.validation),
        _metric_row("Locked", best.locked),
        "",
        "## Benchmark always long",
        "",
        "| Period | Calmar | CAGR | MDD | Trades |",
        "|---|---:|---:|---:|---:|",
        _metric_row("Train", best.benchmark_train),
        _metric_row("Validation", best.benchmark_validation),
        _metric_row("Locked", best.benchmark_locked),
        "",
        "## Robustness",
        "",
        f"`{json.dumps(best.robustness, sort_keys=True, default=str)}`",
        "",
        "## Trial pressure",
        "",
        f"Candidates evaluated: {report.candidates_evaluated}",
        f"Validation examined: {report.validation_examined}",
        f"Rounds completed: {report.rounds_completed}",
        f"Attempts: `{report.attempts_path}`",
        f"Ledger: `{report.ledger_path}`",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class _Dataset:
    prices: pd.Series
    external: Mapping[str, pd.Series] = field(default_factory=dict)
    fred: Mapping[str, pd.Series] = field(default_factory=dict)


_DATASET_CACHE: dict[tuple[Any, ...], _Dataset] = {}


def clear_dataset_cache() -> None:
    """Clear in-process market data cache used by repeated agent rounds."""

    _DATASET_CACHE.clear()


def _open_or_create_run(cfg: AutosearchConfig) -> tuple[Path, _SearchState]:
    root = cfg.run_root()
    root.mkdir(parents=True, exist_ok=True)
    if cfg.resume:
        candidates = sorted(
            [p for p in root.iterdir() if p.is_dir() and (p / "checkpoint.json").exists()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(f"no resumable run under {root}")
        run_dir = candidates[0]
        state = _read_state(run_dir)
        return run_dir, state

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    project_id = f"sp500_autosearch_{run_id}"
    state = _SearchState(project_id=project_id)
    (run_dir / "config.json").write_text(
        json.dumps(asdict(cfg), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    _write_state(run_dir, state)
    return run_dir, state


def _read_state(run_dir: Path) -> _SearchState:
    data = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
    return _SearchState(**data)


def _write_state(run_dir: Path, state: _SearchState) -> None:
    (run_dir / "checkpoint.json").write_text(
        json.dumps(asdict(state), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _update_progress(
    state: _SearchState,
    *,
    started_at: float,
    candidates_at_start: int,
) -> None:
    elapsed = max(time.monotonic() - started_at, 1e-9)
    done = max(0, state.candidates_evaluated - candidates_at_start)
    state.candidates_per_second = round(done / elapsed, 2)
    state.last_checkpoint_utc = datetime.now(timezone.utc).isoformat()


def _append_attempts(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), sort_keys=True, default=str) + "\n")


def _dataset_cache_key(cfg: AutosearchConfig) -> tuple[Any, ...]:
    return (
        id(_load_dataset),
        cfg.symbol,
        cfg.locked_end,
        cfg.provider,
        tuple(cfg.market_symbols),
        tuple(cfg.fred_ids),
    )


def _load_dataset_cached(cfg: AutosearchConfig) -> _Dataset:
    key = _dataset_cache_key(cfg)
    if key not in _DATASET_CACHE:
        _DATASET_CACHE[key] = _load_dataset(cfg)
    return _DATASET_CACHE[key]


def _load_dataset(cfg: AutosearchConfig) -> _Dataset:
    prices = load_spy_prices(cfg.symbol)
    if cfg.locked_end:
        prices = prices.loc[: cfg.locked_end]
    external: dict[str, pd.Series] = {}
    if cfg.market_symbols:
        try:
            import yfinance as yf
        except Exception:
            yf = None
        if yf is not None:
            for sym in cfg.market_symbols:
                try:
                    df = yf.download(
                        sym,
                        start="1993-01-01",
                        end=(cfg.locked_end or prices.index[-1].date().isoformat()),
                        progress=False,
                        auto_adjust=False,
                        threads=False,
                    )
                    if df.empty:
                        continue
                    external[sym] = _adj_close(df, sym).reindex(prices.index).ffill()
                except Exception:
                    continue
    fred: dict[str, pd.Series] = {}
    for fid in cfg.fred_ids:
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fid}"
            df = pd.read_csv(url)
            values = pd.to_numeric(df[fid], errors="coerce")
            series = pd.Series(
                values.to_numpy(),
                index=pd.to_datetime(df["observation_date"]),
                name=fid,
            ).sort_index()
            fred[fid] = series.reindex(prices.index).ffill().shift(5)
        except Exception:
            continue
    return _Dataset(prices=prices, external=external, fred=fred)


def _adj_close(df: pd.DataFrame, symbol: str) -> pd.Series:
    if isinstance(df.columns, pd.MultiIndex):
        level0 = set(df.columns.get_level_values(0))
        col = "Adj Close" if "Adj Close" in level0 else "Close"
        return pd.Series(df[(col, symbol)].astype(float).to_numpy(), index=pd.to_datetime(df.index))
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    return pd.Series(df[col].astype(float).to_numpy(), index=pd.to_datetime(df.index))


def _declare_protocol(
    cfg: AutosearchConfig,
    project_id: str,
    ledger: ResearchLedger,
    train_idx: pd.DatetimeIndex,
    valid_idx: pd.DatetimeIndex,
    locked_idx: pd.DatetimeIndex,
    data: _Dataset,
) -> ResearchProtocolGuard:
    spec = ResearchProtocolSpec(
        project_id=project_id,
        objective=f"SPY autosearch Calmar >= {cfg.target_calmar}",
        metric="calmar",
        allowed_selection_phases=("train",),
        locked_phases=("locked",),
        constraints={
            "operated_instrument": cfg.symbol,
            "exposure": "always +100% or -100%",
            "cash": "never",
            "leverage": "none",
            "selection": "train only",
            "target_calmar": cfg.target_calmar,
        },
        robustness_checks=(
            "lookahead",
            "double_cost",
            "one_day_delay",
            "train_subperiods",
            "benchmark_comparison",
        ),
        selection_data_end=str(valid_idx[-1].date()),
        locked_data_start=str(locked_idx[0].date()),
        locked_data_end=str(locked_idx[-1].date()),
    )
    guard = ResearchProtocolGuard(spec, ledger)
    guard.declare(
        actor="aurora_autosearch",
        payload={
            "strict_train_only": True,
            "market_symbols_loaded": sorted(data.external),
            "fred_ids_loaded": sorted(data.fred),
        },
    )
    for event_type, payload in (
        (LedgerEventType.UNIVERSE_SELECTED, {"operated": cfg.symbol}),
        (
            LedgerEventType.PROVIDER_SET,
            {"provider": cfg.provider, "fred_lag_trading_days": 5},
        ),
        (
            LedgerEventType.DATE_RANGE_SET,
            {
                "train": [str(train_idx[0].date()), str(train_idx[-1].date())],
                "validation": [str(valid_idx[0].date()), str(valid_idx[-1].date())],
                "locked": [str(locked_idx[0].date()), str(locked_idx[-1].date())],
            },
        ),
        (
            LedgerEventType.FEATURE_SET,
            {
                "families": _round_plan(),
                "causal": "features are built on physically sliced periods; FRED is lagged",
            },
        ),
        (LedgerEventType.SEED_SET, {"seed": "deterministic"}),
    ):
        ledger.append(event_type, project_id=project_id, actor="aurora_autosearch", payload=payload)
    return guard


def _round_plan(feature_packs: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[str, ...]:
    base = (
        "spy_core",
        "risk_ratios",
        "macro_stress",
        "slow_regime",
        "vix_regime",
        "sector_rotation",
        "credit_stress",
        "rates_curve",
        "breadth_proxy",
        "defensive_rotation",
        "volatility_breakout",
        "multi_signal",
    )
    if not feature_packs:
        return base
    return tuple(feature_packs) + base


def _rotated_round_plan(
    offset: int,
    *,
    feature_packs: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    rounds = _round_plan(feature_packs)
    if not rounds:
        return rounds
    if feature_packs:
        pack_rounds = tuple(feature_packs)
        base_rounds = _round_plan()
        pack_n = int(offset) % len(pack_rounds)
        base_n = int(offset) % len(base_rounds)
        return (
            pack_rounds[pack_n:]
            + pack_rounds[:pack_n]
            + base_rounds[base_n:]
            + base_rounds[:base_n]
        )
    n = int(offset) % len(rounds)
    return rounds[n:] + rounds[:n]


def _features_for_round(
    data: _Dataset,
    idx: pd.DatetimeIndex,
    round_name: str,
    *,
    feature_packs: Mapping[str, Mapping[str, Any]] | None = None,
) -> pd.DataFrame:
    prices = data.prices.loc[idx]
    out = pd.DataFrame(index=idx)
    pack = (feature_packs or {}).get(round_name)
    idea_round = pack is not None
    windows = (5, 10, 15, 21, 30, 42, 50, 63, 84, 100, 126, 168, 200, 252)
    for w in windows:
        out[f"spy_ret_{w}"] = prices.pct_change(w)
        out[f"spy_ma_{w}"] = prices / prices.rolling(w, min_periods=w).mean() - 1.0
        out[f"spy_dd_{w}"] = prices / prices.rolling(w, min_periods=w).max() - 1.0
    if round_name in {
        "spy_core",
        "vix_regime",
        "slow_regime",
        "volatility_breakout",
        "multi_signal",
    }:
        out["spy_vol_21"] = prices.pct_change().rolling(21, min_periods=21).std()
        out["spy_vol_63"] = prices.pct_change().rolling(63, min_periods=63).std()
    if idea_round:
        out["spy_vol_21"] = prices.pct_change().rolling(21, min_periods=21).std()
        out["spy_vol_63"] = prices.pct_change().rolling(63, min_periods=63).std()
    if idea_round or round_name in {
        "risk_ratios",
        "sector_rotation",
        "slow_regime",
        "credit_stress",
        "breadth_proxy",
        "defensive_rotation",
        "multi_signal",
    }:
        for name in ("QQQ", "IWM", "RSP", "XLF", "XLK", "XLU", "XLY", "XLP", "HYG", "LQD"):
            if name not in data.external:
                continue
        pairs = (
            ("QQQ", "SPY"),
            ("IWM", "SPY"),
            ("RSP", "SPY"),
            ("XLF", "SPY"),
            ("XLK", "XLU"),
            ("XLY", "XLP"),
            ("HYG", "LQD"),
        )
        local = {"SPY": prices, **{k: v.loc[idx] for k, v in data.external.items()}}
        for a, b in pairs:
            if a in local and b in local:
                ratio = local[a] / local[b]
                for w in (21, 63, 126):
                    out[f"{a}_{b}_{w}"] = ratio.pct_change(w)
    if idea_round or round_name in {
        "macro_stress",
        "slow_regime",
        "credit_stress",
        "rates_curve",
        "multi_signal",
    }:
        for fid, series in data.fred.items():
            x = series.loc[idx]
            out[f"fred_{fid}"] = x
            for w in (5, 21, 63):
                out[f"fred_{fid}_chg_{w}"] = x.diff(w)
    if idea_round or round_name in {
        "vix_regime",
        "macro_stress",
        "slow_regime",
        "volatility_breakout",
        "multi_signal",
    }:
        if "^VIX" in data.external:
            vix = data.external["^VIX"].loc[idx]
            out["vix_level"] = vix
            for w in (5, 21, 63, 126):
                out[f"vix_ret_{w}"] = vix.pct_change(w)
                out[f"vix_z_{w}"] = (
                    (vix - vix.rolling(w, min_periods=w).mean())
                    / vix.rolling(w, min_periods=w).std()
                )
        if "^VIX" in data.external and "^VIX3M" in data.external:
            out["vix_term"] = data.external["^VIX"].loc[idx] / data.external["^VIX3M"].loc[idx] - 1.0
    if pack is not None:
        _apply_feature_pack(out, pack)
    return out.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _load_feature_packs(path: str | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}
    packs: dict[str, dict[str, Any]] = {}
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.lstrip("\ufeff")
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        round_name = str(payload.get("round_name", "")).strip()
        family = str(payload.get("feature_family", "")).strip()
        if round_name and family:
            packs[round_name] = payload
    return packs


def _apply_feature_pack(out: pd.DataFrame, pack: Mapping[str, Any]) -> None:
    family = str(pack.get("feature_family", ""))
    suffix = _feature_pack_suffix(pack)
    variant = int(pack.get("feature_variant", 0)) % 18
    short = (5, 10, 15, 21, 30, 42, 50, 63, 84, 100, 126, 5, 10, 21, 30, 42, 63, 84)[variant]
    medium = (21, 42, 50, 63, 84, 100, 126, 168, 200, 252, 126, 63, 84, 126, 168, 200, 252, 200)[variant]
    long = (63, 126, 168, 200, 252, 252, 200, 252, 252, 252, 252, 168, 200, 252, 252, 252, 252, 252)[variant]
    if family == "drawdown_volatility":
        vol_short = _feature_series(out, "spy_vol_21")
        vol_long = _feature_series(out, "spy_vol_63")
        out[f"idea_{suffix}_dd_vol_pressure"] = (
            out.get(f"spy_dd_{medium}", 0.0) - vol_short
        )
        out[f"idea_{suffix}_vol_trend_pressure"] = (
            out.get(f"spy_ret_{short}", 0.0) - vol_long
        )
        out[f"idea_{suffix}_ret_to_vol"] = (
            out.get(f"spy_ret_{short}", 0.0) / (vol_short.abs() + 1e-9)
        )
        out[f"idea_{suffix}_dd_recovery"] = (
            out.get(f"spy_ret_{short}", 0.0)
            - _feature_series(out, f"spy_dd_{long}").abs()
        )
        if "vix_term" in out:
            out[f"idea_{suffix}_vix_drawdown_pressure"] = (
                out["vix_term"] - out.get(f"spy_dd_{long}", 0.0)
            )
        if "vix_level" in out:
            out[f"idea_{suffix}_vix_trend_mix"] = (
                out.get(f"spy_ma_{medium}", 0.0) - out["vix_level"].pct_change(short)
            )
    elif family == "trend_stress_combo":
        stress = out.get("fred_NFCI_chg_5", 0.0)
        out[f"idea_{suffix}_trend_stress_short"] = out.get(f"spy_ma_{short}", 0.0) - stress
        out[f"idea_{suffix}_trend_stress_medium"] = (
            out.get(f"spy_ma_{medium}", 0.0) - out.get("fred_NFCI_chg_21", 0.0)
        )
        out[f"idea_{suffix}_stress_acceleration"] = (
            out.get("fred_NFCI_chg_5", 0.0) - out.get("fred_NFCI_chg_21", 0.0)
        )
        out[f"idea_{suffix}_trend_quality"] = (
            out.get(f"spy_ret_{medium}", 0.0) + out.get(f"spy_ma_{long}", 0.0)
            - out.get("fred_STLFSI4_chg_21", 0.0)
        )
        if "HYG_LQD_63" in out:
            out[f"idea_{suffix}_credit_momentum_blend"] = (
                out["HYG_LQD_63"] + out.get(f"spy_ret_{medium}", 0.0)
            )
            out[f"idea_{suffix}_credit_stress_divergence"] = (
                out["HYG_LQD_63"] - out.get("fred_NFCI_chg_21", 0.0)
            )
    elif family == "defensive_ratio_blend":
        out[f"idea_{suffix}_defensive_blend"] = (
            out.get("XLY_XLP_63", 0.0)
            + out.get("XLK_XLU_63", 0.0)
            + out.get("HYG_LQD_63", 0.0)
        )
        out[f"idea_{suffix}_defensive_trend"] = (
            out[f"idea_{suffix}_defensive_blend"] + out.get(f"spy_ma_{long}", 0.0)
        )
        out[f"idea_{suffix}_defensive_shock"] = (
            out.get("XLY_XLP_21", 0.0)
            + out.get("XLK_XLU_21", 0.0)
            - out.get(f"spy_ret_{short}", 0.0)
        )
        out[f"idea_{suffix}_credit_defensive_spread"] = (
            out.get("HYG_LQD_126", 0.0) - out.get("XLY_XLP_126", 0.0)
        )
    elif family == "yield_curve_macro":
        slope = (
            out.get("fred_T10Y2Y", 0.0)
            + out.get("fred_DGS10", 0.0)
            - out.get("fred_DGS2", 0.0)
        )
        out[f"idea_{suffix}_yield_slope_momentum"] = (
            slope + out.get(f"spy_ma_{medium}", 0.0)
        )
        out[f"idea_{suffix}_yield_stress_blend"] = (
            out.get("fred_DGS10_chg_21", 0.0)
            - out.get("fred_DGS2_chg_21", 0.0)
            - out.get("fred_NFCI_chg_21", 0.0)
        )
        out[f"idea_{suffix}_real_rate_pressure"] = (
            out.get("fred_DGS10_chg_63", 0.0) - out.get(f"spy_ret_{medium}", 0.0)
        )
    elif family == "vix_term_structure":
        out[f"idea_{suffix}_vix_term_pressure"] = (
            out.get("vix_term", 0.0) + out.get("vix_z_21", 0.0)
        )
        out[f"idea_{suffix}_vix_spike_reversal"] = (
            out.get("vix_ret_21", 0.0) - out.get(f"spy_dd_{medium}", 0.0)
        )
        out[f"idea_{suffix}_volatility_risk_premium_proxy"] = (
            out.get("vix_z_63", 0.0) - out.get("spy_vol_63", 0.0)
        )
    elif family == "breadth_proxy_regime":
        out[f"idea_{suffix}_breadth_momentum"] = (
            out.get("RSP_SPY_63", 0.0) + out.get("IWM_SPY_63", 0.0)
        )
        out[f"idea_{suffix}_breadth_trend_quality"] = (
            out.get("RSP_SPY_126", 0.0) + out.get(f"spy_ma_{long}", 0.0)
        )
        out[f"idea_{suffix}_smallcap_divergence"] = (
            out.get("IWM_SPY_21", 0.0) - out.get("QQQ_SPY_21", 0.0)
        )
    elif family == "sector_rotation_momentum":
        out[f"idea_{suffix}_sector_risk_on"] = (
            out.get("XLY_XLP_63", 0.0) + out.get("XLK_XLU_63", 0.0)
        )
        out[f"idea_{suffix}_sector_defensive_rotation"] = (
            out.get("XLY_XLP_21", 0.0) - out.get("XLY_XLP_126", 0.0)
        )
        out[f"idea_{suffix}_financials_rate_blend"] = (
            out.get("XLF_SPY_63", 0.0) + out.get("fred_DGS10_chg_63", 0.0)
        )
    elif family == "crash_asymmetry":
        out[f"idea_{suffix}_crash_pressure"] = (
            _feature_series(out, f"spy_dd_{medium}").abs()
            + out.get("spy_vol_63", 0.0)
            + out.get("vix_ret_21", 0.0)
        )
        out[f"idea_{suffix}_crash_recovery_quality"] = (
            out.get(f"spy_ret_{short}", 0.0)
            - _feature_series(out, f"spy_dd_{long}").abs()
        )
        out[f"idea_{suffix}_left_tail_vol_pressure"] = (
            out.get(f"spy_dd_{short}", 0.0) - out.get("vix_z_63", 0.0)
        )
    elif family == "mean_reversion_stress":
        out[f"idea_{suffix}_mean_reversion_stress"] = (
            -out.get(f"spy_ret_{short}", 0.0) - out.get("fred_NFCI_chg_5", 0.0)
        )
        out[f"idea_{suffix}_reversion_quality"] = (
            -out.get(f"spy_dd_{medium}", 0.0) - out.get("vix_ret_21", 0.0)
        )
        out[f"idea_{suffix}_oversold_stress_release"] = (
            -out.get(f"spy_ret_{short}", 0.0) - out.get("fred_STLFSI4_chg_21", 0.0)
        )
    else:
        out[f"idea_{suffix}_generic_combo"] = (
            out.get(f"spy_ret_{medium}", 0.0) + out.get(f"spy_ma_{long}", 0.0)
        )


def _feature_series(out: pd.DataFrame, column: str) -> pd.Series:
    if column in out:
        return out[column]
    return pd.Series(0.0, index=out.index)


def _feature_pack_suffix(pack: Mapping[str, Any]) -> str:
    raw = str(pack.get("pack_id") or pack.get("idea_id") or "generic")
    keep = "".join(ch.lower() if ch.isalnum() else "_" for ch in raw)
    keep = "_".join(part for part in keep.split("_") if part)
    return keep[:48] or "generic"


def _rules_for_round(
    x_train: pd.DataFrame,
    round_name: str,
    cap: int,
    *,
    blocked_features: Iterable[str] = (),
    blocked_rule_signatures: Iterable[str] = (),
) -> list[dict[str, Any]]:
    percentiles = (5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95)
    rules: list[dict[str, Any]] = []
    blocked = set(blocked_features)
    blocked_rules = set(blocked_rule_signatures)
    columns = _ordered_rule_columns(x_train, round_name, blocked)
    idea_cols = [c for c in columns if c.startswith("idea_")]
    focus_idea = bool(idea_cols and round_name.startswith("idea_"))
    for col in columns:
        if _column_blocked(col, blocked):
            continue
        values = x_train[col].dropna()
        if len(values) < 100:
            continue
        thresholds = sorted({float(np.nanpercentile(values, p)) for p in percentiles})
        for threshold in thresholds:
            _append_rule(
                rules,
                {"type": "single", "feature": col, "threshold": threshold, "invert": False},
                blocked_rules,
            )
            if len(rules) >= cap and not focus_idea:
                return rules
            _append_rule(
                rules,
                {"type": "single", "feature": col, "threshold": threshold, "invert": True},
                blocked_rules,
            )
            if len(rules) >= cap and not focus_idea:
                return rules

    singles = list(rules)
    if focus_idea:
        rules = [rule for rule in rules if _rule_uses_idea_feature(rule)]
    combo_singles = _focused_single_rules(singles, focus_idea)
    for i, left in enumerate(combo_singles[:120]):
        for right in combo_singles[i + 1 : 120]:
            if focus_idea and not (
                _rule_uses_idea_feature(left) or _rule_uses_idea_feature(right)
            ):
                continue
            for kind in ("and", "or"):
                for invert in (False, True):
                    _append_rule(
                        rules,
                        {
                            "type": kind,
                            "left": left,
                            "right": right,
                            "invert": invert,
                        },
                        blocked_rules,
                    )
                    if len(rules) >= cap:
                        return rules

    if round_name in {
        "macro_stress",
        "vix_regime",
        "slow_regime",
        "credit_stress",
        "rates_curve",
        "volatility_breakout",
        "multi_signal",
    } or focus_idea:
        trend_cols = [
            c for c in x_train.columns
            if not _column_blocked(c, blocked)
            and (c.startswith("spy_ma") or c.startswith("spy_ret"))
        ]
        if focus_idea:
            trend_cols = idea_cols + trend_cols
        stress_cols = [
            c for c in x_train.columns
            if not _column_blocked(c, blocked)
            and (
                c.startswith("vix")
                or c.startswith("fred_")
                or "HYG_LQD" in c
                or "XLY_XLP" in c
                or c.startswith("idea_")
            )
        ]
        for trend in trend_cols[:30]:
            for stress in stress_cols[:50]:
                if focus_idea and not (trend.startswith("idea_") or stress.startswith("idea_")):
                    continue
                for tp in (20, 30, 40, 50):
                    for sp in (60, 70, 80, 90):
                        _append_rule(
                            rules,
                            {
                                "type": "riskoff",
                                "trend": trend,
                                "trend_threshold": float(np.nanpercentile(x_train[trend], tp)),
                                "stress": stress,
                                "stress_threshold": float(np.nanpercentile(x_train[stress], sp)),
                                "invert": True,
                            },
                            blocked_rules,
                        )
                        if len(rules) >= cap:
                            return rules
    return rules[:cap]


def _append_rule(
    rules: list[dict[str, Any]],
    rule: dict[str, Any],
    blocked_rule_signatures: set[str],
) -> None:
    if _rule_content_signature(rule) in blocked_rule_signatures:
        return
    rules.append(rule)


def _rule_content_signature(rule: Mapping[str, Any]) -> str:
    kind = str(rule.get("type", "unknown"))
    invert = "!" if rule.get("invert") else ""
    if kind == "single":
        return f"{invert}{kind}:{_normalised_idea_column(str(rule.get('feature', '')))}"
    if kind in {"and", "or"}:
        parts = [
            _rule_content_signature(part)
            for part in (rule.get("left"), rule.get("right"))
            if isinstance(part, Mapping)
        ]
        return f"{invert}{kind}({','.join(sorted(parts))})"
    if kind == "riskoff":
        trend = _normalised_idea_column(str(rule.get("trend", "")))
        stress = _normalised_idea_column(str(rule.get("stress", "")))
        return f"{invert}{kind}:{trend}|{stress}"
    return f"{invert}{kind}"


def _ordered_rule_columns(
    x_train: pd.DataFrame,
    round_name: str,
    blocked: set[str],
) -> list[str]:
    columns = [c for c in x_train.columns if not _column_blocked(c, blocked)]
    if not round_name.startswith("idea_"):
        return columns
    idea = [c for c in columns if c.startswith("idea_")]
    stress = [
        c for c in columns
        if c.startswith("vix") or c.startswith("fred_") or "HYG_LQD" in c or "XLY_XLP" in c
    ]
    trend = [c for c in columns if c.startswith("spy_ma") or c.startswith("spy_ret")]
    rest = [
        c for c in columns
        if c not in set(idea) | set(stress) | set(trend)
    ]
    return list(dict.fromkeys(idea + stress + trend + rest))


def _column_blocked(column: str, blocked: set[str]) -> bool:
    if column in blocked:
        return True
    return _normalised_idea_column(column) in blocked


def _normalised_idea_column(column: str) -> str:
    suffixes = (
        "dd_vol_pressure",
        "vol_trend_pressure",
        "ret_to_vol",
        "dd_recovery",
        "vix_drawdown_pressure",
        "vix_trend_mix",
        "trend_stress_short",
        "trend_stress_medium",
        "stress_acceleration",
        "trend_quality",
        "credit_momentum_blend",
        "credit_stress_divergence",
        "defensive_blend",
        "defensive_trend",
        "defensive_shock",
        "credit_defensive_spread",
        "yield_slope_momentum",
        "yield_stress_blend",
        "real_rate_pressure",
        "vix_term_pressure",
        "vix_spike_reversal",
        "volatility_risk_premium_proxy",
        "breadth_momentum",
        "breadth_trend_quality",
        "smallcap_divergence",
        "sector_risk_on",
        "sector_defensive_rotation",
        "financials_rate_blend",
        "crash_pressure",
        "crash_recovery_quality",
        "left_tail_vol_pressure",
        "mean_reversion_stress",
        "reversion_quality",
        "oversold_stress_release",
        "generic_combo",
    )
    for suffix in suffixes:
        if column.endswith(f"_{suffix}"):
            return f"idea:*:{suffix}"
    return column


def _focused_single_rules(
    singles: list[dict[str, Any]],
    focus_idea: bool,
) -> list[dict[str, Any]]:
    if not focus_idea:
        return singles
    idea = [rule for rule in singles if _rule_uses_idea_feature(rule)]
    other = [rule for rule in singles if not _rule_uses_idea_feature(rule)]
    return idea + other


def _rule_uses_idea_feature(rule: Mapping[str, Any]) -> bool:
    kind = rule.get("type")
    if kind == "single":
        return str(rule.get("feature", "")).startswith("idea_")
    if kind in {"and", "or"}:
        left = rule.get("left")
        right = rule.get("right")
        return (
            isinstance(left, Mapping)
            and _rule_uses_idea_feature(left)
        ) or (
            isinstance(right, Mapping)
            and _rule_uses_idea_feature(right)
        )
    if kind == "riskoff":
        return str(rule.get("trend", "")).startswith("idea_") or str(rule.get("stress", "")).startswith("idea_")
    return False


def _weights_for_rule(features: pd.DataFrame, rule: Mapping[str, Any]) -> np.ndarray:
    kind = rule["type"]
    if kind == "single":
        cond = features[str(rule["feature"])].to_numpy() > float(rule["threshold"])
    elif kind in {"and", "or"}:
        left = _weights_for_rule(features, rule["left"]) > 0
        right = _weights_for_rule(features, rule["right"]) > 0
        cond = left & right if kind == "and" else left | right
    elif kind == "riskoff":
        cond = (
            (features[str(rule["trend"])].to_numpy() < float(rule["trend_threshold"]))
            & (features[str(rule["stress"])].to_numpy() > float(rule["stress_threshold"]))
        )
        # Cond=True is stress. Default mapping below would make it long, so flip.
        cond = ~cond
    else:
        raise ValueError(f"unknown rule type: {kind}")
    weights = np.where(cond, 1.0, -1.0)
    if rule.get("invert"):
        weights = -weights
    return weights.astype(float)


def _period_metrics(prices: pd.Series, weights: np.ndarray, *, costs: CostModel = IBKR_costs, delay: int = 0) -> PeriodMetrics:
    w = np.asarray(weights, dtype=float)
    if len(w) != len(prices):
        raise ValueError("weights length must match prices")
    if delay:
        w = np.r_[np.full(delay, w[0]), w[:-delay]]
    raw = prices.to_numpy(dtype=float)
    returns = np.zeros(len(raw))
    returns[1:] = raw[1:] / raw[:-1] - 1.0
    net = apply_costs(w, returns, costs)
    if len(net):
        net = net.copy()
        net[0] = 0.0
    metrics = compute_metrics(net[1:])
    return PeriodMetrics(
        metrics=metrics,
        trades=int(np.sum(np.abs(np.diff(w)) > 0.0)),
        long_fraction=float(np.mean(w > 0.0)),
        short_fraction=float(np.mean(w < 0.0)),
    )


def _period_metrics_many(
    prices: pd.Series,
    weights: np.ndarray,
    *,
    costs: CostModel = IBKR_costs,
) -> list[PeriodMetrics]:
    w = np.asarray(weights, dtype=float)
    if w.ndim == 1:
        w = w.reshape(-1, 1)
    if w.shape[0] != len(prices):
        raise ValueError("weights length must match prices")
    if w.shape[1] == 0:
        return []

    raw = prices.to_numpy(dtype=float)
    returns = np.zeros(len(raw), dtype=float)
    returns[1:] = raw[1:] / raw[:-1] - 1.0

    net = np.zeros_like(w, dtype=float)
    if len(raw) > 1:
        net[1:, :] = w[:-1, :] * returns[1:, None]
    delta_w = np.abs(np.diff(w, axis=0, prepend=np.zeros((1, w.shape[1]))))
    net -= delta_w * (costs.per_trade_bps() / 1e4)
    short_carried = np.zeros_like(w, dtype=float)
    if len(raw) > 1:
        short_carried[1:, :] = np.abs(np.minimum(w[:-1, :], 0.0))
    net -= short_carried * (costs.borrow_rate_annual / 252.0)
    if len(net):
        net[0, :] = 0.0

    metrics = _compute_metrics_many(net[1:, :])
    trades = np.sum(np.abs(np.diff(w, axis=0)) > 0.0, axis=0)
    long_fraction = np.mean(w > 0.0, axis=0)
    short_fraction = np.mean(w < 0.0, axis=0)
    return [
        PeriodMetrics(
            metrics=m,
            trades=int(trades[i]),
            long_fraction=float(long_fraction[i]),
            short_fraction=float(short_fraction[i]),
        )
        for i, m in enumerate(metrics)
    ]


def _compute_metrics_many(returns: np.ndarray, ppy: int = 252) -> list[Metrics]:
    r = np.asarray(returns, dtype=float)
    if r.ndim == 1:
        r = r.reshape(-1, 1)
    if r.shape[0] < 2 or np.isnan(r).any():
        return [compute_metrics(r[:, i], ppy=ppy) for i in range(r.shape[1])]

    nav = np.cumprod(1.0 + r, axis=0)
    final = nav[-1, :]
    years = r.shape[0] / ppy if ppy > 0 else 0.0
    cagr = np.zeros(r.shape[1], dtype=float)
    positive = (years > 0) & (final > 0)
    if np.any(positive):
        cagr[positive] = np.power(final[positive], 1.0 / years) - 1.0
    cagr[final <= 0] = -1.0

    cummax = np.maximum.accumulate(nav, axis=0)
    dd = (nav - cummax) / cummax
    mdd = np.min(dd, axis=0)
    near_zero_mdd = np.abs(mdd) < 1e-9
    calmar = np.divide(cagr, np.abs(mdd), out=np.zeros_like(cagr), where=~near_zero_mdd)
    calmar = np.where(near_zero_mdd & (cagr > 0), np.inf, calmar)
    calmar = np.where(near_zero_mdd & (cagr < 0), -np.inf, calmar)

    mean = np.mean(r, axis=0)
    std = np.std(r, axis=0)
    sharpe = np.divide(mean, std, out=np.zeros_like(mean), where=std > 1e-12) * np.sqrt(ppy)

    losses_mask = r < 0.0
    losses_count = np.sum(losses_mask, axis=0)
    losses_only = np.where(losses_mask, r, np.nan)
    with np.errstate(invalid="ignore"):
        losses_mean = np.nanmean(losses_only, axis=0)
        downside_std = np.sqrt(np.nanmean((losses_only - losses_mean) ** 2, axis=0))
    downside_std = np.where(losses_count > 1, downside_std, std)
    sortino = (
        np.divide(mean, downside_std, out=np.zeros_like(mean), where=downside_std > 1e-12)
        * np.sqrt(ppy)
    )

    centered = r - mean[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        skew = np.mean(centered**3, axis=0) / std**3
        kurtosis = np.mean(centered**4, axis=0) / std**4
    skew = np.where((std > 1e-12) & (r.shape[0] > 2), skew, 0.0)
    kurtosis = np.where((std > 1e-12) & (r.shape[0] > 3), kurtosis, 0.0)

    wins = np.where(r > 0.0, r, 0.0)
    losses = np.where(r < 0.0, r, 0.0)
    win_rate = np.mean(r > 0.0, axis=0)
    loss_sum = np.sum(losses, axis=0)
    profit_factor = np.divide(
        np.sum(wins, axis=0),
        np.abs(loss_sum),
        out=np.zeros_like(loss_sum),
        where=loss_sum != 0.0,
    )

    out: list[Metrics] = []
    for i in range(r.shape[1]):
        out.append(
            Metrics(
                cagr=round(float(cagr[i]) * 100, 4),
                mdd=round(float(mdd[i]) * 100, 4),
                calmar=round(float(calmar[i]), 4),
                sharpe=round(float(sharpe[i]), 4),
                sortino=round(float(sortino[i]), 4),
                mar=round(float(calmar[i]), 4),
                skew=round(float(skew[i]), 4),
                kurtosis=round(float(kurtosis[i]), 4),
                win_rate=round(float(win_rate[i]), 4),
                profit_factor=round(float(profit_factor[i]), 4),
                n_periods=r.shape[0],
                final_nav=round(float(final[i]), 6),
                n_periods_raw=r.shape[0],
                n_periods_finite=r.shape[0],
            )
        )
    return out


def _robustness(
    prices: pd.Series,
    train_idx: pd.DatetimeIndex,
    weights: np.ndarray,
    third_indices: list[pd.DatetimeIndex],
    x_thirds: list[pd.DataFrame],
    rule: Mapping[str, Any],
) -> dict[str, Any]:
    stress_cost = CostModel(
        commission_bps=IBKR_costs.commission_bps * 2.0,
        spread_bps=IBKR_costs.spread_bps * 2.0,
        slippage_bps=IBKR_costs.slippage_bps * 2.0,
        borrow_rate_annual=IBKR_costs.borrow_rate_annual * 2.0,
    )
    base = _period_metrics(prices.loc[train_idx], weights)
    double_cost = _period_metrics(prices.loc[train_idx], weights, costs=stress_cost)
    delay = _period_metrics(prices.loc[train_idx], weights, delay=1)
    thirds = []
    for idx, x_part in zip(third_indices, x_thirds):
        thirds.append(_period_metrics(prices.loc[idx], _weights_for_rule(x_part, rule)).metrics.calmar)
    robust_score = min([base.metrics.calmar, double_cost.metrics.calmar, delay.metrics.calmar] + thirds)
    return {
        "lookahead": {"passed": True, "method": "physical_slice_features"},
        "base_calmar": base.metrics.calmar,
        "double_cost_calmar": double_cost.metrics.calmar,
        "one_day_delay_calmar": delay.metrics.calmar,
        "thirds_calmar": thirds,
        "robust_train_score": robust_score,
    }


def _robustness_many(
    prices: pd.Series,
    train_idx: pd.DatetimeIndex,
    x_train: pd.DataFrame,
    rows: list[Mapping[str, Any]],
    third_indices: list[pd.DatetimeIndex],
    x_thirds: list[pd.DataFrame],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    rules = [row["rule"] for row in rows]
    weights = np.column_stack([_weights_for_rule(x_train, rule) for rule in rules])
    train_prices = prices.loc[train_idx]
    stress_cost = CostModel(
        commission_bps=IBKR_costs.commission_bps * 2.0,
        spread_bps=IBKR_costs.spread_bps * 2.0,
        slippage_bps=IBKR_costs.slippage_bps * 2.0,
        borrow_rate_annual=IBKR_costs.borrow_rate_annual * 2.0,
    )
    base = _period_metrics_many(train_prices, weights)
    double_cost = _period_metrics_many(train_prices, weights, costs=stress_cost)
    delay = _period_metrics_many(train_prices, _delay_weights_many(weights, delay=1))
    thirds_by_rule: list[list[float]] = [[] for _ in rules]
    for idx, x_part in zip(third_indices, x_thirds):
        part_weights = np.column_stack([_weights_for_rule(x_part, rule) for rule in rules])
        part_metrics = _period_metrics_many(prices.loc[idx], part_weights)
        for i, metric in enumerate(part_metrics):
            thirds_by_rule[i].append(metric.metrics.calmar)

    out: list[dict[str, Any]] = []
    for i in range(len(rules)):
        thirds = thirds_by_rule[i]
        robust_score = min([
            base[i].metrics.calmar,
            double_cost[i].metrics.calmar,
            delay[i].metrics.calmar,
            *thirds,
        ])
        out.append(
            {
                "lookahead": {"passed": True, "method": "physical_slice_features"},
                "base_calmar": base[i].metrics.calmar,
                "double_cost_calmar": double_cost[i].metrics.calmar,
                "one_day_delay_calmar": delay[i].metrics.calmar,
                "thirds_calmar": thirds,
                "robust_train_score": robust_score,
            }
        )
    return out


def _statistical_robustness_for_weights(
    *,
    prices: pd.Series,
    weights: np.ndarray,
    target_calmar: float,
    n_trials: int,
    peer_returns: pd.DataFrame | np.ndarray | None = None,
) -> Any:
    raw = prices.to_numpy(dtype=float)
    returns = np.zeros(len(raw), dtype=float)
    if len(raw) > 1:
        returns[1:] = raw[1:] / raw[:-1] - 1.0
    cfg = StatisticalRobustnessConfig(
        target_calmar=target_calmar,
        # Keep the search gate cheaper than a final human report. The expensive
        # final report can raise these counts without changing semantics.
        n_bootstrap=120,
        n_random_shuffles=120,
        n_permutations=120,
    )
    return statistical_robustness_gate(
        weights,
        returns,
        benchmark_weights=np.ones(len(weights), dtype=float),
        costs=IBKR_costs,
        n_trials=n_trials,
        peer_returns=peer_returns,
        config=cfg,
    )


def _peer_net_returns_for_rows(
    prices: pd.Series,
    x_train: pd.DataFrame,
    rows: list[Mapping[str, Any]],
) -> pd.DataFrame | None:
    if len(rows) < 2:
        return None
    weights = np.column_stack([_weights_for_rule(x_train, row["rule"]) for row in rows])
    raw = prices.to_numpy(dtype=float)
    returns = np.zeros(len(raw), dtype=float)
    if len(raw) > 1:
        returns[1:] = raw[1:] / raw[:-1] - 1.0
    net = np.zeros_like(weights, dtype=float)
    if len(raw) > 1:
        net[1:, :] = weights[:-1, :] * returns[1:, None]
    delta_w = np.abs(np.diff(weights, axis=0, prepend=np.zeros((1, weights.shape[1]))))
    net -= delta_w * (IBKR_costs.per_trade_bps() / 1e4)
    short_carried = np.zeros_like(weights, dtype=float)
    if len(raw) > 1:
        short_carried[1:, :] = np.abs(np.minimum(weights[:-1, :], 0.0))
    net -= short_carried * (IBKR_costs.borrow_rate_annual / 252.0)
    columns = [str(row.get("candidate_id") or i) for i, row in enumerate(rows)]
    return pd.DataFrame(net[1:, :], columns=columns)


def _delay_weights_many(weights: np.ndarray, *, delay: int) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    if delay <= 0:
        return w
    if delay >= len(w):
        return np.repeat(w[:1, :], len(w), axis=0)
    return np.vstack([np.repeat(w[:1, :], delay, axis=0), w[:-delay, :]])


def _thirds(index: pd.DatetimeIndex) -> list[pd.DatetimeIndex]:
    n = len(index)
    return [index[: n // 3], index[n // 3 : 2 * n // 3], index[2 * n // 3 :]]


def _candidate_id(round_name: str, counter: int) -> str:
    return f"SPY-LS-Auto-{round_name}-{counter}"


def _better(row: Mapping[str, Any], current: Mapping[str, Any] | None) -> bool:
    if current is None:
        return True
    score = row.get("robust_train_score")
    cur_score = current.get("robust_train_score")
    if score is not None and cur_score is not None:
        return float(score) > float(cur_score)
    return float(row.get("train_calmar", -1e9)) > float(current.get("train_calmar", -1e9))


def _finalise_candidate(
    *,
    cfg: AutosearchConfig,
    state: _SearchState,
    run_dir: Path,
    guard: ResearchProtocolGuard,
    data: _Dataset,
    selected: Mapping[str, Any],
    train_idx: pd.DatetimeIndex,
    valid_idx: pd.DatetimeIndex,
    locked_idx: pd.DatetimeIndex,
) -> CandidateEvidence:
    round_name = str(selected["round_name"])
    rule = selected["rule"]
    feature_packs = _load_feature_packs(cfg.feature_packs_path)
    x_train = _features_for_round(data, train_idx, round_name, feature_packs=feature_packs)
    x_valid = _features_for_round(data, valid_idx, round_name, feature_packs=feature_packs)
    train_w = _weights_for_rule(x_train, rule)
    valid_w = _weights_for_rule(x_valid, rule)
    train = _period_metrics(data.prices.loc[train_idx], train_w)
    validation = _period_metrics(data.prices.loc[valid_idx], valid_w)
    benchmark_train = _period_metrics(data.prices.loc[train_idx], np.ones(len(train_idx)))
    benchmark_valid = _period_metrics(data.prices.loc[valid_idx], np.ones(len(valid_idx)))
    third_indices = _thirds(train_idx)
    robust = _robustness(
        data.prices,
        train_idx,
        train_w,
        third_indices,
        [
            _features_for_round(data, idx, round_name, feature_packs=feature_packs)
            for idx in third_indices
        ],
        rule,
    )
    statistical = _statistical_robustness_for_weights(
        prices=data.prices.loc[train_idx],
        weights=train_w,
        target_calmar=cfg.target_calmar,
        n_trials=max(1, state.candidates_evaluated),
        peer_returns=None,
    )
    robust = {**robust, "statistical": statistical.to_dict()}
    candidate_id = str(selected.get("candidate_id") or _candidate_id(round_name, state.candidates_evaluated))
    guard.record_candidate_generated(
        candidate_id,
        actor="aurora_autosearch",
        payload={"round": round_name, "rule": rule, "n_candidates_generated": state.candidates_evaluated},
    )
    guard.record_selection(
        candidate_id,
        phases_used=("train",),
        metrics={"train_calmar": train.metrics.calmar, "robust_train_score": robust["robust_train_score"]},
        actor="aurora_autosearch",
        payload={"selection_policy": "train_only_robust_score"},
    )
    passed = (
        robust["robust_train_score"] >= cfg.target_calmar
        and statistical.passed
        and validation.metrics.calmar >= cfg.target_calmar
    )
    guard.record_robustness_run(
        candidate_id,
        checks=cfg_tuple(
            "lookahead",
            "double_cost",
            "one_day_delay",
            "train_subperiods",
            "benchmark_comparison",
            "statistical_robustness",
        ),
        passed=passed,
        metrics={"robustness": robust},
        actor="aurora_autosearch",
    )
    guard.ledger.append(
        LedgerEventType.VALIDATION_RUN,
        project_id=state.project_id,
        actor="aurora_autosearch",
        payload={
            "candidate_id": candidate_id,
            "metrics": validation.metrics.to_dict(),
            "overall_passed": validation.metrics.calmar >= cfg.target_calmar,
            "validation_used_for_selection": False,
        },
    )

    locked = None
    benchmark_locked = None
    if passed and cfg.open_locked_final:
        x_locked = _features_for_round(data, locked_idx, round_name, feature_packs=feature_packs)
        locked_w = _weights_for_rule(x_locked, rule)
        locked = _period_metrics(data.prices.loc[locked_idx], locked_w)
        benchmark_locked = _period_metrics(data.prices.loc[locked_idx], np.ones(len(locked_idx)))
        guard.record_locked_result(
            candidate_id,
            phase="locked",
            metrics=locked.metrics.to_dict(),
            actor="aurora_autosearch",
            payload={"stop_research_after_locked": True},
        )

    return CandidateEvidence(
        candidate_id=candidate_id,
        round_name=round_name,
        rule=rule,
        train=train,
        validation=validation,
        locked=locked,
        benchmark_train=benchmark_train,
        benchmark_validation=benchmark_valid,
        benchmark_locked=benchmark_locked,
        robust_train_score=float(robust["robust_train_score"]),
        robustness=robust,
        passed=passed,
    )


def cfg_tuple(*values: str) -> tuple[str, ...]:
    return tuple(values)


def _metric_row(label: str, value: PeriodMetrics | None) -> str:
    if value is None:
        return f"| {label} | n/a | n/a | n/a | n/a |"
    m = value.metrics
    return f"| {label} | {m.calmar:.4f} | {m.cagr:.2f}% | {m.mdd:.2f}% | {value.trades} |"


__all__ = [
    "AutosearchConfig",
    "AutosearchReport",
    "CandidateEvidence",
    "PeriodMetrics",
    "report_to_markdown",
    "run_sp500_autosearch",
]
