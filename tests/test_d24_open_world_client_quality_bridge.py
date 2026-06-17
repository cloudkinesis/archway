from types import SimpleNamespace

import pytest

from app.models.domain import AWSServiceSelection, Assumption
from app.services.architecture import ArchitecturePlanner, _requirement_coverage
from app.services.canonical_facts import build_canonical_fact_snapshot
from app.services.client_pack import client_pack_files
from app.services.metric_extractor import explicit_numeric_phrases
from app.services.pricing import PricingEngine
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_to_metadata, profile_use_case


def _brief_with_answer():
    brief = SynthesisEngine().create_initial_brief(
        "A textile recycling cooperative wants an AI quality assistant that inspects bale photos, "
        "sensor readings, and operator notes to prioritize material recovery while keeping supplier terms private."
    )
    brief.assumptions.append(
        Assumption(
            text=(
                "Pilot covers 18 facilities, 4,500 material bins, 12 image angles per bale, "
                "2,000 bales per month, 9 MB per image, readings every 7 minutes, "
                "and supervisor review within 20 minutes."
            ),
            reason="Captured during customer discovery.",
            impact="pricing",
            confidence="high",
            user_confirmed=True,
        )
    )
    return brief


def test_interview_quantities_flow_into_canonical_fact_snapshot():
    snapshot = build_canonical_fact_snapshot(_brief_with_answer())

    source_texts = {str(item["source_text"]) for item in snapshot["quantities"]}

    assert any("18 facilities" in text for text in source_texts)
    assert any("4,500 material bins" in text for text in source_texts)
    assert any("12 image angles per bale" in text for text in source_texts)
    assert any("9 mb per image" in text.lower() for text in source_texts)
    assert any("7 minutes" in text for text in source_texts)
    assert any("20 minutes" in text for text in source_texts)
    assert not any("for initial aws pricing estimates" in text.lower() for text in source_texts)


def test_open_world_numeric_extraction_trims_noise_without_domain_rules():
    metrics = explicit_numeric_phrases(
        "Use us-east-1 for initial AWS pricing estimates. "
        "Each case has 4 thermal images per parcel at about 6 MB each and 12 scan events per parcel."
    )
    raw = {item.raw for item in metrics}

    assert "1 for initial aws pricing estimates" not in raw
    assert "4 thermal images per parcel" in raw
    assert "4 thermal images per parcel at" not in raw
    assert "6 mb each" in raw
    assert "12 scan events per parcel" in raw


@pytest.mark.asyncio
async def test_unsupported_pricing_family_exports_complete_not_estimated_trace():
    estimate = await PricingEngine().estimate(
        _brief_with_answer(),
        [
            AWSServiceSelection(service="Amazon S3", purpose="image evidence storage", rationale="managed durability"),
            AWSServiceSelection(service="Amazon SageMaker", purpose="quality inference", rationale="managed ML"),
        ],
    )

    metadata = estimate.metadata
    assert metadata["source_truth_pricing_compiler"]["enabled"] is True
    assert metadata["source_truth_pricing_compiler"]["mode"] == "generic_not_estimated"
    assert metadata["canonical_facts"]["facts"]
    assert metadata["pricing_driver_bindings"]
    assert metadata["service_usage_dimensions"]
    assert metadata["aws_rate_bindings"]
    assert metadata["pricing_ledger"]["line_items"]
    assert all(item["evidence_class"] == "not_estimated" for item in metadata["pricing_ledger"]["line_items"])
    assert any(item["quantity"] is not None for item in metadata["service_usage_dimensions"])
    assert metadata["pricing_ledger"]["summary"]["headline_safe"] is False
    assert estimate.metadata["pricing_can_be_displayed_as_headline"] is False


def test_open_world_architecture_adds_generic_modality_and_offline_components():
    profile = profile_use_case(
        "A specialty returns network inspects parcel images, logger streams, and courier notes, "
        "keeps identifiers private, requires pharmacist approval, and works through intermittent connectivity."
    )
    profile.capabilities = list(dict.fromkeys([*profile.capabilities, "computer_vision", "intermittent_connectivity"]))
    profile.actions = list(dict.fromkeys([*profile.actions, "pharmacist_approval"]))
    report = SimpleNamespace(
        session_id="sess_test",
        metadata={"use_case_profile": profile_to_metadata(profile)},
        use_case_interpretation="Returns network with image, text, approval, evidence, and offline sync requirements.",
        recommended_poc="Run a bounded POC.",
        recommended_production_direction="Use governed AWS-native processing with explicit validation gates.",
        aws_service_recommendations=[],
        assumptions=[],
        risks=[],
    )

    specs = ArchitecturePlanner().generate(report)
    production = next(spec for spec in specs if spec.mode == "production")
    component_ids = {component.id for component in production.components}
    coverage = {item["id"]: item for item in production.metadata["requirement_coverage"]["requirements"]}

    assert {"image_ingest", "vision_inference", "text_document_processing", "edge_offline_sync", "evidence_archive"} <= component_ids
    assert coverage["computer_vision_hot_path"]["status"] == "covered"
    assert coverage["document_processing_path"]["status"] == "covered"
    assert coverage["intermittent_connectivity"]["status"] == "covered"
    assert coverage["governed_action_path"]["status"] == "covered"


def test_architecture_coverage_requires_explicit_imagery_path_not_generic_ml_only():
    profile = profile_use_case(
        "A lab triages multispectral photos and sensor readings, recommends remediation, "
        "and requires human approval before action."
    )
    profile.capabilities = list(dict.fromkeys([*profile.capabilities, "computer_vision"]))
    generic_ml_components = [
        SimpleNamespace(name="Amazon SageMaker", purpose="Model training and inference"),
        SimpleNamespace(name="AWS Step Functions", purpose="Approval workflow"),
    ]
    flows = [SimpleNamespace(label="prediction flow", metadata={})]

    generic = _requirement_coverage(profile, generic_ml_components, flows, production=True)
    imagery = next(item for item in generic["requirements"] if item["id"] == "computer_vision_hot_path")
    assert imagery["status"] == "unmet"

    explicit_components = [
        SimpleNamespace(name="Amazon SageMaker", purpose="Multispectral image preprocessing and vision inference"),
        SimpleNamespace(name="AWS Step Functions", purpose="Approval workflow"),
    ]
    covered = _requirement_coverage(profile, explicit_components, flows, production=True)
    imagery = next(item for item in covered["requirements"] if item["id"] == "computer_vision_hot_path")
    assert imagery["status"] == "covered"


def test_client_pack_carries_workload_facts_and_unbound_pricing_dimensions():
    dossier = SimpleNamespace(
        title="Textile Recycling Quality Assistant",
        verdict="Proceed with caveats.",
        estimated_monthly_cost_range="Pricing is directional and not headline-safe.",
        top_validation_gates=["Confirm service-specific pricing units."],
        workload_family=["computer_vision_quality_inspection"],
        risks=[SimpleNamespace(severity="medium", risk="Pricing units are unbound.", mitigation="Confirm units.")],
        quality_score=SimpleNamespace(pricing_score=5),
    )
    report = {
        "metadata": {
            "canonical_fact_snapshot": {
                "quantities": [
                    {"source_text": "18 facilities"},
                    {"source_text": "4,500 material bins"},
                    {"source_text": "9 MB per image"},
                ],
                "signals": ["photo", "sensor_reading"],
                "actions": ["supervisor_review"],
                "latency_slos": ["within 20 minutes"],
                "compliance_security_hints": ["supplier terms private"],
            },
            "customer_readiness": {"status": "directional_only"},
            "evidence_quality": {"evidence_authority": "mixed"},
        },
        "citation_coverage": {"coverage_percent": 80, "passed": True},
        "evidence_items": [],
        "recommended_production_direction": "Use governed AWS-native processing with explicit validation gates.",
    }
    pricing = {
        "region": "us-east-1",
        "main_cost_drivers": [],
        "unknown_variables": [],
        "metadata": {
            "pricing_can_be_displayed_as_headline": False,
            "pricing_ledger": {"summary": {"headline_safe": False, "procurement_ready": False}},
            "pricing_driver_closure": {"missing_drivers": [], "procurement_ready": False},
            "service_usage_dimensions": [{
                "service_name": "Amazon S3",
                "usage_name": "workload-specific usage not yet bound",
                "unit": "GB-month",
                "formula": "No exact quantity formula is bound; confirm workload driver, AWS usage unit, SKU/tier, and region.",
                "quantity": None,
            }],
        },
    }
    architectures = [{
        "mode": "production",
        "summary": "Managed AWS processing with approval gates.",
        "selected_services": [{"service": "Amazon S3", "purpose": "Evidence storage"}],
        "metadata": {
            "requirement_coverage": {
                "requirements": [{
                    "id": "computer_vision_hot_path",
                    "label": "Computer vision / imagery processing",
                    "status": "unmet",
                    "message": "Computer-vision requirement was extracted but no imagery/video inference path is explicit.",
                }]
            }
        },
    }]

    client = client_pack_files(
        session_name="Textile Recycling Quality Assistant",
        brief={"title": "Textile Recycling Quality Assistant", "refined_problem_statement": "Inspect bales and prioritize recovery."},
        report=report,
        pricing=pricing,
        architectures=architectures,
        diagrams=[],
        deep_dossier=dossier,
        decision_records=[],
    )

    architecture_summary = client["03-architecture-summary.md"]
    pricing_summary = client["04-pricing-summary.md"]
    assert "18 facilities" in architecture_summary
    assert "4,500 material bins" in architecture_summary
    assert "Computer vision / imagery processing" in architecture_summary
    assert "unmet" in architecture_summary
    assert "9 MB per image" in pricing_summary
    assert "Service dimensions still to bind" in pricing_summary
    assert "Amazon S3" in pricing_summary
