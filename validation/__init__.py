"""Validation gates: walk-forward, MC, SPP, lookahead, DSR, purged CV, CSCV,
structural breaks, tail risk, correlation stress, scenarios.
"""
from quantforge.validation import (
    correlation_stress,
    purged_cv,
    scenarios,
    structural_breaks,
    tail_risk,
)
from quantforge.validation.cscv_pbo import (
    cscv,
    CSCVResult,
    cscv_summary_table,
    plot_pbo_distribution,
)
from quantforge.validation.deflated_sharpe import deflated_sharpe_check
from quantforge.validation.gap_sim import gap_sim, GapSimResult
from quantforge.validation.lookahead_check import scan_lookahead
from quantforge.validation.monte_carlo import (
    monte_carlo_bootstrap,
    monte_carlo_trade_reorder,
)
from quantforge.validation.noise_injection import noise_injection, NoiseInjectionResult
from quantforge.validation.pipeline import validate_pipeline, ValidationReport
from quantforge.validation.purged_cv import PurgedKFold, cv_score
from quantforge.validation.retraining import simulate_retraining, RetrainResult
from quantforge.validation.scenarios import KNOWN_CRASHES, stress_test_all_known
from quantforge.validation.spp import spp
from quantforge.validation.structural_breaks import (
    chow_test,
    ChowResult,
    cusum_filter,
    CUSUMResult,
    sadf_test,
    SADFResult,
)
from quantforge.validation.walk_forward import walk_forward

# Batch D advanced robustness modules
from quantforge.validation.adversarial_backtest import AdversarialBacktester
from quantforge.validation.copula_tail import CopulaTailDependence
from quantforge.validation.gan_crisis import CrisisGANGenerator
from quantforge.validation.ood_detection import OODDetector
from quantforge.validation.capacity_estimator import CapacityEstimator
from quantforge.validation.slippage_stress import SlippageStressTest
from quantforge.validation.multi_freq_bootstrap import MultiFrequencyBootstrap
from quantforge.validation.parameter_rank_stability import ParameterRankStability
from quantforge.validation.partial_dependence import PartialDependenceAnalysis
from quantforge.validation.shap_explain import SHAPExplainer

# Submodule re-exports (kept distinct from class / function entries so
# downstream tooling can tell apart "module" from "callable").
_SUBMODULES = [
    "purged_cv",
    "tail_risk",
    "correlation_stress",
    "scenarios",
    "structural_breaks",
    "adversarial_backtest",
    "copula_tail",
    "gan_crisis",
    "ood_detection",
    "capacity_estimator",
    "slippage_stress",
    "multi_freq_bootstrap",
    "parameter_rank_stability",
    "partial_dependence",
    "shap_explain",
]

# Class / function / dataclass entries — the public callable API.
_PUBLIC_API = [
    # walk-forward / MC / SPP
    "walk_forward",
    "monte_carlo_bootstrap",
    "monte_carlo_trade_reorder",
    "spp",
    # lookahead / DSR
    "scan_lookahead",
    "deflated_sharpe_check",
    # pipeline
    "validate_pipeline",
    "ValidationReport",
    # noise / gap / retrain
    "noise_injection",
    "NoiseInjectionResult",
    "gap_sim",
    "GapSimResult",
    "simulate_retraining",
    "RetrainResult",
    # structural breaks
    "chow_test",
    "cusum_filter",
    "sadf_test",
    "ChowResult",
    "CUSUMResult",
    "SADFResult",
    # CSCV
    "cscv",
    "CSCVResult",
    "plot_pbo_distribution",
    "cscv_summary_table",
    # purged CV
    "PurgedKFold",
    "cv_score",
    # scenarios
    "KNOWN_CRASHES",
    "stress_test_all_known",
    # Batch D
    "AdversarialBacktester",
    "CopulaTailDependence",
    "CrisisGANGenerator",
    "OODDetector",
    "CapacityEstimator",
    "SlippageStressTest",
    "MultiFrequencyBootstrap",
    "ParameterRankStability",
    "PartialDependenceAnalysis",
    "SHAPExplainer",
]

__all__ = _SUBMODULES + _PUBLIC_API
