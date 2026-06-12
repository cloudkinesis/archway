from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile
import asyncio
import copy
import json
import threading

from app.core.config import get_settings
from app.core.logging import AuditLogger, hash_payload, read_session_audit
from app.db.session_store import SessionStore
from app.models.domain import ExportBundle
from app.services.artifacts import ArtifactStore
from app.services.build_status import BuildStatusService
from app.services.convergence.golden_convergence_orchestrator import GoldenConvergenceOrchestrator, quality_summary_markdown
from app.services.deep_dossier import DeepDossierService
from app.services.dossier_manifest import MANIFEST_FILENAME, build_dossier_manifest, manifest_markdown
from app.services.golden_regression import GoldenRegressionExportService
from app.services.jobs import job_manager
from app.services.llm.telemetry import llm_telemetry_store
from app.services.mcp_security import mcp_security_status
from app.services.sku_pricing.export_trace import build_pilot_trace_files, pilot_trace_hash
from app.services.sku_pricing.official_snapshot_builder import UNSUPPORTED_OFFICIAL_DIMENSIONS


class ExportPackageService:
    def __init__(self):
        self.artifacts = ArtifactStore()
        self.sessions = SessionStore()

    def generate(self, session_id: str, progress: Callable[[int, str], None] | None = None) -> ExportBundle:
        progress = progress or (lambda _progress, _message: None)
        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError("Session was not found.")
        progress(10, "Collecting session artifacts.")
        root = self.artifacts.ensure_layout(session_id)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        export_name = f"archway-solution-package-{session_id}-{stamp}"
        export_dir = root / "exports" / export_name
        export_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []

        progress(18, "Collecting quality and repair summary.")
        convergence_result, convergence_status, convergence_reason = _collect_async(
            lambda: GoldenConvergenceOrchestrator().run(session_id, session.initial_use_case, [], "deep_dossier"),
            "golden convergence",
            warnings,
        )

        progress(26, "Collecting research, architecture, pricing, and diagram outputs.")
        brief = _read_known_json(root, "brief/current.json", warnings)
        report = _read_known_json(root, "research/report.json", warnings)
        pricing = _read_known_json(root, "pricing/estimate.json", warnings)
        architectures = _read_known_json(root, "architecture/specs.json", warnings)
        architecture_revisions = _read_known_json(root, "architecture/revisions.json", warnings)
        diagrams = _read_known_json(root, "diagrams/gallery.json", warnings)
        audit = read_session_audit(session_id)
        logs = audit.events
        if audit.status in {"degraded", "unreadable"}:
            _warn_once(
                warnings,
                f"Audit log {audit.status}: {audit.malformed_count} malformed / {audit.skipped_count} skipped line(s) were dropped.",
            )
        build_status, build_status_status, build_status_reason = _collect_async(
            lambda: BuildStatusService().status(),
            "build status",
            warnings,
        )
        if build_status is None:
            build_status = {
                "status": build_status_status,
                "computed": False,
                "reason": build_status_reason or "Build status could not be collected during export.",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        golden_regression = GoldenRegressionExportService().export()
        job_telemetry = _job_telemetry(session_id, finalize_export=True, export_result_path=f"exports/{export_name}.zip")
        workflow_status = _workflow_status(session, report)
        diagram_fidelity = _diagram_fidelity(architectures, diagrams)
        report = _report_with_convergence_readiness(report, convergence_result)
        progress(38, "Building narrative research dossier.")
        dossier_service = DeepDossierService()
        deep_dossier = dossier_service.build(
            session_id=session_id,
            brief=brief,
            report=report,
            pricing=pricing,
            architectures=architectures,
            diagrams=diagrams,
        )
        self.artifacts.write_json(session_id, "quality", "dossier_consistency_check", deep_dossier.consistency_check.model_dump(mode="json"))
        for issue in diagram_fidelity.get("missing_requested_views", []):
            _warn_once(
                warnings,
                f"{issue.get('mode')} requested compiler view {issue.get('view_id')} but it was not rendered: {issue.get('reason')}",
            )

        progress(52, "Building markdown artifacts.")
        files: dict[str, str] = {
            "README.md": self._readme(session.name),
            "01-solution-brief.md": self._brief_markdown(brief),
            "02-research-report.md": self._research_markdown(report),
            "02A-executive-summary.md": dossier_service.executive_summary_markdown(deep_dossier),
            "02B-deep-research-dossier.md": dossier_service.full_markdown(deep_dossier),
            "02C-claim-register.md": dossier_service.claim_register_markdown(deep_dossier),
            "02D-evidence-map.md": dossier_service.evidence_map_markdown(deep_dossier, report),
            "02E-consistency-check.md": dossier_service.consistency_markdown(deep_dossier),
            "03-pricing.md": self._pricing_markdown(pricing),
            "04-architecture.md": self._architecture_markdown(architectures, architecture_revisions),
            "05-diagrams.md": self._diagrams_markdown(diagrams),
            "06-evidence-appendix.md": self._evidence_markdown(report),
            "07-diagnostics.md": self._diagnostics_markdown(logs),
            "08-build-status.md": self._build_status_markdown(build_status),
            "09-regression-summary.md": self._regression_markdown(golden_regression),
            "10-quality-and-repair-summary.md": quality_summary_markdown(convergence_result) if convergence_result else "# Quality and Repair Summary\n\nGolden convergence was unavailable at export time.\n",
            "11-pricing-trace.md": self._pricing_trace_markdown(pricing),
            "12-source-policy.md": self._source_policy_markdown(report),
        }
        included_artifacts = []
        for relative_name, content in files.items():
            (export_dir / relative_name).write_text(content, encoding="utf-8")
            included_artifacts.append(f"exports/{export_name}/{relative_name}")

        progress(66, "Writing raw evidence and trace payloads.")
        quality_payloads, quality_artifact_records = self._collect_quality_artifacts(
            session_id, root, convergence_status, convergence_reason,
        )
        quality_artifact_status = {
            "golden_convergence": {"status": convergence_status, "reason": convergence_reason},
            "build_status": {"status": build_status_status, "reason": build_status_reason},
            "customer_readiness": quality_artifact_records["customer_readiness"],
            "quality_findings": quality_artifact_records["quality_findings"],
            "repair_plan": quality_artifact_records["repair_plan"],
            "golden_convergence_result": quality_artifact_records["golden_convergence_result"],
            "diagram_qa": _diagram_qa_status(diagrams),
            "pricing_headline_safety": _pricing_headline_status(pricing),
            "pricing_readiness": _pricing_readiness_status(pricing),
        }
        raw_payloads = {
            "session": session.model_dump(mode="json"),
            "brief": brief,
            "research_report": report,
            "pricing": pricing,
            "architecture_specs": architectures,
            "architecture_revisions": architecture_revisions,
            "diagram_gallery": diagrams,
            "diagnostics": logs,
            "audit_log": audit.to_dict(),
            "mcp_security": mcp_security_status(get_settings()),
            "build_status": build_status,
            "golden_regression_summary": golden_regression,
            "job_telemetry": job_telemetry,
            "workflow_status": workflow_status,
            "diagram_fidelity": diagram_fidelity,
            "deep_research_dossier": deep_dossier.model_dump(mode="json"),
            "research_claims": [claim.model_dump(mode="json") for claim in deep_dossier.claims],
            "evidence_items": report.get("evidence_items", []) if report else [],
            "claim_evidence_map": _claim_evidence_map(deep_dossier.model_dump(mode="json"), report),
            "dossier_consistency_check": deep_dossier.consistency_check.model_dump(mode="json"),
            "dossier_quality_score": deep_dossier.quality_score.model_dump(mode="json"),
            "llm_call_telemetry": [item.model_dump(mode="json") for item in llm_telemetry_store.list(session_id)],
            "deep_use_case_understanding": _report_metadata(report, "deep_understanding"),
            "understanding_validation": _report_metadata(report, "understanding_validation"),
            "understanding_conflicts": _report_metadata(report, "understanding_conflicts"),
            "pricing_sanity_review": _report_metadata(report, "pricing_sanity_review"),
            "pricing_driver_closure": _pricing_metadata(pricing, "pricing_driver_closure") or _read_known_json(root, "pricing/pricing_driver_closure.json", warnings),
            "canonical_facts": _pricing_metadata(pricing, "canonical_facts"),
            "assumption_ledger": _pricing_metadata(pricing, "assumption_ledger"),
            "pricing_driver_bindings": _pricing_metadata(pricing, "pricing_driver_bindings"),
            "service_usage_dimensions": _pricing_metadata(pricing, "service_usage_dimensions"),
            "aws_rate_bindings": _pricing_metadata(pricing, "aws_rate_bindings"),
            "pricing_ledger": _pricing_metadata(pricing, "pricing_ledger"),
            "readiness_report": quality_payloads["customer_readiness"],
            "source_policy": _source_policy_payload(report),
            "architecture_critiques": _architecture_critiques(architectures),
            "golden_convergence_result": convergence_result.model_dump(mode="json") if convergence_result else quality_payloads["golden_convergence_result"],
            "quality_findings": quality_payloads["quality_findings"],
            "repair_plan": quality_payloads["repair_plan"],
            "customer_readiness": quality_payloads["customer_readiness"],
            "quality_artifact_status": quality_artifact_status,
        }
        raw_dir = export_dir / "raw"
        raw_dir.mkdir(exist_ok=True)
        for name, payload in raw_payloads.items():
            raw_path = raw_dir / f"{name}.json"
            raw_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            included_artifacts.append(f"exports/{export_name}/raw/{name}.json")

        progress(78, "Collecting diagram downloads.")
        self._copy_diagram_downloads(root, export_dir, diagrams, included_artifacts, warnings)

        manifest = {
            "name": export_name,
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "included_artifacts": included_artifacts,
            "warnings": warnings,
            "quality_artifact_status": quality_artifact_status,
            "inputs_hash": hash_payload(raw_payloads),
        }
        manifest_path = export_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        included_artifacts.append(f"exports/{export_name}/manifest.json")

        progress(84, "Building verifiable dossier manifest.")
        self._write_dossier_layer(
            export_dir, export_name, session, brief, report, pricing,
            architectures, architecture_revisions, diagrams, convergence_result,
            warnings, included_artifacts,
        )

        progress(88, "Building ZIP package.")
        zip_path = root / "exports" / f"{export_name}.zip"
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
            for path in sorted(export_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=str(path.relative_to(export_dir)))

        artifact_id = self.artifacts.to_artifact_id(session_id, zip_path)
        manifest_artifact_id = self.artifacts.to_artifact_id(session_id, manifest_path)
        AuditLogger(session_id).event(
            "export",
            "solution_package_generated",
            output_hash=hash_payload(manifest),
            artifact_id=artifact_id,
        )
        return ExportBundle(
            session_id=session_id,
            name=export_name,
            artifact_id=artifact_id,
            manifest_artifact_id=manifest_artifact_id,
            included_artifacts=included_artifacts,
            warnings=warnings,
        )

    def _collect_quality_artifacts(self, session_id: str, root: Path, convergence_status: str, convergence_reason: str | None):
        """Collect quality artifacts without emitting raw "missing optional" warnings.

        For each quality artifact: if present, use it; otherwise write a deterministic
        placeholder (status: present/skipped/deferred/not_applicable/failed) into the
        session quality dir so the export carries an explicit, honest record instead of
        a bare missing-artifact warning. Customer readiness fails closed when absent.
        """
        specs = {
            "golden_convergence_result": "quality/golden_convergence_result.json",
            "quality_findings": "quality/quality_findings.json",
            "repair_plan": "quality/repair_plan.json",
            "customer_readiness": "quality/customer_readiness.json",
        }
        timestamp = datetime.now(timezone.utc).isoformat()
        payloads: dict = {}
        records: dict = {}
        for key, relative in specs.items():
            existing = _read_json_quiet(root, relative)
            if existing is not None:
                payloads[key] = existing
                records[key] = {"status": "present", "artifact": relative}
                continue
            if convergence_status == "failed":
                art_status = "failed"
                reason = convergence_reason or "Golden convergence failed during export."
            elif convergence_status == "present":
                art_status = "not_applicable"
                reason = "Golden convergence completed but did not emit this artifact for this run."
            else:
                art_status = "deferred"
                reason = convergence_reason or "Quality computation was deferred during export."
            if key == "customer_readiness":
                placeholder = {
                    "status": "directional_only",
                    "computed": False,
                    "reason": "Customer readiness was not recomputed during export; using current research/pricing/diagram validation state.",
                    "customer_ready": False,
                    "procurement_ready": False,
                    "quality_artifact_status": art_status,
                    "generated_at": timestamp,
                }
            else:
                placeholder = {
                    "status": art_status,
                    "computed": False,
                    "reason": reason,
                    "recommended_next_action": "Run the convergence/quality pass (or re-run export) to populate this artifact.",
                    "customer_readiness_affected": key in {"golden_convergence_result", "quality_findings"},
                    "generated_at": timestamp,
                }
            self.artifacts.write_json(session_id, "quality", key, placeholder)
            payloads[key] = placeholder
            records[key] = {"status": art_status, "reason": reason, "artifact": relative}
        return payloads, records

    def _readme(self, session_name: str) -> str:
        return "\n".join([
            f"# {session_name}",
            "",
            "This Archway solution package contains the local artifacts generated for the session.",
            "",
            "Sections:",
            "- Solution brief",
            "- Evidence-disciplined research report",
            "- Executive summary",
            "- Deep research dossier",
            "- Claim register, evidence map, and consistency check",
            "- Deterministic pricing estimate",
            "- POC and production architecture specs",
            "- Diagram gallery index and diagram files when available",
            "- Evidence appendix",
            "- Diagnostics summary",
            "",
        ])

    def _write_dossier_layer(
        self, export_dir: Path, export_name: str, session, brief, report, pricing,
        architectures, architecture_revisions, diagrams, convergence_result,
        warnings: list[str], included_artifacts: list[str],
    ) -> None:
        """Write supplemental SKU trace files + the verifiable dossier manifest.

        Purely additive. Never changes legacy totals or global readiness; the SKU
        trace files appear only when SKU pilot metadata is present.
        """
        settings = get_settings()
        pilot = ((pricing or {}).get("metadata") or {}).get("sku_pricing_pilot")
        sku_trace_hash = None
        if pilot:
            pricing_dir = export_dir / "pricing"
            pricing_dir.mkdir(exist_ok=True)
            trace_files = build_pilot_trace_files(pilot)
            for name, key in (
                ("sku_pricing_pilot_trace.json", "json"),
                ("sku_pricing_pilot_trace.csv", "csv"),
                ("sku_pricing_pilot_summary.md", "md"),
            ):
                (pricing_dir / name).write_text(trace_files[key], encoding="utf-8")
                included_artifacts.append(f"exports/{export_name}/pricing/{name}")
            sku_trace_hash = pilot_trace_hash(pilot)

        (export_dir / "README_DOSSIER.md").write_text(self._readme_dossier(), encoding="utf-8")
        included_artifacts.append(f"exports/{export_name}/README_DOSSIER.md")

        feature_flags = {
            "enable_sku_pricing_pilot": settings.enable_sku_pricing_pilot,
            "sku_pricing_snapshot_configured": bool(settings.sku_pricing_snapshot_path),
            "llm_provider": settings.llm_provider,
        }
        dossier = build_dossier_manifest(
            export_dir,
            session_id=session.id,
            export_name=export_name,
            generated_at=datetime.now(timezone.utc).isoformat(),
            session_input=getattr(session, "initial_use_case", None),
            brief=brief,
            report=report,
            pricing=pricing,
            architectures=architectures,
            architecture_revisions=architecture_revisions,
            diagrams=diagrams,
            warnings=warnings,
            feature_flags=feature_flags,
            convergence_status=getattr(convergence_result, "final_status", None),
            sku_trace_hash=sku_trace_hash,
            unsupported_dimensions=dict(UNSUPPORTED_OFFICIAL_DIMENSIONS),
        )
        (export_dir / MANIFEST_FILENAME).write_text(
            json.dumps(dossier, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        (export_dir / "dossier_manifest.md").write_text(manifest_markdown(dossier), encoding="utf-8")
        included_artifacts.append(f"exports/{export_name}/{MANIFEST_FILENAME}")
        included_artifacts.append(f"exports/{export_name}/dossier_manifest.md")

    def _readme_dossier(self) -> str:
        return "\n".join([
            "# Verifiable Solution Dossier",
            "",
            "This package ships a `dossier_manifest.json` — the trust spine of the export.",
            "It records, for this solution, what is verified, what is directional, what is",
            "missing, what failed closed, what can be reproduced, and what is NOT",
            "procurement-ready.",
            "",
            "## How to verify this package",
            "```",
            "python scripts/verify_solution_dossier.py /path/to/this/export",
            "```",
            "The verifier recomputes every artifact hash in the manifest inventory and checks",
            "required artifacts exist. It performs NO network calls and NO regeneration.",
            "",
            "## What SKU-backed pilot pricing means",
            "When present, `pricing/sku_pricing_pilot_*` is a SUPPLEMENTAL SKU-backed trace",
            "for a narrow service set. It does NOT replace the legacy estimate and does NOT",
            "change global headline/procurement readiness.",
            "",
            "## Why rate authority and quantity confirmation are separate",
            "- `rate_authoritative` means the rate was bound to an official-source-backed",
            "  snapshot. Fixture-backed rates are never authoritative.",
            "- `quantities_confirmed` means the workload quantities were explicitly confirmed.",
            "- Procurement-ready requires BOTH. Authoritative rates with assumed quantities are",
            "  NOT procurement-ready.",
            "",
            "## Why EventBridge may be 'not estimated'",
            "AWS bills EventBridge custom events per 64KB chunk, not per raw event. Until a",
            "chunk-quantity model exists, EventBridge fails closed rather than guessing.",
            "",
            "## Terms",
            "- Directional: indicative only; not a procurement quote.",
            "- Procurement-ready: bound to authoritative rates AND confirmed quantities, with",
            "  every required line bound and no ambiguity. Global procurement-ready is not",
            "  promoted by the SKU pilot.",
            "",
        ])

    def _brief_markdown(self, brief) -> str:
        if not brief:
            return "# Solution Brief\n\nNo solution brief was available at export time.\n"
        return "\n".join([
            "# Solution Brief",
            "",
            f"## {brief.get('title', 'Untitled')}",
            "",
            brief.get("refined_problem_statement", ""),
            "",
            f"- Industry: {brief.get('industry') or 'Worth confirming'}",
            f"- POC scope: {brief.get('poc_scope', '')}",
            f"- Production scope: {brief.get('production_scope', '')}",
            "",
            "## Assumptions",
            *[f"- {item.get('text')} ({item.get('impact')}, {item.get('confidence')})" for item in brief.get("assumptions", [])],
            "",
            "## Open Questions",
            *[f"- {item.get('text')}" for item in brief.get("open_questions", [])],
            "",
        ])

    def _research_markdown(self, report) -> str:
        if not report:
            return "# Research Report\n\nNo research report was available at export time.\n"
        coverage = report.get("citation_coverage") or {}
        metadata = report.get("metadata") or {}
        research_quality = metadata.get("research_quality") or {}
        evidence_quality = metadata.get("evidence_quality") or {}
        customer_readiness = metadata.get("customer_readiness") or {}
        lines = [
            "# Research Report",
            "",
            f"Executive verdict: {report.get('executive_verdict', '')}",
            "",
            f"Research quality: {research_quality.get('label', 'Unknown')}",
            "",
            research_quality.get("reason", ""),
            "",
            f"Citation coverage: {coverage.get('coverage_percent', 0)}%",
            f"Evidence authority: {str(evidence_quality.get('evidence_authority', 'unknown')).title()}",
            f"Customer readiness: {str(customer_readiness.get('status', 'unknown')).replace('_', ' ').title()}",
            "",
            *[f"- Blocker: {item}" for item in customer_readiness.get("blockers", [])],
            *[f"- Warning: {item}" for item in customer_readiness.get("warnings", [])],
            "",
            "## Service Validation Notes",
            *[f"- {item}" for item in metadata.get("service_validation_notes", [])],
            "",
            "## Service Decision Records",
            *[
                f"- {item.get('decision_id')}: {item.get('selected_service')} for {item.get('capability')} ({item.get('selection_reason')})"
                for item in metadata.get("service_decision_records", [])
            ],
            "",
            "## Facts",
            *[f"- {claim.get('text')} [{', '.join(claim.get('evidence_ids', []))}]" for claim in report.get("facts", [])],
            "",
            "## Recommendations",
            *[f"- {claim.get('text')} [{', '.join(claim.get('evidence_ids', []))}]" for claim in report.get("recommendations", [])],
            "",
            "## Uncertainty",
            *[f"- {claim.get('text')} ({claim.get('citation_status')})" for claim in report.get("uncertainties", [])],
            "",
            "## Feasibility",
            report.get("feasibility_analysis", ""),
            "",
            "## Viability",
            report.get("viability_analysis", ""),
            "",
            "## Competitor Scan",
            report.get("competitor_analysis", ""),
            "",
        ]
        return "\n".join(lines)

    def _pricing_markdown(self, pricing) -> str:
        if not pricing:
            return "# Pricing\n\nNo pricing estimate was available at export time.\n"
        metadata = pricing.get("metadata") or {}
        closure = metadata.get("pricing_driver_closure") or {}
        # Fail closed: only an explicit True is headline-safe.
        headline_safe = metadata.get("pricing_can_be_displayed_as_headline") is True
        if headline_safe:
            headline_lines = [
                f"Estimated monthly range: ${pricing.get('low_monthly_usd')}-${pricing.get('high_monthly_usd')}",
                f"Expected monthly estimate: ${pricing.get('expected_monthly_usd')}",
            ]
        elif closure.get("directional_scenario_allowed"):
            headline_lines = [
                "Directional scenario estimate, not procurement-ready.",
                f"Estimated monthly range: ${pricing.get('low_monthly_usd')}-${pricing.get('high_monthly_usd')}",
                f"Expected monthly scenario estimate: ${pricing.get('expected_monthly_usd')}",
                "This pricing is scenario-based and not procurement-ready.",
            ]
        else:
            headline_lines = [
                "Headline-safe pricing: No",
                f"Reason: {metadata.get('reason') or metadata.get('headline_display') or 'Pricing sanity review blocked headline display.'}",
                "Directional placeholder only - not headline-safe.",
            ]
        lines = [
            "# Pricing",
            "",
            f"Region: {pricing.get('region')}",
            *headline_lines,
            "",
            "Pricing is directional unless AWS Pricing evidence is present in the evidence appendix.",
            "",
            f"Pricing validity: {metadata.get('status', 'unknown')}",
            f"Pricing maturity: {metadata.get('pricing_maturity', closure.get('pricing_maturity', 'unknown'))}",
            f"Extracted scale applied: {metadata.get('scale_applied', 'unknown')}",
            f"Pricing validity reason: {metadata.get('reason', 'No pricing validation metadata was recorded.')}",
            "",
            "## Pricing Driver Closure",
            f"Closure status: {closure.get('status', 'unknown')}",
            f"Scenario profile used: {closure.get('scenario_profile_used') or 'None'}",
            f"Pricing readiness: {closure.get('pricing_maturity', metadata.get('pricing_maturity', 'unknown'))}",
            f"Procurement readiness: {closure.get('procurement_ready', False)}",
            "",
            "### Confirmed Drivers",
            *[f"- {item}" for item in closure.get("confirmed_drivers", [])],
            "",
            "### Assumed Drivers",
            *[f"- {item}" for item in closure.get("assumed_drivers", [])],
            "",
            "### Missing Drivers",
            *[f"- {item.get('display_name')}: {item.get('why_needed')}" for item in closure.get("missing_drivers", [])],
            "",
            "### Next Validation Steps",
            *[f"- {item}" for item in closure.get("next_validation_steps", [])],
            "",
            "## Pricing Drivers",
            *[f"- {item}" for item in pricing.get("main_cost_drivers", [])],
            "",
            "## Unknown Variables",
            *[f"- {item}" for item in pricing.get("unknown_variables", [])],
            "",
            "## Line Items",
        ]
        lines.extend(
            f"- {item.get('service')}: ${item.get('expected_monthly_usd')} expected; basis: {item.get('unit_basis')}; evidence: {', '.join(item.get('evidence_ids', []))}; trace: {_pricing_trace_summary(item.get('pricing_trace') or {})}"
            for item in pricing.get("line_items", [])
        )
        lines.append("")
        return "\n".join(lines)

    def _pricing_trace_markdown(self, pricing) -> str:
        if not pricing:
            return "# Pricing Trace\n\nNo pricing estimate was available at export time.\n"
        metadata = pricing.get("metadata") or {}
        ledger = metadata.get("pricing_ledger") or {}
        closure = metadata.get("pricing_driver_closure") or {}
        rate_bindings = {
            item.get("id"): item
            for item in metadata.get("aws_rate_bindings", [])
            if item.get("id")
        }
        compiler = metadata.get("source_truth_pricing_compiler") or {}
        summary = ledger.get("summary") or {}
        lines = [
            "# Pricing Trace",
            "",
            f"Source-of-truth compiler enabled: {compiler.get('enabled', False)}",
            f"Workload family: {compiler.get('workload_family', 'legacy_directional')}",
            f"Headline-safe: {summary.get('headline_safe', False)}",
            f"Procurement-ready: {summary.get('procurement_ready', False)}",
            f"Pricing checkpoint status: {closure.get('status', 'unknown')}",
            f"Pricing maturity: {metadata.get('pricing_maturity', closure.get('pricing_maturity', 'unknown'))}",
            f"Scenario profile used: {closure.get('scenario_profile_used') or 'None'}",
            f"SKU/tier-backed subtotal: {summary.get('sku_tier_backed_subtotal', 0)}",
            f"AWS catalog-referenced, not SKU-bound subtotal: {summary.get('pricing_page_or_mcp_backed_subtotal', 0)}",
            f"Heuristic subtotal: {summary.get('heuristic_subtotal', 0)}",
            "",
            "## Confirmed vs Assumed vs Missing Drivers",
            f"- Confirmed: {', '.join(closure.get('confirmed_drivers', []) or []) or 'none'}",
            f"- Assumed: {', '.join(closure.get('assumed_drivers', []) or []) or 'none'}",
            f"- Missing: {', '.join(item.get('driver_name', '') for item in closure.get('missing_drivers', []) if item.get('driver_name')) or 'none'}",
            "",
            "## Ledger Line Items",
        ]
        for item in ledger.get("line_items", []):
            rate = rate_bindings.get(item.get("rate_binding_id")) or {}
            lines.append(
                f"- {item.get('service_name')}: usage={item.get('usage_name')}; quantity={item.get('quantity')} {item.get('quantity_unit')}; "
                f"formula={item.get('formula')}; rate_binding={rate.get('binding_status', 'n/a')}; sku={rate.get('sku') or 'n/a'}; "
                f"usage_type={rate.get('usage_type') or 'n/a'}; unit={rate.get('unit') or 'n/a'}; price_per_unit={rate.get('price_per_unit') or 'n/a'}; "
                f"candidate_rate_used_for_total={'yes' if item.get('evidence_class') == 'sku_tier_backed' else 'no'}; monthly_total={item.get('monthly_total')}; "
                f"evidence={item.get('evidence_class')}; procurement_ready={item.get('procurement_ready')}; "
                f"assumptions={', '.join(item.get('assumptions') or []) or 'none'}; limitations={'; '.join(item.get('limitations') or rate.get('notes') or []) or 'none'}"
            )
        findings = metadata.get("pricing_sanity_findings") or []
        lines.extend(["", "## Pricing Sanity Findings"])
        lines.extend(
            f"- {item.get('severity')}: {item.get('code')} - {item.get('description')}"
            for item in findings
        )
        lines.append("")
        return "\n".join(lines)

    def _source_policy_markdown(self, report) -> str:
        payload = _source_policy_payload(report)
        return "\n".join([
            "# Source Policy",
            "",
            f"AWS documentation source: {payload['aws_documentation']}",
            f"AWS pricing source: {payload['aws_pricing']}",
            f"Competitor web scan: {payload['competitor_web_scan']}",
            "",
            payload["competitor_limitation"],
            "",
        ])

    def _architecture_markdown(self, architectures, revisions=None) -> str:
        if not architectures:
            return "# Architecture\n\nNo architecture specs were available at export time.\n"
        lines = ["# Architecture", ""]
        for spec in architectures:
            metadata = spec.get("metadata") or {}
            semantic_views = metadata.get("semantic_views") or []
            expected_views = metadata.get("expected_views") or []
            view_mapping = metadata.get("semantic_to_compiler_view_mapping") or {}
            lines.extend([
                f"## {spec.get('title')} ({spec.get('mode')})",
                "",
                spec.get("summary", ""),
                "",
                "### Diagram View Contract",
                metadata.get("compiler_view_contract", "Diagram views are generated through the configured Archway compiler."),
                "",
                f"- Semantic views requested: {', '.join(semantic_views) if semantic_views else 'n/a'}",
                f"- Compiler views requested: {', '.join(expected_views) if expected_views else 'n/a'}",
                *[f"- {semantic}: {compiler}" for semantic, compiler in view_mapping.items()],
                f"- Deployment target: {metadata.get('deployment_target', 'aws_only')}",
                f"- Deployment target note: {metadata.get('deployment_target_note', 'Recommendations target AWS-native services; external systems are represented only as integration actors.')}",
                f"- Network view status: {metadata.get('network_private_connectivity_view_status', {})}",
                "",
                "### Security Controls",
                *[f"- {item.get('name')}: {item.get('rationale')}" for item in spec.get("security_controls", [])],
                "",
                "### Action Governance Controls",
                *[
                    (
                        f"- {item.get('name')} [{item.get('control_type')}]: flows={', '.join(item.get('governed_flow_ids', [])) or 'n/a'}; "
                        f"actions={', '.join(item.get('action_types', [])) or 'n/a'}; enforcement_point={item.get('enforcement_point') or 'n/a'}; "
                        f"failure_behavior={item.get('failure_behavior')}; rationale={item.get('rationale')}"
                    )
                    for item in spec.get("governance_controls", [])
                ],
                "",
                "### Observability Controls",
                *[f"- {item.get('name')}: {item.get('rationale')}" for item in spec.get("observability_controls", [])],
                "",
            ])
        if revisions:
            lines.extend(["## Revision History", ""])
            for revision in revisions:
                issues = revision.get("validation_issues", [])
                critical_count = len([item for item in issues if item.get("severity") == "critical"])
                lines.append(f"- Revision {revision.get('version')}: {revision.get('reason')} ({critical_count} critical validation issues)")
            lines.append("")
        return "\n".join(lines)

    def _diagrams_markdown(self, diagrams) -> str:
        if not diagrams:
            return "# Diagrams\n\nNo diagram gallery was available at export time.\n"
        lines = ["# Diagram Gallery", ""]
        for gallery in diagrams:
            lines.append(f"## {gallery.get('mode')}")
            missing = gallery.get("missing_requested_views") or []
            if missing:
                lines.extend(["", "Requested views not rendered:"])
                lines.extend(f"- {item.get('view_id')}: {item.get('reason')}" for item in missing)
                lines.append("")
            ledger = gallery.get("view_rendering_ledger") or {}
            broader = ledger.get("rendered_via_broader_supported_view") or []
            omitted = ledger.get("omitted_with_reason") or []
            if broader:
                lines.extend(["", "Semantic views represented through broader supported views:"])
                lines.extend(
                    f"- {item.get('view_id')}: represented by {item.get('represented_by_view_id') or item.get('compiler_view_id')} - {item.get('reason')}"
                    for item in broader
                )
                lines.append("")
            if omitted:
                lines.extend(["", "Requested views omitted with reason:"])
                lines.extend(f"- {item.get('view_id')}: {item.get('reason')}" for item in omitted)
                lines.append("")
            for diagram in gallery.get("diagrams", []):
                detail = f": {diagram.get('format_paths', {})}"
                if diagram.get("compiler_view_id"):
                    detail += f" Compiler view: {diagram.get('compiler_view_id')}."
                if diagram.get("fallback_reason"):
                    detail += f" Note: {diagram.get('fallback_reason')}"
                lines.append(f"- {diagram.get('title')}{detail}")
            lines.append("")
        return "\n".join(lines)

    def _evidence_markdown(self, report) -> str:
        if not report:
            return "# Evidence Appendix\n\nNo evidence was available at export time.\n"
        lines = ["# Evidence Appendix", ""]
        assessments = {item.get("evidence_id"): item for item in report.get("evidence_assessments", [])}
        for item in report.get("evidence_items", []):
            assessment = assessments.get(item.get("id"), {})
            lines.extend([
                f"## {item.get('id')}: {item.get('title')}",
                "",
                f"- Source: {item.get('source_type')}",
                f"- Authority: {assessment.get('source_type', 'unknown')}",
                f"- Confidence: {item.get('confidence')}",
                f"- Trust: {assessment.get('trust_label', 'unknown')} ({assessment.get('trust_score', 'n/a')})",
                f"- URL: {item.get('url') or 'n/a'}",
                "",
                item.get("quote_or_summary", ""),
                "",
            ])
        return "\n".join(lines)

    def _build_status_markdown(self, status) -> str:
        if not status:
            return "# Build Status\n\nBuild status was unavailable at export time.\n"
        lines = ["# Build Status", "", f"Overall: {status.get('status')}", ""]
        for item in status.get("items", []):
            lines.append(f"- {item.get('label')}: {item.get('status')} - {item.get('reason')}")
        lines.append("")
        return "\n".join(lines)

    def _regression_markdown(self, regression) -> str:
        if not regression:
            return "# Regression Summary\n\nGolden regression summary was unavailable at export time.\n"
        lines = [
            "# Regression Summary",
            "",
            f"- Scenario count: {regression.get('scenario_count')}",
            f"- Unique capability sets: {regression.get('unique_capability_sets')}",
            f"- Unique service sets: {regression.get('unique_service_sets')}",
            "",
            "## Scenarios",
        ]
        for row in regression.get("rows", []):
            lines.append(
                f"- {row.get('name')}: families={', '.join(row.get('workload_families', []))}; services={len(row.get('services', []))}; compiler_views={', '.join(row.get('compiler_views', []))}"
            )
        lines.append("")
        return "\n".join(lines)

    def _diagnostics_markdown(self, logs) -> str:
        lines = ["# Diagnostics", "", f"Audit events: {len(logs)}", ""]
        for item in logs[-50:]:
            lines.append(f"- {item.get('timestamp')} · {item.get('phase')} · {item.get('operation')}")
        lines.append("")
        return "\n".join(lines)

    def _copy_diagram_downloads(self, root: Path, export_dir: Path, diagrams, included: list[str], warnings: list[str]) -> None:
        if not diagrams:
            return
        copied: set[str] = set()
        for gallery in diagrams:
            for diagram in gallery.get("diagrams", []):
                view_id = _safe_name(diagram.get("view_id", "diagram"))
                for fmt, artifact_id in (diagram.get("format_paths") or {}).items():
                    self._copy_artifact_preserving_path(root, export_dir, artifact_id, included, warnings, f"{view_id}.{fmt}", copied)
                placement = diagram.get("placement_explanation_artifact_id")
                if placement:
                    self._copy_artifact_preserving_path(root, export_dir, placement, included, warnings, f"{view_id}.placement", copied)
            for qa in gallery.get("qa_reports", []):
                if not qa.get("passed", False):
                    warnings.append(f"Diagram QA did not pass for {gallery.get('mode', 'unknown')} {qa.get('view_id', 'unknown')}.")

    def _copy_artifact_preserving_path(
        self,
        root: Path,
        export_dir: Path,
        artifact_id: str | None,
        included: list[str],
        warnings: list[str],
        label: str,
        copied: set[str],
    ) -> None:
        if not artifact_id:
            return
        relative = Path(str(artifact_id))
        if relative.is_absolute() or ".." in relative.parts:
            warnings.append(f"Skipped unsafe diagram artifact path for {label}")
            return
        source = (root / relative).resolve()
        if not source.is_file() or root not in source.parents:
            warnings.append(f"Skipped missing diagram artifact {artifact_id}")
            return
        dest = export_dir / relative
        key = str(dest)
        if key in copied:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        included.append(str(dest.relative_to(root)))
        copied.add(key)


def _read_known_json(root: Path, relative: str, warnings: list[str]):
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        _warn_once(warnings, f"Missing optional artifact: {relative}")
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _report_with_convergence_readiness(report, convergence_result):
    if not report or not convergence_result:
        return report
    adjusted = copy.deepcopy(report)
    metadata = adjusted.setdefault("metadata", {})
    current = metadata.get("customer_readiness") or {}
    metadata["customer_readiness"] = {
        **current,
        "status": convergence_result.final_status,
        "source": "golden_convergence",
        "reason": "Export dossier readiness is aligned to the final golden convergence status.",
    }
    return adjusted


def _safe_name(value: str) -> str:
    clean = "".join(char if char.isalnum() or char in "-_." else "-" for char in str(value).lower())
    return clean.strip(".-") or "artifact"


def _await_or_none(coro, warnings: list[str], label: str):
    """Legacy degrade helper (kept for compatibility).

    Prefer ``_collect_async`` in the export path, which runs the collector safely
    even when a loop is already running. This helper still defers inside a loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        coro.close()
        _warn_once(warnings, f"Deferred {label}: exporter is already running inside an event loop.")
        return None
    try:
        return asyncio.run(coro)
    except Exception as exc:
        _warn_once(warnings, f"Could not collect {label}: {type(exc).__name__}")
        return None


def _run_coro_blocking(factory):
    """Run an async coroutine to completion from sync code, loop-safe.

    If no event loop is running, use ``asyncio.run``. If a loop is already running
    on this thread, offload to a dedicated worker thread (which has no running loop)
    and run ``asyncio.run`` there. This avoids nested-loop hacks and never calls an
    unsafe ``run``/``run_until_complete`` on the already-running loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    result: dict = {}
    error: dict = {}

    def _runner():
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread
            error["error"] = exc

    thread = threading.Thread(target=_runner, name="archway-export-async", daemon=True)
    thread.start()
    thread.join()
    if "error" in error:
        raise error["error"]
    return result.get("value")


def _collect_async(factory, label: str, warnings: list[str]):
    """Collect an async result loop-safely. Returns (result, status, reason).

    status is "present" on success or "failed" on exception. A single, exact
    warning is recorded on failure (deduplicated); no vague event-loop warning is
    produced because the collector runs regardless of execution context.
    """
    try:
        return _run_coro_blocking(factory), "present", None
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {exc}"[:300]
        _warn_once(warnings, f"Could not collect {label}: {reason}")
        return None, "failed", reason


def _read_json_quiet(root: Path, relative: str):
    path = (root / relative).resolve()
    if root in path.parents and path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _diagram_qa_status(diagrams) -> dict:
    if not diagrams:
        return {"status": "not_applicable", "reason": "No diagram gallery was available at export time."}
    qa_reports = [qa for gallery in diagrams for qa in (gallery.get("qa_reports") or [])]
    if not qa_reports:
        return {"status": "not_applicable", "reason": "No diagram QA reports were present."}
    return {"status": "present", "passed": all(qa.get("passed", False) for qa in qa_reports)}


def _pricing_headline_status(pricing) -> dict:
    if not pricing:
        return {"status": "not_applicable", "reason": "No pricing estimate was available at export time."}
    metadata = pricing.get("metadata") or {}
    return {"status": "present", "headline_safe": bool(metadata.get("pricing_can_be_displayed_as_headline", False))}


def _pricing_readiness_status(pricing) -> dict:
    if not pricing:
        return {"status": "not_applicable", "reason": "No pricing estimate was available at export time."}
    metadata = pricing.get("metadata") or {}
    ledger_summary = (metadata.get("pricing_ledger") or {}).get("summary") or {}
    return {
        "status": "present",
        "pricing_maturity": metadata.get("pricing_maturity"),
        "procurement_ready": bool(ledger_summary.get("procurement_ready", False)),
    }


def _job_telemetry(session_id: str, *, finalize_export: bool = False, export_result_path: str | None = None) -> dict:
    operations = ("research", "architecture", "diagrams", "export")
    jobs = []
    for operation in operations:
        job = job_manager.latest_for_session(session_id, operation)
        if not job:
            continue
        status = job.status
        completed_at = job.completed_at
        message = job.message
        result_path = job.result_path
        status_value = getattr(status, "value", status)
        if finalize_export and operation == "export" and status_value == "running":
            status = "succeeded"
            completed_at = datetime.now(timezone.utc)
            message = "Complete. Export package finalized."
            result_path = export_result_path or result_path
        jobs.append(
            {
                "phase": operation,
                "status": status,
                "started_at": job.started_at,
                "completed_at": completed_at,
                "duration_ms": round((job.duration_seconds or 0) * 1000, 3) if job.duration_seconds is not None else None,
                "message": message,
                "result_path": result_path,
                "error": job.error,
            }
        )
    return {"jobs": jobs}


def _workflow_status(session, report) -> dict:
    readiness = ((report or {}).get("metadata") or {}).get("customer_readiness") or {}
    return {
        "workflow_status": "export_complete",
        "session_status": session.status,
        "active_phase": session.active_phase,
        "customer_readiness": readiness.get("status", "unknown"),
        "customer_ready": readiness.get("status") == "customer_ready",
        "readiness_warnings": readiness.get("warnings", []),
        "readiness_blockers": readiness.get("blockers", []),
    }


def _diagram_fidelity(architectures, diagrams) -> dict:
    specs = architectures or []
    galleries = {gallery.get("mode"): gallery for gallery in (diagrams or [])}
    missing = []
    rendered = {}
    ledgers = {}
    for spec in specs:
        mode = spec.get("mode")
        expected = set(((spec.get("metadata") or {}).get("expected_views") or []))
        gallery = galleries.get(mode) or {}
        rendered_ids = {
            diagram.get("compiler_view_id") or diagram.get("view_id")
            for diagram in gallery.get("diagrams", [])
        }
        rendered[mode] = sorted(item for item in rendered_ids if item)
        ledger = gallery.get("view_rendering_ledger") if isinstance(gallery, dict) else None
        if ledger:
            ledgers[mode] = ledger
            for item in ledger.get("unsupported_not_rendered", []):
                missing.append({**item, "mode": item.get("mode") or mode})
        else:
            for view_id in sorted(expected - rendered_ids):
                missing.append(
                    {
                        "mode": mode,
                        "view_id": view_id,
                        "reason": _missing_view_reason(view_id, gallery),
                    }
                )
        if isinstance(gallery, dict):
            gallery["rendered_view_ids"] = rendered[mode]
            gallery["missing_requested_views"] = [item for item in missing if item.get("mode") == mode]
            if ledger:
                gallery["view_rendering_ledger"] = ledger
    return {"rendered_view_ids_by_mode": rendered, "missing_requested_views": missing, "view_rendering_ledger_by_mode": ledgers}


def _warn_once(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def _missing_view_reason(view_id: str, gallery) -> str:
    qa_reports = (gallery or {}).get("qa_reports") or []
    diagnostics = []
    for qa in qa_reports:
        diagnostics.extend(qa.get("diagnostics") or [])
    for diagnostic in diagnostics:
        message = str(diagnostic.get("message") or "")
        if view_id in message:
            return message
    return "The existing D2 compiler did not emit this requested view. Check render_plan omitted_views for compiler suppression details."


def _pricing_trace_summary(trace: dict) -> str:
    if not trace:
        return "no trace"
    if trace.get("service_code"):
        return (
            f"{trace.get('calculation_source')} service_code={trace.get('service_code')} "
            f"evidence={trace.get('price_list_evidence_id')} procurement_ready={trace.get('procurement_ready')}"
        )
    return f"{trace.get('calculation_source')} procurement_ready={trace.get('procurement_ready')}"


def _claim_evidence_map(dossier: dict, report: dict | None) -> dict:
    evidence = {
        item.get("id"): {
            "title": item.get("title"),
            "source_type": item.get("source_type"),
            "url": item.get("url"),
        }
        for item in ((report or {}).get("evidence_items") or [])
        if item.get("id")
    }
    return {
        claim.get("id"): {
            "claim": claim.get("text"),
            "claim_kind": claim.get("claim_kind"),
            "claim_type": claim.get("claim_type"),
            "evidence": [evidence.get(evidence_id, {"id": evidence_id, "missing": True}) for evidence_id in claim.get("evidence_ids", [])],
            "unsupported": claim.get("unsupported"),
            "requires_validation": claim.get("requires_validation"),
        }
        for claim in dossier.get("claims", [])
    }


def _report_metadata(report: dict | None, key: str):
    return ((report or {}).get("metadata") or {}).get(key)


def _pricing_metadata(pricing: dict | None, key: str):
    return ((pricing or {}).get("metadata") or {}).get(key)


def _source_policy_payload(report: dict | None) -> dict:
    evidence = (report or {}).get("evidence_items") or []
    source_types = {item.get("source_type") for item in evidence}
    metadata = (report or {}).get("metadata") or {}
    research_quality = metadata.get("research_quality") or {}
    competitor = (report or {}).get("competitor_analysis") or ""
    competitor_enabled = "Tavily web search was used" in competitor
    return {
        "aws_documentation": "AWS Docs MCP or official AWS documentation evidence present" if "aws_docs" in source_types else "unavailable or not captured",
        "aws_pricing": "AWS Pricing evidence present; source-bound totals require pricing ledger/rate binding" if "aws_pricing" in source_types else "unavailable or not captured",
        "competitor_web_scan": "enabled" if competitor_enabled else "disabled",
        "competitor_limitation": competitor or "Competitor web scan disabled. Competitive landscape is limited and not market-validated.",
        "research_quality": research_quality,
    }


def _architecture_critiques(architectures) -> list[dict]:
    critiques = []
    for spec in architectures or []:
        metadata = spec.get("metadata") or {}
        critique = metadata.get("architecture_critique")
        if critique:
            critiques.append({"mode": spec.get("mode"), "architecture_id": spec.get("id"), "critique": critique})
    return critiques
