"""``forge triage`` subcommand group (R49 split).

P2.A: vectorized triage backend for fast variant screening.

Note: ``cmd_research_triage`` lives in :mod:`aurora.cli.cmd_research`.
The ``register_research_triage`` helper in this module attaches the
late-bound ``research triage`` subparser onto the research subparsers
to mirror ``build_parser`` behaviour from before the R49 split.
"""
from __future__ import annotations

from ._shared import (
    _arg_error,
    _runtime_error,
    _resolve_strategy,
    _load_triage_config,
    _load_triage_prices,
)


# ---------------------------------------------------------------------------
# Triage subcommands (P2.A vectorized screening)
# ---------------------------------------------------------------------------


def _variants_from_yaml(path: str):
    """Read a YAML/JSON file containing a list of variants."""
    import json
    import os
    import yaml
    from aurora.triage import StrategyVariant
    if not os.path.exists(path):
        _arg_error(f"variants file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        data = json.loads(text) if text.strip() else {}
    else:
        data = yaml.safe_load(text) or {}
    raw = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        _arg_error(
            f"variants file {path!r} must have a top-level 'variants' list"
        )
    assert isinstance(raw, list)
    return [StrategyVariant.from_dict(d) for d in raw]


def cmd_triage_run(args):
    """Run a triage batch and write the result parquet to disk."""
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.triage import TriageEngine

    cfg = _load_triage_config(args)
    policy = ProtocolPolicy.load()
    engine = TriageEngine(cfg, policy)
    variants = _variants_from_yaml(args.variants)
    if not variants:
        return _runtime_error("variants file produced zero variants")
    if getattr(args, "prices", None):
        import pandas as pd
        prices = pd.read_parquet(args.prices)
        if not isinstance(prices.index, pd.DatetimeIndex):
            return _runtime_error(
                f"prices parquet at {args.prices!r} must have a DatetimeIndex"
            )
    else:
        sym = variants[0].universe[0] if variants[0].universe else "SPY"
        prices = _load_triage_prices(sym, cfg.triage_tier_only)
    batch = engine.triage_batch(prices, variants)
    batch.to_parquet(args.output)
    print(
        f"triage batch {batch.batch_id}: "
        f"{batch.n_variants} variants, {batch.n_promising} promising. "
        f"wrote {args.output}"
    )
    return 0


def cmd_triage_list_promising(args):
    """List promising variants from a saved batch parquet."""
    from aurora.triage import TriageBatch

    batch = TriageBatch.from_parquet(args.batch)
    promising = [r for r in batch.results if r.promising]
    promising.sort(
        key=lambda r: -(r.sharpe if r.sharpe == r.sharpe else -9.99)
    )
    top = int(getattr(args, "top", 20) or 20)
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(
            [r.to_dict() for r in promising[:top]], indent=2, default=str,
        ))
        return 0
    if not promising:
        print("(no promising variants in batch)")
        return 0
    for r in promising[:top]:
        print(
            f"{r.variant_id[:12]} sharpe={r.sharpe:.3f} "
            f"max_dd={r.max_dd:.3f} n_trades={r.n_trades}"
        )
    return 0


def cmd_triage_promote(args):
    """Re-run a promising variant on the official engine."""
    from dataclasses import replace as _replace
    from aurora.core.costs import IBKR_costs
    from aurora.core.engine import run_backtest
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.triage import TriageBatch, TriageEngine

    batch = TriageBatch.from_parquet(args.batch)
    target = next(
        (r for r in batch.results if r.variant_id == args.variant_id),
        None,
    )
    if target is None:
        return _runtime_error(
            f"variant_id {args.variant_id!r} not found in batch"
        )
    if not target.promising:
        return _runtime_error(
            f"variant_id {args.variant_id!r} was rejected by triage; "
            "only promising variants can be promoted to the official engine"
        )
    cfg = _load_triage_config(args)
    policy = ProtocolPolicy.load()
    engine = TriageEngine(cfg, policy)
    # Re-mint the token in-process so the single-use machinery accepts it.
    engine._tokens[target.variant_id] = target.promotion_token or "cli_token"
    target = _replace(
        target,
        promotion_token=engine._tokens[target.variant_id],
    )
    sym = (target.metadata.get("universe") or ["SPY"])[0]
    prices = _load_triage_prices(sym, cfg.triage_tier_only)[sym]
    cls_name = target.metadata.get("strategy_class", "").rsplit(".", 1)[-1]
    cls = _resolve_strategy(cls_name)
    strat = cls(**(target.metadata.get("params") or {}))

    def _runner(_prices, **_kw):
        return run_backtest(_prices, strat.signals, costs=IBKR_costs)

    res = engine.promote_to_official(target, _runner, prices=prices)
    print(
        f"promoted {target.variant_id[:12]} -> "
        f"sharpe={res.sharpe:.3f} cagr={res.cagr:.3f} mdd={res.mdd:.3f}"
    )
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the top-level ``triage`` subcommand group."""
    p_triage = subparsers.add_parser(
        "triage",
        help="Vectorized triage screening for thousands of variants",
        description=(
            "P2.A vectorized triage. Runs a fast screen over a list of "
            "StrategyVariant proposals, marks the promising ones, and "
            "writes the batch to a parquet file. Promising variants must "
            "still be re-run on the official engine; triage is NEVER a "
            "promotion verdict."
        ),
    )
    triage_sub = p_triage.add_subparsers(dest="triage_cmd", required=True)

    p_t_run = triage_sub.add_parser(
        "run", help="Score a variants batch and write a parquet result",
    )
    p_t_run.add_argument(
        "--variants", required=True,
        help="Path to a YAML/JSON file with a top-level 'variants' list",
    )
    p_t_run.add_argument(
        "--output", required=True,
        help="Output parquet path for the scored batch",
    )
    p_t_run.add_argument(
        "--config-path", default=None, dest="config_path",
        help="Optional path to a triage.yaml override",
    )
    p_t_run.add_argument(
        "--prices", default=None,
        help="Optional parquet of prices (DatetimeIndex). Overrides the "
             "load_tier(<symbol>) auto-resolve.",
    )
    p_t_run.add_argument(
        "--use-vectorbt", action="store_true",
        help="Route through the optional vectorbt backend if installed",
    )
    p_t_run.add_argument(
        "--tier", default=None,
        help="Override triage_tier_only (must be IS_TRAIN/IS_VALID/OOS_DEV)",
    )
    p_t_run.set_defaults(func=cmd_triage_run)

    p_t_list = triage_sub.add_parser(
        "list-promising",
        help="List the promising variants from a saved batch parquet",
    )
    p_t_list.add_argument(
        "--batch", required=True,
        help="Path to the batch parquet produced by `forge triage run`",
    )
    p_t_list.add_argument(
        "--top", type=int, default=20,
        help="Show the top N promising variants by Sharpe (default 20)",
    )
    p_t_list.add_argument("--json", action="store_true")
    p_t_list.set_defaults(func=cmd_triage_list_promising)

    p_t_prom = triage_sub.add_parser(
        "promote",
        help="Re-run a promising variant on the official engine",
    )
    p_t_prom.add_argument("--batch", required=True,
                          help="Batch parquet produced by `forge triage run`")
    p_t_prom.add_argument("--variant-id", required=True, dest="variant_id",
                          help="variant_id to re-run")
    p_t_prom.add_argument(
        "--config-path", default=None, dest="config_path",
    )
    p_t_prom.add_argument(
        "--tier", default=None,
        help="Override triage_tier_only when reloading prices",
    )
    p_t_prom.set_defaults(func=cmd_triage_promote)


def register_research_triage(research_sub) -> None:
    """Register the trailing ``research triage`` subparser.

    This must be called AFTER :func:`register` (top-level triage) so the
    subparser order in ``forge research --help`` matches the pre-split
    layout exactly.
    """
    from .cmd_research import cmd_research_triage

    p_rs_triage = research_sub.add_parser(
        "triage",
        help="Pre-screen a specs YAML through the triage backend (no IS/WF/OOS).",
    )
    p_rs_triage.add_argument("specs",
                              help="Path to a YAML/JSON file with 'specs:' list")
    p_rs_triage.add_argument(
        "--threshold", default=None,
        help="Comma-separated overrides, e.g. 'sharpe=0.5,max_dd=-0.30'",
    )
    p_rs_triage.add_argument(
        "--config-path", default=None, dest="config_path",
        help="Optional path to a triage.yaml override",
    )
    p_rs_triage.add_argument(
        "--tier", default=None,
        help="Override triage_tier_only",
    )
    p_rs_triage.set_defaults(func=cmd_research_triage)
