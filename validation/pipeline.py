"""Full validation pipeline: 8-gate orchestrator (5 mandatory + DSR + 2 optional).

Mandatory gates: walk-forward, MC bootstrap, MC trade reorder, SPP, lookahead.
Plus DSR (deflated Sharpe) and the two optional gates (noise injection, gap
simulation). Runs all checks, returns ValidationReport. Use to gate any
strategy before paper or live deployment.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, IBKR_costs
from aurora.core.data_layer import IS_END, OOS_START, OOS_END, OOSGuard, split_is_oos
from aurora.core.data_tiers import split_by_tier
from aurora.validation.walk_forward import walk_forward, WFWindow
from aurora.validation.monte_carlo import monte_carlo_bootstrap, monte_carlo_trade_reorder
from aurora.validation.spp import spp
from aurora.validation.lookahead_check import runtime_lookahead_check
from aurora.validation.deflated_sharpe import deflated_sharpe_check
from aurora.validation.noise_injection import noise_injection, NoiseInjectionResult
from aurora.validation.gap_sim import gap_sim, GapSimResult


# P0.A: list of mandatory gate identifiers comes from ``ProtocolPolicy``.
# ``validate_pipeline`` itself runs every gate it knows about; this helper
# exposes the canonical list so external callers / dashboards stay in
# sync with the protocol document.
def get_mandatory_gates() -> list[str]:
    """Return the active mandatory-gate identifiers from
    :class:`quantforge.core.protocol_policy.ProtocolPolicy`.
    """
    from aurora.core.protocol_policy import get_active_policy
    return list(get_active_policy().mandatory_gates)


# Default WF windows match project STANDARD protocol
DEFAULT_WF = [
    WFWindow("WF1", "1995-01-01", "2001-12-31", "2002-01-01", "2005-12-31"),
    WFWindow("WF2", "1995-01-01", "2003-12-31", "2004-01-01", "2006-12-31"),
    WFWindow("WF3", "1995-01-01", "2006-12-31", "2007-01-01", "2009-12-31"),
    WFWindow("WF4", "1995-01-01", "2009-12-31", "2010-01-01", "2012-12-31"),
]


@dataclass
class ValidationReport:
    strategy_name: str
    is_metrics: dict
    oos_metrics: dict
    wf_pass: int
    wf_total: int
    wf_details: list
    mc_bootstrap: dict | None
    mc_reorder: dict | None
    spp_cv: float | None
    lookahead_passed: bool
    lookahead_warnings: list
    dsr: float | None
    dsr_passed: bool | None
    overall_passed: bool
    failures: list[str] = field(default_factory=list)
    noise_result: Optional[NoiseInjectionResult] = None
    gap_result: Optional[GapSimResult] = None
    # P1.B: auditor gate output (None when no auditor_context was provided).
    audit_report: Optional[object] = None
    audit_passed: Optional[bool] = None

    def report(self) -> str:
        lines = [
            "=" * 70,
            f"VALIDATION REPORT: {self.strategy_name}",
            "=" * 70,
            f"IS:  Calmar={self.is_metrics.get('calmar'):.3f}  Sharpe={self.is_metrics.get('sharpe'):.3f}  MDD={self.is_metrics.get('mdd'):.2f}%",
            f"OOS: Calmar={self.oos_metrics.get('calmar'):.3f}  Sharpe={self.oos_metrics.get('sharpe'):.3f}  MDD={self.oos_metrics.get('mdd'):.2f}%",
            f"WF: {self.wf_pass}/{self.wf_total}",
        ]
        if self.mc_bootstrap:
            lines.append(f"MC bootstrap: real_MDD={self.mc_bootstrap['real_mdd']:.2f}% percentile={self.mc_bootstrap['real_mdd_percentile']:.2f}")
        if self.mc_reorder:
            lines.append(f"MC reorder:   real_MDD={self.mc_reorder['real_mdd']:.2f}% percentile={self.mc_reorder['real_mdd_percentile']:.2f}")
        if self.spp_cv is not None:
            lines.append(f"SPP CV (Calmar): {self.spp_cv:.3f}")
        lines.append(f"Lookahead: {'PASS' if self.lookahead_passed else 'FAIL'}")
        if self.lookahead_warnings:
            for w in self.lookahead_warnings: lines.append(f"  warn: {w}")
        if self.dsr is not None:
            lines.append(f"DSR: {self.dsr:.3f}  ({'PASS' if self.dsr_passed else 'FAIL'})")
        if self.noise_result is not None:
            nr = self.noise_result
            lines.append(
                f"Noise injection: base_calmar={nr.base_calmar:.3f} "
                f"p50={nr.calmar_p50:.3f} drop={nr.calmar_drop_pct:.2f}% "
                f"(n={nr.n_samples}, sigma={nr.noise_sigma_bps}bps)"
            )
        if self.gap_result is not None:
            gr = self.gap_result
            lines.append(
                f"Gap sim: base_calmar={gr.base_calmar:.3f} p50={gr.calmar_p50:.3f} "
                f"base_mdd={gr.base_mdd:.2f}% mdd_p5={gr.mdd_p5:.2f}% "
                f"(n={gr.n_samples}, gaps={gr.n_gaps_per_path})"
            )
        if self.audit_passed is not None:
            tag = "PASS" if self.audit_passed else "FAIL"
            lines.append(f"Auditor gate: {tag}")
        lines.append("-" * 70)
        lines.append(f"OVERALL: {'PASS' if self.overall_passed else 'FAIL'}")
        if self.failures:
            for f in self.failures: lines.append(f"  fail: {f}")
        lines.append("=" * 70)
        return "\n".join(lines)


def validate_pipeline(
    strategy_factory: Callable,
    prices: pd.Series,
    name: str,
    n_trials_optimization: int = 1,
    costs: CostModel = IBKR_costs,
    ppy: int = 252,
    wf_windows: Optional[list[WFWindow]] = None,
    spp_param_ranges: Optional[dict] = None,
    spp_strategy_factory: Optional[Callable] = None,
    mc_n_paths: int = 500,
    mc_block_size: int = 21,
    min_dsr: float = 0.95,
    min_wf_pass: int = 3,
    spp_max_cv: float = 0.30,
    mc_min_pct: float = 0.20,
    mc_max_pct: float = 0.80,
    run_noise_injection: bool = False,
    noise_n_samples: int = 100,
    noise_sigma_bps: float = 10.0,
    noise_max_drop_pct: float = 30.0,
    run_gap_sim: bool = False,
    gap_n_samples: int = 100,
    gap_n_per_path: int = 5,
    gap_size_max: float = 0.05,
    gap_max_calmar_drop_pct: float = 40.0,
    gap_max_mdd_increase_pct: float = 50.0,
    fail_fast: bool = False,
    is_tier: str = "IS_ALL",
    oos_tier: str = "OOS_DEV",
    auditor_context: Optional[Any] = None,
    auditor_orchestrator: Optional[Any] = None,
) -> ValidationReport:
    """Run full validation. Returns report with overall pass/fail.

    Tier semantics
    --------------
    Per ``RESEARCH_PROTOCOL.md`` the price history is partitioned into
    five tiers (see :mod:`quantforge.core.data_tiers`):

      * ``IS_TRAIN``  - 1995-01-01..2010-12-31 (model fit)
      * ``IS_VALID``  - 2011-01-01..2012-12-31 (inner WF holdout)
      * ``OOS_DEV``   - 2013-01-01..2020-12-31 (post-GA, can re-touch)
      * ``OOS_LOCKED``- 2021-01-01..2024-12-31 (frozen, single-look ceremony)
      * ``FORWARD``   - 2025-01-01.. (paper / live)

    Routine validation MUST only see the OOS_DEV tier. ``OOS_LOCKED`` and
    ``FORWARD`` are gated behind dedicated ceremonies and require an
    explicit OOSGuard whose phase says so. Selecting them here without
    the matching guard raises ``RuntimeError``. The lockbox-only
    behaviour is a hard-stop, not a warning.

    Args:
        strategy_factory: callable() -> Strategy
        prices: full price series (IS + OOS combined ok; engine handles)
        name: label
        n_trials_optimization: how many configs were tried during optimization
                              (used in DSR; if 1, no selection bias)
        spp_param_ranges: dict[name -> (low, high)] for SPP
        spp_strategy_factory: callable(**params) -> Strategy
        fail_fast: when True, return immediately as soon as any gate fails.
            The remaining (and typically expensive) gates are skipped. The
            partial ``ValidationReport`` always carries ``overall_passed=False``
            and the failure messages collected so far. Default False keeps
            legacy behaviour (run every gate, accumulate every failure).
        is_tier: which IS slice to use as the in-sample input. Allowed:
            ``"IS_TRAIN"`` (<= 2010-12-31) or ``"IS_ALL"`` (IS_TRAIN +
            IS_VALID, default — backward compatible with the legacy
            ``split_is_oos`` IS slice <= 2012-12-31).
        oos_tier: which OOS slice to use as the out-of-sample input.
            Allowed: ``"OOS_DEV"`` (default, 2013-2020), ``"OOS_LOCKED"``
            (2021-2024 - requires an active ``OOSGuard("explicit_unlock_oos_locked")``),
            or ``"FORWARD"`` (>= 2025 - requires
            ``OOSGuard("explicit_unlock_forward")``).
        ...thresholds: see individual gate docs
    """
    # Resolve tier inputs up front. This is the central protocol switch:
    # routine validation must operate on OOS_DEV. Selecting locked tiers
    # is a deliberate ceremony and must be authorized by an OOSGuard
    # whose phase string explicitly opts into that tier.
    is_tier_norm = (is_tier or "IS_ALL").upper()
    oos_tier_norm = (oos_tier or "OOS_DEV").upper()

    if is_tier_norm not in ("IS_TRAIN", "IS_ALL"):
        raise ValueError(
            f"validate_pipeline: is_tier={is_tier!r} not in "
            "('IS_TRAIN', 'IS_ALL')"
        )
    if oos_tier_norm not in ("OOS_DEV", "OOS_LOCKED", "FORWARD"):
        raise ValueError(
            f"validate_pipeline: oos_tier={oos_tier!r} not in "
            "('OOS_DEV', 'OOS_LOCKED', 'FORWARD')"
        )

    if oos_tier_norm in ("OOS_LOCKED", "FORWARD"):
        active = OOSGuard.active()
        required_phase = (
            "explicit_unlock_oos_locked" if oos_tier_norm == "OOS_LOCKED"
            else "explicit_unlock_forward"
        )
        if active is None or active.phase != required_phase:
            raise RuntimeError(
                f"validate_pipeline: oos_tier={oos_tier_norm!r} requires "
                f"an active OOSGuard({required_phase!r}); none found. "
                "Locked tiers are gated by a single-look ceremony."
            )

    failures: list[str] = []

    tiers = split_by_tier(prices)
    if is_tier_norm == "IS_TRAIN":
        is_prices = tiers.is_train
    else:
        is_prices = tiers.is_all
    if oos_tier_norm == "OOS_DEV":
        oos_prices = tiers.oos_dev
    elif oos_tier_norm == "OOS_LOCKED":
        oos_prices = tiers.oos_locked
    else:
        oos_prices = tiers.forward
    # Backward compat: when neither IS nor OOS slice is populated (e.g. a
    # caller passes a synthetic series whose dates fall entirely outside
    # the canonical 1995..2025 calendar), fall back to the legacy
    # ``split_is_oos`` partition so the pipeline still runs end-to-end on
    # purely synthetic test data.
    if len(is_prices) == 0 and len(oos_prices) == 0:
        is_prices, oos_prices = split_is_oos(prices)
    if len(is_prices) < 50 or len(oos_prices) < 50:
        return ValidationReport(
            strategy_name=name,
            is_metrics={},
            oos_metrics={},
            wf_pass=0,
            wf_total=0,
            wf_details=[],
            mc_bootstrap=None,
            mc_reorder=None,
            spp_cv=None,
            lookahead_passed=False,
            lookahead_warnings=[],
            dsr=None,
            dsr_passed=None,
            overall_passed=False,
            failures=["insufficient data"],
        )

    # Auto-generate default WF windows from prices.index when the canonical
    # 1995-2012 windows fall fully outside the available date range. This
    # avoids ``walk_forward`` raising "no overlap" on intraday-only or
    # post-2012 datasets without forcing every caller to hand-build windows.
    if wf_windows is None:
        idx_start = prices.index[0]
        idx_end = prices.index[-1]
        canonical_start = pd.Timestamp(DEFAULT_WF[0].is_start)
        canonical_end = pd.Timestamp(DEFAULT_WF[-1].oos_end)
        if canonical_end < idx_start or canonical_start > idx_end:
            # Carve four equal IS/OOS pairs across the actual date span.
            from aurora.validation.walk_forward import generate_wf_windows
            wf_windows = generate_wf_windows(
                prices, n_windows=4, oos_pct=0.20, mode="rolling"
            )
        else:
            wf_windows = DEFAULT_WF

    # Build the auxiliary-gate price series: IS slice concatenated with the
    # chosen OOS slice. SPP, lookahead_check, MC bootstrap, etc. only ever
    # see this carved series so OOS_LOCKED / FORWARD never leak into the
    # pipeline's secondary gates -- those tiers are exclusively reachable
    # through the explicit_unlock_* ceremonies handled by the tier guard
    # block above. The full ``prices`` argument may carry data beyond
    # OOS_DEV (e.g. a caller passes a 1995..2025 series for plotting); the
    # pipeline must never act on that surplus.
    validation_prices = pd.concat([is_prices, oos_prices]).sort_index()
    # Keep last value when boundary days collide between is and oos slices
    # (defensive; split_by_tier never overlaps, but a synthetic caller
    # could feed weirdly-aligned data).
    validation_prices = validation_prices[~validation_prices.index.duplicated(keep="last")]

    # Cache strategy instance so the factory is not re-invoked 6+ times.
    # ``walk_forward`` re-instantiates per IS slice, so it still gets fresh
    # strategies; we only cache the cases that need a "global" strategy.
    base_strategy = strategy_factory()
    base_signals = base_strategy.signals

    res_is = run_backtest(is_prices, base_signals, costs=costs, ppy=ppy)
    res_oos = run_backtest(oos_prices, base_signals, costs=costs, ppy=ppy)

    is_metrics = {"calmar": res_is.calmar, "sharpe": res_is.sharpe, "cagr": res_is.cagr, "mdd": res_is.mdd}
    oos_metrics = {"calmar": res_oos.calmar, "sharpe": res_oos.sharpe, "cagr": res_oos.cagr, "mdd": res_oos.mdd}

    def _early_fail() -> ValidationReport:
        """Return a partial report when ``fail_fast`` triggers a short-circuit."""
        return ValidationReport(
            strategy_name=name,
            is_metrics=is_metrics,
            oos_metrics=oos_metrics,
            wf_pass=0,
            wf_total=0,
            wf_details=[],
            mc_bootstrap=None,
            mc_reorder=None,
            spp_cv=None,
            lookahead_passed=False,
            lookahead_warnings=[],
            dsr=None,
            dsr_passed=None,
            overall_passed=False,
            failures=list(failures),
        )

    # Walk-forward -- run on the carved validation series. ``walk_forward``
    # filters its own IS/OOS windows; we still pass the carved series so a
    # malformed window cannot drag in OOS_LOCKED / FORWARD by accident.
    wf_res = walk_forward(strategy_factory, validation_prices, wf_windows, costs=costs, ppy=ppy)
    if wf_res.n_pass < min_wf_pass:
        failures.append(f"WF: {wf_res.n_pass}/{wf_res.n_total} < {min_wf_pass}")
        if fail_fast:
            return _early_fail()

    # MC bootstrap on OOS returns
    mc_bs = None; mc_rd = None
    try:
        mc_bs_full = monte_carlo_bootstrap(res_oos.rets[1:], n_paths=mc_n_paths, block_size=mc_block_size, ppy=ppy)
        mc_bs = {"real_mdd": mc_bs_full.real_mdd, "real_mdd_percentile": mc_bs_full.real_mdd_percentile,
                 "p5_mdd": mc_bs_full.p5_mdd, "p50_mdd": mc_bs_full.p50_mdd, "p95_mdd": mc_bs_full.p95_mdd}
        if not (mc_min_pct <= mc_bs_full.real_mdd_percentile <= mc_max_pct):
            failures.append(f"MC bootstrap: real MDD percentile {mc_bs_full.real_mdd_percentile:.2f} outside [{mc_min_pct}, {mc_max_pct}]")
            if fail_fast:
                return _early_fail()
    except Exception as e:
        failures.append(f"MC bootstrap error: {e}")
        if fail_fast:
            return _early_fail()

    # MC trade reorder
    try:
        # Build proper per-bar returns from oos_prices and reorder trades only once.
        # Earlier versions of this block called monte_carlo_trade_reorder TWICE
        # (first with np.zeros(...) as a dead placeholder), which silently
        # consumed the child RNG and poisoned reproducibility hashes.
        prc = oos_prices.values
        rets = np.zeros(len(prc))
        rets[1:] = prc[1:] / prc[:-1] - 1.0
        mc_rd_full = monte_carlo_trade_reorder(res_oos.weights, rets, n_paths=mc_n_paths, ppy=ppy)
        mc_rd = {"real_mdd": mc_rd_full.real_mdd, "real_mdd_percentile": mc_rd_full.real_mdd_percentile,
                 "p50_mdd": mc_rd_full.p50_mdd}
    except Exception as e:
        # not all strategies produce discrete trades; this can fail on continuous-weight
        mc_rd = {"error": str(e)[:80]}

    # SPP
    spp_cv = None
    if spp_param_ranges and spp_strategy_factory:
        try:
            spp_res = spp(spp_strategy_factory, validation_prices, spp_param_ranges, costs=costs, ppy=ppy)
            spp_cv = spp_res.calmar_cv
            if spp_cv > spp_max_cv:
                failures.append(f"SPP CV {spp_cv:.3f} > {spp_max_cv}")
                if fail_fast:
                    return _early_fail()
        except Exception as e:
            failures.append(f"SPP error: {e}")
            if fail_fast:
                return _early_fail()

    # Lookahead (reuses cached base strategy signals). Runs on the carved
    # validation series so the runtime check cannot fingerprint OOS_LOCKED
    # or FORWARD timestamps.
    la_rep = runtime_lookahead_check(base_signals, validation_prices)
    if not la_rep.passed:
        failures.append(f"Lookahead leak detected (delta={la_rep.runtime_metric_delta:.6f})")
        if fail_fast:
            return _early_fail()

    # DSR
    # Always compute DSR. When n_trials_optimization == 1 the gate has no
    # multiplicity to deflate (DSR collapses to PSR-vs-zero); deflated_sharpe_check
    # emits a UserWarning and we still report the value rather than silently
    # skipping the gate. This guarantees single-param strategies are evaluated too.
    dsr = None; dsr_passed = None
    # res_oos.sharpe is annualized; pass ppy so the Mertens variance is applied
    # in per-period units (otherwise DSR is silently inflated).
    dsr_rep = deflated_sharpe_check(
        res_oos.sharpe, n_trials_optimization, len(oos_prices),
        skew=res_oos.metrics.skew, kurtosis=res_oos.metrics.kurtosis,
        min_dsr=min_dsr,
        ppy=ppy,
    )
    dsr = dsr_rep.dsr; dsr_passed = dsr_rep.passed
    if dsr_passed is False:
        failures.append(f"DSR {dsr:.3f} < {min_dsr} (n_trials={n_trials_optimization})")
        if fail_fast:
            return _early_fail()

    # Noise injection (Task 3.5): perturb OOS prices, gate on Calmar drop
    noise_result = None
    if run_noise_injection:
        try:
            noise_result = noise_injection(
                strategy_factory, oos_prices, costs=costs,
                n_samples=noise_n_samples, noise_sigma_bps=noise_sigma_bps, ppy=ppy,
            )
            if not noise_result.passes(max_drop_pct=noise_max_drop_pct):
                failures.append(
                    f"Noise injection: Calmar drop {noise_result.calmar_drop_pct:.2f}% "
                    f">= {noise_max_drop_pct}%"
                )
                if fail_fast:
                    return _early_fail()
        except Exception as e:
            failures.append(f"Noise injection error: {e}")
            if fail_fast:
                return _early_fail()

    # Gap simulation (Task 3.5): inject permanent gaps in OOS, gate on Calmar+MDD
    gap_result = None
    if run_gap_sim:
        try:
            gap_result = gap_sim(
                strategy_factory, oos_prices, costs=costs,
                n_samples=gap_n_samples, n_gaps_per_path=gap_n_per_path,
                gap_size_pct_max=gap_size_max, ppy=ppy,
            )
            if not gap_result.passes(
                max_calmar_drop_pct=gap_max_calmar_drop_pct,
                max_mdd_increase_pct=gap_max_mdd_increase_pct,
            ):
                failures.append(
                    f"Gap sim: base_calmar={gap_result.base_calmar:.3f} "
                    f"p50={gap_result.calmar_p50:.3f} mdd_p5={gap_result.mdd_p5:.2f}% "
                    f"(thresholds calmar<{gap_max_calmar_drop_pct}%, "
                    f"mdd<{gap_max_mdd_increase_pct}%)"
                )
                if fail_fast:
                    return _early_fail()
        except Exception as e:
            failures.append(f"Gap sim error: {e}")
            if fail_fast:
                return _early_fail()

    # P1.B: auditor gate (multi-agent reviewer pipeline).
    # Optional -- runs only when caller provides ``auditor_context``.
    audit_report = None
    audit_passed = None
    if auditor_context is not None:
        try:
            if auditor_orchestrator is None:
                from aurora.agents.auditor import AuditorOrchestrator
                auditor_orchestrator = AuditorOrchestrator.default()
            gate_result = auditor_orchestrator.gate(auditor_context)
            audit_report = gate_result.audit_report
            audit_passed = bool(gate_result.passed)
            if not gate_result.passed:
                failures.append(f"auditor_gate FAIL: {gate_result.reason}")
                if fail_fast:
                    return _early_fail()
        except Exception as e:
            failures.append(f"auditor_gate error: {e}")
            audit_passed = False
            if fail_fast:
                return _early_fail()

    overall = len(failures) == 0

    # On overall PASS, drop a marker file so preflight can verify provenance.
    if overall:
        try:
            from aurora.deployment.preflight import write_validation_marker
            write_validation_marker(
                strategy_name=name,
                metrics={
                    "is": is_metrics,
                    "oos": oos_metrics,
                    "wf_pass": wf_res.n_pass,
                    "wf_total": wf_res.n_total,
                    "dsr": dsr,
                    "spp_cv": spp_cv,
                },
            )
        except Exception:
            # Marker is advisory; never break the pipeline if disk write fails.
            pass

    return ValidationReport(
        strategy_name=name,
        is_metrics=is_metrics,
        oos_metrics=oos_metrics,
        wf_pass=wf_res.n_pass, wf_total=wf_res.n_total, wf_details=wf_res.windows,
        mc_bootstrap=mc_bs, mc_reorder=mc_rd, spp_cv=spp_cv,
        lookahead_passed=la_rep.passed, lookahead_warnings=la_rep.static_warnings,
        dsr=dsr, dsr_passed=dsr_passed,
        overall_passed=overall,
        failures=failures,
        noise_result=noise_result,
        gap_result=gap_result,
        audit_report=audit_report,
        audit_passed=audit_passed,
    )
