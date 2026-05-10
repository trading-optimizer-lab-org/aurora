"""R177 - Research-to-live preflight bundle.

Combines the gates from R161 / R164 / R165 / R166 / R168 / R175 into a
single operator-readable preflight result. The orchestrator already
covers data + market + system gates (R55..R57); this module sits one
level higher and asks "is this strategy ready to leave research?"

The result is a :class:`PreflightBundle` with a list of
:class:`PreflightCheck` records, each carrying status, message and
remediation. Status values: ``pass``, ``warn``, ``fail``, ``skip``.

Inputs are passed in as plain data so the bundle can be tested without
booting the full pipeline; production code wires the aggregator from
DataQualityReports, BenchmarkPack, EvidencePack, StrategyRiskRecord and
broker health snapshots.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, List, Literal, Mapping, Optional, Tuple

from aurora.governance.approvals import (
    LifecycleStage,
    StrategyRiskRecord,
)


CheckStatus = Literal["pass", "warn", "fail", "skip"]


@dataclass(frozen=True)
class PreflightCheck:
    """One gate inside a :class:`PreflightBundle`."""

    name: str
    status: CheckStatus
    message: str
    remediation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PreflightBundle:
    """Aggregated preflight result for a strategy."""

    strategy_id: str
    target_stage: LifecycleStage
    checks: Tuple[PreflightCheck, ...]
    overrides: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    @property
    def overall_status(self) -> CheckStatus:
        if any(c.status == "fail" for c in self.checks):
            return "fail"
        if any(c.status == "warn" for c in self.checks):
            return "warn"
        return "pass"

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "target_stage": self.target_stage.value,
            "overall_status": self.overall_status,
            "checks": [c.to_dict() for c in self.checks],
            "overrides": [dict(o) for o in self.overrides],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def to_table(self) -> str:
        rows = [("CHECK", "STATUS", "MESSAGE")]
        rows.extend((c.name, c.status, c.message) for c in self.checks)
        widths = [max(len(r[i]) for r in rows) for i in range(3)]
        lines = [
            "  ".join(r[i].ljust(widths[i]) for i in range(3))
            for r in rows
        ]
        lines.append("")
        lines.append(f"target: {self.target_stage.value}")
        lines.append(f"overall: {self.overall_status}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_preflight_bundle(
    *,
    strategy_id: str,
    target_stage: LifecycleStage,
    risk_record: Optional[StrategyRiskRecord],
    expected_policy_hash: str,
    expected_snapshot_hash: str,
    expected_strategy_hash: str,
    benchmark_pack: Optional[Mapping[str, Any]] = None,
    benchmark_required_verdict: str = "beats",
    quality_decisions: Optional[List[Mapping[str, Any]]] = None,
    evidence_pack_present: bool = False,
    evidence_pack_hash_ok: bool = False,
    research_ledger_complete: bool = False,
    execution_model: str = "",
    kill_switch_armed: bool = False,
    broker_healthy: bool = False,
    reconciliation_clean: bool = False,
    capital_limits_set: bool = False,
    rollback_plan_present: bool = False,
    overrides: Optional[List[Mapping[str, Any]]] = None,
) -> PreflightBundle:
    """Aggregate all R177 gates into a :class:`PreflightBundle`."""
    checks: List[PreflightCheck] = []

    # Risk record / approval state ------------------------------------------
    if risk_record is None:
        checks.append(PreflightCheck(
            name="risk_record",
            status="fail",
            message="no risk record found",
            remediation="aurora governance risk-record create",
        ))
    else:
        if risk_record.is_expired():
            checks.append(PreflightCheck(
                name="risk_record",
                status="fail",
                message=f"risk record expired on {risk_record.expires_at!s}",
                remediation="aurora governance risk-record renew",
            ))
        elif not risk_record.hashes_match(
            policy_hash=expected_policy_hash,
            snapshot_hash=expected_snapshot_hash,
            strategy_hash=expected_strategy_hash,
        ):
            checks.append(PreflightCheck(
                name="risk_record",
                status="fail",
                message="risk record hashes do not match active validation",
                remediation="rerun validation and refresh the risk record",
            ))
        else:
            stage_order = (
                LifecycleStage.DRAFTED, LifecycleStage.REVIEWED,
                LifecycleStage.SHADOW, LifecycleStage.PAPER,
                LifecycleStage.CANARY, LifecycleStage.LIVE,
            )
            cur_idx = stage_order.index(risk_record.stage)
            tgt_idx = stage_order.index(target_stage)
            if cur_idx < tgt_idx:
                checks.append(PreflightCheck(
                    name="risk_record",
                    status="fail",
                    message=(
                        f"risk record at {risk_record.stage.value} but "
                        f"{target_stage.value} required"
                    ),
                    remediation="aurora governance promote",
                ))
            else:
                checks.append(PreflightCheck(
                    name="risk_record",
                    status="pass",
                    message=f"approved at {risk_record.stage.value}",
                ))

    # Validation hashes -----------------------------------------------------
    checks.append(PreflightCheck(
        name="validation_current",
        status="pass" if expected_strategy_hash else "warn",
        message=(
            "expected_strategy_hash supplied" if expected_strategy_hash
            else "no expected_strategy_hash provided"
        ),
        remediation="" if expected_strategy_hash else (
            "rerun validation pipeline before preflight"
        ),
    ))

    # Benchmark pack --------------------------------------------------------
    if benchmark_pack is None:
        checks.append(PreflightCheck(
            name="benchmark_pack",
            status="fail",
            message="no benchmark pack supplied",
            remediation="run aurora.validation.benchmark_pack first",
        ))
    else:
        verdict = benchmark_pack.get("overall_verdict", "")
        if verdict == benchmark_required_verdict:
            checks.append(PreflightCheck(
                name="benchmark_pack",
                status="pass",
                message=f"benchmark verdict={verdict}",
            ))
        elif verdict in ("ties", "inconclusive"):
            checks.append(PreflightCheck(
                name="benchmark_pack",
                status="warn",
                message=f"benchmark verdict={verdict}",
                remediation="document why ties/inconclusive is acceptable",
            ))
        else:
            checks.append(PreflightCheck(
                name="benchmark_pack",
                status="fail",
                message=f"benchmark verdict={verdict}",
                remediation="strategy must beat its primary baseline",
            ))

    # Quality decisions -----------------------------------------------------
    blocking = [
        q for q in (quality_decisions or [])
        if q.get("decision") in ("rejected", "quarantined")
    ]
    if not quality_decisions:
        checks.append(PreflightCheck(
            name="data_quality",
            status="warn",
            message="no quality decisions supplied",
            remediation="aurora data quality-report --dataset NAME",
        ))
    elif blocking:
        names = sorted(q.get("symbol", "?") for q in blocking)
        checks.append(PreflightCheck(
            name="data_quality",
            status="fail",
            message=f"{len(blocking)} symbols rejected/quarantined: {names[:5]}",
            remediation="approve or replace the blocking symbols",
        ))
    else:
        checks.append(PreflightCheck(
            name="data_quality",
            status="pass",
            message=f"{len(quality_decisions)} symbols approved or warned",
        ))

    # Evidence pack ---------------------------------------------------------
    if not evidence_pack_present:
        checks.append(PreflightCheck(
            name="evidence_pack",
            status="fail",
            message="no evidence pack supplied",
            remediation="aurora report evidence-pack --strategy ID",
        ))
    elif not evidence_pack_hash_ok:
        checks.append(PreflightCheck(
            name="evidence_pack",
            status="fail",
            message="evidence pack hash check failed",
            remediation="regenerate the evidence pack",
        ))
    else:
        checks.append(PreflightCheck(
            name="evidence_pack",
            status="pass",
            message="evidence pack reproducible",
        ))

    # Research ledger -------------------------------------------------------
    checks.append(PreflightCheck(
        name="research_ledger",
        status="pass" if research_ledger_complete else "fail",
        message=(
            "ledger trail complete" if research_ledger_complete
            else "ledger missing required events"
        ),
        remediation=(
            "" if research_ledger_complete
            else "run validation through the research factory"
        ),
    ))

    # Execution model + broker ---------------------------------------------
    if not execution_model:
        checks.append(PreflightCheck(
            name="execution_model",
            status="fail",
            message="execution_model not named",
            remediation="set execution_model in strategy config",
        ))
    else:
        checks.append(PreflightCheck(
            name="execution_model",
            status="pass",
            message=f"execution_model={execution_model}",
        ))

    checks.append(PreflightCheck(
        name="kill_switch",
        status="pass" if kill_switch_armed else "fail",
        message=(
            "kill switch armed" if kill_switch_armed
            else "kill switch not armed"
        ),
        remediation=(
            "" if kill_switch_armed
            else "deployment.brokers.KillSwitch.arm() before promotion"
        ),
    ))

    checks.append(PreflightCheck(
        name="broker_health",
        status="pass" if broker_healthy else "fail",
        message=(
            "broker / paper adapter healthy" if broker_healthy
            else "broker / paper adapter unhealthy"
        ),
        remediation=(
            "" if broker_healthy
            else "investigate broker connection before submitting orders"
        ),
    ))

    checks.append(PreflightCheck(
        name="reconciliation",
        status="pass" if reconciliation_clean else "warn",
        message=(
            "reconciliation clean" if reconciliation_clean
            else "reconciliation not clean"
        ),
        remediation=(
            "" if reconciliation_clean
            else "explain or fix reconciliation diffs first"
        ),
    ))

    checks.append(PreflightCheck(
        name="capital_limits",
        status="pass" if capital_limits_set else "fail",
        message=(
            "capital limits set" if capital_limits_set
            else "capital limits missing"
        ),
        remediation=(
            "" if capital_limits_set
            else "set risk_limits.max_capital before paper/live"
        ),
    ))

    checks.append(PreflightCheck(
        name="rollback_plan",
        status="pass" if rollback_plan_present else "warn",
        message=(
            "rollback plan present" if rollback_plan_present
            else "rollback plan missing"
        ),
        remediation=(
            "" if rollback_plan_present
            else "document the rollback steps before live"
        ),
    ))

    return PreflightBundle(
        strategy_id=strategy_id,
        target_stage=target_stage,
        checks=tuple(checks),
        overrides=tuple(dict(o) for o in (overrides or [])),
    )


__all__ = [
    "CheckStatus",
    "PreflightBundle",
    "PreflightCheck",
    "build_preflight_bundle",
]
