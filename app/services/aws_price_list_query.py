from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import get_settings
from app.models.domain import EvidenceItem
from app.services.pricing_filter_mapper import pricing_filter_plan_for_service


class AWSPriceListQueryClient:
    """Read-only AWS Price List Query API evidence route.

    This client intentionally treats live SKU data as evidence and traceability.
    Archway pricing math remains deterministic unless a later pricing engine
    explicitly consumes SKU dimensions under test.
    """

    def __init__(self):
        self.settings = get_settings()

    async def health_check(self) -> tuple[bool, str, dict[str, Any]]:
        if not _boto3_available():
            return False, "boto3 is not installed for AWS Price List Query API access.", {"configured": False}
        try:
            details = await asyncio.to_thread(self._probe)
            return True, "AWS Price List Query API is reachable with configured AWS credentials.", details
        except Exception as exc:
            return False, f"AWS Price List Query API is unavailable: {type(exc).__name__}.", {"error": str(exc)[:300]}

    async def evidence_for_services(self, services: list[str], region_code: str) -> list[EvidenceItem]:
        if not _boto3_available():
            return []
        return await asyncio.to_thread(self._query_services, services, region_code)

    def _probe(self) -> dict[str, Any]:
        client = _pricing_client(self.settings.bedrock_region)
        response = client.describe_services(MaxResults=1)
        return {
            "configured": True,
            "endpoint_region": "us-east-1",
            "service_count_sampled": len(response.get("Services", [])),
        }

    def _query_services(self, services: list[str], region_code: str) -> list[EvidenceItem]:
        client = _pricing_client(self.settings.bedrock_region)
        evidence: list[EvidenceItem] = []
        seen: set[str] = set()
        for service_name in services:
            plan = pricing_filter_plan_for_service(service_name, region_code=region_code)
            if not plan or plan.service_code in seen:
                continue
            seen.add(plan.service_code)
            filters = [{"Type": "TERM_MATCH", "Field": key, "Value": value} for key, value in plan.filters.items()]
            try:
                response = client.get_products(ServiceCode=plan.service_code, Filters=filters, MaxResults=3)
                price_list = response.get("PriceList") or []
                families, terms, sku_samples = _summarize_price_list(price_list)
                evidence.append(
                    EvidenceItem(
                        source_type="aws_pricing",
                        title=f"AWS Price List Query API products: {plan.service_code}",
                        quote_or_summary=(
                            f"Structured AWS Price List Query API GetProducts matched service recommendation '{service_name}'. "
                            f"ServiceCode={plan.service_code}; filters={plan.filters}; sampled_products={len(price_list)}; "
                            f"product_families={families}; term_types={terms}; sku_samples={sku_samples}. "
                            "Use this as live SKU traceability evidence; Archway deterministic totals remain directional until exact usage dimensions are bound."
                        ),
                        tool_name="AWS Price List Query API",
                        confidence="high" if price_list else "medium",
                    )
                )
            except Exception as exc:
                evidence.append(
                    EvidenceItem(
                        source_type="aws_pricing",
                        title=f"AWS Price List Query API unavailable for {plan.service_code}",
                        quote_or_summary=(
                            f"AWS Price List Query API GetProducts could not retrieve structured products for service recommendation "
                            f"'{service_name}': {type(exc).__name__}. Filters attempted: {plan.filters}."
                        ),
                        tool_name="AWS Price List Query API",
                        confidence="low",
                    )
                )
        return evidence


def _pricing_client(region_name: str):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "pricing",
        region_name="us-east-1",
        config=Config(connect_timeout=5, read_timeout=12, retries={"max_attempts": 2}),
    )


def _boto3_available() -> bool:
    try:
        import boto3  # noqa: F401
        return True
    except Exception:
        return False


def _summarize_price_list(price_list: list[str]) -> tuple[list[str], list[str], list[str]]:
    families: list[str] = []
    terms: list[str] = []
    sku_samples: list[str] = []
    for raw in price_list:
        try:
            item = json.loads(raw)
        except Exception:
            continue
        product = item.get("product") or {}
        attributes = product.get("attributes") or {}
        if product.get("sku"):
            sku_samples.append(str(product["sku"]))
        family = product.get("productFamily") or attributes.get("productFamily")
        if family:
            families.append(str(family))
        terms.extend(str(key) for key in (item.get("terms") or {}).keys())
    return _unique(families, 5), _unique(terms, 5), _unique(sku_samples, 5)


def _unique(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:limit]
