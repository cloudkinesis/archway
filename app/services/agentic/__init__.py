"""D21 agentic control-plane contracts.

Phase 0 is deliberately deterministic: no model calls, no network calls, and no
client-facing authority. The modules in this package define traceable proposal
records and repair plans used by export/audit surfaces.
"""

from app.services.agentic.contracts import (
    AgentDecision,
    AgentEvidenceRef,
    AgentFinding,
    AgentProposal,
    AgentRepairAction,
    AgentRepairPlan,
    AgentRun,
    AgentTask,
    ArtifactCompletenessState,
)
from app.services.agentic.evaluation import (
    EvaluationBatteryResult,
    EvaluationFinding,
    EvaluationLaneScore,
    EvaluationMetric,
    EvaluationRunMetadata,
    EvaluationScenario,
    ScenarioObservation,
)
from app.services.agentic.research_agent import (
    ResearchAgentTrace,
    ResearchEvidenceItem,
    ResearchQueryPlan,
    ResearchQuestion,
    ResearchSynthesis,
)
from app.services.agentic.pricing_dimension_agent import (
    PricingDimensionProposal,
    PricingDimensionTrace,
    PricingDriverCandidate,
    PricingScenarioProfile,
    PricingServiceCandidate,
    PricingUsageDimensionCandidate,
)
from app.services.agentic.use_case_analyst import (
    AnalystCandidate,
    AnalystFinding,
    UseCaseAnalystProposal,
    UseCaseAnalystTrace,
)
from app.services.agentic.narrative_agent import (
    NarrativeRewriteProposal,
    NarrativeSentenceClaim,
    NarrativeTrace,
)
from app.services.agentic.reviewer_agent import (
    ReviewerFindingProposal,
    ReviewerTrace,
)
from app.services.agentic.diagram_planning_agent import (
    DiagramPlanningTrace,
    DiagramViewCandidate,
    DiagramViewPlanProposal,
)

__all__ = [
    "AgentDecision",
    "AgentEvidenceRef",
    "AgentFinding",
    "AgentProposal",
    "AgentRepairAction",
    "AgentRepairPlan",
    "AgentRun",
    "AgentTask",
    "ArtifactCompletenessState",
    "EvaluationBatteryResult",
    "EvaluationFinding",
    "EvaluationLaneScore",
    "EvaluationMetric",
    "EvaluationRunMetadata",
    "EvaluationScenario",
    "ScenarioObservation",
    "ResearchAgentTrace",
    "ResearchEvidenceItem",
    "ResearchQueryPlan",
    "ResearchQuestion",
    "ResearchSynthesis",
    "PricingDimensionProposal",
    "PricingDimensionTrace",
    "PricingDriverCandidate",
    "PricingScenarioProfile",
    "PricingServiceCandidate",
    "PricingUsageDimensionCandidate",
    "AnalystCandidate",
    "AnalystFinding",
    "UseCaseAnalystProposal",
    "UseCaseAnalystTrace",
    "NarrativeRewriteProposal",
    "NarrativeSentenceClaim",
    "NarrativeTrace",
    "ReviewerFindingProposal",
    "ReviewerTrace",
    "DiagramPlanningTrace",
    "DiagramViewCandidate",
    "DiagramViewPlanProposal",
]
