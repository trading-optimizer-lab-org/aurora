"""Six specialized reviewer agents.

All reviewers are deterministic, rule-based pure functions of the
``ReviewContext``. The LLM augmenter (when injected) is severity-capped at
``MEDIUM`` so the LLM never becomes a decisor.

Reviewers
---------
1. :class:`HypothesisReviewer`   - thesis / failure-mode discipline
2. :class:`DataLeakReviewer`     - lookahead / split-boundary leaks
3. :class:`CostReviewer`         - cost denial detection
4. :class:`RegimeReviewer`       - regime concentration / fragility
5. :class:`RiskReviewer`         - risk-limit policy compliance
6. :class:`DeploymentReviewer`   - operational / capacity readiness
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from aurora.agents.auditor.base import (
    LLM_MAX_SEVERITY,
    LLMAugmenter,
    ReviewContext,
    ReviewFinding,
    ReviewReport,
    ReviewSeverity,
    ReviewerAgent,
)


def _now() -> pd.Timestamp:
    """Deterministic timestamp source -- can be monkeypatched in tests."""
    return pd.Timestamp.utcnow()


def _make_report(
    reviewer: str,
    context: ReviewContext,
    findings: List[ReviewFinding],
    summary: str,
    score: Optional[float] = None,
) -> ReviewReport:
    """Build a :class:`ReviewReport` with consistent metadata."""
    if score is None:
        score = ReviewerAgent._score_from_findings(findings)
    return ReviewReport(
        reviewer=reviewer,
        target_strategy_id=context.strategy_id,
        target_run_id=str(context.backtest_results.get("run_id"))
        if context.backtest_results.get("run_id") is not None else None,
        findings=list(findings),
        summary=summary,
        score=float(score),
        timestamp=_now(),
        policy_hash=context.policy.policy_hash,
    )


# ---------------------------------------------------------------------------
# 1. HypothesisReviewer
# ---------------------------------------------------------------------------


class HypothesisReviewer(ReviewerAgent):
    """Checks the strategy_spec documents an honest hypothesis.

    HARD_FAIL conditions
    --------------------
    * ``hypothesis`` field missing or empty.
    * ``expected_edge_bps > 100`` -- a smell test: anything claiming more
      than 100 bps annualized edge is almost certainly mismeasured.

    HIGH conditions
    ---------------
    * ``failure_modes`` not documented (researcher hasn't thought about
      how the strategy can break).

    MEDIUM conditions
    -----------------
    * ``regime_dependence`` not documented.
    * ``assumptions`` not documented.
    """

    name = "HypothesisReviewer"

    def review(self, context: ReviewContext) -> ReviewReport:
        spec = context.strategy_spec or {}
        findings: List[ReviewFinding] = []

        hypothesis = spec.get("hypothesis")
        if not hypothesis or not str(hypothesis).strip():
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HARD_FAIL,
                code="HYPOTHESIS_MISSING",
                title="Strategy hypothesis missing",
                detail=("Every strategy must declare a written hypothesis "
                        "(why this edge exists). Empty or absent hypothesis "
                        "blocks promotion."),
                evidence={"strategy_spec_keys": sorted(spec.keys())},
                suggested_action=(
                    "Document the economic rationale, what behavior the "
                    "edge captures, and why it should persist."
                ),
            ))

        edge = spec.get("expected_edge_bps")
        if isinstance(edge, (int, float)) and edge > 100:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HARD_FAIL,
                code="EXPECTED_EDGE_IMPLAUSIBLE",
                title="expected_edge_bps > 100 (smell test)",
                detail=(f"expected_edge_bps={edge} bps annualized is "
                        "implausible for a real-world strategy. This is "
                        "almost always a measurement error or in-sample "
                        "overfit."),
                evidence={"expected_edge_bps": float(edge)},
                suggested_action=(
                    "Re-check sign/scale of edge calc; common pitfalls: "
                    "daily vs annual confusion, gross vs net of costs."
                ),
            ))

        failure_modes = spec.get("failure_modes")
        if not failure_modes:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HIGH,
                code="FAILURE_MODES_NOT_DOCUMENTED",
                title="No documented failure modes",
                detail=("Strategies must enumerate how they can break "
                        "(regime shift, liquidity dry-up, cost shock, "
                        "structural break). Missing this is a red flag."),
                evidence={},
                suggested_action=(
                    "List 3+ failure modes with monitoring tripwires."
                ),
            ))

        regime_dep = spec.get("regime_dependence")
        if not regime_dep:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.MEDIUM,
                code="REGIME_DEPENDENCE_NOT_DOCUMENTED",
                title="regime_dependence not documented",
                detail=("Document which market regimes the strategy is "
                        "expected to perform in vs avoid."),
                evidence={},
                suggested_action="Add a regime_dependence section.",
            ))

        if not spec.get("assumptions"):
            findings.append(ReviewFinding(
                severity=ReviewSeverity.MEDIUM,
                code="ASSUMPTIONS_NOT_DOCUMENTED",
                title="Strategy assumptions not documented",
                detail=("List the assumptions the edge relies on (cost "
                        "regime, borrow availability, exchange behavior, "
                        "data continuity)."),
                evidence={},
                suggested_action="Add an assumptions section.",
            ))

        all_findings = self._augment(findings, context)
        if all_findings:
            summary = (f"{self.name}: {len(all_findings)} finding(s); "
                       f"max severity = "
                       f"{max(f.severity.rank() for f in all_findings)}")
        else:
            summary = f"{self.name}: thesis discipline OK."
        return _make_report(self.name, context, all_findings, summary)


# ---------------------------------------------------------------------------
# 2. DataLeakReviewer
# ---------------------------------------------------------------------------


class DataLeakReviewer(ReviewerAgent):
    """Detects look-ahead and IS/OOS boundary leaks.

    HARD_FAIL conditions
    --------------------
    * ``backtest_results['lookahead_check']`` is ``False`` /
      ``passed=False``.
    * Any feature in ``backtest_results['features_used']`` references a
      timestamp ``>`` the IS_TRAIN end (per policy.tiers).
    * ``backtest_results['data_fingerprint']['max_index']`` exceeds the
      configured train-end window for an IS run.
    """

    name = "DataLeakReviewer"

    def review(self, context: ReviewContext) -> ReviewReport:
        bt = context.backtest_results or {}
        findings: List[ReviewFinding] = []

        # 1. Direct lookahead check signal.
        la = bt.get("lookahead_check")
        if isinstance(la, dict):
            passed = la.get("passed", la.get("ok", True))
        elif isinstance(la, bool):
            passed = la
        else:
            passed = True  # absent => assume not yet checked, do not fail.
        if la is not None and not passed:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HARD_FAIL,
                code="DATA_LEAK_LOOKAHEAD_DETECTED",
                title="Lookahead leak detected by gate",
                detail=("validation/lookahead_check reported FAIL. The "
                        "strategy uses information not available at "
                        "decision time."),
                evidence={"lookahead_check": la},
                suggested_action=(
                    "Inspect the offending feature; rebuild with "
                    "strict point-in-time joins."
                ),
            ))

        # 2. Per-feature timestamp check vs IS_TRAIN end (if present).
        features_used = bt.get("features_used") or []
        is_train = context.policy.tiers.get("IS_TRAIN")
        if is_train and is_train.end:
            train_end = pd.Timestamp(is_train.end)
            run_phase = (bt.get("phase") or bt.get("tier")
                         or "").upper()
            # Only enforce for IS runs; OOS runs legitimately use
            # post-train data.
            if run_phase in ("IS", "IS_TRAIN", "IS_ALL"):
                for feat in features_used:
                    if not isinstance(feat, dict):
                        continue
                    last_ts = feat.get("max_timestamp") or feat.get("last_ts")
                    if last_ts is None:
                        continue
                    try:
                        ts = pd.Timestamp(last_ts)
                    except Exception:
                        continue
                    if ts > train_end:
                        findings.append(ReviewFinding(
                            severity=ReviewSeverity.HARD_FAIL,
                            code="DATA_LEAK_FEATURE_PAST_TRAIN_END",
                            title=(f"Feature '{feat.get('name','?')}' "
                                   "uses post-train data"),
                            detail=(f"Feature timestamp {ts.isoformat()} "
                                    f"> IS_TRAIN end "
                                    f"{train_end.isoformat()}."),
                            evidence={
                                "feature": feat.get("name"),
                                "max_timestamp": str(ts),
                                "is_train_end": str(train_end),
                            },
                            suggested_action=(
                                "Recompute feature with strict point-in-"
                                "time semantics."
                            ),
                        ))

        # 3. Fingerprint sanity: bt['data_fingerprint']['max_index'] should
        # not exceed train_end on IS runs.
        fp = bt.get("data_fingerprint") or {}
        max_idx = fp.get("max_index") or fp.get("max_ts")
        run_phase = (bt.get("phase") or bt.get("tier") or "").upper()
        if max_idx is not None and run_phase in ("IS", "IS_TRAIN") and is_train and is_train.end:
            try:
                ts = pd.Timestamp(max_idx)
                train_end = pd.Timestamp(is_train.end)
                if ts > train_end:
                    findings.append(ReviewFinding(
                        severity=ReviewSeverity.HARD_FAIL,
                        code="DATA_LEAK_FINGERPRINT_PAST_TRAIN_END",
                        title="Data fingerprint exceeds IS_TRAIN end",
                        detail=(f"max_index={ts.isoformat()} > "
                                f"IS_TRAIN end {train_end.isoformat()}."),
                        evidence={"max_index": str(ts),
                                  "is_train_end": str(train_end)},
                        suggested_action="Re-carve dataset to the IS tier.",
                    ))
            except Exception:
                pass

        all_findings = self._augment(findings, context)
        if all_findings:
            summary = (f"{self.name}: {len(all_findings)} leak finding(s).")
        else:
            summary = f"{self.name}: no leaks detected."
        return _make_report(self.name, context, all_findings, summary)


# ---------------------------------------------------------------------------
# 3. CostReviewer
# ---------------------------------------------------------------------------


class CostReviewer(ReviewerAgent):
    """Compares backtest-reported costs to policy.cost_model expectations.

    HARD_FAIL conditions
    --------------------
    * ``backtest_costs_bps < 0.5 * policy_cost_bps`` -- cost denial.

    MEDIUM conditions
    -----------------
    * ``0.5 * policy_cost_bps <= backtest_costs_bps < 0.8 * policy_cost_bps``
      -- under-modeled costs.
    """

    name = "CostReviewer"

    def review(self, context: ReviewContext) -> ReviewReport:
        bt = context.backtest_results or {}
        findings: List[ReviewFinding] = []

        # Expected cost floor per policy (sum of commission + spread + slippage)
        cm = context.policy.cost_model
        expected_bps = (cm.commission_bps + cm.spread_bps + cm.slippage_bps)

        reported = bt.get("cost_breakdown_bps")
        if reported is None:
            reported = bt.get("total_costs_bps")
        # Acceptable shapes: a number, a dict (sum its values), or None.
        if isinstance(reported, dict):
            try:
                reported_total = float(sum(reported.values()))
            except Exception:
                reported_total = None
        elif isinstance(reported, (int, float)):
            reported_total = float(reported)
        else:
            reported_total = None

        if reported_total is not None and expected_bps > 0:
            ratio = reported_total / expected_bps
            if ratio < 0.5:
                findings.append(ReviewFinding(
                    severity=ReviewSeverity.HARD_FAIL,
                    code="COST_DENIAL",
                    title="Backtest costs < 50% of policy cost model",
                    detail=(f"reported total cost = {reported_total:.2f} bps, "
                            f"policy expects {expected_bps:.2f} bps "
                            f"(ratio={ratio:.2f}). This is cost denial -- "
                            "the strategy's edge may evaporate at the "
                            "real cost floor."),
                    evidence={"reported_bps": reported_total,
                              "expected_bps": expected_bps,
                              "ratio": ratio},
                    suggested_action=(
                        "Re-run backtest with policy.cost_model "
                        "(commission+spread+slippage)."
                    ),
                ))
            elif ratio < 0.8:
                findings.append(ReviewFinding(
                    severity=ReviewSeverity.MEDIUM,
                    code="COST_UNDERMODELED",
                    title="Backtest costs 50-80% of policy",
                    detail=(f"reported {reported_total:.2f} bps vs "
                            f"policy {expected_bps:.2f} bps "
                            f"(ratio={ratio:.2f})."),
                    evidence={"reported_bps": reported_total,
                              "expected_bps": expected_bps,
                              "ratio": ratio},
                    suggested_action=(
                        "Bump cost assumptions to at least the policy floor."
                    ),
                ))
        elif reported_total is None:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.MEDIUM,
                code="COST_NOT_REPORTED",
                title="No cost breakdown in backtest_results",
                detail=("Backtest does not report a cost breakdown; "
                        "cannot reconcile against policy."),
                evidence={"keys": sorted(bt.keys())},
                suggested_action=(
                    "Emit cost_breakdown_bps in the backtest output."
                ),
            ))

        all_findings = self._augment(findings, context)
        if all_findings:
            summary = (f"{self.name}: {len(all_findings)} cost finding(s).")
        else:
            summary = f"{self.name}: costs match policy."
        return _make_report(self.name, context, all_findings, summary)


# ---------------------------------------------------------------------------
# 4. RegimeReviewer
# ---------------------------------------------------------------------------


class RegimeReviewer(ReviewerAgent):
    """Examines per-regime performance.

    Inputs
    ------
    Reads ``backtest_results['by_regime']`` which is expected to be:
        {regime_label: {"sharpe": float, "calmar": float, ...}, ...}

    HIGH conditions
    ---------------
    * Strategy works in only one regime (other regimes have Sharpe <= 0
      or no exposure).

    MEDIUM conditions
    -----------------
    * Worst-regime Sharpe < 0.

    INFO conditions
    ---------------
    * Performance is balanced across regimes (no edge case triggered).
    """

    name = "RegimeReviewer"

    def review(self, context: ReviewContext) -> ReviewReport:
        bt = context.backtest_results or {}
        findings: List[ReviewFinding] = []

        by_regime = bt.get("by_regime")
        if not isinstance(by_regime, dict) or len(by_regime) < 2:
            # Not enough info to make a call. Don't gate, just info.
            findings.append(ReviewFinding(
                severity=ReviewSeverity.INFO,
                code="REGIME_DATA_INSUFFICIENT",
                title="No multi-regime breakdown",
                detail=("backtest_results['by_regime'] missing or "
                        "single-regime; cannot assess regime fragility."),
                evidence={"regimes_seen": list(
                    by_regime.keys()) if isinstance(by_regime, dict) else None},
            ))
        else:
            sharpes = {
                k: float(v.get("sharpe", 0.0))
                for k, v in by_regime.items()
                if isinstance(v, dict)
            }
            if sharpes:
                positive_regimes = [k for k, s in sharpes.items() if s > 0]
                worst = min(sharpes.values())
                if len(positive_regimes) <= 1 and len(sharpes) >= 2:
                    findings.append(ReviewFinding(
                        severity=ReviewSeverity.HIGH,
                        code="REGIME_SINGLE_REGIME_DEPENDENCE",
                        title=("Strategy profitable in <=1 regime"),
                        detail=("All but one regime show non-positive "
                                "Sharpe. Strategy is regime-fragile."),
                        evidence={"by_regime_sharpe": sharpes,
                                  "positive_regimes": positive_regimes},
                        suggested_action=(
                            "Add a regime overlay or stop-out when the "
                            "strategy's home regime ends."
                        ),
                    ))
                elif worst < 0:
                    findings.append(ReviewFinding(
                        severity=ReviewSeverity.MEDIUM,
                        code="REGIME_WORST_SHARPE_NEGATIVE",
                        title="Worst-regime Sharpe is negative",
                        detail=(f"Worst-regime Sharpe={worst:.3f}. "
                                "Strategy bleeds in adverse regimes."),
                        evidence={"by_regime_sharpe": sharpes,
                                  "worst_sharpe": worst},
                        suggested_action=(
                            "Consider regime-aware sizing or exits."
                        ),
                    ))
                else:
                    findings.append(ReviewFinding(
                        severity=ReviewSeverity.INFO,
                        code="REGIME_BALANCED",
                        title="Regime performance balanced",
                        detail=("All regimes show non-negative Sharpe."),
                        evidence={"by_regime_sharpe": sharpes},
                    ))

        all_findings = self._augment(findings, context)
        if all_findings:
            summary = (f"{self.name}: {len(all_findings)} regime finding(s).")
        else:
            summary = f"{self.name}: regime profile balanced."
        return _make_report(self.name, context, all_findings, summary)


# ---------------------------------------------------------------------------
# 5. RiskReviewer
# ---------------------------------------------------------------------------


class RiskReviewer(ReviewerAgent):
    """Compares backtest risk metrics to policy.risk_limits.

    HARD_FAIL conditions
    --------------------
    * max_drawdown > policy.risk_limits.max_drawdown_promotion_threshold
    * max_leverage > policy.risk_limits.max_leverage
    * max_position_concentration > policy.risk_limits.max_position_concentration
    * |correlation_to_benchmark| > policy.risk_limits.max_correlation_to_benchmark
    """

    name = "RiskReviewer"

    def review(self, context: ReviewContext) -> ReviewReport:
        bt = context.backtest_results or {}
        findings: List[ReviewFinding] = []
        rl = context.policy.risk_limits

        max_dd = bt.get("max_drawdown")
        if max_dd is None:
            max_dd = bt.get("mdd")
        if isinstance(max_dd, (int, float)):
            # Drawdown stored as positive fraction in [0,1] OR percent.
            # Normalize: anything > 1 is treated as percent and divided.
            mdd_frac = abs(float(max_dd))
            if mdd_frac > 1.0:
                mdd_frac = mdd_frac / 100.0
            if mdd_frac > rl.max_drawdown_promotion_threshold:
                findings.append(ReviewFinding(
                    severity=ReviewSeverity.HARD_FAIL,
                    code="RISK_MDD_BREACH",
                    title="Max drawdown exceeds promotion threshold",
                    detail=(f"max_drawdown={mdd_frac:.4f} > policy "
                            f"limit {rl.max_drawdown_promotion_threshold:.4f}."),
                    evidence={
                        "max_drawdown": mdd_frac,
                        "limit": rl.max_drawdown_promotion_threshold,
                    },
                    suggested_action=(
                        "Reduce leverage, add stop-loss, or rework risk "
                        "controls."
                    ),
                ))

        max_lev = bt.get("max_leverage")
        if isinstance(max_lev, (int, float)) and float(max_lev) > rl.max_leverage:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HARD_FAIL,
                code="RISK_LEVERAGE_BREACH",
                title="Max leverage exceeds policy limit",
                detail=(f"max_leverage={float(max_lev):.3f} > "
                        f"policy {rl.max_leverage:.3f}."),
                evidence={"max_leverage": float(max_lev),
                          "limit": rl.max_leverage},
                suggested_action="Cap exposure inside the strategy.",
            ))

        max_conc = bt.get("max_position_concentration")
        if (isinstance(max_conc, (int, float))
                and float(max_conc) > rl.max_position_concentration):
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HARD_FAIL,
                code="RISK_CONCENTRATION_BREACH",
                title="Max position concentration exceeds policy",
                detail=(f"max_position_concentration={float(max_conc):.3f} > "
                        f"policy {rl.max_position_concentration:.3f}."),
                evidence={"max_position_concentration": float(max_conc),
                          "limit": rl.max_position_concentration},
                suggested_action="Diversify or cap single-name weight.",
            ))

        corr = bt.get("correlation_to_benchmark")
        if isinstance(corr, (int, float)) and abs(
                float(corr)) > rl.max_correlation_to_benchmark:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HARD_FAIL,
                code="RISK_CORRELATION_BREACH",
                title="|correlation_to_benchmark| exceeds policy",
                detail=(f"|correlation|={abs(float(corr)):.3f} > "
                        f"policy {rl.max_correlation_to_benchmark:.3f}."),
                evidence={"correlation_to_benchmark": float(corr),
                          "limit": rl.max_correlation_to_benchmark},
                suggested_action=(
                    "Strategy is too close to the benchmark; consider "
                    "the alpha-vs-beta tradeoff."
                ),
            ))

        all_findings = self._augment(findings, context)
        if all_findings:
            summary = (f"{self.name}: {len(all_findings)} risk finding(s).")
        else:
            summary = f"{self.name}: within policy risk limits."
        return _make_report(self.name, context, all_findings, summary)


# ---------------------------------------------------------------------------
# 6. DeploymentReviewer
# ---------------------------------------------------------------------------


class DeploymentReviewer(ReviewerAgent):
    """Operational readiness: capacity, borrow, real fees match cost model.

    HARD_FAIL conditions
    --------------------
    * ``planned_size_pct_of_adv > 10%`` -- the strategy can't fit in the
      market without moving prices.

    MEDIUM conditions
    -----------------
    * Strategy shorts but no borrow availability is modeled.
    * Real-broker quotes deviate from policy cost model >50%.
    """

    name = "DeploymentReviewer"

    def review(self, context: ReviewContext) -> ReviewReport:
        bt = context.backtest_results or {}
        spec = context.strategy_spec or {}
        deploy = context.extras.get("deployment") or {}
        findings: List[ReviewFinding] = []

        # Capacity check.
        size_adv_pct = (
            deploy.get("planned_size_pct_of_adv")
            or bt.get("planned_size_pct_of_adv")
            or bt.get("size_pct_of_adv")
        )
        if isinstance(size_adv_pct, (int, float)):
            pct = float(size_adv_pct)
            # Accept either fractional [0,1] or percent [0,100].
            pct_frac = pct / 100.0 if pct > 1.0 else pct
            if pct_frac > 0.10:
                findings.append(ReviewFinding(
                    severity=ReviewSeverity.HARD_FAIL,
                    code="DEPLOY_SIZE_OVER_10PCT_ADV",
                    title=("Planned size > 10% of average daily volume"),
                    detail=(f"planned_size = {pct_frac*100:.2f}% ADV. "
                            "Strategy will move the market."),
                    evidence={"size_pct_of_adv": pct_frac},
                    suggested_action=(
                        "Reduce gross exposure or split across more names."
                    ),
                ))

        # Borrow / shorts.
        shorts = bool(spec.get("uses_shorts")
                      or bt.get("uses_shorts")
                      or bt.get("min_weight", 0) < 0)
        borrow_modeled = bool(
            spec.get("borrow_modeled")
            or deploy.get("borrow_modeled")
            or bt.get("borrow_costs_modeled")
        )
        if shorts and not borrow_modeled:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.MEDIUM,
                code="DEPLOY_SHORTS_NO_BORROW_MODEL",
                title="Strategy shorts but borrow not modeled",
                detail=("uses_shorts=True but borrow availability/cost is "
                        "absent from spec/backtest. Real shorting may "
                        "fail or eat the edge."),
                evidence={"uses_shorts": shorts,
                          "borrow_modeled": borrow_modeled},
                suggested_action=(
                    "Add borrow_modeled=True, document the borrow source."
                ),
            ))

        # Real-broker cost reconciliation.
        cm = context.policy.cost_model
        policy_total = cm.commission_bps + cm.spread_bps + cm.slippage_bps
        real_quotes = deploy.get("broker_cost_quote_bps")
        if isinstance(real_quotes, (int, float)) and policy_total > 0:
            ratio = float(real_quotes) / policy_total
            if abs(ratio - 1.0) > 0.5:
                findings.append(ReviewFinding(
                    severity=ReviewSeverity.MEDIUM,
                    code="DEPLOY_REAL_COSTS_MISALIGNED",
                    title="Real-broker quoted costs diverge from policy",
                    detail=(f"broker quoted {float(real_quotes):.2f} bps "
                            f"vs policy {policy_total:.2f} bps "
                            f"(ratio={ratio:.2f})."),
                    evidence={"broker_cost_bps": float(real_quotes),
                              "policy_cost_bps": policy_total,
                              "ratio": ratio},
                    suggested_action=(
                        "Update policy.cost_model OR reprice strategy."
                    ),
                ))

        # Liquidity floor.
        liquidity_ok = deploy.get("liquidity_fits_size", True)
        if not liquidity_ok:
            findings.append(ReviewFinding(
                severity=ReviewSeverity.HIGH,
                code="DEPLOY_LIQUIDITY_FAIL",
                title="Liquidity does not support planned position size",
                detail=("Operator flagged liquidity_fits_size=False."),
                evidence={"deployment": deploy},
                suggested_action="Reduce target size or pick more liquid names.",
            ))

        all_findings = self._augment(findings, context)
        if all_findings:
            summary = (f"{self.name}: {len(all_findings)} deployment finding(s).")
        else:
            summary = f"{self.name}: operationally ready."
        return _make_report(self.name, context, all_findings, summary)


__all__ = [
    "HypothesisReviewer",
    "DataLeakReviewer",
    "CostReviewer",
    "RegimeReviewer",
    "RiskReviewer",
    "DeploymentReviewer",
]
