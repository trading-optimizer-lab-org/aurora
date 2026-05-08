"""QuantForge ML — labeling, meta-labeling, bet sizing, feature importance.

Implements Lopez de Prado AFML chapters 3-4, 8.
"""
# Always-present modules — these have no optional 3rd-party deps beyond the
# package's hard dependencies, so they import unconditionally. Wrapping them
# in try/except previously hid real bugs (a typo or missing symbol would
# silently disappear from ``__all__``).
from quantforge.ml.labels import (
    TripleBarrierResult,
    daily_volatility,
    triple_barrier_labels,
    meta_labels,
    bet_size_from_proba,
)
from quantforge.ml.feature_importance import (
    mean_decrease_impurity,
    mean_decrease_accuracy,
    single_feature_importance,
    plot_importance,
)
from quantforge.ml.microstructure import (
    corwin_schultz_spread,
    roll_spread_estimator,
    signed_volume,
    order_flow_imbalance,
    vpin,
    kyle_lambda,
    amihud_illiquidity,
)
from quantforge.ml.features_pipeline import (
    FeaturePipeline,
    FeaturePipelineConfig,
)

__all__ = [
    "TripleBarrierResult",
    "daily_volatility",
    "triple_barrier_labels",
    "meta_labels",
    "bet_size_from_proba",
    "mean_decrease_impurity",
    "mean_decrease_accuracy",
    "single_feature_importance",
    "plot_importance",
    "corwin_schultz_spread",
    "roll_spread_estimator",
    "signed_volume",
    "order_flow_imbalance",
    "vpin",
    "kyle_lambda",
    "amihud_illiquidity",
    "FeaturePipeline",
    "FeaturePipelineConfig",
]

# Torch-gated symbols (LSTM + Transformer). Each module exposes a
# ``TORCH_AVAILABLE`` flag and is itself import-safe without torch, so we
# always import the module; consumers should branch on ``TORCH_AVAILABLE``
# at use time.
from quantforge.ml.lstm import (  # noqa: E402  (logical group after __all__)
    LSTMConfig,
    LSTMForecaster,
    make_sequences,
    walk_forward_train,
    TORCH_AVAILABLE,
)
from quantforge.ml.transformer import (  # noqa: E402
    TransformerConfig,
    TimeSeriesTransformer,
    make_multi_horizon_sequences,
)

__all__ += [
    "LSTMConfig",
    "LSTMForecaster",
    "make_sequences",
    "walk_forward_train",
    "TORCH_AVAILABLE",
    "TransformerConfig",
    "TimeSeriesTransformer",
    "make_multi_horizon_sequences",
]

# Gymnasium / SB3-gated symbols. ``rl_agent`` exposes ``GYM_AVAILABLE`` and
# ``SB3_AVAILABLE`` for runtime branching; the module itself is import-safe
# without those extras installed.
from quantforge.ml.rl_agent import (  # noqa: E402
    GYM_AVAILABLE,
    SB3_AVAILABLE,
    TradingEnvConfig,
    TradingEnv,
    RLAgentConfig,
    RLAgent,
    evaluate_policy,
)

__all__ += [
    "GYM_AVAILABLE",
    "SB3_AVAILABLE",
    "TradingEnvConfig",
    "TradingEnv",
    "RLAgentConfig",
    "RLAgent",
    "evaluate_policy",
]


# ---------------------------------------------------------------------------
# Batch C — advanced ML/AI modules. Each submodule handles its own optional
# dependency probing internally; we re-export the public symbols guarded so a
# missing heavy dep never breaks ``import quantforge.ml``.
# ---------------------------------------------------------------------------

try:
    from quantforge.ml.automl_features import (  # noqa: E402
        AutoMLConfig,
        AutoMLFeatureEngineer,
    )
    __all__ += ["AutoMLConfig", "AutoMLFeatureEngineer"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.genetic_programming import (  # noqa: E402
        GPConfig,
        GeneticFormulaEngine,
        DEAP_AVAILABLE,
    )
    __all__ += ["GPConfig", "GeneticFormulaEngine", "DEAP_AVAILABLE"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.transformer_multi_asset import (  # noqa: E402
        MultiAssetTransformer,
        MultiAssetTransformerConfig,
    )
    __all__ += ["MultiAssetTransformer", "MultiAssetTransformerConfig"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.graph_neural_net import (  # noqa: E402
        CorrelationGraphNN,
        CorrelationGNNConfig,
        build_correlation_graph,
        PYG_AVAILABLE,
    )
    __all__ += [
        "CorrelationGraphNN",
        "CorrelationGNNConfig",
        "build_correlation_graph",
        "PYG_AVAILABLE",
    ]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.causal_inference import (  # noqa: E402
        CausalFactorAnalysis,
        CausalReport,
        RefutationResult,
    )
    __all__ += ["CausalFactorAnalysis", "CausalReport", "RefutationResult"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.bayesian_nn import (  # noqa: E402
        BayesianForecaster,
        BayesianConfig,
        PYRO_AVAILABLE,
    )
    __all__ += ["BayesianForecaster", "BayesianConfig", "PYRO_AVAILABLE"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.meta_learning import (  # noqa: E402
        MetaLearner,
        MetaConfig,
        Task as MetaTask,
    )
    __all__ += ["MetaLearner", "MetaConfig", "MetaTask"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.multi_agent_rl import (  # noqa: E402
        MultiAgentTradingEnv,
        MultiAgentEnvConfig,
        long_only_policy,
        flat_policy,
        momentum_policy,
    )
    __all__ += [
        "MultiAgentTradingEnv",
        "MultiAgentEnvConfig",
        "long_only_policy",
        "flat_policy",
        "momentum_policy",
    ]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.llm_portfolio_manager import (  # noqa: E402
        LLMPortfolioManager,
        LLMPortfolioConfig,
        MockAnthropicClient,
        ANTHROPIC_AVAILABLE,
    )
    __all__ += [
        "LLMPortfolioManager",
        "LLMPortfolioConfig",
        "MockAnthropicClient",
        "ANTHROPIC_AVAILABLE",
    ]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.diffusion_scenarios import (  # noqa: E402
        DiffusionScenarioGenerator,
        DiffusionConfig,
    )
    __all__ += ["DiffusionScenarioGenerator", "DiffusionConfig"]
except ImportError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Batch D — next-level ML modules. Optional torch / chromadb / anthropic /
# sentence-transformers deps are guarded inside each submodule.
# ---------------------------------------------------------------------------

try:
    from quantforge.ml.mamba_ssm import (  # noqa: E402
        MambaConfig,
        MambaForecaster,
        MAMBA_AVAILABLE,
    )
    __all__ += ["MambaConfig", "MambaForecaster", "MAMBA_AVAILABLE"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.moe import (  # noqa: E402
        MoEConfig,
        MixtureOfExperts,
    )
    __all__ += ["MoEConfig", "MixtureOfExperts"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.rag_research import (  # noqa: E402
        RAGConfig,
        RAGResearchAssistant,
        MockLLM,
        CHROMADB_AVAILABLE,
    )
    __all__ += ["RAGConfig", "RAGResearchAssistant", "MockLLM", "CHROMADB_AVAILABLE"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.vector_db_papers import (  # noqa: E402
        PapersVectorDB,
        PapersVectorDBConfig,
        SENTENCE_TRANSFORMERS_AVAILABLE,
    )
    __all__ += [
        "PapersVectorDB",
        "PapersVectorDBConfig",
        "SENTENCE_TRANSFORMERS_AVAILABLE",
    ]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.knowledge_distillation import (  # noqa: E402
        DistillationConfig,
        KnowledgeDistiller,
    )
    __all__ += ["DistillationConfig", "KnowledgeDistiller"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.active_learning import (  # noqa: E402
        ActiveLearnerConfig,
        ActiveLearner,
    )
    __all__ += ["ActiveLearnerConfig", "ActiveLearner"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.curriculum_learning import (  # noqa: E402
        CurriculumConfig,
        CurriculumScheduler,
    )
    __all__ += ["CurriculumConfig", "CurriculumScheduler"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.contrastive_strategy import (  # noqa: E402
        ContrastiveConfig,
        ContrastiveStrategyEmbedder,
    )
    __all__ += ["ContrastiveConfig", "ContrastiveStrategyEmbedder"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.self_supervised_pretrain import (  # noqa: E402
        SelfSupervisedConfig,
        SelfSupervisedPretrainer,
    )
    __all__ += ["SelfSupervisedConfig", "SelfSupervisedPretrainer"]
except ImportError:  # pragma: no cover
    pass

try:
    from quantforge.ml.few_shot_strategy import (  # noqa: E402
        FewShotConfig,
        FewShotStrategyAdapter,
    )
    __all__ += ["FewShotConfig", "FewShotStrategyAdapter"]
except ImportError:  # pragma: no cover
    pass
