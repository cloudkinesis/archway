#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.open_world_eval import d23_eval_scenarios, run_fixture_eval, run_live_eval  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the D23 open-world understanding eval battery.")
    parser.add_argument("--output-dir", default="artifacts/d23_eval_battery", help="Directory for JSON and Markdown reports.")
    parser.add_argument("--live", action="store_true", help="Run the live Bedrock/refiners-disabled battery instead of the CI-safe fixture battery.")
    parser.add_argument("--scenario", help="Run one scenario_id from the D23 battery.")
    parser.add_argument("--json", action="store_true", help="Print the result JSON to stdout.")
    args = parser.parse_args()
    scenarios = d23_eval_scenarios()
    if args.scenario:
        scenarios = [scenario for scenario in scenarios if scenario.scenario_id == args.scenario]
        if not scenarios:
            print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
            return 2

    if args.live:
        os.environ["ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING"] = "true"
        os.environ["ARCHWAY_DISABLE_DOMAIN_REFINERS"] = "true"
        os.environ["ARCHWAY_AGENTIC_MODE"] = "live_demo"
        os.environ["ARCHWAY_LLM_PROVIDER"] = "bedrock"
        get_settings.cache_clear()
        result = run_live_eval(scenarios=scenarios)
    else:
        result = run_fixture_eval(scenarios=scenarios)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(_report(result), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2))
    print(
        "D23 eval battery:",
        f"mode={result['mode']}",
        f"scenario_count={result['scenario_count']}",
        f"passed={result['passed']}",
        f"failed={result['failed']}",
        f"output={output_dir}",
    )
    return 0 if result["failed"] == 0 else 1


def _report(result: dict) -> str:
    lines = [
        "# D23 Open-World Understanding Eval Battery",
        "",
        f"- mode: `{result['mode']}`",
        f"- scenarios: `{result['scenario_count']}`",
        f"- passed: `{result['passed']}`",
        f"- failed: `{result['failed']}`",
        "",
        _mode_description(result["mode"]),
        "",
        "## Scenarios",
        "",
    ]
    for item in result["results"]:
        status = "PASS" if item["passed"] else "FAIL"
        lines.extend([
            f"### {item['title']}",
            "",
            f"- id: `{item['scenario_id']}`",
            f"- status: `{status}`",
            f"- accepted: `{item['accepted']}`",
            f"- profile source: `{item['profile_source']}`",
            f"- provider: `{item.get('provider')}`",
            f"- live status: `{item.get('live_status')}`",
            f"- preserved terms: {', '.join(item['preserved_terms']) or 'none'}",
            f"- forbidden leaks: {', '.join(item['forbidden_leaks']) or 'none'}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def _mode_description(mode: str) -> str:
    if mode == "live_bedrock_refiners_disabled":
        return (
            "This battery makes live Bedrock calls with `ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING=true`, "
            "`ARCHWAY_DISABLE_DOMAIN_REFINERS=true`, `ARCHWAY_AGENTIC_MODE=live_demo`, and "
            "`ARCHWAY_LLM_PROVIDER=bedrock`. It scores the model-produced canonical understanding directly; "
            "deterministic fallback profiles do not count as passing."
        )
    return (
        "This battery runs with offline fixtures by default. It validates the D23 schema, fact-preservation gate, "
        "service validation, profile adaptation, generated questions, and forbidden-term leakage checks without "
        "using domain-specific refiners or live model calls."
    )


if __name__ == "__main__":
    raise SystemExit(main())
