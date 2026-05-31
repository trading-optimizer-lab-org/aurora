"""GA runner using DEAP (multi-objective NSGA-II by default)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import random
import uuid
import numpy as np

try:
    from deap import base, creator, tools, algorithms
    HAS_DEAP = True
except ImportError:
    HAS_DEAP = False


VALID_BACKENDS = ("sequential", "joblib")


def _ga_defaults_from_policy() -> dict:
    """Pull GA defaults from the active :class:`ProtocolPolicy`.

    Falls back to the historical literal defaults when the policy fails
    to load (e.g. extreme-edge import failures during tooling) so the
    GA itself never refuses to construct.
    """
    try:
        from aurora.core.protocol_policy import get_active_policy
        ga = get_active_policy().ga_config
        return {
            "population": int(ga.population),
            "generations": int(ga.generations),
            "crossover_prob": float(ga.crossover_prob),
            "mutation_prob": float(ga.mutation_prob),
            "tournament_size": int(ga.tournament_size),
            "n_workers": int(ga.n_workers),
            "seed": int(ga.seed),
            "backend": str(ga.backend),
        }
    except Exception:
        return {
            "population": 200, "generations": 50, "crossover_prob": 0.7,
            "mutation_prob": 0.2, "tournament_size": 3, "n_workers": 1,
            "seed": 42, "backend": "sequential",
        }


_GA_DEFAULTS = _ga_defaults_from_policy()


@dataclass
class GAConfig:
    # P0.A: defaults seeded from the active ``ProtocolPolicy``.
    population: int = field(default_factory=lambda: _GA_DEFAULTS["population"])
    generations: int = field(default_factory=lambda: _GA_DEFAULTS["generations"])
    crossover_prob: float = field(
        default_factory=lambda: _GA_DEFAULTS["crossover_prob"]
    )
    mutation_prob: float = field(
        default_factory=lambda: _GA_DEFAULTS["mutation_prob"]
    )
    tournament_size: int = field(
        default_factory=lambda: _GA_DEFAULTS["tournament_size"]
    )
    n_workers: int = field(default_factory=lambda: _GA_DEFAULTS["n_workers"])
    seed: int = field(default_factory=lambda: _GA_DEFAULTS["seed"])
    backend: str = field(default_factory=lambda: _GA_DEFAULTS["backend"])


def _make_evaluate(strategy_class, prices_is, fitness_fn, param_keys, spec,
                   fitness_signature: str = "is_only"):
    """Build a top-level evaluate function so joblib (loky) can pickle it.

    Returns (decode, evaluate) closures. The closures capture only picklable
    objects: strategy_class (importable), prices_is (pd.Series), fitness_fn
    (importable callable), param_keys (list of strings), spec (StrategySpec).

    Args:
        fitness_signature: "is_only" -> fitness_fn(prices_is, signal_fn).
                           "legacy"  -> fitness_fn(prices_is, None, signal_fn);
                           used to keep deprecated 3-arg fitness functions working
                           without leaking OOS into the GA.
    """
    def decode(genome):
        params = {}
        for k, g in zip(param_keys, genome):
            r = spec.param_ranges[k]
            if isinstance(r, list):
                idx = int(np.clip(g * len(r), 0, len(r) - 1))
                params[k] = r[idx]
            else:
                lo, hi = r
                v = lo + (hi - lo) * g
                # Bool guard: ``isinstance(True, int)`` is True. A 2-tuple of
                # bools must NOT be int-rounded; it should already arrive as
                # a Categorical list per StrategySpec convention, but if a
                # caller passes (False, True) we leave it as a float in [0,1]
                # rather than mis-coerce.
                if (isinstance(lo, int) and isinstance(hi, int)
                        and not isinstance(lo, bool) and not isinstance(hi, bool)):
                    v = int(round(v))
                params[k] = v
        return params

    def evaluate(genome):
        params = decode(genome)
        try:
            strat = strategy_class(**params)
            if fitness_signature == "legacy":
                # Legacy 3-arg fitness: pass None for OOS. The deprecated
                # implementation in fitness.py ignores prices_oos.
                return fitness_fn(prices_is, None, strat.signals)
            return fitness_fn(prices_is, strat.signals)
        except Exception:
            return (-99.0, -99.0, -99.0, 99.0)

    return decode, evaluate


def _detect_fitness_signature(fitness_fn) -> str:
    """Return 'is_only' if fitness_fn takes (prices, signal_fn, ...), else 'legacy'.

    Heuristic: count required positional parameters. The new IS-only fitness
    has 2 positional (prices_is, signal_fn). The legacy version has 3
    (prices_is, prices_oos, signal_fn).
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


def run_ga(strategy_class, prices_is, prices_oos=None, fitness_fn=None,
           config: GAConfig | None = None, verbose: bool = True,
           seeded_pop: list | None = None):
    """Run NSGA-II GA over strategy parameter space.

    NOTE: ``prices_oos`` is accepted for backwards compatibility but is NEVER
    passed to the fitness function. The GA must not see OOS data. To validate
    Pareto front candidates against OOS, call ``aurora.ga.fitness.validate_oos``
    AFTER ``run_ga`` returns, ideally inside an ``OOSGuard`` context.

    Args:
        strategy_class: subclass of Strategy with .spec() defining param ranges
        prices_is: pd.Series of in-sample prices.
        prices_oos: deprecated. Kept so the legacy 3-arg call site keeps working.
            Always ignored by the GA loop.
        fitness_fn: callable. Two supported shapes:
            - new (preferred): ``fn(prices_is, signal_fn) -> tuple``
            - deprecated:      ``fn(prices_is, prices_oos, signal_fn) -> tuple``
              In the deprecated shape, ``None`` is passed for prices_oos and
              the deprecated implementation in fitness.py drops it.
        config: GAConfig
        seeded_pop: optional list of genomes (each a list[float] in [0, 1]) to
            use as the initial population. If shorter than ``config.population``,
            the rest is filled with random genomes. If longer, it is truncated.

    Returns:
        list of (params, fitness) for top individuals (Pareto front)
    """
    if fitness_fn is None:
        raise TypeError("run_ga requires a fitness_fn argument")
    if not HAS_DEAP:
        raise ImportError("deap required: pip install deap")
    # Skip wrapper strategies that cannot be ctor'd from spec params alone.
    if getattr(strategy_class, "is_wrapper", False):
        raise TypeError(
            f"{strategy_class.__name__} is marked is_wrapper=True; it requires "
            "a `base` Strategy in its ctor that is not in spec().param_ranges. "
            "Build a wrapper_factory closing over a concrete base and pass that."
        )

    config = config or GAConfig()
    if config.backend not in VALID_BACKENDS:
        raise ValueError(
            f"invalid backend {config.backend!r}; expected one of {VALID_BACKENDS}"
        )

    random.seed(config.seed)
    np.random.seed(config.seed)

    spec = strategy_class.spec()
    param_keys = sorted(spec.param_ranges.keys())

    # define genome: list of floats in [0, 1], one per param
    n_genes = len(param_keys)

    # NSGA-II setup with PER-CALL unique class names so consecutive run_ga
    # invocations on different strategy classes don't collide on a stale
    # global creator.FitnessMulti definition (DEAP stores creator.* on the
    # `creator` module). ``id() % 1000`` is collision-prone (birthday bound:
    # ~5% chance of collision over 8 strategies in a single process), so use
    # a uuid4 hex prefix. We also clean up via ``hasattr/delattr`` below in
    # case the same uuid happens to recur, which is statistically negligible
    # but cheap to defend against.
    _suffix = uuid.uuid4().hex[:8]
    fit_name = f"FitnessMulti_{strategy_class.__name__}_{_suffix}"
    ind_name = f"Individual_{strategy_class.__name__}_{_suffix}"
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

    fitness_signature = _detect_fitness_signature(fitness_fn)
    decode, evaluate = _make_evaluate(
        strategy_class, prices_is, fitness_fn, param_keys, spec,
        fitness_signature=fitness_signature,
    )

    toolbox.register("evaluate", evaluate)

    # Custom mate operator: wrap cxBlend + post-hoc clip to gene bounds.
    # cxBlend with alpha can produce genes outside [0, 1]; clip every gene to
    # its declared bound. Bounds are read from StrategySpec via the genome
    # convention: every gene is a float in [0, 1] (decode maps to native
    # param ranges). So the bound is uniformly [0.0, 1.0] for all genes.
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

    # Backend: parallel map for evaluation
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
            print(f"GA: backend=joblib n_workers={config.n_workers}")
    else:
        pool_cm = nullcontext(None)
        if verbose and config.backend == "joblib":
            print("GA: backend=joblib but n_workers<=1, falling back to serial map")

    with pool_cm as parallel_pool:
        if parallel_pool is not None:
            from joblib import delayed

            def parallel_map(fn, items):
                return parallel_pool(delayed(fn)(x) for x in items)

            toolbox.register("map", parallel_map)
        else:
            toolbox.register("map", map)

        try:
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
                    print(f"GA: seeded {len(seeds)}/{config.population} initial individuals")
            else:
                pop = toolbox.population(n=config.population)
            fitnesses = list(toolbox.map(toolbox.evaluate, pop))
            for ind, fit in zip(pop, fitnesses):
                ind.fitness.values = fit

            if verbose:
                print(f"GA: pop={config.population} gen={config.generations}")

            # varOr requires lambda_ <= len(pop). When config.population is small but
            # would otherwise default to itself, this is a no-op. Cap at len(pop) to
            # avoid IndexError on tiny populations / edge configs (e.g. pop=10 with
            # someone overriding lambda_).
            lambda_eff = min(config.population, len(pop))

            for gen in range(config.generations):
                offspring = algorithms.varOr(pop, toolbox, lambda_=lambda_eff,
                                             cxpb=config.crossover_prob,
                                             mutpb=config.mutation_prob)
                # Safety net: clip genes to [0, 1] post-varOr. The custom mate operator
                # already clips after crossover; mutGaussian can still push genes out.
                # Invalidate the cached fitness for any individual whose genome was
                # actually changed by clipping so the re-evaluation pass below does
                # not skip it just because varOr happened to leave the fitness valid.
                for ind in offspring:
                    changed = False
                    for i in range(len(ind)):
                        new_val = float(np.clip(ind[i], 0.0, 1.0))
                        if new_val != ind[i]:
                            ind[i] = new_val
                            changed = True
                    if changed and ind.fitness.valid:
                        del ind.fitness.values
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
            # Deterministic tie-breaking: NSGA-II Pareto rank + crowding distance can
            # leave ties. Sort by (negated fitness tuple, genome bytes) so equivalent
            # individuals always come out in the same order across runs with the same
            # seed. Genome bytes act as a stable secondary key independent of object
            # id (which varies between runs).
            def _tie_key(ind):
                fit = tuple(ind.fitness.values)
                # Maximize first 3 → negate so smaller is better (sortable ascending).
                # The 4th objective (mdd_pen) is minimized; keep as-is.
                primary = (-fit[0], -fit[1], -fit[2], fit[3]) if len(fit) >= 4 else tuple(-x for x in fit)
                # Genome bytes as deterministic secondary key.
                secondary = tuple(float(g) for g in ind)
                return primary + secondary

            pareto = sorted(pareto, key=_tie_key)
            return [(decode(ind), ind.fitness.values) for ind in pareto]
        finally:
            # Clean up per-call DEAP creator classes so a uuid collision (negligible
            # probability) cannot trip the hasattr guard above on a re-run.
            if hasattr(creator, fit_name):
                delattr(creator, fit_name)
            if hasattr(creator, ind_name):
                delattr(creator, ind_name)
