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
        # Word-boundary matching: short context tokens ("adp", "asa") must never
        # match inside unrelated words ("adapted", "asap").
        context_hits = tuple(
            sorted(term for term in self.context_vocabulary if re.search(rf"\b{re.escape(term)}\b", text))
        )
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
        (r"\bpayroll exceptions?\b", 1.2),
        (r"\babsence management\b", 1.0),
        (r"\bbenefits admin(?:istration)?\b", 1.0),
        (r"\bleave of absence\b", 1.0),
        (r"\bworkforce compliance\b", 0.8),
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


FIREWALL_SECURITY_OPERATIONS_PACK = CapabilityAcceleratorPack(
    pack_id="firewall_security_operations",
    display_name="Firewall / security operations accelerator",
    description=(
        "Intake accelerator for firewall policy lifecycle, rule hygiene, threat/event "
        "triage, and network-security operations (Cisco Secure Firewall-like ecosystems). "
        "Distinct from network observability: anchored on policy/rule/triage signals."
    ),
    positive_signals=(
        (r"\bfirewall polic(?:y|ies)\b", 1.4),
        (r"\brule recertifications?\b", 1.4),
        (r"\brule (?:cleanup|base)\b", 1.2),
        (r"\baccess control rules?\b", 1.2),
        (r"\bnat rules?\b", 1.2),
        (r"\bids/ips\b|\bintrusion (?:detection|prevention)\b", 1.2),
        (r"\bthreat (?:triage|events?)\b", 1.2),
        (r"\bmicro[- ]?segmentation\b|\bsegmentation\b", 1.0),
        (r"\bvpn (?:anomal\w+|polic(?:y|ies))\b", 1.2),
        (r"\bsecurity policy changes?\b", 1.2),
        (r"\bfirewall (?:rules?|logs?|events?|migrations?)\b", 1.2),
        # Shared/weak terms — deliberately weaker than in the network pack so that
        # pure telemetry/observability use cases never reach this pack's threshold.
        (r"\bfirewalls?\b", 0.6),
        (r"\bsiem\b", 0.4),
        (r"\bsoar\b", 0.4),
        (r"\bsoc\b", 0.4),
        (r"\bvpn\b", 0.3),
        (r"\bsecurity\b", 0.2),
    ),
    negative_guards=("human firewall",),
    context_vocabulary=("cisco", "secure firewall", "asa", "ftd", "firepower", "palo alto", "fortinet"),
    candidate_fallback_families=(
        "observability_monitoring",
        "event_driven_workflow",
        "streaming_ingestion_analytics",
        "agentic_workflow_with_human_approval",
    ),
    next_best_questions=(
        "Which firewall platforms and event sources are authoritative, and how many firewalls, policies, rules, VPN users, and events/day should be modeled?",
        "Is the workflow read-only analytics, recommendation-only, or allowed to update firewall rules, VPN policy, or segmentation — and what approval is required first?",
        "Which SIEM/SOAR/ITSM systems integrate, and what retention/compliance requirements apply to security logs?",
    ),
    missing_fact_prompts=(
        "Firewall/policy/rule counts and event volume are needed before sizing.",
        "Confirm whether rule/policy writeback is in scope or analytics is read-only.",
    ),
    governance_concerns=(
        "Firewall policy changes, rule updates, VPN/segmentation changes, and automated remediation must be approval-gated or policy-approved.",
    ),
    sensitivity_concerns=(
        "Firewall/security events can embed user identifiers and security posture details; apply retention and access boundaries.",
    ),
    pricing_question_hints=(
        "Events per day, firewall/policy count, retention period, and triage workflow volume drive cost.",
    ),
    dossier_notes=(
        "Firewall/security-operations accelerator applied (advisory): question quality and fallback hints only.",
    ),
    disallowed_assumptions=(
        "Do not assume rule/policy writeback is permitted.",
        "Do not assume a specific firewall vendor; company names are context, not requirements.",
    ),
)


SMART_SPACES_LOCATION_IOT_PACK = CapabilityAcceleratorPack(
    pack_id="smart_spaces_location_iot",
    display_name="Smart spaces / location IoT accelerator",
    description=(
        "Intake accelerator for workspace occupancy, indoor location, building "
        "utilization, and environmental sensing (Cisco Spaces-like ecosystems)."
    ),
    positive_signals=(
        (r"\boccupancy\b", 1.0),
        (r"\bmeeting rooms?\b", 1.0),
        (r"\b(?:room|desk|space|building|workspace) utilizations?\b", 1.2),
        (r"\bdesk bookings?\b", 1.2),
        (r"\bfootfall\b", 1.2),
        (r"\bwayfinding\b", 1.4),
        (r"\bindoor (?:location|positioning)\b", 1.4),
        (r"\b(?:wi[- ]?fi|wifi) presence\b", 1.2),
        (r"\bble beacons?\b", 1.2),
        (r"\bsmart buildings?\b", 1.2),
        (r"\bworkplace analytics\b", 1.0),
        (r"\benvironmental sensors?\b", 1.0),
        (r"\bvisitor (?:experience|management)\b", 0.8),
        (r"\bhvac\b", 0.8),
    ),
    negative_guards=(),
    context_vocabulary=("cisco spaces", "meraki", "webex", "catalyst"),
    candidate_fallback_families=(
        "streaming_ingestion_analytics",
        "observability_monitoring",
        "event_driven_workflow",
        "data_lake_and_bi",
    ),
    next_best_questions=(
        "Which location sources are used: Wi-Fi, BLE, cameras, collaboration endpoints, third-party sensors — and what sites/buildings/floors/rooms should be modeled?",
        "Is data anonymized/aggregated or person-identifiable, and what retention/privacy policy applies to location and occupancy data?",
        "What update frequency is required (real-time occupancy, hourly analytics, daily reports), and what actions are allowed: recommendation, space booking, facilities ticket, safety alert?",
    ),
    missing_fact_prompts=(
        "Site/floor/room counts and sensor event volume are needed before sizing.",
        "Confirm whether data is aggregate-only or person-identifiable; privacy posture changes the architecture.",
    ),
    governance_concerns=(
        "Individual tracking, workplace surveillance, or safety actions must be explicitly governed and auditable; aggregate-by-default is the safe posture.",
    ),
    sensitivity_concerns=(
        "Person-location and occupancy data can be privacy-sensitive employee/visitor data; apply anonymization, retention, and access boundaries.",
    ),
    pricing_question_hints=(
        "Sensor/event volume, site count, update frequency, and retention drive cost for spaces analytics.",
    ),
    dossier_notes=(
        "Smart-spaces/location accelerator applied (advisory): question quality and fallback hints only.",
    ),
    disallowed_assumptions=(
        "Do not assume individual-level tracking is permitted; aggregate-by-default.",
        "Do not assume a specific sensing vendor; company names are context, not requirements.",
    ),
)


BANKING_OPEN_BANKING_PAYMENTS_PACK = CapabilityAcceleratorPack(
    pack_id="banking_open_banking_payments",
    display_name="Banking / open banking / payments accelerator",
    description=(
        "Intake accelerator for open-banking APIs, consent workflows, account "
        "information, and payment initiation (Barclays/NatWest-like ecosystems)."
    ),
    positive_signals=(
        (r"\bopen banking\b", 1.4),
        (r"\bpayment initiations?\b", 1.4),
        (r"\bfaster payments\b", 1.4),
        (r"\bbacs\b", 1.4),
        (r"\bchaps\b", 1.4),
        (r"\bpsd2\b", 1.4),
        (r"\biso 20022\b", 1.4),
        (r"\baccount information services?\b", 1.2),
        (r"\bconsent (?:workflows?|management|flows?)\b", 1.2),
        (r"\bbank[- ]to[- ]bank payments?\b", 1.2),
        (r"\bcore banking\b", 1.2),
        (r"\bbanking apis?\b", 1.2),
        (r"\btransaction enrichments?\b", 1.2),
        (r"\baccount aggregations?\b", 1.2),
        (r"\bpartner onboarding\b", 0.8),
        (r"\bswift\b", 0.6),
    ),
    negative_guards=("swiftui", "swift ui", "swift app", "memory bank", "blood bank", "river bank", "bank holiday"),
    context_vocabulary=("barclays", "natwest", "hsbc", "lloyds", "monzo", "starling"),
    candidate_fallback_families=(
        "event_driven_workflow",
        "web_api_application",
        "agentic_workflow_with_human_approval",
        "streaming_ingestion_analytics",
    ),
    next_best_questions=(
        "Which banking API flows are in scope: account information, payment initiation, balances, transaction history, consent, partner onboarding?",
        "Is the system read-only, payment-initiation, or allowed to trigger account/payment actions — and which approvals/consent models apply before any payment-impacting action?",
        "What transaction and API request volume should be modeled, and which downstream systems integrate: core banking, fraud, AML, CRM, API gateway?",
        "What audit, retention, PSD2/Open Banking, and customer-consent requirements apply?",
    ),
    missing_fact_prompts=(
        "Transaction/API volumes and the consent model are needed before sizing.",
        "Confirm whether payment initiation or account writeback is in scope or flows are read-only.",
    ),
    governance_concerns=(
        "Payment initiation, account updates, customer-consent changes, and partner access changes must be approval-gated or policy-controlled; read-only account-information flows still require consent and audit.",
    ),
    sensitivity_concerns=(
        "Banking data is high-sensitivity customer financial data (accounts, payments, transactions); apply strict consent, access, retention, and audit boundaries.",
    ),
    pricing_question_hints=(
        "API request volume, transaction volume, consent events, and retention drive cost for open-banking workloads.",
    ),
    dossier_notes=(
        "Banking/open-banking accelerator applied (advisory): question quality and fallback hints only.",
    ),
    disallowed_assumptions=(
        "Do not assume payment execution is permitted without explicit approval/consent workflows.",
        "Do not assume a specific bank or vendor stack; company names are context, not requirements.",
    ),
)


FINANCIAL_CRIME_RISK_OPERATIONS_PACK = CapabilityAcceleratorPack(
    pack_id="financial_crime_risk_operations",
    display_name="Financial crime / risk operations accelerator",
    description=(
        "Intake accelerator for AML alert triage, transaction monitoring, sanctions "
        "screening, KYC, and investigator/case workflows (large-bank risk operations)."
    ),
    positive_signals=(
        (r"\banti[- ]money laundering\b", 1.4),
        (r"\bfinancial crime\b", 1.4),
        (r"\btransaction monitoring\b", 1.4),
        (r"\bsanctions screening\b", 1.4),
        (r"\bknow your customer\b", 1.4),
        (r"\baml\b", 1.2),
        (r"\bkyc\b", 1.2),
        (r"\balert triage\b", 1.2),
        (r"\bsuspicious activity\b", 1.2),
        (r"\bfraud operations\b", 1.2),
        (r"\bpolitically exposed persons?\b", 1.2),
        (r"\binvestigator workflows?\b", 1.0),
        (r"\bwatchlists?\b", 1.0),
        # 0.9 so the search-and-rescue guard can cancel it (guards cancel < 1.0).
        (r"\bsar/str\b|\b(?:sar|str) filings?\b", 0.9),
        (r"\bcase management\b", 0.8),
        (r"\brisk scoring\b", 0.8),
    ),
    negative_guards=("search and rescue",),
    context_vocabulary=("barclays", "natwest", "fca", "fincen", "fatf"),
    candidate_fallback_families=(
        "event_driven_workflow",
        "streaming_ingestion_analytics",
        "ml_inference_workflow",
        "agentic_workflow_with_human_approval",
    ),
    next_best_questions=(
        "Which records/events are processed: transactions, parties, accounts, alerts, cases, sanctions lists — and at what daily volume, latency, and investigation SLA?",
        "Is the output a recommendation, case creation, block/hold action, or regulatory filing — and what human approval is required before customer-impacting actions?",
        "Which systems integrate: case management, core banking, fraud platform, AML engine, data lake — and what explainability/audit requirements apply?",
    ),
    missing_fact_prompts=(
        "Alert/transaction volumes and investigation SLAs are needed before sizing.",
        "Confirm whether customer-impacting actions (blocks/holds/filings) are in scope or output is recommendation-only.",
    ),
    governance_concerns=(
        "Customer-impacting blocks, holds, SAR/STR filing recommendations, account restrictions, or case-state updates must be governed, auditable, and usually human-approved.",
    ),
    sensitivity_concerns=(
        "Financial-crime data involves customer identities, transactions, and case files; apply strict access, explainability, retention, and audit boundaries.",
    ),
    pricing_question_hints=(
        "Daily alert/transaction volume, screening list sizes, case throughput, and retention drive cost.",
    ),
    dossier_notes=(
        "Financial-crime/risk-operations accelerator applied (advisory): question quality and fallback hints only.",
    ),
    disallowed_assumptions=(
        "Do not assume automated customer-impacting actions are permitted; human approval is the default.",
        "Do not assume a specific bank or screening vendor; company names are context, not requirements.",
    ),
)


CAPABILITY_ACCELERATOR_PACKS: tuple[CapabilityAcceleratorPack, ...] = (
    NETWORK_SECURITY_OBSERVABILITY_PACK,
    HCM_PAYROLL_WORKFORCE_PACK,
    FIREWALL_SECURITY_OPERATIONS_PACK,
    SMART_SPACES_LOCATION_IOT_PACK,
    BANKING_OPEN_BANKING_PAYMENTS_PACK,
    FINANCIAL_CRIME_RISK_OPERATIONS_PACK,
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
