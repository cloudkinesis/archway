from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_harness():
    path = Path(__file__).resolve().parents[1] / "scripts" / "rc2_golden_export_validation.py"
    spec = importlib.util.spec_from_file_location("rc2_golden_export_validation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rc2_golden_export_validation_legal_smoke(tmp_path):
    harness = _load_harness()

    results = harness.run_validation(
        ["legal_contract_rag"],
        out=tmp_path / "rc2_golden_export_validation_report.md",
        data_dir=tmp_path / "archway-data",
        write_report=True,
    )

    assert len(results) == 1
    assert results[0]["status"] in {"PASS", "WARN"}
    assert not results[0]["blockers"], "\n".join(results[0]["blockers"])
    assert Path(results[0]["export_zip_path"]).is_file()
