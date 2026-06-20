from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.models.domain import (
    ArchitectureComponent,
    ArchitectureFlow,
    ArchitectureSpec,
    AWSServiceSelection,
    AWSServiceRecommendation,
    ObservabilityControl,
    PricingAnalysis,
    PricingLineItem,
    SecurityControl,
)
from app.services.agentic.live_bedrock_harness import LiveRunContext, live_call, reset_live_budget
from app.services.agentic.use_case_analyst import UseCaseAnalystProposal
from app.services.architecture import ArchitecturePlanner
from app.services.architecture_critique import ArchitectureCritique, ArchitectureCritiqueFinding, ArchitectureCritiqueService, _downgrade_unconfirmed_model_criticals
from app.services.architecture_revisions import ArchitectureRevisionService
from app.services.convergence.golden_convergence_orchestrator import GoldenConvergenceOrchestrator
from app.services.diagnostic_diagrams import diagnostic_diagram_gallery
from app.services.llm.base import LLMMessage, LLMResult, LLMTaskType
from app.services.pricing import PricingDrivers, PricingEngine, _apply_live_demo_pricing_hardening, derive_pricing_drivers
from app.services.synthesis import SynthesisEngine
from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding, DeepUseCaseUnderstandingService, UnderstandingMetric, deterministic_understanding
from app.services.use_case_profile import profile_from_metadata, profile_use_case
from app.domain.quality_findings import finding


AQUACULTURE_USE_CASE = """
Build an AWS platform for an offshore aquaculture operator with 6 sea cages,
24 underwater cameras, dissolved oxygen sensors, temperature sensors, and feeding
events. The system should detect fish stress and abnormal behavior from camera
streams and telemetry every 30 seconds, alert 40 staff users, retain scored events
for a year, and support intermittent connectivity between cages and shore.
"""


WILDFIRE_USE_CASE = """
Build an AWS wildfire early-warning platform for a county that has 12 camera towers,
satellite imagery refresh every 10 minutes, weather feeds, and 200,000 residents
who may receive alerts. It should detect smoke plumes, route high-confidence
events to a human incident commander before public alerts, and keep towers working
when remote connectivity is intermittent.
"""


AIRPORT_BAGGAGE_USE_CASE = """
Build an AWS platform for an airport operations team that predicts baggage
disruptions and recommends recovery actions across 3 terminals. The platform
ingests 250,000 bag scan events per day, flight schedule changes, belt telemetry,
and transfer-window signals. It must detect at-risk bags within 2 minutes, notify
airline service teams and passengers when appropriate, retain predictions and
audit traces for 90 days, and tolerate intermittent terminal network connectivity.
This is not a document RAG system, not field-service dispatch, and not depot
inventory management.
"""


def test_aquaculture_questions_and_profile_do_not_fall_back_to_document_rag():
    brief = SynthesisEngine().create_initial_brief(AQUACULTURE_USE_CASE)
    profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
    question_text = " ".join([item.text for item in brief.open_questions] + [item.prompt for item in SynthesisEngine().readiness(brief).recommended_minimum_questions]).lower()

    assert "industrial_iot_streaming_ml" in profile.workload_families
    assert "computer_vision_quality_inspection" in profile.workload_families
    assert {"rag_assistant", "document_intelligence"} <= set(profile.excluded_families)
    assert "telemetry" in question_text
    assert "pricing" in question_text
    assert not {"fish_cages", "underwater_cameras", "water_quality_sensors", "farm_staff"} & set(profile.entities)
    assert "recommend_feeding_window" not in profile.actions
    for forbidden in ("contract", "document", "ocr", "rag", "embedding", "vector"):
        assert forbidden not in question_text


def test_latest_export_api_response_includes_usable_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()

    import app.api.routes as routes
    from app.services.artifacts import ArtifactStore

    routes.artifacts = ArtifactStore()
    session_id = "sess_export_paths"
    export_name = "archway-solution-package-sess_export_paths-20260614T000000Z"
    package_dir = routes.artifacts.session_root(session_id) / "exports" / export_name
    package_dir.mkdir(parents=True)
    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "name": export_name,
            "session_id": session_id,
            "included_artifacts": ["README.md", "manifest.json"],
            "warnings": [],
        }),
        encoding="utf-8",
    )
    zip_path = package_dir.parent / f"{export_name}.zip"
    zip_path.write_bytes(b"PK\\x05\\x06" + b"\\x00" * 18)

    latest = routes._latest_export_bundle(session_id)

    assert latest is not None
    assert latest["session_id"] == session_id
    assert latest["export_id"] == export_name
    assert Path(latest["package_dir"]).is_dir()
    assert Path(latest["package_path"]).is_dir()
    assert Path(latest["zip_path"]).is_file()
    assert latest["artifact_id"] == f"exports/{export_name}.zip"
    assert latest["manifest_artifact_id"] == f"exports/{export_name}/manifest.json"
    assert latest["download_url"] == f"/api/sessions/{session_id}/artifacts/exports/{export_name}.zip"
    assert latest["export_url"] == latest["download_url"]


@pytest.mark.asyncio
async def test_enhance_brief_preserves_interview_progress_for_live_ui_flow():
    engine = SynthesisEngine()
    brief = engine.create_initial_brief(AQUACULTURE_USE_CASE)
    first_question = engine.next_question(brief)

    response = engine.respond(
        brief,
        "Model all 6 sea cages, 24 underwater cameras, oxygen and temperature streams, and one shore operations center.",
    )
    answered_before = ((response.brief.use_case_profile or {}).get("interview") or {}).get("answered") or []

    enhanced = await engine.enhance_brief(response.brief, session_id="sess_d22_interview")
    answered_after = ((enhanced.use_case_profile or {}).get("interview") or {}).get("answered") or []
    next_question = engine.next_question(enhanced)

    assert first_question is not None
    assert answered_after == answered_before == [first_question.id]
    assert next_question is not None
    assert next_question.id != first_question.id


@pytest.mark.asyncio
async def test_live_understanding_preserves_deterministic_derived_metrics(monkeypatch):
    async def _complete(self, task, messages, response_schema=None, **kwargs):  # noqa: ARG001
        parsed = DeepUseCaseUnderstanding(
            industry="aquaculture",
            domain="aquaculture",
            workload_families=["industrial_iot_streaming_ml"],
            extracted_metrics=[
                UnderstandingMetric(name="underwater_cameras", value=24, unit="count", source_text="24 underwater cameras"),
                UnderstandingMetric(name="fish_cages", value=6, unit="count", source_text="6 sea cages"),
                UnderstandingMetric(name="staff_users", value=40, unit="count", source_text="40 staff users"),
            ],
        )
        return LLMResult(
            provider="bedrock",
            model_id="us.amazon.nova-pro-v1:0",
            text=parsed.model_dump_json(),
            parsed=parsed,
            validated=True,
            duration_ms=10,
        )

    monkeypatch.setattr("app.services.understanding.deep_use_case_understanding.ModelRouter.complete", _complete)

    understanding = await DeepUseCaseUnderstandingService().build(AQUACULTURE_USE_CASE, session_id="sess_understanding_merge")

    metrics = {metric.name: metric for metric in understanding.extracted_metrics}
    assert metrics["underwater_cameras"].value == 24
    assert metrics["fish_cages"].value == 6
    assert metrics["staff_users"].value == 40
    assert metrics["total_monitored_assets"].value == 70
    assert metrics["total_monitored_assets"].derived is True


def test_wildfire_pricing_binds_towers_and_refresh_cadence_not_placeholder():
    profile = profile_use_case(WILDFIRE_USE_CASE)
    drivers = derive_pricing_drivers(profile)

    assert drivers.asset_count == 12
    assert drivers.telemetry_frequency_seconds == 600
    assert drivers.daily_event_volume == 12 * 144
    assert drivers.asset_count != 1000
    assert "field_service_automation" in profile.excluded_families
    assert not {"camera_towers", "satellite_imagery", "road_closure_feeds", "shelters", "emergency_operators"} & set(profile.entities)
    assert "recommend_evacuation_zone" not in profile.actions
    assert "draft_public_alert" not in profile.actions


def test_airport_baggage_profile_respects_explicit_negative_patterns():
    brief = SynthesisEngine().create_initial_brief(AIRPORT_BAGGAGE_USE_CASE)
    profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
    profile_text = json.dumps(brief.model_dump(mode="json")).lower()

    assert "operational_event_prediction_workflow" in profile.workload_families
    assert "industrial_iot_streaming_ml" not in profile.workload_families
    assert "real_time_anomaly_detection" in profile.workload_families
    assert {"industrial_iot_streaming_ml", "rag_assistant", "document_intelligence", "field_service_automation", "supply_chain_optimization"} <= set(profile.excluded_families)
    assert not {"industrial_iot_streaming_ml", "rag_assistant", "document_intelligence", "field_service_automation", "supply_chain_optimization"} & set(profile.workload_families)
    assert not {"document_retrieval", "rag_retrieval", "document_ingestion", "inventory_or_depot_integration"} & set(profile.capabilities + profile.capability_model)
    assert "grounded retrieval and question answering" not in profile_text
    assert "contract and document repository" not in profile_text
    assert "inventory_or_depot_integration" not in profile.capability_model
    assert "depot dispatch" not in profile_text
    assert not {"airport_terminals", "bag_scan_events", "baggage_belts", "flight_schedule_system", "airline_service_teams", "passengers"} & set(profile.entities)
    assert "recommend_baggage_recovery_action" not in profile.actions


def test_airport_baggage_pricing_binds_event_volume_and_retention():
    profile = profile_use_case(AIRPORT_BAGGAGE_USE_CASE)
    drivers = derive_pricing_drivers(profile)

    assert drivers.asset_count == 3
    assert drivers.daily_event_volume == 250_000
    assert drivers.monthly_event_volume == 7_500_000
    assert drivers.hot_retention_days == 90
    assert drivers.cold_retention_months == 3
    assert drivers.pricing_driver_family == "generic_directional"
    assert drivers.asset_count != 1000


@pytest.mark.asyncio
async def test_airport_baggage_pricing_engine_records_confirmed_operational_drivers():
    brief = SynthesisEngine().create_initial_brief(AIRPORT_BAGGAGE_USE_CASE)
    pricing = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(
                service="Amazon Kinesis Data Streams",
                purpose="bag scan event ingestion",
                rationale="pricing regression fixture",
            ),
            AWSServiceSelection(
                service="Amazon SageMaker",
                purpose="baggage disruption risk scoring",
                rationale="pricing regression fixture",
            ),
        ],
    )

    closure = pricing.metadata["pricing_driver_closure"]
    assert pricing.metadata["status"] == "directional_valid_with_extracted_scale"
    assert pricing.metadata["scale_applied"] is True
    assert pricing.metadata["pricing_can_be_displayed_as_headline"] is False
    assert "events_per_day=250000" in closure["confirmed_drivers"]
    assert "terminal_count=3" in closure["confirmed_drivers"]
    assert "retention_days=90" in closure["confirmed_drivers"]
    assert "invalid_extracted_scale_not_applied" not in str(pricing.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_wildfire_pricing_engine_accepts_refresh_cadence_as_edge_telemetry_scale():
    brief = SynthesisEngine().create_initial_brief(WILDFIRE_USE_CASE)
    pricing = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(
                service="AWS IoT Core",
                purpose="tower telemetry ingest",
                rationale="pricing regression fixture",
            ),
            AWSServiceSelection(
                service="Amazon SageMaker",
                purpose="smoke plume inference",
                rationale="pricing regression fixture",
            ),
        ],
    )

    closure = pricing.metadata["pricing_driver_closure"]
    assert pricing.metadata["status"] == "directional_valid_with_extracted_scale"
    assert pricing.metadata["scale_applied"] is True
    assert "invalid_extracted_scale_not_applied" not in str(pricing.model_dump(mode="json"))
    assert "camera_towers=12" in closure["confirmed_drivers"]
    assert "refresh_cadence_minutes=10" in closure["confirmed_drivers"]
    assert closure["procurement_ready"] is False
    assert pricing.metadata["pricing_can_be_displayed_as_headline"] is False


def test_pricing_hardening_surfaces_confirmed_canonical_drivers_in_closure():
    profile = profile_use_case(WILDFIRE_USE_CASE)
    drivers = derive_pricing_drivers(profile)
    pricing = PricingAnalysis(
        region="us-east-1",
        low_monthly_usd=10,
        expected_monthly_usd=20,
        high_monthly_usd=30,
        line_items=[],
        main_cost_drivers=[
            "asset_count=12",
            "telemetry_frequency_seconds=600",
            "daily_event_volume=1728",
        ],
        cost_optimization_recommendations=[],
        unknown_variables=[],
        evidence_items=[],
        metadata={
            "status": "directional_valid_with_extracted_scale",
            "scale_applied": True,
            "pricing_sanity_findings": [
                {
                    "code": "pricing.nonzero_total_without_pricing_ledger",
                    "severity": "critical",
                    "description": "A non-zero directional estimate exists, but no source-truth pricing ledger was produced.",
                    "customer_readiness_impact": "cap_to_internal_only",
                }
            ],
            "pricing_driver_closure": {
                "workload_family": "industrial_iot_streaming",
                "status": "missing_non_critical",
                "pricing_maturity": "pricing_directional_with_assumptions",
                "confirmed_drivers": [],
                "assumed_drivers": [],
                "missing_drivers": [],
                "headline_pricing_allowed": False,
                "directional_scenario_allowed": True,
                "procurement_ready": False,
                "recommended_next_action": "ready_for_directional_pricing",
                "next_validation_steps": ["Confirm workload-specific usage quantities."],
            }
        },
    )

    _apply_live_demo_pricing_hardening(pricing, profile, drivers)

    closure = pricing.metadata["pricing_driver_closure"]
    assert "camera_towers=12" in closure["confirmed_drivers"]
    assert "refresh_cadence_minutes=10" in closure["confirmed_drivers"]
    assert closure["procurement_ready"] is False
    assert pricing.metadata["pricing_can_be_displayed_as_headline"] is False
    sanity = pricing.metadata["pricing_sanity_findings"][0]
    assert sanity["code"] == "pricing.nonzero_total_without_pricing_ledger"
    assert sanity["severity"] == "warning"
    assert sanity["customer_readiness_impact"] == "cap_to_directional"


def test_convergence_does_not_turn_warning_level_directional_pricing_into_invalid_placeholder(tmp_path):
    pricing = {
        "metadata": {
            "status": "directional_valid_with_extracted_scale",
            "scale_applied": True,
            "pricing_can_be_displayed_as_headline": False,
            "pricing_scenario_validity": "directional",
        }
    }
    warning = finding(
        code="pricing.nonzero_total_without_pricing_ledger",
        severity="warning",
        category="pricing",
        title="Non-Zero Pricing Without Ledger",
        description="Directional estimate is non-headline until a source-truth pricing ledger exists.",
        evidence=["pricing.metadata.source_truth_pricing_compiler.enabled=false"],
        auto_repairable=True,
        customer_readiness_impact="cap_to_directional",
    )

    GoldenConvergenceOrchestrator()._apply_repairs(
        "sess_directional_pricing",
        tmp_path,
        {"pricing": pricing},
        [warning],
    )

    assert pricing["metadata"]["status"] == "directional_valid_with_extracted_scale"
    assert pricing["metadata"]["pricing_can_be_displayed_as_headline"] is False


def test_pricing_hardening_blocks_excluded_document_driver_leakage():
    profile = profile_use_case(AQUACULTURE_USE_CASE)
    pricing = PricingAnalysis(
        region="us-east-1",
        low_monthly_usd=10,
        expected_monthly_usd=20,
        high_monthly_usd=30,
        line_items=[
            PricingLineItem(
                service="Amazon Bedrock Knowledge Bases",
                unit_basis="RAG query and embedding volume",
                low_monthly_usd=10,
                expected_monthly_usd=20,
                high_monthly_usd=30,
                assumptions=[],
                evidence_ids=[],
            )
        ],
        main_cost_drivers=["document_count=1000", "rag_queries_per_day=250"],
        cost_optimization_recommendations=[],
        unknown_variables=["contract pages", "embedding refresh"],
        evidence_items=[],
        metadata={
            "pricing_driver_closure": {
                "status": "directional",
                "pricing_maturity": "directional",
                "headline_pricing_allowed": True,
                "directional_scenario_allowed": True,
                "procurement_ready": False,
            }
        },
    )
    drivers = _drivers_for_hardening(source="document_rag_workflow_extracted_contract_metrics")

    _apply_live_demo_pricing_hardening(pricing, profile, drivers)

    closure = pricing.metadata["pricing_driver_closure"]
    assert pricing.metadata["pricing_scenario_validity"] == "invalid_driver_mismatch"
    assert pricing.metadata["pricing_can_be_displayed_as_headline"] is False
    assert closure["directional_scenario_allowed"] is False
    assert "Pricing scenario needs repair" in pricing.unknown_variables[-1]


def test_architecture_validation_flags_excluded_workload_family_leakage(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    spec = _spec_with_exclusions(
        excluded=["field_service_automation", "document_intelligence"],
        component_name="Depot dispatch document OCR workflow",
    )

    issues = ArchitectureRevisionService().validate([spec])

    messages = " ".join(issue.message for issue in issues).lower()
    assert any(issue.code == "excluded_workload_family_present" and issue.severity == "critical" for issue in issues)
    assert "field-service" in messages
    assert "document" in messages


def test_diagnostic_diagram_gallery_returns_candidate_artifact_when_compiler_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    spec = _spec_with_exclusions(excluded=["rag_assistant"], component_name="Knowledge retrieval")
    issue = ArchitectureRevisionService().validate([spec])[0]

    galleries = diagnostic_diagram_gallery(session_id="sess_diag", specs=[spec], issues=[issue], reason="critical validation issue")

    assert len(galleries) == 1
    assert galleries[0].qa_reports[0].passed is False
    assert galleries[0].diagrams[0].rendered_as_native_view is False
    assert galleries[0].diagrams[0].format_paths["md"].startswith("diagrams/")


def test_architecture_planner_records_requirement_coverage_for_wildfire():
    brief = SynthesisEngine().create_initial_brief(WILDFIRE_USE_CASE)
    report = _minimal_report(brief)

    specs = ArchitecturePlanner().generate(report)

    coverage = specs[0].metadata["requirement_coverage"]
    labels = {item["label"]: item["status"] for item in coverage["requirements"]}
    assert labels["Computer vision / imagery processing"] == "covered"
    assert labels["Real-time ingestion"] == "covered"
    assert labels["Intermittent connectivity / edge buffering"] == "covered"


def test_aquaculture_architecture_covers_edge_buffering_without_document_false_positive(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    brief = SynthesisEngine().create_initial_brief(AQUACULTURE_USE_CASE)
    report = _minimal_report(brief)

    specs = ArchitecturePlanner().generate(report)
    issues = ArchitectureRevisionService().validate(specs)

    assert all(issue.code != "excluded_workload_family_present" for issue in issues)
    assert all("edge buffering is not explicit" not in issue.message.lower() for issue in issues)
    assert any(component.id == "edge_buffer" for component in specs[1].components)
    assert next(component for component in specs[1].components if component.id == "edge_buffer").scope == "regional_managed_data"
    assert any(flow.source == "edge_buffer" or flow.target == "edge_buffer" for flow in specs[1].flows)


def test_model_only_architecture_critique_cannot_create_critical_blocker():
    model_finding = ArchitectureCritiqueFinding(
        severity="critical",
        category="missing_component",
        issue="The architecture does not include a component for edge buffering.",
        why_it_matters="A live model claimed the component is missing.",
        recommended_fix="Add edge buffering.",
        auto_repairable=False,
    )
    downgraded = _downgrade_unconfirmed_model_criticals([model_finding], deterministic_findings=[])

    assert downgraded[0].severity == "warning"
    assert "audit-only" in downgraded[0].why_it_matters
    assert _downgrade_unconfirmed_model_criticals([model_finding], deterministic_findings=[model_finding])[0].severity == "critical"


@pytest.mark.asyncio
async def test_architecture_critique_timeout_falls_back_without_blocking_user(monkeypatch):
    async def timeout_complete(*_args, **_kwargs):
        raise TimeoutError("simulated live critique timeout")

    monkeypatch.setattr("app.services.architecture_critique.ModelRouter.complete", timeout_complete)
    brief = SynthesisEngine().create_initial_brief(AQUACULTURE_USE_CASE)
    report = _minimal_report(brief)
    spec = ArchitecturePlanner().generate(report)[0]
    understanding = deterministic_understanding(report.use_case_interpretation)

    critique = await ArchitectureCritiqueService().critique(
        report.use_case_interpretation,
        understanding,
        spec,
        report.pricing_analysis,
        session_id="test_timeout_fallback",
    )

    assert critique.enhancement_status == "deterministic_fallback:TimeoutError"
    assert isinstance(critique.passed, bool)


@pytest.mark.asyncio
async def test_architecture_critique_uses_live_sized_timeout_budget(monkeypatch):
    observed: dict[str, int] = {}

    async def complete_with_budget(*_args, **kwargs):
        observed["timeout_seconds"] = kwargs.get("timeout_seconds")
        parsed = ArchitectureCritique(passed=True, findings=[])
        return LLMResult(
            provider="bedrock",
            model_id="test-model",
            text=parsed.model_dump_json(),
            parsed=parsed,
            validated=True,
        )

    monkeypatch.setattr("app.services.architecture_critique.ModelRouter.complete", complete_with_budget)
    brief = SynthesisEngine().create_initial_brief(AQUACULTURE_USE_CASE)
    report = _minimal_report(brief)
    spec = ArchitecturePlanner().generate(report)[0]
    understanding = deterministic_understanding(report.use_case_interpretation)

    critique = await ArchitectureCritiqueService().critique(
        report.use_case_interpretation,
        understanding,
        spec,
        report.pricing_analysis,
        session_id="test_timeout_budget",
    )

    assert observed["timeout_seconds"] >= 30
    assert critique.enhancement_status == "bedrock_validated"


def test_live_call_repairs_malformed_structured_output(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_AGENTIC_MODE", "live_demo")
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("ARCHWAY_BEDROCK_MODEL_ID", "anthropic.test-model")
    monkeypatch.setenv("ARCHWAY_AGENTIC_MAX_BEDROCK_CALLS", "2")
    monkeypatch.setenv("ARCHWAY_AGENTIC_SCHEMA_REPAIR_RETRIES", "1")
    get_settings.cache_clear()
    reset_live_budget("sess_repair")
    calls: list[str] = []

    async def _complete(self, task, messages, response_schema=None, **kwargs):  # noqa: ARG001
        calls.append(task.name)
        if len(calls) == 1:
            return LLMResult(
                provider="bedrock",
                model_id="anthropic.test-model",
                text='{"not": "the expected schema"}',
                parsed=None,
                validated=False,
                duration_ms=5,
                retry_count=0,
                token_usage={"input_tokens": 10, "output_tokens": 4},
            )
        parsed = UseCaseAnalystProposal(
            proposal_id="repaired",
            domain_candidates=[],
            workload_family_candidates=[],
            follow_up_questions=["Confirm scale."],
            input_hash="sha256:in",
            output_hash="sha256:out",
        )
        return LLMResult(
            provider="bedrock",
            model_id="anthropic.test-model",
            text=parsed.model_dump_json(),
            parsed=parsed,
            validated=True,
            duration_ms=6,
            retry_count=0,
            token_usage={"input_tokens": 20, "output_tokens": 8},
        )

    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _complete)

    result = live_call(
        LLMTaskType.live_use_case_analyst,
        [LLMMessage(role="user", content="Build a workflow app.")],
        UseCaseAnalystProposal,
        session_id="sess_repair",
        lane="use_case_analyst",
        run_context=LiveRunContext(session_id="sess_repair", canonical_fact_snapshot_hash="sha256:facts"),
    )

    assert result.audit.status == "accepted"
    assert result.audit.repair_attempted is True
    assert result.audit.repair_count == 1
    assert result.audit.original_response_hash
    assert result.audit.repaired_response_hash
    assert result.audit.canonical_fact_snapshot_hash_used == "sha256:facts"
    assert calls == ["use_case_analyst", "use_case_analyst_schema_repair"]
    assert isinstance(result.parsed, UseCaseAnalystProposal)


def _drivers_for_hardening(*, source: str) -> PricingDrivers:
    return PricingDrivers(
        asset_count=1000,
        telemetry_frequency_seconds=60,
        payload_kb=1.0,
        daily_event_volume=1000,
        monthly_event_volume=30_000,
        stream_retention_hours=24,
        hot_retention_days=30,
        cold_retention_months=12,
        flink_kpu_hours=720,
        feature_windows_per_day=1000,
        inference_events_per_day=1000,
        sagemaker_endpoint_hours=720,
        candidate_anomalies_per_day=10,
        confirmed_incidents_per_day=1,
        workflow_executions_per_day=1,
        state_transitions_per_execution=8,
        integration_api_calls_per_day=1,
        notification_events_per_day=10,
        scoring_strategy="test",
        source=source,
        pricing_driver_family="document_rag_workflow",
    )


def _spec_with_exclusions(*, excluded: list[str], component_name: str) -> ArchitectureSpec:
    return ArchitectureSpec(
        session_id="sess_arch",
        mode="poc",
        title="POC test architecture",
        summary="Test architecture",
        selected_services=[
            AWSServiceRecommendation(
                service="Amazon Textract",
                purpose="Document OCR and depot dispatch support",
                rationale="Document processing and field service dispatch.",
            )
        ],
        components=[
            ArchitectureComponent(id="api", name="API", service="Amazon API Gateway"),
            ArchitectureComponent(id="leak", name=component_name, service="Amazon Textract"),
        ],
        flows=[ArchitectureFlow(id="read", source="api", target="leak", label="Read lookup")],
        security_controls=[SecurityControl(name="KMS encryption", rationale="Protect data.")],
        observability_controls=[ObservabilityControl(name="CloudWatch logs", rationale="Audit failures.")],
        scaling_strategy="Scale by workload.",
        resilience_strategy="Use managed retry.",
        cost_optimization_strategy="Measure usage.",
        assumptions=[],
        risks=[],
        metadata={"excluded_families": excluded},
    )


def _minimal_report(brief):
    from app.models.domain import ResearchReport

    return ResearchReport(
        session_id="sess_report",
        executive_verdict="Proceed with a scoped candidate.",
        proceed_recommendation="proceed",
        use_case_interpretation=brief.refined_problem_statement,
        feasibility_analysis="Feasible with validation.",
        viability_analysis="Viable with assumptions.",
        competitor_analysis="Not assessed.",
        recommended_poc="Build a focused POC.",
        recommended_production_direction="Use governed production controls.",
        pricing_analysis=PricingAnalysis(
            region="us-east-1",
            low_monthly_usd=0,
            expected_monthly_usd=0,
            high_monthly_usd=0,
            line_items=[],
            main_cost_drivers=[],
            cost_optimization_recommendations=[],
            unknown_variables=[],
            evidence_items=[],
        ),
        aws_service_recommendations=[
            AWSServiceRecommendation(service="AWS IoT Core", purpose="Telemetry ingestion", rationale="Ingest field telemetry."),
            AWSServiceRecommendation(service="Amazon Kinesis", purpose="Streaming", rationale="Buffer streams."),
            AWSServiceRecommendation(service="Amazon SageMaker", purpose="Computer vision inference", rationale="Run imagery models."),
        ],
        risks=[],
        assumptions=brief.assumptions,
        evidence_items=[],
        evidence_assessments=[],
        facts=[],
        recommendations=[],
        uncertainties=[],
        metadata={"use_case_profile": brief.use_case_profile},
    )
