from datetime import datetime
import json
import sqlite3
from uuid import uuid4

from app.core.config import get_settings
from app.models.domain import Session, SessionPhase, SessionStatus, UseCaseBrief, utc_now
from app.services.artifacts import ArtifactStore


class SessionStore:
    def __init__(self):
        self.settings = get_settings()
        self.artifacts = ArtifactStore()
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.settings.database_path)

    def _init_db(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create(self, initial_use_case: str, brief: UseCaseBrief) -> Session:
        session_id = f"sess_{uuid4().hex[:12]}"
        root = self.artifacts.ensure_layout(session_id)
        now = utc_now()
        session = Session(
            id=session_id,
            name=_session_name(brief.title, initial_use_case),
            created_at=now,
            updated_at=now,
            status=SessionStatus.shaping,
            active_phase=SessionPhase.synthesis,
            initial_use_case=initial_use_case,
            current_summary=brief,
            artifacts_path=str(root),
        )
        self.save(session)
        return session

    def save(self, session: Session) -> Session:
        session.updated_at = utc_now()
        payload = session.model_dump_json()
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO sessions (id, payload, updated_at) VALUES (?, ?, ?)",
                (session.id, payload, session.updated_at.isoformat()),
            )
        return session

    def get(self, session_id: str) -> Session | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return Session.model_validate_json(row[0]) if row else None

    def list(self) -> list[Session]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM sessions ORDER BY updated_at DESC").fetchall()
        return [Session.model_validate_json(row[0]) for row in rows]

    def delete(self, session_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0


def _session_name(title: str, raw: str) -> str:
    candidate = title or raw
    return candidate.strip().splitlines()[0][:72] or "New Archway session"

