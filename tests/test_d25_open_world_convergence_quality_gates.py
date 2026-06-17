from types import SimpleNamespace

from app.models.domain import (
    ArchitectureComponent,
    ArchitectureFlow,
    ArchitectureSpec,
    AWSServiceRecommendation,
    ObservabilityControl,
    SecurityControl,
)
from app.domain.source_of_truth import CanonicalFact, CanonicalFactsLedger
from app.services.architecture import _open_world_components, _requirement_coverage
from app.services.architecture_critique import (
    ArchitectureCritiqueFinding,
    _drop_satisfied_requirement_coverage_findings,
)
from app.services.architecture_revisions import ArchitectureRevisionService
from app.services.client_pack import client_pack_files
from app.services.convergence.golden_convergence_orchestrator import _diagram_findings, _pricing_findings
from app.services.diagram_compiler_adapter import DiagramCompilerAdapter
from app.services.export_package import ExportPackageService, _llm_telemetry_live_audits, _prior_live_call_audits
from app.services.llm.base import LLMTaskType
from app.services.pricing import derive_industrial_iot_pricing_model, derive_pricing_drivers
from app.services.pricing_driver_selector import PricingDriverFamily, select_pricing_driver_family
from app.services.source_truth_pricing_compiler import _generic_quantity_context
from app.services.synthesis import _data_sources, _detect_industry, _problem_statement
from app.services.understanding.deep_use_case_understanding import deterministic_understanding
from app.services.use_case_profile import UseCaseProfile, profile_use_case, reconcile_profile_constraints


def test_problem_statement_uses_article_safe_target_wording():
    profile = SimpleNamespace(domain="the target industry", workload_families=["computer_vision_quality_inspection"])

    statement = _problem_statement(profile, "Inspect assets with photos and notes.")

    assert "for a the" not in statement
    assert statement.startswith("Design an AWS architecture for the target industry workload")


def test_generic_quantity_context_derives_annual_monthly_and_retained_usage_without_domain_rules():
    ledger = CanonicalFactsLedger(facts=[
        CanonicalFact(
            name="condition_assessments_per_year",
            value=120_000,
            unit="assessments_per_year",
            source="user_input",
            source_text="120,000 condition assessments per year",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="restoration_photos_per_item",
            value=18,
            unit="photos_per_object",
            source="user_input",
            source_text="18 high resolution restoration photos per object",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="image_size_mb",
            value=25,
            unit="mb_each",
            source="user_input",
            source_text="25 MB each",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="curator_notes_per_month",
            value=24_000,
            unit="notes_per_month",
            source="user_input",
            source_text="24,000 curator notes per month",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="loan_documents_per_month",
            value=8_000,
            unit="documents_per_month",
            source="user_input",
            source_text="8,000 loan provenance documents per month",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="retention_years",
            value=12,
            unit="years",
            source="user_input",
            source_text="retain evidence for 12 years",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
    ])

    context = _generic_quantity_context(ledger)

    assert context["monthly_events"] == 10_000
    assert context["monthly_inferences"] == 236_000
    assert context["storage_gb_month"] > 600_000
    assert "typed workload streams" in context["event_formula"]


def test_generic_quantity_context_treats_new_per_noun_units_as_per_item_without_vocabulary_lists():
    ledger = CanonicalFactsLedger(facts=[
        CanonicalFact(
            name="inspections_per_year",
            value=1_200,
            unit="inspections_per_year",
            source="user_input",
            source_text="1,200 inspections per year",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="thermal_images_per_vessel",
            value=7,
            unit="thermal_images_per_vessel",
            source="user_input",
            source_text="7 thermal images per vessel",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
    ])

    context = _generic_quantity_context(ledger)

    assert context["monthly_inferences"] == 700
    assert context["monthly_events"] == 100


def test_generic_quantity_context_keeps_asset_cadence_and_per_asset_media_streams_separate():
    ledger = CanonicalFactsLedger(facts=[
        CanonicalFact(
            name="explicit_quantity_bridges_1",
            value=1850,
            unit="bridges",
            source="user_input",
            source_text="1,850 bridges and tunnels",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="telemetry_frequency_seconds",
            value=5,
            unit="seconds",
            source="user_input",
            source_text="vibration sensors every 5 seconds",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="payload_kb",
            value=1.5,
            unit="kb_per_event",
            source="user_input",
            source_text="1.5 KB per vibration sensor event",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="thermal_image_size_mb",
            value=18,
            unit="mb_each",
            source="user_input",
            source_text="Drone thermal images are about 18 MB each",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="thermal_images_per_asset",
            value=20,
            unit="images_per_bridge",
            source="user_input",
            source_text="20 images per bridge or tunnel per quarter",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="raw_retention_months",
            value=18,
            unit="months",
            source="user_input",
            source_text="retain raw sensor history for 18 months",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
    ])

    context = _generic_quantity_context(ledger)

    assert round(context["monthly_events"]) == 959_040_000
    assert round(context["monthly_media_items"]) == 12_333
    assert context["monthly_inferences"] < 20_000
    assert context["storage_gb_month"] < 30_000
    assert not [item for item in context["plausibility_findings"] if item["severity"] == "critical"]


def test_generic_quantity_context_does_not_reuse_derived_event_totals_as_media_items():
    ledger = CanonicalFactsLedger(facts=[
        CanonicalFact(name="explicit_quantity_plants_1", value=180, unit="plants", source="user_input", source_text="180 plants", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="explicit_quantity_trucks_2", value=2400, unit="trucks", source="user_input", source_text="2,400 trucks", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="explicit_quantity_monitored_temperature_sources_3", value=2580, unit="monitored_temperature_sources", source="user_input", source_text="2,580 monitored temperature sources", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="telemetry_frequency_seconds", value=20, unit="seconds", source="user_input", source_text="readings every 20 seconds", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="explicit_quantity_kb_readings_3", value=0.8, unit="kb_readings", source="user_input", source_text="0.8 KB readings", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="explicit_quantity_mb_files_4", value=2, unit="mb_result_files", source="user_input", source_text="2 MB result files", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="explicit_quantity_times_per_day_5", value=600, unit="times_per_day", source="user_input", source_text="600 times per day", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="explicit_quantity_mb_images_6", value=5, unit="mb_images", source="user_input", source_text="5 MB images", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="explicit_quantity_times_per_day_per_site_7", value=12, unit="times_per_day_per_site", source="user_input", source_text="12 times per day per site", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="retention_days", value=120, unit="days", source="user_input", source_text="Retain telemetry for 18 months, swab result files for 7 years, camera evidence for 120 days", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="monthly_event_volume", value=334_368_000, unit="events/month", source="derived", source_text=None, confidence="medium", used_by=["pricing"], validation_status="assumed"),
    ])

    context = _generic_quantity_context(ledger)

    assert context["asset_count"] == 2580
    assert round(context["monthly_events"]) == 334_368_000
    assert context["monthly_media_items"] < 25_000
    assert context["storage_gb_month"] < 10_000
    assert not [item for item in context["plausibility_findings"] if item["severity"] == "critical"]


def test_generic_quantity_context_composes_per_batch_media_without_treating_payload_as_count():
    ledger = CanonicalFactsLedger(facts=[
        CanonicalFact(name="explicit_quantity_sorting_lines_1", value=14, unit="sorting_lines", source="user_input", source_text="14 sorting lines", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="telemetry_frequency_seconds", value=8, unit="seconds", source="user_input", source_text="readings every 8 seconds", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="payload_kb", value=2, unit="kb_per_reading", source="user_input", source_text="2 KB per sensor reading", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="images_per_batch", value=4, unit="images_per_garment_batch", source="user_input", source_text="4 images per garment batch", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="batches_per_line_per_day", value=1200, unit="garment_batches_per_line_per", source="user_input", source_text="1,200 garment batches per line per", confidence="high", used_by=["pricing"], validation_status="confirmed"),
        CanonicalFact(name="image_payload", value=6, unit="mb_per_image", source="user_input", source_text="6 MB per image", confidence="high", used_by=["pricing"], validation_status="confirmed"),
    ])

    context = _generic_quantity_context(ledger)

    assert context["monthly_events"] == 4_536_000
    assert context["media_per_base_item"] == 4
    assert context["media_per_asset"] == 0
    assert context["media_payload_mb"] == 6
    assert context["monthly_media_items"] == 2_016_000
    assert context["monthly_inferences"] == 2_016_000
    assert context["storage_gb_month"] > 100_000
    assert not [item for item in context["plausibility_findings"] if item["severity"] == "critical"]


def test_industrial_iot_pricing_binds_generic_open_world_assets_cadence_and_payload():
    profile = profile_use_case(
        "A regional infrastructure operator wants AWS to monitor 1,850 bridges and tunnels "
        "using vibration sensors every 5 seconds. Use 1.5 KB per vibration sensor event. "
        "Keep raw sensor data hot for 90 days. Not document search and not RAG."
    )

    model = derive_industrial_iot_pricing_model(profile)
    drivers = derive_pricing_drivers(profile)

    assert model.telemetry.asset_count == 1850
    assert model.telemetry.telemetry_frequency_seconds == 5
    assert model.telemetry.payload_kb == 1.5
    assert model.telemetry.daily_raw_event_volume == 31_968_000
    assert drivers.asset_count == 1850
    assert drivers.telemetry_frequency_seconds == 5
    assert drivers.payload_kb == 1.5


def test_deterministic_understanding_carries_profile_metrics_from_followup_answers():
    raw_use_case = "Monitor regional infrastructure assets with telemetry."
    profile = profile_use_case(
        raw_use_case
        + " Follow-up: monitor 1,850 bridges and tunnels using vibration sensors every 5 seconds. "
        "Use 1.5 KB per vibration sensor event."
    )

    understanding = deterministic_understanding(raw_use_case, profile)
    metric_names = {metric.name for metric in understanding.extracted_metrics}

    assert "explicit_quantity_bridges_1" in metric_names
    assert "telemetry_frequency_seconds" in metric_names
    assert any(metric.unit == "kb_per_vibration_sensor_event" for metric in understanding.extracted_metrics)


def test_profile_reconciliation_makes_exclusions_win_without_dropping_source_facts():
    profile = UseCaseProfile(
        domain="novel_operations",
        workload_families=["industrial_iot_streaming_ml", "rag_assistant"],
        excluded_families=["rag_assistant"],
        capabilities=["real_time_ingestion", "rag_retrieval", "document_retrieval"],
        entities=["inspection_packet_pdf", "remote_asset"],
        signals=["thermal_image", "pdf_packet"],
        actions=["inspect_asset"],
        excluded_patterns=["rag_assistant"],
    )

    reconciled = reconcile_profile_constraints(profile)

    assert "rag_assistant" not in reconciled.workload_families
    assert not (set(reconciled.workload_families) & set(reconciled.excluded_families))
    assert "rag_retrieval" not in reconciled.capabilities
    assert "document_retrieval" not in reconciled.capabilities
    assert "inspection_packet_pdf" in reconciled.entities
    assert "pdf_packet" in reconciled.signals
    assert reconciled.discovery_plan["profile_reconciliation"]["rule"] == "exclusion_wins"


def test_profile_domain_detection_ignores_negated_domain_and_document_markers():
    profile = profile_use_case(
        "Vertical farming telemetry for greenhouse sensors and images. "
        "This is not legal, not document search, not RAG, and not a chatbot."
    )

    assert profile.domain != "legal"
    assert "rag_assistant" in profile.excluded_families
    assert "document_intelligence" in profile.excluded_families
    assert "document_retrieval" not in profile.capabilities


def test_work_order_context_does_not_become_retail_order_management():
    text = (
        "Railway bridge monitoring predicts fatigue risk and requires human engineer "
        "approval before any work order is created. Not retail and not inventory optimization."
    )
    profile = profile_use_case(text)

    assert profile.domain != "retail"
    assert _detect_industry(text) != "retail"
    assert all(source.name != "Order management system" for source in _data_sources(text, False, profile))


def test_negated_commerce_marker_does_not_create_order_management_source():
    text = (
        "Monitor production lines with conveyor cameras and sensor telemetry. "
        "QA staff approve uncertain classifications before labels are applied. "
        "Not retail, not commerce, not customer order, and not order fulfillment."
    )
    profile = profile_use_case(text)

    assert all(source.name != "Order management system" for source in _data_sources(text, False, profile))


def test_excluded_family_validator_allows_source_notes_and_work_order_approval():
    spec = ArchitectureSpec(
        session_id="sess_d25_validator",
        mode="poc",
        title="POC rail monitoring architecture",
        summary="Monitor bridges with vibration events, acoustic clips, inspection notes, and human approval before work orders.",
        selected_services=[
            AWSServiceRecommendation(
                service="AWS IoT Core",
                purpose="Ingest vibration sensor events and gateway acoustic clip metadata.",
                rationale="Selected for telemetry ingestion; inspection notes remain a source fact, not document extraction.",
            ),
            AWSServiceRecommendation(
                service="AWS Step Functions",
                purpose="Coordinate human approval before work order creation.",
                rationale="Selected for governed approval workflow without field-service dispatch automation.",
            ),
        ],
        components=[
            ArchitectureComponent(id="iot", name="Telemetry ingestion", service="AWS IoT Core"),
            ArchitectureComponent(id="workflow", name="Engineer approval workflow", service="AWS Step Functions"),
        ],
        flows=[ArchitectureFlow(id="approve", source="iot", target="workflow", label="Risk event approval")],
        security_controls=[SecurityControl(name="KMS encryption", rationale="Encrypt telemetry and evidence data.")],
        observability_controls=[ObservabilityControl(name="CloudWatch logs", rationale="Trace ingestion and approval failures.")],
        scaling_strategy="Scale managed ingestion by telemetry volume.",
        resilience_strategy="Use managed retry and durable workflow state.",
        cost_optimization_strategy="Bind pricing to telemetry and workflow quantities.",
        assumptions=[],
        risks=[],
        metadata={"excluded_families": ["document_intelligence", "rag_assistant", "field_service_automation"]},
    )

    issues = ArchitectureRevisionService().validate([spec])

    assert not [issue for issue in issues if issue.code == "excluded_workload_family_present"]


def test_open_world_components_do_not_add_document_processing_when_excluded():
    profile = UseCaseProfile(
        domain="novel_operations",
        workload_families=["industrial_iot_streaming_ml"],
        excluded_families=["document_intelligence", "rag_assistant"],
        capabilities=["real_time_ingestion"],
        entities=["inspection_notes", "remote_asset"],
        signals=["vibration_event", "inspection_note"],
        actions=["approve_work_order"],
        excluded_patterns=["document_qa_chatbot"],
    )

    components = _open_world_components(profile, [])

    assert all("textract" not in component.service.lower() for component in components)
    assert all(component.id != "text_document_processing" for component in components)


def test_requirement_coverage_does_not_require_document_path_when_excluded():
    profile = UseCaseProfile(
        domain="novel_operations",
        workload_families=["industrial_iot_streaming_ml"],
        excluded_families=["document_intelligence", "rag_assistant"],
        capabilities=["real_time_ingestion"],
        entities=["inspection_notes", "remote_asset"],
        signals=["inspection_note", "vibration_event"],
        actions=[],
        excluded_patterns=["ocr_document_pipeline"],
    )

    coverage = _requirement_coverage(
        profile,
        [ArchitectureComponent(id="iot", name="Telemetry stream", service="AWS IoT Core")],
        [ArchitectureFlow(id="flow", source="device", target="iot", label="Stream telemetry events")],
        production=False,
    )

    requirement_ids = {item["id"] for item in coverage["requirements"]}
    assert "document_processing_path" not in requirement_ids


def test_pricing_driver_selector_honors_excluded_rag_family_even_with_document_inputs():
    profile = UseCaseProfile(
        domain="novel_operations",
        workload_families=["industrial_iot_streaming_ml"],
        excluded_families=["rag_assistant"],
        capabilities=["document_retrieval", "real_time_ingestion"],
        entities=["inspection_packet_pdf"],
        signals=["thermal_image"],
        actions=["inspect_asset"],
        excluded_patterns=["rag_assistant"],
    )

    selected = select_pricing_driver_family(profile)

    assert selected is not PricingDriverFamily.DOCUMENT_RAG_WORKFLOW


def test_export_live_agent_calls_carries_prior_open_world_bedrock_audit():
    payload = {
        "open_world_understanding": {
            "live_call": {
                "provider": "bedrock",
                "model_id": "us.amazon.nova-pro-v1:0",
                "task_type": LLMTaskType.open_world_understanding.value,
                "lane": "open_world_understanding",
                "status": "accepted",
                "validated": True,
                "prompt_hash": "sha256:prompt",
                "response_hash": "sha256:response",
                "duration_ms": 3210,
            }
        }
    }

    audits = _prior_live_call_audits(payload, payload)

    assert len(audits) == 1
    assert audits[0].provider == "bedrock"
    assert audits[0].lane == "open_world_understanding"


def test_export_live_agent_call_collector_finds_nested_profile_trace():
    brief = {
        "use_case_profile": {
            "open_world_understanding": {
                "trace": {
                    "live_call": {
                        "provider": "bedrock",
                        "model_id": "us.amazon.nova-pro-v1:0",
                        "task_type": LLMTaskType.open_world_understanding.value,
                        "lane": "open_world_understanding",
                        "status": "accepted",
                        "validated": True,
                        "prompt_hash": "sha256:prompt",
                        "response_hash": "sha256:response",
                    }
                }
            }
        }
    }

    audits = _prior_live_call_audits(brief)

    assert len(audits) == 1
    assert audits[0].provider == "bedrock"


def test_export_live_agent_calls_include_bedrock_llm_telemetry():
    telemetry = SimpleNamespace(model_dump=lambda mode="json": {
        "call_id": "llm_test123",
        "session_id": "sess_test",
        "task_type": LLMTaskType.deep_use_case_understanding.value,
        "provider": "bedrock",
        "model_id": "us.amazon.nova-pro-v1:0",
        "started_at": "2026-06-17T00:00:00Z",
        "completed_at": "2026-06-17T00:00:03Z",
        "duration_ms": 3000,
        "input_tokens": 100,
        "output_tokens": 50,
        "schema_validated": True,
        "retry_count": 1,
        "status": "succeeded",
        "schema_name": "DeepUseCaseUnderstanding",
        "prompt_hash": "sha256:prompt",
        "warnings": [],
    })

    audits = _llm_telemetry_live_audits([telemetry])

    assert len(audits) == 1
    assert audits[0].provider == "bedrock"
    assert audits[0].status == "accepted"
    assert audits[0].lane == "understanding"
    assert audits[0].validated is True
    assert audits[0].token_usage == {"input_tokens": 100, "output_tokens": 50}


def test_client_pack_hides_legacy_range_for_generic_not_estimated_pricing_and_shows_derived_quantities():
    dossier = SimpleNamespace(
        title="Open World Scenario",
        verdict="Proceed as a directional candidate.",
        estimated_monthly_cost_range="$20-$180 per month",
        top_validation_gates=[],
        workload_family=["open_world_candidate"],
        risks=[],
        quality_score=SimpleNamespace(pricing_score=5),
    )
    report = {
        "metadata": {"customer_readiness": {"status": "directional_only"}},
        "citation_coverage": {"coverage_percent": 80, "passed": True},
        "evidence_items": [],
        "recommended_production_direction": "Use governed AWS-native processing with explicit validation gates.",
    }
    pricing = {
        "region": "us-east-1",
        "main_cost_drivers": [],
        "metadata": {
            "pricing_can_be_displayed_as_headline": False,
            "source_truth_pricing_compiler": {"mode": "generic_not_estimated"},
            "pricing_driver_closure": {"procurement_ready": False, "missing_drivers": []},
            "pricing_ledger": {"summary": {"headline_safe": False, "procurement_ready": False}},
            "service_usage_dimensions": [{
                "service_name": "Amazon S3",
                "usage_name": "derived evidence/data retention",
                "unit": "GB-month",
                "quantity": "632812.5",
                "formula": "monthly_base_volume * images_per_item * mb_per_image / 1024 * retention_months",
            }],
        },
    }

    client = client_pack_files(
        session_name="Open World Scenario",
        brief={"title": "Open World Scenario", "refined_problem_statement": "Assess unfamiliar assets."},
        report=report,
        pricing=pricing,
        architectures=[],
        diagrams=[],
        deep_dossier=dossier,
        decision_records=[],
    )

    pricing_summary = client["04-pricing-summary.md"]
    memo = client["01-executive-memo.md"]
    assert "$20-$180" not in memo
    assert "intentionally withholds a monthly range" in memo
    assert "$20-$180" not in pricing_summary
    assert "Budget-grade pricing is not available yet" in pricing_summary
    assert "Derived usage quantities to review" in pricing_summary
    assert "632812.5 GB-month" in pricing_summary


def test_client_pack_strips_interview_scaffolding_and_negation_lists_from_presentation_text():
    dossier = SimpleNamespace(
        title="Open World Scenario",
        verdict="Proceed as a directional candidate.",
        estimated_monthly_cost_range="$20-$180 per month",
        top_validation_gates=[],
        workload_family=["open_world_candidate"],
        risks=[],
        quality_score=SimpleNamespace(pricing_score=5),
    )
    client = client_pack_files(
        session_name="Open World Scenario",
        brief={
            "title": "Open World Scenario",
            "industry": "infrastructure",
            "refined_problem_statement": (
                "Monitor assets with telemetry. Not legal, not document search, not RAG, not chatbot. "
                "Synthesis interview note: What payload? Answer: Use 1.5 KB per event."
            ),
            "assumptions": [{
                "text": "Interview answer for 'What payload?': Use 1.5 KB per event.",
                "impact": "pricing",
                "confidence": "high",
            }],
        },
        report={"metadata": {"customer_readiness": {"status": "directional_only"}}, "evidence_items": []},
        pricing={"metadata": {"pricing_can_be_displayed_as_headline": False, "source_truth_pricing_compiler": {"mode": "generic_not_estimated"}}},
        architectures=[{
            "mode": "poc",
            "summary": "Monitor assets. Not legal, not document search, not RAG.",
            "selected_services": [],
            "metadata": {"workload_context": {
                "problem": "Monitor assets. Not legal, not document search, not RAG. Synthesis interview note: Why? Answer: Because."
            }},
        }],
        diagrams=[],
        deep_dossier=dossier,
        decision_records=[],
    )

    combined = "\n".join(client.values())

    assert "Synthesis interview note:" not in combined
    assert "not legal, not document search" not in combined.lower()
    assert "Customer clarified: Use 1.5 KB per event" in combined


def test_root_pricing_markdown_hides_directional_range_when_headline_display_is_blocked():
    pricing = {
        "region": "us-east-1",
        "low_monthly_usd": 20,
        "expected_monthly_usd": 60,
        "high_monthly_usd": 180,
        "main_cost_drivers": [],
        "metadata": {
            "pricing_can_be_displayed_as_headline": False,
            "pricing_driver_closure": {"directional_scenario_allowed": True},
        },
    }

    markdown = ExportPackageService()._pricing_markdown(pricing)

    assert "$20" not in markdown
    assert "$180" not in markdown
    assert "Headline-safe pricing: No" in markdown


def test_root_solution_brief_strips_interview_scaffolding_and_negation_lists():
    markdown = ExportPackageService()._brief_markdown({
        "title": "Open World Scenario",
        "refined_problem_statement": (
            "Monitor assets with telemetry. Not legal, not document search, not RAG, not chatbot. "
            "Synthesis interview note: What payload? Answer: Use 1.5 KB per event."
        ),
        "industry": "infrastructure",
        "poc_scope": "Validate telemetry ingestion.",
        "production_scope": "Operate governed telemetry ingestion.",
        "assumptions": [{
            "text": "Interview answer for 'What payload?': Use 1.5 KB per event.",
            "impact": "pricing",
            "confidence": "high",
        }],
        "open_questions": [{
            "text": "Not legal, not document search, not RAG. What retention is required?",
        }],
    })

    assert "Synthesis interview note:" not in markdown
    assert "not legal, not document search" not in markdown.lower()
    assert "Customer clarified: Use 1.5 KB per event" in markdown


def test_root_research_markdown_strips_interview_scaffolding_and_negation_lists():
    markdown = ExportPackageService()._research_markdown({
        "executive_verdict": "Proceed. Not legal, not document search, not RAG.",
        "citation_coverage": {},
        "metadata": {
            "research_quality": {"label": "Mixed", "reason": "Synthesis interview note: Why? Answer: Because."},
            "evidence_quality": {},
            "customer_readiness": {"status": "directional_only", "warnings": ["Interview answer for 'scale?': 100 assets."]},
            "service_validation_notes": [],
            "service_decision_records": [],
        },
        "facts": [{"text": "Interview answer for 'payload?': 1 KB per event.", "evidence_ids": []}],
        "recommendations": [],
        "uncertainties": [{"text": "Not retail, not chatbot, not legal.", "citation_status": "gap"}],
        "feasibility_analysis": "Feasible. Not retail, not chatbot, not legal.",
        "viability_analysis": "Synthesis interview note: What? Answer: yes.",
        "competitor_analysis": "Interview answer for 'competitor?': none.",
    })

    assert "Synthesis interview note:" not in markdown
    assert "Interview answer for" not in markdown
    assert "not retail, not chatbot" not in markdown.lower()
    assert "Customer clarified: 1 KB per event" in markdown


def test_compiler_catalog_canonicalizes_slugged_aws_step_functions_alias():
    adapter = DiagramCompilerAdapter()
    adapter._ensure_import_path()
    from archway_diagram_compiler.aws_provider import AwsProviderCatalog

    info = AwsProviderCatalog().get_service_info("aws_step_functions")

    assert info.service == "step_functions"
    assert info.placement_scope == "regional_orchestration"


def test_model_missing_component_findings_drop_when_requirement_coverage_is_already_satisfied():
    spec = SimpleNamespace(metadata={
        "requirement_coverage": {
            "requirements": [
                {"id": "document_processing_path", "status": "covered"},
                {"id": "intermittent_connectivity", "status": "covered"},
            ]
        }
    })
    findings = [
        ArchitectureCritiqueFinding(
            severity="warning",
            category="missing_component",
            issue="No document extraction component is present.",
            why_it_matters="Documents and notes need a text processing path.",
            recommended_fix="Add document processing.",
            auto_repairable=True,
        ),
        ArchitectureCritiqueFinding(
            severity="warning",
            category="missing_flow",
            issue="No offline sync flow is present.",
            why_it_matters="Intermittent connectivity requires edge sync.",
            recommended_fix="Add offline sync.",
            auto_repairable=True,
        ),
        ArchitectureCritiqueFinding(
            severity="warning",
            category="missing_component",
            issue="No unrelated analytics component is present.",
            why_it_matters="A separate analytics use case was not covered.",
            recommended_fix="Add analytics.",
            auto_repairable=True,
        ),
    ]

    remaining = _drop_satisfied_requirement_coverage_findings(findings, spec)

    assert [item.issue for item in remaining] == ["No unrelated analytics component is present."]


def test_convergence_treats_generic_not_estimated_pricing_as_directional_not_internal_only():
    findings = _pricing_findings({
        "metadata": {
            "status": "invalid_placeholder",
            "pricing_can_be_displayed_as_headline": False,
            "source_truth_pricing_compiler": {"mode": "generic_not_estimated"},
            "service_usage_dimensions": [{
                "quantity": "120000",
                "formula": "Derived from confirmed annual/monthly workload volume.",
            }],
        }
    })

    assert {item.code for item in findings} >= {"pricing.not_estimated_with_derived_dimensions"}
    assert not any(item.customer_readiness_impact == "cap_to_internal_only" for item in findings)


def test_convergence_does_not_fail_when_requested_view_is_represented_by_broader_supported_view():
    findings = _diagram_findings([{
        "mode": "production",
        "missing_requested_views": [{
            "view_id": "rag_retrieval_view",
            "reason": "Represented through production architecture view.",
        }],
        "view_rendering_ledger": [{
            "view_id": "rag_retrieval_view",
            "rendered_via_broader_supported_view": True,
        }],
        "qa_reports": [{
            "view_id": "rag_retrieval_view",
            "passed": False,
            "diagnostics": ["requested view not rendered because broader supported view was used"],
        }],
    }])

    assert {item.code for item in findings} == {
        "diagram.requested_view_represented",
        "diagram.qa_view_coverage_only",
    }
    assert all(item.customer_readiness_impact == "none" for item in findings)
