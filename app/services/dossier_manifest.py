"""Verifiable solution dossier manifest.

Builds `dossier_manifest.json` — the trust spine of an Archway export package. It
records, for one export, what is verified / directional / missing / failed-closed /
reproducible, plus a content-hashed inventory of every artifact so a third party can
verify the package offline.

Hard rules (mirrored from DECISIONS D2/D3/D10/D11):
- Global pricing readiness and SKU pilot readiness are NEVER collapsed into one field.
- SKU pilot presence never upgrades the overall dossier status.
- Rate authority (`rate_authoritative`) and quantity confidence (`quantities_confirmed`)
  are separate axes; assumed quantities can never read as procurement-ready.
- Hashing is stable/canonical (sorted keys, UTF-8, normalized newlines, SHA-256).
- The manifest is excluded from its own artifact inventory (no self-recursion).

This module reads already-produced data/files; it does NOT compute pricing, call the
network, or change any readiness gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = "dossier_manifest_v1"
MANIFEST_FILENAME = "dossier_manifest.json"

# Logical artifacts an export is expected to contain (manifest itself excluded).
REQUIRED_ARTIFACTS = (
    "README.md",
    "manifest.json",
    "01-solution-brief.md",
    "03-pricing.md",
    "raw/pricing.json",
    "raw/session.json",
)

_CONTENT_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".txt": "text/plain",
}


# --------------------------------------------------------------------------- #
# Canonical hashing
# --------------------------------------------------------------------------- #
def _canonicalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(value, dict):
        return {str(k): _canonicalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    return value


def stable_json_hash(value: Any) -> str:
    """Deterministic SHA-256 over a JSON-able value (sorted keys, UTF-8, normalized newlines)."""
    canon = _canonicalize(value)
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def hash_file_bytes(path: str | Path) -> str:
    """SHA-256 over raw file bytes (binary-safe; no newline normalization)."""
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _produced_by(relative: str) -> str:
    if relative == MANIFEST_FILENAME or relative == "dossier_manifest.md":
        return "dossier_manifest"
    if relative.startswith("pricing/sku_pricing_pilot"):
        return "sku_pricing_pilot"
    if relative.startswith("raw/"):
        return "export_package.raw"
    if relative.startswith("diagrams/"):
        return "diagram_compiler"
    if relative == "manifest.json":
        return "export_package"
    if relative.endswith(".md"):
        return "export_package.markdown"
    return "export_package"


# --------------------------------------------------------------------------- #
# Identity / git context
# --------------------------------------------------------------------------- #
def git_context() -> dict:
    """Best-effort, offline code commit + branch. Never raises; None when unavailable."""
    commit = os.getenv("ARCHWAY_BUILD_COMMIT")
    branch = os.getenv("ARCHWAY_BUILD_BRANCH")
    for getter, key in (("rev-parse --short HEAD", "commit"), ("rev-parse --abbrev-ref HEAD", "branch")):
        if (key == "commit" and commit) or (key == "branch" and branch):
            continue
        try:
            out = subprocess.run(
                ["git", *getter.split()],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True, text=True, timeout=5, check=False,
            )
            value = out.stdout.strip() if out.returncode == 0 else None
        except Exception:  # noqa: BLE001
            value = None
        if key == "commit":
            commit = commit or value
        else:
            branch = branch or value
    return {"code_commit": commit, "branch": branch}


# --------------------------------------------------------------------------- #
# Section builders (read-only over already-produced data)
# --------------------------------------------------------------------------- #
def _meta(obj: dict | None, key: str, default=None):
    return ((obj or {}).get("metadata") or {}).get(key, default)


def _inputs_section(session_input, brief, pricing, architectures) -> dict:
    profile = (brief or {}).get("use_case_profile") or {}
    return {
        "raw_user_input_hash": stable_json_hash(session_input or ""),
        "canonical_facts_hash": stable_json_hash(_meta(pricing, "canonical_facts") or {}),
        "use_case_profile_hash": stable_json_hash(profile),
        "selected_domain": profile.get("domain"),
        "selected_family": (profile.get("workload_families") or [None])[0] if profile.get("workload_families") else None,
        "selected_pattern": ((architectures or [{}])[0].get("metadata") or {}).get("pattern_id")
        if architectures else None,
        "pricing_driver_hash": stable_json_hash(_meta(pricing, "pricing_driver_bindings") or _meta(pricing, "pricing_driver_closure") or {}),
        "architecture_input_hash": stable_json_hash(architectures or []),
    }


def _pricing_section(pricing, sku_trace_hash, unsupported_dimensions) -> dict:
    pricing = pricing or {}
    md = pricing.get("metadata") or {}
    compiler = md.get("source_truth_pricing_compiler") or {}
    ledger_summary = (md.get("pricing_ledger") or {}).get("summary") or {}
    closure = md.get("pricing_driver_closure") or {}
    global_section = {
        "low_monthly_usd": pricing.get("low_monthly_usd"),
        "expected_monthly_usd": pricing.get("expected_monthly_usd"),
        "high_monthly_usd": pricing.get("high_monthly_usd"),
        "pricing_can_be_displayed_as_headline": md.get("pricing_can_be_displayed_as_headline") is True,
        "headline_safe": bool(ledger_summary.get("headline_safe", False)),
        "procurement_ready": bool(ledger_summary.get("procurement_ready", False)),
        "pricing_closure_status": closure.get("status", "unknown"),
        "pricing_maturity": md.get("pricing_maturity", closure.get("pricing_maturity", "unknown")),
        "compiler_enabled": bool(compiler.get("enabled", False)),
        "evidence_class_summary": {
            "sku_tier_backed_subtotal": ledger_summary.get("sku_tier_backed_subtotal", 0),
            "catalog_referenced_subtotal": ledger_summary.get("pricing_page_or_mcp_backed_subtotal", 0),
            "heuristic_subtotal": ledger_summary.get("heuristic_subtotal", 0),
        },
    }
    pilot = md.get("sku_pricing_pilot")
    sku_section: dict | None = None
    if pilot:
        rate_authoritative = pilot.get("rate_authoritative")
        # Propagate snapshot provenance from the pilot metadata where available
        # (top-level first; fall back to a nested snapshot block if present).
        snapshot_block = pilot.get("snapshot") if isinstance(pilot.get("snapshot"), dict) else {}
        upstream_source = pilot.get("upstream_source") or snapshot_block.get("upstream_source")
        version_hash = pilot.get("version_hash") or snapshot_block.get("version_hash")
        source_hash = pilot.get("source_hash") or snapshot_block.get("source_hash")
        # When rates claim authority, provenance must be complete (upstream + version +
        # source hash); otherwise mark it partial so the verifier can warn/fail-strict.
        if rate_authoritative:
            provenance_status = "complete" if (upstream_source and version_hash and source_hash) else "partial"
        else:
            provenance_status = "not_authoritative"
        sku_section = {
            "present": True,
            "supplemental": True,
            "status": pilot.get("status"),
            "workload": pilot.get("workload"),
            "sku_backed_subtotal": pilot.get("sku_backed_subtotal"),
            "directional_subtotal": pilot.get("directional_subtotal"),
            # Separate readiness axes — never collapsed (DECISIONS D10/D11).
            "rate_authoritative": rate_authoritative,
            "quantities_confirmed": pilot.get("quantities_confirmed"),
            "quantity_source": pilot.get("quantity_source"),
            "quantity_confidence": pilot.get("quantity_confidence"),
            "sku_pilot_estimate_ready": pilot.get("sku_pilot_estimate_ready"),
            "sku_pilot_procurement_ready": pilot.get("sku_pilot_procurement_ready"),
            "snapshot_id": pilot.get("snapshot_id"),
            "snapshot_source": pilot.get("snapshot_source"),
            "snapshot_authoritative": pilot.get("snapshot_authoritative"),
            "upstream_source": upstream_source,
            "source_hash": source_hash,
            "version_hash": version_hash,
            "estimate_input_hash": pilot.get("estimate_input_hash"),
            "sku_trace_hash": sku_trace_hash,
            "provenance_status": provenance_status,
            "not_estimated": list(pilot.get("not_estimated") or []),
            "unsupported_dimensions": dict(unsupported_dimensions or {}),
        }
    return {"global": global_section, "sku_pilot": sku_section}


def _research_section(report) -> dict:
    report = report or {}
    md = report.get("metadata") or {}
    readiness = md.get("customer_readiness") or {}
    evidence_quality = md.get("evidence_quality") or {}
    evidence_items = report.get("evidence_items") or []
    return {
        "summary_hash": stable_json_hash({
            "executive_verdict": report.get("executive_verdict"),
            "facts": [c.get("text") for c in report.get("facts", [])],
            "recommendations": [c.get("text") for c in report.get("recommendations", [])],
        }),
        "evidence_count": len(evidence_items),
        "evidence_authority": evidence_quality.get("evidence_authority", "unknown"),
        "evidence_readiness": readiness.get("status", "unknown"),
        "missing_evidence_warning": (readiness.get("warnings") or [])[:1][0] if readiness.get("warnings") else None,
    }


def _architecture_section(architectures, revisions) -> dict:
    specs = architectures or []
    services = sorted({
        comp.get("service") or comp.get("name")
        for spec in specs
        for comp in (spec.get("components") or [])
        if comp.get("service") or comp.get("name")
    })
    revisions = revisions or []
    latest = max((r.get("version", 0) for r in revisions), default=None) if revisions else None
    governed = any(spec.get("governance_controls") for spec in specs)
    return {
        "selected_pattern": (specs[0].get("metadata") or {}).get("pattern_id") if specs else None,
        "spec_hash": stable_json_hash(specs),
        "architecture_revision_id": latest,
        "stale_revision_status": (specs[0].get("metadata") or {}).get("stale_revision_status") if specs else None,
        "service_inventory_hash": stable_json_hash(services),
        "service_count": len(services),
        "governance_effectful_flow_status": "present" if governed else "none_declared",
    }


def _diagram_section(export_dir: Path, diagrams) -> list[dict]:
    out: list[dict] = []
    for gallery in diagrams or []:
        mode = gallery.get("mode")
        qa = {q.get("view_id"): q for q in (gallery.get("qa_reports") or [])}
        for diagram in gallery.get("diagrams", []):
            view_id = diagram.get("view_id")
            report = qa.get(view_id, {})
            metrics = report.get("metrics") or {}
            entry: dict = {
                "name": diagram.get("title"),
                "mode": mode,
                "view_id": view_id,
                "validation_status": "passed" if report.get("passed") else ("failed" if report else "unknown"),
                "crossing_count": metrics.get("edge_crossings", metrics.get("crossings")),
                "readability": metrics.get("readability_score", metrics.get("readability")),
                "degraded_reason": diagram.get("fallback_reason"),
                "d2_source_hash": None,
                "image_hash": None,
                "paths": {},
            }
            for fmt, artifact in (diagram.get("format_paths") or {}).items():
                candidate = export_dir / str(artifact)
                if candidate.is_file():
                    entry["paths"][fmt] = str(artifact)
                    if fmt == "d2":
                        entry["d2_source_hash"] = hash_file_bytes(candidate)
                    elif fmt in ("svg", "png") and entry["image_hash"] is None:
                        entry["image_hash"] = hash_file_bytes(candidate)
            out.append(entry)
    out.sort(key=lambda e: (str(e.get("mode")), str(e.get("view_id"))))
    return out


def _artifact_inventory(export_dir: Path) -> list[dict]:
    items: list[dict] = []
    present: set[str] = set()
    for path in sorted(export_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(export_dir).as_posix()
        if relative == MANIFEST_FILENAME:  # exclude manifest from its own inventory
            continue
        present.add(relative)
        items.append({
            "logical_name": relative,
            "path": relative,
            "content_type": _content_type(path),
            "size_bytes": path.stat().st_size,
            "sha256": hash_file_bytes(path),
            "produced_by": _produced_by(relative),
            "required": relative in REQUIRED_ARTIFACTS,
            "status": "present",
        })
    for required in REQUIRED_ARTIFACTS:
        if required not in present:
            items.append({
                "logical_name": required,
                "path": required,
                "content_type": _content_type(Path(required)),
                "size_bytes": 0,
                "sha256": None,
                "produced_by": _produced_by(required),
                "required": True,
                "status": "missing",
            })
    items.sort(key=lambda i: i["path"])  # deterministic ordering
    return items


def _readiness_gates(pricing_section, research_section, architecture_section,
                     diagrams_section, inventory, warnings) -> dict:
    g = pricing_section["global"]
    diagram_validation = "passed"
    if diagrams_section:
        statuses = {d["validation_status"] for d in diagrams_section}
        diagram_validation = "failed" if "failed" in statuses else ("unknown" if statuses == {"unknown"} else "passed")
    elif diagrams_section == []:
        diagram_validation = "none"
    missing_required = [i["logical_name"] for i in inventory if i["required"] and i["status"] != "present"]
    return {
        "pricing_headline_safe": bool(g["pricing_can_be_displayed_as_headline"]),
        "pricing_closure": g["pricing_closure_status"],
        "research_evidence_readiness": research_section["evidence_readiness"],
        "architecture_completeness": "present" if architecture_section["service_count"] > 0 else "incomplete",
        "diagram_validation": diagram_validation,
        "governance_effectful_flow_readiness": architecture_section["governance_effectful_flow_status"],
        "export_artifact_completeness": "complete" if not missing_required else "incomplete",
        "missing_required_artifacts": missing_required,
        "warnings": list(warnings or []),
        "blockers": list(missing_required),
    }


def _overall_status(gates, research_section, pricing_section, convergence_status) -> str:
    # Hard blockers first.
    if gates["blockers"] or gates["export_artifact_completeness"] != "complete":
        return "blocked"
    if str(convergence_status or "").lower() in {"blocked", "failed"}:
        return "blocked"
    if gates["diagram_validation"] == "failed":
        return "blocked"
    # Directional when pricing is not headline-safe or evidence isn't ready.
    if not gates["pricing_headline_safe"] or gates["research_evidence_readiness"] in {"not_ready", "blocked"}:
        return "directional_only"
    if gates["warnings"] or gates["architecture_completeness"] != "present":
        return "ready_with_warnings"
    return "ready"


# --------------------------------------------------------------------------- #
# Public builder
# --------------------------------------------------------------------------- #
def build_dossier_manifest(
    export_dir: str | Path,
    *,
    session_id: str,
    export_name: str,
    generated_at: str,
    session_input: str | None,
    brief: dict | None,
    report: dict | None,
    pricing: dict | None,
    architectures: list | None,
    architecture_revisions: list | None,
    diagrams: list | None,
    warnings: list[str] | None,
    feature_flags: dict | None = None,
    convergence_status: str | None = None,
    sku_trace_hash: str | None = None,
    unsupported_dimensions: dict | None = None,
    app_version: str | None = None,
) -> dict:
    """Assemble the dossier manifest dict. Reads files already written under ``export_dir``."""
    export_dir = Path(export_dir)
    git = git_context()

    inputs = _inputs_section(session_input, brief, pricing, architectures)
    pricing_section = _pricing_section(pricing, sku_trace_hash, unsupported_dimensions)
    research_section = _research_section(report)
    architecture_section = _architecture_section(architectures, architecture_revisions)
    diagrams_section = _diagram_section(export_dir, diagrams)
    inventory = _artifact_inventory(export_dir)
    gates = _readiness_gates(pricing_section, research_section, architecture_section,
                             diagrams_section, inventory, warnings)
    overall = _overall_status(gates, research_section, pricing_section, convergence_status)

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dossier_id": export_name,
        "generated_at": generated_at,
        "identity": {
            "dossier_id": export_name,
            "session_id": session_id,
            "generated_at": generated_at,
            "code_commit": git["code_commit"],
            "branch": git["branch"],
            "app_version": app_version,
            "feature_flags": dict(feature_flags or {}),
        },
        "inputs": inputs,
        "pricing": pricing_section,
        "research": research_section,
        "architecture": architecture_section,
        "diagrams": diagrams_section,
        "readiness_gates": gates,
        "overall_status": overall,
        "artifact_inventory": inventory,
    }


def manifest_markdown(manifest: dict) -> str:
    p = manifest["pricing"]
    sku = p["sku_pilot"]
    lines = [
        "# Dossier Manifest",
        "",
        f"- Schema: {manifest['schema_version']}",
        f"- Dossier id: {manifest['dossier_id']}",
        f"- Generated at: {manifest['generated_at']}",
        f"- Overall status: **{manifest['overall_status']}**",
        "",
        "## Pricing — global (legacy, unchanged)",
        f"- Range: ${p['global']['low_monthly_usd']}–${p['global']['high_monthly_usd']} (expected ${p['global']['expected_monthly_usd']})",
        f"- Headline-safe: {p['global']['pricing_can_be_displayed_as_headline']}",
        f"- Global procurement-ready: {p['global']['procurement_ready']}",
        "",
        "## Pricing — SKU-backed pilot (supplemental)",
    ]
    if sku:
        lines += [
            "Supplemental SKU-backed pilot trace. Does not replace the legacy estimate.",
            f"- Subtotal: {sku['sku_backed_subtotal']}",
            f"- Rate authoritative: {sku['rate_authoritative']}",
            f"- Quantities confirmed: {sku['quantities_confirmed']} (source: {sku['quantity_source']})",
            f"- Pilot estimate-ready: {sku['sku_pilot_estimate_ready']}",
            f"- Pilot procurement-ready: {sku['sku_pilot_procurement_ready']}",
            f"- Snapshot: {sku['snapshot_id']} ({sku['snapshot_source']})",
            f"- Source hash: {sku['source_hash']}",
            f"- Not estimated: {', '.join(sku['not_estimated']) or 'none'}",
        ]
        if sku.get("unsupported_dimensions"):
            lines.append(f"- Unsupported dimensions: {', '.join(sku['unsupported_dimensions'].keys())}")
    else:
        lines.append("No SKU pilot trace present (flag off, non-document-RAG, or no snapshot).")
    gates = manifest["readiness_gates"]
    lines += [
        "",
        "## Readiness gates",
        f"- Pricing headline-safe: {gates['pricing_headline_safe']}",
        f"- Research evidence: {gates['research_evidence_readiness']}",
        f"- Diagram validation: {gates['diagram_validation']}",
        f"- Export artifact completeness: {gates['export_artifact_completeness']}",
        f"- Warnings: {len(gates['warnings'])} · Blockers: {len(gates['blockers'])}",
        "",
        f"Artifacts inventoried: {len(manifest['artifact_inventory'])}",
        "",
    ]
    return "\n".join(lines)
