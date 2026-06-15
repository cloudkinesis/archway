#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.open_world_eval import run_fixture_eval


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the D23 open-world understanding eval battery.")
    parser.add_argument("--output-dir", default="artifacts/d23_eval_battery", help="Directory for JSON and Markdown reports.")
    args = parser.parse_args()

    result = run_fixture_eval()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(_report(result), encoding="utf-8")
    print(
        "D23 eval battery:",
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
        "This battery runs with offline fixtures by default. It validates the D23 schema, fact-preservation gate,",
        "service validation, profile adaptation, generated questions, and forbidden-term leakage checks without",
        "using domain-specific refiners or live model calls.",
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
            f"- preserved terms: {', '.join(item['preserved_terms']) or 'none'}",
            f"- forbidden leaks: {', '.join(item['forbidden_leaks']) or 'none'}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
