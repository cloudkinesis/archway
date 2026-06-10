from dataclasses import dataclass, field

from app.models.domain import (
    ArchitectureComponent,
    ArchitectureFlow,
    AWSServiceRecommendation,
    ObservabilityControl,
    SecurityControl,
)
from app.services.lane_planner import (
    apply_domain_lane_model,
    lane_label_for_component,
    plan_lanes,
    resolve_domain_lane_model,
)
from app.services.use_case_profile import UseCaseProfile
from app.services.view_planner import compiler_views_for_semantic, plan_semantic_views


@dataclass(frozen=True)
class ServicePattern:
    service: str
    purpose: str
    alternatives: tuple[str, ...] = ()
    component_id: str | None = None
    component_name: str | None = None
    service_key: str | None = None
    scope: str | None = None
    logical_group: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WorkloadPattern:
    id: str
    label: str
    services: tuple[ServicePattern, ...]
    flows: tuple[tuple[str, str, str, str | None, str], ...]
    pricing_dimensions: tuple[str, ...]
    poc_scope: str
    production_scope: str
    expected_views: tuple[str, ...]


COMMON_SECURITY = (
    SecurityControl(name="KMS encryption", rationale="Protects application data, telemetry, logs, and generated artifacts."),
    SecurityControl(name="Least-privilege IAM", rationale="Limits blast radius across ingestion, processing, model, workflow, and data services."),
    SecurityControl(name="Audit trail", rationale="Supports investigation, compliance review, and evidence discipline."),
)

COMMON_OBSERVABILITY = (
    ObservabilityControl(name="CloudWatch metrics and logs", rationale="Tracks workload health, latency, throughput, errors, and cost drivers."),
    ObservabilityControl(name="CloudTrail audit events", rationale="Records control-plane activity and supports audit review."),
)


PATTERNS: dict[str, WorkloadPattern] = {
    "healthcare_operations_scheduling": WorkloadPattern(
        id="healthcare_operations_scheduling",
        label="Healthcare operations scheduling",
        services=(
            ServicePattern("External Epic / EHR system", "Authoritative patient and surgery schedule context", ("Cerner", "Meditech", "FHIR gateway"), "ehr", "Epic / EHR System", "external_actor", "external_actor", "Sources and edge"),
            ServicePattern("External OR command center", "Existing OR command center dashboard and operational review point", ("Hospital operations dashboard",), "command_center", "Existing OR Command Center Dashboard", "external_actor", "external_actor", "Sources and edge"),
            ServicePattern("External staffing system", "Nurse, anesthesia, and surgical team availability source", ("Workday", "UKG", "hospital staffing platform"), "staffing", "Staffing System", "external_actor", "external_actor", "Sources and edge"),
            ServicePattern("External sterile processing system", "Instrument tray and sterile processing readiness source", ("Instrument tracking system", "sterile processing inventory"), "sterile_processing", "Sterile Processing / Instrument Tray System", "external_actor", "external_actor", "Sources and edge"),
            ServicePattern("Occupancy metadata processor", "Extracts room occupancy metadata without retaining patient-identifiable video", ("Edge appliance", "AWS Lambda image metadata adapter"), "occupancy_metadata", "Occupancy Metadata Processor", "lambda", "regional_compute", "Sources and edge", metadata={"role": "video_metadata_processor", "privacy_boundary": "metadata_only_no_patient_video_storage"}),
            ServicePattern("AWS Direct Connect / Site-to-Site VPN", "Private connectivity candidate for hospital and EHR integrations", ("AWS PrivateLink", "Transit Gateway VPN"), "private_connectivity", "Private Hospital Connectivity", "direct_connect", "regional_entry", "Workflow and integrations", metadata={"role": "private_connectivity"}),
            ServicePattern("Amazon EventBridge", "Clinical operations event routing for OR schedule, readiness, turnover, and prediction events", ("Amazon SQS", "Amazon MSK"), "events", "OR Schedule Event Router", "eventbridge", "regional_integration", "Workflow and integrations"),
            ServicePattern("Amazon SQS", "Durable approval and integration buffer for schedule recommendations", ("EventBridge Pipes", "Amazon MQ"), "queue", "Clinical Workflow Queue", "sqs", "regional_integration", "Workflow and integrations"),
            ServicePattern("AWS Lambda", "FHIR/HL7 adapters, policy checks, and event normalization", ("Amazon ECS", "AWS Step Functions tasks"), "adapter", "Clinical Integration Adapter", "lambda", "regional_compute", "Workflow and integrations", metadata={"role": "integration_adapter"}),
            ServicePattern("Amazon Cognito", "Authenticated access for OR command center users and API clients", ("IAM Identity Center", "Customer IdP via SAML/OIDC"), "auth", "Clinical API Identity", "cognito", "regional_identity", "Security", metadata={"role": "auth_control"}),
            ServicePattern("Amazon DynamoDB", "PHI-safe operational state, idempotency keys, and current OR status", ("Amazon Aurora PostgreSQL", "Amazon MemoryDB"), "state", "PHI-safe Operational Store", "dynamodb", "regional_managed_data", "Data and model lifecycle", metadata={"role": "phi_safe_operational_store"}),
            ServicePattern("Amazon DynamoDB", "Proposed schedule changes awaiting policy evaluation and approval", ("Amazon Aurora PostgreSQL",), "proposed_changes", "Proposed Schedule Change Store", "dynamodb", "regional_managed_data", "Data and model lifecycle", metadata={"role": "proposed_action_store"}),
            ServicePattern("Amazon SageMaker", "Surgery delay prediction service using approved clinical operations features", ("Amazon Bedrock", "ECS-hosted model service"), "ml", "Surgery Delay Prediction Service", "sagemaker", "regional_managed_ai", "Prediction and scoring", metadata={"role": "model_endpoint"}),
            ServicePattern("AWS Lambda", "Evaluates site policy, PHI boundaries, patient impact, and allowed action mode before approval", ("AWS Step Functions Choice states", "Amazon Verified Permissions"), "policy_evaluator", "Action Policy Evaluator", "lambda", "regional_compute", "Security", metadata={"role": "guardrails"}),
            ServicePattern("AWS Step Functions", "Human approval workflow for charge nurse or clinical operations manager schedule-change decisions", ("Amazon MWAA", "Custom workflow engine"), "workflow", "Human Approval Workflow", "step_functions", "regional_orchestration", "Security", metadata={"role": "human_approval"}),
            ServicePattern("AWS Lambda", "Idempotent approved writeback adapter for Epic/EHR and hospital scheduling systems", ("Amazon ECS",), "writeback_adapter", "Approved Writeback Adapter", "lambda", "regional_compute", "Workflow and integrations", metadata={"role": "approved_writeback_adapter"}),
            ServicePattern("Amazon S3", "Object Lock audit evidence, model artifacts, and retained operational snapshots", ("Amazon Glacier tiers", "AWS Backup vault"), "audit_lake", "HIPAA Audit Evidence Store", "s3", "regional_managed_data", "Observability and audit", metadata={"role": "audit_evidence_store"}),
        ),
        flows=(
            ("ehr", "private_connectivity", "Exchange approved patient/surgery schedule events", "FHIR/HL7 over private link", "private_integration"),
            ("staffing", "private_connectivity", "Read staffing and anesthesia readiness", "HTTPS/private", "private_integration"),
            ("sterile_processing", "private_connectivity", "Read instrument tray and sterile processing status", "HTTPS/private", "private_integration"),
            ("occupancy_metadata", "events", "Publish room occupancy metadata only", None, "event"),
            ("private_connectivity", "adapter", "Deliver clinical system events to integration adapter", None, "private_integration"),
            ("adapter", "events", "Normalize OR schedule, readiness, turnover, and status events", None, "event"),
            ("adapter", "state", "Write PHI-minimized operational state and idempotency keys", None, "data_write"),
            ("events", "state", "Update current room, staffing, tray, and turnover state", None, "event"),
            ("state", "ml", "Read approved feature snapshot for delay prediction", None, "data_read"),
            ("ml", "proposed_changes", "Write recommended delay mitigation or room reassignment proposal", None, "data_write"),
            ("proposed_changes", "policy_evaluator", "Evaluate site policy and patient-impact controls", None, "guardrail_check"),
            ("policy_evaluator", "workflow", "Route schedule change for charge nurse or supervisor approval", None, "human_approval"),
            ("workflow", "queue", "Queue approval task and retry/dead-letter handling", None, "human_approval"),
            ("workflow", "writeback_adapter", "Send only approved schedule change for idempotent writeback", None, "external_write"),
            ("writeback_adapter", "private_connectivity", "Use private hospital connectivity for approved writeback", None, "private_integration"),
            ("private_connectivity", "ehr", "Write approved schedule change to Epic / EHR or hospital scheduling system", "FHIR/HL7 over private link", "external_write"),
            ("events", "command_center", "Publish current OR state and recommendation status", None, "notification"),
            ("command_center", "workflow", "Submit approval decision for schedule recommendation", None, "human_approval"),
            ("writeback_adapter", "command_center", "Publish approved recommendation and action status", "HTTPS/private", "external_write"),
            ("workflow", "audit_lake", "Write approval, override, model version, and decision evidence", None, "audit_trace"),
            ("command_center", "auth", "Authenticate OR command center user or service principal", "OIDC/SAML", "auth"),
            ("auth", "adapter", "Authorize private clinical operations adapter access", None, "auth"),
        ),
        pricing_dimensions=("operating_room_count", "hospital_count", "schedule_events_per_day", "occupancy_metadata_events_per_day", "prediction_refresh_minutes", "approval_tasks_per_day", "audit_retention_years", "phi_state_reads_writes"),
        poc_scope="Validate OR schedule-event ingestion, readiness-state updates, delay prediction, conflict detection, and approval-gated rescheduling recommendations for one hospital, one surgical service line, and a limited set of OR rooms. Measure OR utilization, first-case start delays, turnover delay reduction, preventable cancellations, recommendation acceptance rate, approval latency, and audited writeback success before expanding to additional service lines or hospitals.",
        production_scope="Design a production-grade, single-US-region, multi-AZ healthcare OR scheduling decision-support platform with private hospital-system connectivity, PHI-safe operational state, approval-gated schedule changes, audited EHR/scheduling-system writeback, encryption, least-privilege access, monitoring, retention controls, and graceful degradation when AI recommendations are unavailable.",
        expected_views=("production_logical_service_flow", "async_flow_view", "data_access_view", "network_private_connectivity", "ai_security_governance_view", "security_observability_controls"),
    ),
    "industrial_iot_streaming_ml": WorkloadPattern(
        id="industrial_iot_streaming_ml",
        label="Industrial IoT streaming ML",
        services=(
            ServicePattern("AWS IoT Core", "Secure device telemetry ingestion and rules-based routing", ("Amazon MSK", "Direct Kinesis producers"), "iot", "Device Telemetry Ingestion", "iot_core", "regional_integration", "Ingestion"),
            ServicePattern("Amazon Kinesis Data Streams", "Durable hot stream for telemetry and events", ("Amazon MSK", "Amazon Data Firehose"), "stream", "Telemetry Stream", "kinesis", "regional_integration", "Streaming"),
            ServicePattern("Amazon Managed Service for Apache Flink", "Stateful streaming analytics, windowing, and feature extraction", ("AWS Lambda", "Amazon EMR"), "analytics", "Streaming Analytics", "kinesis", "regional_integration", "Streaming Analytics", metadata={"role": "stream_processor", "selected_service": "managed_service_for_apache_flink"}),
            ServicePattern("Amazon SageMaker", "Model training and real-time or batch inference", ("Amazon Bedrock", "ECS-hosted model service"), "ml", "Predictive Model Inference", "sagemaker", "regional_managed_ai", "ML", metadata={"role": "model_endpoint"}),
            ServicePattern(
                "AWS IoT SiteWise / time-series storage decision",
                "Industrial asset modeling and time-series storage decision point for recent telemetry and operational queries",
                ("Timestream for InfluxDB", "Amazon DynamoDB for high-scale ingestion", "Amazon S3 + Iceberg/Athena", "Aurora/RDS PostgreSQL when SQL query shape fits", "Timestream for LiveAnalytics only after availability validation"),
                "timeseries",
                "Industrial Asset Time-Series Store",
                "dynamodb",
                "regional_managed_data",
                "Data",
                metadata={"service_alternatives_required": True, "role": "time_series_store", "selected_service": "iot_sitewise_time_series_decision"},
            ),
            ServicePattern("Amazon S3", "Raw and curated telemetry data lake", ("Amazon EFS", "Amazon Redshift"), "lake", "Telemetry Data Lake", "s3", "regional_managed_data", "Data Lake", metadata={"role": "data_lake"}),
            ServicePattern("Amazon S3", "Curated feature data and training datasets", ("Amazon SageMaker Feature Store", "AWS Glue Data Catalog"), "features", "Curated Feature Store", "s3", "regional_managed_data", "Data Lake", metadata={"role": "feature_store"}),
            ServicePattern("Amazon SageMaker", "Training jobs from historical failures and curated features", ("Amazon EMR", "ECS training jobs"), "training", "Model Training", "sagemaker", "regional_managed_ai", "ML Lifecycle", metadata={"role": "training_job"}),
            ServicePattern("Amazon SageMaker", "Model registry and approved model artifacts", ("Amazon S3 model artifact registry", "MLflow on ECS"), "registry", "Model Artifact Registry", "sagemaker", "regional_managed_ai", "ML Lifecycle", metadata={"role": "model_registry"}),
        ),
        flows=(
            ("devices", "iot", "Publish telemetry", "MQTT/TLS", "async"),
            ("iot", "stream", "Route normalized events", None, "async"),
            ("stream", "analytics", "Window and extract features", None, "async"),
            ("stream", "lake", "Write raw telemetry lake", None, "data_write"),
            ("analytics", "features", "Write curated feature data", None, "data_write"),
            ("features", "training", "Train on curated features and failure history", None, "data_read"),
            ("training", "registry", "Register approved model artifact", None, "data_write"),
            ("registry", "ml", "Deploy approved model artifact", None, "model_invocation"),
            ("analytics", "ml", "Score aggregated feature windows", None, "model_invocation"),
            ("analytics", "timeseries", "Write hot metrics", None, "data_write"),
        ),
        pricing_dimensions=("device_count", "messages_per_device_per_day", "message_size_kb", "stream_retention_hours", "flink_kpu_hours", "inference_frequency", "hot_storage_days", "cold_storage_years"),
        poc_scope="Validate telemetry ingestion, streaming feature extraction, anomaly scoring, and alert quality on a representative asset subset.",
        production_scope="Operate resilient multi-AZ telemetry ingestion, streaming analytics, model lifecycle, dispatch integration, and governed operational actions.",
        expected_views=("production_logical_service_flow", "async_flow_view", "ai_security_governance_view", "data_access_view", "network_private_connectivity"),
    ),
    "real_time_anomaly_detection": WorkloadPattern(
        id="real_time_anomaly_detection",
        label="Real-time anomaly detection",
        services=(
            ServicePattern("Amazon EventBridge", "Event routing for alerts and downstream automations", ("Amazon SNS", "Amazon SQS"), "events", "Event Router", "eventbridge", "regional_integration", "Events"),
            ServicePattern("Amazon DynamoDB", "Operational state, alert dedupe, and incident state", ("Amazon Aurora", "Amazon Timestream"), "state", "Operational State", "dynamodb", "regional_managed_data", "State"),
            ServicePattern("Amazon SNS", "Operator and system notifications", ("Amazon SQS", "Amazon Pinpoint"), "notify", "Notifications", "sns", "regional_integration", "Notifications"),
        ),
        flows=(
            ("ml", "events", "Emit anomaly event", None, "event"),
            ("events", "state", "Record alert state", None, "data"),
            ("events", "notify", "Notify operators", None, "notification"),
        ),
        pricing_dimensions=("alert_rate", "event_count", "state_reads_writes", "notification_count"),
        poc_scope="Measure false positives, false negatives, and alert latency before enabling automatic downstream actions.",
        production_scope="Route scored anomaly events through durable eventing, dedupe, notification, audit, and incident state controls.",
        expected_views=("production_logical_service_flow", "async_flow_view", "data_access_view"),
    ),
    "field_service_automation": WorkloadPattern(
        id="field_service_automation",
        label="Field service automation",
        services=(
            ServicePattern("AWS Step Functions", "Governed dispatch and exception workflow orchestration", ("Amazon MWAA", "Custom workflow engine"), "workflow", "Dispatch Workflow", "step_functions", "regional_orchestration", "Workflow"),
            ServicePattern("Amazon SQS", "Buffered integration with workforce and inventory systems", ("Amazon EventBridge", "Amazon MQ"), "queue", "Integration Queue", "sqs", "regional_integration", "Integration"),
            ServicePattern("AWS Lambda", "Integration adapters and policy checks", ("Amazon ECS", "App Runner"), "adapter", "System Integration Adapter", "lambda", "regional_compute", "Integration", metadata={"role": "integration_adapter"}),
            ServicePattern("External workforce management system", "Existing field crew dispatch system", ("ServiceNow Field Service", "Salesforce Field Service"), "workforce", "Workforce Management System", "external_actor", "external_actor", "External"),
            ServicePattern("External depot inventory system", "Existing replacement equipment inventory system", ("ERP inventory module", "Warehouse management system"), "inventory", "Depot Inventory System", "external_actor", "external_actor", "External"),
        ),
        flows=(
            ("events", "workflow", "Human approval for dispatch decision", None, ""),
            ("workflow", "queue", "Buffer approved actions", None, "async"),
            ("queue", "adapter", "Invoke integration adapter", None, "async"),
            ("adapter", "workforce", "Create crew dispatch", "HTTPS", "private_integration"),
            ("adapter", "inventory", "Pre-position equipment", "HTTPS", "private_integration"),
        ),
        pricing_dimensions=("workflow_execution_count", "state_transitions", "queue_requests", "integration_api_calls", "human_approval_rate"),
        poc_scope="Run dispatch and inventory recommendations with human approval and audit before direct automation.",
        production_scope="Automate policy-approved dispatch and inventory actions with exception handling, audit, and rollback procedures.",
        expected_views=("production_logical_service_flow", "async_flow_view", "network_private_connectivity"),
    ),
    "rag_assistant": WorkloadPattern(
        id="rag_assistant",
        label="RAG assistant",
        services=(
            ServicePattern("Amazon Bedrock", "Managed foundation model access and guardrails", ("SageMaker endpoint", "Third-party model endpoint"), "model", "Foundation Model", "bedrock", "regional_managed_ai", "AI"),
            ServicePattern("Amazon OpenSearch Serverless", "Vector and hybrid retrieval", ("Aurora pgvector", "Bedrock Knowledge Bases"), "retrieval", "Knowledge Retrieval", "opensearch_serverless", "regional_managed_data", "Retrieval"),
            ServicePattern("Amazon S3", "Source document and artifact storage", ("EFS", "Database blob storage"), "documents", "Curated Documents", "s3", "regional_managed_data", "Documents"),
            ServicePattern("AWS Lambda", "Low-operations orchestration", ("ECS/Fargate", "App Runner"), "orchestrator", "Assistant Orchestrator", "lambda", "regional_compute", "Application"),
            ServicePattern("Amazon API Gateway", "Controlled API entry point", ("ALB", "AppSync"), "api", "Assistant API", "api_gateway", "regional_entry", "API"),
            ServicePattern("Amazon Cognito", "User identity", ("External IdP", "IAM Identity Center"), "auth", "User Identity", "cognito", "regional_identity", "Security"),
        ),
        flows=(
            ("user", "api", "Ask question", "HTTPS", "request"),
            ("api", "auth", "Authenticate", None, "auth"),
            ("api", "orchestrator", "Invoke assistant", None, "request"),
            ("orchestrator", "retrieval", "Retrieve context", None, "rag_retrieval"),
            ("retrieval", "documents", "Read chunks", None, "source_reference"),
            ("orchestrator", "model", "Generate grounded answer", None, "model_invocation"),
        ),
        pricing_dimensions=("requests_per_day", "tokens_per_request", "documents_gb", "vector_index_size", "log_retention_days"),
        poc_scope="Validate answer quality, citations, and safe retrieval against a curated corpus.",
        production_scope="Add private access, stronger IAM, evaluation, audit, and formal content lifecycle controls.",
        expected_views=("production_logical_service_flow", "rag_retrieval_view", "data_access_view", "ai_security_governance_view"),
    ),
    "document_intelligence": WorkloadPattern(
        id="document_intelligence",
        label="Document intelligence",
        services=(
            ServicePattern("Amazon Textract", "Document text and structure extraction", ("Amazon Bedrock Data Automation", "Custom OCR"), "extract", "Document Extraction", "sagemaker", "regional_managed_ai", "AI"),
            ServicePattern("Amazon S3", "Document landing and processed output storage", ("EFS", "Aurora"), "documents", "Document Store", "s3", "regional_managed_data", "Documents"),
            ServicePattern("AWS Step Functions", "Document processing workflow", ("AWS Lambda orchestration",), "workflow", "Document Workflow", "step_functions", "regional_orchestration", "Workflow"),
        ),
        flows=(
            ("user", "documents", "Upload document", "HTTPS", "document_ingestion"),
            ("documents", "workflow", "Start processing", None, "workflow_start"),
            ("workflow", "extract", "Extract text and fields", None, "document_processing"),
        ),
        pricing_dimensions=("documents_per_day", "pages_per_document", "extraction_type", "retention_days"),
        poc_scope="Validate extraction quality and review workflow on representative document classes.",
        production_scope="Operate governed extraction, review, downstream publishing, audit, and retention controls.",
        expected_views=("production_logical_service_flow", "data_access_view", "ai_security_governance_view"),
    ),
    "data_platform_analytics": WorkloadPattern(
        id="data_platform_analytics",
        label="Data platform analytics",
        services=(
            ServicePattern("Amazon S3", "Raw, curated, and published data lake storage", ("Amazon Redshift", "Amazon EFS"), "lake", "Data Lake", "s3", "regional_managed_data", "Data Lake"),
            ServicePattern("AWS Glue", "Catalog, ETL, and data quality jobs", ("Amazon EMR", "AWS Lambda"), "catalog", "Data Catalog and ETL", "glue", "regional_managed_data", "Data Processing"),
            ServicePattern("Amazon Athena", "Serverless SQL analytics over lake data", ("Amazon Redshift", "Amazon EMR"), "query", "Serverless Query", "athena", "regional_managed_data", "Analytics"),
            ServicePattern("Amazon Redshift", "Warehouse for governed aggregate analytics", ("Athena-only lakehouse", "Snowflake"), "warehouse", "Analytics Warehouse", "redshift", "regional_managed_data", "Analytics"),
        ),
        flows=(
            ("lake", "catalog", "Catalog and transform datasets", None, "data_processing"),
            ("catalog", "query", "Expose governed tables", None, "analytics_query"),
            ("catalog", "warehouse", "Publish aggregates", None, "analytics_publish"),
        ),
        pricing_dimensions=("storage_gb", "etl_job_hours", "query_tb_scanned", "warehouse_capacity_hours", "retention_days"),
        poc_scope="Validate data quality, lineage, and representative analytics on a bounded dataset.",
        production_scope="Operate governed ingestion, cataloging, quality checks, analytics access, audit, and retention lifecycle controls.",
        expected_views=("production_logical_service_flow", "data_access_view"),
    ),
    "financial_fraud_detection": WorkloadPattern(
        id="financial_fraud_detection",
        label="Financial fraud detection",
        services=(
            ServicePattern("Amazon Kinesis Data Streams", "Real-time transaction/event stream", ("Amazon MSK", "Amazon Data Firehose"), "stream", "Transaction Stream", "kinesis", "regional_integration", "Streaming"),
            ServicePattern("Amazon Managed Service for Apache Flink", "Streaming feature calculation and rule evaluation", ("AWS Lambda", "Amazon EMR"), "analytics", "Streaming Risk Analytics", "kinesis_stream_analytics", "regional_integration", "Streaming Analytics"),
            ServicePattern("Amazon SageMaker", "Risk scoring model training and inference", ("Amazon Bedrock", "ECS-hosted model"), "ml", "Risk Model Inference", "sagemaker", "regional_managed_ai", "ML"),
            ServicePattern("Amazon DynamoDB", "Case state, feature cache, and dedupe state", ("Amazon Aurora", "Amazon ElastiCache"), "state", "Fraud State Store", "dynamodb", "regional_managed_data", "State"),
            ServicePattern("Amazon EventBridge", "Risk event routing to case and notification systems", ("Amazon SNS", "Amazon SQS"), "events", "Risk Event Router", "eventbridge", "regional_integration", "Events"),
            ServicePattern("Amazon SQS", "Durable analyst review queue and backpressure boundary", ("Amazon EventBridge", "Amazon MQ"), "case_queue", "Analyst Case Queue", "sqs", "regional_integration", "Case Operations"),
            ServicePattern("AWS Step Functions", "Policy approval and high-confidence block workflow", ("Amazon MWAA", "Custom workflow engine"), "policy", "Policy Decision Workflow", "step_functions", "regional_orchestration", "Policy"),
            ServicePattern("AWS Lambda", "Policy checks, transaction hold adapters, and case event handlers", ("Amazon ECS", "App Runner"), "adapter", "Fraud Action Adapter", "lambda", "regional_compute", "Integration", metadata={"role": "integration_adapter"}),
            ServicePattern("Amazon S3", "Object Lock audit evidence, model artifacts, and retained transaction history", ("Amazon Glacier tiers", "Amazon Redshift"), "audit_lake", "Object Lock Audit Evidence Store", "s3", "regional_managed_data", "Audit Evidence", metadata={"role": "audit_evidence_store"}),
        ),
        flows=(
            ("user", "stream", "Submit or observe authorization events", "HTTPS", "transaction_event"),
            ("stream", "analytics", "Calculate risk features", None, "stream_processing"),
            ("analytics", "ml", "Score risk", None, "ml_inference"),
            ("ml", "events", "Emit risk event", None, "event"),
            ("events", "state", "Record case state", None, "state_write"),
            ("events", "case_queue", "Queue suspicious payments for analyst review", None, "queue_for_review"),
            ("events", "policy", "Request policy approval for high-confidence block", None, "policy_change"),
            ("policy", "adapter", "Apply approved block or hold decision", None, "external_write"),
            ("adapter", "state", "Persist action outcome and idempotency key", None, "state_write"),
            ("state", "audit_lake", "Write audit evidence with retention controls", None, "audit_write"),
            ("ml", "audit_lake", "Write score, model version, and decision evidence", None, "audit_write"),
        ),
        pricing_dimensions=("transactions_per_day", "feature_count", "flink_kpu_hours", "inference_frequency", "case_state_reads_writes", "audit_retention"),
        poc_scope="Validate detection quality and analyst review workflow on representative transaction history and shadow traffic.",
        production_scope="Operate low-latency scoring, case routing, audit, model monitoring, and policy-controlled automated holds.",
        expected_views=("production_logical_service_flow", "async_flow_view", "data_access_view", "ai_security_governance_view"),
    ),
    "agentic_workflow": WorkloadPattern(
        id="agentic_workflow",
        label="Agentic workflow",
        services=(
            ServicePattern("Amazon Bedrock", "Managed model and agent reasoning capability", ("SageMaker endpoint", "Third-party model endpoint"), "model", "Reasoning Model", "bedrock", "regional_managed_ai", "AI"),
            ServicePattern("AWS Step Functions", "Governed tool and action orchestration", ("AWS Lambda orchestration", "Temporal"), "workflow", "Tool Governance Workflow", "step_functions", "regional_orchestration", "Workflow"),
            ServicePattern("AWS Lambda", "Tool adapters with policy checks", ("Amazon ECS", "App Runner"), "adapter", "Tool Adapter", "lambda", "regional_compute", "Integration"),
            ServicePattern("Amazon DynamoDB", "Task state, approvals, and idempotency records", ("Amazon Aurora", "Amazon SQS"), "state", "Workflow State", "dynamodb", "regional_managed_data", "State"),
        ),
        flows=(
            ("user", "workflow", "Request task", "HTTPS", "request"),
            ("workflow", "model", "Plan next action", None, "model_invocation"),
            ("workflow", "adapter", "Invoke approved tool", None, "tool_call"),
            ("adapter", "state", "Persist decision state", None, "state_write"),
        ),
        pricing_dimensions=("tasks_per_day", "tokens_per_task", "tool_calls_per_task", "state_transitions", "approval_rate"),
        poc_scope="Validate tool policy, approval gates, traceability, and task success before enabling write actions.",
        production_scope="Operate constrained tools, deterministic approvals, audit, replay, error handling, and cost controls.",
        expected_views=("production_logical_service_flow", "ai_security_governance_view", "agent_tool_execution_view"),
    ),
    "computer_vision_quality_inspection": WorkloadPattern(
        id="computer_vision_quality_inspection",
        label="Computer vision quality inspection",
        services=(
            ServicePattern("Amazon S3", "Image/video landing zone and labeled dataset storage", ("Amazon EFS", "Amazon FSx"), "images", "Inspection Media Store", "s3", "regional_managed_data", "Media"),
            ServicePattern("Amazon SageMaker", "Vision model training and inference", ("Amazon Rekognition Custom Labels", "ECS-hosted model"), "ml", "Vision Model Inference", "sagemaker", "regional_managed_ai", "ML"),
            ServicePattern("Amazon Kinesis Data Streams", "Inspection event stream from lines/cameras", ("Amazon MSK", "IoT Core"), "stream", "Inspection Event Stream", "kinesis", "regional_integration", "Streaming"),
            ServicePattern("Amazon EventBridge", "Defect event routing", ("Amazon SNS", "Amazon SQS"), "events", "Defect Event Router", "eventbridge", "regional_integration", "Events"),
        ),
        flows=(
            ("user", "images", "Review labeled samples", "HTTPS", "human_review"),
            ("stream", "ml", "Score inspection frame", None, "ml_inference"),
            ("ml", "events", "Emit defect event", None, "event"),
            ("images", "ml", "Train model", None, "training_data"),
        ),
        pricing_dimensions=("frames_per_day", "image_storage_gb", "training_hours", "inference_frequency", "defect_event_rate"),
        poc_scope="Validate defect detection quality on representative lines, cameras, and labeled examples.",
        production_scope="Operate resilient inspection ingestion, model monitoring, event routing, review workflow, and retention controls.",
        expected_views=("production_logical_service_flow", "data_access_view", "async_flow_view", "ai_security_governance_view"),
    ),
    "web_api_application": WorkloadPattern(
        id="web_api_application",
        label="Web/API application",
        services=(
            ServicePattern("Amazon API Gateway", "API entry point", ("Application Load Balancer", "AppSync"), "api", "API", "api_gateway", "regional_entry", "API"),
            ServicePattern("AWS Lambda", "Application compute", ("Amazon ECS", "App Runner"), "app", "Application Service", "lambda", "regional_compute", "Application"),
            ServicePattern("Amazon DynamoDB", "Operational data store", ("Amazon Aurora", "Amazon RDS"), "state", "Application Data", "dynamodb", "regional_managed_data", "Data"),
            ServicePattern("Amazon Cognito", "User identity", ("External IdP", "IAM Identity Center"), "auth", "Identity", "cognito", "regional_identity", "Security"),
        ),
        flows=(
            ("user", "api", "Request", "HTTPS", "request"),
            ("api", "auth", "Authenticate", None, "auth"),
            ("api", "app", "Invoke application", None, "request"),
            ("app", "state", "Read/write state", None, "data_access"),
        ),
        pricing_dimensions=("requests_per_day", "active_users", "data_storage_gb", "read_write_units", "log_retention_days"),
        poc_scope="Validate core API workflows with bounded scale and operational logging.",
        production_scope="Add private connectivity, resilience, identity integration, audit, and cost controls.",
        expected_views=("production_logical_service_flow", "data_access_view", "network_private_connectivity"),
    ),
    "capital_markets_risk_engine": WorkloadPattern(
        id="capital_markets_risk_engine",
        label="Capital markets risk engine",
        services=(
            ServicePattern("External market data/exchange feeds", "Existing exchange and market data provider feeds", ("FIX/FAST feed handlers", "Vendor managed data feed"), "market_feeds", "Market Data and Exchange Feeds", "external_actor", "external_actor", "External"),
            ServicePattern("AWS Direct Connect", "Private connectivity boundary for exchange, market data, and internal trading systems", ("Site-to-Site VPN", "Partner connectivity"), "connectivity", "Private Market Connectivity", "direct_connect", "regional_integration", "Network", metadata={"role": "private_connectivity"}),
            ServicePattern("Amazon MSK", "Durable market data, position, and risk event streaming", ("Amazon Kinesis Data Streams", "Self-managed Kafka on EC2/EKS"), "market_stream", "Market Data and Position Stream", "msk", "vpc_resident", "Ingestion", metadata={"role": "market_data_ingestion"}),
            ServicePattern("Amazon DynamoDB", "Low-latency portfolio, position, and risk state store", ("Amazon Aurora", "Amazon Keyspaces"), "portfolio_state", "Portfolio and Position State", "dynamodb", "regional_managed_data", "State", metadata={"role": "portfolio_state_store"}),
            ServicePattern("Amazon ElastiCache", "Sub-second cache for Greeks, VaR, limits, and hot portfolio aggregates", ("DynamoDB Accelerator", "In-memory cache on EKS"), "risk_cache", "Low-Latency Risk Cache", "elasticache", "vpc_resident", "Low-Latency State", metadata={"role": "low_latency_cache"}),
            ServicePattern("AWS Batch", "Monte Carlo VaR and Greeks simulation job orchestration", ("Amazon EKS", "AWS ParallelCluster", "EC2 HPC fleet"), "risk_grid", "Risk Compute Grid", "batch", "vpc_resident", "Risk Compute", metadata={"role": "risk_compute_grid"}),
            ServicePattern("Amazon FSx for Lustre", "High-throughput shared scratch and simulation data store", ("Amazon EFS", "S3-only staged data"), "simulation_fs", "Simulation Scratch Storage", "fsx_lustre", "vpc_resident", "Risk Compute", metadata={"role": "simulation_scratch_storage"}),
            ServicePattern("Amazon S3", "Risk results, model inputs, audit evidence, and regulatory retention store", ("S3 Glacier tiers", "Amazon Redshift"), "risk_lake", "Risk Results and Audit Lake", "s3", "regional_managed_data", "Audit and History", metadata={"role": "risk_results_store"}),
            ServicePattern("AWS Step Functions", "Orchestration for batch risk windows, exception handling, and compliance workflow", ("EventBridge Scheduler", "MWAA"), "risk_workflow", "Risk Orchestration Workflow", "step_functions", "regional_orchestration", "Workflow", metadata={"role": "risk_orchestration"}),
            ServicePattern("Amazon EventBridge", "Publication of risk results and compliance decision events", ("Amazon SNS", "Amazon SQS"), "risk_events", "Risk Event Bus", "eventbridge", "regional_integration", "Events", metadata={"role": "risk_result_publication"}),
            ServicePattern("AWS Lambda", "Pre-trade compliance policy adapter and downstream integration handler", ("Amazon ECS", "EKS service"), "compliance_adapter", "Pre-Trade Compliance Adapter", "lambda", "regional_compute", "Compliance", metadata={"role": "pre_trade_compliance_adapter"}),
            ServicePattern("Amazon Athena", "Historical investigation and regulatory/audit query path", ("Amazon Redshift", "Amazon EMR"), "audit_query", "Audit and Investigation Query", "athena", "regional_managed_data", "Audit and Reporting", metadata={"role": "audit_query"}),
        ),
        flows=(
            ("market_feeds", "connectivity", "Deliver exchange and market data feeds", "Private circuit/FIX", "private_integration"),
            ("connectivity", "market_stream", "Normalize and publish market/position events", None, "stream_ingestion"),
            ("market_stream", "portfolio_state", "Update portfolio and position state", None, "state_write"),
            ("portfolio_state", "risk_cache", "Refresh hot Greeks, limits, and portfolio aggregates", None, "cache_write"),
            ("risk_workflow", "risk_grid", "Start scheduled or triggered VaR/Greeks run", None, "workflow_start"),
            ("risk_grid", "simulation_fs", "Read/write high-throughput simulation scratch data", None, "hpc_data_access"),
            ("portfolio_state", "risk_grid", "Read positions and market context for risk window", None, "state_read"),
            ("risk_grid", "risk_cache", "Publish sub-second risk and Greeks results", None, "cache_write"),
            ("risk_grid", "risk_lake", "Persist risk results, inputs, and model/run evidence", None, "audit_write"),
            ("risk_cache", "compliance_adapter", "Serve pre-trade risk/compliance decision", None, "policy_check"),
            ("compliance_adapter", "connectivity", "Use private connectivity for downstream trading/compliance integration", "PrivateLink/Direct Connect", "private_integration"),
            ("compliance_adapter", "risk_events", "Publish approved/blocked decision event", None, "trade_block"),
            ("risk_lake", "audit_query", "Query retained evidence for regulatory review", None, "analytics_query"),
        ),
        pricing_dimensions=("open_positions", "exchange_count", "greeks_frequency_seconds", "risk_compute_jobs", "hpc_compute_hours", "risk_grid_nodes", "shared_storage_throughput", "portfolio_state_reads_writes", "cache_node_hours", "audit_storage_gb", "reporting_query_tb_scanned"),
        poc_scope="Validate market data normalization, portfolio-state refresh, representative Monte Carlo risk jobs, sub-second cache reads, and compliance decision latency on a bounded portfolio slice.",
        production_scope="Operate private market-data ingestion, low-latency portfolio state, risk compute grid, governed pre-trade decisions, audit evidence retention, and regulatory reporting with measured compute and storage drivers.",
        expected_views=("production_logical_service_flow", "async_flow_view", "data_access_view", "network_private_connectivity", "security_observability_controls"),
    ),
    "live_streaming": WorkloadPattern(
        id="live_streaming",
        label="Live media streaming",
        services=(
            ServicePattern("External live contribution feeds", "Venue, broadcast, or partner live media contribution feeds", ("AWS Elemental Link", "Partner contribution network"), "media_sources", "Live Contribution Feeds", "external_actor", "external_actor", "Media sources"),
            ServicePattern("AWS Elemental MediaLive", "Live encoding and channel processing", ("AWS Elemental MediaConnect", "Partner encoder"), "medialive", "Live Encoding", "medialive", "regional_managed_data", "Live processing", metadata={"role": "live_encoder"}),
            ServicePattern("AWS Elemental MediaPackage", "Origin packaging, manifests, and playback protection integration", ("Amazon S3 origin", "Partner origin"), "mediapackage", "Packaged Origin", "mediapackage", "regional_managed_data", "Origin and rights", metadata={"role": "packaged_origin"}),
            ServicePattern("Amazon CloudFront", "Global CDN delivery and edge policy enforcement", ("Third-party CDN", "Regional delivery only"), "cdn", "Global CDN Delivery", "cloudfront", "global_edge", "CDN delivery", metadata={"role": "cdn_delivery"}),
            ServicePattern("AWS Lambda@Edge / CloudFront Functions", "Geo-rights blackout and lightweight edge request decisions", ("Regional API authorization", "Partner entitlement service"), "edge_policy", "Geo-rights and Edge Policy", "lambda_edge", "global_edge", "Rights enforcement", metadata={"role": "edge_policy"}),
            ServicePattern("Amazon DynamoDB", "Geo-rights, blackout, entitlement, and regional policy store for edge decisions", ("Amazon Aurora", "Partner rights system"), "geo_rights_store", "Geo-Rights Policy Store", "dynamodb", "regional_managed_data", "Rights enforcement", metadata={"role": "geo_rights_policy_store"}),
            ServicePattern("External DRM license/key provider", "SPEKE-compatible DRM license and key service integrated with protected playback", ("Partner DRM provider", "Existing rights platform"), "drm_provider", "DRM License and Key Service", "external_actor", "external_actor", "Rights and consent", metadata={"role": "drm_license_key_provider"}),
            ServicePattern("External consent management platform", "Ad consent, privacy, and regional consent-policy source for playback and ad decisions", ("Existing CMP", "Partner consent platform"), "consent_platform", "Consent Policy Source", "external_actor", "external_actor", "Rights and consent", metadata={"role": "consent_policy_source"}),
            ServicePattern("AWS Elemental MediaTailor", "Server-side ad insertion and ad decision integration", ("Client-side ad insertion", "Partner SSAI"), "ads", "Ad Decision and Insertion", "mediatailor", "regional_integration", "Ad decisions", metadata={"role": "ad_decision"}),
            ServicePattern("Amazon CloudWatch / Kinesis Data Streams", "Playback QoE, error, startup-time, and glass-to-glass latency event collection", ("Third-party QoE analytics", "OpenTelemetry collector"), "qoe_monitoring", "Playback QoE and Latency Monitoring", "cloudwatch", "regional_observability", "Observability", metadata={"role": "qoe_latency_monitoring"}),
            ServicePattern("Amazon S3", "VOD clips, event archives, logs, and media artifacts", ("Amazon EFS", "Partner media store"), "media_lake", "Media Archive and Logs", "s3", "regional_managed_data", "Archive and evidence", metadata={"role": "media_archive"}),
        ),
        flows=(
            ("media_sources", "medialive", "Contribute live sports feed", "RTP/Zixi/SRT", "media_delivery"),
            ("medialive", "mediapackage", "Encode and publish live channels", None, "media_delivery"),
            ("mediapackage", "drm_provider", "Request DRM license and key material for protected playback", "SPEKE/HTTPS", "media_rights"),
            ("mediapackage", "cdn", "Distribute manifests and segments globally", "HTTPS", "media_delivery"),
            ("edge_policy", "geo_rights_store", "Read geo-rights, blackout, and entitlement policy", None, "media_rights"),
            ("edge_policy", "cdn", "Apply geo-rights blackout and entitlement decision", None, "media_rights"),
            ("ads", "consent_platform", "Check ad consent and regional privacy policy before ad decision", "HTTPS", "media_rights"),
            ("ads", "mediapackage", "Insert server-side ad decision into playback session", None, "media_ad_decision"),
            ("cdn", "qoe_monitoring", "Emit playback errors, startup time, rebuffering, and latency QoE events", None, "media_qoe"),
            ("medialive", "media_lake", "Archive event outputs and logs", None, "media_qoe"),
        ),
        pricing_dimensions=("concurrent_viewers", "bitrate_mbps", "cdn_egress_gb", "channel_hours", "origin_requests", "ad_decisions", "drm_license_requests", "country_count"),
        poc_scope="Validate live channel workflow, playback latency, edge blackout policy, and representative viewer load with bounded geography.",
        production_scope="Operate resilient live encoding, origin packaging, CDN delivery, geo-rights enforcement, DRM/ad-decision integration, and media/audit retention.",
        expected_views=("production_logical_service_flow", "live_media_delivery_view", "media_rights_ad_decisioning_view", "media_qoe_analytics_view", "security_observability_controls"),
    ),
}


def selected_patterns(profile: UseCaseProfile) -> list[WorkloadPattern]:
    pattern_ids: list[str] = []
    for family in profile.workload_families:
        pattern_ids.extend(_pattern_ids_for_family(family))
    patterns = [PATTERNS[family] for family in pattern_ids if family in PATTERNS]
    if not patterns:
        patterns = [PATTERNS["web_api_application"]]
    return _dedupe_patterns(patterns)


def service_recommendations(profile: UseCaseProfile, evidence_ids: list[str]) -> list[AWSServiceRecommendation]:
    services: list[AWSServiceRecommendation] = []
    seen = set()
    for pattern in selected_patterns(profile):
        for item in pattern.services:
            key = item.service.lower()
            if key in seen:
                continue
            seen.add(key)
            services.append(
                AWSServiceRecommendation(
                    service=item.service,
                    purpose=item.purpose,
                    rationale=_service_specific_rationale(item, pattern, profile),
                    alternatives_considered=list(item.alternatives),
                    evidence_ids=evidence_ids,
                )
            )
    for recommendation in _capability_service_recommendations(profile, evidence_ids):
        key = recommendation.service.lower()
        if key not in seen:
            services.append(recommendation)
            seen.add(key)
    for common in (
        AWSServiceRecommendation(service="Amazon CloudWatch", purpose="Metrics, logs, dashboards, and alarms", rationale="Required for operational reliability and cost visibility.", alternatives_considered=["Third-party observability"], evidence_ids=evidence_ids),
        AWSServiceRecommendation(service="AWS KMS", purpose="Encryption key management", rationale="Required for encryption controls across data, logs, and integration artifacts.", alternatives_considered=["Service-owned keys only"], evidence_ids=evidence_ids),
        AWSServiceRecommendation(service="AWS CloudTrail", purpose="Audit event recording", rationale="Required for governance and incident investigation.", alternatives_considered=["Application logs only"], evidence_ids=evidence_ids),
    ):
        if common.service.lower() not in seen:
            services.append(common)
            seen.add(common.service.lower())
    return services


def _service_specific_rationale(item: ServicePattern, pattern: WorkloadPattern, profile: UseCaseProfile) -> str:
    role = str(item.metadata.get("role") or item.service_key or item.component_id or item.service).lower()
    service = item.service.lower()
    capability_hint = ", ".join(profile.capabilities[:6]) or "the extracted workload requirements"
    role_rationales = {
        "stream_processor": "It owns stateful windowing, late-event handling, feature extraction, and continuous anomaly-preparation logic before scoring or storage.",
        "model_endpoint": "It owns governed model hosting or batch/real-time scoring, separating ML inference from stream-processing and workflow side effects.",
        "training_job": "It owns repeatable training against historical failure patterns and curated features, keeping model build activity separate from production scoring.",
        "model_registry": "It owns approved model artifact lifecycle and promotion control so production scoring uses traceable model versions.",
        "data_lake": "It owns raw, replayable, and retained data needed for audit, retraining, historical analysis, and forensic recovery.",
        "feature_store": "It owns curated feature datasets so training, validation, and scoring use consistent feature definitions.",
        "time_series_store": "It is intentionally modeled as a decision point because hot operational queries, asset modeling, historical replay, and high-ingest telemetry can require different stores.",
        "integration_adapter": "It owns policy checks, idempotency, retries, and translation between AWS workflows and external enterprise systems.",
        "market_data_ingestion": "It owns normalized market data, position, and risk events without forcing the hot risk path through ad hoc batch scans.",
        "portfolio_state_store": "It owns current positions and portfolio state so risk calculations can read bounded operational state instead of scanning raw history.",
        "low_latency_cache": "It owns hot Greeks, VaR, limits, and portfolio aggregates where sub-second decision paths require fast reads.",
        "risk_compute_grid": "It owns Monte Carlo and Greeks simulation execution as a compute grid with explicit job, node, and runtime drivers.",
        "simulation_scratch_storage": "It owns high-throughput scratch storage for simulation runs, separate from long-retention audit storage.",
        "risk_results_store": "It owns retained risk results, run inputs, model evidence, and regulatory audit artifacts.",
        "risk_orchestration": "It owns scheduled risk windows, exception handling, retries, and bounded workflow state for risk compute.",
        "pre_trade_compliance_adapter": "It owns policy checks and downstream decision publication without hiding trading-impact controls inside compute jobs.",
    }
    service_rationales = (
        ("iot core", "It provides managed device identity, secure MQTT/TLS ingestion, rules routing, and scale boundaries for device telemetry."),
        ("kinesis data streams", "It provides a durable hot buffer for high-volume ordered telemetry and protects downstream analytics from producer spikes."),
        ("eventbridge", "It normalizes domain events and decouples anomaly producers from workflow, notification, and case-management consumers."),
        ("sqs", "It absorbs downstream integration backpressure and supports retry/dead-letter handling for operational actions."),
        ("step functions", "It gives dispatch and exception handling an auditable workflow boundary instead of hiding action policy inside code."),
        ("dynamodb", "It fits low-latency operational state, dedupe keys, alert state, feature cache, and idempotency records."),
        ("s3", "It is the durable system of record for raw/curated data, artifacts, evidence, lifecycle retention, and replay."),
        ("cloudwatch", "It is needed to operate the workload through metrics, logs, alarms, dashboards, and cost/throughput signals."),
        ("kms", "It centralizes encryption key controls for telemetry, model artifacts, logs, and generated evidence packages."),
        ("cloudtrail", "It records control-plane activity for governance, incident investigation, and audit evidence."),
        ("lambda", "It is suitable for bounded integration adapters, policy checks, and event handlers when container orchestration is unnecessary."),
        ("sagemaker", "It supports managed model training, registry, deployment, monitoring, and MLOps controls for predictive workloads."),
        ("bedrock", "It supports managed foundation-model access and governance for generative AI workloads without self-hosting model infrastructure."),
    )
    detail = role_rationales.get(role)
    if not detail:
        detail = next((text for token, text in service_rationales if token in service), None)
    detail = detail or item.purpose
    return (
        f"{detail} Selected for the {pattern.label} workload because the use case requires {capability_hint}. "
        f"Alternatives remain explicit where cost, latency, regional availability, or operational model may change the final selection."
    )


def _capability_service_recommendations(profile: UseCaseProfile, evidence_ids: list[str]) -> list[AWSServiceRecommendation]:
    caps = set(_capabilities(profile))
    recommendations: list[AWSServiceRecommendation] = []

    def add(service: str, purpose: str, rationale: str, alternatives: list[str] | None = None) -> None:
        recommendations.append(
            AWSServiceRecommendation(
                service=service,
                purpose=purpose,
                rationale=rationale,
                alternatives_considered=alternatives or [],
                evidence_ids=evidence_ids,
            )
        )

    if caps & {"hpc_simulation", "monte_carlo_simulation"}:
        add("AWS Batch", "Managed batch and simulation job orchestration", "Selected because the workload requires large simulation or batch compute windows.", ["Amazon EKS", "AWS ParallelCluster"])
        add("Amazon FSx for Lustre", "High-throughput shared storage for simulation datasets", "Selected for high-performance file access during large compute runs.", ["Amazon EFS", "Amazon S3 only"])
    if caps & {"graph_analytics", "graph_store", "graph_ml_inference", "gnn_inference", "molecular_graph_modeling"}:
        add("Amazon Neptune", "Graph database for entity, relationship, or molecular graph workloads", "Selected because extracted capabilities include graph storage, traversal, or graph ML.", ["Amazon DynamoDB adjacency model", "Amazon OpenSearch"])
    if caps & {"video_streaming", "low_latency_media_delivery", "drm_enforcement", "geo_rights_enforcement"}:
        add("Amazon CloudFront", "Global content delivery and edge enforcement", "Selected for high-concurrency media delivery, low-latency distribution, or geo enforcement.", ["Regional delivery only", "Third-party CDN"])
        add("AWS Elemental MediaLive", "Live video processing workflow", "Selected because the workload includes live video streaming or glass-to-glass latency constraints.", ["AWS Elemental MediaConvert", "Partner encoder"])
    if caps & {"air_gapped_deployment", "sovereign_deployment"} or any(posture in profile.deployment_posture for posture in ("air_gapped_on_prem", "sovereign_cloud")):
        add("AWS Outposts", "Hybrid or customer-controlled deployment option", "Selected because the workload explicitly has air-gapped, disconnected, sovereign, or customer-controlled infrastructure constraints.", ["AWS Local Zones", "Customer-managed on-prem only"])
    if caps & {"biometric_request_processing", "biometric_matching", "biometric_data"}:
        add("Amazon Rekognition", "Biometric or image matching candidate requiring strict validation", "Selected as a candidate because extracted capabilities include biometric matching; suitability must be validated against sovereignty and compliance constraints.", ["Custom SageMaker model", "On-prem biometric engine"])
    if caps & {"exchange_colocation", "fpga_acceleration", "microsecond_latency"}:
        add("AWS Direct Connect", "Dedicated private connectivity to external low-latency venues", "Selected because extracted capabilities include exchange or colocated integration.", ["Carrier cross-connect", "Private WAN"])
        add("Amazon EC2 accelerated compute", "Specialized compute candidate for hardware-accelerated workloads", "Selected because extracted capabilities include FPGA acceleration or microsecond-class latency.", ["Customer colocated FPGA appliance", "Bare-metal EC2"])
    if caps & {"ota_rollout_orchestration", "canary_deployment", "automated_rollback"}:
        add("AWS IoT Jobs", "Fleet rollout orchestration and staged device updates", "Selected because extracted capabilities include OTA rollout, canary deployment, or rollback.", ["AWS Systems Manager", "Custom fleet manager"])
    if caps & {"route_optimization", "geospatial_analytics"}:
        add("Amazon Location Service", "Geospatial tracking, routing, and map services", "Selected because extracted capabilities include routing, separation, fleet, or geospatial optimization.", ["Custom GIS platform", "Third-party maps"])
    if caps & {"inventory_optimization", "external_workflow_integration"}:
        add("Amazon EventBridge", "Enterprise integration event routing", "Selected because extracted capabilities include external workflow or inventory integration.", ["Amazon SQS", "Amazon MQ"])
    return recommendations


def pattern_components(profile: UseCaseProfile, production: bool) -> list[ArchitectureComponent]:
    patterns = selected_patterns(profile)
    components: list[ArchitectureComponent] = []
    if any(any(endpoint == "user" for flow in pattern.flows for endpoint in flow[:2]) for pattern in patterns):
        components.append(ArchitectureComponent(id="user", name=_actor_name(profile), service="external_actor", scope="external_actor", logical_group="Actors"))
    has_device_source = any(pattern.id == "industrial_iot_streaming_ml" for pattern in patterns) or (
        any(pattern.id == "real_time_anomaly_detection" for pattern in patterns)
        and "financial_fraud_detection" not in {pattern.id for pattern in patterns}
        and any(capability in _capabilities(profile) for capability in ("device_telemetry", "time_series_storage", "time_series_analytics"))
    )
    if has_device_source:
        components.append(ArchitectureComponent(id="devices", name=_asset_source_name(profile), service="external_actor", scope="external_actor", logical_group="Sources and edge", metadata={"metrics": [metric.__dict__ for metric in profile.metrics], "role": "field_asset"}))
    seen = {component.id for component in components}
    for pattern in patterns:
        for service in pattern.services:
            component_id = service.component_id or _slug(service.service)
            if component_id in seen:
                continue
            if not production and component_id in {"workforce", "inventory"}:
                continue
            components.append(
                ArchitectureComponent(
                    id=component_id,
                    name=service.component_name or service.service,
                    service=service.service_key or _canonical_service_key(service.service),
                    scope="vpc_resident" if production and component_id == "adapter" else service.scope,
                    vpc_id="prod-vpc" if production and component_id == "adapter" else None,
                    logical_group=service.logical_group,
                    metadata=dict(service.metadata),
                )
            )
            seen.add(component_id)
    if production:
        extras = []
        if "api" in seen and "user" in seen:
            extras.extend([
                ArchitectureComponent(id="waf", name="Web Protection", service="waf", scope="edge_or_regional_control", logical_group="Edge Security"),
                ArchitectureComponent(id="shield", name="DDoS Protection", service="shield", scope="global_edge_control", logical_group="Edge Security"),
            ])
        for extra in extras:
            if extra.id not in seen:
                components.append(extra)
                seen.add(extra.id)
    for common in (
        ArchitectureComponent(id="logs", name="Operational Observability", service="cloudwatch", scope="regional_observability", logical_group="Operations"),
        ArchitectureComponent(id="kms", name="Encryption Keys", service="kms", scope="regional_security", logical_group="Security"),
        ArchitectureComponent(id="audit", name="Audit Trail", service="cloudtrail", scope="regional_audit", logical_group="Operations"),
    ):
        if common.id not in seen:
            components.append(common)
            seen.add(common.id)
    domain_lane_model = resolve_domain_lane_model(profile.domain, profile.workload_families)
    if domain_lane_model is not None:
        apply_domain_lane_model(domain_lane_model, components)
    else:
        lane_plan = plan_lanes(_capabilities(profile), components)
        for component in components:
            label = lane_label_for_component(component, lane_plan)
            if label:
                component.logical_group = label
                component.metadata["lane_id"] = next((lane.lane_id for lane in lane_plan.lanes if lane.label == label), None)
                component.metadata["lane_label"] = label
                component.metadata.setdefault("semantic_role", component.logical_group)
    return components


def pattern_flows(profile: UseCaseProfile, production: bool, components: list[ArchitectureComponent]) -> list[ArchitectureFlow]:
    component_ids = {component.id for component in components}
    flows: list[ArchitectureFlow] = []
    index = 1
    for pattern in selected_patterns(profile):
        for source, target, label, protocol, classification in pattern.flows:
            if source not in component_ids or target not in component_ids:
                continue
            metadata = _flow_metadata(profile, source, target, label, classification)
            flows.append(ArchitectureFlow(id=f"f{index}", source=source, target=target, label=label, protocol=protocol, metadata=metadata))
            index += 1
    if production and "waf" in component_ids and "api" in component_ids and "user" in component_ids:
        if "shield" in component_ids:
            flows.append(ArchitectureFlow(id=f"f{index}", source="user", target="shield", label="DDoS-protected ingress", protocol="HTTPS", metadata={"classification": "request"}))
            index += 1
            flows.append(ArchitectureFlow(id=f"f{index}", source="shield", target="waf", label="Forward protected traffic", protocol="HTTPS", metadata={"classification": "request"}))
            index += 1
        else:
            flows.append(ArchitectureFlow(id=f"f{index}", source="user", target="waf", label="Protected ingress", protocol="HTTPS", metadata={"classification": "request"}))
            index += 1
        flows.append(ArchitectureFlow(id=f"f{index}", source="waf", target="api", label="Allowed requests", protocol="HTTPS", metadata={"classification": "request"}))
        index += 1
    healthcare_or = "healthcare_operations_scheduling" in profile.workload_families
    for target, label, classification in (("logs", "Emit metrics and logs", ""), ("kms", "Encrypt data and artifacts", ""), ("audit", "Record audit events", "")):
        if target not in component_ids:
            continue
        for source in _operational_sources(component_ids):
            metadata = {"classification": classification} if classification else {}
            # Healthcare OR: keep governance/observability fan-out as a sidecar so it
            # does not crisscross the primary logical service flow. The edge is
            # preserved (recorded in metadata) and surfaced in governance/detail views.
            if healthcare_or:
                metadata["logical_detail_only"] = True
            flows.append(ArchitectureFlow(id=f"f{index}", source=source, target=target, label=label, metadata=metadata))
            index += 1
            break
    return _dedupe_flows(flows)


def _flow_metadata(profile: UseCaseProfile, source: str, target: str, label: str | None, classification: str | None) -> dict:
    metadata = {"classification": classification} if classification else {}
    if "healthcare_operations_scheduling" not in profile.workload_families:
        return metadata
    text = f"{source} {target} {label or ''} {classification or ''}".lower()
    prohibited = any(term in text for term in ("patient-identifiable video", "facial recognition", "patient identity inference"))
    approval_required = classification in {"external_write", "human_approval"} or any(term in text for term in ("schedule change", "writeback", "reassignment", "staffing assignment", "patient-facing"))
    external_write = classification == "external_write" or "writeback" in text
    patient_impacting = any(term in text for term in ("schedule change", "reassignment", "patient", "ehr", "epic", "anesthesia", "nurse", "staffing"))
    if prohibited:
        governance_mode = "prohibited"
    elif approval_required:
        governance_mode = "approval_required"
    elif classification in {"guardrail_check"}:
        governance_mode = "site_policy_required"
    else:
        governance_mode = "automated_allowed"
    if "writeback" in text or target == "ehr":
        action_type = "ehr_writeback"
    elif "schedule change" in text or "reassignment" in text:
        action_type = "schedule_change"
    elif "staffing" in text:
        action_type = "staffing_change"
    elif "audit" in text:
        action_type = "audit_event"
    elif "notification" in text or "publish approved recommendation" in text:
        action_type = "notification"
    elif classification in {"data_write", "event"}:
        action_type = "state_update"
    else:
        action_type = "recommendation"
    metadata.update({
        "governance_mode": governance_mode,
        "action_type": action_type,
        "external_write": external_write,
        "patient_impacting": patient_impacting,
        "approval_required": approval_required,
        "approver_role": "charge_nurse" if approval_required else None,
        "audit_required": True,
        "idempotency_required": bool(external_write or action_type in {"state_update", "ehr_writeback"}),
        "rollback_or_compensation_required": bool(external_write),
        "policy_control_id": f"policy_healthcare_or_{action_type}",
        "evidence_required": bool(external_write or patient_impacting or "phi" in text),
    })
    if _healthcare_logical_detail_only(source, target, classification):
        metadata["logical_detail_only"] = True
    if prohibited:
        metadata["failure_behavior"] = "block"
    elif approval_required:
        metadata["failure_behavior"] = "queue_for_review"
    return metadata


def _healthcare_logical_detail_only(source: str, target: str, classification: str | None) -> bool:
    return (
        (source == "workflow" and target == "queue")
        or (source == "private_connectivity" and target == "ehr")
        or (source == "writeback_adapter" and target == "command_center")
        or (source == "adapter" and target == "state")
        or (source == "workflow" and target == "audit_lake")
        or classification in {"auth"}
    )


def security_controls(profile: UseCaseProfile, production: bool) -> list[SecurityControl]:
    controls = list(COMMON_SECURITY)
    if profile.actions:
        controls.append(SecurityControl(name="Human approval for high-impact actions", rationale="Prevents unsafe autonomous updates to operational or customer-impacting systems."))
    if production:
        controls.extend([
            SecurityControl(name="Private connectivity and egress controls", rationale="Keeps production integrations and managed service access inside approved network paths where supported."),
            SecurityControl(name="Policy-based action guardrails", rationale="Constrains automated workflows to approved action types, thresholds, and exception paths."),
        ])
    return _dedupe_named(controls)


def observability_controls(profile: UseCaseProfile, production: bool) -> list[ObservabilityControl]:
    controls = list(COMMON_OBSERVABILITY)
    if "real_time_ingestion" in profile.capabilities:
        controls.append(ObservabilityControl(name="Pipeline lag and throughput alarms", rationale="Detects ingestion, stream processing, and inference delays before operational SLAs are missed."))
    if "predictive_ml" in profile.capabilities:
        controls.append(ObservabilityControl(name="Model quality and drift monitoring", rationale="Tracks false positives, false negatives, feature drift, and retraining triggers."))
    if production:
        controls.append(ObservabilityControl(name="Business SLA dashboards", rationale="Connects technical health to outage, dispatch, restoration, and customer-impact objectives."))
    return _dedupe_named(controls)


def pricing_dimensions(profile: UseCaseProfile) -> list[str]:
    dimensions = []
    for family in profile.workload_families:
        dimensions.extend(_family_pricing_dimensions(family))
    for pattern in selected_patterns(profile):
        dimensions.extend(pattern.pricing_dimensions)
    advisory = list(((getattr(profile, "discovery_plan", {}) or {}).get("pricing_drivers") or []))
    dimensions.extend(advisory)
    dimensions.extend(["region", "availability_target", "data_retention", "observability_retention"])
    return list(dict.fromkeys(dimensions))


def _pattern_ids_for_family(family: str) -> list[str]:
    aliases = {
        "surgical_scheduling_prediction": ["healthcare_operations_scheduling"],
        "clinical_workflow_decision_support": ["healthcare_operations_scheduling"],
        "computer_vision_metadata_processing": ["healthcare_operations_scheduling"],
        "approval_gated_workflow_automation": ["healthcare_operations_scheduling"],
        "telecom_network_analytics": ["real_time_anomaly_detection", "data_platform_analytics"],
        "cdr_congestion_prediction": ["real_time_anomaly_detection", "data_platform_analytics"],
        "capital_markets_risk_engine": ["capital_markets_risk_engine"],
        "monte_carlo_risk_grid": ["capital_markets_risk_engine"],
        "pre_trade_compliance": ["capital_markets_risk_engine"],
        "document_intelligence": ["rag_assistant"],
    }
    return aliases.get(family, [family])


def _family_pricing_dimensions(family: str) -> list[str]:
    dimensions = {
        "healthcare_operations_scheduling": ["operating_room_count", "hospital_count", "or_schedule_events_per_day", "occupancy_metadata_events_per_day", "prediction_refresh_minutes", "approval_tasks_per_day", "audit_retention_years"],
        "surgical_scheduling_prediction": ["scheduled_surgeries_per_day", "prediction_refresh_minutes", "feature_snapshot_reads", "recommendations_per_day"],
        "clinical_workflow_decision_support": ["approval_tasks_per_day", "clinical_integration_api_calls", "phi_state_reads_writes"],
        "computer_vision_metadata_processing": ["occupancy_metadata_events_per_day", "metadata_payload_kb", "video_retention_boundary"],
        "approval_gated_workflow_automation": ["workflow_state_transitions", "approval_rate", "override_rate", "audit_retention_years"],
        "financial_fraud_detection": ["transactions_per_day", "scoring_events_per_day", "scoring_latency_target", "feature_reads_per_transaction", "case_creation_rate", "block_rate", "audit_retention"],
        "telecom_network_analytics": ["cdrs_per_day", "cell_tower_count", "prediction_horizon_minutes", "cdr_retention_years", "qos_policy_events"],
        "cdr_congestion_prediction": ["cdrs_per_day", "feature_windows_per_day", "model_scoring_frequency", "traffic_shaping_decisions"],
        "capital_markets_risk_engine": ["open_positions", "exchange_count", "greeks_frequency_seconds", "var_latency_target", "risk_compute_jobs"],
        "monte_carlo_risk_grid": ["simulation_count", "hpc_compute_hours", "shared_storage_throughput", "risk_grid_nodes"],
        "pre_trade_compliance": ["policy_decisions", "audit_retention", "override_workflows", "compliance_reports"],
        "document_intelligence": ["historical_contract_count", "average_pages_or_mb_per_contract", "new_or_updated_contracts_per_month", "document_types", "ocr_text_extraction_rate", "embedding_indexing_frequency", "rag_queries_per_day", "active_legal_users", "obligation_review_approvals_per_month", "audit_retention_duration"],
        "rag_assistant": ["document_count", "document_size", "embedding_indexing_frequency", "rag_queries_per_day", "active_users", "audit_retention_duration"],
    }
    return dimensions.get(family, [])


def expected_views(profile: UseCaseProfile, production: bool) -> list[str]:
    semantic = plan_semantic_views(_capabilities(profile), production=production, network_required=production and _network_required(profile, []))
    compiler_views = compiler_views_for_semantic(semantic)
    is_video_streaming = "video_streaming" in _capabilities(profile) or "live_streaming" in profile.workload_families
    for pattern in selected_patterns(profile):
        compiler_views.extend(
            view
            for view in pattern.expected_views
            if (production or view != "network_private_connectivity") and not (is_video_streaming and view in {"data_access_view", "async_flow_view"})
        )
    return list(dict.fromkeys(compiler_views))


def semantic_views(profile: UseCaseProfile, production: bool) -> list[str]:
    return plan_semantic_views(_capabilities(profile), production=production, network_required=production and _network_required(profile, []))


def poc_scope(profile: UseCaseProfile) -> str:
    return " ".join(pattern.poc_scope for pattern in selected_patterns(profile))


def production_scope(profile: UseCaseProfile) -> str:
    return " ".join(pattern.production_scope for pattern in selected_patterns(profile))


def _dedupe_patterns(patterns: list[WorkloadPattern]) -> list[WorkloadPattern]:
    seen = set()
    result = []
    for pattern in patterns:
        if pattern.id not in seen:
            result.append(pattern)
            seen.add(pattern.id)
    return result


def _actor_name(profile: UseCaseProfile) -> str:
    if profile.domain == "energy_utility":
        return "Grid Operations User"
    if profile.domain == "financial_services":
        return "Payment Authorization Source / Fraud Operations User"
    if profile.domain == "healthcare":
        return "Clinical Operations User"
    return "User"


def _asset_source_name(profile: UseCaseProfile) -> str:
    entities = [entity.replace("_", " ") for entity in profile.entities if entity not in {"field_crew", "depot"}]
    return " / ".join(entities[:3]).title() if entities else "Telemetry Sources"


def _canonical_service_key(service: str) -> str:
    return _slug(service.replace("Amazon ", "").replace("AWS ", ""))


def _slug(value: str) -> str:
    return value.lower().replace("/", " ").replace("-", " ").replace(" ", "_")


def _operational_sources(component_ids: set[str]) -> list[str]:
    preferred = [
        "analytics",
        "stream",
        "hbase_adapter",
        "query",
        "migration",
        "ml",
        "workflow",
        "adapter",
        "app",
        "orchestrator",
        "api",
        "iot",
    ]
    return [item for item in preferred if item in component_ids]


def _capabilities(profile: UseCaseProfile) -> list[str]:
    return list(dict.fromkeys(profile.capability_model + profile.capabilities))


def _network_required(profile: UseCaseProfile, components: list[ArchitectureComponent]) -> bool:
    capabilities = set(_capabilities(profile))
    if {"external_system_integration", "external_workflow_integration", "inventory_or_depot_integration", "private_connectivity"} & capabilities:
        return True
    if profile.domain in {"energy_utility", "telecommunications", "government", "financial_markets"} and "production" not in profile.deployment_posture:
        return True
    ids = {component.id for component in components}
    return bool(ids & {"workforce", "inventory", "adapter"}) or any(component.vpc_id for component in components)


def _dedupe_flows(flows: list[ArchitectureFlow]) -> list[ArchitectureFlow]:
    seen = set()
    result = []
    for flow in flows:
        key = (flow.source, flow.target, flow.label)
        if key in seen:
            continue
        seen.add(key)
        result.append(flow)
    return result


def _dedupe_named(items):
    seen = set()
    result = []
    for item in items:
        if item.name.lower() in seen:
            continue
        seen.add(item.name.lower())
        result.append(item)
    return result
