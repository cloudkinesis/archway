from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding
from app.services.use_case_profile import UseCaseProfile


class UnderstandingValidationIssue(BaseModel):
    severity: str
    code: str
    message: str


class UnderstandingValidationResult(BaseModel):
    passed: bool
    issues: list[UnderstandingValidationIssue] = Field(default_factory=list)


class UnderstandingValidator:
    def validate(self, raw_use_case: str, profile: UseCaseProfile, understanding: DeepUseCaseUnderstanding) -> UnderstandingValidationResult:
        lower = raw_use_case.lower()
        issues: list[UnderstandingValidationIssue] = []
        extracted_names = {metric.name for metric in understanding.extracted_metrics}
        deterministic_names = set()
        for bucket in ("asset_counts", "business_targets"):
            deterministic_names.update(((profile.structured_metrics or {}).get(bucket) or {}).keys())
        missed = sorted(name for name in deterministic_names if name not in extracted_names)
        if missed:
            issues.append(_issue("critical", "explicit_metrics_missed", f"Explicit deterministic metrics were not present in deep understanding: {', '.join(missed[:8])}."))
        if re.search(r"\d", raw_use_case) and not understanding.extracted_metrics:
            issues.append(_issue("critical", "numbers_without_metrics", "Raw use case contains numbers, but understanding extracted no metrics."))
        if profile.domain and understanding.domain not in {profile.domain, "unknown", None} and profile.domain != understanding.industry:
            issues.append(_issue("critical", "domain_conflict", f"Deep understanding domain '{understanding.domain}' conflicts with deterministic domain '{profile.domain}'."))
        if profile.deployment_posture and understanding.deployment_posture == "public_cloud" and any(item in profile.deployment_posture for item in ("hybrid", "edge_and_cloud", "air_gapped_on_prem", "exchange_colocated", "sovereign_cloud")):
            issues.append(_issue("critical", "deployment_posture_conflict", "Deep understanding defaulted to public cloud despite deterministic hybrid/edge/sovereign posture signals."))
        if "semiconductor" in lower and understanding.industry == "healthcare" and not any(term in lower for term in ("patient", "clinical", "ehr", "hospital")):
            issues.append(_issue("critical", "semiconductor_as_healthcare", "Semiconductor workload cannot be classified as healthcare without clinical terms."))
        if "phi_data" in understanding.capabilities and not any(term in lower for term in ("patient", "clinical", "ehr", "hospital", "hipaa", " phi ")):
            issues.append(_issue("critical", "unsupported_phi", "PHI capability appeared without patient/EHR/clinical terms."))
        if "video_streaming" in understanding.capabilities and not any(term in lower for term in ("video", "viewer", "4k", "hdr", "drm", "streaming video")):
            issues.append(_issue("critical", "unsupported_video", "Video streaming capability appeared without media/video terms."))
        if "financial_market_compliance" in understanding.capabilities and not any(term in lower for term in ("trading", "derivatives", "exchange", "mifid", "sec", "finra", "mas", "solvency")):
            issues.append(_issue("critical", "unsupported_financial_compliance", "Financial-market compliance appeared without finance/trading context."))
        if any(term in lower for term in ("sub-second", "microsecond", "seconds", "minutes", "latency")) and not understanding.latency_constraints:
            issues.append(_issue("critical", "latency_not_extracted", "Latency text exists but no latency constraint was extracted."))
        if any(term in lower for term in ("dispatch", "pre-position", "submit bid", "rollout", "ground stop", "block")) and not understanding.action_flows:
            issues.append(_issue("warning", "actions_not_extracted", "Action verbs exist but no action flow was extracted."))
        selected = set(understanding.workload_families)
        excluded = set(understanding.excluded_patterns)
        conflicts = sorted(selected & excluded)
        if conflicts:
            issues.append(_issue("critical", "excluded_pattern_selected", f"Excluded patterns also selected: {', '.join(conflicts)}."))
        return UnderstandingValidationResult(passed=not any(issue.severity == "critical" for issue in issues), issues=issues)


def _issue(severity: str, code: str, message: str) -> UnderstandingValidationIssue:
    return UnderstandingValidationIssue(severity=severity, code=code, message=message)
