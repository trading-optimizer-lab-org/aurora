"""Bayesian Optimization alternative to GA.

Wraps scikit-optimize gp_minimize over StrategySpec.param_ranges.
Falls back to a minimal sklearn+scipy GP-EI implementation if skopt is missing.

OOS-sagrado: Like ``run_ga``, ``bayes_optimize`` must NEVER pass OOS data to
the fitness function. The legacy 3-arg signature ``fn(prices_is, prices_oos,
signal_fn)`` is detected and ``None`` is forwarded for ``prices_oos`` so the
deprecated implementation in ``fitness.py`` can no longer leak OOS into the
selection signal.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Any
import inspect
import random
import numpy as np

try:
    from skopt import gp_minimize, dummy_minimize
    from skopt.space import Real, Integer, Categorical
    HAS_SKOPT = True
except ImportError:
    HAS_SKOPT = False

try:
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import (
        Matern, ConstantKernel, Kernel, Hyperparameter,
    )
    from scipy.stats import norm
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


_SKOPT_INSTALL_MSG = (
    "scikit-optimize required for full BO. Install with: "
    "pip install scikit-optimize  (or pass --with scikit-optimize to uv run)"
)


@dataclass
class BayesConfig:
    n_calls: int = 50
    n_random_starts: int = 10
    seed: int = 42
    acquisition: str = "EI"  # EI | PI | LCB


def _build_skopt_space(param_ranges: dict[str, Any]):
    """Build a list of skopt Dimension objects + parallel list of param keys.

    Sorted by key for determinism.

    Type-mismatch handling: when a (lo, hi) tuple mixes int + float (e.g.
    (0, 0.5)), we treat it as Real and warn — silent int truncation would
    produce a coarse {0, 1, ...} grid that does not match user intent.
    """
    import warnings
    keys = sorted(param_ranges.keys())
    dims = []
    for k in keys:
        r = param_ranges[k]
        if isinstance(r, list):
            dims.append(Categorical(r, name=k))
        elif isinstance(r, tuple) and len(r) == 2:
            lo, hi = r
            if isinstance(lo, bool) or isinstance(hi, bool):
                # bools as categorical
                dims.append(Categorical([lo, hi], name=k))
            elif isinstance(lo, int) and isinstance(hi, int):
                dims.append(Integer(lo, hi, name=k))
            elif isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                # Mixed int/float (e.g. (0, 0.5)) -> warn and treat as Real.
                if (isinstance(lo, int) and not isinstance(lo, bool)
                        and isinstance(hi, float)) or (
                        isinstance(lo, float) and isinstance(hi, int)
                        and not isinstance(hi, bool)):
                    warnings.warn(
                        f"param_range '{k}' mixes int and float bounds "
                        f"({type(lo).__name__}, {type(hi).__name__}); "
                        f"treating as Real to preserve precision.",
                        stacklevel=3,
                    )
                dims.append(Real(float(lo), float(hi), name=k))
            else:
                raise ValueError(f"unsupported range types for '{k}': {type(lo)}, {type(hi)}")
        else:
            raise ValueError(f"unsupported param_range for '{k}': {r!r}")
    return keys, dims


def _decode_skopt(values, keys, param_ranges):
    """Map skopt sampled values back to a dict of native python types.

    Tuple ranges are coerced to:
      - int  when both bounds are int (and neither is bool); the dim is Integer.
      - float when both bounds are float; the dim is Real.
      - float for mixed int+float bounds, matching ``_build_skopt_space`` which
        promotes those to ``Real`` to preserve precision. The previous version
        fell through to the catch-all ``else`` branch and returned the raw
        skopt sample (typically a float), which is fine numerically but is
        type-inconsistent with the Real dim. Make the coercion explicit so the
        decoded params always match the dim's value space.
    """
    params = {}
    for k, v in zip(keys, values):
        r = param_ranges[k]
        if isinstance(r, tuple) and len(r) == 2:
            lo, hi = r
            lo_is_bool = isinstance(lo, bool)
            hi_is_bool = isinstance(hi, bool)
            if (isinstance(lo, int) and isinstance(hi, int)
                    and not lo_is_bool and not hi_is_bool):
                params[k] = int(v)
            elif (isinstance(lo, (int, float)) and isinstance(hi, (int, float))
                    and not lo_is_bool and not hi_is_bool):
                # Pure float range OR mixed int+float (treated as Real
                # in _build_skopt_space). Coerce explicitly.
                params[k] = float(v)
            else:
                params[k] = v
        else:
            params[k] = v
    return params


def _scalarize(fitness_tuple, weights=(0.5, 0.3, 0.2, 0.5),
               normalize: bool = False) -> float:
    """Weighted-sum scalarization for multi-objective tuple.

    Convention from quantforge.ga.fitness.multi_objective_fitness_is:
        (calmar, sharpe, robust, mdd_penalty)
    Maximize first 3, minimize 4th. Returns score where higher = better.

    Args:
        fitness_tuple: 1-, 3-, or 4-element fitness tuple.
        weights: ``(w_calmar, w_sharpe, w_robust, w_mdd)``. The mdd weight is
            applied as ``-w_mdd * mdd_pen`` so passing ``w_mdd=0.5`` matches
            the order of magnitude of the other three weighted terms. Older
            3-tuple form is accepted for backwards compat (mdd weight defaults
            to 0.5).
        normalize: if True, divide each objective by its typical scale
            (``ga.fitness._TYPICAL_SCALES``) before weighting so all four
            terms live on roughly comparable magnitudes. Useful when fitness
            tuples come from ``multi_objective_fitness_is(..., normalize=False)``
            and would otherwise be dominated by Calmar/Sharpe.
    """
    # Backwards-compat: accept 3-element weights and assume w_mdd=0.5.
    if len(weights) == 3:
        w_cal, w_sh, w_rob = weights
        w_mdd = 0.5
    else:
        w_cal, w_sh, w_rob, w_mdd = weights[0], weights[1], weights[2], weights[3]

    if normalize:
        # Lazy import to avoid cycle at module load.
        from quantforge.ga.fitness import _TYPICAL_SCALES as _S
        scales = (_S["calmar"], _S["sharpe"], _S["robust"], _S["mdd_pen"])
    else:
        scales = (1.0, 1.0, 1.0, 1.0)

    if len(fitness_tuple) >= 4:
        cal = fitness_tuple[0] / scales[0]
        sh = fitness_tuple[1] / scales[1]
        rob = fitness_tuple[2] / scales[2]
        mdd_pen = fitness_tuple[3] / scales[3]
        return w_cal * cal + w_sh * sh + w_rob * rob - w_mdd * mdd_pen
    if len(fitness_tuple) == 3:
        return (w_cal * fitness_tuple[0] / scales[0]
                + w_sh * fitness_tuple[1] / scales[1]
                + w_rob * fitness_tuple[2] / scales[2])
    return float(fitness_tuple[0])


def _detect_bayes_fitness_signature(fitness_fn) -> str:
    """Return 'is_only' if fitness_fn takes (prices, signal_fn, ...), else 'legacy'.

    Mirrors quantforge.ga.runner._detect_fitness_signature for the BO codepath
    so the fallback for the deprecated ``(prices_is, prices_oos, signal_fn)``
    shape passes ``None`` for prices_oos rather than leaking the OOS series.
    """
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


def bayes_optimize(strategy_class, prices_is, prices_oos=None,
                   fitness_fn=None, config: BayesConfig = None,
                   scalar: bool = True) -> dict:
    """Bayesian optimization over StrategySpec param space.

    Args:
        strategy_class: subclass of Strategy with .spec()
        prices_is: pd.Series of in-sample prices.
        prices_oos: deprecated. Accepted for backwards compatibility with the
            old 3-arg ``fitness_fn(prices_is, prices_oos, signal_fn)`` shape
            but is NEVER passed to the fitness function. Like ``run_ga``, the
            BO loop forwards ``None`` for the oos slot so the deprecated
            implementation in ``ga.fitness`` cannot see OOS during selection.
            For OOS validation of selected candidates use
            ``quantforge.ga.fitness.validate_oos`` AFTER ``bayes_optimize``
            returns, ideally inside an ``OOSGuard`` context.
        fitness_fn: callable. Two supported shapes:
            - new (preferred): ``fn(prices_is, signal_fn) -> tuple|float``
            - deprecated:      ``fn(prices_is, prices_oos, signal_fn) -> tuple|float``
              ``None`` is passed for ``prices_oos`` and the deprecated
              implementations in ``fitness.py`` drop it.
        config: BayesConfig
        scalar: if True, fitness_fn returns scalar; if False, multi-obj (use scalarized)

    Returns:
        dict with 'best_params', 'best_score', 'all_trials', 'convergence'
    """
    if fitness_fn is None:
        raise TypeError("bayes_optimize requires a fitness_fn argument")
    if not HAS_SKOPT and not HAS_SKLEARN:
        raise ImportError(_SKOPT_INSTALL_MSG)
    # Skip wrapper strategies that cannot be ctor'd from spec params alone.
    # Mirrors run_ga:128-133 so BO and GA agree on which strategies are
    # directly tunable.
    if getattr(strategy_class, "is_wrapper", False):
        raise TypeError(
            f"{strategy_class.__name__} is marked is_wrapper=True; it requires "
            "a `base` Strategy in its ctor that is not in spec().param_ranges. "
            "Build a wrapper_factory closing over a concrete base and pass that."
        )

    config = config or BayesConfig()
    random.seed(config.seed)
    np.random.seed(config.seed)

    spec = strategy_class.spec()
    if not spec.param_ranges:
        raise ValueError(f"{strategy_class.__name__}.spec().param_ranges is empty; nothing to optimize")

    keys, dims = _build_skopt_space(spec.param_ranges) if HAS_SKOPT else _build_fallback_space(spec.param_ranges)

    fitness_signature = _detect_bayes_fitness_signature(fitness_fn)

    all_trials: list[dict] = []
    convergence: list[float] = []
    best_so_far = float("-inf")

    def _eval(values) -> float:
        nonlocal best_so_far
        params = _decode_skopt(values, keys, spec.param_ranges)
        try:
            strat = strategy_class(**params)
            if fitness_signature == "legacy":
                # OOS-sagrado: never pass prices_oos. The deprecated 3-arg
                # fitness implementations in ga.fitness ignore prices_oos.
                out = fitness_fn(prices_is, None, strat.signals)
            else:
                out = fitness_fn(prices_is, strat.signals)
        except Exception:
            score = -99.0
            all_trials.append({"params": params, "score": score, "raw": None, "error": True})
            if score > best_so_far:
                best_so_far = score
            convergence.append(best_so_far)
            return -score

        if scalar and isinstance(out, (int, float, np.floating)):
            score = float(out)
            raw = float(out)
        elif scalar and isinstance(out, tuple):
            # caller said scalar but returned tuple → take first elem
            score = float(out[0])
            raw = out
        else:
            score = _scalarize(out)
            raw = out

        all_trials.append({"params": params, "score": score, "raw": raw, "error": False})
        if score > best_so_far:
            best_so_far = score
        convergence.append(best_so_far)
        # skopt minimizes; we want to maximize → negate
        return -score

    if HAS_SKOPT:
        acq_map = {"EI": "EI", "PI": "PI", "LCB": "LCB"}
        acq = acq_map.get(config.acquisition, "EI")
        n_random = min(config.n_random_starts, config.n_calls)
        result = gp_minimize(
            _eval,
            dimensions=dims,
            n_calls=config.n_calls,
            n_initial_points=n_random,
            acq_func=acq,
            random_state=config.seed,
        )
        best_values = result.x
    else:
        best_values = _fallback_bo(_eval, dims, keys, spec.param_ranges, config)

    best_params = _decode_skopt(best_values, keys, spec.param_ranges)
    best_score = max([t["score"] for t in all_trials]) if all_trials else float("-inf")

    return {
        "best_params": best_params,
        "best_score": best_score,
        "all_trials": all_trials,
        "convergence": convergence,
    }


# -------------------- Fallback: minimal GP-EI without skopt --------------------

def _build_fallback_space(param_ranges: dict[str, Any]):
    """For fallback, return (keys, dims) where dims are just the raw range tuples/lists.

    Raises:
        ValueError: if a tuple range has length != 2 (must be ``(lo, hi)``)
            or if a value is neither a list nor a 2-tuple. The skopt path
            raises in ``_build_skopt_space``; this mirrors that behavior so
            both BO codepaths fail loudly on malformed param_ranges instead
            of silently mis-sampling.
    """
    keys = sorted(param_ranges.keys())
    dims = []
    for k in keys:
        dim = param_ranges[k]
        if isinstance(dim, list):
            dims.append(dim)
            continue
        if isinstance(dim, tuple):
            if len(dim) != 2:
                raise ValueError(
                    f"param_range '{k}' tuple must be (lo, hi); "
                    f"got {len(dim)} elements: {dim!r}"
                )
            dims.append(dim)
            continue
        raise ValueError(
            f"param_range '{k}' must be a list (categorical) or "
            f"(lo, hi) tuple; got {type(dim).__name__}: {dim!r}"
        )
    return keys, dims


def _sample_fallback(dim, rng: np.random.Generator):
    if isinstance(dim, list):
        return dim[rng.integers(0, len(dim))]
    lo, hi = dim
    if isinstance(lo, bool) or isinstance(hi, bool):
        return bool(rng.integers(0, 2))
    if isinstance(lo, int) and isinstance(hi, int):
        return int(rng.integers(lo, hi + 1))
    return float(rng.uniform(lo, hi))


def _encode_fallback(values, dims):
    """Encode mixed-type sample to a real-valued vector for GP."""
    out = []
    for v, dim in zip(values, dims):
        if isinstance(dim, list):
            out.append(float(dim.index(v)))
        else:
            out.append(float(v))
    return np.array(out, dtype=float)


def _is_categorical_dim(dim) -> bool:
    """Detect whether a fallback dim is categorical.

    A dim is categorical if it is a list (explicit choices) OR a (lo, hi)
    tuple where lo or hi is a bool. Numeric int / float ranges are NOT
    categorical.
    """
    if isinstance(dim, list):
        return True
    if isinstance(dim, tuple) and len(dim) == 2:
        lo, hi = dim
        if isinstance(lo, bool) or isinstance(hi, bool):
            return True
    return False


def _categorical_mask(dims) -> np.ndarray:
    """Boolean mask: True where dim is categorical."""
    return np.array([_is_categorical_dim(d) for d in dims], dtype=bool)


def _build_mixed_kernel(cat_mask: np.ndarray):
    """Build a kernel that uses Hamming distance for categorical dims and
    Matern for real dims. When all dims are real, returns plain Matern.

    The Hamming term contributes exp(-Σ 1{x_i != y_i} / scale) for the
    categorical block, which is the standard kernel for unordered categorical
    variables. This avoids the bug of treating categorical-as-int-index as
    a real number under Matern.

    LIMITATION (sub-optimal): the analytic gradient is returned as a zero
    matrix, so sklearn's L-BFGS-B optimizer has no descent direction and the
    caller in ``_fallback_bo`` disables the optimizer entirely
    (``optimizer=None``). This means the GP fits with the constant initial
    length_scale=1.0 and hamming_scale=1.0 and never refines them. For a
    production-quality mixed BO with categorical params we strongly
    recommend installing scikit-optimize (``pip install scikit-optimize``)
    so ``Categorical`` Space dims and the proper acquisition routines are
    used. The fallback exists only to keep the dependency surface small and
    is acceptable for low-dimensional (n<=10) categorical-light problems.

    To remove the limitation: implement analytic gradients
    d/d(length_scale) of k_real (squared exponential) and
    d/d(hamming_scale) of k_cat (Hamming) and stack them into the third
    axis of the returned ``grad`` tensor.
    """
    if not cat_mask.any():
        return ConstantKernel(1.0) * Matern(length_scale=1.0, nu=2.5)

    cat_idx = np.flatnonzero(cat_mask).astype(int)
    real_idx = np.flatnonzero(~cat_mask).astype(int)

    class _MixedKernel(Kernel):
        def __init__(self, length_scale=1.0, hamming_scale=1.0):
            self.length_scale = length_scale
            self.hamming_scale = hamming_scale

        @property
        def hyperparameter_length_scale(self):
            return Hyperparameter("length_scale", "numeric", (1e-3, 1e3))

        @property
        def hyperparameter_hamming_scale(self):
            return Hyperparameter("hamming_scale", "numeric", (1e-3, 1e3))

        def __call__(self, X, Y=None, eval_gradient=False):
            X = np.asarray(X)
            Y = X if Y is None else np.asarray(Y)
            # Real block: squared exponential on the real-valued sub-vector.
            if real_idx.size > 0:
                Xr = X[:, real_idx]
                Yr = Y[:, real_idx]
                d2 = np.sum((Xr[:, None, :] - Yr[None, :, :]) ** 2, axis=2)
                k_real = np.exp(-d2 / (2.0 * self.length_scale ** 2))
            else:
                k_real = np.ones((X.shape[0], Y.shape[0]))
            # Categorical block: Hamming distance via inequality count.
            if cat_idx.size > 0:
                Xc = X[:, cat_idx]
                Yc = Y[:, cat_idx]
                hd = np.sum(Xc[:, None, :] != Yc[None, :, :], axis=2).astype(float)
                k_cat = np.exp(-hd / self.hamming_scale)
            else:
                k_cat = np.ones((X.shape[0], Y.shape[0]))
            K = k_real * k_cat
            if eval_gradient:
                # Don't bother with analytic gradient; return zeros so
                # sklearn skips hyperparameter optimization for this kernel.
                grad = np.zeros((X.shape[0], Y.shape[0], 2))
                return K, grad
            return K

        def diag(self, X):
            return np.ones(np.asarray(X).shape[0])

        def is_stationary(self):
            return True

    return ConstantKernel(1.0) * _MixedKernel(length_scale=1.0, hamming_scale=1.0)


def _fallback_bo(eval_neg, dims, keys, param_ranges, config: BayesConfig):
    """Minimal GP-EI BO using sklearn + scipy when skopt is unavailable.

    Categorical dims (list-typed or bool-typed ranges) are handled with a
    Hamming-distance kernel block so the GP does not treat their index as a
    continuous real value.
    """
    if not HAS_SKLEARN:
        raise ImportError(_SKOPT_INSTALL_MSG)

    rng = np.random.default_rng(config.seed)
    cat_mask = _categorical_mask(dims)
    X_raw: list[list] = []
    X_enc: list[np.ndarray] = []
    y: list[float] = []

    n_random = min(config.n_random_starts, config.n_calls)
    for _ in range(n_random):
        sample = [_sample_fallback(d, rng) for d in dims]
        neg_score = eval_neg(sample)
        X_raw.append(sample)
        X_enc.append(_encode_fallback(sample, dims))
        y.append(neg_score)

    n_remaining = config.n_calls - n_random
    for _ in range(n_remaining):
        Xa = np.vstack(X_enc)
        ya = np.array(y)
        kernel = _build_mixed_kernel(cat_mask)
        # When the kernel block has any categorical dim we use _MixedKernel,
        # which has no analytic gradient. Disable sklearn's hyperparam search
        # (optimizer=None) so it stops emitting "no descent" warnings and
        # silently using a degenerate fit. With all-real dims the Matern path
        # has a real gradient, so we keep the optimizer enabled there.
        gp_kwargs = {
            "kernel": kernel,
            "normalize_y": True,
            "random_state": config.seed,
        }
        if cat_mask.any():
            gp_kwargs["optimizer"] = None
            gp_kwargs["n_restarts_optimizer"] = 0
            import warnings
            warnings.warn(
                "_MixedKernel has zero analytic gradient; disabling sklearn "
                "hyperparameter optimization for the GP fit. This is expected.",
                stacklevel=2,
            )
        else:
            gp_kwargs["n_restarts_optimizer"] = 2
        gp = GaussianProcessRegressor(**gp_kwargs)
        try:
            gp.fit(Xa, ya)
        except Exception:
            sample = [_sample_fallback(d, rng) for d in dims]
            neg_score = eval_neg(sample)
            X_raw.append(sample)
            X_enc.append(_encode_fallback(sample, dims))
            y.append(neg_score)
            continue

        # propose by random search over candidates, pick max EI
        n_cand = 256
        cand_raw = [[_sample_fallback(d, rng) for d in dims] for _ in range(n_cand)]
        cand_enc = np.vstack([_encode_fallback(c, dims) for c in cand_raw])
        mu, sigma = gp.predict(cand_enc, return_std=True)
        sigma = np.maximum(sigma, 1e-9)
        f_best = np.min(ya)  # we are minimizing neg_score
        improvement = f_best - mu
        z = improvement / sigma
        ei = improvement * norm.cdf(z) + sigma * norm.pdf(z)
        if config.acquisition == "PI":
            acq_vals = norm.cdf(z)
        elif config.acquisition == "LCB":
            acq_vals = -(mu - 1.96 * sigma)
        else:
            acq_vals = ei
        best_idx = int(np.argmax(acq_vals))
        sample = cand_raw[best_idx]
        neg_score = eval_neg(sample)
        X_raw.append(sample)
        X_enc.append(_encode_fallback(sample, dims))
        y.append(neg_score)

    best_idx = int(np.argmin(y))
    return X_raw[best_idx]
