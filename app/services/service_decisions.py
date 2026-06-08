from app.domain.capabilities import ArchitectureCapability
from app.domain.service_decision import ServiceDecisionOption, ServiceDecisionRecord
from app.models.domain import EvidenceItem
from app.services.use_case_profile import UseCaseProfile


def build_service_decision_records(profile: UseCaseProfile, evidence: list[EvidenceItem]) -> list[ServiceDecisionRecord]:
    records: list[ServiceDecisionRecord] = []
    evidence_ids = [item.id for item in evidence]
    capabilities = set(profile.capability_model) | set(profile.capabilities)
    if "time_series_storage" in capabilities or "industrial_iot_streaming_ml" in profile.workload_families:
        records.append(
            ServiceDecisionRecord(
                decision_id="ts_storage_001",
                capability=ArchitectureCapability.TIME_SERIES_STORAGE,
                selected_service="AWS IoT SiteWise / time-series storage decision",
                selected_service_rationale=(
                    "Modeled as an explicit decision point because industrial asset modeling, hot operational telemetry, "
                    "high-ingest smart-meter history, training retention, and replay can have different optimal stores."
                ),
                evidence_ids=evidence_ids,
                options_considered=[
                    ServiceDecisionOption(
                        service_name="AWS IoT SiteWise",
                        fit="strong",
                        rationale="Strong fit for industrial asset models, telemetry properties, edge collection, and utility/OT operational context.",
                        risks=["Validate ingest/query limits, pricing dimensions, and fit for high-cardinality smart-meter telemetry."],
                        cost_notes=["Model asset/property counts, ingest rate, hot/warm/cold retention, and query patterns separately."],
                        evidence_ids=evidence_ids,
                    ),
                    ServiceDecisionOption(
                        service_name="Timestream for InfluxDB",
                        fit="medium",
                        rationale="Good fit when InfluxDB-compatible query/API semantics are required.",
                        risks=["Validate current regional availability, operational model, and migration fit."],
                        cost_notes=["Price instance/storage/backup dimensions separately from raw stream ingest."],
                        evidence_ids=evidence_ids,
                    ),
                    ServiceDecisionOption(
                        service_name="Amazon DynamoDB",
                        fit="medium",
                        rationale="Strong for high-scale key-value ingest, alert state, dedupe state, and feature caches.",
                        risks=["Time-series query ergonomics and analytical scans may need lake/analytics companion services."],
                        cost_notes=["Price write/read request units or on-demand operations by measured access pattern."],
                        evidence_ids=evidence_ids,
                    ),
                    ServiceDecisionOption(
                        service_name="Amazon S3 data lake with Iceberg/Athena",
                        fit="strong",
                        rationale="Strong for raw/curated historical telemetry, model training data, retention, and forensic replay.",
                        risks=["Not the hot operational query store by itself."],
                        cost_notes=["Price object storage, lifecycle, catalog, query scans, and compaction jobs."],
                        evidence_ids=evidence_ids,
                    ),
                    ServiceDecisionOption(
                        service_name="Amazon Aurora/RDS PostgreSQL",
                        fit="weak",
                        rationale="Applicable only when SQL transactions/query shape is central and ingest volume is bounded or pre-aggregated.",
                        risks=["Raw high-frequency telemetry can outgrow relational write/query patterns."],
                        cost_notes=["Price provisioned capacity, storage, replicas, and backups if selected."],
                        evidence_ids=evidence_ids,
                    ),
                    ServiceDecisionOption(
                        service_name="Timestream for LiveAnalytics",
                        fit="weak",
                        rationale="Do not select blindly for new workloads without current availability and roadmap validation.",
                        risks=["Availability/service lifecycle warning must be resolved before customer recommendation."],
                        cost_notes=["Refresh with official AWS docs/pricing before use."],
                        evidence_ids=evidence_ids,
                    ),
                ],
                selection_reason="Selected as a decision point rather than a single unvalidated database because industrial telemetry hot queries, asset modeling, training retention, and high-volume ingest have different optimal stores.",
                assumptions=["Final time-series choice depends on confirmed ingest frequency, payload size, query shape, retention, regional availability, and operational model."],
                required_validation=[
                    "Validate current AWS service availability and recommended direction with AWS Docs MCP.",
                    "Validate pricing with AWS Pricing MCP before procurement.",
                    "Benchmark ingest, hot query, historical query, and replay workloads during POC.",
                ],
            )
        )
    return records
