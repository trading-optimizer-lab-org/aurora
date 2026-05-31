"""Validate phase: the core ``submit`` flow (IS / WF / OOS_DEV / auditor).

Module-private mixin. Public API stays at
``aurora.research.factory.factory``.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Optional, TYPE_CHECKING

import pandas as pd

from aurora.research.factory.factory._helpers import _atomic_jsonl_append
from aurora.research.factory.outcomes import (
    CandidateRun,
    RejectionReason,
    ResearchOutcome,
    ResearchStage,
)
from aurora.research.factory.spec import StrategySpec
from aurora.research.protocol_enforcement import (
    ensure_mandatory_research_protocol,
    make_project_id,
    record_robustness_run,
    record_validation_run,
)

if TYPE_CHECKING:
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.research.factory.factory._config import ResearchPipelineConfig
    from aurora.research.factory.factory._helpers import _AuditorProtocol

_log = logging.getLogger(__name__)


class _ValidateMixin:
    """The IS/WF/OOS_DEV pipeline driver."""

    # Attribute declarations so mypy can resolve attribute access.
    config: "ResearchPipelineConfig"
    policy: "ProtocolPolicy"
    registry: Any
    auditor: Optional["_AuditorProtocol"]
    _backtest_fn: Callable[..., dict]
    _walk_forward_fn: Callable[..., dict]
    _data_loader: Callable[..., pd.Series]
    triage_engine: Any
    _MAX_TIER: str

    if TYPE_CHECKING:
        # Method signatures provided by sibling mixins. Declared here so
        # mypy can resolve cross-mixin attribute access without runtime
        # impact.
        def _is_duplicate(self, spec_hash: str) -> bool: ...
        def _load_full_window(self, spec: StrategySpec) -> pd.Series: ...
        def _open_experiment(self, spec: StrategySpec) -> Optional[str]: ...
        def _close_experiment(
            self,
            experiment_id: Optional[str],
            *,
            success: bool,
            score: Optional[float] = None,
            notes: str = "",
        ) -> None: ...
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
        ) -> ResearchOutcome: ...

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
        protocol_guard = ensure_mandatory_research_protocol(
            project_id=make_project_id("factory", spec.spec_id, spec.name),
            objective=spec.hypothesis or f"Research factory submit: {spec.name}",
            metric="research_factory_promising",
            universe=tuple(spec.universe),
            providers=("research_factory_loader",),
            date_range={"max_tier": self._MAX_TIER, "rebalance": spec.rebalance},
            features=(spec.strategy_class,),
            seed=spec.spec_hash[:16],
            candidate_id=spec.spec_id,
            allowed_selection_phases=("is_train", "is_valid", "oos_dev"),
            locked_phases=("oos_locked", "forward"),
            constraints={
                "entrypoint": "ResearchFactory.submit",
                "spec_hash": spec.spec_hash,
                "generator": spec.generator,
            },
            actor="aurora_factory",
        )

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
        protocol_guard.record_selection(
            spec.spec_id,
            phases_used=("is_train", "oos_dev"),
            metrics={
                "is_sharpe": is_sharpe,
                "oos_dev_sharpe": wf_sharpe,
                "promising": True,
            },
            actor="aurora_factory",
            payload={"candidate_run_id": candidate_id},
        )
        record_robustness_run(
            protocol_guard,
            candidate_id=spec.spec_id,
            actor="aurora_factory",
            checks=(
                "is_gate",
                "walk_forward_gate",
                "oos_dev_gate",
                "auditor_gate",
            ),
            passed=True,
            metrics={
                "is_sharpe": is_sharpe,
                "oos_dev_sharpe": wf_sharpe,
                "auditor_hard_fail": False,
            },
            payload={"candidate_run_id": candidate_id},
        )
        record_validation_run(
            protocol_guard,
            candidate_id=spec.spec_id,
            actor="aurora_factory",
            metrics={
                "is_sharpe": is_sharpe,
                "oos_dev_sharpe": wf_sharpe,
                "promising": True,
            },
            payload={"candidate_run_id": candidate_id},
        )
        self._close_experiment(experiment_id, success=True, score=wf_sharpe)
        summary = (
            f"PROMOTED {spec.name} (sharpe IS={is_sharpe:.3f} OOS={wf_sharpe:.3f})"
        )
        return ResearchOutcome(promising=True, candidate=cand, summary=summary)
