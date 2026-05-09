"""``forge run / validate / search / ...`` core analytical subcommands (R49 split).

This module groups the original "core" CLI commands: backtest run /
validate / GA search / list-strategies / tearsheet / bench / config /
preflight / label / factor / attribute / purge-cv / fracdiff / cscv /
search-multi / freeze / dashboard.
"""
from __future__ import annotations

from aurora.core.costs import IBKR_costs
from aurora.core.seed import set_global_seed

from ._shared import (
    _DEFAULT_ANALYTICAL_TIER,
    _TIER_CHOICES,
    _add_tier_arg,
    _arg_error,
    _costs_from,
    _dry_run_summary,
    _load_global_config,
    _policy_tier_choices,
    _resolve_strategy,
    _runtime_error,
    _strategy_library,
)


def _resolve_tier_load(asset, tier):
    """Resolve through ``forge._resolve_tier_load`` for monkeypatch parity.

    Tests in :mod:`tests.test_protocol_round3` patch
    ``aurora.cli.forge._resolve_tier_load``. Looking up the attribute on
    the ``forge`` module at call time preserves that contract after the
    R49 split (see test ``test_cli_run_default_tier_oos_dev``).
    """
    from . import forge as _forge_mod
    return _forge_mod._resolve_tier_load(asset, tier)


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

    cfg = _load_global_config(args)  # noqa: F841
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

    cfg = _load_global_config(args)  # noqa: F841
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

    cfg = _load_global_config(args)  # noqa: F841
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
    from aurora.core.engine import run_backtest  # noqa: F401  (parity import)
    from aurora.analytics.factor_analysis import factor_summary_table

    cfg = _load_global_config(args)  # noqa: F841
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

    cfg = _load_global_config(args)  # noqa: F841
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

    cfg = _load_global_config(args)  # noqa: F841
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
    import pandas as pd  # noqa: F401  (parity import)
    from aurora.ml.fracdiff import find_min_d, fracdiff_correlation

    cfg = _load_global_config(args)  # noqa: F841
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

    cfg = _load_global_config(args)  # noqa: F841
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

    cfg = _load_global_config(args)  # noqa: F841
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

    cfg = _load_global_config(args)  # noqa: F841
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
    import os  # noqa: F401  (parity import)
    cfg = _load_global_config(args)  # noqa: F841
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
    import sys

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
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the core analytical subcommands.

    Order (matches build_parser before split):
      run, validate, search, list-strategies, tearsheet, bench, config,
      preflight, label, factor, attribute, purge-cv, fracdiff, cscv,
      search-multi, freeze.
    """
    # run -------------------------------------------------------------------
    p_run = subparsers.add_parser(
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
    p_val = subparsers.add_parser(
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
    p_search = subparsers.add_parser(
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
    p_ls = subparsers.add_parser(
        "list-strategies", help="List available strategies and their specs",
        description="Print all registered strategies with default parameters and ranges.",
    )
    p_ls.set_defaults(func=cmd_list_strategies)

    # tearsheet -------------------------------------------------------------
    p_ts = subparsers.add_parser(
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
    p_bench = subparsers.add_parser(
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
    p_cfg = subparsers.add_parser(
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
    p_pf = subparsers.add_parser(
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
    p_lab = subparsers.add_parser(
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
    p_fac = subparsers.add_parser(
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
    p_attr = subparsers.add_parser(
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
    p_pcv = subparsers.add_parser(
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
    p_fd = subparsers.add_parser(
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
    p_cscv = subparsers.add_parser(
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
    p_smulti = subparsers.add_parser(
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
    p_freeze = subparsers.add_parser(
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


def register_dashboard(subparsers, parent_parser=None) -> None:
    """Register the ``dashboard`` subcommand (separate so it can be inserted
    between the ``export`` and ``research`` groups, matching the original
    ``build_parser`` order).
    """
    p_dash = subparsers.add_parser(
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
