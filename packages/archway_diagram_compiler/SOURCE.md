# Vendored source provenance — archway_diagram_compiler

This directory vendors the Archway diagram compiler into the Archway repository
so the app is self-contained, reproducible, and reviewable without any external
or iCloud-synced path.

| Field | Value |
|---|---|
| **Original path** | `~/Documents/Archway Diagram Compiler` |
| **External repo HEAD at vendoring** | `c9a8031` ("Initial archway diagram compiler", branch `main` — the only commit in that repo's history) |
| **Source type** | **Working-tree snapshot, NOT clean HEAD** |
| **Snapshot date** | 2026-06-10 |
| **Vendored by branch** | `chore/internalize-diagram-compiler` (base `f692c04`) |

## Why a working-tree snapshot

The Archway runtime never consumed an installed build of the external repo's
HEAD — the adapter inserted the external `src/` directory onto `sys.path` and
imported the **working tree directly**. All RC2 validation evidence (diagram QA
results, the healthcare crossing analysis, the media-streaming view tests, the
`logical_edge_crossing_max = 8` gate behavior) was produced against that
working tree. HEAD `c9a8031` predates the `semantic_archway` lane-template
machinery entirely; vendoring HEAD-only would have changed compiler behavior
and broken `fix/healthcare-diagram-crossings`. The working tree is therefore
the de facto source of truth, and that is what was copied.

## Dirty files copied (modified vs HEAD `c9a8031` at snapshot time)

All 12 files below contained uncommitted modifications in the external repo
(+223/−26 lines total vs HEAD) and were copied in their working-tree state:

1. `src/archway_diagram_compiler/aws_provider.py`
2. `src/archway_diagram_compiler/compiler.py`
3. `src/archway_diagram_compiler/flow_classifier.py`
4. `src/archway_diagram_compiler/flow_ledger.py`
5. `src/archway_diagram_compiler/icons.py`
6. `src/archway_diagram_compiler/lane_templates.py`
7. `src/archway_diagram_compiler/layout_ir.py`
8. `src/archway_diagram_compiler/models.py`
9. `src/archway_diagram_compiler/quality_config.py`
10. `src/archway_diagram_compiler/view_planner.py`
11. `src/archway_diagram_compiler/views.py`
12. `src/archway_diagram_compiler/visual_layout_qa.py`

The external repo's untracked `docs/` (blog drafts), `build/` outputs,
`.git/`, caches, and `egg-info` build metadata were **not** copied.

## What was copied

- `src/archway_diagram_compiler/` — full package source, including
  `assets/aws-icons/64/*.svg` package data (checked-in icon sources, not
  generated artifacts), quality config, lane templates, QA code, and the D2
  renderer code.
- `tests/` — the compiler's own test suite (golden-scenario tests write to
  `tmp_path` only).
- `pyproject.toml`, `README.md`.

## Renderer binary (local tool, NOT committed)

SVG rendering shells out to the `d2` CLI. The compiler's
`find_d2_executable()` resolves it from `PATH` or from a `.tools/d2/d2`
directory at/above the working directory. The binary (~44 MB Mach-O, plus an
optional ~430 MB Playwright/Chromium tree used only for PNG conversion, which
Archway never requests — the adapter renders `("svg",)` only) was a
**gitignored local tool even in the external repo**, so it is NOT vendored
into git here either.

- Local install location: `~/Developer/Archway/.tools/d2/d2` (copied from the
  external repo's `.tools/d2/d2` at vendoring time; `.tools/` is gitignored).
- On a machine without the binary, compilation degrades HONESTLY: `.d2` text
  artifacts are still produced and QA reports `d2_executable_not_found` /
  `missing_render_artifact` — SVG-based checks (e.g. crossing counts) cannot
  run, but nothing is silently faked.
- To set up a new machine: install `d2` on PATH, or copy a `d2` binary to
  `<repo>/.tools/d2/d2`.

## Runtime contract after vendoring

- The Archway adapter (`app/services/diagram_compiler_adapter.py`) imports
  this internal package by default; **the external iCloud path is no longer
  required for default operation**.
- The external-path environment variable (`ARCHWAY_DIAGRAM_COMPILER_PATH`) is
  retained only as an explicit fallback used when the internal package cannot
  be imported; when used, the compiler source is reported as
  `external_override` — never silently.
- **QA threshold preserved:** `logical_edge_crossing_max = 8`
  (`src/archway_diagram_compiler/quality_config.py`). No threshold was changed
  during vendoring; compiler logic was copied verbatim, not rewritten.
