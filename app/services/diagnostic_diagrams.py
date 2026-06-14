from __future__ import annotations

from typing import Any

from app.models.domain import ArchitectureSpec, ArchitectureValidationIssue, DiagramArtifact, DiagramGalleryResult, DiagramQAReport
from app.services.artifacts import ArtifactStore


def diagnostic_diagram_gallery(
    *,
    session_id: str,
    specs: list[ArchitectureSpec],
    issues: list[ArchitectureValidationIssue],
    reason: str = "Architecture validation blockers require candidate-only diagram treatment.",
) -> list[DiagramGalleryResult]:
    artifacts = ArtifactStore()
    galleries: list[DiagramGalleryResult] = []
    for spec in specs:
        issue_rows = [
            f"- {issue.severity}: {issue.code} - {issue.message}"
            for issue in issues
            if issue.mode in {None, spec.mode}
        ]
        body = "\n".join([
            f"# {spec.mode.upper()} Candidate Diagram",
            "",
            "This is a diagnostic/candidate diagram artifact. It preserves the architecture journey without pretending the design is customer-ready.",
            "",
            f"Reason: {reason}",
            "",
            "## Candidate Architecture",
            "",
            spec.summary or "No architecture summary was available.",
            "",
            "## Validation Issues",
            "",
            *(issue_rows or ["- No validation issue details were available."]),
            "",
            "## Repair Path",
            "",
            "- Resolve the validation issues above.",
            "- Regenerate architecture and diagrams.",
            "- Keep pricing headline suppressed until driver bindings match canonical facts.",
            "",
        ])
        path = artifacts.write_text(session_id, "diagrams", f"diagnostic/{spec.mode}/candidate_diagram.md", body)
        artifact_id = artifacts.to_artifact_id(session_id, path)
        diagram = DiagramArtifact(
            id=f"{spec.mode}_diagnostic_candidate",
            title=f"{spec.mode.upper()} diagnostic candidate diagram",
            mode=spec.mode,
            view_id="diagnostic_candidate",
            compiler_view_id="diagnostic_candidate",
            semantic_view_id="diagnostic_candidate",
            user_description="Diagnostic candidate diagram generated because validation issues would otherwise create a dead end.",
            rendered_as_native_view=False,
            fallback_reason=reason,
            format_paths={"md": artifact_id},
        )
        galleries.append(DiagramGalleryResult(
            session_id=session_id,
            architecture_spec_id=spec.id,
            mode=spec.mode,
            diagrams=[diagram],
            qa_reports=[
                DiagramQAReport(
                    view_id="diagnostic_candidate",
                    passed=False,
                    diagnostics=[
                        {
                            "severity": "warning",
                            "code": "diagnostic_candidate_diagram",
                            "message": reason,
                            "validation_issues": [_issue_payload(issue) for issue in issues if issue.mode in {None, spec.mode}],
                        }
                    ],
                    metrics={"diagnostic": True, "candidate_only": True},
                )
            ],
            rendered_view_ids=["diagnostic_candidate"],
            missing_requested_views=[],
            view_rendering_ledger={
                "rendered_explicitly": [],
                "rendered_via_broader_supported_view": [],
                "omitted_with_reason": [],
                "unsupported_not_rendered": [],
                "diagnostic_candidate": [{"mode": spec.mode, "reason": reason}],
            },
        ))
    return galleries


def _issue_payload(issue: ArchitectureValidationIssue) -> dict[str, Any]:
    return issue.model_dump(mode="json") if hasattr(issue, "model_dump") else dict(issue)
