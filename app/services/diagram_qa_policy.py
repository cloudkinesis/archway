from __future__ import annotations

from typing import Any


NON_BLOCKING_DIAGRAM_QA_CODES = frozenset(
    {
        "aws_service_catalog_fallback",
        "too_many_edge_crossings",
        "too_many_visible_edges",
    }
)

RENDER_BLOCKING_DIAGRAM_QA_TERMS = (
    "blank",
    "empty svg",
    "compile",
    "syntax",
    "renderer failed",
    "png failed",
    "svg failed",
    "missing artifact",
    "file not found",
)


def diagnostic_code(diagnostic: Any) -> str:
    if isinstance(diagnostic, dict):
        return str(diagnostic.get("code") or "").lower()
    return ""


def diagnostic_severity(diagnostic: Any) -> str:
    if isinstance(diagnostic, dict):
        return str(diagnostic.get("severity") or "").lower()
    return ""


def diagram_qa_has_render_blocking_terms(diagnostics: list[Any]) -> bool:
    text = " ".join(str(item) for item in diagnostics).lower()
    return any(term in text for term in RENDER_BLOCKING_DIAGRAM_QA_TERMS)


def diagram_qa_is_render_blocking(qa: dict) -> bool:
    if qa.get("passed", False):
        return False
    diagnostics = qa.get("diagnostics") or []
    if not diagnostics:
        return True
    if diagram_qa_has_render_blocking_terms(diagnostics):
        return True
    for item in diagnostics:
        if diagnostic_code(item) in NON_BLOCKING_DIAGRAM_QA_CODES:
            continue
        if diagnostic_severity(item) in {"critical", "error", "fatal"}:
            return True
    return False


def diagram_qa_is_layout_or_catalog_only(qa: dict) -> bool:
    diagnostics = qa.get("diagnostics") or []
    if not diagnostics:
        return False
    if diagram_qa_has_render_blocking_terms(diagnostics):
        return False
    for item in diagnostics:
        code = diagnostic_code(item)
        severity = diagnostic_severity(item)
        if code in NON_BLOCKING_DIAGRAM_QA_CODES:
            continue
        if severity != "info":
            return False
    return True
