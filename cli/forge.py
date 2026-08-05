"""Aurora CLI entry point (legacy file name ``forge.py`` retained).

Quick start::

    forge --help
    forge list-strategies

Run ``forge --help`` for the full list of subcommands and per-command
flags. Per-subcommand documentation is generated from each parser's
``description=`` argument below.

R49: this module is now a slim dispatcher. The actual subcommand
implementations live in :mod:`aurora.cli.cmd_*` modules; shared helpers
live in :mod:`aurora.cli._shared`. Public symbols (``main``,
``build_parser``) remain importable from this module so external
callers and tests have a stable surface.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import (
    cmd_agent,
    cmd_audit,
    cmd_crypto,
    cmd_data,
    cmd_doctor,
    cmd_export,
    cmd_github,
    cmd_ops,
    cmd_policy,
    cmd_research,
    cmd_run as _cmd_run_module,
    cmd_triage,
)
from ._shared import (
    _CLIArgError,
    _add_global_flags,
    _load_global_config,
)

# Re-exports kept for back-compat with code that imports symbols from
# ``aurora.cli.forge`` directly. These are intentionally small and forward
# to ``_shared`` / ``cmd_run`` so the public surface is preserved.
from ._shared import (  # noqa: F401  (back-compat re-exports)
    _DEFAULT_ANALYTICAL_TIER,
    _TIER_CHOICES,
    _add_tier_arg,
    _arg_error,
    _costs_from,
    _dry_run_summary,
    _KNOWN_TOP_LEVEL_CONFIG_KEYS,
    _policy_ceremony_env_flag,
    _policy_tier_choices,
    _resolve_package_version,
    _resolve_strategy,
    _resolve_tier_load,
    _runtime_error,
    _strategy_library,
    _strategy_spec_from_yaml,
    _strategy_specs_from_yaml,
    _validate_config_schema,
    _load_triage_config,
    _load_triage_prices,
)
from .cmd_run import (  # noqa: F401  (back-compat re-exports)
    cmd_attribute,
    cmd_bench,
    cmd_config_init,
    cmd_config_show,
    cmd_cscv,
    cmd_dashboard,
    cmd_factor,
    cmd_fracdiff,
    cmd_freeze,
    cmd_label,
    cmd_list_strategies,
    cmd_preflight,
    cmd_purge_cv,
    cmd_run,
    cmd_search,
    cmd_search_multi,
    cmd_tearsheet,
    cmd_validate,
)
from .cmd_data import (  # noqa: F401
    cmd_data_fetch,
    cmd_data_list_providers,
    cmd_data_verify,
)
from .cmd_crypto import (  # noqa: F401
    cmd_crypto_allow_live,
    cmd_crypto_balance,
    cmd_crypto_exchanges,
    cmd_crypto_fetch,
    cmd_crypto_positions,
    cmd_crypto_submit_order,
)
from .cmd_policy import (  # noqa: F401
    cmd_policy_show,
    cmd_policy_verify,
)
from .cmd_research import (  # noqa: F401
    _load_research_factory,
    cmd_research_archive,
    cmd_research_batch,
    cmd_research_generate,
    cmd_research_lineage,
    cmd_research_promote,
    cmd_research_review_queue,
    cmd_research_submit,
    cmd_research_triage,
)
from .cmd_audit import (  # noqa: F401
    cmd_audit_list_reviewers,
    cmd_audit_run,
)
from .cmd_agent import (  # noqa: F401
    cmd_agent_audit_verify,
    cmd_agent_commit,
    cmd_agent_push,
    cmd_agent_stage,
    cmd_agent_token_issue,
    cmd_agent_token_list,
    cmd_agent_token_revoke,
)
from .cmd_ops import (  # noqa: F401
    cmd_ops_alerts,
    cmd_ops_daily,
    cmd_ops_summary,
)
from .cmd_export import (  # noqa: F401
    cmd_export_lean,
    cmd_export_lean_list,
    cmd_export_verify,
)
from .cmd_triage import (  # noqa: F401
    cmd_triage_list_promising,
    cmd_triage_promote,
    cmd_triage_run,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forge",
        description="Aurora CLI -- backtest, validate, search, report.",
        epilog=(
            "Quick start:\n"
            "  forge --help\n"
            "  forge list-strategies\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_global_flags(p)
    sub = p.add_subparsers(dest="cmd", required=True)

    # Order matches the original build_parser exactly:
    #   run, validate, search, list-strategies, tearsheet, bench, config,
    #   preflight, label, factor, attribute, purge-cv, fracdiff, cscv,
    #   search-multi, freeze, data, crypto, export, dashboard, research,
    #   audit, policy, ops, agent, triage
    _cmd_run_module.register(sub)            # run, validate, search,
                                             # list-strategies, tearsheet,
                                             # bench, config, preflight,
                                             # label, factor, attribute,
                                             # purge-cv, fracdiff, cscv,
                                             # search-multi, freeze
    cmd_data.register(sub)           # data
    cmd_crypto.register(sub)         # crypto
    cmd_export.register(sub)         # export
    _cmd_run_module.register_dashboard(sub)  # dashboard
    research_sub = cmd_research.register(sub)  # research
    cmd_audit.register(sub)          # audit
    cmd_policy.register(sub)         # policy
    cmd_ops.register(sub)            # ops
    cmd_agent.register(sub)          # agent
    cmd_doctor.register(sub)         # doctor (R187)
    cmd_github.register(sub)         # github performance framework
    cmd_triage.register(sub)         # triage (top-level)

    # Late-bound: ``research triage`` parser is appended after the
    # top-level triage group so the help-output order matches the
    # pre-split layout exactly.
    cmd_triage.register_research_triage(research_sub)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # Configure logging for the aurora namespace based on --log-level.
    log_level = getattr(args, "log_level", "INFO")
    try:
        from aurora.core.logging import configure_logging
        configure_logging(level=log_level)
    except Exception:
        # Logging setup should never block command execution.
        pass
    # Eagerly validate --config so a missing path fails fast for any command,
    # including those that do not consult the config (e.g. list-strategies).
    try:
        if getattr(args, "config", None):
            _load_global_config(args)
        return args.func(args)
    except _CLIArgError as e:
        # Argparse-style error: usage banner + exit 2.
        parser.error(e.message)


def _exit_after_main(exit_code: int | None) -> None:
    """Exit a module invocation without corrupting data-verify failures.

    PyArrow can abort during Linux interpreter teardown after a failed parquet
    integrity check, replacing the intentional exit code 1 with SIGABRT.  The
    command is read-only and its output is complete at this point, so flush it
    and bypass native-library teardown only for that explicit failure path.
    """
    normalized = int(exit_code or 0)
    if normalized and sys.argv[1:3] == ["data", "verify"]:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(normalized)
    raise SystemExit(normalized)


if __name__ == "__main__":
    _exit_after_main(main())
