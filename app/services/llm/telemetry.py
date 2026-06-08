from __future__ import annotations

from threading import Lock

from app.services.llm.base import LLMCallTelemetry


class LLMCallTelemetryStore:
    def __init__(self):
        self._lock = Lock()
        self._items: list[LLMCallTelemetry] = []

    def add(self, item: LLMCallTelemetry) -> None:
        with self._lock:
            self._items.append(item)

    def list(self, session_id: str | None = None) -> list[LLMCallTelemetry]:
        with self._lock:
            items = list(self._items)
        if session_id:
            items = [item for item in items if item.session_id == session_id]
        return [item.model_copy(deep=True) for item in items]


llm_telemetry_store = LLMCallTelemetryStore()
