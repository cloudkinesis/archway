"""D36: the live LLM workload-family classification is authoritative at the merge point.

UnderstandingMerger reconciles the deterministic profile with the deep-understanding
result. Authority rule: when a live LLM genuinely diverges (proposes an in-vocabulary
family the ranker did not), the LLM leads (primary family + topology). When there is no
live LLM (offline), the deep-understanding fallback copies the deterministic families, so
the flip is a no-op -- guaranteeing zero golden churn. Hallucinated families are gated out.
"""

from app.services.understanding.understanding_merger import UnderstandingMerger
from app.services.understanding.deep_use_case_understanding import deterministic_understanding
from app.services.use_case_profile import profile_use_case

_UC = "building permit AI review platform with curator approval workflow"


def _det_understanding():
    profile = profile_use_case(_UC)
    return profile, deterministic_understanding(_UC, profile)


def test_offline_is_a_noop_no_churn():
    profile, understanding = _det_understanding()  # deterministic fallback == profile families
    result = UnderstandingMerger().merge(profile, understanding)
    assert result.profile_metadata["workload_families"] == profile.workload_families[:4]
    assert not any(c.field == "workload_families" for c in result.conflicts)


def test_live_llm_divergence_is_authoritative():
    profile, understanding = _det_understanding()
    understanding = understanding.model_copy(deep=True)
    understanding.workload_families = ["document_intelligence", "approval_gated_workflow_automation"]
    understanding.enhancement_status = "bedrock_validated"
    result = UnderstandingMerger().merge(profile, understanding)
    families = result.profile_metadata["workload_families"]
    assert families[0] == "document_intelligence"  # LLM leads, not the deterministic ranker
    assert any(c.field == "workload_families" and c.resolution == "llm_classification_authoritative" for c in result.conflicts)
    # deterministic families are preserved (not dropped), just reordered behind the LLM's.
    for fam in profile.workload_families[:2]:
        assert fam in families


def test_non_live_divergence_does_not_become_authoritative():
    profile, understanding = _det_understanding()
    understanding = understanding.model_copy(deep=True)
    understanding.workload_families = ["document_intelligence", "approval_gated_workflow_automation"]
    understanding.enhancement_status = "deterministic_fallback"
    result = UnderstandingMerger().merge(profile, understanding)
    families = result.profile_metadata["workload_families"]
    assert families[0] == profile.workload_families[0]
    assert "document_intelligence" in families
    assert not any(c.field == "workload_families" for c in result.conflicts)


def test_hallucinated_family_is_gated_out():
    profile, understanding = _det_understanding()
    understanding = understanding.model_copy(deep=True)
    understanding.workload_families = ["totally_made_up_family", "event_driven_workflow"]
    understanding.enhancement_status = "bedrock_validated"
    result = UnderstandingMerger().merge(profile, understanding)
    assert "totally_made_up_family" not in result.profile_metadata["workload_families"]


def test_excluded_family_never_selected_even_if_llm_proposes_it():
    profile, understanding = _det_understanding()
    profile.excluded_families = ["industrial_iot_streaming_ml"]
    understanding = understanding.model_copy(deep=True)
    understanding.workload_families = ["industrial_iot_streaming_ml", "document_intelligence"]
    understanding.enhancement_status = "bedrock_validated"
    result = UnderstandingMerger().merge(profile, understanding)
    assert "industrial_iot_streaming_ml" not in result.profile_metadata["workload_families"]
    assert "document_intelligence" in result.profile_metadata["workload_families"]
