import pytest

from app.domain.capabilities import ArchitectureCapability, DeploymentPosture, LatencyClass
from app.services.capability_extractor import extract_capabilities
from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS, UTILITY_GRID


def values(result):
    return {item.value for item in result.capabilities}


def test_utility_capability_extraction_excludes_rag():
    result = extract_capabilities(UTILITY_GRID)
    caps = values(result)

    assert ArchitectureCapability.DEVICE_TELEMETRY.value in caps
    assert ArchitectureCapability.STREAM_INGESTION.value in caps
    assert ArchitectureCapability.STREAM_PROCESSING.value in caps
    assert ArchitectureCapability.ML_INFERENCE.value in caps
    assert ArchitectureCapability.EVENT_DRIVEN_ORCHESTRATION.value in caps
    assert ArchitectureCapability.EXTERNAL_WORKFLOW_INTEGRATION.value in caps
    assert ArchitectureCapability.RAG_RETRIEVAL.value not in caps
    assert "rag_assistant" in result.excluded_patterns


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("telecom_congestion", ArchitectureCapability.CDR_INGESTION),
        ("investment_risk", ArchitectureCapability.MONTE_CARLO_SIMULATION),
        ("clinical_federated", ArchitectureCapability.FEDERATED_LEARNING),
        ("semiconductor_twin", ArchitectureCapability.DIGITAL_TWIN),
        ("aml_graph", ArchitectureCapability.GRAPH_ANALYTICS),
        ("live_sports", ArchitectureCapability.VIDEO_STREAMING),
        ("drug_graph", ArchitectureCapability.MOLECULAR_GRAPH_MODELING),
        ("market_making", ArchitectureCapability.MICROSECOND_LATENCY),
    ],
)
def test_golden_scenarios_get_distinct_capabilities(name, expected):
    result = extract_capabilities(GOLDEN_SCENARIOS[name])

    assert expected.value in values(result)
    assert ArchitectureCapability.RAG_RETRIEVAL.value not in values(result)


def test_latency_and_deployment_posture_are_realistic_for_non_public_hot_paths():
    identity = extract_capabilities(GOLDEN_SCENARIOS["national_identity"])
    trading = extract_capabilities(GOLDEN_SCENARIOS["market_making"])

    assert DeploymentPosture.AIR_GAPPED_ON_PREM in identity.deployment_posture
    assert DeploymentPosture.EXCHANGE_COLOCATED in trading.deployment_posture
    assert trading.latency_class == LatencyClass.MICROSECOND

