"""Diagram-quality tests for the healthcare OR operations logical service flow.

Root issue (before this branch): the healthcare OR production logical service
flow rendered with 14 visible edge crossings against a gate of 8, because the
generic IoT/telemetry lane planner mis-grouped clinical components and the
governance/observability fan-out crisscrossed the primary view.

This branch adds a reusable domain-aware lane framework (generic fallback kept
intact) with healthcare OR as the first adapter, plus a healthcare-scoped
governance/observability sidecar. These tests prove the crossing count is now
within budget without loosening the gate, and that the clinical semantics are
preserved.
"""

import re

import pytest

from app.models.domain import ArchitectureSpec
from app.services.diagram_compiler_adapter import DiagramCompilerAdapter
from app.services.lane_planner import (
    HEALTHCARE_OPERATIONS_LANE_MODEL,
    RECOGNIZED_COMPILER_LANES,
    resolve_domain_lane_model,
)
from app.services.pattern_catalog import (
    expected_views,
    observability_controls,
    pattern_components,
    pattern_flows,
    security_controls,
    semantic_views,
    service_recommendations,
)
from app.services.use_case_profile import profile_use_case
from app.services.view_planner import diagram_view_mappings, semantic_to_compiler_mapping

HEALTHCARE_OR_USE_CASE = (
    "Large tertiary hospital wants to optimize OR scheduling, predict surgical delays, "
    "coordinate surgeons, anesthetists, nurses, sterile processing, bed occupancy, and EHR "
    "updates with approval workflow and audit trail. Epic EHR, PHI-safe, HIPAA."
)
GENERIC_WEB_USE_CASE = (
    "We need a public web application with API, database, async jobs, observability, and CI/CD."
)
LEGAL_RAG_USE_CASE = (
    "Law firm needs retrieval augmented generation over legal documents with citations, "
    "private data, and audit trail."
)

LOGICAL_VIEW = "production_logical_service_flow"


def _build(use_case: str):
    profile = profile_use_case(use_case)
    components = pattern_components(profile, production=True)
    flows = pattern_flows(profile, production=True, components=components)
    return profile, components, flows


def _compile(use_case: str, title: str):
    profile, components, flows = _build(use_case)
    view_ids = semantic_views(profile, production=True)
    compiler_views = expected_views(profile, production=True)
    mappings = diagram_view_mappings(view_ids, title)
    spec = ArchitectureSpec(
        session_id="sess_diagram_crossings",
        mode="production",
        title=f"PRODUCTION {title} Architecture",
        summary="diagram crossing test",
        selected_services=service_recommendations(profile, evidence_ids=["ev_test"]),
        components=components,
        flows=flows,
        security_controls=security_controls(profile, production=True),
        observability_controls=observability_controls(profile, production=True),
        scaling_strategy="Scale from measured load.",
        resilience_strategy="Multi-AZ managed services.",
        cost_optimization_strategy="Validate measured drivers.",
        assumptions=[],
        risks=[],
        metadata={
            "semantic_views": view_ids,
            "expected_views": compiler_views,
            "requested_views": compiler_views,
            "semantic_to_compiler_view_mapping": semantic_to_compiler_mapping(view_ids),
            "diagram_view_mappings": [mapping.model_dump() for mapping in mappings],
        },
    )
    result = DiagramCompilerAdapter().compile_production_diagrams(spec, "sess_diagram_crossings")
    return profile, components, flows, result


def _crossing_violations(result) -> dict:
    counts: dict[str, int] = {}
    for qa in result.qa_reports:
        for diagnostic in qa.diagnostics:
            if diagnostic.get("code") == "too_many_edge_crossings":
                match = re.search(r"(\w+) has (\d+) visible edge crossing", diagnostic.get("message", ""))
                if match:
                    counts[match.group(1)] = int(match.group(2))
    return counts


@pytest.fixture(scope="module")
def healthcare_result():
    return _compile(HEALTHCARE_OR_USE_CASE, "Healthcare Operations Scheduling")


# 1. Healthcare OR production logical crossings within budget (was 14, gate is 8).
def test_healthcare_or_production_logical_crossings_within_budget(healthcare_result):
    _, _, _, result = healthcare_result
    violations = _crossing_violations(result)
    assert LOGICAL_VIEW not in violations, f"logical view still over crossing budget: {violations}"
    assert all(qa.passed for qa in result.qa_reports), "diagram QA bundle must pass"
    assert LOGICAL_VIEW in result.rendered_view_ids
    assert not result.missing_requested_views


# 2. The crossing gate itself must remain strict (=8); never loosened by this branch.
def test_logical_crossing_threshold_remains_eight(healthcare_result):
    # The fixture's compile inserts the compiler package onto sys.path.
    from archway_diagram_compiler.quality_config import DEFAULT_QUALITY_CONFIG

    assert DEFAULT_QUALITY_CONFIG.logical_edge_crossing_max == 8


# 3. Required healthcare semantic groups present; compiler lanes stay recognized.
def test_healthcare_semantic_groups_present(healthcare_result):
    _, components, _, _ = healthcare_result
    groups = {component.metadata.get("semantic_group") for component in components}
    required = {
        "Clinical Source Systems",
        "Private Integration",
        "PHI-safe Operational State",
        "Decision Intelligence",
        "Approval & Command Center",
        "Governance & Observability",
    }
    assert required <= groups, f"missing clinical semantic groups: {required - groups}"
    assigned_lanes = {c.logical_group for c in components if c.metadata.get("lane_id")}
    assert assigned_lanes <= set(RECOGNIZED_COMPILER_LANES), f"unrecognized compiler lanes: {assigned_lanes}"


# 4. Approval write-back path preserved; optimizer never writes EHR directly.
def test_approval_writeback_path_preserved(healthcare_result):
    _, _, flows, _ = healthcare_result
    edges = {(flow.source, flow.target) for flow in flows}
    for edge in (
        ("ml", "proposed_changes"),
        ("proposed_changes", "policy_evaluator"),
        ("policy_evaluator", "workflow"),
        ("workflow", "writeback_adapter"),
        ("writeback_adapter", "private_connectivity"),
        ("private_connectivity", "ehr"),
    ):
        assert edge in edges, f"approval write-back edge missing: {edge}"
    assert ("ml", "ehr") not in edges, "optimizer must not write directly to EHR"
    assert any(flow.metadata.get("approval_required") for flow in flows), "human approval gate must remain"


# 5. Governance/observability is a sidecar, not a per-node all-to-audit fan-out in primary view.
def test_governance_observability_is_sidecar_not_primary_fanout(healthcare_result):
    _, components, flows, _ = healthcare_result
    sidecar_ids = {c.id for c in components if c.metadata.get("sidecar")}
    assert {"logs", "audit", "kms"} <= sidecar_ids, f"governance nodes not flagged sidecar: {sidecar_ids}"
    governance_targets = {"logs", "kms", "audit", "audit_lake"}
    governance_flows = [flow for flow in flows if flow.target in governance_targets]
    assert governance_flows, "governance flows must still exist (preserved, not dropped)"
    assert all(
        flow.metadata.get("logical_detail_only") for flow in governance_flows
    ), "governance fan-out must be routed to detail/sidecar, not the primary logical view"


# 6. PHI / security posture preserved.
def test_phi_security_posture_preserved(healthcare_result):
    _, components, _, _ = healthcare_result
    ids = {c.id for c in components}
    services = {c.service for c in components}
    assert "kms" in ids and "kms" in services, "encryption boundary must remain"
    assert "private_connectivity" in ids, "private hospital connectivity must remain"
    assert "auth" in ids, "identity/authentication must remain"
    state = next(c for c in components if c.id == "state")
    assert state.metadata.get("semantic_group") == "PHI-safe Operational State"


# 7. No IoT / field-service / depot leakage in the healthcare OR architecture.
def test_no_iot_or_field_service_leakage(healthcare_result):
    _, components, _, _ = healthcare_result
    blob = " ".join(f"{c.id} {c.service} {c.name}".lower() for c in components)
    for forbidden in ("iot_core", "iotsitewise", "sitewise", "field workforce", "depot", " iot "):
        assert forbidden not in blob, f"unexpected IoT/field leakage: {forbidden!r}"


# 8. Unknown domains keep the generic fallback (no clinical groups injected).
def test_generic_use_case_uses_generic_fallback():
    profile, components, _ = _build(GENERIC_WEB_USE_CASE)
    assert resolve_domain_lane_model(profile.domain, profile.workload_families) is None
    assert all(c.metadata.get("semantic_group") != "Clinical Source Systems" for c in components)
    assert all(not str(c.metadata.get("lane_id") or "").startswith("clinical") for c in components)


# 9. Other scenarios still compile with no logical-view crossing regression.
def test_other_scenarios_compile_without_logical_crossing_regression():
    for use_case, title in ((LEGAL_RAG_USE_CASE, "Legal RAG"), (GENERIC_WEB_USE_CASE, "Generic Web")):
        _, _, _, result = _compile(use_case, title)
        violations = _crossing_violations(result)
        assert LOGICAL_VIEW not in violations, f"{title} logical crossings regressed: {violations}"


# 10. The framework is reusable (adapter + fallback), not a one-off healthcare hack.
def test_domain_lane_framework_is_reusable_with_generic_fallback():
    model = resolve_domain_lane_model("healthcare", ["healthcare_operations_scheduling"])
    assert model is HEALTHCARE_OPERATIONS_LANE_MODEL
    # Every domain lane maps to a compiler-recognized lane label (honors the compiler contract).
    assert all(lane.compiler_lane in RECOGNIZED_COMPILER_LANES for lane in model.lanes)
    # Lanes are ordered (clinical flow order) and include a governance sidecar.
    assert any(lane.sidecar for lane in model.lanes)
    # Unknown domains fall back to the generic lane planner.
    assert resolve_domain_lane_model("telecommunications", ["telecom_congestion"]) is None
    assert resolve_domain_lane_model(None, []) is None
