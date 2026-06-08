from app.models.domain import Assumption, EvidenceItem, PricingAnalysis, PricingLineItem, ReportClaim, RiskItem
from app.domain.evidence import EvidenceAuthority, EvidenceMode, classify_evidence_authority, source_allowed_for_mode
from app.services.evidence_discipline import EvidenceDisciplineService, enforce_citation_gate, validate_citation_coverage


def test_evidence_assessment_marks_web_lower_trust():
    service = EvidenceDisciplineService()
    evidence = [
        EvidenceItem(source_type="aws_docs", title="AWS docs", quote_or_summary="docs", confidence="high"),
        EvidenceItem(source_type="web", title="Web result", quote_or_summary="web", confidence="medium"),
    ]

    assessed = service.assess(evidence)

    assert assessed[0].trust_score > assessed[1].trust_score
    assert assessed[1].trust_label == "low"


def test_evidence_authority_classifies_aws_sources_and_marketplace():
    assert classify_evidence_authority("aws_docs", "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html") == EvidenceAuthority.AWS_OFFICIAL_DOCS
    assert classify_evidence_authority("aws_blog", "https://aws.amazon.com/blogs/aws/example/") == EvidenceAuthority.AWS_OFFICIAL_BLOG
    assert classify_evidence_authority("aws_pricing", "https://aws.amazon.com/pricing/") == EvidenceAuthority.AWS_PRICING
    assert classify_evidence_authority("web", "https://aws.amazon.com/marketplace/pp/prodview") == EvidenceAuthority.AWS_MARKETPLACE


def test_evidence_modes_enforce_authority_boundaries():
    assert source_allowed_for_mode("aws_docs", "https://docs.aws.amazon.com/s3/", EvidenceMode.AWS_OFFICIAL_ONLY)
    assert source_allowed_for_mode("web", "https://aws.amazon.com/marketplace/pp/prodview", EvidenceMode.AWS_OFFICIAL_ONLY)
    assert not source_allowed_for_mode("web", "https://example.com/blog", EvidenceMode.AWS_OFFICIAL_ONLY)
    assert source_allowed_for_mode("local_policy", None, EvidenceMode.LOCAL_POLICY_ONLY)
    assert not source_allowed_for_mode("aws_docs", "https://docs.aws.amazon.com/s3/", EvidenceMode.LOCAL_POLICY_ONLY)


def test_citation_coverage_fails_uncited_fact():
    claims = [
        ReportClaim(claim_type="fact", text="Uncited fact", evidence_ids=[], confidence="medium", citation_status="uncited")
    ]

    coverage = validate_citation_coverage(claims)

    assert coverage.passed is False
    assert coverage.uncited_claims == 1


def test_citation_gate_raises_for_uncited_fact():
    claims = [
        ReportClaim(claim_type="fact", text="Uncited fact", evidence_ids=[], confidence="medium", citation_status="uncited")
    ]

    try:
        enforce_citation_gate(claims)
    except ValueError as exc:
        assert "uncited" in str(exc)
    else:
        raise AssertionError("Expected citation gate to fail")


def test_claim_builder_separates_assumptions_from_facts():
    service = EvidenceDisciplineService()
    evidence = [EvidenceItem(source_type="local_policy", title="Policy", quote_or_summary="policy", confidence="medium")]
    pricing_evidence = [EvidenceItem(source_type="local_policy", title="Pricing basis", quote_or_summary="basis", confidence="medium")]
    pricing = PricingAnalysis(
        region="us-east-1",
        low_monthly_usd=10,
        expected_monthly_usd=20,
        high_monthly_usd=40,
        line_items=[
            PricingLineItem(
                service="Amazon Bedrock",
                unit_basis="tokens",
                low_monthly_usd=10,
                expected_monthly_usd=20,
                high_monthly_usd=40,
                assumptions=[],
                evidence_ids=[pricing_evidence[0].id],
            )
        ],
        main_cost_drivers=[],
        cost_optimization_recommendations=[],
        unknown_variables=["token volume"],
        evidence_items=pricing_evidence,
    )
    assumptions = [
        Assumption(text="Use us-east-1", reason="No region chosen", impact="pricing", confidence="medium")
    ]
    risks = [RiskItem(title="Risk", severity="medium", mitigation="Mitigate", evidence_ids=[evidence[0].id])]

    facts, recommendations, uncertainties, coverage = service.build_claims(
        evidence_items=evidence + pricing_evidence,
        assumptions=assumptions,
        pricing=pricing,
        risks=risks,
    )

    assert facts
    assert recommendations
    assert any(item.citation_status == "assumption_only" for item in uncertainties)
    assert coverage.passed is True
