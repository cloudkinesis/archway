#!/usr/bin/env python3
"""Local D21 demo-readiness check.

This script is deterministic and local-only. It does not call GitHub, AWS, MCP,
model providers, the network, or mutate repository/package state.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agentic.evaluation import is_client_agent_output_allowed, run_evaluation_battery  # noqa: E402
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios  # noqa: E402
from app.services.artifact_linter import lint_export_zip, summarize_findings  # noqa: E402
from scripts.d21_agentic_status import build_status  # noqa: E402
from scripts.verify_solution_dossier import verify  # noqa: E402

CLIENT_FORBIDDEN = re.compile(
    r"agentic research|agentic use-case analysis|agentic pricing dimensions|agentic narrative|"
    r"agentic reviewer|agentic diagram plan|agentic architecture candidate|"
    r"model_proposed|AgentProposal|AgentRun|prompt_hash|response_hash|raw proposal|"
    r"NotImplementedError|ARCHWAY_ENABLE_AGENTIC",
    re.IGNORECASE,
)

EXPECTED_CLIENT = {
    "client_pack/START_HERE.md",
    "client_pack/01-executive-memo.md",
    "client_pack/02-solution-brief.md",
    "client_pack/03-architecture-summary.md",
    "client_pack/04-pricing-summary.md",
    "client_pack/05-risks-and-gates.md",
    "client_pack/06-evidence-summary.md",
    "client_pack/07-diagrams-index.md",
}

EXPECTED_AUDIT = {
    "audit_pack/README.md",
    "audit_pack/view-fallback-notes.md",
    "audit_pack/agentic-repair-plan.md",
    "audit_pack/agentic-evaluation-summary.md",
    "audit_pack/agentic-research-summary.md",
    "audit_pack/agentic-use-case-analysis.md",
    "audit_pack/agentic-pricing-dimensions.md",
    "audit_pack/agentic-narrative-proposals.md",
    "audit_pack/agentic-reviewer-findings.md",
    "audit_pack/agentic-diagram-plan.md",
    "audit_pack/agentic-architecture-candidates.md",
}

EXPECTED_RAW = {
    "raw/agent_runs.json",
    "raw/agent_proposals.json",
    "raw/agent_repair_plan.json",
    "raw/agent_evaluation_battery.json",
    "raw/agent_research_trace.json",
    "raw/agent_research_evidence.json",
    "raw/agent_use_case_analyst_trace.json",
    "raw/agent_use_case_analyst_proposal.json",
    "raw/agent_pricing_dimension_trace.json",
    "raw/agent_pricing_dimension_proposal.json",
    "raw/agent_narrative_trace.json",
    "raw/agent_narrative_proposals.json",
    "raw/agent_reviewer_trace.json",
    "raw/agent_reviewer_findings.json",
    "raw/agent_diagram_plan_trace.json",
    "raw/agent_diagram_plan_proposal.json",
    "raw/agent_architecture_candidate_trace.json",
    "raw/agent_architecture_candidate_proposal.json",
}


def build_report(package_paths: list[Path]) -> dict[str, Any]:
    status = build_status()
    battery = run_evaluation_battery(thin_evaluation_scenarios())
    payload = {
        "status": {
            "baseline_commit": status["baseline_commit"],
            "client_pack_agent_output_enabled": status["client_pack_agent_output_enabled"],
            "live_agent_providers_enabled": status["live_agent_providers_enabled"],
            "feature_flags": status["feature_flags"],
            "next_recommended_mode": status["next_recommended_mode"],
        },
        "authority_ok": _authority_ok(status),
        "battery": {
            "scenario_count": len(battery.scenarios),
            "critical_findings": sum(1 for finding in battery.findings if finding.severity == "critical"),
            "human_review_findings": sum(1 for finding in battery.findings if finding.severity == "advisory"),
            "client_agent_output_allowed": is_client_agent_output_allowed(battery).client_agent_output_allowed,
            "reproducibility_hash": battery.reproducibility_hash,
        },
        "packages": [_package_report(path) for path in package_paths],
    }
    package_failures = [
        item for item in payload["packages"]
        if not item["valid"] or item["missing"] or item["lint"]["total"] or item["client_pack_leaks"]
    ]
    payload["passed"] = (
        payload["authority_ok"]
        and payload["battery"]["scenario_count"] == 10
        and payload["battery"]["critical_findings"] == 0
        and payload["battery"]["human_review_findings"] > 0
        and not payload["battery"]["client_agent_output_allowed"]
        and not package_failures
    )
    return payload


def _authority_ok(status: dict[str, Any]) -> bool:
    if any(status["feature_flags"].values()):
        return False
    if status["client_pack_agent_output_enabled"] or status["live_agent_providers_enabled"]:
        return False
    for row in status["authority_matrix"]:
        if row["component"] == "deterministic baseline":
            continue
        if row["default_enabled"] or row["writes_client_pack"]:
            return False
        if any(row[key] for key in (
            "can_affect_readiness",
            "can_affect_pricing_math",
            "can_affect_headline_pricing",
            "can_affect_architecture_compiler_truth",
            "can_affect_diagram_rendering",
        )):
            return False
    return True


def _package_report(zip_path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="archway_d21_check_") as tmp:
        root = Path(tmp) / zip_path.stem
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(root)
            names = set(archive.namelist())
            leaks = []
            for name in sorted(item for item in names if item.startswith("client_pack/") and not item.endswith("/")):
                try:
                    text = archive.read(name).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if CLIENT_FORBIDDEN.search(text):
                    leaks.append(name)
        valid, errors, notes = verify(root)
    missing = sorted((EXPECTED_CLIENT | EXPECTED_AUDIT | EXPECTED_RAW) - names)
    lint = summarize_findings(lint_export_zip(zip_path))
    return {
        "package": str(zip_path),
        "valid": valid,
        "errors": errors,
        "notes": notes,
        "missing": missing,
        "lint": lint,
        "client_pack_leaks": leaks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local D21 demo-readiness checks.")
    parser.add_argument("packages", nargs="*", help="Optional export package zip files to verify.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)

    report = build_report([Path(item) for item in args.packages])
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"D21 demo readiness -> {'PASS' if report['passed'] else 'CHECK'}")
        print(f"  baseline={report['status']['baseline_commit']}")
        print(f"  authority_ok={report['authority_ok']}")
        print(f"  scenarios={report['battery']['scenario_count']} critical={report['battery']['critical_findings']} human_review={report['battery']['human_review_findings']}")
        for package in report["packages"]:
            print(f"  package={package['package']}")
            print(f"    valid={package['valid']} missing={len(package['missing'])} lint={package['lint']['total']} client_leaks={len(package['client_pack_leaks'])}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
