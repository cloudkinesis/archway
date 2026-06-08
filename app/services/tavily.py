from typing import Any

import httpx
from pydantic import BaseModel, Field, HttpUrl

from app.core.config import get_settings
from app.core.logging import AuditLogger, hash_payload
from app.models.domain import EvidenceItem, SessionPhase
from app.tooling.registry import ToolPolicyEngine, build_tool_registry

_SESSION_TAVILY_CALLS: dict[str, int] = {}


def tavily_session_usage(session_id: str | None) -> int:
    return _SESSION_TAVILY_CALLS.get(session_id or "__global__", 0)


class TavilySearchResult(BaseModel):
    title: str
    url: HttpUrl | None = None
    content: str = ""
    score: float | None = None


class TavilySearchResponse(BaseModel):
    query: str
    answer: str | None = None
    results: list[TavilySearchResult] = Field(default_factory=list)


class TavilySearchClient:
    def __init__(self):
        self.settings = get_settings()
        self.policy = ToolPolicyEngine(build_tool_registry())

    async def health_check(self) -> tuple[bool, str]:
        if not self.settings.tavily_api_key:
            return False, "Tavily API key is not configured."
        if not self.settings.enable_web_search:
            return False, "Tavily key is configured, but web search is disabled to preserve quota."
        if self.settings.tavily_max_calls_per_session <= 0:
            return False, "Tavily key is configured, but per-session budget is 0; no live health probe is run."
        return True, "Tavily key is configured. Live probe skipped to preserve quota."

    async def search(
        self,
        query: str,
        session_id: str | None,
        *,
        max_results: int = 5,
        include_domains: list[str] | None = None,
        purpose: str = "general_web",
    ) -> TavilySearchResponse:
        self.policy.assert_allowed(
            "web_search",
            SessionPhase.research,
            {"query": query, "max_results": max_results, "include_domains": include_domains or [], "purpose": purpose},
            session_id,
        )
        if not self.settings.tavily_api_key:
            raise RuntimeError("Tavily API key is not configured.")
        if not self.settings.enable_web_search:
            raise PermissionError("Tavily web search is disabled. Enable ARCHWAY_ENABLE_WEB_SEARCH only when external web evidence is required.")
        if purpose == "competitor_scan" and not self.settings.enable_competitor_web_search:
            raise PermissionError("Competitor web search is disabled. Set ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH=true to opt in.")
        self._consume_budget(session_id, purpose)
        payload: dict[str, Any] = {
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(max_results, 8)),
            "include_answer": True,
            "include_raw_content": False,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        AuditLogger(session_id).event(
            "research",
            "tavily_search_started",
            tool_name="Tavily Web Search",
            inputs_hash=hash_payload(payload),
        )
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                self.settings.tavily_api_url,
                json=payload,
                headers={"Authorization": f"Bearer {self.settings.tavily_api_key}"},
            )
        response.raise_for_status()
        data = response.json()
        AuditLogger(session_id).event(
            "research",
            "tavily_search_completed",
            tool_name="Tavily Web Search",
            output_hash=hash_payload(data),
        )
        return TavilySearchResponse(
            query=query,
            answer=data.get("answer"),
            results=[
                TavilySearchResult(
                    title=str(item.get("title") or "Untitled Tavily result"),
                    url=item.get("url"),
                    content=str(item.get("content") or "")[:1200],
                    score=item.get("score"),
                )
                for item in data.get("results", [])
            ],
        )

    def _consume_budget(self, session_id: str | None, purpose: str) -> None:
        budget = max(0, self.settings.tavily_max_calls_per_session)
        if budget <= 0:
            raise PermissionError(f"Tavily web search budget is 0 for this session; skipped {purpose}.")
        key = session_id or "__global__"
        used = _SESSION_TAVILY_CALLS.get(key, 0)
        if used >= budget:
            raise PermissionError(f"Tavily web search budget exhausted for this session ({used}/{budget}); skipped {purpose}.")
        _SESSION_TAVILY_CALLS[key] = used + 1


def tavily_response_to_evidence(response: TavilySearchResponse) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    if response.answer:
        evidence.append(
            EvidenceItem(
                source_type="web",
                title=f"Tavily answer: {response.query}",
                quote_or_summary=response.answer[:1200],
                tool_name="Tavily Web Search",
                confidence="medium",
            )
        )
    for result in response.results:
        evidence.append(
            EvidenceItem(
                source_type="web",
                title=result.title,
                url=result.url,
                quote_or_summary=result.content or "Tavily returned this source for the query.",
                tool_name="Tavily Web Search",
                confidence="medium",
            )
        )
    return evidence
