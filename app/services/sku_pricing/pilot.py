"""Pilot integration glue between the SKU pricing module and Archway pricing.

Supplemental, additive, flag-gated. When ``ARCHWAY_ENABLE_SKU_PRICING_PILOT`` is
true AND the workload is legal/document RAG AND an authoritative local-cache
snapshot is configured, this attaches a ``sku_pricing_pilot`` metadata trace to
the PricingAnalysis. It NEVER changes low/expected/high totals or the global
``pricing_can_be_displayed_as_headline`` / ``procurement_ready`` fields, and it
never raises into the pricing path.

Scope: legal/document RAG POC only. Standalone SKU module is reused; nothing else
in the product is changed.

DEPENDS ON: feature/sku-backed-pricing-foundation @ 9b168d7,
            feature/sku-pricing-local-cache-adapter @ efe0849.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.config import get_settings

DOCUMENT_RAG_FAMILIES = {"document_intelligence", "rag_assistant"}
DOCUMENT_RAG_CAPABILITIES = {"document_retrieval", "rag_retrieval", "document_ingestion"}

# Per-dimension human-readable architecture role / usage purpose.
PURPOSE_BY_KEY = {
    "s3_standard_storage_gb_month": "Contract corpus storage",
    "lambda_requests": "RAG query compute invocations",
    "lambda_gb_seconds": "RAG query compute duration (assumed)",
    "eventbridge_custom_events": "Document ingestion events",
    "sqs_requests": "Ingestion workflow queue",
    "dynamodb_write_request_units": "Obligation approval metadata writes",
    "dynamodb_read_request_units": "RAG metadata reads",
    "cwl_ingestion_gb": "Application/audit log ingestion",
    "s3_glacier_storage_gb_month": "Long-term contract archive (unsupported in pilot snapshot)",
}


def _num(value: Any) -> Decimal | None:
    if value in (None, "", False):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def is_document_rag_workload(use_case_profile: dict | None) -> bool:
    profile = use_case_profile or {}
    families = set(profile.get("workload_families") or [])
    caps = set(profile.get("capabilities") or []) | set(profile.get("capability_model") or [])
    return bool(families & DOCUMENT_RAG_FAMILIES or caps & DOCUMENT_RAG_CAPABILITIES)


def document_rag_dimensions(pilot_drivers: dict):
    """Map explicit legal/document RAG pilot drivers to simple billable dimensions.

    Reads named drivers from ``use_case_profile['sku_pricing_pilot_drivers']``.
    Missing CORE drivers yield a not_estimated line (keeps pilot not-ready);
    optional drivers only create a line when present. Assumptions are explicit.
    """
    from app.services.sku_pricing.binding import UsageDimension

    drivers = pilot_drivers or {}
    dims: list[UsageDimension] = []

    # --- Core: S3 contract storage ---
    contracts = _num(drivers.get("historical_contract_count"))
    mb = _num(drivers.get("average_mb_per_contract"))
    if contracts and mb:
        gb = (contracts * mb / Decimal(1024)).quantize(Decimal("0.01"))
        dims.append(UsageDimension("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", gb,
                                   formula="historical_contract_count * average_mb_per_contract / 1024", required_for_headline=True))
    else:
        dims.append(UsageDimension("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "GB-Mo", None,
                                   formula="requires historical_contract_count + average_mb_per_contract", required_for_headline=True))

    # --- Core: RAG query Lambda requests + (assumed) duration ---
    rag = _num(drivers.get("rag_queries_per_day"))
    if rag:
        monthly_queries = rag * Decimal(30)
        dims.append(UsageDimension("AWS Lambda", "AWSLambda", "lambda_requests", "Requests", monthly_queries,
                                   formula="rag_queries_per_day * 30", required_for_headline=True))
        dims.append(UsageDimension("AWS Lambda", "AWSLambda", "lambda_gb_seconds", "GB-Second", monthly_queries * Decimal("0.5"),
                                   formula="rag_queries_per_day * 30 * 0.5s @1GB (assumed)",
                                   assumptions=("Assumed 0.5s average RAG-query Lambda duration at 1 GB until measured.",),
                                   required_for_headline=True))
    else:
        dims.append(UsageDimension("AWS Lambda", "AWSLambda", "lambda_requests", "Requests", None,
                                   formula="requires rag_queries_per_day", required_for_headline=True))

    # --- Optional: document ingestion events / queue ---
    new_contracts = _num(drivers.get("new_or_updated_contracts_per_month"))
    if new_contracts:
        dims.append(UsageDimension("Amazon EventBridge", "AmazonEventBridge", "eventbridge_custom_events", "Events", new_contracts,
                                   formula="new_or_updated_contracts_per_month", required_for_headline=False))
        if drivers.get("workflow_queue"):
            dims.append(UsageDimension("Amazon SQS", "AmazonSQS", "sqs_requests", "Requests", new_contracts,
                                       formula="new_or_updated_contracts_per_month (ingestion queue)", required_for_headline=False))

    # --- Optional: obligation approval metadata writes ---
    approvals = _num(drivers.get("obligation_review_approvals_per_month"))
    if approvals:
        dims.append(UsageDimension("Amazon DynamoDB", "AmazonDynamoDB", "dynamodb_write_request_units", "WriteRequestUnits", approvals,
                                   formula="obligation_review_approvals_per_month", required_for_headline=False))

    # --- Optional: CloudWatch Logs ingestion ---
    logs_gb = _num(drivers.get("logs_gb_per_month"))
    if logs_gb:
        dims.append(UsageDimension("Amazon CloudWatch Logs", "AmazonCloudWatch", "cwl_ingestion_gb", "GB", logs_gb,
                                   formula="logs_gb_per_month", required_for_headline=False))

    # --- Optional unsupported dimension (demonstrates fail-closed when present) ---
    glacier = _num(drivers.get("glacier_archive_gb"))
    if glacier:
        dims.append(UsageDimension("Amazon S3", "AmazonS3", "s3_glacier_storage_gb_month", "GB-Mo", glacier,
                                   formula="glacier_archive_gb", required_for_headline=True))

    return dims


def _skip(reason: str, **extra) -> dict:
    return {"enabled": True, "status": "skipped", "reason": reason, **extra}


def build_pilot_trace(use_case_profile: dict | None) -> dict | None:
    """Build the supplemental pilot trace dict, or None when the pilot does not apply.

    Pure-ish: reads config (flag + snapshot path) and the SKU module. Never raises.
    """
    settings = get_settings()
    if not settings.enable_sku_pricing_pilot:
        return None
    if not is_document_rag_workload(use_case_profile):
        return None  # pilot scoped to legal/document RAG only

    try:
        from app.services.sku_pricing.cache import (
            LocalCacheError,
            build_local_cache_estimate,
            load_local_cache_snapshot,
        )
        from app.services.sku_pricing.provenance import is_authoritative_snapshot

        path = settings.sku_pricing_snapshot_path
        if not path:
            return _skip("sku pricing snapshot path not configured")

        try:
            snapshot = load_local_cache_snapshot(path, require_authoritative=False)
        except LocalCacheError as exc:
            return {"enabled": True, "status": "failed_closed", "reason": f"could not load local-cache snapshot: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"enabled": True, "status": "failed_closed", "reason": f"snapshot load error: {type(exc).__name__}"}

        if not is_authoritative_snapshot(snapshot):
            return _skip("snapshot not authoritative", snapshot_id=snapshot.snapshot_id,
                         snapshot_source=snapshot.source, snapshot_authoritative=False)

        profile = use_case_profile or {}
        pilot_drivers = profile.get("sku_pricing_pilot_drivers") or {}
        dims = document_rag_dimensions(pilot_drivers)
        estimate = build_local_cache_estimate(snapshot, dims, workload_drivers=pilot_drivers)
        trace = estimate.to_trace()

        # Rate authority vs quantity confidence are SEPARATE axes (DECISIONS D10).
        # Reaching here means the snapshot is provenance-authoritative -> rates are
        # authoritative. Quantities are only "confirmed" when explicitly attested;
        # assumed/default/inferred drivers must NOT unlock procurement readiness.
        rate_authoritative = True
        quantities_confirmed = bool(profile.get("sku_pricing_pilot_quantities_confirmed"))
        quantity_source = profile.get("sku_pricing_pilot_quantity_source") or (
            "user_confirmed" if quantities_confirmed else "assumed"
        )
        quantity_confidence = "confirmed" if quantities_confirmed else "assumed"
        # estimate.procurement_ready == rates authoritative AND every required line binds
        # with a present quantity. That is "estimate ready", NOT procurement ready.
        estimate_ready = bool(estimate.procurement_ready)
        pilot_procurement_ready = bool(estimate_ready and quantities_confirmed)

        lines = []
        for line in trace["lines"]:
            line = {
                **line,
                "usage_purpose": PURPOSE_BY_KEY.get(line["dimension_key"], ""),
                "rate_authoritative": bool(line.get("procurement_ready")),
                "quantities_confirmed": quantities_confirmed,
            }
            lines.append(line)

        status = "completed" if not estimate.not_estimated else "partial"
        return {
            "enabled": True,
            "status": status,
            "workload": "legal_document_rag_poc",
            "snapshot_id": estimate.snapshot_id,
            "snapshot_source": estimate.snapshot_source,
            "snapshot_authoritative": True,
            "source_hash": (estimate.snapshot_provenance or {}).get("source_hash"),
            "estimate_input_hash": estimate.estimate_input_hash,
            "sku_backed_subtotal": str(estimate.sku_backed_subtotal),
            "directional_subtotal": str(estimate.directional_subtotal),
            "not_estimated": list(estimate.not_estimated),
            # Split readiness axes (pilot-only; deliberately NOT global readiness).
            "rate_authoritative": rate_authoritative,
            "quantities_confirmed": quantities_confirmed,
            "quantity_source": quantity_source,
            "quantity_confidence": quantity_confidence,
            "sku_pilot_estimate_ready": estimate_ready,
            # Procurement-ready ONLY when rates are authoritative AND quantities confirmed.
            "sku_pilot_procurement_ready": pilot_procurement_ready,
            "lines": lines,
            "note": (
                "Supplemental SKU-backed pilot trace. Rate authority and quantity confidence are "
                "separate: assumed quantities never reach procurement readiness. Does not change "
                "PricingAnalysis totals or global headline/procurement readiness."
            ),
        }
    except Exception as exc:  # noqa: BLE001 - pilot must never break pricing
        return {"enabled": True, "status": "failed", "reason": f"sku pilot error: {type(exc).__name__}"}


def attach_sku_pricing_pilot(analysis, brief) -> None:
    """Attach the pilot trace to PricingAnalysis.metadata additively. Never raises.

    Touches ONLY ``metadata['sku_pricing_pilot']`` — never totals or global readiness.
    """
    try:
        use_case_profile = getattr(brief, "use_case_profile", None)
        trace = build_pilot_trace(use_case_profile)
        if trace is None:
            return
        analysis.metadata = {**(analysis.metadata or {}), "sku_pricing_pilot": trace}
    except Exception:  # noqa: BLE001
        return
