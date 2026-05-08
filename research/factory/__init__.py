"""Research Factory: hypothesis -> review-queue automation.

Public re-exports for ``from quantforge.research.factory import ...``:

* :class:`StrategySpec` -- immutable proposal record (factory variant).
* :class:`CandidateRun`, :class:`ResearchOutcome`,
  :class:`ResearchStage`, :class:`RejectionReason` -- outcome types.
* :class:`ResearchFactory`, :class:`ResearchPipelineConfig` -- pipeline.
* :class:`LineageGraph` -- DAG of spec lineage.
* Generators: :class:`HypothesisGenerator`,
  :class:`GAHypothesisGenerator`,
  :class:`TemplateHypothesisGenerator`,
  :class:`LLMHypothesisGenerator`.

NOTE: ``StrategySpec`` from this package collides in name with the GA's
parameter-range descriptor in :mod:`quantforge.strategies.base`. They are
deliberately separate types -- the GA spec describes "what shapes a
parameter can take", while this factory spec describes "one concrete
proposal". Import the one you need by its module path.
"""
from quantforge.research.factory.factory import (
    ResearchFactory,
    ResearchPipelineConfig,
)
from quantforge.research.factory.generators import (
    GAHypothesisGenerator,
    HypothesisGenerator,
    LLMHypothesisGenerator,
    TemplateHypothesisGenerator,
)
from quantforge.research.factory.lineage import LineageGraph
from quantforge.research.factory.outcomes import (
    CandidateRun,
    RejectionReason,
    ResearchOutcome,
    ResearchStage,
)
from quantforge.research.factory.spec import StrategySpec

__all__ = [
    "CandidateRun",
    "GAHypothesisGenerator",
    "HypothesisGenerator",
    "LLMHypothesisGenerator",
    "LineageGraph",
    "RejectionReason",
    "ResearchFactory",
    "ResearchOutcome",
    "ResearchPipelineConfig",
    "ResearchStage",
    "StrategySpec",
    "TemplateHypothesisGenerator",
]
