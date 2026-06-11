"""Deterministic Reviewer Mode + Unified Uncertainty Map (export trust artifacts).

Reviewer Mode pressure-tests Archway's OWN deterministic output before export:
it consolidates signals the pipeline already computed — pricing readiness and
evidence classes, research quality and citation coverage, ADR confidence and
missing facts, typed governance metadata, diagram QA, capability routing — into
findings a human reviewer should challenge first.

Rules of the house (DECISIONS D7/D15/D19 lineage):
- NO LLM/model output. Every finding cites a deterministic evidence source.
- NO invented recommendations: findings explain WHY a state holds and what to
  CONFIRM — never "use service X instead" claims the pipeline did not compute.
- Confidence is RULE-DERIVED; reviewer mode never alters pricing totals,
  readiness flags, architecture specs, or governance enforcement.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["blocker", "warning", "advisory", "info"]
Category = Literal[
    "use_case_understanding",
    "research_evidence",
    "pricing",
    "architecture_decision",
    "governance",
    "diagram",
    "export_integrity",
    "assumption",
    "over_patterning",
    "scenario_simulation",
]
ReviewStatus = Literal["ready", "ready_with_warnings", "directional_only", "needs_review", "blocked"]
SectionConfidence = Literal["high", "medium", "low", "directional", "limited", "warning"]


class ReviewerFinding(BaseModel):
    finding_id: str
    severity: Severity
    category: Category
    title: str
    explanation: str
    evidence_source: str
    related_adrs: list[str] = Field(default_factory=list)
    related_components: list[str] = Field(default_factory=list)
    related_flows: list[str] = Field(default_factory=list)
    related_pricing_drivers: list[str] = Field(default_factory=list)
    related_artifacts: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    blocks_customer_ready: bool = False
    blocks_procurement_ready: bool = False
    generated_by: Literal["deterministic_rule"] = "deterministic_rule"


class ReviewerReport(BaseModel):
    overall_review_status: ReviewStatus
    summary: dict[str, Any] = Field(default_factory=dict)
    findings: list[ReviewerFinding] = Field(default_factory=list)
    top_questions_to_resolve: list[str] = Field(default_factory=list)
    top_assumptions_to_confirm: list[str] = Field(default_factory=list)
    uncertainty_map: dict[str, Any] = Field(default_factory=dict)
    over_patterning_score: float | None = None
    generated_by: Literal["deterministic_rule"] = "deterministic_rule"


def _pricing_signals(pricing: dict | None) -> dict[str, Any]:
    metadata = (pricing or {}).get("metadata") or {}
    ledger_summary = (metadata.get("pricing_ledger") or {}).get("summary") or {}
    closure = metadata.get("pricing_driver_closure") or {}
    pilot = metadata.get("sku_pricing_pilot") or {}
    lines = (metadata.get("pricing_ledger") or {}).get("lines") or []
    evidence_counts: dict[str, int] = {}
    for line in lines:
        if isinstance(line, dict) and line.get("evidence_class"):
            key = str(line["evidence_class"])
            evidence_counts[key] = evidence_counts.get(key, 0) + 1
    return {
        "headline_flag": metadata.get("pricing_can_be_displayed_as_headline", False) is True,
        "headline_safe": bool(ledger_summary.get("headline_safe", False)),
        "procurement_ready": bool(ledger_summary.get("procurement_ready", False)),
        "pricing_maturity": str(closure.get("pricing_maturity") or closure.get("status") or "unknown"),
        "closure_status": str(closure.get("status") or "unknown"),
        "missing_drivers": [str(d) for d in (closure.get("missing_drivers") or [])],
        "unknown_variables": [str(u) for u in ((pricing or {}).get("unknown_variables") or [])],
        "evidence_counts": evidence_counts,
        "pilot": pilot,
        "pilot_present": bool(pilot),
        "pilot_not_estimated": [str(x) for x in (pilot.get("not_estimated") or [])],
    }


def _capability_decision(brief: dict | None) -> dict[str, Any]:
    return ((brief or {}).get("use_case_profile") or {}).get("capability_decision") or {}


def _diagram_signals(diagrams: Any) -> dict[str, Any]:
    galleries = diagrams if isinstance(diagrams, list) else ([diagrams] if isinstance(diagrams, dict) else [])
    missing: list[str] = []
    diagnostics: list[str] = []
    for gallery in galleries:
        if not isinstance(gallery, dict):
            continue
        missing.extend(str(m) for m in (gallery.get("missing_requested_views") or []))
        for qa in gallery.get("qa_reports") or []:
            for item in (qa.get("diagnostics") or []) if isinstance(qa, dict) else []:
                if isinstance(item, dict) and item.get("severity") in {"warning", "error"}:
                    diagnostics.append(str(item.get("code") or item.get("message") or "diagnostic"))
    return {"missing_views": sorted(set(missing)), "diagnostics": sorted(set(diagnostics))}


# --------------------------------------------------------------------------- #
# Finding emitters (deterministic rules only)
# --------------------------------------------------------------------------- #
def _pricing_findings(signals: dict[str, Any]) -> list[ReviewerFinding]:
    findings: list[ReviewerFinding] = []
    if not signals["headline_flag"] or not signals["headline_safe"]:
        findings.append(ReviewerFinding(
            finding_id="rev_pricing_headline_not_safe",
            severity="warning",
            category="pricing",
            title="Pricing headline is not marked safe",
            explanation=(
                f"pricing_can_be_displayed_as_headline={signals['headline_flag']}, "
                f"ledger headline_safe={signals['headline_safe']} — totals are directional, not customer-headline pricing."
            ),
            evidence_source="pricing.metadata + pricing_ledger.summary",
            recommended_action="Treat totals as directional; confirm drivers before presenting a headline figure.",
            blocks_customer_ready=True,
        ))
    if not signals["procurement_ready"]:
        findings.append(ReviewerFinding(
            finding_id="rev_pricing_not_procurement_ready",
            severity="advisory",
            category="pricing",
            title="Pricing is not procurement-ready",
            explanation=f"ledger procurement_ready=False; pricing maturity is '{signals['pricing_maturity']}'.",
            evidence_source="pricing_ledger.summary + pricing_driver_closure",
            recommended_action="Procurement-grade pricing requires confirmed drivers and SKU/rate binding (DECISIONS D3).",
            blocks_procurement_ready=True,
        ))
    missing = signals["missing_drivers"] + signals["unknown_variables"]
    if missing:
        findings.append(ReviewerFinding(
            finding_id="rev_pricing_missing_drivers",
            severity="warning",
            category="pricing",
            title="Pricing drivers are missing or assumed",
            explanation=f"Missing/assumed drivers: {', '.join(sorted(set(missing)))}.",
            evidence_source="pricing_driver_closure + unknown_variables",
            related_pricing_drivers=sorted(set(missing)),
            recommended_action="Confirm these drivers with the customer; totals scale directly with them.",
        ))
    heuristic_lines = signals["evidence_counts"].get("heuristic", 0)
    not_estimated_lines = signals["evidence_counts"].get("not_estimated", 0)
    if heuristic_lines or not_estimated_lines:
        findings.append(ReviewerFinding(
            finding_id="rev_pricing_evidence_classes",
            severity="warning" if not_estimated_lines else "advisory",
            category="pricing",
            title="Pricing lines include heuristic / not-estimated evidence",
            explanation=f"Ledger evidence classes: {signals['evidence_counts']}.",
            evidence_source="pricing_ledger.lines[].evidence_class",
            recommended_action="Lines without SKU/tier backing carry the widest error bars; prioritize confirming their drivers.",
        ))
    pilot = signals["pilot"]
    if signals["pilot_present"]:
        if pilot.get("rate_authoritative") and not pilot.get("quantities_confirmed"):
            findings.append(ReviewerFinding(
                finding_id="rev_sku_rates_real_quantities_assumed",
                severity="warning",
                category="pricing",
                title="SKU pilot rates are authoritative but quantities are assumed",
                explanation=(
                    "rate_authoritative=True with quantities_confirmed=False: the rates are real "
                    "AWS Price List rates, but the volumes behind the subtotal are assumptions."
                ),
                evidence_source="pricing.metadata.sku_pricing_pilot",
                recommended_action="Confirm quantities with the customer; assumed quantities can never reach procurement-ready (D11).",
                blocks_procurement_ready=True,
            ))
        if signals["pilot_not_estimated"]:
            findings.append(ReviewerFinding(
                finding_id="rev_sku_not_estimated_lines",
                severity="warning",
                category="pricing",
                title="SKU pilot has not-estimated dimensions",
                explanation=f"Not estimated: {', '.join(signals['pilot_not_estimated'])}.",
                evidence_source="sku_pricing_pilot.not_estimated",
                recommended_action="These dimensions fail closed (e.g. EventBridge bills 64KB chunks); model them before relying on the subtotal.",
            ))
    return findings


def _research_findings(report: dict | None) -> list[ReviewerFinding]:
    findings: list[ReviewerFinding] = []
    metadata = (report or {}).get("metadata") or {}
    quality = metadata.get("research_quality") or {}
    label = str(quality.get("label") or "")
    coverage = (report or {}).get("citation_coverage") or {}
    coverage_passed = bool(coverage.get("passed", False)) if isinstance(coverage, dict) else False
    if label in {"Limited", "Official Fallback"} or not label:
        findings.append(ReviewerFinding(
            finding_id="rev_research_quality_limited",
            severity="warning",
            category="research_evidence",
            title=f"Research evidence quality: {label or 'unknown'}",
            explanation=str(quality.get("reason") or "MCP/web evidence sources were unavailable or incomplete."),
            evidence_source="report.metadata.research_quality",
            recommended_action="Enable AWS Docs/Pricing MCP evidence sources for validated research.",
            blocks_customer_ready=False,
        ))
    if not coverage_passed:
        findings.append(ReviewerFinding(
            finding_id="rev_citation_coverage_failed",
            severity="warning",
            category="research_evidence",
            title="Citation coverage did not pass",
            explanation="One or more claims lack citations; the report fails the citation gate.",
            evidence_source="report.citation_coverage",
            recommended_action="Treat uncited claims as assumptions until evidence is attached.",
        ))
    evidence_count = len((report or {}).get("evidence_items") or [])
    if evidence_count < 3:
        findings.append(ReviewerFinding(
            finding_id="rev_low_evidence_count",
            severity="advisory",
            category="research_evidence",
            title=f"Low evidence count ({evidence_count})",
            explanation=f"Only {evidence_count} evidence item(s) back the research report.",
            evidence_source="report.evidence_items",
            recommended_action="Add evidence sources before customer-facing claims.",
        ))
    return findings


def _adr_findings(decision_records: list[dict] | None) -> list[ReviewerFinding]:
    findings: list[ReviewerFinding] = []
    for record in decision_records or []:
        if not isinstance(record, dict):
            continue
        adr_id = str(record.get("decision_id") or "adr")
        if record.get("confidence") in {"low", "directional"} or record.get("missing_facts"):
            findings.append(ReviewerFinding(
                finding_id=f"rev_adr_{adr_id}",
                severity="warning" if record.get("missing_facts") else "advisory",
                category="architecture_decision",
                title=f"Decision needs confirmation: {record.get('title', adr_id)}",
                explanation=(
                    f"confidence={record.get('confidence')}, evidence_class={record.get('evidence_class')}, "
                    f"missing_facts={record.get('missing_facts') or []}."
                ),
                evidence_source=f"architecture/decision_records.json#{adr_id}",
                related_adrs=[adr_id],
                related_components=[str(c) for c in (record.get("related_components") or [])],
                recommended_action="; ".join(record.get("reviewer_questions") or []) or "Confirm the decision inputs with the customer.",
            ))
        elif record.get("evidence_class") in {"missing_evidence", "assumption_backed"}:
            findings.append(ReviewerFinding(
                finding_id=f"rev_adr_{adr_id}",
                severity="advisory",
                category="architecture_decision",
                title=f"Decision is {record.get('evidence_class')}: {record.get('title', adr_id)}",
                explanation=f"evidence_class={record.get('evidence_class')} — no research/pricing backing recorded.",
                evidence_source=f"architecture/decision_records.json#{adr_id}",
                related_adrs=[adr_id],
                recommended_action="Attach evidence or confirm the assumption.",
            ))
    return findings


def _governance_findings(architectures: list | None) -> list[ReviewerFinding]:
    findings: list[ReviewerFinding] = []
    spec = next((s for s in (architectures or []) if isinstance(s, dict) and s.get("mode") == "production"),
                next((s for s in (architectures or []) if isinstance(s, dict)), {}))
    governed_flows = [
        str(f.get("id")) for f in (spec.get("flows") or [])
        if isinstance(f, dict) and ((f.get("metadata") or {}).get("approval_required") or (f.get("metadata") or {}).get("external_write"))
    ]
    controls = [c for c in (spec.get("governance_controls") or []) if isinstance(c, dict)]
    if governed_flows:
        findings.append(ReviewerFinding(
            finding_id="rev_governance_effectful_flows",
            severity="warning" if not controls else "advisory",
            category="governance",
            title=f"{len(governed_flows)} effectful/approval-gated flow(s) present",
            explanation=(
                f"Flows {governed_flows} perform external writes or require approval. "
                + (f"{len(controls)} typed governance control(s) are attached." if controls
                   else "No typed governance controls are attached to the spec — verify enforcement before any writeback.")
            ),
            evidence_source="architecture spec flows[].metadata + governance_controls",
            related_flows=governed_flows,
            recommended_action="Verify approval workflow, audit trail, and rollback behavior for every effectful flow before production.",
        ))
    return findings


def _diagram_findings(diagram_signals: dict[str, Any]) -> list[ReviewerFinding]:
    findings: list[ReviewerFinding] = []
    if diagram_signals["missing_views"] or diagram_signals["diagnostics"]:
        findings.append(ReviewerFinding(
            finding_id="rev_diagram_degraded",
            severity="warning",
            category="diagram",
            title="Diagram QA reported degraded/omitted views or diagnostics",
            explanation=(
                f"missing_views={diagram_signals['missing_views']}; diagnostics={diagram_signals['diagnostics']}."
            ),
            evidence_source="diagram gallery qa_reports + missing_requested_views",
            recommended_action="Review diagram diagnostics before customer presentation.",
        ))
    return findings


def _capability_findings(capability: dict[str, Any]) -> list[ReviewerFinding]:
    findings: list[ReviewerFinding] = []
    status = str(capability.get("status") or "")
    if status in {"directional", "discovery_needed"}:
        findings.append(ReviewerFinding(
            finding_id="rev_capability_directional",
            severity="advisory",
            category="use_case_understanding",
            title=f"Capability routing is '{status}'",
            explanation=str(capability.get("reason") or "Deterministic classification is not high-confidence deep support."),
            evidence_source="use_case_profile.capability_decision",
            recommended_action="; ".join(capability.get("next_best_questions") or [])[:400]
            or "Answer the discovery questions before locking the pattern.",
        ))
    elif status == "unsupported_or_blocked":
        findings.append(ReviewerFinding(
            finding_id="rev_capability_blocked",
            severity="blocker",
            category="use_case_understanding",
            title="Use case is unsupported or blocked",
            explanation=str(capability.get("reason") or "The capability router blocked this use case."),
            evidence_source="use_case_profile.capability_decision",
            recommended_action="Do not generate customer-facing artifacts for this use case.",
            blocks_customer_ready=True,
            blocks_procurement_ready=True,
        ))
    if capability.get("fallback_family_source") == "model_prior_unverified":
        findings.append(ReviewerFinding(
            finding_id="rev_capability_model_prior_fallback",
            severity="advisory",
            category="use_case_understanding",
            title="Fallback family came from the (unverified) model prior",
            explanation="The generic fallback family was suggested by the advisory model prior, not deterministic classification.",
            evidence_source="capability_decision.fallback_family_source",
            recommended_action="Confirm the workload shape with the customer.",
        ))
    return findings


def _over_patterning(decision_records: list[dict] | None, capability: dict[str, Any],
                     pricing_signals: dict[str, Any], brief: dict | None) -> tuple[float | None, ReviewerFinding | None]:
    records = [r for r in (decision_records or []) if isinstance(r, dict)]
    component_records = [r for r in records if str(r.get("decision_id", "")).startswith("adr_component_")]
    if not component_records and not records:
        return None, None
    catalog_only = sum(1 for r in component_records if r.get("evidence_class") in {"catalog_backed", "assumption_backed"})
    catalog_ratio = (catalog_only / len(component_records)) if component_records else 0.0
    status = str(capability.get("status") or "")
    directional_component = 1.0 if status in {"directional", "discovery_needed"} or capability.get("generic_fallback_family") == "unknown_directional" else 0.0
    missing_count = len(pricing_signals["missing_drivers"]) + len(pricing_signals["unknown_variables"])
    missing_component = min(missing_count, 4) / 4
    assumptions = len((brief or {}).get("assumptions") or [])
    assumption_component = min(assumptions, 6) / 6
    score = round(0.4 * catalog_ratio + 0.25 * directional_component + 0.2 * missing_component + 0.15 * assumption_component, 2)
    finding = None
    if score >= 0.5:
        finding = ReviewerFinding(
            finding_id="rev_over_patterning",
            severity="warning" if score >= 0.75 else "advisory",
            category="over_patterning",
            title=f"Architecture is heavily pattern-backed (score {score})",
            explanation=(
                f"catalog/assumption-backed component decisions: {catalog_only}/{len(component_records)}; "
                f"capability status '{status or 'n/a'}'; {missing_count} missing/assumed pricing driver(s); "
                f"{assumptions} brief assumption(s). User-confirmed workload facts are thin."
            ),
            evidence_source="ADR evidence_class distribution + capability_decision + pricing_driver_closure + brief.assumptions",
            recommended_action="Confirm scale, region, integrations, and writeback behavior before customer presentation.",
        )
    return score, finding


# --------------------------------------------------------------------------- #
# Unified uncertainty map
# --------------------------------------------------------------------------- #
def build_uncertainty_map(
    brief: dict | None,
    report: dict | None,
    pricing: dict | None,
    architectures: list | None,
    diagrams: Any,
    decision_records: list[dict] | None,
    *,
    manifest_present: bool = True,
    over_patterning_score: float | None = None,
) -> dict[str, Any]:
    signals = _pricing_signals(pricing)
    capability = _capability_decision(brief)
    diagram_signals = _diagram_signals(diagrams)
    records = [r for r in (decision_records or []) if isinstance(r, dict)]
    adr_confidence_counts: dict[str, int] = {}
    for record in records:
        key = str(record.get("confidence") or "unknown")
        adr_confidence_counts[key] = adr_confidence_counts.get(key, 0) + 1

    quality = ((report or {}).get("metadata") or {}).get("research_quality") or {}
    coverage = (report or {}).get("citation_coverage") or {}
    coverage_passed = bool(coverage.get("passed", False)) if isinstance(coverage, dict) else False

    pricing_directional = (
        not signals["headline_safe"] or not signals["procurement_ready"]
        or bool(signals["missing_drivers"]) or bool(signals["unknown_variables"])
        or bool(signals["pilot_not_estimated"])
        or (signals["pilot_present"] and not signals["pilot"].get("quantities_confirmed"))
    )
    research_limited = (not coverage_passed) or str(quality.get("label") or "") in {"Limited", "Official Fallback", ""}
    architecture_conf: SectionConfidence = "medium"
    directional_adrs = adr_confidence_counts.get("directional", 0) + adr_confidence_counts.get("low", 0)
    if str(capability.get("status")) in {"directional", "discovery_needed"} or (over_patterning_score or 0) >= 0.75:
        architecture_conf = "low"
    elif directional_adrs == 0 and str(capability.get("status")) == "supported":
        architecture_conf = "high"
    governed_flows_exist = any(
        (f.get("metadata") or {}).get("approval_required")
        for s in (architectures or []) if isinstance(s, dict)
        for f in (s.get("flows") or []) if isinstance(f, dict)
    )

    by_section: dict[str, str] = {
        "use_case_understanding": "high" if str(capability.get("status")) == "supported" else "medium",
        "research_evidence": "limited" if research_limited else "high",
        "architecture": architecture_conf,
        "pricing": "directional" if pricing_directional else "high",
        "governance": "warning" if governed_flows_exist else "high",
        "diagrams": "warning" if (diagram_signals["missing_views"] or diagram_signals["diagnostics"]) else "high",
        "export_integrity": "high" if manifest_present else "low",
    }
    ranking = {"high": 3, "medium": 2, "warning": 2, "limited": 1, "low": 1, "directional": 1}
    worst = min(by_section.values(), key=lambda v: ranking[v])
    overall = {3: "high", 2: "medium", 1: "directional" if by_section["pricing"] == "directional" else "low"}[ranking[worst]]

    top_uncertainties: list[dict[str, str]] = []
    for driver in sorted(set(signals["missing_drivers"] + signals["unknown_variables"]))[:5]:
        top_uncertainties.append({
            "area": "pricing",
            "reason": f"driver '{driver}' is missing or assumed",
            "source": "pricing_driver_closure",
            "recommended_action": f"Confirm {driver} with the customer.",
        })
    if research_limited:
        top_uncertainties.append({
            "area": "research_evidence",
            "reason": str(quality.get("reason") or "citation coverage did not pass"),
            "source": "research_quality + citation_coverage",
            "recommended_action": "Enable MCP evidence sources for validated research.",
        })
    for record in records:
        if record.get("confidence") in {"low", "directional"} and len(top_uncertainties) < 10:
            top_uncertainties.append({
                "area": "architecture",
                "reason": f"{record.get('decision_id')}: confidence={record.get('confidence')}",
                "source": "architecture/decision_records.json",
                "recommended_action": "; ".join(record.get("reviewer_questions") or []) or "Confirm decision inputs.",
            })

    return {
        "overall_confidence": overall,
        "by_section": by_section,
        "top_uncertainties": top_uncertainties,
        "confidence_inputs": {
            "capability_decision": {"status": capability.get("status"), "fallback_family_source": capability.get("fallback_family_source")},
            "citation_coverage": {"passed": coverage_passed},
            "research_quality": {"label": quality.get("label")},
            "pricing_evidence_classes": signals["evidence_counts"],
            "pricing_flags": {
                "headline_safe": signals["headline_safe"],
                "procurement_ready": signals["procurement_ready"],
                "pricing_maturity": signals["pricing_maturity"],
            },
            "adr_confidence_counts": adr_confidence_counts,
            "diagram_qa": diagram_signals,
            "governance_controls": {"effectful_flows_present": governed_flows_exist},
            "artifact_integrity": {"manifest_present": manifest_present},
        },
        "generated_by": "deterministic_rule",
    }


# --------------------------------------------------------------------------- #
# Reviewer report assembly
# --------------------------------------------------------------------------- #
def build_reviewer_report(
    brief: dict | None,
    report: dict | None,
    pricing: dict | None,
    architectures: list | None,
    diagrams: Any,
    decision_records: list[dict] | None,
    *,
    manifest_present: bool = True,
) -> ReviewerReport:
    signals = _pricing_signals(pricing)
    capability = _capability_decision(brief)
    diagram_signals = _diagram_signals(diagrams)

    findings: list[ReviewerFinding] = []
    findings.extend(_capability_findings(capability))
    findings.extend(_research_findings(report))
    findings.extend(_pricing_findings(signals))
    findings.extend(_adr_findings(decision_records))
    findings.extend(_governance_findings(architectures))
    findings.extend(_diagram_findings(diagram_signals))
    score, over_finding = _over_patterning(decision_records, capability, signals, brief)
    if over_finding is not None:
        findings.append(over_finding)
    findings.sort(key=lambda f: f.finding_id)

    uncertainty = build_uncertainty_map(
        brief, report, pricing, architectures, diagrams, decision_records,
        manifest_present=manifest_present, over_patterning_score=score,
    )

    severities = [f.severity for f in findings]
    if "blocker" in severities:
        status: ReviewStatus = "blocked"
    elif uncertainty["by_section"]["pricing"] == "directional":
        status = "directional_only"
    elif "warning" in severities:
        status = "needs_review"
    elif "advisory" in severities:
        status = "ready_with_warnings"
    else:
        status = "ready"

    questions: list[str] = []
    for record in decision_records or []:
        for question in (record.get("reviewer_questions") or []) if isinstance(record, dict) else []:
            if question not in questions:
                questions.append(question)
    for question in capability.get("next_best_questions") or []:
        if question not in questions:
            questions.append(str(question))
    assumptions: list[str] = []
    for item in ((pricing or {}).get("metadata") or {}).get("assumption_ledger") or []:
        text = str(item.get("text") if isinstance(item, dict) else item)
        if text and text not in assumptions:
            assumptions.append(text)
    for item in (brief or {}).get("assumptions") or []:
        text = str(item.get("text") if isinstance(item, dict) else item)
        if text and text not in assumptions:
            assumptions.append(text)

    counts = {severity: severities.count(severity) for severity in ("blocker", "warning", "advisory", "info")}
    categories = sorted({f.category for f in findings if f.severity in {"blocker", "warning"}})
    return ReviewerReport(
        overall_review_status=status,
        summary={
            "finding_count": len(findings),
            **{f"{severity}_count": count for severity, count in counts.items()},
            "top_categories": categories[:5],
            "blocks_customer_ready": any(f.blocks_customer_ready for f in findings),
            "blocks_procurement_ready": any(f.blocks_procurement_ready for f in findings),
        },
        findings=findings,
        top_questions_to_resolve=questions[:5],
        top_assumptions_to_confirm=assumptions[:5],
        uncertainty_map=uncertainty,
        over_patterning_score=score,
    )


def reviewer_summary_markdown(report: ReviewerReport) -> str:
    lines = [
        "# Reviewer Summary",
        "",
        f"**Overall review status:** {report.overall_review_status}",
        f"**Findings:** {report.summary.get('finding_count', 0)} "
        f"(blockers {report.summary.get('blocker_count', 0)}, warnings {report.summary.get('warning_count', 0)}, "
        f"advisories {report.summary.get('advisory_count', 0)})",
        f"**Over-patterning score:** {report.over_patterning_score}",
        f"**Overall confidence:** {report.uncertainty_map.get('overall_confidence')}",
        "",
        "Deterministic findings over Archway's own output. No model-generated prose.",
        "",
    ]
    for finding in report.findings:
        lines.extend([
            f"## [{finding.severity}] {finding.title}",
            "",
            f"- **Category:** {finding.category} · **Evidence:** {finding.evidence_source}",
            f"- **Why:** {finding.explanation}",
            f"- **Action:** {finding.recommended_action}",
            "",
        ])
    if report.top_questions_to_resolve:
        lines.append("## Top questions to resolve")
        lines.extend(f"- {q}" for q in report.top_questions_to_resolve)
        lines.append("")
    if report.top_assumptions_to_confirm:
        lines.append("## Top assumptions to confirm")
        lines.extend(f"- {a}" for a in report.top_assumptions_to_confirm)
        lines.append("")
    return "\n".join(lines)


def uncertainty_map_markdown(uncertainty: dict[str, Any]) -> str:
    lines = [
        "# Uncertainty Map",
        "",
        f"**Overall confidence:** {uncertainty.get('overall_confidence')}",
        "",
        "| Section | Confidence |",
        "|---|---|",
    ]
    for section, confidence in (uncertainty.get("by_section") or {}).items():
        lines.append(f"| {section} | {confidence} |")
    lines.append("")
    if uncertainty.get("top_uncertainties"):
        lines.append("## Top uncertainties")
        for item in uncertainty["top_uncertainties"]:
            lines.append(f"- **{item.get('area')}**: {item.get('reason')} → {item.get('recommended_action')} (source: {item.get('source')})")
        lines.append("")
    return "\n".join(lines)
