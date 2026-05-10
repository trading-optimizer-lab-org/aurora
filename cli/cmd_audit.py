"""``forge audit`` subcommand group (R49 split).

P1.B auditor: run the 6 specialized reviewer agents against a strategy
+ backtest payload, or list the available reviewers and their HARD_FAIL
conditions.
"""
from __future__ import annotations

from ._shared import _runtime_error


# ---------------------------------------------------------------------------
# Auditor subcommands (P1.B)
# ---------------------------------------------------------------------------


def cmd_audit_run(args):
    """Run all auditor reviewers on a strategy and print/write the report.

    Inputs come from a JSON file passed via --backtest. Expected shape:
      {
        "strategy_spec":     {...},
        "backtest_results":  {...},
        "validation_results": {...} | null,
        "snapshot_id":        "..." | null,
        "extras":             {...} | null
      }
    """
    import json
    import os
    from aurora.agents.auditor import AuditorOrchestrator, ReviewContext
    from aurora.core.protocol_policy import ProtocolPolicy

    bt_path = args.backtest
    if not bt_path or not os.path.exists(bt_path):
        return _runtime_error(
            f"audit run: --backtest path not found: {bt_path!r}"
        )
    try:
        with open(bt_path, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
    except Exception as e:
        return _runtime_error(f"audit run: failed to read --backtest: {e}")

    pol = ProtocolPolicy.load()
    ctx = ReviewContext(
        strategy_id=args.strategy_id,
        strategy_spec=payload.get("strategy_spec") or {},
        backtest_results=payload.get("backtest_results") or {},
        validation_results=payload.get("validation_results"),
        snapshot_id=payload.get("snapshot_id"),
        policy=pol,
        extras=payload.get("extras") or {},
    )
    orch = AuditorOrchestrator.default()
    audit = orch.review(ctx)
    print(f"strategy_id:    {ctx.strategy_id}")
    print(f"reviewers run:  {len(audit.reports)}")
    print(f"hard_fail:      {audit.has_hard_fail}")
    print(f"agg_score:      {audit.aggregate_score:.3f}")
    for rep in audit.reports:
        print(f"  - {rep.reviewer:24s} score={rep.score:.3f} "
              f"findings={len(rep.findings)} hard_fail={rep.has_hard_fail()}")
    out_path = getattr(args, "output", None)
    if out_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".",
                        exist_ok=True)
            if str(out_path).lower().endswith(".md"):
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(audit.to_markdown())
            else:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(audit.to_json())
            print(f"wrote: {out_path}")
        except Exception as e:
            return _runtime_error(f"audit run: write {out_path!r} failed: {e}")
    return 1 if audit.has_hard_fail else 0


def cmd_audit_list_reviewers(args):
    """List the 6 default reviewers and their HARD_FAIL conditions."""
    from aurora.agents.auditor import AuditorOrchestrator
    orch = AuditorOrchestrator.default()
    print(f"AuditorOrchestrator.default(): {len(orch.reviewers)} reviewers")
    rules = {
        "HypothesisReviewer": [
            "hypothesis missing",
            "expected_edge_bps > 100 (smell test)",
        ],
        "DataLeakReviewer": [
            "lookahead_check failed",
            "feature timestamp > IS_TRAIN end",
            "fingerprint max_index > IS_TRAIN end (IS run)",
        ],
        "CostReviewer": [
            "backtest_costs < 50% of policy_cost_model (cost denial)",
        ],
        "RegimeReviewer": [
            "(no HARD_FAIL conditions; HIGH on single-regime dependence)",
        ],
        "RiskReviewer": [
            "max_drawdown > policy.risk_limits.max_drawdown_promotion_threshold",
            "max_leverage > policy.risk_limits.max_leverage",
            "max_position_concentration > policy.risk_limits.max_position_concentration",
            "|correlation_to_benchmark| > policy.risk_limits.max_correlation_to_benchmark",
        ],
        "DeploymentReviewer": [
            "planned_size > 10% of average daily volume",
        ],
    }
    for r in orch.reviewers:
        print(f"\n- {r.name}")
        for cond in rules.get(r.name, ["(no conditions documented)"]):
            print(f"    HARD_FAIL: {cond}")
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the ``audit`` subcommand group on the top-level subparsers."""
    p_audit = subparsers.add_parser(
        "audit",
        help="Run multi-agent auditor or list reviewers",
        description=(
            "P1.B auditor: run the 6 specialized reviewer agents against "
            "a strategy + backtest payload, or list the available "
            "reviewers and their HARD_FAIL conditions."
        ),
    )
    audit_sub = p_audit.add_subparsers(dest="audit_cmd", required=True)
    p_audit_run = audit_sub.add_parser(
        "run", help="Run all reviewers on a strategy",
        description=(
            "Run all 6 default reviewers on a strategy. Reads a JSON "
            "payload (strategy_spec + backtest_results + ...) from "
            "--backtest. Exit code 1 when any HARD_FAIL is found."
        ),
    )
    p_audit_run.add_argument("strategy_id", help="Strategy identifier (label)")
    p_audit_run.add_argument(
        "--backtest", required=True,
        help="Path to a JSON file containing strategy_spec + backtest_results.",
    )
    p_audit_run.add_argument(
        "--output", default=None,
        help="Optional output path. *.md emits markdown, anything else JSON.",
    )
    p_audit_run.set_defaults(func=cmd_audit_run)
    p_audit_list = audit_sub.add_parser(
        "list-reviewers",
        help="List the 6 default reviewers + their HARD_FAIL rules",
        description="List the default reviewers and their HARD_FAIL conditions.",
    )
    p_audit_list.set_defaults(func=cmd_audit_list_reviewers)
