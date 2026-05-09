"""TriageEngine -- vectorized screening backend for thousands of variants.

Goal
----
Triage a large variant batch (10k+ proposals) at *very* low ceremony
cost. Anything that survives triage thresholds is **only** flagged as
"worth running on the official engine" -- the triage engine NEVER
produces a result that can be promoted on its own. Promotion goes
through :class:`aurora.core.engine.run_backtest` (or the official
runner the caller passes to :meth:`TriageEngine.promote_to_official`),
which carries the full QuantForge ceremony (costs, slippage, snapshots,
OOSGuard).

Tier guard
----------
The engine refuses to operate on data crossing the OOS_LOCKED or
FORWARD tier boundaries. ``TriageConfig.triage_tier_only`` is the only
input field that can request a tier; values other than ``IS_TRAIN``,
``IS_VALID``, or ``OOS_DEV`` raise loudly at construction time.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
import warnings
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from aurora.core.protocol_policy import ProtocolPolicy
from aurora.triage.variants import StrategyVariant
from aurora.triage.vectorized import (
    compute_metrics_batch,
    compute_pnl_batch,
    compute_signals_batch,
)

_log = logging.getLogger(__name__)

# Tiers the engine is willing to read. OOS_LOCKED / FORWARD live behind
# the formal-validation ceremony and are off-limits for triage by design.
_ALLOWED_TIERS: frozenset[str] = frozenset({"IS_TRAIN", "IS_VALID", "OOS_DEV"})


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class TriageConfig:
    """Runtime knobs for :class:`TriageEngine`.

    All defaults are intentionally permissive on the threshold side -- the
    triage layer's job is to *eliminate the obvious junk*, not to make
    promotion-grade decisions. Tighten the thresholds at the project
    level if you want a stricter screen, but never lower them below
    sanity floors (a sub-zero Sharpe is rarely worth running on the
    official engine).

    Attributes:
        parallel: when True, batch evaluation uses
            ``concurrent.futures`` to evaluate variants in parallel.
        max_workers: number of worker threads/processes (0 = auto:
            ``os.cpu_count()``).
        cost_bps_simple: flat round-trip cost in basis points (per unit
            turnover) used by the simplified triage cost model.
        slippage_bps_simple: flat slippage bps under the same model.
        min_sharpe_threshold: variants with Sharpe BELOW this threshold
            are rejected.
        max_dd_threshold: variants with max drawdown BELOW (more
            negative than) this threshold are rejected. The threshold
            itself is negative (e.g. ``-0.30`` = "no worse than -30 %").
        min_trades: minimum number of (proxy) trades. Variants below
            this are rejected as statistical noise.
        use_vectorbt: when True and vectorbt is installed, the pnl loop
            routes through :mod:`quantforge.triage.vectorbt_backend`.
            Falls back silently otherwise.
        triage_tier_only: data tier the engine is allowed to read.
            MUST be one of ``IS_TRAIN`` / ``IS_VALID`` / ``OOS_DEV``;
            anything else is rejected at construction.
    """

    parallel: bool = True
    max_workers: int = 0
    cost_bps_simple: float = 5.0
    slippage_bps_simple: float = 1.0
    min_sharpe_threshold: float = 0.5
    max_dd_threshold: float = -0.30
    min_trades: int = 30
    use_vectorbt: bool = False
    triage_tier_only: str = "IS_TRAIN"

    @classmethod
    def from_dict(cls, d: dict) -> "TriageConfig":
        """Build from a YAML/JSON-friendly dict, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        kept = {k: d[k] for k in d if k in known}
        return cls(**kept)

    @classmethod
    def from_yaml(cls, path: str) -> "TriageConfig":
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    def config_hash(self) -> str:
        """Deterministic SHA-256 of the canonical config payload."""
        payload = asdict(self)
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Result + batch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TriageResult:
    """Per-variant triage outcome.

    The ``promotion_token`` is a single-use UUID handed out by
    :class:`TriageEngine` for promising variants. It is stripped on
    :meth:`TriageEngine.promote_to_official` so a caller cannot accidentally
    re-promote the same triage hit twice.
    """

    variant_id: str
    sharpe: float
    cagr: float
    max_dd: float
    n_trades: int
    win_rate: float
    cost_seconds: float
    promising: bool
    rejection_reason: Optional[str]
    metadata: dict
    promotion_token: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TriageBatch:
    """One batch of triage results.

    Records the policy hash and config hash at run time so an auditor can
    reproduce or invalidate the batch by hashing its inputs.
    """

    batch_id: str
    started_at: pd.Timestamp
    finished_at: pd.Timestamp
    n_variants: int
    n_promising: int
    results: list[TriageResult]
    config_hash: str
    policy_hash: str

    def promotable_ids(self) -> list[str]:
        """Return the ``variant_id`` of every promising result."""
        return [r.variant_id for r in self.results if r.promising]

    def to_parquet(self, path) -> None:
        """Write the batch to a parquet file (one row per result).

        Round-trips through :meth:`from_parquet`. The ``metadata`` dict
        is JSON-encoded to keep parquet schema simple.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for r in self.results:
            rows.append({
                "batch_id": self.batch_id,
                "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat(),
                "config_hash": self.config_hash,
                "policy_hash": self.policy_hash,
                "variant_id": r.variant_id,
                "sharpe": r.sharpe,
                "cagr": r.cagr,
                "max_dd": r.max_dd,
                "n_trades": r.n_trades,
                "win_rate": r.win_rate,
                "cost_seconds": r.cost_seconds,
                "promising": r.promising,
                "rejection_reason": r.rejection_reason,
                "metadata": json.dumps(r.metadata, default=str),
                "promotion_token": r.promotion_token,
            })
        df = pd.DataFrame(rows)
        df.to_parquet(path, index=False)

    @classmethod
    def from_parquet(cls, path) -> "TriageBatch":
        path = Path(path)
        df = pd.read_parquet(path)
        if df.empty:
            raise ValueError(f"triage batch parquet at {path!r} is empty")
        head = df.iloc[0]
        results: list[TriageResult] = []
        for _, row in df.iterrows():
            md_raw = row.get("metadata")
            try:
                md = json.loads(md_raw) if md_raw else {}
            except (TypeError, ValueError):
                md = {}
            tok = row.get("promotion_token")
            if isinstance(tok, float) and np.isnan(tok):
                tok = None
            elif tok == "" or tok is None:
                tok = None
            else:
                tok = str(tok)
            rr = row.get("rejection_reason")
            if isinstance(rr, float) and np.isnan(rr):
                rr = None
            elif rr == "" or rr is None:
                rr = None
            else:
                rr = str(rr)
            results.append(TriageResult(
                variant_id=str(row["variant_id"]),
                sharpe=float(row["sharpe"]),
                cagr=float(row["cagr"]),
                max_dd=float(row["max_dd"]),
                n_trades=int(row["n_trades"]),
                win_rate=float(row["win_rate"]),
                cost_seconds=float(row["cost_seconds"]),
                promising=bool(row["promising"]),
                rejection_reason=rr,
                metadata=md,
                promotion_token=tok,
            ))
        return cls(
            batch_id=str(head["batch_id"]),
            started_at=pd.Timestamp(head["started_at"]),
            finished_at=pd.Timestamp(head["finished_at"]),
            n_variants=len(results),
            n_promising=int(sum(1 for r in results if r.promising)),
            results=results,
            config_hash=str(head["config_hash"]),
            policy_hash=str(head["policy_hash"]),
        )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class TriageEngine:
    """Vectorized triage backend.

    See module docstring for the design contract: triage produces
    "worth running on the official engine" verdicts only.
    """

    def __init__(
        self,
        config: TriageConfig,
        policy: ProtocolPolicy,
    ) -> None:
        if not isinstance(config, TriageConfig):
            raise TypeError(
                f"config must be TriageConfig, got {type(config).__name__}"
            )
        if not isinstance(policy, ProtocolPolicy):
            raise TypeError(
                f"policy must be ProtocolPolicy, got {type(policy).__name__}"
            )
        # Tier guard: triage NEVER reads OOS_LOCKED or FORWARD.
        tier_norm = (config.triage_tier_only or "IS_TRAIN").upper()
        if tier_norm not in _ALLOWED_TIERS:
            raise RuntimeError(
                f"TriageEngine refuses tier {config.triage_tier_only!r}; "
                f"allowed tiers are {sorted(_ALLOWED_TIERS)}. "
                "OOS_LOCKED / FORWARD live behind the lockbox ceremony."
            )
        self.config = replace(config, triage_tier_only=tier_norm)
        self.policy = policy

        # vectorbt routing: emit a one-shot warning if asked but missing.
        if self.config.use_vectorbt:
            from aurora.triage import vectorbt_backend
            if not vectorbt_backend.is_available():
                warnings.warn(
                    "TriageConfig.use_vectorbt=True but vectorbt is not "
                    "installed; falling back to the internal numpy backend.",
                    UserWarning,
                    stacklevel=2,
                )

        # Token bookkeeping: variant_id -> token (one-shot).
        self._tokens: dict[str, str] = {}

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    @property
    def allowed_tiers(self) -> frozenset[str]:
        return _ALLOWED_TIERS

    # ------------------------------------------------------------------
    # batch entry point
    # ------------------------------------------------------------------

    def triage_batch(
        self,
        prices: pd.DataFrame,
        variants: Sequence[StrategyVariant],
    ) -> TriageBatch:
        """Score every variant against ``prices`` and bin by threshold.

        Args:
            prices: DataFrame of prices with a DatetimeIndex. Must lie
                strictly within the configured tier window
                (``triage_tier_only``).
            variants: ordered sequence of :class:`StrategyVariant`. The
                engine evaluates them in input order; the same input
                order is preserved on the returned ``TriageBatch.results``.

        Returns:
            :class:`TriageBatch` with one :class:`TriageResult` per
            input variant.
        """
        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=prices.name or "asset")
        if not isinstance(prices, pd.DataFrame):
            raise TypeError(
                "prices must be a DataFrame (or Series); "
                f"got {type(prices).__name__}"
            )
        self._guard_tier_window(prices)

        variants = list(variants)
        batch_id = uuid.uuid4().hex[:12]
        started = pd.Timestamp.utcnow().tz_localize(None)
        if not variants:
            finished = pd.Timestamp.utcnow().tz_localize(None)
            return TriageBatch(
                batch_id=batch_id,
                started_at=started,
                finished_at=finished,
                n_variants=0,
                n_promising=0,
                results=[],
                config_hash=self.config.config_hash(),
                policy_hash=self.policy.policy_hash,
            )

        results = self._evaluate_variants(prices, variants)
        finished = pd.Timestamp.utcnow().tz_localize(None)
        n_promising = sum(1 for r in results if r.promising)
        return TriageBatch(
            batch_id=batch_id,
            started_at=started,
            finished_at=finished,
            n_variants=len(results),
            n_promising=n_promising,
            results=results,
            config_hash=self.config.config_hash(),
            policy_hash=self.policy.policy_hash,
        )

    # ------------------------------------------------------------------
    # promotion
    # ------------------------------------------------------------------

    def promote_to_official(
        self,
        result: TriageResult,
        official_runner: Callable[..., Any],
        *,
        prices: Optional[pd.Series] = None,
        **runner_kwargs,
    ) -> Any:
        """Re-run a promising triage hit on the official engine.

        Args:
            result: a :class:`TriageResult` with ``promising=True`` and a
                live ``promotion_token``.
            official_runner: callable invoked with the variant's ctor kwargs
                and ``prices`` (when supplied). The real engine's signature
                is ``run_backtest(prices, signal_fn, **kwargs)``; tests pass
                a stub that returns whatever they want.
            prices: optional price series forwarded to the runner. Tests can
                pass synthetic prices here without re-loading from data.
            **runner_kwargs: extra kwargs forwarded to ``official_runner``.

        Returns:
            Whatever ``official_runner`` returns.

        Raises:
            ValueError: if the result is not promising or the promotion
                token has already been consumed.
        """
        if not result.promising:
            raise ValueError(
                "promote_to_official refused: result is not promising. "
                "Triage results NEVER promote on their own; only promising "
                "candidates are eligible to re-run on the official engine."
            )
        token = result.promotion_token
        if token is None:
            raise ValueError(
                "promote_to_official refused: result has no promotion_token "
                "(likely loaded from a serialized batch where the token was "
                "stripped)."
            )
        stored = self._tokens.get(result.variant_id)
        if stored != token:
            raise ValueError(
                "promote_to_official refused: promotion_token already "
                "consumed (single-use)."
            )
        # Single-use: invalidate immediately so a second call fails fast.
        self._tokens.pop(result.variant_id, None)

        kwargs = dict(runner_kwargs)
        kwargs.setdefault("variant_id", result.variant_id)
        kwargs.setdefault("strategy_class", result.metadata.get("strategy_class"))
        kwargs.setdefault("params", result.metadata.get("params"))
        kwargs.setdefault("data_tier_used", result.metadata.get("data_tier_used"))
        if prices is not None:
            return official_runner(prices, **kwargs)
        return official_runner(**kwargs)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _guard_tier_window(self, prices: pd.DataFrame) -> None:
        """Raise if ``prices`` crosses an OOS_LOCKED / FORWARD boundary.

        Reads the boundary dates from the active ``ProtocolPolicy``. Any
        bar at or after ``OOS_LOCKED.start`` is fatal -- triage never
        runs on locked data, even if the user requested OOS_DEV (which
        is allowed by config but capped here at the lockbox start).
        """
        if prices.empty:
            return
        idx = pd.to_datetime(prices.index)
        last = idx.max()
        tiers = self.policy.tiers
        oos_locked_start = pd.Timestamp(tiers["OOS_LOCKED"].start)
        if last >= oos_locked_start:
            raise RuntimeError(
                f"TriageEngine refuses to operate on data extending to "
                f"{last.date()}: bars at or after "
                f"{oos_locked_start.date()} cross the OOS_LOCKED boundary. "
                "Trim the input to the configured triage tier."
            )

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------

    def _evaluate_variants(
        self,
        prices: pd.DataFrame,
        variants: Sequence[StrategyVariant],
    ) -> list[TriageResult]:
        """Compute signals + pnl + metrics + threshold gating for variants.

        Branches by ``config.parallel`` and the variant batch size: tiny
        batches stay serial (parallelism overhead dominates).
        """
        # Always start by computing signals serially -- strategy ctors can
        # have arbitrary side effects, so we keep them on the main thread.
        # The pnl/metric layer is the part where parallelism actually
        # matters (when n_variants is large).
        n_var = len(variants)
        if not self.config.parallel or n_var <= 4:
            return self._evaluate_serial(prices, variants)
        return self._evaluate_parallel(prices, variants)

    def _evaluate_serial(
        self,
        prices: pd.DataFrame,
        variants: Sequence[StrategyVariant],
    ) -> list[TriageResult]:
        t0 = time.perf_counter()
        signals = compute_signals_batch(prices, variants)
        if self.config.use_vectorbt:
            from aurora.triage import vectorbt_backend
            rets = vectorbt_backend.vectorbt_pnl_batch(
                prices, signals,
                cost_bps=self.config.cost_bps_simple,
                slippage_bps=self.config.slippage_bps_simple,
            )
        else:
            rets = compute_pnl_batch(
                prices, signals,
                cost_bps=self.config.cost_bps_simple,
                slippage_bps=self.config.slippage_bps_simple,
            )
        metrics = compute_metrics_batch(rets)
        elapsed = time.perf_counter() - t0
        per_variant_cost = elapsed / max(len(variants), 1)
        return [
            self._make_result(v, m, per_variant_cost)
            for v, m in zip(variants, metrics)
        ]

    def _evaluate_parallel(
        self,
        prices: pd.DataFrame,
        variants: Sequence[StrategyVariant],
    ) -> list[TriageResult]:
        """Parallel version that splits the variant list across threads.

        We use threads (not processes) because the heavy lifting after
        signal computation is numpy work that releases the GIL inside
        ``compute_pnl_batch`` and ``compute_metrics_batch``. Strategy
        ``signals()`` calls are pure-python and don't release the GIL,
        but they are also tiny relative to the array-shape ops.
        """
        n = len(variants)
        n_workers = self.config.max_workers or os.cpu_count() or 1
        n_workers = max(1, min(n_workers, n))
        if n_workers <= 1:
            return self._evaluate_serial(prices, variants)
        # Split variant list into n_workers contiguous chunks, preserving
        # input order on reassembly.
        chunk = max(1, n // n_workers)
        slices: list[tuple[int, int]] = []
        for i in range(0, n, chunk):
            slices.append((i, min(i + chunk, n)))

        def _run(slice_pair: tuple[int, int]) -> list[TriageResult]:
            lo, hi = slice_pair
            return self._evaluate_serial(prices, variants[lo:hi])

        out: list[TriageResult] = [None] * n  # type: ignore[list-item]
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            for s, batch in zip(slices, ex.map(_run, slices)):
                lo, hi = s
                for k, r in enumerate(batch):
                    out[lo + k] = r
        return out

    # ------------------------------------------------------------------
    # result construction
    # ------------------------------------------------------------------

    def _make_result(
        self,
        variant: StrategyVariant,
        metrics: dict,
        cost_seconds: float,
    ) -> TriageResult:
        """Apply thresholds + mint a single-use promotion_token if promising."""
        rejection_reason: Optional[str] = None
        # NaN sharpe (no PnL, e.g. degenerate strategy) is treated as
        # below threshold so the variant fails-closed.
        sharpe = float(metrics.get("sharpe", float("nan")))
        max_dd = float(metrics.get("max_dd", float("nan")))
        n_trades = int(metrics.get("n_trades", 0))
        cagr = float(metrics.get("cagr", float("nan")))
        win_rate = float(metrics.get("win_rate", float("nan")))

        if not (sharpe == sharpe) or sharpe < self.config.min_sharpe_threshold:
            rejection_reason = "sharpe_below_threshold"
        elif not (max_dd == max_dd) or max_dd < self.config.max_dd_threshold:
            rejection_reason = "drawdown_below_threshold"
        elif n_trades < self.config.min_trades:
            rejection_reason = "too_few_trades"

        promising = rejection_reason is None
        token: Optional[str] = None
        if promising:
            token = uuid.uuid4().hex
            self._tokens[variant.variant_id] = token

        metadata = {
            "strategy_class": variant.strategy_class,
            "params": dict(variant.params),
            "universe": list(variant.universe),
            "rebalance": variant.rebalance,
            "data_tier_used": self.config.triage_tier_only,
        }
        return TriageResult(
            variant_id=variant.variant_id,
            sharpe=sharpe,
            cagr=cagr,
            max_dd=max_dd,
            n_trades=n_trades,
            win_rate=win_rate,
            cost_seconds=cost_seconds,
            promising=promising,
            rejection_reason=rejection_reason,
            metadata=metadata,
            promotion_token=token,
        )


__all__ = [
    "TriageConfig",
    "TriageResult",
    "TriageBatch",
    "TriageEngine",
]
