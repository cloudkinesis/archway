from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.models.domain import OpenQuestion, SynthesisQuestion, Assumption
from app.services.agentic.live_audit import LiveCallAudit
from app.services.agentic.live_bedrock_harness import LiveRunContext, live_call
from app.services.capability_extractor import explicit_negative_constraints
from app.services.dossier_manifest import stable_json_hash
from app.services.llm.base import LLMMessage, LLMTaskType
from app.services.metric_extractor import extract_metrics
from app.services.pricing_filter_mapper import _SERVICE_CODE_ALIASES, pricing_filter_plan_for_service
from app.services.use_case_profile import ExtractedMetric, UseCaseProfile


SCHEMA_VERSION = "open_world_understanding_v1"
FactKind = Literal["metric", "explicit_exclusion"]
ServiceValidationState = Literal["known-real", "unknown-unverified", "likely-hallucinated"]
ValidationSeverity = Literal["error", "warning", "info"]


class CanonicalSourceFact(BaseModel):
    fact_id: str
    kind: FactKind
    source_text: str
    normalized_value: float | str | None = None
    unit: str | None = None
    label: str


class CanonicalCandidate(BaseModel):
    label: str
    source_text: str | None = None
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: str | None = None
    provenance: Literal["user_input", "model_proposed", "derived"] = "model_proposed"


class CanonicalQuestion(BaseModel):
    question: str
    why_it_matters: str
    impact: Literal["pricing", "security", "architecture", "performance", "compliance", "scope"] = "architecture"
    expected_answer_style: str = "A concrete value, range, or 'unknown, let Archway assume'."


class CanonicalWorkloadUnderstanding(BaseModel):
    schema_version: str = SCHEMA_VERSION
    domain_candidates: list[CanonicalCandidate] = Field(default_factory=list)
    workload_intent: str
    actors: list[CanonicalCandidate] = Field(default_factory=list)
    source_systems: list[CanonicalCandidate] = Field(default_factory=list)
    events_signals: list[CanonicalCandidate] = Field(default_factory=list)
    data_classes: list[CanonicalCandidate] = Field(default_factory=list)
    actions_workflows: list[CanonicalCandidate] = Field(default_factory=list)
    constraints: list[CanonicalCandidate] = Field(default_factory=list)
    scale_metrics: list[CanonicalSourceFact] = Field(default_factory=list)
    latency_slos: list[CanonicalSourceFact] = Field(default_factory=list)
    retention: list[CanonicalSourceFact] = Field(default_factory=list)
    exclusions: list[CanonicalSourceFact] = Field(default_factory=list)
    risks_unknowns: list[str] = Field(default_factory=list)
    candidate_aws_capabilities: list[CanonicalCandidate] = Field(default_factory=list)
    candidate_aws_services: list[CanonicalCandidate] = Field(default_factory=list)
    missing_questions: list[CanonicalQuestion] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"


class ServiceValidation(BaseModel):
    service_name: str
    state: ServiceValidationState
    service_code: str | None = None
    reason: str


class UnderstandingValidationIssue(BaseModel):
    severity: ValidationSeverity
    code: str
    message: str
    target: str | None = None


class OpenWorldUnderstandingTrace(BaseModel):
    enabled: bool
    accepted: bool
    fallback_used: bool = False
    schema_version: str = SCHEMA_VERSION
    provider: str
    model_id: str | None = None
    prompt_hash: str | None = None
    response_hash: str | None = None
    input_hash: str
    output_hash: str
    canonical_fact_snapshot_hash: str
    source_facts: list[CanonicalSourceFact] = Field(default_factory=list)
    understanding: CanonicalWorkloadUnderstanding | None = None
    validation_issues: list[UnderstandingValidationIssue] = Field(default_factory=list)
    service_validations: list[ServiceValidation] = Field(default_factory=list)
    live_call: LiveCallAudit | None = None
    reproducibility_posture: dict[str, str] = Field(default_factory=dict)


class OpenWorldUnderstandingResult(BaseModel):
    profile: UseCaseProfile | None = None
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    synthesis_questions: list[SynthesisQuestion] = Field(default_factory=list)
    trace: OpenWorldUnderstandingTrace


class OpenWorldUnderstandingService:
    def build(
        self,
        raw_use_case: str,
        *,
        settings: Settings | None = None,
        session_id: str | None = None,
        run_context: LiveRunContext | None = None,
    ) -> OpenWorldUnderstandingResult:
        settings = settings or get_settings()
        source_facts = extract_source_facts(raw_use_case)
        input_hash = stable_json_hash({
            "raw_use_case": raw_use_case,
            "source_facts": [fact.model_dump(mode="json") for fact in source_facts],
            "schema_version": SCHEMA_VERSION,
        })
        if not settings.enable_open_world_understanding:
            return _disabled_result(input_hash, source_facts, "ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING is false.")
        if settings.agentic_mode != "live_demo":
            return _disabled_result(input_hash, source_facts, f"agentic_mode:{settings.agentic_mode}")

        messages = _messages(raw_use_case, source_facts)
        run_context = run_context or LiveRunContext(session_id=session_id, raw_use_case=raw_use_case)
        run_context.canonical_fact_snapshot_hash = stable_json_hash([fact.model_dump(mode="json") for fact in source_facts])
        call = live_call(
            LLMTaskType.open_world_understanding,
            messages,
            CanonicalWorkloadUnderstanding,
            session_id=session_id,
            lane="open_world_understanding",
            run_context=run_context,
            sensitivity_text=raw_use_case,
        )
        if isinstance(call.parsed, CanonicalWorkloadUnderstanding):
            return build_result_from_understanding(
                raw_use_case,
                call.parsed,
                source_facts=source_facts,
                provider=call.audit.provider,
                model_id=call.audit.model_id,
                prompt_hash=call.audit.prompt_hash,
                response_hash=call.audit.response_hash,
                live_call=call.audit,
            )
        trace = _base_trace(input_hash, source_facts, provider=call.audit.provider, model_id=call.audit.model_id)
        trace.enabled = True
        trace.live_call = call.audit
        trace.validation_issues.append(UnderstandingValidationIssue(
            severity="error",
            code="open_world_understanding.unavailable",
            message=call.audit.error_message or call.audit.skip_reason or "Open-world understanding did not return a usable schema.",
        ))
        trace.output_hash = stable_json_hash(trace.model_dump(mode="json"))
        return OpenWorldUnderstandingResult(trace=trace)


def build_result_from_understanding(
    raw_use_case: str,
    understanding: CanonicalWorkloadUnderstanding,
    *,
    source_facts: list[CanonicalSourceFact] | None = None,
    provider: str = "fixture",
    model_id: str | None = None,
    prompt_hash: str | None = None,
    response_hash: str | None = None,
    live_call: LiveCallAudit | None = None,
) -> OpenWorldUnderstandingResult:
    source_facts = source_facts or extract_source_facts(raw_use_case)
    input_hash = stable_json_hash({
        "raw_use_case": raw_use_case,
        "source_facts": [fact.model_dump(mode="json") for fact in source_facts],
        "schema_version": SCHEMA_VERSION,
    })
    issues = validate_fact_preservation(source_facts, understanding)
    issues.extend(validate_exclusions(source_facts, understanding))
    service_validations = [classify_aws_service(item.label) for item in understanding.candidate_aws_services]
    issues.extend(
        UnderstandingValidationIssue(
            severity="error",
            code="open_world_understanding.hallucinated_service",
            message=f"Candidate service '{validation.service_name}' does not look like a real AWS service.",
            target="candidate_aws_services",
        )
        for validation in service_validations
        if validation.state == "likely-hallucinated"
    )
    accepted = not any(issue.severity == "error" for issue in issues)
    trace = OpenWorldUnderstandingTrace(
        enabled=True,
        accepted=accepted,
        provider=provider,
        model_id=model_id,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        input_hash=input_hash,
        output_hash="sha256:pending",
        canonical_fact_snapshot_hash=stable_json_hash([fact.model_dump(mode="json") for fact in source_facts]),
        source_facts=source_facts,
        understanding=understanding,
        validation_issues=issues,
        service_validations=service_validations,
        live_call=live_call,
        reproducibility_posture=_reproducibility_posture(model_id),
    )
    if not accepted:
        trace.output_hash = stable_json_hash(trace.model_dump(mode="json"))
        return OpenWorldUnderstandingResult(trace=trace)
    profile = adapt_to_profile(raw_use_case, understanding, source_facts, trace)
    questions = generated_open_questions(understanding)
    trace.output_hash = stable_json_hash(trace.model_dump(mode="json"))
    profile.open_world_understanding["trace_hash"] = trace.output_hash
    profile.discovery_plan["open_world_trace_hash"] = trace.output_hash
    return OpenWorldUnderstandingResult(
        profile=profile,
        open_questions=questions,
        synthesis_questions=generated_synthesis_questions(questions),
        trace=trace,
    )


def extract_source_facts(raw_use_case: str) -> list[CanonicalSourceFact]:
    metrics = extract_metrics(raw_use_case)
    facts: list[CanonicalSourceFact] = []
    for section, values in (("asset_counts", metrics.asset_counts), ("business_targets", metrics.business_targets)):
        for label, value in values.items():
            if value.derived:
                continue
            facts.append(_source_fact(
                kind="metric",
                label=label,
                source_text=value.raw,
                normalized_value=value.value,
                unit=value.unit,
                namespace=section,
            ))
    seen = {fact.source_text.lower() for fact in facts}
    for value, unit, raw in _explicit_numeric_phrase_facts(raw_use_case):
        if raw.lower() in seen:
            continue
        facts.append(_source_fact(
            kind="metric",
            label=_slug(unit),
            source_text=raw,
            normalized_value=value,
            unit=unit.lower(),
            namespace="explicit_numbers",
        ))
        seen.add(raw.lower())
    for exclusion in _explicit_exclusion_phrases(raw_use_case):
        facts.append(_source_fact(
            kind="explicit_exclusion",
            label=_slug(exclusion),
            source_text=exclusion,
            normalized_value=_normalize_exclusion(exclusion),
            unit=None,
            namespace="exclusions",
        ))
    return sorted({fact.fact_id: fact for fact in facts}.values(), key=lambda item: item.fact_id)


def validate_fact_preservation(
    source_facts: list[CanonicalSourceFact],
    understanding: CanonicalWorkloadUnderstanding,
) -> list[UnderstandingValidationIssue]:
    proposed = list(understanding.scale_metrics) + list(understanding.latency_slos) + list(understanding.retention) + list(understanding.exclusions)
    issues: list[UnderstandingValidationIssue] = []
    for fact in source_facts:
        if not _fact_preserved(fact, proposed):
            issues.append(UnderstandingValidationIssue(
                severity="error",
                code="open_world_understanding.fact_not_preserved",
                message=f"User-stated fact was not preserved: {fact.source_text}",
                target=fact.fact_id,
            ))
    return issues


def validate_exclusions(
    source_facts: list[CanonicalSourceFact],
    understanding: CanonicalWorkloadUnderstanding,
) -> list[UnderstandingValidationIssue]:
    exclusions = [fact for fact in source_facts if fact.kind == "explicit_exclusion"]
    if not exclusions:
        return []
    searchable = " ".join(
        item.label
        for bucket in (
            understanding.domain_candidates,
            understanding.actors,
            understanding.source_systems,
            understanding.events_signals,
            understanding.data_classes,
            understanding.actions_workflows,
            understanding.constraints,
            understanding.candidate_aws_capabilities,
            understanding.candidate_aws_services,
        )
        for item in bucket
    ).lower()
    searchable += " " + " ".join(question.question for question in understanding.missing_questions).lower()
    issues: list[UnderstandingValidationIssue] = []
    for fact in exclusions:
        forbidden = _forbidden_terms(str(fact.normalized_value or fact.label))
        if any(term and term in searchable for term in forbidden):
            issues.append(UnderstandingValidationIssue(
                severity="error",
                code="open_world_understanding.exclusion_violated",
                message=f"Explicit exclusion was reintroduced: {fact.source_text}",
                target=fact.fact_id,
            ))
    return issues


def classify_aws_service(service_name: str) -> ServiceValidation:
    plan = pricing_filter_plan_for_service(service_name)
    if plan:
        return ServiceValidation(
            service_name=service_name,
            state="known-real",
            service_code=plan.service_code,
            reason="Matched local AWS pricing/service alias vocabulary.",
        )
    normalized = _normalize_service_name(service_name)
    if re.search(r"\b(aws|amazon)\b", normalized) and not _obviously_fake_service(normalized):
        return ServiceValidation(
            service_name=service_name,
            state="unknown-unverified",
            reason="Looks like an AWS service name but is not in the local vocabulary; accepted with model_proposed label.",
        )
    if any(token in normalized for token, _, _ in _SERVICE_CODE_ALIASES):
        return ServiceValidation(
            service_name=service_name,
            state="known-real",
            reason="Contained a local AWS service alias.",
        )
    return ServiceValidation(
        service_name=service_name,
        state="likely-hallucinated",
        reason="Does not match local aliases or AWS/Amazon service-name shape.",
    )


def adapt_to_profile(
    raw_use_case: str,
    understanding: CanonicalWorkloadUnderstanding,
    source_facts: list[CanonicalSourceFact],
    trace: OpenWorldUnderstandingTrace,
) -> UseCaseProfile:
    metrics_structured = extract_metrics(raw_use_case)
    metrics: list[ExtractedMetric] = []
    for section, values in (("asset_count", metrics_structured.asset_counts), ("business_target", metrics_structured.business_targets)):
        for label, value in values.items():
            metrics.append(ExtractedMetric(label=label, value=value.value, unit=value.unit, raw=value.raw, kind=section))
    capabilities = _capabilities_from_understanding(understanding)
    families = _families_from_understanding(understanding, capabilities)
    exclusions = [_slug(str(fact.normalized_value or fact.label)) for fact in source_facts if fact.kind == "explicit_exclusion"]
    top_domain = _first_label(understanding.domain_candidates)
    profile = UseCaseProfile(
        domain=_slug(top_domain) if top_domain else None,
        workload_families=families or ["web_api_application"],
        excluded_families=_excluded_families_from_facts(exclusions),
        capabilities=capabilities,
        entities=[_slug(item.label) for item in understanding.actors + understanding.source_systems],
        signals=[_slug(item.label) for item in understanding.events_signals],
        actions=[_slug(item.label) for item in understanding.actions_workflows],
        metrics=metrics,
        capability_model=capabilities,
        excluded_patterns=exclusions,
        deployment_posture=[],
        latency_class=_latency_class_from_facts(source_facts),
        structured_metrics=metrics_structured.model_dump(),
        latency_target=_first_fact_text(understanding.latency_slos),
        business_targets=[understanding.workload_intent] if understanding.workload_intent else [],
        confidence=understanding.confidence,
        discovery_plan={
            "source": "open_world_understanding",
            "top_questions": [
                {
                    "question": question.question,
                    "why_it_matters": question.why_it_matters,
                    "expected_answer_style": question.expected_answer_style,
                    "impact": question.impact,
                }
                for question in understanding.missing_questions
            ],
            "service_validations": [item.model_dump(mode="json") for item in trace.service_validations],
        },
        profile_source="open_world_understanding",
        open_world_understanding={
            "schema_version": understanding.schema_version,
            "trace_hash": trace.output_hash,
            "input_hash": trace.input_hash,
            "canonical_fact_snapshot_hash": trace.canonical_fact_snapshot_hash,
            "service_validations": [item.model_dump(mode="json") for item in trace.service_validations],
            "validation_issue_count": len(trace.validation_issues),
            "reproducibility_posture": trace.reproducibility_posture,
            "understanding": understanding.model_dump(mode="json"),
        },
    )
    return profile


def generated_open_questions(understanding: CanonicalWorkloadUnderstanding) -> list[OpenQuestion]:
    questions = [
        OpenQuestion(text=question.question, impact=question.impact)
        for question in understanding.missing_questions
        if question.question.strip()
    ]
    required = [
        OpenQuestion(text="Which AWS region, data residency, and compliance constraints are hard requirements?", impact="compliance"),
        OpenQuestion(text="Which workload volumes, retention periods, and latency targets are confirmed versus assumptions?", impact="pricing"),
        OpenQuestion(text="Which automated actions require human approval or policy gates?", impact="security"),
    ]
    seen = {question.text.lower() for question in questions}
    for question in required:
        if question.text.lower() not in seen:
            questions.append(question)
    return questions[:8]


def generated_synthesis_questions(open_questions: list[OpenQuestion]) -> list[SynthesisQuestion]:
    questions: list[SynthesisQuestion] = []
    for index, question in enumerate(open_questions[:6]):
        assumption = Assumption(
            text=f"Assume best-practice defaults for: {question.text}",
            reason="The open-world understanding identified this as unresolved; Archway can proceed with a clearly labeled assumption.",
            impact=question.impact,
            confidence="medium",
        )
        questions.append(SynthesisQuestion(
            id=f"open-world-{index}",
            prompt=question.text,
            why_it_matters=_why_for_impact(question.impact),
            options=["Known value or policy", "Approximate estimate", "Unknown, let Archway assume"],
            recommended_option="Unknown, let Archway assume",
            assumption_if_skipped=assumption,
        ))
    return questions


def _messages(raw_use_case: str, source_facts: list[CanonicalSourceFact]) -> list[LLMMessage]:
    payload = {
        "raw_use_case": raw_use_case,
        "schema_version": SCHEMA_VERSION,
        "deterministically_extracted_facts": [fact.model_dump(mode="json") for fact in source_facts],
        "instructions": [
            "Do not use any deterministic workload family or preselected category.",
            "Preserve every source_text exactly in the appropriate scale_metrics, latency_slos, retention, or exclusions list.",
            "Represent the use case as a business process first and AWS services second.",
            "Use specific actors and source systems; avoid generic users/operators unless the input is generic.",
            "Ask missing questions that would materially affect architecture, pricing, security, performance, or compliance.",
            "Candidate AWS services are proposals only; deterministic validation will label them.",
        ],
    }
    return [
        LLMMessage(role="system", content=(
            "You are Archway's D23 open-world use-case understanding proposer. "
            "Return JSON only matching the provided schema. You propose; deterministic validation decides what is usable."
        )),
        LLMMessage(role="user", content=json.dumps(payload, indent=2, sort_keys=True)[:24000]),
    ]


def _disabled_result(input_hash: str, source_facts: list[CanonicalSourceFact], reason: str) -> OpenWorldUnderstandingResult:
    trace = _base_trace(input_hash, source_facts, provider="disabled")
    trace.fallback_used = True
    trace.validation_issues.append(UnderstandingValidationIssue(
        severity="info",
        code="open_world_understanding.disabled",
        message=reason,
    ))
    trace.output_hash = stable_json_hash(trace.model_dump(mode="json"))
    return OpenWorldUnderstandingResult(trace=trace)


def _base_trace(
    input_hash: str,
    source_facts: list[CanonicalSourceFact],
    *,
    provider: str,
    model_id: str | None = None,
) -> OpenWorldUnderstandingTrace:
    return OpenWorldUnderstandingTrace(
        enabled=False,
        accepted=False,
        fallback_used=True,
        provider=provider,
        model_id=model_id,
        input_hash=input_hash,
        output_hash="sha256:pending",
        canonical_fact_snapshot_hash=stable_json_hash([fact.model_dump(mode="json") for fact in source_facts]),
        source_facts=source_facts,
        reproducibility_posture=_reproducibility_posture(model_id),
    )


def _source_fact(
    *,
    kind: FactKind,
    label: str,
    source_text: str,
    normalized_value: float | str | None,
    unit: str | None,
    namespace: str,
) -> CanonicalSourceFact:
    payload = {
        "kind": kind,
        "label": label,
        "source_text": source_text.strip(),
        "normalized_value": normalized_value,
        "unit": unit,
        "namespace": namespace,
    }
    return CanonicalSourceFact(
        fact_id="fact_" + stable_json_hash(payload).removeprefix("sha256:")[:12],
        kind=kind,
        source_text=source_text.strip(),
        normalized_value=normalized_value,
        unit=unit,
        label=label,
    )


def _explicit_exclusion_phrases(text: str) -> list[str]:
    phrases = []
    for match in re.finditer(r"(?i)\bnot\s+(?:a\s+|an\s+)?([^.;,\n]+)", text):
        phrase = "not " + match.group(1).strip()
        phrase = re.split(r"\s+and\s+not\s+", phrase, maxsplit=1, flags=re.I)[0].strip()
        if 4 <= len(phrase) <= 120:
            phrases.append(phrase)
    constraints = explicit_negative_constraints(text.lower())
    for label in constraints.get("labels") or []:
        phrases.append(f"not {label.replace('_', ' ')}")
    return sorted(set(phrases))


def _explicit_numeric_phrase_facts(text: str) -> list[tuple[float, str, str]]:
    stopwords = {
        "and", "or", "with", "using", "from", "for", "to", "that", "which", "who", "must", "should",
        "is", "are", "was", "were", "it", "they", "but", "not", "before", "after", "within", "across",
    }
    facts: list[tuple[float, str, str]] = []
    for match in re.finditer(r"\b(?P<value>\d[\d,]*(?:\.\d+)?)\b(?P<tail>(?:[\s/-]+[A-Za-z][A-Za-z0-9/-]*){1,4})", text):
        tokens = [token.strip("-/").lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9/-]*", match.group("tail"))]
        unit_tokens: list[str] = []
        for token in tokens:
            if token in stopwords:
                break
            unit_tokens.append(token)
            if len(unit_tokens) >= 3:
                break
        if not unit_tokens:
            continue
        raw_value = match.group("value")
        value = float(raw_value.replace(",", ""))
        unit = " ".join(unit_tokens)
        raw = f"{raw_value} {unit}"
        facts.append((value, unit, raw))
    return facts


def _normalize_exclusion(exclusion: str) -> str:
    value = re.sub(r"(?i)^not\s+(?:a\s+|an\s+)?", "", exclusion).strip()
    return _slug(value)


def _fact_preserved(fact: CanonicalSourceFact, proposed: list[CanonicalSourceFact]) -> bool:
    for item in proposed:
        if item.source_text.strip().lower() == fact.source_text.strip().lower():
            return True
        if fact.kind == "metric" and item.normalized_value == fact.normalized_value and (item.unit or "").lower() == (fact.unit or "").lower():
            return True
        if fact.kind == "explicit_exclusion" and str(item.normalized_value or item.label) == str(fact.normalized_value or fact.label):
            return True
    return False


def _forbidden_terms(normalized_exclusion: str) -> list[str]:
    terms = [normalized_exclusion.replace("_", " ")]
    constraints = explicit_negative_constraints("not " + normalized_exclusion.replace("_", " "))
    for key in ("families", "patterns", "capabilities", "labels"):
        terms.extend(str(item).replace("_", " ") for item in constraints.get(key) or [])
    return sorted(set(term.lower().strip() for term in terms if term.strip()))


def _normalize_service_name(service_name: str) -> str:
    return " ".join(service_name.lower().replace("/", " ").replace("-", " ").split())


def _obviously_fake_service(normalized: str) -> bool:
    fake_terms = ("magic", "baggageai", "fraudbrain", "madeup", "fictional", "fake")
    return any(term in normalized for term in fake_terms)


def _capabilities_from_understanding(understanding: CanonicalWorkloadUnderstanding) -> list[str]:
    capabilities: list[str] = []
    aliases = {
        "event streaming": "stream_ingestion",
        "streaming": "stream_ingestion",
        "stream processing": "stream_processing",
        "inference": "ml_inference",
        "prediction": "ml_inference",
        "machine learning": "ml_inference",
        "alerting": "alerting_notification",
        "notification": "alerting_notification",
        "workflow": "event_driven_workflow",
        "audit": "audit_trail",
        "observability": "observability",
        "data lake": "data_lake",
        "object storage": "object_storage",
        "private connectivity": "private_connectivity",
        "edge": "edge_processing",
        "rag": "rag_retrieval",
        "document ingestion": "document_ingestion",
    }
    for item in understanding.candidate_aws_capabilities:
        label = item.label.lower()
        slug = _slug(label)
        capabilities.append(aliases.get(label, aliases.get(slug.replace("_", " "), slug)))
    if understanding.events_signals and "stream_ingestion" not in capabilities:
        capabilities.append("stream_ingestion")
    if understanding.actions_workflows and "event_driven_workflow" not in capabilities:
        capabilities.append("event_driven_workflow")
    capabilities.extend(["security_governance", "observability", "audit_trail"])
    return list(dict.fromkeys(capabilities))


def _families_from_understanding(understanding: CanonicalWorkloadUnderstanding, capabilities: list[str]) -> list[str]:
    labels = " ".join([understanding.workload_intent, *[item.label for item in understanding.domain_candidates]]).lower()
    families: list[str] = []
    if {"rag_retrieval", "document_ingestion"} & set(capabilities):
        families.append("rag_assistant" if "rag_retrieval" in capabilities else "document_intelligence")
    if {"stream_ingestion", "stream_processing", "ml_inference"} & set(capabilities):
        families.append("real_time_anomaly_detection" if "anomaly" in labels or "prediction" in labels else "operational_event_prediction_workflow")
    if "event_driven_workflow" in capabilities:
        families.append("agentic_workflow")
    if "data_lake" in capabilities or understanding.data_classes:
        families.append("data_platform_analytics")
    return list(dict.fromkeys(families))[:5] or ["web_api_application"]


def _excluded_families_from_facts(exclusions: list[str]) -> list[str]:
    excluded: list[str] = []
    for item in exclusions:
        constraints = explicit_negative_constraints("not " + item.replace("_", " "))
        excluded.extend(constraints.get("families") or [])
    return list(dict.fromkeys(excluded))


def _latency_class_from_facts(source_facts: list[CanonicalSourceFact]) -> str | None:
    for fact in source_facts:
        if "latency" in fact.label and fact.unit:
            if "millisecond" in fact.unit:
                return "sub_second"
            if "second" in fact.unit:
                return "seconds"
            if "minute" in fact.unit:
                return "minutes"
    return None


def _first_label(items: list[CanonicalCandidate]) -> str | None:
    return items[0].label if items else None


def _first_fact_text(items: list[CanonicalSourceFact]) -> str | None:
    return items[0].source_text if items else None


def _why_for_impact(impact: str) -> str:
    return {
        "pricing": "This controls workload quantities and whether pricing can stay directional or needs more confirmation.",
        "security": "This sets the safety boundary for actions, access, audit, and approval gates.",
        "performance": "This controls latency and throughput design choices.",
        "compliance": "This affects region, data handling, evidence, and readiness claims.",
        "scope": "This prevents the solution from solving the wrong problem.",
    }.get(impact, "This clarifies workload shape and architecture choices.")


def _reproducibility_posture(model_id: str | None) -> dict[str, str]:
    return {
        "model": model_id or "not_invoked",
        "temperature": "0",
        "posture": "facts_reproducible_llm_framing_stable_not_byte_identical",
        "fact_authority": "deterministic_extraction_plus_verbatim_preservation",
    }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
