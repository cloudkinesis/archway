# Diagram Compiler Integration

Archway must use the existing D2 compiler integration. Diagram rendering is not supposed to be reimplemented inside Archway.

## Main Module

`app/services/diagram_compiler_adapter.py` is the boundary.

It:

- Reads the configured compiler path from settings.
- Imports/calls the compiler.
- Normalizes architecture specs into compiler input.
- Runs compile calls with timeout and concurrency control.
- Produces `DiagramGalleryResult` for POC and production.
- Copies or records SVG, D2, and PNG artifact ids.
- Records QA status, diagnostics, rendered views, missing views, and icon embedding metrics.

## Settings

Key settings in `app/core/config.py`:

- `ARCHWAY_DIAGRAM_COMPILER_PATH`
- `ARCHWAY_COMPILER_TOTAL_TIMEOUT_SECONDS`
- `ARCHWAY_COMPILER_MAX_CONCURRENT_JOBS`

The default path points to a local compiler directory. Reviewers should verify local path assumptions if running on another machine.

## View Mapping

The view path includes:

- Expected/semantic views from `pattern_catalog.py`.
- Semantic view mapping in `view_planner.py`.
- Adapter conversion and missing-view detection in `diagram_compiler_adapter.py`.
- Export fidelity checks in `export_package.py`.

Important issue: semantic requested views must not silently disappear. If a semantic view is not rendered, `missing_requested_views` or diagnostics should say so.

## QA Signals

Diagram results can include:

- `qa_report.passed`
- diagnostics
- missing views
- missing semantic views
- icon embedding metrics
- degraded reason
- artifact ids for SVG/D2/PNG

Recent implementation added icon embedding count checks. If D2 icon references and embedded SVG image counts match, icons should not be treated as the root cause of unrelated layout QA findings.

## Frontend Diagram UX

`DiagramView` and `DiagramInspector` in `frontend/src/components/App.tsx` should allow:

- Clickable previews.
- Full-size SVG inspection.
- Zoom/fit/open/download controls.
- Metadata: title, phase/mode, view id, quality status, degraded reason.
- Esc close.

## Known Risks

- Compiler path is local-environment dependent.
- Compiler view catalog and Archway semantic view catalog can drift.
- Some new domain-specific views may be represented as metadata-preserved or substituted views rather than first-class compiler views.
- Diagram QA failures should be reported precisely, not masked by generic degradation text.

