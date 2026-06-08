from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_harness():
    path = Path(__file__).resolve().parents[1] / "scripts" / "rc2_discovery_baseline_report.py"
    spec = importlib.util.spec_from_file_location("rc2_discovery_baseline_report", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rc2_discovery_baseline_matrix_has_no_domain_drift():
    harness = _load_harness()

    results = harness.run_matrix(write_artifact=False)
    errors = harness.validate_results(results)

    assert len(results) == 7
    assert not errors, "\n".join(errors)
