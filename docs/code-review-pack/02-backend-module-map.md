# Backend Module Map

This map lists the main backend modules and what they are responsible for.

## App Entry and API

- `app/main.py`: creates FastAPI app, configures middleware, includes routes, installs safe exception handler.
- `app/api/routes.py`: main API controller. It wires sessions, synthesis, research, pricing checkpoint, architecture generation, diagram generation, diagnostics, jobs, artifact serving, and export package creation.
- `app/models/schemas.py`: request schemas for create/update/session/synthesis/architecture endpoints.
- `app/models/domain.py`: central Pydantic domain model file.

## Configuration and Security

- `app/core/config.py`: environment-driven settings. Includes data paths, compiler path, Tavily, AWS Docs MCP, AWS Pricing MCP, AWS Price List index, Ollama, and Bedrock settings.
- `app/core/logging.py`: logging setup.
- `app/security/*`: request size, rate limit, and security header middleware.

## Session and Artifact Storage

- `app/db/session_store.py`: SQLite-backed session index. Creates `sess_<hex>` ids and stores serialized `Session` models.
- `app/services/artifacts.py`: safe artifact layout, writes JSON, copies files, resolves artifact ids back to files, and prevents path traversal.

## Synthesis and Understanding

- `app/services/synthesis.py`: creates the initial brief, interview questions, readiness, assumptions, and answer recording.
- `app/services/use_case_profile.py`: deterministic use-case classification and profile extraction.
- `app/services/capability_extractor.py`: extracts capabilities, latency/deployment hints, and excluded patterns.
- `app/services/understanding/deep_use_case_understanding.py`: deterministic plus optional LLM-style deeper use-case understanding.
- `app/services/understanding/understanding_validator.py`: catches missed explicit numbers, unsupported capabilities, and mismatch risks.
- `app/services/understanding/understanding_merger.py`: merges deterministic profile and deeper understanding.

## Research and Evidence

- `app/services/research.py`: research orchestration. It pulls local policy/AWS docs/pricing/web evidence where configured, builds recommendations, competitor status, and research metadata.
- `app/services/research_view_model.py`: transforms raw research/pricing into a UI-friendly view model with summary, evidence chips, pricing confidence, risk sections, competitor status, and hidden raw evidence ids.
- `app/services/deep_dossier.py`: builds the deeper export dossier model and narrative sections.
- `app/services/source_policy.py`, `app/services/citation_gate.py`, `app/services/evidence_*`: source authority, citation coverage, evidence digest, and evidence quality helpers.

## Pricing

- `app/services/pricing.py`: deterministic pricing estimate and workload driver extraction.
- `app/services/pricing_driver_selector.py`: selects pricing family from profile.
- `app/services/pricing_driver_closure.py`: identifies confirmed, assumed, and missing pricing drivers; returns checkpoint questions and maturity.
- `app/services/pricing_scenario_profiles.py`: scenario profiles, currently mainly for live media streaming.
- `app/services/source_truth_pricing_compiler.py`: builds canonical facts, assumptions, driver bindings, usage dimensions, ledger, sanity findings, and line-item annotations.
- `app/services/aws_price_list.py`, `app/services/aws_price_list_parser.py`, `app/services/aws_pricing_mcp.py`, `app/services/aws_rate_binding_engine.py`: AWS pricing reference and rate-binding plumbing.
- `app/services/pricing_filter_mapper.py`: maps AWS services to pricing filter plans.

## Architecture and Governance

- `app/services/architecture.py`: architecture planning from research/profile into POC and production specs.
- `app/services/governance_controls.py`: enriches effectful flows with typed governance controls.
- `app/services/architecture_critique.py`: deterministic/optional critique for service-fit and domain-specific architecture issues.
- `app/services/architecture_revisions.py`: stores and tracks architecture revisions.
- `app/services/service_decisions.py`: service decision records used by research and export.
- `app/services/lane_planner.py`: maps components into diagram/compiler lane categories.
- `app/services/pattern_catalog.py`: workload patterns, components, flows, controls, expected views, semantic views, scope text, and pricing dimensions.

## Diagrams

- `app/services/diagram_compiler_adapter.py`: converts `ArchitectureSpec` into compiler input, calls the existing compiler with timeout/concurrency control, copies SVG/D2/PNG artifacts, records missing views and icon metrics.
- `app/services/view_planner.py`: semantic view enum and mapping into compiler view ids.

## Repair, Convergence, and Export

- `app/services/convergence/golden_convergence_orchestrator.py`: collects quality findings, applies limited deterministic repairs, writes convergence artifacts, and assigns final readiness.
- `app/services/convergence/repair_planner.py`: turns findings into repair actions.
- `app/services/convergence/architecture_repairer.py`: applies a small set of architecture repairs.
- `app/services/export_package.py`: builds the zip package, narrative markdown, raw JSON, diagram downloads, quality/repair summaries, pricing trace, and manifest.
- `app/services/customer_readiness.py`: maps evidence/pricing/diagram/architecture state to customer readiness.

## Jobs and Health

- `app/services/jobs.py`: in-memory job manager with polling, cancellation, progress, duration, and error recording.
- `app/services/health.py`: health checks for configured dependencies.
- `app/services/build_status.py`: user-facing build/plumbing readiness summary.

