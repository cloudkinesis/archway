from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding
from app.services.use_case_profile import WORKLOAD_FAMILY_VOCABULARY, UseCaseProfile, profile_to_metadata


def _live_llm_validated(status: str | None) -> bool:
    status = (status or "").strip().lower()
    return status.endswith("_validated") and not status.startswith("deterministic")


def _judge_allows_family_authority(understanding: DeepUseCaseUnderstanding, llm_families: list[str]) -> tuple[bool, list[str], str | None]:
    review = getattr(understanding, "family_topology_judge", None)
    if review is None or review.status == "not_attempted":
        return True, llm_families, None
    rejected = set(review.rejected_families or [])
    accepted = [family for family in (review.accepted_families or llm_families) if family in llm_families and family not in rejected]
    if review.status == "accepted" and review.decision == "accept" and accepted:
        return True, accepted, None
    return False, [family for family in llm_families if family not in rejected], f"judge_{review.decision}"


class UnderstandingConflict(BaseModel):
    field: str
    deterministic_value: object
    llm_value: object
    resolution: str


class UnderstandingMergeResult(BaseModel):
    profile_metadata: dict
    conflicts: list[UnderstandingConflict] = Field(default_factory=list)


class UnderstandingMerger:
    def merge(self, profile: UseCaseProfile, understanding: DeepUseCaseUnderstanding) -> UnderstandingMergeResult:
        metadata = profile_to_metadata(profile)
        conflicts: list[UnderstandingConflict] = []
        if understanding.domain and profile.domain and understanding.domain != profile.domain:
            conflicts.append(UnderstandingConflict(field="domain", deterministic_value=profile.domain, llm_value=understanding.domain, resolution="deterministic_user_facts_win"))
        elif understanding.domain:
            metadata["domain"] = understanding.domain
        if understanding.workload_families:
            # D36: the live LLM's workload-family classification is authoritative for the
            # topology/pricing family, reversing the prior deterministic-first union where
            # the keyword ranker always led. Deterministic gate: only accept LLM families
            # that are in the controlled vocabulary and not explicitly excluded (no
            # hallucinated families). Deterministic families are never dropped — they fill
            # the remaining slots behind the LLM's classification.
            #
            # Churn-safe by construction: when there is no live LLM, the deep-understanding
            # fallback copies the deterministic families, so the LLM proposes nothing new
            # (`llm_new` is empty) and deterministic order is preserved unchanged. The flip
            # only takes effect when a live LLM genuinely diverges.
            excluded = set(profile.excluded_families or [])
            deterministic = [family for family in profile.workload_families if family not in excluded]
            llm = [
                family for family in understanding.workload_families
                if family in WORKLOAD_FAMILY_VOCABULARY and family not in excluded
            ]
            judge_allows_authority, llm, judge_resolution = _judge_allows_family_authority(understanding, llm)
            llm_new = [family for family in llm if family not in deterministic]
            if llm_new and _live_llm_validated(understanding.enhancement_status) and judge_allows_authority:
                merged = list(dict.fromkeys(llm + deterministic))
                conflicts.append(UnderstandingConflict(
                    field="workload_families",
                    deterministic_value=deterministic,
                    llm_value=llm,
                    resolution="llm_classification_authoritative",
                ))
            else:
                merged = list(dict.fromkeys(deterministic + llm))
                if llm_new and _live_llm_validated(understanding.enhancement_status) and not judge_allows_authority:
                    conflicts.append(UnderstandingConflict(
                        field="workload_families",
                        deterministic_value=deterministic,
                        llm_value=llm,
                        resolution=judge_resolution or "llm_classification_judge_blocked",
                    ))
            metadata["workload_families"] = (merged or ["web_api_application"])[:4]
        if understanding.capabilities:
            metadata["capabilities"] = list(dict.fromkeys(metadata.get("capabilities", []) + understanding.capabilities))
        metadata["deep_understanding_status"] = understanding.enhancement_status
        return UnderstandingMergeResult(profile_metadata=metadata, conflicts=conflicts)
