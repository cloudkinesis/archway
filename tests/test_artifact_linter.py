"""Tests for the deterministic, surface-aware artifact linter (Branch 2).

Advisory by default; strict mode reserved for future client-pack fail-closed
gating. The linter never mutates artifacts and never gates golden validation
at introduction.
"""

from __future__ import annotations

import json
from zipfile import ZipFile

from app.services.artifact_linter import (
    classify_surface,
    has_blocking_findings,
    lint_export_directory,
    lint_export_zip,
    lint_markdown,
    summarize_findings,
)

CLIENT_PATH = "02A-executive-summary.md"


def _rules(findings):
    return {finding.rule_id for finding in findings}


# --------------------------------------------------------------------------- #
# Surface classification
# --------------------------------------------------------------------------- #
def test_surface_classification():
    assert classify_surface("README.md") == "client"
    assert classify_surface("02A-executive-summary.md") == "client"
    assert classify_surface("03-pricing.md") == "client"
    assert classify_surface("client_pack/executive-memo.md") == "client"
    # Technical rationale documents are audit surface.
    assert classify_surface("04-architecture.md") == "audit"
    assert classify_surface("02B-deep-research-dossier.md") == "audit"
    assert classify_surface("architecture/decision_records.md") == "audit"
    assert classify_surface("diagrams/poc/arch_1/placement_explanations.md") == "audit"
    assert classify_surface("audit_pack/anything.md") == "audit"
    # Machine surface: JSON, manifests, traces, diagnostics, raw payloads.
    assert classify_surface("manifest.json") == "machine"
    assert classify_surface("dossier_manifest.json") == "machine"
    assert classify_surface("raw/pricing.json") == "machine"
    assert classify_surface("raw/anything.md") == "machine"
    assert classify_surface("11-pricing-trace.md") == "machine"
    assert classify_surface("07-diagnostics.md") == "machine"
    assert classify_surface("diagrams/poc/arch_1/data_access_view/diagram.d2") == "machine"
    assert classify_surface("diagrams/poc/arch_1/data_access_view/diagram.svg") == "machine"


# --------------------------------------------------------------------------- #
# Rule detections (client surface)
# --------------------------------------------------------------------------- #
def test_duplicate_heading_detection():
    text = "# Title\n\n## Summary\n\ncontent\n\n## Summary\n\nmore\n"
    findings = lint_markdown(text, CLIENT_PATH)
    assert "duplicate_heading" in _rules(findings)


def test_duplicate_heading_scoped_to_parent_section():
    # The same subsection name under different parents (POC vs Production
    # architecture halves) is legitimate structure, not a duplicate.
    text = (
        "# Architecture\n\n## POC Architecture (poc)\n\nsummary\n\n### Security Controls\n\n- a\n\n"
        "## Production Architecture (production)\n\nsummary\n\n### Security Controls\n\n- b\n"
    )
    findings = lint_markdown(text, "04-architecture.md")
    assert "duplicate_heading" not in _rules(findings)


def test_multiple_h1_detection():
    text = "# First\n\ncontent\n\n# Second\n\nmore\n"
    findings = lint_markdown(text, CLIENT_PATH)
    matches = [f for f in findings if f.rule_id == "multiple_h1"]
    assert matches and matches[0].line == 5


def test_adjacent_repeated_phrase_detection():
    text = "# Title\n\nControlled API entry point Controlled API entry point selected.\n"
    findings = lint_markdown(text, CLIENT_PATH)
    assert "adjacent_repeated_phrase" in _rules(findings)


def test_title_ending_in_stopword():
    text = "# Operating Room Delay Prediction With\n\ncontent\n"
    findings = lint_markdown(text, CLIENT_PATH)
    assert "title_trailing_stopword" in _rules(findings)


def test_title_ending_in_bare_number():
    text = "# Contract Platform With 5 000\n\ncontent\n"
    findings = lint_markdown(text, CLIENT_PATH)
    assert "title_trailing_number" in _rules(findings)


def test_title_truncated_midword_indicator():
    text = "# Obligation-Tracking Platform Multi-\n\ncontent\n"
    findings = lint_markdown(text, CLIENT_PATH)
    assert "title_truncated_midword" in _rules(findings)


def test_snake_case_in_client_prose():
    text = "# Title\n\nThe workload is schedule_events_per_day driven.\n"
    findings = lint_markdown(text, CLIENT_PATH)
    matches = [f for f in findings if f.rule_id == "snake_case_in_prose"]
    assert matches and "schedule_events_per_day" in matches[0].message


def test_raw_enum_in_client_prose():
    text = "# Title\n\nReadiness: INTERNAL_ONLY for now.\n"
    findings = lint_markdown(text, CLIENT_PATH)
    matches = [f for f in findings if f.rule_id == "raw_enum_in_prose"]
    assert matches and "INTERNAL_ONLY" in matches[0].message
    # Not double-reported as snake_case.
    assert not [f for f in findings if f.rule_id == "snake_case_in_prose"]


def test_empty_section_detection():
    text = "# Title\n\n## Confirmed Drivers\n\n## Next Steps\n\n- one item\n"
    findings = lint_markdown(text, CLIENT_PATH)
    matches = [f for f in findings if f.rule_id == "empty_section"]
    assert matches and "Confirmed Drivers" in matches[0].message


def test_double_punctuation_detection():
    text = "# Title\n\nDegrades gracefully when unavailable..\n"
    findings = lint_markdown(text, CLIENT_PATH)
    assert "double_punctuation" in _rules(findings)
    # Ellipsis is not flagged.
    clean = lint_markdown("# Title\n\nMore to come...\n", CLIENT_PATH)
    assert "double_punctuation" not in _rules(clean)


def test_unformatted_large_number_detection():
    text = "# Title\n\nExpected monthly cost is $10570.0 for this scenario.\n"
    findings = lint_markdown(text, CLIENT_PATH)
    assert "unformatted_large_number" in _rules(findings)
    clean = lint_markdown("# Title\n\nExpected monthly cost is $10,570 for this scenario.\n", CLIENT_PATH)
    assert "unformatted_large_number" not in _rules(clean)


def test_repeated_adr_boilerplate_detection():
    text = (
        "# ADRs\n\nAlternatives remain explicit where cost may change selection.\n\n"
        "Body.\n\nAlternatives remain explicit where cost may change selection.\n"
    )
    findings = lint_markdown(text, "architecture/decision_records.md")
    assert "repeated_boilerplate" in _rules(findings)


# --------------------------------------------------------------------------- #
# Surface behavior
# --------------------------------------------------------------------------- #
def test_machine_surface_excluded(tmp_path):
    payload = {"availability_target": "INTERNAL_ONLY", "cost": 10570}
    assert lint_markdown(json.dumps(payload), "raw/pricing.json") == []
    assert lint_markdown("status INTERNAL_ONLY..", "11-pricing-trace.md") == []
    # Explicit targeting overrides the exclusion.
    targeted = lint_markdown("# T\n\nstatus INTERNAL_ONLY here.\n", "11-pricing-trace.md", surface="client")
    assert "raw_enum_in_prose" in _rules(targeted)


def test_audit_surface_is_permissive_for_technical_keys():
    text = "# Doc\n\nThe driver schedule_events_per_day is INTERNAL_ONLY scoped.\n\ncontent\n"
    findings = lint_markdown(text, "02B-deep-research-dossier.md")
    assert "snake_case_in_prose" not in _rules(findings)
    assert "raw_enum_in_prose" not in _rules(findings)
    # But structural defects are still caught on audit surface.
    dup = lint_markdown("# A\n\ncontent\n\n# B\n\nmore\n", "02B-deep-research-dossier.md")
    assert "multiple_h1" in _rules(dup)


def test_technical_sections_and_ledger_bullets_exempt_on_client_surface():
    text = (
        "# Pricing\n\nProse line is clean.\n\n"
        "## Pricing Drivers\n- hospital_count=18\n- scheduled_surgeries_per_day=32\n\n"
        "## Unknown Variables\n- availability_target\n\n"
        "## Summary\n- assumed_rag_queries_per_day: 200\n"
    )
    findings = lint_markdown(text, "03-pricing.md")
    assert "snake_case_in_prose" not in _rules(findings)


def test_tables_and_code_fences_exempt():
    text = (
        "# Title\n\n| usage_driver | monthly_estimate |\n|---|---|\n| rag_queries_per_day | 200 |\n\n"
        "```\nsnake_case_token = INTERNAL_ONLY\n```\n\nProse stays clean.\n"
    )
    findings = lint_markdown(text, CLIENT_PATH)
    assert "snake_case_in_prose" not in _rules(findings)
    assert "raw_enum_in_prose" not in _rules(findings)


# --------------------------------------------------------------------------- #
# Advisory default / strict mode
# --------------------------------------------------------------------------- #
def test_findings_are_advisory_by_default():
    text = "# Title\n\nstatus INTERNAL_ONLY..\n"
    findings = lint_markdown(text, CLIENT_PATH)
    assert findings
    assert all(f.severity == "advisory" for f in findings)
    assert not has_blocking_findings(findings)


def test_strict_mode_upgrades_client_findings_only():
    text = "# A\n\ncontent\n\n# B\n\nmore\n"
    client = lint_markdown(text, CLIENT_PATH, strict=True)
    assert client and all(f.severity == "error" for f in client)
    assert has_blocking_findings(client)
    audit = lint_markdown(text, "02B-deep-research-dossier.md", strict=True)
    assert audit and all(f.severity == "advisory" for f in audit)


def test_finding_fields_complete():
    findings = lint_markdown("# T\n\nbad_token in prose.\n", CLIENT_PATH)
    finding = findings[0]
    payload = finding.to_dict()
    assert payload["artifact_path"] == CLIENT_PATH
    assert payload["surface"] == "client"
    assert payload["severity"] == "advisory"
    assert payload["rule_id"] == "snake_case_in_prose"
    assert payload["line"] == 3
    assert payload["message"]
    assert payload["excerpt"]


# --------------------------------------------------------------------------- #
# Directory / zip entry points
# --------------------------------------------------------------------------- #
def test_lint_export_directory_and_zip(tmp_path):
    (tmp_path / "README.md").write_text("# Title\n\nstatus INTERNAL_ONLY here.\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "pricing.json").write_text('{"x_y": 1}', encoding="utf-8")
    dir_findings = lint_export_directory(tmp_path)
    assert _rules(dir_findings) == {"raw_enum_in_prose"}

    zip_path = tmp_path / "package.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("README.md", "# Title\n\nstatus INTERNAL_ONLY here.\n")
        archive.writestr("raw/pricing.json", '{"x_y": 1}')
    zip_findings = lint_export_zip(zip_path)
    assert _rules(zip_findings) == {"raw_enum_in_prose"}

    summary = summarize_findings(zip_findings)
    assert summary["total"] == 1
    assert summary["advisory"] == 1
    assert summary["errors"] == 0
    assert summary["by_surface"] == {"client": 1}
