#!/usr/bin/env python3
"""RC2 validation harness.

One command that produces an objective validation report for any branch, so we
stop manually re-proving branch health and re-classifying known failures.

Tooling only: it runs tests / build / golden scripts as subprocesses and
classifies the results. It changes no product runtime behavior and makes no
web / Tavily / AWS MCP calls.

Profiles: focused | stabilization | golden | branch
Statuses: PASS FAIL_NEW FAIL_KNOWN READY READY_WITH_KNOWN_ISSUES
          KNOWN_FAIL_NOW_PASSING WARN SKIPPED NOT_RUN BLOCKED

Examples:
    python scripts/rc2_validate.py --profile focused
    python scripts/rc2_validate.py --profile stabilization --frontend
    python scripts/rc2_validate.py --profile golden --skip-full-suite
    python scripts/rc2_validate.py --profile branch --tests tests/test_job_manager_lifecycle.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "f692c04"

# Outcome / status vocabulary (kept as module constants so tests can reference them).
PASS = "PASS"
FAIL_NEW = "FAIL_NEW"
FAIL_KNOWN = "FAIL_KNOWN"
KNOWN_FAIL_NOW_PASSING = "KNOWN_FAIL_NOW_PASSING"
WARN = "WARN"
SKIPPED = "SKIPPED"
NOT_RUN = "NOT_RUN"
BLOCKED = "BLOCKED"
READY = "READY"
READY_WITH_KNOWN_ISSUES = "READY_WITH_KNOWN_ISSUES"
READY_WITH_UNCOMMITTED_CHANGES = "READY_WITH_UNCOMMITTED_CHANGES"
NOT_EVALUATED = "NOT_EVALUATED"


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #
@dataclass
class CommandResult:
    label: str
    cmd: list[str]
    returncode: int | None
    elapsed_s: float
    status: str  # PASS | FAIL_NEW | NOT_RUN | SKIPPED | WARN
    reason: str = ""
    stdout_path: str | None = None
    stderr_tail: str = ""


@dataclass
class KnownFailure:
    test_id: str
    issue_id: str = ""
    reason: str = ""
    severity: str = "unknown"
    blocks_internal_pilot: bool = False
    status: str = "open"


@dataclass
class Classification:
    passed: list[str] = field(default_factory=list)
    failed_new: list[str] = field(default_factory=list)
    failed_known: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    known_now_passing: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "passed": len(self.passed),
            "failed_known": len(self.failed_known),
            "failed_new": len(self.failed_new),
            "skipped": len(self.skipped),
            "known_now_passing": len(self.known_now_passing),
        }


# --------------------------------------------------------------------------- #
# Known-failures loading (structured YAML; JSON-compatible)
# --------------------------------------------------------------------------- #
def load_known_failures(path: Path) -> tuple[dict[str, KnownFailure], str | None]:
    """Return ({test_id: KnownFailure}, warning_or_None). Never raises."""
    if not path.is_file():
        return {}, f"Known-failures file not found: {path}"
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {}, f"PyYAML unavailable and JSON fallback failed: {type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return {}, f"Failed to parse known-failures file: {type(exc).__name__}: {exc}"

    entries = (data or {}).get("known_failures") or []
    known: dict[str, KnownFailure] = {}
    for item in entries:
        if not isinstance(item, dict) or not item.get("test_id"):
            continue
        known[str(item["test_id"])] = KnownFailure(
            test_id=str(item["test_id"]),
            issue_id=str(item.get("issue_id", "")),
            reason=str(item.get("reason", "")),
            severity=str(item.get("severity", "unknown")),
            blocks_internal_pilot=bool(item.get("blocks_internal_pilot", False)),
            status=str(item.get("status", "open")),
        )
    return known, None


# --------------------------------------------------------------------------- #
# Git context
# --------------------------------------------------------------------------- #
def git_context() -> dict:
    def _git(*args: str) -> str:
        try:
            out = subprocess.run(
                ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
            )
            return out.stdout.strip()
        except Exception:  # noqa: BLE001
            return ""

    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    commit = _git("rev-parse", "HEAD") or "unknown"
    short = _git("rev-parse", "--short", "HEAD") or "unknown"
    porcelain = _git("status", "--porcelain")
    return {
        "branch": branch,
        "commit": commit,
        "commit_short": short,
        "dirty": bool(porcelain.strip()),
        "dirty_files": [line[3:] for line in porcelain.splitlines() if line.strip()][:50],
    }


def frontend_changed(base: str = BASELINE_COMMIT) -> bool:
    try:
        merge_base = subprocess.run(
            ["git", "merge-base", "HEAD", "master"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        merge_base = ""
    ref = merge_base or base
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{ref}..HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
        )
        return any(line.startswith("frontend/") for line in out.stdout.splitlines())
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Subprocess runner
# --------------------------------------------------------------------------- #
def run_command(label: str, cmd: list[str], *, cwd: Path | None, out_dir: Path, timeout: int = 1800) -> CommandResult:
    """Run a command, capture exit code + elapsed; write stdout/stderr to a log file."""
    logs = out_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{label}.log"
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        elapsed = round(time.perf_counter() - start, 3)
        return CommandResult(label, cmd, None, elapsed, NOT_RUN, reason=f"command not found: {exc}")
    except subprocess.TimeoutExpired:
        elapsed = round(time.perf_counter() - start, 3)
        return CommandResult(label, cmd, None, elapsed, FAIL_NEW, reason=f"timed out after {timeout}s")
    elapsed = round(time.perf_counter() - start, 3)
    stdout_path.write_text((proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or ""), encoding="utf-8")
    status = PASS if proc.returncode == 0 else FAIL_NEW
    stderr_tail = "\n".join((proc.stderr or "").splitlines()[-8:])
    return CommandResult(label, cmd, proc.returncode, elapsed, status, stdout_path=str(stdout_path), stderr_tail=stderr_tail)


# --------------------------------------------------------------------------- #
# JUnit parsing + classification (pure; unit-tested directly)
# --------------------------------------------------------------------------- #
def _nodeid_from_testcase(classname: str, name: str) -> str:
    """Reconstruct a pytest-style nodeid (tests/file.py::test) from junit attrs."""
    if not classname:
        return name
    parts = classname.split(".")
    # Module path segments are lowercase-ish file names; a trailing CapWord is a class.
    module_parts: list[str] = []
    class_parts: list[str] = []
    for seg in parts:
        if class_parts or (seg[:1].isupper() and module_parts):
            class_parts.append(seg)
        else:
            module_parts.append(seg)
    file_path = "/".join(module_parts) + ".py" if module_parts else ""
    node = "::".join([p for p in (file_path, *class_parts, name) if p])
    return node


def parse_junit(xml_text: str) -> dict[str, str]:
    """Parse junit XML text -> {nodeid: outcome} where outcome in passed/failed/error/skipped."""
    outcomes: dict[str, str] = {}
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return outcomes
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        nodeid = _nodeid_from_testcase(classname, name)
        outcome = "passed"
        for child in case:
            tag = child.tag.lower()
            if tag in {"failure", "error"}:
                outcome = "failed"
                break
            if tag == "skipped":
                outcome = "skipped"
                break
        outcomes[nodeid] = outcome
    return outcomes


def classify(outcomes: dict[str, str], known: dict[str, KnownFailure]) -> Classification:
    result = Classification()
    for nodeid, outcome in outcomes.items():
        is_known = nodeid in known
        if outcome in {"failed", "error"}:
            (result.failed_known if is_known else result.failed_new).append(nodeid)
        elif outcome == "skipped":
            result.skipped.append(nodeid)
        else:  # passed
            if is_known:
                result.known_now_passing.append(nodeid)
            else:
                result.passed.append(nodeid)
    for lst in (result.passed, result.failed_new, result.failed_known, result.skipped, result.known_now_passing):
        lst.sort()
    return result


# --------------------------------------------------------------------------- #
# Headline + recommended action (pure; unit-tested directly)
# --------------------------------------------------------------------------- #
def compute_headline(
    classification: Classification,
    frontend_status: str,
    fail_on_known: bool = False,
    *,
    dirty: bool = False,
    missing_required: bool = False,
) -> tuple[str, str]:
    """Resolve the single headline status, biased against false 'READY'.

    Precedence: a new regression or frontend-build failure BLOCKS. A missing set of
    expected tests downgrades to WARN (coverage gap) unless explicitly allowed.
    Documented known failures yield READY_WITH_KNOWN_ISSUES. A dirty working tree
    must never headline as plain READY.
    """
    # Hard blockers first.
    if classification.failed_new or frontend_status == FAIL_NEW:
        return BLOCKED, "needs fix - new regression(s) outside the known-failures list"
    if fail_on_known and classification.failed_known:
        return BLOCKED, "blocked by known issue (--fail-on-known set)"

    # Base status from coverage + known failures.
    if missing_required:
        base, recommended = WARN, "expected tests are missing; review the NOT_RUN list before treating this branch as ready (or pass --allow-missing-optional-tests)"
    elif classification.failed_known:
        base, recommended = READY_WITH_KNOWN_ISSUES, "ready for review - only documented known failures remain"
    else:
        base, recommended = READY, "ready for review"

    # Dirty tree must not headline as plain READY.
    if dirty:
        if base == READY:
            base = READY_WITH_UNCOMMITTED_CHANGES
        recommended = recommended + " | review uncommitted changes before treating this branch as ready."
    return base, recommended


# --------------------------------------------------------------------------- #
# Profile target resolution
# --------------------------------------------------------------------------- #
PROFILE_TARGETS: dict[str, list[str]] = {
    "focused": [
        "tests/test_discovery_planner.py",
        "tests/test_pricing.py",
        "tests/test_healthcare_anti_drift.py",
        "tests/golden_scenarios/test_scenario_matrix.py",
    ],
    "stabilization": [
        "tests/test_architecture_revision_lifecycle.py",
        "tests/test_synthesis_completion_loop.py",
        "tests/test_export_quality_artifacts.py",
        "tests/test_job_manager_lifecycle.py",
        "tests/test_typed_effectful_flow_detection.py",
        "tests/test_healthcare_anti_drift.py",
        "tests/test_discovery_planner.py",
        "tests/test_pricing.py",
        "tests/golden_scenarios/test_scenario_matrix.py",
    ],
}


def resolve_targets(profile: str, extra_tests: list[str]) -> tuple[list[str], list[dict]]:
    """Return (existing_targets, not_run_records) — missing files are NOT_RUN, not failures."""
    if profile == "branch":
        candidates = list(extra_tests)
    elif profile == "golden":
        candidates = ["tests"] if True else []  # full suite handled separately
        candidates = []
    else:
        candidates = list(PROFILE_TARGETS.get(profile, []))
        candidates += [t for t in extra_tests if t not in candidates]
    existing: list[str] = []
    not_run: list[dict] = []
    for target in candidates:
        file_part = target.split("::", 1)[0]
        if (REPO_ROOT / file_part).exists():
            existing.append(target)
        else:
            not_run.append({"target": target, "status": NOT_RUN, "reason": "test path not present on this branch"})
    return existing, not_run


# --------------------------------------------------------------------------- #
# Golden Gate checklist mapping
# --------------------------------------------------------------------------- #
GATE_TEST_HINTS = {
    "no_cross_domain_leakage": ["test_healthcare_anti_drift", "test_scenario_matrix", "test_research_view_model"],
    "pricing_fail_closed": ["test_pricing_headline_fail_closed", "test_research_view_model"],
    "export_quality_artifacts": ["test_export_quality_artifacts"],
    "stale_revision_protection": ["test_architecture_revision_lifecycle"],
    "typed_governance_detection": ["test_typed_effectful_flow_detection"],
}


def gate_status_for(hints: list[str], outcomes: dict[str, str]) -> str:
    matched = {nid: out for nid, out in outcomes.items() if any(h in nid for h in hints)}
    if not matched:
        return NOT_EVALUATED
    if any(out in {"failed", "error"} for out in matched.values()):
        return FAIL_NEW
    return PASS


# --------------------------------------------------------------------------- #
# Report building (pure)
# --------------------------------------------------------------------------- #
def build_report(
    *,
    context: dict,
    profile: str,
    classification: Classification,
    outcomes: dict[str, str],
    known: dict[str, KnownFailure],
    command_results: list[CommandResult],
    not_run: list[dict],
    frontend_status: str,
    frontend_reason: str,
    golden: dict,
    warnings: list[str],
    headline: str,
    recommended: str,
) -> dict:
    backend_gate = PASS if (outcomes and not classification.failed_new) else (FAIL_NEW if classification.failed_new else NOT_RUN)
    gate = {
        "backend_tests": backend_gate,
        "frontend_build": frontend_status,
        "discovery_baseline": golden.get("discovery_baseline", NOT_RUN),
        "export_validation": golden.get("export_validation", NOT_RUN),
        "pricing_fail_closed": gate_status_for(GATE_TEST_HINTS["pricing_fail_closed"], outcomes),
        "no_cross_domain_leakage": gate_status_for(GATE_TEST_HINTS["no_cross_domain_leakage"], outcomes),
        "export_quality_artifacts": gate_status_for(GATE_TEST_HINTS["export_quality_artifacts"], outcomes),
        "stale_revision_protection": gate_status_for(GATE_TEST_HINTS["stale_revision_protection"], outcomes),
        "typed_governance_detection": gate_status_for(GATE_TEST_HINTS["typed_governance_detection"], outcomes),
    }
    return {
        "schema": "rc2_validation_report_v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "git": context,
        "headline_status": headline,
        "recommended_next_action": recommended,
        "summary": classification.counts,
        "frontend_build": {"status": frontend_status, "reason": frontend_reason},
        "golden": golden,
        "known_failures_matched": [
            {"test_id": t, "issue_id": known[t].issue_id, "reason": known[t].reason, "blocks_internal_pilot": known[t].blocks_internal_pilot}
            for t in classification.failed_known
        ],
        "new_failures": classification.failed_new,
        "known_fail_now_passing": classification.known_now_passing,
        "skipped": classification.skipped,
        "not_run": not_run,
        "commands": [
            {"label": c.label, "returncode": c.returncode, "elapsed_s": c.elapsed_s, "status": c.status, "reason": c.reason, "log": c.stdout_path}
            for c in command_results
        ],
        "golden_gate_checklist": gate,
        "warnings": warnings,
    }


def render_markdown(report: dict) -> str:
    g = report["git"]
    s = report["summary"]
    lines = [
        "# RC2 Validation Report",
        "",
        f"- Timestamp: {report['timestamp']}",
        f"- Profile: `{report['profile']}`",
        f"- Branch: `{g['branch']}`",
        f"- Commit: `{g['commit_short']}` ({g['commit']})",
        f"- Dirty working tree: {g['dirty']}",
        "",
        f"## Headline: {report['headline_status']}",
        f"Recommended next action: {report['recommended_next_action']}",
        "",
        "## Test summary",
        f"- Passed: {s['passed']}",
        f"- Failed (known): {s['failed_known']}",
        f"- Failed (NEW): {s['failed_new']}",
        f"- Known-fail now passing: {s['known_now_passing']}",
        f"- Skipped: {s['skipped']}",
        "",
        "## Frontend build",
        f"- Status: {report['frontend_build']['status']}"
        + (f" ({report['frontend_build']['reason']})" if report['frontend_build']['reason'] else ""),
        "",
        "## New failures (block the report)",
        *([f"- {t}" for t in report["new_failures"]] or ["- None"]),
        "",
        "## Known failures matched (documented exceptions)",
        *([f"- {item['test_id']} [{item['issue_id']}] blocks_pilot={item['blocks_internal_pilot']} — {item['reason']}" for item in report["known_failures_matched"]] or ["- None"]),
        "",
        "## Known-fail now passing (stale known-failure metadata — clean up)",
        *([f"- {t}" for t in report["known_fail_now_passing"]] or ["- None"]),
        "",
        "## Not run (not present on this branch)",
        *([f"- {item['target']}: {item['reason']}" for item in report["not_run"]] or ["- None"]),
        "",
        "## Golden Gate checklist",
        *[f"- {k}: {v}" for k, v in report["golden_gate_checklist"].items()],
        "",
        "## Commands",
        *[f"- {c['label']}: status={c['status']} rc={c['returncode']} {c['elapsed_s']}s" + (f" — {c['reason']}" if c['reason'] else "") for c in report["commands"]],
        "",
        "## Warnings",
        *([f"- {w}" for w in report["warnings"]] or ["- None"]),
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_pytest_group(targets: list[str], out_dir: Path, *, verbose: bool) -> tuple[CommandResult | None, dict[str, str]]:
    if not targets:
        return None, {}
    junit = out_dir / "logs" / "pytest.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", f"--junitxml={junit}", "-o", "junit_family=xunit2"]
    result = run_command("pytest", cmd, cwd=REPO_ROOT, out_dir=out_dir)
    outcomes = parse_junit(junit.read_text(encoding="utf-8")) if junit.is_file() else {}
    # A non-zero pytest exit with no parsed cases (e.g. collection error) is a real problem.
    if result.returncode not in (0, 1) and not outcomes:
        result.status = FAIL_NEW
        result.reason = result.reason or "pytest could not collect/run targets"
    return result, outcomes


def maybe_frontend_build(args, out_dir: Path) -> tuple[str, str, CommandResult | None]:
    changed = frontend_changed()
    if not args.frontend:
        reason = "frontend changed; consider --frontend" if changed else "not requested"
        return NOT_RUN, reason, None
    res = run_command("frontend_build", ["npm", "run", "build"], cwd=REPO_ROOT / "frontend", out_dir=out_dir)
    if res.status == NOT_RUN:  # npm missing but it WAS requested -> treat as failure
        res.status = FAIL_NEW
        res.reason = "npm not available but --frontend was requested"
        return FAIL_NEW, res.reason, res
    return (PASS if res.returncode == 0 else FAIL_NEW), res.reason, res


def run_golden_scripts(profile: str, out_dir: Path) -> tuple[dict, list[CommandResult]]:
    golden = {"discovery_baseline": NOT_RUN, "export_validation": NOT_RUN}
    cmds: list[CommandResult] = []
    if profile != "golden":
        return golden, cmds
    mapping = [
        ("discovery_baseline", "scripts/rc2_discovery_baseline_report.py"),
        ("export_validation", "scripts/rc2_golden_export_validation.py"),
    ]
    for key, rel in mapping:
        if not (REPO_ROOT / rel).exists():
            golden[key] = NOT_RUN
            continue
        res = run_command(key, [sys.executable, rel], cwd=REPO_ROOT, out_dir=out_dir)
        cmds.append(res)
        golden[key] = PASS if res.returncode == 0 else FAIL_NEW
    return golden, cmds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RC2 validation harness (tooling only).")
    parser.add_argument("--profile", choices=["focused", "stabilization", "golden", "branch"], default="focused")
    parser.add_argument("--tests", nargs="*", default=[], help="explicit test paths (branch profile / extras)")
    parser.add_argument("--frontend", action="store_true", help="run frontend build")
    parser.add_argument("--skip-full-suite", action="store_true", help="golden profile: skip full backend suite")
    parser.add_argument("--out-dir", default="artifacts")
    parser.add_argument("--known-issues-file", default="docs/rc2/known_failures.yaml")
    parser.add_argument("--fail-on-known", action="store_true", default=False)
    parser.add_argument(
        "--allow-missing-optional-tests",
        action="store_true",
        default=False,
        help="stabilization: do not downgrade to WARN when expected optional test files are absent",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    out_dir = (REPO_ROOT / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    known, known_warn = load_known_failures((REPO_ROOT / args.known_issues_file).resolve())
    if known_warn:
        warnings.append(known_warn)

    context = git_context()
    command_results: list[CommandResult] = []

    # Resolve and run backend tests.
    if args.profile == "golden" and not args.skip_full_suite:
        targets = ["tests"]
        not_run: list[dict] = []
    else:
        targets, not_run = resolve_targets(args.profile, args.tests)
        if args.profile == "golden":
            warnings.append("Full backend suite skipped (--skip-full-suite).")

    pytest_result, outcomes = run_pytest_group(targets, out_dir, verbose=args.verbose)
    if pytest_result is not None:
        command_results.append(pytest_result)

    classification = classify(outcomes, known)

    # Frontend build.
    frontend_status, frontend_reason, fe_cmd = maybe_frontend_build(args, out_dir)
    if fe_cmd is not None:
        command_results.append(fe_cmd)

    # Golden scripts.
    golden, golden_cmds = run_golden_scripts(args.profile, out_dir)
    command_results.extend(golden_cmds)
    if golden.get("discovery_baseline") == FAIL_NEW or golden.get("export_validation") == FAIL_NEW:
        warnings.append("A golden validation script exited non-zero; see logs.")

    # Stabilization expects its fix-branch test files; missing ones are a coverage
    # gap that downgrades to WARN unless explicitly allowed. (Other profiles treat
    # missing targets as informational only.)
    missing_required = (
        args.profile == "stabilization" and bool(not_run) and not args.allow_missing_optional_tests
    )
    headline, recommended = compute_headline(
        classification,
        frontend_status,
        args.fail_on_known,
        dirty=context.get("dirty", False),
        missing_required=missing_required,
    )
    # Golden script failures also block.
    if args.profile == "golden" and FAIL_NEW in (golden.get("discovery_baseline"), golden.get("export_validation")):
        headline, recommended = BLOCKED, "needs fix - golden validation script failed"

    report = build_report(
        context=context, profile=args.profile, classification=classification, outcomes=outcomes,
        known=known, command_results=command_results, not_run=not_run, frontend_status=frontend_status,
        frontend_reason=frontend_reason, golden=golden, warnings=warnings, headline=headline, recommended=recommended,
    )

    json_path = out_dir / "rc2_validation_report.json"
    md_path = out_dir / "rc2_validation_report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"RC2 validation [{args.profile}] -> {headline}")
    print(f"  passed={report['summary']['passed']} known_fail={report['summary']['failed_known']} "
          f"new_fail={report['summary']['failed_new']} skipped={report['summary']['skipped']} "
          f"known_now_passing={report['summary']['known_now_passing']}")
    print(f"  report: {md_path}")
    if classification.failed_new:
        print("  NEW failures:")
        for t in classification.failed_new:
            print(f"    - {t}")
    if classification.known_now_passing:
        print("  KNOWN_FAIL_NOW_PASSING (clean up known_failures.yaml):")
        for t in classification.known_now_passing:
            print(f"    - {t}")

    # Exit code: 0 unless a new regression (or known fail with --fail-on-known) blocks.
    return 1 if headline == BLOCKED else 0


if __name__ == "__main__":
    raise SystemExit(main())
