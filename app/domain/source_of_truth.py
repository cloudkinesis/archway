from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


FactSource = Literal["user_input", "synthesis_answer", "derived", "llm_inferred", "default_assumption"]
ValidationStatus = Literal["confirmed", "assumed", "requires_validation", "conflict"]
UsedBy = Literal["pricing", "architecture", "research", "diagram", "governance"]


class CanonicalFact(BaseModel):
    id: str = Field(default_factory=lambda: f"fact_{uuid4().hex[:10]}")
    name: str
    value: str | int | float | bool
    unit: str | None = None
    source: FactSource
    source_text: str | None = None
    confidence: Literal["low", "medium", "high"]
    derived_formula: str | None = None
    used_by: list[UsedBy] = Field(default_factory=list)
    validation_status: ValidationStatus


class CanonicalFactsLedger(BaseModel):
    facts: list[CanonicalFact] = Field(default_factory=list)
    missing_explicit_metrics: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AssumptionRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"asmp_{uuid4().hex[:10]}")
    statement: str
    value: str | int | float | bool | None = None
    unit: str | None = None
    source: Literal["deterministic_default", "scenario_profile", "user_input", "derived"] = "deterministic_default"
    reason: str
    impact_areas: list[Literal["pricing", "architecture", "security", "compliance", "performance", "operations"]]
    confidence: Literal["low", "medium", "high"]
    validation_method: str
    if_wrong: str
    user_editable: bool = True
    impacted_pricing_drivers: list[str] = Field(default_factory=list)
    used_by_driver_ids: list[str] = Field(default_factory=list)
    used_by_line_items: list[str] = Field(default_factory=list)
    used_by_architecture_components: list[str] = Field(default_factory=list)


class AssumptionLedger(BaseModel):
    assumptions: list[AssumptionRecord] = Field(default_factory=list)


class PricingDriverBinding(BaseModel):
    id: str = Field(default_factory=lambda: f"pdb_{uuid4().hex[:10]}")
    driver_name: str
    value: Any = None
    source_fact_id: str | None = None
    assumption_id: str | None = None
    status: Literal["confirmed", "assumed", "missing", "derived"]
    required_for_headline_pricing: bool = False


class ServiceUsageDimension(BaseModel):
    id: str = Field(default_factory=lambda: f"sud_{uuid4().hex[:10]}")
    service_name: str
    usage_name: str
    aws_service_code: str
    quantity: Decimal | None = None
    unit: str
    formula: str
    driver_binding_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    required_rate_dimensions: dict[str, str] = Field(default_factory=dict)


class AwsRateBinding(BaseModel):
    id: str = Field(default_factory=lambda: f"arb_{uuid4().hex[:10]}")
    service_name: str
    aws_service_code: str
    sku: str | None = None
    usage_type: str | None = None
    operation: str | None = None
    product_family: str | None = None
    rate_code: str | None = None
    unit: str | None = None
    begin_range: str | None = None
    end_range: str | None = None
    price_per_unit: Decimal | None = None
    currency: str = "USD"
    effective_date: str | None = None
    source: Literal["price_list_query_api", "price_list_bulk_api", "pricing_mcp", "pricing_page", "unbound"] = "unbound"
    confidence: Literal["high", "medium", "low", "none"] = "none"
    binding_status: Literal["bound", "ambiguous", "not_found", "unsupported"] = "not_found"
    notes: list[str] = Field(default_factory=list)


class PricingLedgerLineItem(BaseModel):
    id: str = Field(default_factory=lambda: f"pli_{uuid4().hex[:10]}")
    service_name: str
    usage_name: str
    quantity: Decimal | None = None
    quantity_unit: str
    formula: str
    rate_binding_id: str | None = None
    unit_price: Decimal | None = None
    monthly_total: Decimal | None = None
    evidence_class: Literal[
        "sku_tier_backed",
        "pricing_mcp_backed",
        "official_pricing_page_backed",
        "price_catalog_referenced",
        "heuristic",
        "not_estimated",
    ]
    procurement_ready: bool
    confidence: Literal["high", "medium", "low"]
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PricingLedgerSummary(BaseModel):
    sku_tier_backed_subtotal: Decimal = Decimal("0")
    pricing_page_or_mcp_backed_subtotal: Decimal = Decimal("0")
    heuristic_subtotal: Decimal = Decimal("0")
    not_estimated_items: list[str] = Field(default_factory=list)
    headline_safe: bool
    procurement_ready: bool


class PricingLedger(BaseModel):
    line_items: list[PricingLedgerLineItem] = Field(default_factory=list)
    summary: PricingLedgerSummary
