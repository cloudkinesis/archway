"""Tests for supplemental SKU pilot trace export + export-package integration."""

from __future__ import annotations

import csv
import io
import json
from zipfile import ZipFile

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.artifacts import ArtifactStore
from app.services.export_package import ExportPackageService
from app.services.sku_pricing.export_trace import (
    CSV_COLUMNS,
    build_pilot_trace_files,
    pilot_trace_hash,
)
from app.services.synthesis import SynthesisEngine


def _pilot(*, authoritative=True, quantities_confirmed=False, eventbridge=False):
    not_estimated = ["Amazon EventBridge:eventbridge_custom_events (not_found)"] if eventbridge else []
    return {
        "enabled": True, "status": "completed", "workload": "legal_document_rag_poc",
        "snapshot_id": "snap-1", "snapshot_source": "local_cache" if authoritative else "static_fixture",
        "snapshot_authoritative": authoritative, "source_hash": "sha256:abc",
        "upstream_source": "aws_price_list_bulk_api" if authoritative else None,
        "version_hash": "vhash123" if authoritative else None,
        "estimate_input_hash": "eih123", "sku_backed_subtotal": "1.73", "directional_subtotal": "0.00",
        "not_estimated": not_estimated, "rate_authoritative": authoritative,
        "quantities_confirmed": quantities_confirmed,
        "quantity_source": "user_confirmed" if quantities_confirmed else "assumed",
        "quantity_confidence": "confirmed" if quantities_confirmed else "assumed",
        "sku_pilot_estimate_ready": authoritative,
        "sku_pilot_procurement_ready": authoritative and quantities_confirmed,
        "lines": [{
            "service_name": "Amazon S3", "service_code": "AmazonS3", "region": "us-east-1",
            "dimension_key": "s3_standard_storage_gb_month", "usage_type": "TimedStorage-ByteHrs",
            "operation": None, "sku": "WP9", "price_dimension_id": "WP9.dim", "unit": "GB-Mo",
            "rate": "0.023", "quantity": "19.53", "formula": "x", "monthly_subtotal": "0.45",
            "evidence_class": "sku_tier_backed", "rate_authoritative": authoritative,
            "quantities_confirmed": quantities_confirmed, "procurement_ready": authoritative and quantities_confirmed,
            "usage_purpose": "Contract corpus storage", "assumptions": [], "reason": "Exact single SKU/rate match.",
        }],
        "note": "supplemental",
    }


# --- trace content (fast unit tests) ----------------------------------------
def test_trace_json_includes_trace_hash():
    pilot = _pilot()
    files = build_pilot_trace_files(pilot)
    payload = json.loads(files["json"])
    assert payload["supplemental"] is True
    assert payload["trace_hash"] == pilot_trace_hash(pilot)
    assert payload["trace"]["snapshot_id"] == "snap-1"


def test_trace_csv_has_required_columns():
    files = build_pilot_trace_files(_pilot())
    reader = csv.DictReader(io.StringIO(files["csv"]))
    assert reader.fieldnames == CSV_COLUMNS
    rows = list(reader)
    assert rows and rows[0]["dimension_key"] == "s3_standard_storage_gb_month"
    assert rows[0]["source_hash"] == "sha256:abc"
    assert rows[0]["rate_authoritative"] in {"True", "true"}


def test_trace_markdown_states_supplemental_and_assumed_caveats():
    md = build_pilot_trace_files(_pilot(authoritative=True, quantities_confirmed=False))["md"]
    assert "Supplemental SKU-backed pilot trace" in md
    assert "Legacy pricing totals are unchanged" in md
    assert "Does not replace the legacy estimate" in md
    assert "Global procurement-ready: unchanged" in md
    assert "Rates are authoritative, but quantities are assumed. This is not procurement-ready." in md


def test_trace_markdown_non_authoritative_warning():
    md = build_pilot_trace_files(_pilot(authoritative=False))["md"]
    assert "This trace is not authoritative and must not be used as a procurement estimate." in md


def test_trace_markdown_eventbridge_note_when_applicable():
    md = build_pilot_trace_files(_pilot(eventbridge=True))["md"]
    assert "EventBridge not estimated because AWS bills 64KB chunks, not raw events." in md


# --- export-package integration (uses generate(); slower) -------------------
def _make_session(tmp_path, monkeypatch, *, pricing_metadata=None):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a legal contract RAG assistant.")
    session = store.create("Build a legal contract RAG assistant.", brief)
    if pricing_metadata is not None:
        ArtifactStore().write_json(session.id, "pricing", "estimate", {
            "region": "us-east-1", "low_monthly_usd": 100, "expected_monthly_usd": 150,
            "high_monthly_usd": 200, "line_items": [], "main_cost_drivers": [],
            "unknown_variables": [], "metadata": pricing_metadata,
        })
    return session


def test_export_includes_dossier_manifest_and_no_sku_files_when_absent(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    bundle = ExportPackageService().generate(session.id)
    zip_path = ExportPackageService().artifacts.resolve(session.id, bundle.artifact_id)
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("dossier_manifest.json"))
    assert "dossier_manifest.json" in names
    assert "README_DOSSIER.md" in names
    assert not any(n.startswith("pricing/sku_pricing_pilot") for n in names)
    assert manifest["pricing"]["sku_pilot"] is None  # absence recorded clearly


def test_export_includes_sku_trace_files_when_pilot_present(tmp_path, monkeypatch):
    pilot = _pilot(authoritative=True, quantities_confirmed=False)
    session = _make_session(tmp_path, monkeypatch, pricing_metadata={"sku_pricing_pilot": pilot})
    bundle = ExportPackageService().generate(session.id)
    zip_path = ExportPackageService().artifacts.resolve(session.id, bundle.artifact_id)
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("dossier_manifest.json"))
    assert "pricing/sku_pricing_pilot_trace.json" in names
    assert "pricing/sku_pricing_pilot_trace.csv" in names
    assert "pricing/sku_pricing_pilot_summary.md" in names
    sku = manifest["pricing"]["sku_pilot"]
    assert sku and sku["sku_trace_hash"] and sku["source_hash"]
    # Provenance propagated end-to-end (authoritative rate + upstream + version).
    assert sku["upstream_source"] == "aws_price_list_bulk_api"
    assert sku["version_hash"] == "vhash123"
    assert sku["provenance_status"] == "complete"
    # Assumed quantities -> not procurement-ready, and global readiness untouched.
    assert sku["sku_pilot_procurement_ready"] is False
    assert manifest["pricing"]["global"]["procurement_ready"] is False
