"""Audit-log robustness: malformed lines never crash; secrets are redacted."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from app.core.config import get_settings
from app.core.logging import (
    AuditLogger,
    AuditReadResult,
    read_audit_jsonl,
    read_session_audit,
    read_session_logs,
    redact_sensitive,
)


def _write(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


# --------------------------- reader tests ---------------------------------- #
def test_missing_audit_log_returns_missing_status(tmp_path):
    result = read_audit_jsonl(tmp_path / "nope.jsonl")
    assert result.status == "missing"
    assert result.events == []


def test_empty_audit_log_returns_ok(tmp_path):
    result = read_audit_jsonl(_write(tmp_path / "a.jsonl", []))
    assert result.status == "ok"
    assert result.events == []


def test_blank_lines_are_skipped_without_malformed_warning(tmp_path):
    path = _write(tmp_path / "a.jsonl", ['{"phase": "p", "operation": "o"}', "", "   ", ""])
    result = read_audit_jsonl(path)
    assert result.status == "ok"
    assert result.malformed_count == 0
    assert len(result.events) == 1


def test_valid_json_object_lines_are_returned(tmp_path):
    path = _write(tmp_path / "a.jsonl", [
        json.dumps({"phase": "synthesis", "operation": "created"}),
        json.dumps({"phase": "research", "operation": "done"}),
    ])
    result = read_audit_jsonl(path)
    assert result.status == "ok"
    assert [e["operation"] for e in result.events] == ["created", "done"]


def test_malformed_json_line_is_skipped_with_warning(tmp_path):
    path = _write(tmp_path / "a.jsonl", ['{"phase": "p", "operation": "good"}', "{bad json"])
    result = read_audit_jsonl(path)
    assert result.status == "degraded"
    assert len(result.events) == 1 and result.events[0]["operation"] == "good"
    assert result.malformed_count == 1
    assert any(w.reason == "malformed_json" for w in result.warnings)


def test_non_object_json_line_is_skipped_with_warning(tmp_path):
    path = _write(tmp_path / "a.jsonl", ["[]", '"hello"', "123", "null",
                                         '{"phase": "p", "operation": "ok"}'])
    result = read_audit_jsonl(path)
    assert result.status == "degraded"
    assert len(result.events) == 1
    assert all(w.reason == "non_object_json" for w in result.warnings)
    assert result.skipped_count == 4


def test_partially_written_line_does_not_crash(tmp_path):
    path = _write(tmp_path / "a.jsonl", ['{"phase": "p", "operation": "ok"}', '{"phase": "p", "opera'])
    result = read_audit_jsonl(path)  # must not raise
    assert result.status == "degraded"
    assert len(result.events) == 1
    assert any(w.reason == "malformed_json" for w in result.warnings)


def test_unreadable_audit_log_returns_unreadable_status(tmp_path):
    # A directory at the audit path makes read_text raise IsADirectoryError (an OSError).
    bad = tmp_path / "audit.jsonl"
    bad.mkdir()
    result = read_audit_jsonl(bad)
    assert result.status == "unreadable"
    assert result.events == []
    assert any(w.reason == "read_error" for w in result.warnings)


# --------------------------- redaction tests ------------------------------- #
def test_redacts_top_level_sensitive_keys():
    out = redact_sensitive({"api_key": "X", "token": "Y", "password": "Z",
                            "authorization": "Bearer abc", "phase": "synthesis"})
    assert out["api_key"] == "<redacted>"
    assert out["token"] == "<redacted>"
    assert out["password"] == "<redacted>"
    assert out["authorization"] == "<redacted>"
    assert out["phase"] == "synthesis"


def test_redacts_nested_sensitive_keys():
    out = redact_sensitive({
        "outer": {"secret_access_key": "AKIA...", "ok": 1},
        "list": [{"refresh_token": "r"}, {"safe": "keep"}],
        "tavily_api_key": "k",
    })
    assert out["outer"]["secret_access_key"] == "<redacted>"
    assert out["outer"]["ok"] == 1
    assert out["list"][0]["refresh_token"] == "<redacted>"
    assert out["list"][1]["safe"] == "keep"
    assert out["tavily_api_key"] == "<redacted>"  # contains api_key


def test_redacts_private_key_and_bearer_values():
    out = redact_sensitive({
        "header": "Bearer eyJhbGciOi...",
        "blob": "-----BEGIN PRIVATE KEY-----\nMII...",
        "akid": "AKIAIOSFODNN7EXAMPLE",
        "note": "plain text",
    })
    assert out["header"] == "<redacted>"
    assert out["blob"] == "<redacted>"
    assert out["akid"] == "<redacted>"
    assert out["note"] == "plain text"


def test_does_not_over_redact_innocent_keys():
    payload = {"author": "Jane", "authority": "high", "authorized_role": "admin",
               "authorization_required": True, "token_count": 1234,
               "pricing_token_estimate": 50, "headline_safe": True}
    out = redact_sensitive(payload)
    assert out == payload  # nothing redacted


def test_writer_redacts_before_persisting_or_exporting(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    AuditLogger("sess_secret").event("synthesis", "created", api_key="SUPERSECRET",
                                      nested={"session_token": "TT"}, asset_count=10)
    result = read_session_audit("sess_secret")
    assert result.status == "ok"
    blob = json.dumps(result.to_dict())
    assert "SUPERSECRET" not in blob and "TT" not in blob
    assert "<redacted>" in blob
    assert any(e.get("asset_count") == 10 for e in result.events)  # innocent value kept


# --------------------------- integration tests ----------------------------- #
def _seed_session_with_bad_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    from app.db.session_store import SessionStore
    from app.services.synthesis import SynthesisEngine
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = store.create("Build a retail assistant for order questions.", brief)
    logs_dir = get_settings().sessions_dir / session.id / "logs"
    _write(logs_dir / "audit.jsonl", [
        json.dumps({"phase": "synthesis", "operation": "created", "api_key": "LEAK"}),
        "{bad json - partially written",
        "[]",
        json.dumps({"phase": "research", "operation": "done"}),
    ])
    return session


def test_diagnostics_survive_malformed_audit_log(tmp_path, monkeypatch):
    session = _seed_session_with_bad_audit(tmp_path, monkeypatch)
    result = read_session_audit(session.id)  # the function diagnostics route calls
    assert result.status == "degraded"
    assert len(result.events) == 2  # two good lines preserved
    assert json.dumps(result.to_dict())  # serializable
    assert "LEAK" not in json.dumps(result.to_dict())  # redacted


def test_session_hydration_survives_malformed_audit_log(tmp_path, monkeypatch):
    session = _seed_session_with_bad_audit(tmp_path, monkeypatch)
    logs = read_session_logs(session.id)  # the list accessor used by hydration's diagnostics block
    assert [e["operation"] for e in logs] == ["created", "done"]


def test_export_package_survives_malformed_audit_log(tmp_path, monkeypatch):
    session = _seed_session_with_bad_audit(tmp_path, monkeypatch)
    from app.services.export_package import ExportPackageService
    service = ExportPackageService()
    bundle = service.generate(session.id)  # must not raise
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        audit_log = json.loads(archive.read("raw/audit_log.json"))
    assert "raw/audit_log.json" in names
    assert audit_log["audit_log_status"] == "degraded"
    assert audit_log["audit_log_warnings"]
    assert any("Audit log degraded" in w for w in bundle.warnings)
    assert "LEAK" not in json.dumps(audit_log)


def test_audit_read_warnings_are_serializable(tmp_path):
    path = _write(tmp_path / "a.jsonl", ["{bad", "[]"])
    result = read_audit_jsonl(path)
    payload = json.dumps(result.to_dict())  # must not raise
    assert "malformed_json" in payload and "non_object_json" in payload


def test_audit_degraded_status_does_not_mark_pricing_or_diagram_ready():
    # Audit hardening must not touch unrelated readiness flags: a pricing-like dict
    # carrying readiness booleans passes through redaction unchanged.
    pricing_meta = {"pricing_can_be_displayed_as_headline": True, "headline_safe": False,
                    "procurement_ready": False, "diagram_validation": "passed",
                    "token_count": 99, "authorization_required": True}
    assert redact_sensitive(pricing_meta) == pricing_meta
    # And an AuditReadResult exposes no pricing/diagram/readiness attribute.
    result = AuditReadResult(status="degraded")
    assert not any(attr in result.to_dict() for attr in
                   ("headline_safe", "procurement_ready", "diagram_validation"))
