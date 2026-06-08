from enum import Enum
from urllib.parse import urlparse


class EvidenceMode(str, Enum):
    AWS_OFFICIAL_ONLY = "aws_official_only"
    AWS_PLUS_APPROVED_THIRD_PARTY = "aws_plus_approved_third_party"
    GENERAL_WEB_RESEARCH = "general_web_research"
    LOCAL_POLICY_ONLY = "local_policy_only"


class EvidenceAuthority(str, Enum):
    AWS_OFFICIAL_DOCS = "aws_official_docs"
    AWS_OFFICIAL_BLOG = "aws_official_blog"
    AWS_SERVICE_PAGE = "aws_service_page"
    AWS_PRICING = "aws_pricing"
    AWS_WHATS_NEW = "aws_whats_new"
    AWS_MARKETPLACE = "aws_marketplace_non_authoritative"
    THIRD_PARTY_HIGH_TRUST = "third_party_high_trust"
    THIRD_PARTY_LOW_TRUST = "third_party_low_trust"
    LOCAL_POLICY = "local_policy"
    USER_INPUT = "user_input"
    UNKNOWN = "unknown"


def classify_evidence_authority(source_type: str, url: str | None) -> EvidenceAuthority:
    if source_type == "local_policy":
        return EvidenceAuthority.LOCAL_POLICY
    if source_type == "user_input":
        return EvidenceAuthority.USER_INPUT
    if source_type == "aws_pricing":
        return EvidenceAuthority.AWS_PRICING
    if not url:
        if source_type == "aws_docs":
            return EvidenceAuthority.AWS_OFFICIAL_DOCS
        if source_type == "aws_blog":
            return EvidenceAuthority.AWS_OFFICIAL_BLOG
        return EvidenceAuthority.UNKNOWN
    parsed = urlparse(str(url))
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.lower()
    if host == "docs.aws.amazon.com":
        return EvidenceAuthority.AWS_OFFICIAL_DOCS
    if host == "aws.amazon.com":
        if path.startswith("/marketplace"):
            return EvidenceAuthority.AWS_MARKETPLACE
        if path.startswith("/pricing") or "/pricing/" in path:
            return EvidenceAuthority.AWS_PRICING
        if path.startswith("/about-aws/whats-new"):
            return EvidenceAuthority.AWS_WHATS_NEW
        if path.startswith("/blogs/awsmarketplace") or path.startswith("/blogs/marketplace"):
            return EvidenceAuthority.AWS_MARKETPLACE
        if path.startswith("/blogs/"):
            return EvidenceAuthority.AWS_OFFICIAL_BLOG
        if path.startswith(("/solutions/", "/architecture/", "/what-is/")):
            return EvidenceAuthority.AWS_SERVICE_PAGE
        return EvidenceAuthority.AWS_SERVICE_PAGE
    if host.endswith(".amazonaws.com") and "pricing" in host:
        return EvidenceAuthority.AWS_PRICING
    if host == "repost.aws":
        return EvidenceAuthority.THIRD_PARTY_HIGH_TRUST
    if host in {"youtube.com", "www.youtube.com", "youtu.be"}:
        return EvidenceAuthority.THIRD_PARTY_LOW_TRUST
    return EvidenceAuthority.THIRD_PARTY_LOW_TRUST


def source_allowed_for_mode(source_type: str, url: str | None, mode: EvidenceMode) -> bool:
    authority = classify_evidence_authority(source_type, url)
    if mode == EvidenceMode.LOCAL_POLICY_ONLY:
        return authority in {EvidenceAuthority.LOCAL_POLICY, EvidenceAuthority.USER_INPUT}
    if mode == EvidenceMode.AWS_OFFICIAL_ONLY:
        return authority in {
            EvidenceAuthority.AWS_OFFICIAL_DOCS,
            EvidenceAuthority.AWS_OFFICIAL_BLOG,
            EvidenceAuthority.AWS_SERVICE_PAGE,
            EvidenceAuthority.AWS_PRICING,
            EvidenceAuthority.AWS_WHATS_NEW,
            EvidenceAuthority.AWS_MARKETPLACE,
        }
    if mode == EvidenceMode.AWS_PLUS_APPROVED_THIRD_PARTY:
        return authority != EvidenceAuthority.UNKNOWN
    return True


def trust_score_for_authority(authority: EvidenceAuthority) -> tuple[int, str, str]:
    policy = {
        EvidenceAuthority.AWS_OFFICIAL_DOCS: (95, "high", "Authoritative AWS documentation."),
        EvidenceAuthority.AWS_PRICING: (100, "high", "Authoritative AWS pricing source or structured Price List catalog."),
        EvidenceAuthority.AWS_WHATS_NEW: (95, "high", "Official AWS launch/current-awareness source."),
        EvidenceAuthority.AWS_OFFICIAL_BLOG: (85, "high", "AWS-authored blog guidance; useful but often scenario-specific."),
        EvidenceAuthority.AWS_SERVICE_PAGE: (85, "high", "Official AWS service or solution page."),
        EvidenceAuthority.AWS_MARKETPLACE: (55, "medium", "AWS Marketplace listing; non-authoritative for AWS architecture or pricing claims."),
        EvidenceAuthority.LOCAL_POLICY: (60, "medium", "Archway local policy/default; internal guidance only."),
        EvidenceAuthority.USER_INPUT: (75, "medium", "User-provided requirements; authoritative for intent, not AWS facts."),
        EvidenceAuthority.THIRD_PARTY_HIGH_TRUST: (65, "medium", "Approved third-party source; corroborate before final claims."),
        EvidenceAuthority.THIRD_PARTY_LOW_TRUST: (35, "low", "Unapproved third-party source."),
        EvidenceAuthority.UNKNOWN: (25, "low", "Unknown or unsupported source authority."),
    }
    return policy[authority]
