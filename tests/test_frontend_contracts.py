from pathlib import Path


def test_research_header_actions_are_wired_or_disabled():
    source = Path("frontend/src/components/App.tsx").read_text(encoding="utf-8")

    assert "onExport={() => exportRun.mutate()}" in source
    assert "api.generateExport(session.id)" in source
    assert "ZIP ready" in source
    assert "onRefreshResearch={() => refreshResearch.mutate()}" in source
    assert "api.runResearch(session.id)" in source
    assert "Refresh evidence" in source
    assert "Run competitor scan" in source


def test_pricing_ui_separates_pricing_basis_and_readiness():
    source = Path("frontend/src/components/App.tsx").read_text(encoding="utf-8")

    assert "Pricing basis" in source
    assert "Pricing readiness" in source
    assert "Directional estimate only. Not procurement-ready." in source
    assert "SKU/rate trace" in source


def test_workspace_resets_scroll_on_session_or_view_change():
    source = Path("frontend/src/components/App.tsx").read_text(encoding="utf-8")

    assert "workspaceRef.current?.scrollIntoView" in source
    assert "window.scrollTo({ top: 0" in source
    assert "[props.session.id, props.view]" in source


def test_hydration_restores_active_phase_and_running_jobs():
    source = Path("frontend/src/components/App.tsx").read_text(encoding="utf-8")

    assert "data.jobs?.research?.status" in source
    assert "data.jobs?.architecture?.status" in source
    assert "data.jobs?.diagrams?.status" in source
    assert "if (data.session) return phaseView(data.session)" in source
    assert source.index("if (data.session) return phaseView(data.session)") < source.index('if (data.research) return "research"')


def test_completed_diagram_sessions_auto_refresh_empty_gallery():
    source = Path("frontend/src/components/App.tsx").read_text(encoding="utf-8")

    assert "autoRefreshAttemptRef" in source
    assert 'session.active_phase === "diagrams"' in source
    assert 'latest?.status === "succeeded"' in source
    assert "void refreshDiagrams()" in source
