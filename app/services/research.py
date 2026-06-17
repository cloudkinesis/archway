from app.core.config import get_settings
from typing import Callable
from app.models.domain import (
    AWSServiceRecommendation,
    AWSServiceSelection,
    EvidenceItem,
    ResearchReport,
    RiskItem,
    SessionPhase,
    UseCaseBrief,
)
from app.services.aws_research_tools import AWSDocsAdapter, AWSPricingAdapter
from app.services.aws_price_list_query import AWSPriceListQueryClient
from app.services.display_labels import display_label
from app.services.evidence_discipline import EvidenceDisciplineService, enforce_citation_gate
from app.services.evidence_quality import summarize_evidence_quality
from app.services.pattern_catalog import pricing_dimensions, service_recommendations
from app.services.pricing import PricingEngine
from app.services.aws_price_list import AWSPriceListBulkClient
from app.services.pricing_sanity_reviewer import PricingSanityReviewer
from app.services.pricing_filter_mapper import pricing_filter_plan_for_service
from app.services.customer_readiness import assess_customer_readiness
from app.services.canonical_facts import build_canonical_fact_snapshot
from app.services.service_decisions import build_service_decision_records
from app.services.tavily import TavilySearchClient, TavilySearchResponse, tavily_response_to_evidence, tavily_session_usage
from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstandingService
from app.services.understanding.understanding_merger import UnderstandingMerger
from app.services.understanding.understanding_validator import UnderstandingValidator
from app.services.use_case_profile import profile_from_metadata, profile_to_metadata, refine_profile_with_context
from app.tooling.registry import ToolPolicyEngine, build_tool_registry


class ResearchOrchestrator:
    def __init__(self):
        self.registry = ToolPolicyEngine(build_tool_registry())
        self.pricing = PricingEngine()
        self.evidence_discipline = EvidenceDisciplineService()
        self.settings = get_settings()

    async def run_research(self, brief: UseCaseBrief, session_id: str, progress: Callable[[int, str], None] | None = None) -> ResearchReport:
        progress = progress or (lambda _progress, _message: None)
        progress(8, "Understanding use case and tool-governance constraints.")
        self.registry.assert_allowed("local_policy", SessionPhase.research, brief.model_dump(), session_id)
        profile = _profile_for_research(brief)
        progress(15, "Running domain classification and workload-family checks.")
        brief = brief.model_copy(deep=True)
        brief.use_case_profile = profile_to_metadata(profile)
        understanding = await DeepUseCaseUnderstandingService().build(brief.raw_use_case, profile, session_id)
        understanding_validation = UnderstandingValidator().validate(brief.raw_use_case, profile, understanding)
        understanding_merge = UnderstandingMerger().merge(profile, understanding)
        effective_brief = brief.model_copy(deep=True)
        effective_brief.use_case_profile = understanding_merge.profile_metadata
        profile = profile_from_metadata(effective_brief.use_case_profile, effective_brief.raw_use_case)
        effective_brief.use_case_profile = profile_to_metadata(profile)
        canonical_snapshot = build_canonical_fact_snapshot(effective_brief)
        workload_label = ", ".join(profile.workload_families)
        evidence = [
            EvidenceItem(
                source_type="local_policy",
                title="Archway workload architecture baseline",
                quote_or_summary=(
                    "Select AWS services from extracted workload capabilities; keep identity, encryption, audit, tool governance, "
                    "citation discipline, pricing assumptions, and operational safety as first-class architecture constraints."
                ),
                tool_name="local_policy",
                confidence="medium",
            ),
            EvidenceItem(
                source_type="user_input",
                title="User-provided use case",
                quote_or_summary=effective_brief.raw_use_case[:500],
                tool_name=None,
                confidence="high",
            ),
        ]
        try:
            progress(25, "Collecting AWS documentation evidence.")
            query = f"AWS architecture guidance for {profile.domain or effective_brief.industry or 'enterprise'} {workload_label} {effective_brief.title}"
            aws_docs = await AWSDocsAdapter().search(query, session_id)
            evidence.extend(aws_docs)
        except Exception as exc:
            evidence.append(
                EvidenceItem(
                    source_type="mcp",
                    title="AWS documentation MCP unavailable",
                    quote_or_summary=f"AWS documentation evidence was unavailable for this run: {type(exc).__name__}.",
                    tool_name="AWS Documentation MCP",
                    confidence="low",
                )
            )
        competitor_status = {
            "tavily_enabled": bool(self.settings.tavily_api_key and self.settings.enable_web_search),
            "competitor_scan_enabled": bool(self.settings.enable_competitor_web_search),
            "session_budget": self.settings.tavily_max_calls_per_session,
            "queries_attempted": 0,
            "queries_executed": 0,
            "results_returned": 0,
            "results_used": 0,
            "skipped_reason": None,
            "failure_reason": None,
        }
        competitor_analysis = _competitor_status_text(competitor_status)
        try:
            if self.settings.enable_competitor_web_search:
                progress(35, "Running Tavily competitor and market scan.")
                searches, scan_metadata = await _run_competitor_scan(effective_brief, profile, workload_label, session_id)
                competitor_status.update(scan_metadata)
                web_evidence = []
                for search in searches:
                    web_evidence.extend(tavily_response_to_evidence(search))
                competitor_status["results_used"] = len(web_evidence)
                if web_evidence:
                    evidence.extend(web_evidence)
                    competitor_analysis = _competitor_analysis_from_searches(searches, competitor_status)
                else:
                    competitor_status["skipped_reason"] = "Tavily returned no usable competitor or market evidence for this query."
                    competitor_analysis = _competitor_status_text(competitor_status)
            else:
                competitor_status["skipped_reason"] = (
                    "Competitor web search is disabled by configuration. Set ARCHWAY_ENABLE_WEB_SEARCH=true, "
                    "ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH=true, and a positive ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION budget to run it."
                )
                competitor_analysis = _competitor_status_text(competitor_status)
        except PermissionError as exc:
            competitor_status["skipped_reason"] = str(exc)
            competitor_analysis = _competitor_status_text(competitor_status)
        except Exception as exc:
            competitor_status["failure_reason"] = f"{type(exc).__name__}: {exc}"
            competitor_analysis = _competitor_status_text(competitor_status)
            evidence.append(
                EvidenceItem(
                    source_type="web",
                    title="Tavily web search unavailable",
                    quote_or_summary=f"Tavily search was configured but could not be used for this run: {type(exc).__name__}.",
                    tool_name="Tavily Web Search",
                    confidence="low",
                )
            )
        progress(45, "Selecting AWS services and building service-decision evidence.")
        selected = _recommend_services(effective_brief, evidence)
        progress(52, "Building workload pricing assumptions and directional estimate.")
        pricing = await self.pricing.estimate(effective_brief, selected)
        try:
            progress(60, "Collecting AWS Price List catalog evidence.")
            price_list_evidence = await AWSPriceListBulkClient().evidence_for_services([item.service for item in selected])
            pricing.evidence_items.extend(price_list_evidence)
            _attach_price_list_evidence(pricing, price_list_evidence)
        except Exception as exc:
            pricing.evidence_items.append(
                EvidenceItem(
                    source_type="aws_pricing",
                    title="AWS Price List Bulk API unavailable",
                    quote_or_summary=f"AWS Price List Bulk API service index could not be used for this run: {type(exc).__name__}.",
                    tool_name="AWS Price List Bulk API",
                    confidence="low",
                )
            )
        try:
            progress(66, "Collecting live AWS Price List query evidence.")
            query_evidence = await AWSPriceListQueryClient().evidence_for_services([item.service for item in selected], pricing.region)
            pricing.evidence_items.extend(query_evidence)
            _attach_price_list_evidence(pricing, query_evidence, source_name="AWS Price List Query API")
        except Exception as exc:
            pricing.evidence_items.append(
                EvidenceItem(
                    source_type="aws_pricing",
                    title="AWS Price List Query API unavailable",
                    quote_or_summary=f"AWS Price List Query API could not be used for this run: {type(exc).__name__}. Deterministic local pricing ranges remain directional.",
                    tool_name="AWS Price List Query API",
                    confidence="low",
                )
            )
        try:
            progress(72, "Checking AWS Pricing MCP evidence path.")
            mcp_pricing_evidence = await AWSPricingAdapter().lookup(
                [item.service for item in selected],
                pricing.region,
                session_id,
            )
            pricing.evidence_items.extend(mcp_pricing_evidence)
            _attach_price_list_evidence(pricing, mcp_pricing_evidence, source_name="AWS Labs Pricing MCP")
        except Exception as exc:
            pricing.evidence_items.append(
                EvidenceItem(
                    source_type="mcp",
                    title="AWS Pricing MCP unavailable",
                    quote_or_summary=f"AWS Pricing evidence was unavailable for this run: {type(exc).__name__}. Deterministic local pricing ranges are used until live pricing evidence is available.",
                    tool_name="AWS Pricing MCP",
                    confidence="low",
                )
            )
        progress(80, "Reviewing pricing sanity and extracted workload drivers.")
        pricing_sanity_review = await PricingSanityReviewer().review(effective_brief.raw_use_case, understanding, pricing, session_id)
        if any(issue.code == "numbers_without_metrics" and issue.severity == "critical" for issue in understanding_validation.issues):
            pricing_sanity_review.passed = False
            pricing_sanity_review.pricing_can_be_displayed_as_headline = False
            pricing_sanity_review.pricing_status = "invalid_placeholder"
            pricing.metadata = {
                **pricing.metadata,
                "status": "invalid_extracted_scale_not_applied",
                "scale_applied": False,
                "reason": "Understanding validation found explicit numbers in the use case but no extracted metrics; headline pricing is blocked.",
            }
        if not pricing_sanity_review.passed:
            pricing.metadata = {
                **pricing.metadata,
                "pricing_sanity_review_status": pricing_sanity_review.pricing_status,
                "pricing_can_be_displayed_as_headline": pricing_sanity_review.pricing_can_be_displayed_as_headline,
            }
        all_evidence = evidence + pricing.evidence_items
        risks = [
            RiskItem(
                title="Evidence or source-quality overclaiming",
                severity="high",
                mitigation="Treat web and local defaults as non-authoritative, expose source limitations, and refresh AWS documentation/pricing evidence before procurement.",
                evidence_ids=[evidence[0].id],
            ),
            RiskItem(
                title="Pricing uncertainty before live AWS pricing integration",
                severity="medium",
                mitigation="Use ranges now and refresh with AWS Pricing tooling before budget approval.",
                evidence_ids=[pricing.evidence_items[0].id] if pricing.evidence_items else [],
            ),
        ]
        if "predictive_ml" in profile.capabilities:
            risks.append(
                RiskItem(
                    title="Prediction error affecting operations",
                    severity="high",
                    mitigation="Measure false positives, false negatives, drift, and business impact before automated action; use human approval for high-impact decisions.",
                    evidence_ids=[evidence[0].id],
                )
            )
        if profile.actions:
            risks.append(
                RiskItem(
                    title="Unsafe automated downstream actions",
                    severity="high",
                    mitigation="Use policy gates, idempotency, audit, rollback paths, and approval thresholds for workflow actions.",
                    evidence_ids=[evidence[0].id],
                )
            )
        if not understanding_validation.passed:
            has_critical_understanding_issue = any(issue.severity == "critical" for issue in understanding_validation.issues)
            risks.append(
                RiskItem(
                    title="Use-case understanding requires validation",
                    severity="high" if has_critical_understanding_issue else "medium",
                    mitigation="Review semantic findings before customer-ready positioning; deterministic user facts remain authoritative where conflicts exist.",
                    evidence_ids=[evidence[1].id],
                )
            )
        if not pricing_sanity_review.passed:
            risks.append(
                RiskItem(
                    title="Pricing-driver semantic mismatch",
                    severity="high",
                    mitigation="Resolve pricing sanity findings before showing cost as a headline or procurement-grade estimate.",
                    evidence_ids=[pricing.evidence_items[0].id] if pricing.evidence_items else [],
                )
            )
        if effective_brief.security_profile.handles_sensitive_data:
            risks.append(
                RiskItem(
                    title="Sensitive data exposure",
                    severity="high",
                    mitigation="Use least-privilege IAM, KMS encryption, private access patterns, audit trails, and human approval for actions.",
                    evidence_ids=[evidence[0].id],
                )
            )
        progress(88, "Building evidence map, citations, and customer-readiness gate.")
        facts, recommendations, uncertainties, citation_coverage = self.evidence_discipline.build_claims(
            evidence_items=all_evidence,
            assumptions=effective_brief.assumptions,
            pricing=pricing,
            risks=risks,
        )
        citation_coverage = enforce_citation_gate(facts + recommendations + uncertainties)
        _apply_evidence_quality_gate(citation_coverage, all_evidence)
        evidence_quality = summarize_evidence_quality(all_evidence, citation_coverage)
        service_decisions = build_service_decision_records(profile, all_evidence)
        customer_readiness = assess_customer_readiness(
            evidence_quality=evidence_quality.model_dump(),
            citation_passed=citation_coverage.passed,
            service_decisions=[item.model_dump(mode="json") for item in service_decisions],
            pricing_unknowns=pricing.unknown_variables,
            pricing_status=pricing.metadata.get("status"),
            pricing_metadata=pricing.metadata,
        )
        if not pricing_sanity_review.pricing_can_be_displayed_as_headline:
            pricing.unknown_variables.append("Pricing sanity review blocked headline cost display until extracted drivers are reconciled.")
        progress(94, "Finalizing research dossier and UI view-model inputs.")
        return ResearchReport(
            session_id=session_id,
            executive_verdict=f"Proceed with caution: classified as {display_label(workload_label, capitalize=False)}. Customer readiness is {display_label(customer_readiness.status.value, capitalize=False)}; governance, evidence, and pricing validation are required before procurement.",
            proceed_recommendation="proceed_with_caution",
            use_case_interpretation=effective_brief.refined_problem_statement,
            assumptions=effective_brief.assumptions,
            feasibility_analysis=_feasibility(profile),
            viability_analysis=_viability(profile, effective_brief),
            competitor_analysis=competitor_analysis,
            aws_service_recommendations=selected,
            pricing_analysis=pricing,
            risks=risks,
            recommended_poc=effective_brief.poc_scope,
            recommended_production_direction=effective_brief.production_scope,
            evidence_items=all_evidence,
            evidence_assessments=self.evidence_discipline.assess(all_evidence),
            facts=facts,
            recommendations=recommendations,
            uncertainties=uncertainties,
            citation_coverage=citation_coverage,
            metadata={
                "canonical_fact_snapshot": canonical_snapshot,
                "canonical_fact_snapshot_hash": canonical_snapshot["hash"],
                "use_case_profile": profile_to_metadata(profile),
                "capabilities": profile.capability_model,
                "deployment_posture": profile.deployment_posture,
                "latency_class": profile.latency_class,
                "workload_families": profile.workload_families,
                "excluded_families": profile.excluded_families,
                "excluded_patterns": profile.excluded_patterns,
                "pricing_dimensions": pricing_dimensions(profile),
                "research_quality": _research_quality(all_evidence),
                "evidence_quality": evidence_quality.model_dump(),
                "service_decision_records": [item.model_dump(mode="json") for item in service_decisions],
                "customer_readiness": customer_readiness.model_dump(mode="json"),
                "service_validation_notes": _service_validation_notes(profile),
                "deep_understanding": understanding.model_dump(mode="json"),
                "understanding_validation": understanding_validation.model_dump(mode="json"),
                "understanding_conflicts": [item.model_dump(mode="json") for item in understanding_merge.conflicts],
                "pricing_sanity_review": pricing_sanity_review.model_dump(mode="json"),
                "competitor_scan": competitor_status,
            },
        )


def _recommend_services(brief: UseCaseBrief, evidence: list[EvidenceItem]) -> list[AWSServiceRecommendation]:
    evidence_ids = [item.id for item in evidence]
    profile = _profile_for_research(brief)
    services = service_recommendations(profile, evidence_ids)
    public_entry_expected = (
        profile.domain != "healthcare"
        and (
            "web_api_application" in profile.workload_families
            or "api_application" in profile.capabilities
            or "public_cloud" in profile.deployment_posture
        )
    )
    if brief.security_profile.handles_sensitive_data and public_entry_expected and not any(item.service == "AWS WAF" for item in services):
        services.append(
            AWSServiceRecommendation(
                service="AWS WAF",
                purpose="Front-door protection for public APIs and consoles where present",
                rationale="Added because the use case has sensitive or critical operational impact.",
                alternatives_considered=["CloudFront-only controls", "Private-only access"],
                evidence_ids=evidence_ids,
            )
        )
    return services


def _profile_for_research(brief: UseCaseBrief):
    profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
    return refine_profile_with_context(
        profile,
        "\n".join([brief.raw_use_case, brief.refined_problem_statement, *[item.text for item in brief.assumptions]]),
    )


def _attach_price_list_evidence(pricing, evidence_items: list[EvidenceItem], source_name: str = "AWS Price List Bulk API") -> None:
    evidence_by_service = {}
    for item in evidence_items:
        summary = item.quote_or_summary or ""
        marker = "service recommendation '"
        if marker not in summary:
            continue
        service = summary.split(marker, 1)[1].split("'", 1)[0]
        evidence_by_service[service.lower()] = item
    for line in pricing.line_items:
        evidence = evidence_by_service.get(line.service.lower())
        plan = pricing_filter_plan_for_service(line.service, region_code=pricing.region)
        if not evidence or not plan:
            if not line.pricing_trace:
                line.pricing_trace = {
                    "calculation_source": "deterministic_local_model",
                    "procurement_ready": False,
                    "reason": "No official Price List offer mapping was available for this line item.",
                }
            continue
        if evidence.id not in line.evidence_ids:
            line.evidence_ids.append(evidence.id)
        existing_trace = dict(line.pricing_trace or {})
        line.pricing_trace = {
            **existing_trace,
            "calculation_source": "deterministic_model_with_official_offer_catalog",
            "procurement_ready": False,
            "service_code": plan.service_code,
            "filters": plan.filters,
            "price_list_evidence_id": evidence.id,
            "source": source_name,
            "source_reference": str(evidence.url) if evidence.url else None,
            "limitation": "Offer catalog is authoritative, but exact SKU/tier quantities are not yet applied to this line-item total.",
        }


def _feasibility(profile) -> str:
    if "industrial_iot_streaming_ml" in profile.workload_families:
        return (
            "Feasible as an AWS industrial IoT and streaming ML architecture: device ingestion, streaming feature extraction, "
            "risk scoring, event routing, time-series storage, and governed operations workflow can be composed from managed services."
        )
    if "rag_assistant" in profile.workload_families:
        return "Feasible as a grounded assistant if retrieval quality, citations, prompt-injection controls, identity, and audit are enforced."
    return f"Feasible as a managed AWS workload if the extracted capabilities ({', '.join(profile.capabilities)}) are validated against real volumes and integration constraints."


def _viability(profile, brief: UseCaseBrief) -> str:
    targets = "; ".join(brief.business_goals[:3]) or "measurable business outcomes"
    if profile.actions:
        return f"Viability depends on proving detection quality and action governance against targets: {targets}. Direct automation should follow measured POC results and approval policy."
    return f"Viability depends on proving quality, latency, reliability, and cost against targets: {targets}."


def _apply_evidence_quality_gate(coverage, evidence: list[EvidenceItem]) -> None:
    source_types = {item.source_type for item in evidence}
    if "aws_docs" not in source_types:
        coverage.passed = False
        coverage.warnings.append("No authoritative AWS documentation evidence was available for this run; recommendations require review.")
    if "aws_pricing" not in source_types:
        coverage.passed = False
        coverage.warnings.append("No authoritative AWS Pricing evidence was available for this run; costs are deterministic estimates, not procurement-grade quotes.")


def _research_quality(evidence: list[EvidenceItem]) -> dict:
    source_types = {item.source_type for item in evidence}
    fallback_docs = any(item.source_type == "aws_docs" and "fallback" in (item.tool_name or "").lower() for item in evidence)
    fallback_pricing = any(item.source_type == "aws_pricing" and "fallback" in (item.tool_name or "").lower() for item in evidence)
    managed_docs = any(item.source_type == "aws_docs" and "managed mcp" in (item.tool_name or "").lower() for item in evidence)
    managed_pricing = any(item.source_type == "aws_pricing" and "managed mcp" in (item.tool_name or "").lower() for item in evidence)
    missing = []
    if "aws_docs" not in source_types:
        missing.append("AWS Docs MCP")
    if "aws_pricing" not in source_types:
        missing.append("AWS Pricing MCP")
    if missing:
        return {
            "label": "Limited",
            "reason": f"{' and '.join(missing)} unavailable. Suitable for directional architecture discussion, not procurement or production approval.",
        }
    if fallback_docs or fallback_pricing:
        return {
            "label": "Official Fallback",
            "reason": "Official AWS web evidence was available, but MCP-backed documentation/pricing validation was not complete. Suitable for customer discussion, not procurement approval.",
        }
    if managed_docs or managed_pricing:
        return {
            "label": "Official MCP Evidence",
            "reason": "Managed AWS MCP evidence was available. Pricing remains directional unless the dedicated AWS Pricing MCP live lookup is configured.",
        }
    return {"label": "Validated", "reason": "Authoritative AWS documentation and pricing evidence were available."}


def _service_validation_notes(profile) -> list[str]:
    notes = []
    if "industrial_iot_streaming_ml" in profile.workload_families:
        notes.append(
            "Time-series storage must be validated against current AWS guidance: compare Timestream for InfluxDB, DynamoDB for high-scale ingestion, S3/Iceberg/Athena for historical analytics, AWS IoT SiteWise for industrial asset modeling, and Aurora/RDS PostgreSQL for SQL-oriented query shapes."
        )
        notes.append(
            "AWS IoT SiteWise is a strong candidate for utility/industrial asset modeling, edge processing, and hot/warm/cold industrial telemetry storage; Kinesis/Flink remains appropriate for streaming feature extraction and low-latency scoring."
        )
    return notes


async def _run_competitor_scan(brief: UseCaseBrief, profile, workload_label: str, session_id: str) -> tuple[list[TavilySearchResponse], dict]:
    client = TavilySearchClient()
    queries = _competitor_queries(brief, profile, workload_label)
    before_calls = tavily_session_usage(session_id)
    searches: list[TavilySearchResponse] = []
    results_returned = 0
    attempted = 0
    for query in queries:
        attempted += 1
        search = await client.search(query, session_id, max_results=5, purpose="competitor_scan")
        searches.append(search)
        results_returned += len(search.results)
        if tavily_session_usage(session_id) - before_calls >= max(1, client.settings.tavily_max_calls_per_session):
            break
    after_calls = tavily_session_usage(session_id)
    return searches, {
        "queries_attempted": attempted,
        "queries_executed": max(0, after_calls - before_calls),
        "results_returned": results_returned,
        "query_plan": queries[:attempted],
    }


def _competitor_queries(brief: UseCaseBrief, profile, workload_label: str) -> list[str]:
    domain = profile.domain or brief.industry or "enterprise"
    title = brief.title or "AWS workload"
    capabilities = " ".join((profile.capability_model or profile.capabilities or [])[:5])
    base = f"{domain} {workload_label} {title} {capabilities}".strip()
    queries = [
        f"{base} market competitors vendor platforms",
        f"{base} commercial alternatives cloud architecture",
        f"{base} customer case studies product comparison",
        f"{base} implementation risks buyer evaluation",
    ]
    families = set(profile.workload_families)
    if profile.domain == "healthcare" or "healthcare_operations_scheduling" in families:
        queries[0] = "perioperative command center OR scheduling optimization vendors hospital operations analytics"
        queries[1] = "operating room utilization surgical delay prediction platform competitors Epic integration"
    elif profile.domain == "telecommunications" or "telecom_network_analytics" in families:
        queries[0] = "telecom network analytics congestion prediction OSS BSS vendor platforms"
        queries[1] = "CDR analytics network telemetry assurance platform competitors"
    elif "live_streaming" in families:
        queries[0] = "live video streaming analytics ad decisioning QoE platform competitors"
        queries[1] = "OTT live sports streaming cloud media workflow vendor comparison"
    elif "financial_fraud_detection" in families or "capital_markets_risk_engine" in families:
        queries[0] = f"financial services {workload_label} vendor platforms cloud alternatives"
        queries[1] = f"{workload_label} risk analytics fraud detection platform competitors"
    return list(dict.fromkeys(queries))


def _competitor_analysis_from_searches(searches: list[TavilySearchResponse], status: dict) -> str:
    lines = [
        "Competitor / market scan completed with Tavily.",
        f"- Queries executed: {status.get('queries_executed')}",
        f"- Results returned: {status.get('results_returned')}",
        f"- Results used: {status.get('results_used')}",
        "- Interpretation rule: external web evidence is market context only; it cannot override user facts, AWS service governance, or pricing readiness.",
        "",
        "## Market signals",
    ]
    for search in searches:
        if search.answer:
            lines.append(f"- {search.answer[:400]}")
        for result in search.results[:3]:
            summary = result.content[:260] if result.content else "Returned by Tavily for the competitor scan."
            lines.append(f"- {result.title}: {summary}")
    lines.extend([
        "",
        "## AWS positioning implication",
        "- Use competitor evidence to understand buyer expectations and packaged alternatives.",
        "- Keep the Archway recommendation AWS-native, evidence-cited, and explicit about governance, integration, and pricing assumptions.",
    ])
    return "\n".join(lines)


def _competitor_status_text(status: dict) -> str:
    lines = [
        "Competitor / market scan status:",
        f"- Tavily enabled: {str(status.get('tavily_enabled')).lower()}",
        f"- Competitor scan enabled: {str(status.get('competitor_scan_enabled')).lower()}",
        f"- Session budget: {status.get('session_budget')}",
        f"- Queries attempted: {status.get('queries_attempted')}",
        f"- Queries executed: {status.get('queries_executed')}",
        f"- Results returned: {status.get('results_returned')}",
        f"- Results used: {status.get('results_used')}",
    ]
    if status.get("skipped_reason"):
        lines.append(f"- Skipped reason: {status['skipped_reason']}")
    if status.get("failure_reason"):
        lines.append(f"- Failure reason: {status['failure_reason']}")
    return "\n".join(lines)
