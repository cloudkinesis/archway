from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.dossier_manifest import stable_json_hash

ReviewerSeverity = Literal["info", "advisory", "warning", "blocker"]
ReviewerCategory = Literal[
    "uncited_claim",
    "unsupported_precision",
    "pricing_overprecision",
    "missing_driver",
    "domain_leakage",
    "readiness_overpromotion",
    "client_machine_speak",
    "diagram_gap",
    "evidence_gap",
    "contradiction",
    "compliance_overclaim",
    "unknown",
]
ReviewerProvenance = Literal["deterministic", "derived", "model_proposed", "skipped"]
ReviewerDecisionStatus = Literal["added", "rejected", "duplicate", "downgraded"]


class ReviewerFindingProposal(BaseModel):
    finding_id: str
    lane: Literal["reviewer"] = "reviewer"
    severity: ReviewerSeverity
    category: ReviewerCategory = "unknown"
    target_artifact: str
    target_section: str | None = None
    message: str
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_repair: str | None = None
    provenance: ReviewerProvenance = "model_proposed"
    can_downgrade_readiness: bool = False


class ReviewerDecision(BaseModel):
    finding_id: str
    decision: ReviewerDecisionStatus
    reason: str
    deterministic_gate: str


class ReviewerTrace(BaseModel):
    run_id: str
    enabled: bool = False
    provider: str
    proposed_findings: list[ReviewerFindingProposal] = Field(default_factory=list)
    accepted_findings: list[ReviewerFindingProposal] = Field(default_factory=list)
    rejected_findings: list[ReviewerFindingProposal] = Field(default_factory=list)
    duplicate_findings: list[ReviewerFindingProposal] = Field(default_factory=list)
    decisions: list[ReviewerDecision] = Field(default_factory=list)
    deterministic_reviewer_ref: dict[str, Any] = Field(default_factory=dict)
    input_hash: str
    output_hash: str
    prompt_hash: str | None = None
    response_hash: str | None = None


class ReviewerProvider(Protocol):
    provider_name: str

    def propose_findings(self, context: dict[str, Any]) -> list[ReviewerFindingProposal]: ...

    def validate_findings(self, findings: list[ReviewerFindingProposal], deterministic_context: dict[str, Any]) -> ReviewerTrace: ...


class DisabledReviewerProvider:
    provider_name = "disabled"

    def trace(self, context: dict[str, Any]) -> ReviewerTrace:
        input_hash = stable_json_hash(context)
        output_hash = stable_json_hash({
            "deterministic_reviewer_ref": _deterministic_reviewer_ref(context),
            "enabled": False,
            "findings": [],
        })
        return ReviewerTrace(
            run_id="reviewer_run_" + input_hash.removeprefix("sha256:")[:12],
            enabled=False,
            provider=self.provider_name,
            deterministic_reviewer_ref=_deterministic_reviewer_ref(context),
            decisions=[
                ReviewerDecision(
                    finding_id="reviewer_disabled",
                    decision="rejected",
                    reason="Agentic reviewer lane is disabled by feature flag.",
                    deterministic_gate="ARCHWAY_ENABLE_AGENTIC_REVIEWER",
                )
            ],
            input_hash=input_hash,
            output_hash=output_hash,
        )


class DeterministicFixtureReviewerProvider:
    provider_name = "deterministic_fixture"

    def propose_findings(self, context: dict[str, Any]) -> list[ReviewerFindingProposal]:
        findings = [
            ReviewerFindingProposal(
                finding_id="agent_review_pricing_precision",
                severity="warning",
                category="pricing_overprecision",
                target_artifact="03-pricing.md",
                target_section="Pricing summary",
                message="Check that directional pricing language does not read as procurement-ready.",
                evidence_refs=["pricing.metadata.pricing_driver_closure"],
                suggested_repair="Keep assumptions and missing quantities visible.",
                provenance="derived",
            ),
            ReviewerFindingProposal(
                finding_id="agent_review_client_machine_speak",
                severity="advisory",
                category="client_machine_speak",
                target_artifact="client_pack/solution-brief.md",
                target_section="Executive summary",
                message="Check whether client-facing prose exposes implementation trace language.",
                evidence_refs=["client_pack"],
                suggested_repair="Move machine-readable trace terms to audit_pack only.",
                provenance="derived",
            ),
        ]
        return sorted(findings, key=lambda item: item.finding_id)

    def validate_findings(self, findings: list[ReviewerFindingProposal], deterministic_context: dict[str, Any]) -> ReviewerTrace:
        return validate_reviewer_findings(findings, deterministic_context, provider_name=self.provider_name)


class LiveReviewerProvider:
    provider_name = "live_stub"

    def propose_findings(self, context: dict[str, Any]) -> list[ReviewerFindingProposal]:
        raise NotImplementedError("Live reviewer provider is intentionally unavailable in this audit-only branch.")

    def validate_findings(self, findings: list[ReviewerFindingProposal], deterministic_context: dict[str, Any]) -> ReviewerTrace:
        raise NotImplementedError("Live reviewer validation is intentionally unavailable in this branch.")


def build_reviewer_context(
    *,
    report: dict | None,
    pricing: dict | None,
    reviewer_report: Any | None,
    client_pack_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    deterministic_findings = _deterministic_findings(reviewer_report)
    metadata = (report or {}).get("metadata") or {}
    pricing_metadata = (pricing or {}).get("metadata") or {}
    return {
        "deterministic_reviewer": {
            "finding_ids": sorted(_finding_id(item) for item in deterministic_findings),
            "finding_count": len(deterministic_findings),
            "summary": getattr(reviewer_report, "summary", {}) if reviewer_report is not None else {},
        },
        "pricing": {
            "headline_safe": pricing_metadata.get("pricing_can_be_displayed_as_headline") is True,
            "procurement_ready": pricing_metadata.get("procurement_ready") is True,
            "closure": pricing_metadata.get("pricing_driver_closure") or {},
        },
        "readiness": (metadata.get("customer_readiness") or {}),
        "client_pack_paths": sorted((client_pack_files or {}).keys()),
    }


def build_reviewer_trace(
    *,
    settings: Settings,
    context: dict[str, Any],
    provider: ReviewerProvider | None = None,
) -> ReviewerTrace:
    if not settings.enable_agentic_reviewer:
        return DisabledReviewerProvider().trace(context)
    provider = provider or DeterministicFixtureReviewerProvider()
    findings = provider.propose_findings(context)
    return provider.validate_findings(findings, context)


def validate_reviewer_findings(
    findings: list[ReviewerFindingProposal],
    deterministic_context: dict[str, Any],
    *,
    provider_name: str,
) -> ReviewerTrace:
    input_hash = stable_json_hash(deterministic_context)
    deterministic_ids = set((_deterministic_reviewer_ref(deterministic_context).get("finding_ids") or []))
    accepted: list[ReviewerFindingProposal] = []
    rejected: list[ReviewerFindingProposal] = []
    duplicates: list[ReviewerFindingProposal] = []
    decisions: list[ReviewerDecision] = []
    seen: set[str] = set()
    for finding in sorted(findings, key=lambda item: item.finding_id):
        if finding.finding_id in deterministic_ids or finding.finding_id in seen:
            duplicates.append(finding)
            decisions.append(ReviewerDecision(
                finding_id=finding.finding_id,
                decision="duplicate",
                reason="Finding duplicates an existing deterministic or agentic finding and was not added again.",
                deterministic_gate="D21 reviewer additive-only validation",
            ))
            continue
        seen.add(finding.finding_id)
        if finding.can_downgrade_readiness:
            rejected.append(finding)
            decisions.append(ReviewerDecision(
                finding_id=finding.finding_id,
                decision="rejected",
                reason="Agentic reviewer findings cannot downgrade or unlock readiness.",
                deterministic_gate="readiness_authority",
            ))
            continue
        if finding.severity == "blocker":
            downgraded = finding.model_copy(update={"severity": "warning"})
            accepted.append(downgraded)
            decisions.append(ReviewerDecision(
                finding_id=finding.finding_id,
                decision="downgraded",
                reason="Agentic blocker severity is advisory-only unless a deterministic gate agrees.",
                deterministic_gate="deterministic_reviewer_authority",
            ))
            continue
        accepted.append(finding)
        decisions.append(ReviewerDecision(
            finding_id=finding.finding_id,
            decision="added",
            reason="Finding is additive, audit-only, and cannot remove deterministic findings.",
            deterministic_gate="D21 reviewer additive-only validation",
        ))
    output_hash = stable_json_hash({
        "deterministic_reviewer_ref": _deterministic_reviewer_ref(deterministic_context),
        "proposed_findings": [item.model_dump(mode="json") for item in sorted(findings, key=lambda item: item.finding_id)],
        "accepted_findings": [item.model_dump(mode="json") for item in accepted],
        "rejected_findings": [item.model_dump(mode="json") for item in rejected],
        "duplicate_findings": [item.model_dump(mode="json") for item in duplicates],
        "decisions": [item.model_dump(mode="json") for item in decisions],
    })
    return ReviewerTrace(
        run_id="reviewer_run_" + input_hash.removeprefix("sha256:")[:12],
        enabled=True,
        provider=provider_name,
        proposed_findings=sorted(findings, key=lambda item: item.finding_id),
        accepted_findings=accepted,
        rejected_findings=rejected,
        duplicate_findings=duplicates,
        decisions=decisions,
        deterministic_reviewer_ref=_deterministic_reviewer_ref(deterministic_context),
        input_hash=input_hash,
        output_hash=output_hash,
    )


def reviewer_summary_markdown(trace: ReviewerTrace) -> str:
    lines = [
        "# D21 Agentic Reviewer Findings",
        "",
        "This audit-only supplement records additive reviewer/red-team findings. Deterministic reviewer findings remain authoritative and cannot be removed or downgraded by this lane.",
        "",
        f"**Enabled:** {'Yes' if trace.enabled else 'No'}",
        f"**Provider:** {trace.provider}",
        f"**Run ID:** `{trace.run_id}`",
        f"**Input hash:** `{trace.input_hash}`",
        f"**Output hash:** `{trace.output_hash}`",
        "",
        "## Accepted Additive Findings",
        "",
    ]
    if trace.accepted_findings:
        lines.extend(f"- [{item.severity}] {item.category} on `{item.target_artifact}`: {item.message}" for item in trace.accepted_findings)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Rejected Findings", ""])
    if trace.rejected_findings:
        lines.extend(f"- {item.finding_id}: {item.message}" for item in trace.rejected_findings)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Duplicate Findings", ""])
    if trace.duplicate_findings:
        lines.extend(f"- {item.finding_id}: {item.message}" for item in trace.duplicate_findings)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Decisions", ""])
    if trace.decisions:
        lines.extend(f"- {item.finding_id}: {item.decision} — {item.reason}" for item in trace.decisions)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "Reviewer-agent output is additive, raw/audit-only, and cannot change readiness, pricing, architecture, governance, diagrams, or client_pack.", ""])
    return "\n".join(lines)


def _deterministic_reviewer_ref(context: dict[str, Any]) -> dict[str, Any]:
    ref = context.get("deterministic_reviewer") or {}
    return {
        "finding_ids": sorted(str(item) for item in ref.get("finding_ids") or []),
        "finding_count": int(ref.get("finding_count") or 0),
        "summary": ref.get("summary") or {},
    }


def _deterministic_findings(reviewer_report: Any | None) -> list[Any]:
    if reviewer_report is None:
        return []
    findings = getattr(reviewer_report, "findings", None)
    if findings is not None:
        return list(findings)
    if isinstance(reviewer_report, dict):
        return list(reviewer_report.get("findings") or [])
    return []


def _finding_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("finding_id") or item.get("rule_id") or item.get("id") or item)
    return str(getattr(item, "finding_id", None) or getattr(item, "rule_id", None) or item)
