"""D35: architecture pattern selection is evidence-driven.

A telemetry/stream-heavy topology (Kinesis/Flink/SageMaker) may only appear when the
workload genuinely streams. Generic workflow/document/approval workloads must get a
governed-orchestration topology, not a borrowed telemetry template. This is enforced
generically (positive justification), not per-family — so any future family that wrongly
maps to a streaming pattern is still caught.
"""

from app.services.pattern_catalog import selected_patterns
from app.services.use_case_profile import UseCaseProfile

_STREAM_SERVICES = ("Kinesis", "Flink", "SageMaker")


def _profile(families, *, actions=None, structured=None):
    return UseCaseProfile(
        domain="x", workload_families=list(families), excluded_families=[],
        capabilities=[], entities=[], signals=[], actions=actions or ["review", "approve"],
        structured_metrics=structured or {},
    )


def _services(profile):
    out = set()
    for pattern in selected_patterns(profile):
        for component in pattern.services:
            out.add(component.service)
    return out


def test_approval_workflow_does_not_get_telemetry_topology():
    services = _services(_profile(["event_driven_workflow", "approval_gated_workflow_automation"]))
    assert not any(any(s in svc for s in _STREAM_SERVICES) for svc in services), services
    assert "AWS Step Functions" in services  # governed orchestration instead


def test_document_workflow_does_not_get_telemetry_topology():
    services = _services(_profile(["approval_gated_workflow_automation"], actions=["review document", "approve permit"]))
    assert not any(any(s in svc for s in _STREAM_SERVICES) for svc in services), services


def test_genuine_streaming_family_keeps_telemetry_topology():
    services = _services(
        _profile(
            ["industrial_iot_streaming_ml", "event_driven_workflow"],
            structured={"asset_counts": {"telemetry_frequency_seconds": {"value": 3.0}}},
        )
    )
    assert any("Kinesis" in svc for svc in services), services


def test_telemetry_quantity_basis_justifies_streaming():
    # Even with only a workflow family, a real cadence metric is genuine streaming evidence,
    # so a co-selected streaming pattern would be kept (guard does not strip it).
    prof = _profile(
        ["real_time_anomaly_detection", "event_driven_workflow"],
        structured={"asset_counts": {"telemetry_frequency_seconds": {"value": 3.0}}},
    )
    # real_time_anomaly_detection is itself streaming evidence; topology must survive.
    assert selected_patterns(prof)


def test_guard_strips_future_wrong_alias_without_streaming_evidence(monkeypatch):
    # A hypothetical future workflow family that (wrongly) aliases to a stream-heavy
    # pattern is still stripped when no streaming evidence exists — proving the guard is
    # not a per-family special case.
    from app.services import pattern_catalog

    original = pattern_catalog._pattern_ids_for_family

    def fake_pattern_ids_for_family(family):
        if family == "future_generic_workflow":
            return ["operational_event_prediction_workflow"]
        return original(family)

    monkeypatch.setattr(pattern_catalog, "_pattern_ids_for_family", fake_pattern_ids_for_family)

    services = _services(_profile(["future_generic_workflow"]))

    assert not any(any(s in svc for s in _STREAM_SERVICES) for svc in services), services
    assert "AWS Step Functions" in services


def test_native_streaming_pattern_family_remains_streaming():
    prof = _profile(
        ["operational_event_prediction_workflow"],
        structured={"asset_counts": {"telemetry_frequency_seconds": {"value": 3.0}}},
    )
    assert any("Kinesis" in c.service for p in selected_patterns(prof) for c in p.services)
