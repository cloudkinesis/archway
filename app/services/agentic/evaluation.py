from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.agentic.contracts import AgentLane
from app.services.agentic.provenance import MODEL_PROPOSED, can_unlock_readiness
from app.services.dossier_manifest import stable_json_hash

EvaluationScoreType = Literal["auto", "human", "mixed"]
EvaluationSeverity = Literal["critical", "warning", "advisory", "info"]
EvaluationExpectedSurface = Literal["raw", "audit_pack", "client_pack"]
EvaluationArtifactOutcome = Literal["solution_package", "directional_diagnostic_package", "unsupported_refusal_package"]
EvaluationPricingLabel = Literal["bound", "scenario_assumed", "ambiguous", "not_estimated", "heuristic", "directional"]
EvaluationDiagramBehavior = Literal["rendered", "fallback_disclosed", "omitted_disclosed", "human_review"]
EvaluationReadinessCap = Literal["demo_ready", "workshop_ready", "procurement_ready", "human_review"]


class EvaluationScenario(BaseModel):
    scenario_id: str
    title: str
    use_case: str
    domain: str
    expected_surface: EvaluationExpectedSurface
    expected_artifact_outcome: EvaluationArtifactOutcome
    required_lanes: list[AgentLane]
    expected_claim_kinds: list[str]
    expected_pricing_labels: list[EvaluationPricingLabel]
    expected_diagram_behavior: EvaluationDiagramBehavior
    expected_readiness_cap: EvaluationReadinessCap
    architecture_soundness_score_type: EvaluationScoreType = "human"
    notes: str

    @property
    def scenario_hash(self) -> str:
        return stable_json_hash(self.model_dump(mode="json"))


class EvaluationMetric(BaseModel):
    metric_id: str
    lane: AgentLane
    score_type: EvaluationScoreType
    value: Any = None
    max_value: float | None = None
    passed: bool
    reason: str


class EvaluationLaneScore(BaseModel):
    lane: AgentLane
    score_type: EvaluationScoreType
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    passed: bool
    confidence_label: str


class EvaluationFinding(BaseModel):
    scenario_id: str
    lane: AgentLane
    severity: EvaluationSeverity
    rule_id: str
    message: str
    artifact_ref: str | None = None


class EvaluationRunMetadata(BaseModel):
    battery_id: str = "d21-thin-open-world-v1"
    version: str = "d21_eval_battery_v1"
    scenario_count: int
    score_policy: str = "auto metrics must pass; human metrics require explicit review before client-facing agent output"
    generated_at: str | None = None


class EvaluationBatteryResult(BaseModel):
    battery_id: str
    scenarios: list[EvaluationScenario]
    lane_scores: list[EvaluationLaneScore]
    findings: list[EvaluationFinding] = Field(default_factory=list)
    reproducibility_hash: str
    generated_at: str | None = None
    version: str
    metadata: EvaluationRunMetadata

    @property
    def passed_auto_metrics(self) -> bool:
        return all(
            metric.passed
            for score in self.lane_scores
            for metric in score.metrics
            if metric.score_type == "auto"
        )

    @property
    def has_critical_findings(self) -> bool:
        return any(finding.severity == "critical" for finding in self.findings)


class ScenarioObservation(BaseModel):
    scenario_id: str
    aws_claims_have_evidence: bool
    missing_evidence_labeled: bool
    pricing_labels: list[EvaluationPricingLabel]
    procurement_pricing_presented: bool = False
    silent_generic_nonzero_pricing: bool = False
    reproducibility_hashes_present: bool = True
    deterministic_ordering: bool = True
    diagram_rendered: bool = False
    diagram_fallback_recorded: bool = False
    diagram_omission_recorded: bool = False
    client_pack_agent_content: bool = False
    repair_actions: list[str] = Field(default_factory=list)
    architecture_reviewed_by_human: bool = False
    model_proposed_unlocks_readiness: bool = False
    research_source_kind_correct: bool = True
    research_unsupported_claims_labeled: bool = True
    research_trace_hash_present: bool = True
    research_synthesis_reviewed_by_human: bool = False
    analyst_domain_workload_labeled: bool = True
    analyst_missing_facts_detected: bool = True
    analyst_conflicts_recorded: bool = True
    analyst_deterministic_facts_not_overwritten: bool = True
    analyst_trace_hash_present: bool = True
    analyst_candidate_services_not_architecture: bool = True
    analyst_pricing_drivers_not_bound: bool = True
    analyst_domain_reviewed_by_human: bool = False
    pricing_dimension_multi_service_coverage: bool = True
    pricing_dimension_source_kind_correct: bool = True
    pricing_dimension_missing_quantities_labeled: bool = True
    pricing_dimension_scenario_assumptions_labeled: bool = True
    pricing_dimension_ambiguities_labeled: bool = True
    pricing_dimension_no_silent_generic_fallback: bool = True
    pricing_dimension_trace_hash_present: bool = True
    pricing_dimension_no_deterministic_overwrite: bool = True
    pricing_dimension_no_readiness_promotion: bool = True
    pricing_dimension_no_client_surface: bool = True
    narrative_verified_claim_only: bool = True
    narrative_no_new_service_claim: bool = True
    narrative_no_new_price: bool = True
    narrative_no_new_readiness: bool = True
    narrative_unsupported_sentence_blocked: bool = True
    narrative_trace_hash_present: bool = True
    narrative_prose_reviewed_by_human: bool = False
    reviewer_additive_only: bool = True
    reviewer_deterministic_findings_not_removed: bool = True
    reviewer_duplicates_handled: bool = True
    reviewer_no_readiness_unlock: bool = True
    reviewer_no_client_surface: bool = True
    reviewer_target_artifact_coverage: bool = True
    reviewer_trace_hash_present: bool = True
    reviewer_usefulness_reviewed_by_human: bool = False


class EvaluationGateStatus(BaseModel):
    client_agent_output_allowed: bool
    reason: str
    required_human_lanes: list[AgentLane] = Field(default_factory=list)


def evaluation_gate_payload(result: EvaluationBatteryResult | None = None) -> dict[str, Any]:
    gate = is_client_agent_output_allowed(result)
    return {
        "status": "evaluated" if result is not None else "not_run_for_package",
        "battery_id": result.battery_id if result else "d21-thin-open-world-v1",
        "client_agent_output_allowed": gate.client_agent_output_allowed,
        "reason": gate.reason,
        "required_human_lanes": list(gate.required_human_lanes),
        "note": "Package export records the D21 gate state only; the standalone battery runner writes full scored results.",
    }


def evaluation_gate_markdown(payload: dict[str, Any]) -> str:
    return "\n".join([
        "# D21 Agentic Evaluation Summary",
        "",
        "This audit artifact records whether client-facing agent output is allowed for this package.",
        "",
        f"**Battery:** {payload.get('battery_id')}",
        f"**Status:** {payload.get('status')}",
        f"**Client-facing agent output allowed:** {'Yes' if payload.get('client_agent_output_allowed') else 'No'}",
        f"**Reason:** {payload.get('reason')}",
        "",
        "The evaluation battery does not call an LLM, does not call the network, and does not certify architecture soundness automatically.",
        "",
    ])


def default_observation_for_scenario(scenario: EvaluationScenario) -> ScenarioObservation:
    return ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=True,
        pricing_labels=list(scenario.expected_pricing_labels),
        diagram_rendered=scenario.expected_diagram_behavior == "rendered",
        diagram_fallback_recorded=scenario.expected_diagram_behavior == "fallback_disclosed",
        diagram_omission_recorded=scenario.expected_diagram_behavior == "omitted_disclosed",
        repair_actions=[
            "Refresh authoritative AWS evidence.",
            "Confirm pricing driver assumptions.",
            "Review diagram fallback or omitted view.",
        ],
    )


def run_evaluation_battery(
    scenarios: list[EvaluationScenario],
    observations: dict[str, ScenarioObservation] | None = None,
) -> EvaluationBatteryResult:
    observations = observations or {}
    all_metrics: list[EvaluationMetric] = []
    findings: list[EvaluationFinding] = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        observation = observations.get(scenario.scenario_id) or default_observation_for_scenario(scenario)
        metrics, scenario_findings = score_scenario(scenario, observation)
        all_metrics.extend(metrics)
        findings.extend(scenario_findings)
    lane_scores = _lane_scores(all_metrics)
    stable_payload = {
        "scenarios": [scenario.model_dump(mode="json") for scenario in sorted(scenarios, key=lambda item: item.scenario_id)],
        "lane_scores": [score.model_dump(mode="json") for score in lane_scores],
        "findings": [finding.model_dump(mode="json") for finding in sorted(findings, key=lambda item: (item.severity, item.scenario_id, item.rule_id))],
        "version": "d21_eval_battery_v1",
    }
    return EvaluationBatteryResult(
        battery_id="d21-thin-open-world-v1",
        scenarios=sorted(scenarios, key=lambda item: item.scenario_id),
        lane_scores=lane_scores,
        findings=sorted(findings, key=lambda item: (item.severity, item.scenario_id, item.rule_id)),
        reproducibility_hash=stable_json_hash(stable_payload),
        version="d21_eval_battery_v1",
        metadata=EvaluationRunMetadata(scenario_count=len(scenarios)),
    )


def score_scenario(scenario: EvaluationScenario, observation: ScenarioObservation) -> tuple[list[EvaluationMetric], list[EvaluationFinding]]:
    metrics = [
        _citation_metric(scenario, observation),
        _research_source_kind_metric(scenario, observation),
        _research_unsupported_labeling_metric(scenario, observation),
        _research_trace_reproducibility_metric(scenario, observation),
        _research_synthesis_human_metric(scenario, observation),
        _analyst_domain_workload_metric(scenario, observation),
        _analyst_missing_facts_metric(scenario, observation),
        _analyst_conflict_metric(scenario, observation),
        _analyst_no_overwrite_metric(scenario, observation),
        _analyst_trace_reproducibility_metric(scenario, observation),
        _analyst_candidate_service_metric(scenario, observation),
        _analyst_pricing_driver_metric(scenario, observation),
        _analyst_domain_human_metric(scenario, observation),
        _pricing_dimension_coverage_metric(scenario, observation),
        _pricing_dimension_source_kind_metric(scenario, observation),
        _pricing_dimension_missing_quantity_metric(scenario, observation),
        _pricing_dimension_scenario_assumption_metric(scenario, observation),
        _pricing_dimension_ambiguity_metric(scenario, observation),
        _pricing_dimension_no_fallback_metric(scenario, observation),
        _pricing_dimension_trace_metric(scenario, observation),
        _pricing_dimension_no_overwrite_metric(scenario, observation),
        _pricing_dimension_no_readiness_metric(scenario, observation),
        _pricing_dimension_client_surface_metric(scenario, observation),
        _narrative_verified_claim_metric(scenario, observation),
        _narrative_no_new_service_metric(scenario, observation),
        _narrative_no_new_price_metric(scenario, observation),
        _narrative_no_new_readiness_metric(scenario, observation),
        _narrative_unsupported_sentence_metric(scenario, observation),
        _narrative_trace_metric(scenario, observation),
        _narrative_prose_human_metric(scenario, observation),
        _reviewer_additive_metric(scenario, observation),
        _reviewer_deterministic_findings_metric(scenario, observation),
        _reviewer_duplicate_metric(scenario, observation),
        _reviewer_no_readiness_metric(scenario, observation),
        _reviewer_client_surface_metric(scenario, observation),
        _reviewer_target_metric(scenario, observation),
        _reviewer_trace_metric(scenario, observation),
        _reviewer_usefulness_human_metric(scenario, observation),
        _pricing_metric(scenario, observation),
        _reproducibility_metric(scenario, observation),
        _diagram_metric(scenario, observation),
        _client_surface_metric(scenario, observation),
        _repair_plan_metric(scenario, observation),
        _architecture_human_metric(scenario, observation),
        _model_proposed_readiness_metric(scenario, observation),
    ]
    findings = [
        finding
        for metric in metrics
        if not metric.passed
        for finding in [_finding_for_metric(scenario, metric)]
        if finding is not None
    ]
    return metrics, findings


def is_client_agent_output_allowed(result: EvaluationBatteryResult | None, *, human_reviewed_lanes: set[AgentLane] | None = None) -> EvaluationGateStatus:
    if result is None:
        return EvaluationGateStatus(client_agent_output_allowed=False, reason="No D21 evaluation battery result is available.")
    if result.has_critical_findings:
        return EvaluationGateStatus(client_agent_output_allowed=False, reason="Critical evaluation findings are present.")
    if not result.passed_auto_metrics:
        return EvaluationGateStatus(client_agent_output_allowed=False, reason="One or more required auto-scored metrics failed.")
    human_lanes = {
        score.lane
        for score in result.lane_scores
        if score.score_type in {"human", "mixed"} and any(metric.score_type == "human" for metric in score.metrics)
    }
    reviewed = human_reviewed_lanes or set()
    missing = sorted(human_lanes - reviewed)
    if missing:
        return EvaluationGateStatus(
            client_agent_output_allowed=False,
            reason="Human-scored lanes require explicit review before client-facing agent output.",
            required_human_lanes=missing,
        )
    return EvaluationGateStatus(client_agent_output_allowed=True, reason="Auto metrics passed and required human lanes were reviewed.")


def evaluation_report_markdown(result: EvaluationBatteryResult) -> str:
    lines = [
        "# D21 Thin Evaluation Battery",
        "",
        f"**Battery:** {result.battery_id}",
        f"**Version:** {result.version}",
        f"**Scenarios:** {len(result.scenarios)}",
        f"**Reproducibility hash:** `{result.reproducibility_hash}`",
        "",
        "## Lane Scores",
        "",
        "| Lane | Score Type | Passed | Confidence |",
        "|---|---|---:|---|",
    ]
    for score in result.lane_scores:
        lines.append(f"| {score.lane} | {score.score_type} | {'yes' if score.passed else 'no'} | {score.confidence_label} |")
    lines.extend(["", "## Scenarios", ""])
    for scenario in result.scenarios:
        lines.append(f"- **{scenario.scenario_id}** — {scenario.title} ({scenario.domain})")
    lines.extend(["", "## Findings", ""])
    if result.findings:
        for finding in result.findings:
            lines.append(f"- [{finding.severity}] `{finding.rule_id}` on {finding.scenario_id}/{finding.lane}: {finding.message}")
    else:
        lines.append("- No findings.")
    lines.extend([
        "",
        "## Authority Boundary",
        "",
        "This battery does not call an LLM, does not call the network, does not certify architecture soundness automatically, and does not grant client-facing agent authority by itself.",
        "",
    ])
    return "\n".join(lines)


def write_evaluation_outputs(result: EvaluationBatteryResult, output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / "result.json"
    report_path = out / "report.md"
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(evaluation_report_markdown(result), encoding="utf-8")
    return {"json": str(result_path), "markdown": str(report_path)}


def _citation_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    passed = observation.aws_claims_have_evidence or observation.missing_evidence_labeled
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.citation_coverage",
        lane="research",
        score_type="auto",
        value=1.0 if passed else 0.0,
        max_value=1.0,
        passed=passed,
        reason="AWS evidence is present or the missing evidence is explicitly labeled." if passed else "AWS/service claim evidence is missing and unlabeled.",
    )


def _research_source_kind_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.research_source_kind",
        lane="research",
        score_type="auto",
        value=observation.research_source_kind_correct,
        passed=observation.research_source_kind_correct,
        reason="Research evidence source kind matches the claim kind." if observation.research_source_kind_correct else "Research evidence source kind does not satisfy the claim kind.",
    )


def _research_unsupported_labeling_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.research_unsupported_labeling",
        lane="research",
        score_type="auto",
        value=observation.research_unsupported_claims_labeled,
        passed=observation.research_unsupported_claims_labeled,
        reason="Unsupported research claims are labeled as gaps/unsupported/needs review." if observation.research_unsupported_claims_labeled else "Unsupported research claims were not labeled.",
    )


def _research_trace_reproducibility_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.research_trace_reproducibility",
        lane="research",
        score_type="auto",
        value=observation.research_trace_hash_present,
        passed=observation.research_trace_hash_present,
        reason="Research trace carries stable hashes." if observation.research_trace_hash_present else "Research trace is missing stable hashes.",
    )


def _research_synthesis_human_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.research_synthesis_quality",
        lane="research",
        score_type="human",
        value="reviewed" if observation.research_synthesis_reviewed_by_human else "not_auto_scored",
        passed=observation.research_synthesis_reviewed_by_human,
        reason="Research synthesis quality is human-reviewed; no automatic insight-quality oracle is claimed." if observation.research_synthesis_reviewed_by_human else "Research synthesis quality requires human review and is not auto-scored.",
    )


def _analyst_domain_workload_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.analyst_domain_workload_labeling",
        lane="use_case_analyst",
        score_type="auto",
        value=observation.analyst_domain_workload_labeled,
        passed=observation.analyst_domain_workload_labeled,
        reason="Use-case analyst labels domain/workload candidates with confidence and provenance." if observation.analyst_domain_workload_labeled else "Use-case analyst candidates are missing domain/workload labels or provenance.",
    )


def _analyst_missing_facts_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.analyst_missing_facts",
        lane="use_case_analyst",
        score_type="auto",
        value=observation.analyst_missing_facts_detected,
        passed=observation.analyst_missing_facts_detected,
        reason="Missing use-case facts are detected and converted into questions." if observation.analyst_missing_facts_detected else "Missing use-case facts were not surfaced.",
    )


def _analyst_conflict_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.analyst_conflict_recording",
        lane="use_case_analyst",
        score_type="auto",
        value=observation.analyst_conflicts_recorded,
        passed=observation.analyst_conflicts_recorded,
        reason="Analyst conflicts with deterministic facts are recorded explicitly." if observation.analyst_conflicts_recorded else "Analyst conflicts with deterministic facts were not recorded.",
    )


def _analyst_no_overwrite_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.analyst_no_deterministic_overwrite",
        lane="use_case_analyst",
        score_type="auto",
        value=observation.analyst_deterministic_facts_not_overwritten,
        passed=observation.analyst_deterministic_facts_not_overwritten,
        reason="Analyst proposals cannot overwrite deterministic facts." if observation.analyst_deterministic_facts_not_overwritten else "Analyst proposal overwrote deterministic facts.",
    )


def _analyst_trace_reproducibility_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.analyst_trace_reproducibility",
        lane="use_case_analyst",
        score_type="auto",
        value=observation.analyst_trace_hash_present,
        passed=observation.analyst_trace_hash_present,
        reason="Use-case analyst trace carries stable hashes." if observation.analyst_trace_hash_present else "Use-case analyst trace is missing stable hashes.",
    )


def _analyst_candidate_service_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.analyst_candidate_services_not_architecture",
        lane="use_case_analyst",
        score_type="auto",
        value=observation.analyst_candidate_services_not_architecture,
        passed=observation.analyst_candidate_services_not_architecture,
        reason="Candidate services remain proposals and are not injected into architecture." if observation.analyst_candidate_services_not_architecture else "Candidate services altered architecture output.",
    )


def _analyst_pricing_driver_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.analyst_pricing_drivers_not_bound",
        lane="use_case_analyst",
        score_type="auto",
        value=observation.analyst_pricing_drivers_not_bound,
        passed=observation.analyst_pricing_drivers_not_bound,
        reason="Candidate pricing drivers remain proposals and are not bound into pricing math." if observation.analyst_pricing_drivers_not_bound else "Candidate pricing drivers affected pricing math.",
    )


def _analyst_domain_human_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.analyst_domain_appropriateness",
        lane="use_case_analyst",
        score_type="human",
        value="reviewed" if observation.analyst_domain_reviewed_by_human else "not_auto_scored",
        passed=observation.analyst_domain_reviewed_by_human,
        reason="Use-case/domain appropriateness is human-reviewed; no automatic truth oracle is claimed." if observation.analyst_domain_reviewed_by_human else "Use-case/domain appropriateness requires human review and is not auto-scored.",
    )


def _pricing_dimension_coverage_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_multi_service_coverage",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_multi_service_coverage,
        passed=observation.pricing_dimension_multi_service_coverage,
        reason="Pricing-dimension lane covers multiple service patterns as candidate dimensions." if observation.pricing_dimension_multi_service_coverage else "Pricing-dimension lane lacks multi-service coverage.",
    )


def _pricing_dimension_source_kind_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_source_kind",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_source_kind_correct,
        passed=observation.pricing_dimension_source_kind_correct,
        reason="Pricing-dimension evidence/source requirements are labeled correctly." if observation.pricing_dimension_source_kind_correct else "Pricing-dimension evidence/source requirements are mislabeled.",
    )


def _pricing_dimension_missing_quantity_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_missing_quantity",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_missing_quantities_labeled,
        passed=observation.pricing_dimension_missing_quantities_labeled,
        reason="Missing customer quantities are labeled instead of priced silently." if observation.pricing_dimension_missing_quantities_labeled else "Missing quantities were not labeled.",
    )


def _pricing_dimension_scenario_assumption_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_scenario_assumptions",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_scenario_assumptions_labeled,
        passed=observation.pricing_dimension_scenario_assumptions_labeled,
        reason="Scenario assumptions are labeled as scenario assumptions." if observation.pricing_dimension_scenario_assumptions_labeled else "Scenario assumptions were not labeled.",
    )


def _pricing_dimension_ambiguity_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_ambiguity",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_ambiguities_labeled,
        passed=observation.pricing_dimension_ambiguities_labeled,
        reason="Ambiguous dimensions are labeled and not bound." if observation.pricing_dimension_ambiguities_labeled else "Ambiguous dimensions were not labeled.",
    )


def _pricing_dimension_no_fallback_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_no_silent_fallback",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_no_silent_generic_fallback,
        passed=observation.pricing_dimension_no_silent_generic_fallback,
        reason="Generic fallback is not treated as authoritative or bound." if observation.pricing_dimension_no_silent_generic_fallback else "Generic fallback was treated as authoritative pricing.",
    )


def _pricing_dimension_trace_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_trace_reproducibility",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_trace_hash_present,
        passed=observation.pricing_dimension_trace_hash_present,
        reason="Pricing-dimension trace carries stable hashes." if observation.pricing_dimension_trace_hash_present else "Pricing-dimension trace is missing stable hashes.",
    )


def _pricing_dimension_no_overwrite_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_no_deterministic_overwrite",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_no_deterministic_overwrite,
        passed=observation.pricing_dimension_no_deterministic_overwrite,
        reason="Pricing-dimension proposals cannot overwrite deterministic pricing." if observation.pricing_dimension_no_deterministic_overwrite else "Pricing-dimension proposal overwrote deterministic pricing.",
    )


def _pricing_dimension_no_readiness_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_no_readiness_promotion",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_no_readiness_promotion,
        passed=observation.pricing_dimension_no_readiness_promotion,
        reason="Pricing-dimension output cannot promote readiness." if observation.pricing_dimension_no_readiness_promotion else "Pricing-dimension output promoted readiness.",
    )


def _pricing_dimension_client_surface_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_dimension_client_surface",
        lane="pricing_dimension",
        score_type="auto",
        value=observation.pricing_dimension_no_client_surface,
        passed=observation.pricing_dimension_no_client_surface,
        reason="Pricing-dimension output stays out of client_pack." if observation.pricing_dimension_no_client_surface else "Pricing-dimension output reached client_pack.",
    )


def _narrative_verified_claim_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.narrative_verified_claim_only",
        lane="narrative",
        score_type="auto",
        value=observation.narrative_verified_claim_only,
        passed=observation.narrative_verified_claim_only,
        reason="Narrative proposals are limited to verified, assumed, not-estimated, or narrative-only sentences." if observation.narrative_verified_claim_only else "Narrative proposal included unsupported factual sentences.",
    )


def _narrative_no_new_service_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.narrative_no_new_service_claim",
        lane="narrative",
        score_type="auto",
        value=observation.narrative_no_new_service_claim,
        passed=observation.narrative_no_new_service_claim,
        reason="Narrative proposal does not introduce new service claims." if observation.narrative_no_new_service_claim else "Narrative proposal introduced a service not present in deterministic architecture.",
    )


def _narrative_no_new_price_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.narrative_no_new_price",
        lane="narrative",
        score_type="auto",
        value=observation.narrative_no_new_price,
        passed=observation.narrative_no_new_price,
        reason="Narrative proposal does not introduce or alter pricing numbers." if observation.narrative_no_new_price else "Narrative proposal introduced or altered pricing numbers.",
    )


def _narrative_no_new_readiness_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.narrative_no_new_readiness",
        lane="narrative",
        score_type="auto",
        value=observation.narrative_no_new_readiness,
        passed=observation.narrative_no_new_readiness,
        reason="Narrative proposal does not promote readiness." if observation.narrative_no_new_readiness else "Narrative proposal promoted readiness.",
    )


def _narrative_unsupported_sentence_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.narrative_unsupported_sentence_blocked",
        lane="narrative",
        score_type="auto",
        value=observation.narrative_unsupported_sentence_blocked,
        passed=observation.narrative_unsupported_sentence_blocked,
        reason="Unsupported narrative sentences are blocked from client surfaces." if observation.narrative_unsupported_sentence_blocked else "Unsupported narrative sentence was not blocked.",
    )


def _narrative_trace_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.narrative_trace_reproducibility",
        lane="narrative",
        score_type="auto",
        value=observation.narrative_trace_hash_present,
        passed=observation.narrative_trace_hash_present,
        reason="Narrative trace carries stable hashes." if observation.narrative_trace_hash_present else "Narrative trace is missing stable hashes.",
    )


def _narrative_prose_human_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.narrative_prose_quality",
        lane="narrative",
        score_type="human",
        value="reviewed" if observation.narrative_prose_reviewed_by_human else "not_auto_scored",
        passed=observation.narrative_prose_reviewed_by_human,
        reason="Narrative prose quality is human-reviewed; no automatic prose-quality oracle is claimed." if observation.narrative_prose_reviewed_by_human else "Narrative prose quality requires human review and is not auto-scored.",
    )


def _reviewer_additive_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reviewer_additive_only",
        lane="reviewer",
        score_type="auto",
        value=observation.reviewer_additive_only,
        passed=observation.reviewer_additive_only,
        reason="Reviewer-agent findings are additive only." if observation.reviewer_additive_only else "Reviewer-agent output removed or rewrote findings.",
    )


def _reviewer_deterministic_findings_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reviewer_deterministic_findings_not_removed",
        lane="reviewer",
        score_type="auto",
        value=observation.reviewer_deterministic_findings_not_removed,
        passed=observation.reviewer_deterministic_findings_not_removed,
        reason="Deterministic reviewer findings remain authoritative." if observation.reviewer_deterministic_findings_not_removed else "Deterministic reviewer findings were removed or downgraded.",
    )


def _reviewer_duplicate_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reviewer_duplicate_handling",
        lane="reviewer",
        score_type="auto",
        value=observation.reviewer_duplicates_handled,
        passed=observation.reviewer_duplicates_handled,
        reason="Duplicate reviewer findings are labeled instead of added repeatedly." if observation.reviewer_duplicates_handled else "Duplicate reviewer findings were not handled.",
    )


def _reviewer_no_readiness_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reviewer_no_readiness_unlock",
        lane="reviewer",
        score_type="auto",
        value=observation.reviewer_no_readiness_unlock,
        passed=observation.reviewer_no_readiness_unlock,
        reason="Reviewer-agent output cannot unlock readiness." if observation.reviewer_no_readiness_unlock else "Reviewer-agent output unlocked readiness.",
    )


def _reviewer_client_surface_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reviewer_client_surface",
        lane="reviewer",
        score_type="auto",
        value=observation.reviewer_no_client_surface,
        passed=observation.reviewer_no_client_surface,
        reason="Reviewer-agent output stays out of client_pack." if observation.reviewer_no_client_surface else "Reviewer-agent output reached client_pack.",
    )


def _reviewer_target_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reviewer_target_artifact_coverage",
        lane="reviewer",
        score_type="auto",
        value=observation.reviewer_target_artifact_coverage,
        passed=observation.reviewer_target_artifact_coverage,
        reason="Reviewer findings carry target artifact or section context." if observation.reviewer_target_artifact_coverage else "Reviewer findings lack target artifact coverage.",
    )


def _reviewer_trace_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reviewer_trace_reproducibility",
        lane="reviewer",
        score_type="auto",
        value=observation.reviewer_trace_hash_present,
        passed=observation.reviewer_trace_hash_present,
        reason="Reviewer trace carries stable hashes." if observation.reviewer_trace_hash_present else "Reviewer trace is missing stable hashes.",
    )


def _reviewer_usefulness_human_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reviewer_finding_usefulness",
        lane="reviewer",
        score_type="human",
        value="reviewed" if observation.reviewer_usefulness_reviewed_by_human else "not_auto_scored",
        passed=observation.reviewer_usefulness_reviewed_by_human,
        reason="Reviewer finding usefulness is human-reviewed; no automatic usefulness oracle is claimed." if observation.reviewer_usefulness_reviewed_by_human else "Reviewer finding usefulness requires human review and is not auto-scored.",
    )


def _pricing_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    observed = set(observation.pricing_labels)
    expected = set(scenario.expected_pricing_labels)
    passed = bool(observed & expected) and not observation.procurement_pricing_presented and not observation.silent_generic_nonzero_pricing
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.pricing_label",
        lane="pricing",
        score_type="auto",
        value=sorted(observed),
        passed=passed,
        reason="Pricing labels are explicit and do not present unconfirmed totals as procurement-grade." if passed else "Pricing label safety failed.",
    )


def _reproducibility_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    passed = observation.reproducibility_hashes_present and observation.deterministic_ordering
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.reproducibility",
        lane="deterministic_baseline",
        score_type="auto",
        value=passed,
        passed=passed,
        reason="Hashes exist and output ordering is deterministic." if passed else "Missing hashes or nondeterministic ordering.",
    )


def _diagram_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    passed = observation.diagram_rendered or observation.diagram_fallback_recorded or observation.diagram_omission_recorded
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.diagram_render_or_disclose",
        lane="diagram_planner",
        score_type="auto",
        value=scenario.expected_diagram_behavior,
        passed=passed,
        reason="Diagram is rendered or fallback/omission is disclosed." if passed else "Diagram is missing without a fallback or omission ledger.",
    )


def _client_surface_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    passed = not observation.client_pack_agent_content
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.client_surface_protection",
        lane="narrative",
        score_type="auto",
        value=not observation.client_pack_agent_content,
        passed=passed,
        reason="No agent proposal content reached client_pack." if passed else "Agent proposal content reached client_pack before battery gate approval.",
    )


def _repair_plan_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    passed = bool(observation.repair_actions)
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.repair_plan",
        lane="repair_planner",
        score_type="auto",
        value=len(observation.repair_actions),
        passed=passed,
        reason="Repair planner produced actionable next steps." if passed else "Missing repair-plan actions for incomplete evidence/pricing/diagram/readiness signals.",
    )


def _architecture_human_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.architecture_soundness",
        lane="architecture",
        score_type="human",
        value="reviewed" if observation.architecture_reviewed_by_human else "not_auto_scored",
        passed=observation.architecture_reviewed_by_human,
        reason="Architecture soundness is human-reviewed; no deterministic oracle is claimed." if observation.architecture_reviewed_by_human else "Architecture soundness requires human review and is not auto-scored.",
    )


def _model_proposed_readiness_metric(scenario: EvaluationScenario, observation: ScenarioObservation) -> EvaluationMetric:
    passed = (not observation.model_proposed_unlocks_readiness) and not can_unlock_readiness(MODEL_PROPOSED)
    return EvaluationMetric(
        metric_id=f"{scenario.scenario_id}.model_proposed_readiness",
        lane="architecture",
        score_type="auto",
        value=not observation.model_proposed_unlocks_readiness,
        passed=passed,
        reason="model_proposed cannot unlock readiness." if passed else "model_proposed was treated as readiness authority.",
    )


def _finding_for_metric(scenario: EvaluationScenario, metric: EvaluationMetric) -> EvaluationFinding | None:
    if metric.score_type == "human":
        return EvaluationFinding(
            scenario_id=scenario.scenario_id,
            lane=metric.lane,
            severity="advisory",
            rule_id=metric.metric_id,
            message=metric.reason,
        )
    return EvaluationFinding(
        scenario_id=scenario.scenario_id,
        lane=metric.lane,
        severity="critical",
        rule_id=metric.metric_id,
        message=metric.reason,
    )


def _lane_scores(metrics: list[EvaluationMetric]) -> list[EvaluationLaneScore]:
    out: list[EvaluationLaneScore] = []
    lanes = sorted({metric.lane for metric in metrics})
    for lane in lanes:
        lane_metrics = [metric for metric in metrics if metric.lane == lane]
        score_types = {metric.score_type for metric in lane_metrics}
        score_type: EvaluationScoreType = "mixed" if len(score_types) > 1 else next(iter(score_types))
        human_metrics = [metric for metric in lane_metrics if metric.score_type == "human"]
        passed = all(metric.passed for metric in lane_metrics)
        if human_metrics and not all(metric.passed for metric in human_metrics):
            confidence = "requires_human_review"
        elif passed:
            confidence = "auto_passed"
        else:
            confidence = "auto_failed"
        out.append(EvaluationLaneScore(lane=lane, score_type=score_type, metrics=lane_metrics, passed=passed, confidence_label=confidence))
    return out
