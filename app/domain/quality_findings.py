from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.domain import utc_now


QualitySeverity = Literal["info", "warning", "critical", "blocker"]
QualityCategory = Literal[
    "understanding",
    "metrics",
    "capabilities",
    "architecture",
    "governance",
    "pricing",
    "evidence",
    "dossier",
    "diagram",
    "export",
    "security",
    "regression",
]
ReadinessImpact = Literal[
    "none",
    "cap_to_workshop",
    "cap_to_customer_demo",
    "cap_to_directional",
    "cap_to_internal_only",
    "fail",
]


class QualityFinding(BaseModel):
    id: str = Field(default_factory=lambda: f"qf_{uuid4().hex[:10]}")
    code: str
    severity: QualitySeverity
    category: QualityCategory
    title: str
    description: str
    evidence: list[str]
    affected_components: list[str] = Field(default_factory=list)
    affected_flows: list[str] = Field(default_factory=list)
    affected_sections: list[str] = Field(default_factory=list)
    auto_repairable: bool
    repair_strategy: str | None = None
    customer_readiness_impact: ReadinessImpact = "none"
    created_at: datetime = Field(default_factory=utc_now)
    repaired: bool = False
    repair_notes: str | None = None


def finding(
    *,
    code: str,
    severity: QualitySeverity,
    category: QualityCategory,
    title: str,
    description: str,
    evidence: list[str] | None = None,
    affected_components: list[str] | None = None,
    affected_flows: list[str] | None = None,
    affected_sections: list[str] | None = None,
    auto_repairable: bool = False,
    repair_strategy: str | None = None,
    customer_readiness_impact: ReadinessImpact = "none",
) -> QualityFinding:
    return QualityFinding(
        code=code,
        severity=severity,
        category=category,
        title=title,
        description=description,
        evidence=evidence or [],
        affected_components=affected_components or [],
        affected_flows=affected_flows or [],
        affected_sections=affected_sections or [],
        auto_repairable=auto_repairable,
        repair_strategy=repair_strategy,
        customer_readiness_impact=customer_readiness_impact,
    )
