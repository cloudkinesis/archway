"""Deterministic, surface-aware linter for rendered dossier artifacts.

Makes the dossier prose fixes regression-proof by detecting machine-language
leakage, structural defects, and formatting regressions in generated markdown.
No model involvement; rules are plain regex/string checks.

Surfaces:
- ``client``  — client-facing markdown (README, executive summary, solution
  brief, pricing/architecture summaries, future ``client_pack/``): strict
  prose rules.
- ``audit``   — audit/technical markdown (deep dossier, evidence appendix,
  placement explanations, ADRs, reviewer output, future ``audit_pack/``):
  permissive — structural and repetition rules only; technical keys allowed.
- ``machine`` — JSON, manifests, SKU/pricing traces, compiler diagnostics,
  raw evidence payloads, diagram sources: excluded from prose-style linting
  unless explicitly targeted via ``lint_markdown(..., surface=...)``.

Rollout contract:
- findings are ADVISORY by default everywhere;
- ``strict=True`` upgrades client-surface findings to ``error`` and is
  reserved for client-pack fail-closed gating, to be enabled only after
  3 consecutive clean golden harness runs;
- readiness-tier gate wiring lands in a later branch.

This module never mutates artifacts and is not part of manifest/verifier
semantics.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from zipfile import ZipFile

from app.services.display_labels import TITLE_TRAILING_STOPWORDS

Surface = Literal["client", "audit", "machine"]
Severity = Literal["advisory", "error"]

# Root-level markdown that a client reads first. 04-architecture.md is
# deliberately NOT client surface today: it is a technical rationale document
# (compiler view contracts, governance control metadata) until Branch 3 ships
# a client-pack architecture memo.
CLIENT_SURFACE_NAMES = frozenset({
    "README.md",
    "01-solution-brief.md",
    "02A-executive-summary.md",
    "03-pricing.md",
})

# Markdown that is technical-by-design: rendered traces and compiler
# diagnostics are machine surface even though they are .md files.
MACHINE_SURFACE_NAMES = frozenset({
    "07-diagnostics.md",
    "11-pricing-trace.md",
})

MACHINE_SUFFIXES = frozenset({".json", ".svg", ".d2", ".csv", ".png", ".zip", ".yaml", ".yml", ".txt"})

_H1_PATTERN = re.compile(r"^# (?!#)")
_HEADING_PATTERN = re.compile(r"^(#{1,6}) +(.*\S)\s*$")
_SNAKE_CASE_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_RAW_ENUM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
_REPEATED_PHRASE_PATTERN = re.compile(r"\b((?:[A-Za-z][\w\-']*[ \t]+){2,7}?[A-Za-z][\w\-']*)[ \t]+\1\b", re.IGNORECASE)
_REPEATED_WORD_PATTERN = re.compile(r"\b([A-Za-z]{3,})\s+\1\b", re.IGNORECASE)
_DOUBLE_PUNCTUATION_PATTERN = re.compile(r"(?<!\.)\.\.(?!\.)|\?\.|!\.|,\.")
_UNFORMATTED_DOLLAR_PATTERN = re.compile(r"\$\d{4,}(?:\.\d+)?\b")
_UNFORMATTED_NUMBER_PATTERN = re.compile(r"(?<![\d,.$])\b\d{5,}\b(?![\d,])")
_TRAILING_NUMBER_PATTERN = re.compile(r"\b\d+$")
_INLINE_CODE_PATTERN = re.compile(r"`[^`]*`")
# Ledger-style bullets ("- hospital_count=18", "- availability_target",
# "- assumed_rag_queries_per_day: 200") are technical rows by design — the
# machine key IS the content a user confirms — so token rules skip them,
# exactly like table rows.
_LEDGER_BULLET_PATTERN = re.compile(r"^\s*-\s+[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\s*([=:].*)?$")
# Sections whose body is trace/ledger content by design (SKU traces, driver
# ledgers): token rules skip them even on client surface — the keys are the
# contract. Mirrors the machine-surface exclusion at section granularity.
TECHNICAL_SECTIONS = frozenset({
    "line items",
    "pricing drivers",
    "unknown variables",
})
_BOILERPLATE_PHRASE = "Alternatives remain explicit"


@dataclass(frozen=True)
class LintFinding:
    artifact_path: str
    surface: Surface
    severity: Severity
    rule_id: str
    line: int | None
    message: str
    excerpt: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def classify_surface(artifact_path: str) -> Surface:
    """Classify an artifact path inside an export package."""
    path = PurePosixPath(str(artifact_path).replace("\\", "/"))
    parts = path.parts
    if "client_pack" in parts:
        return "client" if path.suffix == ".md" else "machine"
    if "audit_pack" in parts:
        return "audit" if path.suffix == ".md" else "machine"
    if "raw" in parts:
        return "machine"
    if path.suffix in MACHINE_SUFFIXES or path.name in MACHINE_SURFACE_NAMES:
        return "machine"
    if path.name in CLIENT_SURFACE_NAMES and len(parts) == 1:
        return "client"
    if path.suffix == ".md":
        return "audit"
    return "machine"


# Rules applied per surface. Audit surface is permissive: structure and
# repetition only — technical keys, enums, and raw numbers are acceptable.
CLIENT_RULES = (
    "multiple_h1",
    "duplicate_heading",
    "empty_section",
    "title_trailing_stopword",
    "title_trailing_number",
    "title_truncated_midword",
    "adjacent_repeated_phrase",
    "snake_case_in_prose",
    "raw_enum_in_prose",
    "double_punctuation",
    "unformatted_large_number",
    "repeated_boilerplate",
)
AUDIT_RULES = (
    "multiple_h1",
    "duplicate_heading",
    "empty_section",
    "adjacent_repeated_phrase",
    "repeated_boilerplate",
)


def lint_markdown(
    text: str,
    artifact_path: str,
    *,
    surface: Surface | None = None,
    strict: bool = False,
) -> list[LintFinding]:
    """Lint one markdown artifact. Machine surface returns no findings unless
    an explicit ``surface`` override targets it as client/audit."""
    resolved: Surface = surface or classify_surface(artifact_path)
    if resolved == "machine":
        return []
    rules = CLIENT_RULES if resolved == "client" else AUDIT_RULES
    severity: Severity = "error" if (strict and resolved == "client") else "advisory"

    findings: list[LintFinding] = []

    def add(rule_id: str, line: int | None, message: str, excerpt: str | None = None) -> None:
        findings.append(LintFinding(
            artifact_path=artifact_path,
            surface=resolved,
            severity=severity,
            rule_id=rule_id,
            line=line,
            message=message,
            excerpt=(excerpt or "")[:160] or None,
        ))

    lines = text.split("\n")
    in_fence = False
    in_technical_section = False
    h1_lines: list[int] = []
    seen_headings: dict[str, int] = {}
    heading_stack: list[tuple[int, str]] = []  # (level, title) ancestry
    headings: list[tuple[int, int, str]] = []  # (line_no, level, text)
    prose_lines: list[tuple[int, str]] = []

    for number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _HEADING_PATTERN.match(raw_line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            in_technical_section = title.lower() in TECHNICAL_SECTIONS
            headings.append((number, level, title))
            if _H1_PATTERN.match(raw_line):
                h1_lines.append(number)
            # Duplicate headings are scoped to their parent section: the same
            # subsection name under different parents (e.g. POC vs Production
            # architecture halves) is legitimate structure.
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            parent = " > ".join(t.lower() for _, t in heading_stack)
            heading_stack.append((level, title))
            key = f"{parent}|{level}:{title.lower()}"
            if "duplicate_heading" in rules and key in seen_headings:
                add("duplicate_heading", number,
                    f"Heading '{title}' duplicates line {seen_headings[key]} in the same section.", raw_line)
            seen_headings.setdefault(key, number)
            continue
        if stripped.startswith("|"):
            continue  # tables hold technical values by design
        if in_technical_section:
            continue  # trace/ledger sections keep machine keys by contract
        if _LEDGER_BULLET_PATTERN.match(raw_line):
            continue  # driver/unknown-variable ledger rows keep machine keys
        if stripped:
            prose_lines.append((number, _INLINE_CODE_PATTERN.sub("", raw_line)))

    if "multiple_h1" in rules and len(h1_lines) > 1:
        for extra in h1_lines[1:]:
            add("multiple_h1", extra,
                f"Document has {len(h1_lines)} H1 headings; first at line {h1_lines[0]}.", lines[extra - 1])

    if "empty_section" in rules:
        for index, (number, level, title) in enumerate(headings):
            start = number
            end = headings[index + 1][0] - 1 if index + 1 < len(headings) else len(lines)
            next_level = headings[index + 1][1] if index + 1 < len(headings) else None
            body = [l for l in lines[start:end] if l.strip() and not l.strip().startswith("```")]
            if not body and (next_level is None or next_level <= level):
                add("empty_section", number, f"Section '{title}' has no content.", lines[number - 1])

    for number, level, title in headings:
        plain = title.rstrip(" .:")
        last_word = plain.rsplit(" ", 1)[-1] if " " in plain else plain
        if "title_trailing_stopword" in rules and last_word.lower() in TITLE_TRAILING_STOPWORDS:
            add("title_trailing_stopword", number,
                f"Heading ends in '{last_word}' — looks truncated mid-clause.", title)
        if "title_trailing_number" in rules and _TRAILING_NUMBER_PATTERN.search(plain) and last_word.isdigit():
            add("title_trailing_number", number,
                f"Heading ends in bare number '{last_word}'.", title)
        if "title_truncated_midword" in rules and plain.endswith("-"):
            add("title_truncated_midword", number, "Heading ends in a dangling hyphen.", title)

    for number, line_text in prose_lines:
        if "adjacent_repeated_phrase" in rules:
            match = _REPEATED_PHRASE_PATTERN.search(line_text) or _REPEATED_WORD_PATTERN.search(line_text)
            if match:
                add("adjacent_repeated_phrase", number,
                    f"Adjacent repeated text: '{match.group(1)}'.", line_text.strip())
        if "snake_case_in_prose" in rules:
            for match in _SNAKE_CASE_PATTERN.finditer(line_text):
                token = match.group(0)
                if _RAW_ENUM_PATTERN.fullmatch(token):
                    continue  # reported by raw_enum_in_prose
                add("snake_case_in_prose", number,
                    f"Machine key '{token}' in client prose.", line_text.strip())
        if "raw_enum_in_prose" in rules:
            for match in _RAW_ENUM_PATTERN.finditer(line_text):
                add("raw_enum_in_prose", number,
                    f"Raw status/enum '{match.group(0)}' in client prose.", line_text.strip())
        if "double_punctuation" in rules:
            match = _DOUBLE_PUNCTUATION_PATTERN.search(line_text)
            if match:
                add("double_punctuation", number,
                    f"Double punctuation '{match.group(0)}'.", line_text.strip())
        if "unformatted_large_number" in rules:
            match = _UNFORMATTED_DOLLAR_PATTERN.search(line_text) or _UNFORMATTED_NUMBER_PATTERN.search(line_text)
            if match:
                add("unformatted_large_number", number,
                    f"Large number '{match.group(0)}' lacks thousands separators.", line_text.strip())

    if "repeated_boilerplate" in rules:
        occurrences = [n for n, line_text in enumerate(lines, start=1) if _BOILERPLATE_PHRASE in line_text]
        if len(occurrences) > 1:
            add("repeated_boilerplate", occurrences[1],
                f"'{_BOILERPLATE_PHRASE}...' appears {len(occurrences)} times; expected once per section.",
                lines[occurrences[1] - 1])

    return findings


def lint_export_directory(root: Path | str, *, strict: bool = False) -> list[LintFinding]:
    """Lint every markdown artifact under an extracted export package."""
    root = Path(root)
    findings: list[LintFinding] = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        findings.extend(lint_markdown(path.read_text(encoding="utf-8"), relative, strict=strict))
    return findings


def lint_export_zip(zip_path: Path | str, *, strict: bool = False) -> list[LintFinding]:
    """Lint markdown artifacts inside an export zip without extracting it."""
    findings: list[LintFinding] = []
    with ZipFile(zip_path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".md"):
                continue
            text = archive.read(name).decode("utf-8", errors="replace")
            findings.extend(lint_markdown(text, name, strict=strict))
    return findings


def summarize_findings(findings: list[LintFinding]) -> dict:
    by_rule: dict[str, int] = {}
    by_surface: dict[str, int] = {}
    for finding in findings:
        by_rule[finding.rule_id] = by_rule.get(finding.rule_id, 0) + 1
        by_surface[finding.surface] = by_surface.get(finding.surface, 0) + 1
    return {
        "total": len(findings),
        "errors": sum(1 for f in findings if f.severity == "error"),
        "advisory": sum(1 for f in findings if f.severity == "advisory"),
        "by_rule": dict(sorted(by_rule.items())),
        "by_surface": dict(sorted(by_surface.items())),
    }


def has_blocking_findings(findings: list[LintFinding]) -> bool:
    return any(finding.severity == "error" for finding in findings)
