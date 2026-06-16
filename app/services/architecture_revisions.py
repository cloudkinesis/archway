from __future__ import annotations

from app.models.domain import (
    ArchitectureRevision,
    ArchitectureSpec,
    ArchitectureValidationIssue,
    ObservabilityControl,
    SecurityControl,
)
from app.models.schemas import ArchitectureSpecPatch
from app.services.artifacts import ArtifactStore
from app.services.governance_controls import GovernanceControlEnricher, unresolved_effectful_flow_ids


class ArchitectureRevisionService:
    def __init__(self):
        self.artifacts = ArtifactStore()
        self.governance = GovernanceControlEnricher()

    def initialize(self, session_id: str, specs: list[ArchitectureSpec], reason: str = "Generated architecture specs") -> ArchitectureRevision:
        """Idempotent first-time setup: create revision 1 only if none exists.

        If a revision already exists this returns the latest one unchanged. Use
        ``record_generation`` for the architecture-generation flow, which must
        always append a new revision.
        """
        revisions = self.list(session_id)
        if revisions:
            return revisions[-1]
        return self._append(session_id, specs, reason)

    def record_generation(self, session_id: str, specs: list[ArchitectureSpec], reason: str = "Generated architecture revision") -> ArchitectureRevision:
        """Persist freshly generated specs as a NEW revision (always appends).

        Each call to ``/architecture/generate`` is an explicit user action, so the
        newly generated specs must become a new, active revision rather than being
        discarded when a prior revision exists (the previous ``initialize`` bug).
        Earlier revisions remain accessible via ``list``; ``active_specs`` returns
        this newest revision so diagrams compile from current specs.
        """
        return self._append(session_id, specs, reason)

    def list(self, session_id: str) -> list[ArchitectureRevision]:
        payload = _read_json_artifact(self.artifacts, session_id, "architecture/revisions.json") or []
        return [ArchitectureRevision.model_validate(item) for item in payload]

    def active_specs(self, session_id: str) -> list[ArchitectureSpec] | None:
        revisions = self.list(session_id)
        if revisions:
            return revisions[-1].specs
        payload = _read_json_artifact(self.artifacts, session_id, "architecture/specs.json")
        return [ArchitectureSpec.model_validate(item) for item in payload] if payload else None

    def update(self, session_id: str, patches: dict[str, ArchitectureSpecPatch], reason: str) -> ArchitectureRevision:
        current = self.active_specs(session_id)
        if current is None:
            raise ValueError("Architecture specs are not ready yet.")
        updated = [self._patch_spec(spec, patches.get(spec.mode)) for spec in current]
        return self._append(session_id, updated, reason)

    def ensure_governance(self, session_id: str, reason: str = "Auto-enriched action governance controls") -> ArchitectureRevision | None:
        current = self.active_specs(session_id)
        if current is None:
            return None
        enriched = self.governance.enrich_specs(current)
        if [spec.model_dump(mode="json") for spec in enriched] == [spec.model_dump(mode="json") for spec in current]:
            revisions = self.list(session_id)
            return revisions[-1] if revisions else None
        return self._append(session_id, enriched, reason)

    def duplicate_active_revision(self, session_id: str, reason: str = "Duplicated active architecture revision") -> ArchitectureRevision:
        """Append a duplicate of the active revision. This is a COPY, not a
        re-derivation: it deep-copies the current active specs and records them
        as a new revision tagged ``duplicated_from_active``. It does not re-run
        the planner, critique, or repair. To re-derive architecture from research,
        call ``/architecture/generate`` again (which appends a fresh revision).
        """
        current = self.active_specs(session_id)
        if current is None:
            raise ValueError("Architecture specs are not ready yet.")
        duplicated = [spec.model_copy(deep=True) for spec in current]
        for spec in duplicated:
            spec.metadata = {**spec.metadata, "duplicated_from_active": True}
        return self._append(session_id, duplicated, reason)

    def regenerate_from_active(self, session_id: str, reason: str = "Duplicated active architecture revision") -> ArchitectureRevision:
        """Deprecated alias for ``duplicate_active_revision`` (kept for compatibility).

        The historical name was misleading: this only duplicates the active
        revision, it does not regenerate from research.
        """
        return self.duplicate_active_revision(session_id, reason)

    def validate(self, specs: list[ArchitectureSpec]) -> list[ArchitectureValidationIssue]:
        issues: list[ArchitectureValidationIssue] = []
        for spec in specs:
            security_names = " ".join(item.name.lower() for item in spec.security_controls)
            observability_names = " ".join(item.name.lower() for item in spec.observability_controls)
            if not spec.security_controls:
                issues.append(ArchitectureValidationIssue(severity="critical", code="missing_security_controls", message="Architecture has no security controls.", mode=spec.mode))
            if "encrypt" not in security_names and "kms" not in security_names:
                issues.append(ArchitectureValidationIssue(severity="important", code="encryption_not_explicit", message="Encryption/KMS is not explicit in security controls.", mode=spec.mode))
            if not spec.observability_controls or ("log" not in observability_names and "cloudwatch" not in observability_names):
                issues.append(ArchitectureValidationIssue(severity="important", code="observability_not_explicit", message="Logging/observability is not explicit.", mode=spec.mode))
            if any(service.selected and not service.evidence_ids for service in spec.selected_services if hasattr(service, "evidence_ids")):
                issues.append(ArchitectureValidationIssue(severity="optional", code="service_evidence_missing", message="Some selected services do not carry evidence IDs.", mode=spec.mode))
            unresolved_governance = unresolved_effectful_flow_ids(spec)
            if unresolved_governance:
                issues.append(
                    ArchitectureValidationIssue(
                        severity="critical",
                        code="write_without_governance",
                        message=f"Effectful flows need linked typed governance controls: {', '.join(unresolved_governance)}.",
                        mode=spec.mode,
                    )
                )
            critique = spec.metadata.get("architecture_critique") or {}
            for finding in critique.get("findings") or []:
                if not isinstance(finding, dict) or finding.get("severity") != "critical":
                    continue
                category = finding.get("category")
                if category == "pricing_driver_mismatch":
                    issues.append(ArchitectureValidationIssue(severity="important", code="pricing_driver_mismatch", message=finding.get("issue") or "Pricing driver mismatch remains unresolved.", mode=spec.mode))
                    continue
                issues.append(
                    ArchitectureValidationIssue(
                        severity="critical",
                        code=f"critical_critique_{category or 'architecture'}",
                        message=finding.get("issue") or "Critical architecture critique finding remains unresolved.",
                        mode=spec.mode,
                    )
                )
            excluded = set(spec.metadata.get("excluded_families") or [])
            text_blob = " ".join([
                spec.title.lower(),
                " ".join(service.service.lower() for service in spec.selected_services),
                " ".join(service.purpose.lower() for service in spec.selected_services),
                " ".join(service.rationale.lower() for service in spec.selected_services),
                " ".join(component.name.lower() for component in spec.components),
                " ".join(component.service.lower() for component in spec.components),
                " ".join(str(flow.metadata.get("classification", "")).lower() for flow in spec.flows),
            ])
            if "rag_assistant" in excluded:
                if any(term in text_blob for term in ("knowledge retrieval", "rag_", "rag assistant", "embedding", "vector search")):
                    issues.append(ArchitectureValidationIssue(severity="critical", code="excluded_workload_family_present", message="RAG assistant components appeared even though the extracted workload excluded that family.", mode=spec.mode))
            if "document_intelligence" in excluded:
                if any(term in text_blob for term in ("document", "contract", "ocr", "textract", "pdf ingestion", "extraction workflow")):
                    issues.append(ArchitectureValidationIssue(severity="critical", code="excluded_workload_family_present", message="Document-intelligence components appeared even though the extracted workload excluded that family.", mode=spec.mode))
            if "field_service_automation" in excluded:
                if any(term in text_blob for term in ("field service", "technician", "crew dispatch", "depot", "work order", "workforce", "spare parts")):
                    issues.append(ArchitectureValidationIssue(severity="critical", code="excluded_workload_family_present", message="Field-service/depot automation components appeared even though the extracted workload excluded that family.", mode=spec.mode))
            requirement_coverage = spec.metadata.get("requirement_coverage") or {}
            for requirement in requirement_coverage.get("requirements") or []:
                if not isinstance(requirement, dict):
                    continue
                if requirement.get("status") == "unmet":
                    issues.append(ArchitectureValidationIssue(severity="important", code="requirement_not_covered", message=str(requirement.get("message") or "A hard requirement is not covered by the active architecture."), mode=spec.mode))
        return issues

    def _append(self, session_id: str, specs: list[ArchitectureSpec], reason: str) -> ArchitectureRevision:
        revisions = self.list(session_id)
        specs = self.governance.enrich_specs(specs)
        revision = ArchitectureRevision(
            session_id=session_id,
            version=len(revisions) + 1,
            reason=reason,
            specs=specs,
            validation_issues=self.validate(specs),
        )
        revisions.append(revision)
        self.artifacts.write_json(session_id, "architecture", "revisions", [item.model_dump(mode="json") for item in revisions])
        self.artifacts.write_json(session_id, "architecture", "specs", [spec.model_dump(mode="json") for spec in specs])
        return revision

    def _patch_spec(self, spec: ArchitectureSpec, patch: ArchitectureSpecPatch | None) -> ArchitectureSpec:
        if patch is None:
            return spec
        updated = spec.model_copy(deep=True)
        for field in ("summary", "scaling_strategy", "resilience_strategy", "cost_optimization_strategy"):
            value = getattr(patch, field)
            if value is not None:
                setattr(updated, field, value)
        if patch.security_controls is not None:
            updated.security_controls = [
                SecurityControl(name=item.get("name", "").strip(), rationale=item.get("rationale", "").strip())
                for item in patch.security_controls
                if item.get("name", "").strip()
            ]
        if patch.observability_controls is not None:
            updated.observability_controls = [
                ObservabilityControl(name=item.get("name", "").strip(), rationale=item.get("rationale", "").strip())
                for item in patch.observability_controls
                if item.get("name", "").strip()
            ]
        updated.metadata = {**updated.metadata, "user_edited": True}
        return updated


def _read_json_artifact(artifacts: ArtifactStore, session_id: str, artifact_id: str):
    try:
        return __import__("json").loads(artifacts.resolve(session_id, artifact_id).read_text(encoding="utf-8"))
    except Exception:
        return None
