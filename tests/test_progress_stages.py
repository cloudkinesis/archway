import pytest

from app.services.research import ResearchOrchestrator
from app.services.synthesis import SynthesisEngine


@pytest.mark.asyncio
async def test_research_progress_emits_meaningful_stage_labels(monkeypatch):
    async def no_evidence(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.services.aws_research_tools.AWSDocsAdapter.search", no_evidence)
    monkeypatch.setattr("app.services.aws_price_list.AWSPriceListBulkClient.evidence_for_services", no_evidence)
    monkeypatch.setattr("app.services.aws_price_list_query.AWSPriceListQueryClient.evidence_for_services", no_evidence)
    monkeypatch.setattr("app.services.aws_research_tools.AWSPricingAdapter.lookup", no_evidence)

    brief = SynthesisEngine().create_initial_brief(
        "Retail order-status assistant with support workflow integration, audit logging, and dashboard reporting."
    )
    updates: list[tuple[int, str]] = []

    await ResearchOrchestrator().run_research(
        brief,
        "sess_progress_research",
        progress=lambda value, message: updates.append((value, message)),
    )

    values = [value for value, _ in updates]
    labels = " ".join(message for _, message in updates).lower()

    assert values == sorted(values)
    assert len(updates) >= 8
    assert "domain classification" in labels
    assert "aws documentation evidence" in labels
    assert "pricing assumptions" in labels
    assert "evidence map" in labels
    assert "view-model inputs" in labels


def test_routes_contain_granular_architecture_and_export_progress_labels():
    from pathlib import Path

    source = Path("app/api/routes.py").read_text(encoding="utf-8")

    for expected in [
        "Generating POC and production architecture options.",
        "Enriching governance controls for effectful flows.",
        "Running architecture critique and repair planning.",
        "Saving revision and preparing diagram inputs.",
        "Solution package is ready.",
    ]:
        assert expected in source

    export_source = Path("app/services/export_package.py").read_text(encoding="utf-8")
    for expected in [
        "Collecting session artifacts.",
        "Building narrative research dossier.",
        "Writing raw evidence and trace payloads.",
        "Building ZIP package.",
    ]:
        assert expected in export_source
