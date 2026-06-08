from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.domain import AWSServiceSelection
from app.services.pattern_catalog import pricing_dimensions, service_recommendations
from app.services.pricing import PricingEngine
from app.services.pricing_driver_selector import select_pricing_driver_family
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_use_case


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    label: str
    use_case: str
    required_any_family: tuple[str, ...]
    required_pricing_family: tuple[str, ...]
    required_question_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]
    required_pricing_drivers: tuple[str, ...] = ()
    forbidden_families: tuple[str, ...] = ()
    forbidden_pricing_families: tuple[str, ...] = ()


SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        id="legal_contract_rag",
        label="Legal contract RAG and obligation workflow",
        use_case=(
            "AI-assisted legal contract review and obligation-tracking platform with 5,000 historical contracts, "
            "RAG Q&A, clause extraction, obligation tracking, approval workflow, and audit trail."
        ),
        required_any_family=("document_intelligence", "rag_assistant"),
        required_pricing_family=("document_rag_workflow",),
        required_question_terms=("historical contracts", "average pages or mb", "documents per month"),
        required_pricing_drivers=("historical_contract_count", "rag_queries_per_day"),
        forbidden_terms=(
            "telemetry frequency",
            "payload size",
            "healthcare",
            "operating room",
            "ehr",
            "telecom",
            "hbase",
            "cdn",
            "iot core",
            "depot",
            "dispatch",
            "payment_fraud_scoring",
        ),
        forbidden_families=("healthcare_operations_scheduling", "telecom_network_analytics", "live_streaming", "industrial_iot_streaming_ml", "financial_fraud_detection"),
        forbidden_pricing_families=("payment_fraud_scoring", "industrial_iot_streaming", "healthcare_operations_scheduling", "telecom_cdr_analytics", "live_media_streaming"),
    ),
    ScenarioSpec(
        id="energy_iot_telemetry",
        label="Energy utility IoT telemetry anomaly detection",
        use_case=(
            "An energy utility IoT telemetry platform ingests device reporting from smart meters and transformer sensors, "
            "runs anomaly detection on voltage and temperature signals, and alerts grid operators."
        ),
        required_any_family=("industrial_iot_streaming_ml", "real_time_anomaly_detection"),
        required_pricing_family=("industrial_iot_streaming",),
        required_question_terms=("reporting frequency",),
        required_pricing_drivers=("asset_count", "telemetry_frequency_seconds"),
        forbidden_terms=("payment_fraud_scoring", "financial_fraud_detection", "fraud scoring", "card transaction", "chargeback"),
        forbidden_families=("financial_fraud_detection",),
        forbidden_pricing_families=("payment_fraud_scoring",),
    ),
    ScenarioSpec(
        id="telecom_hbase_hdfs",
        label="Telecom HBase/HDFS real-time analytics migration",
        use_case="We need to migrate a telecom HBase/HDFS real-time analytics platform to AWS.",
        required_any_family=("telecom_network_analytics", "data_platform_analytics"),
        required_pricing_family=("telecom_cdr_analytics",),
        required_question_terms=("hbase access patterns", "target store"),
        required_pricing_drivers=("storage_gb", "query_tb_scanned"),
        forbidden_terms=("operating room", "patient", "clinical", "charge nurse", "epic", "phi"),
        forbidden_families=("healthcare_operations_scheduling",),
        forbidden_pricing_families=("healthcare_operations_scheduling", "document_rag_workflow", "payment_fraud_scoring"),
    ),
    ScenarioSpec(
        id="healthcare_or",
        label="Healthcare OR scheduling / delay prediction",
        use_case=(
            "A hospital needs operating room delay prediction with Epic schedule data, patient check-in, charge nurse approval, "
            "PHI controls, and sterile processing readiness. Predictions refresh every 2 minutes across 18 hospitals and 240 operating rooms."
        ),
        required_any_family=("healthcare_operations_scheduling", "surgical_scheduling_prediction"),
        required_pricing_family=("healthcare_operations_scheduling",),
        required_question_terms=("or source feeds",),
        required_pricing_drivers=("hospital_count", "operating_room_count", "refresh_cadence_minutes", "approval_workflow_executions_per_day"),
        forbidden_terms=("depot", "dispatch", "confirmed incident", "candidate anomaly", "asset telemetry"),
        forbidden_families=("industrial_iot_streaming_ml", "field_service_automation"),
        forbidden_pricing_families=("industrial_iot_streaming", "payment_fraud_scoring"),
    ),
    ScenarioSpec(
        id="media_qoe_cdn",
        label="Media streaming QoE and CDN log analytics",
        use_case=(
            "A media company streams 4K HDR live sports to global viewers and needs a video streaming analytics platform "
            "for viewer QoE, CDN logs, DRM events, ad decision logs, and playback error analysis."
        ),
        required_any_family=("live_streaming",),
        required_pricing_family=("live_media_streaming",),
        required_question_terms=("viewer-hours", "peak concurrent viewers"),
        required_pricing_drivers=("concurrent_viewers", "cdn_egress_gb"),
        forbidden_terms=("operating room", "patient", "clinical", "charge nurse", "epic", "phi"),
        forbidden_families=("healthcare_operations_scheduling", "computer_vision_quality_inspection"),
        forbidden_pricing_families=("healthcare_operations_scheduling", "document_rag_workflow", "payment_fraud_scoring"),
    ),
    ScenarioSpec(
        id="generic_web_app",
        label="Generic public web app",
        use_case="We need a public web application with API, database, async jobs, observability, and CI/CD.",
        required_any_family=("web_api_application",),
        required_pricing_family=("generic_directional",),
        required_question_terms=("active users", "api requests", "async jobs"),
        required_pricing_drivers=("active_users", "api_requests_per_day", "background_jobs_per_day"),
        forbidden_terms=("telemetry frequency", "payload size", "historical contracts", "rag queries", "hbase access patterns"),
        forbidden_families=("document_intelligence", "rag_assistant", "industrial_iot_streaming_ml", "healthcare_operations_scheduling"),
        forbidden_pricing_families=("document_rag_workflow", "industrial_iot_streaming", "healthcare_operations_scheduling", "payment_fraud_scoring"),
    ),
    ScenarioSpec(
        id="payment_transaction_fraud",
        label="Payment transaction fraud detection",
        use_case=(
            "A bank needs payment transaction fraud detection across card transactions, suspicious payment review, "
            "chargeback investigation, and policy-approved blocking."
        ),
        required_any_family=("financial_fraud_detection",),
        required_pricing_family=("payment_fraud_scoring",),
        required_question_terms=(),
        required_pricing_drivers=("transactions_per_day", "scoring_events_per_day"),
        forbidden_terms=("operating room", "hbase access patterns", "historical contracts"),
        forbidden_families=("document_intelligence", "healthcare_operations_scheduling", "industrial_iot_streaming_ml"),
        forbidden_pricing_families=("document_rag_workflow", "healthcare_operations_scheduling", "industrial_iot_streaming"),
    ),
)


def run_matrix(write_artifact: bool = True, artifact_path: str | Path = "artifacts/rc2_discovery_baseline_report.md") -> list[dict[str, Any]]:
    results = asyncio.run(_run_matrix())
    if write_artifact:
        path = Path(artifact_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(results), encoding="utf-8")
    return results


async def _run_matrix() -> list[dict[str, Any]]:
    return [await _evaluate_scenario(spec) for spec in SCENARIOS]


async def _evaluate_scenario(spec: ScenarioSpec) -> dict[str, Any]:
    engine = SynthesisEngine()
    profile = profile_use_case(spec.use_case)
    brief = engine.create_initial_brief(spec.use_case)
    plan = brief.use_case_profile.get("discovery_plan") or {}
    question = engine.next_question(brief)
    pricing_services = [
        AWSServiceSelection(service=item.service, purpose=item.purpose, rationale=item.rationale)
        for item in service_recommendations(profile, evidence_ids=["ev_rc2"])
    ][:5] or [AWSServiceSelection(service="Amazon API Gateway", purpose="api", rationale="managed")]
    estimate = await PricingEngine().estimate(brief, pricing_services)
    pricing_family = str(estimate.metadata.get("pricing_driver_family") or select_pricing_driver_family(profile).value)
    headline_safe = bool(estimate.metadata.get("pricing_can_be_displayed_as_headline"))
    procurement_ready = any(bool(line.pricing_trace.get("procurement_ready")) for line in estimate.line_items)
    first_question = question.prompt if question else ""
    planner_domain = _candidate_name(plan, "domain_candidates")
    planner_family = _candidate_name(plan, "workload_family_candidates")
    planner_confidence = str(plan.get("confidence") or "unknown")
    pricing_drivers = list(plan.get("pricing_drivers") or pricing_dimensions(profile))
    observed_text = _observed_text(
        profile=profile,
        plan=plan,
        first_question=first_question,
        pricing_family=pricing_family,
        pricing_drivers=pricing_drivers,
        estimate=estimate,
    )
    forbidden_detected = _detect_forbidden_terms(spec.forbidden_terms, observed_text, spec.use_case)
    pipeline_decision = _pipeline_decision(profile, plan)
    return {
        "id": spec.id,
        "label": spec.label,
        "baseline_domain": profile.domain,
        "baseline_families": list(profile.workload_families),
        "planner_domain": planner_domain,
        "planner_family": planner_family,
        "planner_confidence": planner_confidence,
        "planner_ambiguity": bool(plan.get("ambiguity_detected")),
        "not_relevant_patterns": list(plan.get("not_relevant_patterns") or []),
        "pricing_drivers": pricing_drivers,
        "main_cost_drivers": list(estimate.main_cost_drivers),
        "first_interview_question": first_question,
        "pricing_family": pricing_family,
        "pricing_headline_safe": headline_safe,
        "pricing_readiness": "procurement-ready" if procurement_ready else "directional",
        "pricing_procurement_ready": procurement_ready,
        "forbidden_cross_domain_terms": forbidden_detected,
        "pipeline_decision": pipeline_decision,
        "planner_has_procurement_ready_flag": _planner_has_procurement_ready_flag(plan),
        "metadata_status": estimate.metadata.get("status"),
    }


def validate_results(results: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    by_id = {item["id"]: item for item in results}
    specs = {item.id: item for item in SCENARIOS}
    for scenario_id, spec in specs.items():
        result = by_id.get(scenario_id)
        if not result:
            errors.append(f"{scenario_id}: missing result")
            continue
        text = _result_text(result)
        families = set(result["baseline_families"])
        if not any(family in families for family in spec.required_any_family):
            errors.append(f"{scenario_id}: expected one of {spec.required_any_family}, got {result['baseline_families']}")
        for family in spec.forbidden_families:
            if family in families:
                errors.append(f"{scenario_id}: forbidden family {family} present")
        if result["pricing_family"] not in spec.required_pricing_family:
            errors.append(f"{scenario_id}: expected pricing family {spec.required_pricing_family}, got {result['pricing_family']}")
        if result["pricing_family"] in spec.forbidden_pricing_families:
            errors.append(f"{scenario_id}: forbidden pricing family {result['pricing_family']} selected")
        for term in spec.required_question_terms:
            if term.lower() not in result["first_interview_question"].lower():
                errors.append(f"{scenario_id}: first question missing term {term!r}")
        for driver in spec.required_pricing_drivers:
            if driver.lower() not in text:
                errors.append(f"{scenario_id}: pricing/discovery drivers missing {driver!r}")
        if result["forbidden_cross_domain_terms"]:
            errors.append(f"{scenario_id}: forbidden terms detected {result['forbidden_cross_domain_terms']}")
        if result["pricing_headline_safe"]:
            errors.append(f"{scenario_id}: pricing should not be headline-safe in RC2 smoke matrix")
        if result["pricing_procurement_ready"]:
            errors.append(f"{scenario_id}: pricing should not be procurement-ready in RC2 smoke matrix")
        if result["planner_has_procurement_ready_flag"]:
            errors.append(f"{scenario_id}: planner output exposed procurement-ready authority")
    return errors


def render_console_table(results: list[dict[str, Any]]) -> str:
    rows = [
        ["Scenario", "Baseline domain", "Families", "Planner", "Pricing", "Headline", "Decision", "Forbidden"],
    ]
    for item in results:
        rows.append(
            [
                item["id"],
                str(item["baseline_domain"]),
                ",".join(item["baseline_families"][:2]),
                f"{item['planner_domain']}/{item['planner_family']}/{item['planner_confidence']}",
                item["pricing_family"],
                str(item["pricing_headline_safe"]),
                item["pipeline_decision"],
                ",".join(item["forbidden_cross_domain_terms"]) or "-",
            ]
        )
    widths = [max(len(str(row[index])) for row in rows) for index in range(len(rows[0]))]
    lines = []
    for index, row in enumerate(rows):
        lines.append(" | ".join(str(cell).ljust(widths[col]) for col, cell in enumerate(row)))
        if index == 0:
            lines.append("-+-".join("-" * width for width in widths))
    return "\n".join(lines)


def render_markdown(results: list[dict[str, Any]]) -> str:
    errors = validate_results(results)
    lines = [
        "# RC2 Discovery Baseline Report",
        "",
        f"Status: {'PASS' if not errors else 'FAIL'}",
        "",
        "| Scenario | Baseline domain | Families | Planner | Pricing family | Headline safe | Readiness | Decision | Forbidden terms |",
        "|---|---|---|---|---|---:|---|---|---|",
    ]
    for item in results:
        lines.append(
            "| {id} | {domain} | {families} | {planner} | {pricing} | {headline} | {readiness} | {decision} | {forbidden} |".format(
                id=item["id"],
                domain=item["baseline_domain"],
                families=", ".join(item["baseline_families"]),
                planner=f"{item['planner_domain']} / {item['planner_family']} / {item['planner_confidence']}",
                pricing=item["pricing_family"],
                headline=item["pricing_headline_safe"],
                readiness=item["pricing_readiness"],
                decision=item["pipeline_decision"],
                forbidden=", ".join(item["forbidden_cross_domain_terms"]) or "-",
            )
        )
    lines.extend(["", "## First Questions", ""])
    for item in results:
        lines.append(f"- `{item['id']}`: {item['first_interview_question']}")
    lines.extend(["", "## Pricing Drivers", ""])
    for item in results:
        lines.append(f"- `{item['id']}`: {', '.join(item['pricing_drivers'][:12])}")
    if errors:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines) + "\n"


def _candidate_name(plan: dict[str, Any], key: str) -> str:
    candidates = plan.get(key) or []
    if candidates and isinstance(candidates[0], dict):
        return str(candidates[0].get("name") or "unknown")
    return "unknown"


def _pipeline_decision(profile: Any, plan: dict[str, Any]) -> str:
    if plan.get("ambiguity_detected"):
        return "challenged"
    planner_family = _candidate_name(plan, "workload_family_candidates")
    planner_domain = _candidate_name(plan, "domain_candidates")
    family_accepted = planner_family in set(profile.workload_families)
    domain_accepted = planner_domain in {str(profile.domain), "unknown", "None"} or profile.domain is None
    return "accepted" if family_accepted and domain_accepted else "overrode"


def _detect_forbidden_terms(terms: tuple[str, ...], observed_text: str, source_text: str) -> list[str]:
    source_lower = source_text.lower()
    observed_lower = observed_text.lower()
    return [term for term in terms if term.lower() in observed_lower and term.lower() not in source_lower]


def _observed_text(profile: Any, plan: dict[str, Any], first_question: str, pricing_family: str, pricing_drivers: list[str], estimate: Any) -> str:
    return "\n".join(
        [
            str(profile.domain),
            " ".join(profile.workload_families),
            " ".join(profile.capabilities),
            str(plan.get("not_relevant_patterns") or []),
            first_question,
            pricing_family,
            " ".join(pricing_drivers),
            " ".join(estimate.main_cost_drivers),
            " ".join(item.unit_basis for item in estimate.line_items),
            " ".join(assumption for item in estimate.line_items for assumption in item.assumptions),
        ]
    ).lower()


def _result_text(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            str(result["baseline_domain"]),
            " ".join(result["baseline_families"]),
            str(result["planner_domain"]),
            str(result["planner_family"]),
            " ".join(result["pricing_drivers"]),
            " ".join(result.get("main_cost_drivers") or []),
            str(result["first_interview_question"]),
            str(result["pricing_family"]),
        ]
    ).lower()


def _planner_has_procurement_ready_flag(plan: dict[str, Any]) -> bool:
    return any("procurement" in str(key).lower() and "ready" in str(key).lower() for key in plan.keys())


def main() -> int:
    path = Path("artifacts/rc2_discovery_baseline_report.md")
    results = run_matrix(write_artifact=True, artifact_path=path)
    errors = validate_results(results)
    print(render_console_table(results))
    print()
    print(f"Markdown report: {path}")
    print(f"Status: {'PASS' if not errors else 'FAIL'}")
    if errors:
        print("Failures:")
        for error in errors:
            print(f"- {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
