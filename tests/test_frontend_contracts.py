from pathlib import Path


def test_research_header_actions_are_wired_or_disabled():
    source = Path("frontend/src/components/App.tsx").read_text(encoding="utf-8")

    assert "onExport={() => exportRun.mutate()}" in source
    assert "api.generateExport(session.id)" in source
    assert "ZIP ready" in source
    assert "Refresh evidence requires a fresh research run" in source
    assert "Competitor scan runs during a fresh research pass" in source


def test_pricing_ui_separates_pricing_basis_and_readiness():
    source = Path("frontend/src/components/App.tsx").read_text(encoding="utf-8")

    assert "Pricing basis" in source
    assert "Pricing readiness" in source
    assert "Directional estimate only. Not procurement-ready." in source
    assert "SKU/rate trace" in source
