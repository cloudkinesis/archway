"""Tests for the SKU-pricing local-cache adapter.

DEPENDS ON: feature/sku-backed-pricing-foundation. This branch
(feature/sku-pricing-local-cache-adapter) is stacked on commit 9b168d7 and adds
local-cache/provenance/parser functionality on top of the foundation. The module
remains standalone and is NOT wired into live pricing.
"""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.sku_pricing import (
    bind_rate,
    build_local_cache_estimate,
    build_local_cache_snapshot_from_reduced_price_list,
    builtin_fixture_snapshot,
    is_authoritative_snapshot,
    load_local_cache_snapshot,
    parse_reduced_price_list,
    provenance_report,
)
from app.services.sku_pricing.binding import AMBIGUOUS, BOUND, UsageDimension
from app.services.sku_pricing.cache import ProvenanceError
from app.services.sku_pricing.estimate import CATALOG_REFERENCED, NOT_ESTIMATED, SKU_TIER_BACKED, build_estimate
from app.services.sku_pricing.snapshot import compute_version_hash

FIX = Path(__file__).resolve().parent / "fixtures" / "sku_pricing"
LOCAL_CACHE = FIX / "local_cache_snapshot_us_east_1.json"
REDUCED_PL = FIX / "aws_price_list_reduced_us_east_1.json"


def _dim(service_name, service_code, key, unit, qty, *, required=True):
    return UsageDimension(
        service_name=service_name, service_code=service_code, dimension_key=key, unit=unit,
        quantity=Decimal(str(qty)) if qty is not None else None, formula="", required_for_headline=required,
    )


# 1
def test_load_local_cache_snapshot_with_provenance():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    assert snap.source == "local_cache"
    assert snap.snapshot_id == "aws-price-list-us-east-1-2026-06-08-example"
    assert snap.region == "us-east-1"
    assert snap.provenance["upstream_source"] == "aws_price_list_api"
    assert snap.provenance["source_hash"]
    assert snap.version_hash
    assert is_authoritative_snapshot(snap) is True


# 2
def test_static_fixture_is_not_authoritative():
    snap = builtin_fixture_snapshot()
    assert is_authoritative_snapshot(snap) is False
    est = build_local_cache_estimate(snap, [_dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)])
    assert est.lines[0].evidence_class == SKU_TIER_BACKED  # binds exactly
    assert est.lines[0].procurement_ready is False         # but fixture is not authoritative
    assert est.procurement_ready is False


# 3
def test_missing_provenance_fails_authority():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    no_hash = replace(snap, provenance={**snap.provenance, "source_hash": None})
    no_upstream = replace(snap, provenance={**snap.provenance, "upstream_source": None})
    assert is_authoritative_snapshot(no_hash) is False
    assert is_authoritative_snapshot(no_upstream) is False
    assert any("source_hash" in r for r in provenance_report(no_hash).reasons)
    # Loader fails closed when require_authoritative.
    bad = json.loads(LOCAL_CACHE.read_text())
    bad.pop("source_hash")
    p = FIX / "_tmp_bad_cache.json"
    p.write_text(json.dumps(bad))
    try:
        with pytest.raises(ProvenanceError):
            load_local_cache_snapshot(p, require_authoritative=True)
    finally:
        p.unlink(missing_ok=True)


# 4
def test_parse_reduced_aws_price_list_fixture():
    data = json.loads(REDUCED_PL.read_text())
    records = parse_reduced_price_list(data)
    assert len(records) == 10
    by_key = {r.dimension_key: r for r in records}
    assert by_key["s3_standard_storage_gb_month"].rate == Decimal("0.023")
    assert by_key["lambda_requests"].unit == "Requests"
    assert by_key["dynamodb_write_request_units"].sku == "DDB-WRU-USE1"
    # Unsupported services are skipped (reduced parser, not full coverage).
    extra = {"region": "us-east-1", "products": [{"service_name": "X", "service_code": "AmazonEC2", "region": "us-east-1", "usage_type": "BoxUsage", "unit": "Hrs", "usd_rate": "0.1", "dimension_key": "ec2_hours"}]}
    assert parse_reduced_price_list(extra) == []


# 5
def test_local_cache_binding_can_make_line_procurement_ready():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    dim = _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)
    assert bind_rate(snap, dim).status == BOUND
    est = build_local_cache_estimate(snap, [dim])
    assert est.lines[0].evidence_class == SKU_TIER_BACKED
    assert est.lines[0].procurement_ready is True
    assert est.lines[0].monthly_subtotal == Decimal("23.00")


# 6
def test_all_required_lines_bound_can_make_estimate_procurement_ready():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    dims = [
        _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000),
        _dim("AWS Lambda", "AWSLambda", "lambda_requests", "Requests", 10_000_000),
        _dim("Amazon DynamoDB", "AmazonDynamoDB", "dynamodb_write_request_units", "WriteRequestUnits", 1_000_000),
    ]
    est = build_local_cache_estimate(snap, dims)
    assert all(ln.evidence_class == SKU_TIER_BACKED for ln in est.lines)
    assert est.procurement_ready is True
    assert est.headline_safe is True
    assert est.sku_backed_subtotal == Decimal("26.25")  # 23.00 + 2.00 + 1.25


# 7
def test_partial_binding_keeps_estimate_directional():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    dims = [
        _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000),
        _dim("Amazon S3", "AmazonS3", "s3_glacier_storage_gb_month", "GB-Mo", 500),  # not in snapshot
    ]
    est = build_local_cache_estimate(snap, dims)
    assert est.procurement_ready is False
    assert est.headline_safe is False
    not_estimated = [ln for ln in est.lines if ln.evidence_class == NOT_ESTIMATED]
    assert not_estimated and not_estimated[0].reason


# 8
def test_ambiguous_binding_fails_closed():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    dup = replace(snap.rates[0], sku="S3STD-DUP")
    snap2 = replace(snap, rates=snap.rates + (dup,))
    dim = _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)
    assert bind_rate(snap2, dim).status == AMBIGUOUS
    est = build_local_cache_estimate(snap2, [dim])
    assert est.lines[0].evidence_class == CATALOG_REFERENCED
    assert est.lines[0].procurement_ready is False
    assert est.procurement_ready is False


# 9
def test_reproducible_hash_same_inputs_same_snapshot():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    dims = [_dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1234)]
    e1 = build_local_cache_estimate(snap, dims, workload_drivers={"storage_gb": 1234})
    e2 = build_local_cache_estimate(snap, dims, workload_drivers={"storage_gb": 1234})
    assert e1.estimate_input_hash == e2.estimate_input_hash
    assert e1.lines[0].monthly_subtotal == e2.lines[0].monthly_subtotal


# 10
def test_rate_change_changes_hash_and_subtotal():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    bumped = replace(snap.rates[0], rate=Decimal("0.030"))
    snap_b = replace(snap, rates=(bumped,) + snap.rates[1:])
    snap_b = replace(snap_b, version_hash=compute_version_hash(list(snap_b.rates), snap_b.region, snap_b.currency))
    assert snap.version_hash != snap_b.version_hash
    dim = _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)
    assert build_local_cache_estimate(snap, [dim]).lines[0].monthly_subtotal == Decimal("23.00")
    assert build_local_cache_estimate(snap_b, [dim]).lines[0].monthly_subtotal == Decimal("30.00")


# 11
def test_trace_contains_snapshot_provenance():
    snap = load_local_cache_snapshot(LOCAL_CACHE)
    est = build_local_cache_estimate(snap, [_dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)])
    trace = est.to_trace()
    json.dumps(trace)  # serializable
    sn = trace["snapshot"]
    assert sn["snapshot_id"] == snap.snapshot_id
    assert sn["source"] == "local_cache"
    assert sn["upstream_source"] == "aws_price_list_api"
    assert sn["source_hash"]
    assert sn["generated_at"]


# Builder: reduced price list -> authoritative local cache snapshot
def test_build_local_cache_snapshot_from_reduced_price_list_is_authoritative():
    data = json.loads(REDUCED_PL.read_text())
    snap = build_local_cache_snapshot_from_reduced_price_list(
        data, snapshot_id="built-from-reduced-pl", generated_at="2026-06-08T00:00:00Z"
    )
    assert snap.source == "local_cache"
    assert snap.provenance["source_hash"].startswith("sha256:")
    assert is_authoritative_snapshot(snap) is True
    est = build_local_cache_estimate(snap, [_dim("AWS Lambda", "AWSLambda", "lambda_gb_seconds", "GB-Second", 600_000)])
    assert est.lines[0].procurement_ready is True
