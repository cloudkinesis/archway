#!/usr/bin/env python3
"""Emit the D21 agentic control-plane status.

This script is deterministic and local-only. It does not call model providers,
the network, GitHub, AWS, MCP tools, or mutate git state.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.agentic.repair_planner import agentic_feature_flags  # noqa: E402
from app.services.dossier_manifest import stable_json_hash  # noqa: E402

BASELINE_COMMIT = "5791b1a60a33e4aaf4aee4a882b3457c8efa588e"
NEXT_BRANCH = "feature/d21-architecture-candidate-agent-audit-only"

D21_TAGS = (
    ("archway-v2-agentic-foundation", "D21 foundation + deterministic repair planner"),
    ("archway-v2-d21-evaluation-battery", "D21 thin evaluation battery"),
    ("archway-v2-d21-research-agent-audit", "D21 research agent audit-only lane"),
    ("archway-v2-d21-use-case-analyst-audit", "D21 use-case analyst audit-only lane"),
    ("archway-v2-d21-pricing-dimension-audit", "D21 pricing-dimension audit-only lane"),
    ("archway-v2-d21-control-plane", "D21 control-plane consolidation checkpoint"),
    ("archway-v2-d21-narrative-reviewer-audit", "D21 narrative and reviewer audit-only lanes"),
)

RAW_ARTIFACTS = (
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
)

AUDIT_ARTIFACTS = (
    "audit_pack/agentic-repair-plan.md",
    "audit_pack/agentic-evaluation-summary.md",
    "audit_pack/agentic-research-summary.md",
    "audit_pack/agentic-use-case-analysis.md",
    "audit_pack/agentic-pricing-dimensions.md",
    "audit_pack/agentic-narrative-proposals.md",
    "audit_pack/agentic-reviewer-findings.md",
    "audit_pack/agentic-diagram-plan.md",
)


def authority_matrix() -> list[dict[str, Any]]:
    rows = [
        ("deterministic baseline", True, True, True, True, True, True, True, True, True, True, False),
        ("repair planner", False, True, True, True, False, False, False, False, False, False, False),
        ("evaluation battery", False, False, True, True, False, False, False, False, False, False, True),
        ("research agent", False, True, True, True, False, False, False, False, False, False, True),
        ("use-case analyst agent", False, True, True, True, False, False, False, False, False, False, True),
        ("pricing-dimension agent", False, True, True, True, False, False, False, False, False, False, True),
        ("narrative agent", False, True, True, True, False, False, False, False, False, False, True),
        ("reviewer agent", False, True, True, True, False, False, False, False, False, False, True),
        ("diagram planning agent", False, True, True, True, False, False, False, False, False, False, True),
        ("future architecture candidate agent", False, False, False, False, False, False, False, False, False, False, True),
    ]
    keys = (
        "component",
        "default_enabled",
        "can_propose",
        "writes_raw",
        "writes_audit_pack",
        "writes_client_pack",
        "can_affect_readiness",
        "can_affect_pricing_math",
        "can_affect_headline_pricing",
        "can_affect_architecture_compiler_truth",
        "can_affect_diagram_rendering",
        "requires_human_review",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def build_status() -> dict[str, Any]:
    settings = get_settings()
    payload = {
        "status_id": "d21-agentic-control-plane-summary",
        "baseline_commit": BASELINE_COMMIT,
        "feature_flags": agentic_feature_flags(settings),
        "llm_provider": settings.llm_provider,
        "d21_tags": [
            {
                "tag": tag,
                "description": description,
                "local_target": _local_tag_target(tag),
            }
            for tag, description in D21_TAGS
        ],
        "authority_matrix": authority_matrix(),
        "raw_artifacts": list(RAW_ARTIFACTS),
        "audit_artifacts": list(AUDIT_ARTIFACTS),
        "client_pack_agent_output_enabled": False,
        "next_recommended_branch": NEXT_BRANCH,
        "notes": [
            "Current D21 lanes are default-off and raw/audit-only.",
            "Deterministic Archway remains the only authority-bearing baseline.",
            "Architecture candidate lane is not implemented yet.",
        ],
    }
    payload["status_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "status_hash"})
    return payload


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# D21 Agentic Control Plane Status",
        "",
        f"Baseline commit: `{payload['baseline_commit']}`",
        f"Status hash: `{payload['status_hash']}`",
        "",
        "## Landed Tags",
        "",
    ]
    for item in payload["d21_tags"]:
        target = item.get("local_target") or "not found locally"
        lines.append(f"- `{item['tag']}` -> `{target}` ({item['description']})")
    lines.extend(["", "## Feature Flags", ""])
    for key, value in sorted(payload["feature_flags"].items()):
        lines.append(f"- `{key}`: `{str(value).lower()}`")
    lines.extend(["", f"- `llm_provider`: `{payload['llm_provider']}`", "", "## Authority Matrix", ""])
    header = "| Component | Default | Propose | Raw | Audit | Client | Readiness | Pricing Math | Headline | Architecture Truth | Diagram | Human Review |"
    lines.extend([header, "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for row in payload["authority_matrix"]:
        lines.append(
            f"| {row['component']} | {_yn(row['default_enabled'])} | {_yn(row['can_propose'])} | "
            f"{_yn(row['writes_raw'])} | {_yn(row['writes_audit_pack'])} | {_yn(row['writes_client_pack'])} | "
            f"{_yn(row['can_affect_readiness'])} | {_yn(row['can_affect_pricing_math'])} | "
            f"{_yn(row['can_affect_headline_pricing'])} | {_yn(row['can_affect_architecture_compiler_truth'])} | "
            f"{_yn(row['can_affect_diagram_rendering'])} | {_yn(row['requires_human_review'])} |"
        )
    lines.extend(["", "## Raw Artifacts", ""])
    lines.extend(f"- `{item}`" for item in payload["raw_artifacts"])
    lines.extend(["", "## Audit Artifacts", ""])
    lines.extend(f"- `{item}`" for item in payload["audit_artifacts"])
    lines.extend([
        "",
        "## Current Boundary",
        "",
        "- No client-facing agent output is enabled.",
        "- Agentic proposal lanes cannot promote readiness, pricing math, headline pricing, architecture truth, diagram rendering, governance, or verifier semantics.",
        f"- Next recommended branch: `{payload['next_recommended_branch']}`.",
        "",
    ])
    return "\n".join(lines)


def _local_tag_target(tag: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", f"{tag}^{{}}"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _yn(value: bool) -> str:
    return "Yes" if value else "No"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit D21 agentic control-plane status.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--output", help="Optional output path.")
    args = parser.parse_args(argv)

    payload = build_status()
    text = payload if args.json else markdown(payload)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        if args.json:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            path.write_text(str(text), encoding="utf-8")
    else:
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
