"""LLM-assisted research utilities for QuantForge."""
from aurora.research.llm_assistant import (
    LLMConfig,
    LLMResearchAssistant,
    ANTHROPIC_AVAILABLE,
)
from aurora.research.paper_replicator import (
    PaperReplicator,
    PaperSpec,
    ReplicationReport,
)
from aurora.research.strategy_zoo import (
    StrategyZoo,
    ZooEntry,
)
from aurora.research.hypothesis_framework import (
    Hypothesis,
    HypothesisResult,
    HypothesisTester,
)
from aurora.research.wf_tournament import (
    TournamentEntry,
    TournamentReport,
    WalkForwardTournament,
    WindowResult,
)
from aurora.research.strategy_combiner import (
    CombinerEntry,
    CombinerReport,
    StrategyCombiner,
)
from aurora.research.strategy_kg import (
    StrategyKnowledgeGraph,
    StrategyNode,
    FactorNode,
)
from aurora.research.hf_benchmark import (
    FACTOR_NAMES,
    HedgeFundBenchmark,
    StyleAttributionReport,
    synthetic_factor_returns,
)
from aurora.research.leaderboard import (
    LeaderboardEntry,
    StrategyLeaderboard,
)
from aurora.research.strategy_marketplace import (
    MarketplaceStrategy,
    StrategyMarketplace,
)
from aurora.research.auto_research_loop import (
    AutoResearchLoop,
    IterationRecord,
    LoopReport,
    MockLLM,
)
from aurora.research.notebook_templates import (
    NotebookTemplateEngine,
    NotebookSpec,
)
from aurora.research.dvc_mlflow import (
    DVCMLflowIntegration,
    RunRecord,
)
from aurora.research.wandb_tracking import (
    WandBTracker,
    WandBRun,
)
from aurora.research.ab_testing import (
    ABTestFramework,
    ABTestResult,
)
from aurora.research.bandit_allocator import (
    LiveBanditAllocator,
    AllocationReport,
    ArmState,
)
from aurora.research.concept_drift_monitor import (
    ConceptDriftMonitor,
    DriftSignal,
)
from aurora.research.champion_challenger import (
    ChampionChallengerFramework,
    ChampionDecision,
    StrategyState,
)
from aurora.research.shadow_mode import (
    ShadowModeRunner,
    ShadowReport,
)
from aurora.research.canary_deploy import (
    CanaryDeployer,
    CanaryReport,
)
from aurora.research.blue_green_models import (
    BlueGreenModelDeployer,
    DeploymentReport,
)

__all__ = [
    # llm assistant
    "LLMConfig", "LLMResearchAssistant", "ANTHROPIC_AVAILABLE",
    # paper replicator
    "PaperReplicator", "PaperSpec", "ReplicationReport",
    # strategy zoo
    "StrategyZoo", "ZooEntry",
    # hypothesis framework
    "Hypothesis", "HypothesisResult", "HypothesisTester",
    # wf tournament
    "TournamentEntry", "TournamentReport", "WalkForwardTournament", "WindowResult",
    # strategy combiner
    "CombinerEntry", "CombinerReport", "StrategyCombiner",
    # strategy knowledge graph
    "StrategyKnowledgeGraph", "StrategyNode", "FactorNode",
    # hf benchmark
    "FACTOR_NAMES", "HedgeFundBenchmark", "StyleAttributionReport",
    "synthetic_factor_returns",
    # leaderboard
    "LeaderboardEntry", "StrategyLeaderboard",
    # marketplace
    "MarketplaceStrategy", "StrategyMarketplace",
    # auto research loop
    "AutoResearchLoop", "IterationRecord", "LoopReport", "MockLLM",
    # batch H: research workflow modules
    "NotebookTemplateEngine", "NotebookSpec",
    "DVCMLflowIntegration", "RunRecord",
    "WandBTracker", "WandBRun",
    "ABTestFramework", "ABTestResult",
    "LiveBanditAllocator", "AllocationReport", "ArmState",
    "ConceptDriftMonitor", "DriftSignal",
    "ChampionChallengerFramework", "ChampionDecision", "StrategyState",
    "ShadowModeRunner", "ShadowReport",
    "CanaryDeployer", "CanaryReport",
    "BlueGreenModelDeployer", "DeploymentReport",
]
