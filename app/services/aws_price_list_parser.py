from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.pricing_evidence import PriceDimensionEvidence, PriceListParseResult


def parse_price_list_offer(
    payload: dict[str, Any],
    *,
    service_code: str,
    source_reference: str,
    source: str = "price_list_bulk_api",
    filters: dict[str, str] | None = None,
    currency: str = "USD",
) -> PriceListParseResult:
    products = payload.get("products") if isinstance(payload, dict) else None
    terms = payload.get("terms") if isinstance(payload, dict) else None
    if not isinstance(products, dict):
        return PriceListParseResult(service_code=service_code, dimensions=[], failures=["Missing products map."])
    if not isinstance(terms, dict):
        return PriceListParseResult(service_code=service_code, dimensions=[], failures=["Missing terms map."])

    matching_skus = [
        sku for sku, product in products.items()
        if _product_matches(product, filters or {})
    ]
    if not matching_skus:
        return PriceListParseResult(service_code=service_code, dimensions=[], failures=["No products matched pricing filters."])

    dimensions: list[PriceDimensionEvidence] = []
    failures: list[str] = []
    for sku in matching_skus:
        product = products.get(sku) or {}
        attributes = product.get("attributes") if isinstance(product, dict) else {}
        product_family = product.get("productFamily") if isinstance(product, dict) else None
        on_demand_terms = ((terms.get("OnDemand") or {}).get(sku) or {}) if isinstance(terms.get("OnDemand"), dict) else {}
        dimensions.extend(
            _parse_term_dimensions(
                service_code=service_code,
                sku=sku,
                product_family=product_family,
                attributes=attributes if isinstance(attributes, dict) else {},
                term_type="OnDemand",
                terms_for_sku=on_demand_terms,
                source=source,
                source_reference=source_reference,
                currency=currency,
                failures=failures,
            )
        )
    ambiguous = matching_skus if len(matching_skus) > 1 else []
    if not dimensions and not failures:
        failures.append("Matched products did not include parseable OnDemand price dimensions.")
    return PriceListParseResult(
        service_code=service_code,
        dimensions=dimensions,
        ambiguous_skus=ambiguous,
        failures=failures,
    )


def parse_price_list_query_response(
    response: dict[str, Any],
    *,
    service_code: str,
    source_reference: str,
    filters: dict[str, str] | None = None,
    source: str = "price_list_query_api",
) -> PriceListParseResult:
    import json

    products: dict[str, Any] = {}
    terms: dict[str, Any] = {"OnDemand": {}}
    failures: list[str] = []
    for index, raw in enumerate(response.get("PriceList", []), start=1):
        try:
            item = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            failures.append(f"PriceList item {index} was not valid JSON: {exc.msg}.")
            continue
        product = item.get("product") or {}
        sku = product.get("sku")
        if not sku:
            failures.append(f"PriceList item {index} did not contain product.sku.")
            continue
        products[sku] = product
        for sku_key, term in (item.get("terms", {}).get("OnDemand", {}) or {}).items():
            if not isinstance(term, dict):
                continue
            grouped_sku = str(term.get("sku") or sku_key).split(".", 1)[0]
            if "priceDimensions" in term:
                terms["OnDemand"].setdefault(grouped_sku, {})[sku_key] = term
            else:
                terms["OnDemand"].setdefault(grouped_sku, {}).update(term)
    payload = {"products": products, "terms": terms}
    result = parse_price_list_offer(
        payload,
        service_code=service_code,
        source_reference=source_reference,
        source=source,
        filters=filters,
    )
    result.failures.extend(failures)
    return result


def _parse_term_dimensions(
    *,
    service_code: str,
    sku: str,
    product_family: str | None,
    attributes: dict[str, Any],
    term_type: str,
    terms_for_sku: dict[str, Any],
    source: str,
    source_reference: str,
    currency: str,
    failures: list[str],
) -> list[PriceDimensionEvidence]:
    dimensions: list[PriceDimensionEvidence] = []
    for offer_term_code, term in terms_for_sku.items():
        if not isinstance(term, dict):
            continue
        price_dimensions = term.get("priceDimensions") or {}
        for rate_code, price_dimension in price_dimensions.items():
            if not isinstance(price_dimension, dict):
                continue
            price_value = (price_dimension.get("pricePerUnit") or {}).get(currency)
            try:
                price = Decimal(str(price_value))
            except (InvalidOperation, TypeError):
                failures.append(f"SKU {sku} rate {rate_code} did not include a parseable {currency} price.")
                continue
            dimensions.append(
                PriceDimensionEvidence(
                    service_code=service_code,
                    sku=sku,
                    product_family=product_family,
                    usage_type=attributes.get("usagetype") or attributes.get("usageType"),
                    operation=attributes.get("operation"),
                    location=attributes.get("location"),
                    region_code=attributes.get("regionCode"),
                    unit=str(price_dimension.get("unit") or "unknown"),
                    begin_range=str(price_dimension.get("beginRange")) if price_dimension.get("beginRange") is not None else None,
                    end_range=str(price_dimension.get("endRange")) if price_dimension.get("endRange") is not None else None,
                    price_per_unit=price,
                    currency=currency,
                    effective_date=term.get("effectiveDate"),
                    term_type=term_type,
                    offer_term_code=offer_term_code,
                    rate_code=rate_code,
                    source=source,
                    source_reference=source_reference,
                )
            )
    return dimensions


def _product_matches(product: Any, filters: dict[str, str]) -> bool:
    if not filters:
        return True
    if not isinstance(product, dict):
        return False
    attributes = product.get("attributes") or {}
    if not isinstance(attributes, dict):
        return False
    for key, expected in filters.items():
        if expected is None:
            continue
        actual = attributes.get(key)
        if actual is None:
            actual = attributes.get(_alternate_key(key))
        if str(actual or "").lower() != str(expected).lower():
            return False
    return True


def _alternate_key(key: str) -> str:
    aliases = {"usageType": "usagetype", "usagetype": "usageType"}
    return aliases.get(key, key)
