import pytest

from app.services.discovery_planner import DiscoveryPlan, DiscoveryPlannerService, DiscoveryQuestion, DiscoveryCandidate
from app.services.llm.base import LLMResult
from app.services.use_case_profile import UseCaseProfile, profile_use_case


def test_legal_contract_discovery_plan_prefers_document_rag_questions():
    use_case = (
        "AI-assisted legal contract review and obligation-tracking platform with 5,000 historical contracts, "
        "RAG Q&A, clause extraction, obligation tracking, approval workflow, and audit trail."
    )
    profile = profile_use_case(use_case)

    plan = DiscoveryPlannerService().plan_sync(use_case, profile)
    joined_questions = " ".join(item.question for item in plan.top_questions).lower()
    joined_drivers = " ".join(plan.pricing_drivers).lower()

    assert plan.domain_candidates[0].name == "legal"
    assert plan.workload_family_candidates[0].name in {"document_intelligence", "rag_assistant"}
    assert "historical contracts/documents" in joined_questions
    assert "average pages or mb per document" in joined_questions
    assert "rag queries" in joined_questions
    assert "telemetry pricing" not in joined_questions
    assert "payload size" not in joined_questions
    assert "historical_contract_count" in joined_drivers
    assert "rag_queries_per_day" in joined_drivers


def test_true_telemetry_discovery_plan_keeps_telemetry_questions():
    use_case = (
        "A utility company ingests smart meter telemetry every 30 seconds, transformer sensor payloads, and "
        "real-time oscillation signals to detect feeder failures and notify operators."
    )
    profile = profile_use_case(use_case)

    plan = DiscoveryPlannerService().plan_sync(use_case, profile)
    joined_questions = " ".join(item.question for item in plan.top_questions).lower()

    assert "reporting frequency and payload size" in joined_questions
    assert "hot path" in joined_questions
    assert "telemetry" in joined_questions


def test_generic_web_app_discovery_plan_asks_web_scale_not_telemetry():
    use_case = "We need a public web application with API, database, async jobs, observability, and CI/CD."
    profile = profile_use_case(use_case)

    plan = DiscoveryPlannerService().plan_sync(use_case, profile)
    joined_questions = " ".join(item.question for item in plan.top_questions).lower()

    assert plan.ambiguity_detected is False
    assert "active users" in joined_questions
    assert "api requests per day" in joined_questions
    assert "async jobs per day" in joined_questions
    assert "telemetry pricing" not in joined_questions
    assert "payload size" not in joined_questions


def test_low_confidence_plan_asks_clarification():
    profile = UseCaseProfile(
        domain=None,
        workload_families=[],
        excluded_families=[],
        capabilities=[],
        entities=[],
        signals=[],
        actions=[],
        confidence="low",
    )

    plan = DiscoveryPlannerService().plan_sync("We need AI for a new specialist workflow.", profile)

    assert plan.ambiguity_detected is True
    assert plan.top_questions[0].id == "clarify-workload-shape"


@pytest.mark.asyncio
async def test_async_planner_marks_ambiguity_on_llm_disagreement(monkeypatch):
    use_case = (
        "AI-assisted legal contract review and obligation-tracking platform with 5,000 historical contracts, "
        "RAG Q&A, clause extraction, obligation tracking, approval workflow, and audit trail."
    )
    profile = profile_use_case(use_case)

    async def fake_complete(self, task, messages, response_schema=None, temperature=0.2, max_tokens=None, timeout_seconds=None):
        return LLMResult(
            provider="test",
            model_id="fake-discovery",
            text="{}",
            parsed=DiscoveryPlan(
                domain_candidates=[DiscoveryCandidate(name="telecommunications", confidence="medium", rationale="conflict for test")],
                workload_family_candidates=[DiscoveryCandidate(name="telecom_network_analytics", confidence="medium", rationale="conflict for test")],
                confidence="medium",
                top_questions=[
                    DiscoveryQuestion(
                        id="telecom-access",
                        question="What HBase access patterns should Archway preserve before selecting the AWS target store?",
                        why_it_matters="Test disagreement handling.",
                        expected_answer_style="Describe point reads and scans.",
                    )
                ],
            ),
            validated=True,
        )

    monkeypatch.setattr("app.services.discovery_planner.ModelRouter.complete", fake_complete)

    plan = await DiscoveryPlannerService().plan(use_case, profile, session_id="sess_test_discovery")

    assert plan.ambiguity_detected is True
    assert plan.top_questions[0].id == "clarify-domain-shape"
    assert "do not fully agree" in (plan.ambiguity_reason or "").lower()
