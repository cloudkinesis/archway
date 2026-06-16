from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.capability_router import (
    frontier_cache_get,
    frontier_cache_set,
    frontier_calls_made,
    record_frontier_call,
    screen_sensitivity,
    stable_hash,
)
from app.services.llm.base import LLMMessage, LLMTask, LLMTaskType
from app.services.llm.model_router import ModelRouter
from app.services.pattern_catalog import PATTERNS, pricing_dimensions
from app.services.use_case_profile import UseCaseProfile


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryQuestion(BaseModel):
    id: str
    question: str
    why_it_matters: str
    expected_answer_style: str


class DiscoveryCandidate(BaseModel):
    name: str
    confidence: Literal["low", "medium", "high"] = "medium"
    rationale: str


class DiscoveryPlan(BaseModel):
    domain_candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    workload_family_candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    primary_entities: list[str] = Field(default_factory=list)
    primary_actions: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    governance_concerns: list[str] = Field(default_factory=list)
    pricing_drivers: list[str] = Field(default_factory=list)
    not_relevant_patterns: list[str] = Field(default_factory=list)
    assumptions_to_avoid: list[str] = Field(default_factory=list)
    top_questions: list[DiscoveryQuestion] = Field(default_factory=list)
    ambiguity_detected: bool = False
    ambiguity_reason: str | None = None
    advisory_only: bool = True
    generated_by: str = "deterministic"
    warnings: list[str] = Field(default_factory=list)
    # Frontier-model domain-prior provenance (advisory-only; quarantined). All model
    # contributions are limited to questions + a fallback-family candidate.
    model_prior_unverified: bool = False
    prior_provenance: dict = Field(default_factory=dict)


class DiscoveryPlannerService:
    def plan_sync(
        self,
        raw_use_case: str,
        baseline_profile: UseCaseProfile,
        known_domain_packs: list[str] | None = None,
        previous_answers: list[str] | None = None,
    ) -> DiscoveryPlan:
        return _deterministic_plan(raw_use_case, baseline_profile, known_domain_packs or sorted(PATTERNS.keys()), previous_answers or [])

    async def plan(
        self,
        raw_use_case: str,
        baseline_profile: UseCaseProfile,
        known_domain_packs: list[str] | None = None,
        previous_answers: list[str] | None = None,
        session_id: str | None = None,
    ) -> DiscoveryPlan:
        fallback = self.plan_sync(raw_use_case, baseline_profile, known_domain_packs, previous_answers)
        settings = get_settings()
        input_hash = stable_hash(raw_use_case or "")
        base_prov = {
            "source": "deterministic",
            "status": "disabled",
            "advisory_only": True,
            "used_for": "questions_and_fallback_mapping_only",
            "model_id": None,
            "sanitized_input_hash": input_hash,
            "prompt_hash": None,
            "response_hash": None,
            "cache_hit": False,
            "generated_at": _now_iso(),
            "warnings": [],
        }

        # Gate 1 — flag OFF: deterministic Discovery Planner only (default).
        if not settings.enable_frontier_domain_prior:
            fallback.prior_provenance = base_prov
            return fallback
        # Gate 2 — deterministic-known DOMINATES: do not call the model.
        if baseline_profile.confidence == "high" and baseline_profile.workload_families and baseline_profile.domain:
            fallback.prior_provenance = {**base_prov, "status": "skipped_deterministic_known"}
            return fallback
        # Gate 3 — sensitivity screen: fail closed before any model call.
        sensitive, reason = screen_sensitivity(raw_use_case)
        if sensitive:
            fallback.prior_provenance = {**base_prov, "status": "skipped_due_to_sensitivity",
                                         "warnings": [f"frontier_domain_prior_skipped_due_to_sensitivity:{reason}"]}
            fallback.warnings.append("frontier_domain_prior_skipped_due_to_sensitivity")
            return fallback
        # Gate 4 — within-session cache (reproducible per sanitized input).
        cached = frontier_cache_get(session_id, input_hash)
        if cached is not None:
            merged = _merge_plan(fallback, DiscoveryPlan(**cached["llm_plan"]), baseline_profile)
            merged.model_prior_unverified = True
            merged.prior_provenance = {**cached["provenance"], "cache_hit": True}
            return merged
        # Gate 5 — per-session call cap.
        if frontier_calls_made(session_id) >= settings.frontier_domain_prior_max_calls_per_session:
            fallback.prior_provenance = {**base_prov, "source": "frontier_model", "status": "skipped_call_cap"}
            return fallback

        payload = {
            "raw_use_case": raw_use_case,
            "deterministic_baseline_profile": {
                "domain": baseline_profile.domain,
                "workload_families": baseline_profile.workload_families,
                "capabilities": baseline_profile.capabilities,
                "entities": baseline_profile.entities,
                "actions": baseline_profile.actions,
                "signals": baseline_profile.signals,
                "metrics": [metric.__dict__ for metric in baseline_profile.metrics],
                "structured_metrics": baseline_profile.structured_metrics,
                "confidence": baseline_profile.confidence,
            },
            "known_domain_packs": known_domain_packs or sorted(PATTERNS.keys()),
            "previous_interview_answers": previous_answers or [],
            "rules": [
                "Output is advisory only.",
                "Do not mark pricing procurement-ready.",
                "Do not bypass human approval or governance controls.",
                "If uncertain or conflicting, mark ambiguity and ask a clarification question.",
                "Prefer workload-specific pricing drivers over telemetry fallback unless the use case explicitly includes sensors, telemetry, logs, devices, or streaming metrics.",
            ],
        }
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are Archway's discovery planner. Return JSON only. "
                    "Use the deterministic baseline as the safety anchor. "
                    "Your output is ADVISORY ONLY and must not override pricing safety, governance, architecture validation, or diagrams. "
                    "Do not cite sources, do not claim verification, do not invent AWS documentation. "
                    "Prefer asking for missing facts over assuming them, and state uncertainty explicitly. "
                    "If you disagree with the deterministic classifier, mark ambiguity and ask a clarification question."
                ),
            ),
            LLMMessage(role="user", content=json.dumps(payload, default=str)[:22000]),
        ]
        prompt_hash = stable_hash([m.content for m in messages])
        try:
            result = await ModelRouter().complete(
                LLMTask(task_type=LLMTaskType.discovery_planner, session_id=session_id, name="discovery_planner"),
                messages,
                response_schema=DiscoveryPlan,
                temperature=0,
                max_tokens=1800,
                timeout_seconds=45,
            )
        except Exception as exc:  # noqa: BLE001 - model failure must never crash synthesis
            record_frontier_call(session_id)
            fallback.warnings.append("frontier_domain_prior_failed")
            fallback.prior_provenance = {
                **base_prov, "source": "frontier_model", "status": "failed",
                "prompt_hash": prompt_hash,
                "warnings": [f"frontier_domain_prior_failed:{type(exc).__name__}"],
            }
            return fallback
        # Only a real provider call counts against the per-session cap (deterministic
        # no-op provider does not egress and does not consume budget).
        if result.provider != "deterministic":
            record_frontier_call(session_id)

        if result.validated and isinstance(result.parsed, DiscoveryPlan):
            merged = _merge_plan(fallback, result.parsed, baseline_profile)
            merged.generated_by = result.model_id or result.provider
            merged.warnings.extend(result.warnings)
            merged.model_prior_unverified = True
            provenance = {
                "source": "frontier_model",
                "status": "generated",
                "advisory_only": True,
                "used_for": "questions_and_fallback_mapping_only",
                "model_id": result.model_id or result.provider,
                "sanitized_input_hash": input_hash,
                "prompt_hash": prompt_hash,
                "response_hash": stable_hash(result.parsed.model_dump(mode="json")),
                "cache_hit": False,
                "generated_at": _now_iso(),
                # Model domain/family guesses live ONLY here (clearly model-sourced),
                # never in the authoritative deterministic plan fields.
                "model_domain_candidates": [c.name for c in result.parsed.domain_candidates],
                "model_workload_family_candidates": [c.name for c in result.parsed.workload_family_candidates],
                "model_self_confidence_display_only": result.parsed.confidence,
                "warnings": list(result.warnings),
            }
            merged.prior_provenance = provenance
            frontier_cache_set(session_id, input_hash, {"llm_plan": result.parsed.model_dump(mode="json"), "provenance": provenance})
            return merged

        fallback.warnings.extend(result.warnings)
        fallback.warnings.append("frontier_domain_prior_unavailable")
        fallback.prior_provenance = {
            **base_prov,
            "source": "frontier_model",
            "status": "unavailable",
            "model_id": result.model_id,
            "prompt_hash": prompt_hash,
            "warnings": list(result.warnings) + ["frontier_domain_prior_unavailable"],
        }
        return fallback


def _merge_plan(fallback: DiscoveryPlan, llm_plan: DiscoveryPlan, baseline_profile: UseCaseProfile) -> DiscoveryPlan:
    """Quarantined merge: the deterministic plan is the authoritative anchor.

    The model may influence ONLY the interview questions (and, indirectly, push toward
    a clarification question on disagreement). All other fields — pricing_drivers,
    domain/family candidates, governance, data sources, entities, actions — remain
    DETERMINISTIC so model guesses never become canonical facts or pricing/architecture
    inputs. The model's own domain/family guesses are carried separately in
    ``prior_provenance`` (clearly model-sourced) by the caller.
    """
    merged = fallback.model_copy(deep=True)
    merged.advisory_only = True

    # Allowed model influence: interview questions only.
    if llm_plan.top_questions:
        merged.top_questions = llm_plan.top_questions[:5]

    # Ambiguity / disagreement pushes toward MORE caution (a clarification question),
    # never toward "supported". This never upgrades confidence or classification.
    deterministic_domain = baseline_profile.domain
    llm_domain = llm_plan.domain_candidates[0].name if llm_plan.domain_candidates else None
    deterministic_family = baseline_profile.workload_families[0] if baseline_profile.workload_families else None
    llm_family = llm_plan.workload_family_candidates[0].name if llm_plan.workload_family_candidates else None
    if (
        (deterministic_domain and llm_domain and deterministic_domain != llm_domain)
        or (deterministic_family and llm_family and deterministic_family != llm_family)
        or llm_plan.confidence == "low"
    ):
        merged.ambiguity_detected = True
        merged.ambiguity_reason = merged.ambiguity_reason or (
            f"Deterministic classification ({deterministic_domain or 'unknown'} / {deterministic_family or 'unknown'}) "
            f"and the advisory model prior ({llm_domain or 'unknown'} / {llm_family or 'unknown'}) do not fully agree."
        )
        merged.top_questions = [
            DiscoveryQuestion(
                id="clarify-domain-shape",
                question="Which problem shape is closest: document/RAG workflow, telecom/network analytics, operational telemetry, or something else?",
                why_it_matters="This resolves domain ambiguity before pricing, architecture, and workflow assumptions drift into the wrong pattern.",
                expected_answer_style="Pick the closest workload shape and name the primary records, events, or users involved.",
            ),
            *[item for item in merged.top_questions if item.id != "clarify-domain-shape"],
        ][:5]
    return merged


def _deterministic_plan(raw_use_case: str, baseline_profile: UseCaseProfile, known_domain_packs: list[str], previous_answers: list[str]) -> DiscoveryPlan:
    lower = raw_use_case.lower()
    families = list(baseline_profile.workload_families)
    capabilities = set(baseline_profile.capabilities) | set(baseline_profile.capability_model)
    pricing_driver_list = list(dict.fromkeys((pricing_dimensions(baseline_profile) or []) + _advisory_pricing_drivers(lower, baseline_profile)))
    questions = _questions_for_plan(lower, baseline_profile, pricing_driver_list, previous_answers)
    domain = baseline_profile.domain or _advisory_domain(lower)
    domain_candidates = [DiscoveryCandidate(name=domain or "unknown", confidence=baseline_profile.confidence, rationale="Derived from deterministic classification plus discovery hints.")]
    family_candidates = [
        DiscoveryCandidate(name=item, confidence="high" if index == 0 and baseline_profile.confidence == "high" else "medium", rationale="Derived from deterministic workload family ranking.")
        for index, item in enumerate(families[:3])
    ]
    if not family_candidates:
        family_candidates = [DiscoveryCandidate(name="web_api_application", confidence="low", rationale="Fallback candidate when no stronger family was selected.")]
    ambiguity = baseline_profile.confidence == "low" or not families
    if ambiguity:
        questions = [
            DiscoveryQuestion(
                id="clarify-workload-shape",
                question="Which workload shape best describes this use case: document/RAG workflow, transactional web app, streaming telemetry, analytics platform, or another pattern?",
                why_it_matters="Low-confidence classification should be clarified before pricing, governance, and architecture patterns are chosen.",
                expected_answer_style="Name the closest workload shape and the primary records, events, or users.",
            ),
            *[item for item in questions if item.id != "clarify-workload-shape"],
        ][:5]
    return DiscoveryPlan(
        domain_candidates=domain_candidates,
        workload_family_candidates=family_candidates,
        confidence="low" if ambiguity else baseline_profile.confidence if baseline_profile.confidence in {"low", "medium", "high"} else "medium",
        primary_entities=_primary_entities(lower, baseline_profile),
        primary_actions=_primary_actions(lower, baseline_profile),
        data_sources=_data_sources(lower, baseline_profile),
        integrations=_integrations(lower, baseline_profile),
        governance_concerns=_governance(lower, baseline_profile),
        pricing_drivers=pricing_driver_list[:12],
        not_relevant_patterns=_not_relevant(lower, baseline_profile),
        assumptions_to_avoid=_assumptions_to_avoid(lower, baseline_profile),
        top_questions=questions[:5],
        ambiguity_detected=ambiguity,
        ambiguity_reason="Deterministic discovery confidence is low; ask a clarification question before locking a workload family." if ambiguity else None,
        advisory_only=True,
        generated_by="deterministic",
        warnings=[],
    )


def _advisory_domain(lower: str) -> str | None:
    if any(term in lower for term in ("contract", "clause", "obligation", "legal")):
        return "legal"
    if any(term in lower for term in ("document", "manual", "knowledge base", "citation", "rag")):
        return "document_workflow"
    return None


def _advisory_pricing_drivers(lower: str, profile: UseCaseProfile) -> list[str]:
    capabilities = set(profile.capabilities) | set(profile.capability_model)
    families = set(profile.workload_families)
    if {"document_intelligence", "rag_assistant"} & families or {"document_retrieval", "rag_retrieval", "document_ingestion"} & capabilities:
        return [
            "historical_contract_count",
            "average_pages_or_mb_per_contract",
            "new_or_updated_contracts_per_month",
            "document_types",
            "ocr_text_extraction_rate",
            "embedding_indexing_frequency",
            "rag_queries_per_day",
            "active_legal_users",
            "obligation_review_approvals_per_month",
            "downstream_metadata_update_frequency",
            "audit_retention_duration",
        ]
    if "real_time_ingestion" in profile.capabilities:
        return ["telemetry_frequency_seconds", "payload_kb", "daily_event_volume", "retention_duration", "hot_path_latency"]
    if "web_api_application" in families:
        return ["active_users", "api_requests_per_day", "background_jobs_per_day", "database_storage_gb", "audit_retention_duration"]
    return []


def _questions_for_plan(lower: str, profile: UseCaseProfile, pricing_driver_list: list[str], previous_answers: list[str]) -> list[DiscoveryQuestion]:
    families = set(profile.workload_families)
    capabilities = set(profile.capabilities) | set(profile.capability_model)
    answered_text = " ".join(previous_answers).lower()
    if "telecom_network_analytics" in families:
        return _filter_answered(
            [
                DiscoveryQuestion(id="telecom-access", question="What HBase access patterns should Archway preserve before selecting the AWS target store?", why_it_matters="Row-key design, read/write QPS, scans, hot partitions, TTL, and consistency determine the right migration target.", expected_answer_style="Describe point reads, scans, write rate, and retention."),
                DiscoveryQuestion(id="telecom-volume", question="What HDFS data volume, retention, Spark/MapReduce schedule, and cutover window should Archway assume?", why_it_matters="Migration sizing and dual-run cost depend on data volume and job cadence.", expected_answer_style="Approximate TB/PB, retention, and migration window."),
                DiscoveryQuestion(id="telecom-integrations", question="Which OSS/BSS, QoS reporting, and network analytics integrations must be preserved?", why_it_matters="Integration boundaries drive architecture shape and migration sequencing.", expected_answer_style="List the must-keep systems or reports."),
            ],
            answered_text,
        )
    if {"document_intelligence", "rag_assistant"} & families or {"document_retrieval", "rag_retrieval", "document_ingestion"} & capabilities:
        return _filter_answered(
            [
                DiscoveryQuestion(id="document-volume", question="How many historical contracts/documents, average pages or MB per document, and new or updated documents per month should Archway model?", why_it_matters="These drivers size storage, OCR/text extraction, embedding/indexing, and document-processing cost.", expected_answer_style="Counts plus a rough average size or page range are enough."),
                DiscoveryQuestion(id="document-types", question="Which document types are in scope: PDF, DOCX, scanned images, or mixed repositories, and is OCR/text extraction required?", why_it_matters="Document formats change ingestion, OCR, parsing accuracy, and review workflow design.", expected_answer_style="Name the dominant file types and whether scans need OCR."),
                DiscoveryQuestion(id="rag-usage", question="What RAG queries per day or month, embedding/indexing frequency, and active legal/procurement user count should Archway assume?", why_it_matters="This drives model invocation, vector search, refresh cadence, and concurrency assumptions.", expected_answer_style="A daily or monthly estimate is enough."),
                DiscoveryQuestion(id="obligation-workflow", question="What obligation approval volume, downstream metadata update frequency, and audit retention duration should be assumed?", why_it_matters="Workflow state transitions, external writes, and retention materially affect pricing and governance.", expected_answer_style="Approximate approvals per month plus retention duration."),
                DiscoveryQuestion(id="document-risk", question="When evidence is conflicting or a clause is low confidence, should the system flag, queue for review, or allow suggested updates only?", why_it_matters="This sets the governance boundary for legal recommendations and downstream writes.", expected_answer_style="Describe the safe default action and any exceptions."),
            ],
            answered_text,
        )
    if "healthcare_operations_scheduling" in families:
        return _filter_answered(
            [
                DiscoveryQuestion(id="healthcare-sources", question="Which OR source feeds are authoritative, and how fresh are they?", why_it_matters="Schedule, readiness, and turnover feeds drive latency, architecture, and pricing assumptions.", expected_answer_style="Name the source systems and whether they are near-real-time or batch."),
                DiscoveryQuestion(id="healthcare-volume", question="What hospital count, active OR count, scheduled surgeries per day, and refresh cadence should the POC model?", why_it_matters="These are the core workload drivers for pricing and operational scale.", expected_answer_style="Approximate POC scope is fine."),
            ],
            answered_text,
        )
    if "live_streaming" in families:
        return _filter_answered(
            [
                DiscoveryQuestion(id="media-volume", question="What viewer-hours, peak concurrent viewers, and live channel-hours should Archway assume?", why_it_matters="These are the primary delivery and origin cost drivers.", expected_answer_style="Use a conservative event forecast or historical comparable."),
                DiscoveryQuestion(id="media-rights", question="Which DRM, consent, geo-rights, ad decision, and QoE systems must be integrated?", why_it_matters="Playback control and ad/QoE services shape architecture and pricing materially.", expected_answer_style="List the required external controls and observability systems."),
            ],
            answered_text,
        )
    if "real_time_ingestion" in capabilities:
        return _filter_answered(
            [
                DiscoveryQuestion(id="telemetry-volume", question="What reporting frequency and payload size should I use for telemetry pricing?", why_it_matters="This drives ingestion, stream processing, storage, logging, and inference cost.", expected_answer_style="A rough event interval and message size per source is enough."),
                DiscoveryQuestion(id="telemetry-latency", question="What detection latency is required for the hot path?", why_it_matters="This determines whether the design needs streaming inference, edge processing, or batch analytics.", expected_answer_style="State the target in seconds or minutes."),
                DiscoveryQuestion(id="telemetry-retention", question="How long must raw, feature, and scored telemetry be retained?", why_it_matters="Retention drives hot storage, archive, audit, and replay architecture.", expected_answer_style="Split hot retention and long-term retention if you know them."),
            ],
            answered_text,
        )
    if "web_api_application" in families:
        return _filter_answered(
            [
                DiscoveryQuestion(id="web-scale", question="How many active users, API requests per day, and async jobs per day should Archway model?", why_it_matters="These drivers size compute, database throughput, queues, and observability.", expected_answer_style="A rough daily estimate is enough."),
                DiscoveryQuestion(id="web-data", question="What data retention, file storage, and audit requirements apply to the application?", why_it_matters="Storage, backup, and compliance requirements can dominate cost and design choices.", expected_answer_style="State retention windows and whether uploads or audit logs are required."),
            ],
            answered_text,
        )
    return _filter_answered(
        [
            DiscoveryQuestion(id="unknown-shape", question="What are the primary records, events, or documents this system processes each day or month?", why_it_matters="This anchors pricing and architecture around real workload units instead of defaults.", expected_answer_style="Name the main unit of work and a rough daily or monthly volume."),
            DiscoveryQuestion(id="unknown-integrations", question="Which existing systems must be read from or updated, and which updates need human approval?", why_it_matters="Integration and governance boundaries determine architecture and safety controls.", expected_answer_style="List the systems and say whether writes are approval-gated."),
            DiscoveryQuestion(id="unknown-latency", question="What response or processing latency matters most for the first release?", why_it_matters="Latency distinguishes interactive, near-real-time, and batch shapes.", expected_answer_style="State the target in seconds, minutes, or hours."),
        ],
        answered_text,
    )


def _filter_answered(questions: list[DiscoveryQuestion], answered_text: str) -> list[DiscoveryQuestion]:
    if not answered_text:
        return questions
    kept = []
    for item in questions:
        anchor = item.question.split("?", 1)[0].lower()
        if anchor and anchor not in answered_text:
            kept.append(item)
    return kept or questions


def _primary_entities(lower: str, profile: UseCaseProfile) -> list[str]:
    entities = list(profile.entities)
    extra = []
    if _document_pattern_allowed(profile) and any(term in lower for term in ("contract", "clause", "obligation")):
        extra.extend(["contracts", "clauses", "obligations"])
    if "hbase" in lower or "hdfs" in lower:
        extra.extend(["hbase tables", "hdfs datasets"])
    return list(dict.fromkeys(extra + entities))[:8]


def _primary_actions(lower: str, profile: UseCaseProfile) -> list[str]:
    actions = list(profile.actions)
    if any(term in lower for term in ("approval workflow", "approve", "obligation tracking")):
        actions.extend(["approval_workflow", "metadata_update"])
    return list(dict.fromkeys(actions))[:8]


def _data_sources(lower: str, profile: UseCaseProfile) -> list[str]:
    sources = []
    document_allowed = _document_pattern_allowed(profile)
    if document_allowed and any(term in lower for term in ("contract", "document", "agreement")):
        sources.append("contract and document repository")
    if document_allowed and "rag" in lower:
        sources.append("vector index / retrieval corpus")
    if "hbase" in lower or "hdfs" in lower:
        sources.append("HBase and HDFS data stores")
    if "telemetry" in lower or "sensor" in lower or "iot" in lower:
        sources.append("telemetry streams")
    return list(dict.fromkeys(sources))[:8]


def _integrations(lower: str, profile: UseCaseProfile) -> list[str]:
    items = []
    if any(term in lower for term in ("epic", "ehr", "oss/bss", "sap", "crm")):
        items.append("existing enterprise systems")
    if any(term in lower for term in ("approval", "workflow")):
        items.append("approval workflow system")
    return list(dict.fromkeys(items or [integration for integration in ["existing business systems"] if not profile.actions]))[:8]


def _governance(lower: str, profile: UseCaseProfile) -> list[str]:
    issues = []
    if any(term in lower for term in ("approval", "write", "update", "block")) or profile.actions:
        issues.append("human approval and audit trail for external writes or workflow changes")
    if _document_pattern_allowed(profile) and ("rag" in lower or "document" in lower):
        issues.append("grounded answers, citation discipline, and low-confidence escalation")
    return issues[:8]


def _not_relevant(lower: str, profile: UseCaseProfile) -> list[str]:
    blocked = list(profile.excluded_families or [])
    if _document_pattern_allowed(profile) and any(term in lower for term in ("contract", "clause", "obligation", "rag")):
        blocked.extend(["industrial_iot_streaming_ml", "field_service_automation"])
    if any(term in lower for term in ("sensor", "telemetry", "smart meter", "transformer")):
        blocked.extend(["rag_assistant"])
    return list(dict.fromkeys(blocked))[:8]


def _assumptions_to_avoid(lower: str, profile: UseCaseProfile) -> list[str]:
    items = []
    if _document_pattern_allowed(profile) and any(term in lower for term in ("contract", "clause", "obligation", "rag")):
        items.append("Do not assume telemetry frequency or payload size for document/RAG workloads.")
        items.append("Do not assume downstream document updates can bypass approval.")
    if "hbase" in lower or "hdfs" in lower:
        items.append("Do not choose a target store before confirming HBase access patterns.")
    if "sensor" in lower or "telemetry" in lower:
        items.append("Do not assume document or RAG retrieval patterns for telemetry workloads.")
    return items[:8]


def _document_pattern_allowed(profile: UseCaseProfile) -> bool:
    excluded = set(profile.excluded_families or []) | set(profile.excluded_patterns or [])
    capabilities = set(profile.capabilities or []) | set(profile.capability_model or [])
    families = set(profile.workload_families or [])
    if {"rag_assistant", "document_intelligence", "document_qa_chatbot", "contract_review", "ocr_document_pipeline"} & excluded:
        return False
    return bool({"document_intelligence", "rag_assistant"} & families or {"document_retrieval", "rag_retrieval", "document_ingestion"} & capabilities)
