"""Regime analysis utilities.

Modules:
- bayes_alpha: Bayesian rolling regression for alpha estimation.
- hmm: Gaussian HMM regime detector (Hamilton 1989 style).
- hurst: Hurst exponent + DFA regime classifier (Hurst 1951; Peng et al. 1994).
- markov_switching: Markov regime-switching mean strategy (Hamilton 1989).

Public HMM API:
- GaussianHMM, HMMResult
- regime_conditional_metrics, detect_regime_change

Public Hurst API:
- HurstResult
- hurst_rs, hurst_dfa
- rolling_hurst, hurst_regime_filter

Public Bayesian alpha API:
- bayesian_rolling_alpha, BayesAlphaResult, BayesAlphaModel
- ``BayesAlphaModel`` is a thin class wrapper over ``bayesian_rolling_alpha``
  that holds priors + window on the instance and exposes ``.fit()``.

Public Markov switching API:
- MarkovSwitchingMean
"""
# Build ``__all__`` conditionally on import success, mirroring the
# top-level ``quantforge/__init__.py`` pattern. Symbols whose backing
# import failed are left out of ``__all__`` so ``from quantforge.regime
# import *`` does not surface ``None`` placeholders, while the names are
# still bound at module level for ``hasattr``-style probes.
__all__: list[str] = []

try:
    from quantforge.regime.hurst import (
        HurstResult,
        hurst_dfa,
        hurst_regime_filter,
        hurst_rs,
        rolling_hurst,
    )
    __all__.extend([
        "HurstResult",
        "hurst_dfa",
        "hurst_regime_filter",
        "hurst_rs",
        "rolling_hurst",
    ])
except ImportError:  # pragma: no cover
    HurstResult = None  # type: ignore[assignment]
    hurst_dfa = None  # type: ignore[assignment]
    hurst_regime_filter = None  # type: ignore[assignment]
    hurst_rs = None  # type: ignore[assignment]
    rolling_hurst = None  # type: ignore[assignment]

# HMM has an optional hmmlearn dependency; import lazily so consumers that
# only need Hurst do not require hmmlearn to be installed.
try:
    from quantforge.regime.hmm import (
        GaussianHMM,
        HMMResult,
        detect_regime_change,
        regime_conditional_metrics,
    )
    __all__.extend([
        "GaussianHMM",
        "HMMResult",
        "detect_regime_change",
        "regime_conditional_metrics",
    ])
except ImportError:  # pragma: no cover - optional dep
    GaussianHMM = None  # type: ignore[assignment]
    HMMResult = None  # type: ignore[assignment]
    detect_regime_change = None  # type: ignore[assignment]
    regime_conditional_metrics = None  # type: ignore[assignment]

# Bayesian rolling alpha. The module exposes both the function-style entrypoint
# ``bayesian_rolling_alpha`` and a thin class wrapper ``BayesAlphaModel`` that
# stores priors + window on the instance and forwards to the function.
try:
    from quantforge.regime.bayes_alpha import (
        BayesAlphaModel,
        BayesAlphaResult,
        bayesian_rolling_alpha,
    )
    __all__.extend([
        "BayesAlphaModel",
        "BayesAlphaResult",
        "bayesian_rolling_alpha",
    ])
except ImportError:  # pragma: no cover
    BayesAlphaModel = None  # type: ignore[assignment]
    BayesAlphaResult = None  # type: ignore[assignment]
    bayesian_rolling_alpha = None  # type: ignore[assignment]

# Markov switching: MarkovSwitchingMean has an optional statsmodels dep but
# falls back to a manual EM implementation, so the import itself is always
# available.
try:
    from quantforge.regime.markov_switching import MarkovSwitchingMean
    __all__.append("MarkovSwitchingMean")
except ImportError:  # pragma: no cover
    MarkovSwitchingMean = None  # type: ignore[assignment]
