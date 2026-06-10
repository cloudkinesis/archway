"""Tests for the offline official AWS Price List snapshot builder.

Fixtures under ``official_offer_slices/`` are SMALL REAL-SHAPE SLICES trimmed from the
actual us-east-1 AWS Price List offer files (validated 2026-06), so these tests check
the builder against the real offer structure: region-prefixed usagetypes, IA-/Repl-/
Global- decoys, real offer codes (SQS=AWSQueueService, EventBridge=AWSEvents), and the
real Lambda duration unit ``Lambda-GB-Second``.

Proves: source_hash over RAW official bytes; deterministic exact-usagetype mapping;
fail-closed on ambiguity / unit / region / tier; EventBridge intentionally unsupported
(unit-model mismatch); loader + pilot consume builder output; rate authority is separate
from quantity confidence. Offline only — no network, no AWS credentials.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.sku_pricing.cache import load_local_cache_snapshot
from app.services.sku_pricing.official_snapshot_builder import (
    UNSUPPORTED_OFFICIAL_DIMENSIONS,
    SnapshotBuildError,
    build_snapshot_from_offer_files,
    map_offer_products_to_dimension_keys,
    parse_official_offer_file,
    write_local_cache_snapshot,
)
from app.services.sku_pricing.pilot import build_pilot_trace
from app.services.sku_pricing.provenance import is_authoritative_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
SLICES = REPO_ROOT / "tests/fixtures/sku_pricing/official_offer_slices"
SCRIPT = REPO_ROOT / "scripts/build_sku_price_snapshot.py"
REGION = "us-east-1"

# Keys are the real AWS offer codes (== offer file offerCode / product servicecode).
OFFERS = {
    "AmazonS3": SLICES / "AmazonS3.json",
    "AWSLambda": SLICES / "AWSLambda.json",
    "AWSQueueService": SLICES / "AWSQueueService.json",      # SQS
    "AWSEvents": SLICES / "AWSEvents.json",                  # EventBridge (unsupported)
    "AmazonDynamoDB": SLICES / "AmazonDynamoDB.json",
    "AmazonCloudWatch": SLICES / "AmazonCloudWatch.json",
}
LAMBDA_SECOND = SLICES / "AWSLambda_second_unit.json"

FLAG = "ARCHWAY_ENABLE_SKU_PRICING_PILOT"
PATH_ENV = "ARCHWAY_SKU_PRICING_SNAPSHOT_PATH"


@pytest.fixture(autouse=True)
def _clean_settings():
    for key in (FLAG, PATH_ENV):
        os.environ.pop(key, None)
    get_settings.cache_clear()
    yield
    for key in (FLAG, PATH_ENV):
        os.environ.pop(key, None)
    get_settings.cache_clear()


def _offers(*codes):
    return {code: str(OFFERS[code]) for code in codes}


def _rate_for(snapshot, dimension_key):
    matches = [r for r in snapshot.rates if r.dimension_key == dimension_key]
    return matches[0] if matches else None


def _s3_offer():
    offer, _ = parse_official_offer_file(OFFERS["AmazonS3"])
    return offer


def _s3_standard_sku(offer):
    return next(sku for sku, p in offer["products"].items()
               if p["attributes"]["usagetype"] == "TimedStorage-ByteHrs")


# 1 — source hash is over RAW official bytes ----------------------------------
def test_builder_hashes_raw_official_source_bytes():
    snapshot, _ = build_snapshot_from_offer_files(_offers("AmazonS3"), region=REGION)
    raw = Path(OFFERS["AmazonS3"]).read_bytes()
    expected = "sha256:" + hashlib.sha256(raw).hexdigest()
    assert snapshot.provenance["source_file_hashes"]["AmazonS3"] == expected
    assert snapshot.provenance["source_hash"] == expected  # single file


# 2 — emits local_cache with official provenance ------------------------------
def test_builder_emits_local_cache_with_official_provenance():
    snapshot, _ = build_snapshot_from_offer_files(_offers("AmazonS3"), region=REGION)
    assert snapshot.source == "local_cache"
    assert snapshot.provenance["upstream_source"] == "aws_price_list_bulk_api"
    assert snapshot.provenance["upstream_source_url"]
    assert snapshot.generated_at and snapshot.region == REGION
    assert snapshot.services
    assert snapshot.provenance["source_hash"]
    assert is_authoritative_snapshot(snapshot) is True


# 3 — S3 standard storage maps (correct first paid tier, excludes Files- decoy) -
def test_official_s3_storage_maps_to_dimension_key():
    snapshot, report = build_snapshot_from_offer_files(_offers("AmazonS3"), region=REGION)
    rate = _rate_for(snapshot, "s3_standard_storage_gb_month")
    assert rate is not None
    assert rate.rate == Decimal("0.023")  # first 50 TB paid tier
    assert rate.unit == "GB-Mo"
    assert rate.usage_type == "TimedStorage-ByteHrs"  # not USE1-Files-TimedStorage-ByteHrs
    assert rate.sku and rate.price_dimension_id
    selected = next(m for m in report.mapped if m["dimension_key"] == "s3_standard_storage_gb_month")
    assert selected["selected_tier"]["beginRange"] == "0"


# 4 — Lambda requests + duration (real unit Lambda-GB-Second normalizes) -------
def test_official_lambda_request_and_duration_map_to_dimension_keys():
    snapshot, report = build_snapshot_from_offer_files(_offers("AWSLambda"), region=REGION)
    req = _rate_for(snapshot, "lambda_requests")
    dur = _rate_for(snapshot, "lambda_gb_seconds")
    assert req is not None and req.rate == Decimal("0.0000002") and req.unit == "Requests"
    assert req.usage_type == "Request"  # not Global-Request (free tier decoy)
    assert dur is not None and dur.rate == Decimal("0.0000166667") and dur.unit == "GB-Second"
    mapped = next(m for m in report.mapped if m["dimension_key"] == "lambda_gb_seconds")
    assert mapped["official_unit"] == "Lambda-GB-Second"  # real official unit, normalized to GB-Second


# 5 — SQS / DynamoDB / CloudWatch map; EventBridge intentionally unsupported ----
def test_official_sqs_dynamodb_cloudwatch_map_eventbridge_unsupported():
    snapshot, report = build_snapshot_from_offer_files(_offers(*OFFERS.keys()), region=REGION)
    keys = {r.dimension_key for r in snapshot.rates}
    expected_mapped = {
        "s3_standard_storage_gb_month",
        "lambda_requests",
        "lambda_gb_seconds",
        "sqs_requests",
        "dynamodb_read_request_units",
        "dynamodb_write_request_units",
        "dynamodb_storage_gb_month",
        "cwl_ingestion_gb",
        "cwl_storage_gb_month",
    }
    assert keys == expected_mapped
    assert report.rates_emitted == 9
    # EventBridge is explicitly NOT mapped (unit-model mismatch), documented + fail-closed.
    assert "eventbridge_custom_events" not in keys
    assert "eventbridge_custom_events" in UNSUPPORTED_OFFICIAL_DIMENSIONS
    assert any(s.get("reason") == "unsupported_service" and s.get("service_code") == "AWSEvents"
               for s in report.skipped)
    # Real-rate spot checks (us-east-1).
    assert _rate_for(snapshot, "sqs_requests").rate == Decimal("0.0000004")        # Requests-RBP, not FIFO/Fair
    assert _rate_for(snapshot, "dynamodb_read_request_units").rate == Decimal("0.000000125")
    assert _rate_for(snapshot, "dynamodb_write_request_units").rate == Decimal("0.000000625")
    assert _rate_for(snapshot, "dynamodb_storage_gb_month").rate == Decimal("0.25")  # paid tier (0-25 free skipped)
    assert _rate_for(snapshot, "cwl_ingestion_gb").rate == Decimal("0.50")
    assert _rate_for(snapshot, "cwl_storage_gb_month").rate == Decimal("0.03")


# 6 — ambiguous candidates fail closed ----------------------------------------
def test_ambiguous_official_candidates_fail_closed():
    offer = _s3_offer()
    sku = _s3_standard_sku(offer)
    offer["products"]["DUPLICATE"] = copy.deepcopy(offer["products"][sku])
    offer["products"]["DUPLICATE"]["sku"] = "DUPLICATE"
    offer["terms"]["OnDemand"]["DUPLICATE"] = copy.deepcopy(offer["terms"]["OnDemand"][sku])

    result = map_offer_products_to_dimension_keys(offer, region=REGION, service_code="AmazonS3")
    assert not any(r.dimension_key == "s3_standard_storage_gb_month" for r in result.rates)
    skip = next(s for s in result.skipped if s["dimension_key"] == "s3_standard_storage_gb_month")
    assert skip["reason"] == "ambiguous_product"
    assert sorted(skip["candidate_skus"]) == sorted([sku, "DUPLICATE"])


# 7 — free-tier-only / multi-tier without a clear first paid tier fail closed ---
def test_multitier_or_free_tier_without_clear_paid_tier_fails_closed():
    # (a) free-tier-only.
    free = _s3_offer()
    sku = _s3_standard_sku(free)
    for term in free["terms"]["OnDemand"][sku].values():
        for pd in term["priceDimensions"].values():
            pd["pricePerUnit"]["USD"] = "0.0000000000"
    result = map_offer_products_to_dimension_keys(free, region=REGION, service_code="AmazonS3")
    assert not result.rates
    assert next(s for s in result.skipped)["reason"] == "free_tier_only"

    # (b) multi-tier with NO unambiguous beginRange-0 paid tier (S3 std has 3 tiers).
    multi = _s3_offer()
    sku = _s3_standard_sku(multi)
    for term in multi["terms"]["OnDemand"][sku].values():
        for pd in term["priceDimensions"].values():
            pd["beginRange"] = "51200"
    result = map_offer_products_to_dimension_keys(multi, region=REGION, service_code="AmazonS3")
    assert not result.rates
    assert next(s for s in result.skipped)["reason"] == "ambiguous_tier"


# 8 — unit mismatch fails closed ----------------------------------------------
def test_unit_mismatch_fails_closed():
    offer = _s3_offer()
    sku = _s3_standard_sku(offer)
    for term in offer["terms"]["OnDemand"][sku].values():
        for pd in term["priceDimensions"].values():
            pd["unit"] = "Hrs"
    result = map_offer_products_to_dimension_keys(offer, region=REGION, service_code="AmazonS3")
    assert not result.rates
    assert next(s for s in result.skipped)["reason"] == "unit_mismatch"


# 9 — region mismatch fails closed --------------------------------------------
def test_region_mismatch_fails_closed():
    offer = _s3_offer()
    sku = _s3_standard_sku(offer)
    offer["products"][sku]["attributes"]["location"] = "US West (Oregon)"
    result = map_offer_products_to_dimension_keys(offer, region=REGION, service_code="AmazonS3")
    assert not any(r.dimension_key == "s3_standard_storage_gb_month" for r in result.rates)
    assert next(s for s in result.skipped if s["dimension_key"] == "s3_standard_storage_gb_month")["reason"] == "region_mismatch"


# 10 — output consumed by existing local-cache loader -------------------------
def test_snapshot_consumed_by_existing_local_cache_loader(tmp_path):
    snapshot, _ = build_snapshot_from_offer_files(_offers("AmazonS3", "AWSLambda"), region=REGION)
    out = write_local_cache_snapshot(snapshot, tmp_path / "snap.json")
    loaded = load_local_cache_snapshot(out, require_authoritative=True)
    assert loaded.source == "local_cache"
    assert is_authoritative_snapshot(loaded) is True
    assert {r.dimension_key for r in loaded.rates} >= {"s3_standard_storage_gb_month", "lambda_requests"}
    assert loaded.provenance["source_file_hashes"]
    assert loaded.provenance["builder_version"]


# Pilot helper ----------------------------------------------------------------
def _pilot_trace(tmp_path, monkeypatch, drivers, *, confirmed=False, services=("AmazonS3", "AWSLambda")):
    snapshot, _ = build_snapshot_from_offer_files(_offers(*services), region=REGION)
    out = write_local_cache_snapshot(snapshot, tmp_path / "snap.json")
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setenv(PATH_ENV, str(out))
    get_settings.cache_clear()
    profile = {
        "domain": "legal",
        "workload_families": ["rag_assistant", "document_intelligence"],
        "capabilities": ["document_retrieval"],
        "sku_pricing_pilot_drivers": drivers,
    }
    if confirmed:
        profile["sku_pricing_pilot_quantities_confirmed"] = True
    return build_pilot_trace(profile)


# 11 — output consumed by existing source-truth pilot -------------------------
def test_snapshot_consumed_by_existing_sku_pilot(tmp_path, monkeypatch):
    drivers = {"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000}
    trace = _pilot_trace(tmp_path, monkeypatch, drivers)
    assert trace is not None
    assert trace["status"] in {"completed", "partial"}
    assert trace["snapshot_source"] == "local_cache"
    assert trace["rate_authoritative"] is True
    sku_lines = [ln for ln in trace["lines"] if ln["evidence_class"] == "sku_tier_backed"]
    assert any(ln["dimension_key"] == "s3_standard_storage_gb_month" for ln in sku_lines)
    assert all(ln["rate_authoritative"] for ln in sku_lines)


# 12 — assumed quantities do NOT make procurement-ready -----------------------
def test_assumed_quantities_do_not_make_procurement_ready(tmp_path, monkeypatch):
    drivers = {"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000}
    trace = _pilot_trace(tmp_path, monkeypatch, drivers, confirmed=False)
    assert trace["status"] == "completed"
    assert trace["rate_authoritative"] is True
    assert trace["quantities_confirmed"] is False
    assert trace["quantity_source"] == "assumed"
    assert trace["sku_pilot_estimate_ready"] is True
    assert trace["sku_pilot_procurement_ready"] is False


# 13 — confirmed quantities required for procurement-ready ---------------------
def test_confirmed_quantities_required_for_procurement_ready(tmp_path, monkeypatch):
    drivers = {"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000}
    trace = _pilot_trace(tmp_path, monkeypatch, drivers, confirmed=True)
    assert trace["status"] == "completed"
    assert trace["rate_authoritative"] is True
    assert trace["quantities_confirmed"] is True
    assert trace["quantity_source"] == "user_confirmed"
    assert trace["sku_pilot_estimate_ready"] is True
    assert trace["sku_pilot_procurement_ready"] is True


# 14 — CLI builds from local files only, no network / credentials -------------
def test_cli_builds_snapshot_from_local_files_only(tmp_path):
    out = tmp_path / "aws-price-list.json"
    env = {
        **os.environ,
        "AWS_PROFILE": "",
        "AWS_ACCESS_KEY_ID": "",
        "AWS_SECRET_ACCESS_KEY": "",
        "AWS_SESSION_TOKEN": "",
    }
    proc = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--region", REGION,
            "--output", str(out),
            "--offer", f"AmazonS3={OFFERS['AmazonS3']}",
            "--offer", f"AWSLambda={OFFERS['AWSLambda']}",
        ],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["source"] == "local_cache"
    assert data["upstream_source"] == "aws_price_list_bulk_api"
    assert data["rates"]
    assert "rates emitted" in proc.stdout


# 15 — Lambda duration in synthetic official unit "Second" normalizes to GB-Second
def test_official_lambda_duration_second_unit_normalizes_to_gb_second():
    offer, _ = parse_official_offer_file(LAMBDA_SECOND)
    dur_unit = (
        offer["terms"]["OnDemand"]["TG3M4CAGBA3NYQBH"]["TG3M4CAGBA3NYQBH.JRTCKXETXF"]
        ["priceDimensions"]["TG3M4CAGBA3NYQBH.JRTCKXETXF.CUKFZ388N3"]["unit"]
    )
    assert dur_unit == "Second"

    snapshot, report = build_snapshot_from_offer_files({"AWSLambda": str(LAMBDA_SECOND)}, region=REGION)
    dur = _rate_for(snapshot, "lambda_gb_seconds")
    assert dur is not None and dur.rate == Decimal("0.0000166667")
    assert dur.unit == "GB-Second"  # normalized output
    mapped = next(m for m in report.mapped if m["dimension_key"] == "lambda_gb_seconds")
    assert mapped["official_unit"] == "Second"
    req = _rate_for(snapshot, "lambda_requests")
    assert req is not None and req.unit == "Requests" and req.rate == Decimal("0.0000002")


# 16 — an unrelated "Second" unit does NOT map (fail closed via proof gate) -----
def test_unrelated_second_unit_does_not_map_to_lambda_gb_seconds():
    offer, _ = parse_official_offer_file(LAMBDA_SECOND)
    unrelated = copy.deepcopy(offer)
    unrelated["products"]["TG3M4CAGBA3NYQBH"]["attributes"]["usagetype"] = "Lambda-Duration"  # no GB-Second proof
    pd = (
        unrelated["terms"]["OnDemand"]["TG3M4CAGBA3NYQBH"]["TG3M4CAGBA3NYQBH.JRTCKXETXF"]
        ["priceDimensions"]["TG3M4CAGBA3NYQBH.JRTCKXETXF.CUKFZ388N3"]
    )
    pd["description"] = "$0.0000166667 per second of compute"
    result = map_offer_products_to_dimension_keys(unrelated, region=REGION, service_code="AWSLambda")
    # Product no longer matches the exact 'Lambda-GB-Second' usagetype -> not_found (fail closed).
    assert not any(r.dimension_key == "lambda_gb_seconds" for r in result.rates)
    assert any(r.dimension_key == "lambda_requests" for r in result.rates)


# 16b — plural official unit "Seconds" also normalizes (proof from usagetype) -----
def test_official_lambda_duration_plural_seconds_unit():
    offer, _ = parse_official_offer_file(LAMBDA_SECOND)
    plural = copy.deepcopy(offer)
    pd = plural["terms"]["OnDemand"]["TG3M4CAGBA3NYQBH"]["TG3M4CAGBA3NYQBH.JRTCKXETXF"]["priceDimensions"]
    pd["TG3M4CAGBA3NYQBH.JRTCKXETXF.CUKFZ388N3"]["unit"] = "Seconds"
    result = map_offer_products_to_dimension_keys(plural, region=REGION, service_code="AWSLambda")
    dur = next((r for r in result.rates if r.dimension_key == "lambda_gb_seconds"), None)
    assert dur is not None and dur.unit == "GB-Second" and dur.rate == Decimal("0.0000166667")


# 17 — source hash + emitted rates are independent of input dict ordering -------
def test_source_hash_deterministic_regardless_of_input_order():
    order_a = {"AmazonS3": str(OFFERS["AmazonS3"]), "AWSLambda": str(OFFERS["AWSLambda"])}
    order_b = {"AWSLambda": str(OFFERS["AWSLambda"]), "AmazonS3": str(OFFERS["AmazonS3"])}
    snap_a, _ = build_snapshot_from_offer_files(order_a, region=REGION, generated_at="2026-06-01T00:00:00+00:00")
    snap_b, _ = build_snapshot_from_offer_files(order_b, region=REGION, generated_at="2026-06-01T00:00:00+00:00")
    assert snap_a.provenance["source_hash"] == snap_b.provenance["source_hash"]
    assert snap_a.provenance["source_file_hashes"] == snap_b.provenance["source_file_hashes"]
    assert snap_a.version_hash == snap_b.version_hash
    rates_a = sorted((r.dimension_key, str(r.rate), r.sku, r.unit) for r in snap_a.rates)
    rates_b = sorted((r.dimension_key, str(r.rate), r.sku, r.unit) for r in snap_b.rates)
    assert rates_a == rates_b


# 18 — empty / all-skipped input fails closed with a clear error --------------
def test_no_valid_rates_raises():
    offer = _s3_offer()
    offer["products"] = {}
    offer["terms"] = {"OnDemand": {}}
    out_path = SLICES.parent / "_tmp_empty_offer.json"
    try:
        out_path.write_text(json.dumps(offer), encoding="utf-8")
        with pytest.raises(SnapshotBuildError):
            build_snapshot_from_offer_files({"AmazonS3": str(out_path)}, region=REGION)
    finally:
        out_path.unlink(missing_ok=True)
