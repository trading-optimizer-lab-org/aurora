"""Alert checks for the daily ops report.

Module-private mixin used by :class:`DailyOpsBuilder`. Public API stays
at ``aurora.reporting.daily_ops.builder``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from aurora.reporting.daily_ops._helpers import (
    _current_drawdown,
    _series_returns_through,
)
from aurora.reporting.daily_ops._models import DailyOpsAlert

if TYPE_CHECKING:
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.reporting.daily_ops._models import DailyOpsConfig


class _AlertChecksMixin:
    """Alert check methods for the daily ops builder."""

    # Attribute declarations so mypy knows mixins access concrete state
    # populated by :class:`DailyOpsBuilder.__init__`.
    config: "DailyOpsConfig"
    policy: "ProtocolPolicy"
    inputs: Dict[str, Any]

    def _check_drawdown_breach(self) -> List[DailyOpsAlert]:
        returns: Optional[pd.Series] = self.inputs.get("returns")
        if returns is None or len(returns) == 0:
            return []
        r_full = _series_returns_through(returns, self.config.asof_date)
        cur_dd = _current_drawdown(r_full)
        threshold = float(
            self.policy.risk_limits.max_drawdown_promotion_threshold
        )
        if abs(cur_dd) >= threshold:
            return [DailyOpsAlert(
                severity="critical",
                code="DD_BREACH",
                title="Drawdown breaches policy threshold",
                detail=(
                    f"Current drawdown {cur_dd*100:.2f}% breaches policy "
                    f"max_drawdown_promotion_threshold "
                    f"{threshold*100:.2f}%."
                ),
                suggested_action=(
                    "Halt new entries; review position sizing; consider "
                    "consulting the lockbox before resuming."
                ),
            )]
        return []

    def _check_kill_switch_triggered(self) -> List[DailyOpsAlert]:
        ks = self.inputs.get("kill_switch") or {}
        if bool(ks.get("triggered")):
            return [DailyOpsAlert(
                severity="critical",
                code="KILL_SWITCH",
                title="Kill switch is ARMED",
                detail=(
                    f"Reason: {ks.get('reason', 'unspecified')}. "
                    f"All order submissions are rejected at the broker."
                ),
                suggested_action=(
                    "Investigate the trigger; only ``disarm`` after "
                    "manual verification."
                ),
            )]
        return []

    def _check_data_freshness(self) -> List[DailyOpsAlert]:
        df_in = self.inputs.get("data_freshness") or {}
        last_update = df_in.get("last_update")
        if last_update is None:
            return []
        last_ts = pd.Timestamp(last_update)
        delta = (self.config.asof_date - last_ts).days
        if delta >= 2:
            return [DailyOpsAlert(
                severity="warn",
                code="DATA_STALE",
                title="Data feed is stale",
                detail=(
                    f"Last update {last_ts.date().isoformat()} is "
                    f"{delta} days behind asof_date "
                    f"{self.config.asof_date.date().isoformat()}."
                ),
                suggested_action=(
                    "Refresh the data feed before relying on signals."
                ),
            )]
        return []

    def _check_regime_change(self) -> List[DailyOpsAlert]:
        regime = self.inputs.get("regime") or {}
        last_trans = regime.get("last_transition")
        label = regime.get("label")
        if last_trans is None:
            return []
        last_ts = pd.Timestamp(last_trans)
        if (self.config.asof_date - last_ts).days <= 1:
            return [DailyOpsAlert(
                severity="info",
                code="REGIME_CHANGE",
                title="Regime transition in last 24h",
                detail=(
                    f"Current regime: {label}. "
                    f"Transition at {last_ts.date().isoformat()}."
                ),
                suggested_action=(
                    "Review regime-conditioned strategy params; some "
                    "models require warm-up after a transition."
                ),
            )]
        return []

    def _check_drift(self) -> List[DailyOpsAlert]:
        drift = self.inputs.get("drift") or {}
        if not bool(drift.get("breached")):
            return []
        det = drift.get("detector", "?")
        stat = drift.get("stat")
        thr = drift.get("threshold")
        bits = [f"Detector {det} fired."]
        if stat is not None and thr is not None:
            bits.append(f"stat={stat}, threshold={thr}.")
        return [DailyOpsAlert(
            severity="warn",
            code="DRIFT_DETECTED",
            title="Concept drift detected",
            detail=" ".join(bits),
            suggested_action=(
                "Run validation on recent data; consider retraining."
            ),
        )]

    def _check_validation_marker_stale(self) -> List[DailyOpsAlert]:
        vm = self.inputs.get("validation_marker") or {}
        if "mtime" not in vm:
            return []
        mtime = pd.Timestamp(vm["mtime"])
        # Threshold derived from policy: pick the OOS_DEV tier window length
        # divided by N (here N=8 -- ~1 year of an 8-year window) so the
        # threshold scales with the protocol horizon. Falls back to 30 days
        # if the tier is malformed.
        threshold_days = self._validation_marker_threshold_days()
        delta = (self.config.asof_date - mtime).days
        if delta >= threshold_days:
            return [DailyOpsAlert(
                severity="critical",
                code="VALIDATION_MARKER_STALE",
                title="Validation marker is stale",
                detail=(
                    f"Marker at {vm.get('path', '<unknown>')} mtime="
                    f"{mtime.date().isoformat()} is {delta} days old; "
                    f"threshold {threshold_days} days. Deployment refuses "
                    f"orders until re-validated."
                ),
                suggested_action=(
                    "Re-run the validation pipeline; refresh the marker."
                ),
            )]
        return []

    def _validation_marker_threshold_days(self) -> int:
        try:
            tier = self.policy.tiers.get("OOS_DEV")
            if tier is None or tier.start is None or tier.end is None:
                return 30
            start = pd.Timestamp(tier.start)
            end = pd.Timestamp(tier.end)
            window_days = max(1, (end - start).days)
            return max(30, window_days // 8)
        except Exception:
            return 30
