"""Offline official AWS Price List snapshot builder.

Reads operator-provided **official AWS Price List service offer files** from local
disk, deterministically reduces them into Archway's compact ``local_cache``
snapshot schema, hashes the **raw official source bytes**, and stamps enough
provenance to make the resulting rates genuinely rate-authoritative.

Trust rule (why this exists): the foundation/local-cache layers proved the SKU
*mechanism* against hand-authored fixtures. Fixtures are NEVER authoritative. A
``local_cache`` snapshot may be authoritative ONLY if its bytes came from an
official AWS Price List offer file and ``source_hash`` is computed over those raw
bytes — not over a hand-reduced intermediate. This module is that bridge.

Hard constraints:
- Offline only. No network calls, no AWS credentials, no boto3.
- Deterministic mapping from official offer fields -> Archway dimension keys.
- Fail closed: ambiguous / missing / multi-tier / free-tier-only / unit mismatch /
  region mismatch / non-USD never emit a rate.
- Supported service/dimension set is the existing 6-service pilot set only.

DEPENDS ON: feature/sku-backed-pricing-foundation, feature/sku-pricing-local-cache-adapter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.services.sku_pricing.cache import LOCAL_CACHE_SCHEMA_VERSION
from app.services.sku_pricing.snapshot import (
    PriceSnapshot,
    RateRecord,
    _canonical_unit,
    _finalize,
)

BUILDER_VERSION = "1.0"
MAPPING_VERSION = "1.0"
# Upstream provenance label for offer-file-derived caches (added to the trusted set).
UPSTREAM_SOURCE = "aws_price_list_bulk_api"
DEFAULT_UPSTREAM_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json"

# Region code -> official AWS Price List ``location`` attribute string.
REGION_LOCATIONS = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
}

# Region code -> the usagetype prefix AWS uses for that region (e.g. "USE1-...").
# Real us-east-1 offer files use both prefixed and bare usagetypes for some services;
# the builder prefers the region-prefixed form and falls back to the bare form.
REGION_USAGE_PREFIX = {
    "us-east-1": "USE1-",
    "us-east-2": "USE2-",
    "us-west-1": "USW1-",
    "us-west-2": "USW2-",
    "eu-west-1": "EUW1-",
    "eu-central-1": "EUC1-",
}

# Dimensions intentionally NOT emitted from official offer files, with the reason.
# Validated against real us-east-1 offer files (2026-06): these fail closed by design.
UNSUPPORTED_OFFICIAL_DIMENSIONS = {
    "eventbridge_custom_events": (
        "Official AWS EventBridge pricing (offerCode AWSEvents) bills custom events per "
        "'64K-Chunks' unit, which does not match the pilot's per-'Events' model without an "
        "unverified <=64KB event-size assumption. Fail closed pending a unit-model decision."
    ),
}


class SnapshotBuildError(ValueError):
    """Raised for invalid offer input or when no authoritative rate can be emitted."""


@dataclass(frozen=True)
class DimensionSpec:
    """Deterministic predicate mapping official offer products -> an Archway dimension key.

    Predicates use EXACT usagetype matching (with region-prefix awareness) rather than
    substrings, because real AWS offer files carry many near-name variants (IA-, Repl-,
    ARM-, Edge-, Files-, Tables-, Global-) that would otherwise collide. ``offer_code`` is
    the AWS offerCode / product ``servicecode`` (e.g. AWSQueueService for SQS); the
    emitted ``service_code`` / ``service_name`` stay stable for pilot binding.
    """

    dimension_key: str
    service_name: str            # emitted; must align with the pilot UsageDimension.service_name
    service_code: str            # emitted (friendly, stable)
    offer_code: str              # AWS offerCode / product attributes.servicecode to match
    expected_unit: str           # Archway billable unit (canonicalized for binding)
    usage_type_exact: str        # bare usagetype; region-prefixed form preferred when present
    attribute_equals: dict = field(default_factory=dict)  # attribute key -> required value
    product_family: str | None = None     # match product["productFamily"] when set
    # Official units that differ in name but mean the same billable unit, accepted ONLY
    # when the official fields prove it (see unit_alias_proof_contains). Output is always
    # normalized to expected_unit. Empty for most specs (no broad unit coercion).
    unit_aliases: tuple[str, ...] = ()
    # ALL tokens must appear (case-insensitive) across (usagetype + price-dim description)
    # before an alias unit is accepted. Fail closed if the proof is absent.
    unit_alias_proof_contains: tuple[str, ...] = ()


# The supported set, validated against real us-east-1 offer files (2026-06). Each spec
# must resolve to exactly one product + one deterministically-selected paid OnDemand tier.
DIMENSION_SPECS: tuple[DimensionSpec, ...] = (
    DimensionSpec("s3_standard_storage_gb_month", "Amazon S3", "AmazonS3", "AmazonS3", "GB-Mo",
                  "TimedStorage-ByteHrs", {"storageClass": "General Purpose", "volumeType": "Standard"}, "Storage"),
    DimensionSpec("lambda_requests", "AWS Lambda", "AWSLambda", "AWSLambda", "Requests",
                  "Request", {"group": "AWS-Lambda-Requests"}, "Serverless"),
    # Lambda duration: real us-east-1 unit is "Lambda-GB-Second". Accept that (and other
    # GB-second spellings) ONLY when the usagetype/description proves GB-second duration;
    # normalize output to canonical "GB-Second".
    DimensionSpec("lambda_gb_seconds", "AWS Lambda", "AWSLambda", "AWSLambda", "GB-Second",
                  "Lambda-GB-Second", {"group": "AWS-Lambda-Duration"}, "Serverless",
                  unit_aliases=("Lambda-GB-Second", "GB-Seconds", "Second", "Seconds", "second", "seconds"),
                  unit_alias_proof_contains=("GB-Second",)),
    DimensionSpec("sqs_requests", "Amazon SQS", "AmazonSQS", "AWSQueueService", "Requests",
                  "Requests-RBP", {}, "API Request"),
    # eventbridge_custom_events: intentionally unsupported (see UNSUPPORTED_OFFICIAL_DIMENSIONS).
    DimensionSpec("dynamodb_read_request_units", "Amazon DynamoDB", "AmazonDynamoDB", "AmazonDynamoDB",
                  "ReadRequestUnits", "ReadRequestUnits", {}, "Amazon DynamoDB PayPerRequest Throughput"),
    DimensionSpec("dynamodb_write_request_units", "Amazon DynamoDB", "AmazonDynamoDB", "AmazonDynamoDB",
                  "WriteRequestUnits", "WriteRequestUnits", {}, "Amazon DynamoDB PayPerRequest Throughput"),
    DimensionSpec("dynamodb_storage_gb_month", "Amazon DynamoDB", "AmazonDynamoDB", "AmazonDynamoDB", "GB-Mo",
                  "TimedStorage-ByteHrs", {}, "Database Storage"),
    DimensionSpec("cwl_ingestion_gb", "Amazon CloudWatch Logs", "AmazonCloudWatch", "AmazonCloudWatch", "GB",
                  "DataProcessing-Bytes", {}, "Data Payload"),
    DimensionSpec("cwl_storage_gb_month", "Amazon CloudWatch Logs", "AmazonCloudWatch", "AmazonCloudWatch", "GB-Mo",
                  "TimedStorage-ByteHrs", {}, "Storage Snapshot"),
)

SPECS_BY_SERVICE: dict[str, list[DimensionSpec]] = {}
for _spec in DIMENSION_SPECS:
    SPECS_BY_SERVICE.setdefault(_spec.offer_code, []).append(_spec)

SUPPORTED_DIMENSION_KEYS = tuple(s.dimension_key for s in DIMENSION_SPECS)


# --------------------------------------------------------------------------- #
# Parsing + deterministic mapping
# --------------------------------------------------------------------------- #
def _num(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _attrs(product: dict) -> dict:
    return product.get("attributes") or {}


def parse_official_offer_file(path: str | Path) -> tuple[dict, bytes]:
    """Read an official AWS Price List offer file. Returns ``(offer_dict, raw_bytes)``.

    The raw bytes are returned so the caller can hash the *official source*, not a
    re-serialized intermediate.
    """
    raw = Path(path).read_bytes()
    try:
        offer = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SnapshotBuildError(f"Invalid offer file {path}: {exc}") from exc
    if not isinstance(offer, dict) or "products" not in offer:
        raise SnapshotBuildError(f"Offer file {path} is not an AWS Price List offer document.")
    return offer, raw


def _passes_static_predicate(spec: DimensionSpec, product: dict, attrs: dict) -> bool:
    """Service / productFamily / attribute predicate, ignoring location + usagetype."""
    service_code = attrs.get("servicecode")
    if service_code is not None and str(service_code) != spec.offer_code:
        return False
    if spec.product_family and str(product.get("productFamily", "")) != spec.product_family:
        return False
    for key, value in spec.attribute_equals.items():
        if str(attrs.get(key, "")).strip().lower() != str(value).strip().lower():
            return False
    return True


def _flatten_ondemand(offer: dict, sku: str) -> list[dict]:
    on_demand = ((offer.get("terms") or {}).get("OnDemand") or {}).get(sku) or {}
    dims: list[dict] = []
    for term in on_demand.values():
        for pd_id, price_dim in (term.get("priceDimensions") or {}).items():
            dims.append({**price_dim, "_pd_id": pd_id})
    return dims


def _unit_accepted(price_dim: dict, spec: DimensionSpec, attrs: dict) -> bool:
    """Whether a price dimension's official unit may back this spec's expected unit.

    Exact (canonical) match always accepted. A configured alias unit (e.g. Lambda
    duration priced in "Second") is accepted ONLY when every proof token appears in
    the official usagetype + price-dim description — never a broad coercion.
    """
    official = _canonical_unit(str(price_dim.get("unit", "")))
    if official == _canonical_unit(spec.expected_unit):
        return True
    if not spec.unit_aliases:
        return False
    if official not in {_canonical_unit(alias) for alias in spec.unit_aliases}:
        return False
    proof_text = (str(attrs.get("usagetype", "")) + " " + str(price_dim.get("description", ""))).lower()
    return all(token.lower() in proof_text for token in spec.unit_alias_proof_contains)


def _select_price_dimension(price_dims: list[dict], spec: DimensionSpec, attrs: dict) -> tuple[dict | None, str | None]:
    """Pick the standard first paid OnDemand tier. Fail closed on any ambiguity."""
    if not price_dims:
        return None, "missing_ondemand"
    unit_matched = [pd for pd in price_dims if _unit_accepted(pd, spec, attrs)]
    if not unit_matched:
        return None, "unit_mismatch"
    usd = [pd for pd in unit_matched if "USD" in (pd.get("pricePerUnit") or {})]
    if not usd:
        return None, "non_usd_currency"
    paid = [pd for pd in usd if (_num((pd.get("pricePerUnit") or {}).get("USD")) or Decimal(0)) > 0]
    if not paid:
        return None, "free_tier_only"
    if len(paid) == 1:
        return paid[0], None
    # Multi-tier: only auto-select when there is exactly one unambiguous first (beginRange 0) paid tier.
    begin_zero = [pd for pd in paid if str(pd.get("beginRange", "0")) == "0"]
    if len(begin_zero) == 1:
        return begin_zero[0], None
    return None, "ambiguous_tier"


@dataclass
class MappingResult:
    rates: list[RateRecord] = field(default_factory=list)
    mapped: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def map_offer_products_to_dimension_keys(offer: dict, *, region: str, service_code: str | None = None) -> MappingResult:
    """Deterministically map one official offer document to Archway rate records.

    For each supported dimension of the offer's service: find products matching the
    spec predicate. Require exactly one product AND one deterministically-selected
    paid OnDemand tier; otherwise record a skip reason and emit no rate.
    """
    region_location = REGION_LOCATIONS.get(region)
    if region_location is None:
        raise SnapshotBuildError(f"Unsupported region '{region}'; no official location mapping is known.")

    region_prefix = REGION_USAGE_PREFIX.get(region, "")
    code = service_code or offer.get("offerCode")
    specs = SPECS_BY_SERVICE.get(code, [])
    products = offer.get("products") or {}
    result = MappingResult()
    if not specs:
        result.skipped.append({"service_code": code, "reason": "unsupported_service"})
        return result

    for spec in specs:
        # Static predicate (service / family / attrs), location- and usagetype-agnostic.
        base = [
            (sku, p, _attrs(p)) for sku, p in products.items()
            if _passes_static_predicate(spec, p, _attrs(p))
        ]
        # Prefer the region-prefixed exact usagetype; fall back to the bare form.
        targets = ([region_prefix + spec.usage_type_exact] if region_prefix else []) + [spec.usage_type_exact]
        candidates: list[tuple] = []
        for target in targets:
            here = [(sku, p, a) for (sku, p, a) in base
                    if a.get("usagetype") == target and a.get("location") == region_location]
            if here:
                candidates = here
                break

        if not candidates:
            # Distinguish region mismatch (exists elsewhere) from genuinely-not-found.
            exists_other_region = any(a.get("usagetype") in targets for (_, _, a) in base)
            reason = "region_mismatch" if exists_other_region else "not_found"
            result.skipped.append({"dimension_key": spec.dimension_key, "reason": reason})
            continue
        if len(candidates) > 1:
            result.skipped.append({
                "dimension_key": spec.dimension_key,
                "reason": "ambiguous_product",
                "candidate_skus": sorted(sku for sku, _, _ in candidates),
            })
            continue

        sku, product, attrs = candidates[0]
        price_dims = _flatten_ondemand(offer, sku)
        selected, reason = _select_price_dimension(price_dims, spec, attrs)
        if selected is None:
            result.skipped.append({"dimension_key": spec.dimension_key, "reason": reason, "sku": sku})
            continue
        rate_value = _num((selected.get("pricePerUnit") or {}).get("USD"))
        if rate_value is None:
            result.skipped.append({"dimension_key": spec.dimension_key, "reason": "invalid_rate", "sku": sku})
            continue

        operation = attrs.get("operation")
        result.rates.append(RateRecord(
            service_name=spec.service_name,
            service_code=spec.service_code,
            region=region,
            dimension_key=spec.dimension_key,
            usage_type=str(attrs.get("usagetype", "")),
            unit=spec.expected_unit,
            rate=rate_value,
            currency="USD",
            operation=str(operation) if operation not in (None, "") else None,
            sku=sku,
            price_dimension_id=str(selected.get("_pd_id")),
        ))
        result.mapped.append({
            "dimension_key": spec.dimension_key,
            "sku": sku,
            "price_dimension_id": str(selected.get("_pd_id")),
            "usage_type": str(attrs.get("usagetype", "")),
            "operation": operation or None,
            "unit": spec.expected_unit,
            "official_unit": str(selected.get("unit", "")),
            "rate": str(rate_value),
            "matched_fields": {
                "servicecode": attrs.get("servicecode"),
                "location": attrs.get("location"),
                "usagetype": attrs.get("usagetype"),
                "productFamily": product.get("productFamily"),
            },
            "attributes_used": {k: attrs.get(k) for k in spec.attribute_equals},
            "selected_tier": {
                "beginRange": selected.get("beginRange"),
                "endRange": selected.get("endRange"),
            },
            "reason": "Exact single product match + deterministic first paid OnDemand tier.",
        })
    return result


# --------------------------------------------------------------------------- #
# Snapshot assembly + serialization
# --------------------------------------------------------------------------- #
def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass
class BuildReport:
    region: str
    services_read: list[str]
    rates_emitted: int
    mapped: list[dict]
    skipped: list[dict]
    ambiguous: list[dict]
    source_hash: str
    source_file_hashes: dict[str, str]


def build_snapshot_from_offer_files(
    offer_paths: dict[str, str | Path],
    *,
    region: str,
    snapshot_id: str | None = None,
    upstream_source_url: str | None = None,
    generated_at: str | None = None,
    offer_codes: list[str] | None = None,
) -> tuple[PriceSnapshot, BuildReport]:
    """Build a provenance-stamped ``local_cache`` snapshot from official offer files.

    ``offer_paths`` maps an AWS offer code (e.g. ``AmazonS3``) to a local file path.
    ``source_hash`` is computed over the concatenation of the raw official bytes
    (deterministic service order). Fails closed if no authoritative rate is emitted.
    """
    if not offer_paths:
        raise SnapshotBuildError("No offer files provided.")
    if region not in REGION_LOCATIONS:
        raise SnapshotBuildError(f"Unsupported region '{region}'; no official location mapping is known.")

    rates: list[RateRecord] = []
    mapped: list[dict] = []
    skipped: list[dict] = []
    ambiguous: list[dict] = []
    services_read: list[str] = []
    source_file_hashes: dict[str, str] = {}
    raw_by_service: dict[str, bytes] = {}

    for service_code in sorted(offer_paths):
        if offer_codes and service_code not in offer_codes:
            continue
        offer, raw = parse_official_offer_file(offer_paths[service_code])
        services_read.append(service_code)
        source_file_hashes[service_code] = _sha(raw)
        raw_by_service[service_code] = raw

        result = map_offer_products_to_dimension_keys(offer, region=region, service_code=service_code)
        rates.extend(result.rates)
        for item in result.mapped:
            mapped.append({"service_code": service_code, **item})
        for item in result.skipped:
            target = ambiguous if item.get("reason") == "ambiguous_product" else skipped
            target.append({"service_code": service_code, **item})

    concat = b"".join(raw_by_service[code] for code in sorted(raw_by_service))
    source_hash = _sha(concat)

    if not rates:
        raise SnapshotBuildError(
            "No authoritative rates could be emitted from the provided offer files "
            "(all candidates failed closed)."
        )

    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    snapshot_id = snapshot_id or f"aws-price-list-{region}-{source_hash[7:19]}"
    services = tuple(dict.fromkeys(r.service_name for r in rates))
    provenance = {
        "upstream_source": UPSTREAM_SOURCE,
        "upstream_source_url": upstream_source_url or DEFAULT_UPSTREAM_URL,
        "source_hash": source_hash,
        "schema_version": LOCAL_CACHE_SCHEMA_VERSION,
        "source_file_hashes": source_file_hashes,
        "builder_version": BUILDER_VERSION,
        "mapping_version": MAPPING_VERSION,
        "region": region,
        "services_included": list(services),
    }
    snapshot = _finalize(PriceSnapshot(
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        region=region,
        source="local_cache",
        currency="USD",
        services=services,
        rates=tuple(rates),
        provenance=provenance,
    ))
    report = BuildReport(
        region=region,
        services_read=services_read,
        rates_emitted=len(rates),
        mapped=mapped,
        skipped=skipped,
        ambiguous=ambiguous,
        source_hash=source_hash,
        source_file_hashes=source_file_hashes,
    )
    return snapshot, report


def write_local_cache_snapshot(snapshot: PriceSnapshot, path: str | Path) -> Path:
    """Serialize a snapshot to the compact ``local_cache`` JSON the loader consumes."""
    provenance = snapshot.provenance or {}
    data = {
        "snapshot_id": snapshot.snapshot_id,
        "generated_at": snapshot.generated_at,
        "region": snapshot.region,
        "currency": snapshot.currency,
        "source": "local_cache",
        "upstream_source": provenance.get("upstream_source"),
        "upstream_source_url": provenance.get("upstream_source_url"),
        "source_hash": provenance.get("source_hash"),
        "schema_version": provenance.get("schema_version", LOCAL_CACHE_SCHEMA_VERSION),
        "source_file_hashes": provenance.get("source_file_hashes", {}),
        "builder_version": provenance.get("builder_version", BUILDER_VERSION),
        "mapping_version": provenance.get("mapping_version", MAPPING_VERSION),
        "services_included": list(snapshot.services),
        "rates": [rate.to_dict() for rate in snapshot.rates],
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
