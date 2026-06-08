from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.models.domain import CitationCoverageReport, EvidenceItem


class EvidenceAuthority(str, Enum):
    AWS_OFFICIAL = "aws_official"
    AWS_BLOG = "aws_blog"
    AWS_PRICING = "aws_pricing"
    THIRD_PARTY_HIGH_TRUST = "third_party_high_trust"
    THIRD_PARTY_LOW_TRUST = "third_party_low_trust"
    LOCAL_POLICY = "local_policy"
    USER_INPUT = "user_input"
    UNKNOWN = "unknown"


class EvidenceQualitySummary(BaseModel):
    citation_coverage_percent: float
    evidence_authority: Literal["strong", "mixed", "limited", "weak"]
    aws_docs_available: bool
    aws_pricing_available: bool
    customer_ready: bool
    limitations: list[str] = Field(default_factory=list)


def summarize_evidence_quality(evidence: list[EvidenceItem], coverage: CitationCoverageReport | None) -> EvidenceQualitySummary:
    source_types = {item.source_type for item in evidence}
    aws_docs = "aws_docs" in source_types
    aws_pricing = "aws_pricing" in source_types
    aws_docs_mcp = any(item.source_type == "aws_docs" and item.tool_name == "AWS Documentation MCP" and item.confidence == "high" for item in evidence)
    aws_pricing_mcp = any(item.source_type == "aws_pricing" and item.tool_name == "AWS Pricing MCP" and item.confidence == "high" for item in evidence)
    aws_pricing_bulk = any(item.source_type == "aws_pricing" and item.tool_name == "AWS Price List Bulk API" and item.confidence == "high" for item in evidence)
    aws_docs_fallback = any(item.source_type == "aws_docs" and "fallback" in (item.tool_name or "").lower() for item in evidence)
    aws_pricing_fallback = any(item.source_type == "aws_pricing" and "fallback" in (item.tool_name or "").lower() for item in evidence)
    coverage_percent = coverage.coverage_percent if coverage else 0.0
    limitations = []
    if not aws_docs:
        limitations.append("AWS Docs MCP unavailable; AWS service recommendations require authoritative refresh.")
    elif aws_docs_fallback and not aws_docs_mcp:
        limitations.append("AWS documentation evidence came from official AWS web fallback, not AWS Docs MCP.")
    if not aws_pricing:
        limitations.append("AWS Pricing MCP unavailable; pricing is deterministic and directional, not procurement-grade.")
    elif aws_pricing_bulk and not aws_pricing_mcp:
        limitations.append("AWS Price List Bulk API catalog evidence was available; exact SKU/tier price calculations require service-specific filters before procurement.")
    elif aws_pricing_fallback and not aws_pricing_mcp:
        limitations.append("AWS pricing evidence came from official AWS web fallback; deterministic estimates still require live pricing validation.")
    if source_types <= {"local_policy", "user_input", "mcp"}:
        limitations.append("Evidence is limited to user input, local policy, or unavailable-tool notices.")
    if aws_docs_mcp and aws_pricing_mcp and coverage_percent >= 95:
        authority = "strong"
    elif aws_docs or aws_pricing:
        authority = "mixed"
    elif coverage_percent > 0:
        authority = "limited"
    else:
        authority = "weak"
    return EvidenceQualitySummary(
        citation_coverage_percent=coverage_percent,
        evidence_authority=authority,
        aws_docs_available=aws_docs,
        aws_pricing_available=aws_pricing,
        customer_ready=authority == "strong",
        limitations=limitations,
    )
