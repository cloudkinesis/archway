from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
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


# --------------------------------------------------------------------------- #
# Recursive secret redaction
# --------------------------------------------------------------------------- #
REDACTED = "<redacted>"

# Keys whose VALUE is always a credential (case-insensitive, exact match).
_SENSITIVE_EXACT = frozenset({
    "secret", "secrets", "api_key", "apikey", "access_key", "secret_access_key",
    "session_token", "token", "auth", "authorization", "password", "passwd",
    "credential", "credentials", "bearer", "private_key", "client_secret",
    "refresh_token", "id_token", "jwt",
})
# Substrings that mark a key as a credential wherever they appear.
_SENSITIVE_SUBSTRINGS = (
    "secret", "password", "passwd", "credential", "api_key", "apikey",
    "access_key", "private_key", "client_secret", "refresh_token",
    "session_token", "id_token",
)
# Innocent keys that must NEVER be redacted even if they look credential-ish.
_SAFE_KEYS = frozenset({
    "author", "authors", "authority", "authorized_role", "authorization_required",
    "token_count", "token_estimate", "pricing_token_estimate", "input_token_count",
    "output_token_count", "total_token_count",
})


def _is_sensitive_key(key: Any) -> bool:
    k = str(key).strip().lower()
    if k in _SAFE_KEYS:
        return False
    if k in _SENSITIVE_EXACT:
        return True
    if any(token in k for token in _SENSITIVE_SUBSTRINGS):
        return True
    # Credential-style suffix, but not innocent *count keys.
    if k.endswith("_token") and not k.endswith("count"):
        return True
    return False


def _is_sensitive_value(value: str) -> bool:
    s = value.strip()
    return s.startswith("Bearer ") or s.startswith("AKIA") or "-----BEGIN PRIVATE KEY-----" in s


def redact_sensitive(value: Any) -> Any:
    """Recursively redact secrets/tokens in dicts/lists/tuples/sets/scalars.

    Key-based (case-insensitive) for credential-named keys, plus light value-based
    redaction of obvious bearer tokens / AWS access keys / PEM private keys. Innocent
    keys (author, token_count, …) are explicitly preserved. Returns a JSON-friendly
    structure (sets become lists).
    """
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_sensitive_key(k) else redact_sensitive(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str) and _is_sensitive_value(value):
        return REDACTED
    return value


# --------------------------------------------------------------------------- #
# Safe audit-log JSONL reading
# --------------------------------------------------------------------------- #
@dataclass
class AuditReadWarning:
    line_number: int | None
    reason: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReadResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[AuditReadWarning] = field(default_factory=list)
    malformed_count: int = 0
    skipped_count: int = 0
    total_lines: int = 0
    status: Literal["ok", "degraded", "missing", "unreadable"] = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_log_status": self.status,
            "audit_log_warnings": [w.to_dict() for w in self.warnings],
            "malformed_count": self.malformed_count,
            "skipped_count": self.skipped_count,
            "total_lines": self.total_lines,
            "audit_events": self.events,
        }


def read_audit_jsonl(path: str | Path, *, redact: bool = True) -> AuditReadResult:
    """Read an audit JSONL file without ever raising to the caller.

    Malformed / non-object / partially-written lines are skipped with structured
    warnings; blank lines are ignored (not malformed); a missing file is ``missing``;
    an IO/permission error is ``unreadable``. Events are redacted by default.
    """
    p = Path(path)
    if not p.exists():
        return AuditReadResult(status="missing")
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return AuditReadResult(
            warnings=[AuditReadWarning(None, "read_error", f"Could not read audit log: {type(exc).__name__}")],
            status="unreadable",
        )

    events: list[dict[str, Any]] = []
    warnings: list[AuditReadWarning] = []
    malformed = skipped = total = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        total += 1
        if not line.strip():
            continue  # blank line: ignored, not malformed
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            malformed += 1
            skipped += 1
            warnings.append(AuditReadWarning(line_number, "malformed_json", "Skipped malformed audit log line"))
            continue
        if not isinstance(obj, dict):
            skipped += 1
            warnings.append(AuditReadWarning(line_number, "non_object_json", "Skipped non-object audit log line"))
            continue
        events.append(redact_sensitive(obj) if redact else obj)

    return AuditReadResult(
        events=events,
        warnings=warnings,
        malformed_count=malformed,
        skipped_count=skipped,
        total_lines=total,
        status="degraded" if warnings else "ok",
    )


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
        safe = redact_sensitive(record)
        logging.info(json.dumps(safe, default=str, sort_keys=True))
        self._append_session_log(safe)

    def timed(self, phase: str, operation: str, **fields: Any):
        return _TimedAudit(self, phase, operation, fields)

    def _append_session_log(self, record: dict[str, Any]) -> None:
        if not self.session_id:
            return
        # Audit-write failure must never break the main user flow; degrade with a trace.
        try:
            log_dir = self.settings.sessions_dir / self.session_id / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            line = json.dumps(redact_sensitive(record), default=str, sort_keys=True)
            with (log_dir / "audit.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception as exc:  # noqa: BLE001 - audit logging is best-effort
            logging.warning(json.dumps({"audit_log_write_error": type(exc).__name__, "session_id": self.session_id}))


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


def _session_audit_path(session_id: str) -> Path:
    return get_settings().sessions_dir / session_id / "logs" / "audit.jsonl"


def read_session_audit(session_id: str) -> AuditReadResult:
    """Read a session's audit log as a structured, crash-safe result (status + warnings)."""
    return read_audit_jsonl(_session_audit_path(session_id))


def read_session_logs(session_id: str) -> list[dict[str, Any]]:
    """Backward-compatible list accessor: safe, redacted events only (never raises)."""
    return read_session_audit(session_id).events

