"""LLM-assisted research utilities for QuantForge."""
from quantforge.research.llm_assistant import (
    LLMConfig,
    LLMResearchAssistant,
    ANTHROPIC_AVAILABLE,
)
from quantforge.research.paper_replicator import (
    PaperReplicator,
    PaperSpec,
    ReplicationReport,
)
from quantforge.research.strategy_zoo import (
    StrategyZoo,
    ZooEntry,
)
from quantforge.research.hypothesis_framework import (
    Hypothesis,
    HypothesisResult,
    HypothesisTester,
)
from quantforge.research.wf_tournament import (
    TournamentEntry,
    TournamentReport,
    WalkForwardTournament,
    WindowResult,
)
from quantforge.research.strategy_combiner import (
    CombinerEntry,
    CombinerReport,
    StrategyCombiner,
)
from quantforge.research.strategy_kg import (
    StrategyKnowledgeGraph,
    StrategyNode,
    FactorNode,
)
from quantforge.research.hf_benchmark import (
    FACTOR_NAMES,
    HedgeFundBenchmark,
    StyleAttributionReport,
    synthetic_factor_returns,
)
from quantforge.research.leaderboard import (
    LeaderboardEntry,
    StrategyLeaderboard,
)
from quantforge.research.strategy_marketplace import (
    MarketplaceStrategy,
    StrategyMarketplace,
)
from quantforge.research.auto_research_loop import (
    AutoResearchLoop,
    IterationRecord,
    LoopReport,
    MockLLM,
)
from quantforge.research.notebook_templates import (
    NotebookTemplateEngine,
    NotebookSpec,
)
from quantforge.research.dvc_mlflow import (
    DVCMLflowIntegration,
    RunRecord,
)
from quantforge.research.wandb_tracking import (
    WandBTracker,
    WandBRun,
)
from quantforge.research.ab_testing import (
    ABTestFramework,
    ABTestResult,
)
from quantforge.research.bandit_allocator import (
    LiveBanditAllocator,
    AllocationReport,
    ArmState,
)
from quantforge.research.concept_drift_monitor import (
    ConceptDriftMonitor,
    DriftSignal,
)
from quantforge.research.champion_challenger import (
    ChampionChallengerFramework,
    ChampionDecision,
    StrategyState,
)
from quantforge.research.shadow_mode import (
    ShadowModeRunner,
    ShadowReport,
)
from quantforge.research.canary_deploy import (
    CanaryDeployer,
    CanaryReport,
)
from quantforge.research.blue_green_models import (
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
