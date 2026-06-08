from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding
from app.services.use_case_profile import UseCaseProfile, profile_to_metadata


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
            deterministic = list(profile.workload_families)
            merged = list(dict.fromkeys(deterministic + [item for item in understanding.workload_families if item not in profile.excluded_families]))
            metadata["workload_families"] = merged[:4]
        if understanding.capabilities:
            metadata["capabilities"] = list(dict.fromkeys(metadata.get("capabilities", []) + understanding.capabilities))
        metadata["deep_understanding_status"] = understanding.enhancement_status
        return UnderstandingMergeResult(profile_metadata=metadata, conflicts=conflicts)
