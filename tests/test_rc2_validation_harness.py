"""Unit tests for the RC2 validation harness (scripts/rc2_validate.py).

Fast and deterministic: pure classification/headline/report logic is tested
directly, and the few subprocess touchpoints are mocked. No real pytest run,
no network, no slow work.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

# Load the script module by path (it lives under scripts/, not an importable package).
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rc2_validate.py"
_spec = importlib.util.spec_from_file_location("rc2_validate", _SCRIPT)
rc2 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rc2  # register so dataclasses can resolve module annotations
_spec.loader.exec_module(rc2)  # type: ignore


def _known(*test_ids: str) -> dict:
    return {tid: rc2.KnownFailure(test_id=tid, issue_id="I1", reason="documented") for tid in test_ids}


# 1. Known failure classification
def test_known_failure_is_classified_fail_known():
    outcomes = {"tests/test_a.py::test_x": "failed"}
    known = _known("tests/test_a.py::test_x")
    c = rc2.classify(outcomes, known)
    assert c.failed_known == ["tests/test_a.py::test_x"]
    assert c.failed_new == []


# 2. New failure classification
def test_new_failure_is_classified_fail_new():
    outcomes = {"tests/test_a.py::test_y": "failed"}
    c = rc2.classify(outcomes, _known("tests/test_a.py::test_x"))
    assert c.failed_new == ["tests/test_a.py::test_y"]
    assert c.failed_known == []


# Known-fail now passing
def test_known_fail_now_passing_is_flagged():
    outcomes = {"tests/test_a.py::test_x": "passed"}
    c = rc2.classify(outcomes, _known("tests/test_a.py::test_x"))
    assert c.known_now_passing == ["tests/test_a.py::test_x"]
    assert c.passed == []


# Headline logic — anti-laundering
def test_headline_blocked_on_new_failure():
    c = rc2.Classification(failed_new=["tests/test_a.py::test_y"])
    status, _ = rc2.compute_headline(c, rc2.NOT_RUN, fail_on_known=False)
    assert status == rc2.BLOCKED


def test_headline_ready_with_known_issues_only():
    c = rc2.Classification(failed_known=["tests/test_a.py::test_x"], passed=["tests/test_a.py::test_ok"])
    status, _ = rc2.compute_headline(c, rc2.NOT_RUN, fail_on_known=False)
    assert status == rc2.READY_WITH_KNOWN_ISSUES


def test_headline_ready_when_clean():
    c = rc2.Classification(passed=["tests/test_a.py::test_ok"])
    status, _ = rc2.compute_headline(c, rc2.PASS, fail_on_known=False, dirty=False)
    assert status == rc2.READY


def test_dirty_tree_downgrades_ready():
    c = rc2.Classification(passed=["tests/test_a.py::test_ok"])
    status, rec = rc2.compute_headline(c, rc2.PASS, dirty=True)
    assert status == rc2.READY_WITH_UNCOMMITTED_CHANGES
    assert status != rc2.READY
    assert "uncommitted changes" in rec


def test_missing_expected_tests_downgrades_to_warn_by_default():
    c = rc2.Classification(passed=["tests/test_a.py::test_ok"])  # all run tests pass
    status, rec = rc2.compute_headline(c, rc2.PASS, missing_required=True)
    assert status == rc2.WARN
    assert status != rc2.READY
    assert "missing" in rec.lower()


def test_allow_missing_optional_tests_preserves_ready():
    # When the caller passes the flag, missing_required is False -> READY preserved.
    c = rc2.Classification(passed=["tests/test_a.py::test_ok"])
    status, _ = rc2.compute_headline(c, rc2.PASS, missing_required=False, dirty=False)
    assert status == rc2.READY


def test_new_failure_blocks_even_when_dirty_and_missing():
    c = rc2.Classification(failed_new=["tests/test_a.py::test_y"])
    status, _ = rc2.compute_headline(c, rc2.PASS, dirty=True, missing_required=True)
    assert status == rc2.BLOCKED


def test_dirty_keeps_known_issues_headline_but_notes_uncommitted():
    c = rc2.Classification(failed_known=["tests/test_a.py::test_x"])
    status, rec = rc2.compute_headline(c, rc2.NOT_RUN, dirty=True)
    assert status == rc2.READY_WITH_KNOWN_ISSUES  # already not plain READY
    assert "uncommitted changes" in rec


def test_fail_on_known_blocks():
    c = rc2.Classification(failed_known=["tests/test_a.py::test_x"])
    status, _ = rc2.compute_headline(c, rc2.NOT_RUN, fail_on_known=True)
    assert status == rc2.BLOCKED


def test_frontend_failure_blocks_headline():
    c = rc2.Classification(passed=["tests/test_a.py::test_ok"])
    status, _ = rc2.compute_headline(c, rc2.FAIL_NEW, fail_on_known=False)
    assert status == rc2.BLOCKED


# JUnit parsing + nodeid reconstruction
def test_parse_junit_and_nodeid_reconstruction():
    xml = """<?xml version='1.0'?>
    <testsuites><testsuite>
      <testcase classname='tests.test_a' name='test_ok'/>
      <testcase classname='tests.test_a' name='test_bad'><failure>boom</failure></testcase>
      <testcase classname='tests.test_a' name='test_skip'><skipped/></testcase>
    </testsuite></testsuites>"""
    outcomes = rc2.parse_junit(xml)
    assert outcomes["tests/test_a.py::test_ok"] == "passed"
    assert outcomes["tests/test_a.py::test_bad"] == "failed"
    assert outcomes["tests/test_a.py::test_skip"] == "skipped"


# 3. Report generation (markdown + JSON with branch, commit, profile, status)
def test_report_generation_has_core_fields(tmp_path):
    context = {"branch": "feature/x", "commit": "abc123def", "commit_short": "abc123d", "dirty": False, "dirty_files": []}
    classification = rc2.Classification(passed=["tests/test_a.py::test_ok"], failed_known=["tests/test_b.py::test_known"])
    outcomes = {"tests/test_a.py::test_ok": "passed", "tests/test_b.py::test_known": "failed"}
    known = _known("tests/test_b.py::test_known")
    report = rc2.build_report(
        context=context, profile="focused", classification=classification, outcomes=outcomes, known=known,
        command_results=[], not_run=[], frontend_status=rc2.NOT_RUN, frontend_reason="not requested",
        golden={"discovery_baseline": rc2.NOT_RUN, "export_validation": rc2.NOT_RUN}, warnings=[],
        headline=rc2.READY_WITH_KNOWN_ISSUES, recommended="ready for review - known only",
    )
    assert report["git"]["branch"] == "feature/x"
    assert report["git"]["commit"] == "abc123def"
    assert report["profile"] == "focused"
    assert report["headline_status"] == rc2.READY_WITH_KNOWN_ISSUES
    assert report["known_failures_matched"][0]["test_id"] == "tests/test_b.py::test_known"
    # JSON-serializable and renderable.
    json.dumps(report)
    md = rc2.render_markdown(report)
    assert "RC2 Validation Report" in md
    assert "feature/x" in md
    assert "READY_WITH_KNOWN_ISSUES" in md


# 4. Dirty tree detection
def test_dirty_tree_detection(monkeypatch):
    def fake_run(cmd, *a, **k):
        text = ""
        if cmd[:2] == ["git", "rev-parse"] and "--abbrev-ref" in cmd:
            text = "feature/x"
        elif cmd[:2] == ["git", "rev-parse"] and "--short" in cmd:
            text = "abc123d"
        elif cmd[:2] == ["git", "rev-parse"]:
            text = "abc123def456"
        elif cmd[:2] == ["git", "status"]:
            text = " M app/foo.py\n?? bar.py\n"
        return types.SimpleNamespace(stdout=text, stderr="", returncode=0)

    monkeypatch.setattr(rc2.subprocess, "run", fake_run)
    ctx = rc2.git_context()
    assert ctx["dirty"] is True
    assert ctx["branch"] == "feature/x"
    assert ctx["commit_short"] == "abc123d"
    assert ctx["dirty_files"]  # at least one changed path captured
    assert any(f.endswith("foo.py") for f in ctx["dirty_files"])


# 5. Command result parsing: exit code + elapsed recorded
def test_run_command_records_exit_code_and_elapsed(monkeypatch, tmp_path):
    def fake_run(cmd, *a, **k):
        return types.SimpleNamespace(stdout="hello", stderr="warn", returncode=0)

    monkeypatch.setattr(rc2.subprocess, "run", fake_run)
    res = rc2.run_command("demo", ["echo", "hi"], cwd=None, out_dir=tmp_path)
    assert res.returncode == 0
    assert res.status == rc2.PASS
    assert res.elapsed_s >= 0
    assert Path(res.stdout_path).is_file()


def test_run_command_missing_binary_is_not_run(monkeypatch, tmp_path):
    def fake_run(cmd, *a, **k):
        raise FileNotFoundError("npm")

    monkeypatch.setattr(rc2.subprocess, "run", fake_run)
    res = rc2.run_command("frontend_build", ["npm", "run", "build"], cwd=tmp_path, out_dir=tmp_path)
    assert res.status == rc2.NOT_RUN
    assert "not found" in res.reason


# Known-failures loader reads the structured file
def test_load_known_failures_reads_yaml(tmp_path):
    # Parse a self-contained fixture so this test does not couple to the LIVE
    # known_failures.yaml contents (entries are removed once fixed — by design).
    sample = tmp_path / "known_failures.yaml"
    sample.write_text(
        "schema: rc2_known_failures_v1\n"
        "known_failures:\n"
        '  - test_id: "tests/test_example.py::test_known_fail"\n'
        '    issue_id: "I999"\n'
        '    reason: "fixture entry"\n'
        "    severity: low\n"
        "    blocks_internal_pilot: false\n"
        '    added_date: "2026-06-10"\n'
        "    status: open\n",
        encoding="utf-8",
    )
    known, warn = rc2.load_known_failures(sample)
    assert warn is None
    assert any("tests/test_example.py::test_known_fail" in tid for tid in known)
    # The LIVE file must always load cleanly, whether or not entries remain.
    live_known, live_warn = rc2.load_known_failures(Path(rc2.REPO_ROOT) / "docs" / "rc2" / "known_failures.yaml")
    assert live_warn is None
    assert isinstance(live_known, dict)


def test_load_known_failures_missing_file_warns(tmp_path):
    known, warn = rc2.load_known_failures(tmp_path / "nope.yaml")
    assert known == {}
    assert warn and "not found" in warn
