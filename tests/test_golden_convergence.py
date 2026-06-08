import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.architecture import ArchitecturePlanner
from app.services.artifacts import ArtifactStore
from app.services.convergence.golden_convergence_orchestrator import GoldenConvergenceOrchestrator
from app.services.research import ResearchOrchestrator
from app.services.synthesis import SynthesisEngine
from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS


@pytest.mark.asyncio
async def test_convergence_caps_investment_risk_pricing_and_exports_findings(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "deterministic")
    get_settings.cache_clear()
    use_case = GOLDEN_SCENARIOS["investment_risk"]
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief(use_case)
    session = store.create(use_case, brief)
    artifacts = ArtifactStore()

    report = await ResearchOrchestrator().run_research(brief, session.id)
    artifacts.write_json(session.id, "research", "report", report.model_dump(mode="json"))
    artifacts.write_json(session.id, "pricing", "estimate", report.pricing_analysis.model_dump(mode="json"))
    specs = ArchitecturePlanner().generate(report)
    artifacts.write_json(session.id, "architecture", "specs", [spec.model_dump(mode="json") for spec in specs])

    result = await GoldenConvergenceOrchestrator().run(session.id, use_case, [], "deep_dossier")

    assert result.final_status in {"directional_only", "internal_only"}
    assert any(item.code == "pricing.directional_only_missing_core_compute_drivers" for item in result.unresolved_findings + result.repaired_findings)
    assert artifacts.resolve(session.id, "quality/golden_convergence_result.json").is_file()
    assert artifacts.resolve(session.id, "quality/quality_findings.json").is_file()
    repair_plan = __import__("json").loads(artifacts.resolve(session.id, "quality/repair_plan.json").read_text(encoding="utf-8"))
    if repair_plan["actions"] and repair_plan["can_auto_apply"]:
        assert repair_plan["repairs_applied"] > 0
