from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.services.display_labels import dedupe_canonical, display_label, gate_display
from app.models.domain import (
    AssumptionRecord,
    DeepResearchDossier,
    DossierClaimKind,
    DossierConsistencyCheck,
    DossierPricingEvidenceClass,
    DossierPricingLine,
    DossierQualityScore,
    DossierReadinessStatus,
    DossierResearchQuestion,
    FeasibilityRow,
    PricingFormula,
    RequirementRecord,
    ResearchClaim,
    ResearchClaimType,
    RiskRecord,
)


class DeepDossierService:
    def build(
        self,
        *,
        session_id: str,
        brief: dict | None,
        report: dict | None,
        pricing: dict | None,
        architectures: list[dict] | None,
        diagrams: list[dict] | None,
    ) -> DeepResearchDossier:
        brief = brief or {}
        report = report or {}
        pricing = pricing or {}
        architectures = architectures or []
        diagrams = diagrams or []
        metadata = report.get("metadata") or {}
        profile = metadata.get("use_case_profile") or brief.get("use_case_profile") or {}
        evidence_items = report.get("evidence_items") or []
        assessments = {item.get("evidence_id"): item for item in report.get("evidence_assessments", [])}
        readiness = metadata.get("customer_readiness") or {}
        evidence_quality = metadata.get("evidence_quality") or {}
        production = _production_architecture(architectures)
        production_gallery = _production_gallery(diagrams)

        requirements = _requirements(brief, profile)
        assumptions = _assumptions(brief, pricing, evidence_items)
        service_rows = _service_decision_rows(metadata, report)
        feasibility = _feasibility_rows(brief, profile, production, evidence_items)
        pricing_lines = _pricing_lines(pricing)
        risks = _risk_records(report, pricing, profile)
        claims = _claims(report, pricing, service_rows, risks, evidence_items)
        consistency = _consistency_check(
            report=report,
            pricing=pricing,
            claims=claims,
            pricing_lines=pricing_lines,
            diagrams=diagrams,
            evidence_quality=evidence_quality,
            readiness=readiness,
            profile=profile,
        )
        quality = _quality_score(
            evidence_quality=evidence_quality,
            pricing_lines=pricing_lines,
            consistency=consistency,
            production_gallery=production_gallery,
            readiness=readiness,
            service_rows=service_rows,
            risks=risks,
        )
        verdict = _verdict(readiness, consistency, pricing_lines, risks)
        top_gates = _validation_gates(brief, metadata, pricing, risks)
        sections = _sections(
            session_id=session_id,
            generated_at=datetime.now(timezone.utc),
            verdict=verdict,
            brief=brief,
            report=report,
            pricing=pricing,
            production=production,
            production_gallery=production_gallery,
            profile=profile,
            evidence_quality=evidence_quality,
            readiness=readiness,
            requirements=requirements,
            assumptions=assumptions,
            service_rows=service_rows,
            feasibility=feasibility,
            pricing_lines=pricing_lines,
            risks=risks,
            claims=claims,
            consistency=consistency,
            quality=quality,
            evidence_items=evidence_items,
            assessments=assessments,
            top_gates=top_gates,
        )
        return DeepResearchDossier(
            session_id=session_id,
            verdict=verdict,
            title=brief.get("title") or "Untitled AWS solution",
            industry=brief.get("industry") or profile.get("domain"),
            workload_family=list(profile.get("workload_families") or metadata.get("workload_families") or []),
            estimated_monthly_cost_range=_cost_range(pricing),
            top_validation_gates=top_gates[:3],
            research_plan=_research_plan(profile, brief),
            requirements=requirements,
            assumptions=assumptions,
            claims=claims,
            feasibility=feasibility,
            pricing_lines=pricing_lines,
            risks=risks,
            consistency_check=consistency,
            quality_score=quality,
            sections=sections,
        )

    def executive_summary_markdown(self, dossier: DeepResearchDossier) -> str:
        return "\n\n".join([
            "# Executive Summary",
            dossier.sections["cover_summary"],
            dossier.sections["executive_verdict"],
            dossier.sections["final_recommendation"],
        ]) + "\n"

    def full_markdown(self, dossier: DeepResearchDossier) -> str:
        order = [
            "cover_summary",
            "executive_verdict",
            "use_case_interpretation",
            "confirmed_requirements",
            "key_assumptions",
            "evidence_quality",
            "architecture_recommendation",
            "service_decision_matrix",
            "technical_feasibility",
            "pricing_analysis",
            "cost_sensitivity",
            "competitive_landscape",
            "key_differentiators",
            "security_compliance",
            "reliability_resilience",
            "performance_scalability",
            "operational_readiness",
            "risk_matrix",
            "implementation_roadmap",
            "validation_plan",
            "final_recommendation",
            "evidence_appendix",
        ]
        return "\n\n".join(["# Deep Research Dossier", *(dossier.sections[key] for key in order)]) + "\n"

    def claim_register_markdown(self, dossier: DeepResearchDossier) -> str:
        rows = [
            [
                claim.id,
                claim.claim_kind.value,
                claim.claim_type.value,
                claim.confidence,
                "yes" if claim.requires_validation else "no",
                ", ".join(claim.evidence_ids) or "none",
                _presentation_text(claim.text),
            ]
            for claim in dossier.claims
        ]
        return "# Claim Register\n\n" + _table(
            ["ID", "Kind", "Type", "Confidence", "Requires validation", "Evidence", "Claim"],
            rows,
        ) + "\n"

    def evidence_map_markdown(self, dossier: DeepResearchDossier, report: dict | None) -> str:
        report = report or {}
        evidence = {item.get("id"): item for item in report.get("evidence_items", [])}
        rows = []
        for claim in dossier.claims:
            for evidence_id in claim.evidence_ids or ["none"]:
                item = evidence.get(evidence_id, {})
                rows.append([
                    claim.id,
                    evidence_id,
                    item.get("title", "No source"),
                    item.get("source_type", "unknown"),
                    item.get("url") or "n/a",
                    "requires validation" if claim.requires_validation else "supports claim",
                ])
        return "# Evidence Map\n\n" + _table(
            ["Claim", "Evidence", "Source title", "Source type", "URL", "Use"],
            rows,
        ) + "\n"

    def consistency_markdown(self, dossier: DeepResearchDossier) -> str:
        check = dossier.consistency_check
        lines = ["# Consistency Check", "", f"Passed: {check.passed}", ""]
        lines.extend(["## Errors", *[f"- {item}" for item in check.errors or ["None"]], ""])
        lines.extend(["## Warnings", *[f"- {item}" for item in check.warnings or ["None"]], ""])
        return "\n".join(lines)


def _presentation_text(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s*Synthesis interview note:.*?(?=\s*Synthesis interview note:|$)", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\s*\b(?:this is\s+)?not\s+[^.]{1,120}?(?:,\s*not\s+[^.]{1,120}?){1,}(?:\.|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Interview answer for\s+'[^']+':\s*", "Customer clarified: ", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()


def _research_plan(profile: dict, brief: dict) -> list[DossierResearchQuestion]:
    families = ", ".join(profile.get("workload_families") or ["AWS workload"])
    return [
        DossierResearchQuestion(question=f"Which AWS services fit {families}?", category="aws_service_fit", required_source_types=["aws_docs", "local_policy"], priority="critical"),
        DossierResearchQuestion(question="Which pricing dimensions control the largest cost drivers?", category="pricing", required_source_types=["aws_pricing", "price_list"], priority="critical"),
        DossierResearchQuestion(question="Which alternative commercial, cloud-native, and self-managed patterns should be considered?", category="competition", required_source_types=["web", "user_input"], priority="important"),
        DossierResearchQuestion(question="Which security, compliance, and shared-responsibility controls require customer validation?", category="compliance", required_source_types=["aws_docs", "local_policy"], priority="critical"),
        DossierResearchQuestion(question=f"What hybrid, edge, or private connectivity posture is implied by {brief.get('industry') or profile.get('domain') or 'the use case'}?", category="hybrid_deployment", required_source_types=["user_input", "aws_docs"], priority="important"),
    ]


def _requirements(brief: dict, profile: dict) -> list[RequirementRecord]:
    rows = []
    for metric in profile.get("metrics", []):
        rows.append(RequirementRecord(
            requirement=str(metric.get("label", "metric")).replace("_", " ").title(),
            value=f"{metric.get('value')} {metric.get('unit', '')}".strip(),
            source="User input",
            architecture_impact=_metric_arch_impact(metric),
            pricing_impact=_metric_pricing_impact(metric),
            confidence="high",
        ))
    for goal in brief.get("business_goals", []):
        rows.append(RequirementRecord(
            requirement="Business goal",
            value=str(goal),
            source="User input",
            architecture_impact="Defines success metrics, rollout criteria, and operational reporting.",
            pricing_impact="May affect retention, resilience, monitoring, and scale assumptions.",
            confidence="high",
        ))
    return rows or [
        RequirementRecord(
            requirement="Use case",
            value=brief.get("raw_use_case", "Not provided")[:240],
            source="User input",
            architecture_impact="Drives capability extraction and service selection.",
            pricing_impact="Drives workload-driver assumptions.",
            confidence="medium",
        )
    ]


def _assumptions(brief: dict, pricing: dict, evidence_items: list[dict]) -> list[AssumptionRecord]:
    evidence_id = _first_evidence(evidence_items, {"user_input", "local_policy"})
    records = [
        AssumptionRecord(
            assumption=_presentation_text(item.get("text", "")),
            confidence=item.get("confidence", "medium"),
            why_needed=item.get("reason", "Required to proceed without a blocking discovery question."),
            impacts=[item.get("impact", "architecture")],
            if_wrong=_if_wrong(item.get("impact", "architecture")),
            validation_method=_validation_method(item.get("impact", "architecture")),
            used_in_pricing=item.get("impact") == "pricing",
            used_in_architecture=item.get("impact") in {"architecture", "security", "performance", "compliance"},
            evidence_ids=[evidence_id] if evidence_id else [],
        )
        for item in brief.get("assumptions", [])
        if item.get("text")
    ]
    for variable in pricing.get("unknown_variables", [])[:6]:
        records.append(AssumptionRecord(
            assumption=f"{variable} is not yet confirmed.",
            confidence="medium",
            why_needed="The dossier must expose pricing or architecture variables that remain unresolved.",
            impacts=["pricing"],
            if_wrong="The low, expected, and high estimates may move materially.",
            validation_method="Confirm with customer workload measurements, AWS Pricing Calculator, and a POC burn-in.",
            used_in_pricing=True,
            used_in_architecture=False,
            evidence_ids=[evidence_id] if evidence_id else [],
        ))
    return records


def _service_decision_rows(metadata: dict, report: dict) -> list[dict]:
    rows = list(metadata.get("service_decision_records") or [])
    if rows:
        return rows
    return [
        {
            "capability": item.get("purpose"),
            "selected_service": item.get("service"),
            "selected_service_rationale": item.get("rationale"),
            "selection_reason": item.get("rationale"),
            "options_considered": [{"service_name": alt, "fit": "alternative", "rationale": "Alternative listed by service recommendation.", "risks": [], "evidence_ids": item.get("evidence_ids", [])} for alt in item.get("alternatives_considered", [])],
            "required_validation": ["Validate service limits, regional availability, and pricing before procurement."],
            "evidence_ids": item.get("evidence_ids", []),
        }
        for item in report.get("aws_service_recommendations", [])
    ]


def _feasibility_rows(brief: dict, profile: dict, production: dict, evidence_items: list[dict]) -> list[FeasibilityRow]:
    evidence_id = _first_evidence(evidence_items, {"aws_docs", "local_policy"})
    capabilities = set(profile.get("capabilities", [])) | set(profile.get("capability_model", []))
    rows = []
    if _is_media_profile(profile):
        rows.append(FeasibilityRow(requirement="Live media ingest and playback delivery", candidate_design="AWS Elemental MediaLive, MediaPackage, CloudFront, edge policy controls, DRM provider integration, consent checks, and QoE monitoring.", aws_capability="Managed live encoding, origin packaging, CDN delivery, edge policy enforcement, and observable playback event collection.", feasibility_verdict="CONDITIONALLY_FEASIBLE", key_risk="Viewer-hours, bitrate ladder, regional mix, cache-hit ratio, channel-hours, rights-policy behavior, and ad/QoE event rates are not confirmed.", validation_method="Replay representative live events, simulate viewer concurrency, verify DRM/blackout/consent decisions, and measure glass-to-glass latency/QoE.", evidence_ids=[evidence_id] if evidence_id else []))
    elif {"device_telemetry", "stream_ingestion"} & capabilities:
        rows.append(FeasibilityRow(requirement="Real-time telemetry ingestion", candidate_design="AWS IoT Core or Kinesis Data Streams fronted by secure device/gateway ingestion.", aws_capability="Managed ingestion, buffering, and downstream fan-out for telemetry events.", feasibility_verdict="CONDITIONALLY_FEASIBLE", key_risk="Actual reporting frequency and payload size are not confirmed.", validation_method="Replay representative peak telemetry through the POC ingestion path.", evidence_ids=[evidence_id] if evidence_id else []))
    if {"stream_processing", "feature_engineering"} & capabilities:
        rows.append(FeasibilityRow(requirement="Streaming feature extraction and correlation", candidate_design="Managed Service for Apache Flink with durable stream input and replayable data lake output.", aws_capability="Stateful windowing and real-time analytics pattern.", feasibility_verdict="CONDITIONALLY_FEASIBLE", key_risk="KPU sizing and late-event handling require measured data.", validation_method="Run load test with production-like windows, skew, and late events.", evidence_ids=[evidence_id] if evidence_id else []))
    if {"ml_inference", "predictive_ml", "real_time_anomaly_detection", "anomaly_detection"} & capabilities:
        rows.append(FeasibilityRow(requirement="Predictive scoring and anomaly detection", candidate_design="SageMaker training, registry, endpoint or batch scoring depending on latency and volume.", aws_capability="Managed model lifecycle and inference hosting.", feasibility_verdict="REQUIRES_VALIDATION", key_risk="False positives, false negatives, and model latency can affect operations.", validation_method="Validate model quality, drift, inference latency, and approval thresholds before automation.", evidence_ids=[evidence_id] if evidence_id else []))
    if profile.get("actions"):
        rows.append(FeasibilityRow(requirement="Automated operational action", candidate_design="EventBridge, SQS, Step Functions, Lambda adapters, and approval/policy gates.", aws_capability="Durable event choreography with retriable integration adapters.", feasibility_verdict="CONDITIONALLY_FEASIBLE", key_risk="Unsafe downstream operational updates if policy gates are weak.", validation_method="Run shadow-mode operational workflow with idempotency and rollback tests.", evidence_ids=[evidence_id] if evidence_id else []))
    if "network_private_connectivity" in ((production.get("metadata") or {}).get("expected_views") or []):
        rows.append(FeasibilityRow(requirement="Private enterprise integration", candidate_design="VPC-resident integration adapter with private network path to existing enterprise systems.", aws_capability="VPC placement, endpoint/private connectivity pattern, logging, and policy controls.", feasibility_verdict="REQUIRES_VALIDATION", key_risk="Customer network path, DNS, identity, firewall, and latency are not yet confirmed.", validation_method="Validate connectivity design with customer network team and run failover tests.", evidence_ids=[evidence_id] if evidence_id else []))
    return rows


def _pricing_lines(pricing: dict) -> list[DossierPricingLine]:
    lines = []
    for item in pricing.get("line_items", []):
        evidence_class = _pricing_evidence_class(item)
        trace = item.get("pricing_trace") or {}
        not_estimated = evidence_class == DossierPricingEvidenceClass.not_estimated or trace.get("not_estimated")
        expected = None if not_estimated else float(item.get("expected_monthly_usd") or 0)
        quantity_text = (
            f"{trace.get('source_truth_quantity')} {trace.get('source_truth_quantity_unit')}"
            if trace.get("source_truth_quantity")
            else item.get("unit_basis") or "usage driver not quantified"
        )
        formula = PricingFormula(
            formula_text=trace.get("source_truth_formula") or f"Expected monthly estimate from deterministic low/expected/high model for {item.get('service')}.",
            variables={"low": item.get("low_monthly_usd"), "expected": expected, "high": item.get("high_monthly_usd"), "unit_basis": quantity_text},
            unit_price=None,
            quantity=1,
            monthly_total=expected,
            evidence_class=evidence_class,
            evidence_ids=item.get("evidence_ids", []),
        )
        lines.append(DossierPricingLine(
            service=item.get("service", "Unknown service"),
            usage_driver=quantity_text,
            quantity=quantity_text,
            formula=formula,
            unit_price="not SKU/tier resolved",
            monthly_estimate=expected,
            evidence_type=evidence_class,
            sku_usage_rate=str(trace.get("service_code") or trace.get("source_reference") or "not SKU/tier resolved"),
            confidence="medium" if evidence_class != DossierPricingEvidenceClass.heuristic else "low",
            validation_needed=_pricing_validation_needed(evidence_class, trace),
        ))
    return lines


def _risk_records(report: dict, pricing: dict, profile: dict) -> list[RiskRecord]:
    records = [
        RiskRecord(
            severity=item.get("severity", "medium"),
            risk=item.get("title", "Unspecified risk"),
            why_it_matters=_risk_why(item.get("title", "")),
            likelihood="medium",
            impact="high" if item.get("severity") == "high" else "medium",
            mitigation=item.get("mitigation", "Validate before production."),
            validation_owner=_risk_owner(item.get("title", "")),
            blocking_status="watch" if item.get("severity") != "high" else "blocking",
            evidence_ids=item.get("evidence_ids", []),
        )
        for item in report.get("risks", [])
    ]
    if pricing.get("unknown_variables"):
        if _is_media_profile(profile):
            why = "Budget approval can be wrong if viewer-hours, bitrate ladder, regional traffic mix, CDN cache-hit ratio, channel-hours, ad decisions, DRM license volume, or archive retention differ from assumptions."
        else:
            why = "Budget approval can be wrong if workload event rate, message size, retention, or action rate differ from assumptions."
        records.append(RiskRecord(severity="medium", risk="Pricing remains directional until workload drivers are measured.", why_it_matters=why, likelihood="high", impact="medium", mitigation="Run a POC burn-in and refresh with AWS Pricing Calculator or Pricing MCP.", validation_owner="Cloud economist", blocking_status="watch", evidence_ids=[]))
    if "hybrid" in profile.get("deployment_posture", []):
        records.append(RiskRecord(severity="high", risk="Hybrid/private integration is a production readiness gate.", why_it_matters="Automated downstream operational updates depend on reliable customer network, identity, and retry behavior.", likelihood="medium", impact="high", mitigation="Validate private connectivity, DNS, IAM, firewall, idempotency, and rollback in pilot.", validation_owner="Network and operations owner", blocking_status="blocking", evidence_ids=[]))
    return records


def _claims(report: dict, pricing: dict, service_rows: list[dict], risks: list[RiskRecord], evidence_items: list[dict]) -> list[ResearchClaim]:
    claims = []
    for item in report.get("facts", []):
        claims.append(ResearchClaim(text=item.get("text", ""), claim_type=ResearchClaimType.architecture_rationale, claim_kind=DossierClaimKind.fact, confidence=item.get("confidence", "medium"), evidence_ids=item.get("evidence_ids", []), unsupported=not bool(item.get("evidence_ids")), requires_validation=not bool(item.get("evidence_ids")), section_ids=["evidence_quality", "architecture_recommendation"]))
    for item in report.get("recommendations", []):
        claims.append(ResearchClaim(text=item.get("text", ""), claim_type=ResearchClaimType.recommendation, claim_kind=DossierClaimKind.recommendation, confidence=item.get("confidence", "medium"), evidence_ids=item.get("evidence_ids", []), unsupported=not bool(item.get("evidence_ids")), requires_validation=False, section_ids=["executive_verdict", "final_recommendation"]))
    for item in report.get("uncertainties", []):
        claims.append(ResearchClaim(text=item.get("text", ""), claim_type=ResearchClaimType.assumption, claim_kind=DossierClaimKind.assumption, confidence=item.get("confidence", "medium"), evidence_ids=item.get("evidence_ids", []), unsupported=True, requires_validation=True, section_ids=["key_assumptions"]))
    pricing_ids = [evidence_id for line in pricing.get("line_items", []) for evidence_id in line.get("evidence_ids", [])]
    claims.append(ResearchClaim(text=f"DERIVED_CALCULATION: Expected monthly estimate is ${pricing.get('expected_monthly_usd', 0)} and must equal the sum of pricing line items.", claim_type=ResearchClaimType.cost_estimate, claim_kind=DossierClaimKind.derived_calculation, confidence="medium", evidence_ids=list(dict.fromkeys(pricing_ids)), unsupported=not bool(pricing_ids), requires_validation=True, section_ids=["pricing_analysis"]))
    for row in service_rows:
        claims.append(ResearchClaim(text=f"RECOMMENDATION: Use {row.get('selected_service')} for {row.get('capability')}; validation remains required where listed.", claim_type=ResearchClaimType.aws_service_capability, claim_kind=DossierClaimKind.recommendation, confidence="medium", evidence_ids=row.get("evidence_ids", []), unsupported=not bool(row.get("evidence_ids")), requires_validation=bool(row.get("required_validation")), section_ids=["service_decision_matrix"]))
    for risk in risks:
        claims.append(ResearchClaim(text=f"RISK: {risk.risk}", claim_type=ResearchClaimType.risk, claim_kind=DossierClaimKind.risk, confidence="medium", evidence_ids=risk.evidence_ids, unsupported=not bool(risk.evidence_ids), requires_validation=risk.blocking_status == "blocking", section_ids=["risk_matrix"]))
    if not any(item.get("source_type") == "web" for item in evidence_items):
        claims.append(ResearchClaim(text="Assumption: competitor landscape is directional because no authoritative competitor web evidence was available in this run.", claim_type=ResearchClaimType.competitor, claim_kind=DossierClaimKind.assumption, confidence="low", evidence_ids=[], unsupported=True, requires_validation=True, section_ids=["competitive_landscape"]))
    return claims


def _consistency_check(*, report: dict, pricing: dict, claims: list[ResearchClaim], pricing_lines: list[DossierPricingLine], diagrams: list[dict], evidence_quality: dict, readiness: dict, profile: dict) -> DossierConsistencyCheck:
    errors = []
    warnings = []
    line_sum = round(sum(float(line.monthly_estimate or 0) for line in pricing_lines), 2)
    expected = round(float(pricing.get("expected_monthly_usd") or 0), 2)
    if abs(line_sum - expected) > 0.01:
        errors.append(f"Pricing total mismatch: line items sum to {line_sum}, report expected total is {expected}.")
    if any(line.evidence_type == DossierPricingEvidenceClass.heuristic for line in pricing_lines):
        warnings.append("Heuristic pricing line items are present; procurement readiness is No.")
    pricing_metadata = pricing.get("metadata") or {}
    if pricing_metadata.get("status") == "invalid_extracted_scale_not_applied":
        errors.append(f"Pricing invalid: {pricing_metadata.get('reason')}")
    unsupported_aws = [claim.id for claim in claims if claim.claim_type == ResearchClaimType.aws_service_capability and claim.unsupported and not claim.requires_validation]
    if unsupported_aws:
        errors.append(f"Unsupported AWS capability claims were not downgraded: {', '.join(unsupported_aws)}.")
    unsupported_competitor = [claim.id for claim in claims if claim.claim_type == ResearchClaimType.competitor and claim.unsupported and claim.claim_kind != DossierClaimKind.assumption]
    if unsupported_competitor:
        errors.append(f"Unsupported competitor claims must be assumptions: {', '.join(unsupported_competitor)}.")
    compliance_text = " ".join(section for section in [report.get("feasibility_analysis", ""), report.get("viability_analysis", "")]).lower()
    if "compliance" in compliance_text and "final compliance depends" not in compliance_text:
        warnings.append("Compliance language must carry the shared-responsibility caveat in the dossier.")
    if readiness.get("status") == "customer_ready" and evidence_quality.get("evidence_authority") in {"limited", "weak"}:
        errors.append("Customer-ready status is not allowed when evidence authority is limited or weak.")
    if _diagram_qa_failed(diagrams):
        errors.append("Diagram QA failed; dossier cannot be customer-ready.")
    if _diagram_requested_views_missing(diagrams):
        warnings.append("Diagram QA passed, but requested semantic views were not fully rendered by the existing compiler.")
    if readiness.get("status") == "customer_ready" and any(line.evidence_type == DossierPricingEvidenceClass.heuristic for line in pricing_lines):
        errors.append("Customer-ready status is not allowed while major pricing lines remain heuristic.")
    if "rag_assistant" in profile.get("excluded_families", []) and "rag" in " ".join(profile.get("workload_families", [])).lower():
        errors.append("RAG language conflicts with excluded workload families.")
    return DossierConsistencyCheck(passed=not errors, errors=errors, warnings=warnings)


def _quality_score(*, evidence_quality: dict, pricing_lines: list[DossierPricingLine], consistency: DossierConsistencyCheck, production_gallery: dict, readiness: dict, service_rows: list[dict], risks: list[RiskRecord]) -> DossierQualityScore:
    evidence_score = {"strong": 9, "mixed": 7, "limited": 4, "weak": 2}.get(evidence_quality.get("evidence_authority"), 3)
    pricing_score = 8 if pricing_lines and all(line.evidence_type != DossierPricingEvidenceClass.heuristic for line in pricing_lines) else 5
    if any(line.evidence_type == DossierPricingEvidenceClass.sku_tier_backed for line in pricing_lines):
        pricing_score = min(9, pricing_score + 1)
    architecture_score = 8 if production_gallery.get("missing_requested_views") == [] else 5
    feasibility_score = 7 if risks else 5
    risk_score = 8 if len(risks) >= 4 else 6
    competitor_score = 7 if evidence_quality.get("evidence_authority") in {"strong", "mixed"} else 4
    compliance_score = 7
    consistency_score = 9 if consistency.passed else 3
    overall = round((evidence_score + pricing_score + architecture_score + feasibility_score + risk_score + competitor_score + compliance_score + consistency_score) / 8)
    status = _dossier_readiness(readiness, consistency, pricing_score, architecture_score)
    return DossierQualityScore(evidence_score=evidence_score, pricing_score=pricing_score, architecture_score=architecture_score, feasibility_score=feasibility_score, risk_score=risk_score, competitor_score=competitor_score, compliance_score=compliance_score, consistency_score=consistency_score, overall_score=overall, readiness_status=status)


def _sections(**ctx) -> dict[str, str]:
    return {
        "cover_summary": _cover_summary(ctx),
        "executive_verdict": _executive_verdict(ctx),
        "use_case_interpretation": _use_case_interpretation(ctx),
        "confirmed_requirements": _confirmed_requirements(ctx),
        "key_assumptions": _key_assumptions(ctx),
        "evidence_quality": _evidence_quality(ctx),
        "architecture_recommendation": _architecture_recommendation(ctx),
        "service_decision_matrix": _service_decision_matrix(ctx),
        "technical_feasibility": _technical_feasibility(ctx),
        "pricing_analysis": _pricing_analysis(ctx),
        "cost_sensitivity": _cost_sensitivity(ctx),
        "competitive_landscape": _competitive_landscape(ctx),
        "key_differentiators": _key_differentiators(ctx),
        "security_compliance": _security_compliance(ctx),
        "reliability_resilience": _reliability_resilience(ctx),
        "performance_scalability": _performance_scalability(ctx),
        "operational_readiness": _operational_readiness(ctx),
        "risk_matrix": _risk_matrix(ctx),
        "implementation_roadmap": _implementation_roadmap(ctx),
        "validation_plan": _validation_plan(ctx),
        "final_recommendation": _final_recommendation(ctx),
        "evidence_appendix": _evidence_appendix(ctx),
    }


def _cover_summary(ctx: dict) -> str:
    brief = ctx["brief"]
    profile = ctx["profile"]
    quality = ctx["quality"]
    evidence_quality = ctx["evidence_quality"]
    readiness = ctx["readiness"]
    lines = [
        "## Cover Summary",
        "",
        f"Use case title: {brief.get('title', 'Untitled')}",
        f"Industry: {display_label(brief.get('industry') or profile.get('domain') or '') or 'Requires validation'}",
        f"Workload family: {', '.join(display_label(family) for family in profile.get('workload_families', [])) or 'Requires validation'}",
        "Research depth: Deep dossier",
        f"Generated timestamp: {ctx['generated_at'].isoformat()}",
        f"Evidence authority status: {display_label(evidence_quality.get('evidence_authority', 'unknown'))}",
        f"Pricing confidence: {quality.pricing_score}/10",
        f"Customer-readiness status: {display_label(quality.readiness_status.value)}",
        f"Recommendation verdict: {ctx['verdict']}",
        f"Pricing status: {_cost_range(ctx['pricing'])}",
        "",
        "Top validation gates:",
        *[f"- {gate_display(item)}" for item in ctx["top_gates"][:3]],
    ]
    return "\n".join(lines)


def _executive_verdict(ctx: dict) -> str:
    report = ctx["report"]
    risks = ctx["risks"]
    top_risk = risks[0].risk if risks else "Pricing and operational validation remain open."
    validation = gate_display(ctx["top_gates"][0]) if ctx["top_gates"] else "Refresh evidence and pricing before procurement."
    direction = report.get("recommended_production_direction") or "an AWS-native architecture with governed operations, evidence discipline, and explicit pricing validation"
    return "\n".join([
        "## Executive Verdict",
        "",
        _end_sentence(f"{ctx['verdict']}: Archway recommends proceeding only through a staged AWS-native path, starting with a scoped POC and moving to production after the validation gates pass. The recommended direction is {direction}"),
        "",
        _end_sentence(f"The biggest reason to proceed is that the extracted workload capabilities align with managed AWS building blocks for ingestion, event processing, model lifecycle, workflow integration, audit, and observability. {_end_sentence(f'The biggest risk is {top_risk}')} Before production, the customer must validate: {validation}"),
    ])


def _use_case_interpretation(ctx: dict) -> str:
    brief = ctx["brief"]
    profile = ctx["profile"]
    non_goals = profile.get("excluded_families") or profile.get("excluded_patterns") or []
    return "\n".join([
        "## Use Case Interpretation",
        "",
        f"Archway understood the business problem as: {_presentation_text(brief.get('refined_problem_statement') or brief.get('raw_use_case', ''))}",
        "",
        f"Target users/personas: {', '.join(item.get('name', '') for item in brief.get('users', [])) or 'Requires validation'}.",
        f"Operational outcome: {', '.join(brief.get('business_goals', [])) or 'Requires validation'}.",
        f"System behavior: {brief.get('production_scope', '')}",
        f"Deployment posture: {', '.join(profile.get('deployment_posture', [])) or 'Requires validation'}.",
        f"AI/ML workload family: {', '.join(profile.get('workload_families', [])) or 'Requires validation'}.",
        f"Non-goals and excluded patterns: {', '.join(non_goals) or 'None identified'}.",
        "",
        "This interpretation is classified as FACT only where it comes from user input; the architecture direction is a RECOMMENDATION that remains subject to validation gates.",
    ])


def _confirmed_requirements(ctx: dict) -> str:
    return "## Confirmed Requirements\n\n" + _table(
        ["Requirement", "Value", "Source", "Architecture impact", "Pricing impact", "Confidence"],
        [[r.requirement, r.value, r.source, r.architecture_impact, r.pricing_impact, r.confidence] for r in ctx["requirements"]],
    )


def _key_assumptions(ctx: dict) -> str:
    return "## Key Assumptions\n\n" + _table(
        ["Assumption", "Confidence", "Why needed", "Impacts", "If wrong", "Validation method", "Used in pricing?", "Used in architecture?"],
        [[a.assumption, a.confidence, a.why_needed, ", ".join(a.impacts), a.if_wrong, a.validation_method, "yes" if a.used_in_pricing else "no", "yes" if a.used_in_architecture else "no"] for a in ctx["assumptions"]],
    )


def _evidence_quality(ctx: dict) -> str:
    quality = ctx["evidence_quality"]
    readiness = ctx["readiness"]
    lines = [
        "## Evidence Quality and Research Limitations",
        "",
        f"AWS official docs available? {_yes_no(quality.get('aws_docs_available'))}",
        f"AWS Pricing evidence available? {_yes_no(quality.get('aws_pricing_available'))}",
        f"Competitor web evidence available? {_yes_no(any(item.get('source_type') == 'web' for item in ctx['evidence_items']))}",
        f"Evidence authority: {display_label(quality.get('evidence_authority', 'unknown'))}",
        f"Customer readiness: {display_label(ctx['quality'].readiness_status.value)}",
        "",
        "Limitations:",
        *[f"- {item}" for item in quality.get("limitations", []) or ["No limitations recorded."]],
        *[f"- {item}" for item in readiness.get("warnings", [])],
    ]
    return "\n".join(lines)


def _architecture_recommendation(ctx: dict) -> str:
    report = ctx["report"]
    profile = ctx["profile"]
    return "\n".join([
        "## Architecture Recommendation",
        "",
        f"Recommended architecture pattern: AWS-native {', '.join(profile.get('workload_families', [])) or 'enterprise workload'} with governed POC-to-production progression.",
        "",
        f"POC architecture: {report.get('recommended_poc', '')}",
        "",
        f"Production architecture: {report.get('recommended_production_direction', '')}",
        "",
        "Why this pattern fits: the service decisions map extracted capabilities to AWS ingestion, analytics, model, workflow, security, observability, and integration services. What not to build first: direct production write automation, unbounded retention, unsupported RAG/chatbot flows for non-RAG workloads, or procurement-grade budgets before pricing refresh.",
        "",
        f"Hybrid/edge/on-prem requirement: {', '.join(profile.get('deployment_posture', [])) or 'No explicit hybrid posture detected'}; any external systems in diagrams are represented as existing customer integration actors, not recommended non-AWS platform services.",
    ])


def _service_decision_matrix(ctx: dict) -> str:
    rows = []
    for row in ctx["service_rows"]:
        alternatives = row.get("options_considered") or []
        rows.append([
            row.get("capability", ""),
            row.get("selected_service", ""),
            ", ".join(item.get("service_name", "") for item in alternatives[:4]) or "None listed",
            row.get("selection_reason") or row.get("selected_service_rationale", ""),
            "; ".join(item.get("rationale", "") for item in alternatives[:2]) or "Alternatives require validation.",
            "; ".join(risk for item in alternatives for risk in item.get("risks", [])[:1]) or "Validate fit and limits.",
            ", ".join(row.get("evidence_ids", [])) or "Requires validation",
            "; ".join(row.get("required_validation", [])) or "Validate before production.",
        ])
    return "## AWS Service Decision Matrix\n\n" + _table(["Capability", "Recommended AWS service/pattern", "Alternatives considered", "Why selected", "Why alternatives were not selected", "Risks", "Evidence", "Validation needed"], rows)


def _technical_feasibility(ctx: dict) -> str:
    return "## Technical Feasibility Matrix\n\n" + _table(
        ["Requirement", "Candidate design", "AWS capability", "Feasibility verdict", "Key risk", "Validation method", "Evidence"],
        [[r.requirement, r.candidate_design, r.aws_capability, r.feasibility_verdict, r.key_risk, r.validation_method, ", ".join(r.evidence_ids) or "Requires validation"] for r in ctx["feasibility"]],
    )


def _pricing_analysis(ctx: dict) -> str:
    pricing = ctx["pricing"]
    closure = (pricing.get("metadata") or {}).get("pricing_driver_closure") or {}
    lines = ctx["pricing_lines"]
    backed = sum(line.monthly_estimate or 0 for line in lines if line.evidence_type != DossierPricingEvidenceClass.heuristic)
    heuristic = sum(line.monthly_estimate or 0 for line in lines if line.evidence_type == DossierPricingEvidenceClass.heuristic)
    procurement = "No" if heuristic or any(line.validation_needed for line in lines) else "Yes"
    return "\n".join([
        "## Pricing Analysis",
        "",
        f"Pricing confidence: {ctx['quality'].pricing_score}/10",
        f"Low / expected / high estimate: {_usd(pricing.get('low_monthly_usd', 0))} / {_usd(pricing.get('expected_monthly_usd', 0))} / {_usd(pricing.get('high_monthly_usd', 0))} per month",
        f"POC estimate: directional and scoped by the POC architecture; validate with POC burn-in.",
        f"Production estimate: {_cost_range(pricing)}",
        f"Pricing-backed subtotal: {_usd(backed)}",
        f"Heuristic subtotal: {_usd(heuristic)}",
        f"Procurement readiness: {procurement}",
        "Reason: exact SKU/tier quantities remain unresolved for any line marked HEURISTIC or PRICE_LIST_CATALOG_BACKED.",
        "",
        "### Pricing Driver Closure",
        f"Closure status: {closure.get('status', 'unknown')}",
        f"Pricing maturity: {closure.get('pricing_maturity', (pricing.get('metadata') or {}).get('pricing_maturity', 'unknown'))}",
        f"Scenario profile used: {closure.get('scenario_profile_used') or 'None'}",
        f"Procurement readiness: {closure.get('procurement_ready', False)}",
        "This pricing is scenario-based and not procurement-ready." if closure.get("scenario_profile_used") else "No scenario profile was selected.",
        "",
        "Confirmed drivers:",
        *[f"- {item}" for item in closure.get("confirmed_drivers", [])],
        "",
        "Assumed drivers:",
        *[f"- {item}" for item in closure.get("assumed_drivers", [])],
        "",
        "Missing drivers:",
        *[f"- {item.get('display_name')}: {item.get('why_needed')}" for item in closure.get("missing_drivers", [])],
        "",
        "Next validation steps:",
        *[f"- {item}" for item in closure.get("next_validation_steps", [])],
        "",
        "Main cost drivers:",
        *[f"- {item}" for item in pricing.get("main_cost_drivers", [])],
        "",
        _table(["Service", "Usage driver", "Quantity", "Formula", "Unit price", "Monthly estimate", "Evidence type", "SKU / usage type / rate code", "Confidence", "Validation needed"], [[line.service, line.usage_driver, line.quantity, line.formula.formula_text, line.unit_price, str(line.monthly_estimate), line.evidence_type.value, line.sku_usage_rate, line.confidence, line.validation_needed] for line in lines]),
    ])


def _cost_sensitivity(ctx: dict) -> str:
    pricing = ctx["pricing"]
    if _is_media_profile(ctx["profile"]):
        fallback = ["viewer-hours", "average bitrate", "regional traffic mix", "CDN cache-hit ratio", "channel-hours", "ad decision volume"]
    else:
        fallback = ["event rate", "message size", "workflow execution rate"]
    variables = pricing.get("unknown_variables", [])[:6] or fallback
    rows = [[item, "current dossier assumption", "50% of base", "200% of base", "Material; quantify in burn-in", "It controls one or more line-item quantities."] for item in variables]
    return "## Cost Sensitivity Analysis\n\n" + _table(["Variable", "Base assumption", "Low case", "High case", "Monthly cost impact", "Why it matters"], rows)


def _competitive_landscape(ctx: dict) -> str:
    report = ctx["report"]
    web = [item for item in ctx["evidence_items"] if item.get("source_type") == "web"]
    evidence = ", ".join(item.get("id") for item in web) if web else "Assumed - requires validation"
    rows = [
        ["Commercial platforms", "commercial", "Requires validation", "May include packaged workflow and domain features.", "Pricing and model transparency may be unclear.", "Pricing not publicly available from reviewed sources.", "medium", evidence],
        ["Cloud-native AWS build", "cloud-native", "Strong directional fit", "AWS-native services, model ownership, auditability, and staged delivery.", "Requires integration, security, and pricing validation.", _cost_range(ctx["pricing"]), "medium", ", ".join(_evidence_ids(ctx["evidence_items"], {"aws_docs", "aws_pricing"})) or "Requires validation"],
        ["Open-source/self-managed stack", "open-source", "Possible but higher operations burden", "Maximum control and portability.", "Customer owns scaling, patching, compliance evidence, and SRE burden.", "Requires validation", "medium", "Assumed - requires validation"],
        ["Incumbent enterprise systems", "incumbent", "Integration target, not replacement", "May already own operational, inventory, clinical, or case data.", "May constrain API, latency, identity, and workflow design.", "Existing customer cost; not estimated", "low", "User input"],
    ]
    return "\n".join([
        "## Competitive and Alternative Landscape",
        "",
        report.get("competitor_analysis", "Competitive analysis is directional and requires external validation."),
        "",
        _table(["Alternative", "Category", "Fit", "Strengths", "Weaknesses", "Cost visibility", "Lock-in risk", "Evidence"], rows),
        "",
        "Build-vs-buy tradeoff: AWS-native is recommended when the customer values model ownership, staged delivery, and integration with existing AWS governance. It may be weaker than a packaged vertical platform where prebuilt domain workflow, vendor-managed model operations, or bundled support matter more.",
    ])


def _key_differentiators(ctx: dict) -> str:
    evidence = ", ".join(_evidence_ids(ctx["evidence_items"], {"aws_docs", "local_policy"})) or "Requires validation"
    poc_text = "The POC can validate playback latency, QoE, rights enforcement, ad consent, and cost burn-in." if _is_media_profile(ctx["profile"]) else "The POC can validate event processing, scoring, false positives, and action policy before direct automation."
    rows = [
        ["Model ownership", "SageMaker-oriented model lifecycle keeps training, registry, approval, and deployment under customer control.", evidence],
        ["Event-driven auditability", "Streams, events, queues, and workflow records create a natural operational trace.", evidence],
        ["Reduced infrastructure operations", "Managed AWS services reduce customer-owned cluster and patching work compared with self-managed stacks.", evidence],
        ["Hybrid integration posture", "External systems remain integration actors while AWS hosts the platform services.", "User input, architecture metadata"],
        ["Faster POC path", poc_text, "User input, local policy"],
    ]
    return "## Key Differentiators\n\n" + _table(["Differentiator", "Why it matters", "Evidence"], rows)


def _security_compliance(ctx: dict) -> str:
    data_text = "Viewer, ad decision, consent, entitlement, and QoE events may be sensitive." if _is_media_profile(ctx["profile"]) else "Operational events may be sensitive."
    classify_text = "Classify viewer identifiers, consent records, playback events, ad metadata, and operator identities." if _is_media_profile(ctx["profile"]) else "Classify operational events, metadata, and operator identities."
    rows = [
        ["Critical infrastructure / sensitive operations", "Use least privilege, approval gates, and incident audit.", "IAM, KMS, CloudTrail, CloudWatch, policy-gated workflows.", "Define operating policy and approval thresholds.", "local policy / AWS docs", "Security design review"],
        ["Data classification", data_text, "Encryption, retention policy, data lake partitioning.", classify_text, "user input", "Data classification workshop"],
        ["Network boundaries", "Private enterprise integrations are production gates.", "VPC-resident adapters, private routes, logs.", "Firewall, DNS, identity, routing, and failover ownership.", "architecture", "Network validation test"],
        ["Compliance caveat", "AWS eligibility is not workload compliance.", "Use eligible services and evidence collection.", "Final compliance depends on customer configuration, operations, evidence, and auditor/regulator validation.", "local policy", "Auditor/regulator review"],
    ]
    return "## Security and Compliance Analysis\n\nUsing AWS services that are eligible for a compliance program does not automatically make the workload compliant. Final compliance depends on customer configuration, operational controls, evidence, and auditor/regulator validation.\n\n" + _table(["Requirement / regulation", "Architecture implication", "AWS control/pattern", "Customer-owned control", "Evidence", "Validation needed"], rows)


def _reliability_resilience(ctx: dict) -> str:
    rows = [
        ["Regional failure", "Service interruption and delayed detection/action.", "Regional health alarms and DR runbook.", "Multi-region strategy or accepted RTO/RPO.", "Residual risk remains until DR test."],
        ["AZ failure", "Reduced capacity for ingestion, scoring, or adapters.", "Multi-AZ managed services where available.", "Confirm subnet/AZ placement and scaling.", "Capacity may degrade during failover."],
        ["Stream backlog", "Delayed anomaly detection or downstream action.", "Iterator age/backlog alarms and autoscaling.", "Backpressure and replay runbooks.", "Peak event bursts can still affect latency."],
        ["Model endpoint degradation", "Missed or late predictions.", "Health checks, fallback thresholds, and approval queues.", "Shadow scoring and rollback.", "Model quality remains customer-owned."],
        ["External system unavailable", "Downstream operational update fails.", "Queue, retry, dead-letter, idempotent adapter.", "Manual fallback process.", "Operational SLA depends on customer system."],
        ["Human approval bottleneck", "High-impact actions wait too long.", "Priority queues and escalation rules.", "On-call ownership and staffing.", "Surges may still require manual triage."],
    ]
    return "## Reliability and Resilience Analysis\n\n" + _table(["Failure mode", "Impact", "Detection", "Mitigation", "Residual risk"], rows)


def _performance_scalability(ctx: dict) -> str:
    profile = ctx["profile"]
    if _is_media_profile(profile):
        peak = "Peak throughput: requires validation from peak concurrent viewers, bitrate ladder, regional traffic mix, CDN cache behavior, and ad/QoE event rates."
        scale = "Compute scaling strategy: scale live channels, origin packaging, CDN delivery, edge policy evaluation, ad decisions, and QoE event processing from measured POC load."
        buffering = "Queue/stream buffering and backpressure: use stream/queue buffers for playback analytics, ad decisions, rights-policy updates, archives, and downstream reporting."
        quotas = "Quotas requiring validation: MediaLive channel profiles, MediaPackage/origin request limits, CloudFront request and data-transfer tiers, edge function limits, MediaTailor ad decision limits, and analytics/log throughput."
        load = "Load test plan: replay representative live events, simulate viewer concurrency and regional mix, measure glass-to-glass latency/QoE, verify blackout/DRM/consent behavior, and compare expected AWS cost burn."
    else:
        peak = "Peak throughput: requires validation from workload event rate, message size, and operational action rate."
        scale = "Compute scaling strategy: scale stream processing capacity, model endpoints, queue consumers, and adapters from measured POC load."
        buffering = "Queue/stream buffering and backpressure: use streams and queues to decouple producers, model scoring, workflows, and external systems."
        quotas = "Quotas requiring validation: stream shards/throughput, Flink KPU capacity, model endpoint concurrency, API limits, workflow transitions, logs, and private connectivity limits."
        load = "Load test plan: replay representative events, inject peak bursts, measure end-to-end latency, verify backlog recovery, and compare expected AWS cost burn."
    return "\n".join([
        "## Performance and Scalability Analysis",
        "",
        f"Expected throughput: derived from confirmed metrics and assumptions; raw profile metrics include {len(profile.get('metrics', []))} extracted entries.",
        peak,
        f"Latency target: {profile.get('latency_target') or profile.get('latency_class') or 'Requires validation'}.",
        scale,
        buffering,
        quotas,
        load,
    ])


def _operational_readiness(ctx: dict) -> str:
    rows = [
        ["Monitoring", "CloudWatch dashboards for ingest, processing, scoring, queues, adapters, and cost signals."],
        ["Alarms", "Backlog, error rate, model latency, false-positive proxy metrics, failed downstream updates, dead-letter queues, and budget anomalies."],
        ["Runbooks", "Stream replay, model rollback, integration adapter failure, manual operational fallback, and security incident response."],
        ["On-call", "Named owners for platform, ML, security, network, and operations."],
        ["Change management", "Promotion gates for model versions, IaC changes, pricing assumptions, and integration policies."],
        ["Data quality checks", "Schema, missing values, drift, record identity, and timestamp quality before model scoring."],
        ["Release gates", "No direct automation until accuracy, latency, security, compliance, and rollback gates pass."],
    ]
    return "## Operational Readiness\n\n" + _table(["Area", "Required operating practice"], rows)


def _risk_matrix(ctx: dict) -> str:
    return "## Risk and Mitigation Matrix\n\n" + _table(
        ["Severity", "Risk", "Why it matters", "Likelihood", "Impact", "Mitigation", "Validation owner", "Blocking status"],
        [[r.severity, r.risk, r.why_it_matters, r.likelihood, r.impact, r.mitigation, r.validation_owner, r.blocking_status] for r in ctx["risks"]],
    )


def _implementation_roadmap(ctx: dict) -> str:
    services = ", ".join((ctx["production"].get("selected_services") or [{}])[i].get("service", "") for i in range(min(5, len(ctx["production"].get("selected_services") or [])))) or "AWS services selected in architecture"
    rows = [
        ["POC", "Representative ingest, feature extraction, shadow scoring, evidence capture.", "Latency, accuracy, false-positive baseline, and cost burn-in.", services, "Representative event replay, model quality, pricing sanity.", "4-8 weeks", "POC metrics meet agreed thresholds."],
        ["Pilot", "Limited operational workflow with human approval.", "Safe downstream recommendation path.", services, "Approval, rollback, idempotency, network.", "6-10 weeks", "Operational users accept workflow."],
        ["Production rollout", "Resilient AWS platform, private integrations, security controls, runbooks.", "Controlled automation under policy.", services, "DR, security, compliance, quotas, load.", "8-16 weeks", "Production readiness review passes."],
        ["Optimization", "Tune cost, capacity, retention, model retraining, and observability.", "Lower unit cost and better model quality.", services, "Measured cost and SLA review.", "ongoing", "Optimization backlog owned."],
    ]
    return "## Implementation Roadmap\n\n" + _table(["Phase", "Scope", "Success criteria", "AWS services", "Validation gates", "Estimated duration", "Exit criteria"], rows)


def _validation_plan(ctx: dict) -> str:
    gates = ctx["top_gates"]
    defaults = ["Full-scale load test", "Latency profiling", "Model accuracy validation", "False positive / false negative validation", "Quota validation", "Security control validation", "Compliance audit readiness", "DR test", "Network failover test", "Cost burn-in test"]
    return "## Validation Plan\n\n" + "\n".join(f"- OPEN_VALIDATION_ITEM: {gate_display(item)}" for item in list(dict.fromkeys(gates + defaults)))


def _final_recommendation(ctx: dict) -> str:
    if _is_media_profile(ctx["profile"]):
        driver_action = "- Confirm workload drivers: viewer-hours, bitrate ladder, regional traffic mix, CDN cache-hit ratio, channel-hours, ad decisions, DRM license volume, QoE event rate, and archive retention."
    else:
        driver_action = "- Confirm workload drivers: event rate, message size, retention, anomaly rates, and approval rates."
    return "\n".join([
        "## Final Recommendation",
        "",
        f"Verdict: {ctx['verdict']}.",
        "Why: the architecture direction is credible for AWS, but readiness depends on evidence, pricing, integration, security, and operational validation rather than prose confidence.",
        "",
        "Conditions:",
        *[f"- {gate_display(item)}" for item in ctx["top_gates"][:5]],
        "",
        "Next three actions:",
        driver_action,
        "- Run the POC with measured load, model quality, security controls, and cost burn-in.",
        "- Refresh AWS Docs/Pricing evidence and review the dossier with architecture, security, finance, and operations owners.",
        "",
        f"Customer-readiness status: {display_label(ctx['quality'].readiness_status.value)}.",
    ])


def _is_media_profile(profile: dict) -> bool:
    families = set(profile.get("workload_families") or [])
    capabilities = set(profile.get("capabilities") or []) | set(profile.get("capability_model") or [])
    return bool({"live_streaming", "media_streaming"} & families or "video_streaming" in capabilities)


def _evidence_appendix(ctx: dict) -> str:
    rows = []
    for item in ctx["evidence_items"]:
        assessment = ctx["assessments"].get(item.get("id"), {})
        rows.append([item.get("id"), item.get("title"), item.get("url") or "n/a", item.get("source_type"), assessment.get("source_type", "UNKNOWN"), item.get("retrieved_at", ""), _supported_claims(item.get("id"), ctx["claims"]), assessment.get("use_limitations", "Use according to source authority.")])
    return "## Evidence Appendix\n\n" + _table(["Evidence ID", "Source title", "Source URL/reference", "Source type", "Authority", "Retrieved at", "Supports claims", "Limitations"], rows)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        rows = [["n/a" for _ in headers]]
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("\n", " ").replace("|", "/")


def _usd(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"${value}"
    return f"${number:,.0f}"


def _usd_range(pricing: dict) -> str:
    low = _usd(pricing.get("low_monthly_usd", 0))
    high = _usd(pricing.get("high_monthly_usd", 0))
    expected = _usd(pricing.get("expected_monthly_usd", 0))
    return f"{low}–{high}/month, expected ≈ {expected}"


def _end_sentence(text: str) -> str:
    text = str(text or "").rstrip()
    while text.endswith(".."):
        text = text[:-1]
    if not text or text.endswith((".", "?", "!")):
        return text
    return text + "."


def _cost_range(pricing: dict) -> str:
    if not pricing:
        return "Not estimated"
    metadata = pricing.get("metadata") or {}
    closure = metadata.get("pricing_driver_closure") or {}
    if metadata.get("pricing_scenario_validity") == "invalid_driver_mismatch" or metadata.get("status") == "invalid_driver_mismatch":
        return f"Pricing scenario needs repair: {metadata.get('reason') or 'driver set does not match the confirmed workload.'}"
    if metadata.get("pricing_maturity") == "pricing_customer_demo_ready" or closure.get("directional_scenario_allowed"):
        return f"Directional scenario estimate, not procurement-ready: {_usd_range(pricing)}. Replace scenario assumptions with measured workload telemetry, event history, and customer traffic forecasts before budgeting."
    if metadata.get("pricing_can_be_displayed_as_headline") is False:
        return "Directional placeholder only - not headline-safe. Cost range is intentionally withheld from the executive headline; see Pricing Trace for rough-order calculation details."
    if metadata.get("status") == "invalid_extracted_scale_not_applied":
        return f"Pricing invalid until extracted scale is applied: {metadata.get('reason')}"
    if metadata.get("status") == "directional_only_missing_core_compute_drivers":
        return f"Directional only until core compute/SKU drivers are confirmed: {metadata.get('reason')}"
    return _usd_range(pricing)


def _pricing_evidence_class(item: dict) -> DossierPricingEvidenceClass:
    trace = item.get("pricing_trace") or {}
    evidence_class = trace.get("evidence_class")
    if evidence_class == "not_estimated":
        return DossierPricingEvidenceClass.not_estimated
    if evidence_class == "sku_tier_backed":
        return DossierPricingEvidenceClass.sku_tier_backed
    if evidence_class == "price_catalog_referenced":
        return DossierPricingEvidenceClass.price_list_catalog_backed
    if trace.get("sku") or trace.get("rate_code"):
        return DossierPricingEvidenceClass.sku_tier_backed
    if trace.get("service_code") and trace.get("price_list_evidence_id"):
        return DossierPricingEvidenceClass.price_list_catalog_backed
    if any(str(evidence_id).startswith("ev_") for evidence_id in item.get("evidence_ids", [])):
        return DossierPricingEvidenceClass.heuristic if not trace.get("price_list_evidence_id") else DossierPricingEvidenceClass.price_list_catalog_backed
    return DossierPricingEvidenceClass.heuristic


def _pricing_validation_needed(evidence_class: DossierPricingEvidenceClass, trace: dict) -> str:
    if evidence_class == DossierPricingEvidenceClass.sku_tier_backed:
        return "Confirm quantities and effective date before procurement."
    if evidence_class == DossierPricingEvidenceClass.price_list_catalog_backed:
        return "Map offer catalog evidence to exact SKU, usage type, region tier, and quantity."
    return trace.get("reason") or "Refresh with AWS Pricing MCP or AWS Pricing Calculator before budget approval."


def _verdict(readiness: dict, consistency: DossierConsistencyCheck, pricing_lines: list[DossierPricingLine], risks: list[RiskRecord]) -> str:
    if not consistency.passed:
        return "RESEARCH REQUIRED"
    if any(risk.blocking_status == "blocking" for risk in risks):
        return "CONDITIONAL GO"
    if readiness.get("status") == "customer_ready" and all(line.evidence_type != DossierPricingEvidenceClass.heuristic for line in pricing_lines):
        return "GO"
    return "CONDITIONAL GO"


def _dossier_readiness(readiness: dict, consistency: DossierConsistencyCheck, pricing_score: int, architecture_score: int) -> DossierReadinessStatus:
    if not consistency.passed:
        return DossierReadinessStatus.failed_validation
    status = readiness.get("status")
    if status == "internal_only":
        return DossierReadinessStatus.internal_only
    if status == "failed_validation":
        return DossierReadinessStatus.failed_validation
    if status == "directional_only":
        return DossierReadinessStatus.directional_only
    if status in {"customer_demo_ready_with_caveats", "demo_ready_with_caveats"}:
        return DossierReadinessStatus.customer_demo_ready_with_caveats
    if readiness.get("status") == "customer_ready" and pricing_score >= 8 and architecture_score >= 8:
        return DossierReadinessStatus.customer_ready
    if architecture_score >= 8 and pricing_score >= 5:
        return DossierReadinessStatus.customer_demo_ready_with_caveats
    return DossierReadinessStatus.directional_only


def _validation_gates(brief: dict, metadata: dict, pricing: dict, risks: list[RiskRecord]) -> list[str]:
    gates = []
    gates.extend(item.get("text", "") for item in brief.get("open_questions", []) if item.get("text"))
    for record in metadata.get("service_decision_records", []):
        gates.extend(record.get("required_validation", []))
    gates.extend(pricing.get("unknown_variables", [])[:4])
    gates.extend(risk.risk for risk in risks if risk.blocking_status == "blocking")
    return dedupe_canonical([item for item in dict.fromkeys(gates) if item])


def _production_architecture(architectures: list[dict]) -> dict:
    return next((item for item in architectures if item.get("mode") == "production"), architectures[-1] if architectures else {})


def _production_gallery(diagrams: list[dict]) -> dict:
    return next((item for item in diagrams if item.get("mode") == "production"), diagrams[-1] if diagrams else {})


def _diagram_qa_failed(diagrams: list[dict]) -> bool:
    for gallery in diagrams:
        for qa in gallery.get("qa_reports", []):
            if not qa.get("passed", False) and _diagram_qa_is_render_blocking(qa):
                return True
    return False


def _diagram_qa_is_render_blocking(qa: dict) -> bool:
    diagnostics = qa.get("diagnostics") or []
    if not diagnostics:
        return True
    text = " ".join(str(item) for item in diagnostics).lower()
    render_failure_terms = (
        "blank",
        "empty svg",
        "compile",
        "syntax",
        "renderer failed",
        "png failed",
        "svg failed",
        "missing artifact",
        "file not found",
    )
    if any(term in text for term in render_failure_terms):
        return True
    return any(
        str(item.get("severity") if isinstance(item, dict) else "").lower() in {"critical", "error", "fatal"}
        and str(item.get("code") if isinstance(item, dict) else "").lower() not in {"too_many_edge_crossings", "aws_service_catalog_fallback"}
        for item in diagnostics
    )


def _diagram_requested_views_missing(diagrams: list[dict]) -> bool:
    return any(bool(gallery.get("missing_requested_views")) for gallery in diagrams)


def _first_evidence(evidence_items: list[dict], source_types: set[str]) -> str | None:
    item = next((evidence for evidence in evidence_items if evidence.get("source_type") in source_types), None)
    return item.get("id") if item else None


def _evidence_ids(evidence_items: list[dict], source_types: set[str]) -> list[str]:
    return [item.get("id") for item in evidence_items if item.get("source_type") in source_types and item.get("id")]


def _supported_claims(evidence_id: str, claims: list[ResearchClaim]) -> str:
    ids = [claim.id for claim in claims if evidence_id in claim.evidence_ids]
    return ", ".join(ids) if ids else "No direct claim mapping"


def _yes_no(value: Any) -> str:
    return "yes" if value else "no"


def _metric_arch_impact(metric: dict) -> str:
    kind = metric.get("kind")
    if kind == "asset_count":
        return "Drives ingestion, partitioning, storage, observability, and rollout scope."
    if kind in {"target_duration", "current_duration"}:
        return "Drives latency, workflow, and operational response requirements."
    if kind == "target_percent":
        return "Drives outcome measurement and model validation."
    return "Drives scope and validation."


def _metric_pricing_impact(metric: dict) -> str:
    return "Drives event volume and managed-service capacity." if metric.get("kind") == "asset_count" else "May affect capacity, retention, or operational cost."


def _if_wrong(impact: str) -> str:
    return {
        "pricing": "Cost ranges and procurement readiness may be materially wrong.",
        "performance": "Latency, throughput, and capacity design may miss the target.",
        "security": "Controls may be too weak or too heavy for the real risk.",
        "compliance": "Audit or regulator expectations may not be met.",
        "architecture": "Service selection, integration pattern, or rollout phase may need revision.",
    }.get(impact, "Scope and delivery plan may need revision.")


def _validation_method(impact: str) -> str:
    return {
        "pricing": "Validate with measured workload drivers, AWS Pricing Calculator, and Pricing MCP.",
        "performance": "Run representative load, latency, and failure-mode tests.",
        "security": "Review threat model, IAM, encryption, network, and audit controls.",
        "compliance": "Review with compliance owner, auditor, or regulator as applicable.",
        "architecture": "Validate through POC, architecture review, and service quota checks.",
    }.get(impact, "Validate with customer owner before production.")


def _risk_why(title: str) -> str:
    lower = title.lower()
    if "pricing" in lower:
        return "Unvalidated costs can undermine budget approval and rollout scope."
    if "prediction" in lower or "model" in lower:
        return "Bad predictions can cause missed incidents or unnecessary operational action."
    if "action" in lower or "integration" in lower:
        return "Unsafe writes to external systems can affect operations and customers."
    if "evidence" in lower:
        return "Unsupported claims reduce customer trust and review quality."
    return "This risk can affect production readiness."


def _risk_owner(title: str) -> str:
    lower = title.lower()
    if "pricing" in lower:
        return "Cloud economist"
    if "prediction" in lower or "model" in lower:
        return "ML owner"
    if "action" in lower or "integration" in lower:
        return "Operations/integration owner"
    if "security" in lower or "sensitive" in lower:
        return "Security owner"
    return "Architecture owner"
