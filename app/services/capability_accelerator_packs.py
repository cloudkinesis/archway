"""Capability accelerator packs — advisory intake/question-quality hints.

These packs improve use-case understanding for well-known capability ecosystems
(better first questions, missing-fact prompts, governance/sensitivity notes, and
a generic fallback-family candidate). They are ADVISORY ONLY:

Allowed influence:    next-best questions, missing-fact prompts, advisory
                      governance/sensitivity notes, and a generic fallback-family
                      candidate used ONLY when the deterministic fallback is
                      ``unknown_directional``.
Forbidden influence:  pricing quantities/drivers, architecture service selection,
                      final capability status, readiness gates, citations,
                      governance enforcement, diagram truth.

The CapabilityRouter remains the final decision maker. Packs are identified by
CAPABILITY DOMAIN (never by company); company names appear only as optional
context vocabulary. This is not a domain-pack migration (deep vertical logic)
and not a lane model (diagram placement) — intake hints only.

Every declared fallback family is validated at import time against the router's
``GENERIC_FALLBACK_FAMILIES`` allowlist so a pack can never become a silent
drift engine toward a nonexistent family.
"""

from dataclasses import dataclass, field
import re

# Safe top-level import: the router imports THIS module lazily inside route(),
# so capability_router is always fully initialized before this line runs.
from app.services.capability_router import GENERIC_FALLBACK_FAMILIES


@dataclass(frozen=True)
class AcceleratorMatch:
    pack: "CapabilityAcceleratorPack"
    score: float
    matched_signals: tuple[str, ...]
    explanation: str


@dataclass(frozen=True)
class CapabilityAcceleratorPack:
    pack_id: str
    display_name: str
    description: str
    # (word-boundary regex, weight). Weak/generic terms carry low weights so a
    # single word can never reach the threshold on its own.
    positive_signals: tuple[tuple[str, float], ...]
    # Phrases that CANCEL a specific positive match (false-positive guards).
    negative_guards: tuple[str, ...] = ()
    # Optional company/ecosystem context words — small weight contribution only,
    # never a pack identity ("Cisco-like", "ADP-like" context).
    context_vocabulary: tuple[str, ...] = ()
    minimum_score: float = 1.5
    minimum_distinct_signals: int = 2
    # Must be a subset of capability_router.GENERIC_FALLBACK_FAMILIES.
    candidate_fallback_families: tuple[str, ...] = ()
    next_best_questions: tuple[str, ...] = ()
    missing_fact_prompts: tuple[str, ...] = ()
    governance_concerns: tuple[str, ...] = ()
    sensitivity_concerns: tuple[str, ...] = ()
    pricing_question_hints: tuple[str, ...] = ()
    dossier_notes: tuple[str, ...] = ()
    disallowed_assumptions: tuple[str, ...] = ()

    def match(self, raw_use_case: str) -> AcceleratorMatch | None:
        text = (raw_use_case or "").lower()
        if not text:
            return None
        guarded = any(guard in text for guard in self.negative_guards)
        matched: list[tuple[str, float]] = []
        for pattern, weight in self.positive_signals:
            if re.search(pattern, text):
                if guarded and weight < 1.0:
                    # Guards cancel weak/ambiguous matches ("router", "switches",
                    # "security") but cannot suppress strong domain-specific
                    # signals like "netflow" or "payroll cycle".
                    continue
                matched.append((pattern, weight))
        score = sum(weight for _, weight in matched)
        context_hits = tuple(sorted(term for term in self.context_vocabulary if term in text))
        score += 0.3 * len(context_hits)
        distinct = len(matched)
        if distinct < self.minimum_distinct_signals or score < self.minimum_score:
            return None
        signals = tuple(sorted(pattern for pattern, _ in matched)) + tuple(f"context:{t}" for t in context_hits)
        return AcceleratorMatch(
            pack=self,
            score=round(score, 2),
            matched_signals=signals,
            explanation=(
                f"{distinct} distinct signal(s) scored {round(score, 2)} "
                f"(threshold {self.minimum_score}, min distinct {self.minimum_distinct_signals})."
            ),
        )


NETWORK_SECURITY_OBSERVABILITY_PACK = CapabilityAcceleratorPack(
    pack_id="network_security_observability",
    display_name="Network / security / observability accelerator",
    description=(
        "Intake accelerator for network telemetry, security operations, observability, "
        "and collaboration/contact-center analytics use cases (Cisco-like ecosystems)."
    ),
    positive_signals=(
        (r"\bnetwork telemetry\b", 1.2),
        (r"\bnetflow\b", 1.2),
        (r"\bsyslog\b", 0.8),
        (r"\bsnmp\b", 1.0),
        (r"\bswitches\b", 0.8),
        (r"\brouters?\b", 0.8),
        (r"\bwireless lan\b|\bwlan\b", 1.0),
        (r"\bsd[- ]wan\b", 1.2),
        (r"\bfirewalls?\b", 0.8),
        (r"\bvpn\b", 0.6),
        (r"\bzero trust\b", 0.8),
        (r"\bnetwork assurance\b", 1.2),
        (r"\bpacket loss\b", 1.0),
        (r"\bnoc\b", 1.0),
        (r"\bsoc\b", 0.6),
        (r"\bsiem\b", 1.0),
        (r"\bsoar\b", 0.8),
        (r"\bobservability\b", 0.6),
        (r"\bcollaboration analytics\b", 1.2),
        (r"\bcontact[- ]center\b", 1.0),
        (r"\bdevice configurations?\b", 0.8),
        (r"\b(campus|branch|data center) network\b", 1.0),
        (r"\bnetwork (operations|monitoring|analytics)\b", 1.0),
        (r"\blatency\b", 0.3),
        (r"\bsecurity\b", 0.2),
    ),
    negative_guards=(
        "switching payment",
        "switch payment",
        "react router",
        "web router",
        "app router",
        "vue router",
        "career switch",
    ),
    context_vocabulary=("cisco", "meraki", "juniper", "arista"),
    candidate_fallback_families=(
        "streaming_ingestion_analytics",
        "observability_monitoring",
        "event_driven_workflow",
        "ml_inference_workflow",
        "agentic_workflow_with_human_approval",
    ),
    next_best_questions=(
        "Which telemetry sources are authoritative: NetFlow, syslog, SNMP, endpoint/security events, traces?",
        "How many devices, sites, users, and events per second should be modeled, and what retention is required?",
        "Is this read-only analytics, recommendation-only, or allowed to trigger remediation/configuration changes?",
        "Which NOC/SOC/SIEM/SOAR/ITSM or collaboration systems must integrate?",
    ),
    missing_fact_prompts=(
        "Device and site counts, events/sec, and retention window are needed before sizing.",
        "Confirm whether network configuration writeback is in scope or analytics is read-only.",
    ),
    governance_concerns=(
        "Network configuration changes, firewall-rule updates, remediation actions, and device-controller writes must be approval-gated or policy-approved; read-only analytics can remain non-effectful.",
    ),
    sensitivity_concerns=(
        "Network/security logs can embed user identifiers and security posture details; apply log-retention and access boundaries.",
    ),
    pricing_question_hints=(
        "Events per second, device count, retention period, and query latency drive cost for telemetry analytics.",
    ),
    dossier_notes=(
        "Network/security/observability accelerator applied (advisory): question quality and fallback hints only.",
    ),
    disallowed_assumptions=(
        "Do not assume configuration writeback is permitted.",
        "Do not assume a specific vendor stack; company names are context, not requirements.",
    ),
)


HCM_PAYROLL_WORKFORCE_PACK = CapabilityAcceleratorPack(
    pack_id="hcm_payroll_workforce",
    display_name="HCM / payroll / workforce accelerator",
    description=(
        "Intake accelerator for HCM, payroll, time-and-attendance, and workforce "
        "management use cases (ADP-like ecosystems)."
    ),
    positive_signals=(
        (r"\bpayrolls?\b", 1.2),
        (r"\bhcm\b", 1.2),
        (r"\bhris\b", 1.2),
        (r"\bworkforce management\b", 1.2),
        (r"\btime and attendance\b", 1.2),
        (r"\btimecards?\b", 1.0),
        (r"\babsence\b", 0.6),
        (r"\bemployee records?\b", 1.0),
        (r"\bemployee self[- ]service\b", 1.0),
        (r"\bbenefits enrollment\b", 1.0),
        (r"\bpay statements?\b", 1.2),
        (r"\bpayslips?\b", 1.2),
        (r"\bpayroll (tax|cycle|frequency)\b", 1.2),
        (r"\bpay groups?\b", 1.2),
        (r"\bmanager approvals?\b", 0.6),
        (r"\bleave management\b", 1.0),
        (r"\bhr documents?\b", 0.8),
        (r"\bscheduling\b", 0.3),
        (r"\bbenefits\b", 0.4),
        (r"\bcompliance\b", 0.2),
    ),
    negative_guards=(),
    context_vocabulary=("adp", "workday", "successfactors", "ukg"),
    candidate_fallback_families=(
        "event_driven_workflow",
        "document_rag_assistant",
        "batch_data_analytics",
        "agentic_workflow_with_human_approval",
        "secure_file_processing",
        "web_api_application",
    ),
    next_best_questions=(
        "Which systems are authoritative: payroll, HRIS, time and attendance, scheduling, benefits, document repository?",
        "Is the workflow read-only analytics, recommendation-only, manager approval, or payroll/HCM writeback — and which approvals are mandatory before any payroll-impacting update?",
        "What employee population, countries, pay groups, and payroll frequency should be modeled?",
        "What data sensitivity applies: PII, payroll, tax, benefits, leave/absence, union/labor rules?",
    ),
    missing_fact_prompts=(
        "Employee population, pay groups, and payroll cycle are needed before sizing.",
        "Confirm whether payroll/timecard/employee-record writeback is in scope or analytics is read-only.",
    ),
    governance_concerns=(
        "Payroll, timecard, employee-record, benefits, or schedule writeback must be approval-gated and fully audited; no automated payroll-impacting write by default.",
    ),
    sensitivity_concerns=(
        "Payroll/HCM data is high-sensitivity employee PII (pay, tax, benefits, leave); apply strict access, retention, and audit boundaries.",
    ),
    pricing_question_hints=(
        "Employee count, payroll frequency, timecard event volume, and document volume drive cost for HCM workloads.",
    ),
    dossier_notes=(
        "HCM/payroll/workforce accelerator applied (advisory): question quality, sensitivity framing, and fallback hints only.",
    ),
    disallowed_assumptions=(
        "Do not assume payroll writeback is permitted without explicit approval workflows.",
        "Do not assume a specific HCM vendor; company names are context, not requirements.",
    ),
)


CAPABILITY_ACCELERATOR_PACKS: tuple[CapabilityAcceleratorPack, ...] = (
    NETWORK_SECURITY_OBSERVABILITY_PACK,
    HCM_PAYROLL_WORKFORCE_PACK,
)


def _validate_packs() -> None:
    for pack in CAPABILITY_ACCELERATOR_PACKS:
        unknown = [f for f in pack.candidate_fallback_families if f not in GENERIC_FALLBACK_FAMILIES]
        if unknown:
            raise ValueError(
                f"Accelerator pack '{pack.pack_id}' declares fallback families not in "
                f"GENERIC_FALLBACK_FAMILIES: {unknown}. Packs must never route toward "
                f"nonexistent families."
            )


_validate_packs()


def match_accelerator_packs(raw_use_case: str) -> list[AcceleratorMatch]:
    """Deterministic, ordered pack matching (registry order, then score)."""
    matches = [m for pack in CAPABILITY_ACCELERATOR_PACKS if (m := pack.match(raw_use_case))]
    return sorted(matches, key=lambda m: (-m.score, m.pack.pack_id))
