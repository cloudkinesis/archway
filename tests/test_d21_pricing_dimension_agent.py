from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.evaluation import ScenarioObservation, run_evaluation_battery, score_scenario
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.agentic.pricing_dimension_agent import (
    DeterministicFixturePricingDimensionProvider,
    LivePricingDimensionProvider,
    PricingDimensionProposal,
    PricingUsageDimensionCandidate,
    build_pricing_dimension_context,
    build_pricing_dimension_trace,
    validate_pricing_dimension_proposal,
)
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine


SERVICE_FIXTURES = [
    ("Amazon Lex", "AmazonLex", "text_requests", ["monthly_text_requests"]),
    ("Amazon Connect", "AmazonConnect", "voice_minutes", ["monthly_voice_minutes"]),
    ("Amazon Bedrock", "AmazonBedrock", "input_tokens", ["monthly_input_tokens", "model_id"]),
    ("AWS Lambda", "AWSLambda", "requests_duration", ["monthly_requests", "average_duration_ms", "memory_mb"]),
    ("Amazon SQS", "AmazonSQS", "requests", ["monthly_queue_requests"]),
    ("Amazon Kinesis", "AmazonKinesis", "shard_hours", ["shard_hours", "put_payload_units"]),
    ("Amazon CloudFront", "AmazonCloudFront", "data_transfer_requests", ["gb_data_transfer_out", "monthly_requests"]),
    ("Amazon Textract", "AmazonTextract", "pages_feature_type", ["monthly_pages", "feature_type"]),
    ("Amazon OpenSearch Serverless", "AmazonOpenSearchServerless", "ocu_storage", ["ocu_hours", "gb_storage"]),
    ("Amazon EKS", "AmazonEKS", "cluster_runtime", ["cluster_hours", "node_runtime_assumption"]),
]


def _fixture_specs():
    specs = []
    for idx, (service, code, usage, drivers) in enumerate(SERVICE_FIXTURES, start=1):
        specs.append({
            "service_name": service,
            "aws_service_code": code,
            "dimension_id": f"dim_{idx}_{usage}",
            "usage_name": usage,
            "unit": "unit",
            "formula": "monthly_driver * unit_rate",
            "required_rate_dimensions": {"region": "us-east-1"},
            "required_customer_drivers": drivers,
            "source_requirement": "aws_pricing",
            "evidence_refs": [f"fixture:{code}"],
            "drivers": [
                {
                    "driver_key": driver,
                    "display_label": driver.replace("_", " "),
                    "unit": "unit",
                    "status": "missing",
                    "source": "model_proposed",
                    "reason": "Fixture-required customer quantity.",
                }
                for driver in drivers
            ],
        })
    specs[0]["drivers"][0]["status"] = "assumed"
    specs[0]["drivers"][0]["source"] = "scenario_profile"
    specs[0]["drivers"][0]["scenario_default"] = 10000
    specs[0]["source_requirement"] = "scenario_profile"
    specs[0]["provenance"] = "scenario_profile"
    specs[0]["scenario_profiles"] = [{
        "profile_id": "small_pilot",
        "label": "Small pilot",
        "assumptions": ["monthly_text_requests=10000"],
        "intended_use": "small_pilot",
    }]
    specs[1]["ambiguity_reason"] = "voice minutes and chat duration both may apply; customer channel mix is unknown."
    specs[2]["evidence_refs"] = []
    specs[9]["aws_service_code"] = None
    specs[9]["source_requirement"] = "unknown"
    specs[9]["ambiguity_reason"] = "cluster/runtime pricing depends on EKS platform and compute mode choices."
    return specs


def test_pricing_dimension_production_module_does_not_embed_service_fixture_names():
    module_text = Path("app/services/agentic/pricing_dimension_agent.py").read_text(encoding="utf-8")

    for service, *_ in SERVICE_FIXTURES:
        assert service not in module_text


def test_pricing_dimension_flag_defaults_false_and_provider_is_not_invoked(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_PRICING", raising=False)
    get_settings.cache_clear()

    class ExplodingProvider:
        provider_name = "explode"

        def propose(self, context):  # pragma: no cover - should never run
            raise AssertionError("provider should not be invoked when disabled")

        def validate(self, proposal, deterministic_context):  # pragma: no cover
            raise AssertionError("provider should not be invoked when disabled")

    trace = build_pricing_dimension_trace(
        settings=get_settings(),
        context={"dimension_fixture_specs": _fixture_specs()},
        provider=ExplodingProvider(),
    )

    assert get_settings().enable_agentic_pricing is False
    assert trace.enabled is False
    assert trace.provider == "disabled"
    assert trace.proposal.usage_dimensions == []
    assert trace.decisions[0].decision == "rejected"


def test_pricing_dimension_fixture_provider_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_PRICING", "true")
    get_settings.cache_clear()
    context = {"dimension_fixture_specs": _fixture_specs()}
    provider = DeterministicFixturePricingDimensionProvider()

    trace = build_pricing_dimension_trace(settings=get_settings(), context=context, provider=provider)
    again = build_pricing_dimension_trace(settings=get_settings(), context=context, provider=provider)

    assert trace.enabled is True
    assert trace.provider == "deterministic_fixture"
    assert trace.input_hash == again.input_hash
    assert trace.output_hash == again.output_hash
    assert trace.proposal.output_hash == again.proposal.output_hash
    assert len(trace.proposal.service_candidates) == 10
    assert len(trace.proposal.usage_dimensions) == 10
    assert [item.service_name for item in trace.proposal.service_candidates] == sorted(item.service_name for item in trace.proposal.service_candidates)


def test_live_pricing_dimension_provider_degrades_without_live_demo():
    provider = LivePricingDimensionProvider()
    proposal = provider.propose({})
    assert provider.last_call is not None
    assert provider.last_call.status == "not_attempted"
    assert proposal.not_estimated_reasons


def test_multi_service_fixture_labels_missing_ambiguous_assumed_and_not_estimated(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_PRICING", "true")
    get_settings.cache_clear()

    trace = build_pricing_dimension_trace(
        settings=get_settings(),
        context={"dimension_fixture_specs": _fixture_specs()},
        provider=DeterministicFixturePricingDimensionProvider(),
    )
    labels = {item.service_name: item.binding_label for item in trace.proposal.usage_dimensions}

    assert labels["Amazon Lex"] == "scenario_assumed"
    assert labels["Amazon Connect"] == "ambiguous"
    assert labels["Amazon Bedrock"] == "unsupported"
    assert labels["AWS Lambda"] == "missing_quantity"
    assert labels["Amazon EKS"] == "not_estimated"
    assert trace.proposal.scenario_profiles[0].source == "scenario_profile"
    assert trace.proposal.ambiguities
    assert trace.proposal.not_estimated_reasons


def test_pricing_dimension_does_not_overwrite_deterministic_bound_pricing():
    context = {
        "service_usage_dimensions": [{"id": "dim_bound", "binding_status": "bound"}],
        "pricing_driver_bindings": [{"driver_name": "monthly_requests", "status": "confirmed"}],
    }
    proposal = PricingDimensionProposal(
        proposal_id="proposal_bound",
        usage_dimensions=[
            PricingUsageDimensionCandidate(
                dimension_id="dim_bound",
                service_name="Fixture Service",
                aws_service_code="FixtureCode",
                usage_name="requests",
                unit="request",
                required_customer_drivers=["monthly_requests"],
                source_requirement="aws_pricing",
                evidence_refs=["fixture:pricing"],
                binding_label="not_estimated",
            )
        ],
        input_hash="sha256:input",
        output_hash="sha256:output",
    )

    trace = validate_pricing_dimension_proposal(proposal, context, provider_name="unit")

    assert trace.proposal.usage_dimensions[0].binding_label == "bound"
    assert trace.proposal.usage_dimensions[0].accepted_status == "accepted"
    assert trace.deterministic_pricing_ref["headline_safe"] is False
    assert trace.decisions[0].decision == "downgraded"


def test_generic_fallback_is_not_treated_as_bound_or_authoritative():
    proposal = PricingDimensionProposal(
        proposal_id="proposal_unknown",
        usage_dimensions=[
            PricingUsageDimensionCandidate(
                dimension_id="dim_unknown",
                service_name="Unknown Fixture Service",
                usage_name="generic_monthly_band",
                source_requirement="unknown",
                provenance="model_proposed",
            )
        ],
        input_hash="sha256:input",
        output_hash="sha256:output",
    )

    trace = validate_pricing_dimension_proposal(proposal, {}, provider_name="unit")

    assert trace.proposal.usage_dimensions[0].binding_label == "not_estimated"
    assert trace.proposal.usage_dimensions[0].accepted_status == "downgraded"
    assert trace.proposal.usage_dimensions[0].binding_label != "bound"


def test_pricing_dimension_context_uses_existing_signals_only():
    pricing = {
        "metadata": {
            "pricing_can_be_displayed_as_headline": True,
            "pricing_driver_closure": {"missing_drivers": ["monthly_requests"]},
            "service_usage_dimensions": [{"id": "dim_existing", "binding_status": "bound"}],
            "pricing_driver_bindings": [{"driver_name": "monthly_requests", "status": "confirmed"}],
        },
        "expected_monthly_usd": 123,
    }
    architectures = [{"components": [{"service": "Fixture Compute"}]}]

    context = build_pricing_dimension_context(pricing=pricing, architectures=architectures, fixture_specs=_fixture_specs())

    assert context["services"] == ["Fixture Compute"]
    assert context["pricing"]["headline_safe"] is True
    assert context["pricing"]["expected_monthly_usd"] == 123
    assert context["pricing_driver_closure"]["missing_drivers"] == ["monthly_requests"]
    assert context["service_usage_dimensions"][0]["id"] == "dim_existing"


def test_export_emits_pricing_dimension_trace_raw_and_audit_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_PRICING", raising=False)
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = store.create("Build a retail assistant for order questions.", brief)
    service = ExportPackageService()

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)
    export_dir = service.artifacts.session_root(session.id) / "exports" / bundle.name

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        trace = json.loads(archive.read("raw/agent_pricing_dimension_trace.json").decode("utf-8"))
        proposal = json.loads(archive.read("raw/agent_pricing_dimension_proposal.json").decode("utf-8"))

    assert "raw/agent_pricing_dimension_trace.json" in names
    assert "raw/agent_pricing_dimension_proposal.json" in names
    assert "audit_pack/agentic-pricing-dimensions.md" in names
    assert "client_pack/agentic-pricing-dimensions.md" not in names
    assert trace["enabled"] is False
    assert trace["provider"] == "disabled"
    assert proposal["usage_dimensions"] == []

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "raw/agent_pricing_dimension_trace.json" in inventory_paths

    (export_dir / "raw/agent_pricing_dimension_trace.json").write_text("[]\n", encoding="utf-8")
    from tests.test_d21_agentic_foundation import _load_verifier

    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_pricing_dimension_trace.json" in error for error in errors)


def test_evaluation_battery_scores_pricing_dimension_lane_safety():
    scenario = thin_evaluation_scenarios()[0]
    observation = ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=True,
        pricing_labels=["scenario_assumed"],
        diagram_fallback_recorded=True,
        repair_actions=["Ask for volume"],
        pricing_dimension_multi_service_coverage=False,
        pricing_dimension_source_kind_correct=False,
        pricing_dimension_missing_quantities_labeled=False,
        pricing_dimension_scenario_assumptions_labeled=False,
        pricing_dimension_ambiguities_labeled=False,
        pricing_dimension_no_silent_generic_fallback=False,
        pricing_dimension_trace_hash_present=False,
        pricing_dimension_no_deterministic_overwrite=False,
        pricing_dimension_no_readiness_promotion=False,
        pricing_dimension_no_client_surface=False,
    )

    metrics, findings = score_scenario(scenario, observation)
    failed = {metric.metric_id.rsplit(".", 1)[1] for metric in metrics if not metric.passed and metric.score_type == "auto"}

    assert "pricing_dimension_multi_service_coverage" in failed
    assert "pricing_dimension_no_silent_fallback" in failed
    assert "pricing_dimension_missing_quantity" in failed
    assert "pricing_dimension_no_deterministic_overwrite" in failed
    assert any(finding.lane == "pricing_dimension" and finding.severity == "critical" for finding in findings)
    result = run_evaluation_battery([scenario])
    score = next(item for item in result.lane_scores if item.lane == "pricing_dimension")
    assert score.score_type == "auto"
    assert score.confidence_label == "auto_passed"
