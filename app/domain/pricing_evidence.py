from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class PriceDimensionEvidence(BaseModel):
    service_code: str
    sku: str
    product_family: str | None = None
    usage_type: str | None = None
    operation: str | None = None
    location: str | None = None
    region_code: str | None = None
    unit: str
    begin_range: str | None = None
    end_range: str | None = None
    price_per_unit: Decimal
    currency: str
    effective_date: str | None = None
    term_type: Literal["OnDemand", "Reserved", "SavingsPlan", "Other"]
    offer_term_code: str | None = None
    rate_code: str | None = None
    source: Literal["price_list_bulk_api", "price_list_query_api", "pricing_mcp"]
    source_reference: str


class PriceListParseResult(BaseModel):
    service_code: str
    dimensions: list[PriceDimensionEvidence]
    ambiguous_skus: list[str] = []
    failures: list[str] = []
