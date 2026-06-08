import pytest

from app.models.domain import ResearchReport
from app.services.architecture import ArchitecturePlanner
from app.services.diagram_compiler_adapter import DiagramCompilerAdapter
from app.services.research import ResearchOrchestrator
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_use_case


UTILITY_GRID_USE_CASE = (
    "A national electric utility company wants to build a predictive grid failure detection system. "
    "The platform ingests real-time sensor data from 200,000 smart meters and 15,000 distribution transformers, "
    "correlating voltage fluctuations, load imbalances, and ambient temperature readings against historical failure patterns. "
    "When the system detects a transformer approaching thermal runaway or a feeder line showing pre-fault oscillation signatures, "
    "it automatically dispatches field crews via the existing workforce management system and pre-positions replacement equipment "
    "at the nearest depot. The goal is reducing unplanned outages by 45% and cutting mean-time-to-restore from 4 hours to under "
    "90 minutes within the first 18 months of deployment."
)


@pytest.mark.asyncio
async def test_local_flow_reaches_existing_diagram_compiler(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = SynthesisEngine()
    brief = engine.create_initial_brief("Retail support assistant for order status, delivery questions, and agent help.")
    report = await ResearchOrchestrator().run_research(brief, "sess_integration")
    specs = ArchitecturePlanner().generate(report)

    gallery = DiagramCompilerAdapter().compile_poc_diagrams(specs[0], "sess_integration")

    assert gallery.diagrams
    assert any(diagram.format_paths.get("svg") for diagram in gallery.diagrams)
    assert gallery.qa_reports


@pytest.mark.asyncio
async def test_utility_grid_flow_is_not_misclassified_as_rag_assistant(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    brief = SynthesisEngine().create_initial_brief(UTILITY_GRID_USE_CASE)
    profile = profile_use_case(UTILITY_GRID_USE_CASE)
    report = await ResearchOrchestrator().run_research(brief, "sess_utility")
    specs = ArchitecturePlanner().generate(report)

    services = {item.service for item in report.aws_service_recommendations}
    component_services = {component.service for spec in specs for component in spec.components}
    flow_labels = " ".join(flow.label or "" for spec in specs for flow in spec.flows).lower()

    assert profile.domain == "energy_utility"
    assert "industrial_iot_streaming_ml" in profile.workload_families
    assert "rag_assistant" in profile.excluded_families
    assert {"AWS IoT Core", "Amazon Kinesis Data Streams", "Amazon SageMaker", "AWS Step Functions"} <= services
    assert "opensearch_serverless" not in component_services
    assert "bedrock" not in component_services
    assert "dispatch" in flow_labels
    assert report.pricing_analysis.expected_monthly_usd > 1000
    assert not any(item == "device_count" for item in report.pricing_analysis.unknown_variables)
    assert any("asset_count=215000" in item for item in report.pricing_analysis.main_cost_drivers)
    assert any("SiteWise" in item for item in report.metadata["service_validation_notes"])
    assert {"async_flow_view", "ai_security_governance_view"} <= set(specs[1].metadata["expected_views"])
    assert report.citation_coverage is not None
    assert report.citation_coverage.passed is False
    assert report.metadata["research_quality"]["label"] == "Limited"
