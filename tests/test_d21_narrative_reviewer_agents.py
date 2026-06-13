from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.evaluation import ScenarioObservation, run_evaluation_battery, score_scenario
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.agentic.narrative_agent import (
    DeterministicFixtureNarrativeProvider,
    LiveNarrativeProvider,
    NarrativeRewriteProposal,
    NarrativeSentenceClaim,
    build_narrative_context,
    build_narrative_trace,
    validate_narrative_proposal,
)
from app.services.agentic.provenance import MODEL_PROPOSED, can_unlock_readiness
from app.services.agentic.reviewer_agent import (
    DeterministicFixtureReviewerProvider,
    LiveReviewerProvider,
    ReviewerFindingProposal,
    build_reviewer_context,
    build_reviewer_trace,
    validate_reviewer_findings,
)
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine
from tests.test_d21_agentic_foundation import _load_verifier


def test_narrative_and_reviewer_flags_default_false_and_providers_are_not_invoked(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_NARRATIVE", raising=False)
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_REVIEWER", raising=False)
    get_settings.cache_clear()

    class ExplodingNarrativeProvider:
        provider_name = "explode"

        def propose(self, context):  # pragma: no cover
            raise AssertionError("narrative provider should not be invoked")

        def validate(self, proposal, deterministic_context):  # pragma: no cover
            raise AssertionError("narrative provider should not be invoked")

    class ExplodingReviewerProvider:
        provider_name = "explode"

        def propose_findings(self, context):  # pragma: no cover
            raise AssertionError("reviewer provider should not be invoked")

        def validate_findings(self, findings, deterministic_context):  # pragma: no cover
            raise AssertionError("reviewer provider should not be invoked")

    settings = get_settings()
    narrative = build_narrative_trace(settings=settings, context={}, provider=ExplodingNarrativeProvider())
    reviewer = build_reviewer_trace(settings=settings, context={}, provider=ExplodingReviewerProvider())

    assert settings.enable_agentic_narrative is False
    assert settings.enable_agentic_reviewer is False
    assert narrative.enabled is False
    assert narrative.provider == "disabled"
    assert narrative.decisions[0].decision == "rejected"
    assert reviewer.enabled is False
    assert reviewer.provider == "disabled"
    assert reviewer.decisions[0].decision == "rejected"


def test_live_narrative_and_reviewer_providers_are_unavailable():
    with pytest.raises(NotImplementedError):
        LiveNarrativeProvider().propose({})
    with pytest.raises(NotImplementedError):
        LiveReviewerProvider().propose_findings({})


def test_narrative_fixture_provider_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_NARRATIVE", "true")
    get_settings.cache_clear()
    context = build_narrative_context(
        report={"summary": "Original.", "metadata": {"customer_readiness": {"tier": "demo_ready"}}},
        pricing={"expected_monthly_usd": 42, "metadata": {"pricing_driver_closure": {"missing_drivers": ["monthly_requests"]}}},
        architectures=[{"components": [{"service": "Amazon Lex"}]}],
    )
    provider = DeterministicFixtureNarrativeProvider()

    trace = build_narrative_trace(settings=get_settings(), context=context, provider=provider)
    again = build_narrative_trace(settings=get_settings(), context=context, provider=provider)

    assert trace.enabled is True
    assert trace.provider == "deterministic_fixture"
    assert trace.input_hash == again.input_hash
    assert trace.output_hash == again.output_hash
    assert trace.proposal.output_hash == again.proposal.output_hash
    assert all(decision.decision == "accepted_for_audit" for decision in trace.decisions)
    assert all(not sentence.can_render_client for sentence in trace.proposal.sentence_claim_map)


def test_narrative_validation_blocks_unsupported_new_claims_price_and_readiness():
    context = {
        "known_services": ["Amazon Lex"],
        "pricing": {"expected_monthly_usd": 42},
        "readiness": {"tier": "demo_ready"},
    }
    proposal = NarrativeRewriteProposal(
        proposal_id="narrative_bad",
        target_artifact="01-solution-brief.md",
        target_section="Executive summary",
        original_text_hash="sha256:original",
        proposed_text="Amazon Textract will process claims. The package costs $999. It is procurement_ready.",
        sentence_claim_map=[
            NarrativeSentenceClaim(
                sentence_id="s1",
                text="Amazon Textract will process claims.",
                claim_kind="architecture",
                support_status="verified",
                evidence_refs=["architecture.components"],
            ),
            NarrativeSentenceClaim(
                sentence_id="s2",
                text="The package costs $999.",
                claim_kind="pricing",
                support_status="verified",
                evidence_refs=["03-pricing.md"],
            ),
            NarrativeSentenceClaim(
                sentence_id="s3",
                text="It is procurement_ready.",
                claim_kind="readiness",
                support_status="verified",
                evidence_refs=["customer_readiness"],
            ),
            NarrativeSentenceClaim(
                sentence_id="s4",
                text="This should read better.",
                claim_kind="narrative_only",
                support_status="narrative_only",
            ),
        ],
        input_hash="sha256:input",
        output_hash="sha256:output",
    )

    trace = validate_narrative_proposal(proposal, context, provider_name="unit")
    decisions = {decision.sentence_id: decision.decision for decision in trace.decisions}
    statuses = {sentence.sentence_id: sentence.support_status for sentence in trace.proposal.sentence_claim_map}

    assert decisions["s1"] == "client_blocked"
    assert decisions["s2"] == "rejected"
    assert decisions["s3"] == "rejected"
    assert decisions["s4"] == "accepted_for_audit"
    assert statuses["s1"] == "unsupported"
    assert statuses["s2"] == "conflict"
    assert statuses["s3"] == "conflict"
    assert trace.proposal.unsupported_sentence_ids == ["s1", "s2", "s3"]
    assert not can_unlock_readiness(MODEL_PROPOSED)


def test_reviewer_fixture_provider_is_deterministic_and_additive(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_REVIEWER", "true")
    get_settings.cache_clear()
    context = build_reviewer_context(report={}, pricing={}, reviewer_report={"findings": [{"finding_id": "deterministic_1"}]})
    provider = DeterministicFixtureReviewerProvider()

    trace = build_reviewer_trace(settings=get_settings(), context=context, provider=provider)
    again = build_reviewer_trace(settings=get_settings(), context=context, provider=provider)

    assert trace.enabled is True
    assert trace.provider == "deterministic_fixture"
    assert trace.input_hash == again.input_hash
    assert trace.output_hash == again.output_hash
    assert len(trace.accepted_findings) == 2
    assert all(decision.decision == "added" for decision in trace.decisions)
    assert trace.deterministic_reviewer_ref["finding_ids"] == ["deterministic_1"]


def test_reviewer_validation_marks_duplicates_rejects_readiness_and_downgrades_blockers():
    context = {"deterministic_reviewer": {"finding_ids": ["existing"], "finding_count": 1}}
    findings = [
        ReviewerFindingProposal(
            finding_id="existing",
            severity="warning",
            category="evidence_gap",
            target_artifact="06-evidence-appendix.md",
            message="Duplicate deterministic finding.",
        ),
        ReviewerFindingProposal(
            finding_id="readiness_attempt",
            severity="advisory",
            category="readiness_overpromotion",
            target_artifact="01-solution-brief.md",
            message="Attempted readiness mutation.",
            can_downgrade_readiness=True,
        ),
        ReviewerFindingProposal(
            finding_id="agent_blocker",
            severity="blocker",
            category="pricing_overprecision",
            target_artifact="03-pricing.md",
            message="Agent wants blocker severity.",
        ),
    ]

    trace = validate_reviewer_findings(findings, context, provider_name="unit")
    decisions = {decision.finding_id: decision.decision for decision in trace.decisions}

    assert decisions["existing"] == "duplicate"
    assert decisions["readiness_attempt"] == "rejected"
    assert decisions["agent_blocker"] == "downgraded"
    assert trace.accepted_findings[0].finding_id == "agent_blocker"
    assert trace.accepted_findings[0].severity == "warning"
    assert [item.finding_id for item in trace.duplicate_findings] == ["existing"]
    assert [item.finding_id for item in trace.rejected_findings] == ["readiness_attempt"]


def test_export_emits_narrative_and_reviewer_raw_audit_only_and_verifier_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_NARRATIVE", raising=False)
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_REVIEWER", raising=False)
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = store.create("Build a retail assistant for order questions.", brief)
    service = ExportPackageService()

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)
    export_dir = service.artifacts.session_root(session.id) / "exports" / bundle.name

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        narrative = json.loads(archive.read("raw/agent_narrative_trace.json").decode("utf-8"))
        reviewer = json.loads(archive.read("raw/agent_reviewer_trace.json").decode("utf-8"))
        reviewer_findings = json.loads(archive.read("raw/agent_reviewer_findings.json").decode("utf-8"))

    assert "raw/agent_narrative_trace.json" in names
    assert "raw/agent_narrative_proposals.json" in names
    assert "raw/agent_reviewer_trace.json" in names
    assert "raw/agent_reviewer_findings.json" in names
    assert "audit_pack/agentic-narrative-proposals.md" in names
    assert "audit_pack/agentic-reviewer-findings.md" in names
    assert "client_pack/agentic-narrative-proposals.md" not in names
    assert "client_pack/agentic-reviewer-findings.md" not in names
    assert narrative["enabled"] is False
    assert narrative["provider"] == "disabled"
    assert reviewer["enabled"] is False
    assert reviewer["provider"] == "disabled"
    assert reviewer_findings == []

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "raw/agent_narrative_trace.json" in inventory_paths
    assert "audit_pack/agentic-reviewer-findings.md" in inventory_paths

    ok, errors, _ = _load_verifier().verify(export_dir)
    assert ok, errors

    (export_dir / "raw/agent_narrative_trace.json").write_text("[]\n", encoding="utf-8")
    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_narrative_trace.json" in error for error in errors)


def test_evaluation_battery_scores_narrative_and_reviewer_safety():
    scenario = thin_evaluation_scenarios()[0]
    observation = ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=True,
        pricing_labels=["scenario_assumed"],
        diagram_fallback_recorded=True,
        repair_actions=["Ask for volume"],
        narrative_verified_claim_only=False,
        narrative_no_new_service_claim=False,
        narrative_no_new_price=False,
        narrative_no_new_readiness=False,
        narrative_unsupported_sentence_blocked=False,
        narrative_trace_hash_present=False,
        reviewer_additive_only=False,
        reviewer_deterministic_findings_not_removed=False,
        reviewer_duplicates_handled=False,
        reviewer_no_readiness_unlock=False,
        reviewer_no_client_surface=False,
        reviewer_target_artifact_coverage=False,
        reviewer_trace_hash_present=False,
    )

    metrics, findings = score_scenario(scenario, observation)
    failed = {metric.metric_id.rsplit(".", 1)[1] for metric in metrics if not metric.passed and metric.score_type == "auto"}

    assert "narrative_verified_claim_only" in failed
    assert "narrative_unsupported_sentence_blocked" in failed
    assert "reviewer_additive_only" in failed
    assert "reviewer_deterministic_findings_not_removed" in failed
    assert any(finding.lane == "narrative" and finding.severity == "critical" for finding in findings)
    assert any(finding.lane == "reviewer" and finding.severity == "critical" for finding in findings)

    result = run_evaluation_battery([scenario])
    narrative_score = next(item for item in result.lane_scores if item.lane == "narrative")
    reviewer_score = next(item for item in result.lane_scores if item.lane == "reviewer")
    assert narrative_score.score_type == "mixed"
    assert narrative_score.confidence_label == "requires_human_review"
    assert reviewer_score.score_type == "mixed"
    assert reviewer_score.confidence_label == "requires_human_review"
