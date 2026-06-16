"""Client-pack and audit-pack renderers for export packages.

Additive presentation layer only. Every file rendered here derives from the
SAME in-memory payloads as the root numbered artifacts (brief, report,
pricing, architectures, diagrams, deep dossier, decision records, reviewer
report) — no new claims, numbers, readiness states, risks, or architecture
decisions are introduced. No LLM calls, no network calls.

- ``client_pack/``: concise, polished customer-facing markdown obeying the
  client copy contract (display labels, formatted numbers, no machine keys,
  no compiler/view-fallback caveats).
- ``audit_pack/``: a guide to the full technical/audit content plus the
  diagram view-fallback notes, where compiler honesty and provenance belong.

Root numbered files, REQUIRED_ARTIFACTS, manifest, and verifier semantics are
untouched by this module.
"""

from __future__ import annotations

import re

from app.services.customer_readiness import compute_readiness_tier
from app.services.deep_dossier import _cost_range
from app.services.display_labels import display_label, gate_display

_DRIVER_PATTERN = re.compile(r"^(assumed_)?([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+)$")


def front_door_readme(session_name: str) -> str:
    """Root README.md: the first file anyone opens."""
    return "\n".join([
        f"# {session_name}",
        "",
        "This package is Archway's complete solution dossier for the use case above: "
        "the recommended AWS architecture, directional pricing with its assumptions, "
        "compiled diagrams, decision records, and a cryptographically verifiable "
        "manifest. Every number and claim carries its provenance; anything not yet "
        "validated says so explicitly.",
        "",
        "## Where to start",
        "",
        "- **Executive or customer review** — open `client_pack/START_HERE.md` for the "
        "concise, business-language deliverable.",
        "- **Traceability, evidence, and provenance** — open `audit_pack/README.md` for "
        "the guide to the full technical record.",
        "- **Verification** — `dossier_manifest.md` lists every artifact with its "
        "SHA-256 hash; `README_DOSSIER.md` explains offline verification.",
        "",
        "The numbered files in this folder are the complete working artifacts and "
        "remain unchanged for compatibility with existing tooling.",
        "",
    ])


def client_pack_files(
    *,
    session_name: str,
    brief: dict | None,
    report: dict | None,
    pricing: dict | None,
    architectures: list | None,
    diagrams: list | None,
    deep_dossier,
    decision_records: list | None,
) -> dict[str, str]:
    """Render client_pack/ markdown. Keys are paths relative to client_pack/."""
    brief = brief or {}
    report = report or {}
    pricing = pricing or {}
    architectures = architectures or []
    diagrams = diagrams or []
    decision_records = decision_records or []
    # One tier computation feeds every client surface — readiness wording can
    # never diverge between the memo and the pricing summary.
    tier = compute_readiness_tier(report=report, pricing=pricing, architectures=architectures)
    return {
        "START_HERE.md": _start_here(session_name),
        "01-executive-memo.md": _executive_memo(report, deep_dossier, tier),
        "02-solution-brief.md": _solution_brief(brief, deep_dossier),
        "03-architecture-summary.md": _architecture_summary(architectures, decision_records),
        "04-pricing-summary.md": _pricing_summary(pricing, deep_dossier, tier),
        "05-risks-and-gates.md": _risks_and_gates(deep_dossier, tier),
        "06-evidence-summary.md": _evidence_summary(report, deep_dossier),
        "07-diagrams-index.md": _diagrams_index(diagrams),
    }


def audit_pack_files(*, diagrams: list | None) -> dict[str, str]:
    """Render audit_pack/ markdown. Keys are paths relative to audit_pack/."""
    return {
        "README.md": _audit_guide(),
        "view-fallback-notes.md": _view_fallback_notes(diagrams or []),
    }


# --------------------------------------------------------------------------- #
# Client pack sections
# --------------------------------------------------------------------------- #
def _start_here(session_name: str) -> str:
    return "\n".join([
        f"# {session_name}",
        "",
        "This client pack is the concise, business-language view of the full "
        "solution dossier. Read it in order:",
        "",
        "1. `01-executive-memo.md` — verdict, readiness, and what to validate first.",
        "2. `02-solution-brief.md` — the problem as understood, scope, and assumptions.",
        "3. `03-architecture-summary.md` — the recommended AWS architecture and key decisions.",
        "4. `04-pricing-summary.md` — directional pricing with its confidence and caveats.",
        "5. `05-risks-and-gates.md` — risks and the validation gates before production.",
        "6. `06-evidence-summary.md` — how well-evidenced this dossier is.",
        "7. `07-diagrams-index.md` — the architecture diagrams included in this package.",
        "",
        "Every statement here is derived from the full audited record in this "
        "package. For complete traceability — evidence items, decision records, "
        "pricing traces, and the verification manifest — start at "
        "`../audit_pack/README.md`.",
        "",
    ])


def _executive_memo(report: dict, dossier, tier: dict) -> str:
    top_risk = dossier.risks[0].risk if dossier.risks else "Pricing and operational validation remain open."
    direction = report.get("recommended_production_direction") or (
        "an AWS-native architecture with governed operations, evidence discipline, and explicit pricing validation"
    )
    gates = [gate_display(item) for item in dossier.top_validation_gates[:3]]
    cap = tier.get("reasons") or []
    lines = [
        "# Executive Memo",
        "",
        f"**Use case:** {dossier.title}",
        f"**Verdict:** {dossier.verdict}",
        f"**Readiness tier:** {tier['display']}",
        "",
        "## Readiness",
        "",
        _sentence(
            f"This package is graded {tier['display']}"
            + (". It meets every readiness gate" if not cap else f", capped because {cap[0].rstrip('.').lower()}")
        ),
        *(["", "To advance to the next tier:", "", *_bullets([_sentence(reason) for reason in cap])] if cap else []),
        "",
        "## Recommendation",
        "",
        _sentence(f"Proceed through a staged AWS-native path: a scoped proof of concept first, "
                  f"then production once the validation gates below pass. The recommended direction is {direction}"),
        "",
        "## Cost position",
        "",
        _sentence(dossier.estimated_monthly_cost_range),
        "",
        _sentence(f"Treat this as a {tier['estimate_display'].lower()} at the {tier['display'].lower()} tier"),
        "",
        "## What must be validated first",
        "",
        *_bullets(gates),
        "",
        "## Biggest risk",
        "",
        _sentence(str(top_risk)),
        "",
    ]
    return "\n".join(lines)


def _solution_brief(brief: dict, dossier) -> str:
    assumptions = [
        f"{item.get('text')} ({display_label(str(item.get('impact') or 'impact'), capitalize=False)} impact, "
        f"{display_label(str(item.get('confidence') or 'unknown'), capitalize=False)} confidence)"
        for item in brief.get("assumptions", [])
    ]
    questions = [str(item.get("text")) for item in brief.get("open_questions", [])]
    return "\n".join([
        "# Solution Brief",
        "",
        f"**Title:** {brief.get('title') or dossier.title}",
        f"**Industry:** {display_label(str(brief.get('industry') or 'unconfirmed'))}",
        f"**Workload focus:** {', '.join(display_label(f) for f in dossier.workload_family) or 'Requires validation'}",
        "",
        "## The problem as understood",
        "",
        _sentence(str(brief.get("refined_problem_statement") or "No refined problem statement was available at export time")),
        "",
        "## Proof-of-concept scope",
        "",
        _sentence(str(brief.get("poc_scope") or "To be confirmed during discovery")),
        "",
        "## Production scope",
        "",
        _sentence(str(brief.get("production_scope") or "To be confirmed during discovery")),
        "",
        "## Working assumptions",
        "",
        *_bullets(assumptions),
        "",
        "## Open questions for the customer",
        "",
        *_bullets(questions),
        "",
    ])


def _architecture_summary(architectures: list, decision_records: list) -> str:
    lines = ["# Architecture Summary", ""]
    specs = [spec for spec in architectures if isinstance(spec, dict)]
    if not specs:
        lines.extend(["No architecture was available at export time.", ""])
        return "\n".join(lines)
    for spec in specs:
        mode = display_label(str(spec.get("mode") or "architecture"))
        lines.extend([
            f"## {mode} architecture",
            "",
            _sentence(str(spec.get("summary") or "Summary pending")),
            "",
            "Key services:",
            "",
            *_bullets([
                f"**{item.get('service')}** — {_sentence(str(item.get('purpose') or 'Purpose recorded in the full architecture document'))}"
                for item in spec.get("selected_services", [])
                if isinstance(item, dict) and item.get("service")
            ]),
            "",
        ])
    component_decisions = [r for r in decision_records if str(getattr(r, "decision_id", "")).startswith("adr_component_")]
    lines.extend([
        "## Key architecture decisions",
        "",
        _sentence(
            f"{len(component_decisions)} service-selection decisions are recorded with their alternatives and rationale"
            if component_decisions
            else "Decision records for this architecture are recorded in the audit pack"
        ),
        "",
        "The full decision records — including alternatives considered and the "
        "evidence class behind each choice — are in `../architecture/decision_records.md`.",
        "",
    ])
    return "\n".join(lines)


_ESTIMATE_CLASS_GUIDANCE = {
    "planning_estimate": (
        "This is a planning estimate: computed deterministically from the stated "
        "drivers and assumptions, and honest about every quantity that has not "
        "been confirmed. It is a planning aid, not a quote."
    ),
    "budgetary_range": (
        "This is a budgetary range: the pricing basis supports range-level "
        "discussion, but quantities still rest on stated assumptions. Suitable "
        "for workshop budgeting, not for commitment."
    ),
    "rate_backed_estimate": (
        "This is a rate-backed estimate: line items bind to exact AWS SKU/tier "
        "rates with confirmed drivers. Validate against the AWS Pricing "
        "Calculator before final commitment."
    ),
}


def _pricing_summary(pricing: dict, dossier, tier: dict) -> str:
    metadata = pricing.get("metadata") or {}
    closure = metadata.get("pricing_driver_closure") or {}
    procurement_ready = bool(closure.get("procurement_ready", False))
    invalid = metadata.get("pricing_scenario_validity") == "invalid_driver_mismatch" or metadata.get("status") == "invalid_driver_mismatch"
    drivers = [_driver_display(item) for item in pricing.get("main_cost_drivers", [])]
    missing = [
        display_label(str(item.get("display_name") or ""))
        for item in closure.get("missing_drivers", [])
        if isinstance(item, dict) and item.get("display_name")
    ]
    advance = [_sentence(reason) for reason in tier.get("reasons", [])]
    return "\n".join([
        "# Pricing Summary",
        "",
        f"**Region:** {pricing.get('region') or 'Not selected'}",
        f"**Confidence:** {dossier.quality_score.pricing_score}/10",
        f"**Readiness tier:** {tier['display']}",
        f"**Estimate class:** {tier['estimate_display']}",
        f"**Procurement-ready:** {'Yes' if procurement_ready else 'No'}",
        "",
        "## Current estimate",
        "",
        _sentence("Pricing scenario needs repair: driver set does not match the confirmed workload. No polished monthly range is displayed for this invalid scenario." if invalid else dossier.estimated_monthly_cost_range),
        "",
        "## What drives this cost",
        "",
        *_bullets(drivers),
        "",
        "## To reach budget-grade pricing",
        "",
        *_bullets(missing or ["Confirm workload quantities and exact AWS rates before procurement."]),
        "",
        "## To advance beyond this tier",
        "",
        *_bullets(advance or ["This package meets every readiness gate; validate final quantities with the customer."]),
        "",
        "## How to read these numbers",
        "",
        _ESTIMATE_CLASS_GUIDANCE[tier["estimate_class"]] + " The full "
        "calculation trace and evidence are preserved in the audit record.",
        "",
    ])


def _risks_and_gates(dossier, tier: dict) -> str:
    risks = [
        f"**{display_label(str(risk.severity), capitalize=True)}** — {_sentence(str(risk.risk))} "
        f"Mitigation: {_sentence(str(risk.mitigation))}"
        for risk in dossier.risks
    ]
    gates = [gate_display(item) for item in dossier.top_validation_gates]
    cap = [_sentence(reason) for reason in tier.get("reasons") or []]
    return "\n".join([
        "# Risks and Validation Gates",
        "",
        f"**Readiness tier:** {tier['display']}",
        "",
        "## Why this tier",
        "",
        *_bullets(cap or [f"This package meets every readiness gate for {tier['display'].lower()}."]),
        "",
        "## Key risks",
        "",
        *_bullets(risks),
        "",
        "## Gates before production",
        "",
        *_bullets(gates or ["Refresh evidence and pricing before procurement."]),
        "",
    ])


def _evidence_summary(report: dict, dossier) -> str:
    evidence_items = report.get("evidence_items", []) or []
    counts: dict[str, int] = {}
    for item in evidence_items:
        source = display_label(str(item.get("source_type") or "unknown"))
        counts[source] = counts.get(source, 0) + 1
    coverage = (report.get("citation_coverage") or {}).get("coverage_percent", 0)
    authority = ((report.get("metadata") or {}).get("evidence_quality") or {}).get("evidence_authority", "unknown")
    return "\n".join([
        "# Evidence Summary",
        "",
        f"**Evidence authority:** {display_label(str(authority))}",
        f"**Citation coverage:** {coverage}%",
        f"**Evidence items:** {len(evidence_items)}",
        "",
        "## Sources by type",
        "",
        *_bullets([f"{source}: {count}" for source, count in sorted(counts.items())]),
        "",
        "Every claim in this dossier is mapped to its evidence in the audit "
        "record; claims that require validation are labeled rather than asserted.",
        "",
    ])


def _diagrams_index(diagrams: list) -> str:
    lines = [
        "# Diagrams Index",
        "",
        "Architecture diagrams included in this package, by deployment stage. "
        "The rendered files live in the package `diagrams/` folder.",
        "",
    ]
    rows: list[str] = []
    for gallery in diagrams:
        if not isinstance(gallery, dict):
            continue
        mode = display_label(str(gallery.get("mode") or "architecture"))
        for diagram in gallery.get("diagrams", []) or []:
            if not isinstance(diagram, dict):
                continue
            view = display_label(str(diagram.get("view_id") or "view"))
            svg = (diagram.get("format_paths") or {}).get("svg")
            location = f" (`{svg}`)" if svg and ".." not in str(svg) and not str(svg).startswith("/") else ""
            rows.append(f"{mode} — {view}{location}")
    lines.extend(_bullets(rows))
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Audit pack sections
# --------------------------------------------------------------------------- #
def _audit_guide() -> str:
    return "\n".join([
        "# Audit Pack Guide",
        "",
        "This pack indexes the complete technical and provenance record of the "
        "package. The client pack is a presentation of this record — it derives "
        "from the same data and introduces no claims of its own.",
        "",
        "## Where the full record lives",
        "",
        "- **Deep research dossier** — `../02B-deep-research-dossier.md` (full narrative, "
        "all sections), with `../02C-claim-register.md`, `../02D-evidence-map.md`, and "
        "`../02E-consistency-check.md`.",
        "- **Architecture working document** — `../04-architecture.md` (view contracts, "
        "security/governance/observability controls), with decision records in "
        "`../architecture/decision_records.md`.",
        "- **Pricing record** — `../03-pricing.md` (driver ledger, line items) and the "
        "calculation trace in `../11-pricing-trace.md`.",
        "- **Diagram provenance** — `../05-diagrams.md`, per-diagram placement "
        "explanations under `../diagrams/`, and `view-fallback-notes.md` in this pack "
        "for semantic views represented through broader compiler views.",
        "- **Evidence** — `../06-evidence-appendix.md` and raw payloads under `../raw/`.",
        "- **Reviewer output** — `../reviewer/reviewer_summary.md` and "
        "`../reviewer/uncertainty_map.md`.",
        "- **Diagnostics and source policy** — `../07-diagnostics.md`, `../12-source-policy.md`.",
        "- **Verification** — `../dossier_manifest.md` (SHA-256 inventory) and "
        "`../README_DOSSIER.md` (offline verification instructions).",
        "",
    ])


def _view_fallback_notes(diagrams: list) -> str:
    lines = [
        "# Diagram View Fallback Notes",
        "",
        "Compiler honesty record: semantic views that were represented through a "
        "broader supported compiler view, omitted, or not rendered. This detail is "
        "kept out of the client pack by design and preserved here.",
        "",
    ]
    any_section = False
    for gallery in diagrams:
        if not isinstance(gallery, dict):
            continue
        mode = display_label(str(gallery.get("mode") or "architecture"))
        ledger = gallery.get("view_rendering_ledger") or {}
        broader = ledger.get("rendered_via_broader_supported_view") or []
        omitted = ledger.get("omitted_with_reason") or []
        missing = gallery.get("missing_requested_views") or []
        lines.extend([f"## {mode}", ""])
        lines.extend(_bullets(
            [
                f"{item.get('view_id')}: represented by {item.get('represented_by_view_id') or item.get('compiler_view_id')} — {item.get('reason')}"
                for item in broader
            ]
            + [f"{item.get('view_id')}: omitted — {item.get('reason')}" for item in omitted]
            + [f"{item.get('view_id')}: not rendered — {item.get('reason')}" for item in missing]
        ))
        lines.append("")
        any_section = True
    if not any_section:
        lines.extend(["- None recorded.", ""])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _bullets(items: list[str]) -> list[str]:
    cleaned = [item for item in items if item and str(item).strip()]
    return [f"- {item}" for item in cleaned] or ["- None recorded."]


def _sentence(text: str) -> str:
    text = str(text or "").rstrip()
    while text.endswith(".."):
        text = text[:-1]
    if not text or text.endswith((".", "?", "!")):
        return text
    return text + "."


def _driver_display(item: str) -> str:
    match = _DRIVER_PATTERN.match(str(item).strip())
    if not match:
        return gate_display(str(item))
    assumed, name, value = match.groups()
    label = display_label(name)
    suffix = " (assumed)" if assumed else ""
    value = value.strip()
    if value.replace(",", "").isdigit():
        value = f"{int(value.replace(',', '')):,}"
    return f"{label}{suffix}: {value}"


# Re-export for callers that want identical cost wording to the dossier.
cost_range_text = _cost_range
