"""Tests for the SKU-backed pricing foundation (additive; live pricing unchanged)."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from app.services.sku_pricing import (
    PriceSnapshot,
    RateRecord,
    UsageDimension,
    bind_rate,
    build_estimate,
    builtin_fixture_snapshot,
    estimate_input_hash,
    load_snapshot,
)
from app.services.sku_pricing.binding import AMBIGUOUS, BOUND, MISSING_QUANTITY, NOT_FOUND, UNIT_MISMATCH
from app.services.sku_pricing.estimate import CATALOG_REFERENCED, NOT_ESTIMATED, SKU_TIER_BACKED

FIXTURE_JSON = Path(__file__).resolve().parent / "fixtures" / "sku_pricing" / "snapshot_us_east_1_fixture.json"


def _dim(service_name, service_code, key, unit, qty, *, required=True, formula=""):
    return UsageDimension(
        service_name=service_name, service_code=service_code, dimension_key=key, unit=unit,
        quantity=Decimal(str(qty)) if qty is not None else None, formula=formula, required_for_headline=required,
    )


def _authoritative(snapshot: PriceSnapshot) -> PriceSnapshot:
    """Same rates, but flagged as an authoritative source (to test the positive path)."""
    return replace(snapshot, source="local_cache")


# --- rate binding from fixture --------------------------------------------- #
def test_s3_storage_rate_binding_from_fixture():
    snap = builtin_fixture_snapshot()
    dim = _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)
    binding = bind_rate(snap, dim)
    assert binding.status == BOUND
    assert binding.rate_record.rate == Decimal("0.023")
    est = build_estimate(snap, [dim])
    line = est.lines[0]
    assert line.evidence_class == SKU_TIER_BACKED
    assert line.monthly_subtotal == Decimal("23.00")  # 1000 * 0.023


def test_lambda_request_and_duration_binding_from_fixture():
    snap = builtin_fixture_snapshot()
    dims = [
        _dim("AWS Lambda", "AWSLambda", "lambda_requests", "Requests", 10_000_000),
        _dim("AWS Lambda", "AWSLambda", "lambda_gb_seconds", "GB-Second", 600_000),
    ]
    est = build_estimate(snap, dims)
    assert all(ln.evidence_class == SKU_TIER_BACKED for ln in est.lines)
    subtotals = {ln.dimension_key: ln.monthly_subtotal for ln in est.lines}
    assert subtotals["lambda_requests"] == Decimal("2.00")        # 10M * 0.0000002
    assert subtotals["lambda_gb_seconds"] == Decimal("10.00")     # 600000 * 0.0000166667 = 10.00002 -> 10.00


def test_sqs_and_eventbridge_binding_from_fixture():
    snap = builtin_fixture_snapshot()
    dims = [
        _dim("Amazon SQS", "AmazonSQS", "sqs_requests", "Requests", 5_000_000),
        _dim("Amazon EventBridge", "AmazonEventBridge", "eventbridge_custom_events", "Events", 3_000_000),
    ]
    est = build_estimate(snap, dims)
    by_key = {ln.dimension_key: ln for ln in est.lines}
    assert by_key["sqs_requests"].evidence_class == SKU_TIER_BACKED
    assert by_key["sqs_requests"].monthly_subtotal == Decimal("2.00")    # 5M * 0.0000004
    assert by_key["eventbridge_custom_events"].monthly_subtotal == Decimal("3.00")  # 3M * 0.000001


def test_dynamodb_on_demand_binding_from_fixture():
    snap = builtin_fixture_snapshot()
    dims = [
        _dim("Amazon DynamoDB", "AmazonDynamoDB", "dynamodb_write_request_units", "WriteRequestUnits", 1_000_000),
        _dim("Amazon DynamoDB", "AmazonDynamoDB", "dynamodb_read_request_units", "ReadRequestUnits", 4_000_000),
        _dim("Amazon DynamoDB", "AmazonDynamoDB", "dynamodb_storage_gb_month", "GB-Mo", 50),
    ]
    est = build_estimate(snap, dims)
    by_key = {ln.dimension_key: ln for ln in est.lines}
    assert by_key["dynamodb_write_request_units"].monthly_subtotal == Decimal("1.25")
    assert by_key["dynamodb_read_request_units"].monthly_subtotal == Decimal("1.00")
    assert by_key["dynamodb_storage_gb_month"].monthly_subtotal == Decimal("12.50")
    assert all(ln.evidence_class == SKU_TIER_BACKED for ln in est.lines)


def test_cloudwatch_logs_binding_from_fixture():
    snap = builtin_fixture_snapshot()
    dims = [
        _dim("Amazon CloudWatch Logs", "AmazonCloudWatch", "cwl_ingestion_gb", "GB", 100),
        _dim("Amazon CloudWatch Logs", "AmazonCloudWatch", "cwl_storage_gb_month", "GB-Mo", 100),
    ]
    est = build_estimate(snap, dims)
    by_key = {ln.dimension_key: ln for ln in est.lines}
    assert by_key["cwl_ingestion_gb"].monthly_subtotal == Decimal("50.00")
    assert by_key["cwl_storage_gb_month"].monthly_subtotal == Decimal("3.00")


# --- fail-closed behavior --------------------------------------------------- #
def test_ambiguous_binding_does_not_become_sku_backed():
    snap = builtin_fixture_snapshot()
    # Add a duplicate rate for the same dimension_key + unit to force ambiguity.
    dup = replace(snap.rates[0], sku="S3-Standard-DUP-FIXTURE")
    snap2 = replace(snap, rates=snap.rates + (dup,))
    dim = _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)
    binding = bind_rate(snap2, dim)
    assert binding.status == AMBIGUOUS
    est = build_estimate(snap2, [dim])
    assert est.lines[0].evidence_class == CATALOG_REFERENCED
    assert est.lines[0].procurement_ready is False
    assert est.sku_backed_subtotal == Decimal("0.00")


def test_missing_rate_fails_closed():
    snap = builtin_fixture_snapshot()
    dim = _dim("Amazon S3", "AmazonS3", "s3_glacier_storage_gb_month", "GB-Mo", 1000)  # not in snapshot
    binding = bind_rate(snap, dim)
    assert binding.status == NOT_FOUND
    est = build_estimate(snap, [dim])
    assert est.lines[0].evidence_class == NOT_ESTIMATED
    assert est.lines[0].monthly_subtotal is None
    assert est.procurement_ready is False
    assert est.headline_safe is False


def test_unit_mismatch_fails_closed():
    snap = builtin_fixture_snapshot()
    dim = _dim("AWS Lambda", "AWSLambda", "lambda_requests", "GB-Mo", 1000)  # wrong unit for requests
    binding = bind_rate(snap, dim)
    assert binding.status == UNIT_MISMATCH
    est = build_estimate(snap, [dim])
    assert est.lines[0].evidence_class == NOT_ESTIMATED


def test_missing_quantity_fails_closed():
    snap = builtin_fixture_snapshot()
    dim = _dim("AWS Lambda", "AWSLambda", "lambda_requests", "Requests", None)  # missing driver
    binding = bind_rate(snap, dim)
    assert binding.status == MISSING_QUANTITY
    est = build_estimate(snap, [dim])
    assert est.lines[0].evidence_class == NOT_ESTIMATED


# --- no fake procurement readiness ----------------------------------------- #
def test_static_fixture_never_procurement_ready_even_when_all_bound():
    snap = builtin_fixture_snapshot()  # source=static_fixture
    dim = _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)
    est = build_estimate(snap, [dim])
    assert est.lines[0].evidence_class == SKU_TIER_BACKED
    assert est.lines[0].procurement_ready is False   # fixture is not authoritative
    assert est.procurement_ready is False
    assert est.headline_safe is False


def test_authoritative_snapshot_all_bound_is_procurement_ready():
    snap = _authoritative(builtin_fixture_snapshot())  # source=local_cache
    dim = _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)
    est = build_estimate(snap, [dim])
    assert est.lines[0].procurement_ready is True
    assert est.procurement_ready is True
    assert est.headline_safe is True


def test_headline_false_when_any_required_line_not_estimated():
    snap = _authoritative(builtin_fixture_snapshot())
    dims = [
        _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000),
        _dim("Amazon S3", "AmazonS3", "s3_glacier_storage_gb_month", "GB-Mo", 1000, required=True),  # not in snapshot
    ]
    est = build_estimate(snap, dims)
    assert est.headline_safe is False
    assert est.procurement_ready is False
    assert any(ln.evidence_class == NOT_ESTIMATED for ln in est.lines)


def test_non_sku_line_cannot_be_procurement_ready():
    snap = _authoritative(builtin_fixture_snapshot())
    dim = _dim("Amazon S3", "AmazonS3", "missing_key", "GB-Mo", 10)
    est = build_estimate(snap, [dim])
    assert est.lines[0].procurement_ready is False


# --- reproducibility -------------------------------------------------------- #
def test_same_inputs_same_snapshot_same_subtotal():
    snap = builtin_fixture_snapshot()
    dims = [_dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1234)]
    e1 = build_estimate(snap, dims, workload_drivers={"storage_gb": 1234})
    e2 = build_estimate(snap, dims, workload_drivers={"storage_gb": 1234})
    assert e1.estimate_input_hash == e2.estimate_input_hash
    assert e1.lines[0].monthly_subtotal == e2.lines[0].monthly_subtotal


def test_changing_snapshot_id_changes_estimate_hash():
    snap = builtin_fixture_snapshot()
    snap_b = replace(snap, snapshot_id="fixture-us-east-1-v2")
    dims = [_dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)]
    h1 = estimate_input_hash(workload_drivers={}, region="us-east-1", snapshot=snap, dimensions=dims)
    h2 = estimate_input_hash(workload_drivers={}, region="us-east-1", snapshot=snap_b, dimensions=dims)
    assert h1 != h2


def test_changing_rate_changes_version_hash_and_subtotal():
    snap = builtin_fixture_snapshot()
    bumped = replace(snap.rates[0], rate=Decimal("0.030"))
    snap_b = builtin_fixture_snapshot()
    snap_b = replace(snap_b, rates=(bumped,) + snap_b.rates[1:])
    from app.services.sku_pricing.snapshot import compute_version_hash
    snap_b = replace(snap_b, version_hash=compute_version_hash(list(snap_b.rates), snap_b.region, snap_b.currency))
    assert snap.version_hash != snap_b.version_hash
    dims = [_dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)]
    e1 = build_estimate(snap, dims)
    e2 = build_estimate(snap_b, dims)
    assert e1.lines[0].monthly_subtotal == Decimal("23.00")
    assert e2.lines[0].monthly_subtotal == Decimal("30.00")


# --- snapshot abstraction (JSON load) -------------------------------------- #
def test_load_snapshot_from_json_fixture_and_bind():
    snap = load_snapshot(FIXTURE_JSON)
    assert snap.snapshot_id == "json-fixture-us-east-1-v1"
    assert snap.source == "static_fixture"
    assert snap.version_hash  # computed on load
    dim = _dim("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", 1000)
    est = build_estimate(snap, [dim])
    assert est.lines[0].monthly_subtotal == Decimal("23.00")
    # Trace is JSON-serializable and labels the snapshot non-authoritative.
    trace = est.to_trace()
    import json
    json.dumps(trace)
    assert trace["snapshot"]["is_authoritative"] is False
