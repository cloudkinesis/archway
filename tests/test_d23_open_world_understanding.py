from __future__ import annotations

from app.core.config import get_settings
from app.models.domain import OpenQuestion
from app.services.agentic.live_audit import BudgetState, LiveCallAudit, LiveCallResult
from app.services.llm.base import LLMTaskType
from app.services.open_world_eval import _contains_unnegated_term, d23_eval_scenarios, run_fixture_eval
from app.services.open_world_eval import fixture_understanding_for_scenario, run_live_eval
from app.services.open_world_understanding import (
    CanonicalCandidate,
    CanonicalQuestion,
    CanonicalWorkloadUnderstanding,
    build_result_from_understanding,
    classify_aws_service,
    extract_source_facts,
    extract_source_terms,
    validate_exclusions,
    validate_fact_preservation,
)
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import UseCaseProfile, refine_profile_with_context


AIRPORT_USE_CASE = (
    "Build a system for an airport with 4 terminals and 80 baggage belts that predicts missed "
    "connections from bag scans and flight schedule changes within 2 minutes. It must alert airline "
    "service teams and passengers, but it is not a RAG chatbot and not a depot inventory system."
)


def _airport_understanding() -> CanonicalWorkloadUnderstanding:
    facts = extract_source_facts(AIRPORT_USE_CASE)
    return CanonicalWorkloadUnderstanding(
        domain_candidates=[CanonicalCandidate(label="airport baggage operations", confidence="high")],
        workload_intent="Predict airport baggage missed-connection risk and coordinate recovery actions.",
        actors=[
            CanonicalCandidate(label="airline service teams", source_text="airline service teams", confidence="high"),
            CanonicalCandidate(label="passengers", source_text="passengers", confidence="high"),
        ],
        source_systems=[
            CanonicalCandidate(label="bag scan events", source_text="bag scans", confidence="high"),
            CanonicalCandidate(label="flight schedule changes", source_text="flight schedule changes", confidence="high"),
        ],
        events_signals=[
            CanonicalCandidate(label="bag scans", source_text="bag scans", confidence="high"),
            CanonicalCandidate(label="flight schedule changes", source_text="flight schedule changes", confidence="high"),
        ],
        data_classes=[CanonicalCandidate(label="baggage event data", confidence="medium")],
        actions_workflows=[
            CanonicalCandidate(label="alert airline service teams", source_text="alert airline service teams", confidence="high"),
            CanonicalCandidate(label="notify passengers", source_text="passengers", confidence="medium"),
        ],
        constraints=[CanonicalCandidate(label="human approval for passenger-impacting actions", confidence="medium")],
        scale_metrics=[fact for fact in facts if fact.kind == "metric"],
        latency_slos=[fact for fact in facts if "2 minutes" in fact.source_text],
        exclusions=[fact for fact in facts if fact.kind == "explicit_exclusion"],
        risks_unknowns=["Exact passenger notification policy is not confirmed."],
        candidate_aws_capabilities=[
            CanonicalCandidate(label="streaming", confidence="medium"),
            CanonicalCandidate(label="workflow", confidence="medium"),
            CanonicalCandidate(label="observability", confidence="medium"),
        ],
        candidate_aws_services=[
            CanonicalCandidate(label="Amazon S3", confidence="medium"),
            CanonicalCandidate(label="Amazon EventBridge", confidence="medium"),
        ],
        missing_questions=[
            CanonicalQuestion(
                question="How many bag scan events per day and passenger notifications per month should Archway assume?",
                why_it_matters="These quantities drive ingestion, workflow, notification, and pricing assumptions.",
                impact="pricing",
            ),
            CanonicalQuestion(
                question="Which passenger-impacting actions require human approval?",
                why_it_matters="This sets the governance boundary for automated recovery actions.",
                impact="security",
            ),
        ],
        confidence="medium",
    )


def test_extract_source_facts_preserves_numbers_and_exclusions():
    facts = extract_source_facts(AIRPORT_USE_CASE)
    raw_facts = {fact.source_text.lower() for fact in facts}

    assert any("4 terminals" in raw for raw in raw_facts)
    assert any("80 baggage belts" in raw for raw in raw_facts)
    assert any("2 minutes" in raw for raw in raw_facts)
    assert any(fact.kind == "explicit_exclusion" and "rag chatbot" in fact.source_text.lower() for fact in facts)
    assert any(fact.kind == "explicit_exclusion" and "depot inventory" in fact.source_text.lower() for fact in facts)


def test_extract_source_terms_captures_domain_specific_phrases_without_domain_rules():
    terms = extract_source_terms(
        "Predict engine failures for 70 cargo vessels from vibration, fuel quality, maintenance logs, "
        "and sea state. Connectivity is intermittent and alerts go to fleet engineers."
    )

    assert "predict engine failures" in terms
    assert "70 cargo vessels" in terms
    assert "vibration" in terms
    assert "fuel quality" in terms
    assert "maintenance logs" in terms
    assert "fleet engineers" in terms


def test_validator_rejects_dropped_metric_and_reintroduced_exclusion():
    facts = extract_source_facts(AIRPORT_USE_CASE)
    understanding = _airport_understanding()
    understanding.scale_metrics = [fact for fact in understanding.scale_metrics if "80 baggage belts" not in fact.source_text]
    fact_issues = validate_fact_preservation(facts, understanding)

    understanding.actions_workflows.append(CanonicalCandidate(label="RAG chatbot answer workflow", confidence="medium"))
    exclusion_issues = validate_exclusions(facts, understanding)

    assert any(issue.code == "open_world_understanding.fact_not_preserved" for issue in fact_issues)
    assert any(issue.code == "open_world_understanding.exclusion_violated" for issue in exclusion_issues)


def test_build_result_repairs_missing_source_facts_before_accepting():
    understanding = _airport_understanding()
    understanding.scale_metrics = [fact for fact in understanding.scale_metrics if "80 baggage belts" not in fact.source_text]

    result = build_result_from_understanding(AIRPORT_USE_CASE, understanding)

    assert result.trace.accepted
    assert any(issue.code == "open_world_understanding.fact_repaired" for issue in result.trace.validation_issues)
    assert any(fact.source_text == "80 baggage belts" for fact in result.trace.understanding.scale_metrics)


def test_build_result_repairs_missing_source_terms_without_domain_rules():
    raw = (
        "Predict engine failures for 70 cargo vessels from vibration, fuel quality, maintenance logs, "
        "and sea state. Connectivity is intermittent and alerts go to fleet engineers."
    )
    understanding = CanonicalWorkloadUnderstanding(
        domain_candidates=[],
        workload_intent="Predict operational failure risk.",
        risks_unknowns=[],
        candidate_aws_services=[],
        missing_questions=[],
    )

    result = build_result_from_understanding(raw, understanding)
    repaired_labels = " ".join(
        item.label
        for item in (
            result.trace.understanding.actors
            + result.trace.understanding.source_systems
            + result.trace.understanding.events_signals
            + result.trace.understanding.actions_workflows
        )
    )

    assert result.trace.accepted
    assert "fleet engineers" in repaired_labels
    assert "vibration" in repaired_labels
    assert any(issue.code == "open_world_understanding.source_term_repaired" for issue in result.trace.validation_issues)


def test_service_validation_is_three_state():
    assert classify_aws_service("Amazon S3").state == "known-real"
    assert classify_aws_service("aws_iot_core").state == "known-real"
    assert classify_aws_service("aws_step_functions").state == "known-real"
    assert classify_aws_service("timestream").state == "known-real"
    assert classify_aws_service("rekognition").state == "known-real"
    assert classify_aws_service("s3").state == "known-real"
    assert classify_aws_service("aws_s3").state == "known-real"
    assert classify_aws_service("future_data_exchange").state == "unknown-unverified"
    assert classify_aws_service("AWS Quantum Unicorn Ledger").state == "unknown-unverified"
    assert classify_aws_service("BaggageAI Magic Router").state == "likely-hallucinated"


def test_forbidden_term_scorer_uses_word_boundaries_and_negation():
    assert not _contains_unnegated_term("Use object storage for the audit archive.", "rag")
    assert not _contains_unnegated_term("This is not a RAG chatbot.", "rag")
    assert not _contains_unnegated_term("constraint:not_rag_chatbot", "rag")
    assert _contains_unnegated_term("The proposal reintroduced RAG retrieval.", "rag")


def test_adapter_generates_open_world_profile_and_questions():
    result = build_result_from_understanding(AIRPORT_USE_CASE, _airport_understanding())

    assert result.profile is not None
    assert result.trace.accepted
    assert result.profile.profile_source == "open_world_understanding"
    assert result.profile.open_world_understanding["trace_hash"].startswith("sha256:")
    assert result.profile.discovery_plan["source"] == "open_world_understanding"
    assert any("bag scan events" in question.text.lower() for question in result.open_questions)
    assert "industrial_iot_streaming_ml" not in result.profile.workload_families


def test_synthesis_uses_live_open_world_understanding_without_seeded_profile(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING", "true")
    monkeypatch.setenv("ARCHWAY_AGENTIC_MODE", "live_demo")
    get_settings.cache_clear()
    captured_prompt = {}

    def fake_live_call(task_type, messages, response_schema, **kwargs):
        captured_prompt["text"] = "\n".join(message.content for message in messages)
        return LiveCallResult(
            audit=LiveCallAudit(
                provider="bedrock",
                model_id="amazon.nova-pro-v1:0",
                task_type=LLMTaskType.open_world_understanding,
                lane="open_world_understanding",
                status="accepted",
                validated=True,
                prompt_hash="sha256:prompt",
                response_hash="sha256:response",
                budget_state=BudgetState(calls_used=1, max_calls=12),
            ),
            parsed=_airport_understanding(),
            text="{}",
        )

    monkeypatch.setattr("app.services.open_world_understanding.live_call", fake_live_call)

    brief = SynthesisEngine().create_initial_brief(AIRPORT_USE_CASE)

    assert brief.use_case_profile["profile_source"] == "open_world_understanding"
    assert "deterministic_profile" not in captured_prompt["text"]
    assert "industrial_iot_streaming_ml" not in captured_prompt["text"]
    assert any("bag scan events" in question.text.lower() for question in brief.open_questions)
    get_settings.cache_clear()


def test_refiners_disabled_guard_skips_domain_specific_refiners(monkeypatch):
    monkeypatch.setenv("ARCHWAY_DISABLE_DOMAIN_REFINERS", "true")
    get_settings.cache_clear()
    profile = UseCaseProfile(
        domain=None,
        workload_families=["web_api_application"],
        excluded_families=[],
        capabilities=[],
        entities=[],
        signals=[],
        actions=[],
    )

    def fail_refiner(*args, **kwargs):
        raise AssertionError("domain refiner should not run")

    monkeypatch.setattr("app.services.use_case_profile._refine_airport_operations_profile", fail_refiner)
    refined = refine_profile_with_context(profile, AIRPORT_USE_CASE)

    assert refined.workload_families == ["web_api_application"]
    get_settings.cache_clear()


def test_d23_eval_battery_is_diverse_and_passes_offline():
    scenarios = d23_eval_scenarios()
    result = run_fixture_eval()

    assert len(scenarios) >= 10
    assert result["scenario_count"] == len(scenarios)
    assert result["failed"] == 0
    assert len({item.domain for item in scenarios}) >= 10


def test_d23_live_eval_path_scores_model_results_without_fixtures(monkeypatch):
    scenarios = d23_eval_scenarios()
    by_text = {scenario.use_case: scenario for scenario in scenarios}

    class FakeOpenWorldUnderstandingService:
        def build(self, raw_use_case: str, *, session_id: str | None = None):
            scenario = by_text[raw_use_case]
            return build_result_from_understanding(
                raw_use_case,
                fixture_understanding_for_scenario(scenario),
                provider="bedrock",
                model_id="amazon.nova-pro-v1:0",
            )

    monkeypatch.setattr("app.services.open_world_eval.OpenWorldUnderstandingService", FakeOpenWorldUnderstandingService)

    result = run_live_eval(session_prefix="test_d23_live")

    assert result["mode"] == "live_bedrock_refiners_disabled"
    assert result["scenario_count"] == len(scenarios)
    assert result["failed"] == 0
    assert {item["provider"] for item in result["results"]} == {"bedrock"}


def test_open_world_questions_are_preserved_through_synthesis_planner():
    understanding = _airport_understanding()
    understanding.missing_questions = [
        CanonicalQuestion(
            question="What SLA applies to passenger notification after a missed connection is predicted?",
            why_it_matters="This controls workflow urgency and notification assumptions.",
            impact="performance",
        )
    ]
    result = build_result_from_understanding(AIRPORT_USE_CASE, understanding)
    assert result.profile is not None
    result.profile.discovery_plan["top_questions"].append({
        "question": "Which recovery action should be approval-gated?",
        "why_it_matters": "This governs action authority.",
        "impact": "security",
        "expected_answer_style": "Policy boundary",
    })

    from app.services.synthesis import _questions_for_profile

    questions: list[OpenQuestion] = _questions_for_profile(result.profile)

    assert [question.text for question in questions[:2]] == [
        "What SLA applies to passenger notification after a missed connection is predicted?",
        "Which recovery action should be approval-gated?",
    ]
