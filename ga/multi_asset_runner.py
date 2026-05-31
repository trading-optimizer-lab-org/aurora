"""Multi-asset GA runner using DEAP NSGA-II + MultiAssetEngine.

Generic over any multi-asset strategy class that exposes:
- `spec()` -> StrategySpec (genome ranges)
- ctor accepts symbol args + scalar params (e.g. PairTrade(sym_a, sym_b, **params))
- `weights(price_dict)` -> dict[symbol -> np.ndarray]

PairTrade is the reference implementation. Other multi-asset strategies (basket
mean-rev, cointegrated triplets, etc.) plug in by matching this duck-typed shape.

Conventions inherited from single-asset runner:
- genome = list[float] in [0, 1], one gene per sorted spec param
- NSGA-II Pareto front returned as list of (params_dict, fitness_tuple)
- Fitness tuple ordering: (calmar, sharpe, robustness, mdd_penalty)
  weights = (1, 1, 1, -1)  ->  maximize first 3, minimize 4th
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
import random
import uuid
import numpy as np
import pandas as pd

from aurora.ga.runner import GAConfig
from aurora.core.engine_multi import MultiAssetEngine

try:
    from deap import base, creator, tools, algorithms
    HAS_DEAP = True
except ImportError:
    HAS_DEAP = False


@dataclass
class MultiAssetGAConfig(GAConfig):
    """Same as GAConfig plus multi-asset specific knobs.

    gross_leverage_cap, net_leverage_cap forwarded to MultiAssetEngine.
    ppy is forwarded to fitness/engine for periods-per-year scaling.
    """
    gross_leverage_cap: float = 1.0
    net_leverage_cap: float = 2.0
    ppy: int = 252


def _wf_robustness_multi(
    price_dict_is: dict,
    weights_fn: Callable[[dict], dict],
    costs_dict: Optional[dict],
    gross_leverage_cap: float,
    net_leverage_cap: float,
    ppy: int,
    n_windows: int = 4,
) -> float:
    """IS-only walk-forward robustness for multi-asset.

    Splits each symbol's IS series into n_windows contiguous chunks, runs the
    multi-asset engine on each chunk, returns -std of per-chunk Calmar so
    higher (closer to 0) = more stable. Never touches OOS.

    Per-chunk failures (engine raises, NaN/inf Calmar) are SKIPPED rather
    than poisoning the whole estimate with the -99 sentinel. Only when every
    chunk fails do we fall back to -99. Mirrors the single-asset
    ``_walk_forward_robustness`` semantics.
    """
    syms = sorted(price_dict_is.keys())
    if not syms:
        return 0.0
    n = min(len(price_dict_is[s]) for s in syms)
    if n < n_windows * 30:
        return 0.0
    chunk = n // n_windows
    calmars: list[float] = []
    for w in range(n_windows):
        lo = w * chunk
        hi = (w + 1) * chunk if w < n_windows - 1 else n
        sub = {s: price_dict_is[s].iloc[lo:hi] for s in syms}
        try:
            wmap = weights_fn(sub)
            sub_aligned = _align_price_dict(sub, wmap)
            engine = MultiAssetEngine(
                gross_leverage_cap=gross_leverage_cap,
                net_leverage_cap=net_leverage_cap,
            )
            res = engine.run(sub_aligned, wmap, costs_dict=costs_dict, ppy=ppy)
            cal = float(res.calmar)
        except Exception:
            continue
        if not np.isfinite(cal):
            continue
        calmars.append(cal)
    if not calmars:
        return -99.0
    return -float(np.std(calmars))


def multi_asset_fitness_is(
    price_dict_is: dict,
    weights_fn: Callable[[dict], dict],
    costs_dict: Optional[dict] = None,
    gross_leverage_cap: float = 1.0,
    net_leverage_cap: float = 2.0,
    ppy: int = 252,
    max_mdd: float = 0.20,
    wf_windows: int = 4,
    **kw,
) -> tuple:
    """IS-only multi-objective fitness for the multi-asset GA.

    Mirrors the single-asset OOS-sagrado pattern: fitness sees IS prices only.
    Validate Pareto front candidates against OOS via ``multi_asset_validate_oos``
    AFTER ``run_multi_asset_ga`` returns.

    Returns:
        (calmar_is, sharpe_is, robustness_wf, mdd_penalty_is). Sentinel
        (-99, -99, -99, 99) on failure.
    """
    try:
        w_is = weights_fn(price_dict_is)
    except Exception:
        return (-99.0, -99.0, -99.0, 99.0)

    try:
        engine = MultiAssetEngine(
            gross_leverage_cap=gross_leverage_cap,
            net_leverage_cap=net_leverage_cap,
        )
        price_is_aligned = _align_price_dict(price_dict_is, w_is)
        res_is = engine.run(price_is_aligned, w_is, costs_dict=costs_dict, ppy=ppy)
    except Exception:
        return (-99.0, -99.0, -99.0, 99.0)

    cal_is = float(res_is.calmar)
    sh_is = float(res_is.sharpe)
    robust = _wf_robustness_multi(
        price_dict_is, weights_fn, costs_dict,
        gross_leverage_cap, net_leverage_cap, ppy, n_windows=wf_windows,
    )
    mdd_raw = float(res_is.mdd)
    if not np.isfinite(mdd_raw):
        mdd_raw = 99.0
    mdd_pen = max(0.0, abs(mdd_raw / 100.0) - max_mdd)

    out = (cal_is, sh_is, robust, mdd_pen)
    if any(not np.isfinite(x) for x in out):
        return (-99.0, -99.0, -99.0, 99.0)
    return out


def multi_asset_validate_oos(
    price_dict_oos: dict,
    weights_fn: Callable[[dict], dict],
    costs_dict: Optional[dict] = None,
    gross_leverage_cap: float = 1.0,
    net_leverage_cap: float = 2.0,
    ppy: int = 252,
    **kw,
) -> dict:
    """Run candidate weights against OOS data. Used AFTER GA selection only.

    Mirrors aurora.ga.fitness.validate_oos for the multi-asset case.
    Returns a metrics dict; on failure returns NaN-filled dict + 'error' key.
    """
    try:
        w_oos = weights_fn(price_dict_oos)
        engine = MultiAssetEngine(
            gross_leverage_cap=gross_leverage_cap,
            net_leverage_cap=net_leverage_cap,
        )
        price_oos_aligned = _align_price_dict(price_dict_oos, w_oos)
        res = engine.run(price_oos_aligned, w_oos, costs_dict=costs_dict, ppy=ppy)
    except Exception as e:
        nan = float("nan")
        return {
            "calmar": nan, "sharpe": nan, "mdd": nan, "cagr": nan,
            "n_periods": 0, "error": repr(e),
        }
    return {
        "calmar": float(res.calmar),
        "sharpe": float(res.sharpe),
        "mdd": float(res.mdd),
        "cagr": float(res.cagr),
        "n_periods": int(res.metrics.n_periods),
    }


def multi_asset_fitness(
    price_dict_is: dict,
    price_dict_oos: dict,
    weights_fn: Callable[[dict], dict],
    costs_dict: Optional[dict] = None,
    gross_leverage_cap: float = 1.0,
    net_leverage_cap: float = 2.0,
    ppy: int = 252,
    max_mdd: float = 0.20,
    **kw,
) -> tuple:
    """DEPRECATED. OOS-leaking fitness; kept as a thin alias to multi_asset_fitness_is.

    The original implementation read OOS during selection (calmar_oos, sharpe_oos,
    mdd_oos), violating the OOS-sagrado rule used by the single-asset GA. This
    shim now drops ``price_dict_oos`` and delegates to the IS-only fitness so
    that the multi-asset GA cannot leak OOS into its selection signal.

    For OOS validation of selected candidates use ``multi_asset_validate_oos``.
    """
    import warnings
    warnings.warn(
        "multi_asset_fitness(price_dict_is, price_dict_oos, ...) is deprecated; "
        "use multi_asset_fitness_is(price_dict_is, ...). price_dict_oos is "
        "ignored to honor the OOS-sagrado contract.",
        DeprecationWarning,
        stacklevel=2,
    )
    return multi_asset_fitness_is(
        price_dict_is, weights_fn,
        costs_dict=costs_dict,
        gross_leverage_cap=gross_leverage_cap,
        net_leverage_cap=net_leverage_cap,
        ppy=ppy,
        max_mdd=max_mdd,
        **kw,
    )


def _align_price_dict(price_dict: dict, weight_dict: dict) -> dict:
    """Build per-symbol price series matching the weight array length.

    weights() may return arrays on the intersection index; we reindex prices
    to that same intersection so MultiAssetEngine alignment passes.
    """
    # Compute common index of all input price series
    common = None
    for s in sorted(price_dict.keys()):
        idx = price_dict[s].index
        common = idx if common is None else common.intersection(idx)
    if common is None or len(common) == 0:
        raise ValueError("empty common index between price series")

    out = {}
    for s in sorted(price_dict.keys()):
        w = np.asarray(weight_dict[s])
        if len(w) == len(price_dict[s]):
            out[s] = price_dict[s]
        elif len(w) == len(common):
            out[s] = price_dict[s].reindex(common)
        else:
            raise ValueError(
                f"weight length {len(w)} for {s} matches neither original "
                f"({len(price_dict[s])}) nor common ({len(common)})"
            )
    return out


def _decode_genome(genome, param_keys, spec):
    """Decode flat float genome -> param dict using StrategySpec ranges.

    Bool guard: ``isinstance(True, int)`` is True in Python, so a naive
    ``isinstance(lo, int) and isinstance(hi, int)`` check rounds bool ranges
    to ints and feeds the wrong type to the strategy ctor. Exclude bools
    explicitly so categorical bools live as Categorical lists rather than
    being coerced into a 2-element int range. Mirrors
    ``runner._make_evaluate.decode``.
    """
    params = {}
    for k, g in zip(param_keys, genome):
        r = spec.param_ranges[k]
        if isinstance(r, list):
            idx = int(np.clip(g * len(r), 0, len(r) - 1))
            params[k] = r[idx]
        else:
            lo, hi = r
            v = lo + (hi - lo) * g
            if (isinstance(lo, int) and isinstance(hi, int)
                    and not isinstance(lo, bool) and not isinstance(hi, bool)):
                v = int(round(v))
            params[k] = v
    return params


def _detect_ma_fitness_signature(fitness_fn) -> str:
    """Return 'is_only' if fitness_fn(price_dict_is, weights_fn, ...), else 'legacy'.

    Heuristic: count required positional parameters. The IS-only fitness has
    2 positional (price_dict_is, weights_fn); the legacy version has 3
    (price_dict_is, price_dict_oos, weights_fn).
    """
    import inspect
    try:
        sig = inspect.signature(fitness_fn)
    except (TypeError, ValueError):
        return "is_only"
    positional = [
        p for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                      inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.default is inspect.Parameter.empty
    ]
    return "legacy" if len(positional) >= 3 else "is_only"


def _make_evaluate(strategy_class, symbols, price_dict_is, price_dict_oos,
                   fitness_fn, costs_dict, param_keys, spec,
                   gross_cap, net_cap, ppy, fitness_signature: str = "is_only"):
    """Build evaluate closure for DEAP toolbox.

    Strategy ctor signature assumed: positional symbols, then **params.
    For PairTrade: PairTrade(sym_a, sym_b, lookback, entry_z, exit_z, hedge_ratio).

    fitness_signature:
        - 'is_only': fitness_fn(price_dict_is, weights_fn, ...). The GA never
          sees OOS. Preferred and matches OOS-sagrado.
        - 'legacy':  fitness_fn(price_dict_is, price_dict_oos, weights_fn, ...).
          The deprecated alias drops the OOS dict at call time, so this stays
          OOS-clean.
    """
    def evaluate(genome):
        params = _decode_genome(genome, param_keys, spec)
        try:
            strat = strategy_class(*symbols, **params)
            if fitness_signature == "legacy":
                # Deprecated 3-arg shape: pass None for OOS. The deprecated
                # multi_asset_fitness drops it before calling the IS path.
                return fitness_fn(
                    price_dict_is, None, strat.weights,
                    costs_dict=costs_dict,
                    gross_leverage_cap=gross_cap,
                    net_leverage_cap=net_cap,
                    ppy=ppy,
                )
            return fitness_fn(
                price_dict_is, strat.weights,
                costs_dict=costs_dict,
                gross_leverage_cap=gross_cap,
                net_leverage_cap=net_cap,
                ppy=ppy,
            )
        except Exception:
            return (-99.0, -99.0, -99.0, 99.0)
    return evaluate


def run_multi_asset_ga(
    strategy_class,
    price_dict_is: dict,
    price_dict_oos: Optional[dict] = None,
    symbols: Optional[list] = None,
    fitness_fn: Optional[Callable] = None,
    config: Optional[MultiAssetGAConfig] = None,
    costs_dict: Optional[dict] = None,
    verbose: bool = True,
    seeded_pop: list | None = None,
) -> list:
    """Run NSGA-II GA over a multi-asset strategy.

    Args:
        strategy_class: e.g. PairTrade. Must expose .spec() and accept
                        ctor signature `(*symbols, **params)`.
        price_dict_is: {symbol -> pd.Series} IS prices
        price_dict_oos: deprecated; only used by the legacy 3-arg
                        ``multi_asset_fitness`` shim. P3.4 round-4 audit:
                        when ``fitness_signature == 'is_only'`` (the
                        recommended path) this argument is dropped on
                        the floor with a DeprecationWarning. Pass
                        ``None`` for new code.
        symbols: ordered list of symbols passed positionally to strategy ctor
        fitness_fn: callable(price_dict_is, price_dict_oos, weights_fn, **kw) -> tuple
                    Defaults to multi_asset_fitness.
        config: MultiAssetGAConfig (defaults to construction defaults)
        costs_dict: optional {symbol -> CostModel} per asset

    Returns:
        Pareto front: list of (params_dict, fitness_tuple).
    """
    if not HAS_DEAP:
        raise ImportError("deap required: pip install deap")

    config = config or MultiAssetGAConfig()
    fitness_fn = fitness_fn or multi_asset_fitness_is

    from aurora.ga.runner import VALID_BACKENDS
    if config.backend not in VALID_BACKENDS:
        raise ValueError(
            f"invalid backend {config.backend!r}; expected one of {VALID_BACKENDS}"
        )
    if not symbols or len(symbols) < 2:
        raise ValueError(f"symbols must have >= 2 entries, got {symbols!r}")
    if set(price_dict_is.keys()) != set(symbols):
        raise ValueError(
            f"price_dict_is keys {set(price_dict_is.keys())} != symbols {set(symbols)}"
        )

    # P2.4 / P3.4 round-4 audit: detect signature first, only require
    # price_dict_oos for the deprecated 3-arg legacy fitness.
    fitness_signature = _detect_ma_fitness_signature(fitness_fn)
    if fitness_signature == "is_only":
        if price_dict_oos is not None:
            import warnings
            warnings.warn(
                "run_multi_asset_ga: price_dict_oos is deprecated for "
                "is_only fitness signatures and will be ignored. "
                "Drop the OOS dict and run multi_asset_validate_oos "
                "AFTER GA selection.",
                DeprecationWarning,
                stacklevel=2,
            )
            price_dict_oos = None
    else:
        # legacy path: still requires the OOS dict to validate keys.
        if price_dict_oos is None:
            raise ValueError(
                "run_multi_asset_ga: legacy fitness signature requires "
                "price_dict_oos (use the IS-only fitness instead)."
            )
        if set(price_dict_oos.keys()) != set(symbols):
            raise ValueError(
                f"price_dict_oos keys {set(price_dict_oos.keys())} != "
                f"symbols {set(symbols)}"
            )

    random.seed(config.seed)
    np.random.seed(config.seed)

    spec = strategy_class.spec()
    param_keys = sorted(spec.param_ranges.keys())
    n_genes = len(param_keys)
    if n_genes == 0:
        raise ValueError(f"{strategy_class.__name__}.spec() has no param_ranges")

    # NSGA-II creator (4 objectives: cal, sharpe, robust=maximize; mdd_pen=minimize)
    # Use per-call unique class names to avoid stale-global collisions between
    # consecutive run_multi_asset_ga calls with different strategies.
    # ``id() % 1000`` collides ~once every 32 strategies (birthday bound) so
    # use a uuid4 hex prefix instead. The full class qualname is included for
    # debuggability in stack traces / DEAP introspection.
    _suffix = uuid.uuid4().hex[:8]
    fit_name = f"FitnessMultiMA_{strategy_class.__name__}_{_suffix}"
    ind_name = f"IndividualMA_{strategy_class.__name__}_{_suffix}"
    if hasattr(creator, fit_name):
        delattr(creator, fit_name)
    if hasattr(creator, ind_name):
        delattr(creator, ind_name)
    creator.create(fit_name, base.Fitness, weights=(1.0, 1.0, 1.0, -1.0))
    creator.create(ind_name, list, fitness=getattr(creator, fit_name))
    individual_cls = getattr(creator, ind_name)

    toolbox = base.Toolbox()
    toolbox.register("attr_float", random.random)
    toolbox.register("individual", tools.initRepeat, individual_cls,
                     toolbox.attr_float, n_genes)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)

    # fitness_signature already detected above so price_dict_oos
    # validation could short-circuit for is_only. Reuse it here.
    evaluate = _make_evaluate(
        strategy_class, symbols, price_dict_is, price_dict_oos,
        fitness_fn, costs_dict, param_keys, spec,
        config.gross_leverage_cap, config.net_leverage_cap, ppy=config.ppy,
        fitness_signature=fitness_signature,
    )

    toolbox.register("evaluate", evaluate)

    # Custom mate operator: wrap cxBlend with post-hoc clip to [0, 1] gene
    # bounds so blend-with-alpha cannot push genes outside the unit cube.
    # Mirrors runner.py:_mate_blend_clip semantics.
    _BLEND_ALPHA = 0.5

    def _mate_blend_clip(ind1, ind2):
        tools.cxBlend(ind1, ind2, alpha=_BLEND_ALPHA)
        for ind in (ind1, ind2):
            for i in range(len(ind)):
                ind[i] = float(np.clip(ind[i], 0.0, 1.0))
        return ind1, ind2

    toolbox.register("mate", _mate_blend_clip)
    toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=0.1, indpb=0.2)
    toolbox.register("select", tools.selNSGA2)

    # Backend: parallel map for evaluation. Mirrors runner.py:208-237.
    from contextlib import nullcontext
    if config.backend == "joblib" and config.n_workers > 1:
        try:
            from joblib import Parallel, delayed
        except ImportError as e:
            raise ImportError("joblib required for backend='joblib'") from e

        # Reuse one Parallel context for the whole run to avoid spawn overhead.
        # Wrap in `with` so worker processes are reliably cleaned up even if an
        # exception propagates out of the GA loop.
        pool_cm = Parallel(n_jobs=config.n_workers, backend="loky")
        if verbose:
            print(f"MA-GA: backend=joblib n_workers={config.n_workers}")
    else:
        pool_cm = nullcontext(None)
        if verbose and config.backend == "joblib":
            print("MA-GA: backend=joblib but n_workers<=1, falling back to serial map")

    try:
        with pool_cm as parallel_pool:
            if parallel_pool is not None:
                from joblib import delayed

                def parallel_map(fn, items):
                    return parallel_pool(delayed(fn)(x) for x in items)

                toolbox.register("map", parallel_map)
            else:
                toolbox.register("map", map)

            if seeded_pop is not None:
                seeds = [list(g) for g in seeded_pop[:config.population]]
                # Validate genome length and clip into [0, 1] before evaluation.
                for g in seeds:
                    if len(g) != n_genes:
                        raise ValueError(
                            f"seeded_pop genome has {len(g)} genes, expected {n_genes}"
                        )
                    for i in range(len(g)):
                        g[i] = float(np.clip(g[i], 0.0, 1.0))
                pop = [individual_cls(g) for g in seeds]
                if len(pop) < config.population:
                    pop.extend(toolbox.population(n=config.population - len(pop)))
                if verbose:
                    print(f"MA-GA: seeded {len(seeds)}/{config.population} initial individuals")
            else:
                pop = toolbox.population(n=config.population)
            fitnesses = list(toolbox.map(toolbox.evaluate, pop))
            for ind, fit in zip(pop, fitnesses):
                ind.fitness.values = fit

            if verbose:
                print(f"MA-GA: pop={config.population} gen={config.generations} "
                      f"strategy={strategy_class.__name__} symbols={symbols}")

            # varOr requires lambda_ <= len(pop). Cap at len(pop) to avoid
            # IndexError on tiny populations / edge configs. Mirrors runner.py:267.
            lambda_eff = min(config.population, len(pop))

            for gen in range(config.generations):
                offspring = algorithms.varOr(
                    pop, toolbox, lambda_=lambda_eff,
                    cxpb=config.crossover_prob, mutpb=config.mutation_prob,
                )
                for ind in offspring:
                    for i in range(len(ind)):
                        ind[i] = float(np.clip(ind[i], 0.0, 1.0))
                invalid = [ind for ind in offspring if not ind.fitness.valid]
                if invalid:
                    fits = list(toolbox.map(toolbox.evaluate, invalid))
                    for ind, fit in zip(invalid, fits):
                        ind.fitness.values = fit
                pop = toolbox.select(pop + offspring, config.population)

                if verbose and gen % 5 == 0:
                    best = tools.selBest(pop, 1)[0]
                    print(f"  gen {gen}: best fitness = {best.fitness.values}")

            pareto = tools.sortNondominated(pop, len(pop), first_front_only=True)[0]
            # Deterministic tie-breaking matches single-asset runner.run_ga so the
            # multi-asset Pareto ordering is reproducible across runs with the same
            # seed. Without this, ties between non-dominated individuals are broken
            # by Python's stable sort on the unsorted DEAP front, which depends on
            # object id() and varies per run.
            def _tie_key(ind):
                fit = tuple(ind.fitness.values)
                # Maximize first 3 -> negate so smaller is better; mdd_pen (4th) is
                # minimized so keep as-is.
                primary = (-fit[0], -fit[1], -fit[2], fit[3]) if len(fit) >= 4 else tuple(-x for x in fit)
                secondary = tuple(float(g) for g in ind)
                return primary + secondary

            pareto = sorted(pareto, key=_tie_key)
            return [(_decode_genome(ind, param_keys, spec), tuple(ind.fitness.values))
                    for ind in pareto]
    finally:
        # Clean up per-call DEAP creator classes so re-runs with the same uuid
        # (negligible probability) don't trip the hasattr guard above.
        if hasattr(creator, fit_name):
            delattr(creator, fit_name)
        if hasattr(creator, ind_name):
            delattr(creator, ind_name)
