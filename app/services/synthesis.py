import re

from app.core.config import get_settings
from app.models.domain import (
    AICapability,
    Assumption,
    BudgetProfile,
    ComplianceProfile,
    DataSource,
    GapSeverity,
    Integration,
    OpenQuestion,
    ResearchQuestion,
    ScaleProfile,
    SecurityProfile,
    SynthesisQuestion,
    SynthesisReadiness,
    SynthesisResponse,
    UseCaseBrief,
    UseCaseGap,
    UserPersona,
)
from app.services.capability_router import CapabilityRouter
from app.services.discovery_planner import DiscoveryPlannerService
from app.services.display_labels import ACRONYM_CASING, TITLE_TRAILING_STOPWORDS, display_label
from app.services.pattern_catalog import poc_scope, pricing_dimensions, production_scope
from app.services.open_world_understanding import OpenWorldUnderstandingService
from app.services.use_case_profile import profile_from_metadata, profile_to_metadata, profile_use_case, refine_profile_with_context


def _attach_capability_decision(profile, raw_use_case: str) -> None:
    """Attach the deterministic CapabilityRouter decision to the profile.

    The advisory model prior (discovery_plan) is consumed read-only and can never set
    the capability status. Never breaks synthesis.
    """
    try:
        decision = CapabilityRouter().route(profile, getattr(profile, "discovery_plan", {}) or {}, raw_use_case=raw_use_case)
        profile.capability_decision = decision.to_dict()
    except Exception:  # noqa: BLE001 - routing metadata must never break synthesis
        profile.capability_decision = {}


def _is_open_world_profile(profile) -> bool:
    return getattr(profile, "profile_source", "") == "open_world_understanding"


def _understanding_unavailable_reason(open_world, settings) -> str | None:
    """Surface the TRUE reason an *attempted* open-world classification failed.

    Returns None when open-world is disabled by config: that is the sanctioned
    deterministic offline mode, not a fault, and it is governed by the existing
    readiness machinery — it must NOT trip the D27 fail-closed cap. A non-None
    reason means open-world was attempted and did not yield an authoritative
    result (provider down, schema-invalid); convergence caps those to internal_only
    and surfaces this reason verbatim ("retry when online").
    """
    if not getattr(settings, "enable_open_world_understanding", False):
        return None
    trace = getattr(open_world, "trace", None)
    live_call = getattr(trace, "live_call", None) if trace else None
    if live_call is not None and getattr(live_call, "error_message", None):
        return str(live_call.error_message)
    return "Open-world model provider unavailable."


class SynthesisEngine:
    def opening_message(self, brief: UseCaseBrief) -> str:
        return opening_interview_message(brief)

    def next_question(self, brief: UseCaseBrief) -> SynthesisQuestion | None:
        return _next_interview_question(brief)

    def format_question(self, question: SynthesisQuestion | None, answered_count: int = 0) -> str:
        return _interview_message(question, answered_count)

    def create_initial_brief(self, raw_use_case: str) -> UseCaseBrief:
        settings = get_settings()
        open_world = OpenWorldUnderstandingService().build(raw_use_case, settings=settings)
        # D27 INV-2: never silently fall back to the keyword categorizer as an authority.
        # Authority is decided once, on the trace. When the open-world understanding is
        # available, it drives the deliverable. When it is unavailable (provider down,
        # schema-invalid, disabled), we may still build a deterministic profile for
        # interview scaffolding, but it is stamped non-authoritative + carries the true
        # reason, and convergence will cap the package to internal_only.
        authoritative = bool(getattr(open_world.trace, "understanding_authoritative", False))
        if authoritative and open_world.profile is not None:
            profile = open_world.profile
            profile.understanding_authoritative = True
            profile.understanding_unavailable_reason = None
        else:
            profile = profile_use_case(raw_use_case)
            profile.understanding_authoritative = False
            profile.understanding_unavailable_reason = _understanding_unavailable_reason(open_world, settings)
            if settings.enable_open_world_understanding:
                profile.open_world_understanding = open_world.trace.model_dump(mode="json")
        if not _is_open_world_profile(profile):
            profile.discovery_plan = DiscoveryPlannerService().plan_sync(
                raw_use_case,
                profile,
                previous_answers=[],
            ).model_dump(mode="json")
        _attach_capability_decision(profile, raw_use_case)
        industry = profile.domain or _detect_industry(raw_use_case)
        sensitive = _looks_sensitive(raw_use_case, industry)
        title = _title_from_use_case(raw_use_case)
        assumptions = _assumptions_for_profile(profile) + [
            Assumption(
                text="Use us-east-1 for initial AWS pricing estimates unless a deployment region is confirmed.",
                reason="The user has not chosen a deployment region yet.",
                impact="pricing",
                confidence="medium",
            ),
            Assumption(
                text="Treat production-impacting write actions as approval-gated until operating policy is confirmed.",
                reason="Automated actions can affect customers, operations, inventory, money, health, or compliance.",
                impact="security",
                confidence="high",
            ),
            Assumption(
                text="Use conservative throughput and retention assumptions where the input does not give exact rates.",
                reason="Pricing and architecture depend on workload-specific volume, retention, and latency dimensions.",
                impact="pricing",
                confidence="medium",
            ),
        ]
        open_questions = open_world.open_questions or _questions_for_profile(profile)
        return UseCaseBrief(
            title=title,
            raw_use_case=raw_use_case,
            refined_problem_statement=_problem_statement(profile, raw_use_case),
            industry=industry,
            business_goals=_business_goals(raw_use_case, profile),
            users=_users_for_profile(profile),
            ai_capabilities=_capabilities_for_profile(profile),
            data_sources=_data_sources(raw_use_case, sensitive, profile),
            integrations=_integrations_for_profile(profile),
            scale_profile=_scale_profile(profile),
            security_profile=SecurityProfile(handles_sensitive_data=sensitive, requires_human_approval=bool(profile.actions)),
            compliance_profile=ComplianceProfile(regimes=_compliance(industry), audit_required=True),
            budget_profile=BudgetProfile(posture="balanced"),
            poc_scope=poc_scope(profile),
            production_scope=production_scope(profile),
            assumptions=assumptions,
            open_questions=open_questions,
            research_questions=_research_questions_for_profile(profile),
            use_case_profile=profile_to_metadata(profile),
        )

    async def enhance_brief(self, brief: UseCaseBrief, session_id: str | None = None) -> UseCaseBrief:
        existing_interview = dict(((brief.use_case_profile or {}).get("interview") or {}))
        profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
        previous_answers = [item.text for item in brief.assumptions if item.user_confirmed]
        if not _is_open_world_profile(profile):
            plan = await DiscoveryPlannerService().plan(
                brief.raw_use_case,
                profile,
                previous_answers=previous_answers,
                session_id=session_id,
            )
            profile.discovery_plan = plan.model_dump(mode="json")
        _attach_capability_decision(profile, brief.raw_use_case)
        metadata = profile_to_metadata(profile)
        if existing_interview:
            metadata["interview"] = existing_interview
        brief.use_case_profile = metadata
        brief.open_questions = _questions_for_profile(profile)
        return brief

    def respond(self, brief: UseCaseBrief, user_message: str) -> SynthesisResponse:
        updated = brief.model_copy(deep=True)
        profile_metadata = dict(updated.use_case_profile or {})
        interview = dict(profile_metadata.get("interview") or {})
        answered = list(interview.get("answered") or [])
        clarifications = list(interview.get("clarifications") or [])
        profile = profile_from_metadata(updated.use_case_profile, updated.raw_use_case)
        questions = _synthesis_questions(profile, _readiness_assumptions(profile))
        current = next((item for item in questions if item.id not in answered), None)
        interview_complete = current is None and bool(questions)
        if current:
            answered.append(current.id)
            _record_interview_answer(updated, current, user_message)
        elif interview_complete:
            # All interview questions are already answered. Do NOT fall back to
            # question[0]; treat the extra input as a clarification so we don't
            # re-answer the first question or grow the brief with stale context.
            _record_post_completion_clarification(updated, clarifications, user_message)
        lower = user_message.lower()
        if any(word in lower for word in ("production", "prod", "scale")):
            updated.scale_profile.posture = "production"
            updated.production_scope = "Design production with private networking, IAM least privilege, audit trails, resilience, and cost controls."
        if any(word in lower for word in ("refund", "cancel", "update", "write", "ticket", "workflow", "dispatch", "approve")):
            if not any(item.direction in {"write", "read_write"} for item in updated.integrations):
                updated.integrations.append(Integration(name="Action workflow", direction="read_write"))
            updated.ai_capabilities.append(AICapability(name="Governed action execution", risk_level="high", human_approval_required=True))
        if any(word in lower for word in ("pii", "phi", "pci", "sensitive", "patient", "financial", "critical infrastructure")):
            updated.security_profile.handles_sensitive_data = True
            if "PII" not in updated.compliance_profile.regimes:
                updated.compliance_profile.regimes.append("PII")
        profile_metadata = dict(updated.use_case_profile or {})
        interview = {
            **dict(profile_metadata.get("interview") or {}),
            "answered": list(dict.fromkeys(answered)),
            "turn_count": len(set(answered)),
            "clarifications": clarifications,
        }
        profile_metadata["interview"] = interview
        rerouted = refine_profile_with_context(
            profile_from_metadata(profile_metadata, updated.raw_use_case),
            "\n".join([updated.raw_use_case, updated.refined_problem_statement, *[item.text for item in updated.assumptions]]),
        )
        if not _is_open_world_profile(rerouted):
            rerouted.discovery_plan = DiscoveryPlannerService().plan_sync(
                updated.raw_use_case,
                rerouted,
                previous_answers=[item.text for item in updated.assumptions if item.user_confirmed],
            ).model_dump(mode="json")
        _attach_capability_decision(rerouted, updated.raw_use_case)
        profile_metadata = {**profile_to_metadata(rerouted), "interview": interview}
        updated.use_case_profile = profile_metadata
        updated.open_questions = _questions_for_profile(rerouted)
        readiness = self.readiness(updated)
        if interview_complete:
            message = _COMPLETION_CLARIFICATION_MESSAGE
        else:
            question = _next_interview_question(updated)
            message = _interview_message(question, len(set(answered)))
        return SynthesisResponse(message=message, brief=updated, readiness=readiness)

    def readiness(self, brief: UseCaseBrief) -> SynthesisReadiness:
        profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
        gaps: list[UseCaseGap] = []
        if brief.security_profile.handles_sensitive_data is None:
            gaps.append(UseCaseGap(id="sensitive-data", text="Sensitive data or critical operational impact is not confirmed.", severity=GapSeverity.critical, impact="security"))
        if not brief.ai_capabilities:
            gaps.append(UseCaseGap(id="behavior", text="The expected system behavior is not clear yet.", severity=GapSeverity.important, impact="architecture"))
        if not _has_scale_signal(brief, profile):
            severity = GapSeverity.critical if "real_time_ingestion" in profile.capabilities else GapSeverity.important
            gaps.append(UseCaseGap(id="scale", text="Workload volume or throughput is not confirmed.", severity=severity, impact="pricing"))
        if not brief.data_sources:
            gaps.append(UseCaseGap(id="data", text="The source systems are not identified yet.", severity=GapSeverity.important, impact="architecture"))
        assumptions = _readiness_assumptions(profile)
        answered = set(((brief.use_case_profile or {}).get("interview") or {}).get("answered") or [])
        questions = [question for question in _synthesis_questions(profile, assumptions) if question.id not in answered]
        critical = [gap for gap in gaps if gap.severity == GapSeverity.critical]
        important = [gap for gap in gaps if gap.severity == GapSeverity.important]
        optional = [gap for gap in gaps if gap.severity == GapSeverity.optional]
        score = max(0.25, 1.0 - (len(critical) * 0.25 + len(important) * 0.12))
        label = "high" if score >= 0.78 else "medium" if score >= 0.52 else "low"
        return SynthesisReadiness(
            can_proceed=len(critical) == 0,
            confidence_score=round(score, 2),
            confidence_label=label,
            critical_gaps=critical,
            important_gaps=important,
            optional_gaps=optional,
            recommended_minimum_questions=questions[:3],
            assumptions_if_skipped=assumptions[:3],
        )


def _problem_statement(profile, raw_use_case: str) -> str:
    families = ", ".join(display_label(family, capitalize=False) for family in profile.workload_families)
    domain = (profile.domain or "").strip()
    if not domain:
        subject = "the target workload"
    elif domain.lower().startswith(("the ", "this ", "that ")):
        subject = f"{domain} workload"
    else:
        article = "an" if domain[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
        subject = f"{article} {domain} workload"
    return f"Design an AWS architecture for {subject} classified as {families}: {raw_use_case.strip()}"


def opening_interview_message(brief: UseCaseBrief) -> str:
    question = _next_interview_question(brief)
    if not question:
        return "I have enough to shape the first research pass. You can proceed, or add any constraints you want captured before research."
    return _interview_message(question, 0)


def _next_interview_question(brief: UseCaseBrief) -> SynthesisQuestion | None:
    profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
    assumptions = _readiness_assumptions(profile)
    answered = set(((brief.use_case_profile or {}).get("interview") or {}).get("answered") or [])
    return next((item for item in _synthesis_questions(profile, assumptions) if item.id not in answered), None)


def _interview_message(question: SynthesisQuestion | None, answered_count: int) -> str:
    if not question:
        return "That gives me enough for a strong first pass. I’ll carry these interview answers into research, pricing, architecture, diagrams, and the final package."
    prefix = "Good, I captured that." if answered_count else "Let’s tighten the brief before research."
    return "\n\n".join([
        prefix,
        question.prompt,
        f"Why it matters: {question.why_it_matters}",
        "Useful answer styles: " + " | ".join(question.options),
    ])


def _record_interview_answer(brief: UseCaseBrief, question: SynthesisQuestion, answer: str) -> None:
    text = answer.strip()
    if not text:
        return
    existing = {item.text for item in brief.assumptions}
    assumption_text = f"Interview answer for '{question.prompt}': {text}"
    if assumption_text not in existing:
        brief.assumptions.append(Assumption(
            text=assumption_text,
            reason="Captured during the synthesis interview and used to shape research, pricing, architecture, diagrams, and export artifacts.",
            impact=_question_impact(question.id),
            confidence="high",
            user_confirmed=True,
        ))
    brief.open_questions = [item for item in brief.open_questions if question.prompt[:40].lower() not in item.text.lower()]
    # Keep interview detail structured in assumptions/raw metadata; client prose
    # should summarize it instead of carrying verbatim transcript scaffolding.


_COMPLETION_CLARIFICATION_MESSAGE = (
    "Thanks — I’ve added this as an additional clarification. The brief is ready to proceed to research."
)


def _record_post_completion_clarification(brief: UseCaseBrief, clarifications: list[str], message: str) -> None:
    """Record post-interview input as a clean, deduplicated clarification.

    Called only when every interview question is already answered. It must not
    re-answer a question, append junk/duplicate assumptions, or grow the refined
    problem statement with stale question context.
    """
    text = message.strip()
    if not text:
        return
    if any(text.lower() == existing.strip().lower() for existing in clarifications):
        return
    clarifications.append(text)
    assumption_text = f"Additional clarification: {text}"
    if assumption_text not in {item.text for item in brief.assumptions}:
        brief.assumptions.append(Assumption(
            text=assumption_text,
            reason="Captured after the synthesis interview was complete; recorded as an additional clarification rather than a new interview answer.",
            impact="scope",
            confidence="medium",
            user_confirmed=True,
        ))


def _question_impact(question_id: str):
    if any(token in question_id for token in ("cost", "volume", "pricing", "retention")):
        return "pricing"
    if any(token in question_id for token in ("privacy", "security", "governance", "approval", "action")):
        return "security"
    if any(token in question_id for token in ("latency", "sla")):
        return "performance"
    if "compliance" in question_id:
        return "compliance"
    return "architecture"


def _assumptions_for_profile(profile) -> list[Assumption]:
    assumptions = []
    if _is_live_delivery_profile(profile):
        assumptions.append(Assumption(text="Use representative viewer-hours, bitrate ladder, CDN cache-hit ratio, ad decision volume, DRM license volume, and archive retention until traffic forecasts are confirmed.", reason="Live delivery cost depends on audience, bitrate, rights, ad, and archive drivers rather than generic telemetry frequency.", impact="pricing", confidence="medium"))
    elif _is_document_workflow_profile(profile):
        assumptions.append(Assumption(text="Use representative document volume, document size, ingestion cadence, embedding refresh, RAG query volume, approval workflow volume, and audit retention until legal/document workload drivers are confirmed.", reason="Document intelligence and RAG costs depend on ingestion, OCR/extraction, indexing, retrieval, model invocation, workflow, and retention drivers rather than telemetry frequency.", impact="pricing", confidence="medium"))
    elif "real_time_ingestion" in profile.capabilities:
        assumptions.append(Assumption(text="Use representative telemetry rates until exact device reporting frequency and message size are confirmed.", reason="Streaming and storage cost depend on events per second and payload size.", impact="pricing", confidence="medium"))
    if "event_driven_workflow" in profile.capabilities:
        assumptions.append(Assumption(text="Keep external system writes approval-gated in POC and policy-gated in production.", reason="Downstream actions can affect customers, operations, money, or safety.", impact="security", confidence="high"))
    if "predictive_ml" in profile.capabilities:
        assumptions.append(Assumption(text="Start with measurable model quality targets and human review for high-impact predictions.", reason="False positives and false negatives can materially affect operations.", impact="performance", confidence="medium"))
    if not assumptions:
        assumptions.append(Assumption(text="Start with a scoped POC before broad production rollout.", reason="The safest architecture depends on measured usage, data quality, and integration behavior.", impact="scope", confidence="medium"))
    return assumptions


def _questions_for_profile(profile) -> list[OpenQuestion]:
    planner_questions = _planner_questions(profile)
    if planner_questions:
        return planner_questions[:6]
    questions = [
        OpenQuestion(text="What are the primary actors, source systems, and business events in scope for the first release?", impact="architecture"),
        OpenQuestion(text="What expected volume, concurrency, throughput, payload size, and retention should Archway model for pricing?", impact="pricing"),
    ]
    if _is_telecom_hbase_profile(profile):
        questions.extend([
            OpenQuestion(text="What are the HBase access patterns before choosing the AWS target store: row-key design, read/write QPS, scan frequency, hot partitions, TTL, and consistency needs?", impact="architecture"),
            OpenQuestion(text="What HDFS data volume, retention, Spark/MapReduce job schedule, and migration cutover window should be assumed?", impact="pricing"),
            OpenQuestion(text="Which OSS/BSS, QoS reporting, and network analytics integrations must be preserved during migration?", impact="architecture"),
        ])
    elif _is_document_workflow_profile(profile):
        questions.extend([
            OpenQuestion(text="How many historical contracts/documents, average pages or MB per document, and new or updated documents per month should Archway model?", impact="pricing"),
            OpenQuestion(text="Which document types are in scope: PDF, DOCX, scanned images, or mixed sources, and is OCR/text extraction required?", impact="architecture"),
            OpenQuestion(text="What RAG query volume, embedding/indexing frequency, active legal/procurement users, obligation approval volume, and audit retention duration should be assumed?", impact="pricing"),
        ])
    elif "real_time_ingestion" in profile.capabilities:
        questions.extend([
            OpenQuestion(text="What is the reporting frequency and message size for each telemetry source?", impact="pricing"),
            OpenQuestion(text="What end-to-end detection latency is required for hot-path decisions?", impact="performance"),
            OpenQuestion(text="How long must raw, feature, and scored telemetry be retained?", impact="pricing"),
        ])
    else:
        questions.append(OpenQuestion(text="Which integrations, write actions, and approval boundaries must be treated as hard requirements?", impact="security"))
    if "predictive_ml" in profile.capabilities:
        questions.append(OpenQuestion(text="What false positive and false negative posture is acceptable?", impact="architecture"))
    if profile.actions:
        questions.append(OpenQuestion(text="Which external systems receive actions, and which actions need human approval?", impact="security"))
    questions.append(OpenQuestion(text="Which AWS region, data residency, and compliance constraints apply?", impact="compliance"))
    return questions[:6]


def _users_for_profile(profile) -> list[UserPersona]:
    users = []
    if {"real_time_ingestion", "event_driven_workflow"} <= set(profile.capabilities):
        users.extend([
            UserPersona(name="Operations controller", description="Monitors alerts, operational health, and exception queues."),
            UserPersona(name="Response coordinator", description="Coordinates approved follow-up actions across teams and systems."),
            UserPersona(name="Reliability analyst", description="Reviews failure patterns, decision quality, and model performance."),
        ])
    elif "financial_fraud_detection" in profile.workload_families:
        users.append(UserPersona(name="Fraud analyst", description="Reviews risk scores, alerts, and case outcomes."))
    elif "document_intelligence" in profile.workload_families:
        users.append(UserPersona(name="Document operations user", description="Reviews extracted fields and exceptions."))
    elif "rag_assistant" in profile.workload_families:
        users.append(UserPersona(name="Business user", description="Uses the assistant to get faster, safer answers."))
    else:
        users.append(UserPersona(name="Operations user", description="Uses the platform to monitor, decide, and act on business events."))
    return users


def _capabilities_for_profile(profile) -> list[AICapability]:
    items = []
    if "predictive_ml" in profile.capabilities:
        items.append(AICapability(name="Predictive scoring and anomaly detection", risk_level="high", human_approval_required=bool(profile.actions)))
    if "real_time_ingestion" in profile.capabilities:
        items.append(AICapability(name="Streaming telemetry correlation", risk_level="medium", human_approval_required=False))
    if "event_driven_workflow" in profile.capabilities:
        items.append(AICapability(name="Governed operational workflow automation", risk_level="high", human_approval_required=True))
    if "document_retrieval" in profile.capabilities:
        items.append(AICapability(name="Grounded retrieval and question answering", risk_level="medium", human_approval_required=False))
    if "generative_ai" in profile.capabilities and not items:
        items.append(AICapability(name="Generative AI assistance", risk_level="medium", human_approval_required=True))
    return items or [AICapability(name="Rules, analytics, or ML-supported decision workflow", risk_level="medium", human_approval_required=bool(profile.actions))]


def _integrations_for_profile(profile) -> list[Integration]:
    integrations = []
    if "real_time_ingestion" in profile.capabilities:
        integrations.append(Integration(name="Telemetry sources", direction="read"))
    if "enterprise_integration" in profile.capabilities or profile.actions:
        direction = "read_write" if profile.actions else "read"
        integrations.append(Integration(name="Existing enterprise systems", direction=direction))
    if not integrations:
        integrations.append(Integration(name="Existing business systems", direction="unknown"))
    return integrations


def _scale_profile(profile) -> ScaleProfile:
    users = None
    requests = None
    asset_total = 0
    for metric in profile.metrics:
        label = metric.label.lower()
        if any(token in label for token in ("user", "operator", "employee")):
            users = int(metric.value)
        if metric.kind == "asset_count":
            asset_total += int(metric.value)
        if any(token in label for token in ("request", "event", "message", "transaction")):
            requests = int(max(requests or 0, metric.value))
    posture = "production" if any(metric.value >= 100000 for metric in profile.metrics) or profile.actions else "poc"
    return ScaleProfile(users_per_month=users, requests_per_day=requests, documents_gb=None, posture=posture)


def _research_questions_for_profile(profile) -> list[ResearchQuestion]:
    dimensions = ", ".join(pricing_dimensions(profile)[:6])
    return [
        ResearchQuestion(text=f"Which AWS services best fit {', '.join(profile.workload_families)}?", why="The architecture must follow the workload family, not a default assistant pattern."),
        ResearchQuestion(text=f"What pricing dimensions matter most: {dimensions}?", why="Pricing must be based on workload drivers rather than generic request counts."),
        ResearchQuestion(text="What source quality limits apply to this report?", why="Weak or unavailable AWS documentation/pricing evidence must be visible."),
    ]


def _business_goals(text: str, profile=None) -> list[str]:
    if profile and profile.business_targets:
        return profile.business_targets
    goals = []
    lower = text.lower()
    if any(term in lower for term in ("outage", "mttr", "restore")):
        goals.extend(["Reduce unplanned outages", "Reduce mean time to restore"])
    if "support" in lower:
        goals.append("Improve support resolution time")
    if not goals:
        goals.extend(["Improve decision quality", "Create a secure path from POC to production"])
    return goals


def _has_scale_signal(brief: UseCaseBrief, profile) -> bool:
    return bool(brief.scale_profile.requests_per_day or brief.scale_profile.users_per_month or profile.metrics)


def _readiness_assumptions(profile) -> list[Assumption]:
    assumptions = []
    if _is_live_delivery_profile(profile):
        assumptions.append(Assumption(text="Assume viewer-hours, bitrate ladder, regional traffic mix, CDN cache-hit ratio, live channel count, ad decision volume, DRM license volume, and replay/archive retention are not procurement-grade until confirmed.", reason="Live delivery pricing depends on workload-specific audience and rights/ad drivers.", impact="pricing", confidence="medium"))
    elif _is_document_workflow_profile(profile):
        assumptions.append(Assumption(text="Assume contract/document volume, average document size, OCR need, embedding refresh cadence, RAG query volume, active reviewer count, approval workflow volume, and audit retention are not procurement-grade until confirmed.", reason="Legal document intelligence pricing depends on document ingestion, text extraction/OCR, vector indexing, model calls, workflow state transitions, and retention.", impact="pricing", confidence="medium"))
    elif "real_time_ingestion" in profile.capabilities:
        assumptions.append(Assumption(text="Assume telemetry rates are representative but not procurement-grade until exact message frequency and size are confirmed.", reason="Streaming costs depend on event volume and payload size.", impact="pricing", confidence="medium"))
    assumptions.append(Assumption(text="Treat data as sensitive and audit-required until confirmed otherwise.", reason="This is the safer default for architecture and compliance.", impact="security", confidence="medium"))
    assumptions.append(Assumption(text="Require approval for high-impact automated actions in the first release.", reason="Action automation can affect customers, operations, compliance, or safety.", impact="architecture", confidence="high"))
    return assumptions


def _synthesis_questions(profile, assumptions: list[Assumption]) -> list[SynthesisQuestion]:
    planner_questions = _planner_questions(profile)
    if planner_questions:
        return [
            SynthesisQuestion(
                id=f"planner-{index}",
                prompt=item.text,
                why_it_matters=_planner_why(profile, item.text),
                options=_planner_answer_styles(profile, item.text),
                recommended_option=_planner_answer_styles(profile, item.text)[-1],
                assumption_if_skipped=assumptions[0],
            )
            for index, item in enumerate(planner_questions[:5])
        ]
    prompts = [
        ("workload-boundary", "What actors, source systems, business events, and out-of-scope workflows should I model?", "This keeps architecture, pricing, and diagrams aligned to the real workload rather than a named-domain template.", ["Known system inventory", "Approximate operating model", "Pilot subset only", "Let Archway assume"], assumptions[0]),
        ("pricing-drivers", "What volume, throughput, payload size, concurrency, retention, and notification or workflow counts should I use?", "These are the common drivers behind credible directional pricing across AWS services.", ["Known measured volumes", "Approximate forecast", "Pilot-scale estimate", "Let Archway assume"], assumptions[0]),
    ]
    if _is_telecom_hbase_profile(profile):
        prompts.append(("telecom-hbase-access-patterns", "What HBase access patterns should I preserve before selecting the AWS target store?", "Row-key design, read/write QPS, scans, hot partitions, TTL, and consistency determine whether DynamoDB, Keyspaces, OpenSearch, EMR/S3, or another target fits.", ["Known access profile", "Mostly point reads/writes", "Heavy scans/analytics", "Let Archway assume"], assumptions[0]))
        prompts.append(("telecom-hdfs-migration-shape", "What HDFS data volume, retention, Spark/MapReduce schedule, and cutover window should I use?", "Migration sizing and target architecture depend on stored data volume, batch job shape, and parallel-run constraints.", ["Known migration plan", "Estimate from current cluster", "Parallel run required", "Let Archway assume"], assumptions[0]))
    elif _is_document_workflow_profile(profile):
        prompts.append(("document-rag-volume", "How many historical contracts/documents, average pages or MB per document, new or updated documents per month, and RAG queries per day should I model?", "These drivers size storage, OCR/text extraction, embedding/indexing, retrieval, model invocation, and audit cost.", ["Known document forecast", "Known contracts but unknown size", "Known RAG usage only", "Let Archway assume"], assumptions[0]))
        prompts.append(("document-types-ocr", "Which document types are in scope, and do scanned images require OCR/text extraction?", "PDF, DOCX, scanned images, and mixed repositories lead to different ingestion, Textract/OCR, indexing, and validation paths.", ["PDF/DOCX text", "Scanned documents need OCR", "Mixed contract repository", "Let Archway assume"], assumptions[0]))
        prompts.append(("obligation-workflow-volume", "What active legal/procurement user count, obligation review/approval volume, downstream metadata update rate, and audit retention duration should I assume?", "Workflow and audit drivers size approvals, external updates, state storage, logs, and compliance retention.", ["Known workflow volumes", "Known users only", "Audit retention known", "Let Archway assume"], assumptions[-1]))
    elif "real_time_ingestion" in profile.capabilities:
        prompts.append(("telemetry-volume", "What reporting frequency and payload size should I use for telemetry pricing?", "This drives IoT, stream, storage, log, and inference cost.", ["Every few seconds", "Every 1-5 minutes", "Every 5-15 minutes", "Let Archway assume"], assumptions[0]))
        prompts.append(("latency-target", "What detection latency is required for the hot path?", "This determines whether the design needs streaming inference, edge processing, or batch analytics.", ["Under 10 seconds", "Under 60 seconds", "Near-real-time minutes", "Let Archway assume"], assumptions[0]))
    elif "rag_assistant" in profile.workload_families or "document_retrieval" in profile.capabilities:
        prompts.extend([
            ("knowledge-scope", "Which knowledge sources are in scope for the first release?", "Source boundaries drive retrieval, citations, permissions, and ingestion design.", ["Approved policy docs", "Customer support knowledge base", "Operational manuals", "Let Archway assume"], assumptions[0]),
            ("answer-risk", "What should the assistant do when confidence is low or evidence conflicts?", "This governs hallucination controls, escalation, and citation discipline.", ["Refuse/ask for clarification", "Escalate to human", "Show caveated answer", "Let Archway assume"], assumptions[-1]),
        ])
    prompts.append(("action-governance", "Which actions may be automated without human approval?", "This sets the governance boundary for external system writes.", ["None in POC", "Low-risk notifications only", "Policy-approved actions", "Let Archway assume"], assumptions[-1]))
    prompts.append(("deployment-compliance", "Which AWS region, data residency, and compliance constraints must be treated as hard requirements?", "Region, residency, and compliance affect service selection, evidence needs, network posture, and final readiness.", ["Single US region", "Multi-region US", "Specific country/region", "Let Archway assume"], assumptions[-1]))
    return [
        SynthesisQuestion(id=item[0], prompt=item[1], why_it_matters=item[2], options=item[3], recommended_option=item[3][-1], assumption_if_skipped=item[4])
        for item in prompts
    ]


def _data_sources(text: str, sensitive: bool | None, profile=None) -> list[DataSource]:
    sensitivity = "regulated" if sensitive else "unknown"
    sources = []
    if profile and _is_live_delivery_profile(profile):
        sources.append(DataSource(name="Live contribution feeds", sensitivity=sensitivity))
        sources.append(DataSource(name="Playback QoE and ad decision events", sensitivity=sensitivity))
    elif profile and _is_document_workflow_profile(profile):
        sources.append(DataSource(name="Contract and document repository", sensitivity=sensitivity))
        sources.append(DataSource(name="Obligation, approval, and audit workflow records", sensitivity=sensitivity))
    elif profile and "real_time_ingestion" in profile.capabilities:
        sources.append(DataSource(name="Telemetry streams", sensitivity=sensitivity))
    if profile and "time_series_analytics" in profile.capabilities:
        sources.append(DataSource(name="Historical time-series data", sensitivity=sensitivity))
    if profile and "document_retrieval" in profile.capabilities:
        sources.append(DataSource(name="Business knowledge base", sensitivity=sensitivity))
    if _has_commerce_order_context(text.lower()):
        sources.append(DataSource(name="Order management system", sensitivity="confidential"))
    return sources or [DataSource(name="Business data sources", sensitivity=sensitivity)]


def _has_commerce_order_context(lower: str) -> bool:
    if "work order" in lower or "maintenance order" in lower:
        return False
    commerce_markers = ("retail", "commerce", "customer order", "online order", "order fulfillment", "delivery order", "refund")
    return any(_affirmed_marker(lower, marker) for marker in commerce_markers)


def _affirmed_marker(lower: str, marker: str) -> bool:
    start = lower.find(marker)
    while start >= 0:
        prefix = lower[max(0, start - 32):start]
        if not re.search(r"(?:\bnot\b|\bno\b|\bwithout\b|\bexclude[sd]?\b|\bnon[-\s])\W*$", prefix):
            return True
        start = lower.find(marker, start + len(marker))
    return False


def _planner_questions(profile) -> list[OpenQuestion]:
    plan = getattr(profile, "discovery_plan", {}) or {}
    questions = []
    for item in plan.get("top_questions") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        if not text:
            continue
        if not _question_allowed_for_profile(profile, text):
            continue
        questions.append(OpenQuestion(text=text, impact=_planner_impact(item)))
    return questions


def _question_allowed_for_profile(profile, text: str) -> bool:
    lower = text.lower()
    excluded = set(getattr(profile, "excluded_families", []) or []) | set(getattr(profile, "excluded_patterns", []) or [])
    blocked_terms: list[str] = []
    if {"rag_assistant", "document_intelligence"} & excluded:
        blocked_terms.extend([
            "contract", "contracts", "document", "documents", "pdf", "ocr", "textract",
            "rag", "embedding", "embeddings", "vector", "knowledge base", "retrieval",
        ])
    if "field_service_automation" in excluded:
        blocked_terms.extend([
            "field service", "technician", "crew", "depot", "dispatch", "workforce",
            "inventory", "truck", "work order", "spare parts",
        ])
    return not any(term in lower for term in blocked_terms)


def _planner_impact(item: dict) -> str:
    why = str(item.get("why_it_matters") or "").lower()
    if any(token in why for token in ("pricing", "cost", "storage", "retention", "query volume", "ingestion")):
        return "pricing"
    if any(token in why for token in ("approval", "governance", "write", "audit")):
        return "security"
    if any(token in why for token in ("latency", "throughput", "concurrency")):
        return "performance"
    return "architecture"


def _planner_why(profile, prompt: str) -> str:
    plan = getattr(profile, "discovery_plan", {}) or {}
    for item in plan.get("top_questions") or []:
        if isinstance(item, dict) and str(item.get("question") or "").strip() == prompt:
            return str(item.get("why_it_matters") or "This clarifies workload shape, pricing drivers, and governance boundaries.")
    return "This clarifies workload shape, pricing drivers, and governance boundaries."


def _planner_answer_styles(profile, prompt: str) -> list[str]:
    plan = getattr(profile, "discovery_plan", {}) or {}
    for item in plan.get("top_questions") or []:
        if isinstance(item, dict) and str(item.get("question") or "").strip() == prompt:
            style = str(item.get("expected_answer_style") or "").strip()
            if style:
                return [style, "Approximate estimate", "Unknown, let Archway assume"]
    return ["Natural language", "Approximate estimate", "Unknown, let Archway assume"]


def _compliance(industry: str | None) -> list[str]:
    if industry == "healthcare":
        return ["HIPAA/PHI review required"]
    if industry == "financial_services":
        return ["PCI/PII review required"]
    if industry == "energy_utility":
        return ["Critical infrastructure cybersecurity review required", "PII review required"]
    return ["PII review required"]


# Legacy helpers kept for fallback industry/title detection.
def _detect_industry(text: str) -> str | None:
    lower = text.lower()
    mapping = {
        "healthcare": ("patient", "clinical", "hospital", "health", "phi"),
        "retail": ("retail", "customer order", "online order", "order fulfillment", "delivery order", "refund"),
        "manufacturing": ("manufacturing", "machine", "sensor", "downtime", "iot"),
        "automotive": ("dealer", "vehicle", "warranty", "automotive"),
        "banking/financial": ("bank", "fraud", "payment", "financial", "pci"),
    }
    for industry, markers in mapping.items():
        normalized = lower.replace("-", " ")
        if any(marker in lower and not _is_text_marker_negated(normalized, marker) for marker in markers):
            return industry
    return None


def _is_text_marker_negated(normalized_lower: str, marker: str) -> bool:
    marker_pattern = re.escape(marker.replace("-", " ")).replace(r"\ ", r"\s+")
    prefix = r"(?:not|no|without|exclude|excluding|avoid|avoiding|not\s+a|not\s+an|not\s+the)"
    return re.search(rf"\b{prefix}\b(?:\W+\w+){{0,6}}\W+{marker_pattern}\b", normalized_lower) is not None


def _looks_sensitive(text: str, industry: str | None) -> bool | None:
    lower = text.lower()
    if any(marker in lower for marker in ("pii", "phi", "pci", "patient", "financial", "employee", "customer")):
        return True
    if industry in {"healthcare", "banking/financial"}:
        return True
    return None


_TITLE_MAX_WORDS = 10


def _title_from_use_case(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", text)[:_TITLE_MAX_WORDS]
    # Bare numbers ("with 5 000 contracts" -> "5", "000") never end a title,
    # and trimming them can expose a trailing stopword, so trim both kinds.
    while tokens and (tokens[-1].lower() in TITLE_TRAILING_STOPWORDS or tokens[-1].isdigit()):
        tokens.pop()
    if not tokens:
        return "AI Solution Architecture"
    words = []
    for index, token in enumerate(tokens):
        lower = token.lower()
        if token.isupper() and len(token) >= 2:
            words.append(token)
        elif lower in ACRONYM_CASING:
            words.append(ACRONYM_CASING[lower])
        elif index > 0 and lower in TITLE_TRAILING_STOPWORDS:
            words.append(lower)
        elif "-" in token:
            words.append("-".join(_title_word(part, first=(index == 0 and position == 0)) for position, part in enumerate(token.split("-"))))
        else:
            words.append(token.capitalize())
    return " ".join(words)


def _title_word(part: str, *, first: bool) -> str:
    lower = part.lower()
    if part.isupper() and len(part) >= 2:
        return part
    if lower in ACRONYM_CASING:
        return ACRONYM_CASING[lower]
    if not first and lower in TITLE_TRAILING_STOPWORDS:
        return lower
    return part.capitalize()


def _is_live_delivery_profile(profile) -> bool:
    families = set(getattr(profile, "workload_families", []) or [])
    capabilities = set(getattr(profile, "capabilities", []) or []) | set(getattr(profile, "capability_model", []) or [])
    return bool(
        "live_streaming" in families
        or {"video_streaming", "low_latency_media_delivery", "drm_enforcement", "geo_rights_enforcement", "targeted_ad_decisioning"} & capabilities
    )


def _is_telecom_hbase_profile(profile) -> bool:
    families = set(getattr(profile, "workload_families", []) or [])
    capabilities = set(getattr(profile, "capabilities", []) or []) | set(getattr(profile, "capability_model", []) or [])
    return bool(
        getattr(profile, "domain", None) == "telecommunications"
        and (
            "telecom_network_analytics" in families
            or "data_platform_analytics" in families
            or "cdr_ingestion" in capabilities
        )
    )


def _is_document_workflow_profile(profile) -> bool:
    families = set(getattr(profile, "workload_families", []) or [])
    capabilities = set(getattr(profile, "capabilities", []) or []) | set(getattr(profile, "capability_model", []) or [])
    excluded = set(getattr(profile, "excluded_families", []) or []) | set(getattr(profile, "excluded_patterns", []) or [])
    if {"document_intelligence", "rag_assistant"} & excluded:
        return False
    return bool({"document_intelligence", "rag_assistant"} & families or {"document_retrieval", "rag_retrieval", "document_ingestion"} & capabilities)
