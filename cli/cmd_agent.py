"""``forge agent`` subcommand group (R49 split).

P1.A: scoped-token gateway for non-human actors.
"""
from __future__ import annotations

from ._shared import _runtime_error  # noqa: F401  (kept for parity with original)


# ---------------------------------------------------------------------------
# Agent gateway commands (P1.A)
# ---------------------------------------------------------------------------


def _agent_gateway_from_args(args):
    """Construct an :class:`AgentGateway` using config + args overrides.

    Honors ``--audit-path`` if provided, otherwise reads
    ``aurora/config/agent_gateway.yaml``.
    """
    import os as _os  # noqa: F401  (parity with original module)
    from pathlib import Path as _Path
    import yaml
    from aurora.agent_gateway import AgentGateway, GatewayPolicy

    cfg_path = _Path(__file__).resolve().parent.parent / "config" / "agent_gateway.yaml"
    data = {}
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    from aurora.core.runtime_paths import gateway_audit_path as _gw_audit_path
    audit_path = (
        getattr(args, "audit_path", None)
        or data.get("audit_path")
        or str(_gw_audit_path())
    )
    policy = GatewayPolicy(
        paper_only_default=bool(data.get("paper_only_default", True)),
        require_human_commit_for_live=bool(
            data.get("require_human_commit_for_live", True)
        ),
        require_human_commit_for_paper=bool(
            data.get("require_human_commit_for_paper", False)
        ),
        audit_chain_verify_on_startup=bool(
            data.get("audit_chain_verify_on_startup", True)
        ),
        max_token_lifetime_days=int(data.get("max_token_lifetime_days", 30)),
        allow_self_modify=bool(data.get("allow_self_modify", False)),
    )
    _Path(audit_path).parent.mkdir(parents=True, exist_ok=True)
    return AgentGateway(policy=policy, audit_path=_Path(audit_path))


def cmd_agent_token_issue(args):
    from aurora.agent_gateway import TokenScope, issue_token

    scopes = frozenset(TokenScope(s.strip()) for s in args.scopes.split(",") if s.strip())
    allow = frozenset(s.strip() for s in (args.allowlist or "").split(",") if s.strip())
    token = issue_token(
        actor=args.actor,
        scopes=scopes,
        expires_in_days=int(args.expires_days),
        allowlist_symbols=allow,
        max_order_notional_usd=float(args.max_order_notional),
        max_daily_notional_usd=float(args.max_daily_notional),
        cooldown_seconds=int(args.cooldown),
        paper_only=bool(args.paper_only),
    )
    import json as _json
    print(_json.dumps(token.to_dict(), sort_keys=True, indent=2))
    return 0


def cmd_agent_token_list(args):
    gw = _agent_gateway_from_args(args)
    import json as _json
    out = [t.to_dict() for t in gw.list_active()]
    print(_json.dumps(out, sort_keys=True, indent=2))
    return 0


def cmd_agent_token_revoke(args):
    gw = _agent_gateway_from_args(args)
    gw.revoke(args.token_id)
    print(f"revoked {args.token_id}")
    return 0


def cmd_agent_audit_verify(args):
    gw = _agent_gateway_from_args(args)
    report = gw.audit.verify_chain()
    print(f"entries:       {report['n_entries']}")
    print(f"ok:            {report['ok']}")
    print(f"broken_index:  {report['broken_index']}")
    return 0 if report["ok"] else 1


def cmd_agent_stage(args):
    """Read action JSON + token JSON, stage, print staged_id."""
    import json as _json
    from aurora.agent_gateway import (
        ActionRequest, AgentToken, TokenScope,
    )

    with open(args.action_path, "r", encoding="utf-8") as fh:
        adata = _json.load(fh)
    with open(args.token, "r", encoding="utf-8") as fh:
        tdata = _json.load(fh)
    token = AgentToken.from_dict(tdata)
    action = ActionRequest(
        kind=adata["kind"],
        scope=TokenScope(adata["scope"]),
        symbol=adata.get("symbol"),
        notional_usd=float(adata.get("notional_usd", 0.0)),
        payload=adata.get("payload", {}),
    )
    gw = _agent_gateway_from_args(args)
    gw.register_token(token)
    staged = gw.stage(token, action)
    print(_json.dumps({
        "staged_id": staged.staged_id,
        "expires_at": staged.expires_at.isoformat(),
        "request_digest": staged.request_digest,
    }, indent=2))
    return 0


def cmd_agent_commit(args):
    gw = _agent_gateway_from_args(args)
    committed = gw.commit(args.staged_id, human_signature=args.signature)
    import json as _json
    print(_json.dumps({
        "committed_id": committed.committed_id,
        "staged_id": committed.staged.staged_id,
    }, indent=2))
    return 0


def cmd_agent_push(args):
    gw = _agent_gateway_from_args(args)  # noqa: F841
    # The CLI cannot reconstruct a CommittedAction from disk yet (the
    # in-memory map only persists for the lifetime of the gateway). For
    # now this is a safe error rather than a no-op.
    return _runtime_error(
        "agent push requires an in-process CommittedAction; "
        "use the Python API (gateway.push) or extend the CLI to persist "
        "committed actions to disk."
    )


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the ``agent`` subcommand group on the top-level subparsers."""
    p_agent = subparsers.add_parser(
        "agent",
        help="Agent gateway: tokens, staging, commit/push, audit verify",
        description=(
            "Issue / revoke / list scoped agent tokens, stage actions, "
            "counter-sign commits, and verify the append-only audit chain."
        ),
    )
    agent_sub = p_agent.add_subparsers(dest="agent_cmd", required=True)

    p_ag_issue = agent_sub.add_parser(
        "token-issue", help="Issue a fresh signed agent token",
    )
    p_ag_issue.add_argument("--actor", required=True,
                             help="Actor name / LLM model id")
    p_ag_issue.add_argument(
        "--scopes", required=True,
        help="Comma-separated scopes: read_data,read_reports,propose,"
             "backtest_is,valid_oos_dev,paper_trade,live_trade",
    )
    p_ag_issue.add_argument("--expires-days", type=int, default=7,
                             dest="expires_days")
    p_ag_issue.add_argument(
        "--allowlist", default="",
        help="Comma-separated symbol allowlist (empty = any)",
    )
    p_ag_issue.add_argument("--max-order-notional", type=float, default=10000.0,
                             dest="max_order_notional")
    p_ag_issue.add_argument("--max-daily-notional", type=float, default=50000.0,
                             dest="max_daily_notional")
    p_ag_issue.add_argument("--cooldown", type=int, default=5,
                             help="Seconds between actions")
    p_ag_issue.add_argument("--paper-only", action="store_true", default=True,
                             dest="paper_only",
                             help="Force paper_only flag (default ON)")
    p_ag_issue.add_argument("--allow-live", action="store_false",
                             dest="paper_only",
                             help="Allow LIVE_TRADE scope on this token")
    p_ag_issue.set_defaults(func=cmd_agent_token_issue)

    p_ag_list = agent_sub.add_parser(
        "token-list", help="List currently registered active tokens",
    )
    p_ag_list.add_argument("--audit-path", default=None, dest="audit_path")
    p_ag_list.set_defaults(func=cmd_agent_token_list)

    p_ag_revoke = agent_sub.add_parser(
        "token-revoke", help="Revoke a token by id",
    )
    p_ag_revoke.add_argument("token_id")
    p_ag_revoke.add_argument("--audit-path", default=None, dest="audit_path")
    p_ag_revoke.set_defaults(func=cmd_agent_token_revoke)

    p_ag_audit = agent_sub.add_parser(
        "audit-verify", help="Verify the audit chain (exit 1 on tamper)",
    )
    p_ag_audit.add_argument("--audit-path", default=None, dest="audit_path")
    p_ag_audit.set_defaults(func=cmd_agent_audit_verify)

    p_ag_stage = agent_sub.add_parser(
        "stage", help="Stage an action from a JSON description",
    )
    p_ag_stage.add_argument("action_path", help="Path to action JSON")
    p_ag_stage.add_argument("--token", required=True,
                             help="Path to a token JSON file")
    p_ag_stage.add_argument("--audit-path", default=None, dest="audit_path")
    p_ag_stage.set_defaults(func=cmd_agent_stage)

    p_ag_commit = agent_sub.add_parser(
        "commit", help="Commit a staged action with a human signature",
    )
    p_ag_commit.add_argument("staged_id")
    p_ag_commit.add_argument("--signature", default=None,
                              help="hmac of staged_id with QF_OPERATOR_KEY")
    p_ag_commit.add_argument("--audit-path", default=None, dest="audit_path")
    p_ag_commit.set_defaults(func=cmd_agent_commit)

    p_ag_push = agent_sub.add_parser(
        "push", help="Execute a committed action (programmatic API only)",
    )
    p_ag_push.add_argument("committed_id")
    p_ag_push.add_argument("--audit-path", default=None, dest="audit_path")
    p_ag_push.set_defaults(func=cmd_agent_push)
