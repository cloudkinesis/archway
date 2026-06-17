#!/usr/bin/env python3
"""Run the D25 brutal convergence eval battery (offline, deterministic).

Proves the open-world quantity graph / plausibility gate / prose hygiene
generalize across diverse never-coded use cases. No live model calls.
Exit 0 if every scenario passes every golden invariant; 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.d25_convergence_eval import run_convergence_eval  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="D25 convergence quality-gate eval battery.")
    parser.add_argument("--output-dir", default="artifacts/d25_convergence_eval")
    parser.add_argument("--json", action="store_true", help="Print the full JSON result.")
    args = parser.parse_args()

    result = run_convergence_eval()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    print(
        f"D25 convergence battery -> scenarios={result['scenario_count']} "
        f"passed={result['passed']} failed={result['failed']}"
    )
    for item in result["results"]:
        flag = "PASS" if item["passed"] else "FAIL"
        line = (
            f"  [{flag}] {item['scenario_id']:<26} "
            f"events={item['monthly_events']:>15,.0f} storage_gb={item['storage_gb_month']:>11,.0f}"
        )
        print(line)
        if not item["passed"]:
            failing = [name for name, ok in item["checks"].items() if not ok]
            print(f"          failing checks: {failing}")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
