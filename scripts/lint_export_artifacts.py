"""Lint rendered dossier export artifacts (advisory by default).

Usage:
    .venv/bin/python scripts/lint_export_artifacts.py <export-dir-or-zip> [--strict] [--json]

Advisory mode always exits 0. Strict mode upgrades client-surface findings to
errors and exits 1 when any are present — reserved for client-pack fail-closed
gating after 3 consecutive clean golden harness runs (rollout contract).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.artifact_linter import (  # noqa: E402
    has_blocking_findings,
    lint_export_directory,
    lint_export_zip,
    summarize_findings,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Export package directory or .zip")
    parser.add_argument("--strict", action="store_true", help="Client-surface findings become errors; exit 1 if any")
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON")
    args = parser.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"Target not found: {target}", file=sys.stderr)
        return 2
    if target.is_file() and target.suffix == ".zip":
        findings = lint_export_zip(target, strict=args.strict)
    else:
        findings = lint_export_directory(target, strict=args.strict)

    summary = summarize_findings(findings)
    if args.json:
        print(json.dumps({"summary": summary, "findings": [f.to_dict() for f in findings]}, indent=2))
    else:
        mode = "strict" if args.strict else "advisory"
        print(f"Artifact lint [{mode}] -> {summary['total']} finding(s) "
              f"(errors={summary['errors']}, advisory={summary['advisory']})")
        for finding in findings:
            location = f":{finding.line}" if finding.line else ""
            print(f"  [{finding.severity}] {finding.rule_id} {finding.artifact_path}{location} — {finding.message}")
        if summary["by_rule"]:
            print(f"  by rule: {summary['by_rule']}")

    if args.strict and has_blocking_findings(findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
