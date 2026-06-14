from pathlib import Path
from uuid import uuid4
import json
import shutil

from fastapi import HTTPException

from app.core.config import get_settings


class ArtifactStore:
    def __init__(self):
        self.settings = get_settings()

    def session_root(self, session_id: str) -> Path:
        root = (self.settings.sessions_dir / session_id).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def ensure_layout(self, session_id: str) -> Path:
        root = self.session_root(session_id)
        for name in ("brief", "research", "pricing", "architecture", "diagrams/poc", "diagrams/production", "logs", "traces", "evidence", "exports"):
            (root / name).mkdir(parents=True, exist_ok=True)
        return root

    def write_json(self, session_id: str, category: str, name: str, payload: object) -> str:
        path = self._safe_path(session_id, category, f"{name}.json")
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return self.to_artifact_id(session_id, path)

    def write_text(self, session_id: str, category: str, name: str, content: str) -> Path:
        path = self._safe_path(session_id, category, name)
        path.write_text(content, encoding="utf-8")
        return path

    def copy_file(self, session_id: str, category: str, source: Path, name: str | None = None) -> str:
        target = self._safe_path(session_id, category, name or source.name)
        shutil.copy2(source, target)
        return self.to_artifact_id(session_id, target)

    def resolve(self, session_id: str, artifact_id: str) -> Path:
        root = self.session_root(session_id)
        relative = Path(artifact_id)
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(status_code=404, detail="Artifact was not found.")
        path = (root / relative).resolve()
        if not path.is_file() or root not in path.parents:
            raise HTTPException(status_code=404, detail="Artifact was not found.")
        return path

    def to_artifact_id(self, session_id: str, path: Path) -> str:
        root = self.session_root(session_id)
        resolved = path.resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError("Artifact path escapes the session root.")
        return str(resolved.relative_to(root))

    def _safe_path(self, session_id: str, category: str, filename: str) -> Path:
        safe_name = "".join(char for char in filename if char.isalnum() or char in "._-").strip(".")
        if not safe_name:
            safe_name = f"artifact-{uuid4().hex}.json"
        root = self.session_root(session_id)
        category_path = Path(category)
        if category_path.is_absolute() or ".." in category_path.parts:
            raise ValueError("Unsafe artifact category.")
        directory = (root / category_path).resolve()
        if root not in directory.parents and directory != root:
            raise ValueError("Artifact category escapes the session root.")
        directory.mkdir(parents=True, exist_ok=True)
        return directory / safe_name
