# System Architecture

Archway is a local full-stack application.

## Runtime Shape

Backend:

- FastAPI app in `app/main.py`.
- Routes in `app/api/routes.py`.
- Pydantic domain models in `app/models/domain.py`.
- SQLite session index through `app/db/session_store.py`.
- File artifacts under `settings.data_dir`, default `.archway`, through `app/services/artifacts.py`.
- Middleware for CORS, security headers, request size, and rate limiting in `app/security`.

Frontend:

- React + Vite app under `frontend`.
- API client in `frontend/src/lib/api.ts`.
- Types in `frontend/src/lib/types.ts`.
- Main UI currently concentrated in `frontend/src/components/App.tsx`.

External/local integrations:

- Existing D2 diagram compiler through `app/services/diagram_compiler_adapter.py`.
- Optional AWS Docs MCP, AWS Pricing MCP, AWS Price List bulk index, Tavily web search, local Ollama, and Bedrock model provider through settings in `app/core/config.py`.

## Phase Flow

The product flow is:

1. Synthesis: user submits raw use case. `SynthesisEngine` creates `UseCaseBrief`, interview questions, assumptions, and readiness.
2. Research: `ResearchOrchestrator` builds evidence, recommendations, pricing estimate, citation coverage, narrative/digest/view model inputs.
3. Pricing checkpoint: optional explicit driver closure/profile/proceed-without-headline workflow.
4. Architecture: `ArchitecturePlanner` builds POC and production architecture specs. Governance controls and deterministic critique/repair are applied.
5. Diagrams: `DiagramCompilerAdapter` compiles POC and production specs using the configured compiler path and stores a diagram gallery.
6. Diagnostics/export: `ExportPackageService` builds the narrative dossier, raw JSON, diagrams, diagnostics, and zip package.

## API Flow

Key route groups:

- `/api/health`, `/api/build/status`
- `/api/sessions`, `/api/sessions/{session_id}`, `/api/sessions/{session_id}/hydrate`
- `/synthesis/message`, `/synthesis/proceed`
- `/research/run`, `/research/status`, `/research/report`
- `/pricing/checkpoint`, `/pricing/checkpoint/answer`, `/pricing/checkpoint/use-profile`, `/pricing/checkpoint/proceed-without-headline`
- `/architecture/generate`, `/architecture`, `/architecture/revisions`, `/architecture/regenerate`
- `/diagrams/generate`, `/diagrams`
- `/jobs/{job_id}`, `/jobs/{job_id}/cancel`
- `/diagnostics`
- `/export`, `/export/generate`, `/export/package`
- `/artifacts/{artifact_id:path}`

Long-running work is submitted through `JobManager`; the frontend polls job status.

## State and Persistence

Archway persists two layers:

- Session index in SQLite: session id, serialized session payload, update timestamp.
- Session artifacts on disk: JSON reports, pricing, architectures, diagrams, exports, raw payloads.

Hydration uses `session_id` and active revision/session artifacts to reconstruct the UI. Not every artifact path is explicitly revision-scoped today; some data is "current" by session plus active architecture revision metadata.

## Trust Boundary Summary

Security-critical boundaries:

- Request limit/rate limit middleware protects the API surface.
- Artifact resolution rejects absolute paths and `..` traversal.
- Tool integrations are controlled by environment settings.
- Pricing headline safety depends on pricing metadata/ledger, not just non-zero cost.
- Diagram rendering is routed through `DiagramCompilerAdapter`; this is the intended boundary to the existing D2 compiler.

