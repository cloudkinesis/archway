# Archway RC2 Discovery Baseline

Generated: 2026-06-07 19:21 IST

## 1. What Discovery Planner Now Does

Archway now has an advisory Discovery Planner that runs after deterministic use-case profiling and before interview-question selection.

It takes:

- Raw use case text
- Deterministic baseline profile
- Known workload/domain packs
- Previous interview answers, when available

It produces structured discovery metadata:

- Domain candidates
- Workload family candidates
- Confidence
- Primary entities and actions
- Data sources and integrations
- Governance concerns
- Pricing drivers
- Not-relevant patterns
- Assumptions to avoid
- Top next-best interview questions
- Why each question matters
- Expected answer styles

The planner is advisory only. It does not own architecture validation, pricing safety, governance enforcement, diagram planning, procurement readiness, or customer-ready status. If planner output is low-confidence or conflicts with deterministic classification, Archway marks ambiguity and asks a clarification question instead of silently choosing a wrong family.

For unknown or weakly classified domains, Archway now prefers discovery-derived workload drivers over telemetry fallback. Generic telemetry questions should appear only for explicit telemetry, device, sensor, log, metric, IoT, or streaming-event workloads.

## 2. Domains Verified

### Legal Contract RAG

- Baseline: `legal`, `document_intelligence`, `rag_assistant`, `agentic_workflow`
- First question asks for historical contracts/documents, average pages or MB, and new/updated documents per month.
- Pricing family: `document_rag_workflow`
- Status: directional, not headline-safe/procurement-ready

### True IoT Telemetry

- Baseline: `energy_utility`, `industrial_iot_streaming_ml`, `real_time_anomaly_detection`
- First question asks telemetry reporting frequency and payload size.
- Pricing family after fix: `industrial_iot_streaming`
- Status: directional, not headline-safe/procurement-ready

### Telecom HBase/HDFS Migration

- Baseline: `telecommunications`, `data_platform_analytics`, `telecom_network_analytics`
- First question asks HBase access patterns before target-store choice.
- Pricing family: `telecom_cdr_analytics`
- Status: directional, not headline-safe/procurement-ready

### Generic Web App

- Baseline: `web_api_application`
- First question asks active users, API requests/day, and async jobs/day.
- Pricing family: `generic_directional`
- Generic pricing now uses discovery-planner drivers instead of telemetry wording.
- Status: directional, not headline-safe/procurement-ready

### Healthcare OR

- Baseline: `healthcare_operations_scheduling`, `surgical_scheduling_prediction`, `clinical_workflow_decision_support`
- Uses healthcare OR drivers such as hospital count, operating room count, active OR POC count, scheduled surgeries/day, refresh cadence, approval workflows, EHR writebacks, occupancy/readiness events, audit retention, and active coordinator users.
- Reserved-vocabulary lint is scoped to healthcare output only.
- Status: directional, not headline-safe/procurement-ready

### Media QoE

- Baseline: media/live-streaming pattern for video streaming analytics, viewer QoE, CDN logs, DRM/ad/QoE integration where applicable.
- Pricing family: `live_media_streaming`
- Healthcare vocabulary and healthcare pricing drivers do not leak into media outputs.
- Status: directional, not headline-safe/procurement-ready

## 3. Anti-Drift Fixes Completed

- Legal contract/RAG no longer asks telemetry frequency or payload-size questions.
- Document/RAG pricing family and pricing drivers added for legal/document workflows.
- Telecom HBase/HDFS asks HBase access-pattern questions before target-store selection.
- Generic web app asks web-scale questions rather than telemetry questions.
- Healthcare OR pricing uses POC-scoped healthcare drivers, not industrial IoT/depot/dispatch defaults.
- Healthcare reserved-vocabulary lint does not apply globally.
- Generic anomaly detection no longer implies financial fraud.
- Energy utility / IoT telemetry anomaly detection no longer selects `financial_fraud_detection` or `payment_fraud_scoring`.
- Payment fraud still selects `payment_fraud_scoring` when explicit fraud/payment/transaction signals are present.
- Low-confidence discovery produces a clarification question instead of silent wrong-family selection.
- Planner output cannot mark pricing procurement-ready and cannot bypass governance controls.

## 4. Tests Passed

Latest focused validation:

```text
27 passed in 14.82s
```

Covered:

- `tests/test_pricing.py`
- `tests/test_discovery_planner.py`
- `tests/test_healthcare_anti_drift.py`
- `tests/golden_scenarios/test_scenario_matrix.py`

Additional adjacent validation from the Discovery Planner pass:

```text
17 passed in 11.20s
25 passed in 20.10s
```

Covered discovery planner behavior, pricing behavior, healthcare anti-drift, scenario matrix, metric extraction, pricing driver closure, and source-truth pricing compiler tests.

Compile checks passed for touched service files:

- `app/services/discovery_planner.py`
- `app/services/synthesis.py`
- `app/services/pricing.py`
- `app/services/use_case_profile.py`
- `app/services/llm/base.py`
- `app/services/llm/model_router.py`
- `app/services/pricing_driver_selector.py`

## 5. Remaining Known Gaps

- Pricing remains directional for most workload families unless exact SKU/tier binding and validated quantities are available.
- Discovery Planner is advisory and improves interview/question selection, but deterministic validation still needs to catch missed explicit numbers, wrong latency class, wrong deployment posture, and incorrect domain assumptions.
- Some workload-family ordering can still be imperfect when multiple valid families are present, although safety-critical downstream pricing now has stronger guards.
- Full browser/manual UX regression was not rerun after the latest backend-focused anti-drift fix.
- Competitor/Tavily behavior and UI presentation were not part of this RC2 Discovery Baseline validation.
- Frontend remains structurally large and should not be refactored during final stabilization unless it blocks the golden run.

## 6. What Not To Touch Before Final Golden Run

- Do not start a new UI redesign.
- Do not expand telecom, healthcare, media, legal, or generic domain packs unless a golden run exposes a blocking defect.
- Do not relax governance approval controls.
- Do not let LLM planner output override deterministic pricing safety, procurement readiness, architecture validation, or diagram planning.
- Do not bypass the existing D2 compiler.
- Do not make pricing headline-safe without SKU/tier traceability and validated quantities.
- Do not introduce new Tavily/competitor behavior unless specifically testing competitor analysis.
- Do not refactor broad domain classification logic unless a regression proves it is necessary.

## 7. Next Golden Scenarios To Run After Reset

Run these as full end-to-end golden scenarios, including interview, research, architecture, diagrams, diagnostics, export package, and anti-drift inspection:

1. Legal contract RAG and obligation workflow
2. Energy utility IoT telemetry anomaly detection
3. Telecom HBase/HDFS real-time analytics migration
4. Healthcare OR scheduling / delay prediction
5. Media streaming QoE and CDN log analytics
6. Generic public web app with API, database, async jobs, observability, and CI/CD
7. Payment transaction fraud detection as a negative anti-drift control proving fraud still works

Minimum checks per run:

- First interview question is domain-appropriate.
- Pricing family matches workload shape.
- Pricing is clearly directional unless SKU/tier quantities are proven.
- Research narrative has no unrelated domain leakage.
- Diagrams render through the existing D2 compiler.
- Export zip contains the same phase outputs shown in the UI.
