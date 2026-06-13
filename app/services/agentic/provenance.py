"""D21 provenance helpers.

This module intentionally adds exactly one new provenance label:
``model_proposed``. It is a proposal origin, not evidence authority, and never
unlocks readiness by itself.
"""

from __future__ import annotations

from typing import Literal

MODEL_PROPOSED = "model_proposed"

AgentProvenance = Literal[
    "SKU_TIER_BACKED",
    "PRICE_LIST_CATALOG_BACKED",
    "PRICING_MCP_BACKED",
    "OFFICIAL_PRICING_PAGE_BACKED",
    "HEURISTIC",
    "NOT_ESTIMATED",
    "deterministic_default",
    "scenario_profile",
    "user_input",
    "derived",
    "confirmed",
    "assumed",
    "missing",
    "bound",
    "ambiguous",
    "not_found",
    "unsupported",
    "unit_mismatch",
    "missing_quantity",
    "understanding_conflict",
    "canonical_fact",
    "catalog",
    "deterministic_ledger",
    "model_proposed",
]

RAW_ALLOWED_PROVENANCE = frozenset({MODEL_PROPOSED})
AUDIT_ALLOWED_PROVENANCE = frozenset({MODEL_PROPOSED})
CLIENT_BLOCKED_PROVENANCE = frozenset({MODEL_PROPOSED})


def can_write_surface(provenance: str, surface: str, *, upgraded: bool = False) -> bool:
    """Return whether a claim with ``provenance`` may write to a surface.

    ``model_proposed`` is allowed in raw/audit traces. It is blocked from the
    client pack unless a deterministic validator has upgraded the claim to a
    grounded/assumed/not-estimated label.
    """
    surface = surface.strip().lower()
    if provenance == MODEL_PROPOSED:
        if surface in {"raw", "audit_pack"}:
            return True
        if surface == "client_pack":
            return bool(upgraded)
        return False
    return surface in {"raw", "audit_pack", "client_pack"}


def can_unlock_readiness(provenance: str) -> bool:
    """D21 invariant: model-proposed claims never unlock readiness."""
    return provenance != MODEL_PROPOSED
