from app.models.domain import (
    Assumption,
    CitationCoverageReport,
    EvidenceAssessment,
    EvidenceItem,
    PricingAnalysis,
    ReportClaim,
    RiskItem,
)
from app.domain.evidence import classify_evidence_authority, trust_score_for_authority


TRUST_POLICY = {
    "aws_pricing": (100, "high", "Authoritative AWS pricing source."),
    "aws_docs": (95, "high", "Authoritative AWS documentation source."),
    "aws_blog": (80, "high", "AWS-authored guidance, but may be scenario-specific."),
    "mcp": (70, "medium", "MCP tool output; validate against source metadata."),
    "user_input": (70, "medium", "User-provided project context, not an external factual source."),
    "local_policy": (60, "medium", "Archway local policy/default; useful but not live external evidence."),
    "web": (45, "low", "Open web result. Treat as untrusted until corroborated."),
}


class EvidenceDisciplineService:
    def assess(self, evidence_items: list[EvidenceItem]) -> list[EvidenceAssessment]:
        return [self._assess_item(item) for item in evidence_items]

    def build_claims(
        self,
        *,
        evidence_items: list[EvidenceItem],
        assumptions: list[Assumption],
        pricing: PricingAnalysis,
        risks: list[RiskItem],
    ) -> tuple[list[ReportClaim], list[ReportClaim], list[ReportClaim], CitationCoverageReport]:
        evidence_ids = [item.id for item in evidence_items]
        primary_id = evidence_ids[0] if evidence_ids else None
        pricing_ids = [item.id for item in pricing.evidence_items]
        facts = [
            ReportClaim(
                claim_type="fact",
                text="The report is based on user input, local architecture policy, and configured research tools.",
                evidence_ids=[
                    item.id
                    for item in evidence_items
                    if item.source_type in {"user_input", "local_policy", "web", "aws_docs", "aws_pricing"}
                ],
                confidence="medium",
                citation_status="cited",
            ),
            ReportClaim(
                claim_type="fact",
                text=f"Pricing is estimated as a range of ${pricing.low_monthly_usd}-${pricing.high_monthly_usd}/month in {pricing.region}.",
                evidence_ids=pricing_ids,
                confidence="medium",
                citation_status="cited" if pricing_ids else "uncited",
            ),
        ]
        recommendations = [
            ReportClaim(
                claim_type="recommendation",
                text="Start with a read-only, scoped POC before enabling business actions.",
                evidence_ids=[primary_id] if primary_id else [],
                confidence="high",
                citation_status="cited" if primary_id else "uncited",
            ),
            ReportClaim(
                claim_type="recommendation",
                text="Keep prompt injection, evidence citations, IAM scope, encryption, and audit trails as design constraints.",
                evidence_ids=[risk.evidence_ids[0] for risk in risks if risk.evidence_ids],
                confidence="high",
                citation_status="cited" if any(risk.evidence_ids for risk in risks) else "uncited",
            ),
        ]
        uncertainties = [
            ReportClaim(
                claim_type="uncertainty",
                text=f"Assumption: {assumption.text}",
                evidence_ids=[],
                confidence=assumption.confidence,
                citation_status="assumption_only",
            )
            for assumption in assumptions
        ]
        uncertainties.extend(
            ReportClaim(
                claim_type="uncertainty",
                text=f"Unknown pricing variable: {item}",
                evidence_ids=pricing_ids,
                confidence="medium",
                citation_status="cited" if pricing_ids else "uncited",
            )
            for item in pricing.unknown_variables
        )
        coverage = validate_citation_coverage(facts + recommendations + uncertainties)
        return facts, recommendations, uncertainties, coverage

    def _assess_item(self, item: EvidenceItem) -> EvidenceAssessment:
        authority = classify_evidence_authority(item.source_type, str(item.url) if item.url else None)
        score, label, rationale = trust_score_for_authority(authority)
        limitations = "Can support factual claims."
        if authority.value == "aws_marketplace_non_authoritative":
            limitations = "Marketplace listings are not authoritative for AWS service architecture, availability, or pricing claims."
        elif item.source_type == "web":
            limitations = "Use only as untrusted external context unless corroborated by AWS or pricing evidence."
        elif item.source_type == "local_policy":
            limitations = "Do not present as live AWS documentation or live AWS pricing."
        elif item.source_type == "user_input":
            limitations = "Use as project intent/context, not as independent validation."
        return EvidenceAssessment(
            evidence_id=item.id,
            source_type=authority.value,
            trust_score=score,
            trust_label=label,
            rationale=rationale,
            use_limitations=limitations,
        )


def validate_citation_coverage(claims: list[ReportClaim]) -> CitationCoverageReport:
    uncited = [
        claim
        for claim in claims
        if claim.citation_status == "uncited"
        or (claim.claim_type in {"fact", "recommendation"} and not claim.evidence_ids)
    ]
    cited_count = len(claims) - len(uncited)
    total = len(claims)
    coverage = round((cited_count / total) * 100, 2) if total else 100.0
    warnings = []
    if uncited:
        warnings.append("Some factual or recommendation claims lack evidence IDs.")
    if any(claim.citation_status == "assumption_only" for claim in claims):
        warnings.append("Assumptions are separated from evidence-backed facts.")
    return CitationCoverageReport(
        total_claims=total,
        cited_claims=cited_count,
        uncited_claims=len(uncited),
        coverage_percent=coverage,
        passed=len(uncited) == 0,
        warnings=warnings,
    )


def enforce_citation_gate(claims: list[ReportClaim]) -> CitationCoverageReport:
    coverage = validate_citation_coverage(claims)
    if not coverage.passed:
        raise ValueError("Research report contains uncited factual or recommendation claims.")
    return coverage
