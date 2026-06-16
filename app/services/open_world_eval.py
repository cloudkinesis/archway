from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.open_world_understanding import (
    CanonicalCandidate,
    CanonicalQuestion,
    CanonicalSourceFact,
    CanonicalWorkloadUnderstanding,
    OpenWorldUnderstandingResult,
    OpenWorldUnderstandingService,
    build_result_from_understanding,
    extract_source_facts,
)


@dataclass(frozen=True)
class D23EvalScenario:
    scenario_id: str
    title: str
    use_case: str
    domain: str
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...] = ()


def d23_eval_scenarios() -> list[D23EvalScenario]:
    return [
        D23EvalScenario(
            scenario_id="airport_baggage_irregular_ops",
            title="Airport baggage irregular operations",
            use_case=(
                "Build a system for an airport with 4 terminals and 80 baggage belts that predicts missed "
                "connections from bag scans and flight schedule changes within 2 minutes. It must alert airline "
                "service teams and passengers, but it is not a RAG chatbot and not a depot inventory system."
            ),
            domain="airport operations",
            expected_terms=("terminals", "baggage belts", "bag scans", "flight schedule", "airline service teams"),
            forbidden_terms=("rag", "depot inventory"),
        ),
        D23EvalScenario(
            scenario_id="cold_chain_vaccine_excursions",
            title="Vaccine cold-chain excursion response",
            use_case=(
                "Monitor 650 vaccine refrigerators across rural clinics, ingest temperature pings every 60 seconds, "
                "predict excursions before spoilage, and open pharmacist review workflows. Not a vehicle routing tool."
            ),
            domain="health logistics",
            expected_terms=("vaccine refrigerators", "temperature pings", "pharmacist", "spoilage"),
            forbidden_terms=("vehicle routing",),
        ),
        D23EvalScenario(
            scenario_id="museum_collection_preservation",
            title="Museum collection preservation",
            use_case=(
                "Use gallery humidity sensors, conservation notes, and visitor traffic for 120,000 artifacts to detect "
                "preservation risk and recommend curator inspections. Not a retail inventory optimization problem."
            ),
            domain="museum operations",
            expected_terms=("humidity sensors", "conservation notes", "visitor traffic", "artifacts", "curator"),
            forbidden_terms=("retail inventory",),
        ),
        D23EvalScenario(
            scenario_id="port_berth_congestion",
            title="Container port berth congestion",
            use_case=(
                "Forecast berth congestion for 18 cranes and 9 berths using AIS vessel feeds, yard gate events, and "
                "weather. Recommend berth plan changes with dispatcher approval every 15 minutes."
            ),
            domain="port operations",
            expected_terms=("berths", "cranes", "AIS vessel feeds", "yard gate events", "dispatcher"),
        ),
        D23EvalScenario(
            scenario_id="carbon_mrv_satellite",
            title="Carbon project MRV",
            use_case=(
                "Analyze satellite vegetation indices, field audit photos, and landowner attestations for 2,400 carbon "
                "project parcels. Flag suspicious changes and prepare verifier evidence packs. Not financial trading."
            ),
            domain="carbon MRV",
            expected_terms=("satellite vegetation indices", "field audit photos", "landowner", "verifier"),
            forbidden_terms=("financial trading",),
        ),
        D23EvalScenario(
            scenario_id="robot_safety_near_miss",
            title="Warehouse robot near-miss safety",
            use_case=(
                "Detect near-misses between 220 autonomous warehouse robots and workers from lidar events and wearable "
                "proximity signals, then notify safety managers within 10 seconds. Not route optimization."
            ),
            domain="warehouse safety",
            expected_terms=("robots", "workers", "lidar events", "wearable proximity", "safety managers"),
            forbidden_terms=("route optimization",),
        ),
        D23EvalScenario(
            scenario_id="food_recall_traceability",
            title="Food recall traceability",
            use_case=(
                "Trace contaminated ingredients across 45 plants, supplier COAs, batch genealogy, and retailer shipments. "
                "Generate recall scope candidates for quality approval; not a customer support chatbot."
            ),
            domain="food safety",
            expected_terms=("plants", "supplier COAs", "batch genealogy", "retailer shipments", "quality approval"),
            forbidden_terms=("customer support chatbot",),
        ),
        D23EvalScenario(
            scenario_id="campus_energy_flexibility",
            title="University campus energy flexibility",
            use_case=(
                "Optimize HVAC and battery dispatch for 62 buildings using occupancy forecasts, tariff signals, and "
                "solar production, while preserving lab temperature constraints. Not a smart meter outage system."
            ),
            domain="campus energy",
            expected_terms=("HVAC", "battery dispatch", "occupancy forecasts", "tariff signals", "lab temperature"),
            forbidden_terms=("smart meter outage",),
        ),
        D23EvalScenario(
            scenario_id="clinical_trial_matching",
            title="Clinical trial matching",
            use_case=(
                "Match oncology patients against trial criteria using EHR extracts and pathology reports for 14 hospitals, "
                "with coordinator review before outreach. Handle PHI and keep audit evidence."
            ),
            domain="clinical research",
            expected_terms=("oncology patients", "trial criteria", "EHR", "pathology reports", "coordinator"),
        ),
        D23EvalScenario(
            scenario_id="insurance_roof_claims",
            title="Insurance roof claim triage",
            use_case=(
                "Triage roof damage claims from drone imagery, adjuster notes, policy forms, and weather history. Process "
                "35,000 claims per month and route high-risk cases to senior adjusters."
            ),
            domain="insurance claims",
            expected_terms=("drone imagery", "adjuster notes", "policy forms", "weather history", "senior adjusters"),
        ),
        D23EvalScenario(
            scenario_id="maritime_engine_predictive_maintenance",
            title="Maritime engine predictive maintenance",
            use_case=(
                "Predict engine failures for 70 cargo vessels from vibration, fuel quality, maintenance logs, and sea state. "
                "Connectivity is intermittent and alerts go to fleet engineers."
            ),
            domain="maritime maintenance",
            expected_terms=("cargo vessels", "vibration", "fuel quality", "maintenance logs", "fleet engineers"),
        ),
        D23EvalScenario(
            scenario_id="sports_venue_crowd_flow",
            title="Sports venue crowd flow",
            use_case=(
                "Use turnstile events, camera-derived counts, concession queues, and transit feeds for a 65,000-seat stadium "
                "to predict crowding and recommend steward redeployment."
            ),
            domain="sports venue operations",
            expected_terms=("turnstile events", "camera-derived counts", "concession queues", "transit feeds", "steward"),
        ),
    ]


def fixture_understanding_for_scenario(scenario: D23EvalScenario) -> CanonicalWorkloadUnderstanding:
    facts = extract_source_facts(scenario.use_case)
    exclusions = [fact for fact in facts if fact.kind == "explicit_exclusion"]
    metrics = [fact for fact in facts if fact.kind == "metric"]
    candidates = [
        CanonicalCandidate(label=term, source_text=term, confidence="high", provenance="user_input")
        for term in scenario.expected_terms
    ]
    return CanonicalWorkloadUnderstanding(
        domain_candidates=[
            CanonicalCandidate(label=scenario.domain, source_text=scenario.domain, confidence="high", provenance="model_proposed")
        ],
        workload_intent=f"Support {scenario.title.lower()} with validated assumptions and auditable gaps.",
        actors=candidates[:2],
        source_systems=candidates[2:4] or candidates[:1],
        events_signals=candidates[1:4],
        data_classes=candidates[2:],
        actions_workflows=candidates[-2:],
        constraints=[
            CanonicalCandidate(label="human approval for high-impact actions", confidence="medium", provenance="derived")
        ],
        scale_metrics=metrics,
        latency_slos=[fact for fact in facts if "latency" in fact.label or "minute" in (fact.unit or "") or "second" in (fact.unit or "")],
        retention=[],
        exclusions=exclusions,
        risks_unknowns=["Exact deployment region and confirmed production volumes are unknown."],
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
                question=f"What confirmed volume, latency, and retention assumptions should Archway use for {scenario.title.lower()}?",
                why_it_matters="These values drive architecture shape, pricing quantities, and readiness confidence.",
                impact="pricing",
            ),
            CanonicalQuestion(
                question="Which automated actions require human approval before execution?",
                why_it_matters="Action authority determines workflow design and governance controls.",
                impact="security",
            ),
        ],
        confidence="medium",
    )


def run_fixture_eval(scenarios: list[D23EvalScenario] | None = None) -> dict:
    scenarios = scenarios or d23_eval_scenarios()
    results = []
    for scenario in scenarios:
        understanding = fixture_understanding_for_scenario(scenario)
        result = build_result_from_understanding(scenario.use_case, understanding)
        results.append(_score_result(scenario, result, require_live=False))
    passed_count = sum(1 for item in results if item["passed"])
    return {
        "battery": "d23_open_world_understanding_fixture_eval",
        "mode": "offline_fixture",
        "scenario_count": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "results": results,
    }


def run_live_eval(*, session_prefix: str = "d23_live_eval", scenarios: list[D23EvalScenario] | None = None) -> dict:
    scenarios = scenarios or d23_eval_scenarios()
    results = []
    service = OpenWorldUnderstandingService()
    for scenario in scenarios:
        result = service.build(
            scenario.use_case,
            session_id=f"{session_prefix}_{scenario.scenario_id}",
        )
        results.append(_score_result(scenario, result, require_live=True))
    passed_count = sum(1 for item in results if item["passed"])
    return {
        "battery": "d23_open_world_understanding_live_eval",
        "mode": "live_bedrock_refiners_disabled",
        "scenario_count": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "results": results,
    }


def _score_result(scenario: D23EvalScenario, result: OpenWorldUnderstandingResult, *, require_live: bool) -> dict:
    understanding = result.trace.understanding
    raw_text = _understanding_text(understanding, include_repaired=False)
    post_repair_text = _understanding_text(understanding, include_repaired=True)
    raw_preserved_terms = [term for term in scenario.expected_terms if term.lower() in raw_text]
    post_repair_preserved_terms = [term for term in scenario.expected_terms if term.lower() in post_repair_text]
    forbidden_leaks = [term for term in scenario.forbidden_terms if _contains_unnegated_term(raw_text, term)]
    required = max(2, len(scenario.expected_terms) - 1)
    live_call = result.trace.live_call
    live_passed = result.trace.provider == "bedrock" and live_call is not None and live_call.status == "accepted"
    passed = (
        bool(result.profile)
        and result.trace.accepted
        and len(raw_preserved_terms) >= required
        and not forbidden_leaks
        and (live_passed if require_live else True)
    )
    return {
        "scenario_id": scenario.scenario_id,
        "title": scenario.title,
        "accepted": result.trace.accepted,
        "profile_source": result.profile.profile_source if result.profile else None,
        "provider": result.trace.provider,
        "model_id": result.trace.model_id,
        "live_status": live_call.status if live_call else None,
        "error_type": live_call.error_type if live_call else None,
        "error_message": live_call.error_message if live_call else None,
        "live_passed": live_passed,
        "validation_issues": [issue.model_dump(mode="json") for issue in result.trace.validation_issues],
        "service_validations": [item.model_dump(mode="json") for item in result.trace.service_validations],
        "questions": [question.text for question in result.open_questions[:4]],
        "preserved_terms": raw_preserved_terms,
        "preserved_term_count": len(raw_preserved_terms),
        "raw_bedrock_preserved_terms": raw_preserved_terms,
        "raw_bedrock_preserved_term_count": len(raw_preserved_terms),
        "post_repair_preserved_terms": post_repair_preserved_terms,
        "post_repair_preserved_term_count": len(post_repair_preserved_terms),
        "required_preserved_term_count": required,
        "forbidden_leaks": forbidden_leaks,
        "passed": passed,
    }


def _understanding_text(understanding: CanonicalWorkloadUnderstanding | None, *, include_repaired: bool) -> str:
    if understanding is None:
        return ""
    def labels(items: list[CanonicalCandidate]) -> str:
        return " ".join(
            item.label
            for item in items
            if include_repaired or item.provenance not in {"derived", "source_term_repaired"}
        )
    return " ".join([
        understanding.workload_intent,
        labels(understanding.domain_candidates),
        labels(understanding.actors),
        labels(understanding.source_systems),
        labels(understanding.events_signals),
        labels(understanding.data_classes),
        labels(understanding.actions_workflows),
        labels(understanding.constraints),
        labels(understanding.candidate_aws_capabilities),
        labels(understanding.candidate_aws_services),
        " ".join(question.question for question in understanding.missing_questions),
    ]).lower()


def _contains_unnegated_term(text: str, term: str) -> bool:
    text = re.sub(r"[_-]+", " ", text.lower())
    needle = term.lower()
    term_pattern = re.compile(r"(?<![a-z0-9])" + re.escape(needle).replace(r"\ ", r"\s+") + r"(?![a-z0-9])")
    for match in term_pattern.finditer(text):
        prefix = text[max(0, match.start() - 32):match.start()]
        if not any(marker in prefix for marker in ("not ", "no ", "without ", "exclude ", "excluding ", "non-")):
            return True
    return False
