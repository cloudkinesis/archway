from typing import Literal

from pydantic import BaseModel, Field

from app.domain.capabilities import ArchitectureCapability


class ServiceDecisionOption(BaseModel):
    service_name: str
    fit: Literal["strong", "medium", "weak", "not_recommended"]
    rationale: str
    risks: list[str] = Field(default_factory=list)
    cost_notes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ServiceDecisionRecord(BaseModel):
    decision_id: str
    capability: ArchitectureCapability
    selected_service: str
    selected_service_rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    options_considered: list[ServiceDecisionOption]
    selection_reason: str
    assumptions: list[str] = Field(default_factory=list)
    required_validation: list[str] = Field(default_factory=list)
