from __future__ import annotations

from app.domain.source_of_truth import AwsRateBinding, ServiceUsageDimension
from app.services.pricing_authority_resolver import PricingAuthorityResolver


class AwsRateBindingEngine:
    def bind(self, dimension: ServiceUsageDimension, *, region_code: str) -> AwsRateBinding:
        return PricingAuthorityResolver().resolve(dimension, region_code=region_code)
