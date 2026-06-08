from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def hash_payload(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, default=str).encode()
    except TypeError:
        raw = repr(value).encode()
    return sha256(raw).hexdigest()


class AuditLogger:
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id
        self.settings = get_settings()

    def event(self, phase: str, operation: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "trace_id": fields.pop("trace_id", uuid4().hex),
            "phase": phase,
            "operation": operation,
            **fields,
        }
        safe = {key: value for key, value in record.items() if "secret" not in key.lower() and "api_key" not in key.lower()}
        logging.info(json.dumps(safe, default=str, sort_keys=True))
        self._append_session_log(safe)

    def timed(self, phase: str, operation: str, **fields: Any):
        return _TimedAudit(self, phase, operation, fields)

    def _append_session_log(self, record: dict[str, Any]) -> None:
        if not self.session_id:
            return
        log_dir = self.settings.sessions_dir / self.session_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "audit.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")


class _TimedAudit:
    def __init__(self, audit: AuditLogger, phase: str, operation: str, fields: dict[str, Any]):
        self.audit = audit
        self.phase = phase
        self.operation = operation
        self.fields = fields
        self.started = perf_counter()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        self.audit.event(
            self.phase,
            self.operation,
            latency_ms=round((perf_counter() - self.started) * 1000, 2),
            error_type=exc_type.__name__ if exc_type else None,
            **self.fields,
        )
        return False


def read_session_logs(session_id: str) -> list[dict[str, Any]]:
    path = get_settings().sessions_dir / session_id / "logs" / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

