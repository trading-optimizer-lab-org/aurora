"""Validation gates: walk-forward, MC, SPP, lookahead, DSR, purged CV, CSCV,
structural breaks, tail risk, correlation stress, scenarios.
"""
from aurora.validation import (
    correlation_stress,
    purged_cv,
    scenarios,
    structural_breaks,
    tail_risk,
)
from aurora.validation.cscv_pbo import (
    cscv,
    CSCVResult,
    cscv_summary_table,
    plot_pbo_distribution,
)
from aurora.validation.deflated_sharpe import deflated_sharpe_check
from aurora.validation.gap_sim import gap_sim, GapSimResult
from aurora.validation.lookahead_check import scan_lookahead
from aurora.validation.monte_carlo import (
    monte_carlo_bootstrap,
    monte_carlo_trade_reorder,
)
from aurora.validation.noise_injection import noise_injection, NoiseInjectionResult
from aurora.validation.pipeline import validate_pipeline, ValidationReport
from aurora.validation.purged_cv import PurgedKFold, cv_score
from aurora.validation.retraining import simulate_retraining, RetrainResult
from aurora.validation.scenarios import KNOWN_CRASHES, stress_test_all_known
from aurora.validation.statistical_robustness import (
    RobustnessCheck,
    StatisticalRobustnessConfig,
    StatisticalRobustnessReport,
    benjamini_hochberg,
    statistical_robustness_gate,
)
from aurora.validation.robustness_config import UniversalRobustnessConfig
from aurora.validation.robustness_reports import write_universal_robustness_outputs
from aurora.validation.universal_robustness import (
    UniversalRobustnessResult,
    run_batch_universal_robustness,
    run_universal_robustness,
    run_universal_robustness_from_positions,
)
from aurora.validation.spp import spp
from aurora.validation.structural_breaks import (
    chow_test,
    ChowResult,
    cusum_filter,
    CUSUMResult,
    sadf_test,
    SADFResult,
)
from aurora.validation.walk_forward import walk_forward

# Batch D advanced robustness modules
from aurora.validation.adversarial_backtest import AdversarialBacktester
from aurora.validation.copula_tail import CopulaTailDependence
from aurora.validation.gan_crisis import CrisisGANGenerator
from aurora.validation.ood_detection import OODDetector
from aurora.validation.capacity_estimator import CapacityEstimator
from aurora.validation.slippage_stress import SlippageStressTest
from aurora.validation.multi_freq_bootstrap import MultiFrequencyBootstrap
from aurora.validation.parameter_rank_stability import ParameterRankStability
from aurora.validation.partial_dependence import PartialDependenceAnalysis
from aurora.validation.shap_explain import SHAPExplainer

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
    "statistical_robustness",
    "universal_robustness",
    "robustness_config",
    "robustness_data_quality",
    "robustness_duplicates",
    "robustness_reports",
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
    # statistical robustness
    "RobustnessCheck",
    "StatisticalRobustnessConfig",
    "StatisticalRobustnessReport",
    "benjamini_hochberg",
    "statistical_robustness_gate",
    "UniversalRobustnessConfig",
    "UniversalRobustnessResult",
    "run_universal_robustness",
    "run_universal_robustness_from_positions",
    "run_batch_universal_robustness",
    "write_universal_robustness_outputs",
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
