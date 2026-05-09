"""Aurora CLI entry point (legacy file name ``forge.py`` retained).

Quick start::

    forge --help
    forge list-strategies

Run ``forge --help`` for the full list of subcommands and per-command
flags. Per-subcommand documentation is generated from each parser's
``description=`` argument below.
"""
from __future__ import annotations
import argparse
import sys

from aurora.core.seed import set_global_seed
from aurora.core.costs import IBKR_costs, ZERO_costs


# ---------------------------------------------------------------------------
# Error UX helpers
# ---------------------------------------------------------------------------


class _CLIArgError(SystemExit):
    """Argument error raised inside a command; converted to ``parser.error``
    by ``main`` so argparse prints the usage banner and exits with code 2."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _arg_error(message: str) -> None:
    """Raise a structured argument error.

    ``main`` catches this and routes it through ``parser.error`` so the user
    sees the standard argparse usage banner + exit code 2.
    """
    raise _CLIArgError(message)


def _runtime_error(message: str) -> int:
    """Print a runtime failure to stderr and return exit code 1.

    Use for environment / IO / dependency failures (not argument validation).
    """
    print(f"forge: {message}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# Strategy library helpers
# ---------------------------------------------------------------------------


def _strategy_library() -> dict:
    """Build name -> class map from aurora.strategies.library.__all__."""
    from aurora.strategies import library as lib_mod
    return {name: getattr(lib_mod, name) for name in lib_mod.__all__
            if hasattr(lib_mod, name)}


def _resolve_strategy(name: str):
    """Resolve a strategy by name with import fallback.

    Lookup order:
        1. ``quantforge.strategies.library.__all__`` map.
        2. Direct import of ``quantforge.strategies.library.<name>`` and pick
           a class attribute matching ``name``.
        3. Raise SystemExit listing the known strategies.
    """
    lib = _strategy_library()
    if name in lib:
        return lib[name]

    # Fallback: walk every submodule of ``quantforge.strategies.library``
    # looking for a class attribute matching ``name`` exactly. Names like
    # ``MACross`` do not lowercase to a valid module path
    # (``ma_cross.py``), so the previous str.lower() guess silently
    # produced ``ImportError`` and skipped the fallback entirely. Using
    # ``pkgutil.iter_modules`` makes the lookup independent of how the
    # filename is spelled.
    import importlib
    import pkgutil

    from aurora.strategies import library as lib_pkg

    for info in pkgutil.iter_modules(lib_pkg.__path__):
        try:
            mod = importlib.import_module(
                f"{lib_pkg.__name__}.{info.name}"
            )
        except ImportError:
            continue
        cls = getattr(mod, name, None)
        if cls is not None and isinstance(cls, type):
            return cls

    _arg_error(f"Unknown strategy '{name}'. Available: {sorted(lib)}")


def _costs_from(name: str):
    return IBKR_costs if name == "ibkr" else ZERO_costs


# ---------------------------------------------------------------------------
# --tier helper (round-3 audit fix)
# ---------------------------------------------------------------------------
#
# Several CLI commands are post-validation analytics: they want to look
# at recent strategy behaviour, not run a fitness loop. Before round 3
# they all called ``load_asset(include_oos=True)`` on the full cached
# series, which silently included OOS_LOCKED (2021-2024) and FORWARD
# (>=2025) bars even when the user only wanted to inspect the
# protocol-public OOS_DEV slice. The audit asks for an explicit
# ``--tier`` switch so the read is bounded at the source.

# P0.A: valid tier choices come from
# :class:`quantforge.core.protocol_policy.ProtocolPolicy`. The legacy
# ``is_all`` and ``full`` synthetic choices are kept (they are not
# protocol tiers themselves -- ``is_all`` is IS_TRAIN+IS_VALID and
# ``full`` is the env-gated all-tier pass-through), but the five
# protocol tier names are sourced from the active policy.
def _policy_tier_choices() -> tuple[str, ...]:
    """Return the lower-cased tier names declared by the active policy."""
    try:
        from aurora.core.protocol_policy import get_active_policy
        names = tuple(t.lower() for t in get_active_policy().tiers.keys())
    except Exception:
        # Defensive: never block the CLI if the policy fails to load.
        names = ("is_train", "is_valid", "oos_dev", "oos_locked", "forward")
    extras = ("is_all", "full")
    return tuple(list(names) + [e for e in extras if e not in names])


_TIER_CHOICES = _policy_tier_choices()

# Default tier for analytical CLI commands. OOS_DEV is the most common
# "look at recent post-validation behaviour" slice.
_DEFAULT_ANALYTICAL_TIER = "oos_dev"


def _policy_ceremony_env_flag(name: str) -> str:
    """Return the env_flag for a named ceremony from the active policy.

    Falls back to ``name`` itself if the policy is unavailable (defensive
    parity with :func:`_policy_tier_choices`).
    """
    try:
        from aurora.core.protocol_policy import get_active_policy
        cer = get_active_policy().oos_ceremonies.get(name)
        if cer is not None:
            return cer.env_flag
    except Exception:
        pass
    return name


def _resolve_tier_load(asset: str, tier: str) -> "pd.Series":
    """Load price series respecting the CLI ``--tier`` semantics.

    Round-3 audit fix: every analytical CLI command (run, tearsheet,
    factor, attribute, label, fracdiff, purge-cv) must route through
    this helper instead of calling
    ``load_asset(include_oos=True, oos_purpose=...)`` directly. The
    helper enforces the ceremony rules:

      * ``is_train`` / ``is_valid``: read only the relevant in-sample
        slice; no OOSGuard required.
      * ``oos_dev`` (default): read up to OOS_DEV_END under
        ``oos_purpose="cli_analysis"`` so the read is logged AND
        persisted to the lock file.
      * ``oos_locked``: requires an active
        ``OOSGuard("explicit_unlock_oos_locked")`` -- the ceremony
        wrap is the user's responsibility (the helper raises if the
        ceremony is missing).
      * ``forward``: requires an active
        ``OOSGuard("explicit_unlock_forward")``.
      * ``is_all``: IS_TRAIN + IS_VALID combined.
      * ``full``: the legacy "everything" pass-through. Requires the
        environment variable ``QF_ALLOW_FULL_TIER=1`` to opt in
        because it leaks every tier into the analyser, including
        OOS_LOCKED and FORWARD.
    """
    import os
    import pandas as pd  # noqa: F401  (used in type hint string)
    from aurora.core.data_layer import load_asset
    from aurora.core.data_tiers import (
        load_tier,
        load_up_to_tier,
    )

    tier_norm = (tier or _DEFAULT_ANALYTICAL_TIER).lower()
    if tier_norm not in _TIER_CHOICES:
        _arg_error(
            f"--tier must be one of {sorted(_TIER_CHOICES)} (got {tier!r})"
        )

    if tier_norm == "full":
        # Ceremony: explicit env var. Without it we refuse the read.
        from aurora.core.env_compat import aurora_env
        if aurora_env("AU_ALLOW_FULL_TIER", "QF_ALLOW_FULL_TIER") != "1":
            _arg_error(
                "--tier full is gated: set AU_ALLOW_FULL_TIER=1 to opt in. "
                "This tier leaks OOS_LOCKED + FORWARD into the analyser."
            )
        # P2.3 round-4 audit: the env var alone is not enough. Require
        # an active OOSGuard("explicit_unlock_full_tier") so the read
        # is auditable in the lock file alongside other ceremony unlocks.
        from aurora.core.data_layer import OOSGuard as _OOSGuard
        active = _OOSGuard.active()
        if active is None or active.phase != "explicit_unlock_full_tier":
            _arg_error(
                "--tier full requires an active "
                "OOSGuard('explicit_unlock_full_tier'); "
                "set QF_ALLOW_FULL_TIER=1 AND wrap the call in the ceremony "
                "context manager."
            )
        return load_asset(
            asset, include_oos=True,
            oos_purpose="cli_analysis_full_tier",
        )

    if tier_norm == "is_all":
        # IS_TRAIN + IS_VALID -- bounded by IS_VALID end (2012-12-31).
        # No OOS read; no guard required.
        return load_up_to_tier(asset, max_tier="IS_VALID")

    # Everything else maps directly to a tier slice.
    tier_upper_map = {
        "is_train": "IS_TRAIN",
        "is_valid": "IS_VALID",
        "oos_dev": "OOS_DEV",
        "oos_locked": "OOS_LOCKED",
        "forward": "FORWARD",
    }
    upper = tier_upper_map[tier_norm]
    # OOS-bearing tiers want an oos_purpose so the lock-file audit fires.
    purpose = (
        "cli_analysis"
        if upper in ("OOS_DEV", "OOS_LOCKED", "FORWARD")
        else None
    )
    return load_tier(asset, tier=upper, oos_purpose=purpose)


def _add_tier_arg(parser, *, default: str = _DEFAULT_ANALYTICAL_TIER) -> None:
    """Attach the standard ``--tier`` argument to an analytical subparser."""
    parser.add_argument(
        "--tier", default=default, choices=list(_TIER_CHOICES),
        help=(
            "Data tier to load (round-3 protocol fix). "
            "Default: oos_dev. "
            "'oos_locked' / 'forward' require an OOSGuard ceremony. "
            "'full' requires QF_ALLOW_FULL_TIER=1 in the environment."
        ),
    )


# ---------------------------------------------------------------------------
# Config loader (Task 1.5)
# ---------------------------------------------------------------------------


_KNOWN_TOP_LEVEL_CONFIG_KEYS = {
    "data", "costs", "validation", "ga", "seed", "log_level",
}


def _validate_config_schema(path) -> None:
    """Reject unknown top-level keys in the YAML/TOML config file.

    Pydantic's default behaviour is to silently drop unknown keys. We want
    early, loud failure on typos like ``cost`` instead of ``costs``.
    """
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        # Caller's loader will raise FileNotFoundError -> SystemExit; let it.
        return
    suffix = p.suffix.lower()
    raw: dict
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise SystemExit(_runtime_error(f"yaml not available to validate {p}: {e}")) from e
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    elif suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore
            except ImportError as e:
                raise SystemExit(_runtime_error(f"tomllib not available to validate {p}: {e}")) from e
        with p.open("rb") as f:
            raw = tomllib.load(f)
    else:
        _arg_error(
            f"Unsupported config extension: {suffix}. Use .yaml/.yml/.toml"
        )

    if not isinstance(raw, dict):
        _arg_error(f"Config root must be a mapping, got {type(raw).__name__}")

    unknown = sorted(set(raw) - _KNOWN_TOP_LEVEL_CONFIG_KEYS)
    if unknown:
        _arg_error(
            f"Config {p} has unknown top-level keys: {unknown}. "
            f"Allowed: {sorted(_KNOWN_TOP_LEVEL_CONFIG_KEYS)}"
        )


def _load_global_config(args):
    """Load ForgeConfig from --config path if provided, else defaults.

    Returns a ForgeConfig. Errors propagate as SystemExit.

    NOTE: at the moment the only subcommands that *act* on the loaded
    ``ForgeConfig`` are ``dry-run`` (via :func:`_dry_run_summary`) and
    ``config show``. The ``run``, ``search`` and ``validate`` subcommands
    still drive themselves from CLI flags and the per-strategy spec, so
    passing ``--config`` to them currently has no effect outside of a dry
    run. Threading ``cfg.validation.*`` and friends into those subcommands
    is tracked separately.
    """
    from aurora.core.config import default_config, load_config
    path = getattr(args, "config", None)
    if not path:
        return default_config()
    _validate_config_schema(path)
    try:
        return load_config(path)
    except FileNotFoundError as e:
        raise SystemExit(_runtime_error(f"Config file not found: {path}")) from e
    except Exception as e:
        raise SystemExit(_runtime_error(f"Failed to load config {path}: {e}")) from e


# ---------------------------------------------------------------------------
# Dry-run helper
# ---------------------------------------------------------------------------


def _dry_run_summary(args, cfg) -> None:
    """Print the resolved configuration that ``run/search/validate`` would use.

    Includes data range, strategy + params, costs profile, and the gate
    parameters relevant to the subcommand. Does not execute anything.
    """
    print("=" * 70)
    print(f"DRY-RUN: {getattr(args, 'cmd', '<cmd>')}")
    print("=" * 70)
    print(f"Strategy : {getattr(args, 'strategy', None)}")
    print(f"Asset    : {getattr(args, 'asset', None)}")
    print(f"Seed     : {getattr(args, 'seed', None)}")
    print(f"Costs    : {getattr(args, 'costs', None)}")
    print(
        "Data IS  : "
        f"{cfg.data.is_start} -> {cfg.data.is_end}"
    )
    print(
        "Data OOS : "
        f"{cfg.data.oos_start} -> {cfg.data.oos_end}"
    )
    if getattr(args, "cmd", None) == "validate":
        print(f"n-trials : {getattr(args, 'n_trials', None)}")
        print(f"mc-paths : {getattr(args, 'mc_paths', None)}")
    if getattr(args, "cmd", None) == "search":
        print(f"population : {getattr(args, 'population', None)}")
        print(f"generations: {getattr(args, 'generations', None)}")
        print(f"skip-oos   : {getattr(args, 'skip_oos', None)}")
        print(f"oos-top    : {getattr(args, 'oos_top', None)}")
    print(
        "Validation thresholds: "
        f"min_wf_pass={cfg.validation.min_wf_pass} "
        f"spp_max_cv={cfg.validation.spp_max_cv} "
        f"min_dsr={cfg.validation.min_dsr}"
    )
    print("=" * 70)


# ---------------------------------------------------------------------------
# Existing commands (run / validate / search) -- kept stable
# ---------------------------------------------------------------------------


def cmd_validate(args):
    from aurora.validation.pipeline import validate_pipeline
    from aurora.core.data_layer import OOSGuard
    from aurora.core.data_tiers import load_up_to_tier

    cfg = _load_global_config(args)
    if getattr(args, "dry_run", False):
        _dry_run_summary(args, cfg)
        return 0
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)

    # P2.2 round-4 audit: --tier knob for formal validation. Default
    # remains oos_dev (the post-GA dev tier). Selecting oos_locked or
    # forward requires (a) the matching ``--i-understand-ceremony``
    # flag AND (b) is wrapped in an explicit OOSGuard ceremony.
    tier_arg = (getattr(args, "tier", "oos_dev") or "oos_dev").lower()
    if tier_arg not in ("oos_dev", "oos_locked", "forward"):
        _arg_error(
            f"--tier must be one of oos_dev|oos_locked|forward (got {tier_arg!r})"
        )

    if tier_arg in ("oos_locked", "forward"):
        if not getattr(args, "i_understand_ceremony", False):
            _arg_error(
                f"--tier {tier_arg} requires --i-understand-ceremony to "
                "acknowledge that you are unsealing a locked tier."
            )

    tier_map = {
        "oos_dev": ("OOS_DEV", "post_ga_validation", "OOS_DEV"),
        "oos_locked": (
            "OOS_LOCKED", "explicit_unlock_oos_locked", "OOS_LOCKED",
        ),
        "forward": ("FORWARD", "explicit_unlock_forward", "FORWARD"),
    }
    max_tier, guard_phase, oos_tier = tier_map[tier_arg]

    # Round-3 audit fix: load only IS + chosen tier (cap at end of
    # max_tier). The legacy ``load_asset(include_oos=True)`` returned
    # every cached bar.
    #
    # ``require_snapshot=True`` -- formal validation must run against a
    # frozen snapshot for reproducibility; if no SnapshotStore entry
    # exists the load falls back to the parquet cache with a warning,
    # and emits ``RuntimeError`` if neither is available.
    with OOSGuard(guard_phase):
        prices = load_up_to_tier(
            args.asset, max_tier=max_tier, require_snapshot=True,
        )

    spec = cls.spec()

    def factory():
        return cls(**spec.params)

    def factory_with(**kw):
        merged = dict(spec.params); merged.update(kw)
        return cls(**merged)

    # The OOSGuard ceremony for formal validation must wrap the whole
    # validate_pipeline call (not just the load). Otherwise a guard from
    # an outer scope might reset / close before the pipeline finishes
    # reading prices. We open the same ceremony again here -- the load
    # already finished, so re-entering is a no-op for OOS reads but
    # keeps the audit trail attached to validate_pipeline's invocation.
    with OOSGuard(guard_phase):
        rep = validate_pipeline(
            strategy_factory=factory,
            prices=prices,
            name=f"{args.strategy}({args.asset})",
            n_trials_optimization=args.n_trials,
            costs=_costs_from(args.costs),
            spp_param_ranges=spec.param_ranges,
            spp_strategy_factory=factory_with,
            mc_n_paths=args.mc_paths,
            is_tier="IS_ALL",
            oos_tier=oos_tier,
        )
    print(rep.report())
    return 0 if rep.overall_passed else 1


def cmd_search(args):
    """GA search.

    OOS sagrado: the GA fitness loop runs strictly on the chosen IS tier
    (default ``IS_TRAIN``, 1995..2010). The IS series is loaded BEFORE
    the GA starts -- OOS_DEV is not even resident in memory while the
    fitness loop is running. After the Pareto front is selected the
    top candidates are evaluated against the IS_VALID holdout
    (2011-2012, no guard needed) and finally against OOS_DEV
    (2013-2020) inside an ``OOSGuard("post_ga_validation")`` so the
    read is recorded in the lock file. ``OOS_LOCKED`` and ``FORWARD``
    are never touched here.
    """
    from aurora.ga.runner import run_ga, GAConfig
    from aurora.ga.fitness import multi_objective_fitness_is, validate_oos
    from aurora.core.data_layer import load_asset, OOSGuard
    from aurora.core.data_tiers import split_by_tier

    cfg = _load_global_config(args)
    if getattr(args, "dry_run", False):
        _dry_run_summary(args, cfg)
        return 0
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)

    is_tier_arg = (getattr(args, "is_tier", "is_train") or "is_train").lower()
    if is_tier_arg not in ("is_train", "is_all"):
        _arg_error(
            f"--is-tier must be 'is_train' or 'is_all' (got {is_tier_arg!r})"
        )

    # Step 1 -- load IS only. OOS_DEV is NOT in memory during GA. Even
    # though the GA fitness function only consumes is_p, having OOS in
    # the same process address space contradicts the protocol; we want
    # a true ``data_layer`` separation between phases. ``include_oos=False``
    # produces an IS-only slice (<= IS_END = 2012-12-31). We further
    # carve to is_train if the user asked for the strict tier.
    is_only_prices = load_asset(
        args.asset, include_oos=False, require_snapshot=True,
    )
    is_tiers = split_by_tier(is_only_prices)
    if is_tier_arg == "is_train":
        is_p = is_tiers.is_train
    else:
        is_p = is_tiers.is_all

    cfg_ga = GAConfig(population=args.population, generations=args.generations,
                      seed=args.seed)
    pareto = run_ga(cls, is_p, None, multi_objective_fitness_is, cfg_ga)

    print(f"\nPareto front ({len(pareto)} individuals, is_tier={is_tier_arg}):")
    print(f"{'Calmar':>8} {'Sharpe':>8} {'Robust':>8} {'MDDpen':>8}  Params")
    sorted_pareto = sorted(pareto, key=lambda x: -x[1][0])
    for params, fit in sorted_pareto[:20]:
        print(f"{fit[0]:>8.3f} {fit[1]:>8.3f} {fit[2]:>8.3f} {fit[3]:>8.3f}  {params}")

    top_n = max(1, min(int(args.oos_top), len(sorted_pareto)))

    # Inner IS_VALID holdout (2011-2012). Only meaningful when the GA
    # was fit on IS_TRAIN; if the user requested IS_ALL the front
    # already saw IS_VALID and this column is skipped. The IS_VALID
    # slice was carved from the IS-only series above, so no guard is
    # needed here either.
    if is_tier_arg == "is_train" and len(is_tiers.is_valid) >= 50:
        print(f"\nIS_VALID holdout (top {top_n} candidates):")
        print(f"{'Calmar':>8} {'Sharpe':>8} {'MDD':>8} {'CAGR':>8}  Params")
        for params, _fit in sorted_pareto[:top_n]:
            strat = cls(**dict(params))
            m = validate_oos(is_tiers.is_valid, strat.signals, costs=IBKR_costs)
            print(
                f"{m['calmar']:>8.3f} {m['sharpe']:>8.3f} "
                f"{m['mdd']:>8.3f} {m['cagr']:>8.3f}  {params}"
            )

    # Step 2 -- AFTER Pareto, NOW we open the OOSGuard, load the
    # series capped at OOS_DEV_END (round-3 audit fix: previously the
    # full ``include_oos=True`` load would also pull OOS_LOCKED + FORWARD
    # bars from the cached parquet, even though only ``oos_dev`` was
    # used downstream). ``load_up_to_tier`` clamps the read so the
    # lockbox cannot leak into the search transcript.
    if not args.skip_oos:
        from aurora.core.data_tiers import load_up_to_tier
        with OOSGuard("post_ga_validation"):
            full_prices = load_up_to_tier(
                args.asset, max_tier="OOS_DEV", require_snapshot=True,
            )
            full_tiers = split_by_tier(full_prices)
            oos_p = full_tiers.oos_dev
            print(f"\nOOS_DEV validation (top {top_n} candidates):")
            print(f"{'Calmar':>8} {'Sharpe':>8} {'MDD':>8} {'CAGR':>8}  Params")
            for params, _fit in sorted_pareto[:top_n]:
                strat = cls(**dict(params))
                m = validate_oos(oos_p, strat.signals, costs=IBKR_costs)
                print(
                    f"{m['calmar']:>8.3f} {m['sharpe']:>8.3f} "
                    f"{m['mdd']:>8.3f} {m['cagr']:>8.3f}  {params}"
                )
    else:
        print("\nOOS validation skipped (--skip-oos).")
    return 0


def cmd_run(args):
    from aurora.core.engine import run_backtest

    cfg = _load_global_config(args)
    if getattr(args, "dry_run", False):
        _dry_run_summary(args, cfg)
        return 0
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)
    # ``run`` is a post-validation backtest display, not a fitness loop.
    # Round-3 audit fix: ``--tier`` is the explicit knob (default
    # ``oos_dev``). The legacy "include everything" behaviour is now
    # behind ``--tier full`` + ``QF_ALLOW_FULL_TIER=1``.
    prices = _resolve_tier_load(args.asset, getattr(args, "tier",
                                                    _DEFAULT_ANALYTICAL_TIER))
    strat = cls()
    res = run_backtest(prices, strat.signals, costs=_costs_from(args.costs))
    print(f"Strategy: {args.strategy} on {args.asset}")
    print(f"  Calmar: {res.calmar:.3f}")
    print(f"  Sharpe: {res.sharpe:.3f}")
    print(f"  CAGR:   {res.cagr:.2f}%")
    print(f"  MDD:    {res.mdd:.2f}%")
    print(f"  Final NAV: {res.metrics.final_nav:.4f}")
    return 0


# ---------------------------------------------------------------------------
# New commands
# ---------------------------------------------------------------------------


def cmd_list_strategies(args):
    """Print all strategies with class name + spec param ranges."""
    lib = _strategy_library()
    if not lib:
        print("No strategies registered.")
        return 0

    rows = []
    for name in sorted(lib):
        cls = lib[name]
        spec = None
        defaults = ""
        ranges = ""
        try:
            spec = cls.spec()
            defaults = ", ".join(f"{k}={v!r}" for k, v in spec.params.items())
            ranges = ", ".join(f"{k}={v}" for k, v in spec.param_ranges.items())
        except Exception as e:  # pragma: no cover (defensive)
            defaults = f"<spec error: {e}>"
        rows.append((name, cls.__module__, defaults, ranges))

    name_w = max(len("Name"), max(len(r[0]) for r in rows))
    mod_w = max(len("Module"), max(len(r[1]) for r in rows))
    header = f"{'Name'.ljust(name_w)}  {'Module'.ljust(mod_w)}  Defaults"
    print(header)
    print("-" * len(header))
    for name, mod, defaults, ranges in rows:
        print(f"{name.ljust(name_w)}  {mod.ljust(mod_w)}  {defaults}")
        if ranges:
            indent = " " * (name_w + mod_w + 4)
            print(f"{indent}ranges: {ranges}")
    print(f"\nTotal: {len(rows)} strategies")
    return 0


def cmd_tearsheet(args):
    """Run backtest and write HTML tearsheet."""
    from aurora.core.engine import run_backtest
    from aurora.reporting.tearsheet import generate_tearsheet

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)
    prices = _resolve_tier_load(args.asset, getattr(args, "tier",
                                                    _DEFAULT_ANALYTICAL_TIER))
    strat = cls()
    res = run_backtest(prices, strat.signals, costs=_costs_from(args.costs))
    title = args.title or f"{args.strategy} on {args.asset}"
    out_path = generate_tearsheet(res, args.output, title=title)
    print(f"Tearsheet written: {out_path}")
    return 0


def cmd_bench(args):
    """Benchmark sequential engine vs JIT engine on synthetic data."""
    import time
    import numpy as np
    import pandas as pd

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)

    n = int(args.n)
    rng = np.random.default_rng(args.seed)
    idx = pd.date_range("2010-01-04", periods=n, freq="B")
    rets = rng.normal(0.0005, 0.012, n)
    prices = pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="BENCH")
    strat = cls()
    costs = _costs_from(args.costs)

    from aurora.core.engine import run_backtest

    # Warmup once for fairness with JIT compile.
    run_backtest(prices, strat.signals, costs=costs)

    # Sequential timing
    t0 = time.perf_counter()
    for _ in range(args.repeats):
        res_seq = run_backtest(prices, strat.signals, costs=costs)
    seq_s = (time.perf_counter() - t0) / max(1, args.repeats)

    print(f"Sequential ({n} bars x {args.repeats} reps): {seq_s * 1000:.2f} ms / run")
    print(f"  Calmar: {res_seq.calmar:.3f}, Sharpe: {res_seq.sharpe:.3f}")

    # JIT timing (best-effort)
    try:
        from aurora.core.engine_jit import run_backtest_jit, NUMBA_AVAILABLE
        # warmup jit compile
        run_backtest_jit(prices, strat.signals, costs=costs)
        t0 = time.perf_counter()
        for _ in range(args.repeats):
            res_jit = run_backtest_jit(prices, strat.signals, costs=costs)
        jit_s = (time.perf_counter() - t0) / max(1, args.repeats)
        tag = "JIT" if NUMBA_AVAILABLE else "JIT (numpy fallback)"
        print(f"{tag}     ({n} bars x {args.repeats} reps): {jit_s * 1000:.2f} ms / run")
        print(f"  Calmar: {res_jit.calmar:.3f}, Sharpe: {res_jit.sharpe:.3f}")
        if jit_s > 0:
            print(f"Speedup: {seq_s / jit_s:.2f}x")
    except Exception as e:
        print(f"JIT engine unavailable: {e}")
    return 0


def cmd_config_show(args):
    """Print loaded config (defaults if --config not provided)."""
    cfg = _load_global_config(args)
    data = cfg.model_dump()
    fmt = (args.format or "yaml").lower()
    if fmt == "json":
        import json
        print(json.dumps(data, indent=2, sort_keys=False))
    else:
        try:
            import yaml
            print(yaml.safe_dump(data, sort_keys=False, default_flow_style=False).rstrip())
        except ImportError:
            import json
            print(json.dumps(data, indent=2))
    return 0


def cmd_config_init(args):
    """Write default ForgeConfig to args.output (yaml or toml by extension)."""
    from aurora.core.config import default_config, save_config
    from pathlib import Path
    out = Path(args.output)
    if out.exists() and not args.force:
        print(f"Refusing to overwrite existing {out}. Use --force to replace.")
        return 1
    cfg = default_config()
    save_config(cfg, out)
    print(f"Default config written: {out.resolve()}")
    return 0


def _parse_periods(spec: str) -> tuple[int, ...]:
    """Parse '1,5,20' -> (1, 5, 20). Empty/None -> (1, 5, 20)."""
    if not spec:
        return (1, 5, 20)
    out = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            v = int(tok)
        except ValueError:
            _arg_error(f"--periods entry '{tok}' is not an integer")
        if v <= 0:
            _arg_error(f"--periods entry '{tok}' must be > 0")
        out.append(v)
    if not out:
        return (1, 5, 20)
    return tuple(out)


def cmd_label(args):
    """Apply triple-barrier labeling and emit CSV / JSON / stdout summary."""
    import json
    import pandas as pd
    from aurora.ml.labels import triple_barrier_labels

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    prices = _resolve_tier_load(args.asset, getattr(args, "tier",
                                                    _DEFAULT_ANALYTICAL_TIER))

    if args.pt < 0 or args.sl < 0:
        _arg_error("--pt and --sl must be non-negative")
    if args.hp <= 0:
        _arg_error("--hp must be > 0")

    # Default events: every bar (after warmup) — caller can downsample externally.
    events = prices.index
    res = triple_barrier_labels(
        prices=prices,
        events=events,
        pt_sl_factors=(float(args.pt), float(args.sl)),
        holding_period_days=int(args.hp),
        min_return=float(args.min_return),
    )

    counts = res.labels.value_counts().to_dict()
    n = int(len(res.labels))
    print(f"Triple-barrier labels for {args.asset}")
    print(f"  pt={args.pt} sl={args.sl} hp={args.hp} min_return={args.min_return}")
    print(f"  events: {n}")
    print(f"  +1: {int(counts.get(1, 0))}")
    print(f"   0: {int(counts.get(0, 0))}")
    print(f"  -1: {int(counts.get(-1, 0))}")
    if n > 0:
        rmean = float(res.returns.dropna().mean()) if res.returns.notna().any() else 0.0
        print(f"  mean return at first touch: {rmean:.6f}")

    if args.output:
        df = pd.DataFrame({
            "label": res.labels.astype(int),
            "ret": res.returns,
            "first_touch": res.touch_times["first_touch"],
            "pt_touch": res.touch_times["pt_touch"],
            "sl_touch": res.touch_times["sl_touch"],
            "t1_touch": res.touch_times["t1_touch"],
            "daily_vol": res.target_volatility,
        })
        out = str(args.output)
        if out.lower().endswith(".json"):
            df_reset = df.reset_index().rename(columns={"index": "event"})
            df_reset["event"] = df_reset["event"].astype(str)
            for c in ("first_touch", "pt_touch", "sl_touch", "t1_touch"):
                df_reset[c] = df_reset[c].astype(str)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(df_reset.to_dict(orient="records"), f, indent=2)
        else:
            df.to_csv(out, index_label="event")
        print(f"Labels written: {out}")
    return 0


def cmd_factor(args):
    """Compute factor analysis (IC, quantile spread, summary table)."""
    import pandas as pd
    from aurora.core.engine import run_backtest
    from aurora.analytics.factor_analysis import factor_summary_table

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)
    prices = _resolve_tier_load(args.asset, getattr(args, "tier",
                                                    _DEFAULT_ANALYTICAL_TIER))
    strat = cls()
    sigs = strat.signals(prices)
    factor = pd.Series(sigs, index=prices.index, name=args.strategy)

    periods = _parse_periods(args.periods)
    table = factor_summary_table(factor, prices, forward_periods=periods)
    print(f"Factor analysis: {args.strategy} on {args.asset}")
    print(f"  periods: {periods}")
    print()
    print(table.to_string(float_format=lambda v: f"{v:8.4f}"))

    if args.output:
        out = str(args.output)
        if out.lower().endswith(".json"):
            table.reset_index().to_json(out, orient="records", indent=2)
        else:
            table.to_csv(out, index_label="period")
        print(f"Factor summary written: {out}")
    return 0


def cmd_attribute(args):
    """Performance attribution for a strategy.

    Modes:
      --benchmark <ticker>        : factor attribution vs benchmark returns.
      --regime bull,bear --regime-file <csv>
                                  : per-regime attribution from regime label CSV.
    """
    import pandas as pd
    from aurora.core.engine import run_backtest
    from aurora.analytics.attribution import (
        attribution_by_factor,
        attribution_by_time,
    )

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)
    prices = _resolve_tier_load(args.asset, getattr(args, "tier",
                                                    _DEFAULT_ANALYTICAL_TIER))
    strat = cls()
    res = run_backtest(prices, strat.signals, costs=_costs_from(args.costs))
    rets_arr = res.rets
    strat_rets = pd.Series(rets_arr, index=prices.index[-len(rets_arr):], name="strategy")
    strat_rets = strat_rets.dropna()

    if args.regime:
        if not args.regime_file:
            _arg_error("--regime requires --regime-file <csv>")
        regimes_df = pd.read_csv(args.regime_file, index_col=0, parse_dates=True)
        regime_col = regimes_df.columns[0]
        regime_labels = regimes_df[regime_col]
        wanted = {tok.strip() for tok in args.regime.split(",") if tok.strip()}
        if wanted:
            regime_labels = regime_labels[regime_labels.isin(wanted)]
        attr = attribution_by_time(strat_rets, regime_labels)
        print(f"Attribution by regime: {args.strategy} on {args.asset}")
        print(f"  regimes: {sorted(wanted) if wanted else 'all'}")
        print()
        print(attr.contributions.to_string(float_format=lambda v: f"{v:8.4f}"))
        print(f"\nTotal return across bars: {attr.total:.6f}")
    else:
        bench = args.benchmark or args.asset
        # Match the strategy series tier to keep regression aligned.
        bench_prices = _resolve_tier_load(bench, getattr(args, "tier",
                                                          _DEFAULT_ANALYTICAL_TIER))
        bench_rets = bench_prices.pct_change().rename("benchmark")
        attr = attribution_by_factor(
            strat_rets, {"benchmark": bench_rets}, method="ols",
        )
        print(f"Attribution by factor: {args.strategy} on {args.asset}")
        print(f"  benchmark: {bench}")
        print()
        print(attr.contributions.to_string(float_format=lambda v: f"{v:8.4f}"))
        print(f"\nAlpha (intercept * T): {attr.total:.6f}")

    if args.output:
        out = str(args.output)
        if out.lower().endswith(".json"):
            attr.contributions.reset_index().to_json(out, orient="records", indent=2)
        else:
            attr.contributions.to_csv(out)
        print(f"Attribution written: {out}")
    return 0


def cmd_purge_cv(args):
    """Run purged k-fold CV; print per-fold metrics summary."""
    import pandas as pd
    from aurora.validation.purged_cv import cv_score

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)
    prices = _resolve_tier_load(args.asset, getattr(args, "tier",
                                                    _DEFAULT_ANALYTICAL_TIER))
    spec = cls.spec()

    def factory():
        return cls(**spec.params)

    res = cv_score(
        strategy_factory=factory,
        prices=prices,
        n_splits=int(args.k),
        embargo_pct=float(args.embargo),
        costs=_costs_from(args.costs),
    )

    print(f"Purged CV: {args.strategy} on {args.asset}")
    print(f"  k={res.n_splits}  embargo_pct={res.embargo_pct:.4f}")
    print(f"  Calmar  mean/median/std: "
          f"{res.mean_calmar:.4f} / {res.median_calmar:.4f} / {res.std_calmar:.4f}")
    print(f"  Sharpe  mean/median/std: "
          f"{res.mean_sharpe:.4f} / {res.median_sharpe:.4f} / {res.std_sharpe:.4f}")
    print(f"  MDD     mean:            {res.mean_mdd:.4f}")
    print()
    print(f"{'fold':>4}  {'calmar':>8}  {'sharpe':>8}  {'mdd':>8}")
    rows = []
    for fm in res.fold_metrics:
        m = fm.get("metrics") or {}
        c = m.get("calmar", float("nan"))
        s = m.get("sharpe", float("nan"))
        d = m.get("mdd", float("nan"))
        print(f"{fm['fold']:>4}  {c:>8.4f}  {s:>8.4f}  {d:>8.4f}")
        rows.append({"fold": fm["fold"], "calmar": c, "sharpe": s, "mdd": d,
                     "ok": fm.get("ok", False)})

    if args.output:
        out = str(args.output)
        df = pd.DataFrame(rows)
        if out.lower().endswith(".json"):
            df.to_json(out, orient="records", indent=2)
        else:
            df.to_csv(out, index=False)
        print(f"Fold metrics written: {out}")
    return 0


def cmd_fracdiff(args):
    """Find min d for stationarity via ADF sweep."""
    import numpy as np
    import pandas as pd
    from aurora.ml.fracdiff import find_min_d, fracdiff_correlation

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    prices = _resolve_tier_load(args.asset, getattr(args, "tier",
                                                    _DEFAULT_ANALYTICAL_TIER))
    series = np.log(prices.replace(0, np.nan).dropna())
    series.name = args.asset

    min_d, adf_stat, p_value = find_min_d(
        series,
        max_d=float(args.max_d),
        step=float(args.step),
        threshold=float(args.threshold),
        adf_pvalue=float(args.adf_pvalue),
    )

    print(f"Fracdiff min-d sweep: {args.asset}")
    print(f"  max_d={args.max_d}  step={args.step}  threshold={args.threshold}")
    if min_d is None:
        print("  No d in sweep yields stationary series at the given p-value.")
    else:
        print(f"  min_d={min_d:.4f}  adf_stat={adf_stat:.4f}  p_value={p_value:.6f}")

    if args.sweep:
        table = fracdiff_correlation(
            series, max_d=float(args.max_d), step=float(args.step),
            threshold=float(args.threshold),
        )
        print()
        print(table.to_string(index=False, float_format=lambda v: f"{v:8.4f}"))

    if args.output:
        out = str(args.output)
        table = fracdiff_correlation(
            series, max_d=float(args.max_d), step=float(args.step),
            threshold=float(args.threshold),
        )
        if out.lower().endswith(".json"):
            payload = {
                "asset": args.asset,
                "min_d": min_d,
                "adf_stat": adf_stat,
                "p_value": p_value,
                "sweep": table.to_dict(orient="records"),
            }
            import json
            with open(out, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        else:
            table.to_csv(out, index=False)
        print(f"Sweep written: {out}")
    return 0


def cmd_cscv(args):
    """CSCV / PBO test from a returns matrix CSV."""
    import json
    import pandas as pd
    from aurora.validation.cscv_pbo import cscv

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    if not args.returns_csv:
        _arg_error("--returns-csv is required")

    df = pd.read_csv(args.returns_csv, index_col=0)
    try:
        df.index = pd.to_datetime(df.index)
    except Exception:
        pass
    df = df.apply(pd.to_numeric, errors="coerce").dropna(how="all")

    res = cscv(df, n_splits=int(args.n_splits), max_combinations=int(args.max_combos))

    print(f"CSCV / PBO: {args.returns_csv}")
    print(f"  shape: {df.shape[0]} rows x {df.shape[1]} strategies")
    print(f"  n_splits={args.n_splits}  combinations evaluated: {res.n_combinations}")
    print(f"  PBO: {res.pbo:.4f}")
    print(f"  Performance degradation rate: {res.performance_degradation_rate:.4f}")
    print(f"  Stochastic dominance: {res.stochastic_dominance:.4f}")
    print(f"  Logit mean / median: {float(res.logits.mean()):.4f} / "
          f"{float(pd.Series(res.logits).median()):.4f}")

    if args.output:
        out = str(args.output)
        payload = {
            "pbo": res.pbo,
            "n_combinations": res.n_combinations,
            "performance_degradation_rate": res.performance_degradation_rate,
            "stochastic_dominance": res.stochastic_dominance,
            "logit_mean": float(res.logits.mean()),
            "logit_median": float(pd.Series(res.logits).median()),
            "rank_corr_mean": float(res.rank_correlations.mean()),
        }
        if out.lower().endswith(".csv"):
            pd.DataFrame([payload]).to_csv(out, index=False)
        else:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        print(f"CSCV summary written: {out}")
    return 0


def cmd_preflight(args):
    """Run preflight checks for a strategy/symbol."""
    from aurora.deployment.preflight import run_preflight

    cfg = _load_global_config(args)
    set_global_seed(args.seed)
    cls = _resolve_strategy(args.strategy)
    strat = cls()

    rep = run_preflight(
        strategy=strat,
        symbol=args.symbol,
        broker=None,
        min_data_bars=args.min_bars,
        max_position_pct=args.max_position_pct,
        required_files=[],
        project_dir=args.project_dir,
        prices=None,
        min_disk_mb=args.min_disk_mb,
        check_ntp=False,
    )
    print(rep.report())
    return 0 if rep.all_passed else 1


def cmd_search_multi(args):
    """Multi-asset GA search using load_tier per asset.

    P2.4 round-4 audit: previously the multi-asset GA had no CLI
    entrypoint, so users handed it pre-loaded price dicts that bypassed
    every tier-ceremony rule. This command loads each ``--asset`` via
    ``load_tier(asset, 'IS_TRAIN')`` (the same OOS-sagrado path used by
    the single-asset ``cmd_search``), then runs ``run_multi_asset_ga``
    with the IS-only fitness so the GA never sees OOS bars.
    """
    from aurora.ga.multi_asset_runner import (
        run_multi_asset_ga, MultiAssetGAConfig, multi_asset_fitness_is,
    )
    from aurora.core.data_tiers import load_tier

    cfg = _load_global_config(args)
    set_global_seed(args.seed)

    cls = _resolve_strategy(args.strategy)
    symbols = list(args.asset)
    if len(symbols) < 2:
        _arg_error(
            f"search-multi requires --asset given >= 2 times, got {symbols!r}"
        )

    is_tier = (getattr(args, "is_tier", "is_train") or "is_train").upper()
    if is_tier not in ("IS_TRAIN", "IS_VALID"):
        _arg_error(
            f"--is-tier must be 'is_train' or 'is_valid' (got {is_tier!r})"
        )

    price_dict_is: dict = {}
    for s in symbols:
        # load_tier enforces tier-ceremony rules at read time. IS_TRAIN /
        # IS_VALID are routine (no OOSGuard required); load_tier returns
        # only the bars in that window.
        price_dict_is[s] = load_tier(s, tier=is_tier)
        print(f"{s}: IS_TRAIN bars={len(price_dict_is[s])}")

    cfg_ga = MultiAssetGAConfig(
        population=args.population, generations=args.generations,
        seed=args.seed,
    )
    pareto = run_multi_asset_ga(
        cls,
        price_dict_is=price_dict_is,
        price_dict_oos=None,
        symbols=symbols,
        fitness_fn=multi_asset_fitness_is,
        config=cfg_ga,
        verbose=True,
    )
    print(f"\nPareto front: {len(pareto)} individuals")
    print(f"{'Calmar':>8} {'Sharpe':>8} {'Robust':>8} {'MDDpen':>8}  Params")
    for params, fit in sorted(pareto, key=lambda x: -x[1][0])[:15]:
        print(f"{fit[0]:>8.3f} {fit[1]:>8.3f} {fit[2]:>8.3f} {fit[3]:>8.3f}  {params}")
    return 0


def cmd_freeze(args):
    """Freeze a price series snapshot via SnapshotStore.

    P1.3 round-4 audit: previously SnapshotStore.freeze was only
    reachable programmatically; the CLI had no entrypoint to register a
    new snapshot. Without this command, every protocol run that
    requires a hash-verified snapshot (``cmd_search`` /
    ``cmd_validate`` with ``require_snapshot=True``) needed a
    handwritten Python script to populate the SnapshotStore index.

    The command loads the asset (full series, no OOS filter), then
    calls ``store.freeze(...)`` with the requested provenance + locked
    flag. Idempotent because SnapshotStore is content-addressed -- a
    repeat freeze of the same data yields the same SHA-256.
    """
    import os
    cfg = _load_global_config(args)
    set_global_seed(args.seed)

    asset = args.asset
    provenance = args.provenance or "yfinance"
    locked = bool(args.locked)

    # Load the underlying series. We always pull the full series
    # (include_oos=True) so the snapshot covers every tier; downstream
    # consumers carve to the tier they need via ``load_tier`` /
    # ``load_up_to_tier``. Wrap in OOSGuard("snapshot_freeze") so the
    # read is auditable.
    from aurora.core.data_layer import load_asset, OOSGuard
    from aurora.core.snapshots import SnapshotStore

    with OOSGuard("snapshot_freeze"):
        prices = load_asset(asset, source=provenance, include_oos=True)

    if len(prices) == 0:
        return _runtime_error(f"freeze: load_asset({asset!r}) returned 0 bars")

    from aurora.core.runtime_paths import snapshot_root as _snapshot_root
    snap_root = str(_snapshot_root())
    store = SnapshotStore(snap_root)
    snap = store.freeze(
        prices, symbol=asset, provenance=provenance, locked=locked,
    )
    print(f"Frozen snapshot for {asset}:")
    print(f"  sha256:    {snap.sha256}")
    print(f"  data_path: {snap.data_path}")
    print(f"  n_bars:    {snap.n_bars}")
    print(f"  start:     {snap.start.isoformat()}")
    print(f"  end:       {snap.end.isoformat()}")
    print(f"  locked:    {snap.locked}")
    print(f"  provenance:{snap.provenance}")
    return 0


def cmd_dashboard(args):
    """Launch the Streamlit live dashboard.

    Wraps ``streamlit run quantforge/monitoring/dashboard.py`` and passes
    the journal path / refresh interval through environment variables so the
    script entrypoint can pick them up.
    """
    import os
    import shutil
    import subprocess

    from aurora.monitoring.dashboard import STREAMLIT_AVAILABLE

    if not STREAMLIT_AVAILABLE:
        print("streamlit is not installed. Install with 'pip install streamlit'.")
        return 1

    streamlit_bin = shutil.which("streamlit")
    if streamlit_bin is None:
        # Fall back to module invocation; works in venvs where the script is
        # not on PATH but the package is importable.
        cmd = [sys.executable, "-m", "streamlit", "run"]
    else:
        cmd = [streamlit_bin, "run"]

    # Path to the dashboard module file.
    from aurora.monitoring import dashboard as _dash_mod
    script_path = _dash_mod.__file__

    env = os.environ.copy()
    env["QF_JOURNAL"] = str(args.journal)
    env["QF_REFRESH"] = str(int(args.refresh))

    cmd.extend([script_path])
    if args.port:
        cmd.extend(["--server.port", str(int(args.port))])
    if args.headless:
        cmd.extend(["--server.headless", "true"])

    print(f"Launching dashboard: journal={args.journal} refresh={args.refresh}s")
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 0


# ---------------------------------------------------------------------------
# data subcommands (P0.B DataProviderRegistry)
# ---------------------------------------------------------------------------


def cmd_data_list_providers(args):
    """Print the registered data providers + their PIT/tier posture."""
    from aurora.core.data_providers import get_default_registry
    registry = get_default_registry()
    rows = registry.describe()
    if not rows:
        print("(no providers registered)")
        return 0
    name_w = max(len(r["name"]) for r in rows)
    ver_w = max(len(str(r["version"])) for r in rows)
    print(
        f"{'NAME':<{name_w}}  "
        f"{'VERSION':<{ver_w}}  "
        f"{'PIT':<5}  TIER_PERMISSION  SUPPORTED_TIERS"
    )
    for r in rows:
        pit = "yes" if r["point_in_time"] else "no"
        print(
            f"{r['name']:<{name_w}}  "
            f"{str(r['version']):<{ver_w}}  "
            f"{pit:<5}  {r['tier_permission']:<15}  "
            f"{','.join(r['supported_tiers'])}"
        )
    return 0


def cmd_data_fetch(args):
    """Fetch a Dataset from a provider and write parquet + sidecar."""
    import json
    import os
    from aurora.core.data_providers import get_default_registry
    registry = get_default_registry()
    try:
        ds = registry.fetch(
            args.provider, args.symbol, start=args.start, end=args.end,
        )
    except Exception as exc:
        return _runtime_error(f"data fetch: {exc}")
    out = args.output
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    raw = ds.data
    try:
        import pandas as pd
        if isinstance(raw, pd.Series):
            raw.to_frame(raw.name or "value").to_parquet(out)
        else:
            raw.to_parquet(out)
    except Exception as exc:
        return _runtime_error(f"data fetch: parquet write failed: {exc}")
    sidecar_path = out + ".meta.json"
    meta_payload = {
        "name": ds.metadata.name,
        "source": ds.metadata.source,
        "source_version": ds.metadata.source_version,
        "asof_date": ds.metadata.asof_date.isoformat(),
        "point_in_time": ds.metadata.point_in_time,
        "content_hash": ds.metadata.content_hash,
        "tier_permission": ds.metadata.tier_permission,
        "schema_version": ds.metadata.schema_version,
        "extra": ds.metadata.extra,
    }
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(meta_payload, f, indent=2, default=str)
    print(f"Wrote {out} ({len(raw)} rows)")
    print(f"Sidecar metadata: {sidecar_path}")
    print(f"  content_hash: {ds.metadata.content_hash}")
    print(f"  asof_date:    {ds.metadata.asof_date.isoformat()}")
    print(f"  point_in_time:{ds.metadata.point_in_time}")
    print(f"  tier_permission:{ds.metadata.tier_permission}")
    return 0


def cmd_data_verify(args):
    """Recompute content_hash and check tier permission of a fetched parquet."""
    import json
    import os
    parquet = args.parquet
    sidecar = parquet + ".meta.json"
    if not os.path.exists(parquet):
        return _runtime_error(f"data verify: file not found: {parquet}")
    if not os.path.exists(sidecar):
        return _runtime_error(f"data verify: sidecar not found: {sidecar}")
    try:
        with open(sidecar, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as exc:
        return _runtime_error(f"data verify: sidecar read failed: {exc}")

    import pandas as pd
    df = pd.read_parquet(parquet)
    from aurora.core.data_providers import compute_content_hash
    if df.shape[1] == 1:
        recomputed = compute_content_hash(df.iloc[:, 0])
    else:
        recomputed = compute_content_hash(df)
    expected = meta.get("content_hash")
    print(f"file:           {parquet}")
    print(f"expected hash:  {expected}")
    print(f"recomputed hash:{recomputed}")
    if recomputed != expected:
        print("VERIFY: FAIL (content_hash mismatch -- file tampered)")
        return 1
    print("VERIFY: PASS (content_hash matches)")
    print(f"tier_permission: {meta.get('tier_permission')}")
    print(f"point_in_time:   {meta.get('point_in_time')}")
    return 0


# ---------------------------------------------------------------------------
# Crypto / CCXT subcommands (P3.A)
# ---------------------------------------------------------------------------


def _ccxt_load_config():
    """Best-effort load of ``config/ccxt.yaml``. Returns dict or {}."""
    import os
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "config", "ccxt.yaml"),
        "quantforge/config/ccxt.yaml",
        "config/ccxt.yaml",
    ]
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}
    return {}


def cmd_crypto_exchanges(args):
    """List the ccxt-supported exchanges. Lazy-fails cleanly if missing."""
    try:
        import ccxt  # type: ignore
    except Exception:
        print("ccxt not installed. Install with: pip install ccxt")
        return 1
    exchanges = sorted(getattr(ccxt, "exchanges", []))
    print(f"ccxt {getattr(ccxt, '__version__', '?')}: "
          f"{len(exchanges)} exchanges")
    for ex in exchanges:
        print(f"  {ex}")
    return 0


def cmd_crypto_fetch(args):
    """Fetch crypto OHLCV via the CCXTProvider into a parquet."""
    import json
    import os
    try:
        from aurora.core.data_providers.ccxt_provider import CCXTProvider
    except Exception as exc:
        return _runtime_error(f"crypto fetch: {exc}")
    cfg = _ccxt_load_config()
    exchange = args.exchange or cfg.get("default_exchange", "binance")
    provider = CCXTProvider(exchange_id=exchange)
    try:
        ds = provider.fetch(
            args.symbol,
            start=args.start, end=args.end,
            timeframe=args.timeframe,
        )
    except Exception as exc:
        return _runtime_error(f"crypto fetch: {exc}")
    out = args.output
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    try:
        ds.data.to_parquet(out)
    except Exception as exc:
        return _runtime_error(f"crypto fetch: parquet write failed: {exc}")
    sidecar_path = out + ".meta.json"
    payload = {
        "name": ds.metadata.name,
        "source": ds.metadata.source,
        "source_version": ds.metadata.source_version,
        "asof_date": ds.metadata.asof_date.isoformat(),
        "point_in_time": ds.metadata.point_in_time,
        "content_hash": ds.metadata.content_hash,
        "tier_permission": ds.metadata.tier_permission,
        "schema_version": ds.metadata.schema_version,
        "extra": ds.metadata.extra,
    }
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"Wrote {out} ({len(ds.data)} rows)")
    print(f"Sidecar metadata: {sidecar_path}")
    return 0


def cmd_crypto_submit_order(args):
    """Submit a crypto order through the CCXT broker adapter."""
    cfg = _ccxt_load_config()
    exchange = args.exchange or cfg.get("default_exchange", "binance")
    sandbox = not getattr(args, "allow_live", False)
    try:
        from aurora.deployment.ccxt_adapter import CCXTBrokerAdapter
        from aurora.deployment.brokers import Order
    except Exception as exc:
        return _runtime_error(f"crypto submit-order: {exc}")
    try:
        adapter = CCXTBrokerAdapter(
            exchange_id=exchange,
            sandbox=sandbox,
        )
    except ImportError as exc:
        return _runtime_error(f"crypto submit-order: {exc}")
    order = Order(
        symbol=args.symbol,
        qty=float(args.qty),
        side=args.side,
        order_type=args.type,
        limit_price=float(args.limit_price) if args.limit_price else None,
    )
    try:
        resp = adapter.submit_order(order)
    except Exception as exc:
        return _runtime_error(f"crypto submit-order: {exc}")
    print(resp)
    if str(resp.get("status", "")).lower() == "rejected":
        return 1
    return 0


def cmd_crypto_positions(args):
    cfg = _ccxt_load_config()
    exchange = args.exchange or cfg.get("default_exchange", "binance")
    try:
        from aurora.deployment.ccxt_adapter import CCXTBrokerAdapter
    except Exception as exc:
        return _runtime_error(f"crypto positions: {exc}")
    try:
        adapter = CCXTBrokerAdapter(exchange_id=exchange, sandbox=True)
        positions = adapter.get_positions()
    except Exception as exc:
        return _runtime_error(f"crypto positions: {exc}")
    if not positions:
        print("(no positions)")
        return 0
    for p in positions:
        print(f"{p.symbol:<14}  qty={p.qty}")
    return 0


def cmd_crypto_balance(args):
    cfg = _ccxt_load_config()
    exchange = args.exchange or cfg.get("default_exchange", "binance")
    try:
        from aurora.deployment.ccxt_adapter import CCXTBrokerAdapter
    except Exception as exc:
        return _runtime_error(f"crypto balance: {exc}")
    try:
        adapter = CCXTBrokerAdapter(exchange_id=exchange, sandbox=True)
        bal = adapter.get_balance()
    except Exception as exc:
        return _runtime_error(f"crypto balance: {exc}")
    if not bal:
        print("(empty balance)")
        return 0
    free = bal.get("free", {}) if isinstance(bal, dict) else {}
    total = bal.get("total", {}) if isinstance(bal, dict) else {}
    print(f"{'currency':<10}  {'free':>16}  {'total':>16}")
    for ccy in sorted(set(list(free) + list(total))):
        print(f"{ccy:<10}  {free.get(ccy, 0)!s:>16}  {total.get(ccy, 0)!s:>16}")
    return 0


def cmd_crypto_allow_live(args):
    """Write a one-time allow-live consent token for an exchange."""
    cfg = _ccxt_load_config()
    token_dir = (
        args.token_dir
        or cfg.get("allow_live_token_dir")
        or "~/.quantforge/ccxt_tokens"
    )
    try:
        from aurora.deployment.ccxt_adapter import (
            ALLOW_LIVE_TOKEN_ENV_PATTERN,
            LIVE_CEREMONY_PHASE,
            write_allow_live_token,
        )
    except Exception as exc:
        return _runtime_error(f"crypto allow-live: {exc}")
    path = write_allow_live_token(args.exchange, token_dir)
    env_var = ALLOW_LIVE_TOKEN_ENV_PATTERN.format(EXCHANGE=args.exchange.upper())
    print(f"Wrote consent token: {path}")
    print()
    print("To go live, export:")
    print(f"  {env_var}=1")
    print(f"  (and open an OOSGuard with phase={LIVE_CEREMONY_PHASE!r})")
    print()
    print("This token alone does NOT authorize live trading. Live submit "
          "still requires gateway_committed + OOSGuard ceremony.")
    return 0


# ---------------------------------------------------------------------------
# Policy subcommands (P0.A)
# ---------------------------------------------------------------------------


def cmd_policy_show(args):
    """Print the active :class:`ProtocolPolicy` as YAML + the policy hash."""
    from aurora.core.protocol_policy import ProtocolPolicy
    path = getattr(args, "path", None)
    pol = ProtocolPolicy.load(path) if path else ProtocolPolicy.load()
    print(pol.to_yaml())
    print(f"# policy_hash: {pol.policy_hash}")
    return 0


def cmd_policy_verify(args):
    """Recompute the policy hash and compare to the YAML's declared hash.

    Returns exit code 0 on match, 1 on tamper / mismatch.
    """
    import os
    from aurora.core.protocol_policy import ProtocolPolicy
    path = getattr(args, "path", None) or ProtocolPolicy.default_yaml_path()
    if not os.path.exists(path):
        return _runtime_error(
            f"policy verify: YAML not found at {path}. "
            "Run `forge policy show > config/protocol_policy.yaml` to "
            "materialize the default."
        )
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        return _runtime_error(f"policy verify: YAML read failed: {exc}")
    declared = data.get("policy_hash")
    pol = ProtocolPolicy.from_dict(data)
    recomputed = pol.policy_hash
    print(f"path:             {path}")
    print(f"declared hash:    {declared}")
    print(f"recomputed hash:  {recomputed}")
    # A declared hash field is mandatory for verification. When it is
    # present (even as a falsy literal like ``0`` or ``""``), it must
    # match the recomputed digest exactly. Missing entirely (key absent)
    # is treated as "not declared" -> PASS, mirroring how ``--path``
    # might point at a freshly-generated YAML.
    if "policy_hash" in data:
        if str(declared) != str(recomputed):
            print("VERIFY: FAIL (policy_hash mismatch -- YAML tampered)")
            return 1
    print("VERIFY: PASS")
    return 0


# ---------------------------------------------------------------------------
# Research Factory subcommands (P1.C)
# ---------------------------------------------------------------------------


def _load_research_factory(args, *, with_data_loader=True):
    """Construct a :class:`ResearchFactory` for CLI commands.

    Loads the factory config from ``args.config_path`` (default
    ``quantforge/config/research_factory.yaml``), resolves the active
    :class:`ProtocolPolicy`, and wires in an
    :class:`~quantforge.registry.experiments.ExperimentTracker`. A noop
    auditor is left as None -- the auditor (P1.B) is a separate concern.
    """
    import os
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.registry.experiments import ExperimentTracker
    from aurora.research.factory import (
        ResearchFactory, ResearchPipelineConfig,
    )

    # Resolve config: explicit --config-path > bundled default.
    cfg_path = getattr(args, "config_path", None)
    if cfg_path and os.path.exists(cfg_path):
        cfg = ResearchPipelineConfig.from_yaml(cfg_path)
    else:
        # Bundled default location: quantforge/config/research_factory.yaml
        here = os.path.dirname(os.path.abspath(__file__))
        bundled = os.path.normpath(
            os.path.join(here, "..", "config", "research_factory.yaml")
        )
        if os.path.exists(bundled):
            cfg = ResearchPipelineConfig.from_yaml(bundled)
        else:
            cfg = ResearchPipelineConfig()

    pol = ProtocolPolicy.load()
    registry = ExperimentTracker()
    kwargs: dict = {}
    if not with_data_loader:
        # Used by tests / promote-flow to avoid the OOS_DEV cap that the
        # default loader applies. Promote is handled in cmd_research_promote
        # itself; the factory still hard-blocks any callers above OOS_DEV.
        pass
    return ResearchFactory(cfg, pol, registry, **kwargs)


def _strategy_spec_from_yaml(path):
    """Parse a YAML / JSON file into a :class:`StrategySpec`."""
    import json
    import os
    import yaml
    from aurora.research.factory import StrategySpec
    if not os.path.exists(path):
        _arg_error(f"spec file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        data = json.loads(text) if text.strip() else {}
    else:
        data = yaml.safe_load(text) or {}
    if "specs" in data and isinstance(data["specs"], list):
        # Caller passed a batch file to a single-submit command -- be loud.
        _arg_error(
            f"spec file {path!r} contains a 'specs' list; "
            "use `forge research batch` for multi-spec submission."
        )
    return StrategySpec.from_dict(data)


def _strategy_specs_from_yaml(path):
    """Parse a YAML / JSON file into a list of :class:`StrategySpec`."""
    import json
    import os
    import yaml
    from aurora.research.factory import StrategySpec
    if not os.path.exists(path):
        _arg_error(f"specs file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        data = json.loads(text) if text.strip() else {}
    else:
        data = yaml.safe_load(text) or {}
    raw_list = data.get("specs") if isinstance(data, dict) else None
    if not isinstance(raw_list, list):
        _arg_error(
            f"specs file {path!r} must have a top-level 'specs' list; "
            "use `forge research submit` for a single spec."
        )
    return [StrategySpec.from_dict(d) for d in raw_list]


def cmd_research_submit(args):
    """Submit a single :class:`StrategySpec` (YAML/JSON) to the factory."""
    factory = _load_research_factory(args)
    spec = _strategy_spec_from_yaml(args.spec_path)
    outcome = factory.submit(spec)
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(outcome.candidate.to_dict(), default=str, indent=2))
    else:
        print(outcome.summary)
    return 0 if outcome.promising else 1


def cmd_research_batch(args):
    """Submit a batch of specs from a YAML/JSON file with a 'specs' list."""
    factory = _load_research_factory(args)
    specs = _strategy_specs_from_yaml(args.specs_path)
    outcomes = factory.submit_batch(specs)
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(
            [o.candidate.to_dict() for o in outcomes],
            default=str, indent=2,
        ))
    else:
        for o in outcomes:
            print(o.summary)
    return 0 if all(o.promising for o in outcomes) else 1


def cmd_research_review_queue(args):
    """List pending review-queue candidates."""
    factory = _load_research_factory(args)
    items = factory.list_review_queue()
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(
            [c.to_dict() for c in items], default=str, indent=2,
        ))
        return 0
    if not items:
        print("(review queue empty)")
        return 0
    for c in items:
        print(
            f"{c.candidate_id} {c.spec.name} "
            f"is_sharpe={(c.is_metrics or {}).get('sharpe', '?')} "
            f"oos_sharpe={(c.oos_dev_metrics or {}).get('sharpe', '?')}"
        )
    return 0


def cmd_research_archive(args):
    """List archived candidates with optional --reason filter."""
    factory = _load_research_factory(args)
    items = factory.list_archived()
    reason = getattr(args, "reason", None)
    if reason:
        items = [
            c for c in items
            if c.rejection is not None and c.rejection.value == reason
        ]
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(
            [c.to_dict() for c in items], default=str, indent=2,
        ))
        return 0
    if not items:
        print("(archive empty)")
        return 0
    for c in items:
        rej = c.rejection.value if c.rejection else "?"
        detail = (c.rejection_detail or "")[:80]
        print(
            f"{c.candidate_id} {c.spec.name} reason={rej} "
            f"stage={c.stage.value} detail={detail!r}"
        )
    return 0


def cmd_research_lineage(args):
    """Print the lineage chain root -> spec_id and optionally write DOT."""
    factory = _load_research_factory(args)
    chain = factory.get_lineage(args.spec_id)
    for c in chain:
        parent = c.spec.parent_spec_id or "-"
        print(
            f"{c.spec.spec_id} {c.spec.name} stage={c.stage.value} "
            f"parent={parent}"
        )
    if getattr(args, "graphviz", None):
        # Build a graph from EVERY known candidate (review + archive) so
        # the DOT shows the full DAG, not just the chain.
        from aurora.research.factory import LineageGraph
        graph = LineageGraph()
        graph.build(factory.list_review_queue())
        graph.build(factory.list_archived())
        with open(args.graphviz, "w", encoding="utf-8") as f:
            f.write(graph.dot_export())
        print(f"# wrote DOT graph to {args.graphviz}")
    return 0


def cmd_research_generate(args):
    """Bulk-generate strategy specs from a generator and write to a YAML file."""
    import yaml
    from aurora.research.factory import (
        StrategySpec, TemplateHypothesisGenerator,
    )
    gen_name = (args.generator or "template").lower()
    n = int(args.n)
    seed = int(args.seed)
    if gen_name == "template":
        # Use a small built-in template list. Real users override via a
        # custom generator in code; the CLI surface is just the demo path.
        templates = [
            (
                "macross_20_100",
                "aurora.strategies.library.ma_cross.MACross",
                {"fast": 20, "slow": 100, "allow_short": False},
                {"fast": (0.5, 1.5), "slow": (0.8, 1.5)},
            ),
            (
                "tsmom_60",
                "aurora.strategies.library.tsmom.TSMomentum",
                {"lookback": 60, "skip": 0},
                {"lookback": (0.5, 2.0)},
            ),
        ]
        gen = TemplateHypothesisGenerator(
            templates, universe=args.universe.split(","),
            rebalance=args.rebalance,
        )
    else:
        return _runtime_error(
            f"generator {gen_name!r} not supported by `forge research generate`. "
            "Implement a custom generator in code and call ResearchFactory.submit_batch."
        )
    specs = gen.generate(n=n, seed=seed)
    payload = {"specs": [s.to_dict() for s in specs]}
    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)
    print(f"wrote {len(specs)} specs to {args.output}")
    return 0


def cmd_research_promote(args):
    """Promote a review-queue candidate to OOS_LOCKED testing.

    Hard-gated by:
      1. ``--i-understand-promote-to-oos-locked`` flag (CLI ceremony).
      2. an active :class:`OOSGuard` whose phase is
         ``"explicit_unlock_oos_locked"``.

    The actual lockbox-aware validation is delegated to ``forge validate
    --tier oos_locked``; this command's job is to *enter* the lockbox
    ceremony in a controlled way and emit the relevant invocation.
    """
    if not getattr(args, "i_understand", False):
        return _runtime_error(
            "research promote requires --i-understand-promote-to-oos-locked. "
            "OOS_LOCKED is the protocol's single-look ceremony."
        )
    from aurora.core.data_layer import OOSGuard
    factory = _load_research_factory(args)
    candidates = factory.list_review_queue()
    match = next(
        (c for c in candidates if c.candidate_id == args.candidate_id),
        None,
    )
    if match is None:
        return _runtime_error(
            f"candidate_id {args.candidate_id!r} not found in review queue."
        )
    active = OOSGuard.active()
    if active is None or active.phase != "explicit_unlock_oos_locked":
        return _runtime_error(
            "research promote requires an active "
            "OOSGuard('explicit_unlock_oos_locked'); none found. "
            "Wrap the call in `with OOSGuard(\"explicit_unlock_oos_locked\"):` "
            "and re-run, or use the lockbox CI workflow."
        )
    # The promotion itself is a controlled handoff: log the candidate's
    # spec_hash + auditor_report_hash to the OOSGuard's authorized_reads
    # trail, then exit 0. The actual OOS_LOCKED validation is invoked
    # separately by `forge validate --tier oos_locked`.
    active.record_oos_read(
        f"research_promote candidate_id={match.candidate_id} "
        f"spec_hash={match.spec.spec_hash[:12]} "
        f"auditor_hash={(match.auditor_report_hash or 'none')[:12]}"
    )
    print(
        f"PROMOTED {match.candidate_id} ({match.spec.name}) into OOS_LOCKED "
        f"ceremony. Run:\n"
        f"  forge validate --strategy {match.spec.strategy_class.rsplit('.', 1)[-1]} "
        f"--asset {match.spec.universe[0] if match.spec.universe else 'SPY'} "
        f"--tier oos_locked --i-understand-ceremony"
    )
    return 0


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
# Agent gateway commands (P1.A)
# ---------------------------------------------------------------------------


def _agent_gateway_from_args(args):
    """Construct an :class:`AgentGateway` using config + args overrides.

    Honors ``--audit-path`` if provided, otherwise reads
    ``quantforge/config/agent_gateway.yaml``.
    """
    import os as _os
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
    gw = _agent_gateway_from_args(args)
    # The CLI cannot reconstruct a CommittedAction from disk yet (the
    # in-memory map only persists for the lifetime of the gateway). For
    # now this is a safe error rather than a no-op.
    return _runtime_error(
        "agent push requires an in-process CommittedAction; "
        "use the Python API (gateway.push) or extend the CLI to persist "
        "committed actions to disk."
    )


# ---------------------------------------------------------------------------
# ops subcommands (P2.B daily operational report)
# ---------------------------------------------------------------------------


def _build_ops_report(args):
    """Shared helper for ops commands that need a DailyOpsReport."""
    from pathlib import Path as _Path

    import pandas as pd

    from aurora.core.protocol_policy import get_active_policy
    from aurora.reporting.daily_ops import (
        DailyOpsBuilder,
        DailyOpsConfig,
    )

    if getattr(args, "asof", None):
        asof = pd.Timestamp(args.asof)
    else:
        # default: today's date (kept simple; deterministic given the call).
        asof = pd.Timestamp.today().normalize()
    strategies = (
        [s for s in args.strategies.split(",") if s]
        if getattr(args, "strategies", None) else []
    )
    if not strategies:
        # Fall back to a placeholder so the report still renders.
        strategies = ["(none)"]
    fmt = (
        [s for s in args.format.split(",") if s]
        if getattr(args, "format", None) else ["md", "json"]
    )
    portfolio_id = getattr(args, "portfolio", None)
    output_dir = (
        _Path(args.output_dir) if getattr(args, "output_dir", None)
        else None
    )
    cfg = DailyOpsConfig(
        asof_date=asof,
        strategies=strategies,
        portfolio_id=portfolio_id,
        output_format=fmt,
        output_dir=output_dir,
    )
    policy = get_active_policy()
    return DailyOpsBuilder(cfg, policy).build()


def cmd_ops_daily(args):
    """Build the daily ops report. Writes md/json artifacts to disk."""
    from pathlib import Path as _Path

    report = _build_ops_report(args)
    out_dir = (
        _Path(args.output_dir) if getattr(args, "output_dir", None)
        else None
    )
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        date = report.asof_date.date().isoformat()
        if "md" in (args.format or "").split(","):
            (out_dir / f"daily_{date}.md").write_text(
                report.to_markdown(), encoding="utf-8"
            )
        if "json" in (args.format or "").split(","):
            (out_dir / f"daily_{date}.json").write_text(
                report.to_json(), encoding="utf-8"
            )
    # Always print the markdown to stdout so the user sees the result.
    print(report.to_markdown())
    # Exit code 1 if any critical alert is present.
    return 1 if report.has_critical_alerts() else 0


def cmd_ops_alerts(args):
    """Print only the alerts. ``--severity`` filters output."""
    import json as _json

    report = _build_ops_report(args)
    severity = (args.severity or "").lower().strip()
    alerts = list(report.alerts)
    if severity:
        if severity not in ("info", "warn", "critical"):
            return _runtime_error(
                f"--severity must be info|warn|critical, got {severity!r}"
            )
        # Show >= the requested severity.
        order = {"info": 0, "warn": 1, "critical": 2}
        cutoff = order[severity]
        alerts = [a for a in alerts if order[a.severity] >= cutoff]
    if getattr(args, "json", False):
        print(_json.dumps([a.to_dict() for a in alerts], indent=2))
    else:
        if not alerts:
            print("No alerts.")
        else:
            for a in alerts:
                print(f"[{a.severity.upper()}] {a.code}: {a.title}")
                if a.detail:
                    print(f"  {a.detail}")
                if a.suggested_action:
                    print(f"  -> {a.suggested_action}")
    return 1 if any(a.severity == "critical" for a in alerts) else 0


def cmd_ops_summary(args):
    """Print the one-line summary (cron / slack friendly)."""
    report = _build_ops_report(args)
    print(report.to_summary_line())
    return 0


# ---------------------------------------------------------------------------
# Export subcommands (P3.B Lean export adapter)
# ---------------------------------------------------------------------------


def _strategy_spec_for_export(spec_path):
    """Load a StrategySpec from YAML/JSON for the Lean exporter.

    Reuses ``_strategy_spec_from_yaml``; isolated here so the export
    flow stays decoupled from research-factory specifics in future
    refactors (e.g. supporting a GA spec file directly).
    """
    return _strategy_spec_from_yaml(spec_path)


def cmd_export_lean(args):
    """Export a vetted QuantForge spec to a Lean (QuantConnect) project."""
    import json as _json
    from pathlib import Path as _Path

    import pandas as _pd

    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.exports.lean import LeanExportConfig, LeanExporter

    spec = _strategy_spec_for_export(args.spec_path)
    target_dir = _Path(args.target_dir).resolve()
    if not target_dir.parent.exists():
        return _runtime_error(
            f"target-dir parent does not exist: {target_dir.parent}"
        )
    target_dir.mkdir(parents=True, exist_ok=True)

    start = _pd.Timestamp(args.start_date) if args.start_date else _pd.Timestamp("2015-01-01")
    end = _pd.Timestamp(args.end_date) if args.end_date else None
    cfg = LeanExportConfig(
        target_directory=target_dir,
        project_name=args.project_name,
        cash=float(args.cash),
        benchmark=args.benchmark,
        resolution=args.resolution,
        universe_resolution=args.resolution,
        start_date=start,
        end_date=end,
    )
    policy = ProtocolPolicy.load()
    exporter = LeanExporter(cfg, policy)
    marker = None
    if args.validation_marker:
        try:
            marker = _json.loads(args.validation_marker)
        except Exception as e:
            return _runtime_error(f"--validation-marker must be JSON: {e}")
    try:
        artifact = exporter.export(spec, validation_marker=marker, force=args.force)
    except FileExistsError as e:
        return _runtime_error(str(e))
    print(_json.dumps({
        "project_name": artifact.project_name,
        "policy_hash": artifact.policy_hash,
        "files": [str(f) for f in artifact.files_written],
    }, indent=2))
    return 0


def cmd_export_lean_list(args):
    """Print the per-strategy translation tier (full/partial/scaffold-only)."""
    from aurora.exports.lean.exporter import list_translation_tiers

    rows = list_translation_tiers()
    width = max((len(n) for n, _ in rows), default=10)
    for name, tier in rows:
        print(f"{name.ljust(width)}  {tier}")
    return 0


def cmd_export_verify(args):
    """Verify provenance of a Lean export against the active policy."""
    import json as _json
    from pathlib import Path as _Path

    from aurora.exports.lean.exporter import verify_project

    result = verify_project(_Path(args.project_dir))
    if getattr(args, "json", False):
        # Avoid serializing nested Path objects in metadata if present.
        print(_json.dumps({
            "ok": result["ok"],
            "errors": result["errors"],
            "metadata": result["metadata"],
        }, indent=2, default=str))
    else:
        if result["ok"]:
            print("OK")
        else:
            print("FAIL")
            for e in result["errors"]:
                print(f"  - {e}")
    return 0 if result["ok"] else 1


# ---------------------------------------------------------------------------
# Triage subcommands (P2.A vectorized screening)
# ---------------------------------------------------------------------------


def _load_triage_config(args):
    """Load TriageConfig from --config-path / args overrides / bundled YAML."""
    import os
    from aurora.triage import TriageConfig

    cfg_path = getattr(args, "config_path", None)
    if cfg_path and os.path.exists(cfg_path):
        cfg = TriageConfig.from_yaml(cfg_path)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        bundled = os.path.normpath(
            os.path.join(here, "..", "config", "triage.yaml")
        )
        if os.path.exists(bundled):
            cfg = TriageConfig.from_yaml(bundled)
        else:
            cfg = TriageConfig()
    if getattr(args, "use_vectorbt", False):
        from dataclasses import replace as _replace
        cfg = _replace(cfg, use_vectorbt=True)
    if getattr(args, "tier", None):
        from dataclasses import replace as _replace
        cfg = _replace(cfg, triage_tier_only=str(args.tier).upper())
    return cfg


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
    return [StrategyVariant.from_dict(d) for d in raw]


def _load_triage_prices(symbol: str, tier: str):
    """Load a price DataFrame for the given symbol on the given tier."""
    from aurora.core.data_tiers import load_tier
    ser = load_tier(symbol, tier=tier.upper())
    return ser.to_frame(name=symbol)


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


def cmd_research_triage(args):
    """Run triage as a screening pass on a research specs file."""
    from dataclasses import replace as _replace
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.triage import StrategyVariant, TriageEngine

    cfg = _load_triage_config(args)
    threshold = getattr(args, "threshold", None)
    if threshold:
        for kv in str(threshold).split(","):
            if "=" in kv:
                k, _, v = kv.partition("=")
                k = k.strip()
                if k == "sharpe":
                    cfg = _replace(cfg, min_sharpe_threshold=float(v))
                elif k == "max_dd":
                    cfg = _replace(cfg, max_dd_threshold=float(v))
                elif k == "min_trades":
                    cfg = _replace(cfg, min_trades=int(v))
    policy = ProtocolPolicy.load()
    engine = TriageEngine(cfg, policy)
    specs = _strategy_specs_from_yaml(args.specs)
    if not specs:
        return _runtime_error("specs file produced zero specs")
    variants = [
        StrategyVariant.make(
            strategy_class=s.strategy_class,
            params=s.params,
            universe=s.universe,
            rebalance=s.rebalance,
        )
        for s in specs
    ]
    sym = specs[0].universe[0] if specs[0].universe else "SPY"
    prices = _load_triage_prices(sym, cfg.triage_tier_only)
    batch = engine.triage_batch(prices, variants)
    print(
        f"triage: {batch.n_variants} specs scored, "
        f"{batch.n_promising} promising"
    )
    for r in batch.results:
        flag = "PROMISING" if r.promising else "rejected"
        reason = r.rejection_reason or "-"
        print(
            f"  [{flag:9s}] {r.variant_id[:10]} "
            f"sharpe={r.sharpe:.2f} mdd={r.max_dd:.2f} "
            f"n_trades={r.n_trades} reason={reason}"
        )
    return 0 if batch.n_promising > 0 else 1


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", default=None,
        help="Path to ForgeConfig YAML/TOML. Defaults to built-in defaults.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logger level for the quantforge namespace [default: INFO].",
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

    # run -------------------------------------------------------------------
    p_run = sub.add_parser(
        "run", help="Backtest a single strategy",
        description="Backtest a strategy at default parameters and print metrics.",
    )
    p_run.add_argument("--strategy", required=True, help="Strategy name (see list-strategies)")
    p_run.add_argument("--asset", default="SPY", help="Ticker symbol [default: SPY]")
    p_run.add_argument("--costs", choices=["zero", "ibkr"], default="ibkr")
    p_run.add_argument("--seed", type=int, default=42)
    p_run.add_argument("--dry-run", action="store_true",
                       help="Print resolved config and exit without executing.")
    _add_tier_arg(p_run)
    p_run.set_defaults(func=cmd_run)

    # validate --------------------------------------------------------------
    p_val = sub.add_parser(
        "validate",
        help="Run 8-gate orchestrator (5 mandatory + DSR + 2 optional)",
        description=(
            "Run the 8-gate validation orchestrator: 5 mandatory gates "
            "(walk-forward, MC bootstrap, MC trade-reorder, SPP, "
            "lookahead) + DSR + 2 optional gates (noise injection, "
            "gap simulation)."
        ),
    )
    p_val.add_argument("--strategy", required=True)
    p_val.add_argument("--asset", default="SPY")
    p_val.add_argument("--n-trials", type=int, default=1, help="N strategies tested for DSR")
    p_val.add_argument("--costs", choices=["zero", "ibkr"], default="ibkr")
    p_val.add_argument("--mc-paths", type=int, default=500)
    p_val.add_argument("--seed", type=int, default=42)
    p_val.add_argument("--dry-run", action="store_true",
                       help="Print resolved config and exit without executing.")
    # P2.2 round-4 audit -- explicit tier flag for formal validation.
    # Default remains oos_dev. oos_locked/forward additionally require
    # --i-understand-ceremony to acknowledge unsealing the locked tier.
    # P0.A: choices come from ``ProtocolPolicy.tiers`` (the OOS-bearing
    # tiers).
    _validate_tier_choices = [
        t for t in _policy_tier_choices()
        if t in ("oos_dev", "oos_locked", "forward")
    ] or ["oos_dev", "oos_locked", "forward"]
    p_val.add_argument(
        "--tier", default="oos_dev",
        choices=_validate_tier_choices,
        help=("Formal validation tier. Default: oos_dev. "
              "oos_locked/forward require --i-understand-ceremony AND "
              "wrap validate_pipeline in the matching OOSGuard ceremony."),
    )
    p_val.add_argument(
        "--i-understand-ceremony", action="store_true",
        help=("Required when --tier is oos_locked or forward; "
              "acknowledges that this run unseals a locked tier."),
    )
    p_val.set_defaults(func=cmd_validate)

    # search ----------------------------------------------------------------
    p_search = sub.add_parser(
        "search", help="GA strategy parameter search",
        description="Run NSGA-II multi-objective search over strategy parameters.",
    )
    p_search.add_argument("--strategy", required=True)
    p_search.add_argument("--asset", default="SPY")
    p_search.add_argument("--population", type=int, default=100)
    p_search.add_argument("--generations", type=int, default=20)
    p_search.add_argument("--seed", type=int, default=42)
    p_search.add_argument("--skip-oos", action="store_true",
                          help="Skip post-GA OOS validation of top candidates.")
    p_search.add_argument("--oos-top", type=int, default=5,
                          help="Number of top Pareto candidates to OOS-validate "
                               "(default 5).")
    p_search.add_argument(
        "--is-tier", default="is_train", choices=["is_train", "is_all"],
        help=("In-sample tier the GA fitness loop sees: 'is_train' (default, "
              "<=2010-12-31) or 'is_all' (IS_TRAIN + IS_VALID, <=2012-12-31)."),
    )
    p_search.add_argument("--dry-run", action="store_true",
                          help="Print resolved config and exit without executing.")
    p_search.set_defaults(func=cmd_search)

    # list-strategies -------------------------------------------------------
    p_ls = sub.add_parser(
        "list-strategies", help="List available strategies and their specs",
        description="Print all registered strategies with default parameters and ranges.",
    )
    p_ls.set_defaults(func=cmd_list_strategies)

    # tearsheet -------------------------------------------------------------
    p_ts = sub.add_parser(
        "tearsheet", help="Generate HTML tearsheet from a backtest",
        description="Run backtest and write a self-contained HTML tearsheet.",
    )
    p_ts.add_argument("--strategy", required=True)
    p_ts.add_argument("--asset", default="SPY")
    p_ts.add_argument("--output", default="tearsheet.html", help="Output HTML path")
    p_ts.add_argument("--title", default=None, help="Optional title override")
    p_ts.add_argument("--costs", choices=["zero", "ibkr"], default="ibkr")
    p_ts.add_argument("--seed", type=int, default=42)
    _add_tier_arg(p_ts)
    p_ts.set_defaults(func=cmd_tearsheet)

    # bench -----------------------------------------------------------------
    p_bench = sub.add_parser(
        "bench", help="Benchmark backtest engine speed",
        description="Compare sequential vs JIT engine on synthetic prices.",
    )
    p_bench.add_argument("--strategy", default="MACross", help="Strategy to benchmark")
    p_bench.add_argument("--n", type=int, default=10000, help="Number of synthetic bars")
    p_bench.add_argument("--repeats", type=int, default=3, help="Iterations to average")
    p_bench.add_argument("--costs", choices=["zero", "ibkr"], default="zero")
    p_bench.add_argument("--seed", type=int, default=42)
    p_bench.set_defaults(func=cmd_bench)

    # config ----------------------------------------------------------------
    p_cfg = sub.add_parser(
        "config", help="Inspect or scaffold ForgeConfig",
        description="Subcommands: show | init.",
    )
    sub_cfg = p_cfg.add_subparsers(dest="config_cmd", required=True)

    p_show = sub_cfg.add_parser("show", help="Print loaded config")
    p_show.add_argument("--format", choices=["yaml", "json"], default="yaml")
    p_show.set_defaults(func=cmd_config_show)

    p_init = sub_cfg.add_parser("init", help="Write default config to file")
    p_init.add_argument("--output", required=True, help="Output path (.yaml/.yml/.toml)")
    p_init.add_argument("--force", action="store_true", help="Overwrite if exists")
    p_init.set_defaults(func=cmd_config_init)

    # preflight -------------------------------------------------------------
    p_pf = sub.add_parser(
        "preflight", help="Run pre-trade preflight checks",
        description="Run preflight gates (data, anti-lookahead, marker, sizing, ...).",
    )
    p_pf.add_argument("--strategy", required=True)
    p_pf.add_argument("--symbol", required=True, help="Symbol the strategy will trade")
    p_pf.add_argument("--min-bars", type=int, default=200)
    p_pf.add_argument("--max-position-pct", type=float, default=1.0)
    p_pf.add_argument("--project-dir", default=".", help="Project root for marker lookup")
    p_pf.add_argument("--min-disk-mb", type=int, default=100)
    p_pf.add_argument("--seed", type=int, default=42)
    p_pf.set_defaults(func=cmd_preflight)

    # label -----------------------------------------------------------------
    p_lab = sub.add_parser(
        "label", help="Apply triple-barrier labeling",
        description="Label every bar with profit/stop/vertical-time barriers.",
    )
    p_lab.add_argument("--asset", required=True, help="Ticker symbol")
    p_lab.add_argument("--pt", type=float, default=1.0, help="Profit-take vol multiplier")
    p_lab.add_argument("--sl", type=float, default=1.0, help="Stop-loss vol multiplier")
    p_lab.add_argument("--hp", type=int, default=5, help="Holding period in calendar days")
    p_lab.add_argument("--min-return", type=float, default=0.0,
                       help="Min |return| to count as labeled non-zero")
    p_lab.add_argument("--output", default=None, help="CSV/JSON output path")
    p_lab.add_argument("--seed", type=int, default=42)
    _add_tier_arg(p_lab)
    p_lab.set_defaults(func=cmd_label)

    # factor ----------------------------------------------------------------
    p_fac = sub.add_parser(
        "factor", help="Compute factor analysis on a strategy",
        description="IC / quantile-spread / turnover summary across forward periods.",
    )
    p_fac.add_argument("--strategy", required=True)
    p_fac.add_argument("--asset", required=True, help="Ticker symbol")
    p_fac.add_argument("--periods", default="1,5,20",
                       help="Comma-separated forward periods, e.g. 1,5,20")
    p_fac.add_argument("--output", default=None, help="CSV/JSON output path")
    p_fac.add_argument("--seed", type=int, default=42)
    _add_tier_arg(p_fac)
    p_fac.set_defaults(func=cmd_factor)

    # attribute -------------------------------------------------------------
    p_attr = sub.add_parser(
        "attribute", help="Performance attribution for a strategy",
        description="Factor or per-regime attribution.",
    )
    p_attr.add_argument("--strategy", required=True)
    p_attr.add_argument("--asset", required=True)
    p_attr.add_argument("--benchmark", default=None,
                        help="Benchmark ticker for factor attribution")
    p_attr.add_argument("--regime", default=None,
                        help="Comma-separated regime labels to include")
    p_attr.add_argument("--regime-file", default=None,
                        help="CSV (date, label) for regime labels")
    p_attr.add_argument("--costs", choices=["zero", "ibkr"], default="ibkr")
    p_attr.add_argument("--output", default=None, help="CSV/JSON output path")
    p_attr.add_argument("--seed", type=int, default=42)
    _add_tier_arg(p_attr)
    p_attr.set_defaults(func=cmd_attribute)

    # purge-cv --------------------------------------------------------------
    p_pcv = sub.add_parser(
        "purge-cv", help="Purged k-fold cross-validation",
        description="Lopez de Prado purged + embargoed K-fold backtest.",
    )
    p_pcv.add_argument("--strategy", required=True)
    p_pcv.add_argument("--asset", required=True)
    p_pcv.add_argument("--k", type=int, default=5, help="Number of folds (>= 2)")
    p_pcv.add_argument("--embargo", type=float, default=0.01,
                       help="Embargo fraction in [0, 1)")
    p_pcv.add_argument("--costs", choices=["zero", "ibkr"], default="ibkr")
    p_pcv.add_argument("--output", default=None, help="CSV/JSON output path")
    p_pcv.add_argument("--seed", type=int, default=42)
    _add_tier_arg(p_pcv)
    p_pcv.set_defaults(func=cmd_purge_cv)

    # fracdiff --------------------------------------------------------------
    p_fd = sub.add_parser(
        "fracdiff", help="Find minimum d for stationarity",
        description="Sweep d and report ADF p-value of the differentiated log price.",
    )
    p_fd.add_argument("--asset", required=True)
    p_fd.add_argument("--max-d", type=float, default=1.0)
    p_fd.add_argument("--step", type=float, default=0.05)
    p_fd.add_argument("--threshold", type=float, default=1e-5,
                      help="Weight cutoff for FFD window")
    p_fd.add_argument("--adf-pvalue", type=float, default=0.05,
                      help="Stationarity threshold")
    p_fd.add_argument("--sweep", action="store_true",
                      help="Print full d/ADF/correlation table")
    p_fd.add_argument("--output", default=None, help="CSV/JSON output path")
    p_fd.add_argument("--seed", type=int, default=42)
    _add_tier_arg(p_fd)
    p_fd.set_defaults(func=cmd_fracdiff)

    # cscv ------------------------------------------------------------------
    p_cscv = sub.add_parser(
        "cscv", help="CSCV / PBO test from strategy returns",
        description="Combinatorially symmetric CV + Probability of Backtest Overfitting.",
    )
    p_cscv.add_argument("--returns-csv", required=True,
                        help="CSV: rows=time, cols=N strategies (first col=date)")
    p_cscv.add_argument("--n-splits", type=int, default=16,
                        help="Even number of time slices (default 16)")
    p_cscv.add_argument("--max-combos", type=int, default=20000,
                        help="Cap on combinations enumerated")
    p_cscv.add_argument("--output", default=None, help="JSON/CSV summary path")
    p_cscv.add_argument("--seed", type=int, default=42)
    p_cscv.set_defaults(func=cmd_cscv)

    # search-multi ---------------------------------------------------------
    p_smulti = sub.add_parser(
        "search-multi", help="Multi-asset GA search (P2.4 round-4 audit)",
        description=(
            "Run NSGA-II GA on a multi-asset strategy. Each --asset is "
            "loaded via load_tier(asset, 'IS_TRAIN') so tier ceremony "
            "rules apply. Uses the IS-only fitness signature."
        ),
    )
    p_smulti.add_argument("--strategy", required=True)
    p_smulti.add_argument("--asset", action="append", required=True,
                           help="Repeat for each symbol (>= 2).")
    p_smulti.add_argument("--population", type=int, default=30)
    p_smulti.add_argument("--generations", type=int, default=5)
    p_smulti.add_argument("--seed", type=int, default=42)
    p_smulti.add_argument(
        "--is-tier", default="is_train",
        choices=["is_train", "is_valid"],
        help="In-sample tier for the GA (default is_train).",
    )
    p_smulti.set_defaults(func=cmd_search_multi)

    # freeze ----------------------------------------------------------------
    p_freeze = sub.add_parser(
        "freeze", help="Freeze a snapshot of an asset's price series",
        description=(
            "P1.3 round-4 audit: register a hash-verified snapshot of "
            "the loaded asset price series in the SnapshotStore. The "
            "resulting SHA-256 + data_path are printed. Use --locked to "
            "mark the snapshot as locked (load requires "
            "OOSGuard('explicit_unlock_snapshot'))."
        ),
    )
    p_freeze.add_argument("--asset", required=True, help="Ticker symbol")
    p_freeze.add_argument("--locked", action="store_true",
                           help="Mark the snapshot as locked (e.g. OOS slice)")
    p_freeze.add_argument("--provenance", default="yfinance",
                           help="Provenance label for the snapshot")
    p_freeze.add_argument("--seed", type=int, default=42)
    p_freeze.set_defaults(func=cmd_freeze)

    # data ------------------------------------------------------------------
    # P0.B: DataProviderRegistry CLI surface.
    p_data = sub.add_parser(
        "data",
        help="Data provider registry (list-providers, fetch, verify)",
        description=(
            "Manage the DataProviderRegistry: list registered providers, "
            "fetch a dataset to parquet (with sidecar metadata), or "
            "verify the content_hash of a previously-fetched file."
        ),
    )
    data_sub = p_data.add_subparsers(dest="data_cmd", required=True)

    p_data_ls = data_sub.add_parser(
        "list-providers",
        help="List registered providers and their PIT/tier posture",
    )
    p_data_ls.set_defaults(func=cmd_data_list_providers)

    p_data_fetch = data_sub.add_parser(
        "fetch", help="Fetch a Dataset and write parquet + sidecar metadata",
    )
    p_data_fetch.add_argument("provider", help="Registered provider name")
    p_data_fetch.add_argument("symbol", help="Ticker symbol")
    p_data_fetch.add_argument("--start", default=None, help="ISO start date")
    p_data_fetch.add_argument("--end", default=None, help="ISO end date")
    p_data_fetch.add_argument(
        "--output", required=True,
        help="Path to write the parquet file (sidecar gets .meta.json suffix)",
    )
    p_data_fetch.set_defaults(func=cmd_data_fetch)

    p_data_verify = data_sub.add_parser(
        "verify", help="Recompute content_hash and check tier permission",
    )
    p_data_verify.add_argument("parquet", help="Path to a parquet emitted by ``data fetch``")
    p_data_verify.set_defaults(func=cmd_data_verify)

    # crypto ----------------------------------------------------------------
    # P3.A: optional CCXT-backed crypto data + execution.
    p_crypto = sub.add_parser(
        "crypto",
        help="Crypto data + execution via CCXT (optional dep)",
        description=(
            "Crypto integration via the optional ``ccxt`` package. "
            "Sandbox by default; live trading requires a triple-gate: "
            "gateway_committed + OOSGuard ceremony + allow-live token."
        ),
    )
    crypto_sub = p_crypto.add_subparsers(dest="crypto_cmd", required=True)

    p_cx_ex = crypto_sub.add_parser(
        "exchanges", help="List ccxt-supported exchanges (lazy import)",
    )
    p_cx_ex.set_defaults(func=cmd_crypto_exchanges)

    p_cx_fetch = crypto_sub.add_parser(
        "fetch", help="Fetch OHLCV crypto data via CCXTProvider",
    )
    p_cx_fetch.add_argument("symbol", help="Symbol e.g. BTC/USDT")
    p_cx_fetch.add_argument("--exchange", default=None,
                            help="ccxt exchange id (default from config)")
    p_cx_fetch.add_argument("--timeframe", default="1d",
                            help="Candle timeframe (1m/5m/1h/1d/...)")
    p_cx_fetch.add_argument("--start", default=None, help="ISO start date")
    p_cx_fetch.add_argument("--end", default=None, help="ISO end date")
    p_cx_fetch.add_argument("--output", required=True,
                            help="Parquet output path")
    p_cx_fetch.set_defaults(func=cmd_crypto_fetch)

    p_cx_submit = crypto_sub.add_parser(
        "submit-order", help="Submit a crypto order via CCXTBrokerAdapter",
    )
    p_cx_submit.add_argument("--exchange", default=None)
    p_cx_submit.add_argument("--symbol", required=True)
    p_cx_submit.add_argument("--side", choices=["buy", "sell"], required=True)
    p_cx_submit.add_argument("--qty", required=True)
    p_cx_submit.add_argument("--type", choices=["market", "limit"],
                             default="market")
    p_cx_submit.add_argument("--limit-price", default=None,
                             dest="limit_price")
    p_cx_submit.add_argument("--sandbox", action="store_true",
                             help="Force sandbox mode (default)")
    p_cx_submit.add_argument("--allow-live", action="store_true",
                             dest="allow_live",
                             help="Disable sandbox; requires triple-gate")
    p_cx_submit.set_defaults(func=cmd_crypto_submit_order)

    p_cx_pos = crypto_sub.add_parser(
        "positions", help="Show CCXT positions",
    )
    p_cx_pos.add_argument("--exchange", default=None)
    p_cx_pos.set_defaults(func=cmd_crypto_positions)

    p_cx_bal = crypto_sub.add_parser(
        "balance", help="Show CCXT balance",
    )
    p_cx_bal.add_argument("--exchange", default=None)
    p_cx_bal.set_defaults(func=cmd_crypto_balance)

    p_cx_allow = crypto_sub.add_parser(
        "allow-live", help="Write one-time allow-live consent token",
    )
    p_cx_allow.add_argument("exchange",
                            help="Exchange id, e.g. binance")
    p_cx_allow.add_argument("--token-dir", default=None, dest="token_dir",
                            help="Override token storage directory")
    p_cx_allow.set_defaults(func=cmd_crypto_allow_live)

    # export -----------------------------------------------------------------
    # P3.B: Lean (QuantConnect) cross-validation adapter.
    p_export = sub.add_parser(
        "export",
        help="Cross-validation adapters (Lean / QuantConnect)",
        description=(
            "Export a vetted QuantForge spec to a Lean (QuantConnect) C# "
            "project skeleton + provenance metadata for cross-validation. "
            "Export only -- promotion still goes through the QuantForge "
            "research protocol."
        ),
    )
    export_sub = p_export.add_subparsers(dest="export_cmd", required=True)

    p_ex_lean = export_sub.add_parser(
        "lean",
        help="Export a single StrategySpec (YAML/JSON) to a Lean project",
    )
    p_ex_lean.add_argument("spec_path",
                            help="Path to a single-spec YAML/JSON file")
    p_ex_lean.add_argument("--target-dir", required=True, dest="target_dir",
                            help="Parent dir; project goes under <target_dir>/<project_name>/")
    p_ex_lean.add_argument("--project-name", required=True, dest="project_name",
                            help="Lean project / C# class name (sanitized)")
    p_ex_lean.add_argument("--cash", default="100000",
                            help="Initial cash for SetCash() [default: 100000]")
    p_ex_lean.add_argument("--benchmark", default="SPY",
                            help="Lean benchmark symbol [default: SPY]")
    p_ex_lean.add_argument(
        "--resolution", default="Daily",
        choices=["Daily", "Hour", "Minute", "Tick"],
        help="Lean Resolution enum value [default: Daily]",
    )
    p_ex_lean.add_argument("--start-date", default=None, dest="start_date",
                            help="Backtest start date (YYYY-MM-DD)")
    p_ex_lean.add_argument("--end-date", default=None, dest="end_date",
                            help="Backtest end date (YYYY-MM-DD); omit for open")
    p_ex_lean.add_argument(
        "--validation-marker", default=None, dest="validation_marker",
        help="JSON blob recorded as 'validation_marker' in qf_metadata.json",
    )
    p_ex_lean.add_argument("--force", action="store_true",
                            help="Overwrite existing project directory")
    p_ex_lean.set_defaults(func=cmd_export_lean)

    p_ex_list = export_sub.add_parser(
        "lean-list",
        help="List strategies with translation tier (full/partial/scaffold-only)",
    )
    p_ex_list.set_defaults(func=cmd_export_lean_list)

    p_ex_verify = export_sub.add_parser(
        "verify",
        help="Verify qf_metadata.json provenance for an exported Lean project",
    )
    p_ex_verify.add_argument("project_dir",
                              help="Path to a Lean project produced by 'forge export lean'")
    p_ex_verify.add_argument("--json", action="store_true",
                              help="Print verification result as JSON")
    p_ex_verify.set_defaults(func=cmd_export_verify)

    # dashboard -------------------------------------------------------------
    p_dash = sub.add_parser(
        "dashboard", help="Launch live Streamlit dashboard",
        description=("Wrap 'streamlit run' to serve the QuantForge live "
                     "dashboard against a trade journal SQLite file."),
    )
    p_dash.add_argument("--journal", default="aurora.db",
                        help="Path to the trade journal SQLite database")
    p_dash.add_argument("--refresh", type=int, default=30,
                        help="Auto-refresh interval in seconds")
    p_dash.add_argument("--port", type=int, default=None,
                        help="Override Streamlit server port")
    p_dash.add_argument("--headless", action="store_true",
                        help="Run Streamlit in headless mode (no browser open)")
    p_dash.set_defaults(func=cmd_dashboard)

    # research --------------------------------------------------------------
    # P1.C: ResearchFactory pipeline (hypothesis -> review queue).
    p_research = sub.add_parser(
        "research",
        help="Research Factory: submit specs, list review queue / archive, "
             "lineage, generate, promote to OOS_LOCKED",
        description=(
            "P1.C Research Factory. Submit StrategySpec proposals to the "
            "automated IS / WF / OOS_DEV pipeline; failed candidates are "
            "archived with a categorical reason; promising candidates "
            "land in the review queue. Promotion to OOS_LOCKED requires "
            "the lockbox ceremony."
        ),
    )
    research_sub = p_research.add_subparsers(dest="research_cmd", required=True)

    p_rs_submit = research_sub.add_parser(
        "submit", help="Submit one StrategySpec (YAML or JSON) to the factory",
    )
    p_rs_submit.add_argument("spec_path",
                              help="Path to a single-spec YAML/JSON file")
    p_rs_submit.add_argument(
        "--config-path", default=None, dest="config_path",
        help="Optional path to a research_factory.yaml override",
    )
    p_rs_submit.add_argument("--json", action="store_true",
                              help="Print outcome as JSON")
    p_rs_submit.set_defaults(func=cmd_research_submit)

    p_rs_batch = research_sub.add_parser(
        "batch", help="Submit a batch (YAML/JSON with a 'specs' list)",
    )
    p_rs_batch.add_argument("specs_path",
                             help="Path to a YAML/JSON file with 'specs:'")
    p_rs_batch.add_argument(
        "--config-path", default=None, dest="config_path",
        help="Optional path to a research_factory.yaml override",
    )
    p_rs_batch.add_argument("--json", action="store_true",
                             help="Print outcomes as JSON")
    p_rs_batch.set_defaults(func=cmd_research_batch)

    p_rs_review = research_sub.add_parser(
        "review-queue", help="List candidates currently awaiting human review",
    )
    p_rs_review.add_argument("--config-path", default=None, dest="config_path")
    p_rs_review.add_argument("--json", action="store_true")
    p_rs_review.set_defaults(func=cmd_research_review_queue)

    p_rs_arch = research_sub.add_parser(
        "archive", help="List archived (rejected) candidates",
    )
    p_rs_arch.add_argument("--config-path", default=None, dest="config_path")
    p_rs_arch.add_argument(
        "--reason", default=None,
        help="Filter by RejectionReason value "
             "(e.g. spec_invalid, is_sharpe_too_low, wf_degradation, ...)",
    )
    p_rs_arch.add_argument("--json", action="store_true")
    p_rs_arch.set_defaults(func=cmd_research_archive)

    p_rs_lin = research_sub.add_parser(
        "lineage", help="Print lineage chain (root -> spec_id)",
    )
    p_rs_lin.add_argument("spec_id", help="Spec id whose lineage to print")
    p_rs_lin.add_argument("--config-path", default=None, dest="config_path")
    p_rs_lin.add_argument("--graphviz", default=None,
                            help="Optional path to write a DOT graph")
    p_rs_lin.set_defaults(func=cmd_research_lineage)

    p_rs_gen = research_sub.add_parser(
        "generate",
        help="Bulk-generate a YAML 'specs' list from a built-in generator",
    )
    p_rs_gen.add_argument(
        "--generator", default="template",
        help="Generator name. Currently 'template' is supported on the CLI; "
             "ga / llm generators are code-only.",
    )
    p_rs_gen.add_argument("--n", type=int, default=10,
                           help="Number of specs to emit")
    p_rs_gen.add_argument("--seed", type=int, default=42)
    p_rs_gen.add_argument("--universe", default="SPY",
                           help="Comma-separated tickers for the universe")
    p_rs_gen.add_argument("--rebalance", default="1d")
    p_rs_gen.add_argument("--output", required=True,
                           help="Output YAML path (will contain a 'specs:' list)")
    p_rs_gen.set_defaults(func=cmd_research_generate)

    p_rs_prom = research_sub.add_parser(
        "promote",
        help="Promote a review-queue candidate to OOS_LOCKED ceremony",
        description=(
            "Move a candidate from the review queue into the OOS_LOCKED "
            "single-look ceremony. Requires both "
            "--i-understand-promote-to-oos-locked AND an active "
            "OOSGuard('explicit_unlock_oos_locked')."
        ),
    )
    p_rs_prom.add_argument("candidate_id",
                             help="Candidate id from `research review-queue`")
    p_rs_prom.add_argument(
        "--i-understand-promote-to-oos-locked",
        action="store_true", dest="i_understand",
        help="Required acknowledgement that this enters the OOS_LOCKED ceremony.",
    )
    p_rs_prom.add_argument("--config-path", default=None, dest="config_path")
    p_rs_prom.set_defaults(func=cmd_research_promote)

    # policy ----------------------------------------------------------------
    # P1.B: auditor subcommands.
    p_audit = sub.add_parser(
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

    # P0.A: surface the active ProtocolPolicy and verify YAML integrity.
    p_policy = sub.add_parser(
        "policy",
        help="Inspect / verify the active ProtocolPolicy",
        description=(
            "Surface or verify the active ProtocolPolicy. "
            "`show` prints the policy as YAML plus its sha256. "
            "`verify` recomputes the hash and compares to the YAML's "
            "declared hash, catching tampering."
        ),
    )
    policy_sub = p_policy.add_subparsers(dest="policy_cmd", required=True)
    p_pol_show = policy_sub.add_parser(
        "show", help="Print the active policy as YAML",
        description="Print the active ProtocolPolicy as YAML and its hash.",
    )
    p_pol_show.add_argument(
        "--path", default=None,
        help="Optional YAML path to read instead of the default config.",
    )
    p_pol_show.set_defaults(func=cmd_policy_show)
    p_pol_verify = policy_sub.add_parser(
        "verify", help="Recompute policy hash and compare to YAML",
        description=(
            "Recompute the policy_hash from the YAML body and compare to "
            "the declared hash. Exits 1 on mismatch (i.e. tamper)."
        ),
    )
    p_pol_verify.add_argument(
        "--path", default=None,
        help="Optional YAML path to verify (default: bundled config).",
    )
    p_pol_verify.set_defaults(func=cmd_policy_verify)

    # ops -------------------------------------------------------------------
    # P2.B: daily operational report.
    p_ops = sub.add_parser(
        "ops",
        help="Daily operational report and alerts",
        description=(
            "Build the daily ops report (performance, drawdown, exposure, "
            "signals, regime, attribution, no-trade reasoning, alerts) "
            "or extract just the alerts / one-line summary."
        ),
    )
    ops_sub = p_ops.add_subparsers(dest="ops_cmd", required=True)

    def _add_common_ops_args(parser):
        parser.add_argument(
            "--asof", default=None,
            help="ISO date for the report (YYYY-MM-DD). "
                 "Defaults to today's date.",
        )
        parser.add_argument(
            "--strategies", default="",
            help="Comma-separated strategy ids to include in the report.",
        )
        parser.add_argument(
            "--portfolio", default=None,
            help="Portfolio id label.",
        )
        parser.add_argument(
            "--format", default="md,json",
            help="Comma-separated output formats (md and/or json).",
        )

    p_ops_daily = ops_sub.add_parser(
        "daily",
        help="Build the full daily report",
        description=(
            "Assemble all sections + alert checks into a single artifact. "
            "Writes md/json to --output-dir if provided. Exit code 1 "
            "indicates at least one critical alert."
        ),
    )
    _add_common_ops_args(p_ops_daily)
    p_ops_daily.add_argument(
        "--output-dir", default=None, dest="output_dir",
        help="Directory to write daily_<date>.md / .json artifacts to.",
    )
    p_ops_daily.set_defaults(func=cmd_ops_daily)

    p_ops_alerts = ops_sub.add_parser(
        "alerts",
        help="Print only the alerts",
        description=(
            "Run the alert checks and print results. Filter by severity "
            "with --severity {info,warn,critical}. Use --json for JSON "
            "output."
        ),
    )
    _add_common_ops_args(p_ops_alerts)
    p_ops_alerts.add_argument(
        "--severity", default="",
        help="Minimum severity to print (info|warn|critical).",
    )
    p_ops_alerts.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    p_ops_alerts.set_defaults(func=cmd_ops_alerts)

    p_ops_summary = ops_sub.add_parser(
        "summary",
        help="Print one-line summary (cron / slack friendly)",
        description=(
            "Print a compact one-line digest of the report so a cron job "
            "or slack hook can consume it."
        ),
    )
    _add_common_ops_args(p_ops_summary)
    p_ops_summary.set_defaults(func=cmd_ops_summary)

    # agent -----------------------------------------------------------------
    # P1.A: scoped-token gateway for non-human actors.
    p_agent = sub.add_parser(
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

    # triage --------------------------------------------------------------
    # P2.A: vectorized triage backend for fast variant screening.
    p_triage = sub.add_parser(
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

    # research triage -- piggy-backs on the triage engine inside the
    # research factory namespace for parity with `forge research submit`.
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

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # Configure logging for the quantforge namespace based on --log-level.
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


if __name__ == "__main__":
    sys.exit(main())
