"""Regression tests for deterministic dossier prose quality (rows 1-8).

Covers: title generation, heading hierarchy, ADR/rationale rendering,
canonical missing-fact naming, display labels, currency formatting, and
sentence-join hygiene. All fixes are render-time only; pricing math,
governance, routing, and manifest/verifier semantics are untouched.
"""

from __future__ import annotations

import re

from app.services.architecture_decision_records import (
    build_decision_records,
    decision_records_markdown,
)
from app.services.deep_dossier import DeepDossierService, _cost_range, _end_sentence
from app.services.display_labels import dedupe_canonical, display_label, gate_display
from app.services.pattern_catalog import (
    ServicePattern,
    WorkloadPattern,
    _service_specific_rationale,
)
from app.services.synthesis import _title_from_use_case
from app.services.use_case_profile import UseCaseProfile

TRAILING_STOPWORDS = ("with", "for", "of", "and", "to", "the", "a", "an", "in", "on", "by")


def _empty_profile(**overrides) -> UseCaseProfile:
    fields = dict(
        domain=None,
        workload_families=[],
        excluded_families=[],
        capabilities=[],
        entities=[],
        signals=[],
        actions=[],
    )
    fields.update(overrides)
    return UseCaseProfile(**fields)


# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #
def _dossier(report_overrides: dict | None = None):
    brief = {
        "title": "Healthcare OR Delay Prediction",
        "industry": "healthcare",
        "open_questions": [{"text": "Which OR source feeds are authoritative, and how fresh are they?"}],
        "use_case_profile": {
            "domain": "healthcare",
            "workload_families": ["healthcare_operations_scheduling"],
            "capabilities": ["predictive_ml"],
            "deployment_posture": ["hybrid"],
        },
    }
    report = {
        "metadata": {
            "use_case_profile": brief["use_case_profile"],
            "customer_readiness": {"status": "directional_only", "warnings": [], "blockers": []},
            "evidence_quality": {"citation_coverage": {"passed": False}},
        },
        "evidence_items": [{"id": "ev1", "source_type": "local_policy"}],
        "recommended_production_direction": "A production-grade healthcare platform with graceful degradation when AI recommendations are unavailable.",
    }
    report.update(report_overrides or {})
    pricing = {
        "low_monthly_usd": 625.9,
        "expected_monthly_usd": 2940.5,
        "high_monthly_usd": 10570.0,
        "metadata": {
            "pricing_can_be_displayed_as_headline": False,
            "pricing_ledger": {"summary": {"headline_safe": False, "procurement_ready": False}},
        },
        "line_items": [],
        "unknown_variables": ["schedule_events_per_day", "availability_target", "availability target"],
    }
    architectures = [{
        "mode": "production",
        "metadata": {"expected_views": []},
        "selected_services": [{"service": "Amazon DynamoDB"}],
    }]
    return DeepDossierService().build(
        session_id="sess_prose",
        brief=brief,
        report=report,
        pricing=pricing,
        architectures=architectures,
        diagrams=[],
    )


def _adr_records(selected_services: list[dict], pricing: dict | None = None):
    spec = {"mode": "production", "components": [], "flows": [], "selected_services": selected_services}
    return build_decision_records(architectures=[spec], pricing=pricing, report=None, diagrams=None)


# --------------------------------------------------------------------------- #
# Row 1 — title generation
# --------------------------------------------------------------------------- #
def test_title_does_not_end_in_stopword_or_preposition():
    title = _title_from_use_case(
        "A hospital needs operating room delay prediction with"
    )
    assert title == "A Hospital Needs Operating Room Delay Prediction"
    for text in (
        "predict churn for",
        "a law firm wants retrieval augmented search over contracts and",
        "optimize spend of",
        "route alerts to",
    ):
        generated = _title_from_use_case(text)
        assert not generated.lower().endswith(TRAILING_STOPWORDS), generated


def test_title_preserves_acronym_casing():
    title = _title_from_use_case("migrate hbase and hdfs cdr analytics to aws using rag and ai")
    assert "HBase" in title
    assert "HDFS" in title
    assert "CDR" in title
    assert "AWS" in title
    assert "Ai" not in title and "Aws" not in title and "Hbase" not in title
    # Source-cased OR (operating room) is preserved; lowercase "or" stays a conjunction.
    assert "OR" in _title_from_use_case("A hospital needs OR delay prediction")
    assert " or " in _title_from_use_case("flag anomalies in payments or trades daily")


def test_title_uses_lowercase_minor_words_and_has_fallback():
    title = _title_from_use_case("ai assisted legal contract review and obligation tracking")
    assert title == "AI Assisted Legal Contract Review and Obligation Tracking"
    assert _title_from_use_case("") == "AI Solution Architecture"


def test_title_drops_trailing_bare_numbers_and_cases_hyphenated_acronyms():
    # Found by rendered-artifact inspection: "…Platform with 5 000" tail and
    # "Ai-assisted" hyphen casing in the legal golden package.
    title = _title_from_use_case(
        "AI-assisted legal contract review and obligation-tracking platform with 5 000 contracts"
    )
    assert title.startswith("AI-Assisted")
    assert not title.lower().endswith(TRAILING_STOPWORDS)
    assert not title.endswith(("5", "000"))


def test_session_name_truncates_at_word_boundary_without_dangling_stopword():
    from app.db.session_store import _session_name

    long_title = "Ai-assisted Legal Contract Review and Obligation-tracking Platform with 5 000"
    name = _session_name(long_title, "")
    assert len(name) <= 72
    assert not name.endswith(" ")
    assert not name.lower().endswith(TRAILING_STOPWORDS)
    assert not name.endswith(("5", "000"))
    assert _session_name("", "") == "New Archway session"
    assert _session_name("Short title", "") == "Short title"


# --------------------------------------------------------------------------- #
# Row 2 — heading hierarchy
# --------------------------------------------------------------------------- #
def test_executive_summary_has_exactly_one_h1():
    dossier = _dossier()
    md = DeepDossierService().executive_summary_markdown(dossier)
    h1 = re.findall(r"^# .*$", md, flags=re.MULTILINE)
    assert h1 == ["# Executive Summary"]
    assert "## Cover Summary" in md


def test_full_dossier_markdown_has_exactly_one_h1():
    dossier = _dossier()
    md = DeepDossierService().full_markdown(dossier)
    h1 = re.findall(r"^# .*$", md, flags=re.MULTILINE)
    assert h1 == ["# Deep Research Dossier"]
    # Section meaning and ordering preserved, one level down.
    assert "## Cover Summary" in md
    assert "## Final Recommendation" in md
    assert md.index("## Cover Summary") < md.index("## Final Recommendation")


# --------------------------------------------------------------------------- #
# Rows 3 + 4 — ADR/rationale rendering
# --------------------------------------------------------------------------- #
def test_adr_does_not_duplicate_purpose_when_rationale_restates_it():
    records = _adr_records([
        {
            "service": "Amazon API Gateway",
            "purpose": "Controlled API entry point",
            "rationale": "Controlled API entry point Selected for the RAG assistant workload to support retrieval.",
            "alternatives_considered": ["AWS AppSync"],
        }
    ])
    adr = next(r for r in records if r.decision_id == "adr_component_amazon_api_gateway")
    assert adr.chosen_because.count("Controlled API entry point") == 1


def test_adr_joins_distinct_purpose_and_rationale_as_sentences():
    records = _adr_records([
        {
            "service": "Amazon DynamoDB",
            "purpose": "PHI-safe operational state store.",
            "rationale": "It owns hot operational state with predictable latency.",
            "alternatives_considered": ["Amazon Timestream"],
        }
    ])
    adr = next(r for r in records if r.decision_id == "adr_component_amazon_dynamodb")
    assert adr.chosen_because == (
        "PHI-safe operational state store. It owns hot operational state with predictable latency."
    )


def test_rationale_fallback_is_never_identical_to_purpose():
    pattern = WorkloadPattern(
        id="custom",
        label="Custom analytics",
        services=(),
        flows=(),
        pricing_dimensions=(),
        poc_scope="poc",
        production_scope="prod",
        expected_views=(),
    )
    item = ServicePattern(service="Amazon Example Service", purpose="Controlled API entry point")
    profile = _empty_profile(capabilities=["event_driven_workflow", "document_retrieval"])
    rationale = _service_specific_rationale(item, pattern, profile)
    assert rationale != item.purpose
    assert not rationale.startswith(item.purpose)
    assert rationale.startswith("Selected for the Custom analytics workload")


def test_specific_rationales_have_no_repeated_boilerplate_suffix():
    pattern = WorkloadPattern(
        id="custom",
        label="Custom analytics",
        services=(),
        flows=(),
        pricing_dimensions=(),
        poc_scope="poc",
        production_scope="prod",
        expected_views=(),
    )
    item = ServicePattern(service="Amazon DynamoDB", purpose="Operational state store")
    rationale = _service_specific_rationale(item, pattern, _empty_profile())
    assert "because the use case requires" not in rationale
    assert "Alternatives remain explicit" not in rationale


def test_alternatives_caveat_appears_once_as_section_preamble():
    records = _adr_records([
        {"service": "Amazon API Gateway", "purpose": "Entry", "rationale": "Entry point control.", "alternatives_considered": ["AWS AppSync"]},
        {"service": "Amazon DynamoDB", "purpose": "State", "rationale": "Operational state.", "alternatives_considered": ["Amazon Timestream"]},
        {"service": "Amazon S3", "purpose": "Storage", "rationale": "Durable storage.", "alternatives_considered": ["Amazon EFS"]},
    ])
    md = decision_records_markdown(records)
    assert md.count("Alternatives remain explicit") == 1


# --------------------------------------------------------------------------- #
# Row 5 — canonical missing-fact naming
# --------------------------------------------------------------------------- #
def test_missing_facts_canonicalize_naming_variants():
    pricing = {
        "metadata": {"pricing_can_be_displayed_as_headline": False},
        "unknown_variables": ["availability_target", "availability target", "schedule_events_per_day"],
    }
    records = _adr_records(
        [{"service": "Amazon DynamoDB", "purpose": "State", "rationale": "State.", "alternatives_considered": ["Amazon Timestream"]}],
        pricing=pricing,
    )
    adr = next(r for r in records if r.decision_id == "adr_pricing_readiness")
    availability = [fact for fact in adr.missing_facts if "availability" in fact.lower()]
    assert availability == ["availability_target"]
    assert len(adr.missing_facts) == 2
    # Reviewer prose renders display labels, not snake_case keys.
    assert "availability_target" not in adr.reviewer_questions[0]
    assert "availability target" in adr.reviewer_questions[0]


def test_dedupe_canonical_prefers_machine_key_and_keeps_order():
    values = ["availability target", "availability_target", "exact AWS region"]
    assert dedupe_canonical(values) == ["availability_target", "exact AWS region"]


# --------------------------------------------------------------------------- #
# Row 6 — display labels in client-facing prose
# --------------------------------------------------------------------------- #
def test_display_label_examples():
    assert display_label("schedule_events_per_day") == "Schedule events per day"
    assert display_label("INTERNAL_ONLY") == "Internal only"
    assert display_label("healthcare_operations_scheduling") == "Healthcare operations scheduling"
    assert gate_display("Which OR source feeds are authoritative?") == "Which OR source feeds are authoritative?"


def test_cover_summary_uses_display_labels_not_machine_keys():
    dossier = _dossier()
    cover = dossier.sections["cover_summary"]
    assert "healthcare_operations_scheduling" not in cover
    assert "Healthcare operations scheduling" in cover
    assert "DEEP_DOSSIER" not in cover
    assert "DIRECTIONAL_ONLY" not in cover and "INTERNAL_ONLY" not in cover
    gate_bullets = [line for line in cover.splitlines() if line.startswith("- ")]
    assert all("schedule_events_per_day" not in line for line in gate_bullets)
    assert any("Schedule events per day" in line for line in gate_bullets)
    # Raw keys remain unchanged in the JSON/internal fields.
    assert dossier.workload_family == ["healthcare_operations_scheduling"]


def test_top_validation_gates_deduplicate_naming_variants():
    dossier = _dossier()
    availability = [gate for gate in dossier.top_validation_gates if "availability" in gate.lower()]
    assert len(availability) <= 1


# --------------------------------------------------------------------------- #
# Row 7 — currency/number formatting
# --------------------------------------------------------------------------- #
def test_cost_range_has_thousands_separators_and_rounding():
    pricing = {"low_monthly_usd": 625.9, "high_monthly_usd": 10570.0, "expected_monthly_usd": 2940.5}
    assert _cost_range(pricing) == "$626–$10,570/month, expected ≈ $2,940"


def test_directional_scenario_cost_range_is_formatted():
    pricing = {
        "low_monthly_usd": 625.9,
        "high_monthly_usd": 10570.0,
        "expected_monthly_usd": 2940.5,
        "metadata": {"pricing_maturity": "pricing_customer_demo_ready"},
    }
    text = _cost_range(pricing)
    assert "$626–$10,570/month, expected ≈ $2,940" in text
    assert "not procurement-ready" in text


def test_cost_range_fail_closed_branch_unchanged():
    pricing = {
        "low_monthly_usd": 1,
        "expected_monthly_usd": 2,
        "high_monthly_usd": 3,
        "metadata": {"pricing_can_be_displayed_as_headline": False},
    }
    text = _cost_range(pricing)
    assert "not headline-safe" in text
    assert "$1" not in text and "$3" not in text


# --------------------------------------------------------------------------- #
# Row 8 — sentence-join hygiene
# --------------------------------------------------------------------------- #
def test_end_sentence_strips_double_punctuation():
    assert _end_sentence("unavailable..") == "unavailable."
    assert _end_sentence("unavailable.") == "unavailable."
    assert _end_sentence("unavailable") == "unavailable."
    assert _end_sentence("are they?") == "are they?"


def test_executive_paths_have_no_double_punctuation():
    dossier = _dossier()
    md = DeepDossierService().executive_summary_markdown(dossier)
    assert ".." not in md
    assert "?." not in md
