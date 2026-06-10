"""Deterministic capability router + frontier-domain-prior governance helpers.

The CapabilityRouter is the deterministic authority that decides how Archway should
handle a use case:

    supported | directional | discovery_needed | unsupported_or_blocked

The frontier-model domain prior (the existing ``DiscoveryPlannerService.plan()``
LLM path) is ADVISORY ONLY. It may influence ONLY:
  1. candidate interview questions (`next_best_questions`)
  2. a generic fallback-family CANDIDATE (validated against an allowlist)

It can never set the capability status, never enter pricing quantities / architecture
service selection / readiness / citations / governance / diagrams, and its self-reported
confidence never gates anything. Deterministic-known classifications always dominate.

This module also holds the shared helpers the hardened Discovery Planner uses:
sensitivity screening (fail-closed before any model call), stable hashing for
provenance, and a per-session call budget + within-session cache.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CapabilityStatus = Literal["supported", "directional", "discovery_needed", "unsupported_or_blocked"]

# Families Archway models deeply enough to be "supported" when confident.
SUPPORTED_FAMILIES = frozenset({
    "document_intelligence",
    "rag_assistant",
    "telecom_network_analytics",
    "healthcare_operations_scheduling",
    "surgical_scheduling_prediction",
    "clinical_workflow_decision_support",
    "approval_gated_workflow_automation",
    "live_streaming",
    "web_api_application",
})

# Generic fallback families (the only family tokens the model may steer us toward).
GENERIC_FALLBACK_FAMILIES = frozenset({
    "web_api_application",
    "event_driven_workflow",
    "document_rag_assistant",
    "batch_data_analytics",
    "streaming_ingestion_analytics",
    "ml_inference_workflow",
    "agentic_workflow_with_human_approval",
    "data_lake_and_bi",
    "migration_modernization",
    "observability_monitoring",
    "secure_file_processing",
    "unknown_directional",
})


# --------------------------------------------------------------------------- #
# Hashing (provenance)
# --------------------------------------------------------------------------- #
def stable_hash(value: Any) -> str:
    if isinstance(value, str):
        blob = value.encode("utf-8")
    else:
        blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


# --------------------------------------------------------------------------- #
# Sensitivity screening (fail-closed before any model call)
# --------------------------------------------------------------------------- #
# High-signal patterns only — concrete secrets / credential assignments / PHI-PII
# identifier VALUES. Bare topic words ("HIPAA", "PHI") deliberately do NOT trigger a
# skip (that would neuter the prior for whole domains; deterministic-known dominance
# already covers those). We skip on actual sensitive *values*.
_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), "aws_access_key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private_key"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"), "bearer_token"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|client_secret|access[_-]?key|auth[_-]?token|session[_-]?token)\b\s*[:=]\s*\S"), "credential_assignment"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn"),
    (re.compile(r"(?i)\bmedical record number\b|\bMRN[:#]?\s*\d"), "phi_identifier"),
    (re.compile(r"(?i)\bBEGIN AUDIT LOG\b|\baudit\.jsonl\b"), "audit_log_content"),
    # Explicit PHI/PII markers — for the MODEL-PRIOR skip only. Confident known
    # healthcare is already handled by deterministic-known dominance (model not called),
    # so this mainly protects LOW/UNKNOWN sensitive inputs from being sent to the model.
    (re.compile(r"(?i)\b(PHI|HIPAA)\b"), "phi_marker"),
    (re.compile(r"(?i)\b(patient record|medical record|clinical note|insurance claim number)"), "phi_marker"),
    (re.compile(r"(?i)\bMRN\b"), "phi_marker"),
    (re.compile(r"(?i)\bdiagnosis\b"), "phi_marker"),
    # HCM/payroll RECORD/VALUE-level markers — model-prior skip only. Bare topic words
    # ("payroll", "timecard", "benefits", "employee") deliberately do NOT trigger a skip;
    # valid HCM use cases continue with the deterministic fallback + accelerator packs.
    (re.compile(r"(?i)\b(pay statements?|payroll records?|payslips?|tax identifiers?|national id numbers?|bank account numbers?|employee identifiers?|employee ssns?|direct deposit|benefits enrollment records?|medical leave details?)\b"), "hcm_payroll_record"),
)

# --------------------------------------------------------------------------- #
# Deterministic unsafe / abuse blocker
# --------------------------------------------------------------------------- #
# HARD = unambiguous offense (verb + target). Always blocked, even if defensive words
# also appear (e.g. "create malware ... evading detection").
_HARD_ABUSE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(build|create|develop|deploy|distribute|write|generate|operate|launch|run)\b[^.]{0,40}\b(malware|ransomware|trojan|worm|spyware|keylogger|rootkit|botnet|exploit kit|c2|command[- ]and[- ]control)\b"), "malware_or_botnet"),
    (re.compile(r"(?i)\b(steal|stealing|harvest|harvesting|dump|exfiltrate|exfiltrating|siphon|capture)\b[^.]{0,40}\b(credential|credentials|password|passwords|secret|secrets|token|tokens|pii|card numbers?|ssn|customer data)\b"), "credential_or_data_theft"),
    (re.compile(r"(?i)\b(send|sending|launch|launching|run|running|operate|mass|automate|automating)\b[^.]{0,30}\b(phishing|spam|scam)\b"), "phishing_spam_scam"),
    (re.compile(r"(?i)\bphishing (campaign|kit|page|site|email)s?\b"), "phishing"),
    (re.compile(r"(?i)\bbypass(ing)?\b[^.]{0,30}\b(authentication|auth|mfa|2fa|access control|security control|waf|firewall|login)s?\b"), "bypass_security_controls"),
    (re.compile(r"(?i)\bevad(e|ing)\b[^.]{0,30}\b(detection|edr|antivirus|security monitoring|defenses?)\b"), "evade_detection"),
    (re.compile(r"(?i)\bbotnet\b|\bddos attack\b|\bdenial[- ]of[- ]service attack\b"), "attack_infrastructure"),
)

# SOFT = ambiguous nouns that are legitimate in DEFENSIVE products. Blocked only when no
# defensive/authorized framing is present.
_SOFT_ABUSE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bdata exfiltration\b"), "data_exfiltration"),
    (re.compile(r"(?i)\bcredential (theft|stuffing|harvesting)\b"), "credential_theft"),
    (re.compile(r"(?i)\bunauthorized access\b"), "unauthorized_access"),
)

_DEFENSIVE_MARKERS = (
    "detect", "detection", "prevent", "prevention", "protect", "protection",
    "defend", "defens", "mitigat", "monitor", "monitoring", "anti-", "anti ",
    "incident response", "threat intel", "blue team", "soc", "siem", "guard against",
    "authorized", "penetration test", "pentest", "red team", "ethical", "with consent",
    "compliance", "block ",
)


def _looks_abusive(raw_use_case: str) -> tuple[bool, str | None]:
    """Deterministic clearly-abusive intent check.

    HARD offense (verb+target) is always blocked. SOFT ambiguous nouns are blocked only
    when no defensive/authorized framing is present, so legitimate security products
    (detection / prevention / protection / authorized testing) are NOT blocked.
    """
    text = raw_use_case or ""
    for pattern, reason in _HARD_ABUSE_PATTERNS:
        if pattern.search(text):
            return True, reason
    low = text.lower()
    if not any(marker in low for marker in _DEFENSIVE_MARKERS):
        for pattern, reason in _SOFT_ABUSE_PATTERNS:
            if pattern.search(text):
                return True, reason
    return False, None


def screen_sensitivity(text: str | None) -> tuple[bool, str | None]:
    """Return (is_sensitive, reason). Conservative, high-signal only. Never raises."""
    if not text:
        return False, None
    for pattern, reason in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            return True, reason
    return False, None


# --------------------------------------------------------------------------- #
# Per-session frontier-prior budget + within-session cache (process-local)
# --------------------------------------------------------------------------- #
_FRONTIER_CALLS: dict[str, int] = {}
_FRONTIER_CACHE: dict[tuple[str, str], dict] = {}


def reset_frontier_state() -> None:
    _FRONTIER_CALLS.clear()
    _FRONTIER_CACHE.clear()


def frontier_calls_made(session_id: str | None) -> int:
    return _FRONTIER_CALLS.get(session_id or "_", 0)


def record_frontier_call(session_id: str | None) -> None:
    key = session_id or "_"
    _FRONTIER_CALLS[key] = _FRONTIER_CALLS.get(key, 0) + 1


def frontier_cache_get(session_id: str | None, input_hash: str) -> dict | None:
    return _FRONTIER_CACHE.get((session_id or "_", input_hash))


def frontier_cache_set(session_id: str | None, input_hash: str, payload: dict) -> None:
    _FRONTIER_CACHE[(session_id or "_", input_hash)] = payload


# --------------------------------------------------------------------------- #
# Capability decision
# --------------------------------------------------------------------------- #
@dataclass
class CapabilityDecision:
    status: CapabilityStatus
    reason: str
    deterministic_confidence: str
    matched_known_family: str | None
    generic_fallback_family: str
    fallback_family_source: Literal["deterministic", "accelerator_pack", "model_prior_unverified", "default"]
    next_best_questions: list[str] = field(default_factory=list)
    advisory_candidates_unverified: dict = field(default_factory=dict)
    model_prior: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Artifact safety: what may be generated for this use case.
    expected_artifact_level: str = "directional"
    safe_to_generate_architecture: bool = True
    safe_to_generate_pricing: bool = True
    safe_to_generate_diagrams: bool = True
    # Advisory accelerator-pack metadata (ARCHWAY_ENABLE_CAPABILITY_ACCELERATOR_PACKS).
    capability_accelerators: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        # Flag-off decisions stay byte-identical to the pre-accelerator shape.
        if not data.get("capability_accelerators"):
            data.pop("capability_accelerators", None)
        return data


def _deterministic_fallback_family(profile, raw_use_case: str) -> str:
    families = set(getattr(profile, "workload_families", []) or [])
    caps = set(getattr(profile, "capabilities", []) or []) | set(getattr(profile, "capability_model", []) or [])
    lower = (raw_use_case or "").lower()
    if {"document_intelligence", "rag_assistant"} & families or {"document_retrieval", "rag_retrieval", "document_ingestion"} & caps:
        return "document_rag_assistant"
    if "live_streaming" in families:
        return "streaming_ingestion_analytics"
    if "real_time_ingestion" in caps or "streaming" in lower:
        return "streaming_ingestion_analytics"
    if getattr(profile, "actions", None) or {"approval_gated_workflow"} & caps:
        return "agentic_workflow_with_human_approval"
    if {"predictive_ml"} & caps or "inference" in lower:
        return "ml_inference_workflow"
    if any(term in lower for term in ("migrate", "migration", "hbase", "hdfs", "modernize")):
        return "migration_modernization"
    if any(term in lower for term in ("analytics", "business intelligence", "bi dashboard", "data lake", "warehouse")):
        return "data_lake_and_bi"
    if "web_api_application" in families:
        return "web_api_application"
    if any(term in lower for term in ("observability", "monitoring", "metrics", "logs")):
        return "observability_monitoring"
    return "unknown_directional"


def _accelerator_matches(raw_use_case: str) -> list:
    """Advisory accelerator-pack matches, ONLY when the feature flag is on.

    Lazy import keeps module load acyclic (the packs module imports
    GENERIC_FALLBACK_FAMILIES from here for import-time validation) and means a
    disabled flag has zero behavioral or import surface.
    """
    try:
        from app.core.config import get_settings

        if not get_settings().enable_capability_accelerator_packs:
            return []
        from app.services.capability_accelerator_packs import match_accelerator_packs

        return match_accelerator_packs(raw_use_case)
    except Exception:
        # Advisory only: accelerator failures must never break routing.
        return []


def _model_fallback_candidate(discovery_plan: dict) -> str | None:
    """A model-suggested generic family, ACCEPTED ONLY if in the allowlist.

    Reads the model's guesses from ``prior_provenance`` (clearly model-sourced), never
    the authoritative deterministic plan fields.
    """
    provenance = discovery_plan.get("prior_provenance") or {}
    for name in (provenance.get("model_workload_family_candidates") or []):
        token = str(name).strip().lower()
        if token in GENERIC_FALLBACK_FAMILIES:
            return token
    return None


class CapabilityRouter:
    """Deterministic router. The model prior influences only questions + fallback candidate."""

    def route(self, profile, discovery_plan: dict | None = None, *, raw_use_case: str = "") -> CapabilityDecision:
        discovery_plan = discovery_plan or {}
        confidence = str(getattr(profile, "confidence", "medium") or "medium")
        families = list(getattr(profile, "workload_families", []) or [])
        domain = getattr(profile, "domain", None)

        # Safety FIRST: clearly abusive/malicious use cases are blocked deterministically —
        # never generate a (fake) AWS architecture/pricing/diagram for them.
        abusive, abuse_reason = _looks_abusive(raw_use_case)
        if abusive:
            return CapabilityDecision(
                status="unsupported_or_blocked",
                reason=f"Use case requests abusive/malicious capability ({abuse_reason}); Archway will not generate a solution for it.",
                deterministic_confidence=confidence,
                matched_known_family=None,
                generic_fallback_family="unknown_directional",
                fallback_family_source="default",
                next_best_questions=[],
                advisory_candidates_unverified={"evidence_class": "model_prior_unverified"},
                model_prior=dict(discovery_plan.get("prior_provenance") or {}),
                warnings=["unsafe_or_abusive_use_case_blocked"],
                expected_artifact_level="unsupported_explanation",
                safe_to_generate_architecture=False,
                safe_to_generate_pricing=False,
                safe_to_generate_diagrams=False,
            )

        matched_known = next((f for f in families if f in SUPPORTED_FAMILIES), None)
        # Ambiguity from the deterministic profile OR a flagged model disagreement
        # (the latter may only push us toward MORE caution, never toward "supported").
        deterministic_ambiguous = confidence == "low" or not families or domain is None
        plan_ambiguous = bool(discovery_plan.get("ambiguity_detected"))

        out_of_scope = _looks_out_of_scope(raw_use_case) and not families and not matched_known

        if out_of_scope:
            status: CapabilityStatus = "unsupported_or_blocked"
            reason = "Use case does not map to an AWS solution shape Archway can route."
        elif matched_known and confidence == "high" and not deterministic_ambiguous:
            status = "supported"
            reason = f"Deterministic high-confidence match to supported family '{matched_known}'."
        elif deterministic_ambiguous or plan_ambiguous or not families:
            status = "discovery_needed"
            reason = "Deterministic classification is low-confidence/ambiguous; clarify before locking a pattern."
        else:
            status = "directional"
            reason = "Recognized workload shape without high-confidence deep support; directional handling."

        # Advisory accelerator packs (flag-gated; deterministic keyword matching).
        accelerator_matches = _accelerator_matches(raw_use_case)

        # Generic fallback family: deterministic first; advisory sources (accelerator
        # pack, then model prior) may only fill the void.
        fallback = _deterministic_fallback_family(profile, raw_use_case)
        fallback_source: Literal["deterministic", "accelerator_pack", "model_prior_unverified", "default"] = "deterministic"
        pack_fallback_used: str | None = None
        if fallback == "unknown_directional":
            pack_candidate = next(
                (family for m in accelerator_matches for family in m.pack.candidate_fallback_families),
                None,
            )
            model_candidate = _model_fallback_candidate(discovery_plan)
            if pack_candidate:
                fallback = pack_candidate
                fallback_source = "accelerator_pack"
                pack_fallback_used = pack_candidate
            elif model_candidate:
                fallback = model_candidate
                fallback_source = "model_prior_unverified"
            else:
                fallback_source = "default"

        # Allowed model-influenced surface: interview questions only.
        next_questions = [
            str(q.get("question"))
            for q in (discovery_plan.get("top_questions") or [])
            if isinstance(q, dict) and q.get("question")
        ][:5]

        # Allowed accelerator surface: extra advisory questions (deduped, capped) +
        # metadata. Never status, readiness, pricing, architecture, or citations.
        accelerators_meta: list[dict] = []
        for match in accelerator_matches:
            appended = 0
            for question in match.pack.next_best_questions:
                if question not in next_questions and appended < 2 and len(next_questions) < 9:
                    next_questions.append(question)
                    appended += 1
            used_for = ["questions", "missing_facts"]
            if pack_fallback_used and pack_fallback_used in match.pack.candidate_fallback_families:
                used_for.append("fallback_candidate")
            accelerators_meta.append({
                "pack_id": match.pack.pack_id,
                "display_name": match.pack.display_name,
                "match_score": match.score,
                "matched_signals": list(match.matched_signals),
                "match_explanation": match.explanation,
                "advisory_only": True,
                "used_for": used_for,
                "fallback_family_candidate": pack_fallback_used if "fallback_candidate" in used_for else None,
                "questions": list(match.pack.next_best_questions),
                "missing_fact_prompts": list(match.pack.missing_fact_prompts),
                "governance_concerns": list(match.pack.governance_concerns),
                "sensitivity_concerns": list(match.pack.sensitivity_concerns),
                "pricing_question_hints": list(match.pack.pricing_question_hints),
                "notes": list(match.pack.dossier_notes),
                "disallowed_assumptions": list(match.pack.disallowed_assumptions),
            })

        # Artifact level + safety (non-abuse). unsupported_or_blocked (e.g. out-of-scope)
        # gets an explanation only; other statuses are safe to generate.
        if status == "unsupported_or_blocked":
            artifact_level = "unsupported_explanation"
            safe = False
        elif status == "supported":
            artifact_level, safe = "full", True
        elif status == "directional":
            artifact_level, safe = "directional", True
        else:
            artifact_level, safe = "discovery_questions", True

        provenance = dict(discovery_plan.get("prior_provenance") or {})
        # Advisory model candidates, surfaced for transparency but labeled unverified.
        # Sourced from provenance (model-only), never the deterministic plan fields.
        advisory = {
            "evidence_class": "model_prior_unverified",
            "domain_candidates": list(provenance.get("model_domain_candidates") or []),
            "workload_family_candidates": list(provenance.get("model_workload_family_candidates") or []),
            "model_self_confidence_display_only": provenance.get("model_self_confidence_display_only"),
        }

        return CapabilityDecision(
            status=status,
            reason=reason,
            deterministic_confidence=confidence,
            matched_known_family=matched_known,
            generic_fallback_family=fallback,
            fallback_family_source=fallback_source,
            next_best_questions=next_questions,
            advisory_candidates_unverified=advisory,
            model_prior=provenance,
            warnings=list(discovery_plan.get("warnings") or [])[:5],
            expected_artifact_level=artifact_level,
            safe_to_generate_architecture=safe,
            safe_to_generate_pricing=safe,
            safe_to_generate_diagrams=safe,
            capability_accelerators=accelerators_meta,
        )


def _looks_out_of_scope(raw_use_case: str) -> bool:
    text = (raw_use_case or "").strip().lower()
    if len(text) < 8:
        return True
    # Explicit non-AWS / non-cloud declarations that Archway cannot architect for.
    return any(marker in text for marker in (
        "on-premises only", "on premises only", "no cloud", "must not use cloud",
        "non-aws only", "do not use aws",
    ))
