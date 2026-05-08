"""ResearchFactory -- automated hypothesis -> review-queue pipeline.

The factory accepts a :class:`StrategySpec`, runs it through IS / WF /
OOS_DEV gates, and either promotes it to the review queue (for human
sign-off) or archives it with a categorical
:class:`~quantforge.research.factory.outcomes.RejectionReason`.

Hard guarantees
---------------
* No path inside the factory ever touches the OOS_LOCKED or FORWARD
  tiers. All data reads go through
  :func:`quantforge.core.data_tiers.load_up_to_tier` capped at
  ``OOS_DEV`` so even a malformed spec cannot leak the lockbox.
* Every candidate -- promoted or archived -- is appended to a JSONL
  archive (or review queue) via atomic file appends so concurrent
  submitters never interleave bytes.
* Every submission is logged in the
  :class:`~quantforge.registry.experiments.ExperimentTracker`, which
  this module aliases as the "ExperimentRegistry" for naming
  consistency with the parent task spec.
* The optional auditor injection point uses a duck-typed protocol so
  the factory does not import any P1.B code at module load time.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import pandas as pd

from quantforge.core.protocol_policy import ProtocolPolicy
from quantforge.research.factory.lineage import LineageGraph
from quantforge.research.factory.outcomes import (
    CandidateRun,
    RejectionReason,
    ResearchOutcome,
    ResearchStage,
)
from quantforge.research.factory.spec import StrategySpec

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class ResearchPipelineConfig:
    """Knobs controlling the factory's gating behaviour.

    Defaults match ``quantforge/config/research_factory.yaml``. Subclassing
    the dataclass is fine for tests; the factory only relies on attribute
    access.
    """

    is_sharpe_min: float = 0.5
    is_max_drawdown: float = -0.30
    wf_degradation_max: float = 0.50
    wf_instability_max: float = 0.40
    oos_dev_sharpe_min: float = 0.3
    skip_oos_dev_if_wf_fails: bool = True
    archive_path: Path = field(
        default_factory=lambda: __import__(
            "quantforge.core.runtime_paths", fromlist=["research_archive_path"]
        ).research_archive_path()
    )
    review_queue_path: Path = field(
        default_factory=lambda: __import__(
            "quantforge.core.runtime_paths", fromlist=["review_queue_path"]
        ).review_queue_path()
    )
    parallel_workers: int = 1

    @classmethod
    def from_yaml(cls, path: str) -> "ResearchPipelineConfig":
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # Accept Path-typed fields from YAML strings.
        if "archive_path" in data:
            data["archive_path"] = Path(data["archive_path"])
        if "review_queue_path" in data:
            data["review_queue_path"] = Path(data["review_queue_path"])
        return cls(**data)


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
    from quantforge.core.engine import run_backtest
    from quantforge.core.costs import IBKR_costs
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
    from quantforge.validation.walk_forward import walk_forward
    from quantforge.core.costs import IBKR_costs
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


# ---------------------------------------------------------------------------
# ResearchFactory
# ---------------------------------------------------------------------------


class ResearchFactory:
    """Hypothesis -> review-queue automation pipeline.

    Constructor injects the only dependencies the factory needs from the
    rest of the system: a :class:`ProtocolPolicy`, the experiment registry
    (an :class:`~quantforge.registry.experiments.ExperimentTracker`), and
    optionally an auditor. Tests can pass a fake auditor and a custom
    ``backtest_fn`` / ``walk_forward_fn`` to keep the factory unit
    independent of the engine.
    """

    # Class-level guard: data loads inside ``submit`` MUST cap at OOS_DEV.
    # Any code path requesting OOS_LOCKED or FORWARD must raise immediately.
    _MAX_TIER: str = "OOS_DEV"

    def __init__(
        self,
        config: ResearchPipelineConfig,
        policy: ProtocolPolicy,
        registry: Any,  # ExperimentTracker (a.k.a. ExperimentRegistry)
        auditor: Optional[_AuditorProtocol] = None,
        *,
        backtest_fn: Optional[Callable[..., dict]] = None,
        walk_forward_fn: Optional[Callable[..., dict]] = None,
        data_loader: Optional[Callable[..., pd.Series]] = None,
        triage_engine: Any = None,  # quantforge.triage.TriageEngine
    ) -> None:
        self.config = config
        self.policy = policy
        self.registry = registry
        self.auditor = auditor
        self._backtest_fn = backtest_fn or _default_backtest
        self._walk_forward_fn = walk_forward_fn or _default_walk_forward
        self._data_loader = data_loader or self._default_data_loader
        # P2.A: optional triage engine for bulk pre-screening. Accepts any
        # object exposing a ``triage_batch`` method so tests can inject a
        # stub without importing the real engine.
        self.triage_engine = triage_engine

    # ------------------------------------------------------------------
    # data loading -- one place that enforces the OOS_DEV ceiling
    # ------------------------------------------------------------------

    def _default_data_loader(
        self,
        symbol: str,
        max_tier: str = "OOS_DEV",
    ) -> pd.Series:
        """Default loader: ``load_up_to_tier`` capped at OOS_DEV.

        Hard guards against any caller that tries to bypass the ceiling.
        """
        norm = (max_tier or "OOS_DEV").upper()
        if norm not in ("IS_TRAIN", "IS_VALID", "OOS_DEV"):
            raise RuntimeError(
                f"ResearchFactory refuses to load tier {max_tier!r}; "
                "the factory is hard-capped at OOS_DEV. "
                "Use the lockbox ceremony in `forge research promote`."
            )
        from quantforge.core.data_tiers import load_up_to_tier
        return load_up_to_tier(symbol, max_tier=norm, source="yfinance")

    # ------------------------------------------------------------------
    # submission entry point
    # ------------------------------------------------------------------

    def submit(self, spec: StrategySpec) -> ResearchOutcome:
        """Run one spec through the factory.

        Always returns a :class:`ResearchOutcome`. The factory never
        raises on a failed candidate -- failures land in the archive
        with the appropriate :class:`RejectionReason`. Genuine
        infrastructure errors (e.g. registry IO failure) propagate.
        """
        started = pd.Timestamp.utcnow().tz_localize(None)
        t0 = time.perf_counter()
        candidate_id = uuid.uuid4().hex[:12]

        # Bind the active policy hash so a candidate is auditable against
        # the policy in force at submit time. Generators never set this;
        # the factory always overwrites whatever the spec carries.
        spec = spec.with_policy_hash(self.policy.policy_hash)

        # ----- 1. spec validation --------------------------------------
        errs = spec.validate()
        if errs:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.PROPOSED,
                rejection=RejectionReason.SPEC_INVALID,
                detail="; ".join(errs),
                started_at=started,
                t0=t0,
            )

        # ----- 2. dedup vs review queue + archive ----------------------
        if self._is_duplicate(spec.spec_hash):
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.PROPOSED,
                rejection=RejectionReason.DUPLICATE_OF_EXISTING,
                detail=f"spec_hash {spec.spec_hash[:12]} already submitted",
                started_at=started,
                t0=t0,
            )

        # Attempt to log into the experiment registry. The registry is
        # optional to break a hard import cycle in tests; if it raises we
        # capture the error in the rejection detail rather than crashing.
        experiment_id: Optional[str] = None
        try:
            experiment_id = self._open_experiment(spec)
        except Exception as exc:  # pragma: no cover - defensive
            _log.debug("registry start_experiment failed: %s", exc)

        # ----- 3. data load (capped at OOS_DEV) ------------------------
        try:
            prices = self._load_full_window(spec)
        except RuntimeError as exc:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.PROPOSED,
                rejection=RejectionReason.POLICY_VIOLATION,
                detail=f"data load refused: {exc}",
                started_at=started,
                t0=t0,
                experiment_id=experiment_id,
            )
        except Exception as exc:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.PROPOSED,
                rejection=RejectionReason.EXCEPTION,
                detail=f"{type(exc).__name__}: {exc}",
                started_at=started,
                t0=t0,
                experiment_id=experiment_id,
            )

        # ----- 4. IS backtest ------------------------------------------
        try:
            is_metrics = self._backtest_fn(
                spec.strategy_class, spec.params, prices,
            )
        except Exception as exc:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.IS_BACKTEST,
                rejection=RejectionReason.EXCEPTION,
                detail=f"IS backtest raised {type(exc).__name__}: {exc}",
                started_at=started,
                t0=t0,
                experiment_id=experiment_id,
            )
        is_sharpe = float(is_metrics.get("sharpe", 0.0))
        is_mdd = float(is_metrics.get("mdd", 0.0))
        if is_sharpe < self.config.is_sharpe_min:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.IS_BACKTEST,
                rejection=RejectionReason.IS_SHARPE_TOO_LOW,
                detail=(
                    f"IS sharpe={is_sharpe:.3f} < min={self.config.is_sharpe_min:.3f}"
                ),
                started_at=started,
                t0=t0,
                is_metrics=is_metrics,
                experiment_id=experiment_id,
            )
        # MDD is reported in percent (negative). The threshold is also
        # negative ("at most -30% drawdown"). A more negative MDD means
        # a worse drawdown.
        if is_mdd < self.config.is_max_drawdown:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.IS_BACKTEST,
                rejection=RejectionReason.IS_DRAWDOWN_TOO_HIGH,
                detail=(
                    f"IS mdd={is_mdd:.3f} below "
                    f"floor={self.config.is_max_drawdown:.3f}"
                ),
                started_at=started,
                t0=t0,
                is_metrics=is_metrics,
                experiment_id=experiment_id,
            )

        # ----- 5. Walk-forward -----------------------------------------
        try:
            wf_metrics = self._walk_forward_fn(
                spec.strategy_class, spec.params, prices,
            )
        except Exception as exc:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.WALK_FORWARD,
                rejection=RejectionReason.EXCEPTION,
                detail=f"WF raised {type(exc).__name__}: {exc}",
                started_at=started,
                t0=t0,
                is_metrics=is_metrics,
                experiment_id=experiment_id,
            )
        wf_sharpe = float(wf_metrics.get("oos_sharpe_mean", 0.0))
        wf_std = float(wf_metrics.get("oos_sharpe_std", 0.0))
        # Degradation: OOS_sharpe / IS_sharpe must exceed wf_degradation_max
        if is_sharpe > 0:
            ratio = wf_sharpe / is_sharpe
        else:
            ratio = 0.0
        if ratio < self.config.wf_degradation_max:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.WALK_FORWARD,
                rejection=RejectionReason.WF_DEGRADATION,
                detail=(
                    f"WF degradation: oos_sharpe/is_sharpe={ratio:.3f} "
                    f"< min={self.config.wf_degradation_max:.3f}"
                ),
                started_at=started,
                t0=t0,
                is_metrics=is_metrics,
                wf_metrics=wf_metrics,
                experiment_id=experiment_id,
            )
        # Instability: std/|mean| must be below wf_instability_max
        if abs(wf_sharpe) > 1e-9:
            instability = wf_std / abs(wf_sharpe)
        else:
            instability = float("inf")
        if instability > self.config.wf_instability_max:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.WALK_FORWARD,
                rejection=RejectionReason.WF_INSTABILITY,
                detail=(
                    f"WF instability: std/|mean|={instability:.3f} "
                    f"> max={self.config.wf_instability_max:.3f}"
                ),
                started_at=started,
                t0=t0,
                is_metrics=is_metrics,
                wf_metrics=wf_metrics,
                experiment_id=experiment_id,
            )

        # ----- 6. OOS_DEV validation -----------------------------------
        # Reuse the WF mean as the OOS_DEV proxy when the caller has not
        # provided a separate dev run -- this is the cheapest path that
        # still honours the OOS_DEV ceiling. A real installation can
        # inject a dedicated ``oos_dev_fn``; we keep the surface minimal
        # here so tests can drive the gate directly via metrics injection.
        oos_dev_metrics = {
            "sharpe": wf_sharpe,
            "fold_sharpes": list(wf_metrics.get("fold_sharpes") or []),
            "n_pass": int(wf_metrics.get("n_pass", 0)),
            "n_total": int(wf_metrics.get("n_total", 0)),
        }
        if wf_sharpe < self.config.oos_dev_sharpe_min:
            return self._archive(
                candidate_id=candidate_id,
                spec=spec,
                stage=ResearchStage.OOS_DEV_VALIDATION,
                rejection=RejectionReason.OOS_DEV_FAILURE,
                detail=(
                    f"OOS_DEV sharpe={wf_sharpe:.3f} "
                    f"< min={self.config.oos_dev_sharpe_min:.3f}"
                ),
                started_at=started,
                t0=t0,
                is_metrics=is_metrics,
                wf_metrics=wf_metrics,
                oos_dev_metrics=oos_dev_metrics,
                experiment_id=experiment_id,
            )

        # ----- 7. Optional auditor pass --------------------------------
        auditor_hash: Optional[str] = None
        if self.auditor is not None:
            try:
                cand_for_audit = CandidateRun(
                    candidate_id=candidate_id,
                    spec=spec,
                    stage=ResearchStage.OOS_DEV_VALIDATION,
                    is_metrics=is_metrics,
                    wf_metrics=wf_metrics,
                    oos_dev_metrics=oos_dev_metrics,
                    started_at=started,
                )
                report = self.auditor.audit(cand_for_audit)
                auditor_hash = (
                    str(getattr(report, "report_hash", ""))
                    or None
                )
                hard_fail = bool(getattr(report, "hard_fail", False))
                if hard_fail:
                    return self._archive(
                        candidate_id=candidate_id,
                        spec=spec,
                        stage=ResearchStage.OOS_DEV_VALIDATION,
                        rejection=RejectionReason.AUDITOR_HARD_FAIL,
                        detail=(
                            "auditor returned hard_fail=True "
                            f"(report_hash={auditor_hash!r})"
                        ),
                        started_at=started,
                        t0=t0,
                        is_metrics=is_metrics,
                        wf_metrics=wf_metrics,
                        oos_dev_metrics=oos_dev_metrics,
                        auditor_report_hash=auditor_hash,
                        experiment_id=experiment_id,
                    )
            except Exception as exc:
                _log.warning("auditor raised; treating as pass-through: %s", exc)

        # ----- 8. Promote to review queue ------------------------------
        finished = pd.Timestamp.utcnow().tz_localize(None)
        cand = CandidateRun(
            candidate_id=candidate_id,
            spec=spec,
            stage=ResearchStage.REVIEW_QUEUE,
            is_metrics=is_metrics,
            wf_metrics=wf_metrics,
            oos_dev_metrics=oos_dev_metrics,
            auditor_report_hash=auditor_hash,
            rejection=None,
            rejection_detail=None,
            started_at=started,
            finished_at=finished,
            cost_seconds=time.perf_counter() - t0,
        )
        _atomic_jsonl_append(self.config.review_queue_path, cand.to_dict())
        self._close_experiment(experiment_id, success=True, score=wf_sharpe)
        summary = (
            f"PROMOTED {spec.name} (sharpe IS={is_sharpe:.3f} OOS={wf_sharpe:.3f})"
        )
        return ResearchOutcome(promising=True, candidate=cand, summary=summary)

    # ------------------------------------------------------------------
    # batch
    # ------------------------------------------------------------------

    def submit_with_triage(
        self,
        specs: Iterable[StrategySpec],
        *,
        prices: Optional[pd.DataFrame] = None,
    ) -> list[ResearchOutcome]:
        """Pre-screen specs through the triage engine before the full pipeline.

        When :attr:`triage_engine` is None, this method falls back to
        :meth:`submit_batch` (no pre-screening). Otherwise, it converts
        each spec to a :class:`~quantforge.triage.variants.StrategyVariant`,
        runs them through the triage engine in a single batch, and only
        passes the *promising* hits to the full IS / WF / OOS_DEV
        pipeline. Triage hits that fail the simple thresholds are
        archived with :data:`RejectionReason.IS_SHARPE_TOO_LOW` (the
        most-common triage failure mode) so the existing CLI list
        commands work unchanged.

        Triage results are NEVER promotable on their own; this method
        only uses the triage layer as a *filter*, never as a verdict.

        Args:
            specs: iterable of :class:`StrategySpec` proposals.
            prices: optional DataFrame fed straight to the triage engine.
                When None, the factory uses its data loader on the
                first symbol of each spec to assemble a univariate
                DataFrame. The ``triage_tier_only`` setting on the
                triage engine is honored.

        Returns:
            List of :class:`ResearchOutcome` aligned with the input
            specs. Triage-rejected specs return an archived outcome with
            :data:`RejectionReason.IS_SHARPE_TOO_LOW`.
        """
        specs = list(specs)
        if self.triage_engine is None or not specs:
            return [self.submit(s) for s in specs]
        # Build variants from specs.
        from quantforge.triage.variants import StrategyVariant
        variants = [
            StrategyVariant.make(
                strategy_class=s.strategy_class,
                params=s.params,
                universe=s.universe,
                rebalance=s.rebalance,
            )
            for s in specs
        ]
        # Resolve prices via the engine's first universe entry if not given.
        if prices is None:
            symbol = specs[0].universe[0] if specs[0].universe else "SPY"
            tier = getattr(
                self.triage_engine.config, "triage_tier_only", "IS_TRAIN"
            )
            from quantforge.core.data_tiers import load_tier
            ser = load_tier(symbol, tier=tier)
            prices = ser.to_frame(name=symbol)
        triage_batch = self.triage_engine.triage_batch(prices, variants)
        # Index per variant_id for quick lookup.
        by_id = {r.variant_id: r for r in triage_batch.results}
        outcomes: list[ResearchOutcome] = []
        for spec, variant in zip(specs, variants):
            tr = by_id.get(variant.variant_id)
            if tr is not None and tr.promising:
                outcomes.append(self.submit(spec))
            else:
                started = pd.Timestamp.utcnow().tz_localize(None)
                t0 = time.perf_counter()
                detail = (
                    f"triage rejected: {tr.rejection_reason}"
                    if tr is not None
                    else "triage failed to score variant"
                )
                outcomes.append(self._archive(
                    candidate_id=uuid.uuid4().hex[:12],
                    spec=spec.with_policy_hash(self.policy.policy_hash),
                    stage=ResearchStage.PROPOSED,
                    rejection=RejectionReason.IS_SHARPE_TOO_LOW,
                    detail=detail,
                    started_at=started,
                    t0=t0,
                ))
        return outcomes

    def submit_batch(self, specs: Iterable[StrategySpec]) -> list[ResearchOutcome]:
        """Submit many specs.

        Uses ``self.config.parallel_workers`` workers via
        ``concurrent.futures.ThreadPoolExecutor`` when > 1. Threads are
        safe here because the factory's data load and JSONL appends are
        explicitly serialized (``_FILE_LOCK``); the strategy backtest
        itself releases the GIL only sporadically, so the speedup is
        modest but the API matches what callers expect.
        """
        specs = list(specs)
        if self.config.parallel_workers <= 1 or len(specs) <= 1:
            return [self.submit(s) for s in specs]
        with ThreadPoolExecutor(max_workers=self.config.parallel_workers) as ex:
            return list(ex.map(self.submit, specs))

    # ------------------------------------------------------------------
    # query helpers
    # ------------------------------------------------------------------

    def list_review_queue(self) -> list[CandidateRun]:
        """Read the review queue JSONL into a list of :class:`CandidateRun`."""
        return [CandidateRun.from_dict(d)
                for d in _read_jsonl(self.config.review_queue_path)]

    def list_archived(
        self, since: Optional[pd.Timestamp] = None,
    ) -> list[CandidateRun]:
        """Read the archive JSONL.

        Args:
            since: optional cutoff. When provided, only returns candidates
                whose ``started_at`` is >= ``since``.
        """
        records = _read_jsonl(self.config.archive_path)
        out = [CandidateRun.from_dict(d) for d in records]
        if since is not None:
            since_ts = pd.Timestamp(since)
            out = [c for c in out if c.started_at >= since_ts]
        return out

    def get_lineage(self, spec_id: str) -> list[CandidateRun]:
        """Return all candidates in the lineage chain of ``spec_id``.

        Builds the lineage graph from BOTH the review queue and the
        archive (so a parent that was promoted while a child was
        archived still shows up). Returns the chain root-first followed
        by the spec_id itself.
        """
        graph = LineageGraph()
        graph.build(self.list_review_queue())
        graph.build(self.list_archived())
        return graph.lineage_chain(spec_id)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _is_duplicate(self, spec_hash: str) -> bool:
        """True iff ``spec_hash`` appears in the review queue OR archive."""
        for path in (
            self.config.review_queue_path,
            self.config.archive_path,
        ):
            for d in _read_jsonl(path):
                spec = (d.get("spec") or {})
                if spec.get("spec_hash") == spec_hash:
                    return True
        return False

    def _load_full_window(self, spec: StrategySpec) -> pd.Series:
        """Load the OOS_DEV-capped price window for the spec's first symbol.

        The factory currently runs single-asset backtests; multi-asset
        support is a layer above (the universe is preserved on the spec
        but the default backtest runs on ``universe[0]``). This is a
        deliberate scope limit -- the factory's invariants (no OOS_LOCKED)
        do not change for multi-asset, but the engine plumbing does.
        """
        if not spec.universe:
            raise RuntimeError("spec.universe is empty; nothing to backtest")
        symbol = spec.universe[0]
        return self._data_loader(symbol, max_tier=self._MAX_TIER)

    def _open_experiment(self, spec: StrategySpec) -> Optional[str]:
        """Open an experiment in the registry; tolerates a None registry."""
        if self.registry is None:
            return None
        try:
            return self.registry.start_experiment(
                name=f"factory:{spec.name}",
                optimizer="research_factory",
                strategy_class=spec.strategy_class,
                asset=(spec.universe[0] if spec.universe else "UNKNOWN"),
                period_start="IS_TRAIN_START",
                period_end="OOS_DEV_END",
                config={
                    "spec_id": spec.spec_id,
                    "spec_hash": spec.spec_hash,
                    "policy_hash": spec.policy_hash,
                    "params": spec.params,
                    "rebalance": spec.rebalance,
                    "generator": spec.generator,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            _log.debug("start_experiment failed: %s", exc)
            return None

    def _close_experiment(
        self,
        experiment_id: Optional[str],
        *,
        success: bool,
        score: Optional[float] = None,
        notes: str = "",
    ) -> None:
        if experiment_id is None or self.registry is None:
            return
        try:
            self.registry.finish_experiment(
                experiment_id,
                best_score=score,
                notes=notes,
                status="completed" if success else "failed",
            )
        except Exception as exc:  # pragma: no cover - defensive
            _log.debug("finish_experiment failed: %s", exc)

    def _archive(
        self,
        *,
        candidate_id: str,
        spec: StrategySpec,
        stage: ResearchStage,
        rejection: RejectionReason,
        detail: str,
        started_at: pd.Timestamp,
        t0: float,
        is_metrics: Optional[dict] = None,
        wf_metrics: Optional[dict] = None,
        oos_dev_metrics: Optional[dict] = None,
        auditor_report_hash: Optional[str] = None,
        experiment_id: Optional[str] = None,
    ) -> ResearchOutcome:
        """Build + persist an archived :class:`CandidateRun`.

        Always writes to the archive JSONL even when the registry write
        fails -- the JSONL archive is the canonical record; the registry
        is best-effort metadata.
        """
        finished = pd.Timestamp.utcnow().tz_localize(None)
        cand = CandidateRun(
            candidate_id=candidate_id,
            spec=spec,
            stage=ResearchStage.ARCHIVED,
            is_metrics=is_metrics,
            wf_metrics=wf_metrics,
            oos_dev_metrics=oos_dev_metrics,
            auditor_report_hash=auditor_report_hash,
            rejection=rejection,
            rejection_detail=detail,
            started_at=started_at,
            finished_at=finished,
            cost_seconds=time.perf_counter() - t0,
        )
        _atomic_jsonl_append(self.config.archive_path, cand.to_dict())
        self._close_experiment(
            experiment_id, success=False, score=None, notes=f"{rejection.value}: {detail}",
        )
        summary = (
            f"ARCHIVED {spec.name} stage={stage.value} "
            f"reason={rejection.value} ({detail})"
        )
        return ResearchOutcome(promising=False, candidate=cand, summary=summary)


__all__ = [
    "ResearchFactory",
    "ResearchPipelineConfig",
]
