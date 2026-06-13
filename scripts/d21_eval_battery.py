#!/usr/bin/env python3
"""Run the D21 thin open-world evaluation battery.

This runner is deterministic and offline. It does not invoke live agent lanes,
model providers, web search, MCP tools, or package generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agentic.evaluation import run_evaluation_battery, write_evaluation_outputs  # noqa: E402
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the D21 thin evaluation battery.")
    parser.add_argument("--json", action="store_true", help="Emit the result JSON to stdout.")
    parser.add_argument("--output-dir", default="artifacts/d21_eval_battery", help="Directory for result.json and report.md.")
    parser.add_argument("--scenario", help="Run a single scenario_id.")
    parser.add_argument("--fail-on-critical", action="store_true", help="Exit 1 when critical findings are present.")
    args = parser.parse_args(argv)

    scenarios = thin_evaluation_scenarios()
    if args.scenario:
        scenarios = [scenario for scenario in scenarios if scenario.scenario_id == args.scenario]
        if not scenarios:
            print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
            return 2

    result = run_evaluation_battery(scenarios)
    paths = write_evaluation_outputs(result, args.output_dir)

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        critical = sum(1 for finding in result.findings if finding.severity == "critical")
        human = sum(1 for finding in result.findings if finding.severity == "advisory")
        print(f"D21 evaluation battery -> scenarios={len(result.scenarios)} critical={critical} human_review={human}")
        print(f"  result: {paths['json']}")
        print(f"  report: {paths['markdown']}")
        print(f"  reproducibility_hash: {result.reproducibility_hash}")

    if args.fail_on_critical and result.has_critical_findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
