"""Typed effectful-flow detection.

Governance detection prefers explicit typed flow metadata and uses label/classification
string matching only as a union fallback. Vague-label external writes are governed;
read-only flows are not over-governed; existing string detection still works.
"""

from app.models.domain import ArchitectureComponent, ArchitectureFlow, ArchitectureSpec, ObservabilityControl, SecurityControl
from app.services.governance_controls import (
    GovernanceControlEnricher,
    classify_effectful_flows,
    unresolved_effectful_flow_ids,
)


def _flow(flow_id: str, label: str, metadata: dict) -> ArchitectureFlow:
    return ArchitectureFlow(id=flow_id, source="a", target="b", label=label, metadata=metadata)


def _spec_with(flow: ArchitectureFlow) -> ArchitectureSpec:
    return ArchitectureSpec(
        session_id="sess_test",
        mode="production",
        title="Test",
        summary="s",
        selected_services=[],
        components=[ArchitectureComponent(id="a", name="A", service="svc"), ArchitectureComponent(id="b", name="B", service="svc")],
        flows=[flow],
        security_controls=[SecurityControl(name="KMS encryption", rationale="protect")],
        observability_controls=[ObservabilityControl(name="CloudWatch logs", rationale="audit")],
        scaling_strategy="x", resilience_strategy="y", cost_optimization_strategy="z",
        assumptions=[], risks=[],
    )


def _is_governed(flow: ArchitectureFlow) -> bool:
    return bool(classify_effectful_flows([flow]))


def _enriched_flow_governed(flow: ArchitectureFlow):
    """Enrich a spec and report whether the flow ended up governed (controls or downgrade)."""
    enriched = GovernanceControlEnricher().enrich_spec(_spec_with(flow))
    governing = [c for c in enriched.governance_controls if enriched.flows[0].id in c.governed_flow_ids]
    downgraded = bool(enriched.flows[0].metadata.get("recommendation_only"))
    return enriched, governing, downgraded


# Test 1 — typed external write gets governance despite a vague label
def test_typed_external_write_governed_despite_vague_label():
    flow = _flow("f1", "Sync approved change", {
        "external_write": True, "mutates_source_system": True, "requires_approval": True, "action_intent": "writeback",
    })
    assert _is_governed(flow)
    enriched, governing, _ = _enriched_flow_governed(flow)
    assert governing, "typed external write must receive governance controls"
    assert "f1" in unresolved_effectful_flow_ids(_spec_with(flow)) or governing


# Test 2 — read-only RAG retrieval is not over-governed
def test_readonly_rag_retrieval_not_governed():
    flow = _flow("f2", "Vector Search", {
        "action_intent": "none", "external_write": False, "mutates_source_system": False, "classification": "vector_search",
    })
    assert not _is_governed(flow)


# Test 3 — legal approved metadata update gets governance
def test_legal_metadata_update_governed():
    flow = _flow("f3", "Contract Repository Metadata Update", {
        "action_intent": "update", "external_write": True, "mutates_source_system": True,
        "requires_approval": True, "target_system_type": "contract_repository",
    })
    _enriched, governing, _ = _enriched_flow_governed(flow)
    assert governing
    assert any(c.control_type in {"human_approval", "policy_approval"} for c in governing)


# Test 4 — healthcare EHR writeback governed even with a neutral label
def test_healthcare_ehr_writeback_governed_neutral_label():
    flow = _flow("f4", "Apply approved update", {
        "action_intent": "writeback", "external_write": True, "mutates_source_system": True,
        "requires_approval": True, "customer_or_patient_impacting": True, "target_system_type": "ehr",
        "automation_mode": "approval_required",
    })
    _enriched, governing, _ = _enriched_flow_governed(flow)
    assert governing
    # Customer/patient-impacting external write must require human approval (not safe-automated).
    assert any(c.control_type == "human_approval" for c in governing)


# Test 5 — payment block gets governance and is customer-impacting
def test_payment_block_governed():
    flow = _flow("f5", "Fraud decision", {
        "action_intent": "block", "external_write": True, "customer_or_patient_impacting": True,
        "target_system_type": "payment_network",
    })
    items = classify_effectful_flows([flow])
    assert items and items[0].action_type == "trade_block"
    assert items[0].impact_level == "critical"
    _enriched, governing, _ = _enriched_flow_governed(flow)
    assert any(c.control_type == "human_approval" for c in governing)


# Test 6 — telecom network config update gets governance
def test_telecom_network_update_governed():
    flow = _flow("f6", "Policy Engine to Network Controller", {
        "action_intent": "update", "external_write": True, "mutates_source_system": True,
        "target_system_type": "network_controller",
    })
    items = classify_effectful_flows([flow])
    assert items and items[0].action_type == "network_change"
    _enriched, governing, _ = _enriched_flow_governed(flow)
    assert any(c.control_type in {"human_approval", "policy_approval"} for c in governing)


# Test 7 — ambiguous external write fails safe
def test_ambiguous_external_write_fails_safe():
    flow = _flow("f7", "Publish update", {
        "action_intent": "publish", "target_system_type": "generic_external_system",
    })
    enriched, governing, downgraded = _enriched_flow_governed(flow)
    # Must not silently pass: either governed by controls or downgraded to recommendation/queue.
    assert governing or downgraded


# Test 8 — fallback string detection still works (no typed metadata)
def test_string_fallback_detection_still_works():
    for label, classification in (("Approved writeback to system", None), ("Delete stale records", None), ("External update adapter", "external_write")):
        flow = _flow("f8", label, {"classification": classification} if classification else {})
        assert _is_governed(flow), f"string fallback should govern: {label!r}"


# Test 9 — non-effectful internal state write is not over-governed
def test_internal_state_write_not_overgoverned():
    flow = _flow("f9", "Persist internal session context", {
        "action_intent": "update", "external_write": False, "mutates_source_system": False,
        "customer_or_patient_impacting": False, "classification": "state",
    })
    assert not _is_governed(flow)
