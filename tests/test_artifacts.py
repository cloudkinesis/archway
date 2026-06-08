from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.artifacts import ArtifactStore


def test_artifact_store_blocks_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    store = ArtifactStore()
    session_id = "sess_test"
    store.ensure_layout(session_id)

    with pytest.raises(HTTPException):
        store.resolve(session_id, "../secret.txt")


def test_artifact_store_writes_inside_session_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    store = ArtifactStore()

    artifact_id = store.write_json("sess_test", "brief", "current", {"ok": True})

    assert artifact_id == "brief/current.json"
    assert store.resolve("sess_test", artifact_id).is_file()

