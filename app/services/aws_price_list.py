from dataclasses import dataclass
import re
import time
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.models.domain import EvidenceItem
from app.services.pricing_filter_mapper import pricing_filter_plan_for_service


_CACHE_TTL_SECONDS = 3600
_INDEX_CACHE: tuple[float, dict] | None = None


@dataclass(frozen=True)
class PriceListOffer:
    offer_code: str
    current_version_url: str
    current_region_index_url: str | None


class AWSPriceListBulkClient:
    def __init__(self):
        self.settings = get_settings()

    async def health_check(self) -> tuple[bool, str, dict]:
        try:
            index = await self._index()
            offers = index.get("offers") or {}
            return True, "AWS Price List Bulk API index is reachable.", {
                "offer_count": len(offers),
                "publication_date": index.get("publicationDate"),
            }
        except Exception as exc:
            return False, f"AWS Price List Bulk API index is unavailable: {type(exc).__name__}.", {}

    async def evidence_for_services(self, services: list[str]) -> list[EvidenceItem]:
        index = await self._index()
        matches = self.match_services(services, index)
        evidence: list[EvidenceItem] = []
        for service, offer in matches:
            evidence.append(
                EvidenceItem(
                    source_type="aws_pricing",
                    title=f"AWS Price List Bulk API offer: {offer.offer_code}",
                    url=offer.current_version_url,
                    quote_or_summary=(
                        f"Structured AWS Price List Bulk API catalog entry matched from service recommendation '{service}'. "
                        f"Matched offer code: {offer.offer_code}. "
                        "Use the service current price list and regional index for SKU, OnDemand terms, and tiered priceDimensions parsing."
                    ),
                    tool_name="AWS Price List Bulk API",
                    confidence="high",
                )
            )
        return evidence

    def match_services(self, services: list[str], index: dict) -> list[tuple[str, PriceListOffer]]:
        offers = index.get("offers") or {}
        normalized_offers = [
            (_normalize(value.get("offerCode") or key), key, value)
            for key, value in offers.items()
            if isinstance(value, dict)
        ]
        results: list[tuple[str, PriceListOffer]] = []
        seen_offer_codes: set[str] = set()
        for service in services:
            mapped = pricing_filter_plan_for_service(service)
            if mapped and mapped.service_code in offers:
                value = offers[mapped.service_code]
                offer_code = str(value.get("offerCode") or mapped.service_code)
                if offer_code not in seen_offer_codes:
                    seen_offer_codes.add(offer_code)
                    results.append((service, _offer_from_index_value(offer_code, value, self.settings.aws_price_list_bulk_index_url)))
                continue
            normalized_service = _normalize(service)
            candidates = [
                (score, key, value)
                for offer_norm, key, value in normalized_offers
                if (score := _match_score(normalized_service, offer_norm)) > 0
            ]
            if not candidates:
                continue
            candidates.sort(key=lambda item: item[0], reverse=True)
            _, key, value = candidates[0]
            offer_code = str(value.get("offerCode") or key)
            if offer_code in seen_offer_codes:
                continue
            seen_offer_codes.add(offer_code)
            results.append((service, _offer_from_index_value(offer_code, value, self.settings.aws_price_list_bulk_index_url)))
        return results

    async def _index(self) -> dict:
        global _INDEX_CACHE
        now = time.monotonic()
        if _INDEX_CACHE and now - _INDEX_CACHE[0] < _CACHE_TTL_SECONDS:
            return _INDEX_CACHE[1]
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(self.settings.aws_price_list_bulk_index_url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload.get("offers"), dict):
            raise RuntimeError("AWS Price List Bulk API index did not include an offers map.")
        _INDEX_CACHE = (now, payload)
        return payload


def _normalize(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.lower())
    noise = {"amazon", "aws", "service", "managed", "for", "the", "data", "streams"}
    return "".join(word for word in words if word not in noise)


def _match_score(service: str, offer: str) -> int:
    if not service or not offer:
        return 0
    if service == offer:
        return 100
    if service in offer or offer in service:
        return min(len(service), len(offer))
    service_tokens = set(re.findall(r"[a-z0-9]+", service))
    offer_tokens = set(re.findall(r"[a-z0-9]+", offer))
    overlap = service_tokens & offer_tokens
    return len(overlap) * 3


def _offer_from_index_value(offer_code: str, value: dict, index_url: str) -> PriceListOffer:
    return PriceListOffer(
        offer_code=offer_code,
        current_version_url=urljoin(index_url, str(value.get("currentVersionUrl") or "")),
        current_region_index_url=urljoin(index_url, str(value.get("currentRegionIndexUrl") or ""))
        if value.get("currentRegionIndexUrl")
        else None,
    )
