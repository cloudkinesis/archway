"""D37: judge-reviewed topology fit gates LLM family authority.

The main model may propose workload families, but when an explicit judge review exists,
only an accepted judge decision can promote those families to primary topology authority.
Rejected/downgraded judge results keep deterministic order and audit the block.
"""

from app.services.understanding.deep_use_case_understanding import (
    FamilyTopologyJudgeReview,
    deterministic_understanding,
)
from app.services.understanding.understanding_merger import UnderstandingMerger
from app.services.use_case_profile import profile_use_case

_UC = "building permit AI review platform with document review and approval workflow"


def _understanding_with_llm_family():
    profile = profile_use_case(_UC)
    understanding = deterministic_understanding(_UC, profile).model_copy(deep=True)
    understanding.workload_families = ["document_intelligence", "approval_gated_workflow_automation"]
    understanding.enhancement_status = "bedrock_validated"
    return profile, understanding


def test_judge_accept_allows_llm_family_to_lead():
    profile, understanding = _understanding_with_llm_family()
    understanding.family_topology_judge = FamilyTopologyJudgeReview(
        status="accepted",
        decision="accept",
        fit_confidence="high",
        accepted_families=["document_intelligence", "approval_gated_workflow_automation"],
        rationale="Document extraction and approval workflow are supported by the use case.",
    )

    result = UnderstandingMerger().merge(profile, understanding)

    assert result.profile_metadata["workload_families"][0] == "document_intelligence"
    assert any(conflict.resolution == "llm_classification_authoritative" for conflict in result.conflicts)


def test_judge_downgrade_blocks_llm_family_authority():
    profile, understanding = _understanding_with_llm_family()
    understanding.family_topology_judge = FamilyTopologyJudgeReview(
        status="accepted",
        decision="downgrade",
        fit_confidence="medium",
        accepted_families=[],
        rejected_families=[],
        rationale="The proposed family needs human review before driving topology.",
    )

    result = UnderstandingMerger().merge(profile, understanding)

    assert result.profile_metadata["workload_families"][0] == profile.workload_families[0]
    assert "document_intelligence" in result.profile_metadata["workload_families"]
    assert any(conflict.resolution == "judge_downgrade" for conflict in result.conflicts)


def test_judge_rejected_family_is_removed_from_llm_contribution():
    profile, understanding = _understanding_with_llm_family()
    understanding.family_topology_judge = FamilyTopologyJudgeReview(
        status="accepted",
        decision="reject",
        fit_confidence="high",
        rejected_families=["document_intelligence"],
        rationale="Document intelligence was judged unsupported.",
    )

    result = UnderstandingMerger().merge(profile, understanding)

    assert "document_intelligence" not in result.profile_metadata["workload_families"]
    assert any(conflict.resolution == "judge_reject" for conflict in result.conflicts)


def test_missing_judge_review_preserves_d36_behavior():
    profile, understanding = _understanding_with_llm_family()
    understanding.family_topology_judge = None

    result = UnderstandingMerger().merge(profile, understanding)

    assert result.profile_metadata["workload_families"][0] == "document_intelligence"
