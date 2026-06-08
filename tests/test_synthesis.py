from app.services.synthesis import SynthesisEngine
from tests.test_end_to_end_flow import UTILITY_GRID_USE_CASE


def test_proceed_checkpoint_has_at_most_three_questions():
    engine = SynthesisEngine()
    brief = engine.create_initial_brief("Build a customer assistant for order status and delivery questions.")

    readiness = engine.readiness(brief)

    assert len(readiness.recommended_minimum_questions) <= 3
    assert readiness.assumptions_if_skipped


def test_industry_questions_keep_security_assumptions_visible():
    engine = SynthesisEngine()
    brief = engine.create_initial_brief("Create a healthcare assistant that helps nurses find patient policy information.")

    assert brief.industry == "healthcare"
    assert brief.security_profile.handles_sensitive_data is True
    assert any("HIPAA" in regime for regime in brief.compliance_profile.regimes)


def test_ready_brief_can_proceed_even_with_recommended_questions():
    engine = SynthesisEngine()
    brief = engine.create_initial_brief("Build a retail customer support assistant for order and delivery questions.")

    readiness = engine.readiness(brief)

    assert readiness.can_proceed is True
    assert readiness.recommended_minimum_questions


def test_utility_metrics_and_business_goals_are_structured():
    brief = SynthesisEngine().create_initial_brief(UTILITY_GRID_USE_CASE)
    metrics = {item["label"]: item for item in brief.use_case_profile["metrics"]}

    assert metrics["smart_meters"]["value"] == 200000
    assert metrics["distribution_transformers"]["value"] == 15000
    assert metrics["outage_reduction_target_percent"]["value"] == 45
    assert metrics["current_mttr_hours"]["value"] == 4
    assert metrics["target_mttr_minutes"]["value"] == 90
    assert metrics["target_timeline_months"]["value"] == 18
    assert brief.business_goals == [
        "Reduce unplanned outages by 45%.",
        "Cut MTTR from 4 hours to under 90 minutes.",
        "Achieve measurable improvement within 18 months.",
    ]
