"""LLM-assisted research utilities for Aurora."""
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
from aurora.research.protocol_guard import (
    LockedResearchPhaseError,
    ResearchProtocolGuard,
    ResearchProtocolSpec,
)
from aurora.research.protocol_enforcement import (
    default_research_ledger_path,
    ensure_mandatory_research_protocol,
    make_project_id,
    record_robustness_run,
    record_validation_run,
)
from aurora.research.lookahead_guard import (
    LookaheadBiasError,
    assert_signal_is_causal,
)
from aurora.research.sp500_autosearch import (
    AutosearchConfig,
    AutosearchReport,
    CandidateEvidence,
    PeriodMetrics,
    run_sp500_autosearch,
)
from aurora.research.source_discovery import (
    SourceCandidate,
    SourceDiscoveryConfig,
    SourceDiscoveryReport,
    discover_sources,
    source_report_to_markdown,
)
from aurora.research.sp500_research_agent import (
    SP500ResearchAgentConfig,
    SP500ResearchAgentReport,
    run_sp500_research_agent,
    sp500_agent_report_to_markdown,
)
from aurora.research.agent_loop import (
    AgentGoalSpec,
    AgentLoopResult,
    AgentRunState,
    run_agent_loop,
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
    "LockedResearchPhaseError", "ResearchProtocolGuard", "ResearchProtocolSpec",
    "default_research_ledger_path", "ensure_mandatory_research_protocol",
    "make_project_id", "record_robustness_run", "record_validation_run",
    "LookaheadBiasError", "assert_signal_is_causal",
    "AutosearchConfig", "AutosearchReport", "CandidateEvidence",
    "PeriodMetrics", "run_sp500_autosearch",
    "SourceCandidate", "SourceDiscoveryConfig", "SourceDiscoveryReport",
    "discover_sources", "source_report_to_markdown",
    "SP500ResearchAgentConfig", "SP500ResearchAgentReport",
    "run_sp500_research_agent", "sp500_agent_report_to_markdown",
    "AgentGoalSpec", "AgentLoopResult", "AgentRunState", "run_agent_loop",
]
