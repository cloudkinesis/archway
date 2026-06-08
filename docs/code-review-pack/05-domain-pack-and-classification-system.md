# Domain Pack and Classification System

Archway uses deterministic profiling first, with optional model assistance in some understanding/research paths. The core profile logic lives in `app/services/use_case_profile.py`.

## Profile Contents

A use-case profile can include:

- Domain, such as healthcare, telecommunications, media, financial markets, energy utility, generic web application, etc.
- Workload families, such as `healthcare_operations_scheduling`, `telecom_network_analytics`, `live_media_streaming`, `payment_fraud_detection`, `investment_risk_simulation`, or generic web/API/data platform families.
- Capabilities and capability model.
- Extracted metrics.
- Latency class.
- Deployment posture.
- Excluded patterns.

## Pattern Catalog

`app/services/pattern_catalog.py` maps profile families into:

- Workload patterns.
- Service patterns.
- Architecture components.
- Architecture flows.
- Security and observability controls.
- Pricing dimensions.
- Expected compiler views.
- Semantic views.
- POC and production scope text.

This is the main bridge from classification into architecture and diagram output.

## Healthcare Operations Scheduling

Healthcare OR scheduling was added as a specific family to avoid using unrelated industrial IoT/predictive failure pricing and language. Expected drivers include hospital/OR counts, active ORs in POC, surgery/event rates, refresh cadence, recommendation runs, approval workflows, EHR writeback attempts, occupancy readiness events, audit retention, and coordinator users.

Reserved-vocabulary lint is intended to catch healthcare outputs that accidentally include terms like depot, dispatch, confirmed incident, candidate anomaly, asset telemetry, inventory/depot, predictive failure, outage/restoration, unless those terms are explicitly present in input.

This lint should apply only to healthcare outputs.

## Telecom and HBase/HDFS Guarding

Telecom classification should require strong telecom/network/CDR/OSS/BSS/HBase/HDFS signals. Generic observability or Kubernetes telemetry should not become telecom merely because of weak words like telemetry.

For HBase/HDFS telecom migration, the interview should ask HBase access-pattern questions before choosing a target store. This protects against prematurely selecting DynamoDB, Keyspaces, OpenSearch, EMR/S3, or another target without row-key/read-write/scan/TTL/consistency data.

## Media Streaming Guarding

Media/video streaming should map to media delivery/QoE/CDN/logging patterns, not computer vision, unless the use case actually asks for vision/metadata extraction. Media pricing uses viewer-hours, bitrate, CDN egress, channel-hours, rights/ad/QoE/log drivers rather than device telemetry.

## Governance View Guarding

The semantic governance/security view should appear when the architecture has governance/approval/effectful-action flows that need it. It should not be added globally for every workload.

## Domain Drift Risks

Reviewer should test:

- Generic app use case: no healthcare language, no healthcare pricing drivers, no healthcare views.
- Telecom HBase/HDFS use case: telecom/big-data modernization classification, no healthcare wording, first question asks HBase access patterns.
- Media QoE/CDN use case: media/streaming wording, no healthcare wording, no healthcare pricing drivers.

Known limitation: domain packs are currently represented by deterministic functions and pattern catalog records, not by a single clean plugin/package interface. That is workable but less modular than a future domain-pack architecture.

