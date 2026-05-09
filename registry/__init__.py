"""SQLite-backed registry for backtest results + experiment tracker + trade journal.

Public API:
    BacktestRegistry      — main store/query class for backtest results
    RegistryEntry         — dataclass row representation
    store_backtest_result — convenience wrapper around a BacktestResult
    hash_config           — deterministic config hash for dedup
    ExperimentTracker     — MLflow-style tracker for GA/optimization runs
    ExperimentMeta        — metadata for a single experiment
    GenerationLog         — per-generation log for GA runs
    ExperimentResult      — full experiment result (meta + generations + pareto)
    TradeJournal          — live/paper trade log (SQLite)
    JournalEntry          — dataclass row for trade journal
    StrategyVersion       — strategy version dataclass (versioning)
    hash_strategy_code    — deterministic hash of a strategy class
    register              — register a StrategyVersion in a VersionRegistry
"""
from aurora.registry.experiments import (
    ExperimentMeta,
    ExperimentResult,
    ExperimentTracker,
    GenerationLog,
)
from aurora.registry.journal import JournalEntry, TradeJournal
from aurora.registry.registry import (
    BacktestRegistry,
    hash_config,
    RegistryEntry,
    store_backtest_result,
)
from aurora.registry.versioning import (
    hash_strategy_code,
    StrategyVersion,
    VersionRegistry,
)


def register(version: StrategyVersion, registry: "VersionRegistry | None" = None) -> None:
    """Register ``version`` in ``registry`` (creates an in-memory default
    ``VersionRegistry`` when none is supplied).
    """
    reg = registry if registry is not None else VersionRegistry()
    reg.register(version)


__all__ = [
    "BacktestRegistry",
    "ExperimentMeta",
    "ExperimentResult",
    "ExperimentTracker",
    "GenerationLog",
    "JournalEntry",
    "RegistryEntry",
    "StrategyVersion",
    "TradeJournal",
    "VersionRegistry",
    "hash_config",
    "hash_strategy_code",
    "register",
    "store_backtest_result",
]
