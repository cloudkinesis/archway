# Data Models and Artifacts

The central data models are Pydantic models in `app/models/domain.py`, with matching TypeScript interfaces in `frontend/src/lib/types.ts`.

## Session Model

`Session` contains:

- `id`, `name`, `status`, `active_phase`, `updated_at`.
- `initial_use_case`.
- `current_summary`: the active `UseCaseBrief`.

Session rows are stored in SQLite by `SessionStore`. Rich phase data is stored as artifacts on disk.

## Use Case Brief

`UseCaseBrief` contains:

- Raw and refined problem statement.
- Industry.
- Business goals.
- Users/personas.
- AI capabilities.
- Data sources.
- Integrations.
- Assumptions.
- Open questions.
- POC and production scope.
- `use_case_profile` metadata.
- Conversation/history fields used by synthesis.

This brief is the first durable representation of the use case and feeds research, pricing, architecture, and exports.

## Research Models

`ResearchReport` contains:

- Executive verdict and proceed recommendation.
- Use-case interpretation, feasibility, viability, competitor analysis.
- Recommended POC and production direction.
- `PricingAnalysis`.
- AWS service recommendations.
- Risks.
- Evidence items and evidence assessments.
- Facts, recommendations, uncertainties.
- Citation coverage.
- Metadata including competitor/Tavily status, service decisions, source policies, and pricing traces.

Research display should use `ResearchViewModel`, narrative/digest data, and readable evidence labels rather than raw internal evidence ids.

## Pricing Models

`PricingAnalysis` contains:

- Region and low/expected/high monthly estimates.
- Line items.
- Main cost drivers.
- Unknown variables.
- Metadata.

Important metadata keys include pricing driver family, pricing maturity, pricing closure, pricing trace, source-truth compiler details, pricing ledger, headline-safe flags, warnings, and sanity findings. Not every pricing path has procurement-grade SKU/rate backing.

## Architecture Models

`ArchitectureSpec` contains:

- Spec id, name, mode/scope.
- Summary and workload pattern.
- Components.
- Flows.
- Security controls.
- Governance controls.
- Observability controls.
- Scaling/resilience/deployment notes.
- Metadata, including expected/semantic views and critique/repair information.

`ArchitectureFlow` includes data classification and metadata used to infer governance and diagram semantics.

`GovernanceControl` links controls to governed flow ids. This is important because governance should be typed and structural, not detected by brittle string matching.

`ArchitectureRevision` tracks revisions of POC/production specs. Current artifact paths are not all fully revision-scoped; reviewers should verify active revision behavior carefully.

## Diagram Models

`DiagramGalleryResult` contains:

- Gallery id.
- Mode.
- Diagrams.
- QA report.
- Diagnostics.
- Rendered and missing views.

`DiagramArtifact` contains view id, title, artifact ids for SVG/D2/PNG, and quality/degraded fields.

## Deep Dossier Models

`DeepResearchDossier` and related models represent the export narrative:

- Research questions.
- Claims.
- Assumptions.
- Requirements.
- Feasibility rows.
- Pricing lines/formulas.
- Risks.
- Consistency checks.
- Quality score/readiness.

The export package uses this to produce reviewer-facing markdown.

## Artifact Layout

`ArtifactStore.ensure_layout` creates:

- `brief`
- `research`
- `pricing`
- `architecture`
- `diagrams/poc`
- `diagrams/production`
- `logs`
- `traces`
- `evidence`
- `exports`

Artifact ids are relative paths under the session root. `ArtifactStore.resolve` rejects absolute paths and parent traversal.

## Export Package

`ExportPackageService.generate` writes markdown and raw JSON under a generated export folder and zips it. The package includes solution brief, research, deep dossier, claim register, evidence map, pricing, architecture, diagrams, diagnostics, build status, regression summary, quality/repair report, pricing trace, source policy, and raw payloads.

