"""Internal helpers shared by the factory submodules.

Module-private. Public API stays at ``aurora.research.factory.factory``.
"""
from __future__ import annotations

import importlib
import json
import threading
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.research.factory.outcomes import CandidateRun


# ---------------------------------------------------------------------------
# Optional auditor protocol
# ---------------------------------------------------------------------------


class _AuditorProtocol:
    """Duck-typed contract the factory expects from an auditor.

    The real :class:`AgentAuditor` from P1.B may not exist when this
    module imports. We avoid an import-time dependency by treating the
    auditor as a structural type with a single required method
    ``audit(candidate: CandidateRun) -> AuditorReport`` where the report
    has a ``hard_fail: bool`` attribute and a ``report_hash: str``
    attribute (see the auditor's README). When the report shape is
    different the factory falls back to permissive defaults.
    """

    def audit(self, candidate: CandidateRun) -> Any:  # pragma: no cover - protocol stub
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Backtest hook -- factored so tests can inject a fake without monkey-patching
# the engine module.
# ---------------------------------------------------------------------------


def _default_backtest(
    strategy_class_path: str,
    params: dict[str, Any],
    prices: pd.Series,
) -> dict[str, float]:
    """Run a single-asset backtest at the given prices.

    This is the default closure used by :class:`ResearchFactory` when the
    caller does not inject a custom ``backtest_fn``. It imports the
    strategy class lazily so test code can stub the import path without
    needing the strategy module on disk.
    """
    from aurora.core.engine import run_backtest
    from aurora.core.costs import IBKR_costs
    cls = _import_path(strategy_class_path)
    strat = cls(**params)
    res = run_backtest(prices, strat.signals, costs=IBKR_costs)
    return {
        "calmar": float(res.calmar),
        "sharpe": float(res.sharpe),
        "cagr": float(res.cagr),
        "mdd": float(res.mdd),
    }


def _default_walk_forward(
    strategy_class_path: str,
    params: dict[str, Any],
    prices: pd.Series,
) -> dict[str, Any]:
    """Run walk-forward on the given prices.

    Returns a dict with per-fold sharpes plus aggregate stats. The
    factory's WF gating uses ``is_sharpe`` (mean of IS sharpes per fold,
    or just the IS metric the caller already has) and ``oos_sharpe``
    (mean of fold OOS sharpes) to compute degradation.
    """
    from aurora.validation.walk_forward import walk_forward
    from aurora.core.costs import IBKR_costs
    cls = _import_path(strategy_class_path)

    def factory(_is_prices=None):
        return cls(**params)

    res = walk_forward(
        factory,
        prices,
        mode="rolling",
        n_windows=4,
        oos_pct=0.20,
        costs=IBKR_costs,
        criterion="sharpe_positive",
    )
    sharpes = [
        float(w.get("sharpe", 0.0)) for w in res.windows
        if "sharpe" in w
    ]
    if sharpes:
        import statistics
        mean_s = statistics.mean(sharpes)
        std_s = statistics.pstdev(sharpes) if len(sharpes) > 1 else 0.0
    else:
        mean_s = 0.0
        std_s = 0.0
    return {
        "n_pass": int(res.n_pass),
        "n_total": int(res.n_total),
        "fold_sharpes": sharpes,
        "oos_sharpe_mean": mean_s,
        "oos_sharpe_std": std_s,
        "windows": res.windows,
    }


def _import_path(qualified: str) -> Any:
    """Import a fully-qualified ``pkg.mod.Class`` path."""
    if "." not in qualified:
        raise ImportError(
            f"strategy_class={qualified!r} is not a fully-qualified path"
        )
    mod_path, _, attr = qualified.rpartition(".")
    mod = importlib.import_module(mod_path)
    if not hasattr(mod, attr):
        raise ImportError(f"{mod_path} has no attribute {attr!r}")
    return getattr(mod, attr)


# ---------------------------------------------------------------------------
# JSONL append helpers
# ---------------------------------------------------------------------------


_FILE_LOCK = threading.Lock()


def _atomic_jsonl_append(path: Path, record: dict) -> None:
    """Append ``record`` to ``path`` as one JSON-lines entry.

    Serializes writes via a process-wide lock so concurrent submissions do
    not interleave bytes. Creates the parent directory on demand so the
    factory can be used in a fresh repo without manual setup.
    """
    path = Path(path)
    parent = path.parent
    if str(parent) and parent != Path("."):
        parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str)
    with _FILE_LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    """Read all JSON-lines records from ``path``.

    Returns ``[]`` if the file does not exist. Skips malformed lines so a
    half-written archive does not crash a CLI list operation.
    """
    path = Path(path)
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
