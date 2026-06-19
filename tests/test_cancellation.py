from __future__ import annotations
import asyncio
import pytest
from app.services.jobs import JobManager
from app.services.research import ResearchOrchestrator
from app.models.domain import UseCaseBrief

def test_research_job_cooperative_cancellation(monkeypatch):
    # Mock should_cancel to simulate that a cancel request was received
    monkeypatch.setattr("app.services.jobs.job_manager.should_cancel", lambda job_id: True)
    
    # We also mock latest_for_session to return a mock job so the check executes
    mock_job = type("MockJob", (), {"id": "job_123"})()
    monkeypatch.setattr("app.services.jobs.job_manager.latest_for_session", lambda session_id, op: mock_job)
    
    orchestrator = ResearchOrchestrator()
    
    brief = UseCaseBrief(
        title="Test Brief",
        raw_use_case="Test Use Case",
        refined_problem_statement="Test Problem"
    )
    
    with pytest.raises(Exception) as exc_info:
        asyncio.run(orchestrator.run_research(brief, "sess_cancel"))
        
    assert "cancelled by user request" in str(exc_info.value)
