# Frontend Module Map

The frontend is a Vite React application under `frontend`.

## Main Files

- `frontend/src/components/App.tsx`: main application shell and most UI components.
- `frontend/src/lib/api.ts`: typed fetch wrapper for backend endpoints.
- `frontend/src/lib/types.ts`: TypeScript interfaces mirroring backend models.
- `frontend/src/main.tsx`: React entrypoint.
- `frontend/src/styles.css`: application styling.

## App Structure

`App.tsx` currently contains the top-level state, React Query calls, phase switching, and many component definitions. Important components include:

- `App`: holds selected session, active view, hydrated report/pricing/architecture/diagram/export state, and health/build status.
- `HealthGate`: dependency readiness screen.
- `TopBar`: product header and active model label.
- `SessionSidebar`: create/select sessions and show session history.
- `Workspace`: tabbed phase shell for Synthesis, Research, Architecture, Diagrams, and Diagnostics.
- `SynthesisView`: interview/chat flow, readiness, sticky composer behavior, and proceed action.
- `ResearchView`: research run action, job polling, report hydration, pricing checkpoint, narrative/report display.
- `ArchitectureView`: architecture generation, revision display, editor, validation panel, and regenerate flow.
- `DiagramView`: diagram generation, gallery cards, and inspector entry.
- `DiagramInspector`: full-size SVG inspection modal with zoom/open/download controls.
- `DiagnosticsView`: export generation, package links, and diagnostic summaries.
- `SolutionBrief`: right-side live brief.
- `BuildStatusCard`: plumbing readiness summary.
- Research presentation components: `ResearchDigestDashboard`, `ResearchStickyHeader`, `ExecutiveBriefing`, `ResearchSubTabs`, `OverviewResearchTab`, `ArchitectureRationaleTab`, `PricingResearchTab`, `CompetitorsResearchTab`, `RisksResearchTab`, `EvidenceResearchTab`, `NarrativeReport`, `EvidenceAppendix`.

## API Client

`frontend/src/lib/api.ts` wraps:

- Health/build status.
- Session create/list/hydrate/update/delete.
- Synthesis message/proceed.
- Research run/report.
- Pricing checkpoint/profile/proceed-without-headline.
- Architecture generate/get/update/regenerate.
- Diagram generate/get.
- Job poll/cancel.
- Export generate/get.
- Diagnostics.
- Artifact URL construction.

## Current UX State

Recent UI work moved research away from raw database-like evidence output toward a digest, briefing, tabs, and evidence appendix. It also added diagram inspection and session hydration. However, the frontend still has a large monolithic component file. A future maintainability pass should split phase views and research cards into dedicated modules.

## Reviewer Notes

Check that:

- Completed session hydration populates every tab, not just the current phase.
- Research default view hides `ev_*` ids and shows readable source labels.
- Research buttons either work or are disabled with a clear reason.
- The chat composer stays visible in long interviews.
- Diagram preview opens a usable inspector without requiring download.
- Frontend types match backend response shape closely enough to prevent silent UI failures.

