"""Deterministic display-label helpers for client-facing dossier prose.

Converts machine identifiers (snake_case driver keys, status enums) into
readable business language at render time only. Raw keys remain unchanged in
JSON and internal artifacts. No model involvement.
"""

from __future__ import annotations

import re

# Canonical casing for common acronyms when humanizing machine keys or
# generating titles. "or" is intentionally absent: as a lowercase word it is
# almost always the conjunction; source-cased "OR" (operating room) is
# preserved by the all-caps rule in callers instead.
ACRONYM_CASING = {
    "ai": "AI",
    "aml": "AML",
    "api": "API",
    "aws": "AWS",
    "cdn": "CDN",
    "cdr": "CDR",
    "dr": "DR",
    "ehr": "EHR",
    "etl": "ETL",
    "hbase": "HBase",
    "hcm": "HCM",
    "hdfs": "HDFS",
    "iam": "IAM",
    "iot": "IoT",
    "kms": "KMS",
    "kyc": "KYC",
    "llm": "LLM",
    "mcp": "MCP",
    "ml": "ML",
    "ocr": "OCR",
    "phi": "PHI",
    "pii": "PII",
    "poc": "POC",
    "qos": "QoS",
    "rag": "RAG",
    "rpo": "RPO",
    "rto": "RTO",
    "sku": "SKU",
    "sla": "SLA",
    "sns": "SNS",
    "sqs": "SQS",
    "vpc": "VPC",
}

# Words a title or display name should never end on (articles, prepositions,
# conjunctions). Used by title generation and session-name truncation.
TITLE_TRAILING_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "in", "into", "is", "its", "of", "on", "or", "over", "per", "that",
    "the", "their", "to", "under", "using", "via", "which", "with",
}

_MACHINE_KEY_PATTERN = re.compile(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+")


def looks_like_machine_key(value: str) -> bool:
    """True for snake_case identifiers like ``schedule_events_per_day``."""
    return bool(_MACHINE_KEY_PATTERN.fullmatch(value.strip()))


def display_label(value: str, *, capitalize: bool = True) -> str:
    """Humanize a machine key or status enum for client-facing prose.

    ``schedule_events_per_day`` -> ``Schedule events per day``
    ``INTERNAL_ONLY`` -> ``Internal only``
    """
    text = str(value or "").replace("_", " ").strip()
    if not text:
        return str(value or "")
    words = [ACRONYM_CASING.get(word.lower(), word.lower()) for word in text.split()]
    label = " ".join(words)
    if capitalize and label and label[0].islower():
        label = label[0].upper() + label[1:]
    return label


def gate_display(value: str) -> str:
    """Humanize only values that look like machine keys; leave prose alone."""
    return display_label(value) if looks_like_machine_key(str(value or "")) else str(value or "")


def format_usd(value) -> str:
    """Format a dollar amount with thousands separators and whole-dollar
    rounding for client-facing prose. Raw numbers stay raw in JSON."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"${value}"
    return f"${number:,.0f}"


def canonical_fact_key(value: str) -> str:
    """Comparison key that collapses naming variants of the same fact.

    ``availability_target`` and ``availability target`` share one key.
    """
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def dedupe_canonical(values: list[str]) -> list[str]:
    """Drop naming-variant duplicates, keeping one entry per canonical fact.

    Preserves first-seen order. When variants collide, the snake_case form is
    kept because it is the stable machine key.
    """
    groups: dict[str, str] = {}
    order: list[str] = []
    for value in values:
        key = canonical_fact_key(value)
        if not key:
            continue
        if key not in groups:
            groups[key] = value
            order.append(key)
        elif "_" in value and "_" not in groups[key]:
            groups[key] = value
    return [groups[key] for key in order]
