from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding
from app.services.understanding.understanding_validator import UnderstandingValidator
from app.services.research import _brief_validation_context
from app.services.use_case_profile import UseCaseProfile
from app.models.domain import Assumption, UseCaseBrief


def _profile(domain: str | None = None) -> UseCaseProfile:
    return UseCaseProfile(
        domain=domain,
        workload_families=["operational_event_prediction_workflow"],
        excluded_families=[],
        capabilities=[],
        entities=[],
        signals=[],
        actions=[],
        structured_metrics={},
    )


def _understanding(capabilities: list[str], domain: str = "research") -> DeepUseCaseUnderstanding:
    return DeepUseCaseUnderstanding(
        industry=domain,
        domain=domain,
        workload_families=["operational_event_prediction_workflow"],
        capabilities=capabilities,
        extracted_metrics=[],
    )


def test_derived_metric_miss_is_warning_not_readiness_blocker():
    profile = _profile("agriculture")
    profile.structured_metrics = {
        "business_targets": {
            "events_per_day": {"value": 1200, "unit": "events_per_day", "raw": "1,200 events per day", "derived": False},
            "average_eps": {"value": 0.01, "unit": "events_per_second", "raw": "events_per_day / 86400", "derived": True},
        }
    }
    understanding = DeepUseCaseUnderstanding(
        industry="agriculture",
        domain="agriculture",
        workload_families=["operational_event_prediction_workflow"],
        capabilities=[],
        extracted_metrics=[
            {
                "name": "events_per_day",
                "value": 1200,
                "unit": "events_per_day",
                "source_text": "1,200 events per day",
                "confidence": "high",
            }
        ],
    )

    result = UnderstandingValidator().validate(
        "Process 1,200 events per day and alert operators.",
        profile,
        understanding,
    )

    assert result.passed
    assert [(issue.severity, issue.code) for issue in result.issues] == [("warning", "derived_metrics_missed")]


def test_phi_negation_does_not_cap_open_world_understanding_to_internal_only():
    result = UnderstandingValidator().validate(
        "Coordinate field logistics and audit evidence. No real PHI/PII; names should be tokenized.",
        _profile("research"),
        _understanding(["audit_trail", "phi_data"]),
    )

    assert result.passed
    assert [(issue.severity, issue.code) for issue in result.issues] == [("warning", "unsupported_phi")]


def test_model_proposed_phi_without_sensitive_context_still_blocks():
    result = UnderstandingValidator().validate(
        "Coordinate industrial logistics and preserve audit records.",
        _profile("industrial"),
        _understanding(["audit_trail", "phi_data"], domain="industrial"),
    )

    assert not result.passed
    assert [(issue.severity, issue.code) for issue in result.issues] == [("critical", "unsupported_phi")]


def test_healthcare_context_allows_phi_capability():
    result = UnderstandingValidator().validate(
        "Hospital workflow with patient records and HIPAA controls.",
        _profile("healthcare"),
        _understanding(["audit_trail", "phi_data"], domain="healthcare"),
    )

    assert result.passed
    assert result.issues == []


def test_research_validation_context_includes_confirmed_synthesis_answers():
    brief = UseCaseBrief(
        title="Remote operations",
        raw_use_case="Coordinate field logistics and audit records.",
        refined_problem_statement="Coordinate field logistics and audit records.",
        assumptions=[
            Assumption(
                text="No real PHI/PII; crew names should be tokenized.",
                reason="Captured from synthesis interview.",
                impact="security",
                confidence="high",
                user_confirmed=True,
            ),
            Assumption(
                text="Assume sensitive patient data until confirmed.",
                reason="Skipped fallback.",
                impact="security",
                confidence="low",
                user_confirmed=False,
            ),
        ],
    )

    context = _brief_validation_context(brief)

    assert "No real PHI/PII" in context
    assert "Assume sensitive patient data" not in context
