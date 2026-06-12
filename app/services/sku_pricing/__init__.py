"""SKU-backed pricing foundation (additive, standalone).

A small, safe foundation for SKU-backed, reproducible AWS pricing estimates for a
limited service set. It does NOT replace the heuristic pricing engine and is NOT
wired into the live PricingEngine/routes in this branch — running-product
headline/procurement behavior is unchanged.

Core principle: SKU-backed where rate binding is reliable; directional/fail-closed
otherwise. Missing/ambiguous binding never becomes headline-safe, and a
non-authoritative snapshot (static_fixture) never becomes procurement-ready.
"""

from app.services.sku_pricing.binding import RateBinding, UsageDimension, bind_rate
from app.services.sku_pricing.estimate import (
    SkuBackedEstimate,
    SkuBackedLine,
    build_estimate,
    estimate_input_hash,
)
from app.services.sku_pricing.snapshot import (
    AUTHORITATIVE_SOURCES,
    PriceSnapshot,
    RateRecord,
    builtin_fixture_snapshot,
    compute_version_hash,
    load_snapshot,
)

# Local-cache adapter layer (depends on feature/sku-backed-pricing-foundation).
from app.services.sku_pricing.cache import (
    LocalCacheError,
    ProvenanceError,
    build_local_cache_estimate,
    build_local_cache_snapshot,
    build_local_cache_snapshot_from_reduced_price_list,
    compute_source_hash,
    load_local_cache_snapshot,
)
from app.services.sku_pricing.price_list_parser import parse_reduced_price_list
from app.services.sku_pricing.provenance import (
    TRUSTED_UPSTREAM_SOURCES,
    is_authoritative_snapshot,
    provenance_report,
)

# Official offer-file snapshot builder (depends on foundation + local-cache adapter).
from app.services.sku_pricing.official_snapshot_builder import (
    DIMENSION_SPECS,
    SUPPORTED_DIMENSION_KEYS,
    BuildReport,
    DimensionSpec,
    MappingResult,
    SnapshotBuildError,
    build_snapshot_from_offer_files,
    map_offer_products_to_dimension_keys,
    parse_official_offer_file,
    write_local_cache_snapshot,
)

__all__ = [
    "PriceSnapshot",
    "RateRecord",
    "builtin_fixture_snapshot",
    "compute_version_hash",
    "load_snapshot",
    "AUTHORITATIVE_SOURCES",
    "UsageDimension",
    "RateBinding",
    "bind_rate",
    "SkuBackedLine",
    "SkuBackedEstimate",
    "build_estimate",
    "estimate_input_hash",
    # local-cache adapter
    "is_authoritative_snapshot",
    "provenance_report",
    "TRUSTED_UPSTREAM_SOURCES",
    "parse_reduced_price_list",
    "load_local_cache_snapshot",
    "build_local_cache_snapshot",
    "build_local_cache_snapshot_from_reduced_price_list",
    "build_local_cache_estimate",
    "compute_source_hash",
    "LocalCacheError",
    "ProvenanceError",
    # official offer-file snapshot builder
    "DimensionSpec",
    "DIMENSION_SPECS",
    "SUPPORTED_DIMENSION_KEYS",
    "MappingResult",
    "BuildReport",
    "SnapshotBuildError",
    "parse_official_offer_file",
    "map_offer_products_to_dimension_keys",
    "build_snapshot_from_offer_files",
    "write_local_cache_snapshot",
]
