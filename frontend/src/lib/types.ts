export type HealthStatus = "ready" | "degraded" | "failed";

export interface HealthCheckResult {
  id: string;
  label: string;
  status: HealthStatus;
  required: boolean;
  reason: string;
  details: Record<string, unknown>;
}

export interface HealthSummary {
  status: HealthStatus;
  can_continue: boolean;
  limited_mode_available: boolean;
  checks: HealthCheckResult[];
}

export interface BuildStatusSummary {
  status: HealthStatus;
  generated_at: string;
  items: HealthCheckResult[];
}

export interface Session {
  id: string;
  name: string;
  status: string;
  active_phase: string;
  initial_use_case: string;
  current_summary?: UseCaseBrief;
  updated_at: string;
}

export interface UseCaseBrief {
  title: string;
  raw_use_case: string;
  refined_problem_statement: string;
  industry?: string | null;
  business_goals: string[];
  users: { name: string; description: string }[];
  ai_capabilities: { name: string; risk_level: string; human_approval_required: boolean }[];
  data_sources: { name: string; sensitivity: string }[];
  integrations: { name: string; direction: string }[];
  assumptions: { id: string; text: string; reason: string; impact: string; confidence: string }[];
  open_questions: { id: string; text: string; impact: string }[];
  poc_scope: string;
  production_scope: string;
  use_case_profile?: Record<string, unknown>;
}

export interface SynthesisQuestion {
  id: string;
  prompt: string;
  why_it_matters: string;
  options: string[];
  recommended_option: string;
}

export interface Readiness {
  can_proceed: boolean;
  confidence_label: string;
  critical_gaps: unknown[];
  important_gaps: unknown[];
  recommended_minimum_questions: SynthesisQuestion[];
}

export interface ResearchReport {
  executive_verdict: string;
  proceed_recommendation: string;
  use_case_interpretation: string;
  feasibility_analysis: string;
  viability_analysis: string;
  competitor_analysis: string;
  recommended_poc: string;
  recommended_production_direction: string;
  pricing_analysis: {
    region: string;
    low_monthly_usd: number;
    expected_monthly_usd: number;
    high_monthly_usd: number;
    line_items: Array<{ service: string; unit_basis: string; expected_monthly_usd: number; evidence_ids: string[]; assumptions?: string[] }>;
    main_cost_drivers: string[];
    unknown_variables: string[];
    metadata?: {
      pricing_maturity?: string;
      pricing_driver_closure?: PricingDriverClosureReport;
      [key: string]: unknown;
    };
  };
  aws_service_recommendations: Array<{ service: string; purpose: string; rationale: string; alternatives_considered: string[]; evidence_ids: string[] }>;
  risks: Array<{ title: string; severity: string; mitigation: string }>;
  evidence_items: Array<{ id: string; source_type: string; title: string; quote_or_summary: string; confidence: string }>;
  evidence_assessments: Array<{ evidence_id: string; source_type: string; trust_score: number; trust_label: string; rationale: string; use_limitations: string }>;
  facts: Array<{ id: string; text: string; evidence_ids: string[]; confidence: string; citation_status: string }>;
  recommendations: Array<{ id: string; text: string; evidence_ids: string[]; confidence: string; citation_status: string }>;
  uncertainties: Array<{ id: string; text: string; evidence_ids: string[]; confidence: string; citation_status: string }>;
  citation_coverage?: { total_claims: number; cited_claims: number; uncited_claims: number; coverage_percent: number; passed: boolean; warnings: string[] } | null;
  metadata?: Record<string, unknown>;
}

export interface ResearchNarrativeSection {
  id: string;
  title: string;
  markdown: string;
}

export interface ResearchNarrative {
  executive_summary_markdown: string;
  sections: ResearchNarrativeSection[];
  quality_score?: Record<string, unknown>;
  top_validation_gates: string[];
}

export interface ResearchDigest {
  headline: string;
  decision: string;
  one_minute_read: string[];
  aws_direction: string[];
  governance_boundaries: string[];
  pricing_snapshot: string;
  pricing_caveats: string[];
  top_risks: string[];
  validate_next: string[];
  source_chips: Array<{ title: string; source_type: string; confidence: string }>;
  generated_by: string;
  warnings: string[];
}

export interface ResearchViewModel {
  session_id: string;
  revision_id: string;
  generated_at: string;
  model: string;
  verdict: { label: string; value: string; tone: string };
  readiness: { label: string; value: string; tone: string };
  pricing_confidence: { label: string; value: string; tone: string };
  evidence_quality: { label: string; value: string; tone: string };
  competitor_scan_status: { label: string; value: string; tone: string };
  executive_briefing: {
    headline: string;
    one_minute_read: string[];
    aws_direction: string[];
    governance_boundary: string[];
    top_risks: string[];
    validate_next: string[];
  };
  overview: {
    use_case_interpretation: string[];
    understood: string[];
    confirmed: string[];
    assumed: string[];
    open_items: string[];
    poc_path: string[];
    production_path: string[];
  };
  architecture_rationale: {
    pattern: string;
    poc_recommendation: string[];
    production_recommendation: string[];
    service_groups: Array<{ group: string; service: string; role: string; why_selected: string; alternatives: string[]; validation_needed: string; evidence_summary: string }>;
    tradeoffs: string[];
    do_not_build_first: string[];
  };
  pricing_poc: PricingViewModel;
  pricing_production: PricingViewModel;
  competitor_scan: {
    status: "completed" | "not_run" | "skipped" | "failed";
    tavily_enabled: boolean;
    scan_enabled: boolean;
    budget: number;
    queries_attempted: number;
    queries_executed: number;
    results_returned: number;
    results_used: number;
    query_plan: string[];
    analysis_summary: string[];
    aws_positioning_implications: string[];
    skipped_reason?: string | null;
    failure_reason?: string | null;
    competitors: Array<{ name: string; type: string; relevance: string; strengths: string[]; weaknesses: string[]; impact: string; source: string }>;
  };
  risks: Array<{ group: string; title: string; severity: string; why_it_matters: string; basis: string; mitigation: string; validation_owner: string; blocks_procurement: boolean; blocks_diagram_finalization: boolean }>;
  validation_items: string[];
  evidence_summary: {
    top_sources: EvidenceViewItem[];
    source_counts: Record<string, number>;
    confidence_distribution: Record<string, number>;
    claim_coverage: string;
    evidence_authority: string;
    last_refreshed: string;
    evidence_items_for_debug: EvidenceViewItem[];
  };
  raw_debug_refs: Record<string, string>;
}

export interface PricingViewModel {
  phase: "poc" | "production";
  headline_safe: boolean;
  procurement_ready: boolean;
  monthly_low: string;
  monthly_expected: string;
  monthly_high: string;
  confidence: string;
  sku_backed_subtotal: string;
  directional_subtotal: string;
  heuristic_subtotal: string;
  excluded_costs: string[];
  last_refreshed: string;
  assumptions: Array<{ assumption: string; value: string; unit: string; source: string; confidence: string; used_by: string; notes: string }>;
  line_items: Array<{ service: string; architecture_role: string; cost_category: string; quantity: string; unit: string; rate: string; monthly_subtotal: string; pricing_basis: string; confidence: string; trace_summary: string; trace: Record<string, unknown> }>;
  readiness_findings: string[];
}

export interface EvidenceViewItem {
  title: string;
  source_type: string;
  confidence: string;
  used_for: string;
  url?: string | null;
  debug_id?: string | null;
}

export interface MissingPricingDriver {
  driver_name: string;
  display_name: string;
  why_needed: string;
  impact_area: string;
  required_for_headline_pricing: boolean;
}

export interface ScenarioProfile {
  id: string;
  label: string;
  description: string;
  intended_use: string;
  readiness_impact: string;
}

export interface PricingDriverClosureReport {
  workload_family: string;
  status: string;
  pricing_maturity: string;
  confirmed_drivers: string[];
  assumed_drivers: string[];
  missing_drivers: MissingPricingDriver[];
  headline_pricing_allowed: boolean;
  directional_scenario_allowed: boolean;
  procurement_ready: boolean;
  scenario_profile_used?: string | null;
  recommended_next_action: string;
  next_validation_steps: string[];
}

export interface PricingCheckpoint {
  workload_family: string;
  message: string;
  scenario_profiles: ScenarioProfile[];
  closure_report: PricingDriverClosureReport;
}

export interface ArchitectureSpec {
  id: string;
  mode: "poc" | "production";
  title: string;
  summary: string;
  selected_services: Array<{ service: string; purpose: string; rationale: string; alternatives_considered: string[] }>;
  security_controls: Array<{ name: string; rationale: string }>;
  observability_controls: Array<{ name: string; rationale: string }>;
  scaling_strategy: string;
  resilience_strategy: string;
  cost_optimization_strategy: string;
}

export interface ArchitectureValidationIssue {
  severity: "critical" | "important" | "optional";
  code: string;
  message: string;
  mode?: "poc" | "production" | null;
}

export interface ArchitectureRevision {
  id: string;
  session_id: string;
  version: number;
  created_at: string;
  reason: string;
  specs: ArchitectureSpec[];
  validation_issues: ArchitectureValidationIssue[];
}

export interface ArchitectureResponse {
  architectures: ArchitectureSpec[];
  revisions: ArchitectureRevision[];
  validation_issues: ArchitectureValidationIssue[];
}

export interface DiagramGalleryResult {
  mode: "poc" | "production";
  diagrams: Array<{
    id: string;
    title: string;
    view_id: string;
    compiler_view_id?: string | null;
    semantic_view_id?: string | null;
    user_description?: string | null;
    rendered_as_native_view?: boolean;
    fallback_reason?: string | null;
    format_paths: Record<string, string>;
    preview_svg_artifact_id?: string;
  }>;
  qa_reports: Array<{ view_id: string; passed: boolean; diagnostics: unknown[]; metrics: Record<string, unknown> }>;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancel_requested";

export interface JobRun {
  id: string;
  session_id: string;
  operation: "research" | "architecture" | "diagrams" | "export";
  status: JobStatus;
  progress: number;
  message: string;
  duration_seconds?: number | null;
  error?: string | null;
  result_path?: string | null;
}

export interface ExportBundle {
  name: string;
  artifact_id: string;
  manifest_artifact_id: string;
  included_artifacts: string[];
  warnings: string[];
}

export interface HydratedSession {
  session: Session;
  readiness?: Readiness | null;
  brief?: UseCaseBrief | null;
  research?: ResearchReport | null;
  research_narrative?: ResearchNarrative | null;
  research_digest?: ResearchDigest | null;
  research_view_model?: ResearchViewModel | null;
  pricing?: unknown | null;
  architecture: ArchitectureResponse;
  diagrams: DiagramGalleryResult[];
  diagnostics: {
    logs: unknown[];
    latest_export?: ExportBundle | null;
  };
}
